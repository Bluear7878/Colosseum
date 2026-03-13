import asyncio
import base64

from colosseum.core.models import (
    AgentConfig,
    ContextSourceInput,
    ContextSourceKind,
    JudgeConfig,
    JudgeMode,
    ProviderConfig,
    ProviderType,
    RunCreateRequest,
    TaskSpec,
)
from colosseum.providers.cli_wrapper import build_prompt
from colosseum.services.budget import BudgetManager
from colosseum.services.context_bundle import ContextBundleService
from colosseum.services.debate import DebateEngine
from colosseum.services.judge import JudgeService
from colosseum.services.normalizers import ResponseNormalizer
from colosseum.services.orchestrator import ColosseumOrchestrator
from colosseum.services.provider_runtime import ProviderRuntimeService
from colosseum.services.repository import FileRunRepository


def build_orchestrator(tmp_path):
    budget_manager = BudgetManager()
    normalizer = ResponseNormalizer()
    repository = FileRunRepository(root=tmp_path)
    context_service = ContextBundleService()
    provider_runtime = ProviderRuntimeService(
        budget_manager=budget_manager,
        quota_path=tmp_path / "provider_quotas.json",
    )
    judge_service = JudgeService(
        budget_manager=budget_manager,
        provider_runtime=provider_runtime,
    )
    debate_engine = DebateEngine(
        budget_manager=budget_manager,
        normalizer=normalizer,
        provider_runtime=provider_runtime,
    )
    return ColosseumOrchestrator(
        repository=repository,
        context_service=context_service,
        debate_engine=debate_engine,
        judge_service=judge_service,
        budget_manager=budget_manager,
        normalizer=normalizer,
        provider_runtime=provider_runtime,
    )


def test_inline_image_freeze_keeps_bytes_out_of_prompt():
    service = ContextBundleService()
    inline_data = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")
    bundle = service.freeze(
        [
            ContextSourceInput(
                source_id="vision",
                kind=ContextSourceKind.INLINE_IMAGE,
                label="Reference screenshot",
                content=inline_data,
                media_type="image/png",
            )
        ]
    )

    rendered = service.render_for_prompt(bundle)
    image_inputs = service.extract_image_inputs(bundle)

    assert "data:image/png" not in rendered
    assert "Binary attachment omitted from text prompt" in rendered
    assert len(image_inputs) == 1
    assert image_inputs[0]["inline_data"] == inline_data
    assert "shared image" in service.summarize_image_inputs(bundle)


def test_cli_wrapper_prompt_mentions_visual_context_without_embedding_data():
    inline_data = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")
    prompt = build_prompt(
        {
            "operation": "plan",
            "instructions": "Review the task.",
            "metadata": {
                "image_inputs": [
                    {
                        "label": "reference.png",
                        "media_type": "image/png",
                        "checksum": "abcdef0123456789",
                        "size_bytes": 2048,
                        "inline_data": inline_data,
                    }
                ]
            },
        }
    )

    assert "Shared visual context is available" in prompt
    assert "reference.png" in prompt
    assert inline_data not in prompt


def test_orchestrator_handles_image_context(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    inline_data = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")
    request = RunCreateRequest(
        project_name="Colosseum",
        task=TaskSpec(
            title="Vision debate",
            problem_statement="Review the same image and debate the best interpretation strategy.",
        ),
        context_sources=[
            ContextSourceInput(
                source_id="topic",
                kind=ContextSourceKind.INLINE_TEXT,
                label="Topic",
                content="The same screenshot should inform every plan.",
            ),
            ContextSourceInput(
                source_id="img",
                kind=ContextSourceKind.INLINE_IMAGE,
                label="UI screenshot",
                content=inline_data,
                media_type="image/png",
            ),
        ],
        agents=[
            AgentConfig(
                agent_id="agent-a",
                display_name="Agent A",
                provider=ProviderConfig(type=ProviderType.MOCK, model="mock-a"),
            ),
            AgentConfig(
                agent_id="agent-b",
                display_name="Agent B",
                provider=ProviderConfig(type=ProviderType.MOCK, model="mock-b"),
            ),
        ],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
    )

    run = asyncio.run(orchestrator.create_run(request))

    assert run.status.value == "completed"
    assert run.context_bundle is not None
    assert len(orchestrator.context_service.extract_image_inputs(run.context_bundle)) == 1
    assert any("visual evidence" in " ".join(plan.assumptions).lower() for plan in run.plans)


def test_cli_wrapper_prompt_mentions_search_policy_when_present():
    prompt = build_prompt(
        {
            "operation": "plan",
            "instructions": "Review the task.",
            "metadata": {
                "search_policy": "Internet search is encouraged when the frozen bundle is insufficient.",
            },
        }
    )

    assert "Search policy:" in prompt
    assert "Internet search is encouraged" in prompt


def test_cli_wrapper_persona_prompt_enforces_voice_without_relaxing_guardrails():
    prompt = build_prompt(
        {
            "operation": "debate",
            "instructions": "Respond to the other plan.",
            "metadata": {
                "persona": "Speak with clipped, ruthless confidence, but stay evidence-first.",
            },
        }
    )

    assert "VOICE CONTRACT" in prompt
    assert "diction, cadence, level of directness" in prompt
    assert (
        "JSON validity, evidence quality, and required schema always take priority over style"
        in prompt
    )
    assert "critique_points[*].text" in prompt
