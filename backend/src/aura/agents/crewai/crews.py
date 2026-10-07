"""The v1 roster from ARCHITECTURE.md section 4: Researcher -> Drafter -> Reviewer.

Three agents is a hard ceiling on CPU-only inference. Do not add a fourth.

Every role's text comes from the versioned prompt registry (aura.agents.prompts): the files
there are the single source, pinned by hash, and agent_run records "<id>@v<N>".
"""
from crewai import Agent, Crew, Process, Task

from aura.agents import prompts

_ROLE_IDS = {"Deal Researcher": "crew.researcher", "Drafter": "crew.drafter",
             "Reviewer": "crew.reviewer", "Document Classifier": "classify_document",
             "Financial Extractor": "extract_financials"}

# Prompt template refs for agent_run lineage, one per agent role (the active versions).
ROLE_TEMPLATES = {role: prompts.get(template_id).ref for role, template_id in _ROLE_IDS.items()}


def template_for(role: str) -> str:
    return ROLE_TEMPLATES.get(role, "crew.unregistered")


def _agent(template_id: str, llm, tools: list) -> tuple[Agent, prompts.PromptTemplate]:
    t = prompts.get(template_id)
    return Agent(role=t.role, goal=t.goal, backstory=t.backstory, tools=tools, llm=llm,
                 allow_delegation=False, verbose=False), t


def build_classify_crew(llm) -> Crew:
    """One agent, one task: propose a document class as JSON. A person confirms it."""
    classifier, t = _agent("classify_document", llm, [])
    task = Task(description=t.task, expected_output=t.expected_output, agent=classifier)
    return Crew(agents=[classifier], tasks=[task], process=Process.sequential,
                memory=False, verbose=False)


def build_extract_crew(llm) -> Crew:
    """One agent, one task: read headline financials out of a document as JSON. A person
    verifies anything the model is unsure of."""
    extractor, t = _agent("extract_financials", llm, [])
    task = Task(description=t.task, expected_output=t.expected_output, agent=extractor)
    return Crew(agents=[extractor], tasks=[task], process=Process.sequential,
                memory=False, verbose=False)


def build_crew(llm, tools: list | None = None) -> Crew:
    tools = tools or []
    researcher, rt = _agent("crew.researcher", llm, tools)
    drafter, dt = _agent("crew.drafter", llm, tools)
    reviewer, vt = _agent("crew.reviewer", llm, [])

    research_task = Task(description=rt.task, expected_output=rt.expected_output,
                         agent=researcher)
    draft_task = Task(description=dt.task, expected_output=dt.expected_output, agent=drafter,
                      context=[research_task])
    review_task = Task(description=vt.task, expected_output=vt.expected_output, agent=reviewer,
                       context=[draft_task])

    # memory=False is REQUIRED - CrewAI's memory backend reaches for OpenAI
    # embeddings, which violates the local-only, zero-spend constraint.
    return Crew(agents=[researcher, drafter, reviewer],
                tasks=[research_task, draft_task, review_task],
                process=Process.sequential, memory=False, verbose=False)
