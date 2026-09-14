import json

import pytest

from src.evals.build_multiturn import (
    ADVERSARIAL_CASES,
    DEFAULT_OUTPUT,
    TEMPLATES,
    harvest_wildchat,
    template_records,
    validate_conversations,
    wildchat_multiturn_candidate,
)


def _wildchat_row(*user_turns: str, language: str = "English", toxic: bool = False, record_id: str = "b" * 32) -> dict:
    conversation = []
    for content in user_turns:
        conversation.append({"role": "user", "content": content, "turn_identifier": 1})
        conversation.append({"role": "assistant", "content": "ok", "turn_identifier": 1})
    return {"language": language, "toxic": toxic, "conversation_hash": record_id, "conversation": conversation}


def test_templates_are_valid_and_cover_all_adversarial_cases():
    records = template_records()
    validate_conversations(records)
    assert len(records) == 18
    assert {record["language"] for record in records} == {"vi", "en"}
    covered = {record["adversarial_case"] for record in records if record["adversarial_case"] is not None}
    assert covered == set(ADVERSARIAL_CASES)


def test_validator_rejects_bad_labels():
    records = template_records()
    records[0]["turns"][0]["expected_intent"] = "continue"  # first turn must be new_task
    with pytest.raises(ValueError, match="first turn"):
        validate_conversations(records)

    records = template_records()
    records[1]["turns"][1]["expected_tier"] = "T4"
    with pytest.raises(ValueError, match="unknown tier"):
        validate_conversations(records)

    records = template_records()
    records[1]["id"] = records[0]["id"]
    with pytest.raises(ValueError, match="duplicate"):
        validate_conversations(records)

    records = template_records()
    correction = next(
        turn for record in records for turn in record["turns"] if turn["expected_intent"] == "correction"
    )
    correction["user"] = "please change it"  # no artifact, no correction phrase
    with pytest.raises(ValueError, match="no evidence"):
        validate_conversations(records)


def test_wildchat_candidate_filters():
    good = _wildchat_row("write a python function", "it fails with TypeError", "now add tests")
    candidate = wildchat_multiturn_candidate(good)
    assert candidate is not None
    assert candidate["source"] == "wildchat"
    assert len(candidate["turns"]) == 3
    assert all(turn["expected_tier"] is None for turn in candidate["turns"])

    assert wildchat_multiturn_candidate(_wildchat_row("def f(): pass", "fix bug")) is None  # <3 turns
    assert wildchat_multiturn_candidate(_wildchat_row("hi", "how are you", "tell me a joke")) is None  # no code
    assert (
        wildchat_multiturn_candidate(_wildchat_row("import os", "email me at a@b.com", "thanks")) is None
    )  # PII
    assert wildchat_multiturn_candidate(_wildchat_row("import os", "b", "c", toxic=True)) is None


def test_harvest_dedups_and_raises_when_stream_too_short():
    row = _wildchat_row("write a python function", "it fails", "add tests")
    assert len(harvest_wildchat([row, row], limit=1)) == 1
    with pytest.raises(ValueError, match="stream ended"):
        harvest_wildchat([row, row], limit=2)


def test_committed_dataset_matches_templates():
    lines = DEFAULT_OUTPUT.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line]
    validate_conversations(records)
    committed_templates = [record for record in records if record["source"] == "template"]
    assert committed_templates == TEMPLATES
