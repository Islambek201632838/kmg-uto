"""Тест скоринга кандидатов."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

from app.services.scorer import score_candidates, smoke_test

smoke_test()

# Разные приоритеты
candidates = [
    {"wialon_id": 1, "name": "Ближняя", "distance_km": 5.0, "eta_minutes": 15.0, "compatible": True},
    {"wialon_id": 2, "name": "Средняя", "distance_km": 15.0, "eta_minutes": 40.0, "compatible": True},
    {"wialon_id": 3, "name": "Далёкая", "distance_km": 30.0, "eta_minutes": 80.0, "compatible": True},
    {"wialon_id": 4, "name": "Несовместимая", "distance_km": 3.0, "eta_minutes": 8.0, "compatible": False},
]

for p in ["high", "medium", "low"]:
    result = score_candidates(candidates, p)
    print(f"\nPriority={p}:")
    for r in result:
        print(f"  #{r.wialon_id} {r.name:15s} score={r.score:.2f} | {r.reason}")
