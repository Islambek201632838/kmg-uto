"""Формула скоринга кандидатов + генерация reason.

Из PPTX формализации (слайд 7):
score(vk, jl) = 1 - (ωd·D_norm + ωt·ETA_norm + ωw·wait_norm + ωp·penalty_SLA)

ωd=0.30 (расстояние), ωt=0.30 (ETA), ωw=0.15 (простой/ожидание), ωp=0.25 (штраф SLA)

ETA = travel_time + wait
wait = max(0, tw_start - free_at - travel_time)
penalty_SLA = max(0, ETA - deadline) / deadline

Thread-safe, stateless.
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

WEIGHT_DISTANCE = 0.30
WEIGHT_ETA = 0.30
WEIGHT_WAIT = 0.15
WEIGHT_SLA_PENALTY = 0.25

# SLA дедлайны из ТЗ (минуты)
PRIORITY_DEADLINE_MINUTES = {"high": 120, "medium": 300, "low": 720}
PRIORITY_WEIGHTS = {"high": 0.55, "medium": 0.35, "low": 0.10}


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    wialon_id: int
    name: str
    distance_km: float
    eta_minutes: float
    score: float
    reason: str


def score_candidates(
    candidates: list[dict],
    priority: str,
) -> list[ScoredCandidate]:
    """Скоринг списка кандидатов для одной заявки.

    candidates: list of {
        wialon_id, name, distance_km, eta_minutes,
        compatible: bool,
        wait_minutes: float (опционально),
    }
    priority: high / medium / low

    Возвращает отсортированный список (лучший первый).
    Несовместимые исключаются (жёсткое ограничение из PPTX слайд 5).
    """
    if not candidates:
        return []

    # Жёсткое ограничение: только совместимые и достижимые
    eligible = [
        c for c in candidates
        if c["distance_km"] < float("inf") and c.get("compatible", True)
    ]
    if not eligible:
        return []

    deadline = PRIORITY_DEADLINE_MINUTES.get(priority, 720)

    # Нормализация по максимуму среди кандидатов
    max_dist = max(c["distance_km"] for c in eligible) or 1.0
    max_eta = max(c["eta_minutes"] for c in eligible) or 1.0
    max_wait = max(c.get("wait_minutes", 0.0) for c in eligible) or 1.0

    scored: list[ScoredCandidate] = []

    for c in eligible:
        dist_norm = c["distance_km"] / max_dist
        eta_norm = c["eta_minutes"] / max_eta
        wait = c.get("wait_minutes", 0.0)
        wait_norm = wait / max_wait if max_wait > 0 else 0.0

        # Штраф SLA: насколько ETA превышает дедлайн
        penalty_sla = max(0.0, c["eta_minutes"] - deadline) / deadline

        raw_score = 1.0 - (
            WEIGHT_DISTANCE * dist_norm
            + WEIGHT_ETA * eta_norm
            + WEIGHT_WAIT * wait_norm
            + WEIGHT_SLA_PENALTY * min(penalty_sla, 1.0)
        )
        score = round(min(max(raw_score, 0.0), 1.0), 2)

        reason = _build_reason(c, score, penalty_sla, priority)

        scored.append(ScoredCandidate(
            wialon_id=c["wialon_id"],
            name=c["name"],
            distance_km=round(c["distance_km"], 1),
            eta_minutes=round(c["eta_minutes"], 1),
            score=score,
            reason=reason,
        ))

    scored.sort(key=lambda s: -s.score)
    return scored


def _build_reason(
    candidate: dict,
    score: float,
    penalty_sla: float,
    priority: str,
) -> str:
    """Генерация текстового обоснования выбора."""
    parts: list[str] = []

    dist = candidate["distance_km"]
    eta = candidate["eta_minutes"]

    # Расстояние
    if dist < 5:
        parts.append(f"ближайшая ({dist:.1f} км)")
    elif dist < 20:
        parts.append(f"на расстоянии {dist:.1f} км")
    else:
        parts.append(f"далёкая ({dist:.1f} км)")

    # ETA
    if eta < 60:
        parts.append(f"ETA {eta:.0f} мин")
    else:
        parts.append(f"ETA {eta / 60:.1f} ч")

    # SLA
    if penalty_sla > 0:
        parts.append(f"превышение SLA на {penalty_sla * 100:.0f}%")
    else:
        parts.append("в рамках SLA")

    # Приоритет
    if priority == "high":
        parts.append("высокий приоритет")

    return ", ".join(parts)


def smoke_test() -> None:
    """Smoke test скоринга."""
    candidates = [
        {"wialon_id": 1, "name": "Test-1", "distance_km": 10.0, "eta_minutes": 20.0, "compatible": True},
        {"wialon_id": 2, "name": "Test-2", "distance_km": 25.0, "eta_minutes": 50.0, "compatible": True},
        {"wialon_id": 3, "name": "Test-3", "distance_km": 5.0, "eta_minutes": 10.0, "compatible": False},
    ]
    result = score_candidates(candidates, "high")

    # Test-3 исключён (несовместим — жёсткое ограничение)
    assert len(result) == 2, f"Ожидалось 2 кандидата (без несовместимого), получено {len(result)}"
    assert 0 <= result[0].score <= 1, f"Score вне [0, 1]: {result[0].score}"
    assert result[0].score >= result[1].score, "Не отсортировано по score"
    assert result[0].reason, "Пустой reason"
    assert result[0].wialon_id == 1, f"Лучший кандидат не Test-1: {result[0].wialon_id}"

    logger.info("Smoke test scorer: OK")
