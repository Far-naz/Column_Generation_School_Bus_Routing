from module.input_model import InputModel
from module.stop_point import Stop, Student
from module.route import Route
from heuristic.label_setting import LabelSettingAlgorithmPulling


import random
from dataclasses import dataclass, field


@dataclass
class _StudentNode:
    student: Student
    min_dist_to_tour: (
        float  # minimum distance from this stop to any stop in the current tour
    )


def farthest_insertion_route(
    students: list[Student],
    problem_model: InputModel,
    seed: int,
) -> Route:
    """
    Giant tour construction via farthest insertion.

    Each iteration:
      1. Select the unvisited stop FARTHEST from the current partial tour.
      2. Insert it at the CHEAPEST arc (minimum detour cost).
      3. Update min_dist_to_tour for all remaining unvisited stops.

    `seed` controls which stop seeds the initial 2-node sub-tour, giving
    diverse starting points across iterations.
    """
    if not students:
        return Route(
            stops=[problem_model.first_depot, problem_model.last_depot],
            total_distance=problem_model.distance_matrix[
                (
                    problem_model.first_depot.second_id,
                    problem_model.last_depot.second_id,
                )
            ],
            total_walking_distance=0.0,
            served_students=[],
        )

    dm = problem_model.distance_matrix
    wl = problem_model.walking_distance_list
    depot_id = problem_model.first_depot.second_id

    # --- Seed selection ------------------------------------------------
    # Sort by distance from depot for reproducibility, then offset by seed.
    ordered = sorted(
        students,
        key=lambda s: dm[(depot_id, s.second_id)],
    )
    seed_student = ordered[seed % len(ordered)]

    # --- Initial 2-node sub-tour: depot → seed_student → depot ----------
    route_stops: list[Stop] = [
        problem_model.first_depot,
        seed_student,
        problem_model.last_depot,
    ]
    total_walking = wl[seed_student.second_id]

    # --- Initialise unvisited nodes with distance to the seed stop ------
    # Mirrors C# Initialize() + first distance update after FindSecondFarthestStop.
    unvisited: list[_StudentNode] = [
        _StudentNode(
            student=s,
            min_dist_to_tour=min(
                dm[(depot_id, s.second_id)],
                dm[(seed_student.second_id, s.second_id)],
            ),
        )
        for s in ordered
        if s.second_id != seed_student.second_id
    ]

    # --- Main loop ------------------------------------------------------
    while unvisited:

        # Step 1: pick the stop FARTHEST from the current tour
        # Mirrors FindInsertNextStop() selection block in C#.
        farthest_node = max(unvisited, key=lambda n: n.min_dist_to_tour)
        selected: Student = farthest_node.student

        # Step 2: find the cheapest arc to insert `selected` into
        # Mirrors the arc-traversal do-while loop in C#.
        best_position = 1
        best_insertion_cost = float("inf")

        for i in range(1, len(route_stops)):
            prev = route_stops[i - 1]
            nxt = route_stops[i]
            cost = (
                dm[(prev.second_id, selected.second_id)]
                + dm[(selected.second_id, nxt.second_id)]
                - dm[(prev.second_id, nxt.second_id)]
            )
            if cost < best_insertion_cost:
                best_insertion_cost = cost
                best_position = i

        # Step 3: insert
        route_stops.insert(best_position, selected)
        total_walking += wl[selected.second_id]
        unvisited.remove(farthest_node)

        # Step 4: update min_dist_to_tour for remaining unvisited stops
        # Mirrors the distance-update block at the end of FindInsertNextStop().
        for node in unvisited:
            d_to_new = dm[(node.student.second_id, selected.second_id)]
            if d_to_new < node.min_dist_to_tour:
                node.min_dist_to_tour = d_to_new

    # --- Compute total route distance -----------------------------------
    total_distance = sum(
        dm[(route_stops[i].second_id, route_stops[i + 1].second_id)]
        for i in range(len(route_stops) - 1)
    )

    return Route(
        stops=route_stops,
        total_distance=total_distance,
        total_walking_distance=total_walking,
        served_students=[
            s.second_id
            for s in route_stops
            if s.second_id != problem_model.first_depot.second_id
            and s.second_id != problem_model.last_depot.second_id
        ],
    )


