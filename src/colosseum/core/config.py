from pathlib import Path


ARTIFACT_ROOT = Path(".colosseum/runs")
STATE_ROOT = Path(".colosseum/state")
PROVIDER_QUOTA_PATH = STATE_ROOT / "provider_quotas.json"
PLAN_SCHEMA_VERSION = "1.0"
ROUND_SEQUENCE = (
    "critique",
    "rebuttal",
    "synthesis",
    "final_comparison",
    "targeted_revision",
)
MAX_CONTEXT_PROMPT_CHARS = 28000
MAX_DEBATE_SUMMARY_CHARS = 320
MAX_DEBATE_MEMORY_CHARS = 480
MAX_DEBATE_PEER_SUMMARIES = 3
PROMPT_BUDGET_TRUNCATION_MARKER = "\n...[TRUNCATED FOR PROMPT BUDGET]"
MIN_EVIDENCE_SUPPORT_TO_FINALIZE = 0.6
LOW_EVIDENCE_SUPPORT_THRESHOLD = 0.45
BASE_EVIDENCE_POLICY = (
    "Evidence-first rule: ground claims in the frozen context bundle, explicit source evidence, "
    "or clearly labeled inference. If evidence is missing or ambiguous, say so directly and reduce confidence."
)
SEARCH_ENCOURAGED_POLICY = (
    "Internet search is encouraged when the frozen bundle is incomplete, stale, or insufficient. "
    "If your provider supports web search or browsing, prefer authoritative sources and clearly distinguish fetched evidence from frozen-bundle evidence. "
    "If browsing is unavailable, say so and do not fill gaps from memory."
)
SEARCH_DISABLED_POLICY = (
    "Do not fill evidence gaps from memory. If the frozen bundle is insufficient and you are not using external search, "
    "state that limitation explicitly and keep confidence low."
)


def build_evidence_policy(encourage_internet_search: bool) -> str:
    extra = SEARCH_ENCOURAGED_POLICY if encourage_internet_search else SEARCH_DISABLED_POLICY
    return f"{BASE_EVIDENCE_POLICY} {extra}"


EVIDENCE_POLICY = build_evidence_policy(False)

# Depth profiles: map depth (1-5) to judge behavior overrides.
# Keys: min_novelty_threshold, convergence_threshold, minimum_confidence_to_stop
DEPTH_PROFILES = {
    1: {  # Quick — single round, judge eager to finalize
        "min_novelty_threshold": 0.05,
        "convergence_threshold": 0.40,
        "minimum_confidence_to_stop": 0.55,
    },
    2: {  # Brief — two rounds, moderate thresholds
        "min_novelty_threshold": 0.10,
        "convergence_threshold": 0.55,
        "minimum_confidence_to_stop": 0.65,
    },
    3: {  # Standard — balanced debate
        "min_novelty_threshold": 0.18,
        "convergence_threshold": 0.75,
        "minimum_confidence_to_stop": 0.78,
    },
    4: {  # Thorough — relaxed thresholds, more exploration
        "min_novelty_threshold": 0.25,
        "convergence_threshold": 0.85,
        "minimum_confidence_to_stop": 0.85,
    },
    5: {  # Deep Dive — full sequence, very hard to stop early
        "min_novelty_threshold": 0.30,
        "convergence_threshold": 0.92,
        "minimum_confidence_to_stop": 0.92,
    },
}
