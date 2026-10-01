"""In-memory collection of column generation traces for later analysis.

Designed to cost (almost) nothing during the solve:
- only timer reads, references to objects that already exist (duals, routes)
  and appends to Python lists happen inside the algorithm;
- no extra solver calls, no I/O, no serialisation until the run has finished
  (RunRecorder writes everything in one transaction after stopping its clock);
- when no collector is active, `current()` returns a no-op object.

The algorithm code only ever calls `telemetry.current()` and the methods below.
"""

from __future__ import annotations

import time

LAMBDA_TOL = 1e-9


class Telemetry:
    def __init__(self, store_duals: bool = True):
        self.store_duals = store_duals
        self._wall0 = time.perf_counter()
        self._cpu0 = time.process_time()
        self.iterations: list[dict] = []
        self.columns: dict[int, dict] = {}
        self._next_col_id = 0

    def clock(self) -> tuple[float, float]:
        """(wall, cpu) seconds since the collector was activated."""
        return time.perf_counter() - self._wall0, time.process_time() - self._cpu0

    def register_columns(self, routes, iteration, phase, node_id, default_source) -> None:
        """Give each new column a stable id (kept through deepcopy) and remember
        where it came from. Already registered columns are skipped."""
        for r in routes:
            if getattr(r, "col_id", None) is not None:
                continue
            r.col_id = self._next_col_id
            self._next_col_id += 1
            self.columns[r.col_id] = {
                "route": r,
                "iteration": iteration,
                "phase": phase,
                "node_id": node_id,
                "source": getattr(r, "source", None)
                or ("dummy" if getattr(r, "is_dummy", False) else default_source),
                "reduced_cost": r.cost,
                "max_lambda": 0.0,
                "in_final": False,
            }

    def observe_lambdas(self, routes, lambdas) -> None:
        """Track the largest lambda each column ever reaches (column usefulness)."""
        for r, lam in zip(routes, lambdas):
            if lam > LAMBDA_TOL:
                col = self.columns.get(getattr(r, "col_id", None))
                if col is not None and lam > col["max_lambda"]:
                    col["max_lambda"] = lam

    def mark_final(self, routes) -> None:
        for r in routes or []:
            col = self.columns.get(getattr(r, "col_id", None))
            if col is not None:
                col["in_final"] = True

    def log_iteration(self, row: dict) -> None:
        self.iterations.append(row)


class _NoOpTelemetry:
    store_duals = False

    def clock(self):
        return 0.0, 0.0

    def register_columns(self, *args, **kwargs):
        pass

    def observe_lambdas(self, *args, **kwargs):
        pass

    def mark_final(self, *args, **kwargs):
        pass

    def log_iteration(self, *args, **kwargs):
        pass


_NOOP = _NoOpTelemetry()
_current: Telemetry | None = None


def current() -> Telemetry | _NoOpTelemetry:
    return _current if _current is not None else _NOOP


def activate(telemetry: Telemetry) -> None:
    global _current
    _current = telemetry


def deactivate() -> None:
    global _current
    _current = None
