"""The v1 roster from ARCHITECTURE.md section 4: Researcher -> Drafter -> Reviewer.

Three agents is a hard ceiling on CPU-only inference. Do not add a fourth.
"""
from crewai import Agent, Crew, Process, Task

# Prompt template ids for agent_run lineage: one per agent role, versioned by hand whenever
# the role text or its task description changes.
ROLE_TEMPLATES = {
    "Deal Researcher": "crew.researcher.v1",
    "Drafter": "crew.drafter.v1",
    "Reviewer": "crew.reviewer.v1",
    "Document Classifier": "classify_document.v1",
    "Financial Extractor": "extract_financials.v1",
}


def template_for(role: str) -> str:
    return ROLE_TEMPLATES.get(role, "crew.unregistered")


def build_classify_crew(llm) -> Crew:
    """One agent, one task: propose a document class as JSON. A person confirms it."""
    classifier = Agent(
        role="Document Classifier",
        goal="Propose which class a deal document belongs to. Never guess wildly.",
        backstory="You read a filename and the start of a document and name its class. "
                  "You reply with one JSON object and nothing else.",
        tools=[], llm=llm, allow_delegation=False, verbose=False,
    )
    task = Task(
        description="Classify this document.\nFilename: {filename}\nCurrent class: "
                    "{current_class}\nValid classes: {classes}\nFirst text:\n{excerpt}\n\n"
                    'Reply as JSON: {{"doc_class": "<one valid class>", '
                    '"confidence": <0 to 1>, "rationale": "<one sentence>"}}',
        expected_output="A single JSON object with doc_class, confidence and rationale.",
        agent=classifier,
    )
    return Crew(agents=[classifier], tasks=[task], process=Process.sequential,
                memory=False, verbose=False)


def build_extract_crew(llm) -> Crew:
    """One agent, one task: read headline financials out of a document as JSON. A person
    verifies anything the model is unsure of."""
    extractor = Agent(
        role="Financial Extractor",
        goal="Read the headline figures from a financial document. Never invent a number.",
        backstory="You read the start of a document and report revenue, EBITDA and net debt "
                  "in rupees. A figure you cannot find is null. You reply with one JSON "
                  "object and nothing else.",
        tools=[], llm=llm, allow_delegation=False, verbose=False,
    )
    task = Task(
        description="Extract figures from this document.\nFilename: {filename}\nFirst text:\n"
                    "{excerpt}\n\nReply as JSON: "
                    '{{"revenue_inr": <number or null>, "ebitda_inr": <number or null>, '
                    '"net_debt_inr": <number or null>, "confidence": <0 to 1>}}',
        expected_output="A single JSON object with the three figures and a confidence.",
        agent=extractor,
    )
    return Crew(agents=[extractor], tasks=[task], process=Process.sequential,
                memory=False, verbose=False)


def build_crew(llm, tools: list | None = None) -> Crew:
    tools = tools or []

    researcher = Agent(
        role="Deal Researcher",
        goal="Gather the facts needed about a deal. Never invent data.",
        backstory="You look up real records before answering. If a tool can "
                  "answer, you call it. You answer in two sentences.",
        tools=tools, llm=llm, allow_delegation=False, verbose=False,
    )
    drafter = Agent(
        role="Drafter",
        goal="Write the requested business artifact using only the researcher's facts.",
        backstory="You write concise, professional Indian business correspondence. "
                  "You never send anything yourself - you produce a draft.",
        tools=tools, llm=llm, allow_delegation=False, verbose=False,
    )
    reviewer = Agent(
        role="Reviewer",
        goal="Check the draft for factual errors and unprofessional tone.",
        backstory="You are terse. You reply either 'APPROVED' plus the final "
                  "draft, or list the specific problems.",
        tools=[], llm=llm, allow_delegation=False, verbose=False,
    )

    research_task = Task(
        description="Gather the facts needed for this brief: {brief}",
        expected_output="Two sentences of factual context.", agent=researcher,
    )
    draft_task = Task(
        description="Write the artifact requested by this brief: {brief}",
        expected_output="The finished draft text.", agent=drafter,
        context=[research_task],
    )
    review_task = Task(
        description="Review the draft. If it should be sent, state the tool call "
                    'as JSON: {{"tool": "send_email", "arguments": {{...}}}}',
        expected_output="Either APPROVED plus the draft, or a list of problems.",
        agent=reviewer, context=[draft_task],
    )

    # memory=False is REQUIRED - CrewAI's memory backend reaches for OpenAI
    # embeddings, which violates the local-only, zero-spend constraint.
    return Crew(agents=[researcher, drafter, reviewer],
                tasks=[research_task, draft_task, review_task],
                process=Process.sequential, memory=False, verbose=False)
