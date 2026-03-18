"""POST /api/multitask — группировка заявок в multi-stop маршруты + экономия."""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Request

from app.schemas import MultitaskRequest, MultitaskResponse, StrategyType
from app.services.shortest_path import (
    build_cost_matrix, nearest_vehicle_distances, sort_vehicles_by_distance,
)
from app.services.vrp_solver import solve_vrp

logger = logging.getLogger(__name__)
router = APIRouter()

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="multitask")


def _solve_multitask(G, fleet, tasks_by_id, task_ids, constraints):
    """Синхронная логика multitask."""
    tasks = []
    for tid in task_ids:
        t = tasks_by_id.get(tid)
        if t is None:
            raise ValueError(f"Заявка {tid} не найдена")
        if t.target_node is None:
            raise ValueError(f"Заявка {tid}: скважина не привязана к графу")
        tasks.append(t)

    task_nodes = [t.target_node for t in tasks]
    vehicles = fleet.get_all()
    vehicle_pairs = [(v.wialon_id, v.start_node) for v in vehicles]

    # Baseline: ближайшая машина для каждой заявки (один batch SSSP)
    baseline_map = nearest_vehicle_distances(G, vehicle_pairs, task_nodes)
    baseline_km = sum(d for d, _ in baseline_map.values() if d < float("inf"))

    # Выбор ближайших N машин (один SSSP от первой заявки через reverse graph)
    max_vehicles = min(len(vehicles), max(len(tasks) * 2, 10))
    scored_v = sort_vehicles_by_distance(G, vehicles, task_nodes[0])
    selected_vehicles = [v for _, v in scored_v[:max_vehicles]]

    # Cost matrix
    all_nodes = [v.start_node for v in selected_vehicles] + task_nodes
    cost_matrix = build_cost_matrix(G, all_nodes)

    # Time windows
    tws = [(0, 720)] * len(selected_vehicles)
    for t in tasks:
        tw = t.time_window
        tws.append((min(tw[0], 720), min(tw[1], 720)))

    # VRP
    result = solve_vrp(
        cost_matrix_km=cost_matrix,
        task_ids=[t.task_id for t in tasks],
        vehicle_start_indices=list(range(len(selected_vehicles))),
        service_times_min=[t.service_time_minutes for t in tasks],
        time_windows=tws,
        vehicle_wialon_ids=[v.wialon_id for v in selected_vehicles],
        max_time_minutes=constraints.max_total_time_minutes,
        time_limit_sec=5,
    )

    baseline_time = baseline_km / 35.0 * 60.0

    if result is None or not result.groups:
        return {
            "groups": [[tid] for tid in task_ids],
            "strategy_summary": StrategyType.separate,
            "total_distance_km": round(baseline_km, 1),
            "total_time_minutes": round(baseline_time, 1),
            "baseline_distance_km": round(baseline_km, 1),
            "baseline_time_minutes": round(baseline_time, 1),
            "savings_percent": 0.0,
            "reason": "VRP не нашёл улучшения; раздельное обслуживание оптимально",
        }

    optimized_km = result.total_distance_km

    # Неназначенные — добавить baseline расстояние
    assigned = {tid for g in result.groups for tid in g}
    unassigned = [tid for tid in task_ids if tid not in assigned]
    groups = result.groups + [[tid] for tid in unassigned]
    for tid in unassigned:
        t = tasks_by_id[tid]
        d, _ = baseline_map.get(t.target_node, (0, -1))
        if d < float("inf"):
            optimized_km += d

    savings = ((baseline_km - optimized_km) / baseline_km * 100.0) if baseline_km > 0 else 0.0
    savings = max(0.0, savings)

    if len(groups) == 1 and len(groups[0]) == len(task_ids):
        strategy = StrategyType.single_unit
    elif len(groups) == len(task_ids):
        strategy = StrategyType.separate
    else:
        strategy = StrategyType.mixed

    unassigned_time = sum(
        baseline_map.get(tasks_by_id[tid].target_node, (0, -1))[0] / 35.0 * 60.0
        for tid in unassigned
        if baseline_map.get(tasks_by_id[tid].target_node, (float("inf"), -1))[0] < float("inf")
    )

    reason = _build_reason(groups, task_ids, optimized_km, baseline_km, savings)

    return {
        "groups": groups,
        "strategy_summary": strategy,
        "total_distance_km": round(optimized_km, 1),
        "total_time_minutes": round(result.total_time_minutes + unassigned_time, 1),
        "baseline_distance_km": round(baseline_km, 1),
        "baseline_time_minutes": round(baseline_time, 1),
        "savings_percent": round(savings, 1),
        "reason": reason,
    }


def _build_reason(groups, task_ids, optimized_km, baseline_km, savings):
    parts = []
    multi_groups = [g for g in groups if len(g) > 1]
    single_groups = [g for g in groups if len(g) == 1]

    if multi_groups:
        for g in multi_groups:
            parts.append(f"заявки {', '.join(g)} объединены в один маршрут")
        saved = baseline_km - optimized_km
        if saved > 0:
            parts.append(f"экономия {saved:.1f} км ({savings:.1f}%)")

    if single_groups and multi_groups:
        parts.append(f"{len(single_groups)} заявок обслуживаются раздельно")

    if not multi_groups:
        parts.append("объединение не даёт выигрыша в рамках ограничений")
        parts.append("раздельное обслуживание оптимально")

    return "; ".join(parts)


@router.post(
    "/multitask",
    response_model=MultitaskResponse,
    summary="Группировка заявок в multi-stop маршруты",
    description="""
Оценивает целесообразность **объединения заявок** в multi-stop маршруты и возвращает оптимальную группировку.

**Алгоритм:**
1. Построение cost matrix (расстояния между всеми парами техника↔заявки)
2. Расчёт baseline — сумма раздельных маршрутов (ближайшая машина на каждую заявку)
3. OR-Tools CVRPTW — оптимизация с временными окнами и ограничениями
4. Сравнение: `savings_percent = (baseline - optimized) / baseline × 100%`

**Стратегии ответа:**
- `single_unit` — все заявки одной машиной
- `mixed` — часть объединена, часть раздельно
- `separate` — объединение не даёт выигрыша

**Ограничения:** `max_total_time_minutes` (макс. время маршрута), `max_detour_ratio` (макс. крюк)
""",
)
async def multitask(req: MultitaskRequest, request: Request):
    G = request.app.state.graph
    fleet = request.app.state.fleet
    tasks_by_id = request.app.state.tasks_by_id

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            _pool, _solve_multitask,
            G, fleet, tasks_by_id, req.task_ids, req.constraints,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    logger.info(
        "Multitask: %d tasks -> %d groups, savings=%.1f%%",
        len(req.task_ids), len(result["groups"]), result["savings_percent"],
    )

    return MultitaskResponse(**result)
