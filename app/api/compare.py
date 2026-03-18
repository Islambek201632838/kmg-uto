"""GET /api/compare — сравнение baseline vs VRP на всех заявках."""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.services.baseline import solve_baseline, compare_with_vrp
from app.services.shortest_path import build_cost_matrix, sort_vehicles_by_distance
from app.services.vrp_solver import solve_vrp
from app.services.sa_solver import solve_sa

logger = logging.getLogger(__name__)
router = APIRouter()

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="compare")


class CompareResponse(BaseModel):
    baseline_km: float
    baseline_time_min: float
    optimized_km: float
    optimized_time_min: float
    savings_km: float
    savings_percent: float
    baseline_assignments: list[dict]
    vrp_groups: list[list[str]]
    sa_km: float
    sa_groups: list[list[str]]
    sa_iterations: int
    task_count: int


def _run_compare(G, fleet, tasks):
    # 1. Baseline (уже оптимизирован через SSSP внутри solve_baseline)
    baseline = solve_baseline(G, fleet, tasks)

    # 2. VRP
    valid_tasks = [t for t in tasks if t.target_node is not None]
    vehicles = fleet.get_all()
    max_v = min(len(vehicles), max(len(valid_tasks) * 2, 10))

    # Один SSSP через reverse graph вместо 117 отдельных single_path
    scored_v = sort_vehicles_by_distance(G, vehicles, valid_tasks[0].target_node)
    sel_vehicles = [v for _, v in scored_v[:max_v]]

    all_nodes = [v.start_node for v in sel_vehicles] + [t.target_node for t in valid_tasks]
    cost_matrix = build_cost_matrix(G, all_nodes)

    tws = [(0, 720)] * len(sel_vehicles)
    for t in valid_tasks:
        tw = t.time_window
        tws.append((min(tw[0], 720), min(tw[1], 720)))

    vrp_result = solve_vrp(
        cost_matrix_km=cost_matrix,
        task_ids=[t.task_id for t in valid_tasks],
        vehicle_start_indices=list(range(len(sel_vehicles))),
        service_times_min=[t.service_time_minutes for t in valid_tasks],
        time_windows=tws,
        vehicle_wialon_ids=[v.wialon_id for v in sel_vehicles],
        max_time_minutes=720,
        time_limit_sec=5,
    )

    vrp_km = vrp_result.total_distance_km if vrp_result else baseline.total_distance_km
    vrp_time = vrp_result.total_time_minutes if vrp_result else baseline.total_time_minutes
    vrp_groups = vrp_result.groups if vrp_result else [[t.task_id] for t in valid_tasks]

    # 3. Simulated Annealing (альтернативный подход)
    sa_result = solve_sa(
        cost_matrix_km=cost_matrix,
        task_ids=[t.task_id for t in valid_tasks],
        vehicle_start_indices=list(range(len(sel_vehicles))),
        vehicle_wialon_ids=[v.wialon_id for v in sel_vehicles],
        max_time_minutes=720,
    )

    comp = compare_with_vrp(baseline, vrp_km)

    return {
        "baseline_km": baseline.total_distance_km,
        "baseline_time_min": baseline.total_time_minutes,
        "optimized_km": comp["optimized_km"],
        "optimized_time_min": round(vrp_time, 1),
        "savings_km": comp["savings_km"],
        "savings_percent": comp["savings_percent"],
        "baseline_assignments": [
            {"task_id": a.task_id, "vehicle": a.vehicle_name, "distance_km": a.distance_km}
            for a in baseline.assignments
        ],
        "vrp_groups": vrp_groups,
        "sa_km": sa_result.total_distance_km,
        "sa_groups": sa_result.groups,
        "sa_iterations": sa_result.iterations,
        "task_count": len(valid_tasks),
    }


@router.get(
    "/compare",
    response_model=CompareResponse,
    summary="Сравнение: baseline vs VRP",
    description="""
Запускает **три алгоритма** на всех загруженных заявках и сравнивает результаты:

**Baseline (жадный):**
- Для каждой заявки — ближайшая свободная совместимая техника
- Порядок: high → medium → low
- Без глобальной оптимизации

**VRP (OR-Tools CVRPTW):**
- Глобальная оптимизация с временными окнами
- Multi-stop маршруты
- Open-end routes

**Simulated Annealing:**
- Метаэвристика с cooling schedule
- 50000 итераций, swap/reassign соседство
- Для сравнения с VRP-солвером

**Время выполнения:** 10-20 сек (зависит от количества заявок)
""",
)
async def compare(request: Request):
    G = request.app.state.graph
    fleet = request.app.state.fleet
    tasks = request.app.state.tasks

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_pool, _run_compare, G, fleet, tasks)

    logger.info(
        "Compare: baseline=%.1fkm, optimized=%.1fkm, savings=%.1f%%",
        result["baseline_km"], result["optimized_km"], result["savings_percent"],
    )

    return CompareResponse(**result)
