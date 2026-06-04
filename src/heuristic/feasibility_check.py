from module.route import Route
from module.input_model import InputModel

from enum import Enum
from dataclasses import dataclass


class FEASIBILITY(Enum):
    SUCCESS = 0
    CAPACITY = 1
    ROUTE_LENGTH = 2


@dataclass
class FeasibleResult:
    is_sucessful: bool
    error: FEASIBILITY


def is_feasible(routes: list[Route], input_model: InputModel) -> FeasibleResult:
    for route in routes:
        if len(route.served_students) > input_model.capacity_of_vehicle:
            return FeasibleResult(False, FEASIBILITY.CAPACITY)
        elif route.total_distance > input_model.max_travel_distance:
            return FeasibleResult(False, FEASIBILITY.ROUTE_LENGTH)

    return FeasibleResult(True, FEASIBILITY.SUCCESS)
