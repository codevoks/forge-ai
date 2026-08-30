from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    @contextmanager
    def transaction(
        self,
        *,
        tenant_id: str | None = None,
        actor_id: str | None = None,
        worker_id: str | None = None,
    ) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                if tenant_id is not None:
                    conn.execute("select set_config('forge.tenant_id', %s, true)", (tenant_id,))
                if actor_id is not None:
                    conn.execute("select set_config('forge.actor_id', %s, true)", (actor_id,))
                if worker_id is not None:
                    conn.execute("select set_config('forge.worker_id', %s, true)", (worker_id,))
                yield conn

    def ping(self) -> bool:
        try:
            with psycopg.connect(self.database_url) as conn:
                conn.execute("select 1")
            return True
        except psycopg.Error:
            return False
