#!/usr/bin/env python3
"""Quick test for model-first scorer integration."""

from kani.scorer import Scorer

s = Scorer()
tests = [
    "hello",
    "Write a Python function to sort a list",
    "Design a distributed database with CRDT support and multi-region failover",
    "Prove that P != NP implies one-way functions exist, step by step",
    "今日の天気は？",
    "Kubernetesクラスタのアーキテクチャを設計して、マルチリージョンフェイルオーバーを実装してください",
]
for t in tests:
    r = s.classify(t)
    method = r.signals.get("method", {}).get("raw", "default")
    print(
        f"[{r.tier.value:9s}] conf={r.confidence:.3f} method={method!s:9s} | {t[:70]}"
    )
