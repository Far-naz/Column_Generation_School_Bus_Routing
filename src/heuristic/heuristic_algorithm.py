from module.input_model import InputModel
from module.stop_point import Stop, Student
from module.route import Route
from heuristic.label_setting import LabelSettingAlgorithmPulling

def nearest_insertion_route(
    students: list[Student], problem_model: InputModel, seed: int
) -> Route:

    unvisited_stops = students.copy()
    unvisited_stops.sort(
        key=lambda s: problem_model.distance_matrix[
            (problem_model.first_depot.second_id, s.second_id)
        ]
    )

    first_stop = problem_model.first_depot
    last_stop = problem_model.last_depot

    route_stops = [first_stop, last_stop]
    total_distance = problem_model.distance_matrix[
        (first_stop.second_id, last_stop.second_id)
    ]
    total_walking_distance = 0.0

    max_it = 10
    while unvisited_stops and max_it > 0:
        max_it -= 1
        best_insertion = None
        best_insertion_cost = float("inf")
        for stop in unvisited_stops:
            for i in range(1, len(route_stops)):
                prev_stop = route_stops[i - 1]
                next_stop = route_stops[i]
                added_distance = (
                    problem_model.distance_matrix[(prev_stop.second_id, stop.second_id)]
                    + problem_model.distance_matrix[
                        (stop.second_id, next_stop.second_id)
                    ]
                    - problem_model.distance_matrix[
                        (prev_stop.second_id, next_stop.second_id)
                    ]
                )
                if added_distance < best_insertion_cost:
                    best_insertion_cost = added_distance
                    best_insertion = (stop, i, added_distance)

        if best_insertion is None:
            break

        stop_to_insert, insert_position, distance_increase = best_insertion
        route_stops.insert(insert_position, stop_to_insert)
        total_distance += distance_increase
        unvisited_stops.remove(stop_to_insert)

    new_route = Route(
        stops=route_stops,
        total_distance=total_distance,
        total_walking_distance=total_walking_distance,
        served_students=[s.second_id for s in route_stops],
    )
    print(f"Final route stops after nearest insertion: {str(new_route)}.")
    return new_route

def create_giant_feasible_route(route: Route, model):
    label_setting = LabelSettingAlgorithmPulling(
        route, model
    )
    improved_route: Route | None = label_setting.run()
    if improved_route is not None:
        if route.total_distance < improved_route.total_distance:
           print(
               f"Improved route via label setting: Stops {[s.second_id for s in improved_route.stops]}, "
               f"Total distance: {improved_route.total_distance}, Total cost: {improved_route.cost}, total walking distance: {improved_route.total_walking_distance}"
           )
        return improved_route
        # else:
        # print(f'the route could not be improved via label setting, improved cost: {improved_route.total_distance}, improved cost: {improved_route.cost}, total walking distance: {improved_route.total_walking_distance}')
    else:
        return route

