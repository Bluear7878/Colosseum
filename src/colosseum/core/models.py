from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskType(StrEnum):
    CODEBASE_IMPLEMENTATION = "codebase_implementation"
    RESEARCH_DESIGN = "research_design"
    GENERAL_DEBATE = "general_debate"
    POLICY_ANALYSIS = "policy_analysis"
    TECHNICAL_REVIEW = "technical_review"
    PRODUCT_STRATEGY = "product_strategy"
    OPEN_DISCUSSION = "open_discussion"


class ContextSourceKind(StrEnum):
    INLINE_TEXT = "inline_text"
    INLINE_IMAGE = "inline_image"
    LOCAL_FILE = "local_file"
    LOCAL_IMAGE = "local_image"
    LOCAL_DIRECTORY = "local_directory"
    EXTERNAL_REFERENCE = "external_reference"


class ProviderType(StrEnum):
    MOCK = "mock"
    COMMAND = "command"
    CLAUDE_CLI = "claude_cli"
    CODEX_CLI = "codex_cli"
    GEMINI_CLI = "gemini_cli"
    OLLAMA = "ollama"
    HUGGINGFACE_LOCAL = "huggingface_local"


class BillingTier(StrEnum):
    PAID = "paid"
    FREE = "free"


class JudgeMode(StrEnum):
    AUTOMATED = "automated"
    AI = "ai"
    HUMAN = "human"


class RunStatus(StrEnum):
    PENDING = "pending"
    PLANNING = "planning"
    DEBATING = "debating"
    AWAITING_HUMAN_JUDGE = "awaiting_human_judge"
    COMPLETED = "completed"
    FAILED = "failed"


class RoundType(StrEnum):
    CRITIQUE = "critique"
    REBUTTAL = "rebuttal"
    SYNTHESIS = "synthesis"
    FINAL_COMPARISON = "final_comparison"
    TARGETED_REVISION = "targeted_revision"


class JudgeActionType(StrEnum):
    CONTINUE_DEBATE = "continue_debate"
    FINALIZE = "finalize"
    REQUEST_REVISION = "request_revision"
    HUMAN_REQUIRED = "human_required"


class VerdictType(StrEnum):
    WINNER = "winner"
    MERGED = "merged"
    TARGETED_REVISION = "targeted_revision"
    NO_DECISION = "no_decision"


class PaidExhaustionAction(StrEnum):
    FAIL = "fail"
    SWITCH_TO_FREE = "switch_to_free"
    WAIT_FOR_RESET = "wait_for_reset"


class RuntimeEventType(StrEnum):
    QUOTA_SWITCHED = "quota_switched"
    WAITING_FOR_RESET = "waiting_for_reset"
    QUOTA_BLOCKED = "quota_blocked"
    QUOTA_RESET = "quota_reset"


class UsageMetrics(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0

    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, other: "UsageMetrics") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.estimated_cost_usd += other.estimated_cost_usd


class ProviderPricing(BaseModel):
    prompt_cost_per_1k_tokens: float = 0.0
    completion_cost_per_1k_tokens: float = 0.0


class ProviderConfig(BaseModel):
    type: ProviderType = ProviderType.MOCK
    model: str = "mock-default"
    command: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int | None = 300
    pricing: ProviderPricing = Field(default_factory=ProviderPricing)
    ollama_model: str | None = None  # only used when type=ollama
    hf_model: str | None = None  # only used when type=huggingface_local
    billing_tier: BillingTier | None = None
    quota_key: str | None = None


class AgentConfig(BaseModel):
    agent_id: str
    display_name: str
    specialty: str | None = None
    system_prompt: str | None = None
    provider: ProviderConfig
    persona_id: str | None = None
    persona_content: str | None = None


class TaskSpec(BaseModel):
    title: str
    problem_statement: str
    task_type: TaskType = TaskType.CODEBASE_IMPLEMENTATION
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    desired_output: str | None = None


class ContextSourceInput(BaseModel):
    source_id: str
    kind: ContextSourceKind
    label: str
    path: str | None = None
    uri: str | None = None
    content: str | None = None
    description: str | None = None
    media_type: str | None = None
    max_chars: int = 12000
    max_files: int = 25


class ContextFragment(BaseModel):
    fragment_id: str = Field(default_factory=lambda: str(uuid4()))
    label: str
    path: str | None = None
    content: str
    checksum: str
    truncated: bool = False
    media_type: str | None = None
    is_binary: bool = False
    size_bytes: int | None = None
    inline_data: str | None = None


class FrozenContextSource(BaseModel):
    source_id: str
    kind: ContextSourceKind
    label: str
    description: str | None = None
    resolved_path: str | None = None
    resolved_uri: str | None = None
    checksum: str
    fragments: list[ContextFragment] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FrozenContextBundle(BaseModel):
    bundle_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    manifest_version: str = "1.0"
    sources: list[FrozenContextSource]
    aggregate_checksum: str
    bundle_summary: str


