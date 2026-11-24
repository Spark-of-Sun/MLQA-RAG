"""ASGI entry point for the ops image (operator ingress only): `uvicorn ops.asgi:app`."""

from ops.app import create_app

app = create_app()
