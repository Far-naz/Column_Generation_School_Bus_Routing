from module.stop_point import Stop
import matplotlib.pyplot as plt
from helper.distance_calculator import compute_distance_two_points
from module.input_model import DataSource
from serializer.serialize import (
    get_schools,
    read_all_stops,
    read_bus_stops,
    read_students_locations,
)
import config as cfg



def read_stops_from_file(data_source=DataSource.TOY, school_id=33337) -> list[Stop]:
    if data_source == DataSource.TOY:
        stops = read_all_stops()
    elif data_source == DataSource.REAL:
        stops: list[Stop] = []
        school = get_schools(cfg.SCHOOL_FILE, school_id)
        student_stops = read_students_locations(cfg.STUDENT_FILE, school_id)
        print(f"Number of student stops read: {len(student_stops)}")
        bus_stops = read_bus_stops(cfg.BUS_FILE, len(student_stops))
        stops.extend(school)
        stops.extend(student_stops)
        stops.extend(bus_stops)
    return stops


def get_all_stops(covering_stops):
    all_stops = []
    for stops in covering_stops.values():
        for stop in stops:
            all_stops.append(stop)

    # sort by second_idx
    all_stops.sort(key=lambda s: s.second_idx)

    # print all_stops with their second_idx
    for s in all_stops:
        print(
            f"Stop ID: {s.id}, second_idx: {s.second_idx}, is_student: {s.is_student}, is_covered: {s.is_covered}, std_id: {s.std_id}"
        )
    return all_stops



def get_students(stops):
    return [s for s in stops if s.is_student]


def get_student_ids(all_stops):
    return [s for s in all_stops if s.is_student and not s.is_covered]


def get_walking_distances(covering_stops, students, N_H, metric):
    W = [0.0 for _ in N_H]
    for s_id, stops in covering_stops.items():
        if not any(s.id == s_id for s in students):
            continue
        std = next(s for s in students if s.second_idx == s_id)
        for stop_point in stops:
            dist = compute_distance_two_points(std, stop_point, metric=metric)
            W[stop_point.second_idx] = dist

    return W


# stops = read_all_stops()
def plot_stops(stops):
    # plot stops based on lat and lon
    lats = [s.lat for s in stops]
    lons = [s.lon for s in stops]
    plt.scatter(lons, lats)
    for s in stops:
        if s.is_student:
            plt.text(s.lon, s.lat, str(s.id), color="red", fontsize=12)
        else:
            plt.text(s.lon, s.lat, str(s.id), color="blue", fontsize=12)
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Stops Locations")
    plt.grid()
    plt.show()


# stops = read_stops_from_file(DataSource.REAL, school_id=33337)
# plot_stops(stops)
