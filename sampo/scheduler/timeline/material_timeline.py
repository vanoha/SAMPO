import math
from operator import itemgetter

from sortedcontainers import SortedKeyList

from sampo.schemas.landscape import LandscapeConfiguration, MaterialDelivery
from sampo.schemas.resources import Material
from sampo.schemas.time import Time


class SupplyTimeline:
    def __init__(self, landscape_config: LandscapeConfiguration):
        self._timeline = {}
        # material -> list of depots, that can supply this type of resource
        self._resource_sources: dict[str, dict[str, int]] = {}
        for landscape in landscape_config.get_all_resources():
            self._timeline[landscape.id] = SortedKeyList([(Time(0), landscape.count), (Time.inf(), landscape.count)],
                                                         itemgetter(0))
            for count, res in landscape.get_available_resources():
                res_source = self._resource_sources.get(res, None)
                if res_source is None:
                    res_source = {}
                    self._resource_sources[res] = res_source
                res_source[landscape.id] = count

    def find_min_material_time(self, id: str, start_time: Time, materials: list[Material], batch_size: int) \
            -> tuple[MaterialDelivery, Time]:
        sum_materials = sum([material.count for material in materials])
        ratio = sum_materials / batch_size
        batches = math.ceil(ratio)

        first_batch = [material.copy().with_count(material.count // batches) for material in materials]
        return self.supply_resources(id, start_time, first_batch, True)

    def deliver_materials(self, id: str, start_time: Time, finish_time: Time,
                          materials: list[Material], batch_size: int) -> tuple[list[MaterialDelivery], Time, Time]:
        """
        Models material delivery.

        Delivery performed in batches sized by batch_size.

        :return: pair of material-driven minimum start and finish times
        """
        sum_materials = sum([material.count for material in materials])
        ratio = sum_materials / batch_size
        batches = math.ceil(ratio)

        first_batch = [material.copy().with_count(material.count // batches) for material in materials]
        other_batches = [first_batch for _ in range(batches - 1)]
        other_batches.append([material.copy().with_count(material.count * (ratio - batches)) for material in materials])

        deliveries = []
        d, start_time = self.supply_resources(id, start_time, first_batch, False)
        deliveries.append(d)
        batch_processing = [self.supply_resources(id, finish_time, batch, False) for batch in other_batches]
        finish_time = max([b[1] for b in batch_processing])
        deliveries.extend([b[0] for b in batch_processing])

        return deliveries, start_time, finish_time

    def _find_best_supply(self, material: str, count: int) -> str:
        # TODO Make better algorithm
        # Return the first depot that can supply given materials
        return [depot_id for depot_id, depot_count in self._resource_sources[material].items() if depot_count >= count][0]

    def supply_resources(self, id: str, deadline: Time, materials: list[Material], simulate: bool) \
            -> tuple[MaterialDelivery, Time]:
        """
        Finds minimal time that given materials can be supplied, greater that given start time

        :param id: work id
        :param deadline: the time work starts
        :param materials: material resources that are required to start
        :param simulate: should timeline only find minimum supply time and not change timeline
        # :param workground_size: material capacity of the workground
        :return: the time when resources are ready
        """
        min_start_time = deadline
        delivery = MaterialDelivery(id)

        def record_delivery(name: str, time: Time, depot: str, count: int):
            # update depot state
            self._resource_sources[name][depot] -= count
            # add to the result
            delivery.add_delivery(name, time, count)

        for material in materials:
            depot = self._find_best_supply(material.name, material.count)
            material_timeline = self._timeline[depot]

            count_left = material.count
            cur_start_time = deadline

            going_right = False

            while count_left > 0:
                # find current area
                idx_left = material_timeline.bisect_key_left(cur_start_time)
                idx_right = material_timeline.bisect_key_right(cur_start_time)

                # find first area with count > 0
                if going_right:
                    while idx_left >= 0 and material_timeline[idx_left][1] == 0:
                        idx_right = idx_left
                        idx_left -= 1
                        if idx_left < 0:
                            going_right = True

                if not going_right:
                    # we can't supply given materials to 'start_time' moment
                    # so, let's go deeper
                    cur_start_time = deadline
                    idx_left = material_timeline.bisect_key_left(cur_start_time)
                    idx_right = material_timeline.bisect_key_right(cur_start_time)

                    while idx_right < len(material_timeline) and material_timeline[idx_left][1] == 0:
                        idx_left = idx_right
                        idx_right += 1

                    # Here we know that we can't supply materials to 'start_time' moment
                    # TODO grab from right part of this area

                # TODO Handle case that we completely can't supply given materials to 'start_time' moment

                time_start = material_timeline[idx_left][0]
                time_end = material_timeline[idx_right][0]
                capacity = material_timeline[0][1]

                # grab resources
                # grab from start point, if fallen onto it
                if time_end == cur_start_time:
                    count_left -= material_timeline[idx_right][1]
                    if not simulate:
                        if count_left < 0:
                            record_delivery(material.name, time_start, depot, material_timeline[idx_right][1] + count_left)
                            material_timeline[idx_right] = (time_start, -count_left)
                        else:
                            record_delivery(material.name, time_start, depot, material_timeline[idx_right][1])
                            material_timeline[idx_right] = (time_start, 0)

                # grab from current area
                cur_start_time = min(cur_start_time, time_end)
                while count_left > 0 and cur_start_time >= time_start:
                    count_left -= capacity
                    cur_start_time -= 1

                if not simulate:
                    # update the idx_left milestone
                    if cur_start_time < time_start:
                        if count_left >= 0:
                            record_delivery(material.name, time_start, depot, material_timeline[idx_left][1])
                            material_timeline[idx_left] = (time_start, 0)
                        else:
                            record_delivery(material.name, time_start, depot, material_timeline[idx_left][1] + count_left)
                            material_timeline[idx_left] = (time_start, -count_left)
                    else:
                        # optimization: we don't need to add milestone with count = capacity, e.g. count_left = 0
                        if count_left < 0:
                            record_delivery(material.name, cur_start_time + 1, depot, -count_left)
                            material_timeline.add((cur_start_time + 1, capacity + count_left))

            min_start_time = min(min_start_time, cur_start_time)

        return delivery, min_start_time





