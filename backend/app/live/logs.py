"""Structured (JSON) logs for the live pipeline: one JSON object per line with the stage and, when known, the token and symbol."""
from __future__ import annotations

import datetime as dt
import json
import logging
import sys

FIELDS = ("token", "symbol", "stage")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": dt.datetime.fromtimestamp(record.created, dt.timezone.utc).isoformat(timespec="milliseconds"), "level": record.levelname,
             "logger": record.name, "msg": record.getMessage()}
        for f in FIELDS:
            v = getattr(record, f, None)
            if v is not None:
                d[f] = v
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d, ensure_ascii=False)


def configure() -> None:
    """Route the pipeline's loggers ('live*', 'app.live*') through the JSON formatter (idempotent). Secrets are never put in a message."""
    for name in ("live", "app.live"):
        lg = logging.getLogger(name)
        if any(isinstance(h.formatter, JsonFormatter) for h in lg.handlers):
            continue
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(JsonFormatter())
        lg.handlers = [h]
        lg.propagate = False
        lg.setLevel(logging.INFO)
