# ИС УТО — Интеллектуальная система маршрутизации спецтехники

Прототип системы оптимальной маршрутизации спецтехники на нефтяном месторождении Жетыбай.
Решает задачу **Vehicle Routing Problem (VRP)** с временными окнами, множеством депо и совместимостью техники.

## Что делает система

- Рекомендует оптимальную единицу техники для заявки (топ-3 с обоснованием)
- Строит маршруты по графу дорог месторождения (Dijkstra)
- Группирует заявки в multi-stop маршруты и считает экономию
- Сравнивает baseline (жадный) vs оптимизированный (OR-Tools VRP)
- Визуализирует маршруты и технику на карте

## Математическая модель

### Целевая функция

```
min Z = α·Σ(пробег) + β·Σ(wl·τl) + γ·Σ(простой)
```

- α, β, γ — настраиваемые веса компонент
- wl — вес приоритета: high=0.55, medium=0.35, low=0.10
- τl — опоздание (soft constraint → штраф)

### Ограничения

| # | Тип | Ограничение |
|---|-----|-------------|
| 1 | Hard | Каждая заявка назначена ровно одной машине |
| 2 | Hard | Техника совместима с типом работ |
| 3 | Hard | Маршрут строго по графу дорог |
| 4 | Hard | Open-end: техника остаётся на месте последней заявки |
| 5 | Hard | Начало работ не раньше прибытия техники |
| 6 | Soft | Временные окна (штраф за нарушение) |
| 7 | Soft | SLA дедлайн: high +2ч, medium +5ч, low +12ч |
| 8 | Soft | Multi-stop detour ≤ max_detour_ratio |

### Формула скоринга кандидата

```
score(vk, jl) = 1 - (ωd·D_norm + ωt·ETA_norm + ωw·wait_norm + ωp·penalty_SLA)
```

| Вес | Компонент | Значение |
|-----|-----------|----------|
| ωd | Расстояние | 0.30 |
| ωt | ETA | 0.30 |
| ωw | Время ожидания | 0.15 |
| ωp | Штраф SLA | 0.25 |

## Стек

| Компонент | Технология |
|-----------|------------|
| Backend | Python 3.11, FastAPI, Uvicorn |
| БД | PostgreSQL 17 |
| ORM / Миграции | SQLAlchemy 2.0 (async), Alembic |
| Граф дорог | networkx (DiGraph, 4624 узла, 38062 ребра) |
| Пространственный индекс | scipy.spatial.KDTree |
| VRP-солвер | Google OR-Tools (CVRPTW) |
| Метаэвристика | Simulated Annealing (для сравнения) |
| LLM | Gemini 2.0 Flash (обоснования на естественном языке) |
| Карта | Folium (3 слоя, fullscreen, линейка) |
| Фронтенд | Streamlit |
| Контейнеризация | Docker, Docker Compose |

## Быстрый старт

### Требования

- Docker и Docker Compose

### Запуск

```bash
# 1. Клонировать репозиторий
git clone <repo-url> && cd iso_uto

# 2. Создать .env из примера и заполнить пароли
cp .env.example .env
# отредактировать .env — задать DB_PASSWORD и REMOTE_DB_*

# 3. Поднять всё
docker compose up -d
```

После запуска автоматически:
- Поднимается PostgreSQL с нужными схемами (`references`, `dct`)
- Применяются миграции Alembic (8 таблиц, 23 индекса)
- Стартует FastAPI-бэкенд (lifespan загружает граф, KDTree, fleet, tasks)
- Стартует Streamlit-фронтенд

### Сервисы

| Сервис | URL | Описание |
|--------|-----|----------|
| API | http://localhost:8003 | FastAPI backend |
| API Docs | http://localhost:8003/docs | Swagger UI |
| UI | http://localhost:8503 | Streamlit + Folium карта |
| PostgreSQL | localhost:5434 | БД (для прямого подключения) |

### Проверка

```bash
curl http://localhost:8003/health
# {"status": "ok"}
```

## API

### POST /api/recommendations

Рекомендация топ-3 единиц техники для заявки с обоснованием.

```json
// Запрос
{
  "task_id": "T-2025-0001",
  "priority": "high",
  "destination_uwi": "JET_0944",
  "planned_start": "2025-02-20T08:00:00",
  "duration_hours": 4.5
}

// Ответ
{
  "units": [
    {
      "wialon_id": 28991328,
      "name": "BPA_Daewoo BH 120F GDW 807JR12",
      "eta_minutes": 251.5,
      "distance_km": 146.7,
      "score": 0.48,
      "reason": "на расстоянии 146.7 км, совместима по типу работ, ETA 4.2 ч, высокий приоритет"
    }
  ]
}
```

### POST /api/route

