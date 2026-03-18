"""Проверка подключения к БД и валидация моделей."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


async def check():
    async with engine.connect() as conn:
        # Проверка подключения
        row = await conn.execute(text("SELECT version()"))
        print(f"[OK] PostgreSQL: {row.scalar()[:60]}...")

        # Подсчёт записей в ключевых таблицах
        tables = [
            ("references", "road_nodes"),
            ("references", "road_edges"),
            ("references", "wells"),
            ("references", "wialon_units_snapshot_1"),
            ("references", "wialon_units_snapshot_2"),
            ("references", "wialon_units_snapshot_3"),
            ("dct", "dictionaries"),
            ("dct", "elements"),
        ]

        print("\n{:<45} {:>8}".format("Таблица", "Записей"))
        print("-" * 55)
        for schema, table in tables:
            result = await conn.execute(
                text(f'SELECT count(*) FROM "{schema}"."{table}"')
            )
            count = result.scalar()
            print(f"  {schema}.{table:<35} {count:>8}")

        # Пример данных из road_nodes
        print("\n--- road_nodes (первые 3) ---")
        rows = await conn.execute(
            text('SELECT node_id, lon, lat FROM "references".road_nodes LIMIT 3')
        )
        for r in rows:
            print(f"  node_id={r[0]}, lon={r[1]}, lat={r[2]}")

        # Пример данных из wialon_snapshot_3
        print("\n--- wialon_units_snapshot_3 (первые 3) ---")
        rows = await conn.execute(
            text('SELECT wialon_id, nm, pos_x, pos_y FROM "references".wialon_units_snapshot_3 LIMIT 3')
        )
        for r in rows:
            print(f"  wialon_id={r[0]}, nm={r[1]}, pos_x={r[2]}, pos_y={r[3]}")

        # Пример данных из wells
        print("\n--- wells (первые 3) ---")
        rows = await conn.execute(
            text('SELECT uwi, well_name, latitude, longitude FROM "references".wells WHERE latitude IS NOT NULL LIMIT 3')
        )
        for r in rows:
            print(f"  uwi={r[0]}, name={r[1]}, lat={r[2]}, lon={r[3]}")

        # Словари совместимости
        print("\n--- dct.dictionaries ---")
        rows = await conn.execute(
            text("SELECT id, code, name FROM dct.dictionaries WHERE active = true")
        )
        for r in rows:
            print(f"  id={r[0]}, code={r[1]}, name={r[2]}")

    await engine.dispose()
    print("\n[OK] Все проверки пройдены")


if __name__ == "__main__":
    asyncio.run(check())
