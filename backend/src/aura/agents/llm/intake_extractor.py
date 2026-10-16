"""The deal-intake field extractor: the local model through Ollama's chat API, one field
group per call (core.ports.intake.FieldExtractor).

- the prompt is the group's versioned template (agents/prompts/intake.<group>@vN.md);
- temperature 0, thinking off (qwen3.5 otherwise spends its budget reasoning), and Ollama's
  structured output: `format` is a JSON Schema of the group's answer, so even a 4B model
  returns parseable JSON; what still comes back malformed goes through the JSON repair;
- every call is recorded as an agent_run row (archetype 'intake_extractor', the template
  id, the intake id; no deal yet) through RunRecorder, which also retries transient errors,
  enforces the run's call and time budget and takes the process-wide model slot. These runs
  are not agent-capability runs: no autonomy metric reads them.
"""
import json

from aura.agents import prompts
from aura.agents.llm.recording import RunRecorder
from aura.agents.llm.repair import extract_json
from aura.core.ports.orchestrator import TransientModelError

ARCHETYPE = "intake_extractor"
LIST_KEYS = {"parties": "parties", "regulatory": "regulatory_flags",
             "mandate": "mandate_criteria"}


def _value_schema(field: dict) -> dict:
    t = field.get("type")
    if t == "enum" and field.get("options"):
        return {"anyOf": [{"type": "string", "enum": list(field["options"])}, {"type": "null"}]}
    if t in ("integer",):
        return {"type": ["integer", "string", "null"]}
    if t in ("number", "percent"):
        return {"type": ["number", "string", "null"]}
    if t == "boolean":
        return {"type": ["boolean", "null"]}
    if t == "string_list":
        return {"type": ["array", "null"], "items": {"type": "string"}}
    return {"type": ["string", "null"]}


def answer_schema(group: str, fields: list[dict]) -> dict:
    """The JSON Schema Ollama constrains the answer to."""
    if group in LIST_KEYS:
        key = LIST_KEYS[group]
        item = {"type": "object", "properties": {
            "chunk": {"type": "string"}, "quote": {"type": "string"}}}
        if group == "parties":
            item["properties"].update(
                name={"type": "string"},
                role={"type": "string", "enum": ["buyer", "seller", "target", "issuer",
                                                 "investor", "lender", "advisor", "counsel"]},
                party_type={"type": "string", "enum": [
                    "company", "llp", "fund", "trust", "individual", "government_body",
                    "foreign_entity", "partnership"]})
            item["properties"]["quote"]["maxLength"] = 200
            item["required"] = ["name", "role"]
        elif group == "regulatory":
            item["properties"].update(flag={"type": "string", "enum": [
                "RBI", "FEMA", "CCI", "SEBI", "PRESS_NOTE_3"]}, reason={"type": "string"})
            item["required"] = ["flag", "reason"]
        else:
            item["properties"].update(criterion_key={"type": "string"},
                                      operator={"type": "string"}, value={},
                                      hardness={"type": "string"},
                                      weight={"type": ["number", "null"]})
            item["required"] = ["criterion_key", "operator", "value", "hardness"]
        return {"type": "object", "properties": {key: {"type": "array", "items": item,
                                                         "maxItems": 8}},
                "required": [key]}
    props = {}
    for f in fields:
        key = f["key"].removeprefix("profile.")
        props[key] = {"type": "object", "properties": {
            "value": _value_schema(f), "confidence": {"type": "number"},
            "chunk": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["value", "confidence"]}
    return {"type": "object", "properties": props, "required": list(props)}


def render(group: str, fields: list[dict], passages: str,
           transaction_class: str | None) -> tuple[str, list[dict]]:
    template = prompts.get(f"intake.{group}")
    lines = []
    for f in fields:
        key = f["key"].removeprefix("profile.")
        desc = f.get("description") or f.get("label") or ""
        lines.append(f"- {key}: {f.get('label')}. {desc} ({f.get('format')})")
    values = {"fields": "\n".join(lines), "passages": passages,
              "transaction_class": transaction_class or "unknown"}
    messages = [{"role": "system",
                 "content": f"{template.goal.format(**values)}\n{template.backstory}"},
                {"role": "user", "content": template.task.format(**values)}]
    return template.ref, messages


class OllamaFieldExtractor:
    def __init__(self, recorder: RunRecorder, base_url: str, model: str,
                 timeout: float = 300.0, num_ctx: int = 8192, think: bool = False):
        self.recorder = recorder
        self.base_url, self.model = base_url.rstrip("/"), model
        self.timeout, self.num_ctx, self.think = timeout, num_ctx, think

    def _chat(self, messages: list[dict], schema: dict) -> tuple[str, int, int]:
        import httpx
        try:
            r = httpx.post(f"{self.base_url}/api/chat", timeout=self.timeout, json={
                "model": self.model, "stream": False, "think": self.think,
                "format": schema, "messages": messages,
                "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": 1500}})
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise TransientModelError(f"Ollama unreachable: {exc}") from exc
        if r.status_code >= 500:
            raise TransientModelError(f"Ollama answered {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        body = r.json()
        content = (body.get("message") or {}).get("content") or ""
        return content, int(body.get("prompt_eval_count") or 0), int(body.get("eval_count") or 0)

    def extract(self, group: str, fields: list[dict], passages: str,
                transaction_class: str | None) -> dict | None:
        template_id, messages = render(group, fields, passages, transaction_class)
        schema = answer_schema(group, fields)
        usage = {"in": 0, "out": 0}

        def call() -> str:
            text, tin, tout = self._chat(messages, schema)
            usage["in"] += tin
            usage["out"] += tout
            return text

        text = self.recorder.traced(call, archetype=ARCHETYPE, template_id=template_id,
                                    messages=messages,
                                    usage=lambda: (usage["in"], usage["out"]))
        parsed = extract_json(text)
        if parsed is None:
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return None
        return parsed if isinstance(parsed, dict) else None


class ScriptedFieldExtractor:
    """A deterministic stand-in for tests and stub evals: answers from a dict keyed by
    group ({group: answer}); a callable value receives (fields, passages)."""
    model = "stub"

    def __init__(self, answers: dict | None = None, recorder: RunRecorder | None = None):
        self.answers = answers or {}
        self.recorder = recorder
        self.calls: list[tuple[str, str]] = []

    def extract(self, group: str, fields: list[dict], passages: str,
                transaction_class: str | None) -> dict | None:
        template_id, messages = render(group, fields, passages, transaction_class)
        answer = self.answers.get(group)
        if callable(answer):
            answer = answer(fields, passages)
        self.calls.append((group, passages))
        text = json.dumps(answer) if answer is not None else "not json"
        if self.recorder is not None:
            text = self.recorder.traced(lambda: text, archetype=ARCHETYPE,
                                        template_id=template_id, messages=messages)
        return extract_json(text)
