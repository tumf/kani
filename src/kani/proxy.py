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
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from kani.api_keys import has_keys, validate_key
from kani.compaction import (
    BackgroundCompactionWorker,
    CompactionResult,
    _merge_summaries,
    generate_summary,
    get_worker,
    set_worker,
    try_sync_compaction,
)
from kani.compaction_store import (
    enqueue_summary,
    get_inflight_summary,
    get_latest_ready_summary_for_session,
    get_ready_summary,
    get_snapshot,
    init_db,
    mark_stale_summaries,
    resolve_session_id,
    save_snapshot,
    snapshot_hash,
    upsert_session,
)
from kani.config import KaniConfig, load_config
from kani.dashboard import (
    dashboard_needs_stderr_backfill,
    get_dashboard_stats,
    ingest_execution_logs,
    ingest_jsonl_logs,
    ingest_stderr_proxy_logs,
    log_execution_event,
    recommended_dashboard_ingest_days,
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

    # Initialise compaction store and background worker
    assert _config is not None
    cc = _config.smart_proxy.context_compaction
    if cc.enabled:
        try:
            init_db()
            max_conc = cc.background_precompaction.max_concurrency
            set_worker(BackgroundCompactionWorker(max_concurrency=max_conc))
            logger.info("Smart-proxy context compaction enabled (worker started)")
        except Exception:
            logger.exception(
                "Failed to initialise compaction store — disabling compaction"
            )

    yield

    # Shutdown background worker
    worker = get_worker()
    if worker is not None:
        await worker.shutdown()
        set_worker(None)

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


# ── Compaction helpers ────────────────────────────────────────────────────────


def _compaction_headers(result: CompactionResult) -> dict[str, str]:
    """Build X-Kani-Compaction-* response headers from a CompactionResult."""
    h: dict[str, str] = {
        "X-Kani-Compaction": result.mode,
    }
    if result.session_id:
        h["X-Kani-Compaction-Session"] = result.session_mode
    if result.estimated_tokens_saved > 0:
        h["X-Kani-Compaction-Saved-Tokens"] = str(result.estimated_tokens_saved)
    return h


async def _resolve_compaction(
    messages: list[dict[str, Any]],
    request: Request,
    profile: str | None,
    request_id: str | None,
) -> CompactionResult:
    """Run compaction logic for a routed request.

    Returns a CompactionResult describing the outcome. On any error the result
    will have mode='failed' and the caller must use the original messages.
    """
    assert _config is not None
    cc = _config.smart_proxy.context_compaction
    if not cc.enabled:
        return CompactionResult(mode="off", messages=messages)

    sync_cfg = cc.sync_compaction
    bg_cfg = cc.background_precompaction

    # Resolve session
    explicit_header = request.headers.get(cc.session.header_name)
    try:
        session_id, session_mode = resolve_session_id(
            messages,
            explicit_header=explicit_header,
            model=str(request.headers.get("x-kani-model", "")),
        )
    except Exception as exc:
        logger.warning("COMPACTION session resolution failed: %s", exc)
        return CompactionResult(mode="failed", messages=messages, error=str(exc))

    # Estimate token usage
    from kani.compaction import _estimate_tokens

    prompt_tokens = _estimate_tokens(messages)
    threshold_tokens = int(cc.context_window_tokens * sync_cfg.threshold_percent / 100)
    bg_trigger_tokens = int(cc.context_window_tokens * bg_cfg.trigger_percent / 100)

    # Persist session state
    try:
        snap_hash_val = snapshot_hash(messages)
        upsert_session(
            session_id,
            profile=profile,
            request_id=request_id,
            snapshot_hash=snap_hash_val,
            prompt_tokens=prompt_tokens,
        )
        mark_stale_summaries(session_id, snap_hash_val)
    except Exception as exc:
        logger.warning("COMPACTION session persistence failed: %s", exc)
        snap_hash_val = snapshot_hash(messages)

    # Check for a ready cached summary (Phase B reuse)
    compacted_messages = messages
    mode = "skipped"
    estimated_saved = 0

    if sync_cfg.enabled:
        try:
            ready = get_ready_summary(session_id, snap_hash_val)
        except Exception as exc:
            logger.warning("COMPACTION cache lookup failed: %s", exc)
            ready = None

        if ready and ready.get("summary_text"):
            # Reuse cached summary (Phase B hit)
            compacted, saved = try_sync_compaction(
                messages,
                ready["summary_text"],
                sync_cfg.protect_first_n,
                sync_cfg.protect_last_n,
                prompt_tokens,
            )
            if compacted is not None:
                compacted_messages = compacted
                mode = "cached"
                estimated_saved = saved
                logger.info(
                    "COMPACTION mode=cached session=%s snap=%s saved=%d request_id=%s",
                    session_id,
                    snap_hash_val[:8],
                    saved,
                    request_id,
                )
            else:
                mode = "skipped"
        elif prompt_tokens >= threshold_tokens:
            # Phase A: generate summary inline
            summary_model = sync_cfg.summary_model
            base_url_for_summary = ""
            api_key_for_summary = ""

            if summary_model:
                # find a provider that can serve this model
                dp = _config.providers.get(_config.default_provider)
                if dp:
                    base_url_for_summary = dp.base_url.rstrip("/")
                    api_key_for_summary = dp.api_key or ""
            else:
                # use compress profile via default provider
                compress_profile = _config.profiles.get("compress")
                if compress_profile:
                    tier_cfg = compress_profile.tiers.get(
                        "SIMPLE", next(iter(compress_profile.tiers.values()), None)
                    )
                    if tier_cfg:
                        summary_model = tier_cfg.primary_model_id()
                dp = _config.providers.get(_config.default_provider)
                if dp:
                    base_url_for_summary = dp.base_url.rstrip("/")
                    api_key_for_summary = dp.api_key or ""

            if summary_model and base_url_for_summary:
                try:
                    # Look up prior summary for incremental path
                    prior_summary_row = get_latest_ready_summary_for_session(session_id)
                    prior_text: str | None = None
                    prior_covered: int = 0
                    new_covered: int = 0

                    if prior_summary_row and prior_summary_row.get("summary_text"):
                        # Validate prior summary still applies to current messages
                        prior_snap = get_snapshot(prior_summary_row["snapshot_hash"])
                        if prior_snap:
                            import json as _json

                            prior_msgs = _json.loads(prior_snap["messages_json"])
                            prior_covered_raw = (
                                prior_summary_row.get("covered_message_count", 0) or 0
                            )
                            n = len(messages)
                            has_system = (
                                messages[0].get("role") == "system"
                                if messages
                                else False
                            )
                            head_end = sync_cfg.protect_first_n + (
                                1 if has_system else 0
                            )
                            covered_end = head_end + prior_covered_raw
                            # Validate: covered prefix of prior matches current messages
                            if (
                                covered_end <= len(prior_msgs)
                                and covered_end <= n
                                and prior_msgs[:covered_end] == messages[:covered_end]
                            ):
                                prior_text = prior_summary_row["summary_text"]
                                prior_covered = prior_covered_raw

                    if prior_text is not None:
                        # Incremental path: summarize only the delta
                        n = len(messages)
                        has_system = (
                            messages[0].get("role") == "system" if messages else False
                        )
                        head_end = sync_cfg.protect_first_n + (1 if has_system else 0)
                        tail_start = n - sync_cfg.protect_last_n
                        delta_messages = messages[head_end + prior_covered : tail_start]

                        if not delta_messages:
                            # No new messages since last summary — reuse prior
                            delta_summary = ""
                            final_summary = prior_text
                            new_covered = prior_covered
                        else:
                            delta_summary = await generate_summary(
                                delta_messages + messages[tail_start:],
                                summary_model=summary_model,
                                base_url=base_url_for_summary,
                                api_key=api_key_for_summary,
                                protect_first_n=0,
                                protect_last_n=sync_cfg.protect_last_n,
                            )
                            final_summary = await _merge_summaries(
                                prior_text,
                                delta_summary,
                                sync_cfg.merge_threshold,
                                summary_model=summary_model,
                                base_url=base_url_for_summary,
                                api_key=api_key_for_summary,
                            )
                            new_covered = max(0, tail_start - head_end)

                        compacted, saved = try_sync_compaction(
                            messages,
                            final_summary,
                            sync_cfg.protect_first_n,
                            sync_cfg.protect_last_n,
                            prompt_tokens,
                        )
                        summary_text = final_summary
                    else:
                        # Full single-pass (no prior summary)
                        summary_text = await generate_summary(
                            messages,
                            summary_model=summary_model,
                            base_url=base_url_for_summary,
                            api_key=api_key_for_summary,
                            protect_first_n=sync_cfg.protect_first_n,
                            protect_last_n=sync_cfg.protect_last_n,
                        )
                        n = len(messages)
                        has_system = (
                            messages[0].get("role") == "system" if messages else False
                        )
                        head_end = sync_cfg.protect_first_n + (1 if has_system else 0)
                        tail_start = n - sync_cfg.protect_last_n
                        new_covered = max(0, tail_start - head_end)
                        compacted, saved = try_sync_compaction(
                            messages,
                            summary_text,
                            sync_cfg.protect_first_n,
                            sync_cfg.protect_last_n,
                            prompt_tokens,
                        )

                    if compacted is not None:
                        # Persist the generated summary for future reuse
                        try:
                            snap_h = save_snapshot(session_id, messages, prompt_tokens)
                            from kani.compaction_store import update_summary

                            new_id = enqueue_summary(session_id, snap_h, new_covered)
                            update_summary(
                                new_id,
                                status="ready",
                                summary_text=summary_text,
                                estimated_tokens_saved=saved,
                                covered_message_count=new_covered,
                            )
                        except Exception as exc:
                            logger.warning(
                                "COMPACTION persist inline summary failed: %s", exc
                            )

                        compacted_messages = compacted
                        mode = "inline"
                        estimated_saved = saved
                        logger.info(
                            "COMPACTION mode=inline session=%s snap=%s saved=%d request_id=%s",
                            session_id,
                            snap_hash_val[:8],
                            saved,
                            request_id,
                        )
                    else:
                        mode = "skipped"
                        logger.info(
                            "COMPACTION mode=skipped (unsafe structure) session=%s request_id=%s",
                            session_id,
                            request_id,
                        )
                except Exception as exc:
                    mode = "failed"
                    logger.warning(
                        "COMPACTION inline failed session=%s error=%s request_id=%s",
                        session_id,
                        exc,
                        request_id,
                    )
            else:
                mode = "skipped"

    # Phase B: schedule background precompaction if threshold crossed
    if bg_cfg.enabled and prompt_tokens >= bg_trigger_tokens:
        try:
            if not get_inflight_summary(session_id, snap_hash_val):
                snap_h = save_snapshot(session_id, messages, prompt_tokens)
                # Look up prior summary for incremental background compaction
                bg_prior_row = get_latest_ready_summary_for_session(session_id)
                bg_prior_text: str | None = None
                bg_prior_covered: int = 0
                if bg_prior_row and bg_prior_row.get("summary_text"):
                    bg_prior_snap = get_snapshot(bg_prior_row["snapshot_hash"])
                    if bg_prior_snap:
                        import json as _json2

                        bg_prior_msgs = _json2.loads(bg_prior_snap["messages_json"])
                        bg_covered_raw = (
                            bg_prior_row.get("covered_message_count", 0) or 0
                        )
                        n = len(messages)
                        has_system = (
                            messages[0].get("role") == "system" if messages else False
                        )
                        head_end = sync_cfg.protect_first_n + (1 if has_system else 0)
                        covered_end = head_end + bg_covered_raw
                        if (
                            covered_end <= len(bg_prior_msgs)
                            and covered_end <= n
                            and bg_prior_msgs[:covered_end] == messages[:covered_end]
                        ):
                            bg_prior_text = bg_prior_row["summary_text"]
                            bg_prior_covered = bg_covered_raw

                summary_id = enqueue_summary(session_id, snap_h)
                worker = get_worker()
                if worker is not None:
                    dp = _config.providers.get(_config.default_provider)
                    bg_model = sync_cfg.summary_model
                    if not bg_model:
                        compress_profile = _config.profiles.get("compress")
                        if compress_profile:
                            tier_cfg = compress_profile.tiers.get(
                                "SIMPLE",
                                next(iter(compress_profile.tiers.values()), None),
                            )
                            if tier_cfg:
                                bg_model = tier_cfg.primary_model_id()
                    if bg_model and dp:
                        worker.schedule(
                            summary_id,
                            session_id,
                            snap_h,
                            messages,
                            summary_model=bg_model,
                            base_url=dp.base_url.rstrip("/"),
                            api_key=dp.api_key or "",
                            protect_first_n=sync_cfg.protect_first_n,
                            protect_last_n=sync_cfg.protect_last_n,
                            original_tokens=prompt_tokens,
                            merge_threshold=sync_cfg.merge_threshold,
                            prior_summary=bg_prior_text,
                            prior_covered_count=bg_prior_covered,
                        )
                        logger.info(
                            "COMPACTION_BG queued session=%s snap=%s request_id=%s incremental=%s",
                            session_id,
                            snap_h[:8],
                            request_id,
                            bg_prior_text is not None,
                        )
        except Exception as exc:
            logger.warning("COMPACTION_BG scheduling failed: %s", exc)

    return CompactionResult(
        applied=mode in ("inline", "cached"),
        messages=compacted_messages,
        mode=mode,
        session_id=session_id,
        session_mode=session_mode,
        estimated_tokens_saved=estimated_saved,
    )


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

        # Smart-proxy context compaction (Phase A + B)
        compaction_result = await _resolve_compaction(
            messages, request, profile_name, request_id
        )
        if compaction_result.applied:
            body = dict(body)
            body["messages"] = compaction_result.messages

        # Replace the model field with the actual model name
        body["model"] = decision.model
        response = await _try_with_fallbacks(
            body, decision, profile_name, request_id=request_id
        )

        # Attach compaction headers
        compaction_hdrs = _compaction_headers(compaction_result)
        if compaction_hdrs:
            for k, v in compaction_hdrs.items():
                response.headers[k] = v

        return response

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
async def dashboard(profiles: list[str] | None = Query(default=None)):
    """HTML dashboard showing routing analytics."""
    ingest_days = recommended_dashboard_ingest_days(full_days=30, incremental_days=2)
    ingest_jsonl_logs(days=ingest_days)
    execution_ingested = ingest_execution_logs(days=ingest_days)
    if execution_ingested == 0 and dashboard_needs_stderr_backfill():
        ingest_stderr_proxy_logs()

    stats = get_dashboard_stats(hours=24, profiles=profiles)
    html = render_dashboard_html(stats)
    return HTMLResponse(content=html)


@app.get("/dashboard/stats")
async def dashboard_stats(
    hours: int = 24, profiles: list[str] | None = Query(default=None)
):
    """JSON endpoint for dashboard stats."""
    ingest_days = max(
        max(1, hours // 24),
        recommended_dashboard_ingest_days(full_days=30, incremental_days=2),
    )
    ingest_jsonl_logs(days=ingest_days)
    execution_ingested = ingest_execution_logs(days=ingest_days)
    if execution_ingested == 0 and dashboard_needs_stderr_backfill():
        ingest_stderr_proxy_logs()
    return get_dashboard_stats(hours=hours, profiles=profiles)
