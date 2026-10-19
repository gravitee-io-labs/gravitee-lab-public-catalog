"""What happened during one chat turn: the rows the web app shows under "Behind the answer", and one log line for each.

A row is {step: llm | exchange | tool, name, outcome: ok | denied | blocked | rate_limited | error, ms, detail,
arguments, status, transaction_id, request_id}. A key with no value is left out. Nothing secret goes in a row.
"""
import logging
import time
from typing import Any

log = logging.getLogger("bank-agent")


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class Trace:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(self, step: str, name: str, outcome: str, ms: int, detail: str = "", **extra: Any) -> None:
        row: dict[str, Any] = {"step": step, "name": name, "outcome": outcome, "ms": ms}
        if detail:
            row["detail"] = detail
        row.update({key: value for key, value in extra.items() if value is not None})
        self.rows.append(row)
        status = f" ({row['status']})" if "status" in row else ""
        log.info("%s %s -> %s%s in %d ms", step, name, outcome, status, ms)
