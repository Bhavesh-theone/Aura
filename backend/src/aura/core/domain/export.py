"""A deal export: everything a person may see about one deal, assembled once and rendered
to PDF, Word, Excel, JSON or CSV by the adapters in aura.exports. Pure data.

Each section is a list of tables. A table names its columns and their types so every
renderer can format a cell without guessing: 'inr' cells hold whole rupees (int), 'date' and
'datetime' cells ISO strings, 'bool' cells booleans."""
from dataclasses import dataclass, field

EXPORT_SCHEMA_VERSION = 1

# Section ids, in report order, with their human titles.
SECTIONS: dict[str, str] = {
    "summary": "Deal summary",
    "stages": "Stage history",
    "parties": "Parties",
    "profile": "Deal profile",
    "financials": "Financials",
    "mandate": "Mandate",
    "documents": "Documents",
    "diligence": "Diligence and findings",
    "conditions": "Conditions precedent",
    "compliance": "Compliance",
    "decisions": "Decisions",
    "agent_runs": "Agent runs",
    "audit": "Audit chain",
}
DEFAULT_SECTIONS: tuple[str, ...] = tuple(SECTIONS)

# 'enum' is a code ('red_flag', 'DILIGENCE'): raw in JSON / CSV, sentence case for people.
COLUMN_TYPES = ("text", "enum", "inr", "int", "float", "pct", "date", "datetime", "bool")


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    type: str = "text"      # one of COLUMN_TYPES
    width: float = 1.0      # relative width in the human renderings
    human: bool = True      # False: machine renderings only (JSON, CSV, Excel)


@dataclass
class ExportTable:
    key: str
    title: str
    columns: list[Column]
    rows: list[dict] = field(default_factory=list)
    note: str | None = None          # shown under the title (e.g. "masked for your role")
    truncated: bool = False


@dataclass
class ExportSection:
    key: str
    title: str
    tables: list[ExportTable] = field(default_factory=list)
    facts: list[tuple[str, str]] = field(default_factory=list)   # label, display value
    data: dict = field(default_factory=dict)  # extra machine data for JSON (raw profile ...)


@dataclass
class DealExportBundle:
    schema_version: int
    generated_at: str               # ISO 8601, UTC
    generated_by: str
    generated_by_role: str
    deal: dict                      # header: ids, class, stage, outcome, dates, owner, team
    sections: list[ExportSection]
    upsi: bool                      # a document on the deal is UPSI or sensitivity 4+
    audit: dict                     # chain status and head at export time

    @property
    def section_keys(self) -> list[str]:
        return [s.key for s in self.sections]

    def section(self, key: str) -> ExportSection | None:
        return next((s for s in self.sections if s.key == key), None)

    def to_json_dict(self) -> dict:
        """The JSON export: stable keys, ISO dates, rupees as integers."""
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "generated_by": self.generated_by,
            "generated_by_role": self.generated_by_role,
            "deal": self.deal,
            "confidential": True,
            "upsi": self.upsi,
            "audit": self.audit,
            "sections": {
                s.key: {
                    "title": s.title,
                    **({"facts": {label: value for label, value in s.facts}} if s.facts
                       else {}),
                    **s.data,
                    "tables": {t.key: {"title": t.title,
                                       "columns": [{"key": c.key, "label": c.label,
                                                    "type": c.type} for c in t.columns],
                                       "rows": t.rows,
                                       **({"note": t.note} if t.note else {}),
                                       **({"truncated": True} if t.truncated else {})}
                               for t in s.tables},
                } for s in self.sections},
        }
