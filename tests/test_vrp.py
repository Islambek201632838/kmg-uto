"""Тест VRP-солвера с реальными данными."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["USE_DB"] = "remote"

import numpy as np
from app.services.graph_loader import load_graph
from app.services.spatial_index import SpatialIndex, load_wells, build_well_node_map
from app.services.fleet_state import load_fleet
from app.services.task_parser import load_tasks
from app.services.shortest_path import build_cost_matrix
from app.services.vrp_solver import solve_vrp


async def main():
    G = await load_graph()
    index = SpatialIndex(G)
    wells = await load_wells()
    wnm = build_well_node_map(wells, index)
    fleet = await load_fleet(index)
    tasks = await load_tasks(wnm, csv_path="data/tasks_synthetic.csv")

    # Берём 4 заявки и 5 ближайших машин
    test_tasks = [t for t in tasks if t.target_node is not None][:4]
    vehicles = fleet.get_all()[:5]

    print(f"Tasks: {[t.task_id for t in test_tasks]}")
    print(f"Vehicles: {[v.wialon_id for v in vehicles]}")

    # Собираем узлы: [vehicle_starts..., task_targets...]
    all_nodes = [v.start_node for v in vehicles] + [t.target_node for t in test_tasks]
    matrix = build_cost_matrix(G, all_nodes)

    # Time windows (в минутах от начала дня)
    tws = [(0, 720)] * len(vehicles)  # vehicles — нет ограничений
    for t in test_tasks:
        tws.append(t.time_window)

    result = solve_vrp(
        cost_matrix_km=matrix,
        task_ids=[t.task_id for t in test_tasks],
        vehicle_start_indices=list(range(len(vehicles))),
        service_times_min=[t.service_time_minutes for t in test_tasks],
        time_windows=tws,
        vehicle_wialon_ids=[v.wialon_id for v in vehicles],
        max_time_minutes=720,
        time_limit_sec=10,
    )

    if result:
        print(f"\nРешение:")
        print(f"  Группы: {result.groups}")
        print(f"  Техника: {result.assigned_vehicles}")
        print(f"  Расстояние: {result.total_distance_km} км")
        print(f"  Время: {result.total_time_minutes} мин")
    else:
        print("Решение не найдено")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
    asyncio.run(main())
