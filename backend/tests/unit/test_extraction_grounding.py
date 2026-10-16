"""A confident extraction must be grounded in the text the model read (E2E 2026-10-13: the
live model read "412.38" (in ₹ crore) as ₹41,238,000,000 at confidence 1.0, so a 10x wrong
figure skipped review)."""
from aura.agents.crewai.orchestrator import (UNGROUNDED_CONFIDENCE_CAP, grounded_confidence,
                                             ungrounded_figures)
from aura.core.domain.extraction import CONFIDENCE_GATE

PNL = ("(All amounts in ₹ crore, unless otherwise stated)\n"
       "Revenue from operations | 24 | 412.38 | 356.91\nEBITDA |  | 68.15 | 52.52\n"
       "Net debt (borrowings less cash) | (96.40) |")


def test_figures_found_at_a_unit_scale_keep_the_model_confidence():
    figures = {"revenue_inr": 4_123_800_000, "ebitda_inr": 681_500_000,
               "net_debt_inr": -964_000_000}
    assert ungrounded_figures(figures, PNL) == []
    assert grounded_confidence(figures, 1.0, PNL) == 1.0


def test_a_mis_scaled_figure_is_capped_below_the_review_gate():
    figures = {"revenue_inr": 41_238_000_000, "ebitda_inr": 6_815_000_000, "net_debt_inr": None}
    assert ungrounded_figures(figures, PNL) == ["revenue_inr", "ebitda_inr"]
    capped = grounded_confidence(figures, 1.0, PNL)
    assert capped == UNGROUNDED_CONFIDENCE_CAP < CONFIDENCE_GATE


def test_figures_left_in_crore_units_are_not_taken_as_rupees():
    # The same live model, another run: the table's crore numbers returned as rupees.
    figures = {"revenue_inr": 412.38, "ebitda_inr": 68.15, "net_debt_inr": None}
    assert ungrounded_figures(figures, PNL) == ["revenue_inr", "ebitda_inr"]
    assert grounded_confidence(figures, 0.9, PNL) == UNGROUNDED_CONFIDENCE_CAP


def test_rupees_lakh_and_indian_grouping_are_recognised():
    text = "Turnover Rs 4,56,00,000; EBITDA 72.5 lakh; net debt INR 12.3 million"
    figures = {"revenue_inr": 45_600_000, "ebitda_inr": 7_250_000, "net_debt_inr": 12_300_000}
    assert ungrounded_figures(figures, text) == []


def test_null_figures_and_a_low_confidence_are_left_alone():
    assert grounded_confidence({"revenue_inr": None}, 0.4, "nothing here") == 0.4
    assert grounded_confidence({"revenue_inr": 123.0}, 0.3, "no numbers") == 0.3