'''from module.stop_point import Stop, STOP_TYPE,Student
from module.route import Route
from module.input_model import InputModel
from heuristic.label_setting import LabelSettingAlgorithmPulling
import module.sucess_result as mr
import random


random.seed(42)


def route_single_student(
    stop: Stop,
    distances: dict[tuple[int, int], float],
    first_depot: Stop,
    last_depot: Stop,
) -> Route:
    """Create a route that serves a single student at the given stop."""
    if not stop.stop_type == STOP_TYPE.STUDENT:
        raise ValueError("The provided stop does not correspond to a student.")

    distance_to_depot = (
        distances[(stop.id, first_depot.id)] + distances[(last_depot.id, stop.id)]
    )
    route = Route(
        stops=[first_depot, stop, last_depot],
        total_distance=distance_to_depot,
        total_walking_distance=0.0,
        served_students=[stop.second_id],
    )
    return route


def create_initial_route(
    students: list[Stop],
    distances: dict[tuple[int, int], float],
    first_depot: Stop,
    last_depot: Stop,
) -> list[Route]:
    """Create initial routes, each serving a single student."""
    print("Creating initial routes...")
    initial_routes = []
    all_students = [stop for stop in students]
    for stop in all_students:
        route = route_single_student(
            stop, distances, first_depot=first_depot, last_depot=last_depot
        )
        initial_routes.append(route)
    return initial_routes


def insert_stop_to_route(
    route: Route,
    new_stop: Stop,
    problem_model: InputModel,
    pi: dict[int, float],
    mu: float,
) -> Route | None:
    """Insert a new stop into the existing route at the best position."""
    # print(f"Trying to insert stop {new_stop.second_id} into route with stops {[s.second_id for s in route.stops]}")
    best_distance = float("inf")
    best_stops = None
    best_served_students = None

    # first and last positions are depot, so we insert between them
    new_distance = route.total_distance
    for i in range(1, len(route.stops) - 1):
        new_stops = route.stops[:i] + [new_stop] + route.stops[i:]
        # remove the distance between i-1 and i, and add distances for new edges
        new_distance = (
            route.total_distance
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
            best_stops = new_stops
            best_served_students = list(route.served_students) + [new_stop.second_id]

    if best_stops is not None and best_served_students is not None:
        walking_distance = (
            route.total_walking_distance
            + problem_model.walking_distance_list[new_stop.second_id]
        )
        cost = walking_distance - sum(pi[i] for i in best_served_students) - mu
        return Route(
            stops=best_stops,
            total_distance=best_distance,
            served_students=best_served_students,
            total_walking_distance=walking_distance,
            cost=cost,
        )
    else:
        return None


def is_route_feasible(route, problem_model):
    # based on problem_model.max_route_distance
    return route.total_distance <= problem_model.max_route_distance


def select_stop_to_insert(
    route: Route,
    candidate_students: list[Student],
    problem_model: InputModel,
    pi: dict[int, float],
    mu: float,
) -> Route | None:
    """
    Select the best stop to insert based on marginal reduced cost.
    Returns None if no improving insertion exists.
    """
    # print(
    #    f"Inserting: select best stop of route with stops {[s.second_id for s in route.stops]}"
    # )
    best_route = route.__copy__()
    best_delta_rc = 0.0  # must be negative to improve

    for std in candidate_students:
        if std.second_id in route.served_students:
            continue

        for candidate_stop in std.covering_stops:
            new_route_for_std = insert_stop_to_route(
                best_route, candidate_stop, problem_model, pi, mu
            )

            if new_route_for_std is not None:
                delta_cost = new_route_for_std.cost - route.cost
                delta_rc = delta_cost

                if delta_rc < best_delta_rc:
                    best_delta_rc = delta_rc
                    best_route = new_route_for_std

    return best_route


def improvement_route(
    route: Route, model: InputModel, pi: list[float], mu: float, find_new_stop=True
) -> Route | None:
    print(
        f"Label setting. initial route found via graph: Stops {[s.second_id for s in route.stops]}, Total distance: {route.total_distance}, Total walking distance: {route.total_walking_distance}"
    )
    try:
        # best_route = route.__copy__()
        label_setting = LabelSettingAlgorithmPulling(
            route, model, pi, mu, find_new_stop
        )
        improved_route: Route | None = label_setting.run()
        if improved_route is not None:
            # if best_route.total_distance < improved_route.total_distance:
            #    print(
            #        f"Improved route via label setting: Stops {[s.second_id for s in improved_route.stops]}, "
            #        f"Total distance: {improved_route.total_distance}, Total cost: {improved_route.cost}, total walking distance: {improved_route.total_walking_distance}"
            #    )
            return improved_route
            # else:
            # print(f'the route could not be improved via label setting, improved cost: {improved_route.total_distance}, improved cost: {improved_route.cost}, total walking distance: {improved_route.total_walking_distance}')
        else:
            return route
    except Exception as e:
        print(f"Label setting failed with exception: {e}")
        return None


def check_new_route_is_duplicate(
    new_route: Route,
    existing_routes: list[Route],
) -> bool:
    """Check if the new route is a duplicate of any existing route."""
    new_route_stops = [stop.second_id for stop in new_route.stops]
    for route in existing_routes:
        existing_route_stops = route["nodes"]
        if new_route_stops == existing_route_stops:
            return True
    return False


def check_duplicate_routes(routes: list[Route]) -> bool:
    """Check for duplicate routes with the same set of ordered stops."""
    seen_routes = set()
    for route in routes:
        route_signature = tuple(stop.id for stop in route.stops)
        # reverse order to consider routes that are the same in reverse
        reverse_signature = tuple(reversed(route_signature))
        if route_signature in seen_routes or reverse_signature in seen_routes:
            return True
        seen_routes.add(route_signature)
    return False


def add_route_to_master(route, routes, logger, reduced_cost):
    if check_new_route_is_duplicate(route, routes):
        print("New route is a duplicate. Skipping.")
        return False, routes
    else:
        new_route = {
            "nodes": [stop.second_id for stop in route.stops],
            "cost": route.total_walking_distance,
            "cover": route.served_students,
            "pickup_point": [
                stop.second_id for stop in route.stops if not stop.is_depot
            ],
            "distance": route.total_distance,
        }

        routes.append(new_route)
        logger.info(
            f"New route successfully added. route: {new_route}, with negative Reduced cost: {reduced_cost}"
        )
        return True, routes


def add_single_route_to_master(
    init_routes, problem_model: ProblemModel, pi: dict[int, float], mu: float, logger
) -> list[Route]:
    logger.info("Adding single student routes to master problem.")

    for std in problem_model.S_H:
        route: Route = route_single_student(
            std,
            problem_model.distance_matrix,
            problem_model.first_depot,
            problem_model.last_depot,
        )
        route.cost = route.total_walking_distance - pi[std.second_id] - mu
        add_route_to_master(route, init_routes, logger, route.cost)

        imp_route = improvement_route(route, problem_model, pi, mu, find_new_stop=False)
        if imp_route is not None:
            imp_route.cost = (
                imp_route.total_walking_distance
                - sum(pi[i] for i in imp_route.served_students)
                - mu
            )
            if imp_route.cost < 0:
                added, init_routes = add_route_to_master(
                    imp_route, init_routes, logger, imp_route.cost
                )
                if added:
                    logger.info(
                        f"Improved single student route added: Stops {[s.second_id for s in imp_route.stops]}, Total distance: {imp_route.total_distance}, Total walking distance: {imp_route.total_walking_distance}, Cost: {imp_route.cost}"
                    )

    return init_routes


def remove_stop_from_route(
    stop_to_remove: int,
    route_stops: list[Stop],
    distance: float,
    walking_distance: float,
    problem_model: ProblemModel,
    pi: dict[int, float],
    mu: float,
) -> Route:
    # print(f"Removing stop {stop_to_remove.second_id} from route with stops {[s.second_id for s in route_stops]}")
    if stop_to_remove not in [s.second_id for s in route_stops]:
        print(
            f"Route stops: {[s.second_id for s in route_stops]}, stop to remove: {stop_to_remove}"
        )
        return None

    remove_index = [s.second_id for s in route_stops].index(stop_to_remove)
    selcted_stop_to_remove: Stop = route_stops[remove_index]

    if remove_index == 0 or remove_index == len(route_stops) - 1:
        print("Cannot remove depot stops.")
        return None

    new_stops = route_stops[:remove_index] + route_stops[remove_index + 1 :]

    new_distance = (
        distance
        - problem_model.distance_matrix[
            (
                route_stops[remove_index - 1].second_id,
                selcted_stop_to_remove.second_id,
            )
        ]
        - problem_model.distance_matrix[
            (
                selcted_stop_to_remove.second_id,
                route_stops[remove_index + 1].second_id,
            )
        ]
        + problem_model.distance_matrix[
            (
                route_stops[remove_index - 1].second_id,
                route_stops[remove_index + 1].second_id,
            )
        ]
    )
    new_distance += problem_model.distance_matrix[
        route_stops[remove_index - 1].second_id,
        route_stops[remove_index + 1].second_id,
    ]

    new_walking_distance = (
        walking_distance
        - problem_model.walking_distance_list[selcted_stop_to_remove.second_id]
    )

    new_route_stops: list[Stop] = route_stops.copy()
    new_route_stops.remove(selcted_stop_to_remove)

    cover_students = [
        s.std_id for s in new_route_stops if s.is_student and not s.is_covered
    ]

    reduced_cost = (new_walking_distance) - sum(pi[i] for i in cover_students) - mu

    return Route(
        stops=new_stops,
        total_distance=new_distance,
        total_walking_distance=new_walking_distance,
        served_students=cover_students,
        cost=reduced_cost,
    )


def nearest_insertion_route(
    stops: list[Stop], problem_model: ProblemModel, pi, mu
) -> Route:
    # create a route with nearest insertion heuristic
    unvisited_stops = stops.copy()
    # sort unvisited stops by distance to depot
    unvisited_stops.sort(
        key=lambda s: problem_model.distance_matrix[
            (problem_model.first_depot.second_id, s.second_id)
        ]
    )

    first_stop = problem_model.first_depot
    last_stop = problem_model.last_depot

    route_stops = [first_stop, last_stop]
    total_distance = problem_model.distance_matrix[
        (first_stop.second_id, last_stop.second_id)
    ]
    total_walking_distance = 0.0
    served_students = []

    fail = True
    max_it = 10
    while unvisited_stops and max_it > 0:
        max_it -= 1
        best_insertion = None
        best_insertion_cost = float("inf")
        for stop in unvisited_stops:
            for i in range(1, len(route_stops)):
                prev_stop = route_stops[i - 1]
                next_stop = route_stops[i]
                added_distance = (
                    problem_model.distance_matrix[(prev_stop.second_id, stop.second_id)]
                    + problem_model.distance_matrix[
                        (stop.second_id, next_stop.second_id)
                    ]
                    - problem_model.distance_matrix[
                        (prev_stop.second_id, next_stop.second_id)
                    ]
                )
                if added_distance < best_insertion_cost:
                    best_insertion_cost = added_distance
                    best_insertion = (stop, i, added_distance)

        if best_insertion is None:
            break

        stop_to_insert, insert_position, distance_increase = best_insertion
        route_stops.insert(insert_position, stop_to_insert)
        total_distance += distance_increase
        if stop_to_insert.is_student:
            served_students.append(stop_to_insert.std_id)
            total_walking_distance += problem_model.walking_distance_list[
                stop_to_insert.second_id
            ]
        unvisited_stops.remove(stop_to_insert)

    if total_distance > problem_model.max_route_distance:
        imp_route = improvement_route(
            Route(
                stops=route_stops,
                total_distance=total_distance,
                total_walking_distance=total_walking_distance,
                served_students=served_students,
            ),
            problem_model,
            pi,
            mu,
            True,
        )
        if (
            imp_route is not None
            and imp_route.total_distance <= problem_model.max_route_distance
        ):
            route_stops = imp_route.stops
            total_distance = imp_route.total_distance
            total_walking_distance = imp_route.total_walking_distance
            served_students = imp_route.served_students
        else:
            best_cost = float("inf")
            best_route = None
            for st in imp_route.served_students:
                new_route = remove_stop_from_route(
                    st,
                    route_stops,
                    total_distance,
                    total_walking_distance,
                    problem_model,
                    pi,
                    mu,
                )
                if (
                    new_route is not None
                    and new_route.total_distance <= problem_model.max_route_distance
                ):
                    if new_route.cost < best_cost:
                        best_cost = new_route.cost
                        best_route = new_route
            if best_route is not None:
                route_stops = best_route.stops
                total_distance = best_route.total_distance
                total_walking_distance = best_route.total_walking_distance
                served_students = best_route.served_students
            else:
                return None
    print(
        f"Final route stops after nearest insertion: {[s.second_id for s in route_stops]}, with total distance {total_distance} and walking distance {total_walking_distance}."
    )
    if len(route_stops) <= 2:
        print("No stops inserted into the route.")
        return None
    new_route = Route(
        stops=route_stops,
        total_distance=total_distance,
        total_walking_distance=total_walking_distance,
        served_students=served_students,
    )
    return new_route


def create_route_by_students(
    positive_pi_students, problem_model, routes, pi, mu, logger
) -> Route:
    logger.info("Creating new route from positive dual students.")
    order_pi = sorted(positive_pi_students, key=lambda s_id: pi[s_id], reverse=True)
    students_pi = [s for s in problem_model.S_H if s.second_id in order_pi]
    new_route: Route | None = nearest_insertion_route(
        students_pi, problem_model, pi, mu
    )
    if new_route is not None:
        new_route.cost = (
            new_route.total_walking_distance
            - sum(pi[i] for i in new_route.served_students)
            - mu
        )
        if new_route.cost < -1e-6:
            return new_route
    return None


def heuristic_pricing_problem(
    routes: list[dict],
    problem_model: ProblemModel,
    pi: dict[int, float],
    mu: float,
    iteration: int,
    logger,
) -> tuple:
    logger.info("Starting heuristic pricing problem.")

    max_cost = float("inf")
    best_route = None
    for r in routes[1:]:
        route = Route(
            stops=[problem_model.all_stops[stop_id] for stop_id in r["nodes"]],
            total_distance=r["distance"],
            total_walking_distance=r["cost"],
            served_students=r["cover"],
        )
        temp_route = select_stop_to_insert(
            route, problem_model.S_H, problem_model, pi, mu
        )
        if temp_route is not None and temp_route.cost < max_cost:
            max_cost = temp_route.cost
            best_route = temp_route

    if best_route is not None and best_route.cost < -1e-6:
        logger.info(
            f"Heuristic pricing problem found new route with reduced cost: {best_route.cost}"
        )
        add_route_to_master(best_route, routes, logger, best_route.cost)
    else:

        logger.info(
            f"Heuristic pricing problem found new route with reduced cost: {best_route.cost}"
        )
        for r in routes[1:]:
            route = Route(
                stops=[problem_model.all_stops[stop_id] for stop_id in r["nodes"]],
                total_distance=r["distance"],
                total_walking_distance=r["cost"],
                served_students=r["cover"],
            )
            improved_route: Route | None = improvement_route(
                route, problem_model, pi, mu, True
            )
            if improved_route != None:
                if improved_route.cost < 0:
                    logger.info(
                        f"Improved route found with reduced cost: {improved_route.cost}"
                    )
                    result_improve, routes = add_route_to_master(
                        improved_route, routes, logger, improved_route.cost
                    )
                    if result_improve:
                        return mr.ModelSuccess.SUCCESS, routes
                    else:
                        continue
                else:
                    continue
            else:
                continue
    return mr.ModelSuccess.NO_NEW_ROUTE, routes


# from read_students import DataSource
# problem_model = ProblemModel(
#   numberOfVehicles=2,
#   vehicleCapacity=20,
#   maxTravelDistance=22.22,
#   DataSource=DataSource.TOY,
#   allowed_walking_dist=1,
#   school_id=33337,
# )

# routes = create_initial_route(
#   problem_model.all_stops,
#   problem_model.distance_matrix,
#   problem_model.first_depot,
#   problem_model.last_depot,
# )  # for testing purposes

# print("Initial route:")
# for r in routes:
#   print(
#       f"Route stops: {[s.second_id for s in r.stops]}, Total distance: {r.total_distance}, total walking distance: {r.total_walking_distance}"
#   )
# pi = {stop.second_id: random.uniform(0, 10) for stop in problem_model.all_stops}
# mu = random.uniform(0, 10)
# improved_route = select_stop_to_insert(
#   routes[4],
#    problem_model.S_H,
#   problem_model,
#   pi,
#   mu
# )
# print("Improved route after selecting stop to insert:")
# if improved_route is not None:
#    covered_students = improved_route.served_students
#    print(
#        f"Route stops: {[s.second_id for s in improved_route.stops]}, Total distance: {improved_route.total_distance}, total walking distance: {improved_route.total_walking_distance}, cost: {improved_route.cost}, covered students: {covered_students}"
#    )
#
# best_route = find_best_stop_route(improved_route, problem_model)'''
