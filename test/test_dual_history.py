import csv

import pytest

from src.module.dual_history import DualHistory


def test_analyze_detects_direction_reversals():
    history = DualHistory()
    for iteration, pi_value, mu in [
        (1, 1.0, 4.0),
        (2, 3.0, 3.0),
        (3, 1.0, 2.0),
        (4, 3.0, 1.0),
    ]:
        history.record(iteration, {7: pi_value}, mu, objective=10.0 - iteration)

    metrics = history.analyze()

    assert metrics["pi[7]"].amplitude == pytest.approx(2.0)
    assert metrics["pi[7]"].total_variation == pytest.approx(6.0)
    assert metrics["pi[7]"].direction_changes == 2
    assert metrics["pi[7]"].oscillation_rate == pytest.approx(1.0)
    assert metrics["mu"].direction_changes == 0


def test_csv_export_uses_one_row_per_dual(tmp_path):
    history = DualHistory()
    history.record(1, {2: 1.5, 1: 0.5}, -2.0, objective=12.0)

    output_path = history.to_csv(tmp_path / "analysis" / "duals.csv")

    with output_path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert [row["variable"] for row in rows] == ["pi[1]", "pi[2]", "mu"]
    assert all(row["iteration"] == "1" for row in rows)
    assert all(row["objective"] == "12.0" for row in rows)
