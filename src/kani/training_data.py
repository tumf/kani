"""Build training datasets from kani routing logs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

from kani.dirs import data_dir, log_dir


class AgenticExample(TypedDict):
    prompt: str
    label: str
    agentic_score: float
    tier: str
    profile: str | None
    timestamp: str | None


class BootstrapAgenticExample(TypedDict):
    prompt: str
    label: str
    source: str


VALID_AGENTIC_LABELS = {"AGENTIC", "NON_AGENTIC"}

DEFAULT_BOOTSTRAP_SEED_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("Open the repo and update the config file", "AGENTIC"),
    ("Run the test suite and fix failures", "AGENTIC"),
    ("Create the pull request with these changes", "AGENTIC"),
    ("Inspect the logs and restart the service", "AGENTIC"),
    ("Explain the architecture and tradeoffs", "NON_AGENTIC"),
    ("Summarize this article", "NON_AGENTIC"),
    ("What does this error mean?", "NON_AGENTIC"),
    ("この文章を要約して", "NON_AGENTIC"),
)

DEFAULT_BOOTSTRAP_EXCLUDED_PROMPTS = frozenset(
    {
        ".",
        "y",
        "n",
        "ok",
        "plz",
        "hello",
    }
)


def _normalize_agentic_label(label: str) -> str:
    normalized = str(label).strip().upper()
    if normalized not in VALID_AGENTIC_LABELS:
        raise ValueError(f"Unsupported agentic label: {label}")
    return normalized


def _normalize_bootstrap_examples(
    examples: list[dict[str, str]] | None,
    *,
    source: str,
) -> list[BootstrapAgenticExample]:
    if not examples:
        return []

    normalized: list[BootstrapAgenticExample] = []
    for item in examples:
        prompt = str(item.get("prompt") or "").strip()
        if not prompt:
            continue
        normalized.append(
            {
                "prompt": prompt,
                "label": _normalize_agentic_label(str(item.get("label") or "")),
                "source": source,
            }
        )
    return normalized


def _default_bootstrap_examples() -> list[BootstrapAgenticExample]:
    return [
        {"prompt": prompt, "label": label, "source": "seed"}
        for prompt, label in DEFAULT_BOOTSTRAP_SEED_EXAMPLES
    ]


def _normalize_label_overrides(
    label_overrides: dict[str, str] | None,
) -> list[BootstrapAgenticExample]:
    if not label_overrides:
        return []

    normalized: list[BootstrapAgenticExample] = []
    for prompt, label in label_overrides.items():
        prompt_text = str(prompt).strip()
        if not prompt_text:
            continue
        normalized.append(
            {
                "prompt": prompt_text,
                "label": _normalize_agentic_label(label),
                "source": "override",
            }
        )
    return normalized


def _bootstrap_prompt_candidates(
    records: list[dict[str, Any]], *, excluded_prompts: set[str]
) -> list[str]:
    prompts: list[str] = []
    seen: set[str] = set()

    for record in records:
        if record.get("profile") == "compress":
            continue

        prompt = str(record.get("prompt") or record.get("prompt_preview") or "").strip()
        if not prompt or prompt in seen or prompt in excluded_prompts:
            continue
        if prompt.startswith("[System:") or prompt.startswith("User:"):
            continue

        seen.add(prompt)
        prompts.append(prompt)

    return prompts


def _write_json_dataset(
    output_path: Path, examples: Sequence[Mapping[str, Any]]
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_routing_records(paths: list[Path]) -> list[dict[str, Any]]:
    """Load JSONL routing log records from *paths*."""
    records: list[dict[str, Any]] = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    records.append(payload)
    return records


def _label_from_signal_dict(signals: dict[str, Any]) -> str | None:
    label = signals.get("agenticLabel")
    if not isinstance(label, dict):
        return None
    raw = label.get("raw")
    if raw in {"AGENTIC", "NON_AGENTIC"}:
        return str(raw)
    return None


def _label_from_signal_names(
    record: dict[str, Any], signal_names: list[str]
) -> str | None:
    if "agenticLabel" not in signal_names:
        return None

    # Router logs may only persist the signal names, not the raw label value.
    # In that case, only infer the label when we know the binary classifier ran.
    if record.get("profile") != "agentic" or record.get("tier") != "SIMPLE":
        return None

    score = record.get("agentic_score")
    if score == 1.0:
        return "AGENTIC"
    if score == 0.0:
        return "NON_AGENTIC"
    return None


def infer_agentic_label(record: dict[str, Any]) -> str | None:
    """Infer an AGENTIC/NON_AGENTIC label from a routing log record."""
    signals = record.get("signals")
    if isinstance(signals, dict):
        label = _label_from_signal_dict(signals)
        if label is not None:
            return label
    if isinstance(signals, list):
        return _label_from_signal_names(record, [str(item) for item in signals])
    return None


def extract_agentic_examples(records: list[dict[str, Any]]) -> list[AgenticExample]:
    """Extract labeled agentic examples from routing log records.

    Deduplicates by prompt and keeps the latest record for each prompt.
    """
    latest_by_prompt: dict[str, AgenticExample] = {}

    for record in records:
        prompt = str(record.get("prompt") or record.get("prompt_preview") or "").strip()
        if not prompt:
            continue

        label = infer_agentic_label(record)
        if label is None:
            continue

        example: AgenticExample = {
            "prompt": prompt,
            "label": label,
            "agentic_score": float(record.get("agentic_score", 0.0)),
            "tier": str(record.get("tier") or ""),
            "profile": str(record.get("profile"))
            if record.get("profile") is not None
            else None,
            "timestamp": str(record.get("timestamp"))
            if record.get("timestamp") is not None
            else None,
        }

        current = latest_by_prompt.get(prompt)
        if current is None or (example["timestamp"] or "") >= (
            current["timestamp"] or ""
        ):
            latest_by_prompt[prompt] = example

    return sorted(
        latest_by_prompt.values(),
        key=lambda item: ((item["timestamp"] or ""), item["prompt"]),
    )


def build_agentic_dataset(
    log_paths: list[Path], output_path: Path
) -> list[AgenticExample]:
    """Build and persist an agentic training dataset from routing logs."""
    examples = extract_agentic_examples(load_routing_records(log_paths))
    _write_json_dataset(output_path, examples)
    return examples


def load_bootstrap_seed_examples(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Bootstrap seed file must contain a JSON list")
    return [item for item in data if isinstance(item, dict)]


def load_bootstrap_label_overrides(path: Path) -> dict[str, str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return {str(key): str(value) for key, value in data.items()}
    if isinstance(data, list):
        return {
            str(item["prompt"]): str(item["label"])
            for item in data
            if isinstance(item, dict) and "prompt" in item and "label" in item
        }
    raise ValueError("Bootstrap overrides file must contain a JSON object or list")


def load_bootstrap_excluded_prompts(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return set()
    if text.startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("Bootstrap exclude file JSON must be a list")
        return {str(item).strip() for item in data if str(item).strip()}
    return {line.strip() for line in text.splitlines() if line.strip()}


def bootstrap_agentic_dataset(
    log_paths: list[Path],
    output_path: Path,
    *,
    classifier: Any | None,
    seed_examples: list[dict[str, str]] | None = None,
    label_overrides: dict[str, str] | None = None,
    excluded_prompts: set[str] | None = None,
    default_seed_examples: list[dict[str, str]] | None = None,
    default_excluded_prompts: set[str] | None = None,
) -> list[BootstrapAgenticExample]:
    """Bootstrap an agentic dataset from explicit labels, seeds, and classifier labels."""
    records = load_routing_records(log_paths)
    merged: dict[str, BootstrapAgenticExample] = {}

    for example in extract_agentic_examples(records):
        merged[example["prompt"]] = {
            "prompt": example["prompt"],
            "label": example["label"],
            "source": "explicit",
        }

    seed_pool = (
        _default_bootstrap_examples()
        if default_seed_examples is None
        else _normalize_bootstrap_examples(default_seed_examples, source="seed")
    )
    seed_pool.extend(_normalize_bootstrap_examples(seed_examples, source="seed"))
    for example in seed_pool:
        merged.setdefault(example["prompt"], example)

    for example in _normalize_label_overrides(label_overrides):
        merged[example["prompt"]] = example

    excluded = set(DEFAULT_BOOTSTRAP_EXCLUDED_PROMPTS)
    if default_excluded_prompts is not None:
        excluded = set(default_excluded_prompts)
    if excluded_prompts:
        excluded.update(excluded_prompts)

    if classifier is not None:
        for prompt in _bootstrap_prompt_candidates(records, excluded_prompts=excluded):
            if prompt in merged:
                continue
            result = classifier.classify(prompt)
            if result is None:
                continue
            _, label = result
            merged[prompt] = {
                "prompt": prompt,
                "label": _normalize_agentic_label(label),
                "source": "classifier",
            }

    examples = sorted(merged.values(), key=lambda item: item["prompt"])
    _write_json_dataset(output_path, examples)
    return examples


def resolve_log_paths(
    paths: list[str], *, log_directory: Path, pattern: str
) -> list[Path]:
    """Resolve explicit log files or discover them from *log_directory*."""
    if paths:
        return [Path(path).expanduser() for path in paths]
    return sorted(log_directory.expanduser().glob(pattern))


def bootstrap_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap AGENTIC/NON_AGENTIC training data from routing logs"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional routing log files. If omitted, scan --log-dir with --glob.",
    )
    parser.add_argument(
        "--log-dir",
        default=str(log_dir()),
        help="Directory containing routing-*.jsonl files",
    )
    parser.add_argument(
        "--glob",
        default="routing-*.jsonl",
        help="Glob used when explicit paths are omitted",
    )
    parser.add_argument(
        "--output",
        default=str(data_dir() / "agentic_training_prompts.json"),
        help="Output JSON dataset path",
    )
    parser.add_argument(
        "--seed-file",
        help="Optional JSON list of {prompt, label} seed examples",
    )
    parser.add_argument(
        "--overrides-file",
        help="Optional JSON object/list overriding prompt labels",
    )
    parser.add_argument(
        "--exclude-file",
        help="Optional newline or JSON-list file of prompts to skip",
    )
    parser.add_argument(
        "--model",
        help="Override the cheap LLM judge model used for classifier bootstrapping",
    )
    parser.add_argument(
        "--base-url",
        help="Override the cheap LLM judge base URL used for classifier bootstrapping",
    )
    parser.add_argument(
        "--api-key",
        help="Override the cheap LLM judge API key used for classifier bootstrapping",
    )
    args = parser.parse_args(argv)

    log_paths = resolve_log_paths(
        args.paths,
        log_directory=Path(args.log_dir),
        pattern=args.glob,
    )
    if not log_paths:
        parser.error("No routing log files found")

    from kani.scorer import AgenticClassifier

    seed_examples = (
        load_bootstrap_seed_examples(Path(args.seed_file).expanduser())
        if args.seed_file
        else None
    )
    label_overrides = (
        load_bootstrap_label_overrides(Path(args.overrides_file).expanduser())
        if args.overrides_file
        else None
    )
    excluded_prompts = (
        load_bootstrap_excluded_prompts(Path(args.exclude_file).expanduser())
        if args.exclude_file
        else None
    )

    classifier = AgenticClassifier(
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
    )
    output_path = Path(args.output).expanduser()
    examples = bootstrap_agentic_dataset(
        log_paths,
        output_path,
        classifier=classifier,
        seed_examples=seed_examples,
        label_overrides=label_overrides,
        excluded_prompts=excluded_prompts,
    )

    source_counts: dict[str, int] = {}
    for item in examples:
        source_counts[item["source"]] = source_counts.get(item["source"], 0) + 1

    positives = sum(1 for item in examples if item["label"] == "AGENTIC")
    negatives = sum(1 for item in examples if item["label"] == "NON_AGENTIC")
    print(f"Loaded {len(log_paths)} log files")
    print(f"Wrote {len(examples)} bootstrapped examples to {output_path}")
    print(f"  AGENTIC: {positives}")
    print(f"  NON_AGENTIC: {negatives}")
    for source, count in sorted(source_counts.items()):
        print(f"  {source}: {count}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build AGENTIC/NON_AGENTIC training data from kani routing logs"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional routing log files. If omitted, scan --log-dir with --glob.",
    )
    parser.add_argument(
        "--log-dir",
        default=str(log_dir()),
        help="Directory containing routing-*.jsonl files",
    )
    parser.add_argument(
        "--glob",
        default="routing-*.jsonl",
        help="Glob used when explicit paths are omitted",
    )
    parser.add_argument(
        "--output",
        default=str(data_dir() / "agentic_training_prompts.json"),
        help="Output JSON dataset path",
    )
    args = parser.parse_args(argv)

    log_paths = resolve_log_paths(
        args.paths,
        log_directory=Path(args.log_dir),
        pattern=args.glob,
    )
    if not log_paths:
        parser.error("No routing log files found")

    output_path = Path(args.output).expanduser()
    examples = build_agentic_dataset(log_paths, output_path)

    positives = sum(1 for item in examples if item["label"] == "AGENTIC")
    negatives = sum(1 for item in examples if item["label"] == "NON_AGENTIC")
    print(f"Loaded {len(log_paths)} log files")
    print(f"Wrote {len(examples)} labeled examples to {output_path}")
    print(f"  AGENTIC: {positives}")
    print(f"  NON_AGENTIC: {negatives}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
