from module.stop_point import Stop, Student
from module.route import Route
from module.input_model import InputModel
from module.sucess_result import ModelSuccess
import logging
from dataclasses import dataclass, field


def check_new_route_is_duplicate(
    new_route: Route,
    existing_routes,
) -> bool:
    """Check if the new route is a duplicate of any existing route."""
    new_route_stops = [stop.second_id for stop in new_route.stops]
    for route in existing_routes:
        existing_route_stops = [stop.second_id for stop in route.stops]
        if new_route_stops == existing_route_stops or new_route_stops == list(
            reversed(existing_route_stops)
        ):
            return True
    return False


def _add_route_to_master(route: Route, routes, logger):
    if check_new_route_is_duplicate(route, routes):
        print("New route is a duplicate. Skipping.")
        return False, routes
    else:
        routes.append(route)
        logger.info(f"New route successfully added with negative Reduced cost")
        return True, routes


def create_route_with_single_student(
    student: Student,
    problem_model: InputModel,
) -> Route | None:
    """Create a route that serves a single student at the given stop.
    among the candidate stops, select the one with the lowest walking distance
    that can be served within the max travel distance constraint."""

    best_walking_distance = float("inf")
    total_route_distance = 0.0
    best_stop: Stop | None = None
    for stop in student.covering_stops:
        distance_to_depot = (
            problem_model.distance_matrix[
                (problem_model.first_depot.second_id, stop.second_id)
            ]
            + problem_model.distance_matrix[
                (stop.second_id, problem_model.last_depot.second_id)
            ]
        )
        walking_distance = problem_model.walking_distance_list[stop.second_id]

        if (
            walking_distance < best_walking_distance
            and distance_to_depot <= problem_model.max_travel_distance
        ):
            best_walking_distance = walking_distance
            total_route_distance = distance_to_depot
            best_stop = stop

    if best_stop is not None:

        return Route(
            stops=[problem_model.first_depot, best_stop, problem_model.last_depot],
            total_distance=total_route_distance,
            total_walking_distance=best_walking_distance,
            served_students=[student.second_id],
            pickup_map={student.second_id: best_stop.second_id},
        )
    return None


def add_single_route_to_master(
    init_routes, problem_model: InputModel, pi: dict[int, float], mu: float, logger
) -> list[Route]:
    logger.info("Adding single student routes to master problem.")

    for student in problem_model.students:
        route: Route | None = create_route_with_single_student(
            student,
            problem_model,
        )
        if route is not None:
            route.cost = route.total_walking_distance - pi[student.second_id] - mu
            route.source = "init_single"
            _add_route_to_master(route, init_routes, logger)

    return init_routes


# ---------------------------------------------------------------------------
# Heuristic pricing
#
# Goal: find routes with negative reduced cost
#       sum_i W[stop_i] - sum_s pi_s - mu   (mu <= 0)
# Every stop node belongs to exactly one student (covering stops are
# per-student copies), so a route is a tour plus one pickup node per student.
#
# Dominance used throughout: a student whose pi_s is not larger than the
# walking distance of its cheapest stop can only increase the reduced cost, so
# it is never worth serving.
# ---------------------------------------------------------------------------
RC_TOL = 1e-6
GAIN_EPS = 1e-9
MAX_NEW_COLUMNS = 10
N_SEEDS = 8
MAX_IMPROVE_ROUNDS = 20


@dataclass
class _State:
    """A route under construction: tour (incl. both depots) + student -> node."""

    nodes: list[Stop]
    assign: dict[int, Stop] = field(default_factory=dict)
    dist: float = 0.0


def _empty_state(pm: InputModel) -> _State:
    d = pm.distance_matrix
    return _State(
        nodes=[pm.first_depot, pm.last_depot],
        dist=d[(pm.first_depot.second_id, pm.last_depot.second_id)],
    )


def _insertion_delta(nodes, pos, stop, d) -> float:
    a, b = nodes[pos - 1].second_id, nodes[pos].second_id
    s = stop.second_id
    return d[(a, s)] + d[(s, b)] - d[(a, b)]


def _cheapest_insertion(nodes, stop, d) -> tuple[float, int]:
    best_delta, best_pos = float("inf"), -1
    for pos in range(1, len(nodes)):
        delta = _insertion_delta(nodes, pos, stop, d)
        if delta < best_delta:
            best_delta, best_pos = delta, pos
    return best_delta, best_pos


