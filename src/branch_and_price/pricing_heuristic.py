from module.stop_point import Stop, Student
from module.route import Route
from module.input_model import InputModel
from module.sucess_result import ModelSuccess
import logging


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
            _add_route_to_master(route, init_routes, logger)

    return init_routes


def _find_best_location_to_insert_stop_to_route(
    route: Route,
    new_stop: Stop,
    problem_model: InputModel,
):
    """Insert a new stop into the existing route at the best position."""
    # print(f"Trying to insert stop {new_stop.second_id} into route with stops {[s.second_id for s in route.stops]}")
    best_distance = float("inf")

    curr_distance = route.total_distance

    best_candidate_stop = None
    best_location = -1

    for i in range(1, len(route.stops) - 1):
        if (
            new_stop.second_id is None
            or route.stops[i].second_id is None
            or route.stops[i - 1].second_id is None
        ):
            continue
        if (
            new_stop.second_id == route.stops[i].second_id
            or new_stop.second_id == route.stops[i - 1].second_id
        ):
            continue
        new_distance = (
            curr_distance
            - problem_model.distance_matrix[
                (route.stops[i - 1].second_id, route.stops[i].second_id)
            ]
            + problem_model.distance_matrix[
                (route.stops[i - 1].second_id, new_stop.second_id)
            ]
            + problem_model.distance_matrix[
                (new_stop.second_id, route.stops[i].second_id)
            ]
        )

        if (
            new_distance < best_distance
            and new_distance <= problem_model.max_travel_distance
        ):
            best_distance = new_distance
            best_location = i
            best_candidate_stop = new_stop

    if best_candidate_stop is not None:
        return best_candidate_stop, best_location, best_distance
    else:
        return None, -1, 0


def best_pickup_for_student(
    problem_model: InputModel,
    student: Student,
    route: Route,
    pi: dict[int, float],
    mu: float,
) -> Route | None:
    selected_pickup_points: list[Stop] = []
    if pi is None or student.second_id not in pi:
        return None

    for cs in student.covering_stops:
        if (
            cs.second_id is not None
            and (
                problem_model.walking_distance_list[cs.second_id]
                - pi[student.second_id]
            )
            < 0
        ):
            selected_pickup_points.append(cs)

    selected_pickup_points = sorted(
        selected_pickup_points,
        key=lambda s: problem_model.walking_distance_list[s.second_id],
    )

    for stop in selected_pickup_points:
        candidate_stop, location, distance = (
            _find_best_location_to_insert_stop_to_route(route, stop, problem_model)
        )
        if candidate_stop is not None and candidate_stop.second_id is not None:
            new_stops = (
                route.stops[:location] + [candidate_stop] + route.stops[location:]
            )
            new_walking_distance = (
                route.total_walking_distance
                + problem_model.walking_distance_list[candidate_stop.second_id]
            )
            base_served = set(route.served_students)

            if student.second_id is not None:
                served_students = base_served | {student.second_id}
            else:
                served_students = base_served

            new_cost = (
                new_walking_distance
                - sum(pi[s] for s in served_students if s in pi)
                - mu
            )

            return Route(
                stops=new_stops,
                total_distance=distance,
                total_walking_distance=new_walking_distance,
                served_students=served_students,
                cost=new_cost,
            )
    return None


def _nearest_insertion(
    route: Route,
    problem_model: InputModel,
    pi: dict[int, float],
    mu: float,
    new_route: bool = False,
) -> Route | None:

    all_students = [s for s in problem_model.students]
    all_students.sort(
        key=lambda s: problem_model.distance_matrix[
            (problem_model.first_depot.second_id, s.second_id)
        ]
    )

    unvisited_stops: list[Student] = []
    for s in all_students:
        if s.second_id not in route.served_students:
            if new_route:
                if pi[s.second_id] > 0:
                    unvisited_stops.append(s)
            else:
                unvisited_stops.append(s)

    best_route = None
    successfully_added = False
    if new_route:
        #print(f'unvisitedstops: {[p.second_id for p in unvisited_stops]}')
        curr_route = Route(
            stops=[problem_model.first_depot, problem_model.last_depot],
            total_distance=0.0,
            total_walking_distance=0.0,
            served_students=[],
        )
    else:
        curr_route = route.__copy__()
    while unvisited_stops:
        std = unvisited_stops[0]
        temp_route = best_pickup_for_student(problem_model, std, curr_route, pi, mu)
        #if new_route and temp_route is not None:
        #    print(f'new student added: {list(temp_route.served_students)}')
        if temp_route is not None:
            if (
                temp_route.total_distance <= problem_model.max_travel_distance
                and len(temp_route.served_students) <= problem_model.capacity_of_vehicle
            ):
                curr_route = temp_route
                successfully_added = True
        unvisited_stops.remove(std)
    
    #if new_route:
    #    print(f'selected route:{[st for st in curr_route.served_students]},sucessfully added, and cost is {curr_route.cost}, stops: {[s.second_id for s in curr_route.stops]}')
    if successfully_added and curr_route.cost < 0:
        best_route = curr_route
        print(
            f"Nearest insertion route result: Stops {[s.second_id for s in best_route.stops]}, Total distance: {best_route.total_distance}, Total walking distance: {best_route.total_walking_distance}, reduced cost : {best_route.cost}"
        )
    return best_route


# the objective is to find a route with negative reduced cost that min (c_r -sum pi_i - mu) over all routes r
def generate_routes(
    routes: list[Route],
    problem_model: InputModel,
    pi: dict[int, float],
    mu: float,
    lambdas: list[float],
    logger: logging.Logger,
) -> tuple[ModelSuccess, list[Route]]:
    logger.info("Starting heuristic pricing problem.")

    try_new = True
    routes_eligible = routes[1:]
    route_len = len(routes_eligible)
    iteration = 0
    while iteration < route_len and try_new:
        route = routes_eligible[iteration]
        new_route = _nearest_insertion(route, problem_model, pi, mu)
        if new_route is not None:
            added, routes = _add_route_to_master(new_route, routes, logger)
            if added:
                try_new = False
                return ModelSuccess.SUCCESS, routes
        iteration += 1

    if try_new:
        #print("heuristic cannot find, but try again among positive lambdas")
        route_pos_lambada = [i for i, l in enumerate(lambdas) if l > 0.0]
        #print(f"number of positive lambdas:{len(route_pos_lambada)}")
        for pos_lambda in route_pos_lambada:
            new_extra_route = _nearest_insertion(
                routes[pos_lambda], problem_model, pi, mu, True
            )
            if new_extra_route is not None:
                added, routes = _add_route_to_master(new_extra_route, routes, logger)
                if added:
                    try_new = False
                    return ModelSuccess.SUCCESS, routes

    logger.info("No improving route found in heuristic pricing problem.")
    return ModelSuccess.NO_NEW_ROUTE, routes
