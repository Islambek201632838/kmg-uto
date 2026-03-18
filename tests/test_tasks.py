"""Тест парсера заявок + генерация синтетических данных."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["USE_DB"] = "remote"

from app.services.graph_loader import load_graph
from app.services.spatial_index import SpatialIndex, load_wells, build_well_node_map
from app.services.task_parser import load_tasks, save_tasks_csv, smoke_test


async def main():
    G = await load_graph()
    index = SpatialIndex(G)
    wells = await load_wells()
    wnm = build_well_node_map(wells, index)

    # Генерация синтетических заявок
    tasks = await load_tasks(wnm, count=25)
    smoke_test(tasks)

    # Сохранить CSV
    save_tasks_csv(tasks, "data/tasks_synthetic.csv")

    # Статистика
    print(f"\nЗаявки: {len(tasks)}")
    for t in tasks[:5]:
        tw = t.time_window
        print(
            f"  {t.task_id}: priority={t.priority}, uwi={t.destination_uwi}, "
            f"node={t.target_node}, dur={t.duration_hours}h, "
            f"shift={t.shift}, window={tw[0]//60}:00-{tw[1]//60}:00, "
            f"type={t.task_type}"
        )
    print(f"  ... и ещё {len(tasks) - 5} заявок")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
    asyncio.run(main())
