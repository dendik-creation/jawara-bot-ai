"""One JSON object per log line, `extra=` fields merged at top level.

Copied rather than imported from the gateway on purpose: ML Service is a
separate deployable with its own image and its own dependency set. A shared
`common/` package would reintroduce exactly the coupling the split removed
(02_Architecture/04_ML_Service.md §1).
"""

import json
import logging
from datetime import datetime, timezone

_RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
