"""Наивный baseline-алгоритм: жадное назначение ближайшей свободной техники.

Оптимизирован: SSSP от target (reverse graph) вместо 117 single_path на каждую заявку.
"""
import logging
import time
from dataclasses import dataclass

import networkx as nx

from app.services.fleet_state import FleetState, Vehicle
from app.services.task_parser import Task

logger = logging.getLogger(__name__)

DEFAULT_AVG_SPEED_KMH = 35.0


@dataclass(frozen=True, slots=True)
class BaselineAssignment:
    task_id: str
    wialon_id: int
    vehicle_name: str
    distance_km: float
    time_minutes: float


@dataclass(frozen=True, slots=True)
class BaselineResult:
    assignments: list[BaselineAssignment]
    total_distance_km: float
    total_time_minutes: float
    unassigned: list[str]


def solve_baseline(G, fleet: FleetState, tasks: list[Task]) -> BaselineResult:
    """Жадный baseline: для каждой заявки — ближайшая свободная техника.

    Оптимизация: один SSSP от target в reverse graph покрывает ВСЕ машины (~25мс vs 117×10мс).
    """
    t0 = time.perf_counter()

    priority_order = {"high": 0, "medium": 1, "low": 2}
    sorted_tasks = sorted(tasks, key=lambda t: priority_order.get(t.priority, 2))

    vehicle_positions: dict[int, int] = {v.wialon_id: v.start_node for v in fleet.get_all()}
    assigned_vehicles: set[int] = set()
    G_rev = G.reverse(copy=False)

    assignments: list[BaselineAssignment] = []
    unassigned: list[str] = []
    total_dist = 0.0
    total_time = 0.0

    for task in sorted_tasks:
        if task.target_node is None:
            unassigned.append(task.task_id)
            continue

        # Один SSSP от target в обратном графе = расстояния от всех узлов до target
        try:
            lengths_rev = nx.single_source_dijkstra_path_length(G_rev, task.target_node, weight="weight")
        except nx.NodeNotFound:
            unassigned.append(task.task_id)
            continue

        best_dist = float("inf")
        best_vehicle: Vehicle | None = None

        for v in fleet.get_all():
            if v.wialon_id in assigned_vehicles:
                continue
            if v.skills and task.task_type and task.task_type not in v.skills:
                continue

            current_node = vehicle_positions[v.wialon_id]
            d_m = lengths_rev.get(current_node, float("inf"))
            d_km = d_m / 1000.0

            if d_km < best_dist:
                best_dist = d_km
                best_vehicle = v

        if best_vehicle and best_dist < float("inf"):
            time_min = (best_dist / best_vehicle.avg_speed_kmh) * 60.0
            assignments.append(BaselineAssignment(
                task_id=task.task_id,
                wialon_id=best_vehicle.wialon_id,
                vehicle_name=best_vehicle.name,
                distance_km=round(best_dist, 1),
                time_minutes=round(time_min, 1),
            ))
            total_dist += best_dist
            total_time += time_min
            vehicle_positions[best_vehicle.wialon_id] = task.target_node
            assigned_vehicles.add(best_vehicle.wialon_id)
        else:
            unassigned.append(task.task_id)

    elapsed = time.perf_counter() - t0
    logger.info(
        "Baseline: %d назначено, %d не назначено, %.1f км, %.1f мин, %.3fs",
        len(assignments), len(unassigned), total_dist, total_time, elapsed,
    )

    return BaselineResult(
        assignments=assignments,
        total_distance_km=round(total_dist, 1),
        total_time_minutes=round(total_time, 1),
        unassigned=unassigned,
    )


def compare_with_vrp(baseline: BaselineResult, vrp_distance_km: float) -> dict:
    savings_km = baseline.total_distance_km - vrp_distance_km
    savings_pct = (savings_km / baseline.total_distance_km * 100.0) if baseline.total_distance_km > 0 else 0.0
    return {
        "baseline_km": baseline.total_distance_km,
        "optimized_km": round(vrp_distance_km, 1),
        "savings_km": round(savings_km, 1),
        "savings_percent": round(max(0, savings_pct), 1),
    }
