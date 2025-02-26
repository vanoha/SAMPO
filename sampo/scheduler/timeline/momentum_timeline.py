from collections import deque
from typing import Optional, Union, Iterable

from sortedcontainers import SortedList

from sampo.scheduler.timeline.base import Timeline
from sampo.scheduler.timeline.material_timeline import SupplyTimeline
from sampo.schemas.contractor import Contractor, WorkerContractorPool
from sampo.schemas.graph import GraphNode
from sampo.schemas.landscape import LandscapeConfiguration
from sampo.schemas.requirements import WorkerReq
from sampo.schemas.resources import Worker
from sampo.schemas.scheduled_work import ScheduledWork
from sampo.schemas.time import Time
from sampo.schemas.time_estimator import WorkTimeEstimator
from sampo.schemas.types import AgentId, ScheduleEvent, EventType
from sampo.utilities.collections_util import build_index


class MomentumTimeline(Timeline):
    """
    Timeline that stores the intervals in which resources is occupied.
    """

    def __init__(self, tasks: Iterable[GraphNode], contractors: Iterable[Contractor],
                 worker_pool: WorkerContractorPool, landscape: LandscapeConfiguration):
        """
        This should create an empty Timeline from given a list of tasks and contractor list.
        """

        # using  time, seq_id and event_type we can guarantee that
        # there may be only one possible order in cases:
        # (a) when events have the same time
        # (in this cases we need both time and seq_id to properly handle available_workers processing logic)
        # (b) when events have the same time and their start and end matches
        # (service tasks for instance may have zero length)
        def event_cmp(event: Union[ScheduleEvent, Time, tuple[Time, int, int]]) -> tuple[Time, int, int]:
            if isinstance(event, ScheduleEvent):
                if event.event_type is EventType.INITIAL:
                    return Time(-1), -1, event.event_type.priority

                return event.time, event.seq_id, event.event_type.priority

            if isinstance(event, Time):
                # instances of Time must be greater than almost all ScheduleEvents with same time point
                return event, Time.inf().value, 2

            if isinstance(event, tuple):
                return event

            raise ValueError(f"Incorrect type of value: {type(event)}")

        # to efficiently search for time slots for tasks to be scheduled
        # we need to keep track of starts and ends of previously scheduled tasks
        # and remember how many workers of a certain type is available at this particular moment
        self._timeline: dict[str, dict[str, SortedList[ScheduleEvent]]] = {
            contractor.id: {
                w_name: SortedList(
                    iterable=(ScheduleEvent(-1, EventType.INITIAL, Time(0), None, ws.count),),
                    key=event_cmp
                )
                for w_name, ws in contractor.workers.items()
            }
            for contractor in contractors
        }

        # internal index, earlier - task_index parameter for schedule method
        self._task_index = 0
        self._material_timeline = SupplyTimeline(landscape)

    def find_min_start_time_with_additional(self,
                                            node: GraphNode,
                                            worker_team: list[Worker],
                                            node2swork: dict[GraphNode, ScheduledWork],
                                            assigned_start_time: Optional[Time] = None,
                                            assigned_parent_time: Time = Time(0),
                                            work_estimator: Optional[WorkTimeEstimator] = None) \
            -> tuple[Time, Time, dict[GraphNode, tuple[Time, Time]]]:
        """
        Looking for an available time slot for given 'GraphNode'

        :param worker_team: list of passed workers. Should be IN THE SAME ORDER AS THE CORRESPONDING WREQS
        :param node: info about given GraphNode
        :param node2swork: dictionary, that match GraphNode to ScheduleWork respectively
        :param assigned_start_time: start time, that can be received from
        another algorithms of calculation the earliest start time
        :param assigned_parent_time: minimum start time
        :param work_estimator: function that calculates execution time of the GraphNode
        :return: start time, end time, time of execution
        """
        inseparable_chain = node.get_inseparable_chain_with_self()
        contractor_id = worker_team[0].contractor_id if worker_team else ""
        # 1. identify earliest possible start time by max parent's end time

        def apply_time_spec(time: Time):
            return max(time, assigned_start_time) if assigned_start_time is not None else time

        max_parent_time: Time = max(apply_time_spec(
            max((node2swork[pnode].min_child_start_time for pnode in node.parents), default=Time(0))
        ), assigned_parent_time)

        if node.neighbors:
            max_neighbor_time = max(node2swork[neighbor].start_time for neighbor in node.neighbors)
            max_parent_time = max(max_parent_time, max_neighbor_time)

        nodes_max_parent_times: dict[GraphNode, Time] = {n: max((max(apply_time_spec(node2swork[pnode].min_child_start_time),
                                                                     assigned_parent_time)
                                                                 if pnode in node2swork else assigned_parent_time
                                                                 for pnode in n.parents),
                                                                default=assigned_parent_time)
                                                         for n in inseparable_chain}

        # 2. calculating execution time of the task

        exec_time: Time = Time(0)
        exec_times: dict[GraphNode, tuple[Time, Time]] = {}  # node: (lag, exec_time)
        for _, chain_node in enumerate(inseparable_chain):
            node_exec_time: Time = Time(0) if len(chain_node.work_unit.worker_reqs) == 0 else \
                chain_node.work_unit.estimate_static(worker_team, work_estimator)
            lag_req = nodes_max_parent_times[chain_node] - max_parent_time - exec_time
            lag = lag_req if lag_req > 0 else 0

            exec_times[chain_node] = lag, node_exec_time
            exec_time += lag + node_exec_time

        if len(worker_team) == 0:
            max_material_time = self._material_timeline.find_min_material_time(node.id, max_parent_time, node.work_unit.need_materials(), node.work_unit.workground_size)
            max_parent_time = max(max_parent_time, max_material_time)
            return max_parent_time, max_parent_time, exec_times

        start_time = assigned_start_time if assigned_start_time is not None else self._find_min_start_time(
            self._timeline[contractor_id], inseparable_chain, max_parent_time, exec_time, worker_team
        )

        max_material_time = self._material_timeline.find_min_material_time(node.id,
                                                                           start_time,
                                                                           node.work_unit.need_materials(),
                                                                           node.work_unit.workground_size)
        st = max(max_material_time, start_time)
        assert st >= assigned_parent_time

        return start_time, start_time + exec_time, exec_times

    def _find_min_start_time(self,
                             resource_timeline: dict[str, SortedList[ScheduleEvent]],
                             inseparable_chain: list[GraphNode],
                             parent_time: Time,
                             exec_time: Time,
                             passed_workers: list[Worker]) -> Time:
        """
        Find start time for the whole 'GraphNode'

        :param resource_timeline: dictionary that stores resource and its Timeline
        :param inseparable_chain: list of GraphNodes that represent one big task,
        that are divided into several dependent tasks
        :param parent_time: the minimum start time
        :param exec_time: the time of execution 
        :param passed_workers: list of passed workers. Should be IN THE SAME ORDER AS THE CORRESPONDING WREQS
        :return:
        """
        # if it is a service unit, then it can be satisfied by any contractor at any moment
        # because no real workers are going to be used to execute the task,
        # however, we still should respect dependencies of the service task
        # and should start it only after all the dependency tasks are done
        if all((node.work_unit.is_service_unit for node in inseparable_chain)):
            return parent_time

        # checking if the contractor can satisfy requirements for the task at all,
        # we return None in cases when the task cannot be executed
        # even if it is scheduled to the very end, e.g., after the end of all other tasks
        # already scheduled to this contractor

        for node in inseparable_chain:
            for i, wreq in enumerate(node.work_unit.worker_reqs):
                initial_event: ScheduleEvent = resource_timeline[wreq.kind][0]
                assert initial_event.event_type is EventType.INITIAL
                # if this contractor initially has fewer workers of this type, then needed...
                if initial_event.available_workers_count < passed_workers[i].count:
                    return Time.inf()

        # here we look for the earliest time slot that can satisfy all the worker's specializations
        # we do it in that manner because each worker specialization can be treated separately
        # e.g. requested for different tasks
        # We check only the first node since all inseparable nodes have
        # same worker_reqs despite the difference in exec time
        queue = deque(inseparable_chain[0].work_unit.worker_reqs)

        start = parent_time
        scheduled_wreqs: list[WorkerReq] = []

        type2count: dict[str, int] = build_index(passed_workers, lambda w: w.name, lambda w: w.count)

        i = 0
        while len(queue) > 0:
            # if i > 0 and i % 50 == 0:
            #     print(f"Warning! Probably cycle in looking for diff workers: {i} iteration")
            i += 1

            wreq = queue.popleft()
            state = resource_timeline[wreq.kind]
            # we look for the earliest time slot starting from 'start' time moment
            # if we have found a time slot for the previous task,
            # we should start to find for the earliest time slot of other task since this new time
            found_start = self._find_earliest_time_slot(state, start, exec_time, type2count[wreq.kind])

            assert found_start >= start

            if len(scheduled_wreqs) == 0 or start == found_start:
                # we schedule the first worker's specialization or the next spec has the same start time
                # as the all previous ones
                scheduled_wreqs.append(wreq)
                start = max(found_start, start)
            else:
                # The current worker specialization can be started only later than
                # the previously found start time.
                # In this case we need to add back all previously scheduled wreq-s into the queue
                # to be scheduled again with the new start time (e.g. found start).
                # This process should reach its termination at least at the very end of this contractor's schedule.
                queue.extend(scheduled_wreqs)
                scheduled_wreqs.clear()
                scheduled_wreqs.append(wreq)
                start = max(found_start, start)

        return start

    @staticmethod
    def _find_earliest_time_slot(state: SortedList[ScheduleEvent],
                                 parent_time: Time,
                                 exec_time: Time,
                                 required_worker_count: int) -> Time:
        """
        Searches for the earliest time starting from start_time, when a time slot
        of exec_time is available, when required_worker_count of resources is available

        :param state: stores Timeline for the certain resource
        :param parent_time: the minimum start time starting from the end of the parent task
        :param exec_time: execution time of work
        :param required_worker_count: requirements amount of Worker
        :return: the earliest start time
        """
        current_start_time = parent_time
        current_start_idx = state.bisect_right(current_start_time) - 1

        # the condition means we have reached the end of schedule for this contractor subject to specialization (wreq)
        # as long as we assured that this contractor has enough capacity at all to handle the the task
        # we can stop and put the task at the very end
        i = 0
        while len(state[current_start_idx:]) > 0:
            # if i > 0 and i % 50 == 0:
            #     print(f"Warning! Probably cycle in looking for earliest time slot: {i} iteration")
            #     print(f"Current start time: {current_start_time}, current start idx: {current_start_idx}")
            i += 1
            end_idx = state.bisect_right(current_start_time + exec_time + 1)

            # checking from the end of execution interval, i.e., end_idx - 1
            # up to (including) the event right prepending the start
            # of the execution interval, i.e., current_start_idx - 1
            # we need to check the event current_start_idx - 1 cause it is the first event
            # that influence amount of available for us workers
            not_enough_workers_found = False
            for idx in range(end_idx - 1, current_start_idx - 2, -1):
                if state[idx].available_workers_count < required_worker_count or state[idx].time <= parent_time:
                    # we're trying to find a new slot that would start with
                    # either the last index passing the quantity check
                    # or the index after the execution interval
                    # we need max here to process a corner case when the problem arises
                    # on current_start_idx - 1
                    # without max it would get into infinite cycle
                    current_start_idx = max(idx, current_start_idx) + 1
                    not_enough_workers_found = True
                    break

            if not not_enough_workers_found:
                break

            if current_start_idx >= len(state):
                break

            current_start_time = state[current_start_idx].time

        return current_start_time

    def update_timeline(self,
                        finish_time: Time,
                        node: GraphNode,
                        node2swork: dict[GraphNode, ScheduledWork],
                        worker_team: list[Worker]):
        """
        Inserts `chosen_workers` into the timeline with it's `inseparable_chain`
        """
        # 7. for each worker's specialization of the chosen contractor being used by the task
        # we update counts of available workers on previously scheduled events
        # that lie between start and end of the task
        # Also, add events of the start and the end to worker's specializations
        # of the chosen contractor.

        task_index = self._task_index
        self._task_index += 1

        # experimental logics lightening. debugging showed its efficiency.

        swork = node2swork[node]  # masking the whole chain ScheduleEvent with the first node
        start = swork.start_time
        end = node2swork[node.get_inseparable_chain_with_self()[-1]].finish_time + 1
        for w in worker_team:
            state = self._timeline[w.contractor_id][w.name]
            start_idx = state.bisect_right(start)
            end_idx = state.bisect_right(end)
            available_workers_count = state[start_idx - 1].available_workers_count
            # updating all events in between the start and the end of our current task
            for event in state[start_idx: end_idx]:
                assert event.available_workers_count >= w.count
                event.available_workers_count -= w.count

            assert available_workers_count >= w.count

            if start_idx < end_idx:
                event: ScheduleEvent = state[end_idx - 1]
                assert state[0].available_workers_count >= event.available_workers_count + w.count
                end_count = event.available_workers_count + w.count
            else:
                assert state[0].available_workers_count >= available_workers_count
                end_count = available_workers_count

            state.add(ScheduleEvent(task_index, EventType.START, start, swork, available_workers_count - w.count))
            state.add(ScheduleEvent(task_index, EventType.END, end, swork, end_count))

    def schedule(self,
                 node: GraphNode,
                 node2swork: dict[GraphNode, ScheduledWork],
                 workers: list[Worker],
                 contractor: Contractor,
                 assigned_start_time: Optional[Time] = None,
                 assigned_time: Optional[Time] = None,
                 assigned_parent_time: Time = Time(0),
                 work_estimator: Optional[WorkTimeEstimator] = None):
        inseparable_chain = node.get_inseparable_chain_with_self()
        start_time, _, exec_times = \
            self.find_min_start_time_with_additional(node, workers, node2swork, assigned_start_time,
                                                     assigned_parent_time, work_estimator)
        if assigned_time is not None:
            exec_times = {n: (Time(0), assigned_time // len(inseparable_chain))
                          for n in inseparable_chain}

        # TODO Decide how to deal with exec_times(maybe we should remove using pre-computed exec_times)
        self._schedule_with_inseparables(node, node2swork, inseparable_chain,
                                         workers, contractor, start_time, exec_times)

    def _schedule_with_inseparables(self,
                                    node: GraphNode,
                                    node2swork: dict[GraphNode, ScheduledWork],
                                    inseparable_chain: list[GraphNode],
                                    worker_team: list[Worker],
                                    contractor: Contractor,
                                    start_time: Time,
                                    exec_times: dict[GraphNode, tuple[Time, Time]]):
        # 6. create a schedule entry for the task

        nodes_start_times: dict[GraphNode, Time] = {n: max((node2swork[pnode].min_child_start_time
                                                            if pnode in node2swork else Time(0)
                                                            for pnode in n.parents),
                                                           default=Time(0))
                                                    for n in inseparable_chain}

        curr_time = start_time
        for i, chain_node in enumerate(inseparable_chain):
            _, node_time = exec_times[chain_node]

            lag_req = nodes_start_times[chain_node] - curr_time
            node_lag = lag_req if lag_req > 0 else 0

            start_work = curr_time + node_lag
            swork = ScheduledWork(
                work_unit=chain_node.work_unit,
                start_end_time=(start_work, start_work + node_time),
                workers=worker_team,
                contractor=contractor
            )
            curr_time += node_time + node_lag
            node2swork[chain_node] = swork

        self.update_timeline(curr_time, node, node2swork, worker_team)

    def __getitem__(self, item: AgentId):
        return self._timeline[item[0]][item[1]]
