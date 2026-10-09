"""A single wall-clock deadline shared by every phase of one solve."""

from __future__ import annotations

import math
import time

# Shortest time limit handed to Gurobi; a smaller one is not meaningful.
MIN_SOLVER_TIME = 1.0


class Deadline:
    """Deadline for one run, with a reserve kept for the final integer model.

    The search (column generation, branch-and-price) may use the time up to
    ``end - final_reserve``; the final model gets whatever is left after that.
    ``time_limit=None`` means no limit.
    """

    def __init__(self, time_limit: float | None, final_reserve: float = 0.0):
        self.time_limit = time_limit
        self.final_reserve = final_reserve if time_limit is not None else 0.0
        self._end = None if time_limit is None else time.perf_counter() + time_limit

    def search_remaining(self) -> float:
        """Seconds left for the search phases (inf when there is no limit)."""
        if self._end is None:
            return math.inf
        return self._end - self.final_reserve - time.perf_counter()

    def search_expired(self) -> bool:
        return self.search_remaining() <= 0

    def cap(self, limit: float) -> float:
        """A solver time limit that never runs past the search deadline."""
        return max(MIN_SOLVER_TIME, min(limit, self.search_remaining()))

    def final_time_limit(self) -> float | None:
        """Time limit for the final integer model: everything that is left,
        but at least the reserve (the search may overrun slightly)."""
        if self._end is None:
            return None
        left = self._end - time.perf_counter()
        return max(left, self.final_reserve, MIN_SOLVER_TIME)


NO_DEADLINE = Deadline(None)
