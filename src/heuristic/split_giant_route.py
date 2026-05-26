from module.route import Route
from module.stop_point import Stop
from module.input_model import InputModel
import math
from heuristic.label_setting import LabelSettingAlgorithmPulling


class SplitTour:
    input_model: InputModel
    routes: list[Route]
    giant_tour: Route
    _last_seq: dict[int, list[int]]
    _best_seq_point: list[Stop]
    matrix_place: dict[tuple, str]
    matrix_dis_position: dict[tuple, int]
    matrix_partition: dict[tuple, float]
    last_index: dict[tuple, int]

    def __init__(self, input_model, giant_tour: Route) -> None:
        self.input_model = input_model
        self.giant_tour = giant_tour
        self.matrix_place: dict[tuple, str] = {}
        self.matrix_dis_position: dict[tuple, int] = {}
        self._last_seq: dict[int, list[int]] = {}
        self.matrix_partition: dict[tuple, float] = {}
        self.last_index: dict[tuple, int] = {}

    def split(self) -> list[Route] | None:
        final_result = None
        try:
            stop_count: int = len(self.giant_tour.stops)
            self._best_seq_point = list(self.giant_tour.stops)

            matrix_dist: dict[tuple, float] = self._calculate_matrix(stop_count)
            num_vehicles: int = self._partition_matrix(stop_count, matrix_dist)
            if not self._need_more_search(num_vehicles, stop_count):
                final_result = self._do_routing(num_vehicles)

        except Exception as e:
            print(f"there is an error: {e}")

        return final_result

    def _do_routing(self, num_vehicle: int):
        routes: list[Route] = []
        seq_index_result = sorted(self._last_seq[num_vehicle])

        # iteration over consecutive breakpoints.
        for counter in range(len(seq_index_result) - 1):
            start = seq_index_result[counter]
            end   = seq_index_result[counter + 1]

            best_points: list[Stop] = [self.input_model.first_depot]
            visited_stops: list[str] = self.matrix_place[start, end].split(";")

            for stop_id in visited_stops:
                if not stop_id:          # guard against trailing ";" empty strings
                    continue
                if all(b.second_id != stop_id for b in best_points):
                    sp = next(
                        s for s in self.input_model.all_stops
                        if s.second_id == stop_id
                    )
                    best_points.append(sp)

            best_points.append(self.input_model.last_depot)

            new_route = Route(
                best_points,
                total_distance=0,
                total_walking_distance=0,
                served_students=[],
            )
            routes.append(new_route)

        return routes

    def _need_more_search(self, row_id, stop_count):
        need_more: bool = True
        if self.matrix_partition[row_id, stop_count - 1] != math.inf:
            need_more = False

            seq_index: list[int] = [stop_count - 1]
            for t in range(row_id, 0, -1):
                seq_index.append(self.last_index[t, seq_index[-1]])

            self._last_seq[row_id] = seq_index

        return need_more

    def _calculate_cost(self, row: int, column: int):
        first_depot = self.input_model.first_depot
        last_depot  = self.input_model.last_depot

        tmpPointswithDepot: list[Stop] = [first_depot]
        selected_node_tmp: str = str(first_depot.second_id) + ";"

        for k in range(row, column):
            tmpPointswithDepot.append(self.giant_tour.stops[k + 1])
            selected_node_tmp += str(self._best_seq_point[k + 1].second_id) + ";"

        if last_depot not in tmpPointswithDepot:
            tmpPointswithDepot.append(last_depot)
            selected_node_tmp += str(last_depot.second_id) + ";"

        selectednodes = ";".join(str(s.second_id) for s in tmpPointswithDepot) + ";"

        route_distance = 0.0  # TODO: calculate real route distance
        walk_distance  = 0.0
        tmp_route = Route(tmpPointswithDepot, route_distance, walk_distance, served_students=[])

        if route_distance > self.input_model.max_travel_distance:
            tmp_route = LabelSettingAlgorithmPulling(tmp_route, self.input_model).run()
            selectednodes = ";".join(str(s.second_id) for s in tmp_route.stops) + ";"

        self.matrix_place[row, column] = selectednodes
        self.depot_position = row

        return tmp_route

    def _calculate_matrix(self, num_stops: int):
        matrix_dist: dict[tuple, float] = {
            (i, j): math.inf for i in range(num_stops) for j in range(num_stops)
        }
        self.matrix_place = {}
        self.matrix_dis_position = {}

        for i in range(num_stops - 1):
            j: int = i + 1
            for _c in range(self.input_model.capacity_of_vehicle):
                if j >= num_stops:
                    break

                result: Route | None = self._calculate_cost(i, j)
                if result is not None:
                    if result.total_distance <= self.input_model.max_travel_distance:
                        matrix_dist[i, j] = result.total_walking_distance
                        self.matrix_dis_position[i, j] = self.depot_position

                j += 1

        return matrix_dist

    def _do_partition(
        self, matrix_dist: dict[tuple, float], row_id: int, stop_count: int
    ) -> bool:
        for end_point in range(row_id, stop_count):
            for i in range(row_id - 1, end_point):
                dist = self.matrix_partition[row_id - 1, i] + matrix_dist[i, end_point]
                if dist < self.matrix_partition[row_id, end_point]:
                    self.matrix_partition[row_id, end_point] = dist
                    self.last_index[row_id, end_point] = i

        return False

    def _partition_matrix(self, stop_count: int, matrix_dist: dict[tuple, float]):
        self.matrix_partition = {
            (i, j): math.inf for i in range(stop_count) for j in range(stop_count)
        }
        self.last_index = {
            (i, j): -1 for i in range(stop_count) for j in range(stop_count)
        }

        # Initialise row 0 (single-vehicle base case) — kept outside the loop below
        for end_point in range(1, stop_count):
            self.matrix_partition[0, end_point] = matrix_dist[0, end_point]
        num_vehicles: int = 0
        for i in range(1, self.input_model.number_of_vehicles):
            self._do_partition(matrix_dist, i, stop_count)
            num_vehicles = i

        return num_vehicles