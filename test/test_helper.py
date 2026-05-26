from module.route import Route
from module.label_setting_point import Stop

from heuristic.helper import duplicate_students_in_routes
'''
route1 = Route(
    stops=[
        Stop(Id=0, is_depot=True, is_student=False, second_idx=0, is_covered = False),
        Stop(Id=1, is_depot=False, is_student=True, second_idx=1, is_covered = False),
        Stop(Id=2, is_depot=False, is_student=True, second_idx=2, is_covered = False),
        Stop(Id=3, is_depot=False, is_student=True, second_idx=3, is_covered = False),
        Stop(Id=0, is_depot=True, is_student=False, second_idx=4, is_covered = False),
    ],
    total_distance=10.0,
    total_walking_distance=5.0,
    served_students={1, 2, 3},
    cost=15.0,
)
route2 = Route(
    stops=[
        Stop(Id=0, is_depot=True, is_student=False, second_idx=0, is_covered = False),
        Stop(Id=1, is_depot=False, is_student=True, second_idx=1, is_covered = False),
        Stop(Id=3, is_depot=False, is_student=True, second_idx=3, is_covered = False),
        Stop(Id=0, is_depot=True, is_student=False, second_idx=4, is_covered = False),
    ],
    total_distance=5.0,
    total_walking_distance=0.0,
    served_students={1, 3},
    cost=10.0,
)

def test_duplicate_students_in_routes():
    routes = [route1, route2]
    assert duplicate_students_in_routes(routes) == {1: [0, 1], 3: [0, 1]}


test_duplicate_students_in_routes()'''