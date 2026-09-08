"""The v1 roster from ARCHITECTURE.md section 4: Researcher -> Drafter -> Reviewer.

Three agents is a hard ceiling on CPU-only inference. Do not add a fourth.
"""
from crewai import Agent, Crew, Process, Task


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
