"""Тест кратчайших путей и cost matrix."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["USE_DB"] = "remote"

import networkx as nx
from app.services.graph_loader import load_graph
from app.services.spatial_index import SpatialIndex, load_wells, build_well_node_map
from app.services.shortest_path import single_path, build_cost_matrix, smoke_test


async def main():
    G = await load_graph()
    index = SpatialIndex(G)
    wells = await load_wells()
    wnm = build_well_node_map(wells, index)

    smoke_test(G)

    # Берём скважины из наибольшей компоненты (чтобы пути были конечными)
    largest_cc = max(nx.weakly_connected_components(G), key=len)
    reachable_uwis = [u for u, nid in wnm.items() if nid in largest_cc]
    print(f"\nСкважин в наибольшей компоненте: {len(reachable_uwis)}/{len(wnm)}")

    # Маршрут между двумя скважинами
    src_uwi, dst_uwi = reachable_uwis[0], reachable_uwis[1]
    src, dst = wnm[src_uwi], wnm[dst_uwi]
    result = single_path(G, src, dst)
    print(f"\nМаршрут {src_uwi} -> {dst_uwi}:")
    print(f"  distance: {result.distance_km} km")
    print(f"  time: {result.time_minutes} min")
    print(f"  path: {len(result.nodes)} узлов")

    # Cost matrix 5x5
    test_uwis = reachable_uwis[:5]
    test_nodes = [wnm[u] for u in test_uwis]
    matrix = build_cost_matrix(G, test_nodes)
    print(f"\nCost matrix 5x5 (km):")
    header = "            " + " ".join(f"{u:>10}" for u in test_uwis)
    print(header)
    for i, u in enumerate(test_uwis):
        row = " ".join(f"{matrix[i][j]:10.1f}" for j in range(len(test_uwis)))
        print(f"  {u:>10}: {row}")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
    asyncio.run(main())
