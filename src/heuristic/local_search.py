from module.route import Route
from module.stop_point import Stop


def compute_route_distance(stops: list[Stop], distance_matrix: dict) -> float:
    return sum(
        distance_matrix[(stops[i].second_id, stops[i + 1].second_id)]
        for i in range(len(stops) - 1)
    )


def two_opt_swap_stops(
    route: Route,
    i: int,
    j: int,
    distance_matrix: dict,
) -> Route:
    """
    Returns a new Route with stops[i+1..j] reversed.
    Depot endpoints (index 0 and -1) are never touched by the caller.
    """
    new_stops = (
        route.stops[: i + 1]
        + list(reversed(route.stops[i + 1 : j + 1]))
        + route.stops[j + 1 :]
    )
    new_distance = compute_route_distance(new_stops, distance_matrix)

    return Route(
        stops=new_stops,
        total_distance=new_distance,
        total_walking_distance=route.total_walking_distance,
        served_students=route.served_students,
    )


def two_opt(route: Route, distance_matrix: dict, max_travel_distance: float) -> Route:
    best = route
    improved = True

    while improved:
        improved = False
        n = len(best.stops)

        for i in range(1, n - 2):  # skip depot at 0
            for j in range(i + 1, n - 1):  # skip depot at n-1
                candidate = two_opt_swap_stops(best, i, j, distance_matrix)

                if (
                    candidate.total_distance < best.total_distance
                    and candidate.total_distance <= max_travel_distance
                ):
                    best = candidate
                    improved = True

    return best


def two_opt_algorithm(
    routes: list[Route],
    distance_matrix: dict,
    max_travel_distance: float,
) -> list[Route]:
    return [two_opt(route, distance_matrix, max_travel_distance) for route in routes]


def local_search_algorithm(
    routes: list[Route],
    distance_matrix: dict,
    max_travel_distance: float,
) -> list[Route]:
    return two_opt_algorithm(routes, distance_matrix, max_travel_distance)
