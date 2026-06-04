from module.input_model import InputModel, DataSource
from heuristic.multi_start_local_search import LargeNeighborhoodSearch

problem_model = InputModel(
    number_of_vehicles=2,
    capacity_of_vehicle=10,
    max_travel_distance=112.5,
    data_source=DataSource.REAL,
    allowed_walking_distance=0.1,
    school_id=33337,
)


lns = LargeNeighborhoodSearch(model=problem_model, max_iter=50)
lns.run()
