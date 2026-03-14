from __future__ import annotations

import re

from colosseum.core.models import GeneratedPersona, PersonaProfileRequest


class PersonaGenerator:
    PERSONALITY_HINTS = {
        "analytical": {
            "priority": "define terms, pressure-test assumptions, and separate signal from noise",
            "style": "asks for missing evidence before accepting a strong claim",
            "risk": "can over-index on precision and slow down a decision",
            "voice": "measured, precise, and slightly surgical rather than theatrical",
        },
        "skeptical": {
            "priority": "surface hidden failure modes and challenge optimistic leaps",
            "style": "treats unclear claims as unproven until tightened",
            "risk": "can sound colder or harsher than intended",
            "voice": "dry, firm, and hard to impress",
        },
        "empathetic": {
            "priority": "protect stakeholder impact and avoid elegant-but-fragile decisions",
            "style": "reframes conflict around people, incentives, and long-term trust",
            "risk": "may underplay aggressive but valuable trade-offs",
            "voice": "warm, grounded, and attentive to downstream human impact",
        },
        "bold": {
            "priority": "push toward action when analysis is good enough to move",
            "style": "prefers decisive comparisons and clear calls over hedging",
            "risk": "can dismiss nuance too early if unchecked",
            "voice": "high-conviction, energetic, and impatient with drift",
        },
        "calm": {
            "priority": "lower emotional noise and keep the room focused on substance",
            "style": "responds without escalation and converts attacks into structured points",
            "risk": "can appear less urgent than the situation really is",
            "voice": "steady, low-drama, and composed under pressure",
        },
        "playful": {
            "priority": "keep the exchange lively without losing the argument",
            "style": "uses wit, contrast, and memorable phrasing to land a point",
            "risk": "can be misread as unserious if evidence is thin",
            "voice": "light on its feet, sharp, and a little mischievous",
        },
    }

    STYLE_HINTS = {
        "direct": {
            "opening": "opens with the conclusion first, then backs it with 2-3 reasons",
            "debate": "cuts to the weak link quickly instead of circling around it",
            "cadence": "short to medium sentences with minimal throat-clearing",
            "signature": "states the call early, then pressures the weakest assumption",
        },
        "collaborative": {
            "opening": "starts by identifying what is already true on both sides",
            "debate": "tries to build hybrid answers instead of winning on rhetoric alone",
            "cadence": "inclusive transitions that still keep momentum",
            "signature": "acknowledges a valid peer point before redirecting to a better synthesis",
        },
        "evidence": {
            "opening": "anchors claims in examples, mechanisms, and practical constraints",
            "debate": "asks 'what would change your mind?' before escalating",
            "cadence": "claim-then-evidence rhythm with visible uncertainty labels",
            "signature": "ties each strong claim to a mechanism, example, or testable consequence",
        },
        "strategic": {
            "opening": "frames the issue around sequencing, incentives, and second-order effects",
            "debate": "keeps returning to trade-offs, not isolated local optimizations",
            "cadence": "long enough to show the system, short enough to keep pressure on the decision",
            "signature": "zooms out to sequencing and incentives when the room gets lost in local detail",
        },
        "provocative": {
            "opening": "uses sharp framing to expose lazy assumptions early",
            "debate": "intentionally stress-tests weak spots before offering synthesis",
            "cadence": "punchy, contrast-heavy, and willing to sound uncomfortable",
            "signature": "uses one sharp comparison to break stale consensus",
        },
        "concise": {
            "opening": "keeps arguments compact and avoids filler or throat-clearing",
            "debate": "prefers one strong point over five diluted ones",
            "cadence": "lean and compressed, with almost no filler",
            "signature": "delivers one high-signal point, then moves on instead of repeating it",
        },
    }

    def generate(self, profile: PersonaProfileRequest) -> GeneratedPersona:
        name = self._resolve_name(profile)
        persona_id = self._slugify(name)
        profession = self._clean_sentence(profile.profession)
        personality = self._clean_sentence(profile.personality)
        debate_style = self._clean_sentence(profile.debate_style)
        owner_notes = (profile.free_text or "").strip()

        personality_hint = self._select_personality_hint(personality)
        style_hint = self._select_style_hint(debate_style)
        description = f"{profession} lens with a {personality.lower()} temperament and a {debate_style.lower()} debate style."

        content = "\n".join(
            [
                f"# {name}",
                f"> {description}",
                "",
                "## Your Role",
                (
                    f"You are the user's debate alter ego. You reason like a {profession.lower()} and show up as "
                    f"someone who is {personality.lower()}. In arguments, you stay {debate_style.lower()}."
                ),
                (
                    f"Your main job is to make the user's real priorities legible: {personality_hint['priority']}. "
                    f"You should sound human, sharp, and internally consistent rather than generic."
                ),
                "",
                "## Debating Style",
                f"- Opening move: {style_hint['opening']}.",
                f"- Core behavior: {personality_hint['style']}.",
                f"- During disagreement: {style_hint['debate']}.",
                "- Prefer concrete trade-offs, implementation consequences, and plain language over vague abstractions.",
                "",
                "## Voice Signals",
                f"- Overall tone: {personality_hint['voice']}.",
                f"- Sentence rhythm: {style_hint['cadence']}.",
                f"- Signature move: {style_hint['signature']}.",
                "- Do not flatten into generic assistant wording or sterile corporate filler.",
                "",
                "## Core Principles",
                f"- Protect the lens of a {profession.lower()} even when the room gets abstract.",
                f"- Keep the emotional tone aligned with a {personality.lower()} person, not a sterile assistant.",
                f"- Default to a {debate_style.lower()} rhythm unless the situation clearly calls for something else.",
                "",
                "## Blind Spots To Watch",
                f"- Risk: {personality_hint['risk']}.",
                "- If the user's stated context conflicts with your instinct, follow the user's context.",
                "- Do not invent background facts about the user that were not provided.",
                "",
                "## User Notes",
                owner_notes
                or "- No extra notes were provided. Infer conservatively from the survey only.",
            ]
        ).strip()

        return GeneratedPersona(
            persona_id=persona_id,
            name=name,
            description=description,
            content=content,
        )

    def _resolve_name(self, profile: PersonaProfileRequest) -> str:
        raw = (profile.persona_name or "").strip()
        if raw:
            return raw
        profession = profile.profession.strip() or "Debater"
        return f"{profession.title()} Debate Self"

    def _slugify(self, text: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
        return slug or "generated_persona"

    def _select_personality_hint(self, personality: str) -> dict[str, str]:
        lowered = personality.lower()
        for key, hint in self.PERSONALITY_HINTS.items():
            if key in lowered:
                return hint
        return {
            "priority": "keep the user's priorities clear and resist low-signal argument drift",
            "style": "states a position cleanly and updates when the counterargument is actually stronger",
            "risk": "may become too generic if the user-specific context is not pulled forward",
            "voice": "clear, human, and distinct from generic assistant prose",
        }

    def _select_style_hint(self, debate_style: str) -> dict[str, str]:
        lowered = debate_style.lower()
        for key, hint in self.STYLE_HINTS.items():
            if key in lowered:
                return hint
        return {
            "opening": "starts with a clear thesis and then explains the reasoning without fluff",
            "debate": "keeps the discussion bounded and returns to the actual decision criteria",
            "cadence": "controlled and readable, with no filler for filler's sake",
            "signature": "returns to the actual decision criteria whenever the debate starts drifting",
        }

    def _clean_sentence(self, text: str) -> str:
        value = " ".join(text.strip().split())
        return value or "pragmatic"
