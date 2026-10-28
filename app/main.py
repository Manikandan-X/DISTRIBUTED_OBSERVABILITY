"""Default entry point (``uvicorn app.main:app``): the API Gateway.

Every other service has its own entry point in ``app/apps/`` - see README.
"""

from app.apps.gateway import app  # noqa: F401
