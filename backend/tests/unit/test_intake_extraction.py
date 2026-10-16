"""Deal intake extraction, unit level: rupee normalisation, identifier and table-grid
extraction, conflicts, confidence, schema validation and keeping the creator's edits."""
import pytest

from aura.core.domain.intake import Candidate, Citation, Intake, StagedChunk
from aura.core.services import intake as svc
from aura.core.services import intake_extraction as E
from aura.core.services import intake_fields as F


def chunk(text, cid=1, doc=1, kind="text", page=1, meta=None, name="doc.pdf"):
    return StagedChunk(chunk_id=cid, document_id=doc, filename=name, page_from=page,
                       page_to=page, kind=kind, text=text, meta=meta or {})


@pytest.mark.parametrize("raw,unit,expected", [
    ("₹412.38 crore", None, 4_123_800_000), ("INR 150 crore", None, 1_500_000_000),
    ("Rs. 12.5 Cr", None, 125_000_000), ("12.5 L", None, 1_250_000),
    ("₹1,00,000", None, 100_000), ("3.2 lakh", None, 320_000), ("45 million", None, 45_000_000),
    (96.4, "crore", 964_000_000), ("(3.42)", "crore", -34_200_000), ("abc", None, None)])
def test_rupee_amounts_are_whole_rupees(raw, unit, expected):
    assert F.parse_inr(raw, unit) == expected


def test_values_are_validated_by_type():
    cin, pan = F.BASE_BY_KEY["cin"], F.BASE_BY_KEY["pan"]
    assert F.normalise_value(cin, "u29253mh2011ptc215478") == ("U29253MH2011PTC215478", None)
    value, error = F.normalise_value(pan, "AAFCK48211")
    assert value is None and "PAN" in error
    assert F.normalise_value(F.BASE_BY_KEY["incorporation_date"], "14/06/2024")[0] == \
        "2024-06-14"
    value, error = F.normalise_value(F.BASE_BY_KEY["incorporation_date"], "in 2011")
    assert value is None and "2011" in error
    assert F.normalise_value(F.BASE_BY_KEY["tenor_months"], "5 years")[0] == 60
    assert F.normalise_value(F.BASE_BY_KEY["transaction_class"], "NCD issue")[0] == "DEBT"
    assert F.normalise_value(F.BASE_BY_KEY["coupon_pct"], "75%")[1]  # above 50% p.a.
    assert F.sanity_errors({"revenue_inr": 100, "ebitda_inr": 150}) == {
        "ebitda_inr": "EBITDA is larger than revenue; check the column or unit"}


def test_identifiers_are_found_with_page_citations_and_not_read_out_of_a_gstin():
    text = ("Kaveri Precision Components Private Limited\nCIN: U29253MH2011PTC215478 | "
            "PAN: AAFCK4821M | GSTIN 27AAFCK4821M1Z5")
    found = {(c.key, c.value) for c in E.identifier_candidates([chunk(text, page=3)])}
    assert found == {("cin", "U29253MH2011PTC215478"), ("pan", "AAFCK4821M"),
                     ("gstin", "27AAFCK4821M1Z5")}
    cin = next(c for c in E.identifier_candidates([chunk(text, page=3)]) if c.key == "cin")
    assert cin.citations[0].page_from == 3 and "U29253MH2011PTC215478" in cin.citations[0].quote
    names = E.company_name_candidates([chunk(text)])
    assert names[0].value == "Kaveri Precision Components Private Limited"


def test_the_latest_actual_year_column_of_a_table_grid_is_read_in_its_unit():
    grid = ("Statement of Profit and Loss\nParticulars | Note | FY24 | FY23\n"
            "Revenue from operations | 24 | 412.38 | 356.91\nEBITDA |  | 68.15 | 52.52\n"
            "Profit for the year |  | 31.93 | 24.85")
    meta = {"header": "Particulars | Note | FY24 | FY23",
            "heading": "Statement of Profit and Loss"}
    unit = chunk("(All amounts in ₹ crore, unless otherwise stated)", cid=1)
    table = chunk(grid, cid=2, kind="table", meta=meta)
    got = {c.key: c for c in E.table_candidates([unit, table]) if c.source == "table"}
    assert got["revenue_inr"].value == 4_123_800_000
    assert got["ebitda_inr"].value == 681_500_000 and got["pat_inr"].value == 319_300_000
    assert got["fiscal_year"].value == "FY24" and got["reporting_unit"].value == "crore"
    assert "412.38" in got["revenue_inr"].citations[0].quote
    # projections are skipped even when later
    model = ("Particulars | FY24A | FY25E | FY26E\nRevenue from operations | 412.38 | 468.52 | "
             "531.27")
    got = E.table_candidates([chunk("Financial model (₹ crore)", cid=3, doc=2),
                              chunk(model, cid=4, doc=2, kind="table",
                                    meta={"header": "Particulars | FY24A | FY25E | FY26E"})])
    assert next(c for c in got if c.key == "revenue_inr").value == 4_123_800_000


def _cand(key, value, conf, source, doc):
    return Candidate(key, value, conf, source, [Citation(doc, f"d{doc}.pdf", 1, 1, doc, "q")])


