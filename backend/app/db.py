"""asyncpg-Verbindungspool."""
import asyncpg
from . import config

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if not config.DATABASE_URL:
            raise RuntimeError("DATABASE_URL in der Konfiguration fehlt.")
        _pool = await asyncpg.create_pool(
            dsn=config.DATABASE_URL,
            min_size=config.DB_POOL_MIN,
            max_size=config.DB_POOL_MAX,
            command_timeout=30,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB-Pool nicht initialisiert")
    return _pool


async def apply_schema(schema_sql: str) -> None:
    """Schema idempotent anwenden (CREATE TABLE IF NOT EXISTS ...)."""
    async with pool().acquire() as conn:
        await conn.execute(schema_sql)
