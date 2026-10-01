from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass, field

from branch_and_price.models import restricted_master_problem, pricing_problem
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
from module.input_model import InputModel
from helper import telemetry
from module.dual_history import DualHistory
from module.result_model import RMPResult
from module.route import Route
from module.sucess_result import ModelSuccess


EPS = 1e-9
INT_EPS = 1e-6
ROOT_MAX_ITER = 500
NODE_MAX_ITER = 200
BP_MAX_DEPTH = 20


@dataclass
class ColumnGenerationResult:
    success: bool
    routes: list[Route]
    rmp: RMPResult | None
    result_mode: ModelSuccess
    integer_found: bool
    dual_history: DualHistory = field(default_factory=DualHistory)


def _count_selected_integer_routes(
    routes: list[Route], lambda_values: list[float] | None
) -> int:
    """Count non-dummy routes whose master variable is essentially 1.0.

    The count must always be done against the exact route list used to solve
    the current master problem, otherwise lambda values can become misaligned
    after routes are filtered or extended.
    """
    if not routes or not lambda_values:
        return 0

    return sum(
        1
        for route, val in zip(routes, lambda_values)
        if abs(val - 1.0) <= INT_EPS and not getattr(route, "is_dummy", False)
    )

NO_IMPROVING_COLUMN = {ModelSuccess.NO_NEW_ROUTE, ModelSuccess.NO_NEGATIVE_ROUTE}


def _dummy_lambda_active(routes, lambda_values, tol=INT_EPS):
    """True if the dummy/artificial route still carries positive mass in
    the RMP solution — i.e. some student is only 'covered' by the
    artificial slack, not by any real route."""
    if not routes or not lambda_values:
        return False
    return any(
        getattr(route, "is_dummy", False) and val > tol
        for route, val in zip(routes, lambda_values)
    )


