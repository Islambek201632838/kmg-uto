from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --- Enums ---

class Priority(str, Enum):
    """Приоритет заявки. Влияет на SLA-дедлайн и вес штрафа."""
    high = "high"
    medium = "medium"
    low = "low"


class StrategyType(str, Enum):
    """Стратегия группировки заявок."""
    single_unit = "single_unit"
    mixed = "mixed"
    separate = "separate"


# --- /api/recommendations ---

class RecommendationRequest(BaseModel):
    """Запрос рекомендации техники для выполнения заявки."""
    task_id: str = Field(..., description="Идентификатор заявки", examples=["T-2025-0001"])
    priority: Priority = Field(..., description="Приоритет: high (дедлайн +2ч), medium (+5ч), low (+12ч)", examples=["high"])
    destination_uwi: str = Field(..., description="UWI скважины (точка назначения)", examples=["JET_0944"])
    planned_start: datetime = Field(..., description="Планируемое начало работ", examples=["2025-02-20T08:00:00"])
    duration_hours: float = Field(..., gt=0, description="Планируемая длительность работ (часы)", examples=[4.5])

    model_config = {"json_schema_extra": {
        "examples": [{
            "task_id": "T-2025-0001",
            "priority": "high",
            "destination_uwi": "JET_0944",
            "planned_start": "2025-02-20T08:00:00",
            "duration_hours": 4.5,
        }]
    }}


class UnitRecommendation(BaseModel):
    """Кандидат техники с оценкой и обоснованием."""
    wialon_id: int = Field(..., description="ID техники в Wialon")
    name: str = Field(..., description="Название техники")
    eta_minutes: float = Field(..., description="Расчётное время прибытия (мин)")
    distance_km: float = Field(..., description="Расстояние по графу дорог (км)")
    score: float = Field(..., ge=0, le=1, description="Оценка от 0 до 1 (1 = лучший)")
    reason: str = Field(..., description="Текстовое обоснование выбора")


class RecommendationResponse(BaseModel):
    """Топ-3 рекомендации техники для заявки."""
    units: list[UnitRecommendation] = Field(..., description="Отсортированный список кандидатов (лучший первый)")


# --- /api/route ---

class RoutePoint(BaseModel):
    """Точка маршрута — координаты + опциональные идентификаторы."""
    wialon_id: Optional[int] = Field(None, description="ID техники в Wialon (опционально)")
    uwi: Optional[str] = Field(None, description="UWI скважины (опционально)")
    lon: float = Field(..., description="Долгота")
    lat: float = Field(..., description="Широта")


class RouteRequest(BaseModel):
    """Запрос маршрута между двумя точками."""
    from_point: RoutePoint = Field(..., alias="from", description="Точка отправления")
    to_point: RoutePoint = Field(..., alias="to", description="Точка назначения")

    model_config = {"populate_by_name": True, "json_schema_extra": {
        "examples": [{
            "from": {"wialon_id": 28991328, "lon": 59.18, "lat": 49.65},
            "to": {"uwi": "JET_0944", "lon": 55.19, "lat": 46.65},
        }]
    }}


class RouteResponse(BaseModel):
    """Маршрут по графу дорог с координатами для отрисовки polyline."""
    distance_km: float = Field(..., description="Длина маршрута (км)")
    time_minutes: float = Field(..., description="Расчётное время в пути (мин)")
    nodes: list[int] = Field(..., description="Последовательность node_id графа")
    coords: list[list[float]] = Field(..., description="Координаты [[lon, lat], ...] для polyline")


# --- /api/multitask ---

class MultitaskConstraints(BaseModel):
    """Ограничения для группировки заявок."""
    max_total_time_minutes: int = Field(720, gt=0, description="Максимальное время маршрута (мин). По умолчанию 720 (12 ч смена)")
    max_detour_ratio: float = Field(1.3, gt=1.0, description="Допустимый крюк при объединении (1.3 = не более 30%)")


class MultitaskRequest(BaseModel):
    """Запрос группировки заявок в multi-stop маршруты."""
    task_ids: list[str] = Field(..., min_length=1, description="Список ID заявок для оптимизации")
    constraints: MultitaskConstraints = Field(default_factory=MultitaskConstraints, description="Ограничения")

    model_config = {"json_schema_extra": {
        "examples": [{
            "task_ids": ["T-2025-0001", "T-2025-0003", "T-2025-0004", "T-2025-0005"],
            "constraints": {"max_total_time_minutes": 720, "max_detour_ratio": 1.3},
        }]
    }}


class MultitaskResponse(BaseModel):
    """Результат оптимизации: группы заявок + экономия."""
    groups: list[list[str]] = Field(..., description="Группы заявок (каждая группа = один маршрут)")
    strategy_summary: StrategyType = Field(..., description="Стратегия: single_unit / mixed / separate")
    total_distance_km: float = Field(..., description="Суммарное расстояние оптимизированного плана (км)")
    total_time_minutes: float = Field(..., description="Суммарное время оптимизированного плана (мин)")
    baseline_distance_km: float = Field(..., description="Суммарное расстояние при раздельном обслуживании (км)")
    baseline_time_minutes: float = Field(..., description="Суммарное время при раздельном обслуживании (мин)")
    savings_percent: float = Field(..., description="Процент экономии расстояния")
    reason: str = Field(..., description="Текстовое обоснование группировки")
