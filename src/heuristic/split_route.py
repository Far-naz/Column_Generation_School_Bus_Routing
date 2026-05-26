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

        # Seed the working sequence from the giant tour.  _calculate_cost
        # may refine individual entries via label-setting; we need a valid
        # list to index into from the start.
        best_seq: list[Stop] = list(self.giant_tour.stops)

        state = _SplitState(n=stop_count)

        self._calculate_matrix(stop_count, best_seq, state)
        self._partition_matrix(stop_count, target_row, state)

        if not self._need_more_search(target_row, stop_count, state):
            return self._do_routing(target_row, best_seq, state)

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
        best_seq: list[Stop],
        state: _SplitState,
    ) -> None:
        """
        Fill state.matrix_dist[i][j] with the walking distance of the best
        feasible sub-tour covering stops i+1 … j.

        The outer loop iterates over starting positions i; the inner loop
        extends j up to capacity_of_vehicle stops forward.  If the resulting
        route exceeds max_travel_distance, the label-setting algorithm is
        called to find a feasible re-routing; if still infeasible the arc
        cost stays at infinity.
        """
        for i in range(num_stops - 1):
            j = i + 1
            for _ in range(self.input_model.capacity_of_vehicle):
                if j >= num_stops:
                    break

                route, node_str, depot_pos = self._calculate_cost(i, j, best_seq)

                if route is None:
                    break  # cost calculation failed; no point extending further
 
                if self._is_feasible(route):
                    state.matrix_dist[i][j] = route.total_walking_distance
                    state.matrix_place[i, j] = node_str
                else:
                    # Adding more stops will only worsen distance and load,
                    # so no extension of this arc can be feasible either.
                    break

                j += 1  # must be the last statement inside the capacity loop

    def _calculate_cost(
        self,
        row: int,
        column: int,
        best_seq: list[Stop],
    ) -> tuple[Route | None, str, int]:
        """
        Build the candidate sub-tour from stop row+1 to stop column (inclusive)
        bookended by depots, and repair it via label-setting if it violates the
        travel-distance limit.

        Returns
        -------
        route      : the (possibly repaired) Route object, or None on failure
        node_str   : semicolon-joined second_ids of the chosen stops
        depot_pos  : the starting index of this arc (always `row`)
        """
        first_depot = self.input_model.first_depot
        last_depot = self.input_model.last_depot

        walk_distance = 0.0
        served_stds: list[int] = []

        tmp_stops: list[Stop] = [first_depot]
        node_parts: list[str] = [str(first_depot.second_id)]

        for k in range(row, column):
            stop = self.giant_tour.stops[k + 1]
            tmp_stops.append(stop)
            node_parts.append(str(best_seq[k + 1].second_id))
            walk_distance += self.input_model.walking_distance_list[stop.second_id]
            served_stds.append(stop.student_id)

        if last_depot not in tmp_stops:
            tmp_stops.append(last_depot)
            node_parts.append(str(last_depot.second_id))

        node_str = ";".join(node_parts) + ";"

        route_distance = 0.0
        for t in range(len(tmp_stops) - 1):
            route_distance += self.input_model.distance_matrix[
                (tmp_stops[t].second_id, tmp_stops[t + 1].second_id)
            ]

        tmp_route = Route(
            tmp_stops,
            total_distance=route_distance,
            total_walking_distance=walk_distance,
            served_students=served_stds,
        )

        tmp_route, node_str = self._repair_if_needed(tmp_route, node_str)

        return tmp_route, node_str, row

    def _repair_if_needed(
        self,
        route:    Route,
        node_str: str,
    ) -> tuple[Route | None, str]:
        if route.total_distance <= self.input_model.max_travel_distance:
            return route, node_str
        try:
            route    = LabelSettingAlgorithmPulling(route, self.input_model).run()
            node_str = ";".join(str(s.second_id) for s in route.stops) + ";"
            return route, node_str
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
        """
        Check whether a finite solution exists for row_id vehicles covering
        all stop_count stops.  If it does, backtrack the last_index pointers
        to recover the breakpoint sequence and store it in state.last_seq.

        Returns True  → no feasible partition found; the caller should try
                        more vehicles or declare failure.
        Returns False → a feasible partition exists; proceed to _do_routing.
        """
        if state.matrix_partition[row_id][stop_count - 1] == math.inf:
            return True  # no feasible partition with row_id vehicles

        # Backtrack: start from the last stop and follow last_index pointers.
        seq: list[int] = [stop_count - 1]
        for t in range(row_id, 0, -1):
            seq.append(state.last_index[t][seq[-1]])

        seq.append(0)
        state.last_seq[row_id] = seq
        return False

    def _do_routing(
        self,
        num_vehicle: int,
        best_seq: list[Stop],
        state: _SplitState,
    ) -> list[Route]:
        """
        Convert the sorted breakpoint list into Route objects.

        Each consecutive pair (start, end) in the sorted breakpoints defines
        one sub-tour.  The stop second_ids for that arc were stored in
        state.matrix_place during Phase 1 and are used to look up the
        canonical Stop objects.

        A dict-based lookup (O(1) per stop) replaces the original O(n) linear
        scan over all_stops.
        """
        # Build a fast lookup from second_id → Stop once, not per stop.
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
            visited_ids = state.matrix_place.get((start, end), "").split(";")

            seen: set[int] = {self.input_model.first_depot.second_id}
            for stop_id_str in visited_ids[:-1]:
                stop_id = int(stop_id_str)
                if not stop_id or stop_id in seen:
                    continue
                sp = stop_lookup.get(stop_id)
                if sp is not None:
                    best_points.append(sp)
                    total_walk += self.input_model.walking_distance_list[sp.second_id]
                    if sp.student_id != 0:
                        served_stds.append(sp.student_id)
                    seen.add(stop_id)

            # best_points.append(self.input_model.last_depot)
            total_dist = 0.0
            for p in range(len(best_points) - 1):
                total_dist += self.input_model.distance_matrix[
                    (best_points[p].second_id, best_points[p + 1].second_id)
                ]

            routes.append(
                Route(
                    best_points,
                    total_distance=total_dist,
                    total_walking_distance=total_walk,
                    served_students=served_stds,
                )
            )

        return routes
