"""Shared prompt contracts used across debate and judge surfaces."""

from __future__ import annotations


DEBATE_BEHAVIOR_GUARDRAIL = (
    "Do not flatter the judge, beg for selection, claim victory without support, or invent agreement. "
    "No bluffing, no fabricated evidence, no fake certainty, and no strategic praise."
)

DEBATE_HONESTY_GUARDRAIL = (
    "Do not lie, invent evidence, fake consensus, or claim that a peer agreed when they did not."
)

JUDGE_RECORD_ONLY_GUARDRAIL = (
    "Judge ONLY from the submitted plans and debate record below. "
    "Do not browse, do not ask for external search, and do not mention browsing limitations. "
    "Treat debater-submitted citations, concessions, and uncertainties as the full record for this decision."
)
