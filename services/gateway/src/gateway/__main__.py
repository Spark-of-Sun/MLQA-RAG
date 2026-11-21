"""`python -m gateway`: run the API on 127.0.0.1:8000."""

from __future__ import annotations

import logging

import uvicorn

from gateway.app import create_app
from lmqa_models.settings import load_settings


def main() -> None:
    settings = load_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(create_app(settings), host=settings.api_host, port=settings.api_port, log_level="info")


if __name__ == "__main__":
    main()
