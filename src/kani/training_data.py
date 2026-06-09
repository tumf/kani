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

SEMANTIC_DIMENSION_CALIBRATION: dict[str, dict[str, str]] = {
    "codePresence": {
        "low": "No code, stack traces, commands, or implementation-specific syntax.",
        "medium": "Mentions code, tools, commands, errors, or files without requiring code-heavy work.",
        "high": "Contains code blocks, tracebacks, concrete implementation details, or asks to write/debug code.",
    },
    "reasoningMarkers": {
        "low": "No explicit request to explain, compare, prove, analyze, or find causes.",
        "medium": "Asks for an explanation, comparison, or analysis with limited depth.",
        "high": "Requires deep reasoning such as proof, root-cause analysis, trade-off analysis, or multi-factor diagnosis.",
    },
    "technicalTerms": {
        "low": "Uses general language with little or no software, API, config, or infrastructure terminology.",
        "medium": "Includes a few technical terms or one concrete tool/API/configuration topic.",
        "high": "Dense technical vocabulary across APIs, frameworks, configs, infrastructure, or ML/routing concepts.",
    },
    "creativeMarkers": {
        "low": "No request to draft, design, write creative copy, or generate narrative content.",
        "medium": "Asks for a short draft, wording, design idea, or light creative transformation.",
        "high": "Requires substantial creative generation, brand/design direction, story, copy, or stylistic iteration.",
    },
    "simpleIndicators": {
        "low": "Not a short greeting, acknowledgement, yes/no answer, or trivial conversational turn.",
        "medium": "Mostly simple but includes a small concrete request or context.",
        "high": "A very short greeting, acknowledgement, thanks, confirmation, or simple yes/no-style prompt.",
    },
    "multiStepPatterns": {
        "low": "Single-step request with no ordered sequence or dependency between actions.",
        "medium": "Two or more implied steps, a short procedure, or one follow-up dependency.",
        "high": "Explicit multi-stage workflow with ordered steps, verification, iteration, or coordination.",
    },
    "questionComplexity": {
        "low": "No question or a direct factual/simple question.",
        "medium": "One substantive question or a question needing some context synthesis.",
        "high": "Multiple questions, conditional questions, or a broad inquiry requiring structured reasoning.",
    },
    "imperativeVerbs": {
        "low": "No action command or only passive information-seeking wording.",
        "medium": "One clear action verb such as add, update, check, run, summarize, or explain.",
        "high": "Multiple action commands or direct instructions to implement, fix, test, investigate, and verify.",
    },
    "constraintCount": {
        "low": "No explicit constraints, prohibitions, required formats, or must/never conditions.",
        "medium": "One or two constraints such as required output, scope, or forbidden behavior.",
        "high": "Several strict constraints, acceptance criteria, forbidden actions, or compliance requirements.",
    },
    "outputFormat": {
        "low": "No requested structure or format.",
        "medium": "Requests a common format such as JSON, markdown, table, list, or concise bullets.",
        "high": "Requires an exact schema, machine-readable shape, strict keys, or multiple formatting rules.",
    },
    "referenceComplexity": {
        "low": "No external references, file paths, URLs, logs, or prior artifacts.",
        "medium": "One or two references such as a URL, file path, issue, config, or log snippet.",
        "high": "Several references or requires cross-reading files, URLs, logs, specs, or previous context.",
    },
    "negationComplexity": {
        "low": "No negation, exception, or forbidden behavior.",
        "medium": "One explicit not/without/never condition or simple exception.",
        "high": "Multiple prohibitions, nuanced exceptions, or safety constraints that affect execution.",
    },
    "domainSpecificity": {
        "low": "General-purpose request that does not depend on a specialized domain.",
        "medium": "Depends on one recognizable domain such as Python, CLI routing, config, or testing.",
        "high": "Requires specialized project/domain knowledge across routing, providers, proxy behavior, or ML features.",
    },
    "agenticTask": {
        "low": "Only asks for an answer or explanation; no tool use, repository change, or verification expected.",
        "medium": "Asks the assistant to perform a bounded action such as inspect, run, update, or produce an artifact.",
        "high": "Requires autonomous implementation, debugging, multi-step tool use, verification, or repository modification.",
    },
}


