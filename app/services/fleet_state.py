"""Состояние парка техники: позиции, тип, avg_speed, skills.

Загрузка из wialon_units_snapshot_3 (последний снапшот).
Тип техники извлекается из nm (BPA_Daewoo..., ОТК_КамАЗ...).
Совместимость: словарь dct.dictionaries TRS_VEHKIND / TRS_WTYPE.
"""
import asyncio
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from sqlalchemy import create_engine, text

from app.config import settings
from app.services.spatial_index import SpatialIndex

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fleet_state")

DEFAULT_AVG_SPEED_KMH = 35.0

# Известные модели техники для нормализации
_KNOWN_MODELS = [
    "Daewoo BH 120F", "Daewoo BH-120F",
    "Hyundai Universe", "Hyundai County", "Hyundai UniversE",
    "Toyota Coaster", "Toyota Haice",
    "YUTONG", "ShacmaN", "Паз", "ПАЗ",
]

# Регистрационный номер (3 цифры + 2 буквы + 12 или KZ + ...)
_PLATE_RE = re.compile(r"\s+(?:GDW\s+)?(?:KZ\s*)?[0-9]{2,3}\s*[A-ZА-ЯЁ]{2}\s*\d{2}$", re.IGNORECASE)


def _parse_vehicle_type(nm: str) -> str:
    """Извлечь тип/модель техники из nm.

    BPA_Daewoo BH 120F GDW 807JR12 -> Daewoo BH 120F
    ОТК_Hyundai Universe 228 ND 12 -> Hyundai Universe
    BPA_651 JY|12 YUTONG -> YUTONG
    """
    # Убрать префикс организации (BPA_, ОТК_)
    body = nm.split("_", 1)[1] if "_" in nm else nm

    # Попробовать найти известную модель
    for model in _KNOWN_MODELS:
        if model.lower() in body.lower():
            return model

    # Fallback: убрать номер с конца
    clean = _PLATE_RE.sub("", body).strip()
    # Убрать pipe-формат (651 JY|12)
    clean = re.sub(r"\d+\s*[A-Z]{2}\|?\d+\s*", "", clean).strip()
    return clean if clean else body


@dataclass(slots=True)
class Vehicle:
    wialon_id: int
    name: str
    vehicle_type: str
    pos_x: float  # lon
    pos_y: float  # lat
    pos_t: int     # unix timestamp последней позиции
    registration_plate: str
    start_node: int  # ближайший узел графа
    avg_speed_kmh: float = DEFAULT_AVG_SPEED_KMH
    free_at: float = 0.0  # время освобождения (мин от начала горизонта планирования)
    skills: list[str] = field(default_factory=list)  # совместимые типы работ


@dataclass(slots=True)
class FleetState:
    vehicles: dict[int, Vehicle]  # wialon_id -> Vehicle
    compatibility: dict[str, list[str]]  # vehicle_type -> [work_type_code, ...]

    def get_vehicle(self, wialon_id: int) -> Vehicle | None:
        return self.vehicles.get(wialon_id)

    def get_all(self) -> list[Vehicle]:
        return list(self.vehicles.values())

    def get_compatible(self, work_type: str) -> list[Vehicle]:
        """Техника, совместимая с типом работы."""
        return [
            v for v in self.vehicles.values()
            if not v.skills or work_type in v.skills
        ]

    @property
    def size(self) -> int:
        return len(self.vehicles)


