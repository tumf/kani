"""Kani Scoring Engine - 15-dimension prompt classifier.

A Python port of ClawRouter's scoring system. Classifies prompts into
four tiers: SIMPLE, MEDIUM, COMPLEX, REASONING based on weighted
dimension analysis.
"""

from __future__ import annotations

import logging
import math
import os
import pickle
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import tiktoken
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Tier(str, Enum):
    SIMPLE = "SIMPLE"
    MEDIUM = "MEDIUM"
    COMPLEX = "COMPLEX"
    REASONING = "REASONING"


# ---------------------------------------------------------------------------
# Configuration (fully overridable via Pydantic model)
# ---------------------------------------------------------------------------

class KeywordDimensionConfig(BaseModel):
    """Config for a single keyword-match dimension."""
    keywords: list[str]
    low_threshold: int = 1
    high_threshold: int = 3
    none_score: float = 0.0
    low_score: float = 0.5
    high_score: float = 1.0


class ScoringConfig(BaseModel):
    """Master configuration for the scoring engine."""

    # -- Keyword dimensions ------------------------------------------------
    code_presence: KeywordDimensionConfig = KeywordDimensionConfig(
        keywords=[
            "function", "class", "import", "def", "SELECT", "async", "await",
            "const", "let", "var", "return", "```",
            # JP
            "関数", "クラス", "インポート", "非同期", "定数", "変数",
        ],
        low_threshold=1, high_threshold=3,
        none_score=0.0, low_score=0.5, high_score=1.0,
    )

    reasoning_markers: KeywordDimensionConfig = KeywordDimensionConfig(
        keywords=[
            "prove", "theorem", "derive", "step by step", "chain of thought",
            "formally", "mathematical", "proof", "logically",
            # JP
            "証明", "定理", "導出", "ステップバイステップ", "論理的",
        ],
        low_threshold=1, high_threshold=2,
        none_score=0.0, low_score=0.5, high_score=1.0,
    )

    technical_terms: KeywordDimensionConfig = KeywordDimensionConfig(
        keywords=[
            "algorithm", "optimize", "architecture", "distributed",
            "kubernetes", "microservice", "database", "infrastructure",
            # JP
            "アルゴリズム", "最適化", "アーキテクチャ", "分散",
            "マイクロサービス", "データベース",
        ],
        low_threshold=1, high_threshold=3,
        none_score=0.0, low_score=0.5, high_score=1.0,
    )

    creative_markers: KeywordDimensionConfig = KeywordDimensionConfig(
        keywords=[
            "story", "poem", "compose", "brainstorm", "creative", "imagine",
            "write a",
            # JP
            "物語", "詩", "作曲", "ブレインストーム", "創造的", "想像",
        ],
        low_threshold=1, high_threshold=3,
        none_score=0.0, low_score=0.5, high_score=1.0,
    )

    simple_indicators: KeywordDimensionConfig = KeywordDimensionConfig(
        keywords=[
            "what is", "define", "translate", "hello", "yes or no",
            "capital of", "how old", "who is", "when was",
            # JP
            "とは", "定義", "翻訳", "こんにちは", "はいかいいえ", "首都", "誰",
        ],
        low_threshold=1, high_threshold=2,
        none_score=0.0, low_score=-0.5, high_score=-1.0,
    )

    imperative_verbs: KeywordDimensionConfig = KeywordDimensionConfig(
        keywords=[
            "build", "create", "implement", "design", "develop", "construct",
            "generate", "deploy", "configure", "set up",
            # JP
            "構築", "作成", "実装", "設計", "開発", "生成", "デプロイ", "設定",
        ],
        low_threshold=1, high_threshold=3,
        none_score=0.0, low_score=0.5, high_score=1.0,
    )

    constraint_count: KeywordDimensionConfig = KeywordDimensionConfig(
        keywords=[
            "must", "should", "ensure", "require", "constraint", "limit",
            "boundary", "within",
            # JP
            "必須", "すべき", "確保", "要求", "制約", "制限", "境界", "以内",
        ],
        low_threshold=1, high_threshold=3,
        none_score=0.0, low_score=0.5, high_score=1.0,
    )

    output_format: KeywordDimensionConfig = KeywordDimensionConfig(
        keywords=[
            "json", "csv", "table", "markdown", "yaml", "xml",
            "format as", "output as",
        ],
        low_threshold=1, high_threshold=2,
        none_score=0.0, low_score=0.5, high_score=1.0,
    )

    reference_complexity: KeywordDimensionConfig = KeywordDimensionConfig(
        keywords=[
            "according to", "based on", "reference", "citing",
            "as mentioned", "per the",
        ],
        low_threshold=1, high_threshold=3,
        none_score=0.0, low_score=0.5, high_score=1.0,
    )

    negation_complexity: KeywordDimensionConfig = KeywordDimensionConfig(
        keywords=[
            "not", "don't", "without", "except", "exclude", "never", "nor",
        ],
        low_threshold=1, high_threshold=3,
        none_score=0.0, low_score=0.5, high_score=1.0,
    )

    domain_specificity: KeywordDimensionConfig = KeywordDimensionConfig(
        keywords=[
            "medical", "legal", "financial", "scientific", "academic",
            "clinical", "regulatory", "compliance",
        ],
        low_threshold=1, high_threshold=3,
        none_score=0.0, low_score=0.5, high_score=1.0,
    )

    agentic_keywords: list[str] = Field(default=[
        "read file", "edit", "modify", "update", "execute", "run", "deploy",
        "install", "step 1", "step 2", "fix", "debug", "check",
        # JP
        "ファイル読み込み", "編集", "修正", "更新", "実行", "デプロイ",
        "インストール", "ステップ1", "ステップ2", "修正", "デバッグ", "確認",
    ])

    # -- Multi-step regex patterns -----------------------------------------
    multi_step_patterns: list[str] = Field(default=[
        r"first.*then",
        r"step \d",
        r"\d\.\s",
    ])

    # -- Dimension weights -------------------------------------------------
    weights: dict[str, float] = Field(default={
        "tokenCount": 0.08,
        "codePresence": 0.15,
        "reasoningMarkers": 0.18,
        "technicalTerms": 0.10,
        "creativeMarkers": 0.05,
        "simpleIndicators": 0.02,
        "multiStepPatterns": 0.12,
        "questionComplexity": 0.05,
        "imperativeVerbs": 0.03,
        "constraintCount": 0.04,
        "outputFormat": 0.03,
        "referenceComplexity": 0.02,
        "negationComplexity": 0.01,
        "domainSpecificity": 0.02,
        "agenticTask": 0.04,
    })

    # -- Tier boundaries ---------------------------------------------------
    simple_medium_boundary: float = 0.0
    medium_complex_boundary: float = 0.3
    complex_reasoning_boundary: float = 0.5

    # -- Confidence sigmoid ------------------------------------------------
    sigmoid_steepness: float = 12.0
    min_confidence: float = 0.7

    # -- Reasoning override ------------------------------------------------
    reasoning_override_min_matches: int = 2
    reasoning_override_min_confidence: float = 0.85


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DimensionResult:
    """Score for a single dimension."""
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
# Scorer
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
        self.embedding_model: str = data.get("embedding_model", "text-embedding-3-small")
        self._client: Any | None = None

    @classmethod
    def load(cls, model_dir: Path | None = None) -> EmbeddingClassifier | None:
        """Load the classifier singleton. Returns None if model file not found."""
        if cls._instance is not None and cls._model_dir == model_dir:
            return cls._instance
        if model_dir is None:
            # Default: <project_root>/models/tier_classifier.pkl
            model_dir = Path(__file__).resolve().parent.parent.parent / "models"
        pkl = model_dir / "tier_classifier.pkl"
        if not pkl.exists():
            return None
        try:
            cls._instance = cls(pkl)
            cls._model_dir = model_dir
            log.info("Loaded embedding classifier from %s", pkl)
            return cls._instance
        except Exception as e:
            log.warning("Failed to load embedding classifier: %s", e)
            return None

    def _get_client(self) -> Any:
        """Lazy-init OpenAI client for embedding inference."""
        if self._client is not None:
            return self._client
        from openai import OpenAI
        # Prefer OPENAI_API_KEY, fall back to OPENROUTER_API_KEY
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        base_url = None
        model = self.embedding_model
        if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
            base_url = "https://openrouter.ai/api/v1"
            # OpenRouter uses provider-prefixed model names
            if not model.startswith("openai/"):
                model = f"openai/{model}"
            self.embedding_model = model
        if not api_key:
            raise RuntimeError("No OPENAI_API_KEY or OPENROUTER_API_KEY for embeddings")
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        return self._client

    def predict(self, text: str) -> tuple[Tier, float]:
        """Predict tier and confidence for a prompt.

        Returns:
            (tier, confidence) tuple.
        """
        import numpy as np
        client = self._get_client()
        resp = client.embeddings.create(input=[text], model=self.embedding_model)
        embedding = np.array([resp.data[0].embedding], dtype=np.float32)
        proba = self.classifier.predict_proba(embedding)[0]
        pred_idx = int(np.argmax(proba))
        tier_name = self.label_encoder.inverse_transform([pred_idx])[0]
        confidence = float(proba[pred_idx])
        return Tier(tier_name), confidence


