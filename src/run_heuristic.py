from module.input_model import InputModel, DataSource
from module.stop_point import Stop, Student
from module.route import Route
from heuristic.heuristic_algorithm import nearest_insertion_route
from heuristic.label_setting import LabelSettingAlgorithmPulling
from heuristic.large_neighborhood_search import LargeNeighborhoodSearch
problem_model = InputModel(
    number_of_vehicles=2,
    capacity_of_vehicle=10,
    max_travel_distance=111.0,
    data_source=DataSource.REAL,
    allowed_walking_distance=1.5,
    school_id=33337,
)


lns =LargeNeighborhoodSearch(model=problem_model, max_iter=1)
lns.run()

#TODO
'''
2opt optimization, and running wit different seeds is left

'''