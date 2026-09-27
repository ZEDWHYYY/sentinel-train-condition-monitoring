"""SENTINEL PS3 diagnostic API.

Opening the app starts no telemetry, simulator, RUL training or external call:
only the run database and one bounded analysis worker.

Run:  uvicorn main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import jobs
import storage
from api_v1 import router
from diagnostics.model_store import model_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init()
    jobs.start()
    yield


app = FastAPI(title="SENTINEL PS3 diagnostics", version="1.0.0", lifespan=lifespan)
origins = os.environ.get("SENTINEL_ALLOWED_ORIGINS",
                         "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001")
app.add_middleware(CORSMiddleware, allow_origins=origins.split(","), allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "The request was not valid.",
                                                            "detail": exc.errors()[:5], "recoverable": True}})


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "sentinel-ps3", "models": model_status(), "scorer": "frozen-ps3-models"}
