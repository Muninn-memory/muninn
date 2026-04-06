from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Lock

_LOCK = Lock()
_CONFIGURED_DIR_ATTR = "_huginn_logging_dir"
_MANAGED_HANDLER_ATTR = "_huginn_managed_handler"


def _mark_managed(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _MANAGED_HANDLER_ATTR, True)
    return handler


def _is_managed(handler: logging.Handler) -> bool:
    return bool(getattr(handler, _MANAGED_HANDLER_ATTR, False))


def configure_logging(log_dir: str = "./logs") -> None:
    """
    Configure root logging once for Huginn.
    Idempotent: repeated calls with the same target dir do not add duplicate handlers.
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    target_dir = str(Path(log_dir).resolve())
    with _LOCK:
        root = logging.getLogger()
        current = getattr(root, _CONFIGURED_DIR_ATTR, None)
        if current == target_dir:
            return

        # Remove only handlers managed by this function, preserving external handlers.
        for handler in list(root.handlers):
            if _is_managed(handler):
                root.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass
                owned_stream = getattr(handler, "_huginn_owned_stream", None)
                if owned_stream is not None:
                    try:
                        owned_stream.close()
                    except Exception:
                        pass

        os.makedirs(target_dir, exist_ok=True)
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

        stream_handler = _mark_managed(logging.StreamHandler())
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

        file_stream = open(
            os.path.join(target_dir, "huginn.log"),
            mode="a",
            encoding="utf-8",
            errors="replace",
        )
        file_handler = _mark_managed(logging.StreamHandler(file_stream))
        setattr(file_handler, "_huginn_owned_stream", file_stream)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        root.setLevel(logging.INFO)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("primp").setLevel(logging.WARNING)
        logging.getLogger("ddgs.ddgs").setLevel(logging.ERROR)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        setattr(root, _CONFIGURED_DIR_ATTR, target_dir)


def get_managed_handler_count() -> int:
    root = logging.getLogger()
    return sum(1 for handler in root.handlers if _is_managed(handler))
