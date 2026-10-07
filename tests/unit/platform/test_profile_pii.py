"""FR-M6: value-pattern verification for classification.

The acceptance criteria that matter here are the anti-false-positive ones: a
UUID primary key must not be graded sensitive, and weak evidence must land in
review rather than being published (QC4 / AC-6.1 / AC-6.3).
"""
from __future__ import annotations

import pytest

from local_ingestion.platform.profile.pii import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    evaluate_column,
    is_low_cardinality,
)


def test_phone_numbers_are_detected_with_evidence():
    verdict = evaluate_column("contact", ["13800138000"] * 10)
    assert verdict.grade == 3
    assert "value:phone_cn" in verdict.evidence
    assert not verdict.needs_review


def test_emails_are_detected():
    verdict = evaluate_column("contact", ["a@b.com"] * 10)
    assert verdict.grade == 3
    assert "value:email" in verdict.evidence


def test_id_card_outranks_bank_card():
    """An 18-digit id also matches the 16–19 digit bank pattern; id must win."""
    verdict = evaluate_column("id_no", ["110101199003071234"] * 10)
    assert "value:id_card_cn" in verdict.evidence
    assert verdict.grade == 4


def test_uuid_primary_key_is_not_graded_sensitive():
    """AC-6.1: a UUID column must not come back sensitive.

    It is high-cardinality, so it is not skipped — it simply matches nothing.
    """
    uuids = [f"3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6a{i:02d}" for i in range(50)]
    verdict = evaluate_column("id", uuids, distinct_count=50, row_count=50)
    assert verdict.grade == 1
    assert verdict.confidence == 0.0
    assert not verdict.evidence


def test_enum_like_column_is_skipped():
    """Low cardinality → skip the scan entirely (FR-M6.4)."""
    verdict = evaluate_column("status", ["A", "B"], distinct_count=2, row_count=10_000)
    assert verdict.skipped
    assert verdict.skip_reason == "low_cardinality"


def test_low_cardinality_detection_ratio():
    assert is_low_cardinality(5, 10_000) is True
    assert is_low_cardinality(9_000, 10_000) is False
    # Unknown cardinality must not suppress detection.
    assert is_low_cardinality(None, 10_000) is False


def test_name_hit_without_samples_goes_to_review():
    """A suggestive name and no values is weak evidence, not a published grade."""
    verdict = evaluate_column("user_phone", [])
    assert "name" in verdict.evidence
    assert verdict.needs_review


def test_weak_value_evidence_goes_to_review():
    """One phone number among 100 values must not be published as fact."""
    values = ["13800138000"] + [f"note-{i}" for i in range(99)]
    verdict = evaluate_column("col_7", values)
    assert verdict.confidence < DEFAULT_CONFIDENCE_THRESHOLD or verdict.needs_review


def test_name_hit_alone_can_publish_when_above_threshold():
    verdict = evaluate_column("user_phone", [], name_hit=True)
    # name bonus (0.5) exceeds the default threshold, so it publishes...
    assert verdict.confidence >= DEFAULT_CONFIDENCE_THRESHOLD
    # ...but carries only name evidence, which review UI can filter on.
    assert verdict.evidence == ["name"]


def test_name_plus_value_confidence_is_capped():
    verdict = evaluate_column("user_phone", ["13800138000"] * 10, name_hit=True)
    assert verdict.confidence <= 1.0
    assert set(verdict.evidence) == {"name", "value:phone_cn"}


def test_no_signal_is_not_flagged_for_review():
    """An ordinary column should produce neither a grade nor a review item."""
    verdict = evaluate_column("product_code", ["A-100", "A-101"])
    assert verdict.grade == 1
    assert verdict.evidence == []
    assert not verdict.needs_review


def test_null_and_empty_values_are_ignored():
    verdict = evaluate_column("contact", [None, "", "13800138000", "13800138001"])
    assert "value:phone_cn" in verdict.evidence


def test_verdict_serialises_for_storage():
    verdict = evaluate_column("contact", ["13800138000"])
    payload = verdict.as_dict()
    assert payload["grade"] == 3
    assert isinstance(payload["evidence"], list)
    assert "confidence" in payload
