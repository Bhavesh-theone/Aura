"""Make every call on a CrewAI LLM go through a RunRecorder.

CrewAI hides its model calls behind the agent executor, and its hook system swallows hook
errors, so a hook cannot enforce "no record, no output". The one place every inference passes
is LLM.call(). instrument_llm() swaps the instance onto a subclass whose call() records the
run and raises if it cannot.
"""
from aura.agents.llm.recording import RunRecorder, normalise_messages

_CLASSES: dict[type, type] = {}


def _usage(llm):
    def read() -> tuple[int, int]:
        summary = llm.get_token_usage_summary()
        return summary.prompt_tokens, summary.completion_tokens
    return read


def _recording_class(base: type) -> type:
    if base in _CLASSES:
        return _CLASSES[base]
    base_call = base.call

    def call(self, messages, *args, **kwargs):
        recorder: RunRecorder = self._aura_recorder
        agent = kwargs.get("from_agent") or (args[4] if len(args) > 4 else None)
        role = getattr(agent, "role", None) or "unknown"
        from aura.agents.crewai.crews import template_for
        return recorder.traced(
            lambda: base_call(self, messages, *args, **kwargs),
            archetype=role, template_id=template_for(role),
            messages=normalise_messages(messages), usage=_usage(self))

    _CLASSES[base] = type(f"Recording{base.__name__}", (base,), {"call": call})
    return _CLASSES[base]


def instrument_llm(llm, recorder: RunRecorder):
    if type(llm) not in _CLASSES.values():
        llm.__class__ = _recording_class(type(llm))
    llm._aura_recorder = recorder
    return llm
