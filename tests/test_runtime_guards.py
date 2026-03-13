import json
from pathlib import Path

from colosseum.core.config import MAX_CONTEXT_PROMPT_CHARS
from colosseum.core.models import (
    ContextSourceInput,
    ContextSourceKind,
    ProviderConfig,
    ProviderType,
    RiskItem,
)
from colosseum.providers.command import CommandProvider
from colosseum.providers.factory import build_provider
from colosseum.services.context_bundle import ContextBundleService
from colosseum.services.repository import FileRunRepository


def test_context_prompt_is_capped():
    service = ContextBundleService()
    large_text = "x" * (MAX_CONTEXT_PROMPT_CHARS * 2)
    bundle = service.freeze(
        [
            ContextSourceInput(
                source_id="large",
                kind=ContextSourceKind.INLINE_TEXT,
                label="Large",
                content=large_text,
            )
        ]
    )

    rendered = service.render_for_prompt(bundle)
    assert len(rendered) <= MAX_CONTEXT_PROMPT_CHARS
    assert "TRUNCATED FOR PROMPT BUDGET" in rendered or "Prompt budget applied" in rendered


def test_provider_factory_uses_selected_local_model():
    provider = build_provider(
        ProviderConfig(
            type=ProviderType.HUGGINGFACE_LOCAL,
            model="ollama:llama3.3",
        )
    )
    assert isinstance(provider, CommandProvider)
    assert "--model" in provider.command
    assert provider.command[-1] == "llama3.3"
    assert provider.env["OLLAMA_HOST"] == "127.0.0.1:11435"
    assert provider.env["COLOSSEUM_LOCAL_RUNTIME_MANAGED"] == "1"


def test_repository_loads_unique_prefix(tmp_path: Path):
    repository = FileRunRepository(root=tmp_path)
    run_dir = tmp_path / "12345678-demo"
    run_dir.mkdir(parents=True)
    payload = {
        "run_id": "12345678-demo",
        "project_name": "Colosseum",
        "created_at": "2026-03-12T00:00:00Z",
        "updated_at": "2026-03-12T00:00:00Z",
        "status": "completed",
        "task": {"title": "Prefix", "problem_statement": "Prefix load"},
        "context_bundle": None,
        "agents": [],
        "judge": {"mode": "automated"},
        "budget_policy": {},
        "budget_ledger": {},
        "plans": [],
        "plan_evaluations": [],
        "debate_rounds": [],
        "judge_trace": [],
        "verdict": None,
        "stop_reason": None,
        "human_judge_packet": None,
        "error_message": None,
    }
    (run_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")

    run = repository.load_run("12345678")
    assert run.run_id == "12345678-demo"


def test_risk_item_normalizes_severity_labels():
    assert RiskItem(title="Caps", severity="High", mitigation="Watch it").severity == "high"
    assert RiskItem(title="Alias", severity="critical", mitigation="Watch it").severity == "high"
    assert RiskItem(title="Unknown", severity="severe", mitigation="Watch it").severity == "medium"
