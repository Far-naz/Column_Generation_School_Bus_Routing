from __future__ import annotations

from typing import Optional, Tuple
import logging
from module.route import Route

from module.branch import BranchRule


def route_respects_branch_rules(route: Route, branch_rules: list[BranchRule]) -> bool:
    served = set(route.served_students)

    for rule in branch_rules:
        a, b = rule.student_a, rule.student_b
        has_a = a in served
        has_b = b in served

        if rule.mode == "together":
            pass
            #if not (has_a == has_b):
            #    return False

        elif rule.mode == "separate":
            if has_a and has_b:
                return False

        else:
            raise ValueError(f"Unknown branch mode: {rule.mode}")

    return True


def filter_routes_by_branch_rules(routes: list[Route], branch_rules: list[BranchRule]) -> list[Route]:
    return [r for r in routes if route_respects_branch_rules(r, branch_rules)]



def choose_branch_pair_from_fractional_solution(
    logger,
    routes: list[Route],
    preferred_pair: Optional[Tuple[int, int]] = None,
    
) -> Tuple[int, int] | None:
    if preferred_pair is not None:
        return preferred_pair

    pair_score = {}
    pair_count = {}

    for route_idx, route in enumerate(routes):
        # Skip dummy route
        if getattr(route, "is_dummy", False):
            continue

        lam = getattr(route, "lambda_value", 0.0)

        # Only fractional routes
        if 1e-6 < lam < 1.0 - 1e-6:
            students = list(route.served_students)

            for i in range(len(students)):
                for j in range(i + 1, len(students)):
                    pair = tuple(sorted((students[i], students[j])))
                    pair_score[pair] = pair_score.get(pair, 0.0) + lam
                    pair_count[pair] = pair_count.get(pair, 0) + 1

    if not pair_score:
        logger.info("No fractional pair found — all fractional routes are single-student. Pruning node.")
        return None
        #raise RuntimeError("No fractional pair found for branching.")

    # Prefer pairs that appear in more than one fractional route
    candidates = [p for p in pair_score if pair_count[p] >= 2]
    if not candidates:
        candidates = list(pair_score.keys())

    best_pair = min(candidates, key=lambda p: abs(pair_score[p] - 0.5))
    print(f"Chosen branching pair: {best_pair} with score {pair_score[best_pair]:.4f} (count: {pair_count[best_pair]})")
    return best_pair


# -------------------------------------------------------------------
# Route post-processing after pricing / heuristics
# -------------------------------------------------------------------
def _route_key(route: Route) -> tuple:
    return tuple(sorted(route.served_students))

def keep_only_branch_feasible_new_routes(
    old_routes,
    new_routes,
    branch_rules: list[BranchRule],
    logger: logging.Logger,
) -> list[Route]:
    """
    Keeps all old routes, but among newly generated routes only retains
    those satisfying current branch rules.
    """
    dummy_key = _route_key(old_routes[0]) 
    old_keys = set(_route_key(r) for r in old_routes)
    
    result = []
    removed = 0

    for r in new_routes:
        key = _route_key(r)
        if key == dummy_key or key in old_keys:
            result.append(r)
        else:
            if route_respects_branch_rules(r, branch_rules):
                result.append(r)
            else:
                removed += 1

    if removed > 0:
        logger.info(f"Removed {removed} generated routes violating branch rules.")

    return result