class ColumnGenerationSolver:
    def __init__(
        self,
        problem_model: InputModel,
        logger: logging.Logger,
        branch_rules=None,
        max_iter: int = 200,
        is_heuristic: bool = True,
        phase: str = "root",
        node_id: int = 0,
        depth: int = 0,
    ):
        self.problem_model = problem_model
        self.logger = logger
        self.branch_rules = branch_rules if branch_rules is not None else []
        self.max_iter = max_iter
        self.is_heuristic = is_heuristic
        self.dual_history = DualHistory()
        # identify where this CG run sits, for the telemetry trace
        self.phase = phase
        self.node_id = node_id
        self.depth = depth

    def _result(self, **kwargs) -> ColumnGenerationResult:
        return ColumnGenerationResult(**kwargs, dual_history=self.dual_history)

    def run(self, routes: list[Route]) -> ColumnGenerationResult:
        # A solver instance may be run more than once; each run gets its own trace.
        self.dual_history = DualHistory()
        self.logger.info("Starting column generation loop with %s initial routes.", len(routes))

        if len(routes) == 0:
            self.logger.info("No initial routes provided. Ending column generation.")
            return self._result(
                success=False, routes=routes, rmp=None,
                result_mode=ModelSuccess.INFEASIBLE, integer_found=False,
            )

        # The dummy route is exempt from branch rules, so filtering the whole
        # pool keeps it and keeps `routes` aligned with the RMP's route list.
        routes = filter_routes_by_branch_rules(routes, self.branch_rules)

        tel = telemetry.current()
        tel.register_columns(routes, 0, self.phase, self.node_id, "initial")

        result_mode = ModelSuccess.SUCCESS
        last_rmp = None

        for it in range(self.max_iter):
            self.logger.info("--- Iteration %s ---", it + 1)
            self.logger.info(
                "Branch rules: %s",
                [(r.student_a, r.student_b, r.mode) for r in self.branch_rules],
            )

            master_routes = copy.deepcopy(routes)
            t_rmp = time.perf_counter()
            rmp: RMPResult = restricted_master_problem(
                routes=master_routes, problem_model=self.problem_model,
                logger=self.logger, branch_rules=self.branch_rules, return_full=True,
            )
            rmp_time = time.perf_counter() - t_rmp

            if not rmp.success:
                self.logger.info("RMP not optimal.")
                return self._result(
                    success=False, routes=routes, rmp=rmp,
                    result_mode=ModelSuccess.INFEASIBLE, integer_found=False,
                )

            last_rmp = rmp
            pi, mu = rmp.pi, rmp.mu
            self.dual_history.record(
                iteration=it + 1,
                pi=pi,
                mu=mu,
                objective=rmp.obj_value,
            )
            tel.observe_lambdas(rmp.routes, rmp.lambda_values)
            wall, cpu = tel.clock()
            # One trace row per iteration; filled in below and stored in the
            # `finally`, so iterations that end in an early return are kept.
            row = {
                "phase": self.phase, "node_id": self.node_id, "depth": self.depth,
                "iteration": it + 1, "wall_s": wall, "cpu_s": cpu,
                "rmp_obj": rmp.obj_value, "rmp_time": rmp_time,
                "n_columns": len(rmp.routes),
                "n_fractional": sum(
                    1 for v in rmp.lambda_values if INT_EPS < v < 1.0 - INT_EPS
                ),
                "is_integer": rmp.is_integer,
                "dummy_lambda": sum(
                    v for r, v in zip(rmp.routes, rmp.lambda_values)
                    if getattr(r, "is_dummy", False)
                ),
                "mu": mu, "pi": pi if tel.store_duals else None,
                "pricing_level": None, "heuristic_time": None,
                "heuristic_success": None, "best_rc_heuristic": None,
                "exact_time": None, "exact_status": None, "best_rc_exact": None,
                "n_added": 0, "certified": False, "lagrangian_lb": None,
            }
            try:
                routes_before = copy.deepcopy(routes)
                column_added = False

                # True only when EXACT pricing itself reports NO_NEGATIVE_ROUTE —
                # i.e. a genuine certificate that no improving column exists.
                # A heuristic failure, or a branch-filter rejection of an exact
                # column, does NOT count as a certificate.
                certified_no_column = False

                if all(abs(v) <= EPS for v in pi.values()) and abs(mu) <= EPS:
                    self.logger.warning(
                        "All duals and mu are ~0. The master is degenerate; pricing is still required."
                    )

                if self.is_heuristic:
                    # ---- Step 1: heuristic pricing ----
                    row["pricing_level"] = "heuristic"
                    t_h = time.perf_counter()
                    if it == 0:
                        before_count = len(routes)
                        routes = add_single_route_to_master(
                            routes, self.problem_model, pi, mu, self.logger
                        )
                        heuristic_mode = (
                            ModelSuccess.SUCCESS if len(routes) > before_count
                            else ModelSuccess.NO_NEW_ROUTE
                        )
                    else:
                        heuristic_mode, routes = generate_routes(
                            routes, self.problem_model, pi, mu, rmp.lambda_values, self.logger,
                        )

                    if self.branch_rules:
                        routes = keep_only_branch_feasible_new_routes(
                            routes_before, routes, self.branch_rules, self.logger
                        )
                    row["heuristic_time"] = time.perf_counter() - t_h
                    new_h = routes[len(routes_before):]
                    row["heuristic_success"] = (
                        heuristic_mode == ModelSuccess.SUCCESS and bool(new_h)
                    )
                    if new_h:
                        row["best_rc_heuristic"] = min(r.cost for r in new_h)

                    if heuristic_mode == ModelSuccess.SUCCESS and len(routes) > len(routes_before):
                        result_mode = ModelSuccess.SUCCESS
                        column_added = True
                    else:
                        # ---- Step 2: heuristic found nothing usable -> exact fallback ----
                        self.logger.info(
                            "Heuristic pricing found no usable route. Falling back to exact pricing."
                        )
                        routes = routes_before

                        row["pricing_level"] = "heuristic+exact"
                        t_e = time.perf_counter()
                        result_mode, exact_routes = pricing_problem(
                            pi=pi, mu=mu, problem_model=self.problem_model,
                            routes=copy.deepcopy(master_routes), logger=self.logger,
                            branch_rules=self.branch_rules,
                        )
                        row["exact_time"] = time.perf_counter() - t_e
                        row["exact_status"] = result_mode.name
                        if result_mode == ModelSuccess.SUCCESS and exact_routes:
                            row["best_rc_exact"] = exact_routes[-1].cost

                        if result_mode == ModelSuccess.SUCCESS and exact_routes is not None:
                            candidate_routes = (
                                keep_only_branch_feasible_new_routes(
                                    routes_before, exact_routes, self.branch_rules, self.logger
                                )
                                if self.branch_rules else exact_routes
                            )
                            if len(candidate_routes) > len(routes_before):
                                routes = candidate_routes
                                column_added = True
                            else:
                                # Branch filter rejected the exact column — treat as
                                # "no usable column" but NOT as a certificate.
                                result_mode = ModelSuccess.NO_NEW_ROUTE
                                routes = routes_before

                        elif result_mode == ModelSuccess.TIME_LIMIT:
                            self.logger.warning("Exact pricing hit time limit. Cannot certify optimality.")
                            return self._result(
                                success=True, routes=routes_before, rmp=rmp,
                                result_mode=ModelSuccess.TIME_LIMIT, integer_found=False,
                            )

                        elif result_mode == ModelSuccess.INFEASIBLE:
                            self.logger.error("Exact pricing subproblem failed to solve (status error).")
                            return self._result(
                                success=False, routes=routes_before, rmp=rmp,
                                result_mode=ModelSuccess.INFEASIBLE, integer_found=False,
                            )

                        else:
                            # NO_NEGATIVE_ROUTE — a genuine certificate.
                            certified_no_column = True
                            routes = routes_before

                else:
                    # ---- Exact pricing only (branch-and-price nodes) ----
                    row["pricing_level"] = "exact"
                    t_e = time.perf_counter()
                    result_mode, candidate_routes = pricing_problem(
                        pi=pi, mu=mu, problem_model=self.problem_model,
                        routes=copy.deepcopy(master_routes), logger=self.logger,
                        branch_rules=self.branch_rules,
                    )
                    row["exact_time"] = time.perf_counter() - t_e
                    row["exact_status"] = result_mode.name
                    if result_mode == ModelSuccess.SUCCESS and candidate_routes:
                        row["best_rc_exact"] = candidate_routes[-1].cost

                    if result_mode == ModelSuccess.SUCCESS and candidate_routes is not None:
                        if len(candidate_routes) > len(routes_before):
                            routes = candidate_routes
                            column_added = True
                        else:
                            result_mode = ModelSuccess.NO_NEW_ROUTE

                    elif result_mode == ModelSuccess.TIME_LIMIT:
                        self.logger.warning("Exact pricing hit time limit. Cannot certify optimality.")
                        return self._result(
                            success=True, routes=routes_before, rmp=rmp,
                            result_mode=ModelSuccess.TIME_LIMIT, integer_found=False,
                        )

                    elif result_mode == ModelSuccess.INFEASIBLE:
                        self.logger.error("Exact pricing subproblem failed to solve (status error).")
                        return self._result(
                            success=False, routes=routes_before, rmp=rmp,
                            result_mode=ModelSuccess.INFEASIBLE, integer_found=False,
                        )

                    else:
                        certified_no_column = True

                if column_added:
                    new_cols = routes[len(routes_before):]
                    row["n_added"] = len(new_cols)
                    tel.register_columns(
                        new_cols, it + 1, self.phase, self.node_id,
                        "exact" if row["exact_status"] else "heuristic",
                    )
                if certified_no_column:
                    # No column with negative reduced cost exists, so the RMP
                    # objective is a valid lower bound for this node.
                    row["certified"] = True
                    row["lagrangian_lb"] = rmp.obj_value

                # ---- Single, unified termination check ----
                if result_mode in NO_IMPROVING_COLUMN:
                    if certified_no_column and _dummy_lambda_active(rmp.routes, rmp.lambda_values):
                        self.logger.warning(
                            "Exact pricing certifies no improving column exists, but the "
                            "dummy route is still active (obj=%s) — this node is infeasible.",
                            rmp.obj_value,
                        )
                        return self._result(
                            success=False, routes=routes, rmp=rmp,
                            result_mode=ModelSuccess.INFEASIBLE, integer_found=False,
                        )

                    int_lambda_count = _count_selected_integer_routes(rmp.routes, rmp.lambda_values)
                    if rmp.is_integer and int_lambda_count <= self.problem_model.number_of_vehicles:
                        self.logger.info("Optimal integer solution found after pricing convergence.")
                        return self._result(
                            success=True, routes=routes, rmp=rmp,
                            result_mode=ModelSuccess.SUCCESS, integer_found=True,
                        )

                    self.logger.info("Column generation converged but solution is fractional.")
                    return self._result(
                        success=True, routes=routes, rmp=rmp,
                        result_mode=ModelSuccess.NO_NEW_ROUTE, integer_found=False,
                    )

            finally:
                tel.log_iteration(row)

            # Otherwise a column was added — loop continues, re-solving the RMP.

        self.logger.info("Reached maximum iterations: %s", self.max_iter)
        return self._result(
            success=last_rmp is not None and last_rmp.success,
            routes=routes, rmp=last_rmp, result_mode=result_mode,
            integer_found=last_rmp.is_integer if last_rmp else False,
        )

