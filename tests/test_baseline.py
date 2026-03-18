"""Тест baseline-алгоритма и сравнение с VRP."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["USE_DB"] = "remote"

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

from app.services.graph_loader import load_graph
from app.services.spatial_index import SpatialIndex, load_wells, build_well_node_map
from app.services.fleet_state import load_fleet
from app.services.task_parser import load_tasks
from app.services.baseline import solve_baseline


async def main():
    G = await load_graph()
    index = SpatialIndex(G)
    wells = await load_wells()
    wnm = build_well_node_map(wells, index)
    fleet = await load_fleet(index)
    tasks = await load_tasks(wnm, csv_path="data/tasks_synthetic.csv")

    result = solve_baseline(G, fleet, tasks)

    print(f"\nBaseline: {len(result.assignments)} назначено, {len(result.unassigned)} не назначено")
    print(f"  Расстояние: {result.total_distance_km} км")
    print(f"  Время: {result.total_time_minutes} мин")
    print(f"\nНазначения:")
    for a in result.assignments[:10]:
        print(f"  {a.task_id}: {a.vehicle_name[:30]} -> {a.distance_km} км, {a.time_minutes} мин")
    if len(result.assignments) > 10:
        print(f"  ... и ещё {len(result.assignments) - 10}")


if __name__ == "__main__":
    asyncio.run(main())
