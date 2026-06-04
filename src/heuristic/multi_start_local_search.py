from module.route import Route
from module.input_model import InputModel
from heuristic.initial_route import (
    nearest_insertion_route,
    farthest_insertion_route,
    create_giant_feasible_route,
)
from heuristic.split_route import SplitTour
from heuristic.feasibility_check import is_feasible, FeasibleResult
from heuristic.local_search import local_search_algorithm
import random
from datetime import datetime


class LargeNeighborhoodSearch:

    def __init__(self, model: InputModel, max_iter: int):
        self.model = model
        self.max_iter = max_iter
        self.routes: list[Route] = []

    def run(self):
        improved_result = []
        for iter in range(self.max_iter):
            print("-------------------")
            random.seed(datetime.now().timestamp())
            seed_val = random.random()
            giant_route: Route | None = nearest_insertion_route(
                self.model.students, self.model, iter
            )

            print(str(giant_route))

            if giant_route is not None:
                result: list[Route] | None = SplitTour(self.model, giant_route).split()

                if result:
                    print(f"number of return routes: {len(result)}")

                    if len(result) > 0:
                        feasibility_result: FeasibleResult = is_feasible(
                            result, self.model
                        )

                        if feasibility_result.is_sucessful:

                            improved_result = local_search_algorithm(
                                result,
                                self.model.distance_matrix,
                                self.model.max_travel_distance,
                            )

                # else:
                #    print('Cannot split')

        if improved_result is not None:
            for r in improved_result:
                print(str(r))

        return improved_result
