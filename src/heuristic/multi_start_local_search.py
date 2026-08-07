from module.route import Route
from module.input_model import InputModel
from heuristic.initial_route import (
    nearest_insertion_route,
    farthest_insertion_route,
    create_giant_feasible_route,
)
from heuristic.simulated_annealing import simulated_annealing_giant_route
from heuristic.split_route import SplitTour
from heuristic.feasibility_check import is_feasible, FeasibleResult
from heuristic.local_search import local_search_algorithm
from heuristic.label_setting import LabelSettingAlgorithmPulling
import random

class MultiStartLocalSearch:

    def __init__(self, model: InputModel, max_iter: int):
        self.model = model
        self.max_iter = max_iter
        #self.seed = seed
        self.routes: list[Route] = []

    def _route_key(self, route: Route) -> tuple[int, ...]:
        return tuple(s.second_id for s in route.stops)

    def run(self):
        #rng = random.Random()

        current_giant = nearest_insertion_route(
            self.model.students,
            self.model,
            seed=42,
            greediness=0.8,
        )

        current_split = SplitTour(self.model, current_giant).split()
        current_best_cost = float("inf")
        current_best_route = float("inf")
        best_solution = None

        if current_split and is_feasible(current_split, self.model).is_sucessful:
            current_split = local_search_algorithm(
                current_split,
                self.model.distance_matrix,
                self.model.max_travel_distance,
            )
            current_best_cost = sum(r.total_walking_distance for r in current_split)
            current_best_route = sum(r.total_distance for r in current_split)
            best_solution = current_split

        temperature = 100.0
        alpha = 0.99

        for iter in range(self.max_iter):
            print(f'--iter{iter}---')
            # perturb the current giant route, not a fresh unrelated one
            candidate_giant = simulated_annealing_giant_route(
                current_giant,
                self.model,
                seed=iter,
                steps=50,
                t0=temperature,
                alpha=alpha,
            )

            candidate_split = SplitTour(self.model, candidate_giant).split()
            if not candidate_split:
                temperature *= alpha
                continue

            feas = is_feasible(candidate_split, self.model)
            if not feas.is_sucessful:
                temperature *= alpha
                continue

            candidate_split = local_search_algorithm(
                candidate_split,
                self.model.distance_matrix,
                self.model.max_travel_distance,
            )

            candidate_cost = sum(r.total_walking_distance for r in candidate_split)
            candidate_distance = sum(r.total_distance for r in candidate_split)

            # always improve best-so-far
            if candidate_cost == current_best_cost and candidate_distance < current_best_route:
                best_solution = candidate_split
                current_best_cost = candidate_cost

            if candidate_cost < current_best_cost:
                best_solution = candidate_split
                current_best_cost = candidate_cost

            # accept/reject for the next iteration
            if candidate_cost <= current_best_cost:
                current_giant = candidate_giant

            temperature *= alpha

        return best_solution

    def run2(self):
        best_solution: list[Route] | None = None
        best_cost = float("inf")
        
        seen_routes: set[tuple[int, ...]] = set()

        for iter in range(self.max_iter):
            print(f"--iter:{iter}--------")

            giant_route = nearest_insertion_route(
                self.model.students,
                self.model,
                seed=iter,
                greediness=0.8
            )

            # Perturb the giant route with simulated annealing
            #giant_route = simulated_annealing_giant_route(
            #    base_route,
            #    self.model,
            #    seed=iter,
            #    steps=300,
            #    t0=50.0,
            #    alpha=0.99,
            #)

            key = tuple(s.second_id for s in giant_route.stops)
            if key in seen_routes:
                continue

            seen_routes.add(key)

            #print(str(giant_route))

            result = SplitTour(self.model, giant_route).split()
            
            if not result:
                continue

            feasibility_result = is_feasible(result, self.model)

            if not feasibility_result.is_sucessful:
                continue

            
            improved_solution = local_search_algorithm(
                result,
                self.model.distance_matrix,
                self.model.max_travel_distance,
            )

            # Define objective
            current_cost = sum(r.total_walking_distance for r in improved_solution)

            if current_cost < best_cost:
                best_cost = current_cost
                best_solution = improved_solution

                print(
                    f"Iteration {iter}: New best solution found "
                    f"with cost {best_cost:.2f}"
                )

        return best_solution