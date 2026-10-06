from aura.core.domain.enums import ActionCategory
from aura.core.policy.gate_policy import (DEFAULT_MATERIALITY_CAP_INR, classify, recommendation,
                                          requires_approval)


def test_materiality_above_the_cap_requires_a_human_whatever_the_category():
    cap = 50_000_000
    assert requires_approval(ActionCategory.INTERNAL_READ, cap + 1, cap) is True
    assert requires_approval(ActionCategory.INTERNAL_WRITE, cap + 1, cap) is True
    assert requires_approval(ActionCategory.INTERNAL_WRITE, cap, cap) is False  # not above
    assert requires_approval(ActionCategory.INTERNAL_WRITE, None, cap) is False


def test_default_cap_is_five_crore():
    assert DEFAULT_MATERIALITY_CAP_INR == 50_000_000
    assert requires_approval(ActionCategory.INTERNAL_WRITE, 50_000_001) is True
    assert requires_approval(ActionCategory.INTERNAL_WRITE, 49_999_999) is False


def test_recommendation_is_policy_not_model():
    assert recommendation(ActionCategory.OUTBOUND) == "approve"
    assert recommendation(ActionCategory.UNKNOWN) == "reject"
    assert recommendation(ActionCategory.MONEY, 60_000_000) == "reject"


def test_new_agent_tools_are_mapped_and_gated():
    assert classify("classify_document") is ActionCategory.DOCUMENT_CLASSIFICATION
    assert classify("draft_email") is ActionCategory.OUTBOUND
    assert requires_approval(classify("classify_document")) is True
    assert requires_approval(classify("draft_email")) is True
