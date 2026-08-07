from enum import Enum

class ModelSuccess(Enum):
    SUCCESS = 1
    NO_NEGATIVE_ROUTE = 2
    INFEASIBLE = 3
    NO_NEW_ROUTE = 4
    NO_SOLUTION = 5
    TIME_LIMIT = 6