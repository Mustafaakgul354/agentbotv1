"""AgentBot multi-agent appointment automation package."""

__all__ = ["__version__"]

__version__ = "0.1.0"

# Optional ASGI export for convenience when serving via uvicorn
try:  # pragma: no cover - import side-effect only when FastAPI installed
    from .app.main import app as asgi_app  # type: ignore
except Exception:  # pragma: no cover
    asgi_app = None  # type: ignore

