"""Тест всех API-эндпоинтов через HTTP."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = "http://localhost:8003"


def test_health():
    r = httpx.get(f"{BASE}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    print("[OK] GET /health")


def test_recommendations():
    r = httpx.post(f"{BASE}/api/recommendations", json={
        "task_id": "T-2025-0001",
        "priority": "high",
        "destination_uwi": "JET_0944",
        "planned_start": "2025-02-20T08:00:00",
        "duration_hours": 4.5,
    })
    assert r.status_code == 200
    d = r.json()
    assert "units" in d
    assert len(d["units"]) > 0
    u = d["units"][0]
    assert u["score"] > 0
    assert u["distance_km"] > 0
    assert u["reason"]
    print(f"[OK] POST /api/recommendations -> {len(d['units'])} units, top score={u['score']}")


def test_route():
    r = httpx.post(f"{BASE}/api/route", json={
        "from": {"lon": 55.19, "lat": 46.65},
        "to": {"lon": 55.20, "lat": 46.66},
    })
    assert r.status_code == 200
    d = r.json()
    assert d["distance_km"] > 0
    assert d["time_minutes"] > 0
    assert len(d["nodes"]) >= 2
    assert len(d["coords"]) == len(d["nodes"])
    print(f"[OK] POST /api/route -> {d['distance_km']} km, {len(d['nodes'])} nodes")


def test_multitask():
    r = httpx.post(f"{BASE}/api/multitask", json={
        "task_ids": ["T-2025-0001", "T-2025-0003", "T-2025-0005"],
        "constraints": {"max_total_time_minutes": 720, "max_detour_ratio": 1.3},
    }, timeout=60)
    assert r.status_code == 200
    d = r.json()
    assert "groups" in d
    assert d["baseline_distance_km"] > 0
    assert d["savings_percent"] >= 0
    print(f"[OK] POST /api/multitask -> {len(d['groups'])} groups, savings={d['savings_percent']}%")


def test_compare():
    r = httpx.get(f"{BASE}/api/compare", timeout=120)
    assert r.status_code == 200
    d = r.json()
    assert d["baseline_km"] > 0
    assert d["savings_percent"] >= 0
    print(f"[OK] GET /api/compare -> baseline={d['baseline_km']}km, optimized={d['optimized_km']}km, savings={d['savings_percent']}%")


if __name__ == "__main__":
    test_health()
    test_recommendations()
    test_route()
    test_multitask()
    test_compare()
    print("\n=== Все API-тесты пройдены ===")
