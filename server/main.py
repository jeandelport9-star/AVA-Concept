from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import automation, db
from .api import r

WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="AVA", docs_url="/api/docs")
app.include_router(r)


@app.middleware("http")
async def no_stale_app(request, call_next):
    """Browsers must re-check the app's own files on every load (a quick 304 when unchanged), so an update shows up
    straight away instead of the browser running yesterday's scripts from its cache."""
    resp = await call_next(request)
    path = request.url.path
    if not path.startswith(("/api/", "/uploads/")) and not path.startswith("/vendor/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.on_event("startup")
def _start():
    db.init()
    automation.start_background()


db.init()
app.mount("/uploads", StaticFiles(directory=db.UPLOADS), name="uploads")


@app.get("/sw.js")
def sw():
    return FileResponse(WEB / "sw.js", media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
