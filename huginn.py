from __future__ import annotations

# Compat launcher: preserva `python huginn.py` para polling Telegram
# enquanto a arquitetura principal roda em `huginn.server`.
import os

os.environ.setdefault("PYTHONUTF8", "1")

from huginn import configure_logging

configure_logging()

from huginn.channels.telegram import main


if __name__ == "__main__":
    main()
