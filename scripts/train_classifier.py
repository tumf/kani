#!/usr/bin/env python3
"""Train the embedding-based tier classifier for kani.

Usage:
    uv run python scripts/train_classifier.py [--data data/training_prompts.json] [--output models/]

Steps:
1. Load labeled prompts from JSON
2. Get embeddings via OpenAI text-embedding-3-small
3. Train LogisticRegression classifier
4. Evaluate with cross-validation
5. Save model + label encoder as pickle
"""

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
BATCH_SIZE = 100  # OpenAI allows up to 2048 inputs per request


def get_embeddings(
    client: OpenAI, texts: list[str], model: str = EMBEDDING_MODEL
) -> np.ndarray:
    """Get embeddings for a list of texts, batched."""
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        print(f"  Embedding batch {i // BATCH_SIZE + 1}/{(len(texts) - 1) // BATCH_SIZE + 1} ({len(batch)} items)...")
        resp = client.embeddings.create(input=batch, model=model)
        for item in resp.data:
            all_embeddings.append(item.embedding)
        if i + BATCH_SIZE < len(texts):
            time.sleep(0.2)  # Rate limit courtesy
    return np.array(all_embeddings, dtype=np.float32)


def load_or_compute_embeddings(
    client: OpenAI,
    texts: list[str],
    cache_path: Path,
    model: str = EMBEDDING_MODEL,
) -> np.ndarray:
    """Load embeddings from cache or compute them."""
    # Cache key based on content hash
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Train kani tier classifier")
    parser.add_argument("--data", default="data/training_prompts.json", help="Training data JSON")
    parser.add_argument("--output", default="models", help="Output directory for model files")
    parser.add_argument("--cache", default="data/cache", help="Embedding cache directory")
    args = parser.parse_args()

    # Load data
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"Error: {data_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(data_path) as f:
        dataset = json.load(f)

    prompts = [d["prompt"] for d in dataset]
    labels = [d["tier"] for d in dataset]
    print(f"Loaded {len(prompts)} prompts")
    for tier in sorted(set(labels)):
        print(f"  {tier}: {labels.count(tier)}")

    # Encode labels
    le = LabelEncoder()
    y = le.fit_transform(labels)
    print(f"\nLabel encoding: {dict(zip(le.classes_, le.transform(le.classes_)))}")

    # Get embeddings
    print("\n--- Embeddings ---")
    # Support OpenRouter as an alternative embedding provider
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    base_url = None
    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        base_url = "https://openrouter.ai/api/v1"
        print("  Using OpenRouter for embeddings")
    if not api_key:
        print("Error: Set OPENAI_API_KEY or OPENROUTER_API_KEY", file=sys.stderr)
        sys.exit(1)
    embedding_model = EMBEDDING_MODEL_OPENROUTER if base_url else EMBEDDING_MODEL
    client = OpenAI(api_key=api_key, base_url=base_url)
    X = load_or_compute_embeddings(client, prompts, Path(args.cache), embedding_model)
    print(f"  Shape: {X.shape}")

    # Train with cross-validation
    print("\n--- Cross-validation ---")
    clf = LogisticRegression(
        max_iter=1000,
        C=1.0,
        solver="lbfgs",
        class_weight="balanced",  # Handle class imbalance
    )

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    y_pred = cross_val_predict(clf, X, y, cv=cv)

    print("\nClassification Report:")
    print(classification_report(y, y_pred, target_names=le.classes_))

    print("Confusion Matrix:")
    cm = confusion_matrix(y, y_pred)
    # Pretty print
    print(f"{'':>12}", end="")
    for name in le.classes_:
        print(f"{name:>10}", end="")
    print()
    for i, name in enumerate(le.classes_):
        print(f"{name:>12}", end="")
        for j in range(len(le.classes_)):
            print(f"{cm[i][j]:>10}", end="")
        print()

    # Train final model on all data
    print("\n--- Training final model ---")
    clf.fit(X, y)

    # Save model
    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    model_file = output_path / "tier_classifier.pkl"
    with open(model_file, "wb") as f:
        pickle.dump(
            {
                "classifier": clf,
                "label_encoder": le,
                "embedding_model": EMBEDDING_MODEL,
                "embedding_dim": EMBEDDING_DIM,
                "training_size": len(prompts),
                "class_distribution": dict(zip(*np.unique(labels, return_counts=True))),
            },
            f,
        )

    print(f"\nModel saved to {model_file}")
    print(f"  Size: {model_file.stat().st_size / 1024:.1f} KB")

    # Quick sanity check
    print("\n--- Sanity check ---")
    test_prompts = [
        "hello",
        "write a Python function to sort a list",
        "design a distributed database with CRDT support and multi-region failover",
        "prove that P ≠ NP implies one-way functions exist, step by step",
    ]
    test_embeddings = get_embeddings(client, test_prompts, model=embedding_model)
    predictions = clf.predict(test_embeddings)
    probas = clf.predict_proba(test_embeddings)

    for prompt, pred_idx, proba in zip(test_prompts, predictions, probas):
        tier = le.inverse_transform([pred_idx])[0]
        conf = proba[pred_idx]
        print(f"  [{tier}] (conf={conf:.3f}) {prompt[:70]}")


if __name__ == "__main__":
    main()
