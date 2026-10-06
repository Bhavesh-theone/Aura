"""Guard descriptions, and doc_class / party_type aligned with the frontend vocabulary.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

DOC_CLASSES = ["financial_statement", "cap_table", "board_resolution", "moa_aoa", "term_sheet",
               "spa", "shpa", "valuation_report", "tax_return", "litigation_summary",
               "env_clearance", "engagement_letter", "nda", "bank_statement", "gst_return",
               "charge_document", "land_title"]
OLD_DOC_CLASSES = ["teaser", "nda", "engagement_letter", "information_memorandum",
                   "financial_statements", "valuation_report", "term_sheet", "spa", "shpa", "sha",
                   "loan_agreement", "dd_report", "board_resolution", "cp_evidence",
                   "correspondence", "other"]
PARTY_TYPES = ["company", "llp", "fund", "trust", "individual", "government_body",
               "foreign_entity", "partnership", "sole_prop", "huf"]
OLD_PARTY_TYPES = ["company", "llp", "individual", "fund", "institution"]

# Old doc class -> new. Classes with no real equivalent land in financial_statement (a class
# no stage guard looks at) and are marked unconfirmed so a person re-checks them.
DOC_UP = {"financial_statements": "financial_statement", "sha": "shpa",
          "loan_agreement": "charge_document", "teaser": "financial_statement",
          "information_memorandum": "financial_statement", "dd_report": "financial_statement",
          "correspondence": "financial_statement", "other": "financial_statement",
          "cp_evidence": "board_resolution"}
LOSSY = ["sha", "teaser", "information_memorandum", "dd_report", "correspondence", "other",
         "cp_evidence"]
DOC_DOWN = {"financial_statement": "financial_statements", "cap_table": "other",
            "moa_aoa": "other", "tax_return": "other", "litigation_summary": "dd_report",
            "env_clearance": "other", "bank_statement": "other", "gst_return": "other",
            "charge_document": "loan_agreement", "land_title": "other"}
PARTY_UP = {"institution": "company"}
PARTY_DOWN = {"trust": "institution", "government_body": "institution",
              "foreign_entity": "company", "partnership": "llp", "sole_prop": "individual",
              "huf": "individual"}

GUARD_DESCRIPTIONS = {
    "T2_engagement_letter": "A signed engagement letter is on file",
    "T3_has_document": "At least one document has been uploaded to the deal",
    "T5_counterparty_on_deal": "A buyer, investor or lender is linked to the deal",
    "T8_term_sheet": "A term sheet is on file",
    "T9_no_open_blockers": "No blocker-severity diligence item is still open",
    "T10_definitive_agreement": "A definitive agreement (SPA or SHPA) is on file",
    "T11_all_cps_cleared": "Every condition precedent is satisfied or waived",
}


def _in(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _case(column: str, mapping: dict) -> str:
    whens = " ".join(f"WHEN '{a}' THEN '{b}'" for a, b in mapping.items())
    return f"CASE {column} {whens} ELSE {column} END"


def _retype(table: str, column: str, constraint: str, old: list, new: list,
            mapping: dict) -> None:
    """Swap a CHECK for another, mapping the data in between."""
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(constraint, type_="check")
    op.execute(f"UPDATE {table} SET {column} = {_case(column, mapping)}")
    with op.batch_alter_table(table) as batch:
        batch.create_check_constraint(constraint, f"{column} IN ({_in(new)})")


def upgrade() -> None:
    op.add_column("stage_guard", sa.Column("description", sa.Text(), nullable=False,
                                           server_default=""))
    for name, text in GUARD_DESCRIPTIONS.items():
        op.get_bind().execute(
            sa.text("UPDATE stage_guard SET description = :d WHERE guard_name = :n"),
            {"d": text, "n": name})

    with op.batch_alter_table("document") as batch:
        batch.drop_constraint("ck_doc_class_valid", type_="check")
    op.execute(f"UPDATE document SET class_confirmed = 0 WHERE doc_class IN ({_in(LOSSY)})")
    op.execute(f"UPDATE document SET doc_class = {_case('doc_class', DOC_UP)}")
    with op.batch_alter_table("document") as batch:
        batch.create_check_constraint("ck_doc_class_valid",
                                      f"doc_class IN ({_in(DOC_CLASSES)})")

    _retype("party", "party_type", "ck_party_type_valid", OLD_PARTY_TYPES, PARTY_TYPES,
            PARTY_UP)


def downgrade() -> None:
    _retype("party", "party_type", "ck_party_type_valid", PARTY_TYPES, OLD_PARTY_TYPES,
            PARTY_DOWN)
    _retype("document", "doc_class", "ck_doc_class_valid", DOC_CLASSES, OLD_DOC_CLASSES,
            DOC_DOWN)
    with op.batch_alter_table("stage_guard") as batch:
        batch.drop_column("description")
