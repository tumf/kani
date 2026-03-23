"""Kani scoring engine.

Model-first prompt classifier used by the router.

The old keyword-heavy rules engine has been removed in favor of:
1. a trained embedding classifier when available
2. an LLM classifier as the uncertainty fallback
3. a conservative default when neither model can decide
"""

from __future__ import annotations

import logging
import os
import pickle
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

log = logging.getLogger(__name__)


def _build_embedding_client(model_name: str) -> tuple[Any, str]:
    """Create an embedding client using OpenAI or OpenRouter env vars."""
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    base_url = None
    resolved_model = model_name

    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        base_url = "https://openrouter.ai/api/v1"
        if not resolved_model.startswith("openai/"):
            resolved_model = f"openai/{resolved_model}"

    if not api_key:
        raise RuntimeError("No OPENAI_API_KEY or OPENROUTER_API_KEY for embeddings")

    return OpenAI(api_key=api_key, base_url=base_url), resolved_model


# ---------------------------------------------------------------------------
# Enums / config
# ---------------------------------------------------------------------------


class Tier(str, Enum):
    SIMPLE = "SIMPLE"
    MEDIUM = "MEDIUM"
    COMPLEX = "COMPLEX"
    REASONING = "REASONING"


class ScoringConfig(BaseModel):
    """Configuration for the model-first scoring pipeline."""

    min_confidence: float = 0.7
    fallback_tier: Tier = Tier.MEDIUM
    fallback_confidence: float = 0.35


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class DimensionResult:
    """Retained for API compatibility.

    The keyword-based dimension scorer has been removed, so callers should expect
    this list to usually be empty.
    """

    name: str
    raw_score: float
    weight: float
    weighted_score: float
    match_count: int = 0


