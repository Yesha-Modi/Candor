"""What the agent is allowed to return.

The three decisions are the project's whole point. Making them a required field
means the model has to choose one — it cannot drift into answering a question it
should have refused, because "answer" and "refuse" are different shapes.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AgentResponse(BaseModel):
    decision: Literal["answer", "clarify", "refuse"] = Field(
        description=(
            "answer: the question is clear and the data can answer it. "
            "clarify: more than one defensible reading, and they give different "
            "numbers — ask which is wanted. "
            "refuse: the data cannot answer this at all."
        )
    )

    sql: Optional[str] = Field(
        default=None,
        description="DuckDB SELECT statement. Required when decision is 'answer', otherwise null.",
    )

    clarifying_question: Optional[str] = Field(
        default=None,
        description=(
            "One short question naming the competing readings. "
            "Required when decision is 'clarify', otherwise null."
        ),
    )

    refusal_reason: Optional[str] = Field(
        default=None,
        description=(
            "Which specific data is missing, and why no column substitutes for it. "
            "Required when decision is 'refuse', otherwise null."
        ),
    )

    metrics_used: list[str] = Field(
        default_factory=list,
        description="Names of semantic layer metrics this answer composes. Empty for clarify and refuse.",
    )

    assumptions: list[str] = Field(
        default_factory=list,
        description=(
            "Choices made that the question did not specify — a date range, a "
            "status filter, a tie-break. Empty if none were needed."
        ),
    )

    confidence: Literal["high", "medium", "low"] = Field(
        description="How certain this is the right reading of the question."
    )


def validate_shape(response: AgentResponse) -> list[str]:
    """Check the fields match the decision. Returns a list of problems."""
    problems = []

    if response.decision == "answer":
        if not response.sql:
            problems.append("decision is 'answer' but no sql was given")
        if response.clarifying_question:
            problems.append("decision is 'answer' but a clarifying_question was given")
        if response.refusal_reason:
            problems.append("decision is 'answer' but a refusal_reason was given")

    elif response.decision == "clarify":
        if not response.clarifying_question:
            problems.append("decision is 'clarify' but no clarifying_question was given")
        if response.sql:
            problems.append("decision is 'clarify' but sql was given anyway")

    elif response.decision == "refuse":
        if not response.refusal_reason:
            problems.append("decision is 'refuse' but no refusal_reason was given")
        if response.sql:
            problems.append("decision is 'refuse' but sql was given anyway")

    return problems