from dataclasses import dataclass
from typing import Optional
from enum import Enum


class STOP_TYPE(Enum):
    SCHOOL = 0
    STUDENT = 1
    BUSSTOP = 2

class Label:
    def __init__(self, route_dist, walk_dist, stop, parent=None, cost=0.0):
        self.route_dist = route_dist
        self.walk_dist = walk_dist
        self.stop = stop
        self.parent = parent  
        self.cost = cost

@dataclass
class Stop:
    id: int
    second_id: int
    lat: float
    lon: float
    stop_type: STOP_TYPE
    name: int

    def __init__(
        self, lat: float, lon: float, id: int, stop_type: STOP_TYPE, name: int, second_id: int = -1
    ):
        self.lat = lat
        self.lon = lon
        self.id = id
        self.second_id = second_id
        self.name = name
        self.stop_type = stop_type

    def __hash__(self) -> int:
        return hash(self.second_id)
    
    def __eq__(self, other):
        if not isinstance(other, Stop):
            return False
        return self.second_id == other.second_id
    

@dataclass
class Student(Stop):
    covering_stops: list[Stop]

    def __init__(
        self, lat: float, lon: float, id: int, name: int, second_id: int = -1
    ):
        super().__init__(lat, lon, id, STOP_TYPE.STUDENT, name=name, second_id=second_id)
        self.covering_stops = [self]

    def __hash__(self) -> int:
        return super().__hash__()