"""Prompt-building helpers for persona-aware agent behavior."""

from __future__ import annotations

from dataclasses import dataclass
import re


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

PERSONA_FLATNESS_GUARDRAIL = (
    "VOICE FAILURE MODE: Do not flatten into generic assistant prose, neutral corporate filler, "
    "or interchangeable debate boilerplate. The persona should be visible in sentence shape, "
    "transitions, emphasis, concessions, and how arguments are framed."
)

_ORDERED_BULLET_RE = re.compile(r"^\d+\.\s+")
_SECTION_ALIASES = {
    "your role": "role",
    "role": "role",
    "debating style": "debating_style",
    "debate style": "debating_style",
    "voice signals": "voice_signals",
    "voice signal": "voice_signals",
    "signature moves": "signature_moves",
    "signature move": "signature_moves",
    "language habits": "voice_signals",
    "rhetorical habits": "voice_signals",
    "core principles": "core_principles",
    "principles": "core_principles",
    "watchouts": "watchouts",
    "blind spots to watch": "watchouts",
    "user notes": "user_notes",
}


@dataclass(frozen=True)
class PersonaVoiceProfile:
    """Structured voice cues extracted from a persona markdown document."""

    name: str | None = None
    description: str | None = None
    role: str | None = None
    debating_style: tuple[str, ...] = ()
    voice_signals: tuple[str, ...] = ()
    signature_moves: tuple[str, ...] = ()
    core_principles: tuple[str, ...] = ()
    watchouts: tuple[str, ...] = ()
    user_notes: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.name,
                self.description,
                self.role,
                self.debating_style,
                self.voice_signals,
                self.signature_moves,
                self.core_principles,
                self.watchouts,
                self.user_notes,
            )
        )


def _normalize_line(text: str) -> str:
    return " ".join(text.strip().split())


def _parse_section_content(lines: list[str]) -> tuple[str | None, tuple[str, ...]]:
    """Split a section into paragraph text and bullet items."""
    bullets: list[str] = []
    paragraphs: list[str] = []
    for raw_line in lines:
        line = _normalize_line(raw_line)
        if not line:
            continue
        if line.startswith(("- ", "* ")):
            bullets.append(line[2:].strip())
            continue
        if _ORDERED_BULLET_RE.match(line):
            bullets.append(_ORDERED_BULLET_RE.sub("", line).strip())
            continue
        paragraphs.append(line)
    paragraph_text = " ".join(paragraphs).strip() or None
    return paragraph_text, tuple(item for item in bullets if item)


def _select_items(*groups: tuple[str, ...], limit: int = 3) -> list[str]:
    items: list[str] = []
    for group in groups:
        for entry in group:
            if entry and entry not in items:
                items.append(entry)
            if len(items) >= limit:
                return items
    return items


def parse_persona_voice_profile(persona_content: str | None) -> PersonaVoiceProfile:
    """Extract structured voice cues from free-form persona markdown."""
    if not persona_content or not persona_content.strip():
        return PersonaVoiceProfile()

    name: str | None = None
    description: str | None = None
    current_section: str | None = None
    sections: dict[str, list[str]] = {}
    freeform_lines: list[str] = []

    for raw_line in persona_content.strip().splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if current_section:
                sections.setdefault(current_section, []).append("")
            continue
        if stripped.startswith("# ") and not name:
            name = _normalize_line(stripped[2:])
            continue
        if stripped.startswith("> ") and not description:
            description = _normalize_line(stripped[2:])
            continue
        if stripped.startswith("## "):
            section_name = _normalize_line(stripped[3:]).lower()
            current_section = _SECTION_ALIASES.get(section_name)
            if current_section:
                sections.setdefault(current_section, [])
            continue
        if current_section:
            sections.setdefault(current_section, []).append(stripped)
            continue
        freeform_lines.append(_normalize_line(stripped))

    role_text, role_items = _parse_section_content(sections.get("role", []))
    debating_style_text, debating_style_items = _parse_section_content(
        sections.get("debating_style", [])
    )
    voice_signal_text, voice_signal_items = _parse_section_content(
        sections.get("voice_signals", [])
    )
    signature_text, signature_items = _parse_section_content(sections.get("signature_moves", []))
    principle_text, principle_items = _parse_section_content(sections.get("core_principles", []))
    watchout_text, watchout_items = _parse_section_content(sections.get("watchouts", []))
    user_note_text, user_note_items = _parse_section_content(sections.get("user_notes", []))

    fallback_freeform = " ".join(item for item in freeform_lines if item).strip() or None

    role = role_text or next(iter(role_items), None) or fallback_freeform
    debating_style = debating_style_items or ((debating_style_text,) if debating_style_text else ())
    voice_signals = voice_signal_items or ((voice_signal_text,) if voice_signal_text else ())
    signature_moves = signature_items or ((signature_text,) if signature_text else ())
    core_principles = principle_items or ((principle_text,) if principle_text else ())
    watchouts = watchout_items or ((watchout_text,) if watchout_text else ())
    user_notes = user_note_items or ((user_note_text,) if user_note_text else ())

    return PersonaVoiceProfile(
        name=name,
        description=description or fallback_freeform,
        role=role,
        debating_style=debating_style,
        voice_signals=voice_signals,
        signature_moves=signature_moves,
        core_principles=core_principles,
        watchouts=watchouts,
        user_notes=user_notes,
    )


