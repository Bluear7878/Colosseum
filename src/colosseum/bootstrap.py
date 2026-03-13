from __future__ import annotations

from functools import lru_cache

from colosseum.services.budget import BudgetManager
from colosseum.services.context_bundle import ContextBundleService
from colosseum.services.debate import DebateEngine
from colosseum.services.judge import JudgeService
from colosseum.services.normalizers import ResponseNormalizer
from colosseum.services.orchestrator import ColosseumOrchestrator
from colosseum.services.provider_runtime import ProviderRuntimeService
from colosseum.services.report_synthesizer import ReportSynthesizer
from colosseum.services.repository import FileRunRepository


@lru_cache(maxsize=1)
def get_orchestrator() -> ColosseumOrchestrator:
    budget_manager = BudgetManager()
    normalizer = ResponseNormalizer()
    repository = FileRunRepository()
    context_service = ContextBundleService()
    provider_runtime = ProviderRuntimeService(budget_manager=budget_manager)
    judge_service = JudgeService(
        budget_manager=budget_manager,
        provider_runtime=provider_runtime,
    )
    debate_engine = DebateEngine(
        budget_manager=budget_manager,
        normalizer=normalizer,
        provider_runtime=provider_runtime,
    )
    report_synthesizer = ReportSynthesizer(provider_runtime=provider_runtime)
    return ColosseumOrchestrator(
        repository=repository,
        context_service=context_service,
        debate_engine=debate_engine,
        judge_service=judge_service,
        budget_manager=budget_manager,
        normalizer=normalizer,
        provider_runtime=provider_runtime,
        report_synthesizer=report_synthesizer,
    )
