"""Пространственный индекс KDTree и snap_to_node.

Thread-safe после инициализации. snap_to_node(lon, lat) -> node_id за O(log N).
Batch-привязка скважин к узлам графа при старте.
"""
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy.spatial import KDTree
import networkx as nx
from sqlalchemy import create_engine, text

from app.config import settings

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="spatial_index")


class SpatialIndex:
    """Thread-safe пространственный индекс на KDTree. Иммутабельный после __init__."""

    __slots__ = ("_tree", "_node_ids", "_coords")

    def __init__(self, G: nx.DiGraph):
        t0 = time.perf_counter()

        node_ids = []
        coords = []
        for nid, data in G.nodes(data=True):
            node_ids.append(nid)
            coords.append((data["lon"], data["lat"]))

        self._node_ids = np.array(node_ids, dtype=np.int64)
        self._coords = np.array(coords, dtype=np.float64)
        self._tree = KDTree(self._coords)

        logger.info("KDTree: %d точек за %.3fs", len(self._node_ids), time.perf_counter() - t0)

    def snap_to_node(self, lon: float, lat: float) -> int:
        """Ближайший узел графа к (lon, lat). Thread-safe."""
        _, idx = self._tree.query([lon, lat])
        return int(self._node_ids[idx])

    def snap_to_node_batch(self, points: list[tuple[float, float]]) -> list[int]:
        """Batch snap для N точек за один вызов KDTree. Thread-safe."""
        if not points:
            return []
        arr = np.array(points, dtype=np.float64)
        _, indices = self._tree.query(arr)
        return [int(self._node_ids[i]) for i in indices]

    @property
    def size(self) -> int:
        return len(self._node_ids)


def _load_wells_sync() -> list[dict]:
    """Bulk-загрузка скважин из БД (sync, thread pool)."""
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    with engine.connect() as conn:
        rows = conn.execute(
            text('SELECT uwi, longitude, latitude FROM "references".wells')
        ).fetchall()
    engine.dispose()
    return [{"uwi": r[0], "longitude": r[1], "latitude": r[2]} for r in rows]


async def load_wells() -> list[dict]:
    """Async загрузка скважин."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_pool, _load_wells_sync)


def build_well_node_map(wells: list[dict], index: SpatialIndex) -> dict[str, int]:
    """Привязка скважин к узлам графа: uwi -> node_id. Batch snap."""
    t0 = time.perf_counter()

    valid = [(w["uwi"], float(w["longitude"]), float(w["latitude"]))
             for w in wells if w["longitude"] is not None and w["latitude"] is not None]

    points = [(lon, lat) for _, lon, lat in valid]
    node_ids = index.snap_to_node_batch(points)

    mapping = {uwi: nid for (uwi, _, _), nid in zip(valid, node_ids)}

    skipped = len(wells) - len(valid)
    logger.info(
        "Привязка скважин: %d привязано, %d без координат, %.3fs",
        len(mapping), skipped, time.perf_counter() - t0,
    )
    return mapping


def smoke_test(index: SpatialIndex, well_node_map: dict[str, int]) -> None:
    """Smoke test пространственного индекса и привязки скважин."""
    assert index.size > 0, "KDTree пустой"

    # Точная координата узла должна вернуть этот узел
    test_lon, test_lat = index._coords[0]
    result = index.snap_to_node(float(test_lon), float(test_lat))
    assert result == int(index._node_ids[0]), "snap_to_node: неверный результат для точной координаты"

    # Batch
    pts = [(float(index._coords[i][0]), float(index._coords[i][1])) for i in range(min(5, index.size))]
    batch = index.snap_to_node_batch(pts)
    assert len(batch) == len(pts), "snap_to_node_batch: неверная длина"

    # Привязка скважин
    assert len(well_node_map) > 0, "well_node_map пустой"

    logger.info(
        "Smoke test spatial_index: OK (KDTree=%d, wells=%d)",
        index.size, len(well_node_map),
    )
