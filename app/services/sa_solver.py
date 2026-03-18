"""Simulated Annealing солвер для VRP.

Альтернативный метод оптимизации для сравнения с OR-Tools CVRPTW.
Метаэвристика: случайные перестановки с вероятностью принятия ухудшений.
"""
import logging
import math
import random
import time
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SASolution:
    groups: list[list[str]]
    total_distance_km: float
    total_time_minutes: float
    iterations: int
    temperature_final: float


def solve_sa(
    cost_matrix_km: np.ndarray,
    task_ids: list[str],
    vehicle_start_indices: list[int],
    vehicle_wialon_ids: list[int],
    max_time_minutes: int = 720,
    initial_temp: float = 1000.0,
    cooling_rate: float = 0.9995,
    min_temp: float = 0.1,
    max_iterations: int = 100000,
    seed: int = 42,
) -> SASolution:
    """Simulated Annealing для задачи назначения заявок на технику.

    Решение: permutation assignment — каждой заявке назначается vehicle.
    Соседство: swap двух назначений или переназначение одной заявки.
    Целевая функция: суммарная дистанция vehicle → task.
    """
    t0 = time.perf_counter()
    rng = random.Random(seed)

    num_vehicles = len(vehicle_start_indices)
    num_tasks = len(task_ids)

    if num_tasks == 0 or num_vehicles == 0:
        return SASolution(groups=[], total_distance_km=0, total_time_minutes=0,
                          iterations=0, temperature_final=0)

    task_start = num_vehicles  # задачи в матрице после vehicles

    # Начальное решение: жадное назначение ближайшего vehicle
    assignment = []  # assignment[task_idx] = vehicle_idx
    for ti in range(num_tasks):
        task_node = task_start + ti
        best_v = 0
        best_d = float("inf")
        for vi in range(num_vehicles):
            d = cost_matrix_km[vehicle_start_indices[vi]][task_node]
            if d < best_d:
                best_d = d
                best_v = vi
        assignment.append(best_v)

    def total_cost(asgn: list[int]) -> float:
        """Суммарная дистанция: Σ dist(vehicle_i, task_i) + Σ dist(task_i, task_j) в группах."""
        cost = 0.0
        # Группируем задачи по vehicle
        groups: dict[int, list[int]] = {}
        for ti, vi in enumerate(asgn):
            groups.setdefault(vi, []).append(ti)

        for vi, task_indices in groups.items():
            v_node = vehicle_start_indices[vi]
            prev_node = v_node
            for ti in task_indices:
                t_node = task_start + ti
                d = cost_matrix_km[prev_node][t_node]
                if d < float("inf") and not np.isinf(d):
                    cost += d
                else:
                    cost += 500.0  # мягкий штраф за недостижимость
                prev_node = t_node
        return cost

    current_cost = total_cost(assignment)
    best_assignment = assignment[:]
    best_cost = current_cost
    temp = initial_temp
    iterations = 0

    for i in range(max_iterations):
        if temp < min_temp:
            break

        # Генерация соседа
        new_assignment = assignment[:]
        move = rng.random()

        if move < 0.5 and num_tasks >= 2:
            # Swap: поменять назначения двух задач
            a, b = rng.sample(range(num_tasks), 2)
            new_assignment[a], new_assignment[b] = new_assignment[b], new_assignment[a]
        else:
            # Reassign: переназначить одну задачу на другой vehicle
            ti = rng.randrange(num_tasks)
            new_vi = rng.randrange(num_vehicles)
            new_assignment[ti] = new_vi

        new_cost = total_cost(new_assignment)
        delta = new_cost - current_cost

        # Критерий Метрополиса
        if delta < 0 or rng.random() < math.exp(-delta / temp):
            assignment = new_assignment
            current_cost = new_cost

            if current_cost < best_cost:
                best_cost = current_cost
                best_assignment = assignment[:]

        temp *= cooling_rate
        iterations = i + 1

    # Собрать группы
    groups_map: dict[int, list[str]] = {}
    for ti, vi in enumerate(best_assignment):
        groups_map.setdefault(vi, []).append(task_ids[ti])

    groups = list(groups_map.values())
    avg_speed_km_per_min = 35.0 / 60.0
    total_time = best_cost / avg_speed_km_per_min if avg_speed_km_per_min > 0 else 0

    elapsed = time.perf_counter() - t0
    logger.info(
        "SA решён: %d групп, %.1f км, %d итераций, temp_final=%.4f, %.3fs",
        len(groups), best_cost, iterations, temp, elapsed,
    )

    return SASolution(
        groups=groups,
        total_distance_km=round(best_cost, 1),
        total_time_minutes=round(total_time, 1),
        iterations=iterations,
        temperature_final=round(temp, 6),
    )
