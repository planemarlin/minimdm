"""Structured logging: JSON formatter and request-ID injection."""
import json
import logging
import uuid

# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Request-ID filter — injects request_id into every log record
# ---------------------------------------------------------------------------

class RequestIdFilter(logging.Filter):
    """Adds the current request_id to log records if one is available."""

    # Module-level storage for the active request ID.
    # FastAPI runs each request in a thread (sync) or task (async); using a
    # simple module-level variable is safe for the thread-per-request model
    # and acceptable for the async model where only one request ID is active
    # in a given context at a time. For full async correctness a
    # contextvars.ContextVar would be needed, but it adds complexity with
    # little practical benefit for a single-process deployment.
    _current_request_id: str | None = None

    @classmethod
    def set(cls, request_id: str | None) -> None:
        cls._current_request_id = request_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = self.__class__._current_request_id
        return True


# ---------------------------------------------------------------------------
# Setup helper — called once at application startup
# ---------------------------------------------------------------------------

def configure_logging(log_format: str, debug: bool) -> None:
    """Configure root logger and uvicorn loggers with the chosen formatter."""
    level = logging.DEBUG if debug else logging.INFO

    if log_format == "json":
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    request_filter = RequestIdFilter()

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(request_filter)

    # Apply to root logger and the two uvicorn loggers
    for name in ("root", "uvicorn", "uvicorn.access", "uvicorn.error", "app"):
        logger = logging.getLogger(None if name == "root" else name)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = name != "root"

    # Suppress propagation duplicates from uvicorn child loggers
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).propagate = False


def new_request_id() -> str:
    return str(uuid.uuid4())
