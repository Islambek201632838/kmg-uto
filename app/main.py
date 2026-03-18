"""FastAPI приложение ИС УТО. Lifespan загружает все данные в память при старте."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.services import graph_loader, spatial_index, shortest_path, fleet_state, task_parser

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-5s  %(name)s  %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Инициализация ИС УТО ===")

    # 1. Граф дорог
    G = await graph_loader.load_graph()
    graph_loader.smoke_test(G)
    app.state.graph = G

    # 2. Пространственный индекс + привязка скважин
    index = spatial_index.SpatialIndex(G)
    app.state.spatial_index = index

    wells = await spatial_index.load_wells()
    well_node_map = spatial_index.build_well_node_map(wells, index)
    spatial_index.smoke_test(index, well_node_map)
    app.state.well_node_map = well_node_map
    app.state._wells_raw = wells  # для /api/tasks endpoint

    # 4. Парк техники
    fleet = await fleet_state.load_fleet(index)
    fleet_state.smoke_test(fleet)
    app.state.fleet = fleet

    # 5. Заявки (синтетические или из CSV)
    tasks = await task_parser.load_tasks(well_node_map, csv_path="data/tasks_synthetic.csv")
    task_parser.smoke_test(tasks)
    app.state.tasks = tasks
    app.state.tasks_by_id = {t.task_id: t for t in tasks}

    # 6. Smoke test кратчайших путей
    shortest_path.smoke_test(G)

    logger.info("=== Инициализация завершена ===")
    yield
    logger.info("=== Shutdown ===")


DESCRIPTION = """
## Интеллектуальная система маршрутизации спецтехники

Решает задачу **Vehicle Routing Problem (VRP)** на месторождении Жетыбай:
- **4 624** узла дорожного графа, **38 062** ребра (двусторонние)
- **117** единиц техники из Wialon GPS-мониторинга
- **3 293** скважины с привязкой к графу дорог

### Алгоритмы
- **Dijkstra** — кратчайшие пути по графу (networkx)
- **KDTree** — привязка координат к узлам за O(log N) (scipy)
- **OR-Tools CVRPTW** — оптимизация маршрутов с временными окнами
- **Скоринг** — формула из 4 компонент: расстояние, ETA, ожидание, SLA

### Формула скоринга
```
score = 1 - (0.30·D_norm + 0.30·ETA_norm + 0.15·wait_norm + 0.25·penalty_SLA)
```
"""

TAGS_METADATA = [
    {
        "name": "Рекомендации",
        "description": "Подбор оптимальной техники для заявки. Возвращает **топ-3** с обоснованием.",
    },
    {
        "name": "Маршруты",
        "description": "Построение маршрута между двумя точками по **графу дорог** месторождения.",
    },
    {
        "name": "Мультизадачность",
        "description": "Группировка заявок в **multi-stop** маршруты. Расчёт экономии по сравнению с раздельным обслуживанием.",
    },
    {
        "name": "Сравнение",
        "description": "Сравнение **baseline** (жадный алгоритм) vs **VRP** (OR-Tools) на всех заявках.",
    },
    {
        "name": "Данные",
        "description": "Справочные данные: заявки с координатами скважин, парк техники с GPS-позициями. Используется фронтендом.",
    },
    {
        "name": "Система",
        "description": "Проверка состояния системы.",
    },
]

app = FastAPI(
    title="ИС УТО — Маршрутизация спецтехники",
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=TAGS_METADATA,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Роутеры
from app.api import recommendations, route, multitask, compare  # noqa: E402

app.include_router(recommendations.router, prefix="/api", tags=["Рекомендации"])
app.include_router(route.router, prefix="/api", tags=["Маршруты"])
app.include_router(multitask.router, prefix="/api", tags=["Мультизадачность"])
app.include_router(compare.router, prefix="/api", tags=["Сравнение"])


@app.get("/health", tags=["Система"], summary="Проверка состояния")
async def health():
    """Возвращает `ok` если API запущен и все сервисы инициализированы."""
    return {"status": "ok"}


@app.get(
    "/api/tasks",
    tags=["Данные"],
    summary="Список заявок с координатами скважин",
    description="""
Возвращает все загруженные заявки с **координатами целевых скважин**.

Используется Streamlit UI для отображения маркеров на карте и заполнения форм.

**Данные для каждой заявки:**
- `task_id` — идентификатор
- `priority` — приоритет (high / medium / low)
- `destination_uwi` — UWI целевой скважины
- `lon`, `lat` — координаты скважины (может быть `null` если скважина без координат)
- `duration_hours` — планируемая длительность работ
- `task_type` — код типа работ
- `shift` — смена (day / night)
""",
)
async def get_tasks(request: Request):
    tasks = request.app.state.tasks
    wells_raw = getattr(request.app.state, "_wells_raw", [])
    well_coords = {w["uwi"]: (float(w["longitude"]), float(w["latitude"]))
                   for w in wells_raw if w["longitude"] is not None}
    return [
        {
            "task_id": t.task_id,
            "priority": t.priority,
            "destination_uwi": t.destination_uwi,
            "lon": well_coords.get(t.destination_uwi, (None, None))[0],
            "lat": well_coords.get(t.destination_uwi, (None, None))[1],
            "duration_hours": t.duration_hours,
            "task_type": t.task_type,
            "shift": t.shift,
        }
        for t in tasks
    ]


@app.get(
    "/api/fleet",
    tags=["Данные"],
    summary="Парк техники с координатами",
    description="""
Возвращает все **117 единиц техники** из последнего снапшота Wialon с текущими GPS-координатами.

Используется Streamlit UI для отображения техники на карте.

**Данные для каждой единицы:**
- `wialon_id` — ID в системе Wialon
- `name` — полное название (организация + модель + номер)
- `vehicle_type` — распознанный тип техники (Hyundai Universe, Toyota Coaster и др.)
- `lon`, `lat` — последние GPS-координаты
""",
)
async def get_fleet(request: Request):
    fleet = request.app.state.fleet
    return [
        {
            "wialon_id": v.wialon_id,
            "name": v.name,
            "vehicle_type": v.vehicle_type,
            "lon": v.pos_x,
            "lat": v.pos_y,
        }
        for v in fleet.get_all()
    ]
