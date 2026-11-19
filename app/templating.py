"""Shared paths and Jinja2 templates instance."""
import inspect
from pathlib import Path

from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Starlette >= 0.29 takes (request, name); older versions take (name, {"request": request}).
_REQUEST_FIRST = next(iter(inspect.signature(templates.TemplateResponse).parameters)) == "request"


def render(request, name: str, **context):
    if _REQUEST_FIRST:
        return templates.TemplateResponse(request, name, context)
    return templates.TemplateResponse(name, {"request": request, **context})
