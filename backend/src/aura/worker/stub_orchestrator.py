"""Deterministic stand-in for the CrewAI orchestrator, used when Ollama is unreachable.

It proposes the same actions the crew would, so the whole handoff loop runs with no model:
a plain brief proposes an outbound email, `classify_document` proposes a class from the
filename, and `draft_email` drafts a note to a deal party. Once the context carries a
decision marker, the next segment completes the job. Every run still writes an agent_run
row (model_id 'stub').
"""
import json
import re
import time



from aura.core.clock import utcnow
from aura.agents.llm.recording import RunRecorder
from aura.core.domain.enums import ActionCategory, DocClass
from aura.core.domain.extraction import ExtractionProposal
from aura.core.domain.segment import ProposedAction
from aura.core.policy.gate_policy import classify
from aura.core.ports.orchestrator import OrchestratorResult, RunContext

# First keyword hit wins. Ordered most specific first.
_KEYWORDS: list[tuple[tuple[str, ...], DocClass]] = [
    (("term sheet", "term_sheet", "termsheet"), DocClass.TERM_SHEET),
    (("engagement",), DocClass.ENGAGEMENT_LETTER),
    (("shpa", "shareholder"), DocClass.SHPA),
    (("spa", "share purchase"), DocClass.SPA),
    (("nda", "non-disclosure", "confidential"), DocClass.NDA),
    (("valuation",), DocClass.VALUATION_REPORT),
    (("cap table", "cap_table", "captable"), DocClass.CAP_TABLE),
    (("moa", "aoa", "memorandum", "articles"), DocClass.MOA_AOA),
    (("board", "resolution"), DocClass.BOARD_RESOLUTION),
    (("gst",), DocClass.GST_RETURN),
    (("tax", "itr"), DocClass.TAX_RETURN),
    (("bank",), DocClass.BANK_STATEMENT),
    (("charge", "mortgage", "hypothecation"), DocClass.CHARGE_DOCUMENT),
    (("land", "title deed"), DocClass.LAND_TITLE),
    (("litigation", "legal proceedings"), DocClass.LITIGATION_SUMMARY),
    (("environment", "clearance", "pollution"), DocClass.ENV_CLEARANCE),
    (("financial", "balance sheet", "p&l", "audited"), DocClass.FINANCIAL_STATEMENT),
]


def guess_class(filename: str, current: str) -> tuple[str, float]:
    name = filename.lower()
    for words, doc_class in _KEYWORDS:
        if any(w in name for w in words):
            return doc_class.value, 0.9
    return current, 0.3


_FIGURES = {"revenue_inr": r"revenue", "ebitda_inr": r"ebitda", "net_debt_inr": r"net[ _]debt"}


def read_figures(text: str) -> tuple[dict, float]:
    """Headline figures found as 'label: number' in the text. All three found is a
    confident read; each one missing lowers the confidence, so a thin document is sent to
    a person."""
    figures: dict = {}
    for key, label in _FIGURES.items():
        match = re.search(label + r"[^0-9\n]{0,20}([0-9][0-9,]*(?:\.[0-9]+)?)", text, re.I)
        figures[key] = float(match.group(1).replace(",", "")) if match else None
    found = sum(1 for v in figures.values() if v is not None)
    return figures, 0.98 if found == len(_FIGURES) else round(0.3 + 0.2 * found, 2)


class StubOrchestrator:
    def run(self, context_in: dict, run_context: RunContext) -> OrchestratorResult:
        if context_in.get("draft") or context_in.get("proposal_made"):
            done = dict(context_in) if context_in.get("proposal_made") \
                else {**context_in, "sent": True}
            return OrchestratorResult(completed=True, context_out=done, proposed_action=None)

        started, clock = utcnow(), time.perf_counter()
        capability = context_in.get("capability")
        if capability == "classify_document":
            result = self._classify(context_in)
        elif capability == "extract_financials":
            result = self._extract(context_in)
        elif capability == "draft_email":
            result = self._draft_email(context_in)
        else:
            result = self._brief(context_in)

        action, extraction = result.proposed_action, result.extraction
        output = ({"tool": action.tool, "arguments": action.arguments} if action else
                  {"extraction": extraction.payload, "confidence": extraction.confidence})
        recorder = RunRecorder(run_context, "stub", "1")
        recorder.record(
            archetype="stub", template_id=f"stub.{capability or 'brief'}.v1",
            messages=[{"role": "user", "content": json.dumps(context_in, sort_keys=True,
                                                             default=str)}],
            output_text=json.dumps(output, default=str),
            started_at=started, completed_at=utcnow(),
            latency_ms=int((time.perf_counter() - clock) * 1000),
            confidence=(action.arguments.get("confidence") if action
                        else extraction.confidence),
            tool_calls=[{"tool": action.tool, "arguments": action.arguments}] if action else [])
        if extraction is not None:
            extraction.model_run_id = recorder.last_run_id
        return result

    def _extract(self, context_in: dict) -> OrchestratorResult:
        payload, confidence = read_figures(context_in["document"].get("excerpt") or "")
        return OrchestratorResult(
            completed=False, context_out={**context_in, "proposal_made": True},
            proposed_action=None,
            extraction=ExtractionProposal(schema_name="financials.v1", payload=payload,
                                          confidence=confidence))

    def _brief(self, context_in: dict) -> OrchestratorResult:
        brief = context_in.get("brief", "(no brief)")
        draft = f"Dear contact,\n\nRegarding: {brief}\n\nBest,\nOpulence"
        return OrchestratorResult(
            completed=False,
            context_out={**context_in, "draft": draft},
            proposed_action=ProposedAction(
                tool="send_email",
                category=ActionCategory.OUTBOUND,
                arguments={"body": draft},
                summary=f"Send outbound email: {brief}",
            ),
        )

    def _classify(self, context_in: dict) -> OrchestratorResult:
        doc = context_in["document"]
        proposed, confidence = guess_class(doc["filename"], doc["current_class"])
        action = ProposedAction(
            tool="classify_document", category=classify("classify_document"),
            arguments={"document_id": doc["id"], "filename": doc["filename"],
                       "current_class": doc["current_class"], "proposed_class": proposed,
                       "confidence": confidence,
                       "rationale": "Chosen from keywords in the filename (stub)."},
            summary=f"Classify {doc['filename']} as {proposed}")
        return OrchestratorResult(completed=False,
                                  context_out={**context_in, "proposal_made": True},
                                  proposed_action=action)

    def _draft_email(self, context_in: dict) -> OrchestratorResult:
        deal, party = context_in["deal"], context_in["party"]
        body = (f"Dear {party['display_name']},\n\nI am writing about {deal['name']}, which is "
                f"currently at the {deal['stage']} stage. {context_in.get('brief', '')}\n\n"
                "Best regards,\nOpulence").replace("  ", " ")
        action = ProposedAction(
            tool="draft_email", category=classify("draft_email"),
            arguments={"party_id": party["id"], "to": party["display_name"],
                       "subject": f"Regarding {deal['name']}", "body": body},
            summary=f"Draft an outbound email to {party['display_name']} about {deal['name']}")
        return OrchestratorResult(completed=False,
                                  context_out={**context_in, "draft": body,
                                               "proposal_made": True},
                                  proposed_action=action)
