from __future__ import annotations

import re
from typing import Any

from colosseum.core.models import (
    AgentConfig,
    AgentMessage,
    DebateClaim,
    PlanDocument,
    RiskItem,
    RoundType,
    UsageMetrics,
)


SECTION_PATTERNS = {
    "evidence_basis": re.compile(r"evidence|citations?|support", re.IGNORECASE),
    "assumptions": re.compile(r"assumptions?:", re.IGNORECASE),
    "architecture": re.compile(r"architecture|design", re.IGNORECASE),
    "implementation_strategy": re.compile(r"implementation", re.IGNORECASE),
    "risks": re.compile(r"risks?|trade[- ]?offs?", re.IGNORECASE),
    "strengths": re.compile(r"strengths?", re.IGNORECASE),
    "weaknesses": re.compile(r"weaknesses?", re.IGNORECASE),
}


class ResponseNormalizer:
    def normalize_plan(
        self,
        agent: AgentConfig,
        payload: dict[str, Any],
        raw_content: str,
        usage: UsageMetrics,
    ) -> PlanDocument:
        if payload:
            return PlanDocument(
                agent_id=agent.agent_id,
                display_name=agent.display_name,
                summary=payload.get("summary", raw_content[:300] or "No summary provided."),
                evidence_basis=self._normalize_list(payload.get("evidence_basis")),
                assumptions=self._normalize_list(payload.get("assumptions")),
                architecture=self._normalize_list(payload.get("architecture")),
                implementation_strategy=self._normalize_list(
                    payload.get("implementation_strategy")
                ),
                risks=self._normalize_risks(payload.get("risks")),
                strengths=self._normalize_list(payload.get("strengths")),
                weaknesses=self._normalize_list(payload.get("weaknesses")),
                trade_offs=self._normalize_list(payload.get("trade_offs")),
                open_questions=self._normalize_list(payload.get("open_questions")),
                raw_response=raw_content,
                usage=usage,
            )

        sections = self._extract_sections(raw_content)
        return PlanDocument(
            agent_id=agent.agent_id,
            display_name=agent.display_name,
            summary=raw_content[:300] or "No summary provided.",
            evidence_basis=sections["evidence_basis"],
            assumptions=sections["assumptions"],
            architecture=sections["architecture"],
            implementation_strategy=sections["implementation_strategy"],
            risks=[RiskItem(title=risk, severity="medium", mitigation="Clarify during review.") for risk in sections["risks"]],
            strengths=sections["strengths"],
            weaknesses=sections["weaknesses"],
            raw_response=raw_content,
            usage=usage,
        )

    def normalize_message(
        self,
        agent_id: str,
        plan_id: str,
        round_index: int,
        round_type: RoundType,
        payload: dict[str, Any],
        raw_content: str,
        usage: UsageMetrics,
    ) -> AgentMessage:
        if payload:
            return AgentMessage(
                round_index=round_index,
                round_type=round_type,
                agent_id=agent_id,
                plan_id=plan_id,
                content=payload.get("content", raw_content[:300]),
                critique_points=self._normalize_claims(payload.get("critique_points")),
                defense_points=self._normalize_claims(payload.get("defense_points")),
                concessions=self._normalize_list(payload.get("concessions")),
                hybrid_suggestions=self._normalize_list(payload.get("hybrid_suggestions")),
                referenced_plan_ids=self._normalize_list(payload.get("referenced_plan_ids")),
                usage=usage,
            )

        return AgentMessage(
            round_index=round_index,
            round_type=round_type,
            agent_id=agent_id,
            plan_id=plan_id,
            content=raw_content[:500],
            usage=usage,
        )

    def _normalize_list(self, value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]

    def _normalize_risks(self, value: Any) -> list[RiskItem]:
        if not value:
            return []
        risks: list[RiskItem] = []
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    risks.append(
                        RiskItem(
                            title=str(item.get("title", "Unspecified risk")),
                            severity=str(item.get("severity", "medium")),
                            mitigation=str(item.get("mitigation", "No mitigation provided.")),
                        )
                    )
                else:
                    risks.append(
                        RiskItem(
                            title=str(item),
                            severity="medium",
                            mitigation="Clarify mitigation during implementation.",
                        )
                    )
        return risks

    def _normalize_claims(self, value: Any) -> list[DebateClaim]:
        if not value:
            return []
        claims: list[DebateClaim] = []
        for item in value:
            if isinstance(item, dict):
                claims.append(
                    DebateClaim(
                        category=str(item.get("category", "general")),
                        text=str(item.get("text", "")),
                        target_plan_ids=self._normalize_list(item.get("target_plan_ids")),
                        evidence=self._normalize_list(item.get("evidence")),
                    )
                )
            else:
                claims.append(DebateClaim(category="general", text=str(item)))
        return claims

    def _extract_sections(self, raw_content: str) -> dict[str, list[str]]:
        buckets = {key: [] for key in SECTION_PATTERNS}
        current_key = "implementation_strategy"
        for line in raw_content.splitlines():
            cleaned = line.strip(" -*")
            if not cleaned:
                continue
            for key, pattern in SECTION_PATTERNS.items():
                if pattern.search(cleaned):
                    current_key = key
                    cleaned = ""
                    break
            if cleaned:
                buckets[current_key].append(cleaned)
        return buckets
