"""ASGI entry point for the gateway image: `uvicorn gateway.asgi:app`."""

from gateway.app import create_app

app = create_app()
