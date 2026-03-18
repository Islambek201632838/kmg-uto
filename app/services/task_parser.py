"""Парсер и генератор заявок.

Заявки по ТЗ предоставляются в CSV (или генерируются синтетически).
Каждая заявка привязывается к скважине -> узлу графа.
"""
import asyncio
import csv
import io
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="task_parser")

# SLA по ТЗ
PRIORITY_WEIGHTS = {"high": 0.55, "medium": 0.35, "low": 0.10}
PRIORITY_DEADLINE_HOURS = {"high": 2, "medium": 5, "low": 12}
SHIFTS = {
    "day": (8, 20),    # 08:00-20:00
    "night": (20, 8),  # 20:00-08:00 (следующего дня)
}


@dataclass(slots=True)
class Task:
    task_id: str
    priority: str           # high / medium / low
    destination_uwi: str
    planned_start: datetime
    duration_hours: float
    task_type: str          # код типа работы
    shift: str              # day / night
    target_node: int | None = None  # заполняется при привязке к графу

    @property
    def priority_weight(self) -> float:
        return PRIORITY_WEIGHTS.get(self.priority, 0.10)

    @property
    def deadline_hours(self) -> float:
        return PRIORITY_DEADLINE_HOURS.get(self.priority, 12)

    @property
    def service_time_minutes(self) -> float:
        return self.duration_hours * 60.0

    @property
    def time_window(self) -> tuple[int, int]:
        """Временное окно в минутах от начала дня."""
        start_h, end_h = SHIFTS.get(self.shift, (8, 20))
        if start_h < end_h:
            return start_h * 60, end_h * 60
        return start_h * 60, (24 + end_h) * 60


def parse_csv(csv_path: str | Path, well_node_map: dict[str, int]) -> list[Task]:
    """Загрузить заявки из CSV файла.

    Ожидаемые колонки:
    task_id, priority, destination_uwi, planned_start, duration_hours, task_type, shift
    """
    t0 = time.perf_counter()
    tasks = []
    path = Path(csv_path)

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            task = Task(
                task_id=row["task_id"],
                priority=row["priority"].lower(),
                destination_uwi=row["destination_uwi"],
                planned_start=datetime.fromisoformat(row["planned_start"]),
                duration_hours=float(row["duration_hours"]),
                task_type=row.get("task_type", ""),
                shift=row.get("shift", "day"),
                target_node=well_node_map.get(row["destination_uwi"]),
            )
            tasks.append(task)

    unlinked = sum(1 for t in tasks if t.target_node is None)
    logger.info(
        "CSV загружен: %d заявок, %d без привязки к графу, %.3fs",
        len(tasks), unlinked, time.perf_counter() - t0,
    )
    return tasks


def generate_synthetic_tasks(
    well_node_map: dict[str, int],
    count: int = 25,
    seed: int = 42,
) -> list[Task]:
    """Генерация синтетических заявок для демо/тестирования.

    По ТЗ: ~25-30 заявок, разные приоритеты и смены.
    """
    t0 = time.perf_counter()
    rng = random.Random(seed)

    # Скважины с привязкой к графу
    valid_uwis = [uwi for uwi, nid in well_node_map.items() if nid is not None]
    if not valid_uwis:
        logger.error("Нет скважин с привязкой к графу — генерация невозможна")
        return []

    priorities = ["high", "medium", "low"]
    priority_dist = [0.2, 0.5, 0.3]  # 20% high, 50% medium, 30% low
    shifts = ["day", "night"]
    shift_dist = [0.7, 0.3]

    # Примеры типов работ
    work_types = [
        "ТР-11", "103", "КР706", "ТР4-12", "ТР6-4", "СК5-2", "КР1105",
    ]

    base_date = datetime(2025, 2, 20, 8, 0, 0)
    tasks: list[Task] = []

    for i in range(count):
        priority = rng.choices(priorities, weights=priority_dist, k=1)[0]
        shift = rng.choices(shifts, weights=shift_dist, k=1)[0]
        uwi = rng.choice(valid_uwis)

        day_offset = rng.randint(0, 2)
        if shift == "day":
            hour = rng.randint(8, 18)
        else:
            hour = rng.choice([20, 21, 22, 23, 0, 1, 2, 3, 4, 5])

        planned_start = base_date + timedelta(days=day_offset, hours=hour - 8)

        task = Task(
            task_id=f"T-2025-{i + 1:04d}",
            priority=priority,
            destination_uwi=uwi,
            planned_start=planned_start,
            duration_hours=round(rng.uniform(1.0, 8.0), 1),
            task_type=rng.choice(work_types),
            shift=shift,
            target_node=well_node_map.get(uwi),
        )
        tasks.append(task)

    logger.info(
        "Синтетические заявки: %d шт, high=%d, medium=%d, low=%d, %.3fs",
        len(tasks),
        sum(1 for t in tasks if t.priority == "high"),
        sum(1 for t in tasks if t.priority == "medium"),
        sum(1 for t in tasks if t.priority == "low"),
        time.perf_counter() - t0,
    )
    return tasks


async def load_tasks(
    well_node_map: dict[str, int],
    csv_path: str | Path | None = None,
    count: int = 25,
) -> list[Task]:
    """Async загрузка заявок: из CSV если есть, иначе синтетические."""
    loop = asyncio.get_running_loop()
    if csv_path and Path(csv_path).exists():
        return await loop.run_in_executor(_pool, parse_csv, csv_path, well_node_map)
    return await loop.run_in_executor(_pool, generate_synthetic_tasks, well_node_map, count)


def save_tasks_csv(tasks: list[Task], path: str | Path) -> None:
    """Сохранить заявки в CSV (для воспроизводимости)."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "task_id", "priority", "destination_uwi", "planned_start",
            "duration_hours", "task_type", "shift",
        ])
        writer.writeheader()
        for t in tasks:
            writer.writerow({
                "task_id": t.task_id,
                "priority": t.priority,
                "destination_uwi": t.destination_uwi,
                "planned_start": t.planned_start.isoformat(),
                "duration_hours": t.duration_hours,
                "task_type": t.task_type,
                "shift": t.shift,
            })
    logger.info("Заявки сохранены: %s (%d шт)", path, len(tasks))


def smoke_test(tasks: list[Task]) -> None:
    """Smoke test заявок."""
    assert len(tasks) > 0, "Нет заявок"

    for t in tasks:
        assert t.priority in PRIORITY_WEIGHTS, f"Неизвестный приоритет: {t.priority}"
        assert t.duration_hours > 0, f"Нулевая длительность: {t.task_id}"
        assert t.destination_uwi, f"Пустой uwi: {t.task_id}"
        assert t.shift in SHIFTS, f"Неизвестная смена: {t.shift}"

    linked = sum(1 for t in tasks if t.target_node is not None)
    assert linked > 0, "Ни одна заявка не привязана к графу"

    logger.info(
        "Smoke test task_parser: OK (%d tasks, %d linked to graph)",
        len(tasks), linked,
    )
