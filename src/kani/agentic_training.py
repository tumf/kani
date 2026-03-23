"""Train an embedding-based AGENTIC/NON_AGENTIC classifier for kani."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
import time
from pathlib import Path

import numpy as np
from openai import OpenAI
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.preprocessing import LabelEncoder


EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_MODEL_OPENROUTER = "openai/text-embedding-3-small"
EMBEDDING_DIM = 1536
BATCH_SIZE = 100
VALID_AGENTIC_LABELS = {"AGENTIC", "NON_AGENTIC"}


def get_embeddings(
    client: OpenAI, texts: list[str], model: str = EMBEDDING_MODEL
) -> np.ndarray:
    """Get embeddings for a list of texts, batched."""
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
) -> np.ndarray:
    """Load embeddings from cache or compute them."""
    content_hash = hashlib.sha256(
        json.dumps(texts, sort_keys=True).encode()
    ).hexdigest()[:12]
    cache_file = cache_path / f"embeddings_{content_hash}.npy"

    if cache_file.exists():
        print(f"  Loading cached embeddings from {cache_file}")
        return np.load(cache_file)

    print(f"  Computing embeddings for {len(texts)} texts...")
    embeddings = get_embeddings(client, texts, model=model)
    cache_path.mkdir(parents=True, exist_ok=True)
    np.save(cache_file, embeddings)
    print(f"  Cached to {cache_file}")
    return embeddings


def build_embedding_client() -> tuple[OpenAI, str]:
    """Create an embedding client using OpenAI or OpenRouter env vars."""
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    base_url = None
    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        base_url = "https://openrouter.ai/api/v1"
        print("  Using OpenRouter for embeddings")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY or OPENROUTER_API_KEY")

    embedding_model = EMBEDDING_MODEL_OPENROUTER if base_url else EMBEDDING_MODEL
    return OpenAI(api_key=api_key, base_url=base_url), embedding_model


def load_agentic_examples(data_path: Path) -> tuple[list[str], list[str]]:
    """Load prompt/label pairs for binary AGENTIC training."""
    with open(data_path, encoding="utf-8") as f:
        dataset = json.load(f)

    prompts = [str(item["prompt"]).strip() for item in dataset]
    labels = [str(item["label"]).strip().upper() for item in dataset]

    invalid_labels = sorted(
        {label for label in labels if label not in VALID_AGENTIC_LABELS}
    )
    if invalid_labels:
        raise ValueError(f"Unsupported agentic labels: {', '.join(invalid_labels)}")
    if not prompts:
        raise ValueError("Agentic training dataset is empty")
    if any(not prompt for prompt in prompts):
        raise ValueError("Agentic training dataset contains empty prompts")
    if len(set(labels)) < 2:
        raise ValueError(
            "Agentic training dataset needs both AGENTIC and NON_AGENTIC labels"
        )

    return prompts, labels


def _cross_validation_splits(labels: list[str]) -> int:
    counts = [labels.count(label) for label in sorted(set(labels))]
    return max(2, min(5, min(counts)))


def train_agentic_classifier(
    *,
    data_path: Path,
    output_dir: Path,
    cache_dir: Path,
) -> Path:
    """Train and persist an embedding-based binary agentic classifier."""
    prompts, labels = load_agentic_examples(data_path)
    print(f"Loaded {len(prompts)} prompts")
    for label in sorted(set(labels)):
        print(f"  {label}: {labels.count(label)}")

    label_encoder = LabelEncoder()
    y = label_encoder.fit_transform(labels)
    encoded_labels = label_encoder.transform(labels)
    label_encoding = {
        label: int(code) for label, code in zip(labels, encoded_labels, strict=False)
    }
    print(f"\nLabel encoding: {label_encoding}")

    print("\n--- Embeddings ---")
    client, embedding_model = build_embedding_client()
    X = load_or_compute_embeddings(client, prompts, cache_dir, embedding_model)
    print(f"  Shape: {X.shape}")

    clf = LogisticRegression(
        max_iter=1000,
        C=1.0,
        solver="lbfgs",
        class_weight="balanced",
    )

    print("\n--- Cross-validation ---")
    cv = StratifiedKFold(
        n_splits=_cross_validation_splits(labels),
        shuffle=True,
        random_state=42,
    )
    y_pred = cross_val_predict(clf, X, y, cv=cv)

    classes = sorted(set(labels))

    print("\nClassification Report:")
    print(classification_report(y, y_pred, target_names=classes))

    print("Confusion Matrix:")
    cm = confusion_matrix(y, y_pred)
    print(f"{'':>16}", end="")
    for name in classes:
        print(f"{name:>14}", end="")
    print()
    for i, name in enumerate(classes):
        print(f"{name:>16}", end="")
        for j in range(len(classes)):
            print(f"{cm[i][j]:>14}", end="")
        print()

    print("\n--- Training final model ---")
    clf.fit(X, y)

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "agentic_classifier.pkl"
    class_distribution = {label: labels.count(label) for label in sorted(set(labels))}
    with open(model_path, "wb") as f:
        pickle.dump(
            {
                "classifier": clf,
                "label_encoder": label_encoder,
                "embedding_model": embedding_model,
                "embedding_dim": EMBEDDING_DIM,
                "training_size": len(prompts),
                "class_distribution": class_distribution,
                "label_type": "agentic",
            },
            f,
        )

    print(f"\nModel saved to {model_path}")
    print(f"  Size: {model_path.stat().st_size / 1024:.1f} KB")

    print("\n--- Sanity check ---")
    sanity_prompts = [
        "Open the repo and update the config file",
        "Explain the architecture and tradeoffs",
    ]
    sanity_embeddings = get_embeddings(client, sanity_prompts, model=embedding_model)
    predictions = clf.predict(sanity_embeddings)
    probabilities = clf.predict_proba(sanity_embeddings)
    for prompt, pred_idx, proba in zip(
        sanity_prompts, predictions, probabilities, strict=False
    ):
        label = label_encoder.inverse_transform([pred_idx])[0]
        confidence = float(proba[pred_idx])
        print(f"  [{label}] (conf={confidence:.3f}) {prompt[:70]}")

    return model_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train kani AGENTIC classifier")
    parser.add_argument(
        "--data",
        default="data/agentic_training_prompts.json",
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
        train_agentic_classifier(
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