def _load_fleet_sync(spatial_index: SpatialIndex) -> FleetState:
    """Синхронная загрузка парка техники и словаря совместимости."""
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    t0 = time.perf_counter()

    vehicles: dict[int, Vehicle] = {}

    with engine.connect() as conn:
        # Загрузка snapshot_3
        rows = conn.execute(text('''
            SELECT wialon_id, nm, pos_x, pos_y, pos_t, registration_plate
            FROM "references".wialon_units_snapshot_3
            WHERE pos_x IS NOT NULL AND pos_y IS NOT NULL
        ''')).fetchall()

        # Batch snap to node
        points = [(float(r[2]), float(r[3])) for r in rows]
        node_ids = spatial_index.snap_to_node_batch(points)

        for r, start_node in zip(rows, node_ids):
            wid = int(r[0])
            nm = r[1] or ""
            vehicles[wid] = Vehicle(
                wialon_id=wid,
                name=nm,
                vehicle_type=_parse_vehicle_type(nm),
                pos_x=float(r[2]),
                pos_y=float(r[3]),
                pos_t=int(r[4]) if r[4] else 0,
                registration_plate=r[5] or "",
                start_node=start_node,
            )

        # Расчёт avg_speed из снапшотов 1 и 3
        speed_rows = conn.execute(text('''
            SELECT s1.wialon_id, s1.pos_x, s1.pos_y, s1.pos_t,
                   s3.pos_x, s3.pos_y, s3.pos_t
            FROM "references".wialon_units_snapshot_1 s1
            JOIN "references".wialon_units_snapshot_3 s3 ON s1.wialon_id = s3.wialon_id
            WHERE s1.pos_x IS NOT NULL AND s3.pos_x IS NOT NULL
                  AND s1.pos_t IS NOT NULL AND s3.pos_t IS NOT NULL
                  AND s1.pos_t != s3.pos_t
        ''')).fetchall()

        import math
        speed_count = 0
        for sr in speed_rows:
            wid = int(sr[0])
            if wid not in vehicles:
                continue
            dx = float(sr[4]) - float(sr[1])
            dy = float(sr[5]) - float(sr[2])
            dist_km = math.sqrt(dx * dx + dy * dy) * 111.0  # градусы → км (грубо)
            dt_hours = abs(int(sr[6]) - int(sr[3])) / 3600.0
            if dt_hours > 0 and dist_km > 0.01:
                speed = dist_km / dt_hours
                # Снапшоты разнесены на недели — скорости очень малые
                # Используем формулу: реальная скорость ≈ dist / active_time
                # Предположим техника активна 8ч/сутки, остальное стоит
                active_ratio = 8.0 / 24.0
                adjusted_speed = speed / active_ratio if active_ratio > 0 else speed
                if 5.0 <= adjusted_speed <= 80.0:
                    vehicles[wid].avg_speed_kmh = round(adjusted_speed, 1)
                    speed_count += 1
                elif dist_km > 1.0:
                    # Если перемещение > 1 км, но скорость не в диапазоне — default
                    vehicles[wid].avg_speed_kmh = DEFAULT_AVG_SPEED_KMH
                    speed_count += 1

        logger.info("avg_speed рассчитан для %d/%d единиц из снапшотов", speed_count, len(vehicles))

        # Загрузка словаря совместимости
        # TRS_VEHKIND -> типы техники, TRS_WTYPE -> типы работ
        compatibility: dict[str, list[str]] = {}

        veh_kinds = conn.execute(text('''
            SELECT e.short_name, e.code
            FROM dct.elements e
            JOIN dct.dictionaries d ON e.dictionary_id = d.id
            WHERE d.code = 'TRS_VEHKIND' AND e.active = true
        ''')).fetchall()

        work_types = conn.execute(text('''
            SELECT e.short_name, e.code
            FROM dct.elements e
            JOIN dct.dictionaries d ON e.dictionary_id = d.id
            WHERE d.code = 'TRS_WTYPE' AND e.active = true
        ''')).fetchall()

        work_type_codes = [r[1] for r in work_types]

        # Пока нет явной таблицы связи техника↔работа,
        # считаем все типы техники совместимыми со всеми типами работ.
        # При появлении данных — заменить на реальную матрицу.
        for vk in veh_kinds:
            vk_name = vk[0].get("ru", "") if isinstance(vk[0], dict) else str(vk[0])
            compatibility[vk_name] = work_type_codes

        # Присвоить skills каждому vehicle (все work types по умолчанию)
        for v in vehicles.values():
            v.skills = work_type_codes

    engine.dispose()

    elapsed = time.perf_counter() - t0
    logger.info(
        "Fleet загружен: %d единиц, %d типов техники, %d типов работ за %.3fs",
        len(vehicles), len(compatibility), len(work_type_codes), elapsed,
    )

    return FleetState(vehicles=vehicles, compatibility=compatibility)


async def load_fleet(spatial_index: SpatialIndex) -> FleetState:
    """Async обёртка — загрузка в thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_pool, _load_fleet_sync, spatial_index)


def smoke_test(fleet: FleetState) -> None:
    """Smoke test парка техники."""
    assert fleet.size > 0, "Парк пустой"

    sample = next(iter(fleet.vehicles.values()))
    assert sample.wialon_id > 0, "wialon_id <= 0"
    assert sample.avg_speed_kmh > 0, f"avg_speed={sample.avg_speed_kmh} <= 0"
    assert sample.start_node >= 0, f"start_node={sample.start_node} < 0"
    assert sample.pos_x != 0 and sample.pos_y != 0, "Нулевые координаты"

    # Проверка vehicle_type парсинга
    types = {v.vehicle_type for v in fleet.vehicles.values()}
    assert len(types) > 0, "Не распарсен ни один тип техники"

    logger.info(
        "Smoke test fleet_state: OK (%d vehicles, %d types: %s)",
        fleet.size, len(types), ", ".join(sorted(types)[:5]) + "...",
    )
