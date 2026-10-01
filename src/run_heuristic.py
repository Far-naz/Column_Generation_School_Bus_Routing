from module.input_model import InputModel, DataSource
from heuristic.multi_start_local_search import MultiStartLocalSearch
from helper.logger_setup import setup_logger
from helper.results_db import RunRecorder
from datetime import datetime


def solve(
    number_of_vehicles,
    capacity_of_vehicle,
    max_travel_distance,
    allowed_walking_distance,
    school_id,
    data_source= DataSource.REAL,
):
    problem_model = InputModel(
        number_of_vehicles=number_of_vehicles,
        capacity_of_vehicle=capacity_of_vehicle,
        max_travel_distance=max_travel_distance,
        data_source=data_source,
        allowed_walking_distance=allowed_walking_distance,
        school_id=school_id,
    )

    model_info = (
        f"[S={len(problem_model.students)}"
        f",B={problem_model.number_of_vehicles}"
        f",Cap={problem_model.capacity_of_vehicle}"
        f",D={problem_model.max_travel_distance}"
        f",W={problem_model.allowed_walking_dist}],"
        f"{problem_model.school_id}"
    )

    logger = setup_logger(f"heuristic_{model_info}")
    logger.info(f"Model info: {model_info}")
    logger.info(f"Number of stops in the problem model: {len(problem_model.all_stops)}")

    params = {"max_iter": 250}
    with RunRecorder("heuristic", problem_model, params, logger) as rec:
        start_time = datetime.now()
        lns = MultiStartLocalSearch(model=problem_model, max_iter=params["max_iter"])
        logger.info(f"max_iter: {lns.max_iter}")
        results = lns.run()

        end_time = datetime.now()
        logger.info(f"Total time taken: {end_time - start_time}")
        if results:
            logger.info(
                f'total route distance: {sum(r.total_distance for r in results) if results else "N/A"}, total walking distance: {sum(r.total_walking_distance for r in results) if results else "N/A"}'
            )
            for re in results:
                # print(str(re))
                logger.info(str(re))
        rec.set_result(results)
    return results


if __name__ == "__main__":
    solve(
        number_of_vehicles=2,
        capacity_of_vehicle=100,
        max_travel_distance=18.80,
        data_source=DataSource.REAL,
        allowed_walking_distance=0.5,
        school_id=42539,
    )
    #(2, 100, 95.0, 0.5, 40755)
