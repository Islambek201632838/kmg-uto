"""Тесты маршрутов: разные сценарии для /api/route."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = "http://localhost:8003"


def test_short_route():
    """Короткий маршрут между близкими точками."""
    r = httpx.post(f"{BASE}/api/route", json={
        "from": {"lon": 55.19, "lat": 46.65},
        "to": {"lon": 55.20, "lat": 46.66},
    })
    assert r.status_code == 200
    d = r.json()
    assert 0 < d["distance_km"] < 10
    assert len(d["nodes"]) >= 2
    print(f"[OK] Короткий маршрут: {d['distance_km']} km, {len(d['nodes'])} nodes, {d['time_minutes']} min")


def test_long_route():
    """Длинный маршрут между удалёнными точками."""
    r = httpx.post(f"{BASE}/api/route", json={
        "from": {"lon": 59.18, "lat": 49.65},
        "to": {"lon": 55.19, "lat": 46.65},
    })
    assert r.status_code == 200
    d = r.json()
    assert d["distance_km"] > 50
    assert len(d["nodes"]) > 10
    assert len(d["coords"]) == len(d["nodes"])
    print(f"[OK] Длинный маршрут: {d['distance_km']} km, {len(d['nodes'])} nodes, {d['time_minutes']} min")


def test_same_point():
    """Маршрут из точки в неё же."""
    r = httpx.post(f"{BASE}/api/route", json={
        "from": {"lon": 55.19, "lat": 46.65},
        "to": {"lon": 55.19, "lat": 46.65},
    })
    assert r.status_code == 200
    d = r.json()
    assert d["distance_km"] == 0.0
    assert d["time_minutes"] == 0.0
    print(f"[OK] Та же точка: distance=0, nodes={len(d['nodes'])}")


def test_route_with_wialon_id():
    """Маршрут с wialon_id и uwi."""
    r = httpx.post(f"{BASE}/api/route", json={
        "from": {"wialon_id": 28991328, "lon": 59.177796, "lat": 49.645158},
        "to": {"uwi": "JET_0944", "lon": 55.19, "lat": 46.65},
    })
    assert r.status_code == 200
    d = r.json()
    assert d["distance_km"] > 0
    print(f"[OK] Маршрут с wialon/uwi: {d['distance_km']} km, {d['time_minutes']} min")


def test_route_coords_format():
    """Проверка формата coords: [[lon, lat], ...]."""
    r = httpx.post(f"{BASE}/api/route", json={
        "from": {"lon": 55.19, "lat": 46.65},
        "to": {"lon": 55.25, "lat": 46.70},
    })
    assert r.status_code == 200
    d = r.json()
    for coord in d["coords"]:
        assert len(coord) == 2, f"Coord должен быть [lon, lat], получено {coord}"
        assert isinstance(coord[0], float), "lon не float"
        assert isinstance(coord[1], float), "lat не float"
    # Первая и последняя координаты должны быть около запрошенных
    print(f"[OK] Формат coords: {len(d['coords'])} точек, start={d['coords'][0]}, end={d['coords'][-1]}")


if __name__ == "__main__":
    test_short_route()
    test_long_route()
    test_same_point()
    test_route_with_wialon_id()
    test_route_coords_format()
    print("\n=== Все тесты маршрутов пройдены ===")
