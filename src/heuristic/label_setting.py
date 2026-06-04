from module.route import Route
from module.label_setting_point import Label
from module.input_model import InputModel
from module.stop_point import Stop, STOP_TYPE


class LabelSettingAlgorithmPulling:
    def __init__(self, route: Route, model: InputModel):
        self.route               = route
        self.max_route_distance  = model.max_travel_distance
        self.model               = model

    def run(self) -> Route:
        stops: list[Stop] = self.route.stops

        def cluster_of(stop: Stop) -> list[Stop]:
            if stop.second_id == self.model.first_depot.second_id:
                return [self.model.first_depot]
            if stop.second_id == self.model.last_depot.second_id:
                return [self.model.last_depot]
            # Regular student stop — use the student's covering stops.
            std = next(
                s for s in self.model.students if s.second_id == stop.student_id
            )
            return std.covering_stops

        # -------------------------------------------------------------------
        # Initialise: seed the first depot with a zero-cost label.
        # -------------------------------------------------------------------
        stop_labels: dict[int, list[Label]] = {}
        id_counter   = 0
        first_label  = Label(
            id=id_counter, route_dist=0.0, walk_dist=0.0,
            stop=stops[0], parent=-1,
        )
        stop_labels[stops[0].second_id] = [first_label]
        id_counter += 1

        all_labels: dict[int, Label] = {first_label.id: first_label}

        # -------------------------------------------------------------------
        # Main label-propagation loop.
        # -------------------------------------------------------------------
        for i, current_stop in enumerate(stops[1:], start=1):
            current_cluster = cluster_of(current_stop)
            prev_cluster    = cluster_of(stops[i - 1])

            for current in current_cluster:
                new_labels: list[Label] = []

                for prev_stop in prev_cluster:
                    for prev_label in stop_labels.get(prev_stop.second_id, []):
                        # Labels are stored sorted by route_dist; once one
                        # exceeds the budget no later one can be feasible.
                        if prev_label.route_dist > self.max_route_distance:
                            break

                        d = self.model.distance_matrix[
                            (prev_stop.second_id, current.second_id)
                        ]
                        new_route_dist = prev_label.route_dist + d

                        if new_route_dist > self.max_route_distance:
                            continue

                        walk_dist = (
                            prev_label.walk_dist
                            + self.model.walking_distance_list[current.second_id]
                        )
                        new_label = Label(
                            id=id_counter,
                            route_dist=new_route_dist,
                            walk_dist=walk_dist,
                            stop=current,
                            parent=prev_label.id,
                        )
                        new_labels.append(new_label)
                        all_labels[id_counter] = new_label
                        id_counter += 1

                if not new_labels:
                    continue

                # Keep the Pareto front: sort by route_dist, then retain only
                # labels where walk_dist strictly decreases (dominance pruning).
                new_labels.sort(key=lambda lb: lb.route_dist)
                pareto: list[Label] = [new_labels[0]]
                for lb in new_labels[1:]:
                    if lb.walk_dist < pareto[-1].walk_dist:
                        pareto.append(lb)

                stop_labels[current.second_id] = pareto

        # -------------------------------------------------------------------
        # Extract the best label at the final stop and backtrack the path.
        # -------------------------------------------------------------------
        final_stop   = stops[-1]
        final_labels = stop_labels.get(final_stop.second_id, [])
        if not final_labels:
            raise Exception(
                f"No feasible route found for sub-tour "
                f"{[s.second_id for s in stops]}"
            )

        best_label = min(final_labels, key=lambda lb: lb.walk_dist)

        selected_stops: list[Stop] = []
        curr = best_label
        while curr.parent != -1:
            selected_stops.append(curr.stop)
            curr = all_labels[curr.parent]   # O(1) dict lookup
        selected_stops.append(curr.stop)     # append the root (first depot)
        selected_stops.reverse()

        served_students = [
            s.student_id
            for s in selected_stops
            if s.stop_type != STOP_TYPE.SCHOOL
            and s.second_id != self.model.first_depot.second_id
        ]

        return Route(
            stops=selected_stops,
            total_distance=best_label.route_dist,
            total_walking_distance=best_label.walk_dist,
            served_students=served_students,
            cost=best_label.walk_dist,
        )