def test_agreeing_candidates_merge_and_disagreeing_ones_conflict():
    spec = F.BASE_BY_KEY["revenue_inr"]
    rec, conflict = E.merge_field(spec, [_cand("revenue_inr", 4_123_800_000, 0.9, "table", 1),
                                         _cand("revenue_inr", 4_124_000_000, 0.88, "regex", 2)],
                                  1)
    assert conflict is None and rec["confidence"] == 0.93 and len(rec["citations"]) == 2
    rec, conflict = E.merge_field(spec, [_cand("revenue_inr", 4_123_800_000, 0.9, "table", 1),
                                         _cand("revenue_inr", 3_569_100_000, 0.8, "llm", 2)], 1)
    assert conflict is not None and rec["conflict_id"] == "c1"
    assert [c["source"] for c in conflict["candidates"]] == ["table", "llm"]
    # a low-confidence model guess does not contest a deterministic reading
    rec, conflict = E.merge_field(spec, [_cand("revenue_inr", 4_123_800_000, 0.9, "table", 1),
                                         _cand("revenue_inr", 1, 0.3, "llm", 2)], 1)
    assert conflict is None
    # names compare without case, punctuation and Pvt/Ltd spelling
    assert F.same_value(F.BASE_BY_KEY["company_name"], "Kaveri Pvt. Ltd.",
                        "KAVERI PRIVATE LIMITED")


def test_model_confidence_is_self_report_times_the_validation_multiplier():
    tags = {"C1": chunk("Coupon: 11.25% per annum, payable quarterly", cid=9)}
    spec = F.BASE_BY_KEY["coupon_pct"]
    good = E.llm_candidates("terms", [spec], {"coupon_pct": {
        "value": "11.25%", "confidence": 0.8, "chunk": "C1", "quote": "11.25% per annum"}},
        tags, None, {})
    assert good[0].confidence == 0.8 and good[0].citations[0].chunk_id == 9
    unsure = E.llm_candidates("terms", [spec], {"coupon_pct": {
        "value": "9.5%", "confidence": 0.8, "chunk": "C1", "quote": "not in the text"}},
        tags, None, {})
    assert unsure[0].confidence == pytest.approx(0.48)
    errors = {}
    assert E.llm_candidates("terms", [F.BASE_BY_KEY["tenor_months"]],
                            {"tenor_months": {"value": "forever"}}, tags, None, errors) == []
    assert "tenor_months" in errors


def test_the_profile_is_built_and_validated_against_the_class_schema():
    schema = svc.schema_for("DEBT")
    keys = {s.key for s in F.profile_fields(schema)}
    assert {"profile.amount_inr", "profile.security_package.primary"} <= keys
    profile = F.build_profile({"profile.amount_inr": 1_500_000_000,
                               "profile.security_package.primary": "First charge",
                               "profile.repayment": None}, schema)
    assert profile == {"amount_inr": 1_500_000_000,
                       "security_package": {"primary": "First charge"}}
    from aura.core.services.deal_profile import profile_errors
    assert profile_errors("DEBT", profile) == []
    assert profile_errors("DEBT", {"tenor_months": 0})[0][0] == "tenor_months"


def test_a_new_extraction_keeps_the_creators_values_and_resolved_conflicts():
    intake = Intake(id=1, created_by="bhavesh", fields={
        "deal_name": {"value": "Mine", "source": "user", "accepted": True},
        "cin": {"value": "U29253MH2011PTC215478", "source": "regex", "accepted": True,
                "confidence": 0.8}},
        conflicts=[{"id": "c1", "field": "registered_office", "resolved": True, "chosen": 1,
                    "candidates": [{"value": "A"}, {"value": "Plot 42, Pune"}]}])
    result = E.ExtractionResult(
        fields={"deal_name": {"value": "Project Kaveri", "auto_value": "Project Kaveri",
                              "confidence": 0.9, "source": "regex", "citations": []},
                "cin": {"value": "U29253MH2011PTC215478", "auto_value": "x",
                        "confidence": 0.99, "source": "regex", "citations": []},
                "registered_office": {"value": "B", "auto_value": "B", "confidence": 0.9,
                                      "source": "regex", "citations": [],
                                      "conflict_id": "c1"}},
        conflicts=[{"id": "c1", "field": "registered_office", "label": "Registered office",
                    "chosen": None, "resolved": False,
                    "candidates": [{"value": "B", "source": "regex", "confidence": 0.9,
                                    "citations": []},
                                   {"value": "Plot 42, Pune", "source": "llm",
                                    "confidence": 0.7, "citations": []}]}],
        transaction_class="DEBT", warnings=[], llm_used=True, llm_groups=[], duration_ms=1)
    svc.apply_extraction(intake, result)
    assert intake.fields["deal_name"]["value"] == "Mine"
    assert intake.fields["deal_name"]["edited"] is True
    assert intake.fields["cin"]["accepted"] is True
    assert intake.conflicts[0]["resolved"] and intake.conflicts[0]["chosen"] == 1
    assert intake.fields["registered_office"]["value"] == "Plot 42, Pune"
    assert svc.override_summary(intake)["changed"] >= 1


def test_file_names_give_a_first_document_class():
    assert svc.guess_doc_class("kaveri_ncd_term_sheet.pdf").value == "term_sheet"
    assert svc.guess_doc_class("Board Resolution scan.pdf").value == "board_resolution"
    assert svc.guess_doc_class("kaveri_teaser.pptx").value == "financial_statement"
