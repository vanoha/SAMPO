from copy import deepcopy
from operator import attrgetter
from typing import Callable

from sampo.scheduler.utils.obstruction import Obstruction
from sampo.schemas.graph import WorkGraph, GraphNode
from sampo.schemas.works import WorkUnit
from sampo.utilities.collections_util import build_index


class BlockNode:
    """
    `BlockNode` represents the node of `BlockGraph` and contains corresponding
    `WorkGraph` and related dependencies between blocks in `BlockGraph`.
    """
    def __init__(self, wg: WorkGraph, obstruction: Obstruction | None = None):
        self.wg = wg
        self.obstruction = obstruction
        self.blocks_from: list[BlockNode] = []
        self.blocks_to: list[BlockNode] = []

    @property
    def id(self):
        return self.wg.start.id

    def __hash__(self):
        return hash(self.id)


class BlockGraph:
    """
    Represents the block graph, where blocks are instances of `WorkGraph` and
    edges are simple *FS* dependencies.
    """
    def __init__(self, nodes: list[BlockNode]):
        self.nodes = nodes
        self.node_dict = build_index(self.nodes, attrgetter('id'))

    @staticmethod
    def pure(nodes: list[WorkGraph], obstruction_getter: Callable[[int], Obstruction | None] = lambda _: None):
        return BlockGraph([BlockNode(node, obstruction_getter(i)) for i, node in enumerate(nodes)])

    def __getitem__(self, item) -> BlockNode:
        return self.node_dict[item]

    def __len__(self):
        return len(self.nodes)

    def to_work_graph(self) -> WorkGraph:
        """
        Construct 'WorkGraph' that is equal to the `BlockGraph`.
        """
        copied_nodes = deepcopy(self.nodes)
        for node in copied_nodes:
            node.wg = WorkGraph._deserialize(node.wg._serialize())
            for wg_node in node.wg.nodes:
                wg_node.__dict__.pop('parents', None)
                wg_node.__dict__.pop('parents_set', None)
                wg_node.__dict__.pop('children', None)
                wg_node.__dict__.pop('children_set', None)
                wg_node.__dict__.pop('inseparable_parent', None)
                wg_node.__dict__.pop('inseparable_son', None)
                wg_node.__dict__.pop('get_inseparable_chain', None)

        nodes_without_children = []

        global_start = GraphNode(WorkUnit('start', 'start', is_service_unit=True), [])

        for end in copied_nodes:
            end.wg.start.add_parents([start.wg.finish for start in end.blocks_to])
            if len(end.wg.start.parents) == 0:
                end.wg.start.add_parents([global_start])
            if len(end.wg.finish.children) == 0:
                nodes_without_children.append(end.wg.finish)

        global_end = GraphNode(WorkUnit('finish', 'finish', is_service_unit=True), nodes_without_children)

        # global_start: GraphNode = [node for node in copied_nodes if len(node.blocks_to) == 0][0].wg.start
        # global_end:   GraphNode = [node for node in copied_nodes if len(node.blocks_from) == 0][0].wg.finish

        return WorkGraph(global_start, global_end)

    def toposort(self) -> list[BlockNode]:
        """
        Sort current 'BlockGraph' in topologic order

        :return: ordered list of BlockNode
        """
        visited = set()
        ans = []

        def dfs(u: BlockNode):
            visited.add(u)
            for v in u.blocks_to:
                if v not in visited:
                    dfs(v)
            ans.append(u)

        for node in self.nodes:
            if node not in visited:
                dfs(node)
        ans.reverse()

        return ans

    @staticmethod
    def add_edge(start: BlockNode, end: BlockNode):
        start.blocks_to.append(end)
        end.blocks_from.append(start)
