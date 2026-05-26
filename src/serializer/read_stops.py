from module.stop_point import Student, Stop, STOP_TYPE
from config import STUDENT_FILE, BUS_FILE
import pandas as pd
from helper.distance_calculator import compute_distance_two_points, DistanceMetric


def _read_students_from_file(data_file: str, school_id: int) -> list[Student]:
    students:list[Student] =[]
    # csv file with header ClientId,AddrId,SubscriptionTemplateId,LocName,schooltype,LocId,schoollat,schoollon,FromAddrType,ToAddrType,adresslat,adresslon,grade,requestedtimeinbound,requestedtimeoutbound
    df = pd.read_csv(data_file)
    df_school = df[df["LocId"] == school_id]
    idx = 1
    for _, row in df_school.iterrows():
        student_id = idx
        name = row["ClientId"]
        lat = float(row["adresslat"]) / 1e6
        lon = float(row["adresslon"]) / 1e6
        existed = [ss for ss in students if lat == ss.lat and lon == ss.lon]
        if len(existed) == 0:
            student = Student(
                id=student_id, lat=lat, lon=lon, second_id=student_id, name=name
            )
            students.append(student)
            idx += 1

    return students


def _read_bus_stops_from_file(data_file: str) -> list[Stop]:
    stops = []
    # csv file with header: StopId,StopAbbr,StopName,Lat,Lon
    df = pd.read_csv(data_file)
    for _, row in df.iterrows():
        name = row["StopId"]
        lat = float(row["Lat"]) / 1e6
        lon = float(row["Lon"]) / 1e6
        stop = Stop(id=name, lat=lat, lon=lon, stop_type=STOP_TYPE.BUSSTOP, name=name, student_id=-1)
        stops.append(stop)

    return stops


def get_students(school: Stop) -> list[Student]:
    student_stops = _read_students_from_file(STUDENT_FILE, school.name)
    print(f"Number of student stops read: {len(student_stops)}")

    return student_stops


def _get_all_stops(school: Stop, students: list[Student]) -> list[Stop]:
    stops: list[Stop] = []
    bus_stops = _read_bus_stops_from_file(BUS_FILE)
    stops.extend([school])
    stops.extend(students)
    stops.extend(bus_stops)

    return stops


def _covering_stop_points(
    student: Student,
    all_stops: list[Stop],
    allowed_walking_dist: float,
    distance_metric: DistanceMetric,
    last_id: int,
) -> tuple[list[Stop], int]:
    covered_list: list[Stop] = []
    for stop in all_stops:
        if stop.id == student.second_id:  # not consider itself
            continue
        dist = compute_distance_two_points(student, stop, distance_metric)
        if dist <= allowed_walking_dist:
            covered_stop = Stop(
                lat=stop.lat,
                lon=stop.lon,
                id=stop.id,
                second_id=last_id,
                stop_type=stop.stop_type,
                name=stop.name,
                student_id=student.second_id
            )
            covered_list.append(covered_stop)
            last_id += 1
    return covered_list, last_id


def get_covering_stops(
    school: Stop,
    students: list[Student],
    allowed_walking_dist: float,
    distance_metric: DistanceMetric,
) -> list[Student]:

    all_stops = _get_all_stops(school=school, students=students)
    last_index = len(students) + 1
    for student in students:
        covering_points, last_index = _covering_stop_points(
            student=student,
            all_stops=all_stops,
            allowed_walking_dist=allowed_walking_dist,
            distance_metric=distance_metric,
            last_id=last_index,
        )
        student.covering_stops.extend(covering_points)

    return students


def get_all_stops(school: Stop, students: list[Student]) -> list[Stop]:
    all_stop_list: list[Stop] = []
    all_stop_list.append(school)
    for student in students:
        all_stop_list.extend(student.covering_stops)
    last_idx = len(all_stop_list)
    last_school = Stop(
        id=school.id,
        lat=school.lat,
        lon=school.lon,
        stop_type=STOP_TYPE.SCHOOL,
        second_id=last_idx,
        name = school.name,
        student_id=school.student_id
    )
    all_stop_list.append(last_school)
    return all_stop_list


def get_walking_distances(students: list[Student], all_stops: list[Stop], metric):
    walking_dist = [0.0 for _ in all_stops]
    for student in students:
        for stop in student.covering_stops:
            dist = compute_distance_two_points(student, stop, metric=metric)
            walking_dist[stop.second_id] = dist

    return walking_dist
