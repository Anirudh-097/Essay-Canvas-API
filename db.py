"""PostgreSQL data-access layer for the Essay Learner API."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from psycopg import Connection
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row


PROJECT_ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = PROJECT_ROOT / "supabase" / "schema.sql"

_pool: ConnectionPool[Connection[Any]] | None = None
_pool_lock = threading.Lock()
_schema_initialized = False


def _get_pool() -> ConnectionPool[Connection[Any]]:
    """Create the process-wide pool lazily so /health stays dependency-light."""

    global _pool, _schema_initialized
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    conninfo=database_url,
                    # Supabase's transaction pooler does not preserve prepared
                    # statements between backend connections.
                    kwargs={"row_factory": dict_row, "prepare_threshold": None},
                    min_size=1,
                    max_size=int(os.getenv("DATABASE_POOL_MAX_SIZE", "5")),
                    timeout=10,
                    open=False,
                )
                _pool.open(wait=True)

    if not _schema_initialized:
        with _pool_lock:
            if not _schema_initialized:
                with _pool.connection() as connection:
                    with connection.transaction():
                        connection.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
                _schema_initialized = True

    return _pool


@contextmanager
def connect() -> Iterator[Connection[Any]]:
    """Borrow a pooled connection and commit or roll back the request."""

    with _get_pool().connection() as connection:
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def get_topics() -> list[dict[str, Any]]:
    with connect() as connection:
        return connection.execute(
            "SELECT id, topic, used, last_used FROM topics ORDER BY id"
        ).fetchall()


def get_topic(topic_id: int = 0) -> dict[str, Any] | None:
    with connect() as connection:
        return connection.execute(
            "SELECT id, topic, used, last_used FROM topics WHERE id = %s",
            (topic_id,),
        ).fetchone()


def get_random_practice_topic(
    exclude_topic_id: int | None = None,
) -> dict[str, Any] | None:
    with connect() as connection:
        if exclude_topic_id is None:
            return connection.execute(
                "SELECT id, topic, used, last_used FROM topics "
                "ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
        return connection.execute(
            "SELECT id, topic, used, last_used FROM topics "
            "WHERE id != %s ORDER BY RANDOM() LIMIT 1",
            (exclude_topic_id,),
        ).fetchone()


def get_or_assign_today() -> dict[str, Any] | None:
    """Return today's topic, assigning one atomically when necessary."""

    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)
    with connect() as connection:
        with connection.transaction():
            existing = connection.execute(
                """SELECT id, topic, used, last_used FROM topics
                   WHERE last_used::date = %s ORDER BY id LIMIT 1""",
                (today,),
            ).fetchone()
            if existing:
                return existing

            selected = connection.execute(
                """SELECT id, topic, used, last_used FROM topics
                   WHERE used = FALSE ORDER BY RANDOM() LIMIT 1
                   FOR UPDATE SKIP LOCKED"""
            ).fetchone()
            if selected is None:
                selected = connection.execute(
                    """SELECT id, topic, used, last_used FROM topics
                       ORDER BY last_used IS NOT NULL, last_used, RANDOM()
                       LIMIT 1 FOR UPDATE SKIP LOCKED"""
                ).fetchone()
            if selected is None:
                return None

            connection.execute(
                "UPDATE topics SET used = TRUE, last_used = %s WHERE id = %s",
                (now, selected["id"]),
            )
            return connection.execute(
                "SELECT id, topic, used, last_used FROM topics WHERE id = %s",
                (selected["id"],),
            ).fetchone()


def save_attempt(
    topic_id: int,
    paragraph_type: str,
    score: int,
    grammar: int,
    vocabulary: int,
    structure: int,
    argument_quality: int,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc)
    with connect() as connection:
        cursor = connection.execute(
            """INSERT INTO attempts
               (topic_id, paragraph_type, score, grammar, vocabulary, structure,
                argument_quality, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                topic_id,
                paragraph_type,
                score,
                grammar,
                vocabulary,
                structure,
                argument_quality,
                created_at,
            ),
        )
        return connection.execute(
            """SELECT id, topic_id, paragraph_type, score, grammar, vocabulary,
                      structure, argument_quality, created_at
               FROM attempts WHERE id = %s""",
            (cursor.fetchone()["id"],),
        ).fetchone()


def get_progress() -> list[dict[str, Any]]:
    with connect() as connection:
        return connection.execute(
            """SELECT id, topic_id, paragraph_type, score, grammar, vocabulary,
                      structure, argument_quality, created_at
               FROM attempts ORDER BY created_at"""
        ).fetchall()
