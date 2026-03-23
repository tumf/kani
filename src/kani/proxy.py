"""OpenAI-compatible proxy server for kani LLM smart router."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from kani.api_keys import has_keys, validate_key
from kani.config import KaniConfig, load_config
from kani.dashboard import (
    get_dashboard_stats,
    ingest_execution_logs,
    ingest_jsonl_logs,
    ingest_stderr_proxy_logs,
    log_execution_event,
    render_dashboard_html,
)
from kani.router import Router, RoutingDecision

logger = logging.getLogger("kani.proxy")
logger.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
logger.addHandler(_handler)

# ── Global state ──────────────────────────────────────────────────────────────

_config: KaniConfig | None = None
_router: Router | None = None
_http: httpx.AsyncClient | None = None


def _resolve_config_path(explicit: str | None = None) -> str | None:
    """Return the config file path from explicit arg, env-var, or None (auto-discover)."""
    if explicit:
        return explicit
    return os.environ.get("KANI_CONFIG")


def configure(config_path: str | None = None) -> None:
    """Load config and build the router (called before app startup)."""
    global _config, _router
    path = _resolve_config_path(config_path)
    _config = load_config(path)
    _router = Router(_config)
    logger.info("Loaded config from %s", path)


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http
    if _config is None:
        configure()
    _http = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    logger.info("HTTP connection pool started")
    yield
    await _http.aclose()
    logger.info("HTTP connection pool closed")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="kani", version="0.1.0", lifespan=lifespan)


# ── Auth middleware ─────────────────────────────────────────────────────────

_AUTH_EXEMPT = {"/health", "/docs", "/openapi.json"}


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """Require a valid Bearer token when API keys are configured."""

    async def dispatch(self, request: Request, call_next):
        # Skip auth if no keys configured (backward-compat)
        if not has_keys():
            return await call_next(request)

        # Exempt non-API paths
        if request.url.path in _AUTH_EXEMPT:
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            if validate_key(token):
                return await call_next(request)

        return _openai_error(401, "Invalid or missing API key", "authentication_error")


app.add_middleware(ApiKeyAuthMiddleware)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _openai_error(
    status: int, message: str, err_type: str = "invalid_request_error"
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "message": message,
                "type": err_type,
                "param": None,
                "code": None,
            }
        },
    )


def _kani_headers(
    decision: RoutingDecision,
    *,
    actual_model: str | None = None,
    actual_provider: str | None = None,
) -> dict[str, str]:
    return {
        "X-Kani-Tier": str(decision.tier),
        "X-Kani-Model": actual_model or decision.model,
        "X-Kani-Provider": actual_provider or decision.provider,
        "X-Kani-Score": f"{decision.score:.4f}",
        "X-Kani-Signals": json.dumps(decision.signals) if decision.signals else "{}",
    }


def _get_default_provider_info() -> tuple[str, str, str]:
    """Return (base_url, api_key, model) for the default provider."""
    assert _config is not None
    dp_name = _config.default_provider
    dp = _config.providers[dp_name]
    base_url = dp.base_url.rstrip("/")
    api_key = dp.api_key or ""
    # pick first model from provider as default
    model = dp.models[0] if dp.models else "gpt-4o-mini"
    return base_url, api_key, model


def _log_usage(
    model: str,
    provider: str | None,
    usage: dict[str, Any] | None,
    profile: str | None = None,
    elapsed_ms: float | None = None,
    *,
    decision: RoutingDecision | None = None,
    request_id: str | None = None,
) -> None:
    """Log token usage from an upstream response."""
    if not usage:
        return
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    total = usage.get("total_tokens", 0) or (prompt + completion)
    parts = []
    if request_id:
        parts.append(f"request_id={request_id}")
    parts.extend(
        [
            f"model={model}",
            f"provider={provider or 'unknown'}",
            f"prompt={prompt}",
            f"completion={completion}",
            f"total={total}",
        ]
    )
    if profile:
        parts.append(f"profile={profile}")
    if elapsed_ms is not None:
        parts.append(f"elapsed_ms={elapsed_ms:.0f}")
    logger.info("USAGE %s", " ".join(parts))

    log_execution_event(
        request_id=request_id,
        tier=decision.tier if decision else None,
        score=decision.score if decision else None,
        confidence=decision.confidence if decision else None,
        agentic_score=decision.agentic_score if decision else None,
        model=model,
        provider=provider,
        profile=profile,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        elapsed_ms=elapsed_ms,
    )


async def _proxy_upstream(
    base_url: str,
    api_key: str,
    body: dict[str, Any],
    decision: RoutingDecision | None,
    profile: str | None = None,
    *,
    actual_provider: str | None = None,
    request_id: str | None = None,
) -> StreamingResponse | JSONResponse:
    """Forward a chat-completion request to the upstream provider."""
    assert _http is not None
    # Avoid doubling /v1 if base_url already ends with it
    if base_url.endswith("/v1"):
        url = f"{base_url}/chat/completions"
    else:
        url = f"{base_url}/v1/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    is_streaming = body.get("stream", False)
    model_name = body.get("model", "unknown")
    extra_headers = (
        _kani_headers(
            decision,
            actual_model=model_name,
            actual_provider=actual_provider,
        )
        if decision
        else {}
    )
    t0 = time.monotonic()

    try:
        if is_streaming:
            # Inject stream_options to request usage in final chunk
            stream_opts = body.get("stream_options") or {}
            stream_opts["include_usage"] = True
            body["stream_options"] = stream_opts

            req = _http.build_request("POST", url, json=body, headers=headers)
            upstream = await _http.send(req, stream=True)

            if upstream.status_code != 200:
                raw = await upstream.aread()
                await upstream.aclose()
                return _openai_error(
                    upstream.status_code,
                    f"Upstream error: {raw.decode(errors='replace')[:500]}",
                    "upstream_error",
                )

            async def _stream():
                try:
                    async for line in upstream.aiter_lines():
                        yield f"{line}\n"
                        # Parse usage from the final data chunk
                        if line.startswith("data: ") and line != "data: [DONE]":
                            try:
                                chunk = json.loads(line[6:])
                                usage = chunk.get("usage")
                                if usage:
                                    elapsed = (time.monotonic() - t0) * 1000
                                    _log_usage(
                                        model_name,
                                        actual_provider,
                                        usage,
                                        profile,
                                        elapsed,
                                        decision=decision,
                                        request_id=request_id,
                                    )
                            except (json.JSONDecodeError, TypeError):
                                pass
                finally:
                    await upstream.aclose()

            resp_headers = dict(extra_headers)
            resp_headers["Content-Type"] = "text/event-stream"
            resp_headers["Cache-Control"] = "no-cache"
            resp_headers["Connection"] = "keep-alive"
            return StreamingResponse(
                _stream(),
                media_type="text/event-stream",
                headers=resp_headers,
            )
        else:
            resp = await _http.post(url, json=body, headers=headers)
            elapsed = (time.monotonic() - t0) * 1000
            if resp.status_code != 200:
                return _openai_error(
                    resp.status_code,
                    f"Upstream error: {resp.text[:500]}",
                    "upstream_error",
                )
            resp_data = resp.json()
            _log_usage(
                model_name,
                actual_provider,
                resp_data.get("usage"),
                profile,
                elapsed,
                decision=decision,
                request_id=request_id,
            )
            return JSONResponse(
                content=resp_data,
                headers=extra_headers,
            )

    except httpx.TimeoutException:
        return _openai_error(504, "Upstream provider timed out", "timeout_error")
    except httpx.HTTPError as exc:
        return _openai_error(
            502, f"Upstream connection error: {exc!r}", "upstream_error"
        )


# ── Fallback helpers ──────────────────────────────────────────────────────────


def _is_retryable_error(result: StreamingResponse | JSONResponse) -> bool:
    """Check if a response is a retryable error (5xx, timeout, connection error)."""
    if isinstance(result, JSONResponse):
        return result.status_code >= 500
    return False


async def _try_with_fallbacks(
    body: dict[str, Any],
    decision: RoutingDecision,
    profile: str | None = None,
    *,
    request_id: str | None = None,
) -> StreamingResponse | JSONResponse:
    """Try primary, then fallbacks on failure."""
    # Try primary
    result = await _proxy_upstream(
        decision.base_url.rstrip("/"),
        decision.api_key or "",
        body,
        decision,
        profile=profile,
        actual_provider=decision.provider,
        request_id=request_id,
    )

    if not _is_retryable_error(result):
        return result

    # Try fallbacks
    for i, fb in enumerate(decision.fallbacks):
        logger.warning(
            "FALLBACK [%d/%d] model=%s provider=%s (primary=%s failed)",
            i + 1,
            len(decision.fallbacks),
            fb.model,
            fb.provider,
            decision.model,
        )
        fb_body = dict(body)
        fb_body["model"] = fb.model
        result = await _proxy_upstream(
            fb.base_url.rstrip("/"),
            fb.api_key or "",
            fb_body,
            decision,
            profile=profile,
            actual_provider=fb.provider,
            request_id=request_id,
        )
        if not _is_retryable_error(result):
            return result

    # All failed, return last error
    return result


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Main proxy endpoint — OpenAI-compatible chat completions."""
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return _openai_error(400, "Invalid JSON body")

    model_field: str = body.get("model", "")
    messages = body.get("messages", [])

    if model_field.startswith("kani/"):
        # ── Routed request ────────────────────────────────────────────────
        profile_name = model_field.split("/", 1)[1]  # e.g. "auto", "eco"
        request_id = uuid.uuid4().hex[:12]
        assert _router is not None
        try:
            decision: RoutingDecision = _router.route(messages, profile=profile_name)
        except Exception as exc:
            logger.exception("Router error")
            return _openai_error(500, f"Routing failed: {exc}", "router_error")

        logger.info(
            "ROUTE request_id=%s model=%s provider=%s tier=%s score=%.4f confidence=%.4f agentic=%.4f profile=%s",
            request_id,
            decision.model,
            decision.provider,
            decision.tier,
            decision.score,
            decision.confidence,
            decision.agentic_score,
            profile_name,
        )

        # Replace the model field with the actual model name
        body["model"] = decision.model
        return await _try_with_fallbacks(
            body, decision, profile_name, request_id=request_id
        )

    else:
        # ── Pass-through to default provider ──────────────────────────────
        assert _config is not None
        base_url, api_key, _ = _get_default_provider_info()
        logger.info(
            "PASSTHROUGH model=%s provider=%s", model_field, _config.default_provider
        )
        return await _proxy_upstream(
            base_url,
            api_key,
            body,
            decision=None,
            profile=None,
            actual_provider=_config.default_provider,
        )


