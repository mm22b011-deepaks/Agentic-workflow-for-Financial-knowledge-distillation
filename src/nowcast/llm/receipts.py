"""Do not resend requests whose outcome is unknown after interruption."""

from __future__ import annotations

import dataclasses
import json
import os
import time

from sqlalchemy import text

from nowcast.errors import NowcastError
from nowcast.jobs import JobStore, process_identity
from nowcast.llm.caller import LLMResult


class RequestUncertain(NowcastError):
    """A previous in-flight request cannot safely be repeated."""


class RequestReceipts:
    def __init__(self, store: JobStore):
        self.store = store

    def begin(self, key: str) -> LLMResult | None:
        blocked = False
        with self.store.transaction() as connection:
            row = (
                connection.execute(
                    text('SELECT * FROM request_receipts WHERE request_key=:key'), {'key': key}
                )
                .mappings()
                .first()
            )
            if row and row['status'] == 'complete':
                return dataclasses.replace(LLMResult(**json.loads(row['result'])), cached=True)
            if row and row['status'] in {'pending', 'uncertain'}:
                blocked = True
                if (
                    not process_identity(row['pid'])
                    or process_identity(row['pid']) != row['identity']
                ):
                    connection.execute(
                        text(
                            "UPDATE request_receipts SET status='uncertain' WHERE request_key=:key"
                        ),
                        {'key': key},
                    )
            else:
                if row:
                    connection.execute(
                        text('DELETE FROM request_receipts WHERE request_key=:key'), {'key': key}
                    )
                connection.execute(
                    text(
                        "INSERT INTO request_receipts(request_key,status,pid,identity,created_at) VALUES (:key,'pending',:pid,:identity,:created)"
                    ),
                    {
                        'key': key,
                        'pid': os.getpid(),
                        'identity': process_identity(os.getpid()),
                        'created': time.time(),
                    },
                )
        if blocked:
            raise RequestUncertain('request needs attention; automatic resend refused')
        return None

    def finish(self, key: str, result: LLMResult) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                text(
                    "UPDATE request_receipts SET status='complete',result=:result WHERE request_key=:key"
                ),
                {'key': key, 'result': json.dumps(dataclasses.asdict(result))},
            )

    def failed(self, key: str, status: str = 'uncertain') -> None:
        with self.store.transaction() as connection:
            connection.execute(
                text('UPDATE request_receipts SET status=:status WHERE request_key=:key'),
                {'key': key, 'status': status},
            )
