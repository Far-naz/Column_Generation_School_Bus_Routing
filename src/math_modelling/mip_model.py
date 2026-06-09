from datetime import datetime

from module.input_model import InputModel
from module.sucess_result import ModelSuccess
from module.route import Route
import math

import logging
import gurobipy as gp
from gurobipy import GRB

from dataclasses import dataclass


@dataclass
class DecisionVar:
    x: dict
    x_hat: dict
    u: dict
    z: dict

    def __init__(self, x, x_hat, u, z) -> None:
        self.x = x
        self.x_hat = x_hat
        self.u = u
        self.z = z


def _build_route_solution(
    sp: gp.Model,
    input_model: InputModel,
    decision_var: DecisionVar,
    logger: logging.Logger,
) -> list[Route]:
    K = input_model.number_of_vehicles
    S = input_model.students
    N_H = input_model.all_stop_ids[:-1]
    W = input_model.walking_distance_list
    d = input_model.distance_matrix

    logger.info(f"Main problem objective : {sp.objVal}")
    final_route: list[Route] = []
    routes = {}
    for k in range(K):
        new_nodes = [0]
        current = 0
        while True:
            found = False
            for j in N_H:
                if (
                    j != current
                    and decision_var.x.get((current, j, k)) is not None
                    and decision_var.x[current, j, k].X > 0.5
                ):
                    next_node = j
                    found = True
                    break
            if not found or next_node == 0:
                break
            new_nodes.append(next_node)
            current = next_node
        new_nodes.append(input_model.last_depot.second_id)  # 0)
        routes[k] = new_nodes

    for k in range(K):
        pickup_stop_students = {}
        for i in N_H:
            if decision_var.z[i, k].X > 0.5 and i != 0:
                for s in S:
                    Cs = s.covering_stops
                    if any(c.second_id == i for c in Cs):
                        pickup_stop_students[s] = i
        covered_students = [
            s
            for s in S
            if any(decision_var.z[i.second_id, k].X > 0.5 for i in s.covering_stops)
        ]
        route_cost = sum(W[i] for i in N_H if decision_var.z[i, k].X > 0.5)
        total_distance = sum(
            d[i, j] * decision_var.x[i, j, k].X
            for i in N_H
            for j in N_H
            if i != j
            if decision_var.x[i, j, k].X > 0.5
        )

        logger.info(
            f"New route nodes:{routes[k]} covered_students: {[s.second_id for s in covered_students]}- total walking distance:{route_cost}- total distance:{total_distance}"
        )
        result_route = Route(
            stops=routes[k],
            served_students=[s.second_id for s in covered_students],
            total_distance=total_distance,
            total_walking_distance=route_cost,
        )

        final_route.append(result_route)

    return final_route


def _build_constraints(sp: gp.Model, dec_var: DecisionVar, problem_model: InputModel):
    K = problem_model.number_of_vehicles
    Q = problem_model.capacity_of_vehicle
    S = problem_model.students
    S_ids = problem_model.all_student_ids
    N_H = problem_model.all_stop_ids[:-1]

    sp.addConstrs(
        gp.quicksum(
            dec_var.z[i.second_id, k] for i in s.covering_stops for k in range(K)
        )
        == 1
        for s in S
    )

    sp.addConstr(gp.quicksum(dec_var.z[0, k] for k in range(K)) <= K)

    sp.addConstrs(
        gp.quicksum(dec_var.x[i, j, k] for j in N_H if j != i) == dec_var.z[i, k]
        for i in N_H
        for k in range(K)
    )

    for k in range(K):
        for i in N_H:
            if i == 0:
                continue
            sp.addConstr(
                gp.quicksum(dec_var.x[i, j, k] for j in N_H if j != i)
                == gp.quicksum(dec_var.x[j, i, k] for j in N_H if j != i)
            )

    sp.addConstrs(gp.quicksum(dec_var.z[i, k] for i in N_H) <= Q for k in range(K))

    sp.addConstrs(
        dec_var.x_hat[s1.second_id, s2.second_id, k]
        == gp.quicksum(
            dec_var.x[i.second_id, j.second_id, k]
            for i in s1.covering_stops
            for j in s2.covering_stops
            if i.second_id != j.second_id
        )
        for s1 in S
        for s2 in S
        if s1 != s2
        for k in range(K)
    )

    # Subtour elimination (MTZ)
    for k in range(K):
        for i in S_ids:
            for j in S_ids:
                if i != j:  # and i != 0 and j != 0:
                    sp.addConstr(
                        dec_var.u[i, k]
                        - dec_var.u[j, k]
                        + Q * dec_var.x_hat[i, j, k]
                        + (Q - 2) * dec_var.x_hat[j, i, k]
                        <= Q - 1
                    )
    sp.addConstrs(
        dec_var.u[i, k] >= dec_var.x_hat[i, 0, k] + (Q - 1) * dec_var.x_hat[0, i, k]
        for i in S_ids
        # if i != 0
        for k in range(K)
    )

    return sp


