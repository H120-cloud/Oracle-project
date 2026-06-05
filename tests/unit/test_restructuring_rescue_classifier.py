from src.core.agentic.news_momentum_catalyst_classifier import classify_headline
from src.core.agentic.news_momentum_models import CatalystCategory, CatalystSubType


def test_chapter_11_debt_cut_with_financing_is_restructuring_rescue():
    headline = "Inotiv enters Chapter 11 to cut $326M debt, secure $65M financing"

    category, sub_type, is_negative, is_vague = classify_headline(headline)

    assert category == CatalystCategory.FINANCIAL
    assert sub_type == CatalystSubType.DEBT_RESTRUCTURING
    assert is_negative is False
    assert is_vague is False


def test_plain_chapter_11_without_rescue_terms_stays_negative():
    headline = "Company files for Chapter 11 bankruptcy protection"

    category, sub_type, is_negative, _ = classify_headline(headline)

    assert category == CatalystCategory.NEGATIVE
    assert sub_type == CatalystSubType.OTHER
    assert is_negative is True
