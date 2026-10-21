from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import automation, db
from .api import r

WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="AVA", docs_url="/api/docs")
app.include_router(r)


MAINTENANCE_API = ("/api/tickets", "/api/pros", "/api/contractor/", "/api/reports/maintenance")


@app.middleware("http")
async def maintenance_module(request, call_next):
    """Repairs and the contractor marketplace are switched off while maintenance runs in Fixit (setting module_maintenance)."""
    if request.url.path.startswith(MAINTENANCE_API):
        from . import fees
        if not fees.on("maintenance"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Repairs and maintenance are handled in Fixit for now."}, status_code=404)
    return await call_next(request)


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
