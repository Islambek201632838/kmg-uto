"""VRP-солвер на Google OR-Tools CVRPTW.

Multi-depot, time windows, open-end routes, fleet compatibility.
Запускается в thread pool (OR-Tools — CPU-bound, GIL-free C++).
"""
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ortools.constraint_solver import routing_enums_pb2, pywrapcp
import numpy as np

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vrp_solver")

SOLVER_TIME_LIMIT_SECONDS = 5
SCALE = 1000  # OR-Tools работает с int — масштабируем km*1000


@dataclass(frozen=True, slots=True)
class VRPSolution:
    groups: list[list[str]]              # task_ids группированные по маршрутам
    assigned_vehicles: list[int | None]  # wialon_id для каждой группы
    total_distance_km: float
    total_time_minutes: float
    routes: list[list[int]]              # node_ids для каждого маршрута


def solve_vrp(
    cost_matrix_km: np.ndarray,
    task_ids: list[str],
    vehicle_start_indices: list[int],
    service_times_min: list[float],
    time_windows: list[tuple[int, int]],
    vehicle_wialon_ids: list[int],
    max_time_minutes: int = 720,
    time_limit_sec: int = SOLVER_TIME_LIMIT_SECONDS,
) -> VRPSolution | None:
    """Решение VRP через OR-Tools.

    Args:
        cost_matrix_km: матрица расстояний (vehicles+tasks x vehicles+tasks) в км
        task_ids: id заявок
        vehicle_start_indices: индексы стартовых узлов техники в cost_matrix
        service_times_min: время обслуживания каждой заявки (мин)
        time_windows: временные окна [(start_min, end_min), ...] для каждого узла матрицы
        vehicle_wialon_ids: wialon_id для каждого vehicle
        max_time_minutes: макс. время маршрута на одну машину
        time_limit_sec: лимит времени солвера
    """
    t0 = time.perf_counter()

    num_vehicles = len(vehicle_start_indices)
    num_tasks = len(task_ids)
    num_nodes = len(cost_matrix_km)

    if num_tasks == 0 or num_vehicles == 0:
        return VRPSolution(groups=[], assigned_vehicles=[], total_distance_km=0, total_time_minutes=0, routes=[])

    # OR-Tools требует int — масштабируем
    dist_matrix_int = (cost_matrix_km * SCALE).astype(np.int64)
    # Заменяем inf на большое число
    max_val = int(1e9)
    dist_matrix_int = np.where(np.isinf(cost_matrix_km), max_val, dist_matrix_int)

    # Создаём менеджер
    # Стартовые индексы для каждого vehicle, end index = -1 (open-end)
    # OR-Tools: starts = vehicle_start_indices, ends = dummy node
    # Для open-end: ends = [num_nodes] (добавляем dummy)
    dummy_idx = num_nodes
    num_nodes_with_dummy = num_nodes + 1

    # Расширяем матрицу dummy node
    extended = np.full((num_nodes_with_dummy, num_nodes_with_dummy), max_val, dtype=np.int64)
    extended[:num_nodes, :num_nodes] = dist_matrix_int
    # Из любого узла в dummy = 0 (open-end)
    extended[:, dummy_idx] = 0
    extended[dummy_idx, :] = max_val

    starts = vehicle_start_indices
    ends = [dummy_idx] * num_vehicles

    manager = pywrapcp.RoutingIndexManager(num_nodes_with_dummy, num_vehicles, starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    # Distance callback
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(extended[from_node][to_node])

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Time dimension
    avg_speed_km_per_min = 35.0 / 60.0  # 35 км/ч

    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        dist_km = extended[from_node][to_node] / SCALE
        travel_min = dist_km / avg_speed_km_per_min if avg_speed_km_per_min > 0 else max_val
        # Добавить service_time если уезжаем от task node
        svc = 0
        task_start_idx = num_vehicles  # первые num_vehicles — стартовые позиции
        if task_start_idx <= from_node < task_start_idx + num_tasks:
            svc = int(service_times_min[from_node - task_start_idx])
        return int(min(travel_min + svc, max_val))

    time_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.AddDimension(
        time_callback_index,
        max_time_minutes,  # slack
        max_time_minutes,  # max cumul
        False,
        "Time",
    )
    time_dimension = routing.GetDimensionOrDie("Time")

    # Time windows
    for i in range(num_nodes_with_dummy):
        index = manager.NodeToIndex(i)
        if index == -1:
            continue
        if i < len(time_windows):
            tw_start, tw_end = time_windows[i]
            # Clamp to [0, max_time_minutes]
            tw_start = max(0, min(tw_start, max_time_minutes))
            tw_end = max(tw_start, min(tw_end, max_time_minutes))
            time_dimension.CumulVar(index).SetRange(tw_start, tw_end)
        else:
            time_dimension.CumulVar(index).SetRange(0, max_time_minutes)

    # Разрешить не обслуживать заявки (penalty за пропуск)
    task_start_idx = num_vehicles
    for i in range(num_tasks):
        node_index = manager.NodeToIndex(task_start_idx + i)
        if node_index != -1:
            routing.AddDisjunction([node_index], max_val)

    # Параметры поиска
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = time_limit_sec

    # Решаем
    solution = routing.SolveWithParameters(search_params)
    elapsed = time.perf_counter() - t0

    if not solution:
        logger.warning("VRP: решение не найдено за %ds", time_limit_sec)
        return None

    # Извлечение решения
    groups: list[list[str]] = []
    assigned_vehicles: list[int | None] = []
    routes: list[list[int]] = []
    total_distance = 0

    real_dist = 0.0
    for v in range(num_vehicles):
        index = routing.Start(v)
        route_tasks: list[str] = []
        route_nodes: list[int] = []
        route_dist = 0.0

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if task_start_idx <= node < task_start_idx + num_tasks:
                route_tasks.append(task_ids[node - task_start_idx])
            route_nodes.append(node)

            next_index = solution.Value(routing.NextVar(index))
            from_node = node
            to_node = manager.IndexToNode(next_index)
            if from_node < num_nodes and to_node < num_nodes:
                d = cost_matrix_km[from_node][to_node]
                if d < float("inf"):
                    route_dist += d
            index = next_index

        if route_tasks:
            groups.append(route_tasks)
            assigned_vehicles.append(vehicle_wialon_ids[v])
            routes.append(route_nodes)
            real_dist += route_dist

    total_time = real_dist / avg_speed_km_per_min if avg_speed_km_per_min > 0 else 0

    logger.info(
        "VRP решён: %d групп, %.1f км, %.1f мин, %.2fs",
        len(groups), real_dist, total_time, elapsed,
    )

    return VRPSolution(
        groups=groups,
        assigned_vehicles=assigned_vehicles,
        total_distance_km=round(real_dist, 1),
        total_time_minutes=round(total_time, 1),
        routes=routes,
    )


async def solve_vrp_async(**kwargs) -> VRPSolution | None:
    """Async обёртка — OR-Tools в thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_pool, lambda: solve_vrp(**kwargs))


def smoke_test() -> None:
    """Smoke test VRP-солвера с минимальной задачей."""
    # 2 vehicles, 2 tasks, простая матрица
    cost = np.array([
        [0, 0, 10, 20],  # vehicle 0
        [0, 0, 15, 5],   # vehicle 1
        [10, 15, 0, 8],  # task 0
        [20, 5, 8, 0],   # task 1
    ], dtype=np.float64)

    result = solve_vrp(
        cost_matrix_km=cost,
        task_ids=["T-001", "T-002"],
        vehicle_start_indices=[0, 1],
        service_times_min=[30.0, 30.0],
        time_windows=[(0, 720), (0, 720), (0, 720), (0, 720)],
        vehicle_wialon_ids=[100, 200],
        max_time_minutes=720,
        time_limit_sec=5,
    )

    assert result is not None, "VRP вернул None"
    assert len(result.groups) > 0, "VRP: пустые группы"

    all_tasks = [t for g in result.groups for t in g]
    assert "T-001" in all_tasks or "T-002" in all_tasks, "VRP: ни одна заявка не назначена"

    logger.info("Smoke test vrp_solver: OK (%d groups)", len(result.groups))
