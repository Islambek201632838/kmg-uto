"""POST /api/recommendations — топ-3 единицы техники для заявки."""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Request

from app.schemas import RecommendationRequest, RecommendationResponse, UnitRecommendation
from app.services.shortest_path import single_path, DEFAULT_AVG_SPEED_KMH
from app.services.scorer import score_candidates
from app.services.llm_reason import enrich_reasons

logger = logging.getLogger(__name__)
router = APIRouter()

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="recommendations")

TOP_N = 3


def _compute_candidates(G, fleet, target_node, task_type, tw_start_min=0.0):
    """Синхронный расчёт расстояний от каждой единицы техники до цели. Thread pool."""
    candidates = []
    for v in fleet.get_all():
        path_result = single_path(G, v.start_node, target_node, v.avg_speed_kmh)
        compatible = not v.skills or task_type in v.skills

        # wait = max(0, tw_start - free_at - travel_time) из PPTX слайд 7
        travel_min = path_result.time_minutes if path_result.time_minutes < float("inf") else 0
        wait_min = max(0.0, tw_start_min - v.free_at - travel_min)
        eta_total = travel_min + wait_min  # ETA = travel + wait

        candidates.append({
            "wialon_id": v.wialon_id,
            "name": v.name,
            "distance_km": path_result.distance_km,
            "eta_minutes": eta_total,
            "wait_minutes": wait_min,
            "compatible": compatible,
        })
    return candidates


@router.post(
    "/recommendations",
    response_model=RecommendationResponse,
    summary="Рекомендация техники для заявки",
    description="""
Для указанной заявки находит **топ-3 оптимальных единицы техники** из парка.

**Алгоритм:**
1. Привязка скважины (`destination_uwi`) к ближайшему узлу графа дорог
2. Расчёт Dijkstra от каждой единицы техники до цели (параллельно в thread pool)
3. Скоринг кандидатов по формуле: `score = 1 - (0.30·D + 0.30·ETA + 0.15·wait + 0.25·SLA)`
4. Несовместимая техника исключается (жёсткое ограничение)
5. Возврат топ-3 с текстовым обоснованием (`reason`)

**SLA дедлайны:** high → +2 ч, medium → +5 ч, low → +12 ч
""",
)
async def recommendations(req: RecommendationRequest, request: Request):
    G = request.app.state.graph
    fleet = request.app.state.fleet
    well_node_map = request.app.state.well_node_map

    # Привязка скважины к узлу графа
    target_node = well_node_map.get(req.destination_uwi)
    if target_node is None:
        raise HTTPException(status_code=404, detail=f"Скважина {req.destination_uwi} не найдена")

    # Определяем task_type и tw_start из заявки
    task_type = ""
    tw_start_min = 0.0
    tasks_by_id = getattr(request.app.state, "tasks_by_id", {})
    if req.task_id in tasks_by_id:
        task = tasks_by_id[req.task_id]
        task_type = task.task_type
        tw_start_min = float(task.time_window[0])

    # Расчёт расстояний в thread pool (CPU-bound Dijkstra)
    loop = asyncio.get_running_loop()
    candidates = await loop.run_in_executor(
        _pool, _compute_candidates, G, fleet, target_node, task_type, tw_start_min,
    )

    # Скоринг
    scored = score_candidates(candidates, req.priority.value)

    # Топ-3
    top = scored[:TOP_N]

    # LLM reason (Gemini) — обогащаем топ кандидатов
    top_dicts = [
        {"name": s.name, "distance_km": s.distance_km, "eta_minutes": s.eta_minutes,
         "score": s.score, "wait_minutes": 0, "compatible": True}
        for s in top
    ]
    await enrich_reasons(top_dicts, req.priority.value)

    units = [
        UnitRecommendation(
            wialon_id=s.wialon_id,
            name=s.name,
            eta_minutes=s.eta_minutes,
            distance_km=s.distance_km,
            score=s.score,
            reason=td.get("llm_reason", s.reason),
        )
        for s, td in zip(top, top_dicts)
    ]

    logger.info(
        "Recommendations: task=%s uwi=%s priority=%s -> %d candidates, top=%s",
        req.task_id, req.destination_uwi, req.priority.value,
        len(scored), [u.wialon_id for u in units],
    )

    return RecommendationResponse(units=units)
