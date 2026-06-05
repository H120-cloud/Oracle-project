from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.agentic.pre_news_detector import _news_item_analysis_text


pytestmark = [pytest.mark.unit]


def test_pre_news_analysis_text_includes_source_description():
    item = SimpleNamespace(
        headline="Bio Green Med announces update",
        description="Share-for-share exchange would make Future NRG a wholly owned BGMS unit.",
        summary="",
    )

    text = _news_item_analysis_text(item)

    assert "Bio Green Med announces update" in text
    assert "wholly owned BGMS unit" in text
