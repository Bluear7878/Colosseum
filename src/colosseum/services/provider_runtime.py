from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from colosseum.core.config import PROVIDER_QUOTA_PATH
from colosseum.core.models import (
    AgentConfig,
    BillingTier,
    ExperimentRun,
    PaidExhaustionAction,
    ProviderConfig,
    ProviderQuotaState,
    ProviderType,
    RuntimeEvent,
    RuntimeEventType,
    utc_now,
)
from colosseum.providers.base import ProviderQuotaExceededError, ProviderResult
from colosseum.providers.factory import build_provider
from colosseum.services.budget import BudgetManager


@dataclass
class QuotaReservation:
    quota_key: str
    reserved_tokens: int


@dataclass
class ProviderExecution:
    result: ProviderResult
    effective_provider: ProviderConfig


class ProviderRuntimeService:
    def __init__(
        self,
        budget_manager: BudgetManager,
        quota_path: Path | None = None,
    ) -> None:
        self.budget_manager = budget_manager
        self.quota_path = quota_path or PROVIDER_QUOTA_PATH
        self.quota_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def list_quota_states(self) -> list[ProviderQuotaState]:
        with self._lock:
            states = self._load_states_unlocked()
            self._save_states_unlocked(states)
            return list(states.values())

    def upsert_quota_states(self, updates: list[ProviderQuotaState]) -> list[ProviderQuotaState]:
        with self._lock:
            states = self._load_states_unlocked()
            for state in updates:
                updated = state.model_copy(deep=True)
                updated.remaining_tokens = max(0, updated.remaining_tokens)
                updated.cycle_token_limit = max(0, updated.cycle_token_limit)
                updated.updated_at = utc_now()
                states[updated.quota_key] = updated
            self._save_states_unlocked(states)
            return list(states.values())

    def validate_agents_selectable(self, agents: list[AgentConfig]) -> None:
        blocked: list[str] = []
        for agent in agents:
            reason = self.selection_block_reason(agent.provider)
            if reason:
                blocked.append(f"{agent.display_name}: {reason}")
        if blocked:
            raise ValueError("Paid quota exhausted. " + " ".join(blocked))

    def validate_provider_selectable(self, provider: ProviderConfig, label: str = "Provider") -> None:
        reason = self.selection_block_reason(provider)
        if reason:
            raise ValueError(f"{label} is not selectable because {reason}")

    def selection_block_reason(self, provider: ProviderConfig) -> str | None:
        if not self.is_paid_provider(provider):
            return None
        with self._lock:
            states = self._load_states_unlocked()
            quota_key = self.quota_key_for_provider(provider)
            if not quota_key or quota_key not in states:
                return None
            state = states[quota_key]
            if not self._is_tracked(state):
                return None
            if state.remaining_tokens > 0:
                return None
            if state.reset_at:
                return f"tracked remaining tokens are 0; reset scheduled at {state.reset_at.isoformat()}."
            return "tracked remaining tokens are 0."

    async def execute(
        self,
        run: ExperimentRun,
        actor_id: str,
        actor_label: str,
        provider_config: ProviderConfig,
        operation: str,
        instructions: str,
        metadata: dict,
        timeout_override: int | None = None,
    ) -> ProviderExecution:
        original_provider = provider_config.model_copy(deep=True)
        if timeout_override is not None:
            original_provider.timeout_seconds = timeout_override
        current_provider = original_provider.model_copy(deep=True)
        attempts = 0

        while attempts < 3:
            attempts += 1
            current_provider, reservation = await self._prepare_provider_for_call(
                run,
                actor_id,
                actor_label,
                current_provider,
                original_provider,
                operation,
                instructions,
            )
            provider = build_provider(current_provider)
            try:
                result = await provider.generate(
                    operation=operation,
                    instructions=instructions,
                    metadata=metadata,
                )
            except ProviderQuotaExceededError as exc:
                self._cancel_reservation(reservation)
                self._mark_provider_exhausted(current_provider)
                self._append_event(
                    run,
                    RuntimeEventType.QUOTA_BLOCKED,
                    actor_id=actor_id,
                    actor_label=actor_label,
                    provider_label=self.provider_label(current_provider),
                    message=str(exc) or f"{self.provider_label(current_provider)} reported quota exhaustion.",
                    metadata={"operation": operation},
                )
                current_provider = await self._recover_after_exhaustion(
                    run,
                    actor_id,
                    actor_label,
                    original_provider,
                    current_provider,
                )
                continue
            except Exception:
                self._cancel_reservation(reservation)
                raise

            self._finalize_reservation(reservation, result.usage.total_tokens)
            return ProviderExecution(result=result, effective_provider=current_provider)

        raise RuntimeError(f"Could not complete {operation} for {actor_label} after repeated quota exhaustion.")

    def quota_key_for_provider(self, provider: ProviderConfig) -> str | None:
        if provider.quota_key:
            return provider.quota_key
        if provider.type == ProviderType.CLAUDE_CLI:
            return "paid:claude"
        if provider.type == ProviderType.CODEX_CLI:
            return "paid:openai"
        if provider.type == ProviderType.GEMINI_CLI:
            return "paid:gemini"
        if provider.billing_tier == BillingTier.PAID:
            return f"paid:{provider.type.value}:{provider.model}"
        return None

    def is_paid_provider(self, provider: ProviderConfig) -> bool:
        if provider.billing_tier is not None:
            return provider.billing_tier == BillingTier.PAID
        return provider.type in {
            ProviderType.CLAUDE_CLI,
            ProviderType.CODEX_CLI,
            ProviderType.GEMINI_CLI,
        }

    def provider_label(self, provider: ProviderConfig) -> str:
        if provider.quota_key == "paid:claude" or provider.type == ProviderType.CLAUDE_CLI:
            return "Claude"
        if provider.quota_key == "paid:openai" or provider.type == ProviderType.CODEX_CLI:
            return "OpenAI"
        if provider.quota_key == "paid:gemini" or provider.type == ProviderType.GEMINI_CLI:
            return "Gemini"
        return provider.model

    async def _prepare_provider_for_call(
        self,
        run: ExperimentRun,
        actor_id: str,
        actor_label: str,
        provider: ProviderConfig,
        original_provider: ProviderConfig,
        operation: str,
        instructions: str,
    ) -> tuple[ProviderConfig, QuotaReservation | None]:
        if not self.is_paid_provider(provider):
            return provider, None

        quota_key = self.quota_key_for_provider(provider)
        if not quota_key:
            return provider, None

        estimate = self._estimate_call_tokens(operation, instructions)

        while True:
            with self._lock:
                states = self._load_states_unlocked()
                state = states.get(quota_key)
                if state is None or not self._is_tracked(state):
                    return provider, None
                if state.remaining_tokens > 0:
                    reserved = min(state.remaining_tokens, estimate)
                    state.remaining_tokens -= reserved
                    state.updated_at = utc_now()
                    states[quota_key] = state
                    self._save_states_unlocked(states)
                    return provider, QuotaReservation(quota_key=quota_key, reserved_tokens=reserved)

            provider = await self._recover_after_exhaustion(
                run,
                actor_id,
                actor_label,
                original_provider,
                provider,
            )
            if provider.model != original_provider.model or provider.type != original_provider.type:
                return provider, None

    async def _recover_after_exhaustion(
        self,
        run: ExperimentRun,
        actor_id: str,
        actor_label: str,
        original_provider: ProviderConfig,
        current_provider: ProviderConfig,
    ) -> ProviderConfig:
        policy = run.paid_provider_policy
        provider_label = self.provider_label(current_provider)
        if policy.on_exhaustion == PaidExhaustionAction.SWITCH_TO_FREE:
            if not policy.fallback_provider:
                raise RuntimeError(f"{provider_label} quota is exhausted and no free fallback is configured.")
            fallback = policy.fallback_provider.model_copy(deep=True)
            self._append_event(
                run,
                RuntimeEventType.QUOTA_SWITCHED,
                actor_id=actor_id,
                actor_label=actor_label,
                provider_label=provider_label,
                message=f"{provider_label} quota is exhausted. Switched to free fallback {fallback.model}.",
                metadata={"from_model": original_provider.model, "to_model": fallback.model},
            )
            return fallback

        if policy.on_exhaustion == PaidExhaustionAction.WAIT_FOR_RESET:
            quota_key = self.quota_key_for_provider(original_provider)
            if not quota_key:
                raise RuntimeError(f"{provider_label} quota is exhausted and cannot be reset automatically.")
            delay = self._seconds_until_reset(quota_key)
            if delay is None:
                raise RuntimeError(f"{provider_label} quota is exhausted and no reset time is configured.")
            if policy.wait_for_reset_max_seconds is not None and delay > policy.wait_for_reset_max_seconds:
                raise RuntimeError(
                    f"{provider_label} quota resets in {int(delay)} seconds, which exceeds the wait limit."
                )
            self._append_event(
                run,
                RuntimeEventType.WAITING_FOR_RESET,
                actor_id=actor_id,
                actor_label=actor_label,
                provider_label=provider_label,
                message=f"{provider_label} quota is exhausted. Waiting {int(delay)} seconds for the next reset window.",
                metadata={"wait_seconds": int(delay)},
            )
            await asyncio.sleep(max(0.0, delay))
            reset_logged = False
            with self._lock:
                states = self._load_states_unlocked()
                state = states.get(quota_key)
                if state and state.reset_at and state.reset_at <= utc_now():
                    state.remaining_tokens = max(state.remaining_tokens, state.cycle_token_limit)
                    state.reset_at = None
                    state.updated_at = utc_now()
                    states[quota_key] = state
                    self._save_states_unlocked(states)
                if state and state.remaining_tokens > 0:
                    reset_logged = True
            if reset_logged:
                self._append_event(
                    run,
                    RuntimeEventType.QUOTA_RESET,
                    actor_id=actor_id,
                    actor_label=actor_label,
                    provider_label=provider_label,
                    message=f"{provider_label} quota reset window opened. Resuming the run.",
                    metadata={"quota_key": quota_key},
                )
            return original_provider.model_copy(deep=True)

        raise RuntimeError(f"{provider_label} quota is exhausted.")

    def _seconds_until_reset(self, quota_key: str) -> float | None:
        with self._lock:
            states = self._load_states_unlocked()
            state = states.get(quota_key)
            if state is None or state.reset_at is None:
                return None
            return max(0.0, (state.reset_at - utc_now()).total_seconds())

    def _mark_provider_exhausted(self, provider: ProviderConfig) -> None:
        quota_key = self.quota_key_for_provider(provider)
        if not quota_key:
            return
        with self._lock:
            states = self._load_states_unlocked()
            state = states.get(quota_key)
            if state is None:
                return
            state.remaining_tokens = 0
            state.updated_at = utc_now()
            states[quota_key] = state
            self._save_states_unlocked(states)

    def _finalize_reservation(self, reservation: QuotaReservation | None, actual_tokens: int) -> None:
        if reservation is None:
            return
        delta = actual_tokens - reservation.reserved_tokens
        if delta == 0:
            return
        with self._lock:
            states = self._load_states_unlocked()
            state = states.get(reservation.quota_key)
            if state is None:
                return
            if delta > 0:
                state.remaining_tokens = max(0, state.remaining_tokens - delta)
            else:
                state.remaining_tokens += abs(delta)
            state.updated_at = utc_now()
            states[reservation.quota_key] = state
            self._save_states_unlocked(states)

    def _cancel_reservation(self, reservation: QuotaReservation | None) -> None:
        if reservation is None:
            return
        with self._lock:
            states = self._load_states_unlocked()
            state = states.get(reservation.quota_key)
            if state is None:
                return
            state.remaining_tokens += reservation.reserved_tokens
            state.updated_at = utc_now()
            states[reservation.quota_key] = state
            self._save_states_unlocked(states)

    def _estimate_call_tokens(self, operation: str, instructions: str) -> int:
        completion_reserve = {
            "plan": 500,
            "debate": 320,
            "judge": 220,
            "synthesis": 400,
        }.get(operation, 250)
        return self.budget_manager.estimate_tokens(instructions) + completion_reserve

    def _is_tracked(self, state: ProviderQuotaState) -> bool:
        return bool(state.cycle_token_limit > 0 or state.remaining_tokens > 0 or state.reset_at is not None)

    def _append_event(
        self,
        run: ExperimentRun,
        event_type: RuntimeEventType,
        actor_id: str,
        actor_label: str,
        provider_label: str | None,
        message: str,
        metadata: dict | None = None,
    ) -> None:
        run.runtime_events.append(
            RuntimeEvent(
                event_type=event_type,
                actor_id=actor_id,
                actor_label=actor_label,
                provider_label=provider_label,
                message=message,
                metadata=metadata or {},
            )
        )

    def _load_states_unlocked(self) -> dict[str, ProviderQuotaState]:
        if not self.quota_path.exists():
            return {}
        raw = json.loads(self.quota_path.read_text(encoding="utf-8"))
        states = {
            item["quota_key"]: ProviderQuotaState.model_validate(item)
            for item in raw
            if isinstance(item, dict) and item.get("quota_key")
        }
        changed = False
        for quota_key, state in list(states.items()):
            if state.reset_at and state.reset_at <= utc_now() and state.cycle_token_limit > 0:
                state.remaining_tokens = state.cycle_token_limit
                state.reset_at = None
                state.updated_at = utc_now()
                states[quota_key] = state
                changed = True
        if changed:
            self._save_states_unlocked(states)
        return states

    def _save_states_unlocked(self, states: dict[str, ProviderQuotaState]) -> None:
        payload = [state.model_dump(mode="json") for state in sorted(states.values(), key=lambda item: item.label)]
        self.quota_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
