"""Тест загрузки графа из remote БД."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["USE_DB"] = "remote"

from app.services.graph_loader import load_graph, smoke_test


async def main():
    print("Загрузка графа...")
    G = await load_graph()
    print(f"Граф: {G.number_of_nodes()} узлов, {G.number_of_edges()} рёбер")

    smoke_test(G)

    # Пример узла
    sample = next(iter(G.nodes))
    print(f"Пример узла: node_id={sample}, data={G.nodes[sample]}")

    # Пример ребра
    u, v = next(iter(G.edges))
    print(f"Пример ребра: {u} -> {v}, weight={G.edges[u, v]['weight']}")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
    asyncio.run(main())
