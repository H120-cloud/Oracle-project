"""
Regression suite — catalyst classifier against historical misses.

Every entry in tests/fixtures/historical_misses.json becomes one parametrized
test case. These tests pin the classifier's behavior on the IMRN and LNKS
headlines that previously slipped through and motivated this refactor.

Rules:
    - Tests with status="confirmed" MUST pass.
    - Tests with status="proposed" pass today but the user has not yet
      blessed the labels; they are still mandatory in CI to prevent
      regressions, but the PR must call them out for review.
    - Skipping a test in this file requires an explicit pytest.mark.skip
      with a written reason; CI should grep for unexplained skips.

This is the contract Priority 1 (semantic classifier) must keep satisfying.
"""

from __future__ import annotations

import pytest

from src.core.agentic.news_momentum_catalyst_classifier import classify_headline
from src.core.agentic.news_momentum_models import CatalystCategory, CatalystSubType


pytestmark = [pytest.mark.regression, pytest.mark.classifier]


def _ids(entries):
    return [e["id"] for e in entries]


@pytest.fixture(scope="module")
def fixture_entries(golden_historical_misses):
    return golden_historical_misses


def test_fixture_file_is_non_empty(golden_historical_misses):
    assert len(golden_historical_misses) >= 9, (
        "Historical-miss fixture has shrunk. Removing regression cases is "
        "not allowed without an explicit refactor doc entry."
    )


def test_every_entry_has_required_fields(golden_historical_misses):
    required = {
        "id", "ticker", "headline", "expected_category",
        "expected_sub_type", "expected_is_negative", "should_alert",
        "label_provenance", "status",
    }
    for entry in golden_historical_misses:
        missing = required - set(entry.keys())
        assert not missing, f"{entry.get('id', '?')} missing fields: {missing}"


def _load_fixture_entries():
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "fixtures" / "historical_misses.json"
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _param(entry):
    """Wrap an entry in pytest.param, honoring the xfail_today flag.

    xfail_today entries are *target* behaviors P1 must achieve.
    They are kept in the suite so the day they start passing, the test
    surfaces an XPASS and forces us to flip the flag → promoting the
    target to a hard regression.
    """
    if entry.get("xfail_today"):
        return pytest.param(
            entry,
            id=entry["id"],
            marks=pytest.mark.xfail(
                strict=True,
                reason=entry.get("xfail_reason", "target behavior, not yet implemented"),
            ),
        )
    return pytest.param(entry, id=entry["id"])


@pytest.mark.parametrize("entry", [_param(e) for e in _load_fixture_entries()])
def test_classifier_matches_expected_label(entry):
    """
    The classifier must return the expected (category, sub_type, is_negative)
    triple for each historical miss. is_vague is informational only.
    """
    category, sub_type, is_negative, _is_vague = classify_headline(entry["headline"])

    expected_category = CatalystCategory(entry["expected_category"])
    expected_sub_type = CatalystSubType(entry["expected_sub_type"])
    expected_is_negative = entry["expected_is_negative"]

    assert category == expected_category, (
        f"{entry['id']} category mismatch: got {category.value!r}, "
        f"expected {expected_category.value!r}. Headline: {entry['headline']!r}"
    )
    assert sub_type == expected_sub_type, (
        f"{entry['id']} sub_type mismatch: got {sub_type.value!r}, "
        f"expected {expected_sub_type.value!r}. Headline: {entry['headline']!r}"
    )
    assert is_negative == expected_is_negative, (
        f"{entry['id']} is_negative mismatch: got {is_negative}, "
        f"expected {expected_is_negative}. Headline: {entry['headline']!r}"
    )
