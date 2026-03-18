#!/bin/bash
set -e

wait_local_db() {
  echo "==> Ожидание локальной PostgreSQL..."
  until python -c "
import psycopg2
conn = psycopg2.connect(
    host='${DB_HOST}', port='${DB_PORT}',
    dbname='${DB_NAME}', user='${DB_USER}', password='${DB_PASSWORD}'
)
conn.close()
print('PostgreSQL готов')
" 2>/dev/null; do
    sleep 1
  done
}

run_migrations() {
  echo "==> Применение миграций (локальная БД)..."
  # Миграции всегда на локальную БД, независимо от USE_DB
  USE_DB=local alembic upgrade head
}

case "$1" in
  api)
    wait_local_db
    run_migrations

    echo "==> Запуск FastAPI на порту ${API_PORT:-8003}..."
    exec uvicorn app.main:app --host 0.0.0.0 --port "${API_PORT:-8003}"
    ;;

  streamlit)
    echo "==> Запуск Streamlit..."
    exec streamlit run streamlit_app.py \
      --server.port 8503 \
      --server.address 0.0.0.0 \
      --server.headless true \
      --browser.gatherUsageStats false
    ;;

  migrate)
    wait_local_db
    run_migrations
    echo "==> Миграции применены"
    ;;

  *)
    exec "$@"
    ;;
esac
