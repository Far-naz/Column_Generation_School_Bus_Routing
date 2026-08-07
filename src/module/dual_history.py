from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Hashable, Iterable


@dataclass(frozen=True)
class DualSnapshot:
    """Dual solution of one restricted-master iteration."""

    iteration: int
    pi: dict[Hashable, float]
    mu: float
    objective: float


@dataclass(frozen=True)
class OscillationMetric:
    """Summary of how one dual variable moves over the recorded iterations."""

    observations: int
    minimum: float
    maximum: float
    mean: float
    standard_deviation: float
    amplitude: float
    total_variation: float
    mean_absolute_change: float
    direction_changes: int
    oscillation_rate: float


@dataclass
class DualHistory:
    """In-memory dual trace with analysis and long-format CSV export."""

    snapshots: list[DualSnapshot] = field(default_factory=list)

    def record(
        self,
        iteration: int,
        pi: dict[Hashable, float],
        mu: float,
        objective: float,
    ) -> None:
        # Copy pi because callers may reuse or mutate the solver result dictionary.
        self.snapshots.append(
            DualSnapshot(iteration, dict(pi), float(mu), float(objective))
        )

    def analyze(self, tolerance: float = 1e-9) -> dict[str, OscillationMetric]:
        """Return movement metrics for every ``pi`` and for ``mu``.

        Oscillation is measured as reversals in the direction of non-trivial
        consecutive changes. Flat changes within ``tolerance`` are ignored.
        """
        series: dict[str, list[float]] = {"mu": [s.mu for s in self.snapshots]}
        student_ids = {
            student_id for snapshot in self.snapshots for student_id in snapshot.pi
        }
        for student_id in sorted(student_ids, key=str):
            series[f"pi[{student_id}]"] = [
                snapshot.pi[student_id]
                for snapshot in self.snapshots
                if student_id in snapshot.pi
            ]

        return {
            name: _metric(values, tolerance)
            for name, values in series.items()
            if values
        }

    def to_csv(self, path: str | Path) -> Path:
        """Store the trace in long format: one row per variable and iteration."""
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=["iteration", "variable", "value", "objective"],
            )
            writer.writeheader()
            for snapshot in self.snapshots:
                sorted_duals = sorted(
                    snapshot.pi.items(), key=lambda item: str(item[0])
                )
                for student_id, value in sorted_duals:
                    writer.writerow(
                        {
                            "iteration": snapshot.iteration,
                            "variable": f"pi[{student_id}]",
                            "value": value,
                            "objective": snapshot.objective,
                        }
                    )
                writer.writerow(
                    {
                        "iteration": snapshot.iteration,
                        "variable": "mu",
                        "value": snapshot.mu,
                        "objective": snapshot.objective,
                    }
                )
        return output_path


def _metric(values: Iterable[float], tolerance: float) -> OscillationMetric:
    samples = list(values)
    changes = [right - left for left, right in zip(samples, samples[1:])]
    directions = [
        1 if change > 0 else -1
        for change in changes
        if abs(change) > tolerance
    ]
    direction_changes = sum(
        left != right for left, right in zip(directions, directions[1:])
    )
    possible_reversals = max(0, len(directions) - 1)

    return OscillationMetric(
        observations=len(samples),
        minimum=min(samples),
        maximum=max(samples),
        mean=statistics.fmean(samples),
        standard_deviation=statistics.pstdev(samples),
        amplitude=max(samples) - min(samples),
        total_variation=sum(abs(change) for change in changes),
        mean_absolute_change=(
            statistics.fmean(abs(change) for change in changes) if changes else 0.0
        ),
        direction_changes=direction_changes,
        oscillation_rate=(
            direction_changes / possible_reversals if possible_reversals else 0.0
        ),
    )
