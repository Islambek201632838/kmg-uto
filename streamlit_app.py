"""ИС УТО — Streamlit UI с Folium-картой."""
import os

import folium
import httpx
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

API_URL = os.getenv("API_URL", "http://localhost:8003")
TIMEOUT = 120

GROUP_COLORS = ["green", "blue", "orange", "purple", "darkred", "cadetblue", "darkgreen", "pink"]

st.set_page_config(page_title="ИС УТО", page_icon="🚛", layout="wide")

# ── Session state init ───────────────────────────────────────────

for key in ("rec_result", "rec_route", "rec_task", "route_result",
            "multi_result", "compare_result"):
    if key not in st.session_state:
        st.session_state[key] = None


# ── Helpers ──────────────────────────────────────────────────────

def api_get(path: str) -> dict | None:
    try:
        r = httpx.get(f"{API_URL}{path}", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Ошибка API: {e}")
        return None


def api_post(path: str, data: dict) -> dict | None:
    try:
        r = httpx.post(f"{API_URL}{path}", json=data, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Ошибка API: {e}")
        return None


def create_base_map(center=None, zoom=10):
    if center is None:
        center = [46.65, 55.19]
    m = folium.Map(
        location=center,
        zoom_start=zoom,
        tiles=None,
        control_scale=True,
    )
    # Слои карт
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Спутник",
    ).add_to(m)
    folium.TileLayer(
        tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr="OpenTopoMap", name="Топо",
    ).add_to(m)
    # Fullscreen
    from folium.plugins import Fullscreen, MeasureControl
    Fullscreen(position="topleft", title="На весь экран", title_cancel="Свернуть").add_to(m)
    MeasureControl(position="bottomleft", primary_length_unit="kilometers").add_to(m)
    return m


def fit_map_bounds(m, all_coords):
    """Автоматический зум по всем точкам на карте."""
    if not all_coords:
        return
    lats = [c[0] for c in all_coords]
    lons = [c[1] for c in all_coords]
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]], padding=[30, 30])


def add_vehicle_marker(m, lon, lat, name, wialon_id, rank=None, **extra):
    parts = [f"<b>{name}</b>", f"ID: {wialon_id}"]
    if extra.get("distance_km"):
        parts.append(f"Расстояние: {extra['distance_km']} км")
    if extra.get("eta_minutes"):
        parts.append(f"ETA: {extra['eta_minutes']} мин")
    if extra.get("score"):
        parts.append(f"Score: {extra['score']}")
    # Цвет по рангу: 1=green, 2=orange, 3=gray
    colors = {1: "#2196F3", 2: "#FF9800", 3: "#9E9E9E"}
    color = colors.get(rank, "#2196F3")
    label = f"#{rank}" if rank else ""
    folium.CircleMarker(
        location=[lat, lon], radius=9 if rank == 1 else 7,
        color=color, fill=True, fill_color=color, fill_opacity=0.8,
        popup=folium.Popup("<br>".join(parts), max_width=280),
        tooltip=f"{label} {name}",
    ).add_to(m)
    if rank:
        folium.Marker(
            location=[lat, lon],
            icon=folium.DivIcon(html=f'<div style="font-size:11px;font-weight:bold;color:{color};text-align:center;margin-top:-22px">{label}</div>'),
        ).add_to(m)


def add_well_marker(m, lon, lat, uwi, color="red"):
    folium.CircleMarker(
        location=[lat, lon], radius=7,
        color=color, fill=True, fill_color=color, fill_opacity=0.8,
        popup=folium.Popup(f"<b>UWI:</b> {uwi}<br>({lat:.5f}, {lon:.5f})", max_width=220),
        tooltip=f"📍 {uwi}",
    ).add_to(m)


def add_route_line(m, coords, color="green", distance_km=0, time_minutes=0, weight=5):
    if not coords:
        return
    points = [[c[1], c[0]] for c in coords]
    tooltip = f"🛣️ {distance_km:.1f} км, ⏱️ {time_minutes:.0f} мин" if distance_km else ""
    # Тень
    folium.PolyLine(locations=points, color="black", weight=weight + 2, opacity=0.2).add_to(m)
    # Линия
    folium.PolyLine(locations=points, color=color, weight=weight, opacity=0.85, tooltip=tooltip).add_to(m)


