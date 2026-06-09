# Routing

## ADDED Requirements

### Requirement: Lazy calibration prompt construction

The training-data annotation module MUST defer semantic-dimension calibration text construction until annotation prompt construction time, so that import-time failures do not block unrelated callers (implementation detail).

#### Scenario: Import does not eagerly validate calibration

- GIVEN the routing module defines `SEMANTIC_DIMENSIONS`
- AND the annotation module is imported
- WHEN the annotation module's training data classes are instantiated later
- THEN no semantic dimension calibration validation runs at import time

## MODIFIED Requirements

### Requirement: Agentic 分類

SIMPLE ティアのプロンプトに対して、agentic/non-agentic の追加分類を行うことができる (MAY)。

#### Scenario: Agentic 分類の発動条件

- GIVEN `classify_agentic=True` が指定される
- AND ティア分類の結果が SIMPLE である
- WHEN agentic 分類が実行される
- THEN agentic embedding 分類器 (信頼度閾値 0.7) → agentic LLM 分類器のカスケードで分類する
- AND `agentic_score` が 0.0 (NON_AGENTIC) または 1.0 (AGENTIC) に設定される
