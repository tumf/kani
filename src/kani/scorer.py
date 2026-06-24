"""Kani scoring engine.

Distilled feature-based prompt classifier used by the router.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import pickle
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, cast

import numpy as np
from openai import OpenAI
from pydantic import BaseModel

log = logging.getLogger(__name__)

RUNTIME_FEATURE_CLASSIFIER_SUPPORTED = True
FEATURE_CLASSIFIER_FILENAME = "feature_classifier.pkl"
FEATURE_EMBEDDING_TIMEOUT_SECONDS = 5.0
EMBEDDING_TEXT_LIMIT = 4000

FEATURE_DIMENSIONS: tuple[str, ...] = (
    "tokenCount",
    "codePresence",
    "reasoningMarkers",
    "technicalTerms",
    "creativeMarkers",
    "simpleIndicators",
    "multiStepPatterns",
    "questionComplexity",
    "imperativeVerbs",
    "constraintCount",
    "outputFormat",
    "referenceComplexity",
    "negationComplexity",
    "domainSpecificity",
    "agenticTask",
)

SEMANTIC_DIMENSIONS: tuple[str, ...] = FEATURE_DIMENSIONS[1:]

_DIMENSION_VALUE_MAP = {"low": 0.0, "medium": 0.5, "high": 1.0}
_VALID_LABELS = frozenset(_DIMENSION_VALUE_MAP)


class Tier(str, Enum):
    SIMPLE = "SIMPLE"
    MEDIUM = "MEDIUM"
    COMPLEX = "COMPLEX"
    REASONING = "REASONING"


class ScoringConfig(BaseModel):
    """Configuration for the distilled feature scoring pipeline."""

    fallback_tier: Tier = Tier.MEDIUM
    fallback_confidence: float = 0.35


@dataclass
class DimensionResult:
    name: str
    raw_score: float
    weight: float
    weighted_score: float
    match_count: int = 0


@dataclass
class ClassificationResult:
    score: float
    tier: Tier
    confidence: float
    signals: dict[str, Any] = field(default_factory=dict)
    agentic_score: float = 0.0
    dimensions: list[DimensionResult] = field(default_factory=list)


@dataclass(frozen=True)
class FeatureClassifierStatus:
    """Static runtime support and asset status for doctor diagnostics."""

    supported: bool
    path: Path
    exists: bool
    loadable: bool
    message: str
    embedding_mode: str = "api"
    embedding_model: str = "text-embedding-3-small"
    embedding_timeout_seconds: float = FEATURE_EMBEDDING_TIMEOUT_SECONDS
    default_only: bool = False
    classifier_model: str = ""
    embedding_model_mismatch: bool = False
    embedding_model_mismatch: bool = False


@dataclass(frozen=True)
class RuntimeEmbeddingSettings:
    """Resolved runtime embedding backend settings."""

    mode: str
    model: str
    base_url: str | None
    api_key: str
    timeout_seconds: float


_DEFAULT_WEIGHTS: dict[str, float] = {
    "tokenCount": 0.15,
    "codePresence": 1.0,
    "reasoningMarkers": 1.4,
    "technicalTerms": 1.1,
    "creativeMarkers": 0.8,
    "simpleIndicators": 1.0,
    "multiStepPatterns": 1.3,
    "questionComplexity": 1.2,
    "imperativeVerbs": 0.9,
    "constraintCount": 1.2,
    "outputFormat": 0.9,
    "referenceComplexity": 1.1,
    "negationComplexity": 0.9,
    "domainSpecificity": 1.1,
    "agenticTask": 1.4,
}

_DEFAULT_THRESHOLDS: dict[str, float] = {
    "SIMPLE": 0.2,
    "MEDIUM": 0.45,
    "COMPLEX": 0.7,
}


def _token_count(text: str) -> int:
    return max(1, len(text.split()))


def _tier_from_score(score: float, thresholds: dict[str, float]) -> Tier:
    simple_max = float(thresholds.get("SIMPLE", 0.2))
    medium_max = float(thresholds.get("MEDIUM", 0.45))
    complex_max = float(thresholds.get("COMPLEX", 0.7))

    if score <= simple_max:
        return Tier.SIMPLE
    if score <= medium_max:
        return Tier.MEDIUM
    if score <= complex_max:
        return Tier.COMPLEX
    return Tier.REASONING


def _semantic_axis_score(
    semantic_labels: dict[str, str],
    names: list[str],
) -> float:
    values = [
        _DIMENSION_VALUE_MAP.get(semantic_labels.get(name, "low"), 0.0)
        for name in names
    ]
    return sum(values) / max(len(values), 1)


def _tier_from_axes(
    score: float,
    semantic_labels: dict[str, str],
    thresholds: dict[str, float],
) -> Tier:
    base_tier = _tier_from_score(score, thresholds)
    complexity_score = _semantic_axis_score(
        semantic_labels,
        [
            "codePresence",
            "multiStepPatterns",
            "constraintCount",
            "imperativeVerbs",
            "domainSpecificity",
            "technicalTerms",
        ],
    )
    reasoning_score = _semantic_axis_score(
        semantic_labels,
        [
            "reasoningMarkers",
            "questionComplexity",
            "referenceComplexity",
            "negationComplexity",
        ],
    )

    axis_tier = Tier.SIMPLE
    if reasoning_score >= 0.75 or semantic_labels.get("reasoningMarkers") == "high":
        axis_tier = Tier.REASONING
    elif (
        semantic_labels.get("agenticTask") == "high"
        and semantic_labels.get("imperativeVerbs") == "high"
    ):
        axis_tier = Tier.MEDIUM
    elif complexity_score >= 0.8:
        axis_tier = Tier.COMPLEX
    elif complexity_score >= 0.5:
        axis_tier = Tier.MEDIUM

    return max(base_tier, axis_tier, key=lambda tier: list(Tier).index(tier))


def _default_model_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "models"


def _feature_classifier_path(feature_model_dir: Any | None = None) -> Path:
    model_dir = (
        Path(feature_model_dir).expanduser()
        if feature_model_dir
        else _default_model_dir()
    )
    return model_dir / FEATURE_CLASSIFIER_FILENAME


def _as_float_mapping(value: object, *, name: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"feature classifier bundle field {name!r} must be a mapping")
    return {str(key): float(item) for key, item in value.items()}


def _resolve_runtime_embedding_settings() -> RuntimeEmbeddingSettings:
    """Resolve runtime embedding settings from config or environment variables."""
    try:
        from kani.config import load_config

        loaded = load_config()
        cfg = loaded.embedding
        if cfg is not None:
            if cfg.effective_mode == "disabled":
                return RuntimeEmbeddingSettings(
                    mode="disabled",
                    model=cfg.effective_model,
                    base_url=None,
                    api_key="",
                    timeout_seconds=cfg.timeout_seconds,
                )
            if cfg.effective_mode == "local":
                return RuntimeEmbeddingSettings(
                    mode="local",
                    model=cfg.local_model,
                    base_url=None,
                    api_key="",
                    timeout_seconds=cfg.timeout_seconds,
                )
            resolved = loaded.embedding_resolved()
            if resolved is not None:
                base_url, api_key = resolved
                return RuntimeEmbeddingSettings(
                    mode="api",
                    model=cfg.model,
                    base_url=base_url,
                    api_key=api_key,
                    timeout_seconds=cfg.timeout_seconds,
                )
    except Exception as exc:
        log.debug("Runtime embedding config resolution failed: %s", exc, exc_info=True)

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    base_url = None
    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        base_url = "https://openrouter.ai/api/v1"
    if not api_key:
        raise RuntimeError("embedding configuration is unavailable")
    embedding_model = (
        "openai/text-embedding-3-small" if base_url else "text-embedding-3-small"
    )
    return RuntimeEmbeddingSettings(
        mode="api",
        model=embedding_model,
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=FEATURE_EMBEDDING_TIMEOUT_SECONDS,
    )


def _resolve_runtime_embedding_client() -> tuple[OpenAI, str, float]:
    """Resolve API embedding client for compatibility with older tests."""
    settings = _resolve_runtime_embedding_settings()
    if settings.mode != "api":
        raise RuntimeError(f"embedding mode {settings.mode!r} does not use API client")
    return (
        OpenAI(api_key=settings.api_key or "dummy", base_url=settings.base_url),
        settings.model,
        settings.timeout_seconds,
    )


class LocalEmbeddingBackend:
    """Lazy local embedding backend using sentence-transformers when installed."""

    def __init__(self, model_name: str) -> None:
        if not model_name:
            raise RuntimeError("embedding.local_model is required for local mode")
        self.model_name = model_name
        self._model: Any | None = None

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from importlib import import_module

                module = import_module("sentence_transformers")
                sentence_transformer = getattr(module, "SentenceTransformer")
            except (ImportError, AttributeError) as exc:
                raise RuntimeError(
                    "local embedding requires sentence-transformers to be installed"
                ) from exc
            self._model = sentence_transformer(self.model_name)
        return self._model

    def embed(self, text: str) -> np.ndarray[Any, np.dtype[np.float32]]:
        model = self._load_model()
        encoded = model.encode([text], normalize_embeddings=False)
        embedding = np.asarray(encoded[0], dtype=np.float32)
        return cast(np.ndarray[Any, np.dtype[np.float32]], embedding)


class DistilledFeatureClassifier:
    """Runtime adapter for the trusted distilled feature classifier bundle."""

    def __init__(
        self,
        *,
        classifier: Any,
        label_encoders: dict[str, Any],
        embedding_model: str,
        embedding_dim: int,
        weights: dict[str, float],
        tier_thresholds: dict[str, float],
        feature_schema_version: str,
        model_path: Path,
        embedding_timeout_seconds: float = FEATURE_EMBEDDING_TIMEOUT_SECONDS,
        runtime_embedding_mode: str = "api",
        runtime_embedding_model: str = "",
        embedding_model_mismatch: bool = False,
    ) -> None:
        self.classifier = classifier
        self.label_encoders = label_encoders
        self.embedding_model = embedding_model
        self.embedding_dim = embedding_dim
        self.weights = weights
        self.tier_thresholds = tier_thresholds
        self.feature_schema_version = feature_schema_version
        self.model_path = model_path
        self.embedding_timeout_seconds = embedding_timeout_seconds
        self.runtime_embedding_mode = runtime_embedding_mode
        self.runtime_embedding_model = runtime_embedding_model or embedding_model
        self.embedding_model_mismatch = embedding_model_mismatch

    @classmethod
    def load(cls, feature_model_dir: Any | None = None) -> "DistilledFeatureClassifier":
        model_path = _feature_classifier_path(feature_model_dir)
        log.info("Loading distilled feature classifier model_path=%s", model_path)
        if not model_path.is_file():
            raise FileNotFoundError(f"feature classifier not found: {model_path}")

        with model_path.open("rb") as f:
            bundle = pickle.load(f)
        return cls.from_bundle(bundle, model_path=model_path)

    @classmethod
    def from_bundle(
        cls,
        bundle: object,
        *,
        model_path: Path,
    ) -> "DistilledFeatureClassifier":
        if not isinstance(bundle, dict):
            raise ValueError("feature classifier bundle must be a mapping")

        required = {
            "classifier",
            "label_encoders",
            "semantic_dimensions",
            "embedding_model",
            "embedding_dim",
            "weights",
            "tier_thresholds",
            "feature_schema_version",
        }
        missing = sorted(required - set(bundle))
        if missing:
            raise ValueError(
                f"feature classifier bundle missing fields: {', '.join(missing)}"
            )

        semantic_dimensions = tuple(str(dim) for dim in bundle["semantic_dimensions"])
        if semantic_dimensions != SEMANTIC_DIMENSIONS:
            raise ValueError(
                "feature classifier semantic_dimensions do not match runtime "
                f"SEMANTIC_DIMENSIONS: {semantic_dimensions!r}"
            )

        embedding_dim = int(bundle["embedding_dim"])
        if embedding_dim <= 0:
            raise ValueError("feature classifier embedding_dim must be positive")

        classifier = bundle["classifier"]
        if not callable(getattr(classifier, "predict", None)):
            raise ValueError(
                "feature classifier bundle classifier must expose predict()"
            )

        label_encoders_raw = bundle["label_encoders"]
        if not isinstance(label_encoders_raw, dict):
            raise ValueError("feature classifier label_encoders must be a mapping")
        label_encoders: dict[str, Any] = {}
        for dimension in SEMANTIC_DIMENSIONS:
            encoder = label_encoders_raw.get(dimension)
            if encoder is None or not callable(
                getattr(encoder, "inverse_transform", None)
            ):
                raise ValueError(f"missing label encoder for {dimension}")
            label_encoders[dimension] = encoder

        bundle_embedding_model = str(bundle["embedding_model"])
        try:
            settings = _resolve_runtime_embedding_settings()
        except Exception as exc:
            log.debug(
                "Runtime embedding settings unavailable during bundle load: %s", exc
            )
            settings = RuntimeEmbeddingSettings(
                mode="api",
                model=bundle_embedding_model,
                base_url=None,
                api_key="",
                timeout_seconds=FEATURE_EMBEDDING_TIMEOUT_SECONDS,
            )
        embedding_model_mismatch = (
            settings.mode != "disabled" and bundle_embedding_model != settings.model
        )
        if embedding_model_mismatch:
            log.warning(
                "Runtime embedding model mismatch bundle_model=%s runtime_mode=%s runtime_model=%s",
                bundle_embedding_model,
                settings.mode,
                settings.model,
            )

        return cls(
            classifier=classifier,
            label_encoders=label_encoders,
            embedding_model=bundle_embedding_model,
            embedding_dim=embedding_dim,
            weights=_as_float_mapping(bundle["weights"], name="weights"),
            tier_thresholds=_as_float_mapping(
                bundle["tier_thresholds"], name="tier_thresholds"
            ),
            feature_schema_version=str(bundle["feature_schema_version"]),
            model_path=model_path,
            embedding_timeout_seconds=settings.timeout_seconds,
            runtime_embedding_mode=settings.mode,
            runtime_embedding_model=settings.model,
            embedding_model_mismatch=embedding_model_mismatch,
        )

    def predict(self, text: str) -> tuple[dict[str, str], float]:
        embedding = self._embed_text(text)
        raw_prediction = self.classifier.predict(embedding.reshape(1, -1))
        prediction = np.asarray(raw_prediction)
        if prediction.shape != (1, len(SEMANTIC_DIMENSIONS)):
            raise ValueError(
                "feature classifier prediction shape mismatch: "
                f"expected (1, {len(SEMANTIC_DIMENSIONS)}), got {prediction.shape}"
            )

        semantic_labels: dict[str, str] = {}
        for index, dimension in enumerate(SEMANTIC_DIMENSIONS):
            encoder = self.label_encoders[dimension]
            decoded = encoder.inverse_transform([prediction[0, index]])
            label = str(decoded[0])
            if label not in _VALID_LABELS:
                raise ValueError(f"invalid decoded label for {dimension}: {label}")
            semantic_labels[dimension] = label

        confidence = (
            0.85 if any(value != "low" for value in semantic_labels.values()) else 0.65
        )
        return semantic_labels, confidence

    def _embed_text(self, text: str) -> np.ndarray[Any, np.dtype[np.float32]]:
        try:
            settings = _resolve_runtime_embedding_settings()
        except Exception as exc:
            log.debug("Runtime embedding settings unavailable before request: %s", exc)
            settings = RuntimeEmbeddingSettings(
                mode="api",
                model=self.embedding_model,
                base_url=None,
                api_key="",
                timeout_seconds=self.embedding_timeout_seconds,
            )
        if settings.mode == "disabled":
            raise RuntimeError("embedding mode is disabled")

        truncated_text = text[:EMBEDDING_TEXT_LIMIT]
        timeout_seconds = settings.timeout_seconds
        log.debug(
            "Requesting runtime embedding mode=%s model=%s text_length=%d timeout=%s",
            settings.mode,
            settings.model,
            len(truncated_text),
            timeout_seconds,
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            if settings.mode == "api":
                resolved = cast(Any, _resolve_runtime_embedding_client())
                if len(resolved) == 2:
                    client, _resolved_model = resolved
                    model = self.embedding_model
                    timeout_seconds = self.embedding_timeout_seconds
                else:
                    client, model, timeout_seconds = resolved
                future = executor.submit(
                    client.embeddings.create,
                    input=[truncated_text],
                    model=model,
                )
            elif settings.mode == "local":
                backend = LocalEmbeddingBackend(settings.model)
                future = executor.submit(backend.embed, truncated_text)
            else:
                raise RuntimeError(f"unsupported embedding mode: {settings.mode}")
            try:
                response = future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError as exc:
                future.cancel()
                raise TimeoutError("runtime embedding request timed out") from exc

        if settings.mode == "local":
            embedding = np.asarray(response, dtype=np.float32)
        else:
            data = getattr(response, "data", None)
            if not data:
                raise ValueError("embedding response did not include data")
            values = getattr(data[0], "embedding", None)
            if values is None:
                raise ValueError("embedding response item did not include embedding")
            embedding = np.asarray(values, dtype=np.float32)
        if embedding.shape != (self.embedding_dim,):
            raise ValueError(
                "embedding dimension mismatch: "
                f"expected {self.embedding_dim}, got {embedding.shape}"
            )
        return cast(np.ndarray[Any, np.dtype[np.float32]], embedding)


def inspect_feature_classifier_runtime_status(
    feature_model_dir: Any | None = None,
) -> FeatureClassifierStatus:
    """Return read-only feature classifier diagnostics without embedding calls."""
    model_path = _feature_classifier_path(feature_model_dir)
    try:
        settings = _resolve_runtime_embedding_settings()
    except Exception:
        settings = RuntimeEmbeddingSettings(
            mode="api",
            model="(environment fallback)",
            base_url=None,
            api_key="",
            timeout_seconds=FEATURE_EMBEDDING_TIMEOUT_SECONDS,
        )

    if not model_path.exists():
        return FeatureClassifierStatus(
            supported=RUNTIME_FEATURE_CLASSIFIER_SUPPORTED,
            path=model_path,
            exists=False,
            loadable=False,
            message="absent; routing will use default-only fallback until trained model is installed",
            embedding_mode=settings.mode,
            embedding_model=settings.model,
            embedding_timeout_seconds=settings.timeout_seconds,
            default_only=True,
        )

    try:
        classifier = DistilledFeatureClassifier.load(feature_model_dir)
    except Exception as exc:
        return FeatureClassifierStatus(
            supported=RUNTIME_FEATURE_CLASSIFIER_SUPPORTED,
            path=model_path,
            exists=True,
            loadable=False,
            message=f"unloadable ({type(exc).__name__}); routing will use default-only fallback",
            embedding_mode=settings.mode,
            embedding_model=settings.model,
            embedding_timeout_seconds=settings.timeout_seconds,
            default_only=True,
        )

    default_only = settings.mode == "disabled"
    message = "loadable by runtime; activation still requires embedding configuration at request time"
    if default_only:
        message = (
            "loadable but embedding is disabled; routing will use default-only fallback"
        )
    elif classifier.embedding_model_mismatch:
        message = (
            "loadable with embedding model mismatch; learned classifier may fall back"
        )

    return FeatureClassifierStatus(
        supported=RUNTIME_FEATURE_CLASSIFIER_SUPPORTED,
        path=model_path,
        exists=True,
        loadable=True,
        message=message,
        embedding_mode=settings.mode,
        embedding_model=settings.model,
        embedding_timeout_seconds=settings.timeout_seconds,
        default_only=default_only,
        classifier_model=classifier.embedding_model,
        embedding_model_mismatch=classifier.embedding_model_mismatch,
    )


class Scorer:
    """Distilled feature-based prompt classifier."""

    def __init__(
        self,
        config: ScoringConfig | None = None,
        *,
        feature_model_dir: Any | None = None,
        enable_routing_log: bool = True,
    ) -> None:
        self.config = config or ScoringConfig()
        self.feature_model_dir = (
            Path(feature_model_dir).expanduser() if feature_model_dir else None
        )
        self._enable_routing_log = enable_routing_log
        self._feature_classifier: DistilledFeatureClassifier | None = None
        self._feature_classifier_load_attempted = False
        self._feature_classifier_load_error: Exception | None = None

    @staticmethod
    def _build_dimensions(
        token_count: int,
        semantic_labels: dict[str, str],
        weights: dict[str, float],
    ) -> tuple[list[DimensionResult], float, float]:
        dimensions: list[DimensionResult] = []

        token_value = min(token_count / 2000.0, 1.0)
        token_weight = float(weights.get("tokenCount", 0.15))
        dimensions.append(
            DimensionResult(
                name="tokenCount",
                raw_score=token_value,
                weight=token_weight,
                weighted_score=token_value * token_weight,
            )
        )

        total_weighted = token_value * token_weight
        total_weight = token_weight
        agentic_score = 0.0

        for dim in SEMANTIC_DIMENSIONS:
            label = semantic_labels.get(dim, "low")
            value = _DIMENSION_VALUE_MAP.get(label, 0.0)
            weight = float(weights.get(dim, 1.0))
            weighted = value * weight
            dimensions.append(
                DimensionResult(
                    name=dim,
                    raw_score=value,
                    weight=weight,
                    weighted_score=weighted,
                )
            )
            if dim == "agenticTask":
                agentic_score = value
            total_weighted += weighted
            total_weight += weight

        score = total_weighted / max(total_weight, 1e-9)
        return dimensions, score, agentic_score

    def _load_feature_classifier(self) -> DistilledFeatureClassifier | None:
        if self._feature_classifier_load_attempted:
            return self._feature_classifier

        self._feature_classifier_load_attempted = True
        try:
            self._feature_classifier = DistilledFeatureClassifier.load(
                self.feature_model_dir
            )
            log.info(
                "Runtime distilled feature classifier loaded model_path=%s",
                self._feature_classifier.model_path,
            )
        except Exception as exc:
            self._feature_classifier_load_error = exc
            log.warning(
                "Runtime distilled feature classifier unavailable; using default fallback: %s",
                exc,
            )
            self._feature_classifier = None
        return self._feature_classifier

    def _classify_with_features(self, text: str) -> ClassificationResult:
        token_count = _token_count(text)
        classifier = self._load_feature_classifier()
        if classifier is None:
            if self._feature_classifier_load_error is not None:
                raise RuntimeError(
                    "distilled feature classifier unavailable"
                ) from self._feature_classifier_load_error
            raise RuntimeError("distilled feature classifier unavailable")

        semantic_labels, confidence = classifier.predict(text)
        dimensions, score, agentic_score = self._build_dimensions(
            token_count,
            semantic_labels,
            classifier.weights,
        )
        tier = _tier_from_axes(score, semantic_labels, classifier.tier_thresholds)

        signals: dict[str, Any] = {
            "method": {"raw": "distilled-features", "matches": 0},
            "tokenCount": token_count,
            "semanticLabels": semantic_labels,
            "featureVersion": classifier.feature_schema_version,
        }

        return ClassificationResult(
            score=score,
            tier=tier,
            confidence=confidence,
            signals=signals,
            agentic_score=agentic_score,
            dimensions=dimensions,
        )

    def _default_result(self) -> ClassificationResult:
        return ClassificationResult(
            score=0.0,
            tier=self.config.fallback_tier,
            confidence=self.config.fallback_confidence,
            signals={"method": {"raw": "default", "matches": 0}},
            agentic_score=0.0,
            dimensions=[],
        )

    def classify(self, text: str) -> ClassificationResult:
        log.debug("Scoring classification input text_length=%d", len(text))
        try:
            result = self._classify_with_features(text)
        except TimeoutError as exc:
            log.warning("Runtime embedding timed out, using default fallback: %s", exc)
            result = self._default_result()
        except RuntimeError as exc:
            if "embedding mode is disabled" in str(exc):
                log.info("Runtime embedding disabled, using default fallback")
            else:
                log.exception("Feature classification failed, using default fallback")
            result = self._default_result()
        except Exception:
            log.exception("Feature classification failed, using default fallback")
            result = self._default_result()

        if self._enable_routing_log:
            from kani.logger import RoutingLogger

            RoutingLogger.log(text, result)
        return result
