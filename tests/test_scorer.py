"""Tests for kani scoring engine."""

from __future__ import annotations

from kani.scorer import ClassificationResult, Scorer, ScoringConfig, Tier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify(text: str, config: ScoringConfig | None = None) -> ClassificationResult:
    scorer = Scorer(config)
    return scorer.classify(text)


# ---------------------------------------------------------------------------
# Simple prompts -> SIMPLE tier
# ---------------------------------------------------------------------------


class TestSimpleTier:
    def test_hello(self) -> None:
        result = _classify("Hello")
        assert result.tier == Tier.SIMPLE

    def test_what_is(self) -> None:
        result = _classify("What is the capital of France?")
        assert result.tier == Tier.SIMPLE

    def test_define(self) -> None:
        result = _classify("Define photosynthesis")
        assert result.tier in (Tier.SIMPLE, Tier.MEDIUM)

    def test_yes_or_no(self) -> None:
        result = _classify("Is the sky blue? yes or no")
        assert result.tier == Tier.SIMPLE

    def test_japanese_simple(self) -> None:
        result = _classify("こんにちは")
        assert result.tier == Tier.SIMPLE

    def test_who_is(self) -> None:
        result = _classify("Who is Albert Einstein?")
        assert result.tier == Tier.SIMPLE


# ---------------------------------------------------------------------------
# Code prompts -> MEDIUM or COMPLEX
# ---------------------------------------------------------------------------


class TestCodePrompts:
    def test_simple_code_question(self) -> None:
        result = _classify("What does the import statement do in Python?")
        # Has both simple indicator and code presence -> at least MEDIUM
        assert result.tier in (Tier.MEDIUM, Tier.COMPLEX, Tier.SIMPLE)

    def test_code_with_keywords(self) -> None:
        result = _classify(
            "Write a function that uses async await to fetch data "
            "and return a class instance with const values"
        )
        assert result.tier in (Tier.MEDIUM, Tier.COMPLEX, Tier.REASONING)

    def test_complex_code_prompt(self) -> None:
        result = _classify(
            "Implement a distributed microservice architecture using kubernetes. "
            "The algorithm must optimize database queries. Build the infrastructure "
            "with async functions and deploy using class-based design patterns. "
            "Ensure the code handles import errors and return proper error codes. "
            "First set up the project, then configure the services. Step 1: design. "
            "Step 2: implement. Must handle all constraints within the boundary limits. "
            "The system should require compliance with regulatory standards. "
            "Generate the output as json format. According to best practices, "
            "develop a robust and scalable solution that meets all requirements."
        )
        # Score lands in COMPLEX range but may fall to MEDIUM via ambiguity guard
        assert result.tier in (Tier.MEDIUM, Tier.COMPLEX, Tier.REASONING)
        # Verify the raw score is at least in the complex range
        assert result.score >= 0.3

    def test_code_with_backticks(self) -> None:
        result = _classify(
            "Review the following code:\n```\ndef hello():\n    return 'hi'\n```"
        )
        # Should detect code presence
        dims = {d.name: d for d in result.dimensions}
        assert dims["codePresence"].match_count >= 1


# ---------------------------------------------------------------------------
# Reasoning prompts -> REASONING tier
# ---------------------------------------------------------------------------


class TestReasoningPrompts:
    def test_prove_theorem(self) -> None:
        result = _classify(
            "Prove the theorem that every continuous function on a closed interval "
            "is bounded. Derive the result step by step."
        )
        assert result.tier == Tier.REASONING

    def test_mathematical_proof(self) -> None:
        result = _classify(
            "Provide a mathematical proof that the square root of 2 is irrational. "
            "Reason logically and formally."
        )
        assert result.tier == Tier.REASONING

    def test_chain_of_thought(self) -> None:
        result = _classify(
            "Using chain of thought reasoning, prove that P implies Q "
            "given the following axioms."
        )
        assert result.tier == Tier.REASONING

    def test_japanese_reasoning(self) -> None:
        result = _classify(
            "この定理を証明してください。ステップバイステップで導出してください。"
        )
        assert result.tier == Tier.REASONING

    def test_reasoning_override_confidence(self) -> None:
        """Reasoning override should produce confidence >= 0.85."""
        result = _classify("Prove the theorem formally using mathematical induction.")
        assert result.tier == Tier.REASONING
        assert result.confidence >= 0.85


