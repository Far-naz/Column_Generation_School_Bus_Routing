from math import radians, sin, cos, sqrt, atan2
import enum


class DistanceMetric(enum.Enum):
    EUCLIDEAN = "euclidean"
    HARVESIAN = "harvesian"


def _compute_harvesian_distance_two_points(stop1, stop2) -> float:
    R = 6371.0088  # Radius of the Earth in kilometers
    lat1 = radians(stop1.lat)
    lon1 = radians(stop1.lon)
    lat2 = radians(stop2.lat)
    lon2 = radians(stop2.lon)

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


def _compute_euclidean_distance_two_points(stop1, stop2) -> float:
    return ((stop1.lat - stop2.lat) ** 2 + (stop1.lon - stop2.lon) ** 2) ** 0.5


def _compute_euclidean_distance_matrix(N_H, all_stops) -> dict[tuple, float]:
    d = {}
    for i in N_H:
        for j in N_H:
            stop_i = next(s for s in all_stops if s.second_id == i)
            stop_j = next(s for s in all_stops if s.second_id == j)
            dist = _compute_euclidean_distance_two_points(stop_i, stop_j)
            d[i, j] = dist
            d[j, i] = dist

    return d


def _compute_harvesian_distance_matrix(N_H, all_stops) -> dict[tuple, float]:
    
    # O(n) lookup instead of O(n) scan inside the double loop
    stop_lookup = {s.second_id: s for s in all_stops}
    
    d = {}
    n = len(N_H)
    for i in range(n):
        id_i = N_H[i]
        stop_i = stop_lookup[id_i]
        for j in range(i, n):          # upper triangle only — no redundant work
            id_j = N_H[j]
            stop_j = stop_lookup[id_j]
            dist = _compute_harvesian_distance_two_points(stop_i, stop_j)
            d[id_i, id_j] = dist
            d[id_j, id_i] = dist       # symmetric fill in one shot

    return d


def compute_distance_two_points(stop1, stop2, metric=DistanceMetric.EUCLIDEAN) -> float:
    if metric == DistanceMetric.EUCLIDEAN:
        return _compute_euclidean_distance_two_points(stop1, stop2)
    elif metric == DistanceMetric.HARVESIAN:
        return _compute_harvesian_distance_two_points(stop1, stop2)
    else:
        raise ValueError(f"Unknown distance metric: {metric}")


def compute_distance_matrix(
    N_H, all_stops, metric=DistanceMetric.EUCLIDEAN
) -> dict[tuple, float]:
    if metric == DistanceMetric.EUCLIDEAN:
        return _compute_euclidean_distance_matrix(N_H, all_stops)
    else:  # metric == DistanceMetric.HARVESIAN:
        return _compute_harvesian_distance_matrix(N_H, all_stops)
