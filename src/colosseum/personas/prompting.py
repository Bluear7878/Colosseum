"""Prompt-building helpers for persona-aware agent behavior."""

from __future__ import annotations


PERSONA_VOICE_CONTRACT = (
    "VOICE CONTRACT: Write in a way that sounds recognizably like this persona. "
    "Let your diction, cadence, level of directness, emotional temperature, and rhetorical habits "
    "show up naturally in every free-text field. Do not describe the persona from the outside; "
    "speak through that lens."
)

PERSONA_STYLE_GUARDRAIL = (
    "STYLE GUARDRAIL: Persona changes framing and wording, not facts. "
    "Do not invent biography, personal anecdotes, endorsements, or unsupported claims just to sound in-character. "
    "If the persona would normally sound overconfident, keep the factual claim calibrated and label uncertainty explicitly. "
    "JSON validity, evidence quality, and required schema always take priority over style."
)


def build_persona_prefix(
    persona_content: str | None,
    system_prompt: str | None = None,
) -> list[str]:
    """Return standardized persona/system prefix blocks for prompt assembly."""
    if persona_content and persona_content.strip():
        return [
            "=== YOUR PERSONA ===\n" + persona_content.strip() + "\n=== END PERSONA ===",
            PERSONA_VOICE_CONTRACT,
            PERSONA_STYLE_GUARDRAIL,
        ]
    if system_prompt and system_prompt.strip():
        return ["System: " + system_prompt.strip()]
    return []


def build_persona_expression_requirement(target: str = "response") -> str:
    """Return a compact reminder that the persona should shape delivery."""
    return (
        f"PERSONA EXPRESSION: Even while staying evidence-first, make the {target} sound like the assigned persona. "
        "Keep the voice visible in phrasing and argumentative rhythm, not just in stated preferences."
    )
