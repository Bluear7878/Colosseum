from pathlib import Path


ARTIFACT_ROOT = Path(".colosseum/runs")
REVIEW_REPORT_ROOT = Path(".colosseum/reviews")
STATE_ROOT = Path(".colosseum/state")
PROVIDER_QUOTA_PATH = STATE_ROOT / "provider_quotas.json"
LOCAL_RUNTIME_SETTINGS_PATH = STATE_ROOT / "local_runtime.json"
LOCAL_RUNTIME_PID_PATH = STATE_ROOT / "local_runtime.pid"
LOCAL_RUNTIME_LOG_PATH = STATE_ROOT / "local_runtime.log"
DEFAULT_LOCAL_RUNTIME_HOST = "127.0.0.1:11435"
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
        "min_rounds": 1,
    },
    2: {  # Brief — two rounds, moderate thresholds
        "min_novelty_threshold": 0.10,
        "convergence_threshold": 0.55,
        "minimum_confidence_to_stop": 0.65,
        "min_rounds": 1,
    },
    3: {  # Standard — balanced debate
        "min_novelty_threshold": 0.18,
        "convergence_threshold": 0.75,
        "minimum_confidence_to_stop": 0.78,
        "min_rounds": 1,
    },
    4: {  # Thorough — relaxed thresholds, more exploration
        "min_novelty_threshold": 0.25,
        "convergence_threshold": 0.85,
        "minimum_confidence_to_stop": 0.85,
        "min_rounds": 2,
    },
    5: {  # Deep Dive — full sequence, very hard to stop early
        "min_novelty_threshold": 0.30,
        "convergence_threshold": 0.92,
        "minimum_confidence_to_stop": 0.92,
        "min_rounds": 2,
    },
}

# ── Review phase configuration ──────────────────────────────────────────
REVIEW_PHASE_CONFIG = {
    "project_rules": {
        "label": "Phase A: Project Rules Compliance",
        "task_title_prefix": "[Rules]",
        "criteria": [
            "Does the code follow the project's coding standards and conventions?",
            "Are naming conventions consistent with the project style?",
            "Does the code respect project-specific rules (CLAUDE.md, .editorconfig, linter configs)?",
            "Are imports organized according to project guidelines?",
        ],
        "depth_override": None,
    },
    "implementation": {
        "label": "Phase B: Implementation Correctness",
        "task_title_prefix": "[Impl]",
        "criteria": [
            "Does the code correctly implement the intended functionality?",
            "Are edge cases handled properly?",
            "Is error handling comprehensive and appropriate?",
            "Are there any logical bugs or off-by-one errors?",
            "Do the data types and structures match the requirements?",
        ],
        "depth_override": None,
    },
    "architecture": {
        "label": "Phase C: Architecture & Design",
        "task_title_prefix": "[Arch]",
        "criteria": [
            "Does the design follow established architectural patterns in the codebase?",
            "Is the code modular and well-separated (single responsibility)?",
            "Are dependencies managed properly (no circular deps, minimal coupling)?",
            "Is the code extensible for foreseeable requirements?",
            "Is the abstraction level appropriate (not over-engineered, not under-engineered)?",
        ],
        "depth_override": None,
    },
    "security_performance": {
        "label": "Phase D: Security & Performance",
        "task_title_prefix": "[SecPerf]",
        "criteria": [
            "Are there any security vulnerabilities (injection, XSS, auth bypass)?",
            "Is sensitive data handled safely (no hardcoded secrets, proper encryption)?",
            "Are there memory leaks or resource management issues?",
            "Are there obvious performance bottlenecks (N+1 queries, unnecessary allocations)?",
            "Is concurrency handled correctly (race conditions, deadlocks)?",
        ],
        "depth_override": None,
    },
    "test_coverage": {
        "label": "Phase E: Test Coverage",
        "task_title_prefix": "[Test]",
        "criteria": [
            "Are there sufficient unit tests for the new/changed code?",
            "Do tests cover edge cases and error paths?",
            "Are tests well-structured and maintainable?",
            "Is there appropriate integration/E2E test coverage?",
            "Are test fixtures and mocks used appropriately?",
        ],
        "depth_override": None,
    },
    "red_team": {
        "label": "Phase F: Red Team / Adversarial",
        "task_title_prefix": "[RedTeam]",
        "criteria": [
            "Can adversarial or malformed input crash the system or cause undefined behavior?",
            "Are authentication and authorization checks bypassable under edge-case conditions?",
            "Can error messages, stack traces, or logs leak sensitive internal information?",
            "Are there race conditions or TOCTOU vulnerabilities exploitable under concurrent access?",
            "Can dependency confusion, supply-chain, or deserialization attacks be leveraged?",
            "Is it possible to escalate privileges or access resources beyond intended scope?",
        ],
        "depth_override": None,
    },
}
