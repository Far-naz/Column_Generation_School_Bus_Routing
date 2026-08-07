from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import webbrowser

import folium
from folium import PolyLine
from module.route import Route
import time

# A palette of distinct colors for routes
ROUTE_COLORS = [
    "#e6194b",
    "#3cb44b",
    "#4363d8",
    "#f58231",
    "#911eb4",
    "#42d4f4",
    "#f032e6",
    "#bfef45",
    "#fabed4",
    "#469990",
    "#dcbeff",
    "#9a6324",
    "#fffac8",
    "#800000",
    "#aaffc3",
]


from module.input_model import DataSource, InputModel
from module.stop_point import STOP_TYPE, Stop, Student
from run_heuristic import solve
from run_main import main_exact

DEFAULT_SCHOOL_ID = 42539#40755#:25#42539:18#33337:10



DEFAULT_NUMBER_OF_VEHICLES = 2
DEFAULT_CAPACITY_OF_VEHICLE = 100
DEFAULT_MAX_TRAVEL_DISTANCE = 18.9
DEFAULT_ALLOWED_WALKING_DISTANCE = 0.7

def _get_student_stop_assignments(
    route: Route,
    model: InputModel,
) -> dict[int, Stop]:
    """
    Returns {student_id: assigned_stop} for all students served by this route.
    Uses stop.covering_students (or model.students) to find which stop
    each student walks to.
    """
    # Build lookup: student_id -> Student object
    student_lookup = {s.id: s for s in model.students if _is_original_student(s)}

    assignments: dict[int, Stop] = {}

    for stop in route.stops:
        if stop.stop_type == STOP_TYPE.SCHOOL:
            continue
        # Each stop knows which students it covers
        student: Student = next(std for std in model.students if stop.student_id == std.second_id)
        #for student in find_student.covering_stops:
        sid = student.id #if hasattr(student, 'id') else student
        #    # Only assign students actually served by this route
        #    if sid in route.served_students:
        assignments[sid] = stop

    return assignments

def _build_model(
    allowed_walking_distance: float, school_id: int = DEFAULT_SCHOOL_ID
) -> InputModel:
    return InputModel(
        DEFAULT_NUMBER_OF_VEHICLES,
        DEFAULT_CAPACITY_OF_VEHICLE,
        DEFAULT_MAX_TRAVEL_DISTANCE,
        allowed_walking_distance,
        school_id,
        DataSource.REAL,
    )


def _is_original_student(stop: Stop) -> bool:
    return stop.stop_type == STOP_TYPE.STUDENT and stop.second_id == stop.id


def _unique_points(stops: list[Stop]) -> list[Stop]:
    unique: OrderedDict[tuple[float, float, int], Stop] = OrderedDict()
    for stop in stops:
        key = (round(stop.lat, 7), round(stop.lon, 7), stop.stop_type.value)
        if key not in unique:
            unique[key] = stop
    return list(unique.values())


def _collect_visible_stops(students: list[Student]) -> list[Stop]:
    visible: list[Stop] = []
    for student in students:
        visible.extend(student.covering_stops)
    return _unique_points(visible)


def _walking_radius_meters(model: InputModel) -> float:
    # Real-data setup uses haversine distance in kilometers.
    if model.distance_metric.value == "harvesian":
        return model.allowed_walking_dist * 1000.0
    return 0.0