class Scorer:
    """15-dimension prompt scoring engine."""

    def __init__(
        self,
        config: ScoringConfig | None = None,
        *,
        use_embedding: bool = True,
        embedding_model_dir: Path | None = None,
        embedding_min_confidence: float = 0.65,
    ) -> None:
        self.config = config or ScoringConfig()
        self._encoder: tiktoken.Encoding | None = None
        self._embedding_clf: EmbeddingClassifier | None = None
        self._use_embedding = use_embedding
        self._embedding_model_dir = embedding_model_dir
        self._embedding_min_confidence = embedding_min_confidence
        self._embedding_loaded = False

    @property
    def encoder(self) -> tiktoken.Encoding:
        if self._encoder is None:
            self._encoder = tiktoken.get_encoding("cl100k_base")
        return self._encoder

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _keyword_score(
        text: str,
        keywords: list[str],
        low_threshold: int,
        high_threshold: int,
        none_score: float,
        low_score: float,
        high_score: float,
    ) -> tuple[float, int]:
        """Count case-insensitive keyword matches and return (score, count)."""
        lower = text.lower()
        count = sum(1 for kw in keywords if kw.lower() in lower)
        if count >= high_threshold:
            return high_score, count
        if count >= low_threshold:
            return low_score, count
        return none_score, count

    @staticmethod
    def _keyword_score_from_config(
        text: str, cfg: KeywordDimensionConfig,
    ) -> tuple[float, int]:
        return Scorer._keyword_score(
            text, cfg.keywords,
            cfg.low_threshold, cfg.high_threshold,
            cfg.none_score, cfg.low_score, cfg.high_score,
        )

    def _estimate_tokens(self, text: str) -> int:
        return len(self.encoder.encode(text))

    @staticmethod
    def _sigmoid_confidence(distance: float, steepness: float) -> float:
        return 1.0 / (1.0 + math.exp(-steepness * distance))

    # -- dimension scorers -------------------------------------------------

    def _score_token_count(self, text: str) -> DimensionResult:
        tokens = self._estimate_tokens(text)
        if tokens < 50:
            raw = -1.0
        elif tokens > 500:
            raw = 1.0
        else:
            raw = 0.0
        w = self.config.weights["tokenCount"]
        return DimensionResult("tokenCount", raw, w, raw * w, match_count=tokens)

    def _score_keyword_dim(
        self, text: str, name: str, cfg: KeywordDimensionConfig,
    ) -> DimensionResult:
        raw, count = self._keyword_score_from_config(text, cfg)
        w = self.config.weights[name]
        return DimensionResult(name, raw, w, raw * w, match_count=count)

    def _score_multi_step(self, text: str) -> DimensionResult:
        hit = any(
            re.search(pat, text, re.IGNORECASE | re.DOTALL)
            for pat in self.config.multi_step_patterns
        )
        raw = 0.5 if hit else 0.0
        w = self.config.weights["multiStepPatterns"]
        return DimensionResult("multiStepPatterns", raw, w, raw * w, match_count=int(hit))

    def _score_question_complexity(self, text: str) -> DimensionResult:
        count = text.count("?")
        raw = 0.5 if count > 3 else 0.0
        w = self.config.weights["questionComplexity"]
        return DimensionResult("questionComplexity", raw, w, raw * w, match_count=count)

    def _score_agentic(self, text: str) -> DimensionResult:
        lower = text.lower()
        count = sum(1 for kw in self.config.agentic_keywords if kw.lower() in lower)
        if count >= 4:
            raw = 1.0
        elif count >= 3:
            raw = 0.6
        elif count >= 1:
            raw = 0.2
        else:
            raw = 0.0
        w = self.config.weights["agenticTask"]
        return DimensionResult("agenticTask", raw, w, raw * w, match_count=count)

    # -- main classify -----------------------------------------------------

    def _try_embedding_classify(self, text: str) -> ClassificationResult | None:
        """Attempt embedding-based classification. Returns None on failure."""
        if not self._use_embedding:
            return None
        # Lazy load once
        if not self._embedding_loaded:
            self._embedding_loaded = True
            self._embedding_clf = EmbeddingClassifier.load(self._embedding_model_dir)
        if self._embedding_clf is None:
            return None
        try:
            tier, confidence = self._embedding_clf.predict(text)
            if confidence < self._embedding_min_confidence:
                log.debug(
                    "Embedding confidence %.2f < threshold %.2f, falling back to rules",
                    confidence, self._embedding_min_confidence,
                )
                return None
            return ClassificationResult(
                score=confidence,
                tier=tier,
                confidence=confidence,
                signals={"method": {"raw": "embedding", "matches": 0}},
                agentic_score=0.0,
                dimensions=[],
            )
        except Exception as e:
            log.warning("Embedding classification failed: %s", e)
            return None

    def classify(self, text: str) -> ClassificationResult:
        """Classify a prompt into a tier with confidence and dimension details.

        Strategy: try embedding-based classifier first. If it returns a
        high-confidence result, use that. Otherwise fall back to the
        15-dimension rule-based scorer.
        """
        # --- Attempt embedding-based classification ---
        emb_result = self._try_embedding_classify(text)
        if emb_result is not None:
            return emb_result

        # --- Fall back to rule-based scoring ---
        return self._rules_classify(text)

    def _rules_classify(self, text: str) -> ClassificationResult:
        """15-dimension rule-based classification (original logic)."""
        cfg = self.config

        dims: list[DimensionResult] = [
            self._score_token_count(text),
            self._score_keyword_dim(text, "codePresence", cfg.code_presence),
            self._score_keyword_dim(text, "reasoningMarkers", cfg.reasoning_markers),
            self._score_keyword_dim(text, "technicalTerms", cfg.technical_terms),
            self._score_keyword_dim(text, "creativeMarkers", cfg.creative_markers),
            self._score_keyword_dim(text, "simpleIndicators", cfg.simple_indicators),
            self._score_multi_step(text),
            self._score_question_complexity(text),
            self._score_keyword_dim(text, "imperativeVerbs", cfg.imperative_verbs),
            self._score_keyword_dim(text, "constraintCount", cfg.constraint_count),
            self._score_keyword_dim(text, "outputFormat", cfg.output_format),
            self._score_keyword_dim(text, "referenceComplexity", cfg.reference_complexity),
            self._score_keyword_dim(text, "negationComplexity", cfg.negation_complexity),
            self._score_keyword_dim(text, "domainSpecificity", cfg.domain_specificity),
            self._score_agentic(text),
        ]

        total_score = sum(d.weighted_score for d in dims)

        # Determine reasoning match count for override
        reasoning_dim = next(d for d in dims if d.name == "reasoningMarkers")
        reasoning_match_count = reasoning_dim.match_count

        # Agentic score from agentic dimension
        agentic_dim = next(d for d in dims if d.name == "agenticTask")
        agentic_score = agentic_dim.raw_score

        # Build signals dict
        signals: dict[str, Any] = {
            d.name: {"raw": d.raw_score, "matches": d.match_count}
            for d in dims
        }

        # -- Tier determination --------------------------------------------
        boundaries = [
            cfg.simple_medium_boundary,
            cfg.medium_complex_boundary,
            cfg.complex_reasoning_boundary,
        ]

        if total_score <= cfg.simple_medium_boundary:
            tier = Tier.SIMPLE
        elif total_score <= cfg.medium_complex_boundary:
            tier = Tier.MEDIUM
        elif total_score <= cfg.complex_reasoning_boundary:
            tier = Tier.COMPLEX
        else:
            tier = Tier.REASONING

        # Confidence: distance from nearest boundary
        min_dist = min(abs(total_score - b) for b in boundaries)
        confidence = self._sigmoid_confidence(min_dist, cfg.sigmoid_steepness)

        # Special override: reasoning keywords >= threshold
        if reasoning_match_count >= cfg.reasoning_override_min_matches:
            tier = Tier.REASONING
            confidence = max(confidence, cfg.reasoning_override_min_confidence)

        # Ambiguity guard: low confidence -> default to MEDIUM
        if confidence < cfg.min_confidence:
            tier = Tier.MEDIUM

        return ClassificationResult(
            score=total_score,
            tier=tier,
            confidence=confidence,
            signals=signals,
            agentic_score=agentic_score,
            dimensions=dims,
        )
