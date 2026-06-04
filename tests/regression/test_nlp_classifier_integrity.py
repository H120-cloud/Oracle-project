"""
Regression guard — NLP classifier ↔ main pipeline enum consistency.

The NLP semantic layer was silently DEAD for an unknown period: it referenced
CatalystSubType members that don't exist (MERGER_ACQUISITION, PARTNERSHIP,
AI_ML, INSIDER_PURCHASE), so every call raised AttributeError, which the main
classifier swallowed and fell back to regex-only. These tests pin the two
invariants that prevent that class of silent failure from recurring.
"""

from __future__ import annotations

import pytest

from src.core.agentic.news_momentum_nlp_classifier import (
    _NLP_LABEL_TO_SUBTYPE,
    LABEL_MAP,
    classify_headline as nlp_classify,
)
from src.core.agentic.news_momentum_catalyst_classifier import SUBTYPE_TO_CATEGORY

pytestmark = [pytest.mark.regression, pytest.mark.classifier]


def test_every_nlp_label_maps_to_a_real_subtype():
    """Each NLP output label must translate to a CatalystSubType that the main
    pipeline knows how to route. A missing entry = silent VAGUE_PR downgrade."""
    for label in LABEL_MAP:
        assert label in _NLP_LABEL_TO_SUBTYPE, f"NLP label {label!r} has no subtype mapping"
        subtype = _NLP_LABEL_TO_SUBTYPE[label]
        assert subtype in SUBTYPE_TO_CATEGORY, (
            f"NLP label {label!r} maps to {subtype!r} which is absent from "
            f"SUBTYPE_TO_CATEGORY → would route to OTHER."
        )


def test_nlp_classifier_never_raises():
    """The NLP layer must classify without throwing — the AttributeError crash
    that silently disabled it must not return."""
    for hl in [
        "Company wins $200M government contract",
        "Firm to acquire competitor in all-cash deal",
        "Startup announces AI partnership",
        "Insider buying reported by CEO",
        "Company provides corporate update",
        "",
    ]:
        subtype, conf = nlp_classify(hl)
        assert subtype is not None
        assert 0.0 <= conf <= 1.0
