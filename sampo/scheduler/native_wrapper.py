from deap.base import Toolbox

from sampo.schemas.time import Time

native = True
try:
    from native import decodeEvaluationInfo
    from native import evaluate as evaluator
    from native import freeEvaluationInfo
    from native import runGenetic
except ImportError:
    print("Can't find native module; switching to default")
    decodeEvaluationInfo = lambda *args: args
    freeEvaluationInfo = lambda *args: args
    runGenetic = lambda *args: args
    evaluator = None
    native = False


from sampo.scheduler.genetic.converter import ChromosomeType
from sampo.schemas.contractor import Contractor
from sampo.schemas.graph import WorkGraph, GraphNode
from sampo.schemas.resources import Worker
from sampo.schemas.time_estimator import WorkTimeEstimator
from sampo.utilities.collections_util import reverse_dictionary


class NativeWrapper:
    def __init__(self,
                 toolbox: Toolbox,
                 wg: WorkGraph,
                 contractors: list[Contractor],
                 worker_name2index: dict[str, int],
                 worker_pool_indices: dict[int, dict[int, Worker]],
                 parents: dict[int, list[int]],
                 time_estimator: WorkTimeEstimator):
        self.native = native
        if not native:
            def fit(chromosome: ChromosomeType) -> int:
                if toolbox.validate(chromosome):
                    sworks = toolbox.chromosome_to_schedule(chromosome)[0]
                    return max([swork.finish_time for swork in sworks.values()]).value
                else:
                    return Time.inf()
            self.evaluator = lambda _, chromosomes: [fit(chromosome) for chromosome in chromosomes]
            self._cache = None
            return

        # the outer numeration. Begins with inseparable heads, continuous with tails.
        numeration: dict[int, GraphNode] = {i: node for i, node in
                                            enumerate(filter(lambda node: not node.is_inseparable_son(), wg.nodes))}
        heads_count = len(numeration)
        for i, node in enumerate([node for node in wg.nodes if node.is_inseparable_son()]):
            numeration[heads_count + i] = node
        rev_numeration = reverse_dictionary(numeration)

        # TODO remove assignment unuseful info to self

        self.numeration = numeration
        # for each vertex index store list of parents' indices
        self.parents = [[rev_numeration[p] for p in numeration[index].parents] for index in range(wg.vertex_count)]
        head_parents = [parents[i] for i in range(len(parents))]
        # for each vertex index store list of whole it's inseparable chain indices
        self.inseparables = [[rev_numeration[p] for p in numeration[index].get_inseparable_chain_with_self()]
                             for index in range(wg.vertex_count)]
        # contractors' workers matrix. If contractor can't supply given type of worker, 0 should be passed
        self.workers = [[0 for _ in range(len(worker_name2index))] for _ in contractors]
        for i, contractor in enumerate(contractors):
            for worker in contractor.workers.values():
                self.workers[i][worker_name2index[worker.name]] = worker.count

        min_req = [[] for _ in range(len(numeration))]  # np.zeros((len(numeration), len(worker_pool_indices)))
        max_req = [[] for _ in range(len(numeration))]  # np.zeros((len(numeration), len(worker_pool_indices)))
        for work_index, node in numeration.items():
            cur_min_req = [0 for _ in worker_name2index]
            cur_max_req = [0 for _ in worker_name2index]
            for req in node.work_unit.worker_reqs:
                worker_index = worker_name2index[req.kind]
                cur_min_req[worker_index] = req.min_count
                cur_max_req[worker_index] = req.max_count
            min_req[work_index] = cur_min_req
            max_req[work_index] = cur_max_req

        volume = [node.work_unit.volume for node in numeration.values()]

        self.totalWorksCount = wg.vertex_count
        self.time_estimator = time_estimator
        self.worker_pool_indices = worker_pool_indices
        self._current_chromosomes = None

        self.evaluator = evaluator

        # preparing C++ cache
        self._cache = decodeEvaluationInfo(self, self.parents, head_parents, self.inseparables, self.workers,
                                           self.totalWorksCount,
                                           False, volume, min_req, max_req)

    def calculate_working_time(self, chromosome_ind: int, team_target: int, work: int) -> int:
        team = self._current_chromosomes[chromosome_ind][1][team_target]
        workers = [self.worker_pool_indices[worker_index][team[len(self.workers[0])]]
                   .copy().with_count(team[worker_index])
                   for worker_index in range(len(self.workers[0]))
                   if team[worker_index] > 0]
        return self.numeration[work].work_unit.estimate_static(workers, self.time_estimator).value

    def evaluate(self, chromosomes: list[ChromosomeType]):
        self._current_chromosomes = chromosomes
        return self.evaluator(self._cache, chromosomes)

    def run_genetic(self, chromosomes: list[ChromosomeType],
                    mutate_order, mate_order, mutate_resources, mate_resources,
                    mutate_contractors, mate_contractors, selection_size):
        self._current_chromosomes = chromosomes
        return runGenetic(self._cache, chromosomes, mutate_order, mutate_resources, mutate_contractors,
                          mate_order, mate_resources, mate_contractors, selection_size)

    def close(self):
        freeEvaluationInfo(self._cache)
