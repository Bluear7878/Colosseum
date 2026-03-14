from colosseum.personas.prompting import (
    build_persona_expression_requirement,
    build_persona_prefix,
    parse_persona_voice_profile,
)


STRUCTURED_PERSONA = """
# Relentless Closer

> High-pressure operator who speaks in scoreboards and accountability.

## Your Role
Drive the room toward measurable execution. Keep standards obvious.

## Debating Style
- Push for concrete scoreboards, milestones, and visible progress.
- Challenge half-measures before they harden into the default.

## Voice Signals
- Overall tone: clipped, intense, and forward-leaning.
- Signature move: turn vague optimism into a measurable demand.

## Core Principles
- High standards are a feature, not a tax.
- Confidence should be earned through preparation.

## Watchouts
- Avoid confusing intensity with correctness.
- Respect team chemistry, not only individual output.
""".strip()


def test_parse_persona_voice_profile_extracts_structured_sections():
    profile = parse_persona_voice_profile(STRUCTURED_PERSONA)

    assert profile.name == "Relentless Closer"
    assert (
        profile.description
        == "High-pressure operator who speaks in scoreboards and accountability."
    )
    assert profile.role == "Drive the room toward measurable execution. Keep standards obvious."
    assert (
        "Push for concrete scoreboards, milestones, and visible progress." in profile.debating_style
    )
    assert "Overall tone: clipped, intense, and forward-leaning." in profile.voice_signals
    assert "High standards are a feature, not a tax." in profile.core_principles
    assert "Avoid confusing intensity with correctness." in profile.watchouts


def test_build_persona_prefix_includes_voice_profile_block():
    rendered = "\n\n".join(build_persona_prefix(STRUCTURED_PERSONA))

    assert "PERSONA VOICE PROFILE:" in rendered
    assert "Push for concrete scoreboards, milestones, and visible progress." in rendered
    assert "High standards are a feature, not a tax." in rendered
    assert "generic assistant prose" in rendered


def test_build_persona_expression_requirement_uses_structured_persona_cues():
    requirement = build_persona_expression_requirement(
        "debate response, including concessions",
        STRUCTURED_PERSONA,
    )

    assert "Avoid generic assistant wording." in requirement
    assert "Overall tone: clipped, intense, and forward-leaning." in requirement
    assert "High standards are a feature, not a tax." in requirement


def test_unstructured_persona_still_produces_a_voice_profile():
    rendered = "\n\n".join(
        build_persona_prefix("Use short, severe sentences. Attack weak reasoning immediately.")
    )

    assert "PERSONA VOICE PROFILE:" in rendered
    assert "Use short, severe sentences. Attack weak reasoning immediately." in rendered
