"""Build distilled feature training datasets from kani routing logs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Protocol, TypedDict

import httpx

from kani.classification_context import build_classification_input
from kani.config import load_config
from kani.dirs import data_dir, log_dir
from kani.scorer import SEMANTIC_DIMENSIONS

VALID_DIMENSION_LABELS = {"low", "medium", "high"}


class FeatureAnnotator(Protocol):
    def annotate(self, prompt: str) -> dict[str, str] | None: ...


class DistilledFeatureExample(TypedDict):
    prompt: str
    tokenCount: int
    codePresence: str
    reasoningMarkers: str
    technicalTerms: str
    creativeMarkers: str
    simpleIndicators: str
    multiStepPatterns: str
    questionComplexity: str
    imperativeVerbs: str
    constraintCount: str
    outputFormat: str
    referenceComplexity: str
    negationComplexity: str
    domainSpecificity: str
    agenticTask: str
    timestamp: str | None
    source: str


class LLMFeatureAnnotator:
    """Offline annotator that labels semantic dimensions with an LLM."""

    _PROMPT_TEMPLATE = (
        "You are labeling prompts for routing distillation. "
        "Return JSON object only with exactly these keys: "
        f"{', '.join(SEMANTIC_DIMENSIONS)}. "
        "Each value must be one of: low, medium, high.\n\n"
        "Prompt:\n{prompt}"
    )

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        cfg = None
        resolved = None
        try:
            loaded = load_config()
            cfg = loaded.feature_annotator
            resolved = loaded.feature_annotator_resolved()
        except Exception:
            pass

        self.model = (
            model
            or os.environ.get("KANI_LLM_ANNOTATOR_MODEL")
            or (cfg.model if cfg else None)
            or "google/gemini-2.5-flash-lite"
        )
        self.base_url = (
            base_url
            or os.environ.get("KANI_LLM_ANNOTATOR_BASE_URL")
            or (resolved[0] if resolved else None)
            or "https://openrouter.ai/api/v1"
        ).rstrip("/")
        self.api_key = (
            api_key
            or os.environ.get("KANI_LLM_ANNOTATOR_API_KEY")
            or (resolved[1] if resolved else None)
            or os.environ.get("OPENROUTER_API_KEY", "")
        )

    def annotate(self, prompt: str) -> dict[str, str] | None:
        if not self.api_key:
            raise RuntimeError(
                "KANI_LLM_ANNOTATOR_API_KEY or OPENROUTER_API_KEY is required"
            )

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": self._PROMPT_TEMPLATE.format(prompt=prompt[:2000]),
                    }
                ],
                "temperature": 0.0,
                "max_tokens": 300,
                "response_format": {"type": "json_object"},
            },
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()
        content = (
            data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        )
        if not content:
            return None
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return None

        labels: dict[str, str] = {}
        for dim in SEMANTIC_DIMENSIONS:
            value = str(parsed.get(dim, "")).strip().lower()
            if value not in VALID_DIMENSION_LABELS:
                return None
            labels[dim] = value
        return labels


def deterministic_token_count(prompt: str) -> int:
    return max(1, len(prompt.split()))


def load_routing_records(paths: list[Path]) -> list[dict[str, Any]]:
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


def _validate_semantic_labels(labels: dict[str, str]) -> bool:
    for dim in SEMANTIC_DIMENSIONS:
        value = labels.get(dim)
        if value not in VALID_DIMENSION_LABELS:
            return False
    return True


def _extract_semantic_labels_from_record(
    record: dict[str, Any],
) -> dict[str, str] | None:
    signals = record.get("signals")
    if not isinstance(signals, dict):
        return None

    raw_labels = signals.get("semanticLabels")
    if not isinstance(raw_labels, dict):
        return None

    labels: dict[str, str] = {
        key: str(value).strip().lower() for key, value in raw_labels.items()
    }
    if not _validate_semantic_labels(labels):
        return None
    return {dim: labels[dim] for dim in SEMANTIC_DIMENSIONS}


def _classification_prompt_from_record(record: dict[str, Any]) -> str:
    context = record.get("classification_context")
    if isinstance(context, dict):
        context_text = str(context.get("text") or "").strip()
        if context_text:
            return context_text

    messages = record.get("messages")
    if isinstance(messages, list):
        try:
            return build_classification_input(messages).text
        except Exception:
            pass

    return str(record.get("prompt") or record.get("prompt_preview") or "").strip()


def extract_distilled_feature_examples(
    records: list[dict[str, Any]],
    *,
    annotator: FeatureAnnotator | None = None,
) -> list[DistilledFeatureExample]:
    latest_by_prompt: dict[str, DistilledFeatureExample] = {}

    for record in records:
        prompt = _classification_prompt_from_record(record)
        if not prompt:
            continue

        labels = _extract_semantic_labels_from_record(record)
        source = "log"
        if labels is None and annotator is not None:
            labels = annotator.annotate(prompt)
            source = "annotated"

        if labels is None:
            continue

        if not _validate_semantic_labels(labels):
            continue

        example: DistilledFeatureExample = {
            "prompt": prompt,
            "tokenCount": deterministic_token_count(prompt),
            "codePresence": labels["codePresence"],
            "reasoningMarkers": labels["reasoningMarkers"],
            "technicalTerms": labels["technicalTerms"],
            "creativeMarkers": labels["creativeMarkers"],
            "simpleIndicators": labels["simpleIndicators"],
            "multiStepPatterns": labels["multiStepPatterns"],
            "questionComplexity": labels["questionComplexity"],
            "imperativeVerbs": labels["imperativeVerbs"],
            "constraintCount": labels["constraintCount"],
            "outputFormat": labels["outputFormat"],
            "referenceComplexity": labels["referenceComplexity"],
            "negationComplexity": labels["negationComplexity"],
            "domainSpecificity": labels["domainSpecificity"],
            "agenticTask": labels["agenticTask"],
            "timestamp": str(record.get("timestamp"))
            if record.get("timestamp")
            else None,
            "source": source,
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


def build_feature_dataset(
    log_paths: list[Path],
    output_path: Path,
    *,
    annotator: FeatureAnnotator | None = None,
) -> list[DistilledFeatureExample]:
    examples = extract_distilled_feature_examples(
        load_routing_records(log_paths), annotator=annotator
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return examples


def resolve_log_paths(
    paths: list[str], *, log_directory: Path, pattern: str
) -> list[Path]:
    if paths:
        return [Path(path).expanduser() for path in paths]
    return sorted(log_directory.expanduser().glob(pattern))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build distilled semantic feature dataset from routing logs"
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
        default=str(data_dir() / "distilled_feature_dataset.json"),
        help="Output JSON dataset path",
    )
    parser.add_argument(
        "--annotate-missing",
        action="store_true",
        help="Use LLM annotation for records missing semantic labels",
    )
    parser.add_argument("--model", help="LLM model for annotation")
    parser.add_argument("--base-url", help="LLM base URL for annotation")
    parser.add_argument("--api-key", help="LLM API key for annotation")
    args = parser.parse_args(argv)

    log_paths = resolve_log_paths(
        args.paths,
        log_directory=Path(args.log_dir),
        pattern=args.glob,
    )
    if not log_paths:
        parser.error("No routing log files found")

    annotator = None
    if args.annotate_missing:
        annotator = LLMFeatureAnnotator(
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
        )

    output_path = Path(args.output).expanduser()
    examples = build_feature_dataset(log_paths, output_path, annotator=annotator)

    print(f"Loaded {len(log_paths)} log files")
    print(f"Wrote {len(examples)} distilled feature examples to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
