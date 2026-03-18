"""POST /api/route — маршрут между двумя точками по графу дорог."""
import logging

from fastapi import APIRouter, HTTPException, Request

from app.schemas import RouteRequest, RouteResponse
from app.services.shortest_path import single_path_async

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/route",
    response_model=RouteResponse,
    summary="Маршрут между двумя точками",
    description="""
Строит **кратчайший маршрут по графу дорог** месторождения между двумя точками.

**Алгоритм:**
1. Привязка координат `from` и `to` к ближайшим узлам графа (KDTree snap)
2. Поиск кратчайшего пути Dijkstra (weight = метры)
3. Извлечение координат каждого узла пути для отрисовки polyline

**Ответ содержит:**
- `distance_km` — длина маршрута в километрах
- `time_minutes` — расчётное время при средней скорости 35 км/ч
- `nodes` — последовательность node_id графа
- `coords` — массив `[[lon, lat], ...]` для отрисовки на карте
""",
)
async def route(req: RouteRequest, request: Request):
    G = request.app.state.graph
    index = request.app.state.spatial_index

    # snap to node
    source_node = index.snap_to_node(req.from_point.lon, req.from_point.lat)
    target_node = index.snap_to_node(req.to_point.lon, req.to_point.lat)

    if source_node == target_node:
        coord = [req.from_point.lon, req.from_point.lat]
        return RouteResponse(distance_km=0.0, time_minutes=0.0, nodes=[source_node], coords=[coord])

    # Dijkstra в thread pool
    result = await single_path_async(G, source_node, target_node)

    if result.distance_km == float("inf"):
        raise HTTPException(status_code=404, detail="Маршрут не найден: точки в разных компонентах графа")

    logger.info(
        "Route: %d -> %d, %.1f km, %.1f min, %d nodes",
        source_node, target_node, result.distance_km, result.time_minutes, len(result.nodes),
    )

    return RouteResponse(
        distance_km=result.distance_km,
        time_minutes=result.time_minutes,
        nodes=result.nodes,
        coords=result.coords,
    )
