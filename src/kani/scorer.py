"""Kani scoring engine.

Distilled feature-based prompt classifier used by the router.
"""

from __future__ import annotations

import logging
import os
import pickle
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel

log = logging.getLogger(__name__)


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


def _build_embedding_client(model_name: str) -> tuple[Any, str]:
    from openai import OpenAI

    from kani.config import load_config

    try:
        loaded = load_config()
        cfg = loaded.embedding
    except Exception:
        loaded = None
        cfg = None

    if loaded and cfg:
        resolved = loaded.embedding_resolved()
        if resolved is not None:
            base_url, api_key = resolved
            resolved_model = cfg.model or model_name
            return OpenAI(
                api_key=api_key or "dummy",
                base_url=base_url,
            ), resolved_model

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    base_url = None
    resolved_model = model_name

    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        base_url = "https://openrouter.ai/api/v1"
        if not resolved_model.startswith("openai/"):
            resolved_model = f"openai/{resolved_model}"

    if not api_key:
        raise RuntimeError("No embedding config or OPENAI_API_KEY / OPENROUTER_API_KEY")

    return OpenAI(api_key=api_key, base_url=base_url), resolved_model


class DistilledFeatureClassifier:
    """Embedding-based multi-output semantic feature classifier."""

    _instance: DistilledFeatureClassifier | None = None
    _model_dir: Path | None = None

    def __init__(self, model_path: Path) -> None:
        with open(model_path, "rb") as f:
            data = pickle.load(f)

        self.classifier = data["classifier"]
        self.embedding_model: str = data.get(
            "embedding_model", "text-embedding-3-small"
        )
        self.semantic_dimensions: list[str] = list(
            data.get("semantic_dimensions", SEMANTIC_DIMENSIONS)
        )
        self.label_encoders: dict[str, Any] = data["label_encoders"]
        self.weights: dict[str, float] = dict(data.get("weights", {}))
        self.tier_thresholds: dict[str, float] = dict(
            data.get(
                "tier_thresholds",
                {"SIMPLE": 0.2, "MEDIUM": 0.6, "COMPLEX": 0.8},
            )
        )
        self._client: Any | None = None

    @classmethod
    def load(cls, model_dir: Path | None = None) -> DistilledFeatureClassifier | None:
        if cls._instance is not None and cls._model_dir == model_dir:
            return cls._instance
        if model_dir is None:
            model_dir = Path(__file__).resolve().parent.parent.parent / "models"
        pkl = model_dir / "feature_classifier.pkl"
        if not pkl.exists():
            return None
        try:
            cls._instance = cls(pkl)
            cls._model_dir = model_dir
            log.info("Loaded distilled feature classifier from %s", pkl)
            return cls._instance
        except Exception:
            log.exception("Failed to load distilled feature classifier")
            return None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        self._client, self.embedding_model = _build_embedding_client(
            self.embedding_model
        )
        return self._client

    def _embed(self, text: str) -> np.ndarray:
        client = self._get_client()
        resp = client.embeddings.create(input=[text[:4000]], model=self.embedding_model)
        return np.array([resp.data[0].embedding], dtype=np.float32)

    def predict(self, text: str) -> tuple[dict[str, str], float]:
        embedding = self._embed(text)
        predicted = self.classifier.predict(embedding)[0]
        probs = self.classifier.predict_proba(embedding)

        labels: dict[str, str] = {}
        confidences: list[float] = []

        for index, dim in enumerate(self.semantic_dimensions):
            encoder = self.label_encoders[dim]
            encoded_value = int(predicted[index])
            label = str(encoder.inverse_transform([encoded_value])[0]).lower()
            labels[dim] = label

            dim_proba = probs[index][0]
            confidences.append(float(np.max(dim_proba)))

        if not confidences:
            confidence = 0.0
        else:
            confidences.sort(reverse=True)
            top_k = 5
            confidence = float(np.mean(confidences[:top_k]))
        return labels, confidence


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
    if base_tier in {Tier.SIMPLE, Tier.MEDIUM}:
        return base_tier

    complex_score = _semantic_axis_score(
        semantic_labels,
        [
            "codePresence",
            "multiStepPatterns",
            "constraintCount",
            "imperativeVerbs",
            "agenticTask",
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
            "agenticTask",
        ],
    )

    if reasoning_score >= 0.5 and reasoning_score >= complex_score:
        return Tier.REASONING
    return Tier.COMPLEX


class Scorer:
    """Distilled feature-based prompt classifier."""

    def __init__(
        self,
        config: ScoringConfig | None = None,
        *,
        feature_model_dir: Path | None = None,
        enable_routing_log: bool = True,
    ) -> None:
        self.config = config or ScoringConfig()
        self._feature_model_dir = feature_model_dir
        self._feature_clf: DistilledFeatureClassifier | None = None
        self._feature_loaded = False
        self._enable_routing_log = enable_routing_log

    def _load_feature_model(self) -> DistilledFeatureClassifier | None:
        if not self._feature_loaded:
            self._feature_loaded = True
            self._feature_clf = DistilledFeatureClassifier.load(self._feature_model_dir)
        return self._feature_clf

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
            total_weighted += weighted
            total_weight += weight
            if dim == "agenticTask":
                agentic_score = value

        score = total_weighted / max(total_weight, 1e-9)
        return dimensions, score, agentic_score

    def _classify_with_features(
        self, text: str, feature_clf: DistilledFeatureClassifier
    ) -> ClassificationResult:
        token_count = _token_count(text)
        semantic_labels, confidence = feature_clf.predict(text)
        dimensions, score, agentic_score = self._build_dimensions(
            token_count,
            semantic_labels,
            feature_clf.weights,
        )
        tier = _tier_from_axes(score, semantic_labels, feature_clf.tier_thresholds)

        signals: dict[str, Any] = {
            "method": {"raw": "distilled-features", "matches": 0},
            "tokenCount": token_count,
            "semanticLabels": semantic_labels,
            "featureVersion": "v1",
        }

        result = ClassificationResult(
            score=score,
            tier=tier,
            confidence=confidence,
            signals=signals,
            agentic_score=agentic_score,
            dimensions=dimensions,
        )

        if self._enable_routing_log:
            from kani.logger import RoutingLogger

            RoutingLogger.log(text, result)

        return result

    def classify(self, text: str) -> ClassificationResult:
        log.debug("Scoring classification input text_length=%d", len(text))
        feature_clf = self._load_feature_model()
        if feature_clf is not None:
            try:
                return self._classify_with_features(text, feature_clf)
            except Exception:
                log.warning(
                    "Feature classifier predict failed, falling back", exc_info=True
                )

        result = ClassificationResult(
            score=0.0,
            tier=self.config.fallback_tier,
            confidence=self.config.fallback_confidence,
            signals={"method": {"raw": "default", "matches": 0}},
            agentic_score=0.0,
            dimensions=[],
        )
        if self._enable_routing_log:
            from kani.logger import RoutingLogger

            RoutingLogger.log(text, result)
        return result
