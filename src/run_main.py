from module.input_model import InputModel, DataSource
from helper.logger_setup import setup_logger
from math_modelling.mip_model import main_problem, shotest_path, minmax_problem
from module.sucess_result import ModelSuccess
from branch_and_price.column_generation import main_column_generation
from module.route import Route
from branch_and_price.models import solve_final_model
from branch_and_price.warm_start import create_initial_route
from heuristic.helper import drop_duplicate_students
from helper.results_db import RunRecorder
from helper.time_budget import Deadline
from config import TIME_LIMIT, FINAL_MODEL_RESERVE, PRICING_TIME_LIMIT
import branch_and_price.column_generation as cg
import branch_and_price.models as models
import branch_and_price.pricing_heuristic as ph

import logging
from datetime import datetime

# Gurobi's "no limit" value, used when time_limit is None.
NO_TIME_LIMIT = 1e100


def _cg_params(time_limit) -> dict:
    """Algorithm settings of the column generation run, for reproducibility."""
    return {
        "time_limit": time_limit,
        "final_model_reserve": FINAL_MODEL_RESERVE,
        "root_max_iter": cg.ROOT_MAX_ITER,
        "node_max_iter": cg.NODE_MAX_ITER,
        "bp_max_depth": cg.BP_MAX_DEPTH,
        "pricing_time_limit": PRICING_TIME_LIMIT,
        "pricing_rc_tol": models.PRICING_RC_TOL,
        "heuristic_rc_tol": ph.RC_TOL,
        "heuristic_max_new_columns": ph.MAX_NEW_COLUMNS,
        "heuristic_n_seeds": ph.N_SEEDS,
        "heuristic_max_improve_rounds": ph.MAX_IMPROVE_ROUNDS,
    }


def main_exact(number_of_vehicles,
    capacity_of_vehicle,
    max_travel_distance,
    allowed_walking_distance,
    school_id,
    data_source= DataSource.REAL,
    time_limit: float | None = TIME_LIMIT) -> None| list[Route]:
    """time_limit: total solve time in seconds (default config.TIME_LIMIT,
    None = no limit). Data loading is not counted."""

    mip_model = False
    min_max_problem = False
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
        f",W={problem_model.allowed_walking_dist}]"
    )

    print(f"total number of stops: {len(problem_model.all_stops)}")

    if mip_model:
        method = "milp_minmax" if min_max_problem else "milp"
        logger = setup_logger(f"{method}_{model_info}")
        params = {"time_limit": time_limit}
        milp_time_limit = time_limit if time_limit is not None else NO_TIME_LIMIT

        with RunRecorder(method, problem_model, params, logger) as rec:
            if min_max_problem:
                result, routes, sp, var = minmax_problem(
                    problem_model, logger, time_limit=milp_time_limit
                )
            else:
                result, routes = main_problem(
                    problem_model, logger, time_limit=milp_time_limit
                )

            if result == ModelSuccess.SUCCESS and routes:
                print(
                    f"total route distance: {sum(r.total_distance for r in routes)}, total walking distance: {sum(r.total_walking_distance for r in routes)}"
                )
                rec.set_result(routes, "success")
                return routes
            print("Model did not find a successful solution.")
            rec.set_result([], result.name.lower())

    else:
        logger: logging.Logger = setup_logger(f"column_generation_{model_info}")

        logger.info(f"Model info: {model_info}")
        logger.info(
            f"Number of stops in the problem model: {len(problem_model.all_stops)}"
        )

        with RunRecorder(
            "column_generation", problem_model, _cg_params(time_limit), logger
        ) as rec:
            # one deadline for the whole solve, started together with the clock
            deadline = Deadline(time_limit, FINAL_MODEL_RESERVE)
            start_time = datetime.now()
            initial_route: Route = create_initial_route(
                problem_model.students, problem_model.distance_matrix, problem_model
            )
            initial_routes = [initial_route]
            logger.info(
                f"Initial routes: {[f'Route {i}: {[s.second_id for s in r.stops]}' for i, r in enumerate(initial_routes)]}"
            )

            outcome = main_column_generation(
                problem_model, initial_routes, logger, deadline=deadline
            )
            # ------------------------------
            # FINAL RMP SOLVE (LP)  Heuristic Solution
            logger.info("--- Final RMP Solve ---")
            final_routes = solve_final_model(
                outcome.routes, problem_model, logger,
                time_limit=deadline.final_time_limit(),
            )

            end_time = datetime.now()
            logger.info(f"Total time taken: {end_time - start_time}")

            if final_routes is not None:
                polished_routes = drop_duplicate_students(
                    final_routes, problem_model, logger
                )
                logger.info("Final routes:")
                for r, route in enumerate(polished_routes):
                    logger.info(
                        f"Route {r}: {str(route)}"
                    )
                logger.info(
                    f'total route distance: {sum(r.total_distance for r in polished_routes) if polished_routes else "N/A"}, total walking distance: {sum(r.total_walking_distance for r in polished_routes) if polished_routes else "N/A"}'
                )

                result_routes = polished_routes if polished_routes else final_routes
                total_walk = sum(r.total_walking_distance for r in result_routes)
                if outcome.proven_optimal:
                    status, lower_bound = "optimal", total_walk
                else:
                    status = "time_limit" if outcome.timed_out else "feasible"
                    lower_bound = outcome.lower_bound
                logger.info(f"Status: {status}, lower bound: {lower_bound}")
                rec.set_result(result_routes, status, lower_bound=lower_bound)
                return result_routes
            logger.warning("Final model infeasible: real columns cannot cover all students.")
            rec.set_result(
                [], "time_limit" if outcome.timed_out else "infeasible",
                lower_bound=outcome.lower_bound,
            )


if __name__ == "__main__":
    main_exact(2, 20, 20, 0.2, 42539)
    #print(f"{datetime.now()} - Finished run for max travel distance: {dis}")





# 18: 42539,25: 40755,10: 33337

#TODO
'''
run two thing: students pickup from their home addresses, 2. min route distance problem
Could you find a pareto frontier with one step for it to show?
run 10 instances for MILP, column generation

'''