def build_map(model: InputModel, routes: list[Route] | None = None) -> folium.Map:
    school = model.school
    students = [student for student in model.students if _is_original_student(student)]
    visible_stops = [
        stop for stop in _collect_visible_stops(model.students)
        if not _is_original_student(stop) and stop.stop_type != STOP_TYPE.SCHOOL
    ]

    student_lookup = {s.id: s for s in students}

    center_lat = school.lat
    center_lon = school.lon
    if students:
        center_lat = sum(s.lat for s in students) / len(students)
        center_lon = sum(s.lon for s in students) / len(students)

    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=13, control_scale=True)

    folium.Marker(
        location=[school.lat, school.lon],
        tooltip=f"School {school.id}",
    ).add_to(fmap)

    walking_radius_m = _walking_radius_meters(model)

    for student in students:
        folium.CircleMarker(
            location=[student.lat, student.lon],
            radius=4,
            color="#7f1d1d",
            fill=True,
            fill_color="#d94f30",
            fill_opacity=0.9,
            tooltip=f"Student {student.id}",
            popup=f"Student ID: {student.id}",
        ).add_to(fmap)
        if walking_radius_m > 0:
            folium.Circle(
                location=[student.lat, student.lon],
                radius=walking_radius_m,
                color="#d94f30",
                weight=1,
                fill=True,
                fill_opacity=0.08,
            ).add_to(fmap)

    for stop in visible_stops:
        folium.CircleMarker(
            location=[stop.lat, stop.lon],
            radius=3,
            color="#12467a",
            fill=True,
            fill_color="#1f77b4",
            fill_opacity=0.85,
            tooltip=f"Stop {stop.id}",
            popup=f"Stop ID: {stop.id}",
        ).add_to(fmap)

    if routes:
        active = [r for r in routes if not r.is_dummy and len(r.stops) >= 2]

        for i, route in enumerate(active):
            color = ROUTE_COLORS[i % len(ROUTE_COLORS)]

            # --- 1. Draw bus route polyline ---
            coords = [(s.lat, s.lon) for s in route.stops]
            if coords[-1] != (school.lat, school.lon):
                coords.append((school.lat, school.lon))

            folium.PolyLine(
                locations=coords,
                color=color,
                weight=5,
                opacity=0.9,
                tooltip=f"Route {i+1} | {route.total_distance:.2f} km | {len(route.served_students)} students",
            ).add_to(fmap)

            # Number the pickup stops along the route
            for j, stop in enumerate(route.stops):
                if stop.stop_type == STOP_TYPE.SCHOOL:
                    continue
                folium.CircleMarker(
                    location=[stop.lat, stop.lon],
                    radius=7,
                    color=color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=1.0,
                    tooltip=f"Route {i+1} · pickup #{j} · stop {stop.second_id}",
                ).add_to(fmap)

            # --- 2. Draw walking lines: student home → assigned pickup stop ---
            assignments = _get_student_stop_assignments(route, model)
            print(f"  Route {i+1}: {len(assignments)} student→stop assignments")  # DEBUG

            for student_id, pickup_stop in assignments.items():
                student = student_lookup.get(student_id)
                if student is None:
                    print(f"    WARNING: student {student_id} not found in lookup")
                    continue

                walk_dist_km = None
                # Try to get actual walking distance if stored on student
                if hasattr(student, 'covering_stops'):
                    for cs in student.covering_stops:
                        if cs.second_id == pickup_stop.second_id:
                            walk_dist_km = getattr(cs, 'distance', None)
                            break

                tooltip_text = (
                    f"Student {student_id} → Stop {pickup_stop.second_id}"
                    + (f" ({walk_dist_km:.3f} km)" if walk_dist_km else "")
                )

                folium.PolyLine(
                    locations=[
                        [student.lat, student.lon],
                        [pickup_stop.lat, pickup_stop.lon],
                    ],
                    color=color,          # same color as the bus route
                    weight=2,
                    opacity=0.7,
                    dash_array="6 4",     # dashed = walking
                    tooltip=tooltip_text,
                ).add_to(fmap)

    return fmap

def launch_map_interface(
    school_id: int = DEFAULT_SCHOOL_ID,
    initial_allowed_walking_distance: float = DEFAULT_ALLOWED_WALKING_DISTANCE,
    output_file: str = "map_interface.html",
    open_browser: bool = True,
) -> Path:
    model = _build_model(initial_allowed_walking_distance, school_id=school_id)
    # model = _build_model(allowed_walking_distance=0.5)
    routes = solve(
        number_of_vehicles=DEFAULT_NUMBER_OF_VEHICLES,
        capacity_of_vehicle=DEFAULT_CAPACITY_OF_VEHICLE,
        max_travel_distance=DEFAULT_MAX_TRAVEL_DISTANCE,
        allowed_walking_distance=DEFAULT_ALLOWED_WALKING_DISTANCE,
        school_id=DEFAULT_SCHOOL_ID,
    )
    if routes:
        for r in routes:
            print(str(r))
    fmap = build_map(model, routes=routes)
    # Use a timestamped filename to bypass any cache
    timestamp = int(time.time())
    output_path = Path(f"map_routes.html") #_{timestamp}"
    if not output_path.is_absolute():
        output_path = Path(__file__).resolve().parent / output_path
    fmap.save(str(output_path))
    print(f"Saved to: {output_path}")

    #fmap = build_map(model)

    #output_path = Path(output_file)
    #if not output_path.is_absolute():
    #    output_path = Path(__file__).resolve().parent / output_path
    #fmap.save(str(output_path))

    if open_browser:
        webbrowser.open(output_path.resolve().as_uri())

    return output_path


if __name__ == "__main__":
    launch_map_interface()
