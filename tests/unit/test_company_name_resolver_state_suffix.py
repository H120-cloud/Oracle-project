"""Resolver must handle SEC state-of-incorporation suffixes (e.g. 'QUALCOMM INC/DE').

The '/DE' suffix left a stray 'de' token so a bare 'Qualcomm' query scored 0.842
fuzzy — just under the 0.85 cutoff — and failed to resolve. This affects every
name-resolving source (investing.com, Sharecast, PRNewswire).
"""

import pytest

from src.core.company_name_resolver import CompanyNameResolver, normalize_name


@pytest.mark.unit
def test_normalize_strips_sec_state_suffix():
    assert normalize_name("QUALCOMM INC/DE") == "qualcomm"
    assert normalize_name("Qualcomm") == "qualcomm"
    # normal names unaffected
    assert normalize_name("Apple Inc") == "apple"


@pytest.mark.unit
def test_resolver_matches_name_with_state_suffix():
    resolver = CompanyNameResolver()
    # built the way _build_from_sec does: normalize the SEC title
    resolver._map = {normalize_name("QUALCOMM INC/DE"): "QCOM"}
    resolver._loaded = True
    resolver._index = None
    assert resolver.resolve("Qualcomm") == "QCOM"
