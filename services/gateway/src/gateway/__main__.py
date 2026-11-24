"""`python -m gateway`: run the API on 127.0.0.1:8000."""

from __future__ import annotations

import uvicorn

from gateway.app import create_app
from lmqa_models.settings import load_settings
from lmqa_security.redact import configure_logging


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level, fmt="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        create_app(settings), host=settings.api_host, port=settings.api_port, log_level="info"
    )


if __name__ == "__main__":
    main()
