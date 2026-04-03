"""Deprecated wrappers for distilled feature classifier training.

This module keeps legacy function names for compatibility while delegating to the
new multi-output distilled feature training pipeline.
"""

from __future__ import annotations

from pathlib import Path

from kani.feature_training import (
    load_feature_examples,
    main as _feature_main,
    train_feature_classifier,
)


def load_agentic_examples(data_path: Path) -> tuple[list[str], list[str]]:
    """Compatibility wrapper returning prompts and agenticTask labels."""
    prompts, labels_by_dimension = load_feature_examples(data_path)
    return prompts, labels_by_dimension["agenticTask"]


def train_agentic_classifier(
    *,
    data_path: Path,
    output_dir: Path,
    cache_dir: Path,
) -> Path:
    """Compatibility wrapper delegating to distilled feature training."""
    return train_feature_classifier(
        data_path=data_path,
        output_dir=output_dir,
        cache_dir=cache_dir,
    )


def main(argv: list[str] | None = None) -> int:
    """Run distilled feature training through legacy entrypoint."""
    return _feature_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
