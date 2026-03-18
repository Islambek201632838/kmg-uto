"""Тест KDTree + snap_to_node + привязка скважин."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["USE_DB"] = "remote"

from app.services.graph_loader import load_graph, smoke_test as graph_smoke
from app.services.spatial_index import (
    SpatialIndex, load_wells, build_well_node_map, smoke_test,
)


async def main():
    G = await load_graph()
    graph_smoke(G)

    index = SpatialIndex(G)

    wells = await load_wells()
    print(f"Скважин загружено: {len(wells)}")

    well_node_map = build_well_node_map(wells, index)

    smoke_test(index, well_node_map)

    # Пример
    sample_uwi = next(iter(well_node_map))
    sample_node = well_node_map[sample_uwi]
    print(f"Пример: uwi={sample_uwi} -> node_id={sample_node}")
    print(f"  Координаты узла: {G.nodes[sample_node]}")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
    asyncio.run(main())
