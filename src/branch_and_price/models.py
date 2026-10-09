import gurobipy as gp
from gurobipy import GRB
import module.sucess_result as mr
import logging
from module.input_model import InputModel
from module.route import Route
import math
from branch_and_price.branch_and_bound import filter_routes_by_branch_rules
from typing import Optional
from module.result_model import RMPResult
from module.branch import BranchRule
from config import PRICING_TIME_LIMIT

_PRICING_MODEL_CACHE = {}
PRICING_RC_TOL = 1e-6


def check_new_route_is_duplicate(
    nodes,
    existing_routes: list[Route],
) -> bool:
    """Check if the new route is a duplicate of any existing route."""
    new_route_stops = nodes
    for route in existing_routes:
        # todo how list is comparing.
        existing_route_stops = [stop.second_id for stop in route.stops]
        if new_route_stops == existing_route_stops or new_route_stops == list(
            reversed(existing_route_stops)
        ):
            return True
    return False


def restricted_master_problem(
    routes,
    problem_model: InputModel,
    logger: logging.Logger,
    branch_rules: Optional[list[BranchRule]] = None,
    return_full: bool = True,
) -> RMPResult:
    """
    Branch-aware RMP.

    Notes:
    - Keeps your original signature style.
    - Adds:
        branch_rules
        return_full
    - By default returns only (pi, mu), so your existing code remains compatible.
    """
    #print("RMP is started.")
    if branch_rules is None:
        branch_rules = []

    S, K = problem_model.all_student_ids, problem_model.number_of_vehicles

    feasible_routes = filter_routes_by_branch_rules(routes, branch_rules)

    if len(feasible_routes) == 0:
        logger.info("No feasible routes remain under current branch rules.")
        if return_full:
            return RMPResult(
                success=False,
                pi={},
                mu=0.0,
                obj_value=math.inf,
                routes=[],
                lambda_values=[],
                is_integer=False,
            )
        # return None, None

    m = gp.Model()

    lambda_vars = [
        m.addVar(vtype=GRB.CONTINUOUS, lb=0.0, name=f"lambda_{r}")
        for r in range(len(feasible_routes))
    ]

    # Objective
    m.setObjective(
        gp.quicksum(
            lambda_vars[r] * route.total_walking_distance
            for r, route in enumerate(feasible_routes)
        ),
        GRB.MINIMIZE,
    )

    # Coverage constraints
    # Your code used >= 1, so I keep that.
    covers = m.addConstrs(
        (
            gp.quicksum(
                lambda_vars[r]
                for r, route in enumerate(feasible_routes)
                if s in route.served_students
            )
            >= 1
            for s in S
        ),
        name="cover",
    )

    # Vehicle limit
    vehicle_limit = m.addConstr(
        gp.quicksum(lambda_vars[r] for r in range(len(feasible_routes))) <= K,
        name="vehicle_limit",
    )

    m.Params.OutputFlag = 0
    m.optimize()

    if m.status != GRB.OPTIMAL:
        logger.info("RMP not optimal. Stopping.")
        return RMPResult(
            success=False,
            pi={},
            mu=0.0,
            obj_value=math.inf,
            routes=[],
            lambda_values=[],
            is_integer=False,
        )

    lambda_values = [lambda_vars[r].X for r in range(len(feasible_routes))]

    for r, route in enumerate(feasible_routes):
        logger.info(f"Lambda for Route {r}: {lambda_values[r]} -> {str(route)}")
        route.lambda_value = lambda_values[r]

    # Routes filtered out by branching should not look active
    feasible_ids = {id(r) for r in feasible_routes}
    filtered_out = [r for r in routes if id(r) not in feasible_ids]
    for route in filtered_out:
        route.lambda_value = 0.0

    pi = {s: covers[s].Pi for s in S}
    mu = vehicle_limit.Pi

    logger.info(f"Duals: {pi}, {mu}, obj: {m.ObjVal}")

    is_integer = all(abs(v - round(v)) <= 1e-6 for v in lambda_values)

    return RMPResult(
        success=True,
        pi=pi,
        mu=mu,
        obj_value=m.ObjVal,
        routes=feasible_routes,
        lambda_values=lambda_values,
        is_integer=is_integer,
    )


