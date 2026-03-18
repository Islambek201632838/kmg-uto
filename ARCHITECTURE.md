# ИС УТО — Архитектура и принципы разработки

## Проект

Хакатон KMG: интеллектуальная маршрутизация спецтехники на нефтяных месторождениях.
VRP (Vehicle Routing Problem) с time windows, multi-depot, open-end routes, fleet compatibility.

## Стек

Python 3.11, FastAPI, PostgreSQL 17, SQLAlchemy 2.0 (async), Alembic, networkx, scipy.KDTree, Google OR-Tools CVRPTW, Folium, Streamlit, Docker Compose.

## Принципы кода

### 1. ACID

- Все операции с БД через `async with session.begin()` — автоматический commit/rollback
- Никаких голых `session.commit()` — только транзакционные context managers
- Bulk-операции через `session.execute(insert(...).values(batch))` вместо поштучных INSERT
- При ошибке — полный rollback, логирование, reraise
- Read-only запросы: `session.execute(select(...))` без begin — autocommit read

```python
# Правильно
async with session.begin():
    session.add_all(objects)
# commit автоматический

# Неправильно
session.add(obj)
session.commit()  # нет гарантии rollback при ошибке
```

### 2. Async

- FastAPI endpoints — всегда `async def`
- БД: `AsyncSession` + `asyncpg` для всех рантайм-запросов
- CPU-bound задачи (Dijkstra, OR-Tools) — через `loop.run_in_executor()`
- Sync psycopg2 допускается только в Alembic миграциях и bulk-загрузке при старте
- `asyncio.gather()` для параллельных независимых I/O-задач

```python
# CPU-bound → thread/process pool
result = await loop.run_in_executor(executor, heavy_function, args)

# Параллельные I/O
results = await asyncio.gather(fetch_a(), fetch_b(), fetch_c())
```

### 3. Multithreading

- `ThreadPoolExecutor` для I/O-bound и лёгких CPU задач (Dijkstra single path)
- Именованные потоки: `thread_name_prefix="service_name"`
- Thread-safe структуры: `KDTree.query()`, `networkx.DiGraph` (read-only после загрузки)
- Не мутировать shared state из потоков — граф и KDTree иммутабельны после lifespan init

```python
_thread_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dijkstra")

async def compute():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_thread_pool, sync_func, arg)
```

### 4. Multiprocessing

- `ProcessPoolExecutor` для CPU-heavy batch-операций (cost matrix NxN, VRP solver)
- `max_tasks_per_child=50` для предотвращения memory leaks
- Данные в subprocess передавать сериализуемые (dict/list, не объекты SQLAlchemy)
- Для графа: сериализовать в `{nodes: [...], edges: [...]}` перед передачей

```python
_process_pool = ProcessPoolExecutor(max_workers=4, max_tasks_per_child=50)

def _worker(serialized_data):  # запускается в отдельном процессе
    # десериализация, вычисления, возврат результата
    return result
```

### 5. Smoke Tests

Каждый сервис должен иметь функцию `smoke_test()`, которая вызывается в lifespan после инициализации:

```python
def smoke_test(dependency) -> None:
    """Быстрая проверка работоспособности после загрузки."""
    assert condition, "Описание что сломалось"
    logger.info("Smoke test service_name: OK")
```

Что проверять:
- `graph_loader`: граф не пустой, атрибуты lon/lat/weight присутствуют, связность
- `spatial_index`: KDTree не пустой, snap точной координаты возвращает верный узел
- `shortest_path`: путь между двумя узлами существует, матрица 3x3 корректна
- `fleet_state`: парк не пустой, avg_speed > 0
- `scorer`: score в [0, 1], reason не пустой
- `vrp_solver`: решение для 2 заявок не падает

### 6. Easy Init

- `docker compose up -d` — единственная команда для запуска
- Миграции применяются автоматически при старте API контейнера
- healthcheck на postgres перед миграциями
- `.env.example` с описанием всех переменных
- Lifespan загружает всё в память при старте, потом отдаёт контроль

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Загрузить граф в thread pool
    # 2. Построить KDTree
    # 3. Загрузить fleet state
    # 4. Привязать скважины к узлам
    # 5. Smoke tests
    logger.info("Инициализация завершена")
    yield
    # cleanup pools
```

## Структура сервисов

```
app/services/
├── graph_loader.py     # networkx DiGraph из БД (thread pool bulk load)
├── spatial_index.py    # KDTree, snap_to_node() — thread-safe
├── shortest_path.py    # Dijkstra (threads) + cost matrix (processes)
├── fleet_state.py      # Парк техники: позиции, avg_speed, skills
├── scorer.py           # Формула скоринга + reason генерация
├── vrp_solver.py       # OR-Tools CVRPTW (process pool)
└── task_parser.py      # Парсинг заявок, time windows, SLA
```

## Паттерн сервиса

```python
"""Описание модуля."""
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=N, thread_name_prefix="name")

class ServiceName:
    __slots__ = (...)  # экономия памяти

    def __init__(self, dependency):
        # инициализация

    def method(self, args) -> Result:
        # бизнес-логика

async def load_service(deps) -> ServiceName:
    # async загрузка
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_pool, ServiceName, deps)

def smoke_test(service: ServiceName) -> None:
    assert ..., "описание"
    logger.info("Smoke test name: OK")
```

## Логирование

- `logging.getLogger(__name__)` в каждом модуле
- INFO: старт/финиш загрузки с таймингами
- WARNING: некритичные проблемы (несвязный граф, скважины без координат)
- ERROR: только при реальных сбоях
- Без print()

## Запрещено

- `session.commit()` вне context manager
- `time.sleep()` в async коде
- Мутация shared state после lifespan init
- Передача ORM-объектов между потоками/процессами
- `print()` вместо `logger`
- Хардкод credentials в коде