Маршрут между двумя точками по графу дорог. Возвращает координаты для polyline.

```json
// Запрос
{
  "from": {"wialon_id": 28991328, "lon": 59.18, "lat": 49.65},
  "to": {"uwi": "JET_0944", "lon": 55.19, "lat": 46.65}
}

// Ответ
{
  "distance_km": 225.3,
  "time_minutes": 386.2,
  "nodes": [3840, 3837, ...],
  "coords": [[56.99, 47.13], [56.98, 47.12], ...]
}
```

### POST /api/multitask

Группировка заявок в multi-stop маршруты с расчётом экономии относительно baseline.

```json
// Запрос
{
  "task_ids": ["T-2025-0001", "T-2025-0003", "T-2025-0004", "T-2025-0005"],
  "constraints": {
    "max_total_time_minutes": 720,
    "max_detour_ratio": 1.3
  }
}

// Ответ
{
  "groups": [["T-2025-0001", "T-2025-0005"], ["T-2025-0003"], ["T-2025-0004"]],
  "strategy_summary": "mixed",
  "total_distance_km": 457.5,
  "baseline_distance_km": 604.1,
  "savings_percent": 24.3,
  "reason": "заявки T-2025-0001, T-2025-0005 объединены в один маршрут; экономия 146.6 км (24.3%)"
}
```

### GET /api/compare

Сравнение baseline (жадный) vs VRP (оптимизированный) на всех заявках.

```json
// Ответ
{
  "baseline_km": 3623.9,
  "optimized_km": 759.7,
  "savings_percent": 79.0,
  "task_count": 25,
  "vrp_groups": [["T-2025-0013"], ["T-2025-0001", "T-2025-0005"], ...]
}
```

### GET /api/tasks

Список всех заявок с координатами скважин. Используется фронтендом для карты.

```json
// Ответ (фрагмент)
[
  {
    "task_id": "T-2025-0001",
    "priority": "medium",
    "destination_uwi": "JET_0944",
    "lon": 56.18893,
    "lat": 46.53764,
    "duration_hours": 2.0,
    "task_type": "ТР-11",
    "shift": "day"
  }
]
```

### GET /api/fleet

Парк техники (117 единиц) с GPS-координатами из Wialon.

```json
// Ответ (фрагмент)
[
  {
    "wialon_id": 28991328,
    "name": "BPA_Daewoo BH 120F GDW 807JR12",
    "vehicle_type": "Daewoo BH 120F",
    "lon": 59.177796,
    "lat": 49.645158
  }
]
```

## Архитектура

### Инициализация при старте (lifespan)

1. **Граф дорог** — `road_nodes` (4624) + `road_edges` (19031 → 38062 с обратными) → `networkx.DiGraph` в thread pool
2. **KDTree** — пространственный индекс по координатам узлов, `snap_to_node(lon, lat)` за O(log N)
3. **Скважины** — 3293 привязаны к ближайшим узлам графа (batch snap)
4. **Парк техники** — 117 единиц из `wialon_snapshot_3`, 9 типов, привязаны к узлам
5. **Заявки** — 25 синтетических из CSV (или генерация)
6. **Smoke tests** — проверка каждого сервиса

### Concurrency

| Задача | Метод | Почему |
|--------|-------|--------|
| Загрузка графа/данных | `ThreadPoolExecutor` + `run_in_executor` | I/O-bound, не блокирует event loop |
| Dijkstra (single path) | `ThreadPoolExecutor(8)` | CPU-bound, GIL-free в C-расширениях networkx |
| Cost matrix NxN | `ThreadPoolExecutor(8)`, параллельно по строкам | Каждая строка — независимый Dijkstra |
| VRP-солвер | `ThreadPoolExecutor(2)` | OR-Tools — C++ backend, GIL-free |
| API endpoints | `async def` | FastAPI async I/O |

### Данные

| Таблица | Схема | Записей |
|---------|-------|---------|
| road_nodes | references | 4,624 |
| road_edges | references | 19,031 (38,062 с обратными) |
| wells | references | 3,450 (3,293 с координатами) |
| wialon_snapshot_1/2/3 | references | 116/116/117 |
| dictionaries | dct | 17 |
| elements | dct | 35,794 |

## Структура проекта