def _two_opt(state: _State, d) -> bool:
    """Shorten the tour in place (depots fixed). Returns True if improved."""
    nodes = state.nodes
    improved_any = False
    improved = True
    while improved:
        improved = False
        for i in range(1, len(nodes) - 2):
            for j in range(i + 1, len(nodes) - 1):
                a, b = nodes[i - 1].second_id, nodes[i].second_id
                c, e = nodes[j].second_id, nodes[j + 1].second_id
                gain = d[(a, b)] + d[(c, e)] - d[(a, c)] - d[(b, e)]
                if gain > 1e-9:
                    nodes[i : j + 1] = reversed(nodes[i : j + 1])
                    state.dist -= gain
                    improved = improved_any = True
    return improved_any


def _student_value(pm: InputModel, student: Student, pi) -> float:
    """pi_s minus the cheapest walking distance: the best possible gain."""
    W = pm.walking_distance_list
    return pi.get(student.second_id, 0.0) - min(
        W[cs.second_id] for cs in student.covering_stops
    )


def _greedy_add(state: _State, pm: InputModel, pi, candidates, mode: str) -> bool:
    """Repeatedly insert the best (student, stop, position) that keeps the
    tour within the distance limit and the bus within capacity.

    mode "ratio": maximise gain per extra distance (distance is the scarce
    resource); mode "gain": maximise gain, break ties by extra distance.
    """
    d, W = pm.distance_matrix, pm.walking_distance_list
    added = False
    while len(state.assign) < pm.capacity_of_vehicle:
        best = None  # (score, student, stop, pos, delta)
        for s in candidates:
            if s.second_id in state.assign:
                continue
            pi_s = pi.get(s.second_id, 0.0)
            for stop in s.covering_stops:
                gain = pi_s - W[stop.second_id]
                if gain <= GAIN_EPS:
                    continue
                delta, pos = _cheapest_insertion(state.nodes, stop, d)
                if pos < 0 or state.dist + delta > pm.max_travel_distance:
                    continue
                score = gain / (delta + 1e-3) if mode == "ratio" else gain - 1e-6 * delta
                if best is None or score > best[0]:
                    best = (score, s, stop, pos, delta)
        if best is None:
            break
        _, s, stop, pos, delta = best
        state.nodes.insert(pos, stop)
        state.assign[s.second_id] = stop
        state.dist += delta
        added = True
    return added


def _drop_and_switch(state: _State, pm: InputModel, pi) -> bool:
    """Drop students that cost more than they earn; move students to a
    cheaper-to-walk stop whenever the tour still fits."""
    d, W = pm.distance_matrix, pm.walking_distance_list
    student_by_id = {s.second_id: s for s in pm.students}
    changed = False

    for sid in list(state.assign):
        node = state.assign[sid]
        idx = state.nodes.index(node)
        prev_id, next_id = state.nodes[idx - 1].second_id, state.nodes[idx + 1].second_id
        saved = (
            d[(prev_id, node.second_id)]
            + d[(node.second_id, next_id)]
            - d[(prev_id, next_id)]
        )

        if pi.get(sid, 0.0) < W[node.second_id] - GAIN_EPS:
            state.nodes.pop(idx)
            del state.assign[sid]
            state.dist -= saved
            changed = True
            continue

        # try cheaper stops for this student, removing its current node first
        rest = state.nodes[:idx] + state.nodes[idx + 1 :]
        rest_dist = state.dist - saved
        for cs in sorted(student_by_id[sid].covering_stops, key=lambda c: W[c.second_id]):
            if W[cs.second_id] >= W[node.second_id] - 1e-9:
                break
            delta, pos = _cheapest_insertion(rest, cs, d)
            if pos >= 0 and rest_dist + delta <= pm.max_travel_distance:
                rest.insert(pos, cs)
                state.nodes = rest
                state.assign[sid] = cs
                state.dist = rest_dist + delta
                changed = True
                break
    return changed


def _improve(state: _State, pm: InputModel, pi, candidates) -> None:
    d = pm.distance_matrix
    for _ in range(MAX_IMPROVE_ROUNDS):
        changed = _two_opt(state, d)
        changed |= _drop_and_switch(state, pm, pi)
        changed |= _greedy_add(state, pm, pi, candidates, "ratio")
        if not changed:
            break


