# Design: Context-Aware Classification Input

## Overview

This change shifts routing classification away from using only the final user message. Instead, routing and training pipelines will derive a deterministic classification input from the surrounding conversation context.

The goal is not to classify the entire raw transcript verbatim, but to construct a bounded text representation that preserves the intent required for complexity and agentic routing decisions.

## Problem

The current extraction logic in `Router._extract_prompts()` returns:

- the last `system` message
- the last `user` message

The scorer then classifies only the final user prompt. This loses important context when the final message is a continuation, confirmation, or short amendment.

Examples:

- "はい"
- "続けて"
- "それでお願いします"
- "その方針で"

These are low-information messages in isolation, but high-information when attached to the active task context.

## Design Goals

- Preserve enough recent context to classify task complexity and agentic intent correctly.
- Use the same representation in runtime and offline dataset generation.
- Keep the representation deterministic and bounded.
- Avoid adding new runtime LLM dependencies.

## Proposed Input Model

Introduce a shared builder that produces a `classification_text` from message arrays.

The builder should include, in a deterministic order:

1. Relevant system prompt text
2. The latest user request that introduced or materially changed the task
3. Recent follow-up user turns that refine constraints or confirm continuation
4. Optionally selected assistant text only when needed to preserve explicit task framing already established in the conversation

The builder should exclude irrelevant old turns and non-text multimodal content, consistent with current message extraction behavior.

## Bounding Strategy

The classification input should remain bounded to avoid runaway token cost and noisy context.

Recommended strategy:

- include the latest system message
- walk backward through recent conversation turns
- keep user turns that still belong to the active task thread
- stop when the text budget or turn budget is reached
- prefer preserving user-authored constraints and task statements over assistant exposition

This remains deterministic and does not require summarization.

## Runtime Integration

### Router

`Router` should stop treating the final user turn as the sole classification prompt.

Instead it should:

- extract a bounded context-aware classification text
- pass that text into `Scorer.classify(...)`
- continue routing on the returned tier and agentic score as before

### Scorer

`Scorer` does not need to understand message arrays directly if the shared builder already produces classification text. The scorer may continue accepting a single string input, but that string must now represent the conversation context rather than only the last user prompt.

## Training Integration

The training-data generation path must use the same classification-input semantics, otherwise runtime and distilled supervision diverge.

Dataset builders should therefore operate on conversation-derived classification text whenever message arrays or logs contain enough information to reconstruct it.

If historical logs only contain a raw prompt, those records may still be used, but newly written logs should preserve context-aware classification input metadata to improve future training quality.

## Logging

To keep scoring decisions replayable, logs should include either:

- the exact classification text used for scoring, or
- a bounded preview plus enough metadata to reconstruct it deterministically

This avoids a situation where production routing decisions cannot be reproduced offline because only the last user message was stored.

## Risks and Trade-offs

### Risk: Too much assistant text biases classification

Mitigation:
- prefer user and system text first
- include assistant text only when it carries task framing that would otherwise be lost
- cover with regression tests

### Risk: Too much context raises token cost for embeddings

Mitigation:
- use bounded context construction
- prefer recent, relevant turns only
- add deterministic clipping rules

### Risk: Historical logs remain less useful than new logs

Mitigation:
- allow backward-compatible dataset generation from old prompt-only logs
- improve logging shape for all new routing decisions