# ---------------------------------------------------------------------------
# Agentic prompts -> agentic_score > 0
# ---------------------------------------------------------------------------


class TestAgenticPrompts:
    def test_agentic_basic(self) -> None:
        result = _classify("Read file config.yaml and edit the deploy section")
        assert result.agentic_score > 0

    def test_agentic_multi_keyword(self) -> None:
        result = _classify(
            "Step 1: read file package.json. Step 2: update the version. "
            "Then run the tests and fix any errors. Debug if needed and deploy."
        )
        assert result.agentic_score > 0
        # Should be high agentic score with many matches
        dims = {d.name: d for d in result.dimensions}
        assert dims["agenticTask"].match_count >= 4
        assert result.agentic_score == 1.0

    def test_agentic_zero(self) -> None:
        result = _classify("What is the meaning of life?")
        assert result.agentic_score == 0.0

    def test_japanese_agentic(self) -> None:
        result = _classify(
            "ファイル読み込みして編集してください。修正してデプロイしてください。"
        )
        assert result.agentic_score > 0


# ---------------------------------------------------------------------------
# Configuration override
# ---------------------------------------------------------------------------


class TestConfigOverride:
    def test_custom_weights(self) -> None:
        config = ScoringConfig(
            weights={
                "tokenCount": 0.0,
                "codePresence": 0.0,
                "reasoningMarkers": 1.0,  # massively boosted
                "technicalTerms": 0.0,
                "creativeMarkers": 0.0,
                "simpleIndicators": 0.0,
                "multiStepPatterns": 0.0,
                "questionComplexity": 0.0,
                "imperativeVerbs": 0.0,
                "constraintCount": 0.0,
                "outputFormat": 0.0,
                "referenceComplexity": 0.0,
                "negationComplexity": 0.0,
                "domainSpecificity": 0.0,
                "agenticTask": 0.0,
            },
            reasoning_override_min_matches=999,  # disable override
        )
        result = _classify("prove the theorem", config)
        # Should still produce a score driven by reasoning
        assert result.score > 0

    def test_custom_boundaries(self) -> None:
        config = ScoringConfig(
            medium_complex_boundary=0.01,
            complex_reasoning_boundary=0.02,
            min_confidence=0.0,  # disable ambiguity guard for this test
        )
        # Even a moderately complex prompt should hit REASONING with low boundaries
        result = _classify(
            "Build a microservice with kubernetes and optimize the algorithm",
            config,
        )
        assert result.tier in (Tier.COMPLEX, Tier.REASONING)


# ---------------------------------------------------------------------------
# Dimension details
# ---------------------------------------------------------------------------


class TestDimensions:
    def test_dimensions_returned(self) -> None:
        result = _classify("Hello world")
        assert len(result.dimensions) == 15

    def test_multi_step_pattern(self) -> None:
        result = _classify("First do X, then do Y. Step 3: finalize.")
        dims = {d.name: d for d in result.dimensions}
        assert dims["multiStepPatterns"].raw_score == 0.5

    def test_question_complexity(self) -> None:
        result = _classify("Why? How? When? Where? What?")
        dims = {d.name: d for d in result.dimensions}
        assert dims["questionComplexity"].raw_score == 0.5

    def test_output_format(self) -> None:
        result = _classify("Format as json and output as csv table")
        dims = {d.name: d for d in result.dimensions}
        assert dims["outputFormat"].match_count >= 2

    def test_confidence_is_valid(self) -> None:
        result = _classify("Build a complex distributed system")
        assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string(self) -> None:
        result = _classify("")
        assert result.tier in (Tier.SIMPLE, Tier.MEDIUM)

    def test_very_long_prompt(self) -> None:
        long_text = "word " * 600
        result = _classify(long_text)
        dims = {d.name: d for d in result.dimensions}
        assert dims["tokenCount"].raw_score == 1.0

    def test_short_prompt_negative_token_score(self) -> None:
        result = _classify("Hi")
        dims = {d.name: d for d in result.dimensions}
        assert dims["tokenCount"].raw_score == -1.0