def render_map(m, key="map"):
    """Рендер карты с LayerControl."""
    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, use_container_width=True, height=550, returned_objects=[], key=key)


# ── Данные заявок (загрузка с API) ────────────────────────────────

@st.cache_data(ttl=600)
def load_tasks_from_api():
    try:
        r = httpx.get(f"{API_URL}/api/tasks", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


@st.cache_data(ttl=600)
def load_fleet_from_api():
    try:
        r = httpx.get(f"{API_URL}/api/fleet", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


TASKS_API = load_tasks_from_api()
FLEET_API = load_fleet_from_api()

# Fallback если API недоступен
if TASKS_API:
    TASKS = [{"id": t["task_id"], "uwi": t["destination_uwi"], "priority": t["priority"],
              "lon": t.get("lon"), "lat": t.get("lat")} for t in TASKS_API]
else:
    TASKS = [{"id": f"T-2025-{i+1:04d}", "uwi": f"JET_{i:04d}", "priority": "medium",
              "lon": None, "lat": None} for i in range(25)]

TASK_OPTIONS = [f"{t['id']} — {t['uwi']} ({t['priority']})" for t in TASKS]
TASK_BY_ID = {t["id"]: t for t in TASKS}


# ── Sidebar ──────────────────────────────────────────────────────

st.sidebar.title("🚛 ИС УТО")
st.sidebar.markdown("Маршрутизация спецтехники")

mode = st.sidebar.radio(
    "Режим работы",
    ["📋 Рекомендации", "🗺️ Маршрут", "📦 Мультизадачность", "📊 Сравнение", "🎯 Демо-сценарии"],
)


# ══════════════════════════════════════════════════════════════════
# Режим 1: Рекомендации
# ══════════════════════════════════════════════════════════════════

if mode == "📋 Рекомендации":
    st.title("Рекомендации техники для заявки")

    with st.sidebar:
        st.subheader("Параметры заявки")
        sel_idx = st.selectbox("Выберите заявку", range(len(TASKS)), format_func=lambda i: TASK_OPTIONS[i])
        task = TASKS[sel_idx]
        priority = st.selectbox("Приоритет", ["high", "medium", "low"],
                                index=["high", "medium", "low"].index(task["priority"]))
        duration = st.slider("Длительность (часы)", 1.0, 12.0, 4.5, 0.5)

        if st.button("🔍 Найти технику", use_container_width=True, type="primary"):
            with st.spinner("Поиск оптимальной техники..."):
                st.session_state.rec_result = api_post("/api/recommendations", {
                    "task_id": task["id"], "priority": priority,
                    "destination_uwi": task["uwi"],
                    "planned_start": "2025-02-20T08:00:00", "duration_hours": duration,
                })
                st.session_state.rec_task = task
                # Маршрут от первого vehicle до скважины (реальные координаты)
                fleet_v = FLEET_API[0] if FLEET_API else {"lon": 59.18, "lat": 49.65}
                to_lon = task.get("lon") or 55.19
                to_lat = task.get("lat") or 46.65
                st.session_state.rec_route = api_post("/api/route", {
                    "from": {"lon": fleet_v["lon"], "lat": fleet_v["lat"]},
                    "to": {"uwi": task["uwi"], "lon": to_lon, "lat": to_lat},
                })

    result = st.session_state.rec_result
    route_data = st.session_state.rec_route
    rec_task = st.session_state.rec_task

    m = create_base_map()

    if result and result.get("units"):
        units = result["units"]
        best = units[0]

        col1, col2, col3 = st.columns(3)
        col1.metric("📏 Расстояние", f"{best['distance_km']:.1f} км")
        col2.metric("⏱️ ETA", f"{best['eta_minutes']:.0f} мин")
        col3.metric("⭐ Score", f"{best['score']:.2f}")

        all_points = []
        if route_data and route_data.get("coords"):
            coords = route_data["coords"]
            add_route_line(m, coords, "#2E7D32", route_data["distance_km"], route_data["time_minutes"])
            add_well_marker(m, coords[-1][0], coords[-1][1], rec_task["uwi"] if rec_task else "")
            all_points.append([coords[-1][1], coords[-1][0]])
            for i, u in enumerate(units):
                add_vehicle_marker(m, coords[0][0] + i * 0.008, coords[0][1] + i * 0.008,
                                   u["name"], u["wialon_id"], rank=i + 1,
                                   score=u["score"], distance_km=u["distance_km"], eta_minutes=u["eta_minutes"])
                all_points.append([coords[0][1] + i * 0.008, coords[0][0] + i * 0.008])
            for c in coords:
                all_points.append([c[1], c[0]])
        fit_map_bounds(m, all_points)

    else:
        st.markdown("Выберите заявку и нажмите **Найти технику**")

    render_map(m, key="rec_map")

    if result and result.get("units"):
        st.subheader("Топ-3 кандидата")
        for i, u in enumerate(result["units"]):
            with st.expander(f"#{i+1} — {u['name']} (score: {u['score']:.2f})", expanded=(i == 0)):
                c1, c2, c3 = st.columns(3)
                c1.metric("Расстояние", f"{u['distance_km']:.1f} км")
                c2.metric("ETA", f"{u['eta_minutes']:.0f} мин")
                c3.metric("Score", f"{u['score']:.2f}")
                st.info(f"💡 {u['reason']}")


# ══════════════════════════════════════════════════════════════════
# Режим 2: Маршрут
# ══════════════════════════════════════════════════════════════════

elif mode == "🗺️ Маршрут":
    st.title("Маршрут по графу дорог")

    with st.sidebar:
        st.subheader("Точка отправления")
        from_lon = st.number_input("Долгота (from)", value=55.19, format="%.5f", key="f_lon")
        from_lat = st.number_input("Широта (from)", value=46.65, format="%.5f", key="f_lat")
        st.subheader("Точка назначения")
        to_lon = st.number_input("Долгота (to)", value=55.25, format="%.5f", key="t_lon")
        to_lat = st.number_input("Широта (to)", value=46.70, format="%.5f", key="t_lat")

        if st.button("🗺️ Построить маршрут", use_container_width=True, type="primary"):
            with st.spinner("Расчёт маршрута..."):
                st.session_state.route_result = api_post("/api/route", {
                    "from": {"lon": from_lon, "lat": from_lat},
                    "to": {"lon": to_lon, "lat": to_lat},
                })

    result = st.session_state.route_result

    m = create_base_map()

    if result and result.get("coords"):
        col1, col2, col3 = st.columns(3)
        col1.metric("📏 Расстояние", f"{result['distance_km']:.1f} км")
        col2.metric("⏱️ Время", f"{result['time_minutes']:.0f} мин")
        col3.metric("📍 Узлов", len(result["nodes"]))

        coords = result["coords"]
        m = create_base_map()
        add_route_line(m, coords, "#2E7D32", result["distance_km"], result["time_minutes"])
        folium.Marker([coords[0][1], coords[0][0]], popup="Старт",
                      icon=folium.Icon(color="blue", icon="play", prefix="fa")).add_to(m)
        folium.Marker([coords[-1][1], coords[-1][0]], popup="Финиш",
                      icon=folium.Icon(color="red", icon="flag", prefix="fa")).add_to(m)
        fit_map_bounds(m, [[c[1], c[0]] for c in coords])
    else:
        st.markdown("Введите координаты и нажмите **Построить маршрут**")

    render_map(m, key="route_map")


# ══════════════════════════════════════════════════════════════════
# Режим 3: Мультизадачность
# ══════════════════════════════════════════════════════════════════

elif mode == "📦 Мультизадачность":
    st.title("Группировка заявок в multi-stop маршруты")

    with st.sidebar:
        st.subheader("Выберите заявки")
        selected = st.multiselect("Заявки (мин. 2)", TASK_OPTIONS, default=TASK_OPTIONS[:4])
        st.subheader("Ограничения")
        max_time = st.slider("Макс. время маршрута (мин)", 120, 720, 720, 60)
        max_detour = st.slider("Макс. крюк (ratio)", 1.0, 2.0, 1.3, 0.1)

        if st.button("📦 Оптимизировать", use_container_width=True, type="primary") and len(selected) >= 2:
            task_ids = [TASKS[TASK_OPTIONS.index(s)]["id"] for s in selected]
            with st.spinner(f"Оптимизация {len(task_ids)} заявок (OR-Tools VRP, ~15 сек)..."):
                st.session_state.multi_result = api_post("/api/multitask", {
                    "task_ids": task_ids,
                    "constraints": {"max_total_time_minutes": max_time, "max_detour_ratio": max_detour},
                })

    result = st.session_state.multi_result

    if result:
        col1, col2, col3 = st.columns(3)
        col1.metric("📏 Оптимизировано", f"{result['total_distance_km']:.1f} км")
        col2.metric("📏 Baseline", f"{result['baseline_distance_km']:.1f} км")
        savings = result["savings_percent"]
        col3.metric("💰 Экономия", f"{savings:.1f}%",
                    delta=f"-{result['baseline_distance_km'] - result['total_distance_km']:.1f} км")

        strategy_labels = {
            "single_unit": "🟢 Все заявки одной машиной",
            "mixed": "🟡 Частичное объединение",
            "separate": "🔴 Раздельное обслуживание",
        }
        st.info(f"**Стратегия:** {strategy_labels.get(result['strategy_summary'], result['strategy_summary'])}")
        st.success(f"💡 {result['reason']}")

        # Карта с реальными координатами скважин
        m = create_base_map()
        all_points = []

        for gi, group in enumerate(result["groups"]):
            color = GROUP_COLORS[gi % len(GROUP_COLORS)]
            group_coords = []

            for task_id in group:
                t = TASK_BY_ID.get(task_id)
                if t and t.get("lon") and t.get("lat"):
                    lon, lat = t["lon"], t["lat"]
                    add_well_marker(m, lon, lat, f"{task_id} ({t['uwi']})", color=color)
                    all_points.append([lat, lon])
                    group_coords.append((lon, lat))

            # Соединить точки в группе линией если multi-stop
            if len(group_coords) > 1:
                line_points = [[lat, lon] for lon, lat in group_coords]
                folium.PolyLine(
                    locations=line_points, color=color, weight=3,
                    opacity=0.6, dash_array="8",
                    tooltip=f"Группа {gi+1}: {len(group)} заявок",
                ).add_to(m)

            # Подпись группы (рядом с первой точкой группы)
            if group_coords:
                label_lon, label_lat = group_coords[0]
                folium.Marker(
                    location=[label_lat + 0.005, label_lon],
                    icon=folium.DivIcon(
                        html=f'<div style="font-size:12px;font-weight:bold;color:white;'
                             f'background:{color};padding:3px 8px;border-radius:10px;'
                             f'white-space:nowrap;text-align:center">'
                             f'Группа {gi+1} ({len(group)})</div>'),
                ).add_to(m)

        fit_map_bounds(m, all_points)
    else:
        m = create_base_map()
        st.markdown("Выберите заявки и нажмите **Оптимизировать**")

    render_map(m, key="multi_map")

    if result:
        st.subheader("Группы маршрутов")
        for gi, group in enumerate(result["groups"]):
            label = "multi-stop" if len(group) > 1 else "отдельно"
            st.markdown(f"**Группа {gi+1}** ({label}): {', '.join(group)}")


# ══════════════════════════════════════════════════════════════════
# Режим 4: Сравнение
# ══════════════════════════════════════════════════════════════════

elif mode == "📊 Сравнение":
    st.title("Baseline vs VRP — сравнение алгоритмов")

    with st.sidebar:
        st.info("Сравнение на всех 25 заявках. Время: 15-30 сек.")
        if st.button("📊 Запустить сравнение", use_container_width=True, type="primary"):
            with st.spinner("Выполняется сравнение (baseline + VRP)..."):
                st.session_state.compare_result = api_get("/api/compare")

    result = st.session_state.compare_result

    if result:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📋 Заявок", result["task_count"])
        col2.metric("📏 Baseline", f"{result['baseline_km']:.0f} км")
        col3.metric("📏 VRP", f"{result['optimized_km']:.0f} км")
        col4.metric("💰 Экономия", f"{result['savings_percent']:.1f}%",
                    delta=f"-{result['baseline_km'] - result['optimized_km']:.0f} км")

        st.subheader("Сравнение 3 алгоритмов")
        sa_km = result.get("sa_km", result["baseline_km"])
        df_compare = pd.DataFrame({
            "Алгоритм": ["Baseline (жадный)", "Simulated Annealing", "VRP (OR-Tools)"],
            "Расстояние (км)": [result["baseline_km"], sa_km, result["optimized_km"]],
        })
        st.bar_chart(df_compare.set_index("Алгоритм")["Расстояние (км)"])

        # Таблица сравнения
        sa_savings = ((result["baseline_km"] - sa_km) / result["baseline_km"] * 100) if result["baseline_km"] > 0 else 0
        st.dataframe(pd.DataFrame({
            "Алгоритм": ["Baseline (жадный)", "Simulated Annealing", "VRP (OR-Tools)"],
            "Расстояние (км)": [result["baseline_km"], sa_km, result["optimized_km"]],
            "Экономия (%)": [0, round(max(0, sa_savings), 1), result["savings_percent"]],
            "Метод": ["Ближайшая свободная", f"Метаэвристика ({result.get('sa_iterations', 0)} итер.)", "CVRPTW солвер"],
        }), use_container_width=True, hide_index=True)

        st.subheader("Baseline — назначения")
        if result.get("baseline_assignments"):
            st.dataframe(pd.DataFrame(result["baseline_assignments"]), use_container_width=True, hide_index=True)

        st.subheader("VRP — группировка")
        for gi, group in enumerate(result.get("vrp_groups", [])):
            label = "multi-stop" if len(group) > 1 else "отдельно"
            st.markdown(f"**Группа {gi+1}** ({label}): {', '.join(group)}")

        # Объяснение алгоритмов
        st.divider()
        st.subheader("Как работают алгоритмы")

        with st.expander("🔴 Baseline (жадный)", expanded=False):
            st.markdown("""
**Идея:** для каждой заявки берёт ближайшую свободную технику. Никакой оптимизации.

**Алгоритм:**
1. Отсортировать заявки по приоритету (high → medium → low)
2. Для каждой заявки: найти ближайшую совместимую свободную технику
3. Назначить, пометить как занятую

**Проблема:** каждая заявка решается отдельно. Не видит что 3 заявки рядом — выгоднее одной машиной.
Это как диспетчер назначает вручную — каждый раз "кто ближе".
            """)

        with st.expander("🟡 Simulated Annealing (отжиг)", expanded=False):
            st.markdown("""
**Идея:** случайно меняет назначения. Хорошие изменения — принимает. Плохие — иногда тоже,
чтобы не застрять в "локальном минимуме".

**Название** из металлургии: если металл остывает медленно — атомы находят оптимальное положение.

**Алгоритм (100 000 итераций):**
1. Начать с baseline-решения
2. Случайное изменение: поменять 2 назначения или переназначить 1 заявку
3. Если стало лучше → принять
4. Если хуже → принять с вероятностью P = e^(-Δ/T)
   - Высокая температура (начало) → принимает почти всё (исследует)
   - Низкая температура (конец) → принимает только улучшения (сходится)
5. Температура × 0.9995 каждую итерацию

**P = e^(-Δ/T)** — чем больше разница (Δ) и ниже температура (T), тем меньше шанс принять плохой ход.
            """)

        with st.expander("🟢 OR-Tools VRP (CVRPTW)", expanded=False):
            st.markdown("""
**Идея:** математический солвер от Google. Находит (почти) оптимальное назначение с учётом ВСЕХ ограничений.

**CVRPTW** = Capacitated Vehicle Routing Problem with Time Windows

**Работает в 2 фазы:**
1. **Начальное решение** (PATH_CHEAPEST_ARC): из каждой машины — к ближайшей непосещённой заявке
2. **Улучшение** (GUIDED_LOCAL_SEARCH, 5 сек): перестановки, перемещения, обмены между маршрутами

**Ограничения:**
- Каждая заявка = ровно 1 машина
- Time window: день 08:00–20:00, ночь 20:00–08:00
- Skills: техника совместима с типом работ
- Open-end: машина НЕ возвращается на базу
- SLA: high = +2ч дедлайн, medium = +5ч, low = +12ч

**Почему лучше:** видит ВСЕ заявки одновременно и оптимизирует глобально, а не по одной.
            """)

        with st.expander("📐 Формула скоринга", expanded=False):
            st.markdown("""
**Каждый кандидат (техника) получает score от 0 до 1:**

```
score = 1 − (0.30 × D_norm + 0.30 × ETA_norm + 0.15 × Wait_norm + 0.25 × SLA_penalty)
```

| Фактор | Вес | Что значит |
|--------|-----|-----------|
| D_norm | 30% | Расстояние по графу дорог (км), нормализовано |
| ETA_norm | 30% | Время прибытия (мин), нормализовано |
| Wait_norm | 15% | Время ожидания до начала time window |
| SLA_penalty | 25% | Штраф за опоздание: max(0, ETA − дедлайн) / дедлайн |

**SLA дедлайны по приоритету:** high = +2ч, medium = +5ч, low = +12ч

Чем ближе score к 1 — тем лучше техника для этой заявки.
            """)

    else:
        st.markdown("""
### Что сравнивается?

| | Baseline (жадный) | VRP (OR-Tools) |
|---|---|---|
| **Алгоритм** | Ближайшая свободная техника | CVRPTW глобальная оптимизация |
| **Multi-stop** | Нет | Да |
| **Приоритеты** | Порядок обработки | Штрафы в целевой функции |
| **Время** | Мгновенно | 15 сек (solver limit) |

Нажмите **"Запустить сравнение"** в sidebar.
        """)


# ══════════════════════════════════════════════════════════════════
# Режим 5: Демо-сценарии (ТЗ 10.2)
# ══════════════════════════════════════════════════════════════════

elif mode == "🎯 Демо-сценарии":
    st.title("Демо-сценарии для жюри")

    scenario = st.sidebar.radio("Сценарий", [
        "1. Срочная заявка (high)",
        "2. Baseline vs Оптимизация",
        "3. Многозадачность (multi-stop)",
    ])

    # ── Сценарий 1: Срочная заявка ──
    if scenario == "1. Срочная заявка (high)":
        st.subheader("Сценарий 1: Срочная заявка (high priority)")
        st.markdown("""
**Условие:** поступила срочная заявка с приоритетом `high` (дедлайн +2 часа).
Система должна выбрать оптимальную технику с обоснованием и показать маршрут.
        """)

        if "demo1" not in st.session_state:
            st.session_state.demo1 = None

        if st.sidebar.button("▶️ Запустить сценарий 1", use_container_width=True, type="primary"):
            high_task = next((t for t in TASKS if t["priority"] == "high"), TASKS[0])
            with st.spinner("Поиск техники для срочной заявки..."):
                st.session_state.demo1 = {
                    "rec": api_post("/api/recommendations", {
                        "task_id": high_task["id"], "priority": "high",
                        "destination_uwi": high_task["uwi"],
                        "planned_start": "2025-02-20T08:00:00", "duration_hours": 2.0,
                    }),
                    "task": high_task,
                }

        d1 = st.session_state.demo1
        if d1 and d1["rec"] and d1["rec"].get("units"):
            units = d1["rec"]["units"]
            best = units[0]
            task = d1["task"]

            col1, col2, col3 = st.columns(3)
            col1.metric("📏 Расстояние", f"{best['distance_km']:.1f} км")
            col2.metric("⏱️ ETA", f"{best['eta_minutes']:.0f} мин")
            col3.metric("⭐ Score", f"{best['score']:.2f}")

            st.success(f"**Лучший кандидат:** {best['name']}")
            st.info(f"💡 **Обоснование:** {best['reason']}")

            for i, u in enumerate(units):
                st.markdown(f"**#{i+1}** {u['name']} — {u['distance_km']:.1f} км, ETA {u['eta_minutes']:.0f} мин, score={u['score']:.2f}")

    # ── Сценарий 2: Baseline vs Оптимизация ──
    elif scenario == "2. Baseline vs Оптимизация":
        st.subheader("Сценарий 2: Baseline vs Оптимизированный алгоритм")
        st.markdown("""
**Условие:** сравниваем «просто ближайшая техника» (baseline) с оптимизированным
назначением через OR-Tools VRP. Визуализация разницы в километраже и времени.
        """)

        if "demo2" not in st.session_state:
            st.session_state.demo2 = None

        if st.sidebar.button("▶️ Запустить сценарий 2", use_container_width=True, type="primary"):
            with st.spinner("Сравнение baseline vs VRP (10-15 сек)..."):
                st.session_state.demo2 = api_get("/api/compare")

        d2 = st.session_state.demo2
        if d2:
            sa_km = d2.get("sa_km", d2["baseline_km"])
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("📏 Baseline", f"{d2['baseline_km']:.0f} км")
            col2.metric("📏 SA", f"{sa_km:.0f} км")
            col3.metric("📏 VRP", f"{d2['optimized_km']:.0f} км")
            col4.metric("💰 VRP экономия", f"{d2['savings_percent']:.1f}%",
                        delta=f"-{d2['savings_km']:.0f} км")

            st.bar_chart(pd.DataFrame({
                "Алгоритм": ["Baseline (жадный)", "Simulated Annealing", "VRP (OR-Tools)"],
                "Расстояние (км)": [d2["baseline_km"], sa_km, d2["optimized_km"]],
            }).set_index("Алгоритм")["Расстояние (км)"])

            st.markdown(f"**Заявок:** {d2['task_count']} | **Групп VRP:** {len(d2['vrp_groups'])}")

    # ── Сценарий 3: Многозадачность ──
    elif scenario == "3. Многозадачность (multi-stop)":
        st.subheader("Сценарий 3: Многозадачность — 1 машина vs 3 отдельных")
        st.markdown("""
**Условие:** 3 заявки в одном районе. Система определяет: выгоднее ли отправить
одну машину на все 3 точки, или обслуживать раздельно. Показывает экономию в км.
        """)

        if "demo3" not in st.session_state:
            st.session_state.demo3 = None

        if st.sidebar.button("▶️ Запустить сценарий 3", use_container_width=True, type="primary"):
            # Берём 3 заявки с близкими скважинами (JET_*)
            jet_tasks = [t for t in TASKS if t["uwi"].startswith("JET_")][:3]
            if len(jet_tasks) < 3:
                jet_tasks = TASKS[:3]
            task_ids = [t["id"] for t in jet_tasks]

            with st.spinner(f"Оптимизация {len(task_ids)} заявок..."):
                st.session_state.demo3 = {
                    "result": api_post("/api/multitask", {
                        "task_ids": task_ids,
                        "constraints": {"max_total_time_minutes": 720, "max_detour_ratio": 1.3},
                    }),
                    "task_ids": task_ids,
                }

        d3 = st.session_state.demo3
        if d3 and d3["result"]:
            r = d3["result"]
            col1, col2, col3 = st.columns(3)
            col1.metric("📏 Оптимизировано", f"{r['total_distance_km']:.1f} км")
            col2.metric("📏 Раздельно", f"{r['baseline_distance_km']:.1f} км")
            savings = r["savings_percent"]
            col3.metric("💰 Экономия", f"{savings:.1f}%",
                        delta=f"-{r['baseline_distance_km'] - r['total_distance_km']:.1f} км")

            strategy_labels = {
                "single_unit": "🟢 Одна машина на все заявки",
                "mixed": "🟡 Частичное объединение",
                "separate": "🔴 Раздельное обслуживание",
            }
            st.info(f"**Стратегия:** {strategy_labels.get(r['strategy_summary'], r['strategy_summary'])}")
            st.success(f"💡 {r['reason']}")

            st.markdown("**Группы:**")
            for gi, group in enumerate(r["groups"]):
                label = "multi-stop" if len(group) > 1 else "отдельно"
                st.markdown(f"  Группа {gi+1} ({label}): {', '.join(group)}")
