"""Regression tests for company-name -> ticker resolution false-matching.

The prior implementation cut a raw 2-/3-word prefix and looked it up, so
"Apple Hospitality" resolved to AAPL (prefix "apple"). These tests pin the
fail-safe behavior: a confident exact/near-exact match resolves, anything
ambiguous or generic returns None rather than guessing a high-cap ticker.
"""

from __future__ import annotations

import pytest

from src.core.company_name_resolver import CompanyNameResolver, normalize_name

pytestmark = pytest.mark.unit


def _resolver(mapping: dict[str, str]) -> CompanyNameResolver:
    r = CompanyNameResolver()
    r._map = dict(mapping)
    r._loaded = True
    r._index = None  # force rebuild from the injected map
    return r


# Representative slice of the SEC name->ticker map (already normalized keys).
_SEC = {
    "apple": "AAPL",
    "apple hospitality reit": "APLE",
    "microsoft": "MSFT",
    "bitmine immersion technologies": "BMNR",
    "plug power": "PLUG",
    "global payments": "GPN",
    "nvidia": "NVDA",
}


# ── Fail-safe: the headline false-match must NOT resolve to a high-cap ───────

def test_apple_hospitality_does_not_resolve_to_aapl_when_reit_absent():
    r = _resolver({"apple": "AAPL"})
    assert r.resolve("Apple Hospitality Group") is None


def test_apple_hospitality_resolves_to_its_own_ticker_not_apple():
    r = _resolver(_SEC)
    result = r.resolve("Apple Hospitality")
    assert result != "AAPL"
    assert result == "APLE"


def test_generic_only_name_returns_none():
    r = _resolver(_SEC)
    for name in ("Global Holdings Group", "Technologies Inc", "Holdings Corp"):
        assert r.resolve(name) is None, name


def test_partial_overlap_with_generic_tail_does_not_false_match():
    # "Apple Global Technologies" shares only the generic-laden tail with no
    # real company of that name -> must not collapse to AAPL.
    r = _resolver({"apple": "AAPL"})
    assert r.resolve("Apple Global Technologies Holdings") is None


def test_two_word_registered_name_is_not_a_prefix_magnet():
    # The core prior bug: a registered 2-word name ("plug power") prefix-matched
    # ANY longer, DIFFERENT headline starting with those two words. A distinct
    # company must not be mis-attributed to PLUG.
    r = _resolver({"plug power": "PLUG"})
    assert r.resolve("Plug Power Solutions Acquisition Corp") is None


# ── Valid corporate variations still resolve ───────────────────────────────

def test_exact_name_with_suffix_resolves():
    r = _resolver(_SEC)
    assert r.resolve("Apple Inc.") == "AAPL"
    assert r.resolve("Microsoft Corporation") == "MSFT"


def test_registered_multiword_name_resolves_exactly():
    r = _resolver(_SEC)
    assert r.resolve("Bitmine Immersion Technologies") == "BMNR"


def test_minor_variation_resolves_via_fuzzy_threshold():
    # Singular/plural designator drift should still map confidently.
    r = _resolver(_SEC)
    assert r.resolve("Bitmine Immersion Technology") == "BMNR"


def test_suffix_stripping_resolves():
    r = _resolver(_SEC)
    assert r.resolve("Plug Power, Inc.") == "PLUG"


def test_global_payments_is_not_treated_as_generic_only():
    # "global" is a generic token, but "payments" is significant -> resolves.
    r = _resolver(_SEC)
    assert r.resolve("Global Payments Inc") == "GPN"


# ── Empty / junk input ─────────────────────────────────────────────────────

def test_empty_and_unknown_return_none():
    r = _resolver(_SEC)
    assert r.resolve("") is None
    assert r.resolve("Zzzqqq Nonexistent Co") is None


def test_normalize_name_strips_suffixes_and_punct():
    assert normalize_name("Apple, Inc.") == "apple"
    assert normalize_name("Plug Power LLC") == "plug power"
