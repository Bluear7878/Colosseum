from __future__ import annotations

import json
from pathlib import Path

from colosseum.core.config import ARTIFACT_ROOT
from colosseum.core.models import ExperimentRun, RunListItem


class FileRunRepository:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or ARTIFACT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    def save_run(self, run: ExperimentRun) -> None:
        run_dir = self.root / run.run_id
        plans_dir = run_dir / "plans"
        debate_dir = run_dir / "debate"
        judge_dir = run_dir / "judge"
        for directory in (run_dir, plans_dir, debate_dir, judge_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self._write_json(run_dir / "run.json", run.model_dump(mode="json"))
        self._write_json(run_dir / "task.json", run.task.model_dump(mode="json"))
        if run.context_bundle:
            self._write_json(
                run_dir / "context_bundle.json",
                run.context_bundle.model_dump(mode="json"),
            )
        for plan in run.plans:
            self._write_json(plans_dir / f"{plan.plan_id}.json", plan.model_dump(mode="json"))
        for debate_round in run.debate_rounds:
            self._write_json(
                debate_dir / f"round-{debate_round.index}.json",
                debate_round.model_dump(mode="json"),
            )
        self._write_json(
            judge_dir / "trace.json",
            [decision.model_dump(mode="json") for decision in run.judge_trace],
        )
        if run.verdict:
            self._write_json(judge_dir / "verdict.json", run.verdict.model_dump(mode="json"))
        if run.human_judge_packet:
            self._write_json(
                judge_dir / "human_packet.json",
                run.human_judge_packet.model_dump(mode="json"),
            )

    def load_run(self, run_id: str) -> ExperimentRun:
        path = self.root / run_id / "run.json"
        if not path.exists():
            matches = sorted(self.root.glob(f"{run_id}*/run.json"))
            if not matches:
                raise FileNotFoundError(f"Run {run_id} does not exist.")
            if len(matches) > 1:
                raise FileNotFoundError(f"Run prefix {run_id} is ambiguous.")
            path = matches[0]
        return ExperimentRun.model_validate_json(path.read_text(encoding="utf-8"))

    def list_runs(self) -> list[RunListItem]:
        items: list[RunListItem] = []
        for path in sorted(self.root.glob("*/run.json"), reverse=True):
            run = ExperimentRun.model_validate_json(path.read_text(encoding="utf-8"))
            items.append(
                RunListItem(
                    run_id=run.run_id,
                    project_name=run.project_name,
                    task_title=run.task.title,
                    status=run.status,
                    judge_mode=run.judge.mode,
                    updated_at=run.updated_at,
                    verdict_type=run.verdict.verdict_type if run.verdict else None,
                    total_tokens=run.budget_ledger.total.total_tokens,
                )
            )
        return sorted(items, key=lambda item: item.updated_at, reverse=True)

    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
