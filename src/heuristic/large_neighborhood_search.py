from module.route import Route
from module.label_setting_point import Label
from module.input_model import InputModel
from module.stop_point import Stop, STOP_TYPE
from module.label_setting_point import Label
from heuristic.heuristic_algorithm import nearest_insertion_route
from heuristic.label_setting import LabelSettingAlgorithmPulling
from heuristic.split_route import SplitTour
from heuristic.feasibility_check import is_feasible, FeasibleResult, FEASIBILITY
from heuristic.local_search import local_search_algorithm


class LargeNeighborhoodSearch:
    seed_val = 42

    def __init__(self, model: InputModel, max_iter: int):
        self.model = model
        self.max_iter = max_iter
        self.routes: list[Route] = []

    def run(self):

        for iter in range(self.max_iter):
            giant_route: Route = nearest_insertion_route(
                self.model.students, self.model, self.seed_val
            )

            result: list[Route]|None = SplitTour(self.model, giant_route).split()
            if result:
                print(f'number of return routes: {len(result)}')
                for r in result:
                    print(str(r))

            return result
            #if result:
            #    feasibility_result: FeasibleResult = is_feasible(result, self.model)
            #    new_improved_routes = []
            #    if feasibility_result.is_sucessful:
            #        for r in result:
            #            improved_route_result = local_search_algorithm(r)
            #            new_improved_routes.append(improved_route_result)