class RiskItem(BaseModel):
    title: str
    severity: Literal["low", "medium", "high"]
    mitigation: str

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity_case(cls, v: str) -> str:
        if isinstance(v, str):
            return v.lower()
        return v

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: object) -> Literal["low", "medium", "high"]:
        normalized = str(value or "medium").strip().lower()
        aliases = {
            "med": "medium",
            "moderate": "medium",
            "critical": "high",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"low", "medium", "high"}:
            return "medium"
        return normalized


class PlanDocument(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str
    display_name: str
    created_at: datetime = Field(default_factory=utc_now)
    schema_version: str = "1.0"
    summary: str
    evidence_basis: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    architecture: list[str] = Field(default_factory=list)
    implementation_strategy: list[str] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    trade_offs: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    raw_response: str | None = None
    usage: UsageMetrics = Field(default_factory=UsageMetrics)


class PlanEvaluation(BaseModel):
    plan_id: str
    scores: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    overall_score: float = 0.0


class DebateClaim(BaseModel):
    claim_id: str = Field(default_factory=lambda: str(uuid4()))
    category: str
    text: str
    target_plan_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class AgentMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    round_index: int
    round_type: RoundType
    agent_id: str
    plan_id: str
    content: str
    critique_points: list[DebateClaim] = Field(default_factory=list)
    defense_points: list[DebateClaim] = Field(default_factory=list)
    concessions: list[str] = Field(default_factory=list)
    hybrid_suggestions: list[str] = Field(default_factory=list)
    referenced_plan_ids: list[str] = Field(default_factory=list)
    novelty_score: float = 1.0
    repetitive: bool = False
    usage: UsageMetrics = Field(default_factory=UsageMetrics)


class RoundSummary(BaseModel):
    agreements: list[str] = Field(default_factory=list)
    key_disagreements: list[str] = Field(default_factory=list)
    strongest_arguments: list[str] = Field(default_factory=list)
    hybrid_opportunities: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    moderator_note: str = ""


class DebateAgenda(BaseModel):
    agenda_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    question: str
    why_it_matters: str = ""
    focus_areas: list[str] = Field(default_factory=list)
    source_plan_ids: list[str] = Field(default_factory=list)


class AdoptedArgument(BaseModel):
    agent_id: str
    display_name: str
    claim_kind: Literal["critique", "defense", "concession", "hybrid"]
    summary: str
    target_plan_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    adoption_reason: str = ""
    source_message_id: str | None = None


class RoundAdjudication(BaseModel):
    agenda_title: str = ""
    agenda_question: str = ""
    adopted_arguments: list[AdoptedArgument] = Field(default_factory=list)
    resolution: str = ""
    unresolved_points: list[str] = Field(default_factory=list)
    judge_note: str = ""
    moved_to_next_issue: bool = True


class DebateRound(BaseModel):
    round_id: str = Field(default_factory=lambda: str(uuid4()))
    index: int
    round_type: RoundType
    purpose: str
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime = Field(default_factory=utc_now)
    agenda: DebateAgenda | None = None
    messages: list[AgentMessage] = Field(default_factory=list)
    summary: RoundSummary = Field(default_factory=RoundSummary)
    adjudication: RoundAdjudication | None = None
    usage: UsageMetrics = Field(default_factory=UsageMetrics)


class JudgeConfig(BaseModel):
    mode: JudgeMode = JudgeMode.AUTOMATED
    provider: ProviderConfig | None = None
    minimum_confidence_to_stop: float = 0.78
    prefer_merged_plan_on_close_scores: bool = True


class JudgeDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    mode: JudgeMode
    action: JudgeActionType
    reasoning: str
    confidence: float
    disagreement_level: float
    expected_value_of_next_round: float
    next_round_type: RoundType | None = None
    focus_areas: list[str] = Field(default_factory=list)
    budget_pressure: float = 0.0
    agenda: DebateAgenda | None = None


class JudgeVerdict(BaseModel):
    verdict_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    judge_mode: JudgeMode
    verdict_type: VerdictType
    winning_plan_ids: list[str] = Field(default_factory=list)
    synthesized_plan: PlanDocument | None = None
    rationale: str
    selected_strengths: list[str] = Field(default_factory=list)
    rejected_risks: list[str] = Field(default_factory=list)
    stop_reason: str
    confidence: float


class PaidProviderPolicy(BaseModel):
    on_exhaustion: PaidExhaustionAction = PaidExhaustionAction.FAIL
    fallback_provider: ProviderConfig | None = None
    wait_for_reset_max_seconds: int | None = None


class BudgetPolicy(BaseModel):
    max_rounds: int = 3
    min_rounds: int = 1
    total_token_budget: int = 120000
    per_round_token_limit: int = 12000
    per_agent_message_limit: int = 1
    min_novelty_threshold: float = 0.18
    convergence_threshold: float = 0.75
    planning_timeout_seconds: int = 360
    round_timeout_seconds: int = 300
    late_round_timeout_factor: float = 0.8
    min_round_timeout_seconds: int = 120
    per_round_timeouts: list[int] = Field(default_factory=list)

    def timeout_for_round(self, round_index: int) -> int:
        """Return the timeout in seconds for a given debate round (1-based).

        Values in *per_round_timeouts* take precedence.  A stored value of
        ``0`` means **no limit**.  When no explicit per-round value exists
        the legacy decay formula is used; *round_timeout_seconds* of ``0``
        also means no limit.
        """
        if self.per_round_timeouts and round_index <= len(self.per_round_timeouts):
            return self.per_round_timeouts[round_index - 1]  # 0 = no limit
        if self.round_timeout_seconds == 0:
            return 0  # no limit
        t = self.round_timeout_seconds * (self.late_round_timeout_factor ** (round_index - 1))
        if self.min_round_timeout_seconds == 0:
            return int(t)
        return max(self.min_round_timeout_seconds, int(t))


class BudgetLedger(BaseModel):
    total: UsageMetrics = Field(default_factory=UsageMetrics)
    by_actor: dict[str, UsageMetrics] = Field(default_factory=dict)
    by_round: dict[str, UsageMetrics] = Field(default_factory=dict)
    exhausted: bool = False
    stop_reason: str | None = None

    def record(self, actor_id: str, usage: UsageMetrics, round_index: int | None = None) -> None:
        self.total.add(usage)
        actor_usage = self.by_actor.setdefault(actor_id, UsageMetrics())
        actor_usage.add(usage)
        if round_index is not None:
            round_key = str(round_index)
            round_usage = self.by_round.setdefault(round_key, UsageMetrics())
            round_usage.add(usage)


class PlanSummaryCard(BaseModel):
    plan_id: str
    display_name: str
    summary: str
    evidence_basis: list[str]
    strengths: list[str]
    weaknesses: list[str]
    overall_score: float = 0.0


class HumanJudgePacket(BaseModel):
    generated_at: datetime = Field(default_factory=utc_now)
    plan_cards: list[PlanSummaryCard] = Field(default_factory=list)
    last_round_summary: RoundSummary | None = None
    key_disagreements: list[str] = Field(default_factory=list)
    strongest_arguments: list[str] = Field(default_factory=list)
    recommended_action: str
    available_actions: list[str] = Field(default_factory=list)
    suggested_agenda: DebateAgenda | None = None


class ProviderQuotaState(BaseModel):
    quota_key: str
    label: str
    billing_tier: BillingTier = BillingTier.PAID
    cycle_token_limit: int = 0
    remaining_tokens: int = 0
    reset_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class ProviderQuotaBatchUpdate(BaseModel):
    states: list[ProviderQuotaState] = Field(default_factory=list)


class PersonaProfileRequest(BaseModel):
    persona_name: str | None = None
    profession: str
    personality: str
    debate_style: str
    free_text: str | None = None


class GeneratedPersona(BaseModel):
    persona_id: str
    name: str
    description: str
    content: str


class RuntimeEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    event_type: RuntimeEventType
    actor_id: str
    actor_label: str
    provider_label: str | None = None
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FinalReport(BaseModel):
    executive_summary: str
    key_conclusions: list[str] = Field(default_factory=list)
    debate_highlights: list[str] = Field(default_factory=list)
    verdict_explanation: str = ""
    recommendations: list[str] = Field(default_factory=list)


class ExperimentRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    encourage_internet_search: bool = False
    response_language: str = "auto"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    status: RunStatus = RunStatus.PENDING
    task: TaskSpec
    context_bundle: FrozenContextBundle | None = None
    agents: list[AgentConfig]
    judge: JudgeConfig
    paid_provider_policy: PaidProviderPolicy = Field(default_factory=PaidProviderPolicy)
    budget_policy: BudgetPolicy = Field(default_factory=BudgetPolicy)
    budget_ledger: BudgetLedger = Field(default_factory=BudgetLedger)
    plans: list[PlanDocument] = Field(default_factory=list)
    plan_evaluations: list[PlanEvaluation] = Field(default_factory=list)
    debate_rounds: list[DebateRound] = Field(default_factory=list)
    judge_trace: list[JudgeDecision] = Field(default_factory=list)
    runtime_events: list[RuntimeEvent] = Field(default_factory=list)
    verdict: JudgeVerdict | None = None
    final_report: FinalReport | None = None
    stop_reason: str | None = None
    human_judge_packet: HumanJudgePacket | None = None
    error_message: str | None = None


class RunListItem(BaseModel):
    run_id: str
    project_name: str
    task_title: str
    status: RunStatus
    judge_mode: JudgeMode
    updated_at: datetime
    verdict_type: VerdictType | None = None
    total_tokens: int = 0


class RunCreateRequest(BaseModel):
    project_name: str = "Colosseum"
    encourage_internet_search: bool = False
    response_language: str = "auto"
    task: TaskSpec
    context_sources: list[ContextSourceInput] = Field(default_factory=list)
    agents: list[AgentConfig]
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    paid_provider_policy: PaidProviderPolicy = Field(default_factory=PaidProviderPolicy)
    budget_policy: BudgetPolicy = Field(default_factory=BudgetPolicy)


class HumanJudgeActionRequest(BaseModel):
    action: Literal["request_round", "select_winner", "merge_plans", "request_revision"]
    round_type: RoundType | None = None
    winning_plan_ids: list[str] = Field(default_factory=list)
    instructions: str | None = None
