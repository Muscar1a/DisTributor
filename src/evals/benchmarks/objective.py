"""Adapters and deterministic graders for the first objective benchmarks."""

from __future__ import annotations

import os
import re
from typing import Any

CHOICES = "ABCDEFGHIJ"


def _tier_from_math_level(level: Any) -> str:
    match = re.search(r"([1-5])", str(level))
    value = int(match.group(1)) if match else 5
    return "T1" if value <= 2 else "T2" if value <= 4 else "T3"


def normalize_math500(row: dict[str, Any], index: int) -> dict[str, Any]:
    problem = str(row["problem"]).strip()
    answer = str(row.get("answer") or extract_boxed(str(row["solution"]))).strip()
    if not answer:
        raise ValueError(f"MATH-500 row {index} has no extractable answer")
    level = row.get("level", 5)
    return {
        "id": f"math500-{row.get('unique_id', index)}",
        "benchmark": "MATH-500",
        "prompt": problem + "\n\nGive the final answer inside \\boxed{}.",
        "reference_answer": answer,
        "grader": "math_verify_v1",
        "quality_type": "objective",
        "expected_tier": _tier_from_math_level(level),
        "category": "math_reasoning",
        "language": "en",
        "metadata": {"subject": row.get("subject"), "level": level},
    }


def normalize_mmlu_pro(row: dict[str, Any], index: int) -> dict[str, Any]:
    options = list(row["options"])
    if not 2 <= len(options) <= len(CHOICES):
        raise ValueError(f"MMLU-Pro row {index} has {len(options)} options")
    answer_index = row.get("answer_index", row.get("answer"))
    if isinstance(answer_index, str) and answer_index.upper() in CHOICES:
        answer = answer_index.upper()
    else:
        answer = CHOICES[int(answer_index)]
    formatted = "\n".join(f"{CHOICES[i]}. {option}" for i, option in enumerate(options))
    question_id = row.get("question_id", index)
    return {
        "id": f"mmlu-pro-{question_id}",
        "benchmark": "MMLU-Pro",
        "prompt": f"{str(row['question']).strip()}\n\n{formatted}\n\nAnswer with only the option letter.",
        "reference_answer": answer,
        "grader": "multiple_choice_v1",
        "quality_type": "objective",
        "expected_tier": "T3",
        "category": str(row.get("category") or "multitask"),
        "language": "en",
        "metadata": {"source": row.get("src"), "answer_index": answer_index},
    }


def extract_boxed(text: str) -> str:
    """Return the final balanced \boxed{...} payload, including nested braces."""
    marker = "\\boxed{"
    start = text.rfind(marker)
    if start < 0:
        return ""
    cursor = start + len(marker)
    depth = 1
    for index in range(cursor, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[cursor:index].strip()
    return ""


def normalize_math_answer(value: str) -> str:
    normalized = extract_boxed(value) or value
    normalized = normalized.strip().strip("$")
    normalized = normalized.replace("\\left", "").replace("\\right", "")
    normalized = normalized.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    normalized = normalized.replace("\\,", "").replace(" ", "")
    normalized = normalized.rstrip(". ")
    return normalized.casefold()


def verify_math_answer(response: str, reference_answer: str) -> bool:
    """Compare MATH answers symbolically with the pinned Hugging Face verifier."""
    try:
        from math_verify import parse, verify
        from math_verify.parser import ExprExtractionConfig, LatexExtractionConfig
    except ImportError as exc:
        raise RuntimeError("Install src/evals/requirements.txt before grading MATH responses") from exc

    # Currency inside a box (for example ``\boxed{\$78}``) is a unit marker,
    # not a LaTeX math delimiter. Math-Verify handles ordinary units itself.
    response = response.replace("\\$", "")
    reference_answer = reference_answer.replace("\\$", "")
    timeout_seconds = None if os.name == "nt" else 5
    gold = parse(
        reference_answer,
        extraction_config=[LatexExtractionConfig(), ExprExtractionConfig()],
        parsing_timeout=timeout_seconds,
    )
    prediction = parse(
        response,
        extraction_config=[
            LatexExtractionConfig(boxed_match_priority=0),
            ExprExtractionConfig(),
        ],
        parsing_timeout=timeout_seconds,
    )
    return bool(verify(gold, prediction, timeout_seconds=timeout_seconds))


def extract_choice(value: str) -> str:
    stripped = value.strip().upper()
    if stripped in CHOICES:
        return stripped
    matches = re.findall(r"(?:ANSWER|OPTION|CHOICE)?\s*[:=]?\s*\(?([A-J])\)?\b", stripped)
    return matches[-1] if matches else ""


def grade_response(grader: str, response: str, reference_answer: str) -> bool:
    if grader == "multiple_choice_v1":
        return extract_choice(response) == reference_answer.strip().upper()
    if grader == "math_normalized_exact_v1":
        return normalize_math_answer(response) == normalize_math_answer(reference_answer)
    if grader == "math_verify_v1":
        return verify_math_answer(response, reference_answer)
    raise ValueError(f"Unknown grader {grader!r}")


def extract_python_code(response: str) -> str:
    """Strip Markdown fences while preserving the model's Python source."""
    fenced = re.findall(r"```(?:python)?\s*\n(.*?)```", response, flags=re.IGNORECASE | re.DOTALL)
    return (fenced[-1] if fenced else response).strip()
