from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .settings import load
from .worker import RelateWorker

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True
)
log = logging.getLogger(__name__)

settings = load()
worker = RelateWorker(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker.start()
    log.info("sauron-relate iniciado: camaras=%s", settings.cameras)
    yield
    worker.stop()


app = FastAPI(title="Sauron Relate", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return JSONResponse(worker.health())


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=settings.health_port, log_level="info")


if __name__ == "__main__":
    main()
