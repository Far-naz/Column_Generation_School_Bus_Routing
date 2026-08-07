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

    for i in range(1, len(route.stops)):
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
    if pi is None or student.second_id not in pi:
        return None

    selected_pickup_points = sorted(
        [cs for cs in student.covering_stops if cs.second_id is not None],
        key=lambda s: problem_model.walking_distance_list[s.second_id],
    )

    for stop in selected_pickup_points:
        candidate_stop, location, distance = (
            _find_best_location_to_insert_stop_to_route(route, stop, problem_model)
        )
        if candidate_stop is not None and candidate_stop.second_id is not None:
            new_stops = route.stops[:location] + [candidate_stop] + route.stops[location:]
            new_walking_distance = (
                route.total_walking_distance
                + problem_model.walking_distance_list[candidate_stop.second_id]
            )
            served_students = set(route.served_students) | {student.second_id}
            new_cost = (
                new_walking_distance
                - sum(pi[s] for s in served_students if s in pi)
                - mu
            )

            # Carry forward existing pickup_map and add new student→stop mapping
            new_pickup_map = {
                **getattr(route, "pickup_map", {}),
                student.second_id: candidate_stop.second_id,
            }

            new_route = Route(
                stops=new_stops,
                total_distance=distance,
                total_walking_distance=new_walking_distance,
                served_students=served_students,
                cost=new_cost,
            )
            new_route.pickup_map = new_pickup_map
            return new_route
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
        key=lambda s: pi.get(s.second_id, 0.0) - min(
            problem_model.walking_distance_list[cs.second_id]
            for cs in s.covering_stops if cs.second_id is not None
        ),
        # i.e. highest (pi - walking_cost) first
    )

    unvisited_stops: list[Student] = []
    for s in all_students:
        if s.second_id not in route.served_students:
            if new_route:
                if pi.get(s.second_id, 0.0):
                    unvisited_stops.append(s)
            else:
                unvisited_stops.append(s)

    best_route = None
    successfully_added = False
    if new_route:
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
        if temp_route is not None:
            if (
                temp_route.total_distance <= problem_model.max_travel_distance
                and len(temp_route.served_students) <= problem_model.capacity_of_vehicle
            ):
                curr_route = _stop_swap(temp_route, problem_model, pi, mu)  # swap after each insert
                successfully_added = True
        unvisited_stops.remove(std)
    
    if successfully_added and curr_route.cost < 0:
        best_route = curr_route
        #print(
        #    f"Nearest insertion route result: Stops {[s.second_id for s in best_route.stops]}, Total distance: {best_route.total_distance}, Total walking distance: {best_route.total_walking_distance}, reduced cost : {best_route.cost}"
        #)
    return best_route


def _farthest_insertion(
    problem_model: InputModel,
    pi: dict[int, float],
    mu: float,
) -> Route | None:
    """Build a route by starting with the student hardest to serve
    and inserting others around them."""

    all_students = [
        s for s in problem_model.students if pi.get(s.second_id, 0.0) > 0
    ]
    if not all_students:
        return None

    # Seed: student with highest (pi - best_walking) — most valuable
    seed = max(
        all_students,
        key=lambda s: pi.get(s.second_id, 0.0) - min(
            problem_model.walking_distance_list[cs.second_id]
            for cs in s.covering_stops if cs.second_id is not None
        )
    )

    curr_route = Route(
        stops=[problem_model.first_depot, problem_model.last_depot],
        total_distance=0.0,
        total_walking_distance=0.0,
        served_students=[],
    )

    # Insert seed first
    temp = best_pickup_for_student(problem_model, seed, curr_route, pi, mu)
    if temp is None:
        return None
    curr_route = temp
    successfully_added = True

    remaining = [s for s in all_students if s.second_id != seed.second_id]

    while remaining:
        best_std = None
        best_temp = None
        best_gain = float("inf")

        for std in remaining:
            temp = best_pickup_for_student(problem_model, std, curr_route, pi, mu)
            if temp is not None:
                if (
                    temp.total_distance <= problem_model.max_travel_distance
                    and len(temp.served_students) <= problem_model.capacity_of_vehicle
                ):
                    if temp.cost < best_gain:
                        best_gain = temp.cost
                        best_temp = temp
                        best_std = std

        if best_std is None or best_temp is None:
            break

        curr_route = _stop_swap(best_temp, problem_model, pi, mu)
        remaining.remove(best_std)
    if successfully_added and curr_route and curr_route.cost < 0:
        return curr_route
    return None

