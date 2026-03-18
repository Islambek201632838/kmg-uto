"""LLM-генерация reason через Gemini 2.0 Flash.

Берёт числовые параметры скоринга и генерирует объяснение на естественном языке.
Fallback на шаблонный reason если Gemini недоступен или API key не задан.
"""
import asyncio
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_model = None


def _init_model():
    """Ленивая инициализация Gemini модели."""
    global _model
    if _model is not None:
        return _model
    if not settings.GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY не задан — LLM reason отключён")
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        _model = genai.GenerativeModel("gemini-2.0-flash")
        logger.info("Gemini 2.0 Flash инициализирован")
        return _model
    except Exception as e:
        logger.warning("Не удалось инициализировать Gemini: %s", e)
        return None


def generate_reason_sync(
    vehicle_name: str,
    distance_km: float,
    eta_minutes: float,
    score: float,
    priority: str,
    wait_minutes: float = 0,
    compatible: bool = True,
    sla_penalty: float = 0,
) -> str | None:
    """Синхронная генерация reason через Gemini. Возвращает None при ошибке."""
    model = _init_model()
    if model is None:
        return None

    prompt = f"""Ты — диспетчер спецтехники на нефтяном месторождении.
Сформулируй краткое обоснование (1-2 предложения, на русском) почему выбрана эта техника для заявки.

Параметры:
- Техника: {vehicle_name}
- Расстояние: {distance_km:.1f} км
- ETA (время прибытия): {eta_minutes:.0f} мин
- Время ожидания: {wait_minutes:.0f} мин
- Приоритет заявки: {priority}
- Score (оценка): {score:.2f} из 1.00
- Совместима по типу работ: {"да" if compatible else "нет"}
- Превышение SLA: {sla_penalty * 100:.0f}%

Ответь одним абзацем, без заголовков. Укажи ключевые факторы выбора."""

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if len(text) > 300:
            text = text[:297] + "..."
        return text
    except Exception as e:
        logger.warning("Gemini error: %s", e)
        return None


async def generate_reason_async(
    vehicle_name: str,
    distance_km: float,
    eta_minutes: float,
    score: float,
    priority: str,
    wait_minutes: float = 0,
    compatible: bool = True,
    sla_penalty: float = 0,
) -> str | None:
    """Async обёртка для LLM reason."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, generate_reason_sync,
        vehicle_name, distance_km, eta_minutes, score,
        priority, wait_minutes, compatible, sla_penalty,
    )


async def enrich_reasons(candidates: list[dict], priority: str) -> list[dict]:
    """Обогатить топ-N кандидатов LLM-reason. Параллельно через asyncio.gather."""
    if not settings.GEMINI_API_KEY:
        return candidates

    tasks = []
    for c in candidates:
        tasks.append(generate_reason_async(
            vehicle_name=c.get("name", ""),
            distance_km=c.get("distance_km", 0),
            eta_minutes=c.get("eta_minutes", 0),
            score=c.get("score", 0),
            priority=priority,
            wait_minutes=c.get("wait_minutes", 0),
            compatible=c.get("compatible", True),
            sla_penalty=c.get("sla_penalty", 0),
        ))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for c, llm_reason in zip(candidates, results):
        if isinstance(llm_reason, str) and llm_reason:
            c["llm_reason"] = llm_reason

    return candidates