def nearest_insertion_route(
    students: list[Student],
    problem_model: InputModel,
    seed: float,
    greediness: float = 0.1,  # 0.0 = fully random, 1.0 = fully greedy
) -> Route:
    """
    Nearest insertion heuristic for the giant tour.

    Parameters
    ----------
    seed        : controls randomness — different seeds produce different tours
    greediness  : fraction of the candidate list that is the 'elite' set.
                  A random choice is made within the elite set (GRASP-style).
                  1.0 = always pick the best insertion (original deterministic behaviour).
                  0.0 = pick from the full candidate list uniformly.
    """
    rng = random.Random(seed)  # isolated RNG — does not affect global state

    unvisited = students.copy()

    first_stop = problem_model.first_depot
    last_stop = problem_model.last_depot

    # --- Seed-dependent starting stop -----------------------------------
    # Sort by distance for reproducibility, then pick a random position
    # biased toward the front (closer stops are more likely but not certain).
    unvisited.sort(
        key=lambda s: problem_model.distance_matrix[(first_stop.second_id, s.second_id)]
    )

    # Draw starting index from the first third of the sorted list,
    # so seeds still produce tours of reasonable quality.
    start_range = max(1, len(unvisited) // 3)
    start_idx = rng.randint(0, start_range - 1)
    seed_stop = unvisited.pop(start_idx)

    route_stops: list[Stop] = [first_stop, seed_stop, last_stop]
    total_distance = (
        problem_model.distance_matrix[(first_stop.second_id, seed_stop.second_id)]
        + problem_model.distance_matrix[(seed_stop.second_id, last_stop.second_id)]
    )
    total_walking_distance = problem_model.walking_distance_list[seed_stop.second_id]

    # --- Main insertion loop -------------------------------------------
    while unvisited:
        # Evaluate every (stop, position) pair and collect all candidates.
        candidates: list[tuple[float, Student, int]] = []

        for stop in unvisited:
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
                candidates.append((added_distance, stop, i))

        if not candidates:
            break

        # --- GRASP-style elite selection --------------------------------
        candidates.sort(key=lambda c: c[0])

        elite_size = max(1, int(len(candidates) * greediness))
        # Clamp so at seed=0 with greediness=1.0 we still get deterministic
        # best-first behaviour.
        if greediness >= 1.0:
            chosen_cost, stop_to_insert, insert_position = candidates[0]
        else:
            elite = candidates[:elite_size]
            chosen_cost, stop_to_insert, insert_position = rng.choice(elite)

        route_stops.insert(insert_position, stop_to_insert)
        total_distance += chosen_cost
        total_walking_distance += problem_model.walking_distance_list[
            stop_to_insert.second_id
        ]
        unvisited.remove(stop_to_insert)

    new_route = Route(
        stops=route_stops,
        total_distance=total_distance,
        total_walking_distance=total_walking_distance,
        served_students=[
            s.second_id
            for s in route_stops
            if s.second_id != first_stop.second_id
            and s.second_id != last_stop.second_id
        ],
    )
    return new_route


def create_giant_feasible_route(route: Route, model: InputModel) -> Route:
    improved_route: Route | None = LabelSettingAlgorithmPulling(route, model).run()
    if improved_route is not None:
        return improved_route
    return route


def generate_giant_route_population(
    students: list[Student],
    problem_model: InputModel,
    num_routes: int = 10,
    greediness: float = 0.3,
) -> list[Route]:
    """
    Generate a diverse population of giant tours by running nearest insertion
    with different seeds, then repair each via label setting.

    This is the intended entry point for branch-and-price initialisation
    or any metaheuristic that needs a pool of starting solutions.
    """
    routes: list[Route] = []
    seen_stop_sequences: set[tuple[int, ...]] = set()

    for seed in range(num_routes * 3):  # over-generate to allow dedup
        candidate = nearest_insertion_route(
            students, problem_model, seed=seed, greediness=greediness
        )
        feasible = create_giant_feasible_route(candidate, problem_model)

        # Deduplicate by stop sequence so the population stays diverse.
        key = tuple(s.second_id for s in feasible.stops)
        if key not in seen_stop_sequences:
            seen_stop_sequences.add(key)
            routes.append(feasible)

        if len(routes) >= num_routes:
            break

    # Sort by total walking distance so callers get the best routes first.
    routes.sort(key=lambda r: r.total_walking_distance)
    return routes


"""
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
"""