def _stop_swap(route: Route, problem_model: InputModel, pi: dict, mu: float) -> Route:
    student_lookup = {s.second_id: s for s in problem_model.students}
    pickup_map = dict(getattr(route, "pickup_map", {}))

    improved = True
    while improved:
        improved = False
        for student_id in list(route.served_students):
            student = student_lookup.get(student_id)
            if student is None:
                continue

            current_stop_id = pickup_map.get(student_id)
            if current_stop_id is None:
                continue

            current_stop = next(
                (st for st in route.stops if st.second_id == current_stop_id), None
            )
            if current_stop is None:
                continue

            # Is this stop exclusive to student_id, or do other served
            # students also pick up here? If shared, we must not remove
            # or overwrite it on route.stops when student_id moves off it.
            stop_shared_with_others = any(
                sid != student_id and stid == current_stop_id
                for sid, stid in pickup_map.items()
            )

            for cs in student.covering_stops:
                if cs.second_id == current_stop_id:
                    continue

                new_walk = (
                    route.total_walking_distance
                    - problem_model.walking_distance_list[current_stop_id]
                    + problem_model.walking_distance_list[cs.second_id]
                )
                if new_walk >= route.total_walking_distance - 1e-6:
                    continue

                new_stop_already_in_route = any(
                    st.second_id == cs.second_id for st in route.stops
                )

                if not stop_shared_with_others:
                    # Safe to do the original in-place replacement.
                    new_stops = [
                        cs if st.second_id == current_stop_id else st
                        for st in route.stops
                    ]
                    new_dist = sum(
                        problem_model.distance_matrix[
                            (new_stops[k].second_id, new_stops[k + 1].second_id)
                        ]
                        for k in range(len(new_stops) - 1)
                    )
                    candidate_pickup_map = dict(pickup_map)
                    candidate_pickup_map[student_id] = cs.second_id

                elif new_stop_already_in_route:
                    # current_stop stays (others still need it); cs is
                    # already physically on the route, so no distance
                    # change — just remap this student to it.
                    new_stops = route.stops
                    new_dist = route.total_distance
                    candidate_pickup_map = dict(pickup_map)
                    candidate_pickup_map[student_id] = cs.second_id

                else:
                    # current_stop stays (others still need it), and cs
                    # is a genuinely new physical stop — insert it rather
                    # than replace, and cost the insertion properly.
                    candidate_stop, location, new_dist = (
                        _find_best_location_to_insert_stop_to_route(
                            route, cs, problem_model
                        )
                    )
                    if candidate_stop is None:
                        continue
                    new_stops = (
                        route.stops[:location] + [cs] + route.stops[location:]
                    )
                    candidate_pickup_map = dict(pickup_map)
                    candidate_pickup_map[student_id] = cs.second_id

                if new_dist <= problem_model.max_travel_distance:
                    new_cost = (
                        new_walk
                        - sum(pi.get(s, 0.0) for s in route.served_students)
                        - mu
                    )
                    new_route = Route(
                        stops=new_stops,
                        total_distance=new_dist,
                        total_walking_distance=new_walk,
                        served_students=route.served_students,
                        cost=new_cost,
                    )
                    new_route.pickup_map = candidate_pickup_map
                    route = new_route
                    pickup_map = candidate_pickup_map
                    improved = True
                    break
    return route

# the objective is to find a route with negative reduced cost that min (c_r -sum pi_i - mu) over all routes r
def generate_routes(routes, problem_model, pi, mu, lambdas, logger):
    logger.info("Starting heuristic pricing problem.")

    best_candidate = None
    routes_eligible = [r for r in routes[1:] if not getattr(r, "is_dummy", False)]

    # Pass 1: extend existing routes
    for route in routes_eligible:
        new_route = _nearest_insertion(route, problem_model, pi, mu)
        if new_route is not None:
            new_route = _stop_swap(new_route, problem_model, pi, mu)  # ← here
            if best_candidate is None or new_route.cost < best_candidate.cost:
                best_candidate = new_route

    # Pass 2: build fresh routes from positive-lambda seeds
    route_pos_lambda = [i for i, l in enumerate(lambdas) if l > 0.0]
    for idx in route_pos_lambda:
        new_route = _nearest_insertion(routes[idx], problem_model, pi, mu, new_route=True)
        if new_route is not None:
            new_route = _stop_swap(new_route, problem_model, pi, mu)
            if best_candidate is None or new_route.cost < best_candidate.cost:
                best_candidate = new_route

    # Pass 3: completely fresh route — always run
    fresh = _nearest_insertion(
        Route(
            stops=[problem_model.first_depot, problem_model.last_depot],
            total_distance=0.0,
            total_walking_distance=0.0,
            served_students=[],
        ),
        problem_model, pi, mu, new_route=True,
    )
    if fresh is not None:
        fresh = _stop_swap(fresh, problem_model, pi, mu)
        if best_candidate is None or fresh.cost < best_candidate.cost:
            best_candidate = fresh

    # Pass 4: farthest insertion with best-gain student selection
    farthest = _farthest_insertion(problem_model, pi, mu)
    if farthest is not None:
        farthest = _stop_swap(farthest, problem_model, pi, mu)
        if best_candidate is None or farthest.cost < best_candidate.cost:
            best_candidate = farthest

    if best_candidate is not None:
        added, routes = _add_route_to_master(best_candidate, routes, logger)
        if added:
            return ModelSuccess.SUCCESS, routes

    logger.info("No improving route found in heuristic pricing problem.")
    return ModelSuccess.NO_NEW_ROUTE, routes