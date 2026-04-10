"""Topic-adherence helpers used by the judge and debate services.

These utilities exist because the per-round agenda for round N+1 used to be
derived purely from round N's `key_disagreements` / `unresolved_questions`,
with no check that those leftover items were still about the original task.
A meta-complaint such as "Agent X failed to provide a plan summary" could
become the entire agenda for the next round, dragging the whole debate
off-topic. See ``docs/gotchas.md`` for the full incident write-up.

The helpers here are intentionally pure functions of the run state so they
can be unit-tested in isolation and reused from any service that touches
agenda or summary text.
"""

from __future__ import annotations

import re

from colosseum.core.models import ExperimentRun


# Below this fraction of "topic-vocabulary" tokens, a candidate agenda or
# message is treated as drifting off the original task. Tuned against the
# replayed offending runs in `.colosseum/runs/` (round 2/3 meta-complaints
# scored ~0.0; legitimate on-topic critiques scored >= 0.20).
TOPIC_OVERLAP_DRIFT_THRESHOLD = 0.15

# Phrases that almost always indicate a meta-debate about a peer agent's
# behavior rather than the actual task. Matched as substrings on the
# lowercased text so they catch both English and Korean variants without
# needing per-language stopword lists.
META_DRIFT_MARKERS: tuple[str, ...] = (
    "failed to provide",
    "provided no",
    "no plan summary",
    "no summary provided",
    "empty response",
    "did not submit",
    "did not provide",
    "no plan was provided",
    "zero evidence of a strategy",
    "제공하지 않",
    "제공하지 못",
    "제공되지 않",
    "플랜이 없",
    "플랜이 비",
    "응답이 비",
    "빈 컨텍스트",
    "빈 응답",
    "요약이 없",
    "요약을 제공",
)

_TOKEN_RE = re.compile(r"[\w']{2,}", re.UNICODE)


# Tokens that show up in essentially every plan/summary regardless of topic.
# Stripping them keeps the overlap ratio meaningful — otherwise a meta
# critique like "Agent X failed to provide a plan summary" scores a fake
# overlap with words that exist in every plan template.
_PROCESS_NOISE_TOKENS: frozenset[str] = frozenset(
    {
        # English process / debate vocabulary
        "plan", "plans", "summary", "summaries", "agent", "agents",
        "team", "teams", "response", "responses", "answer", "answers",
        "message", "messages", "round", "rounds", "issue", "issues",
        "point", "points", "judge", "judges", "judging", "debate", "debates",
        "evidence", "claim", "claims", "argument", "arguments",
        "failed", "failure", "fails", "provide", "provided", "providing",
        "approach", "approaches", "strategy", "strategies", "step", "steps",
        # English connective stopwords
        "the", "and", "but", "with", "for", "from", "that", "this", "these",
        "those", "any", "all", "not", "without", "into", "onto", "over",
        "under", "about", "into", "out", "your", "our", "their", "his",
        "her", "its", "they", "them", "you", "we", "us", "is", "are", "was",
        "were", "be", "been", "being", "have", "has", "had", "do", "does",
        "did", "of", "to", "in", "on", "by", "as", "an", "at", "or", "if",
        "it", "so",
    }
)


def _tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in _TOKEN_RE.findall(text or "")]


def topic_token_set(run: ExperimentRun) -> set[str]:
    """Build the canonical "what is this debate actually about" vocabulary.

    Drawn from the task spec and the opening plan summaries (which capture
    the agreed problem framing before any drift could happen). Plan
    *critiques* are deliberately excluded so we don't pollute the topic set
    with the very meta-complaints we want to filter out.
    """
    parts: list[str] = [
        run.task.title or "",
        run.task.problem_statement or "",
        " ".join(run.task.success_criteria or []),
        " ".join(run.task.constraints or []),
    ]
    if run.task.desired_output:
        parts.append(run.task.desired_output)
    for plan in run.plans:
        parts.append(plan.summary or "")
    return {tok for tok in _tokenize(" ".join(parts)) if tok not in _PROCESS_NOISE_TOKENS}


def topic_overlap(text: str, tokens: set[str]) -> float:
    """Fraction of content tokens in *text* that appear in *tokens*.

    Process-noise tokens (the words every plan summary contains regardless
    of topic) are excluded from both the candidate text and the topic set
    so a meta-complaint can't fake an overlap with generic vocabulary.
    """
    words = [tok for tok in _tokenize(text) if tok not in _PROCESS_NOISE_TOKENS]
    if not words or not tokens:
        return 0.0
    matched = sum(1 for word in words if word in tokens)
    return matched / len(words)


def has_meta_drift_marker(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in META_DRIFT_MARKERS)


def is_drifting(
    text: str,
    run: ExperimentRun,
    tokens: set[str] | None = None,
    threshold: float = TOPIC_OVERLAP_DRIFT_THRESHOLD,
) -> bool:
    """Return True when *text* looks off-topic for the current run."""
    if not text or not text.strip():
        return True
    if has_meta_drift_marker(text):
        return True
    token_set = tokens if tokens is not None else topic_token_set(run)
    if not token_set:
        return False
    return topic_overlap(text, token_set) < threshold


def anchor_question(question: str, topic: str) -> str:
    """Wrap *question* so it explicitly references the original *topic*.

    Idempotent: if the topic is already mentioned, the question is returned
    unchanged so we don't double-stamp anchored questions across rounds.
    """
    question = (question or "").strip()
    topic = (topic or "").strip()
    if not topic:
        return question
    if topic.lower() in question.lower():
        return question
    if not question:
        return f"How should the team make progress on '{topic}'?"
    return f"In the context of '{topic}': {question}"
