"""Train a multi-output distilled feature classifier for kani routing."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any, cast

import numpy as np
from openai import OpenAI
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.multioutput import MultiOutputClassifier
from sklearn.preprocessing import LabelEncoder

from kani.scorer import SEMANTIC_DIMENSIONS

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_MODEL_OPENROUTER = "openai/text-embedding-3-small"
EMBEDDING_DIM = 1536
BATCH_SIZE = 100
VALID_DIMENSION_LABELS = {"low", "medium", "high"}
DEFAULT_WEIGHTS: dict[str, float] = {
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
DEFAULT_THRESHOLDS: dict[str, float] = {"SIMPLE": 0.2, "MEDIUM": 0.45, "COMPLEX": 0.7}


def get_embeddings(
    client: OpenAI, texts: list[str], model: str = EMBEDDING_MODEL
) -> np.ndarray[Any, np.dtype[np.float32]]:
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        print(
            f"  Embedding batch {i // BATCH_SIZE + 1}/{(len(texts) - 1) // BATCH_SIZE + 1} ({len(batch)} items)..."
        )
        resp = client.embeddings.create(input=batch, model=model)
        for item in resp.data:
            all_embeddings.append(item.embedding)
        if i + BATCH_SIZE < len(texts):
            time.sleep(0.2)
    return np.array(all_embeddings, dtype=np.float32)


def load_or_compute_embeddings(
    client: OpenAI,
    texts: list[str],
    cache_path: Path,
    model: str = EMBEDDING_MODEL,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    content_hash = hashlib.sha256(
        json.dumps(texts, sort_keys=True).encode()
    ).hexdigest()[:12]
    cache_file = cache_path / f"embeddings_{content_hash}.npy"

    if cache_file.exists():
        print(f"  Loading cached embeddings from {cache_file}")
        return cast(np.ndarray[Any, np.dtype[np.float32]], np.load(cache_file))

    print(f"  Computing embeddings for {len(texts)} texts...")
    embeddings = get_embeddings(client, texts, model=model)
    cache_path.mkdir(parents=True, exist_ok=True)
    np.save(cache_file, embeddings)
    print(f"  Cached to {cache_file}")
    return embeddings


def build_embedding_client() -> tuple[OpenAI, str]:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    base_url = None
    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        base_url = "https://openrouter.ai/api/v1"
        print("  Using OpenRouter for embeddings")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY or OPENROUTER_API_KEY")

    embedding_model = EMBEDDING_MODEL_OPENROUTER if base_url else EMBEDDING_MODEL
    return OpenAI(api_key=api_key, base_url=base_url), embedding_model


def load_feature_examples(data_path: Path) -> tuple[list[str], dict[str, list[str]]]:
    with open(data_path, encoding="utf-8") as f:
        dataset = json.load(f)

    prompts = [str(item["prompt"]).strip() for item in dataset]
    if not prompts:
        raise ValueError("Feature training dataset is empty")
    if any(not prompt for prompt in prompts):
        raise ValueError("Feature training dataset contains empty prompts")

    labels_by_dimension: dict[str, list[str]] = {dim: [] for dim in SEMANTIC_DIMENSIONS}
    for item in dataset:
        for dim in SEMANTIC_DIMENSIONS:
            label = str(item.get(dim, "")).strip().lower()
            if label not in VALID_DIMENSION_LABELS:
                raise ValueError(f"Invalid label for {dim}: {label}")
            labels_by_dimension[dim].append(label)

    return prompts, labels_by_dimension


def train_feature_classifier(
    *,
    data_path: Path,
    output_dir: Path,
    cache_dir: Path,
) -> Path:
    prompts, labels_by_dimension = load_feature_examples(data_path)
    print(f"Loaded {len(prompts)} prompts")

    label_encoders: dict[str, LabelEncoder] = {}
    encoded_targets: list[np.ndarray[Any, np.dtype[np.int_]]] = []
    for dim in SEMANTIC_DIMENSIONS:
        encoder = LabelEncoder()
        target_raw = encoder.fit_transform(labels_by_dimension[dim])
        target = cast(np.ndarray[Any, np.dtype[np.int_]], target_raw)
        label_encoders[dim] = encoder
        encoded_targets.append(target)

        classes_raw = cast(np.ndarray[Any, np.dtype[Any]], encoder.classes_)
        classes = [str(label) for label in classes_raw]
        encoded_class_values_raw = encoder.transform(classes)
        encoded_class_values = cast(
            np.ndarray[Any, np.dtype[np.int_]], encoded_class_values_raw
        )
        class_mapping = {
            label: int(encoded_class_values[index])
            for index, label in enumerate(classes)
        }
        print(f"  {dim}: {class_mapping}")

    for dim, labels in labels_by_dimension.items():
        if len(set(labels)) < 2:
            raise ValueError(f"Dimension {dim} needs at least two label classes")

    y = np.column_stack(encoded_targets)

    print("\n--- Embeddings ---")
    client, embedding_model = build_embedding_client()
    X = load_or_compute_embeddings(client, prompts, cache_dir, embedding_model)
    print(f"  Shape: {X.shape}")

    base_clf = LogisticRegression(
        max_iter=1200,
        C=1.0,
        solver="lbfgs",
        class_weight="balanced",
    )
    clf = MultiOutputClassifier(base_clf)

    print("\n--- Training model ---")
    clf.fit(X, y)

    print("\n--- Training report (in-sample) ---")
    y_pred = clf.predict(X)
    for idx, dim in enumerate(SEMANTIC_DIMENSIONS):
        classes_raw = cast(np.ndarray[Any, np.dtype[Any]], label_encoders[dim].classes_)
        target_names = [str(name) for name in classes_raw]
        report = classification_report(
            y[:, idx],
            y_pred[:, idx],
            target_names=target_names,
            zero_division="0",
        )
        print(f"[{dim}]\n{report}")

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "feature_classifier.pkl"

    class_distribution: dict[str, dict[str, int]] = {}
    for dim in SEMANTIC_DIMENSIONS:
        counts: dict[str, int] = {}
        for label in labels_by_dimension[dim]:
            counts[label] = counts.get(label, 0) + 1
        class_distribution[dim] = counts

    with open(model_path, "wb") as f:
        pickle.dump(
            {
                "classifier": clf,
                "label_encoders": label_encoders,
                "semantic_dimensions": list(SEMANTIC_DIMENSIONS),
                "embedding_model": embedding_model,
                "embedding_dim": EMBEDDING_DIM,
                "training_size": len(prompts),
                "class_distribution": class_distribution,
                "weights": DEFAULT_WEIGHTS,
                "tier_thresholds": DEFAULT_THRESHOLDS,
                "feature_schema_version": "v1",
            },
            f,
        )

    print(f"Model saved to {model_path}")
    print(f"  Size: {model_path.stat().st_size / 1024:.1f} KB")
    return model_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train kani distilled feature classifier"
    )
    parser.add_argument(
        "--data",
        default="data/distilled_feature_dataset.json",
        help="Training data JSON",
    )
    parser.add_argument(
        "--output",
        default="models",
        help="Output directory for model files",
    )
    parser.add_argument(
        "--cache",
        default="data/cache",
        help="Embedding cache directory",
    )
    args = parser.parse_args(argv)

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"Error: {data_path} not found", file=sys.stderr)
        return 1

    try:
        train_feature_classifier(
            data_path=data_path,
            output_dir=Path(args.output),
            cache_dir=Path(args.cache),
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