@dataclass
class ClassificationResult:
    """Full classification output."""

    score: float
    tier: Tier
    confidence: float
    signals: dict[str, Any] = field(default_factory=dict)
    agentic_score: float = 0.0
    dimensions: list[DimensionResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Embedding classifier
# ---------------------------------------------------------------------------


class EmbeddingClassifier:
    """Embedding-based tier classifier using a pre-trained sklearn model."""

    _instance: EmbeddingClassifier | None = None
    _model_dir: Path | None = None

    def __init__(self, model_path: Path) -> None:
        with open(model_path, "rb") as f:
            data = pickle.load(f)
        self.classifier = data["classifier"]
        self.label_encoder = data["label_encoder"]
        self.embedding_model: str = data.get(
            "embedding_model", "text-embedding-3-small"
        )
        self._client: Any | None = None

    @classmethod
    def load(cls, model_dir: Path | None = None) -> EmbeddingClassifier | None:
        """Load the classifier singleton. Returns None if model file not found."""
        if cls._instance is not None and cls._model_dir == model_dir:
            return cls._instance
        if model_dir is None:
            model_dir = Path(__file__).resolve().parent.parent.parent / "models"
        pkl = model_dir / "tier_classifier.pkl"
        if not pkl.exists():
            return None
        try:
            cls._instance = cls(pkl)
            cls._model_dir = model_dir
            log.info("Loaded embedding classifier from %s", pkl)
            return cls._instance
        except Exception as exc:
            log.warning("Failed to load embedding classifier: %s", exc)
            return None

    def _get_client(self) -> Any:
        """Lazy-init OpenAI client for embedding inference."""
        if self._client is not None:
            return self._client

        self._client, self.embedding_model = _build_embedding_client(
            self.embedding_model
        )
        return self._client

    def predict(self, text: str) -> tuple[Tier, float]:
        """Predict tier and confidence for a prompt."""
        import numpy as np

        client = self._get_client()
        resp = client.embeddings.create(input=[text], model=self.embedding_model)
        embedding = np.array([resp.data[0].embedding], dtype=np.float32)
        proba = self.classifier.predict_proba(embedding)[0]
        pred_idx = int(np.argmax(proba))
        tier_name = self.label_encoder.inverse_transform([pred_idx])[0]
        confidence = float(proba[pred_idx])
        return Tier(tier_name), confidence


class AgenticEmbeddingClassifier:
    """Embedding-based AGENTIC/NON_AGENTIC classifier."""

    _instance: AgenticEmbeddingClassifier | None = None
    _model_dir: Path | None = None

    def __init__(self, model_path: Path) -> None:
        with open(model_path, "rb") as f:
            data = pickle.load(f)
        if data.get("label_type") not in {None, "agentic"}:
            raise ValueError("Model bundle is not an agentic classifier")
        self.classifier = data["classifier"]
        self.label_encoder = data["label_encoder"]
        self.embedding_model: str = data.get(
            "embedding_model", "text-embedding-3-small"
        )
        self._client: Any | None = None

    @classmethod
    def load(cls, model_dir: Path | None = None) -> AgenticEmbeddingClassifier | None:
        """Load the classifier singleton. Returns None if model file not found."""
        if cls._instance is not None and cls._model_dir == model_dir:
            return cls._instance
        if model_dir is None:
            model_dir = Path(__file__).resolve().parent.parent.parent / "models"
        pkl = model_dir / "agentic_classifier.pkl"
        if not pkl.exists():
            return None
        try:
            cls._instance = cls(pkl)
            cls._model_dir = model_dir
            log.info("Loaded agentic embedding classifier from %s", pkl)
            return cls._instance
        except Exception as exc:
            log.warning("Failed to load agentic embedding classifier: %s", exc)
            return None

    def _get_client(self) -> Any:
        """Lazy-init OpenAI client for embedding inference."""
        if self._client is not None:
            return self._client

        self._client, self.embedding_model = _build_embedding_client(
            self.embedding_model
        )
        return self._client

    def predict(self, text: str) -> tuple[float, str, float]:
        """Return (agentic_score, label, confidence) for a prompt."""
        import numpy as np

        client = self._get_client()
        resp = client.embeddings.create(input=[text], model=self.embedding_model)
        embedding = np.array([resp.data[0].embedding], dtype=np.float32)
        proba = self.classifier.predict_proba(embedding)[0]
        pred_idx = int(np.argmax(proba))
        label = str(self.label_encoder.inverse_transform([pred_idx])[0])
        confidence = float(proba[pred_idx])

        classes = [str(name) for name in self.label_encoder.classes_]
        try:
            agentic_idx = classes.index("AGENTIC")
        except ValueError as exc:
            raise ValueError("Agentic classifier is missing AGENTIC label") from exc

        agentic_score = float(proba[agentic_idx])
        return agentic_score, label, confidence


# ---------------------------------------------------------------------------
# LLM classifier
# ---------------------------------------------------------------------------


class LLMClassifier:
    """LLM-as-judge classifier for uncertainty fallback."""

    _PROMPT_TEMPLATE = (
        "Classify this user prompt into exactly one tier: SIMPLE, MEDIUM, "
        "COMPLEX, or REASONING. Respond with ONLY the tier name, nothing "
        "else.\n\nUser prompt: {text}"
    )

    _VALID_TIERS = {"SIMPLE", "MEDIUM", "COMPLEX", "REASONING"}

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.model = model or os.environ.get(
            "KANI_LLM_CLASSIFIER_MODEL", "google/gemini-2.5-flash-lite"
        )
        self.base_url = (
            base_url
            or os.environ.get(
                "KANI_LLM_CLASSIFIER_BASE_URL", "https://openrouter.ai/api/v1"
            )
        ).rstrip("/")
        self.api_key = (
            api_key
            or os.environ.get("KANI_LLM_CLASSIFIER_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY", "")
        )

    def _call_llm(self, prompt: str, *, max_tokens: int = 20) -> str | None:
        """Send a classification prompt and return normalized content."""
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.0,
                },
                timeout=2.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
                .upper()
            )
        except Exception as exc:
            log.debug("LLM classifier error: %s", exc)
            return None

    def classify(self, text: str) -> tuple[Tier, float] | None:
        """Call the LLM to classify *text*.

        Returns (Tier, 0.8) on success, None on any error or timeout.
        """
        prompt = self._PROMPT_TEMPLATE.format(text=text[:500])
        content = self._call_llm(prompt)
        if content is None:
            return None
        for tier_name in self._VALID_TIERS:
            if tier_name in content:
                return Tier(tier_name), 0.8
        log.warning("LLM classifier returned unrecognised tier: %r", content)
        return None


