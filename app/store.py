"""Where short links are kept.

MemoryStore is used for tests and quick local runs; PostgresStore is used when
DATABASE_URL is set (Docker Compose and Kubernetes).
"""

import threading


class MemoryStore:
    def __init__(self):
        self._links = {}
        self._lock = threading.Lock()

    def save(self, code, url):
        """Store a new link. Returns False if the code is already taken."""
        with self._lock:
            if code in self._links:
                return False
            self._links[code] = {"url": url, "clicks": 0}
            return True

    def hit(self, code):
        """Count a click and return the target URL, or None if unknown."""
        with self._lock:
            link = self._links.get(code)
            if link is None:
                return None
            link["clicks"] += 1
            return link["url"]

    def stats(self, code):
        with self._lock:
            link = self._links.get(code)
            if link is None:
                return None
            return {"code": code, "url": link["url"], "clicks": link["clicks"]}

    def ping(self):
        return True


class PostgresStore:
    def __init__(self, dsn):
        from psycopg_pool import ConnectionPool

        self._pool = ConnectionPool(dsn, min_size=1, max_size=5, open=True)
        with self._pool.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS links (
                    code       TEXT PRIMARY KEY,
                    url        TEXT NOT NULL,
                    clicks     BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

    # All queries use %s parameters, never string formatting, so user input
    # can't change the SQL (no SQL injection).
    def save(self, code, url):
        with self._pool.connection() as conn:
            cur = conn.execute(
                "INSERT INTO links (code, url) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING",
                (code, url),
            )
            return cur.rowcount == 1

    def hit(self, code):
        with self._pool.connection() as conn:
            row = conn.execute(
                "UPDATE links SET clicks = clicks + 1 WHERE code = %s RETURNING url",
                (code,),
            ).fetchone()
            return row[0] if row else None

    def stats(self, code):
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT url, clicks FROM links WHERE code = %s", (code,)
            ).fetchone()
            if row is None:
                return None
            return {"code": code, "url": row[0], "clicks": row[1]}

    def ping(self):
        with self._pool.connection() as conn:
            conn.execute("SELECT 1")
        return True


def build_store(database_url):
    if database_url:
        return PostgresStore(database_url)
    return MemoryStore()