def _semantic_dimension_calibration_text() -> str:
    missing = set(SEMANTIC_DIMENSIONS) - set(SEMANTIC_DIMENSION_CALIBRATION)
    extra = set(SEMANTIC_DIMENSION_CALIBRATION) - set(SEMANTIC_DIMENSIONS)
    if missing or extra:
        raise ValueError(
            "Semantic dimension calibration must exactly match SEMANTIC_DIMENSIONS; "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )

    lines = ["Calibration guidance:"]
    for dim in SEMANTIC_DIMENSIONS:
        labels = SEMANTIC_DIMENSION_CALIBRATION[dim]
        invalid_labels = set(labels) - VALID_DIMENSION_LABELS
        missing_labels = VALID_DIMENSION_LABELS - set(labels)
        if invalid_labels or missing_labels:
            raise ValueError(
                "Semantic dimension calibration labels must be low, medium, high; "
                f"dimension={dim} missing={sorted(missing_labels)} "
                f"invalid={sorted(invalid_labels)}"
            )
        lines.append(f"- {dim}:")
        for label in ("low", "medium", "high"):
            lines.append(f"  - {label}: {labels[label]}")
    return "\n".join(lines)


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
        "Each value must be one of: low, medium, high. "
        "Do not include any explanation or markdown.\n\n"
        f"{_semantic_dimension_calibration_text()}\n\n"
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

        try:
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
                            "content": self._PROMPT_TEMPLATE.format(
                                prompt=prompt[:2000]
                            ),
                        }
                    ],
                    "temperature": 0.0,
                    "max_tokens": 300,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            return None

        content = (
            data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        )
        if not content:
            return None
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return None
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
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
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


def _make_example(
    prompt: str,
    labels: dict[str, str],
    record: dict[str, Any],
    source: str,
) -> DistilledFeatureExample:
    return {
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
        "timestamp": str(record.get("timestamp")) if record.get("timestamp") else None,
        "source": source,
    }


def _save_examples(
    latest_by_prompt: dict[str, DistilledFeatureExample],
    output_path: Path,
) -> list[DistilledFeatureExample]:
    examples = sorted(
        latest_by_prompt.values(),
        key=lambda item: ((item["timestamp"] or ""), item["prompt"]),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return examples


_CHECKPOINT_INTERVAL = 1


def extract_distilled_feature_examples(
    records: list[dict[str, Any]],
    *,
    annotator: FeatureAnnotator | None = None,
    checkpoint_path: Path | None = None,
) -> list[DistilledFeatureExample]:
    latest_by_prompt: dict[str, DistilledFeatureExample] = {}

    if checkpoint_path and checkpoint_path.exists():
        try:
            existing = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                for item in existing:
                    prompt = item.get("prompt", "")
                    if prompt:
                        latest_by_prompt[prompt] = item
                print(f"  Resumed {len(latest_by_prompt)} examples from checkpoint")
        except (json.JSONDecodeError, OSError):
            pass

    annotated_since_save = 0
    skipped = 0
    total = len(records)

    for idx, record in enumerate(records, 1):
        prompt = _classification_prompt_from_record(record)
        if not prompt:
            skipped += 1
            print(f"  [{idx}/{total}] skip: empty prompt")
            continue

        labels = _extract_semantic_labels_from_record(record)
        source = "log"
        if labels is None and annotator is not None:
            if prompt in latest_by_prompt:
                skipped += 1
                print(f"  [{idx}/{total}] skip: duplicate")
                continue
            print(f"  [{idx}/{total}] annotate: {prompt[:120].replace(chr(10), ' ')}")
            labels = annotator.annotate(prompt)
            source = "annotated"
            annotated_since_save += 1

        if labels is None:
            skipped += 1
            print(f"  [{idx}/{total}] skip: no labels returned")
            continue

        if not _validate_semantic_labels(labels):
            continue

        example = _make_example(prompt, labels, record, source)

        current = latest_by_prompt.get(prompt)
        if current is None or (example["timestamp"] or "") >= (
            current["timestamp"] or ""
        ):
            latest_by_prompt[prompt] = example

        if checkpoint_path and annotated_since_save >= _CHECKPOINT_INTERVAL:
            _save_examples(latest_by_prompt, checkpoint_path)
            print(
                f"  [{idx}/{total}] checkpoint: {len(latest_by_prompt)} examples saved"
            )
            annotated_since_save = 0

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
        load_routing_records(log_paths),
        annotator=annotator,
        checkpoint_path=output_path if annotator else None,
    )
    _save_examples(
        {e["prompt"]: e for e in examples},
        output_path,
    )
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
