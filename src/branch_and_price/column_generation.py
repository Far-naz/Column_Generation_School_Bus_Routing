from branch_and_price.models import (
    restricted_master_problem,
    pricing_problem,
)
from module.result_model import RMPResult
from module.sucess_result import ModelSuccess
from module.input_model import InputModel
from module.route import Route
import logging

from branch_and_price.pricing_heuristic import (
    add_single_route_to_master,
    generate_routes,
)
from branch_and_price.branch_and_bound import (
    keep_only_branch_feasible_new_routes,
    filter_routes_by_branch_rules,
    choose_branch_pair_from_fractional_solution,
)
from module.branch import BranchRule, BPNode
import copy
from dataclasses import dataclass


@dataclass
class ColumnGenerationResult:
    success: bool
    routes: list[Route]
    rmp: RMPResult | None
    result_mode: ModelSuccess
    integer_found: bool


class ColumnGenerationSolver:
    def __init__(
        self,
        problem_model: InputModel,
        logger: logging.Logger,
        branch_rules=None,
        max_iter: int = 200,
        is_heuristic: bool = True,
    ):
        self.problem_model = problem_model
        self.logger = logger
        self.branch_rules = branch_rules if branch_rules is not None else []
        self.max_iter = max_iter
        self.is_heuristic = is_heuristic

    def run(self, routes: list[Route]) -> ColumnGenerationResult:
        print(f"Starting column generation loop with {len(routes)} initial routes.")
        if len(routes) == 0:
            self.logger.info("No initial routes provided. Ending column generation.")
            return ColumnGenerationResult(
                success=False,
                routes=routes,
                rmp=None,
                result_mode=ModelSuccess.INFEASIBLE,
                integer_found=False,
            )

        routes = filter_routes_by_branch_rules(copy.deepcopy(routes), self.branch_rules)
        result_mode = ModelSuccess.SUCCESS
        last_rmp = None

        for it in range(self.max_iter):
            self.logger.info(f"--- Iteration {it + 1} ---")
            self.logger.info(
                f"Branch rules: {[(r.student_a, r.student_b, r.mode) for r in self.branch_rules]}"
            )

            rmp: RMPResult = restricted_master_problem(
                routes=copy.deepcopy(routes),
                problem_model=self.problem_model,
                logger=self.logger,
                branch_rules=self.branch_rules,
                return_full=True,
            )

            if not rmp.success:
                self.logger.info("RMP not optimal.")
                return ColumnGenerationResult(
                    success=False,
                    routes=routes,
                    rmp=rmp,
                    result_mode=ModelSuccess.INFEASIBLE,
                    integer_found=False,
                )

            last_rmp = rmp
            pi, mu = rmp.pi, rmp.mu

            if it > 0 and rmp.is_integer:
                int_lambda_count = sum(
                    1 for val in rmp.lambda_values if abs(val - 1.0) <= 1e-6
                )
                if int_lambda_count <= self.problem_model.number_of_vehicles:
                    self.logger.info("Integer solution found!")
                    return ColumnGenerationResult(
                        success=True,
                        routes=routes,
                        rmp=rmp,
                        result_mode=ModelSuccess.SUCCESS,
                        integer_found=True,
                    )

            if self.is_heuristic:
                routes_before = copy.deepcopy(routes)
                heuristic_mode = ModelSuccess.SUCCESS

                if it == 0:
                    before_count = len(routes)
                    routes = add_single_route_to_master(
                        routes, self.problem_model, pi, mu, self.logger
                    )
                    heuristic_mode = (
                        ModelSuccess.SUCCESS
                        if len(routes) > before_count
                        else ModelSuccess.NO_NEW_ROUTE
                    )
                else:
                    heuristic_mode, routes = generate_routes(
                        routes, self.problem_model, pi, mu, rmp.lambda_values, self.logger
                    )

                routes = keep_only_branch_feasible_new_routes(
                    routes_before, routes, self.branch_rules, self.logger
                )

                if heuristic_mode != ModelSuccess.SUCCESS:
                    self.logger.info(
                        "Heuristic pricing could not find a new route. Trying exact pricing fallback."
                    )

                    result_mode, exact_routes = pricing_problem(
                        pi=pi,
                        mu=mu,
                        problem_model=self.problem_model,
                        routes=routes,
                        logger=self.logger,
                        branch_rules=self.branch_rules,
                    )

                    if exact_routes is not None:
                        routes = keep_only_branch_feasible_new_routes(
                            routes_before, exact_routes, self.branch_rules, self.logger
                        )

                    if result_mode == ModelSuccess.SUCCESS:
                        self.logger.info(
                            "Exact pricing fallback found a route. Continuing with heuristic pricing."
                        )
                    else:
                        self.logger.info(
                            f"Exact pricing fallback did not find a route ({result_mode})."
                        )
                else:
                    result_mode = ModelSuccess.SUCCESS

            else:
                result_mode, candidate_routes = pricing_problem(
                    pi=pi,
                    mu=mu,
                    problem_model=self.problem_model,
                    routes=routes,
                    logger=self.logger,
                    branch_rules=self.branch_rules,
                )
                routes = candidate_routes if candidate_routes is not None else routes

            if result_mode != ModelSuccess.SUCCESS:
                if (
                    self.is_heuristic == False
                    and rmp.obj_value > self.problem_model.upper_bound
                    and len(rmp.lambda_values) > 0
                    and rmp.lambda_values[0] > 0
                ):
                    self.logger.warning(
                        f"This problem is probably infeasible. obj:{rmp.obj_value}, route_0:{rmp.lambda_values[0]}, upper_bound:{self.problem_model.upper_bound}"
                    )
                    return ColumnGenerationResult(
                        success=False,
                        routes=routes,
                        rmp=rmp,
                        result_mode=ModelSuccess.INFEASIBLE,
                        integer_found=False,
                    )
                self.logger.info(
                    f"Column generation stopped with result mode {result_mode}"
                )
                return ColumnGenerationResult(
                    success=True,
                    routes=routes,
                    rmp=rmp,
                    result_mode=result_mode,
                    integer_found=False,
                )

        self.logger.info(f"Reached maximum iterations: {self.max_iter}")
        return ColumnGenerationResult(
            success=last_rmp is not None and last_rmp.success,
            routes=routes,
            rmp=last_rmp,
            result_mode=result_mode,
            integer_found=last_rmp.is_integer if last_rmp else False,
        )