def pricing_problem(
    pi: dict,
    mu: float,
    problem_model: InputModel,
    routes: list[Route],
    logger: logging.Logger,
    branch_rules: Optional[list[BranchRule]] = None,
    time_limit: Optional[float] = None,
):
    """
    Solve or update the pricing problem.

    time_limit: seconds for this call; defaults to config.PRICING_TIME_LIMIT.

    If is_initial=True: build the Gurobi model from scratch.
    Otherwise: only update objective coefficients (pi, mu, W).

    branch_rules:
        list of BranchRule(student_a, student_b, mode)
        mode in {"together", "none"}
    """
    print("exact procing is started.")
    if branch_rules is None:
        branch_rules = []

    branch_signature = tuple(
        (rule.student_a, rule.student_b, rule.mode) for rule in branch_rules
    )
    cache_key = (id(problem_model), branch_signature)
    cached_model = None  # _PRICING_MODEL_CACHE.get(cache_key)

    N_H = problem_model.all_stop_ids[:-1]
    S = problem_model.students
    S_ids = problem_model.all_student_ids
    W = problem_model.walking_distance_list
    d = problem_model.distance_matrix
    Q = problem_model.capacity_of_vehicle
    max_route_distance = problem_model.max_travel_distance

    first_depot_index = problem_model.school.second_id
    last_depot_index = problem_model.last_depot.second_id

    if cached_model is None:
        sp = gp.Model("pricing")
        sp.params.TimeLimit = PRICING_TIME_LIMIT if time_limit is None else time_limit

        x = {}
        for i in N_H:
            for j in N_H:
                if i != j:
                    x[i, j] = sp.addVar(vtype=GRB.BINARY, name=f"x_{i}_{j}")

        S_depot = [0] + S_ids
        x_hat = sp.addVars(S_depot, S_depot, vtype=GRB.BINARY, name="x_hat")

        u = {
            s: sp.addVar(vtype=GRB.CONTINUOUS, lb=0, ub=Q, name=f"u_{s}")
            for s in S_ids
        }
        z = {i: sp.addVar(vtype=GRB.BINARY, name=f"z_{i}") for i in N_H}
        y = {s: sp.addVar(vtype=GRB.BINARY, name=f"y_{s}") for s in S_ids}

        sp.update()

        for i in N_H:
            if i == first_depot_index or i == last_depot_index:
                continue
            sp.addConstr(
                gp.quicksum(x[i, j] for j in N_H if j != i)
                == gp.quicksum(x[j, i] for j in N_H if j != i)
            )

        sp.addConstrs(
            x_hat[s1.second_id, s2.second_id]
            == gp.quicksum(
                x[i.second_id, j.second_id]
                for i in s1.covering_stops
                for j in s2.covering_stops
                if i.second_id != j.second_id
            )
            for s1 in S
            for s2 in S
            if s1 != s2
        )

        sp.addConstr(
            gp.quicksum(x[first_depot_index, j] for j in N_H if j != first_depot_index)
            == 1
        )
        #sp.addConstr(
        #    gp.quicksum(x[j, first_depot_index] for j in N_H if j != first_depot_index)
        #    == 0
        #)
        sp.addConstr(
            gp.quicksum(x[j, first_depot_index] for j in N_H if j != first_depot_index)
            == 1
        )
        #sp.addConstr(
        #    gp.quicksum(x[last_depot_index, j] for j in N_H if j != last_depot_index)
        #    == 0
        #)

        sp.addConstrs(gp.quicksum(x[i, j] for j in N_H if j != i) == z[i] for i in N_H)

        for s in S:
            Cs = s.covering_stops
            sp.addConstr(
                y[s.second_id]
                == gp.quicksum(z[i.second_id] for i in Cs if i.second_id is not None)
            )

        sp.addConstr(
            gp.quicksum(
                x[first_depot_index, j]
                for j in N_H
                if j not in (first_depot_index, last_depot_index)
            )
            == 1
        )
        sp.addConstr(
            gp.quicksum(
                x[j, first_depot_index]
                for j in N_H
                if j not in (first_depot_index, last_depot_index)
            )
            == 1
        )

        sp.addConstr(gp.quicksum(y[s] for s in S_ids) <= Q)
        sp.addConstr(
            gp.quicksum(d[i, j] * x[i, j] for i in N_H for j in N_H if i != j) <= max_route_distance
        )

        sp.addConstrs(
            u[i] - u[j] + Q * x_hat[i, j] + (Q - 2) * x_hat[j, i] <= Q - 1
            for i in S_ids
            for j in S_ids
            if i != j
        )

        sp.addConstrs(
            u[i] >= x_hat[i, first_depot_index] + (Q - 1) * x_hat[first_depot_index, i]
            for i in S_ids
            if i != first_depot_index
        )

        for idx, rule in enumerate(branch_rules):
            a, b = rule.student_a, rule.student_b

            if a not in y or b not in y:
                raise ValueError(
                    f"Branch rule uses students not in pricing vars: {(a, b)}"
                )

            if rule.mode == "together":
                sp.addConstr(y[a] == y[b], name=f"branch_together_{a}_{b}_{idx}")
            elif rule.mode == "separate":
                sp.addConstr(y[a] + y[b] <= 1, name=f"branch_separate_{a}_{b}_{idx}")
            else:
                raise ValueError(f"Unknown branch rule mode: {rule.mode}")

        obj = (
            gp.quicksum(W[i] * z[i] for i in N_H if i != first_depot_index)
            - gp.quicksum(pi[s] * y[s] for s in S_ids)
            - mu
        )
        sp.setObjective(obj, GRB.MINIMIZE)
        sp.params.OutputFlag = 0
        sp.update()

        _PRICING_MODEL_CACHE[cache_key] = {
            "model": sp,
            "x": x,
            "z": z,
            "y": y,
        }
    else:
        sp = cached_model["model"]
        x = cached_model["x"]
        z = cached_model["z"]
        y = cached_model["y"]

        for i in N_H:
            z[i].Obj = W[i]
        for s in S_ids:
            y[s].Obj = -pi[s]
        sp.ObjCon = -mu
        sp.update()

    # ---- Solve ----
    # Column generation only needs to know whether ANY route has negative
    # reduced cost, not the most negative one. Cutoff prunes everything that
    # is not improving (so "no improving route" is proven quickly as
    # CUTOFF/INFEASIBLE), and BestObjStop ends the search at the first
    # improving route found.
    sp.params.Cutoff = -PRICING_RC_TOL
    sp.params.BestObjStop = -PRICING_RC_TOL
    sp.optimize()

    if sp.status in (GRB.CUTOFF, GRB.INFEASIBLE, GRB.INF_OR_UNBD):
        # No route beats the cutoff: a genuine certificate for exact pricing.
        logger.info("No negative reduced-cost route found (cutoff / infeasible).")
        return mr.ModelSuccess.NO_NEGATIVE_ROUTE, routes

    if (
        sp.status in (GRB.OPTIMAL, GRB.USER_OBJ_LIMIT)
        or (sp.status == GRB.TIME_LIMIT and sp.SolCount > 0)
    ):
        if sp.status == GRB.TIME_LIMIT:
            logger.warning(
                f"Pricing subproblem hit time limit but found incumbent: obj={sp.objVal:.6f}"
            )
        obj_calculated = (
            sum(W[i] for i in N_H if z[i].X > 0.5)
            - sum(pi[s] for s in S_ids if y[s].X > 0.5)
            - mu
        )

        # TODO, why is it so different in very small number of z and y
        logger.info(
            f"Subproblem objective (reduced cost): {sp.objVal}, manual calculation of Obj:{obj_calculated}"
        )
        print(f'Exact price is finished by obj:{obj_calculated}')

        if obj_calculated < -1e-3:

            first = first_depot_index
            last = last_depot_index

            new_nodes = [first]
            current = first
            visited = {first}

            while True:
                next_nodes = [
                    j for j in N_H if (current, j) in x and x[current, j].X > 0.5
                ]

                if len(next_nodes) != 1:
                    logger.warning(
                        f"Invalid route structure at node {current}: {next_nodes}"
                    )
                    break

                next_node = next_nodes[0]

                if next_node == first:
                    break

                if next_node in visited:
                    logger.warning("Cycle detected in route extraction")
                    break

                new_nodes.append(next_node)
                visited.add(next_node)
                current = next_node

            # final validation
            #if new_nodes[-1] != first:
            #    logger.warning("Extracted path does not end at last depot")
            #    return mr.ModelSuccess.NO_NEGATIVE_ROUTE, routes

            new_nodes.append(last)

            #is_duplicate = check_new_route_is_duplicate(new_nodes, routes)
            #if is_duplicate:
            #    logger.info("New route is a duplicate. Skipping.")
            #    return mr.ModelSuccess.NO_NEW_ROUTE, routes

            pickup_stops_students = {}
            for i in N_H:
                if z[i].X > 0.5 and i != 0:
                    for s in S:
                        Cs = s.covering_stops
                        if any(c.second_id == i for c in Cs):
                            pickup_stops_students[s] = i

            covered_students = [s for s in S_ids if y[s].X > 0.5]
            route_cost = sum(W[i] for i in N_H if z[i].X > 0.5)
            total_distance = sum(d[i, j] * x[i, j].X for (i, j) in x)

            logger.info(
                f"New route nodes:{new_nodes} "
                f"covered_students:{covered_students} "
                f"students pick up point:{[f'{s.second_id} -> {pickup_stops_students[s]}' for s in pickup_stops_students]} "
                f"total walking distance:{route_cost} "
                f"total distance:{total_distance}"
            )

            routes.append(
                Route(
                    stops=[problem_model.get_stop(i) for i in new_nodes],
                    served_students=set(covered_students),
                    total_walking_distance=route_cost,
                    total_distance=total_distance,
                )
            )

            return mr.ModelSuccess.SUCCESS, routes
        
        elif sp.status == GRB.TIME_LIMIT:
            # Incumbent is not improving, but optimality was not proven.
            logger.warning("Pricing subproblem hit time limit; cannot certify.")
            return mr.ModelSuccess.TIME_LIMIT, None

        else:
            logger.info("No negative reduced-cost route found.")
            return mr.ModelSuccess.NO_NEGATIVE_ROUTE, routes

    elif sp.status == GRB.TIME_LIMIT:
        # Hit limit with no feasible solution found at all
        logger.warning("Pricing subproblem hit time limit with no incumbent.")
        return mr.ModelSuccess.TIME_LIMIT, None

    else:
        logger.warning(f"Subproblem not optimal or infeasible; status: {sp.status}")
        return mr.ModelSuccess.INFEASIBLE, None


