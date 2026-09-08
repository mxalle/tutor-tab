from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine
from app.routers import lessons, payments, students

# The Mini App is a single static page served by this same app, so it shares an
# origin with the API and can call it with plain relative URLs.
MINIAPP_DIR = Path(__file__).resolve().parent.parent / "miniapp"
MINIAPP_INDEX = MINIAPP_DIR / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(students.router)
app.include_router(lessons.router)
app.include_router(payments.router)


@app.get("/health", tags=["service"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


if MINIAPP_INDEX.is_file():
    # Declared before the mount so that `/app` itself answers with the page
    # instead of redirecting to `/app/`.
    @app.get("/app", include_in_schema=False)
    async def miniapp_index() -> FileResponse:
        return FileResponse(MINIAPP_INDEX)

    app.mount(
        "/app", StaticFiles(directory=MINIAPP_DIR, html=True), name="miniapp"
    )
