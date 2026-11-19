"""Application entry point: uvicorn app.main:app"""
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from app.config import get_settings
from app.db import get_client
from app import worker
from app.services import bootstrap
from app.routers import pages, staff, staff_live, staff_students, student
from app.templating import STATIC_DIR

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = get_client(settings)
    app.state.client = client
    app.state.db = client[settings.mongo_db]
    try:
        bootstrap.run(app.state.db, settings.mongo_collection)
    except PyMongoError:
        # DB down at startup: requests will return 503 until it is reachable.
        pass
    stop, thread = threading.Event(), None
    if settings.embedded_worker:
        # Single-service deployments (e.g. Render free plan) run grading inside the web process.
        thread = threading.Thread(target=worker.serve, args=(app.state.db, settings, stop), name="embedded-worker", daemon=True)
        thread.start()
    try:
        yield
    finally:
        stop.set()
        if thread:
            thread.join(timeout=5)
        client.close()


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)


@app.exception_handler(PyMongoError)
async def mongo_error_handler(request: Request, exc: PyMongoError):
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


app.include_router(pages.router)
app.include_router(student.router)
app.include_router(staff.router)
app.include_router(staff_students.router)
app.include_router(staff_live.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
