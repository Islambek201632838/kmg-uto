"""Загрузка графа дорог из БД в networkx.DiGraph.

Bulk-загрузка при старте через синхронный psycopg2 в thread pool.
Рёбра в БД хранятся односторонние — добавляем обратные (дороги двусторонние).
Результат: in-memory DiGraph (~4624 узлов, ~38062 рёбер), готовый для Dijkstra.
"""
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import networkx as nx
from sqlalchemy import create_engine, text

from app.config import settings

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="graph_loader")


def _load_from_db() -> nx.DiGraph:
    """Синхронная bulk-загрузка графа. Вызывается в thread pool."""
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    G = nx.DiGraph()

    with engine.connect() as conn:
        t0 = time.perf_counter()
        rows = conn.execute(
            text('SELECT node_id, lon, lat FROM "references".road_nodes')
        ).fetchall()
        nodes = [(r[0], {"lon": float(r[1]), "lat": float(r[2])}) for r in rows]
        G.add_nodes_from(nodes)
        logger.info("Узлы загружены: %d за %.3fs", len(nodes), time.perf_counter() - t0)

        t0 = time.perf_counter()
        rows = conn.execute(
            text('SELECT source, target, weight FROM "references".road_edges')
        ).fetchall()
        # Дороги двусторонние — добавляем прямое и обратное ребро
        edges = []
        for r in rows:
            w = {"weight": float(r[2])}
            edges.append((r[0], r[1], w))
            edges.append((r[1], r[0], w))
        G.add_edges_from(edges)
        logger.info(
            "Рёбра загружены: %d из БД -> %d (с обратными) за %.3fs",
            len(rows), G.number_of_edges(), time.perf_counter() - t0,
        )

    engine.dispose()
    return G


async def load_graph() -> nx.DiGraph:
    """Async обёртка — bulk-загрузка в thread pool, не блокирует event loop."""
    loop = asyncio.get_running_loop()
    G = await loop.run_in_executor(_pool, _load_from_db)
    return G


def smoke_test(G: nx.DiGraph) -> None:
    """Проверка целостности графа после загрузки."""
    assert G.number_of_nodes() > 0, "Граф пустой: 0 узлов"
    assert G.number_of_edges() > 0, "Граф пустой: 0 рёбер"

    sample_node = next(iter(G.nodes))
    data = G.nodes[sample_node]
    assert "lon" in data and "lat" in data, f"Узел {sample_node} без lon/lat"

    sample_edge = next(iter(G.edges))
    w = G.edges[sample_edge]["weight"]
    assert w > 0, f"Ребро {sample_edge} weight={w} <= 0"

    if nx.is_weakly_connected(G):
        logger.info("Граф связный (weakly connected)")
    else:
        components = list(nx.weakly_connected_components(G))
        largest = max(len(c) for c in components)
        logger.warning(
            "Граф НЕ связный: %d компонент, наибольшая %d узлов",
            len(components), largest,
        )

    logger.info(
        "Smoke test graph_loader: OK (%d nodes, %d edges)",
        G.number_of_nodes(), G.number_of_edges(),
    )
