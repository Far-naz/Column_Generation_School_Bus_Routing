from dataclasses import dataclass
from module.stop_point import Stop, Student
from helper.distance_calculator import DistanceMetric, compute_distance_matrix
from serializer.read_school import get_school
from serializer.read_stops import (
    get_students,
    get_covering_stops,
    get_all_stops,
    get_walking_distances,
)
from enum import Enum

class DataSource(Enum):
    TOY = "toy"
    REAL = "real"



@dataclass
class InputModel:
    number_of_vehicles: int
    capacity_of_vehicle: int
    max_travel_distance: float
    allowed_walking_dist: float
    school_id: int

    students: list[Student]
    all_stops: list[Stop]
    walking_distance_list: list[float]
    school: Stop
    all_stop_ids: list[int]
    all_student_ids: list[int]

    def __init__(
        self,
        number_of_vehicles: int,
        capacity_of_vehicle: int,
        max_travel_distance: float,
        allowed_walking_distance: float,
        school_id: int,
        data_source: DataSource,
    ):
        self.number_of_vehicles = number_of_vehicles
        self.capacity_of_vehicle = capacity_of_vehicle
        self.max_travel_distance = max_travel_distance
        self.allowed_walking_dist = allowed_walking_distance
        self.school_id = school_id
        self.distance_metric = (
            DistanceMetric.EUCLIDEAN
            if data_source == DataSource.TOY
            else DistanceMetric.HARVESIAN
        )

        self.school = get_school(school_id=self.school_id)
        student_list = get_students(school=self.school)
        self.all_student_ids = [std.second_id for std in student_list]
        self.students = get_covering_stops(
            school=self.school,
            students=student_list,
            allowed_walking_dist=self.allowed_walking_dist,
            distance_metric=self.distance_metric,
        )
        self.all_stops = get_all_stops(school=self.school, students=self.students)
        self.all_stop_ids = [s.second_id for s in self.all_stops]

        self.first_depot = self.all_stops[0]
        self.last_depot = self.all_stops[-1]

        self.walking_distance_list = get_walking_distances(
            self.students, self.all_stops, self.distance_metric
        )
        self.distance_matrix = compute_distance_matrix(
            self.all_stop_ids, self.all_stops, self.distance_metric
        )
        self.upper_bound = allowed_walking_distance * len(self.all_stop_ids)

    def get_stop(self, stop_id) -> Stop:
        if stop_id is None:
            raise ValueError("stop_id cannot be None.")
        for stop in self.all_stops:
            if stop.second_id == stop_id:
                return stop
        raise ValueError(f"Stop with ID {stop_id} not found.")



