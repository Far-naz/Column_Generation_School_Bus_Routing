from dataclasses import dataclass

from module.stop_point import Stop


@dataclass
class Route:
    stops: list[Stop]
    total_distance: float
    total_walking_distance: float
    served_students: set[int] | list[int]
    cost : float = 0.0
    lambda_value: float | None = None
    is_dummy: bool= False
    pickup_map: dict[int, int] | None = None

    def __init__(
        self,
        stops: list[Stop],
        total_distance: float,
        total_walking_distance: float,
        served_students: set[int] | list[int],
        cost: float = 0.0,
        is_dummy : bool = False,
        pickup_map: dict[int, int] | None = None,
    ):
        self.stops = stops
        self.total_distance = total_distance
        self.total_walking_distance = total_walking_distance
        self.served_students = served_students
        self.cost = cost
        self.is_dummy = is_dummy
        self.pickup_map = pickup_map if pickup_map is not None else {}

    def __copy__(self):
        return Route(
            stops=self.stops.copy(),
            total_distance=self.total_distance,
            total_walking_distance=self.total_walking_distance,
            served_students=self.served_students.copy() if isinstance(self.served_students, set) else set(self.served_students),
            cost=self.cost,
            pickup_map=self.pickup_map.copy() if self.pickup_map else {},
        )

    def __str__(self) -> str:
        string_result = f"walk_dis: {self.total_walking_distance},"
        string_result += f"route_dis: {self.total_distance},"
        string_result += f"stops: {[s.second_id for s in self.stops]}, "
        string_result += f"Served students: {self.served_students}"
            
        return string_result
    
    def __eq__(self, other):
        if not isinstance(other, Route):
            return False
        return [s.second_id for s in self.stops] == [s.second_id for s in other.stops]
    
    def __hash__(self):
        return hash(tuple(s.second_id for s in self.stops))