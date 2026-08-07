import copy
import math
import random
from module.route import Route
from module.input_model import InputModel
from module.stop_point import Stop

def build_route_from_stops(stops: list[Stop], model: InputModel) -> Route:
    total_distance = sum(
        model.distance_matrix[(stops[i].second_id, stops[i + 1].second_id)]
        for i in range(len(stops) - 1)
    )
    total_walking_distance = sum(
        model.walking_distance_list[s.second_id]
        for s in stops
        if s.second_id != model.first_depot.second_id
        and s.second_id != model.last_depot.second_id
    )

    return Route(
        stops=stops,
        total_distance=total_distance,
        total_walking_distance=total_walking_distance,
        served_students=[
            s.second_id
            for s in stops
            if s.second_id != model.first_depot.second_id
            and s.second_id != model.last_depot.second_id
        ],
    )


def perturb_route(route: Route, model: InputModel, rng: random.Random) -> Route:
    """
    Create a neighboring giant route by applying one random move.
    Depots stay fixed.
    """
    stops = copy.deepcopy(route.stops)
    inner = stops[1:-1]

    if len(inner) < 2:
        return route

    move_type = rng.choice(["swap", "relocate", "two_opt"])

    if move_type == "swap":
        i, j = rng.sample(range(len(inner)), 2)
        inner[i], inner[j] = inner[j], inner[i]

    elif move_type == "relocate":
        i, j = rng.sample(range(len(inner)), 2)
        node = inner.pop(i)
        inner.insert(j, node)

    elif move_type == "two_opt":
        i, j = sorted(rng.sample(range(len(inner)), 2))
        inner[i:j + 1] = reversed(inner[i:j + 1])

    new_stops = [stops[0]] + inner + [stops[-1]]
    return build_route_from_stops(new_stops, model)


def simulated_annealing_giant_route(
    initial_route: Route,
    model: InputModel,
    seed: int = 42,
    steps: int = 500,
    t0: float = 100.0,
    alpha: float = 0.995,
) -> Route:
    """
    Improve a giant route by simulated annealing.
    Returns the best route found.
    """
    rng = random.Random(seed)

    current = copy.deepcopy(initial_route)
    best = copy.deepcopy(initial_route)

    current_cost = current.total_distance
    best_cost = current_cost

    temperature = t0

    for _ in range(steps):
        candidate = perturb_route(current, model, rng)
        candidate_cost = candidate.total_distance

        delta = candidate_cost - current_cost

        # Accept if better, or sometimes if worse
        if delta <= 0 or rng.random() < math.exp(-delta / max(temperature, 1e-9)):
            current = candidate
            current_cost = candidate_cost

            if current_cost < best_cost:
                best = copy.deepcopy(current)
                best_cost = current_cost

        temperature *= alpha

    return best