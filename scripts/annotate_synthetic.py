"""Annotate synthetic prompts with the configured feature annotator."""

from __future__ import annotations

import json
from pathlib import Path

from kani.training_data import LLMFeatureAnnotator, _validate_semantic_labels

src = Path("data/synthetic_prompts.jsonl")
out = Path("data/synthetic_labeled.json")
annotator = LLMFeatureAnnotator()
rows: list[dict] = []
for i, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
    if not line.strip():
        continue
    prompt = json.loads(line)["prompt"]
    print(f"[{i}] annotate: {prompt[:80]}")
    labels = annotator.annotate(prompt)
    if not labels or not _validate_semantic_labels(labels):
        print(f"[{i}] skip: invalid labels")
        continue
    rows.append(
        {
            "prompt": prompt,
            "tokenCount": max(1, len(prompt.split())),
            **labels,
            "timestamp": None,
            "source": "synthetic-annotated",
        }
    )
    out.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[{i}] checkpoint: {len(rows)} saved")

print(f"wrote {len(rows)} rows to {out}")
