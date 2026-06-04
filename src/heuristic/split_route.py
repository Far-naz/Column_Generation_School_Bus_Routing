from __future__ import annotations

import math
from dataclasses import dataclass, field

from module.input_model import InputModel
from module.route import Route
from module.stop_point import Stop
from heuristic.label_setting import LabelSettingAlgorithmPulling

# ---------------------------------------------------------------------------
# Internal state container — one instance per split() call.
# Keeping the matrices here means SplitTour is safe to call multiple times
# and avoids a growing list of mutable instance attributes.
# ---------------------------------------------------------------------------


@dataclass
class _SplitState:
    """All transient data produced during a single split run."""

    n: int  # number of stops in the giant tour (including virtual depot slots)

    # 2-D lists are dramatically faster than dict[tuple] for the DP inner loop.
    matrix_dist: list[list[float]] = field(init=False)
    matrix_partition: list[list[float]] = field(init=False)
    last_index: list[list[int]] = field(init=False)

    # Per-(i,j) arc: semicolon-separated stop second_ids chosen for that sub-tour.
    matrix_place: dict[tuple[int, int], str] = field(default_factory=dict)

    # Backtracked breakpoint sequences, keyed by number of vehicles.
    last_seq: dict[int, list[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = self.n
        self.matrix_dist = [[math.inf] * n for _ in range(n)]
        self.matrix_partition = [[math.inf] * n for _ in range(n)]
        self.last_index = [[-1] * n for _ in range(n)]


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class SplitTour:
    """
    Implements the Split procedure from Prins (2004 / 2014).

    Given a giant tour produced by the 'Order First' phase, this class
    partitions it into a set of feasible vehicle routes by finding the
    shortest path in an auxiliary graph via dynamic programming.

    Usage
    -----
        routes = SplitTour(input_model, giant_tour).split()
    """

    def __init__(self, input_model: InputModel, giant_tour: Route) -> None:
        self.input_model = input_model
        self.giant_tour = giant_tour

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def split(self) -> list[Route] | None:
        """
        Partition the giant tour into exactly ``input_model.num_of_vehicle``
        routes.

        The DP table uses 0-based row indices where row k represents k+1
        vehicles, so the target row is ``num_of_vehicle - 1``.

        Returns
        -------
        list[Route]
            Exactly num_of_vehicle routes when a feasible partition exists,
            or None when the requested fleet size cannot cover the tour.
        """
        num_of_vehicle: int = self.input_model.number_of_vehicles
        if num_of_vehicle < 1:
            raise ValueError(f"num_of_vehicle must be >= 1, got {num_of_vehicle}")

        stop_count: int = len(self.giant_tour.stops)

        # Row k in the DP represents k+1 vehicles, so target row = k-1.
        target_row: int = num_of_vehicle - 1

        state = _SplitState(n=stop_count)

        self._calculate_matrix(stop_count, state)
        self._partition_matrix(stop_count, target_row, state)

        if not self._need_more_search(target_row, stop_count, state):
            return self._do_routing(target_row, state)

        return None  # requested fleet size cannot cover this tour feasibly

    # ------------------------------------------------------------------
    # Phase 1 — build the arc-cost matrix
    # ------------------------------------------------------------------
    def _is_feasible(self, route: Route) -> bool:
        if route.total_distance > self.input_model.max_travel_distance:
            return False
        if len(route.served_students) > self.input_model.capacity_of_vehicle:
            return False
        return True

    def _calculate_matrix(
        self,
        num_stops: int,
        state: _SplitState,
    ) -> None:
        for i in range(num_stops - 1):
            j = i + 1
            for _ in range(self.input_model.capacity_of_vehicle):
                if j >= num_stops:
                    break

                route, node_str, depot_pos = self._calculate_cost(i, j)

                if route is None:
                    j += 1
                    continue  # ✅ skip broken arc, don't abort column

                if self._is_feasible(route):
                    state.matrix_dist[i][j] = route.total_walking_distance
                    state.matrix_place[i, j] = node_str
                else:
                    break  # capacity/distance monotone — no point extending

                j += 1

    def _calculate_cost(
        self,
        row: int,
        column: int,
    ) -> tuple[Route | None, str, int]:
        first_depot = self.input_model.first_depot
        last_depot = self.input_model.last_depot

        walk_distance = 0.0
        served_stds: list[int] = []
        tmp_stops: list[Stop] = [first_depot]
        node_parts: list[str] = [str(first_depot.second_id)]

        # ✅ range is now (row+1, column+1) — inclusive, consistent source
        for k in range(row + 1, column + 1):
            stop = self.giant_tour.stops[k]
            tmp_stops.append(stop)
            node_parts.append(str(stop.second_id))
            walk_distance += self.input_model.walking_distance_list[stop.second_id]
            if stop.student_id is not None and stop.student_id != 0:
                served_stds.append(stop.student_id)

        # ✅ Always close with last depot
        if tmp_stops[-1].second_id != last_depot.second_id:
            tmp_stops.append(last_depot)
            node_parts.append(str(last_depot.second_id))

        node_str = ";".join(node_parts) + ";"

        route_distance = sum(
            self.input_model.distance_matrix[
                (tmp_stops[t].second_id, tmp_stops[t + 1].second_id)
            ]
            for t in range(len(tmp_stops) - 1)
        )

        tmp_route = Route(
            tmp_stops,
            total_distance=route_distance,
            total_walking_distance=walk_distance,
            served_students=served_stds,
        )

        return self._repair_if_needed(tmp_route, node_str) + (row,)

    def _repair_if_needed(
        self,
        route: Route,
        node_str: str,
    ) -> tuple[Route | None, str]:
        if route.total_distance <= self.input_model.max_travel_distance:
            return route, node_str
        try:
            imp_route = LabelSettingAlgorithmPulling(route, self.input_model).run()
            node_str = ";".join(str(s.second_id) for s in imp_route.stops) + ";"
            return imp_route, node_str
        except Exception:
            return None, ""

    # ------------------------------------------------------------------
    # Phase 2 — dynamic programming partition
    # ------------------------------------------------------------------

    def _partition_matrix(
        self,
        stop_count: int,
        target_row: int,
        state: _SplitState,
    ) -> None:
        """
        Fill the DP table state.matrix_partition using Bellman's recurrence:

            V[k][j] = min_{i=k-1}^{j-1}  V[k-1][i] + c(i, j)

        where k is the row index (0-based) and c(i, j) is the arc cost from
        state.matrix_dist.  Row k represents k+1 vehicles, so to target
        exactly N vehicles we fill rows 0 … N-1 (i.e. up to target_row).

        Row 0 (single-vehicle base case) is initialised directly from
        matrix_dist.  Rows 1 … target_row are filled by _do_partition.
        The two steps are intentionally separate loops — nesting them was a
        prior bug that called _do_partition stop_count times per vehicle.
        """
        # Base case: row 0 — one vehicle covers stops 0 … end_point directly.
        for end_point in range(1, stop_count):
            state.matrix_partition[0][end_point] = state.matrix_dist[0][end_point]

        # Fill rows 1 … target_row (2-vehicle case up to N-vehicle case).
        # We stop exactly at target_row; no extra rows are computed.
        for k in range(1, target_row + 1):
            self._do_partition(state.matrix_dist, k, stop_count, state)

    def _do_partition(
        self,
        matrix_dist: list[list[float]],
        row_id: int,
        stop_count: int,
        state: _SplitState,
    ) -> None:
        """
        One pass of the Bellman recurrence for a fixed vehicle count row_id.

        The lower bound on end_point is row_id + 1 (we need at least row_id
        stops before the end point).  The lower bound on the predecessor i is
        row_id - 1 (the previous row must have covered at least row_id - 1
        stops).
        """
        for end_point in range(row_id + 1, stop_count):
            for i in range(row_id - 1, end_point):
                dist = state.matrix_partition[row_id - 1][i] + matrix_dist[i][end_point]
                if dist < state.matrix_partition[row_id][end_point]:
                    state.matrix_partition[row_id][end_point] = dist
                    state.last_index[row_id][end_point] = i

    # ------------------------------------------------------------------
    # Phase 3 — backtrack and reconstruct routes
    # ------------------------------------------------------------------

    def _need_more_search(
        self,
        row_id: int,
        stop_count: int,
        state: _SplitState,
    ) -> bool:
        if state.matrix_partition[row_id][stop_count - 1] == math.inf:
            return True

        seq: list[int] = [stop_count - 1]
        for t in range(row_id, 0, -1):
            prev = state.last_index[t][seq[-1]]
            if prev == -1:  # ✅ broken backtrack chain
                return True
            seq.append(prev)
        seq.append(0)

        state.last_seq[row_id] = seq
        return False

    def _do_routing(
        self,
        num_vehicle: int,
        state: _SplitState,
    ) -> list[Route]:
        stop_lookup: dict[int, Stop] = {
            s.second_id: s for s in self.input_model.all_stops
        }

        breakpoints = sorted(state.last_seq[num_vehicle])
        routes: list[Route] = []

        for idx in range(len(breakpoints) - 1):
            start = breakpoints[idx]
            end = breakpoints[idx + 1]

            total_walk = 0.0
            served_stds: list[int] = []
            best_points: list[Stop] = [self.input_model.first_depot]
            seen: set[int] = {self.input_model.first_depot.second_id}

            visited_ids = state.matrix_place.get((start, end), "").split(";")
            for stop_id_str in visited_ids:
                if not stop_id_str:
                    continue
                stop_id = int(stop_id_str)
                if stop_id in seen:
                    continue
                if stop_id == self.input_model.last_depot.second_id:
                    continue  # add last depot explicitly below
                sp = stop_lookup.get(stop_id)
                if sp is not None:
                    best_points.append(sp)
                    total_walk += self.input_model.walking_distance_list[sp.second_id]
                    if sp.student_id is not None and sp.student_id != 0:
                        served_stds.append(sp.student_id)
                    seen.add(stop_id)

            # ✅ Always close route
            best_points.append(self.input_model.last_depot)

            total_dist = sum(
                self.input_model.distance_matrix[
                    (best_points[p].second_id, best_points[p + 1].second_id)
                ]
                for p in range(len(best_points) - 1)
            )

            routes.append(
                Route(
                    best_points,
                    total_distance=total_dist,
                    total_walking_distance=total_walk,
                    served_students=served_stds,
                )
            )

        return routes
