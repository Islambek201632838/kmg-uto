"""Тест загрузки парка техники."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["USE_DB"] = "remote"

from app.services.graph_loader import load_graph
from app.services.spatial_index import SpatialIndex
from app.services.fleet_state import load_fleet, smoke_test


async def main():
    G = await load_graph()
    index = SpatialIndex(G)

    fleet = await load_fleet(index)
    smoke_test(fleet)

    # Статистика
    types = {}
    for v in fleet.get_all():
        types[v.vehicle_type] = types.get(v.vehicle_type, 0) + 1

    print(f"\nПарк: {fleet.size} единиц")
    print(f"Типы техники ({len(types)}):")
    for t, cnt in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t}: {cnt}")

    # Пример
    sample = fleet.get_all()[0]
    print(f"\nПример: wialon_id={sample.wialon_id}")
    print(f"  name: {sample.name}")
    print(f"  type: {sample.vehicle_type}")
    print(f"  pos: ({sample.pos_x}, {sample.pos_y})")
    print(f"  start_node: {sample.start_node}")
    print(f"  speed: {sample.avg_speed_kmh} km/h")
    print(f"  skills: {len(sample.skills)} work types")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
    asyncio.run(main())
