"""Run: python -m hub  (from loopHub/, with LOOPHUB_WEBHOOK_SECRET set)."""
import logging

import uvicorn

from . import config as config_mod
from .app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
cfg = config_mod.load()
uvicorn.run(create_app(cfg), host="127.0.0.1", port=cfg.port)