@app.get("/v1/models")
async def list_models():
    """Return available kani/* virtual models plus underlying models."""
    assert _config is not None
    ts = int(time.time())
    data: list[dict[str, Any]] = []

    # Virtual kani models (one per profile)
    for profile_name in _config.profiles:
        data.append(
            {
                "id": f"kani/{profile_name}",
                "object": "model",
                "created": ts,
                "owned_by": "kani",
            }
        )

    # Collect underlying models from all profiles
    seen_models: set[str] = set()
    for profile in _config.profiles.values():
        for tier_cfg in profile.tiers.values():
            all_model_ids = [
                tier_cfg.primary_model_id(),
                *tier_cfg.fallback_model_ids(),
            ]
            for m in all_model_ids:
                if m not in seen_models:
                    seen_models.add(m)
                    data.append(
                        {
                            "id": m,
                            "object": "model",
                            "created": ts,
                            "owned_by": "provider",
                        }
                    )

    return {"object": "list", "data": data}


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.post("/v1/route")
async def route_debug(request: Request):
    """Debug endpoint: return routing decision without proxying."""
    try:
        body = await request.json()
    except Exception:
        return _openai_error(400, "Invalid JSON body")

    messages = body.get("messages", [])
    profile = body.get("profile", None)

    assert _router is not None
    try:
        decision = _router.route(messages, profile=profile)
    except Exception as exc:
        logger.exception("Router error in debug endpoint")
        return _openai_error(500, f"Routing failed: {exc}", "router_error")

    return decision.model_dump()


# ── Dashboard endpoints ────────────────────────────────────────────────────


@app.get("/dashboard")
async def dashboard():
    """HTML dashboard showing routing analytics."""
    ingest_jsonl_logs(days=30)
    execution_ingested = ingest_execution_logs(days=30)
    if execution_ingested == 0:
        ingest_stderr_proxy_logs()

    stats = get_dashboard_stats(hours=24)
    html = render_dashboard_html(stats)
    return HTMLResponse(content=html)


@app.get("/dashboard/stats")
async def dashboard_stats(hours: int = 24):
    """JSON endpoint for dashboard stats."""
    ingest_jsonl_logs(days=max(1, hours // 24))
    execution_ingested = ingest_execution_logs(days=30)
    if execution_ingested == 0:
        ingest_stderr_proxy_logs()
    return get_dashboard_stats(hours=hours)
