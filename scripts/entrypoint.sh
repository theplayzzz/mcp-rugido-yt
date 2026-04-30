#!/bin/sh
set -eu

# Espera o Postgres ficar disponível antes de aplicar migrations
wait_for_db() {
    python - <<'PY'
import os, time
import asyncio
import asyncpg

url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
async def ping():
    for i in range(60):
        try:
            conn = await asyncpg.connect(url)
            await conn.close()
            print("DB pronto")
            return
        except Exception as e:
            print(f"DB ainda não pronto ({e}); tentando de novo em 1s...", flush=True)
            await asyncio.sleep(1)
    raise SystemExit("Timeout esperando o Postgres")

asyncio.run(ping())
PY
}

case "${1:-serve}" in
    serve)
        wait_for_db
        echo ">> Aplicando migrations..."
        alembic upgrade head
        echo ">> Iniciando servidor..."
        exec mcp-rugido-yt
        ;;
    migrate)
        wait_for_db
        exec alembic upgrade head
        ;;
    shell)
        exec python
        ;;
    *)
        exec "$@"
        ;;
esac