def column_generation_loop(
    problem_model: InputModel,
    routes: list[Route],
    logger: logging.Logger,
    branch_rules=None,
    max_iter=200,
    is_heuristic=True,
    phase: str = "root",
    node_id: int = 0,
    depth: int = 0,
) -> ColumnGenerationResult:
    solver = ColumnGenerationSolver(
        problem_model=problem_model,
        logger=logger,
        branch_rules=branch_rules,
        max_iter=max_iter,
        is_heuristic=is_heuristic,
        phase=phase,
        node_id=node_id,
        depth=depth,
    )
    return solver.run(routes)


def branch_and_price_dfs(
    routes: list,
    problem_model,
    logger,
    preferred_pair=None,
    max_depth=BP_MAX_DEPTH,
    initial_upper_bound=float("inf"),
):
    best_routes = None
    best_obj = initial_upper_bound
    next_node_id = 0

    def dfs(node: BPNode):
        nonlocal best_routes, best_obj, next_node_id

        logger.info(
            "Entering node %s, depth=%s, rules=%s",
            node.node_id,
            node.depth,
            [(r.student_a, r.student_b, r.mode) for r in node.branch_rules],
        )

        if node.depth > max_depth:
            logger.info("Max depth reached at node %s", node.node_id)
            return False

        cg_result = column_generation_loop(
            problem_model=problem_model,
            routes=node.routes,
            logger=logger,
            branch_rules=node.branch_rules,
            max_iter=NODE_MAX_ITER,
            is_heuristic=False,
            phase="branch_and_price",
            node_id=node.node_id,
            depth=node.depth,
        )

        rmp = cg_result.rmp
        node_routes = cg_result.routes

        if not cg_result.success or rmp is None or not rmp.success:
            return False

        # Prune only against a valid incumbent integer solution.
        if best_routes is not None and rmp.obj_value >= best_obj - 1e-6:
            return False

        if cg_result.integer_found:
            best_obj = rmp.obj_value
            best_routes = copy.deepcopy(node_routes)
            return True

        branch_pair = choose_branch_pair_from_fractional_solution(
            logger,
            rmp.routes,
            preferred_pair=preferred_pair,
        )
        if branch_pair is None:
            return False

        a, b = branch_pair

        left_id = next_node_id + 1
        right_id = next_node_id + 2
        next_node_id += 2

        left = BPNode(
            node_id=left_id,
            depth=node.depth + 1,
            branch_rules=node.branch_rules + [BranchRule(a, b, "together")],
            routes=copy.deepcopy(node_routes),
        )

        right = BPNode(
            node_id=right_id,
            depth=node.depth + 1,
            branch_rules=node.branch_rules + [BranchRule(a, b, "separate")],
            routes=copy.deepcopy(node_routes),
        )

        found_left = dfs(left)
        found_right = dfs(right)
        return found_left or found_right

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


def main_column_generation(problem_model, initial_routes: list[Route], logger) -> list[Route]:
    routes = copy.deepcopy(initial_routes)

    cg_result = column_generation_loop(
        problem_model=problem_model,
        routes=routes,
        logger=logger,
        branch_rules=[],
        max_iter=ROOT_MAX_ITER,
        is_heuristic=True,
    )

    if cg_result.integer_found:
        logger.info("Solved directly by heuristic column generation.")
        return cg_result.routes

    logger.info(
        "Heuristic column generation did not finish integrally. Starting branch-and-price."
    )

    # Do not use an LP relaxation value as an incumbent upper bound.
    initial_ub = float("inf")

    dfs_result_mode, best_routes, dfs_success = branch_and_price_dfs(
        routes=cg_result.routes,
        problem_model=problem_model,
        logger=logger,
        initial_upper_bound=initial_ub,
    )

    if dfs_success or dfs_result_mode == ModelSuccess.SUCCESS:
        logger.info("Branch-and-price successful.")
        return best_routes

    logger.info("Branch-and-price failed. Returning best known route pool.")
    return cg_result.routes