def solve_final_model(
    routes: list[Route], problem_model: InputModel, logger: logging.Logger,
    time_limit: Optional[float] = None,
):
    S, K = problem_model.students, problem_model.number_of_vehicles
    S_ids = problem_model.all_student_ids
    # The dummy route is only a feasibility slack for the RMP; it must never
    # appear in a real solution. Without it, the model is infeasible when the
    # real columns cannot cover all students with K vehicles.
    routes = [r for r in routes if not getattr(r, "is_dummy", False)]
    m = gp.Model()
    lambda_vars = [
        m.addVar(vtype=GRB.BINARY, name=f"lambda_{r}") for r in range(len(routes))
    ]
    # Objective
    m.setObjective(
        gp.quicksum(
            lambda_vars[r] * route.total_walking_distance
            for r, route in enumerate(routes)
        ),
        GRB.MINIMIZE,
    )
    # Each student covered exactly once
    m.addConstrs(
        (
            gp.quicksum(
                lambda_vars[r] if s in route.served_students else 0
                for r, route in enumerate(routes)
            )
            >= 1
            for s in S_ids
        )
    )
    # Vehicle limit
    m.addConstr(gp.quicksum(lambda_vars[r] for r, _ in enumerate(routes)) <= K)
    m.params.OutputFlag = 0
    if time_limit is not None:
        m.params.TimeLimit = time_limit
    m.optimize()
    if m.status == GRB.OPTIMAL or (m.status == GRB.TIME_LIMIT and m.SolCount > 0):
        final_routes: list[Route] = []
        if m.status == GRB.TIME_LIMIT:
            logger.warning(
                f"Final model hit its time limit; best found {m.ObjVal}, bound {m.ObjBound}"
            )
        logger.info(f"Optimal objective: {m.ObjVal}")
        logger.info("Route usage:")
        for r, route in enumerate(routes):
            if lambda_vars[r].X > 1e-6:
                pickup_points = {}
                for stop in route.stops:
                    for s in S:
                        Cs = s.covering_stops
                        if any(c.second_id == stop.second_id for c in Cs):
                            pickup_points[s.second_id] = stop.second_id

                logger.info(
                    f"Route: {[stop.second_id for stop in route.stops]}, total walking time: {route.total_walking_distance}, total distance: {route.total_distance},  students: {route.served_students}, pickup point: {pickup_points}"
                )
                final_routes.append(route)
        return final_routes

    else:
        logger.warning("Final RMP not optimal.")
