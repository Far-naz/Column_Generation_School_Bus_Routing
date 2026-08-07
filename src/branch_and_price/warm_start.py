from module.stop_point import Student
from module.route import Route
from module.input_model import InputModel


def create_initial_route(
    students: list[Student], distance: dict[tuple, float], problem_model: InputModel
) -> Route:
    """Create an initial route that covers all students in a single route."""
    first_depot = problem_model.first_depot
    last_depot = problem_model.last_depot

    # Create a route that goes from first depot to each student's covering stop and then to last depot
    stops = [first_depot]
    for student in students:
        stops.append(student)
    stops.append(last_depot)

    route_distance = sum(
        distance[stops[i].second_id, stops[i + 1].second_id]
        for i in range(len(stops) - 1)
    )

    return Route(
        stops=stops,
        served_students=[student.second_id for student in students],
        total_walking_distance=10000,
        total_distance=route_distance,
        is_dummy = True
    )
