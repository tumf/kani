"""Build training datasets from kani routing logs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, TypedDict

from kani.dirs import data_dir, log_dir


class AgenticExample(TypedDict):
    prompt: str
    label: str
    agentic_score: float
    tier: str
    profile: str | None
    timestamp: str | None


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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return examples


def resolve_log_paths(
    paths: list[str], *, log_directory: Path, pattern: str
) -> list[Path]:
    """Resolve explicit log files or discover them from *log_directory*."""
    if paths:
        return [Path(path).expanduser() for path in paths]
    return sorted(log_directory.expanduser().glob(pattern))


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