def _build_decision_variables(sp: gp.Model, problem_model: InputModel) -> DecisionVar:
    K = problem_model.number_of_vehicles
    Q = problem_model.capacity_of_vehicle
    S_ids = problem_model.all_student_ids
    N_H = problem_model.all_stop_ids[:-1]

    x = {}
    for k in range(K):
        for i in N_H:
            for j in N_H:
                if i != j:
                    x[i, j, k] = sp.addVar(vtype=GRB.BINARY, name=f"x_{i}_{j}_{k}")

    S_depot = [0] + S_ids
    x_hat = {}
    for s1 in S_depot:
        for s2 in S_depot:
            if s1 != s2:
                for k in range(K):
                    x_hat[s1, s2, k] = sp.addVar(
                        vtype=GRB.BINARY, name=f"x_hat_{s1}_{s2}_{k}"
                    )

    u = {}
    for s in S_ids:
        for k in range(K):
            u[s, k] = sp.addVar(vtype=GRB.CONTINUOUS, lb=0, ub=Q - 1, name=f"u_{s}_{k}")

    z = {}
    for i in N_H:
        for k in range(K):
            z[i, k] = sp.addVar(vtype=GRB.BINARY, name=f"z_{i}_{k}")

    return DecisionVar(x=x, x_hat=x_hat, u=u, z=z)


def main_problem(problem_model: InputModel, logger: logging.Logger):
    K = problem_model.number_of_vehicles
    max_route_distance = problem_model.max_travel_distance
    d = problem_model.distance_matrix
    N_H = problem_model.all_stop_ids[:-1]
    W = problem_model.walking_distance_list

    logger.info("min total walking distance.")
    logger.info(f"number of nodes: {len(N_H)}")

    sp = gp.Model("main_problem")

    decision_var: DecisionVar = _build_decision_variables(sp, problem_model)

    x = decision_var.x
    z = decision_var.z

    sp = _build_constraints(sp, decision_var, problem_model)

    sp.addConstrs(
        gp.quicksum(d[i, j] * x[i, j, k] for i in N_H for j in N_H if i != j)
        <= max_route_distance
        for k in range(K)
    )

    obj = gp.quicksum(W[i] * z[i, k] for i in N_H for k in range(K))
    sp.setObjective(obj, GRB.MINIMIZE)

    sp.params.TimeLimit = 1800
    sp.params.OutputFlag = 0

    start_time = datetime.now()

    sp.optimize()

    end_time = datetime.now()

    elapsed_time = end_time - start_time
    logger.info(f"Main problem solved in {elapsed_time.total_seconds():.2f} seconds")

    if sp.status == GRB.OPTIMAL:
        final_route = _build_route_solution(sp, problem_model, decision_var, logger)

        return ModelSuccess.SUCCESS, final_route
    elif sp.status == GRB.TIME_LIMIT:
        ub = sp.ObjVal if sp.SolCount > 0 else math.inf  # best feasible solution found
        lb = sp.ObjBound  # best proven lower bound
        gap = sp.MIPGap  # relative gap = (UB-LB)/|UB|
        logger.warning(f"Time limit hit. LB={lb:.4f}, UB={ub:.4f}, gap={gap:.2%}")

        if sp.SolCount > 0:
            final_route = _build_route_solution(sp, problem_model, decision_var, logger)
            return ModelSuccess.INFEASIBLE, final_route
        else:
            return ModelSuccess.INFEASIBLE, None
    else:
        logger.warning(f"Subproblem not optimal or infeasible; status: {sp.status}")
        return ModelSuccess.INFEASIBLE, None


