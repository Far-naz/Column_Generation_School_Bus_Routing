from __future__ import annotations
from typing import Optional
from module.stop_point import Stop

class Label:
    stop: Stop
    walk_dist: float
    route_dist: float
    id: int
    parent: int

    def __init__(self,id: int, route_dist: float, walk_dist: float, stop: Stop, parent: int= -1):
        self.id = id
        self.route_dist = route_dist
        self.walk_dist = walk_dist
        self.stop = stop
        self.parent = parent