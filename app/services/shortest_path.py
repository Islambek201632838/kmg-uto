"""Сервис кратчайших путей: Dijkstra + матрица стоимостей.

- single_path: один маршрут source -> target (thread pool)
- build_cost_matrix: NxN матрица через ThreadPoolExecutor (параллельный Dijkstra по строкам)
"""
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_AVG_SPEED_KMH = 35.0

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dijkstra")


@dataclass(frozen=True, slots=True)
class PathResult:
    distance_km: float
    time_minutes: float
    nodes: list[int]
    coords: list[list[float]]


def single_path(
    G: nx.DiGraph,
    source: int,
    target: int,
    avg_speed_kmh: float = DEFAULT_AVG_SPEED_KMH,
) -> PathResult:
    """Кратчайший путь Dijkstra между двумя узлами. Thread-safe (read-only граф)."""
    if source == target:
        coord = [G.nodes[source]["lon"], G.nodes[source]["lat"]]
        return PathResult(distance_km=0.0, time_minutes=0.0, nodes=[source], coords=[coord])

    try:
        distance_m = nx.dijkstra_path_length(G, source, target, weight="weight")
        path_nodes = nx.dijkstra_path(G, source, target, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return PathResult(distance_km=float("inf"), time_minutes=float("inf"), nodes=[], coords=[])

    distance_km = distance_m / 1000.0  # weight в метрах
    coords = [[G.nodes[n]["lon"], G.nodes[n]["lat"]] for n in path_nodes]
    time_minutes = (distance_km / avg_speed_kmh) * 60.0

    return PathResult(
        distance_km=round(distance_km, 3),
        time_minutes=round(time_minutes, 1),
        nodes=path_nodes,
        coords=coords,
    )


async def single_path_async(
    G: nx.DiGraph,
    source: int,
    target: int,
    avg_speed_kmh: float = DEFAULT_AVG_SPEED_KMH,
) -> PathResult:
    """Async обёртка — Dijkstra в thread pool, не блокирует event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_pool, single_path, G, source, target, avg_speed_kmh)


def _compute_row(args: tuple) -> tuple[int, list[float]]:
    """Dijkstra one-to-all для одной строки матрицы. Запускается в thread pool."""
    G, i, source, all_nodes = args
    try:
        lengths = nx.single_source_dijkstra_path_length(G, source, weight="weight")
    except nx.NodeNotFound:
        return i, [float("inf")] * len(all_nodes)
    return i, [lengths.get(n, float("inf")) / 1000.0 for n in all_nodes]  # м -> км


def build_cost_matrix(G: nx.DiGraph, node_list: list[int]) -> np.ndarray:
    """Матрица расстояний NxN (в км). Строки считаются параллельно в thread pool."""
    n = len(node_list)
    if n == 0:
        return np.empty((0, 0), dtype=np.float64)

    t0 = time.perf_counter()
    matrix = np.full((n, n), float("inf"), dtype=np.float64)
    np.fill_diagonal(matrix, 0.0)

    tasks = [(G, i, node_list[i], node_list) for i in range(n)]
    futures = [_pool.submit(_compute_row, t) for t in tasks]

    for f in futures:
        i, row = f.result()
        matrix[i] = row

    elapsed = time.perf_counter() - t0
    reachable = np.isfinite(matrix).sum() - n  # исключая диагональ
    total_pairs = n * n - n
    logger.info(
        "Cost matrix %dx%d: %.3fs, достижимых пар %d/%d (%.0f%%)",
        n, n, elapsed, reachable, total_pairs,
        (reachable / total_pairs * 100) if total_pairs > 0 else 0,
    )
    return matrix


async def build_cost_matrix_async(G: nx.DiGraph, node_list: list[int]) -> np.ndarray:
    """Async обёртка для build_cost_matrix."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, build_cost_matrix, G, node_list)


def distances_from_node(G: nx.DiGraph, source: int) -> dict[int, float]:
    """SSSP: расстояния от source до ВСЕХ узлов за один Dijkstra вызов (км).

    Один вызов ≈ 25мс вместо 10мс × N вызовов single_path.
    """
    try:
        lengths = nx.single_source_dijkstra_path_length(G, source, weight="weight")
    except nx.NodeNotFound:
        return {}
    return {n: d / 1000.0 for n, d in lengths.items()}


def _sssp_worker(args):
    """SSSP worker для thread pool."""
    G, source = args
    return source, distances_from_node(G, source)


def nearest_vehicle_distances(
    G: nx.DiGraph,
    vehicle_nodes: list[tuple[int, int]],
    target_nodes: list[int],
) -> dict[int, tuple[float, int]]:
    """Для каждого target_node найти ближайший vehicle. Параллельно через SSSP.

    vehicle_nodes: [(wialon_id, start_node), ...]
    target_nodes: [node_id, ...]
    Returns: {target_node: (distance_km, wialon_id)}
    """
    t0 = time.perf_counter()

    # SSSP от каждого target (обратный подход — меньше SSSP если targets < vehicles)
    # Но граф направленный, поэтому SSSP от vehicles
    # Оптимизация: SSSP от каждого vehicle параллельно в thread pool
    tasks = [(G, node) for _, node in vehicle_nodes]
    futures = [_pool.submit(_sssp_worker, t) for t in tasks]

    # vehicle_node -> {target_node: dist_km}
    vehicle_dists: list[tuple[int, dict]] = []
    for f, (wid, _) in zip(futures, vehicle_nodes):
        _, dists = f.result()
        vehicle_dists.append((wid, dists))

    # Для каждого target — найти min
    result = {}
    for tn in target_nodes:
        best_dist = float("inf")
        best_wid = -1
        for wid, dists in vehicle_dists:
            d = dists.get(tn, float("inf"))
            if d < best_dist:
                best_dist = d
                best_wid = wid
        result[tn] = (best_dist, best_wid)

    elapsed = time.perf_counter() - t0
    logger.info(
        "nearest_vehicle_distances: %d vehicles x %d targets в %.3fs",
        len(vehicle_nodes), len(target_nodes), elapsed,
    )
    return result


def sort_vehicles_by_distance(
    G: nx.DiGraph,
    vehicles,
    target_node: int,
) -> list[tuple[float, object]]:
    """Отсортировать технику по расстоянию до target. Один SSSP от target (reverse).

    vehicles: список объектов с атрибутом start_node (Vehicle, tuple, etc.)
    """
    t0 = time.perf_counter()

    G_rev = G.reverse(copy=False)
    try:
        lengths = nx.single_source_dijkstra_path_length(G_rev, target_node, weight="weight")
    except nx.NodeNotFound:
        return [(float("inf"), v) for v in vehicles]

    result = []
    for v in vehicles:
        node = v.start_node if hasattr(v, "start_node") else (v[1] if isinstance(v, tuple) else v)
        d = lengths.get(node, float("inf")) / 1000.0
        result.append((d, v))

    result.sort(key=lambda x: x[0])
    logger.debug("sort_vehicles: %d vehicles в %.3fs", len(vehicles), time.perf_counter() - t0)
    return result


def smoke_test(G: nx.DiGraph) -> None:
    """Smoke test кратчайших путей."""
    nodes = list(G.nodes)
    if len(nodes) < 2:
        logger.warning("Smoke test shortest_path: < 2 узлов, пропуск")
        return

    # Single path
    result = single_path(G, nodes[0], nodes[1])
    assert result.distance_km >= 0, f"Отрицательное расстояние: {result.distance_km}"
    if result.distance_km < float("inf"):
        assert len(result.nodes) >= 2, "Путь найден, но nodes < 2"
        assert len(result.coords) == len(result.nodes), "coords/nodes length mismatch"
        assert result.time_minutes > 0, "Нулевое время при ненулевом расстоянии"

    # Cost matrix 3x3
    test_nodes = nodes[:3]
    matrix = build_cost_matrix(G, test_nodes)
    assert matrix.shape == (3, 3), f"Матрица {matrix.shape}, ожидалось (3, 3)"
    for i in range(3):
        assert matrix[i][i] == 0.0, f"Диагональ [{i}][{i}] != 0"

    logger.info("Smoke test shortest_path: OK")