def shotest_path(problem_model: InputModel, logger: logging.Logger):
    K = problem_model.number_of_vehicles
    d = problem_model.distance_matrix
    N_H = problem_model.all_stop_ids[:-1]

    logger.info("min the shortest path problem")
    logger.info(f"number of nodes: {len(N_H)}")

    sp = gp.Model("main_shortest_path_problem")

    decision_var: DecisionVar = _build_decision_variables(sp, problem_model)

    x = decision_var.x
    sp = _build_constraints(sp, decision_var, problem_model)

    obj = gp.quicksum(
        d[i, j] * x[i, j, k] for i in N_H for j in N_H if i != j for k in range(K)
    )
    sp.setObjective(obj, GRB.MINIMIZE)

    sp.params.TimeLimit = 1800
    sp.params.OutputFlag = 0

    start_time = datetime.now()

    sp.optimize()

    end_time = datetime.now()

    elapsed_time = end_time - start_time
    logger.info(f"Main problem solved in {elapsed_time.total_seconds():.2f} seconds")

    if sp.status == GRB.OPTIMAL:

        final_route = _build_route_solution(sp, problem_model, decision_var, logger)

        return ModelSuccess.SUCCESS, final_route
    else:
        logger.warning(f"Subproblem not optimal or infeasible; status: {sp.status}")
        return ModelSuccess.INFEASIBLE, None


def minmax_problem(problem_model: InputModel, logger: logging.Logger):
    K = problem_model.number_of_vehicles
    d = problem_model.distance_matrix
    N_H = problem_model.all_stop_ids[:-1]

    logger.info("the min max problem of route distance")
    logger.info(f"number of nodes: {len(N_H)}")

    sp = gp.Model("min_max_path_problem")

    decision_var: DecisionVar = _build_decision_variables(sp, problem_model)

    x = decision_var.x
    TMAX = sp.addVar(lb=0, vtype=GRB.CONTINUOUS)
    sp = _build_constraints(sp, decision_var, problem_model)

    # obj = gp.quicksum(
    #    d[i, j] * x[i, j, k] for i in N_H for j in N_H if i != j for k in range(K)
    # )

    for k in range(K):
        sp.addConstr(
            gp.quicksum(d[i, j] * x[i, j, k] for i in N_H for j in N_H if i != j)
            <= TMAX
        )

    sp.setObjective(TMAX, GRB.MINIMIZE)

    sp.params.TimeLimit = 1800
    sp.params.OutputFlag = 0

    start_time = datetime.now()
    #sp.write("model.lp")
    # sp.relax()
    sp.optimize()

    end_time = datetime.now()

    elapsed_time = end_time - start_time
    logger.info(f"Main problem solved in {elapsed_time.total_seconds():.2f} seconds")

    if sp.status == GRB.OPTIMAL:

        final_route = _build_route_solution(sp, problem_model, decision_var, logger)

        return ModelSuccess.SUCCESS, final_route
    else:
        logger.warning(f"Subproblem not optimal or infeasible; status: {sp.status}")
        return ModelSuccess.INFEASIBLE, None