def column_generation_loop(
    problem_model: InputModel,
    routes: list[Route],
    logger: logging.Logger,
    branch_rules=None,
    max_iter=200,
    is_heuristic=True,
) -> ColumnGenerationResult:
    solver = ColumnGenerationSolver(
        problem_model=problem_model,
        logger=logger,
        branch_rules=branch_rules,
        max_iter=max_iter,
        is_heuristic=is_heuristic,
    )
    return solver.run(routes)


def branch_and_price_dfs(
    routes: list,
    problem_model,
    logger,
    preferred_pair=None,
    max_depth=20,
):
    best_routes = None
    best_obj = float("inf")
    next_node_id = 0

    def dfs(node: BPNode):
        nonlocal best_routes, best_obj, next_node_id

        logger.info(
            f"Entering node {node.node_id}, depth={node.depth}, "
            f"rules={[(r.student_a, r.student_b, r.mode) for r in node.branch_rules]}"
        )

        if node.depth > max_depth:
            logger.info(f"Max depth reached at node {node.node_id}")
            return False

        cg_result = column_generation_loop(
            problem_model=problem_model,
            routes=node.routes,
            logger=logger,
            branch_rules=node.branch_rules,
            max_iter=200,
            is_heuristic=False,
        )

        rmp = cg_result.rmp
        node_routes = cg_result.routes

        if not cg_result.success or rmp is None or not rmp.success:
            return False

        if rmp.obj_value >= best_obj - 1e-6:
            return False

        if cg_result.integer_found:
            best_obj = rmp.obj_value
            best_routes = copy.deepcopy(node_routes)
            return True

        a, b = choose_branch_pair_from_fractional_solution(
            rmp.routes,
            preferred_pair=preferred_pair,
        )

        left = BPNode(
            node_id=next_node_id + 1,
            depth=node.depth + 1,
            branch_rules=node.branch_rules + [BranchRule(a, b, "together")],
            routes=copy.deepcopy(node_routes),
        )
        print("left node created with rule: together", a, b)

        right = BPNode(
            node_id=next_node_id + 2,
            depth=node.depth + 1,
            branch_rules=node.branch_rules + [BranchRule(a, b, "separate")],
            routes=copy.deepcopy(node_routes),
        )

        next_node_id += 2

        return dfs(left) or dfs(right)

    root = BPNode(
        node_id=0,
        depth=0,
        branch_rules=[],
        routes=copy.deepcopy(routes),
    )

    success = dfs(root)

    if success and best_routes is not None:
        return ModelSuccess.SUCCESS, best_routes, True

    return ModelSuccess.INFEASIBLE, routes, False


def main_column_generation(
    problem_model, initial_routes: list[Route], logger
) -> list[Route]:
    routes = copy.deepcopy(initial_routes)

    cg_result = column_generation_loop(
        problem_model=problem_model,
        routes=routes,
        logger=logger,
        branch_rules=[],
        max_iter=500,
        is_heuristic=True,
    )

    if cg_result.integer_found:
        logger.info("Solved directly by heuristic column generation.")
        return cg_result.routes

    logger.info(
        "Heuristic column generation did not finish integrally. Starting branch-and-price."
    )

    dfs_result_mode, best_routes, dfs_success = branch_and_price_dfs(
        routes=cg_result.routes,
        problem_model=problem_model,
        logger=logger,
    )

    if dfs_success or dfs_result_mode == ModelSuccess.SUCCESS:
        logger.info("Branch-and-price successful.")
        return best_routes

    logger.info("Branch-and-price failed. Returning best known route pool.")
    return cg_result.routes
