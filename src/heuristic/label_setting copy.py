from module.route import Route
from module.label_setting_point import Label
from module.input_model import InputModel
from module.stop_point import Stop, STOP_TYPE
from module.label_setting_point import Label


class LabelSettingAlgorithmPulling:
    def __init__(self, route: Route, model: InputModel):
        self.route: Route = route
        self.max_route_distance: float = model.max_travel_distance
        self.walking_distance: list[float] = model.walking_distance_list
        self.students = model.students
        self.model = model

    def run(self) -> Route:
        stops: list[Stop] = self.route.stops

        stop_labels_dic: dict[int, list[Label]] = {}

        first_stop: Stop = stops[0]
        label = Label(id=0, route_dist=0.0, walk_dist=0.0, stop=first_stop, parent=-1)
        labels: list[Label] = []
        labels.append(label)
        stop_labels_dic[first_stop.second_id] = labels

        id_label = 1
        for i, current_stop in enumerate(stops[1:], start=1):
            if current_stop.stop_type == STOP_TYPE.SCHOOL:
                current_cluster = [self.model.last_depot]
            else:
                current_std = next(
                    s for s in self.students if s.second_id == current_stop.student_id
                )
                current_cluster = current_std.covering_stops

            prev_stop_point: Stop = stops[i - 1]
            if prev_stop_point.stop_type == STOP_TYPE.SCHOOL:
                prev_cluster = [self.model.first_depot]
            else:
                pre_std = next(
                    s
                    for s in self.students
                    if s.second_id == prev_stop_point.student_id
                )
                prev_cluster = pre_std.covering_stops

            for current in current_cluster:
                new_labels: list[Label] = []
                for prev_cluster_stop in prev_cluster:
                    pre_labels = stop_labels_dic.get(prev_cluster_stop.second_id, [])
                    for prev_label in pre_labels:
                        if prev_label.route_dist > self.max_route_distance:
                            break

                        d = self.model.distance_matrix[
                            (prev_cluster_stop.second_id, current.second_id)
                        ]
                        new_route_dist = prev_label.route_dist + d

                        if new_route_dist <= self.max_route_distance:
                            walking_dist = (
                                prev_label.walk_dist
                                + self.model.walking_distance_list[current.second_id]
                            )
                            new_label: Label = Label(
                                id=id_label,
                                route_dist=new_route_dist,
                                walk_dist=walking_dist,
                                stop=current,
                                parent=prev_label.id,
                            )
                            new_labels.append(new_label)
                            id_label += 1

                if new_labels:
                    new_labels.sort(key=lambda l: l.route_dist)
                    stop_labels_dic[current.second_id] = [new_labels[0]]

                    last = 0
                    for lb in range(1, len(new_labels)):
                        if new_labels[lb].walk_dist < new_labels[last].walk_dist:
                            stop_labels_dic[current.second_id].append(new_labels[lb])
                            last = lb

        all_keys = stop_labels_dic.keys()

        all_label_list: list[Label] = []
        for k in all_keys:
            all_label_list.extend(stop_labels_dic[k])

        print(len(all_label_list))

        final_stop = stops[-1]
        final_labels = stop_labels_dic.get(final_stop.second_id, [])
        if not final_labels:
            #return None
            raise Exception("No feasible route found")

        best_label: Label = min(final_labels, key=lambda l: l.walk_dist)

        selected_stops: list[Stop] = []
        curr: Label = best_label

        while curr.parent != -1:
            selected_stops.append(curr.stop)
            curr_id = curr.parent
            curr = next(la for la in all_label_list if curr_id == la.id)

        selected_stops.append(curr.stop)
        selected_stops.reverse()

        served_students = [
            s.student_id for s in selected_stops if s.stop_type != STOP_TYPE.SCHOOL
        ]
        cost = best_label.walk_dist

        result = Route(
            stops=selected_stops,
            total_distance=best_label.route_dist,
            total_walking_distance=best_label.walk_dist,
            served_students=served_students,
            cost=cost,
        )
        return result