```
.
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── requirements.txt
├── .env.example
├── ARCHITECTURE.md            # Архитектура и принципы
├── alembic/                   # Миграции БД
│   ├── env.py
│   └── versions/
├── data/
│   ├── init_schemas.sql       # Инициализация схем PostgreSQL
│   ├── mock_uto_backup.sql    # SQL-дамп с данными
│   └── tasks_synthetic.csv    # Синтетические заявки (25 шт)
├── app/
│   ├── main.py                # FastAPI + lifespan
│   ├── config.py              # Конфигурация (pydantic-settings)
│   ├── database.py            # Async SQLAlchemy engine
│   ├── models.py              # ORM-модели (Mapped columns)
│   ├── schemas.py             # Pydantic request/response
│   ├── api/
│   │   ├── recommendations.py # POST /api/recommendations
│   │   ├── route.py           # POST /api/route
│   │   ├── multitask.py       # POST /api/multitask
│   │   └── compare.py         # GET /api/compare
│   └── services/
│       ├── graph_loader.py    # networkx DiGraph из БД
│       ├── spatial_index.py   # KDTree, snap_to_node()
│       ├── shortest_path.py   # Dijkstra + cost matrix
│       ├── fleet_state.py     # Состояние парка техники
│       ├── scorer.py          # Формула скоринга (PPTX)
│       ├── vrp_solver.py      # OR-Tools CVRPTW
│       ├── sa_solver.py       # Simulated Annealing (сравнение)
│       ├── baseline.py        # Жадный baseline-алгоритм
│       ├── llm_reason.py      # Gemini 2.0 Flash для reason
│       └── task_parser.py     # Парсер/генератор заявок
├── tests/
│   ├── check_db.py            # Проверка подключения к БД
│   ├── test_graph.py          # Загрузка графа дорог
│   ├── test_spatial.py        # KDTree + snap_to_node
│   ├── test_shortest_path.py  # Dijkstra + cost matrix
│   ├── test_fleet.py          # Парк техники
│   ├── test_tasks.py          # Парсер заявок
│   ├── test_scorer.py         # Формула скоринга
│   ├── test_vrp.py            # VRP-солвер
│   ├── test_baseline.py       # Baseline-алгоритм
│   ├── test_routes.py         # Сценарии маршрутов (API)
│   └── test_api.py            # Интеграционные тесты API
└── streamlit_app.py           # UI: карта + sidebar
```

## Работа с миграциями

```bash
# Применить миграции (выполняется автоматически при docker compose up)
docker compose exec uto-api alembic upgrade head

# Создать новую миграцию после изменения models.py
docker compose exec uto-api alembic revision --autogenerate -m "описание"

# Откатить последнюю миграцию
docker compose exec uto-api alembic downgrade -1

# Посмотреть текущую версию
docker compose exec uto-api alembic current
```

## Тесты

### Unit-тесты сервисов (через .venv, remote БД)

```bash
.venv/bin/python tests/check_db.py           # Подключение к БД
.venv/bin/python tests/test_graph.py          # Граф: 4624 nodes, 38062 edges
.venv/bin/python tests/test_spatial.py        # KDTree + привязка 3293 скважин
.venv/bin/python tests/test_shortest_path.py  # Dijkstra + cost matrix 5x5
.venv/bin/python tests/test_fleet.py          # 117 единиц техники, 9 типов
.venv/bin/python tests/test_tasks.py          # 25 синтетических заявок
.venv/bin/python tests/test_scorer.py         # Скоринг кандидатов
.venv/bin/python tests/test_vrp.py            # OR-Tools VRP
.venv/bin/python tests/test_baseline.py       # Жадный baseline
```

### Интеграционные тесты API (docker compose должен быть запущен)

```bash
.venv/bin/python tests/test_api.py            # Все эндпоинты
.venv/bin/python tests/test_routes.py         # Сценарии маршрутов
```

## Переключение между БД

В `.env` переменная `USE_DB` управляет источником данных:

- `USE_DB=local` — локальный PostgreSQL в Docker (пустой, для миграций)
- `USE_DB=remote` — удалённая БД хакатона (readonly, данные графа/техники/скважин)

Миграции всегда применяются к локальной БД. Данные загружаются из БД, выбранной `USE_DB`.

## Результаты (на 25 синтетических заявках)

### Сравнение 3 алгоритмов

| Алгоритм | Расстояние | Экономия | Метод |
|----------|-----------|----------|-------|
| Baseline (жадный) | 3623.9 км | — | Ближайшая свободная техника |
| Simulated Annealing | 1178.7 км | **67.5%** | Метаэвристика, 18K итераций |
| VRP (OR-Tools) | 759.7 км | **79.0%** | CVRPTW солвер |

### Инновационные компоненты

**LLM для обоснований (Gemini 2.0 Flash):**
- Каждая рекомендация сопровождается обоснованием на естественном языке
- Gemini анализирует числовые параметры (расстояние, ETA, SLA, совместимость) и формулирует объяснение
- Fallback на шаблонный reason если API key не задан

**Simulated Annealing:**
- Альтернативный метод оптимизации для сравнения с OR-Tools
- 100K итераций, cooling schedule, swap/reassign соседство
- Показывает 67.5% экономии (vs 79.0% у OR-Tools) — подтверждает превосходство MILP-солвера