def build_persona_voice_profile_block(persona_content: str | None) -> str | None:
    """Summarize the persona into high-leverage voice constraints for the model."""
    profile = parse_persona_voice_profile(persona_content)
    if profile.is_empty:
        return None

    lines = ["PERSONA VOICE PROFILE:"]
    if profile.name:
        lines.append(f"- Character anchor: {profile.name}")
    if profile.description:
        lines.append(f"- Public lens: {profile.description}")
    if profile.role:
        lines.append(f"- Operating stance: {profile.role}")

    visible_habits = _select_items(
        profile.voice_signals,
        profile.signature_moves,
        profile.debating_style,
        limit=4,
    )
    if visible_habits:
        lines.append("- Keep these habits visibly present in the writing:")
        lines.extend(f"  - {item}" for item in visible_habits)

    principles = _select_items(profile.core_principles, limit=3)
    if principles:
        lines.append("- Let these principles shape emphasis and trade-offs:")
        lines.extend(f"  - {item}" for item in principles)

    watchouts = _select_items(profile.watchouts, limit=3)
    if watchouts:
        lines.append("- Avoid these style failures while staying in character:")
        lines.extend(f"  - {item}" for item in watchouts)

    lines.append(
        "- Keep the same voice in openings, transitions, rebuttals, concessions, and recommendation sentences."
    )
    lines.append(
        "- Short JSON fields may stay concise, but they must still sound like the same persona speaking."
    )
    return "\n".join(lines)


def build_persona_prefix(
    persona_content: str | None,
    system_prompt: str | None = None,
) -> list[str]:
    """Return standardized persona/system prefix blocks for prompt assembly."""
    if persona_content and persona_content.strip():
        blocks = [
            "=== YOUR PERSONA ===\n" + persona_content.strip() + "\n=== END PERSONA ===",
            PERSONA_VOICE_CONTRACT,
            PERSONA_STYLE_GUARDRAIL,
            PERSONA_FLATNESS_GUARDRAIL,
        ]
        voice_profile = build_persona_voice_profile_block(persona_content)
        if voice_profile:
            blocks.append(voice_profile)
        return blocks
    if system_prompt and system_prompt.strip():
        return ["System: " + system_prompt.strip()]
    return []


def build_persona_expression_requirement(
    target: str = "response",
    persona_content: str | None = None,
) -> str:
    """Return a compact reminder that the persona should shape delivery."""
    requirement = (
        f"PERSONA EXPRESSION: Even while staying evidence-first, make the {target} sound like the assigned persona. "
        "Keep the voice visible in phrasing, argumentative rhythm, and sentence shape, not just in stated preferences. "
        "Avoid generic assistant wording."
    )
    profile = parse_persona_voice_profile(persona_content)
    if profile.is_empty:
        return requirement

    visible_habits = _select_items(
        profile.voice_signals,
        profile.signature_moves,
        profile.debating_style,
        limit=3,
    )
    if visible_habits:
        requirement += " Make these habits concrete: " + "; ".join(visible_habits) + "."

    principles = _select_items(profile.core_principles, limit=2)
    if principles:
        requirement += " Let these principles remain visible: " + "; ".join(principles) + "."
    return requirement