def _state_to_route(state: _State, pm: InputModel, pi, mu) -> Route:
    W = pm.walking_distance_list
    walking = sum(W[n.second_id] for n in state.assign.values())
    return Route(
        stops=list(state.nodes),
        total_distance=state.dist,
        total_walking_distance=walking,
        served_students=set(state.assign),
        cost=walking - sum(pi.get(s, 0.0) for s in state.assign) - mu,
        pickup_map={s: n.second_id for s, n in state.assign.items()},
    )


def _state_from_route(route: Route, pm: InputModel) -> _State | None:
    """Rebuild construction state from an existing route's stop nodes."""
    d = pm.distance_matrix
    nodes = list(route.stops)
    assign = {n.student_id: n for n in nodes[1:-1]}
    if len(assign) != len(nodes) - 2:
        return None
    dist = sum(
        d[(nodes[k].second_id, nodes[k + 1].second_id)] for k in range(len(nodes) - 1)
    )
    return _State(nodes=nodes, assign=assign, dist=dist)


def _seed_state(student: Student, pm: InputModel) -> _State | None:
    """Single-student start using the cheapest-walking stop that fits."""
    d, W = pm.distance_matrix, pm.walking_distance_list
    first, last = pm.first_depot.second_id, pm.last_depot.second_id
    for stop in sorted(student.covering_stops, key=lambda c: W[c.second_id]):
        dist = d[(first, stop.second_id)] + d[(stop.second_id, last)]
        if dist <= pm.max_travel_distance:
            return _State(
                nodes=[pm.first_depot, stop, pm.last_depot],
                assign={student.second_id: stop},
                dist=dist,
            )
    return None


def generate_routes(
    routes, problem_model, pi, mu, lambdas, logger, max_new: int = MAX_NEW_COLUMNS
):
    """Heuristic pricing: build several diverse routes, keep the improving ones.

    Starts: (a) greedy from scratch in two scoring modes, (b) greedy from each
    of the most valuable students as seed, (c) every route currently used by
    the master (lambda > 0). Each start is polished by local search.
    """
    logger.info("Starting heuristic pricing problem.")
    pm = problem_model

    promising = [s for s in pm.students if _student_value(pm, s, pi) > GAIN_EPS]
    if not promising:
        logger.info("No student has pi above its best walking distance.")
        return ModelSuccess.NO_NEW_ROUTE, routes

    found: dict[tuple, Route] = {}

    def consider(state: _State | None, source: str) -> None:
        if state is None or not state.assign:
            return
        _improve(state, pm, pi, promising)
        route = _state_to_route(state, pm, pi, mu)
        route.source = source
        if route.cost < -RC_TOL:
            found.setdefault(tuple(n.second_id for n in route.stops), route)

    for mode in ("ratio", "gain"):
        st = _empty_state(pm)
        _greedy_add(st, pm, pi, promising, mode)
        consider(st, f"greedy_{mode}")

    seeds = sorted(promising, key=lambda s: _student_value(pm, s, pi), reverse=True)
    for seed in seeds[:N_SEEDS]:
        for mode in ("ratio", "gain"):
            st = _seed_state(seed, pm)
            if st is not None:
                _greedy_add(st, pm, pi, promising, mode)
                consider(st, f"seed_{mode}")

    if lambdas is not None and len(lambdas) == len(routes):
        active = [r for r, lam in zip(routes, lambdas) if lam > 1e-9]
    else:
        active = routes
    for r in active:
        if not getattr(r, "is_dummy", False):
            consider(_state_from_route(r, pm), "extend_active")

    added = 0
    for route in sorted(found.values(), key=lambda r: r.cost):
        if added >= max_new:
            break
        ok, routes = _add_route_to_master(route, routes, logger)
        added += ok

    if added:
        logger.info(
            f"Heuristic pricing added {added} routes "
            f"(best cost {min(r.cost for r in found.values()):.6f})."
        )
        return ModelSuccess.SUCCESS, routes

    logger.info("No improving route found in heuristic pricing problem.")
    return ModelSuccess.NO_NEW_ROUTE, routes