class AgenticClassifier:
    """Cheap binary classifier for action-oriented prompts."""

    _PROMPT_TEMPLATE = (
        "Decide whether this user prompt is AGENTIC or NON_AGENTIC. "
        "AGENTIC means the user is primarily asking the model to take actions "
        "using tools or external systems, such as editing files, running "
        "commands, browsing, calling APIs, or executing a multi-step task in "
        "the world. NON_AGENTIC means the user mainly wants a text answer, "
        "analysis, explanation, summary, or advice. Respond with ONLY "
        "AGENTIC or NON_AGENTIC.\n\nUser prompt: {text}"
    )

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.model = model or os.environ.get(
            "KANI_AGENTIC_CLASSIFIER_MODEL",
            os.environ.get("KANI_LLM_CLASSIFIER_MODEL", "google/gemini-2.5-flash-lite"),
        )
        self.base_url = (
            base_url
            or os.environ.get(
                "KANI_AGENTIC_CLASSIFIER_BASE_URL",
                os.environ.get(
                    "KANI_LLM_CLASSIFIER_BASE_URL", "https://openrouter.ai/api/v1"
                ),
            )
        ).rstrip("/")
        self.api_key = (
            api_key
            or os.environ.get("KANI_AGENTIC_CLASSIFIER_API_KEY")
            or os.environ.get("KANI_LLM_CLASSIFIER_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY", "")
        )

    def _call_llm(self, prompt: str, *, max_tokens: int = 8) -> str | None:
        """Send a classification prompt and return normalized content."""
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.0,
                },
                timeout=2.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
                .upper()
            )
        except Exception as exc:
            log.debug("Agentic classifier error: %s", exc)
            return None

    def classify(self, text: str) -> tuple[float, str] | None:
        """Return (agentic_score, label) or None on failure."""
        prompt = self._PROMPT_TEMPLATE.format(text=text[:500])
        content = self._call_llm(prompt)
        if content is None:
            return None
        if "NON_AGENTIC" in content:
            return 0.0, "NON_AGENTIC"
        if "AGENTIC" in content:
            return 1.0, "AGENTIC"
        log.warning("Agentic classifier returned unrecognised label: %r", content)
        return None


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class Scorer:
    """Model-first prompt classifier.

    Pipeline:
    1. Use the embedding classifier when it exists and is confident enough.
    2. Escalate uncertain or unavailable cases to a cheap LLM classifier.
    3. Fall back to a conservative default tier when both are unavailable.
    """

    def __init__(
        self,
        config: ScoringConfig | None = None,
        *,
        use_embedding: bool = True,
        embedding_model_dir: Path | None = None,
        embedding_min_confidence: float = 0.65,
        use_llm_classifier: bool = True,
        llm_classifier: LLMClassifier | None = None,
        agentic_classifier: AgenticClassifier | None = None,
        agentic_embedding_model_dir: Path | None = None,
        agentic_embedding_min_confidence: float = 0.7,
        enable_routing_log: bool = True,
    ) -> None:
        self.config = config or ScoringConfig()
        self._embedding_clf: EmbeddingClassifier | None = None
        self._use_embedding = use_embedding
        self._embedding_model_dir = embedding_model_dir
        self._embedding_min_confidence = embedding_min_confidence
        self._embedding_loaded = False
        self._use_llm_classifier = use_llm_classifier
        self._llm_classifier = llm_classifier or LLMClassifier()
        self._agentic_classifier = agentic_classifier
        self._agentic_embedding_clf: AgenticEmbeddingClassifier | None = None
        self._agentic_embedding_model_dir = agentic_embedding_model_dir
        self._agentic_embedding_min_confidence = agentic_embedding_min_confidence
        self._agentic_embedding_loaded = False
        self._enable_routing_log = enable_routing_log

    def _try_embedding_predict(self, text: str) -> tuple[Tier, float] | None:
        """Attempt embedding-based classification. Returns None on failure."""
        if not self._use_embedding:
            return None
        if not self._embedding_loaded:
            self._embedding_loaded = True
            self._embedding_clf = EmbeddingClassifier.load(self._embedding_model_dir)
        if self._embedding_clf is None:
            return None
        try:
            return self._embedding_clf.predict(text)
        except Exception as exc:
            log.warning("Embedding classification failed: %s", exc)
            return None

    @staticmethod
    def _build_result(
        *,
        tier: Tier,
        confidence: float,
        method: str,
        score: float | None = None,
        agentic_score: float = 0.0,
        extra_signals: dict[str, Any] | None = None,
    ) -> ClassificationResult:
        signals: dict[str, Any] = {"method": {"raw": method, "matches": 0}}
        if extra_signals:
            signals.update(extra_signals)
        return ClassificationResult(
            score=confidence if score is None else score,
            tier=tier,
            confidence=confidence,
            signals=signals,
            agentic_score=agentic_score,
            dimensions=[],
        )

    def _try_agentic_embedding_predict(
        self,
        text: str,
    ) -> tuple[float, str, float] | None:
        """Attempt learned AGENTIC/NON_AGENTIC classification."""
        if not self._agentic_embedding_loaded:
            self._agentic_embedding_loaded = True
            self._agentic_embedding_clf = AgenticEmbeddingClassifier.load(
                self._agentic_embedding_model_dir
            )
        if self._agentic_embedding_clf is None:
            return None
        try:
            return self._agentic_embedding_clf.predict(text)
        except Exception as exc:
            log.warning("Agentic embedding classification failed: %s", exc)
            return None

    @staticmethod
    def _set_agentic_result(
        result: ClassificationResult,
        *,
        agentic_score: float,
        label: str,
        method: str,
        extra_signals: dict[str, Any] | None = None,
    ) -> ClassificationResult:
        result.agentic_score = agentic_score
        result.signals["agenticMethod"] = {"raw": method, "matches": 0}
        result.signals["agenticLabel"] = {"raw": label, "matches": 0}
        if extra_signals:
            result.signals.update(extra_signals)
        return result

    def _apply_agentic_classification(
        self,
        text: str,
        result: ClassificationResult,
        *,
        classify_agentic: bool,
    ) -> ClassificationResult:
        """Optionally enrich SIMPLE prompts with agentic classification."""
        if not classify_agentic or result.tier != Tier.SIMPLE:
            return result

        agentic_embedding = self._try_agentic_embedding_predict(text)
        if agentic_embedding is not None:
            agentic_score, label, confidence = agentic_embedding
            if confidence >= self._agentic_embedding_min_confidence:
                return self._set_agentic_result(
                    result,
                    agentic_score=agentic_score,
                    label=label,
                    method="embedding",
                )

        if self._agentic_classifier is not None:
            agentic_result = self._agentic_classifier.classify(text)
            if agentic_result is not None:
                agentic_score, label = agentic_result
                extra_signals: dict[str, Any] | None = None
                if agentic_embedding is not None:
                    _, _, confidence = agentic_embedding
                    extra_signals = {
                        "agenticEmbeddingConfidence": {
                            "raw": confidence,
                            "matches": 0,
                        }
                    }
                return self._set_agentic_result(
                    result,
                    agentic_score=agentic_score,
                    label=label,
                    method="llm",
                    extra_signals=extra_signals,
                )

        if agentic_embedding is not None:
            agentic_score, label, _ = agentic_embedding
            return self._set_agentic_result(
                result,
                agentic_score=agentic_score,
                label=label,
                method="embedding-low-confidence",
            )

        return result

    def classify(
        self, text: str, *, classify_agentic: bool = False
    ) -> ClassificationResult:
        """Classify a prompt into a tier with confidence and metadata."""
        result = self._classify_internal(text)
        result = self._apply_agentic_classification(
            text,
            result,
            classify_agentic=classify_agentic,
        )

        if self._enable_routing_log:
            from kani.logger import RoutingLogger

            RoutingLogger.log(text, result)

        return result

    def _classify_internal(self, text: str) -> ClassificationResult:
        """Core classification pipeline."""
        embedding_prediction = self._try_embedding_predict(text)
        if embedding_prediction is not None:
            tier, confidence = embedding_prediction
            if confidence >= self._embedding_min_confidence:
                return self._build_result(
                    tier=tier,
                    confidence=confidence,
                    method="embedding",
                )

        if self._use_llm_classifier:
            llm_result = self._llm_classifier.classify(text)
            if llm_result is not None:
                tier, confidence = llm_result
                extra_signals: dict[str, Any] | None = None
                if embedding_prediction is not None:
                    _, embedding_confidence = embedding_prediction
                    extra_signals = {
                        "embeddingConfidence": {
                            "raw": embedding_confidence,
                            "matches": 0,
                        }
                    }
                return self._build_result(
                    tier=tier,
                    confidence=confidence,
                    method="llm",
                    extra_signals=extra_signals,
                )

        if embedding_prediction is not None:
            tier, confidence = embedding_prediction
            return self._build_result(
                tier=tier,
                confidence=confidence,
                method="embedding-low-confidence",
            )

        return self._build_result(
            tier=self.config.fallback_tier,
            confidence=self.config.fallback_confidence,
            method="default",
            score=0.0,
        )
