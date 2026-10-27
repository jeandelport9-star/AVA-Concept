"""HTTP API. JSON in/out; multipart for uploads. Every back-office route is scoped to what the signed-in user may see."""
import csv
import io
import json
import re
import uuid
from datetime import date, datetime, timedelta
from hashlib import md5
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse

from . import ai, automation, db, fees, services as sv
from .auth import (can_prop, check_pw, hash_pw, in_list, new_session, optional_user, prop_ids, public_user, role, user)

r = APIRouter(prefix="/api")
STAFF = ("admin", "pm")
OFFICE = ("admin", "pm", "landlord")


async def body(request: Request):
    ct = request.headers.get("content-type", "")
    if "multipart" in ct or "form-urlencoded" in ct:
        f = await request.form()
        out, files = {}, {}
        for k, v in f.multi_items():
            if hasattr(v, "filename"):
                if v.filename:
                    files.setdefault(k, []).append(v)
            else:
                out[k] = v
        out["_files"] = files
        return out
    try:
        return await request.json()
    except Exception:
        return {}


async def save_files(files, sub="misc"):
    urls = []
    for f in files or []:
        ext = (f.filename.rsplit(".", 1)[-1] if "." in f.filename else "bin").lower()[:5]
        if ext not in {"jpg", "jpeg", "png", "webp", "gif", "pdf", "mp4", "mov", "heic", "doc", "docx", "xlsx", "csv", "txt", "webm", "ogg", "m4a", "mp3", "wav"}:
            ext = "bin"
        folder = db.UPLOADS / sub / date.today().strftime("%Y%m")
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex[:16]}.{ext}"
        (folder / name).write_bytes(await f.read())
        urls.append(f"/uploads/{sub}/{folder.name}/{name}")
    return urls


def money(v, default=None):
    r = db.rands(num(v))
    return default if r is None else r


def num(v, cast=float, default=None):
    try:
        return cast(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def flag(v):
    return 1 if str(v).lower() in ("1", "true", "on", "yes") else 0


# =================================================================== auth
@r.post("/auth/register")
async def register(request: Request, response: Response):
    b = await body(request)
    email = (b.get("email") or "").strip().lower()
    if not re.match(r"[^@\s]+@[^@\s]+\.\w+", email):
        raise HTTPException(400, "Enter a valid email address")
    if len(b.get("password") or "") < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    rl = b.get("role") or "tenant"
    if rl not in ("tenant", "landlord", "contractor", "pm"):
        raise HTTPException(400, "Unknown account type")
    if db.val("SELECT 1 FROM users WHERE email=?", email):
        raise HTTPException(400, "An account with this email already exists - sign in instead")
    uid = db.ins("users", email=email, pw_hash=hash_pw(b["password"]), name=(b.get("name") or email.split("@")[0]).strip(),
                 phone=b.get("phone"), role=rl, company=b.get("company"), commission_pct=4.0 if rl == "pm" else None)
    if rl == "contractor":
        trades = b.get("trades") or "Handyman"
        db.ins("contractors", user_id=uid, trades=trades if isinstance(trades, list) else [t.strip() for t in trades.split(",") if t.strip()],
               areas=[a.strip() for a in (b.get("areas") or "").split(",") if a.strip()], approved=0,
               lat=num(b.get("lat")), lng=num(b.get("lng")), base_address=b.get("base_address"), radius_km=num(b.get("radius_km"), float, 25),
               website=b.get("website"), years=num(b.get("years"), int), insured=flag(b.get("insured")), callout_fee=num(b.get("callout_fee"), int, 0),
               registration=b.get("registration"), bio=b.get("bio"),
               sub_until=(date.today() + timedelta(days=fees.S("free_trial_days"))).isoformat())
        for a in db.q("SELECT id FROM users WHERE role='admin'"):
            sv.notify(a["id"], "Contractor awaiting approval", b.get("company") or b.get("name"), "#/app/contractors", "admin")
    tok = new_session(uid)
    response.set_cookie("ava_session", tok, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 60)
    return {"user": public_user(db.q1("SELECT * FROM users WHERE id=?", uid)), "token": tok}


@r.post("/auth/login")
async def login(request: Request, response: Response):
    b = await body(request)
    u = db.q1("SELECT * FROM users WHERE email=?", (b.get("email") or "").strip().lower())
    if not u or not check_pw(b.get("password") or "", u["pw_hash"]):
        raise HTTPException(400, "Email or password is wrong")
    if not u["active"]:
        raise HTTPException(403, "This account is disabled")
    tok = new_session(u["id"])
    response.set_cookie("ava_session", tok, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 60)
    return {"user": public_user(u), "token": tok}


@r.post("/auth/logout")
def logout(request: Request, response: Response):
    tok = request.cookies.get("ava_session")
    if tok:
        db.exe("DELETE FROM sessions WHERE token=?", tok)
    response.delete_cookie("ava_session")
    return {"ok": True}


def MAINT_TASKS():
    """While maintenance runs in Fixit, repair-related to-dos stay out of every inbox."""
    return "" if fees.on("maintenance") else " AND t.kind NOT IN ('maintenance','approval')"


def features():
    return {"maintenance": fees.on("maintenance"), "fixit_url": fees.S("fixit_url") or ""}


@r.get("/me")
def me(u=Depends(optional_user)):
    if not u:
        return {"user": None, "features": features()}
    unread = db.val("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", u["id"])
    return {"user": public_user(u), "unread": unread, "features": features()}


@r.put("/me")
async def me_update(request: Request, u=Depends(user)):
    b = await body(request)
    kw = {k: b[k] for k in ("name", "phone", "company") if k in b}
    if b.get("password"):
        if not check_pw(b.get("current_password") or "", u["pw_hash"]):
            raise HTTPException(400, "Current password is wrong")
        kw["pw_hash"] = hash_pw(b["password"])
    if u["role"] == "pm" and "commission_pct" in b:
        kw["commission_pct"] = max(3.0, min(5.0, float(b["commission_pct"])))
    db.upd("users", u["id"], **kw)
    return public_user(db.q1("SELECT * FROM users WHERE id=?", u["id"]))


# =================================================================== public portal
PUBLIC_COLS = ("id, title, type, address, suburb, city, province, lat, lng, bedrooms, bathrooms, parking, size_m2, erf_size, features, pets, "
               "furnished, rent, deposit, available_from, headline, description, featured, views, created_at, published_at, pm_id")


def cover(pid):
    return db.val("SELECT url FROM media WHERE property_id=? AND kind='photo' ORDER BY sort, id LIMIT 1", pid)


def listings(limit: int = 60, **f):
    """Search live listings with the Property24 filter set (see server/search.py)."""
    from . import search
    rows, _ = search.run(f, PUBLIC_COLS, limit)
    return decorate(rows)


def decorate(rows):
    for x in rows:
        x["cover"] = cover(x["id"])
        x["photos"] = db.val("SELECT COUNT(*) FROM media WHERE property_id=? AND kind='photo'", x["id"])
        x["has_tour"] = bool(db.val("SELECT 1 FROM media WHERE property_id=? AND kind='pano'", x["id"]))
    return rows


@r.get("/listings")
def listings_route(request: Request, limit: int = 60):
    return listings(limit, **{k: v for k, v in request.query_params.items() if k != "limit"})


@r.get("/search")
def search_route(request: Request, limit: int = 120):
    from . import search
    f = {k: v for k, v in request.query_params.items() if k != "limit"}
    rows, total = search.run(f, PUBLIC_COLS, limit)
    return {"rows": decorate(rows), "total": total}


@r.get("/search/facets")
def search_facets():
    from . import search
    return search.facets()


@r.get("/listings/{pid}")
def listing(pid: int, u=Depends(optional_user)):
    p = db.q1(f"SELECT {PUBLIC_COLS}, listing_status FROM properties WHERE id=?", pid)
    if not p or (p["listing_status"] != "live" and not (u and pid in prop_ids(u))):
        raise HTTPException(404, "This listing is no longer available")
    db.exe("UPDATE properties SET views=views+1 WHERE id=?", pid)
    p["media"] = db.q("SELECT * FROM media WHERE property_id=? ORDER BY kind, sort, id", pid)
    p["move_in"] = fees.move_in_costs(p["rent"] or 0, p["bedrooms"], p["bathrooms"])
    pm = db.q1("SELECT id, name, company, phone FROM users WHERE id=?", p["pm_id"])
    if pm:
        pm["rating"] = db.val("SELECT ROUND(AVG(rating),1) FROM reviews WHERE target_type='pm' AND target_id=? AND status='published'", pm["id"])
        pm["managed"] = fees.pm_managed_count(pm["id"])
    p["pm"] = pm
    p["rating"] = db.val("SELECT ROUND(AVG(rating),1) FROM reviews WHERE target_type='property' AND target_id=? AND status='published'", pid)
    p["saved"] = bool(u and db.val("SELECT 1 FROM favourites WHERE user_id=? AND property_id=?", u["id"], pid))
    p["applied"] = bool(u and db.val("SELECT 1 FROM applications WHERE user_id=? AND property_id=? AND status!='withdrawn'", u["id"], pid))
    sim = listings(city=p["city"], limit=8)
    p["similar"] = [s for s in sim if s["id"] != pid][:4]
    return p


@r.get("/listings/{pid}/slots")
def slots(pid: int):
    taken = {v["slot"] for v in db.q("SELECT slot FROM viewings WHERE property_id=? AND status IN ('requested','confirmed')", pid)}
    out, d = [], date.today()
    for i in range(1, 15):
        dd = d + timedelta(days=i)
        if dd.weekday() in (1, 3):
            times = ["16:30", "17:15", "18:00"]
        elif dd.weekday() == 5:
            times = ["09:00", "10:00", "11:00", "12:00"]
        else:
            continue
        for t in times:
            s = f"{dd.isoformat()}T{t}"
            out.append({"slot": s, "free": s not in taken})
    return out


@r.post("/viewings")
async def book_viewing(request: Request, u=Depends(optional_user)):
    b = await body(request)
    p = sv.prop(int(b["property_id"]))
    if not b.get("slot"):
        raise HTTPException(400, "Choose a time")
    if db.val("SELECT 1 FROM viewings WHERE property_id=? AND slot=? AND status IN ('requested','confirmed')", p["id"], b["slot"]):
        raise HTTPException(400, "That time has just been taken - choose another")
    vid = db.ins("viewings", property_id=p["id"], user_id=u["id"] if u else None, name=b.get("name") or (u and u["name"]),
                 email=b.get("email") or (u and u["email"]), phone=b.get("phone") or (u and u["phone"]), slot=b["slot"],
                 status="confirmed", notes=b.get("notes"))
    if b.get("via_agent"):
        db.ins("agent_log", session=b.get("session"), user_id=u["id"] if u else None, property_id=p["id"], role=u["role"] if u else "visitor",
               text=f"Booked viewing {b['slot']}", reply="Viewing confirmed", intent="booked")
    sv.notify(p["pm_id"], "Viewing booked", f"{b.get('name') or u['name']} – {p['title']} {b['slot'].replace('T', ' ')}", "#/app/viewings", "viewing")
    sv.log(p["pm_id"], p["id"], f"Viewing auto-confirmed for {b['slot'].replace('T', ' ')}", "#/app/viewings")
    return {"id": vid, "status": "confirmed", "address": p["address"], "lat": p["lat"], "lng": p["lng"]}


@r.get("/favourites")
def favs(u=Depends(user)):
    rows = db.q(f"SELECT {PUBLIC_COLS}, listing_status FROM properties WHERE id IN (SELECT property_id FROM favourites WHERE user_id=?)", u["id"])
    for x in rows:
        x["cover"] = cover(x["id"])
    return rows


@r.post("/favourites/{pid}")
def fav_toggle(pid: int, u=Depends(user)):
    if db.val("SELECT 1 FROM favourites WHERE user_id=? AND property_id=?", u["id"], pid):
        db.exe("DELETE FROM favourites WHERE user_id=? AND property_id=?", u["id"], pid)
        return {"saved": False}
    db.exe("INSERT INTO favourites(user_id, property_id) VALUES(?,?)", u["id"], pid)
    return {"saved": True}


@r.get("/alerts")
def alerts(u=Depends(user)):
    return db.q("SELECT * FROM alerts WHERE user_id=? ORDER BY id DESC", u["id"])


@r.post("/alerts")
async def alert_add(request: Request, u=Depends(user)):
    b = await body(request)
    return {"id": db.ins("alerts", user_id=u["id"], query=json.dumps(b))}


@r.delete("/alerts/{aid}")
def alert_del(aid: int, u=Depends(user)):
    db.exe("DELETE FROM alerts WHERE id=? AND user_id=?", aid, u["id"])
    return {"ok": True}


@r.get("/fees/public")
def fees_public(rent: float = 20000, bedrooms: float = 2, bathrooms: float = 1, homes: int = 1):
    rent, homes = db.rands(rent), max(1, homes)
    return {"move_in": fees.move_in_costs(rent, bedrooms, bathrooms), "landlord": fees.landlord_monthly(rent, n_rented=homes, insured=False),
            "compare": fees.agent_comparison(rent, homes), "homes": homes, "inspection_fee": fees.inspection_fee(bedrooms, bathrooms),
            "tiers": fees.S("ava_tiers"), "pm_tiers": fees.S("pm_tiers"), "admin_fee": fees.S("admin_fee"),
            "insurance": fees.S("insurance_monthly")}


@r.get("/stats/public")
def stats_public():
    live = "listing_status='live' AND kind='rental'"
    provs = db.q(f"SELECT province, COUNT(*) n, MIN(rent) lo FROM properties WHERE {live} GROUP BY province ORDER BY n DESC")
    for p in provs:
        pid = db.val(f"SELECT id FROM properties WHERE {live} AND province=? ORDER BY featured DESC, views DESC LIMIT 1", p["province"])
        p["cover"] = cover(pid)
    return {"live": db.val(f"SELECT COUNT(*) FROM properties WHERE {live}"),
            "managed": db.val("SELECT COUNT(*) FROM properties WHERE kind='rental'"),
            "pms": db.val("SELECT COUNT(*) FROM users WHERE role='pm'"),
            "cities": [x["city"] for x in db.q(f"SELECT city, COUNT(*) n FROM properties WHERE {live} GROUP BY city ORDER BY n DESC LIMIT 8")],
            "provinces": provs,
            "new_week": db.val(f"SELECT COUNT(*) FROM properties WHERE {live} AND COALESCE(published_at, created_at) >= date('now','-7 day')")}


# =================================================================== applications
@r.post("/applications")
async def apply(request: Request, u=Depends(user)):
    b = await body(request)
    p = sv.prop(int(b["property_id"]))
    if p["listing_status"] != "live":
        raise HTTPException(400, "This property is not taking applications")
    if db.val("SELECT 1 FROM applications WHERE user_id=? AND property_id=? AND status NOT IN ('withdrawn','declined')", u["id"], p["id"]):
        raise HTTPException(400, "You have already applied for this property")
    docs = []
    for kind in ("id", "payslips", "bank_statements", "other"):
        for url in await save_files(b["_files"].get(kind), "docs"):
            docs.append({"kind": kind, "url": url})
    aid = db.ins("applications", property_id=p["id"], user_id=u["id"], name=b.get("name") or u["name"], email=u["email"],
                 phone=b.get("phone") or u["phone"], employer=b.get("employer"), income=num(b.get("income"), int, 0),
                 other_income=num(b.get("other_income"), int, 0), occupants=num(b.get("occupants"), int, 1),
                 pets=flag(b.get("pets")), move_in=b.get("move_in"), message=b.get("message"), docs=docs)
    a = db.q1("SELECT * FROM applications WHERE id=?", aid)
    sc, notes = ai.score_application(a, p["rent"])
    db.upd("applications", aid, score=sc, score_notes="\n".join(notes), status="screening")
    sv.task(p["pm_id"], p["id"], "application", f"Application {sc}/100 – {p['title']}", f"{a['name']}: {notes[0]}", "#/app/applications",
            1 if sc >= 70 else 3, dedupe=f"app:{aid}")
    sv.notify(p["pm_id"], "New rental application", f"{a['name']} · score {sc}", "#/app/applications", "application")
    sv.notify(p["landlord_id"], "New rental application", f"{p['title']} · score {sc}", "#/app/applications", "application")
    return {"id": aid, "score": sc, "notes": notes}


@r.get("/applications")
def applications(u=Depends(user), property_id: int = 0):
    if u["role"] == "tenant":
        return db.q("SELECT a.*, p.title, p.rent FROM applications a JOIN properties p ON p.id=a.property_id WHERE a.user_id=? ORDER BY a.id DESC", u["id"])
    ids = prop_ids(u)
    sql = f"SELECT a.*, p.title, p.rent, p.suburb FROM applications a JOIN properties p ON p.id=a.property_id WHERE a.property_id IN {in_list(ids)}"
    if property_id:
        sql += f" AND a.property_id={int(property_id)}"
    return db.q(sql + " ORDER BY CASE a.status WHEN 'screening' THEN 0 WHEN 'shortlisted' THEN 1 WHEN 'submitted' THEN 2 ELSE 3 END, a.score DESC")


@r.put("/applications/{aid}")
async def application_update(aid: int, request: Request, u=Depends(user)):
    a = db.q1("SELECT * FROM applications WHERE id=?", aid)
    b = await body(request)
    if u["role"] == "tenant":
        if a["user_id"] != u["id"]:
            raise HTTPException(403)
        db.upd("applications", aid, status="withdrawn")
        return {"ok": True}
    can_prop(u, a["property_id"], True)
    kw = {k: b[k] for k in ("status", "credit_score", "rental_history", "decision_note") if k in b}
    db.upd("applications", aid, **kw)
    a = db.q1("SELECT * FROM applications WHERE id=?", aid)
    p = sv.prop(a["property_id"])
    if "credit_score" in kw or "rental_history" in kw:
        sc, notes = ai.score_application(a, p["rent"])
        db.upd("applications", aid, score=sc, score_notes="\n".join(notes))
    if kw.get("status") == "declined":
        sv.notify(a["user_id"], "Application update", f"Unfortunately your application for {p['title']} was not successful.", "#/search", "application")
        sv.close_tasks(f"app:{aid}")
    return db.q1("SELECT * FROM applications WHERE id=?", aid)


@r.post("/applications/{aid}/credit-check")
def credit_check(aid: int, u=Depends(role(*OFFICE))):
    """Stand-in for the TPN / XDS bureau call: deterministic from the ID so demos repeat."""
    a = db.q1("SELECT * FROM applications WHERE id=?", aid)
    can_prop(u, a["property_id"], True)
    seed = int(md5((a["email"] or str(aid)).encode()).hexdigest()[:6], 16)
    cs = 560 + seed % 200
    hist = "Good – paid on time (TPN rental profile)" if seed % 5 else "Some arrears in the last 24 months"
    db.upd("applications", aid, credit_score=cs, rental_history=hist)
    a = db.q1("SELECT * FROM applications WHERE id=?", aid)
    sc, notes = ai.score_application(a, sv.prop(a["property_id"])["rent"])
    db.upd("applications", aid, score=sc, score_notes="\n".join(notes))
    return db.q1("SELECT * FROM applications WHERE id=?", aid)


@r.post("/applications/{aid}/approve")
async def application_approve(aid: int, request: Request, u=Depends(role(*OFFICE))):
    a = db.q1("SELECT * FROM applications WHERE id=?", aid)
    can_prop(u, a["property_id"], True)
    b = await body(request)
    start = b.get("start_date") or a["move_in"] or (date.today() + timedelta(days=14)).isoformat()
    lid = sv.make_lease(a["property_id"], a["user_id"], start, int(b.get("months") or 12), num(b.get("rent"), int),
                        aid, float(b.get("escalation") or 8))
    db.upd("applications", aid, status="approved")
    sv.close_tasks(f"app:{aid}")
    sv.notify(a["user_id"], "Application approved!", "Your lease is ready to sign in the app.", f"#/app/lease/{lid}", "application")
    return {"lease_id": lid}


# =================================================================== dashboard
def kpis(ids):
    il = in_list(ids)
    per = sv.period()
    leases = db.q(f"SELECT * FROM leases WHERE status='active' AND property_id IN {il}")
    rentals = db.val(f"SELECT COUNT(*) FROM properties WHERE kind='rental' AND id IN {il}") or 0
    arrears = sum(max(0, sv.balance("tenant", l["id"])) for l in leases)
    charged = db.val(f"SELECT COALESCE(SUM(amount),0) FROM ledger WHERE account='tenant' AND kind='rent_charge' AND period=? AND property_id IN {il}", per) or 0
    collected = -(db.val(f"SELECT COALESCE(SUM(amount),0) FROM ledger WHERE account='tenant' AND kind='payment' AND period=? AND property_id IN {il}", per) or 0)
    return {
        "properties": rentals, "let": len(leases), "vacant": rentals - len({l["property_id"] for l in leases}),
        "occupancy": round(100 * len({l['property_id'] for l in leases}) / rentals) if rentals else 0,
        "rent_roll": sum(l["rent"] for l in leases), "charged": round(charged), "collected": round(collected),
        "collection_rate": round(100 * min(collected, charged) / charged) if charged else 100,
        "arrears": round(arrears), "in_arrears": sum(1 for l in leases if sv.balance("tenant", l["id"]) > 0),
        "deposits_held": round(db.val(f"SELECT COALESCE(SUM(amount),0) FROM ledger WHERE account='deposit' AND property_id IN {il}") or 0),
        "open_tickets": db.val(f"SELECT COUNT(*) FROM tickets WHERE status NOT IN ('closed','cancelled','completed') AND property_id IN {il}"),
        "urgent_tickets": db.val(f"SELECT COUNT(*) FROM tickets WHERE status NOT IN ('closed','cancelled','completed') AND priority='Urgent' AND property_id IN {il}"),
        "live_listings": db.val(f"SELECT COUNT(*) FROM properties WHERE listing_status='live' AND id IN {il}"),
        "open_snags": db.val(f"SELECT COUNT(*) FROM snags WHERE status!='closed' AND property_id IN {il}"),
        "overdue_snags": db.val(f"SELECT COUNT(*) FROM snags WHERE status!='closed' AND due_date<? AND property_id IN {il}", db.today()),
        "expiring_60": sum(1 for l in leases if l["end_date"] <= (date.today() + timedelta(days=60)).isoformat()),
    }


@r.get("/dashboard")
def dashboard(u=Depends(user)):
    ids = prop_ids(u)
    il = in_list(ids)
    out = {"role": u["role"]}
    if u["role"] in ("pm", "admin", "landlord"):
        out["kpis"] = kpis(ids)
    if u["role"] in ("pm", "admin"):
        pmw = "" if u["role"] == "admin" else f" AND pm_id={u['id']}"
        out["tasks"] = db.q(f"SELECT t.*, p.title ptitle FROM tasks t LEFT JOIN properties p ON p.id=t.property_id WHERE t.status='open' AND t.kind NOT LIKE '\\_%' ESCAPE '\\' {MAINT_TASKS()} {pmw.replace('pm_id', 't.pm_id')} ORDER BY t.priority, COALESCE(t.due,'9999'), t.id DESC LIMIT 60")
        out["activity"] = db.q(f"SELECT * FROM activity WHERE 1=1 {pmw} ORDER BY id DESC LIMIT 25")
        out["automated_week"] = db.val(f"SELECT COUNT(*) FROM activity WHERE actor='AVA Autopilot' AND created_at>=? {pmw}", (date.today() - timedelta(days=7)).isoformat())
        out["anomalies"] = ai.ledger_anomalies(ids)
        out["last_tick"] = db.get_setting("last_tick")
        out["today"] = {
            "viewings": db.q(f"SELECT v.*, p.title FROM viewings v JOIN properties p ON p.id=v.property_id WHERE v.status='confirmed' AND v.slot>=? AND v.property_id IN {il} ORDER BY v.slot LIMIT 6", db.today()),
            "inspections": db.q(f"SELECT i.*, p.title FROM inspections i JOIN properties p ON p.id=i.property_id WHERE i.status!='final' AND i.property_id IN {il} ORDER BY i.date LIMIT 6"),
        }
        last = sv.period(date.today().replace(day=1) - timedelta(days=1))
        paid = db.val(f"SELECT COALESCE(SUM(amount),0) FROM ledger WHERE account='pm' AND period=? AND property_id IN {il}", last) or 0
        if not paid:   # statements for last month only run on payout day – show what has already been earned
            for r in db.q(f"SELECT g.property_id, SUM(g.amount) rent_in, p.pm_id FROM ledger g JOIN properties p ON p.id=g.property_id WHERE g.account='owner' AND g.kind='rent_received' AND g.period=? AND g.property_id IN {il} GROUP BY g.property_id", last):
                paid += db.rands(r["rent_in"] * fees.pm_commission_pct(r["pm_id"]) / 100) + fees.S("finders_fee")
        out["pm_earnings"] = db.rands(paid)
        out["pm_earnings_period"] = last
        out["payout_day"] = fees.S("payout_day")
        out["commission_pct"] = fees.pm_commission_pct(u["id"]) if u["role"] == "pm" else None
    if u["role"] == "landlord":
        out["properties"] = properties(u)
        out["savings"] = fees.landlord_savings(u["id"])
        out["approvals"] = db.q(f"SELECT t.*, p.title ptitle FROM tickets t JOIN properties p ON p.id=t.property_id WHERE t.status='awaiting_approval' AND t.property_id IN {il}") if fees.on("maintenance") else []
        out["statements"] = db.q(f"SELECT property_id, period, -SUM(amount) payout FROM ledger WHERE account='owner' AND kind='payout' AND property_id IN {il} GROUP BY property_id, period ORDER BY period DESC LIMIT 12")
        out["income_12m"] = db.q(f"SELECT period, SUM(CASE WHEN kind='rent_received' THEN amount ELSE 0 END) income, -SUM(CASE WHEN amount<0 AND kind!='payout' THEN amount ELSE 0 END) costs FROM ledger WHERE account='owner' AND property_id IN {il} GROUP BY period ORDER BY period DESC LIMIT 12")
    if u["role"] == "tenant":
        lease = db.q1("SELECT l.*, p.title, p.address, p.pm_id FROM leases l JOIN properties p ON p.id=l.property_id WHERE l.tenant_id=? ORDER BY (l.status='active') DESC, (l.status='awaiting_signature') DESC, l.id DESC LIMIT 1", u["id"])
        out["lease"] = lease
        if lease:
            out["balance"] = sv.balance("tenant", lease["id"])
            out["next_due"] = ai.next_due(lease)
            out["deposit_held"] = sv.balance("deposit", lease["id"])
            out["tickets"] = db.q("SELECT * FROM tickets WHERE lease_id=? ORDER BY id DESC LIMIT 6", lease["id"])
            out["inspections"] = db.q("SELECT * FROM inspections WHERE lease_id=? ORDER BY id DESC", lease["id"])
            out["pm"] = db.q1("SELECT id, name, phone, email FROM users WHERE id=?", lease["pm_id"])
            out["ref"] = f"AVA{lease['id']:05d}"
        out["applications"] = db.q("SELECT a.*, p.title FROM applications a JOIN properties p ON p.id=a.property_id WHERE a.user_id=? ORDER BY a.id DESC LIMIT 5", u["id"])
        out["viewings"] = db.q("SELECT v.*, p.title FROM viewings v JOIN properties p ON p.id=v.property_id WHERE v.user_id=? AND v.slot>=? ORDER BY v.slot", u["id"], db.today())
    if u["role"] == "contractor":
        c = db.q1("SELECT * FROM contractors WHERE user_id=?", u["id"])
        out["profile"] = c
        out["rfqs"] = db.q("SELECT q.*, t.title, t.ref, t.priority, t.quote_deadline, p.suburb FROM quotes q JOIN tickets t ON t.id=q.ticket_id JOIN properties p ON p.id=t.property_id WHERE q.contractor_id=? AND q.status='requested' ORDER BY q.id DESC", u["id"])
        out["jobs"] = db.q("SELECT t.*, p.title ptitle, p.address FROM tickets t JOIN properties p ON p.id=t.property_id WHERE t.contractor_id=? AND t.status IN ('approved','scheduled','in_progress','info_needed') ORDER BY t.priority='Urgent' DESC, t.id", u["id"])
        out["snags"] = db.q("SELECT s.*, p.title ptitle FROM snags s JOIN properties p ON p.id=s.property_id WHERE s.contractor_id=? AND s.status IN ('open','in_progress') ORDER BY s.due_date", u["id"])
        out["rating"] = db.val("SELECT ROUND(AVG(rating),1) FROM reviews WHERE target_type='contractor' AND target_id=? AND status='published'", u["id"])
        out["earned"] = db.val("SELECT COALESCE(SUM(cost),0) FROM tickets WHERE contractor_id=? AND status IN ('completed','closed')", u["id"])
        from . import marketplace
        out["market"] = marketplace.profile(u["id"])
        out["open_nearby"] = sum(1 for i in marketplace.open_issues(u["id"])["issues"] if i["can_apply"])
        out["fee"] = fees.S("contractor_listing_fee")
        out["radius"] = fees.S("quote_radius_km")
    return out


@r.post("/autopilot/run")
def autopilot_run(u=Depends(role(*STAFF))):
    return automation.tick()


@r.get("/tasks")
def tasks(u=Depends(role(*STAFF)), status: str = "open"):
    w = "" if u["role"] == "admin" else f" AND t.pm_id={u['id']}"
    return db.q(f"SELECT t.*, p.title ptitle FROM tasks t LEFT JOIN properties p ON p.id=t.property_id WHERE t.status=? AND t.kind NOT LIKE '\\_%' ESCAPE '\\' {MAINT_TASKS()} {w} ORDER BY t.priority, t.id DESC LIMIT 200", status)


@r.post("/tasks/{tid}/{action}")
def task_action(tid: int, action: str, u=Depends(role(*STAFF))):
    if action == "done":
        db.upd("tasks", tid, status="done", done_at=db.now())
    elif action == "snooze":
        db.upd("tasks", tid, due=(date.today() + timedelta(days=3)).isoformat(), priority=3)
    return {"ok": True}


# =================================================================== properties
@r.get("/properties")
def properties(u=Depends(user), kind: str = ""):
    ids = prop_ids(u)
    sql = f"""SELECT p.*, lu.name landlord_name, pu.name pm_name FROM properties p LEFT JOIN users lu ON lu.id=p.landlord_id
              LEFT JOIN users pu ON pu.id=p.pm_id WHERE p.id IN {in_list(ids)}"""
    if kind:
        sql += f" AND p.kind='{'project' if kind == 'project' else 'rental'}'"
    rows = db.q(sql + " ORDER BY p.title")
    for p in rows:
        l = db.q1("SELECT l.id, l.rent, l.end_date, l.status, u.name tenant_name FROM leases l JOIN users u ON u.id=l.tenant_id WHERE l.property_id=? AND l.status IN ('active','awaiting_signature') ORDER BY l.id DESC LIMIT 1", p["id"])
        p["lease"] = l
        p["balance"] = sv.balance("tenant", l["id"]) if l and l["status"] == "active" else 0
        p["cover"] = cover(p["id"])
        p["open_tickets"] = db.val("SELECT COUNT(*) FROM tickets WHERE property_id=? AND status NOT IN ('closed','cancelled','completed')", p["id"])
        p["open_snags"] = db.val("SELECT COUNT(*) FROM snags WHERE property_id=? AND status!='closed'", p["id"])
        p["description"] = None
    return rows


@r.post("/properties")
async def property_create(request: Request, u=Depends(role(*OFFICE))):
    b = await body(request)
    if not b.get("title") and not b.get("address"):
        raise HTTPException(400, "Give the property a name or address")
    landlord = u["id"] if u["role"] == "landlord" else num(b.get("landlord_id"), int)
    if b.get("landlord_email") and not landlord:
        landlord = ensure_user(b["landlord_email"], b.get("landlord_name"), "landlord", u)
    pm = u["id"] if u["role"] == "pm" else num(b.get("pm_id"), int)
    feats = b.get("features") or []
    if isinstance(feats, str):
        feats = [f.strip() for f in feats.split(",") if f.strip()]
    pid = db.ins("properties", pm_id=pm, landlord_id=landlord, title=b.get("title") or b.get("address"), kind=b.get("kind") or "rental",
                 type=b.get("type") or "Apartment", address=b.get("address"), suburb=b.get("suburb"), city=b.get("city"),
                 province=b.get("province"), lat=num(b.get("lat")), lng=num(b.get("lng")), erf=b.get("erf"),
                 bedrooms=num(b.get("bedrooms"), float, 0), bathrooms=num(b.get("bathrooms"), float, 0), parking=num(b.get("parking"), int, 0),
                 size_m2=num(b.get("size_m2")), erf_size=num(b.get("erf_size")), features=feats, pets=flag(b.get("pets")), furnished=flag(b.get("furnished")),
                 rent=num(b.get("rent"), int), deposit=num(b.get("deposit"), int), available_from=b.get("available_from"),
                 insured=flag(b.get("insured", 1)))
    p = sv.prop(pid)
    if not p["deposit"] and p["rent"]:
        db.upd("properties", pid, deposit=round(p["rent"] * fees.S("deposit_months")))
    sv.log(pm, pid, f"Property added: {p['title']}", f"#/app/property/{pid}", u["name"])
    return {"id": pid}


def ensure_user(email, name, role_, by):
    email = email.strip().lower()
    x = db.q1("SELECT id FROM users WHERE email=?", email)
    if x:
        return x["id"]
    uid = db.ins("users", email=email, pw_hash=hash_pw("ava12345"), name=name or email.split("@")[0], role=role_)
    if role_ == "contractor":
        db.ins("contractors", user_id=uid, approved=1)
    return uid


@r.get("/properties/{pid}")
def property_get(pid: int, u=Depends(user)):
    can_prop(u, pid)
    p = sv.prop(pid)
    p["media"] = db.q("SELECT * FROM media WHERE property_id=? ORDER BY kind, sort, id", pid)
    p["landlord"] = db.q1("SELECT id, name, email, phone, company FROM users WHERE id=?", p["landlord_id"])
    p["pm"] = db.q1("SELECT id, name, email, phone FROM users WHERE id=?", p["pm_id"])
    p["leases"] = db.q("SELECT l.*, u.name tenant_name, u.email tenant_email, u.phone tenant_phone FROM leases l JOIN users u ON u.id=l.tenant_id WHERE l.property_id=? ORDER BY l.id DESC", pid)
    for l in p["leases"]:
        l["balance"] = sv.balance("tenant", l["id"])
        l["deposit_held"] = sv.balance("deposit", l["id"])
    active = next((l for l in p["leases"] if l["status"] == "active"), None)
    p["risk"] = ai.renewal_risk(active["id"]) if active else None
    p["tickets"] = db.q("SELECT * FROM tickets WHERE property_id=? ORDER BY id DESC LIMIT 30", pid)
    p["inspections"] = db.q("SELECT * FROM inspections WHERE property_id=? ORDER BY date DESC, id DESC", pid)
    p["applications"] = db.q("SELECT id, name, score, status, created_at FROM applications WHERE property_id=? ORDER BY id DESC", pid) if u["role"] in OFFICE else []
    p["viewings"] = db.q("SELECT * FROM viewings WHERE property_id=? AND slot>=? ORDER BY slot", pid, db.today()) if u["role"] in OFFICE else []
    p["owner_ledger"] = db.q("SELECT * FROM ledger WHERE property_id=? AND account='owner' ORDER BY date DESC, id DESC LIMIT 40", pid) if u["role"] in OFFICE else []
    p["tenant_ledger"] = db.q("SELECT * FROM ledger WHERE lease_id=? AND account='tenant' ORDER BY date DESC, id DESC LIMIT 40", active["id"]) if active and u["role"] in OFFICE + ("tenant",) else []
    p["owner_balance"] = sv.balance("owner", property_id=pid)
    p["snag_metrics"] = sv.snag_metrics([pid]) if p["kind"] == "project" or db.val("SELECT 1 FROM snags WHERE property_id=?", pid) else None
    p["price"] = ai.comparable_rent(p)
    p["fees"] = fees.landlord_monthly(p["rent"] or 0, p["landlord_id"], p["pm_id"], p["insured"]) if p["rent"] else None
    p["documents"] = db.q("SELECT * FROM documents WHERE property_id=? ORDER BY id DESC", pid)
    return p


@r.put("/properties/{pid}")
async def property_update(pid: int, request: Request, u=Depends(role(*OFFICE))):
    can_prop(u, pid, True)
    b = await body(request)
    allowed = ("title", "kind", "type", "address", "suburb", "city", "province", "lat", "lng", "erf", "bedrooms", "bathrooms", "parking",
               "size_m2", "erf_size", "features", "pets", "furnished", "rent", "deposit", "available_from", "headline", "description", "insured", "featured", "landlord_id", "pm_id")
    kw = {k: b[k] for k in allowed if k in b}
    if isinstance(kw.get("features"), str):
        kw["features"] = [f.strip() for f in kw["features"].split(",") if f.strip()]
    for k in ("pets", "furnished", "insured", "featured"):
        if k in kw:
            kw[k] = flag(kw[k])
    db.upd("properties", pid, **kw)
    return sv.prop(pid)


@r.post("/properties/{pid}/ai-copy")
def property_copy(pid: int, u=Depends(role(*OFFICE))):
    can_prop(u, pid, True)
    return ai.listing_copy(sv.prop(pid))


@r.post("/properties/{pid}/publish")
def publish(pid: int, u=Depends(role(*OFFICE))):
    can_prop(u, pid, True)
    p = sv.prop(pid)
    missing = [m for m, ok in (("rent", p["rent"]), ("description", p["description"]), ("at least 3 photos",
              (db.val("SELECT COUNT(*) FROM media WHERE property_id=? AND kind='photo'", pid) or 0) >= 3), ("map location", p["lat"])) if not ok]
    if missing:
        raise HTTPException(400, "Before publishing add: " + ", ".join(missing))
    if db.val("SELECT 1 FROM leases WHERE property_id=? AND status='active' AND end_date>?", pid, (date.today() + timedelta(days=60)).isoformat()):
        raise HTTPException(400, "This property has an active lease for more than 60 more days")
    db.upd("properties", pid, listing_status="live", published_at=db.now())
    n = automation.area_alerts(pid)
    sv.log(p["pm_id"], pid, f"Listing published on AVA; {n} saved-search alert(s) sent", f"#/p/{pid}", u["name"])
    return {"ok": True, "alerts_sent": n}


@r.post("/properties/{pid}/unpublish")
def unpublish(pid: int, u=Depends(role(*OFFICE))):
    can_prop(u, pid, True)
    db.upd("properties", pid, listing_status="off")
    return {"ok": True}


@r.post("/properties/{pid}/media")
async def media_add(pid: int, request: Request, u=Depends(role(*OFFICE))):
    can_prop(u, pid, True)
    b = await body(request)
    kind = b.get("kind") or "photo"
    urls = await save_files(b["_files"].get("files"), "media")
    start = db.val("SELECT COALESCE(MAX(sort),0) FROM media WHERE property_id=?", pid) or 0
    for i, url in enumerate(urls):
        db.ins("media", property_id=pid, kind=kind, url=url, room=b.get("room"), caption=b.get("caption"), sort=start + i + 1)
    return db.q("SELECT * FROM media WHERE property_id=? ORDER BY kind, sort, id", pid)


@r.put("/media/{mid}")
async def media_update(mid: int, request: Request, u=Depends(role(*OFFICE))):
    m = db.q1("SELECT * FROM media WHERE id=?", mid)
    can_prop(u, m["property_id"], True)
    b = await body(request)
    db.upd("media", mid, **{k: b[k] for k in ("caption", "room", "sort", "kind") if k in b})
    return {"ok": True}


@r.delete("/media/{mid}")
def media_delete(mid: int, u=Depends(role(*OFFICE))):
    m = db.q1("SELECT * FROM media WHERE id=?", mid)
    can_prop(u, m["property_id"], True)
    db.exe("DELETE FROM media WHERE id=?", mid)
    return {"ok": True}


@r.post("/properties/{pid}/documents")
async def doc_add(pid: int, request: Request, u=Depends(user)):
    can_prop(u, pid)
    b = await body(request)
    for f, url in zip(b["_files"].get("files", []), await save_files(b["_files"].get("files"), "docs")):
        db.ins("documents", property_id=pid, user_id=u["id"], name=b.get("name") or f.filename, url=url, kind=b.get("kind") or "other",
               lease_id=num(b.get("lease_id"), int))
    return db.q("SELECT * FROM documents WHERE property_id=? ORDER BY id DESC", pid)


@r.get("/people")
def people(u=Depends(role(*STAFF)), role_: str = ""):
    sql = "SELECT id, name, email, phone, role, company FROM users WHERE active=1"
    if role_:
        sql += " AND role=?"
        return db.q(sql + " ORDER BY name", role_)
    return db.q(sql + " ORDER BY name")


# =================================================================== viewings
@r.get("/viewings")
def viewings(u=Depends(user)):
    if u["role"] == "tenant":
        return db.q("SELECT v.*, p.title, p.address FROM viewings v JOIN properties p ON p.id=v.property_id WHERE v.user_id=? ORDER BY v.slot DESC", u["id"])
    return db.q(f"SELECT v.*, p.title, p.address FROM viewings v JOIN properties p ON p.id=v.property_id WHERE v.property_id IN {in_list(prop_ids(u))} ORDER BY v.slot DESC LIMIT 200")


@r.put("/viewings/{vid}")
async def viewing_update(vid: int, request: Request, u=Depends(user)):
    v = db.q1("SELECT * FROM viewings WHERE id=?", vid)
    if u["role"] == "tenant" and v["user_id"] != u["id"]:
        raise HTTPException(403)
    if u["role"] != "tenant":
        can_prop(u, v["property_id"])
    b = await body(request)
    kw = {k: b[k] for k in ("status", "slot", "notes") if k in b}
    db.upd("viewings", vid, **kw)
    if v["user_id"] and u["id"] != v["user_id"]:
        sv.notify(v["user_id"], f"Viewing {kw.get('status', 'updated')}", v["slot"].replace("T", " "), f"#/p/{v['property_id']}", "viewing")
    return {"ok": True}


# =================================================================== leases
@r.get("/leases")
def leases(u=Depends(user)):
    if u["role"] == "tenant":
        rows = db.q("SELECT l.*, p.title FROM leases l JOIN properties p ON p.id=l.property_id WHERE l.tenant_id=? ORDER BY l.id DESC", u["id"])
    else:
        rows = db.q(f"SELECT l.*, p.title, u.name tenant_name FROM leases l JOIN properties p ON p.id=l.property_id JOIN users u ON u.id=l.tenant_id WHERE l.property_id IN {in_list(prop_ids(u))} ORDER BY l.status='active' DESC, l.end_date")
    for l in rows:
        l["balance"] = sv.balance("tenant", l["id"])
        l["terms"] = None
    return rows


@r.get("/leases/{lid}")
def lease_get(lid: int, u=Depends(user)):
    l = db.q1("SELECT * FROM leases WHERE id=?", lid)
    if not l:
        raise HTTPException(404)
    if u["role"] == "tenant" and l["tenant_id"] != u["id"]:
        raise HTTPException(403)
    if u["role"] != "tenant":
        can_prop(u, l["property_id"])
    l["property"] = sv.prop(l["property_id"])
    l["tenant"] = db.q1("SELECT id, name, email, phone FROM users WHERE id=?", l["tenant_id"])
    l["landlord"] = db.q1("SELECT id, name, email, phone, company FROM users WHERE id=?", l["property"]["landlord_id"])
    l["pm"] = db.q1("SELECT id, name, email, phone FROM users WHERE id=?", l["property"]["pm_id"])
    l["ledger"] = db.q("SELECT * FROM ledger WHERE lease_id=? AND account='tenant' ORDER BY date, id", lid)
    l["deposit_ledger"] = db.q("SELECT * FROM ledger WHERE lease_id=? AND account='deposit' ORDER BY date, id", lid)
    l["balance"] = sv.balance("tenant", lid)
    l["deposit_held"] = sv.balance("deposit", lid)
    l["risk"] = ai.renewal_risk(lid) if u["role"] in OFFICE else None
    l["ref"] = f"AVA{lid:05d}"
    l["checklist"] = lease_checklist(l)
    return l


def lease_checklist(l):
    """'No steps missed': the compliance trail for this tenancy."""
    lid, pid = l["id"], l["property_id"]
    steps = [
        ("Application vetted (affordability, credit, TPN)", bool(l["application_id"] and db.val("SELECT credit_score FROM applications WHERE id=?", l["application_id"]))),
        ("Lease signed by tenant", bool(l["tenant_sig"])),
        ("Lease signed by landlord / agent", bool(l["landlord_sig"])),
        ("Deposit received into interest-bearing trust account", sv.balance("deposit", lid, kinds=["deposit_received"]) >= (l["deposit"] or 0) > 0),
        ("Joint ingoing inspection signed", bool(db.val("SELECT 1 FROM inspections WHERE lease_id=? AND type='ingoing' AND status='final'", lid))),
        ("Rental insurance active", bool(l["property"]["insured"])),
        ("Keys handed over (recorded in ingoing)", bool(db.val("SELECT 1 FROM insp_items i JOIN insp_rooms r ON r.id=i.room_id JOIN inspections x ON x.id=i.inspection_id WHERE x.lease_id=? AND r.name='Keys & meters' AND i.condition IS NOT NULL", lid))),
    ]
    if l["status"] in ("ended",) or db.val("SELECT 1 FROM inspections WHERE lease_id=? AND type='outgoing'", lid):
        steps += [("Joint outgoing inspection signed", bool(db.val("SELECT 1 FROM inspections WHERE lease_id=? AND type='outgoing' AND status='final'", lid))),
                  ("Deposit refunded with interest and breakdown", bool(db.val("SELECT 1 FROM ledger WHERE lease_id=? AND kind='deposit_refund'", lid)))]
    return [{"step": s, "done": d} for s, d in steps]


@r.post("/leases")
async def lease_create(request: Request, u=Depends(role(*OFFICE))):
    """Load an existing tenancy, or let directly to a known tenant."""
    b = await body(request)
    pid = int(b["property_id"])
    can_prop(u, pid, True)
    tid = num(b.get("tenant_id"), int) or ensure_user(b["tenant_email"], b.get("tenant_name"), "tenant", u)
    lid = sv.make_lease(pid, tid, b.get("start_date") or db.today(), int(b.get("months") or 12), num(b.get("rent"), int), None,
                        float(b.get("escalation") or 8))
    return {"id": lid}


@r.post("/leases/{lid}/sign")
async def lease_sign(lid: int, request: Request, u=Depends(user)):
    b = await body(request)
    if not (b.get("sig") or "").startswith("data:image"):
        raise HTTPException(400, "Draw your signature first")
    return sv.sign_lease(lid, u, b["sig"])


@r.post("/leases/{lid}/renew")
async def lease_renew(lid: int, request: Request, u=Depends(role(*OFFICE))):
    l = db.q1("SELECT * FROM leases WHERE id=?", lid)
    can_prop(u, l["property_id"], True)
    b = await body(request)
    start = (date.fromisoformat(l["end_date"]) + timedelta(days=1)).isoformat()
    rent = num(b.get("rent"), int) or round(l["rent"] * (1 + (l["escalation_pct"] or 0) / 100) / 10) * 10
    nid = sv.make_lease(l["property_id"], l["tenant_id"], start, int(b.get("months") or 12), rent, None, l["escalation_pct"], renewal_of=lid)
    sv.close_tasks(f"renewal:{lid}")
    return {"id": nid}


@r.post("/leases/{lid}/notice")
async def lease_notice(lid: int, request: Request, u=Depends(user)):
    l = db.q1("SELECT * FROM leases WHERE id=?", lid)
    if u["id"] != l["tenant_id"] and u["role"] not in OFFICE:
        raise HTTPException(403)
    b = await body(request)
    d = date.today()
    bd = 0
    while bd < 20:
        d += timedelta(days=1)
        if d.weekday() < 5:
            bd += 1
    end = max(b.get("end_date") or "", d.isoformat())
    db.upd("leases", lid, end_date=end)
    p = sv.prop(l["property_id"])
    sv.task(p["pm_id"], p["id"], "renewal", f"Notice given – {p['title']}", f"Lease now ends {end}. Re-list the property.", f"#/app/property/{p['id']}", 1, dedupe=f"notice:{lid}")
    sv.notify(p["landlord_id"], "Tenant gave notice", f"{p['title']} – ends {end}", f"#/app/property/{p['id']}", "lease")
    return {"end_date": end}


# =================================================================== money
@r.get("/money/summary")
def money_summary(u=Depends(role(*OFFICE))):
    ids = prop_ids(u)
    per = sv.period()
    rows = db.q(f"SELECT l.*, p.title, u.name tenant_name, u.phone tenant_phone FROM leases l JOIN properties p ON p.id=l.property_id JOIN users u ON u.id=l.tenant_id WHERE l.status='active' AND l.property_id IN {in_list(ids)} ORDER BY p.title")
    for l in rows:
        l["balance"] = sv.balance("tenant", l["id"])
        l["paid_month"] = -(db.val("SELECT COALESCE(SUM(amount),0) FROM ledger WHERE lease_id=? AND kind='payment' AND period=?", l["id"], per) or 0)
        l["deposit_held"] = sv.balance("deposit", l["id"])
        l["ref"] = f"AVA{l['id']:05d}"
        l["terms"] = None
        l["state"] = "paid" if l["balance"] <= 0 else ("partial" if l["paid_month"] > 0 else "unpaid")
    return {"period": per, "kpis": kpis(ids), "rent_roll": rows,
            "payments": db.q(f"SELECT pay.*, p.title, u.name tenant_name FROM payments pay JOIN leases l ON l.id=pay.lease_id JOIN properties p ON p.id=l.property_id JOIN users u ON u.id=l.tenant_id WHERE l.property_id IN {in_list(ids)} ORDER BY pay.id DESC LIMIT 50")}


@r.post("/payments")
async def payment_add(request: Request, u=Depends(role(*OFFICE))):
    b = await body(request)
    l = db.q1("SELECT * FROM leases WHERE id=?", int(b["lease_id"]))
    can_prop(u, l["property_id"], True)
    amt = money(b.get("amount"))
    if not amt or amt <= 0:
        raise HTTPException(400, "Enter the amount received")
    return {"id": sv.record_payment(l["id"], amt, b.get("method") or "eft", b.get("reference") or "", u["id"], b.get("date") or None)}


@r.post("/payments/import")
async def payments_import(request: Request, u=Depends(role(*OFFICE))):
    """Bank statement CSV (date, description/reference, amount). Lines with AVA00012-style references are matched and allocated."""
    b = await body(request)
    f = (b["_files"].get("file") or [None])[0]
    if not f:
        raise HTTPException(400, "Choose the CSV exported from online banking")
    text = (await f.read()).decode("utf-8", "ignore")
    ids = set(prop_ids(u))
    matched, unmatched = [], []
    for row in csv.reader(io.StringIO(text)):
        line = " ".join(row)
        m = re.search(r"AVA\s?0*(\d+)", line, re.I)
        amts = [float(x.replace(",", "").replace(" ", "")) for x in row if re.fullmatch(r"\s*-?[\d\s,]+\.\d{2}\s*", x)]
        dt = next((x for x in row if re.fullmatch(r"\d{4}-\d{2}-\d{2}", x.strip())), None)
        if not amts:
            continue
        amt = amts[-1]
        if amt <= 0:
            continue
        l = db.q1("SELECT * FROM leases WHERE id=?", int(m.group(1))) if m else None
        if l and l["property_id"] in ids:
            if db.val("SELECT 1 FROM payments WHERE lease_id=? AND amount=? AND reference=?", l["id"], amt, line[:80]):
                continue
            sv.record_payment(l["id"], amt, "eft", line[:80], u["id"], dt)
            matched.append({"lease_id": l["id"], "amount": amt, "line": line[:80]})
        else:
            unmatched.append({"amount": amt, "line": line[:80]})
    return {"matched": matched, "unmatched": unmatched}


@r.post("/pay/start")
async def pay_start(request: Request, u=Depends(user)):
    b = await body(request)
    l = db.q1("SELECT * FROM leases WHERE id=?", int(b["lease_id"]))
    if not l or (u["role"] == "tenant" and l["tenant_id"] != u["id"]):
        raise HTTPException(403)
    amt = db.rands(b.get("amount") or 0)
    if amt <= 0:
        raise HTTPException(400, "Nothing to pay")
    pay_id = db.ins("payments", lease_id=l["id"], amount=amt, method="payfast", status="pending", created_by=u["id"], reference=f"AVA{l['id']:05d}")
    mid, mkey = fees.S("payfast_merchant_id"), fees.S("payfast_merchant_key")
    if not (mid and mkey):
        return {"mode": "simulated", "payment_id": pay_id}
    base = fees.S("public_url") or str(request.base_url).rstrip("/")
    data = {"merchant_id": mid, "merchant_key": mkey, "return_url": f"{base}/#/app/pay?done=1", "cancel_url": f"{base}/#/app/pay",
            "notify_url": f"{base}/api/payfast/itn", "name_first": u["name"].split()[0], "email_address": u["email"],
            "m_payment_id": str(pay_id), "amount": f"{amt:.2f}", "item_name": f"Rent AVA{l['id']:05d}"}
    data["signature"] = payfast_sig(data)
    url = "https://sandbox.payfast.co.za/eng/process" if fees.S("payfast_sandbox") else "https://www.payfast.co.za/eng/process"
    return {"mode": "payfast", "url": url, "fields": data}


def payfast_sig(data):
    s = "&".join(f"{k}={quote_plus(str(v).strip())}" for k, v in data.items() if v not in ("", None) and k != "signature")
    if fees.S("payfast_passphrase"):
        s += f"&passphrase={quote_plus(fees.S('payfast_passphrase'))}"
    return md5(s.encode()).hexdigest()


@r.post("/payfast/itn")
async def payfast_itn(request: Request):
    f = dict((await request.form()).items())
    if payfast_sig({k: v for k, v in f.items()}) != f.get("signature"):
        raise HTTPException(400, "Bad signature")
    pay = db.q1("SELECT * FROM payments WHERE id=?", int(f.get("m_payment_id", 0)))
    if pay and pay["status"] == "pending" and f.get("payment_status") == "COMPLETE":
        if (pay["reference"] or "").startswith("SUB"):
            from . import marketplace
            db.upd("payments", pay["id"], status="complete", gateway_id=f.get("pf_payment_id", ""))
            marketplace.extend_subscription(int(pay["reference"][3:]), 1, float(f.get("amount_gross", pay["amount"])), f.get("pf_payment_id", ""))
        else:
            db.exe("DELETE FROM payments WHERE id=?", pay["id"])
            sv.record_payment(pay["lease_id"], float(f.get("amount_gross", pay["amount"])), "payfast", f.get("pf_payment_id", ""))
    return Response("OK")


@r.post("/pay/simulate/{pay_id}")
def pay_simulate(pay_id: int, u=Depends(user)):
    pay = db.q1("SELECT * FROM payments WHERE id=? AND status='pending'", pay_id)
    if not pay:
        raise HTTPException(404)
    if fees.S("payfast_merchant_id"):
        raise HTTPException(400, "Live payments are configured")
    db.exe("DELETE FROM payments WHERE id=?", pay_id)
    return {"id": sv.record_payment(pay["lease_id"], pay["amount"], "card", f"SIM-{pay_id}", u["id"])}


@r.get("/money/payouts")
def payouts(period: str = "", u=Depends(role(*OFFICE))):
    per = period or (date.today().replace(day=1) - timedelta(days=1)).isoformat()[:7]
    out = []
    for p in db.q(f"SELECT * FROM properties WHERE id IN {in_list(prop_ids(u))} AND kind='rental' ORDER BY title"):
        rent_in = db.val("SELECT COALESCE(SUM(amount),0) FROM ledger WHERE property_id=? AND account='owner' AND kind='rent_received' AND period=?", p["id"], per) or 0
        paid = -(db.val("SELECT COALESCE(SUM(amount),0) FROM ledger WHERE property_id=? AND kind='payout' AND period=?", p["id"], per) or 0)
        if not rent_in and not paid:
            continue
        est = fees.landlord_monthly(rent_in, p["landlord_id"], p["pm_id"], p["insured"]) if rent_in and not paid else None
        out.append({"property_id": p["id"], "title": p["title"], "landlord": db.val("SELECT name FROM users WHERE id=?", p["landlord_id"]),
                    "rent_in": rent_in, "balance": sv.balance("owner", property_id=p["id"]), "paid": paid,
                    "fees_est": est["total"] if est else None})
    return {"period": per, "rows": out}


@r.post("/money/payouts/run")
async def payouts_run(request: Request, u=Depends(role(*STAFF))):
    b = await body(request)
    per = b.get("period") or (date.today().replace(day=1) - timedelta(days=1)).isoformat()[:7]
    ids = b.get("property_ids") or [x["property_id"] for x in payouts(per, u)["rows"] if not x["paid"]]
    res = [x for x in (sv.payout_run(int(pid), per) for pid in ids if int(pid) in prop_ids(u)) if x]
    from . import trust
    trust.queue_owner_payouts(u)      # the money leaves the trust account when the payment batch is released
    if u["role"] == "pm":
        sv.close_tasks(f"payout:{u['id']}:{per}")
    return {"period": per, "results": res}


@r.get("/statement/{pid}/{per}")
def statement(pid: int, per: str, u=Depends(role(*OFFICE))):
    can_prop(u, pid)
    s = sv.statement(pid, per)
    s["landlord"] = db.q1("SELECT name, email, company FROM users WHERE id=?", s["property"]["landlord_id"])
    return s


@r.get("/money/earnings")
def earnings(u=Depends(role(*STAFF))):
    w = "" if u["role"] == "admin" else f" AND property_id IN {in_list(prop_ids(u))}"
    pm = db.q(f"SELECT period, kind, SUM(amount) amount FROM ledger WHERE account='pm' {w} GROUP BY period, kind ORDER BY period DESC LIMIT 36")
    ava = db.q("SELECT period, SUM(amount) amount FROM ledger WHERE account='ava' GROUP BY period ORDER BY period DESC LIMIT 12") if u["role"] == "admin" else []
    managed = fees.pm_managed_count(u["id"]) if u["role"] == "pm" else None
    return {"pm": pm, "ava": ava, "managed": managed, "commission_pct": fees.pm_commission_pct(u["id"]) if u["role"] == "pm" else None,
            "targets": [{"month": 3, "rented": 10}, {"month": 6, "rented": 25}, {"month": 9, "rented": 45}, {"month": 12, "rented": 70}],
            "rented": db.val(f"SELECT COUNT(*) FROM leases WHERE status='active' {w}"),
            "book": commission_book(u), "payout_day": fees.S("payout_day"), "finders_fee": fees.S("finders_fee")}


def commission_book(u):
    """What each portfolio manager earns: commission % of the rent collected on every let home + the finder's fee, per month."""
    pms = [u] if u["role"] == "pm" else db.q("SELECT * FROM users WHERE role='pm' AND active=1 ORDER BY name")
    out = []
    for pm in pms:
        pct = fees.pm_commission_pct(pm["id"])
        n = fees.pm_managed_count(pm["id"])
        tiers = fees.S("pm_tiers")
        nxt = None
        if fees.S("pm_commission_mode") == "tiered":
            i = next((k for k, (upto, _) in enumerate(tiers) if n <= upto), len(tiers) - 1)
            if i < len(tiers) - 1:
                nxt = (tiers[i][0] + 1, tiers[i + 1][1])     # homes needed for the next tier, and its rate
        rows = []
        for p in db.q("""SELECT p.id, p.title, p.suburb, p.city, p.rent asking, p.listing_status, l.rent lease_rent, l.id lease_id
                         FROM properties p LEFT JOIN leases l ON l.property_id=p.id AND l.status='active'
                         WHERE p.pm_id=? AND p.kind='rental' AND p.listing_status!='draft' ORDER BY (l.id IS NULL), p.title""", pm["id"]):
            let = p["lease_rent"] is not None
            rent = p["lease_rent"] if let else p["asking"]
            com = db.rands(rent * pct / 100)
            rows.append({"id": p["id"], "title": p["title"], "area": f"{p['suburb']}, {p['city']}", "let": let, "rent": rent,
                         "commission": com, "finders_fee": fees.S("finders_fee"), "month": com + fees.S("finders_fee")})
        let_rows = [r for r in rows if r["let"]]
        month = sum(r["month"] for r in let_rows)
        potential = sum(r["month"] for r in rows)
        roll = sum(r["rent"] for r in let_rows)
        up = None
        if nxt:
            gain = sum(db.rands(r["rent"] * nxt[1] / 100) - r["commission"] for r in let_rows)
            up = {"homes": nxt[0], "more": nxt[0] - n, "pct": nxt[1], "extra_month": gain}
        out.append({"pm_id": pm["id"], "name": pm["name"], "region": pm.get("company"), "pct": pct, "homes": n, "let": len(let_rows),
                    "rent_roll": roll, "commission_month": sum(r["commission"] for r in let_rows), "finders_month": fees.S("finders_fee") * len(let_rows),
                    "month": month, "year": month * 12, "potential_month": potential, "potential_year": potential * 12, "next_tier": up, "rows": rows})
    return out


# =================================================================== maintenance
def ticket_scope(u):
    if u["role"] == "contractor":
        return f"(t.contractor_id={u['id']} OR t.id IN (SELECT ticket_id FROM quotes WHERE contractor_id={u['id']}))"
    if u["role"] == "tenant":
        return f"(t.reported_by={u['id']} OR t.lease_id IN (SELECT id FROM leases WHERE tenant_id={u['id']}))"
    return f"t.property_id IN {in_list(prop_ids(u))}"


@r.get("/tickets")
def tickets(u=Depends(user), status: str = "", property_id: int = 0):
    sql = f"""SELECT t.*, p.title ptitle, p.suburb, c.name contractor_name, c.company contractor_company,
              (SELECT COUNT(*) FROM quotes q WHERE q.ticket_id=t.id AND q.status IN ('submitted','shortlisted')) quotes_in
              FROM tickets t JOIN properties p ON p.id=t.property_id LEFT JOIN users c ON c.id=t.contractor_id WHERE {ticket_scope(u)}"""
    if status == "open":
        sql += " AND t.status NOT IN ('closed','cancelled')"
    elif status:
        sql += f" AND t.status='{re.sub('[^a-z_]', '', status)}'"
    if property_id:
        sql += f" AND t.property_id={int(property_id)}"
    return db.q(sql + " ORDER BY CASE t.priority WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, t.id DESC LIMIT 300")


@r.post("/tickets")
async def ticket_create(request: Request, u=Depends(user)):
    b = await body(request)
    pid = num(b.get("property_id"), int)
    if u["role"] == "tenant" and not pid:
        pid = db.val("SELECT property_id FROM leases WHERE tenant_id=? AND status='active' ORDER BY id DESC LIMIT 1", u["id"])
    if not pid:
        raise HTTPException(400, "Choose the property")
    can_prop(u, pid)
    if not (b.get("title") or "").strip():
        raise HTTPException(400, "Describe the problem in a few words")
    photos = await save_files(b["_files"].get("photos"), "tickets")
    tid = sv.create_ticket(u, pid, b["title"].strip(), b.get("description") or "", b.get("room") or "", photos,
                           "tenant" if u["role"] == "tenant" else "pm", b.get("priority") or None)
    return ticket_get(tid, u)


@r.get("/tickets/{tid}")
def ticket_get(tid: int, u=Depends(user)):
    t = db.q1(f"SELECT t.* FROM tickets t WHERE t.id=? AND {ticket_scope(u)}", tid)
    if not t:
        raise HTTPException(404, "Request not found")
    t["property"] = {k: v for k, v in sv.prop(t["property_id"]).items() if k in ("id", "title", "address", "suburb", "city", "lat", "lng", "landlord_id", "pm_id")}
    booked = u["role"] != "contractor" or t["contractor_id"] == u["id"]
    if not booked:   # quoting companies see the suburb only: no address, exact pin or tenant details until the owner books them
        t["property"]["address"] = t["property"]["suburb"] + " (full address after approval)"
        t["property"]["lat"] = round(t["property"]["lat"], 2) if t["property"].get("lat") is not None else None
        t["property"]["lng"] = round(t["property"]["lng"], 2) if t["property"].get("lng") is not None else None
        t["property"]["title"] = f"Home in {t['property']['suburb']}"
    t["booked"] = booked
    hide = u["role"] in ("tenant", "contractor")
    t["events"] = db.q(f"SELECT e.*, u.name user_name, u.role user_role FROM ticket_events e LEFT JOIN users u ON u.id=e.user_id WHERE ticket_id=? {'AND internal=0' if hide else ''} ORDER BY e.id", tid)
    if not booked:
        for e in t["events"]:
            if e.get("user_role") in ("tenant", "landlord"):
                e["user_name"] = "Tenant" if e["user_role"] == "tenant" else "Owner"
    qs = db.q("""SELECT q.*, u.name contractor_name, u.company,
                 (SELECT ROUND(AVG(rating),1) FROM reviews r WHERE r.target_type='contractor' AND r.target_id=q.contractor_id AND r.status='published') rating,
                 (SELECT COUNT(*) FROM reviews r WHERE r.target_type='contractor' AND r.target_id=q.contractor_id AND r.status='published') reviews,
                 (SELECT COUNT(*) FROM tickets x WHERE x.contractor_id=q.contractor_id AND x.status IN ('completed','closed')) jobs_done,
                 c.years, c.insured, c.vetted, c.bee_level
                 FROM quotes q JOIN users u ON u.id=q.contractor_id LEFT JOIN contractors c ON c.user_id=q.contractor_id WHERE ticket_id=? ORDER BY q.rank_score DESC, q.amount""", tid)
    t["quotes"] = [q for q in qs if u["role"] in OFFICE or q["contractor_id"] == u["id"]]
    t["contractor"] = db.q1("SELECT id, name, company, phone FROM users WHERE id=?", t["contractor_id"]) if t["contractor_id"] else None
    if t["lease_id"] and u["role"] != "tenant" and booked:
        t["tenant"] = db.q1("SELECT u.id, u.name, u.phone FROM leases l JOIN users u ON u.id=l.tenant_id WHERE l.id=?", t["lease_id"])
    t["can"] = ticket_caps(t, u)
    t["review"] = db.q1("SELECT * FROM reviews WHERE ticket_id=? AND author_id=?", tid, u["id"])
    t["suggested"] = ai.best_contractors(t["trade"], None, 5) if u["role"] in STAFF else []
    if u["role"] in OFFICE and t["property"].get("lat") is not None:
        from . import marketplace
        radius = t.get("radius_km") or fees.S("quote_radius_km")
        asked = {q["contractor_id"]: q["status"] for q in qs}
        cands = marketplace.candidates(t["trade"], t["property"]["lat"], t["property"]["lng"], also=tuple(asked))
        t["map"] = {"radius": radius, "steps": [s for s in fees.S("widen_steps_km") if s > radius],
                    "next": marketplace.next_radius(t["trade"], t["property"]["lat"], t["property"]["lng"], radius, tuple(asked)),
                    "companies": [{**c, "asked": c["id"] in asked, "quote_status": asked.get(c["id"])} for c in cands
                                  if c["distance_km"] is not None and (c["distance_km"] <= max(radius * 3, 60) or c["id"] in asked)][:40]}
    return t


def ticket_caps(t, u):
    r_, s = u["role"], t["status"]
    mine_q = next((q for q in t.get("quotes", []) if q["contractor_id"] == u["id"]), None)
    return {
        "approve": (r_ in ("landlord", "admin") or (r_ == "pm" and not fees.S("owner_chooses_quote")) or (r_ == "pm" and not t["property"].get("landlord_id")))
                   and s in ("awaiting_approval", "quoting") and any(q["status"] in ("shortlisted", "submitted") for q in t.get("quotes", [])),
        "compare": r_ in OFFICE and any(q["status"] in ("shortlisted", "submitted") for q in t.get("quotes", [])) and s in ("awaiting_approval", "quoting"),
        "rate": r_ in ("tenant", "landlord") and s in ("completed", "closed") and bool(t.get("contractor_id")),
        "issue": (r_ == "contractor" and t["contractor_id"] == u["id"] or r_ in STAFF) and s in ("approved", "scheduled", "in_progress"),
        "variation": r_ in ("landlord", "admin") or (r_ == "pm" and (not fees.S("owner_chooses_quote") or not t["property"].get("landlord_id"))),
        "quote": r_ == "contractor" and mine_q is not None and mine_q["status"] in ("requested", "submitted") and s in ("quoting", "awaiting_approval"),
        "schedule": (r_ == "contractor" and t["contractor_id"] == u["id"] or r_ in STAFF) and s in ("approved", "scheduled"),
        "start": (r_ == "contractor" and t["contractor_id"] == u["id"] or r_ in STAFF) and s in ("approved", "scheduled"),
        "complete": (r_ == "contractor" and t["contractor_id"] == u["id"] or r_ in STAFF) and s in ("approved", "scheduled", "in_progress"),
        "close": (r_ in ("tenant",) + STAFF) and s == "completed",
        "widen": r_ in OFFICE and s in ("new", "quoting", "awaiting_approval") and not t.get("contractor_id"),
        "manage": r_ in STAFF,
        "info": r_ in ("contractor",) + STAFF and s not in ("closed", "cancelled"),
        "reply": s not in ("closed", "cancelled"),
    }


@r.post("/tickets/{tid}/widen")
async def ticket_widen(tid: int, request: Request, u=Depends(role(*OFFICE))):
    t = ticket_get(tid, u)
    if not t["can"]["widen"]:
        raise HTTPException(403, "The range can't be changed on this job")
    b = await body(request)
    return sv.widen(tid, b.get("radius") or 25, u)


@r.put("/tickets/{tid}")
async def ticket_update(tid: int, request: Request, u=Depends(role(*STAFF))):
    t = db.q1("SELECT * FROM tickets WHERE id=?", tid)
    can_prop(u, t["property_id"], True)
    b = await body(request)
    kw = {k: b[k] for k in ("priority", "responsible", "deduct_from_rent", "category", "trade", "status", "title", "cost") if k in b}
    db.upd("tickets", tid, **kw)
    sv.event(tid, u["id"], "update", "Updated " + ", ".join(f"{k} → {v}" for k, v in kw.items()), internal=1)
    return ticket_get(tid, u)


@r.post("/tickets/{tid}/event")
async def ticket_event(tid: int, request: Request, u=Depends(user)):
    t = ticket_get(tid, u)
    b = await body(request)
    photos = await save_files(b["_files"].get("photos"), "tickets")
    text = (b.get("text") or "").strip()
    if not text and not photos:
        raise HTTPException(400, "Write a message or add a photo")
    internal = flag(b.get("internal")) if u["role"] in STAFF else 0
    sv.event(tid, u["id"], "comment", text, photos[0] if photos else None, internal)
    for ph in photos[1:]:
        sv.event(tid, u["id"], "photo", "", ph, internal)
    if t["status"] == "info_needed" and u["role"] in ("tenant", "landlord"):
        db.upd("tickets", tid, status="approved" if t["contractor_id"] else "quoting")
    if ai.sentiment(text) == "negative" and u["role"] == "tenant":
        p = sv.prop(t["property_id"])
        sv.task(p["pm_id"], p["id"], "escalation", f"Frustrated tenant: {t['title']}", text[:140], f"#/app/ticket/{tid}", 1, dedupe=f"sent:{tid}:{db.today()}")
        db.upd("tickets", tid, sentiment="negative")
    others = {t["property"]["pm_id"], t["contractor_id"]} | ({t.get("tenant", {}) and t["tenant"]["id"]} if t.get("tenant") else set())
    if t["lease_id"] and u["role"] != "tenant":
        others.add(db.val("SELECT tenant_id FROM leases WHERE id=?", t["lease_id"]))
    for o in others - {u["id"], None}:
        if internal and db.val("SELECT role FROM users WHERE id=?", o) not in STAFF:
            continue
        sv.notify(o, f"{t['ref']}: new message", text[:80], f"#/app/ticket/{tid}", "maintenance")
    return ticket_get(tid, u)


@r.post("/tickets/{tid}/request-info")
async def ticket_info(tid: int, request: Request, u=Depends(user)):
    t = ticket_get(tid, u)
    if not t["can"]["info"]:
        raise HTTPException(403)
    b = await body(request)
    who = b.get("to") or "tenant"
    db.upd("tickets", tid, status="info_needed")
    sv.event(tid, u["id"], "info_request", f"More information needed from the {who}: {b.get('text', '')}")
    target = db.val("SELECT tenant_id FROM leases WHERE id=?", t["lease_id"]) if who == "tenant" and t["lease_id"] else t["property"]["landlord_id"]
    sv.notify(target, f"{t['ref']}: more info needed", b.get("text", ""), f"#/app/ticket/{tid}", "maintenance")
    return ticket_get(tid, u)


@r.post("/tickets/{tid}/quotes")
async def quote_submit(tid: int, request: Request, u=Depends(role("contractor"))):
    q = db.q1("SELECT * FROM quotes WHERE ticket_id=? AND contractor_id=?", tid, u["id"])
    if not q or q["status"] not in ("requested", "submitted"):
        raise HTTPException(400, "This quote request is closed")
    b = await body(request)
    amt = money(b.get("amount"))
    if not amt or amt <= 0:
        raise HTTPException(400, "Enter your quote amount (incl. VAT if registered)")
    files = await save_files(b["_files"].get("file"), "quotes")
    db.upd("quotes", q["id"], amount=amt, eta_days=num(b.get("eta_days"), int, 2), notes=b.get("notes"), file=files[0] if files else q["file"],
           status="submitted", submitted_at=db.now())
    sv.event(tid, u["id"], "quote", f"Quote submitted: R{amt:,.0f}, {num(b.get('eta_days'), int, 2)} day(s)", internal=1)
    if not db.val("SELECT 1 FROM quotes WHERE ticket_id=? AND status='requested'", tid):
        sv.shortlist(tid)
    return ticket_get(tid, u)


@r.post("/tickets/{tid}/request-quotes")
async def quotes_request(tid: int, request: Request, u=Depends(role(*STAFF))):
    t = ticket_get(tid, u)
    b = await body(request)
    for cid in b.get("contractor_ids") or []:
        if not db.val("SELECT 1 FROM quotes WHERE ticket_id=? AND contractor_id=?", tid, cid):
            db.ins("quotes", ticket_id=tid, contractor_id=int(cid), status="requested")
            sv.notify(int(cid), "Quote requested", t["title"], f"#/app/ticket/{tid}", "quote")
    deadline = (datetime.now() + timedelta(hours=fees.S("quote_window_hours"))).isoformat(timespec="minutes")
    db.upd("tickets", tid, status="quoting", quote_deadline=deadline)
    sv.event(tid, u["id"], "rfq", "Quotes requested manually")
    return ticket_get(tid, u)


@r.post("/tickets/{tid}/shortlist")
def ticket_shortlist(tid: int, u=Depends(role(*STAFF))):
    ticket_get(tid, u)
    if not sv.shortlist(tid):
        raise HTTPException(400, "No quotes submitted yet")
    return ticket_get(tid, u)


@r.post("/tickets/{tid}/approve")
async def ticket_approve(tid: int, request: Request, u=Depends(role(*OFFICE))):
    ticket_get(tid, u)
    b = await body(request)
    sv.approve_quote(tid, int(b["quote_id"]), u)
    return ticket_get(tid, u)


@r.post("/tickets/{tid}/assign")
async def ticket_assign(tid: int, request: Request, u=Depends(role(*STAFF))):
    t = ticket_get(tid, u)
    b = await body(request)
    cid = int(b["contractor_id"])
    db.upd("tickets", tid, contractor_id=cid, status="approved", cost=money(b.get("cost")))
    c = db.q1("SELECT name, company FROM users WHERE id=?", cid)
    sv.event(tid, u["id"], "assigned", f"Assigned directly to {c['company'] or c['name']}")
    sv.notify(cid, "New job assigned", t["title"], f"#/app/ticket/{tid}", "maintenance")
    return ticket_get(tid, u)


@r.post("/tickets/{tid}/status")
async def ticket_status(tid: int, request: Request, u=Depends(user)):
    t = ticket_get(tid, u)
    b = await body(request)
    st = b.get("status")
    can = t["can"]
    if st == "scheduled" and can["schedule"]:
        db.upd("tickets", tid, status="scheduled", scheduled_for=b.get("scheduled_for"))
        sv.event(tid, u["id"], "scheduled", f"Booked for {(b.get('scheduled_for') or '').replace('T', ' ')}")
        if t["lease_id"]:
            sv.notify(db.val("SELECT tenant_id FROM leases WHERE id=?", t["lease_id"]), "Repair booked", f"{t['title']} – {(b.get('scheduled_for') or '').replace('T', ' ')}", f"#/app/ticket/{tid}", "maintenance")
    elif st == "in_progress" and can["start"]:
        db.upd("tickets", tid, status="in_progress")
        sv.event(tid, u["id"], "started", "Contractor on site – work started")
    elif st == "cancelled" and can["manage"]:
        db.upd("tickets", tid, status="cancelled")
        sv.event(tid, u["id"], "cancelled", b.get("note") or "Cancelled")
    elif st == "reopen" and (can["manage"] or u["role"] == "tenant"):
        db.upd("tickets", tid, status="approved" if t["contractor_id"] else "new")
        sv.event(tid, u["id"], "reopened", b.get("note") or "Not fixed – reopened")
    else:
        raise HTTPException(400, "That step isn't available now")
    return ticket_get(tid, u)


@r.post("/tickets/{tid}/complete")
async def ticket_complete(tid: int, request: Request, u=Depends(user)):
    t = ticket_get(tid, u)
    if not t["can"]["complete"]:
        raise HTTPException(403)
    b = await body(request)
    photos = await save_files(b["_files"].get("photos"), "tickets")
    if u["role"] == "contractor" and not photos:
        raise HTTPException(400, "Add at least one 'after' photo")
    sv.complete_ticket(tid, u, b.get("cost"), b.get("note") or "", photos)
    return ticket_get(tid, u)


def add_review(t, u, b):
    rating = num(b.get("rating"), int)
    if not rating or not t["contractor_id"]:
        return
    if db.val("SELECT 1 FROM reviews WHERE ticket_id=? AND author_id=?", t["id"], u["id"]):
        raise HTTPException(400, "You've already rated this job")
    crit = {k: num(b.get(k), int) for k in ("quality", "punctuality", "price_score", "communication")}
    db.ins("reviews", target_type="contractor", target_id=t["contractor_id"], author_id=u["id"], author_role=u["role"], rating=rating,
           text=(b.get("review") or "").strip() or None, ticket_id=t["id"], status="published" if rating >= 3 else "pending", **crit)
    sv.notify(t["contractor_id"], f"New {rating}★ review", (b.get("review") or "")[:80], "#/app/profile", "review")
    if rating < 3:
        for a_ in db.q("SELECT id FROM users WHERE role='admin'"):
            sv.notify(a_["id"], "Low rating to moderate", f"{t['ref']} rated {rating}/5", "#/app/reviews", "admin")


@r.post("/tickets/{tid}/close")
async def ticket_close(tid: int, request: Request, u=Depends(user)):
    t = ticket_get(tid, u)
    if not t["can"]["close"]:
        raise HTTPException(403)
    b = await body(request)
    sv.close_job(tid, u["id"])
    if u["role"] in ("tenant", "landlord"):
        add_review(t, u, b)
    return ticket_get(tid, u)


@r.post("/tickets/{tid}/issue")
async def ticket_issue(tid: int, request: Request, u=Depends(user)):
    t = ticket_get(tid, u)
    if not (u["role"] in STAFF or (u["role"] == "contractor" and t["contractor_id"] == u["id"])):
        raise HTTPException(403)
    b = await body(request)
    photos = await save_files(b["_files"].get("photos"), "tickets")
    audio = (await save_files(b["_files"].get("audio"), "voice") or [None])[0]
    if not (b.get("text") or "").strip() and not photos and not audio:
        raise HTTPException(400, "Add a photo, a voice note or a few words")
    sv.report_issue(tid, u, b.get("kind") or "other", (b.get("text") or "").strip(), money(b.get("extra_cost")), b.get("eta") or None, photos, audio)
    return ticket_get(tid, u)


@r.post("/tickets/{tid}/variation/{qid}")
async def ticket_variation(tid: int, qid: int, request: Request, u=Depends(role("landlord", "admin", "pm"))):
    t = ticket_get(tid, u)
    if u["role"] == "pm" and fees.S("owner_chooses_quote") and t["property"].get("landlord_id"):
        raise HTTPException(403, "The owner approves extra work")
    b = await body(request)
    sv.decide_variation(tid, qid, flag(b.get("accept")), u)
    return ticket_get(tid, u)


@r.post("/tickets/{tid}/review")
async def ticket_review(tid: int, request: Request, u=Depends(user)):
    t = ticket_get(tid, u)
    if not t["can"]["rate"]:
        raise HTTPException(403, "Only the tenant or owner can rate this job")
    add_review(t, u, await body(request))
    return ticket_get(tid, u)


# =================================================================== contractors & reviews
@r.get("/contractors")
def contractors(u=Depends(role(*STAFF))):
    rows = db.q("""SELECT u.id, u.name, u.email, u.phone, u.company, u.active, c.*,
                  (SELECT ROUND(AVG(rating),1) FROM reviews r WHERE r.target_type='contractor' AND r.target_id=u.id AND r.status='published') rating,
                  (SELECT COUNT(*) FROM reviews r WHERE r.target_type='contractor' AND r.target_id=u.id AND r.status='published') reviews,
                  (SELECT COUNT(*) FROM tickets t WHERE t.contractor_id=u.id AND t.status IN ('completed','closed')) jobs_done,
                  (SELECT COUNT(*) FROM tickets t WHERE t.contractor_id=u.id AND t.status IN ('approved','scheduled','in_progress')) jobs_open,
                  (SELECT ROUND(AVG(julianday(t.completed_at)-julianday(t.created_at)),1) FROM tickets t WHERE t.contractor_id=u.id AND t.completed_at IS NOT NULL) avg_days,
                  (SELECT COUNT(*) FROM snags s WHERE s.contractor_id=u.id AND s.status!='closed') snags_open
                  FROM users u JOIN contractors c ON c.user_id=u.id ORDER BY c.approved, u.company""")
    return rows


@r.post("/contractors")
async def contractor_add(request: Request, u=Depends(role(*STAFF))):
    b = await body(request)
    uid = ensure_user(b["email"], b.get("name"), "contractor", u)
    db.upd("users", uid, company=b.get("company"), phone=b.get("phone"))
    db.exe("INSERT OR IGNORE INTO contractors(user_id) VALUES(?)", uid)
    db.exe("UPDATE contractors SET trades=?, areas=?, approved=1, callout_fee=? WHERE user_id=?",
           json.dumps([t.strip() for t in (b.get("trades") or "Handyman").split(",") if t.strip()]),
           json.dumps([a.strip() for a in (b.get("areas") or "").split(",") if a.strip()]), num(b.get("callout_fee"), int, 0), uid)
    return {"id": uid, "temp_password": "ava12345"}


@r.put("/contractors/{cid}")
async def contractor_update(cid: int, request: Request, u=Depends(user)):
    if u["role"] not in STAFF and u["id"] != cid:
        raise HTTPException(403)
    b = await body(request)
    kw = {}
    for k in ("trades", "areas"):
        if k in b:
            kw[k] = json.dumps(b[k] if isinstance(b[k], list) else [x.strip() for x in b[k].split(",") if x.strip()])
    for k in ("callout_fee", "bio", "bee_level", "registration", "base_address", "website"):
        if k in b:
            kw[k] = b[k]
    for k in ("lat", "lng", "radius_km", "years"):
        if k in b:
            kw[k] = num(b[k])
    if "insured" in b:
        kw["insured"] = flag(b["insured"])
    if u["role"] in STAFF:
        for k in ("approved", "vetted"):
            if k in b:
                kw[k] = flag(b[k])
    if kw:
        db.exe(f"UPDATE contractors SET {','.join(k + '=?' for k in kw)} WHERE user_id=?", *kw.values(), cid)
    if kw.get("approved"):
        sv.notify(cid, "You're approved on AVA", "You'll now receive quote requests in your area.", "#/app", "admin")
    return {"ok": True}


@r.get("/contractors/{cid}/reviews")
def contractor_reviews(cid: int, u=Depends(user)):
    return db.q("SELECT r.*, u.name author FROM reviews r LEFT JOIN users u ON u.id=r.author_id WHERE target_type='contractor' AND target_id=? AND status='published' ORDER BY id DESC", cid)


@r.get("/reviews")
def reviews(u=Depends(role("admin")), status: str = "pending"):
    return db.q("SELECT r.*, a.name author, c.company, c.name cname FROM reviews r LEFT JOIN users a ON a.id=r.author_id LEFT JOIN users c ON c.id=r.target_id WHERE r.status=? ORDER BY r.id DESC", status)


@r.put("/reviews/{rid}")
async def review_mod(rid: int, request: Request, u=Depends(role("admin"))):
    b = await body(request)
    db.upd("reviews", rid, status=b.get("status", "published"))
    return {"ok": True}


# =================================================================== inspections
@r.get("/inspections")
def inspections(u=Depends(user), property_id: int = 0, type: str = ""):
    if u["role"] == "tenant":
        w = f"i.lease_id IN (SELECT id FROM leases WHERE tenant_id={u['id']})"
    else:
        w = f"i.property_id IN {in_list(prop_ids(u))}"
    sql = f"""SELECT i.*, p.title, p.suburb, p.kind pkind, u.name inspector,
              (SELECT COUNT(*) FROM insp_items it WHERE it.inspection_id=i.id) items,
              (SELECT COUNT(*) FROM insp_items it WHERE it.inspection_id=i.id AND it.condition IS NOT NULL) rated,
              (SELECT COUNT(*) FROM insp_rooms r WHERE r.inspection_id=i.id AND r.pano_url IS NOT NULL) panos,
              (SELECT COUNT(*) FROM snags s WHERE s.inspection_id=i.id) snags
              FROM inspections i JOIN properties p ON p.id=i.property_id LEFT JOIN users u ON u.id=i.inspector_id WHERE {w}"""
    if property_id:
        sql += f" AND i.property_id={int(property_id)}"
    if type == "rental":
        sql += " AND i.type IN ('ingoing','interim','outgoing')"
    elif type == "construction":
        sql += " AND i.type IN ('snag','handover','reinspection')"
    return db.q(sql + " ORDER BY i.status='final', i.date DESC, i.id DESC LIMIT 300")


@r.post("/inspections")
async def inspection_create(request: Request, u=Depends(role(*OFFICE))):
    b = await body(request)
    pid = int(b["property_id"])
    can_prop(u, pid, True)
    t = b.get("type") or "interim"
    if t not in ("ingoing", "interim", "outgoing", "snag", "handover", "reinspection"):
        raise HTTPException(400, "Unknown inspection type")
    lease_id = num(b.get("lease_id"), int) or (db.val("SELECT id FROM leases WHERE property_id=? AND status IN ('active','awaiting_signature') ORDER BY id DESC LIMIT 1", pid)
                                               if t in ("ingoing", "interim", "outgoing") else None)
    iid = sv.create_inspection(pid, t, lease_id, u["id"], b.get("date") or db.today())
    return {"id": iid}


@r.get("/inspections/{iid}")
def inspection_get(iid: int, u=Depends(user)):
    i = sv.inspection_full(iid)
    if u["role"] == "tenant":
        if not i["lease_id"] or db.val("SELECT tenant_id FROM leases WHERE id=?", i["lease_id"]) != u["id"]:
            raise HTTPException(403)
    elif u["role"] == "contractor":
        if not any(s["contractor_id"] == u["id"] for s in i["snags"]):
            raise HTTPException(403)
    else:
        can_prop(u, i["property_id"])
    i["can_edit"] = u["role"] in OFFICE and i["status"] != "final"
    i["contractors"] = db.q("SELECT u.id, u.name, u.company, c.trades FROM users u JOIN contractors c ON c.user_id=u.id WHERE c.approved=1 ORDER BY u.company") if u["role"] in OFFICE else []
    return i


@r.put("/inspections/{iid}")
async def inspection_update(iid: int, request: Request, u=Depends(role(*OFFICE))):
    i = db.q1("SELECT * FROM inspections WHERE id=?", iid)
    can_prop(u, i["property_id"], True)
    b = await body(request)
    kw = {k: b[k] for k in ("date", "summary", "tenant_present", "status") if k in b}
    if "tenant_present" in kw:
        kw["tenant_present"] = flag(kw["tenant_present"])
    db.upd("inspections", iid, **kw)
    return {"ok": True}


@r.delete("/inspections/{iid}")
def inspection_delete(iid: int, u=Depends(role(*OFFICE))):
    i = db.q1("SELECT * FROM inspections WHERE id=?", iid)
    can_prop(u, i["property_id"], True)
    if i["status"] == "final":
        raise HTTPException(400, "A signed inspection can't be deleted")
    db.exe("DELETE FROM insp_items WHERE inspection_id=?", iid)
    db.exe("DELETE FROM insp_rooms WHERE inspection_id=?", iid)
    db.exe("DELETE FROM inspections WHERE id=?", iid)
    return {"ok": True}


def _room_ctx(room_id, u):
    rm = db.q1("SELECT * FROM insp_rooms WHERE id=?", room_id)
    i = db.q1("SELECT * FROM inspections WHERE id=?", rm["inspection_id"])
    can_prop(u, i["property_id"], True)
    if i["status"] == "final":
        raise HTTPException(400, "This inspection is signed off and locked")
    return rm, i


@r.post("/inspections/{iid}/rooms")
async def room_add(iid: int, request: Request, u=Depends(role(*OFFICE))):
    i = db.q1("SELECT * FROM inspections WHERE id=?", iid)
    can_prop(u, i["property_id"], True)
    b = await body(request)
    name = (b.get("name") or "Room").strip()
    rid = db.ins("insp_rooms", inspection_id=iid, name=name, sort=(db.val("SELECT MAX(sort) FROM insp_rooms WHERE inspection_id=?", iid) or 0) + 1)
    if i["type"] in ("ingoing", "interim", "outgoing"):
        for j, it in enumerate(sv.items_for(name)):
            db.ins("insp_items", room_id=rid, inspection_id=iid, name=it, sort=j)
    return {"id": rid}


@r.put("/rooms/{rid}")
async def room_update(rid: int, request: Request, u=Depends(role(*OFFICE))):
    _room_ctx(rid, u)
    b = await body(request)
    db.upd("insp_rooms", rid, **{k: b[k] for k in ("name", "notes", "pano_yaw", "sort") if k in b})
    return {"ok": True}


@r.delete("/rooms/{rid}")
def room_delete(rid: int, u=Depends(role(*OFFICE))):
    _room_ctx(rid, u)
    db.exe("DELETE FROM insp_items WHERE room_id=?", rid)
    db.exe("DELETE FROM insp_rooms WHERE id=?", rid)
    return {"ok": True}


@r.post("/rooms/{rid}/pano")
async def room_pano(rid: int, request: Request, u=Depends(role(*OFFICE))):
    _room_ctx(rid, u)
    b = await body(request)
    urls = await save_files(b["_files"].get("file"), "panos")
    if not urls:
        raise HTTPException(400, "Choose a 360° photo (equirectangular JPG) or a frame from a 360 video")
    db.upd("insp_rooms", rid, pano_url=urls[0])
    return {"url": urls[0]}


@r.post("/rooms/{rid}/photos")
async def room_photos(rid: int, request: Request, u=Depends(role(*OFFICE))):
    rm, _ = _room_ctx(rid, u)
    b = await body(request)
    urls = await save_files(b["_files"].get("files"), "insp")
    db.upd("insp_rooms", rid, photos=(rm["photos"] or []) + urls)
    return {"photos": (rm["photos"] or []) + urls}


@r.post("/rooms/{rid}/items")
async def item_add(rid: int, request: Request, u=Depends(role(*OFFICE))):
    rm, i = _room_ctx(rid, u)
    b = await body(request)
    iid = db.ins("insp_items", room_id=rid, inspection_id=i["id"], name=(b.get("name") or "Item").strip(),
                 sort=(db.val("SELECT MAX(sort) FROM insp_items WHERE room_id=?", rid) or 0) + 1)
    return {"id": iid}


def _item_ctx(item_id, u):
    it = db.q1("SELECT * FROM insp_items WHERE id=?", item_id)
    _room_ctx(it["room_id"], u)
    return it


@r.put("/items/{item_id}")
async def item_update(item_id: int, request: Request, u=Depends(role(*OFFICE))):
    _item_ctx(item_id, u)
    b = await body(request)
    kw = {k: b[k] for k in ("name", "condition", "clean", "working", "notes", "pin", "charge", "charge_to", "photos") if k in b}
    if "charge" in kw:
        kw["charge"] = db.rands(kw["charge"]) if kw["charge"] not in (None, "") else None
    db.upd("insp_items", item_id, **kw)
    return db.q1("SELECT * FROM insp_items WHERE id=?", item_id)


@r.delete("/items/{item_id}")
def item_delete(item_id: int, u=Depends(role(*OFFICE))):
    _item_ctx(item_id, u)
    db.exe("DELETE FROM insp_items WHERE id=?", item_id)
    return {"ok": True}


@r.post("/items/{item_id}/photos")
async def item_photos(item_id: int, request: Request, u=Depends(role(*OFFICE))):
    it = _item_ctx(item_id, u)
    b = await body(request)
    urls = await save_files(b["_files"].get("files"), "insp")
    photos = (it["photos"] or []) + urls
    db.upd("insp_items", item_id, photos=photos)
    return {"photos": photos}


@r.post("/inspections/{iid}/sign")
async def inspection_sign(iid: int, request: Request, u=Depends(user)):
    i = db.q1("SELECT * FROM inspections WHERE id=?", iid)
    b = await body(request)
    sig = b.get("sig") or ""
    if not sig.startswith("data:image"):
        raise HTTPException(400, "Draw the signature first")
    who = b.get("who")
    if who == "tenant":
        if u["role"] == "tenant" and db.val("SELECT tenant_id FROM leases WHERE id=?", i["lease_id"]) != u["id"]:
            raise HTTPException(403)
        if u["role"] not in ("tenant",) + OFFICE:
            raise HTTPException(403)
        db.upd("inspections", iid, tenant_sig=sig, tenant_signed_at=db.now())
    elif who == "contractor":
        db.upd("inspections", iid, contractor_sig=sig, contractor_signed_at=db.now())
    else:
        can_prop(u, i["property_id"], True)
        db.upd("inspections", iid, agent_sig=sig, agent_signed_at=db.now())
    if i["status"] == "draft":
        db.upd("inspections", iid, status="awaiting_signatures")
    return {"ok": True}


@r.post("/inspections/{iid}/finalise")
def inspection_finalise(iid: int, u=Depends(role(*OFFICE))):
    i = db.q1("SELECT * FROM inspections WHERE id=?", iid)
    can_prop(u, i["property_id"], True)
    return {"tickets_created": sv.finalise_inspection(iid, u)}


@r.post("/inspections/{iid}/refund-deposit")
def inspection_refund(iid: int, u=Depends(role(*STAFF))):
    i = db.q1("SELECT * FROM inspections WHERE id=?", iid)
    can_prop(u, i["property_id"], True)
    if i["type"] != "outgoing" or i["status"] != "final":
        raise HTTPException(400, "Finalise the outgoing inspection first")
    sv.refund_deposit(iid, u)
    return {"ok": True}


# =================================================================== snags
def snag_scope(u):
    if u["role"] == "contractor":
        return f"s.contractor_id={u['id']}"
    return f"s.property_id IN {in_list(prop_ids(u))}"


@r.get("/snags")
def snags(u=Depends(user), property_id: int = 0, status: str = "", contractor_id: int = 0):
    sql = f"""SELECT s.*, p.title ptitle, c.company contractor_company, c.name contractor_name
              FROM snags s JOIN properties p ON p.id=s.property_id LEFT JOIN users c ON c.id=s.contractor_id WHERE {snag_scope(u)}"""
    if property_id:
        sql += f" AND s.property_id={int(property_id)}"
    if status == "open":
        sql += " AND s.status!='closed'"
    elif status == "overdue":
        sql += f" AND s.status!='closed' AND s.due_date<'{db.today()}'"
    elif status:
        sql += f" AND s.status='{re.sub('[^a-z_]', '', status)}'"
    if contractor_id:
        sql += f" AND s.contractor_id={int(contractor_id)}"
    return db.q(sql + " ORDER BY CASE s.status WHEN 'ready' THEN 0 WHEN 'open' THEN 1 WHEN 'in_progress' THEN 1 ELSE 2 END, s.due_date, s.id")


@r.get("/snags/metrics")
def snags_metrics(u=Depends(user), property_id: int = 0):
    ids = prop_ids(u)
    if property_id:
        ids = [property_id] if property_id in ids else []
    return sv.snag_metrics(ids)


@r.post("/snags")
async def snag_add(request: Request, u=Depends(role(*OFFICE))):
    b = await body(request)
    pid = int(b["property_id"])
    can_prop(u, pid, True)
    if not (b.get("title") or "").strip():
        raise HTTPException(400, "Describe the snag")
    photos = await save_files(b["_files"].get("photos"), "snags")
    pin = b.get("pin")
    if isinstance(pin, str) and pin:
        pin = json.loads(pin)
    sid = sv.add_snag(u, pid, num(b.get("inspection_id"), int), room=b.get("room"), room_id=num(b.get("room_id"), int), pin=pin or None,
                      title=b["title"].strip(), description=b.get("description"), trade=b.get("trade"),
                      contractor_id=num(b.get("contractor_id"), int), priority=b.get("priority") or "Medium",
                      category=b.get("category") or "Workmanship", qty=num(b.get("qty"), float, 1), unit=b.get("unit") or "no.",
                      rate=money(b.get("rate")), due_date=b.get("due_date") or None, photos_before=photos)
    return db.q1("SELECT * FROM snags WHERE id=?", sid)


@r.put("/snags/{sid}")
async def snag_update(sid: int, request: Request, u=Depends(role(*OFFICE))):
    s = db.q1("SELECT * FROM snags WHERE id=?", sid)
    can_prop(u, s["property_id"], True)
    b = await body(request)
    kw = {k: b[k] for k in ("title", "description", "trade", "contractor_id", "priority", "category", "qty", "unit", "rate", "due_date", "room", "pin", "status") if k in b}
    db.upd("snags", sid, **kw)
    if kw.get("contractor_id") and kw["contractor_id"] != s["contractor_id"]:
        sv.notify(int(kw["contractor_id"]), f"Snag {s['ref']} assigned to you", s["title"], f"#/app/snags/{s['property_id']}", "snag")
    return db.q1("SELECT * FROM snags WHERE id=?", sid)


@r.post("/snags/{sid}/photos")
async def snag_photos(sid: int, request: Request, u=Depends(user)):
    s = db.q1(f"SELECT s.* FROM snags s WHERE s.id=? AND {snag_scope(u)}", sid)
    if not s:
        raise HTTPException(404)
    b = await body(request)
    urls = await save_files(b["_files"].get("files"), "snags")
    col = "photos_after" if b.get("which") == "after" else "photos_before"
    db.upd("snags", sid, **{col: (s[col] or []) + urls})
    return db.q1("SELECT * FROM snags WHERE id=?", sid)


@r.post("/snags/{sid}/ready")
async def snag_ready(sid: int, request: Request, u=Depends(user)):
    s = db.q1(f"SELECT s.* FROM snags s WHERE s.id=? AND {snag_scope(u)}", sid)
    if not s:
        raise HTTPException(404)
    b = await body(request)
    urls = await save_files(b["_files"].get("photos"), "snags")
    if u["role"] == "contractor" and not urls and not s["photos_after"]:
        raise HTTPException(400, "Add an 'after' photo of the fix")
    db.upd("snags", sid, status="ready", ready_at=db.now(), contractor_note=b.get("note"), photos_after=(s["photos_after"] or []) + urls)
    p = sv.prop(s["property_id"])
    sv.notify(p["pm_id"], f"Snag {s['ref']} ready for re-inspection", s["title"], f"#/app/snags/{p['id']}", "snag")
    return db.q1("SELECT * FROM snags WHERE id=?", sid)


@r.post("/snags/{sid}/verify")
async def snag_verify(sid: int, request: Request, u=Depends(role(*OFFICE))):
    s = db.q1("SELECT * FROM snags WHERE id=?", sid)
    can_prop(u, s["property_id"], True)
    b = await body(request)
    urls = await save_files(b["_files"].get("photos"), "snags")
    if b.get("result") == "close":
        db.upd("snags", sid, status="closed", closed_at=db.now(), closed_by=u["id"], closed_inspection_id=num(b.get("inspection_id"), int),
               photos_after=(s["photos_after"] or []) + urls)
        sv.close_tasks(f"snagdue:{sid}")
        if s["contractor_id"]:
            sv.notify(s["contractor_id"], f"Snag {s['ref']} closed", s["title"], f"#/app/snags/{s['property_id']}", "snag")
    else:
        due = (date.today() + timedelta(days=fees.S("snag_due_days").get(s["priority"], 7))).isoformat()
        db.upd("snags", sid, status="open", rework_count=(s["rework_count"] or 0) + 1, due_date=due, ready_at=None,
               contractor_note=(b.get("note") or "Not accepted at re-inspection"), photos_before=(s["photos_before"] or []) + urls)
        if s["contractor_id"]:
            sv.notify(s["contractor_id"], f"Snag {s['ref']} rejected – rework", b.get("note") or s["title"], f"#/app/snags/{s['property_id']}", "snag")
    return db.q1("SELECT * FROM snags WHERE id=?", sid)


# =================================================================== messages & assistant
def threads_for(u):
    ids = prop_ids(u)
    if u["role"] == "tenant":
        keys = [f"lease:{l['id']}" for l in db.q("SELECT id FROM leases WHERE tenant_id=?", u["id"])]
    elif u["role"] == "landlord":
        keys = [f"owner:{pid}" for pid in ids]
    elif u["role"] in STAFF:
        keys = [f"lease:{l['id']}" for l in db.q(f"SELECT id FROM leases WHERE property_id IN {in_list(ids)}")] + [f"owner:{pid}" for pid in ids]
    else:
        keys = []
    return keys


def thread_title(key, u):
    kind, i = key.split(":")
    if kind == "lease":
        x = db.q1("SELECT p.title, u.name FROM leases l JOIN properties p ON p.id=l.property_id JOIN users u ON u.id=l.tenant_id WHERE l.id=?", int(i))
        return (f"{x['name']} · {x['title']}" if u["role"] != "tenant" else f"{x['title']} – your manager") if x else key
    if kind == "owner":
        x = db.q1("SELECT p.title, u.name FROM properties p LEFT JOIN users u ON u.id=p.landlord_id WHERE p.id=?", int(i))
        return (f"{x['name']} (owner) · {x['title']}" if u["role"] != "landlord" else f"{x['title']} – portfolio manager") if x else key
    return key


@r.get("/threads")
def threads(u=Depends(user)):
    out = []
    for k in threads_for(u):
        last = db.q1("SELECT * FROM messages WHERE thread=? ORDER BY id DESC LIMIT 1", k)
        if not last and u["role"] in STAFF:
            continue
        read = db.val("SELECT last_id FROM thread_reads WHERE thread=? AND user_id=?", k, u["id"]) or 0
        unread = db.val("SELECT COUNT(*) FROM messages WHERE thread=? AND id>? AND from_id!=?", k, read, u["id"])
        neg = db.val("SELECT 1 FROM messages WHERE thread=? AND id>? AND sentiment='negative'", k, read)
        out.append({"key": k, "title": thread_title(k, u), "last": last, "unread": unread, "flag": bool(neg)})
    return sorted(out, key=lambda x: (x["last"] or {}).get("id", 0), reverse=True)


@r.get("/threads/{key}")
def thread(key: str, u=Depends(user)):
    if key not in threads_for(u):
        raise HTTPException(403)
    msgs = db.q("SELECT m.*, u.name from_name, u.role from_role FROM messages m LEFT JOIN users u ON u.id=m.from_id WHERE thread=? ORDER BY id", key)
    for m in msgs:
        m["mine"] = m["from_id"] == u["id"]
    if msgs:
        db.exe("INSERT INTO thread_reads(thread,user_id,last_id) VALUES(?,?,?) ON CONFLICT(thread,user_id) DO UPDATE SET last_id=excluded.last_id", key, u["id"], msgs[-1]["id"])
    return {"key": key, "title": thread_title(key, u), "messages": msgs,
            "suggested": ai.suggest_reply(msgs) if u["role"] in STAFF and msgs and not msgs[-1]["mine"] else ""}


@r.post("/threads/{key}")
async def thread_post(key: str, request: Request, u=Depends(user)):
    if key not in threads_for(u):
        raise HTTPException(403)
    b = await body(request)
    text = (b.get("body") or "").strip()
    if not text:
        raise HTTPException(400, "Type a message")
    s = ai.sentiment(text)
    db.ins("messages", thread=key, from_id=u["id"], body=text, sentiment=s)
    kind, i = key.split(":")
    i = int(i)
    if kind == "lease":
        l = db.q1("SELECT l.*, p.pm_id, p.title, p.landlord_id FROM leases l JOIN properties p ON p.id=l.property_id WHERE l.id=?", i)
        to = [l["pm_id"]] if u["id"] == l["tenant_id"] else [l["tenant_id"]]
        if s == "negative" and u["id"] == l["tenant_id"]:
            sv.task(l["pm_id"], l["property_id"], "escalation", f"Unhappy tenant – {l['title']}", text[:140], "#/app/inbox", 1, dedupe=f"msgneg:{key}:{db.today()}")
    else:
        p = sv.prop(i)
        to = [p["pm_id"]] if u["id"] == p["landlord_id"] else [p["landlord_id"]]
    for t in to:
        sv.notify(t, f"Message from {u['name']}", text[:90], "#/app/inbox?t=" + key, "message")
    return thread(key, u)


@r.post("/assist")
async def assist(request: Request, u=Depends(user)):
    b = await body(request)
    text = (b.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Ask me something")
    return ai.assistant(u, text)


@r.post("/agent")
async def virtual_agent(request: Request, u=Depends(optional_user)):
    from . import agent
    b = await body(request)
    text = (b.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Ask me something")
    return agent.respond(u, text[:600], {"property_id": num(b.get("property_id"), int), "session": (b.get("session") or "")[:40], "contact": b.get("contact")})


@r.post("/agent/handoff")
async def agent_handoff(request: Request, u=Depends(optional_user)):
    b = await body(request)
    pid = num(b.get("property_id"), int)
    p = db.q1("SELECT * FROM properties WHERE id=?", pid) if pid else None
    pm = p["pm_id"] if p else db.val("SELECT id FROM users WHERE role='pm' ORDER BY id LIMIT 1")
    who = f"{b.get('name') or (u and u['name']) or 'Visitor'} {b.get('phone') or (u and u['phone']) or ''}".strip()
    sv.task(pm, pid, "escalation", f"Call back: {who}", (b.get("note") or "Asked the virtual agent for a person") + (f" – {p['title']}" if p else ""), "#/app/ai", 1)
    sv.notify(pm, "Lead wants a call back", who, "#/app/ai", "lead")
    db.ins("agent_log", session=b.get("session"), user_id=u["id"] if u else None, property_id=pid, role=u["role"] if u else "visitor",
           text=f"Call-back request: {who}", reply="Passed to portfolio manager", intent="handoff", handoff=1)
    return {"ok": True}


@r.get("/agent/stats")
def agent_stats(u=Depends(role(*STAFF))):
    from . import agent
    return agent.stats(u["id"] if u["role"] == "pm" else None)


@r.post("/triage")
async def triage_preview(request: Request, u=Depends(user)):
    b = await body(request)
    return ai.triage(b.get("title") or "", b.get("description") or "")


@r.get("/notifications")
def notifications(u=Depends(user)):
    return db.q("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 60", u["id"])


@r.post("/notifications/read")
def notifications_read(u=Depends(user)):
    db.exe("UPDATE notifications SET read=1 WHERE user_id=?", u["id"])
    return {"ok": True}


# =================================================================== admin & settings
@r.get("/users")
def users(u=Depends(role("admin"))):
    return db.q("SELECT id, email, name, phone, role, company, active, verified, created_at FROM users ORDER BY role, name")


@r.post("/users")
async def user_create(request: Request, u=Depends(role("admin"))):
    b = await body(request)
    uid = ensure_user(b["email"], b.get("name"), b.get("role") or "pm", u)
    return {"id": uid, "temp_password": "ava12345"}


@r.put("/users/{uid}")
async def user_update(uid: int, request: Request, u=Depends(role("admin"))):
    b = await body(request)
    kw = {k: b[k] for k in ("active", "role", "verified", "name", "company") if k in b}
    db.upd("users", uid, **kw)
    return {"ok": True}


@r.get("/settings")
def settings_get(u=Depends(role("admin", "pm"))):
    s = fees.all_settings()
    secret = lambda k: "key" in k or "passphrase" in k or "secret" in k
    if u["role"] != "admin":
        s = {k: v for k, v in s.items() if not secret(k)}
    else:   # secrets never travel back to the browser in full
        for k in [k for k in s if secret(k) and k != "payfast_merchant_key" and s[k]]:
            s[k] = "••••" + str(s[k])[-4:]
    return s


@r.put("/settings")
async def settings_put(request: Request, u=Depends(role("admin"))):
    b = await body(request)
    for k, v in b.items():
        if k in fees.DEFAULTS and not (isinstance(v, str) and v.startswith("••••")):
            db.set_setting(k, v)
    return fees.all_settings()


# =================================================================== reports (Excel)
@r.get("/reports/{name}.xlsx")
def report(name: str, u=Depends(role(*OFFICE))):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    ids = prop_ids(u)
    il = in_list(ids)
    wb = Workbook()
    ws = wb.active
    if name == "rent-roll":
        ws.title = "Rent roll"
        head = ["Property", "Tenant", "Reference", "Lease start", "Lease end", "Rent", "Escalation %", "Balance", "Deposit held"]
        rows = [[l["title"], l["tenant_name"], l["ref"], l["start_date"], l["end_date"], l["rent"], l["escalation_pct"], l["balance"], l["deposit_held"]]
                for l in money_summary(u)["rent_roll"]]
    elif name == "arrears":
        ws.title = "Arrears"
        head = ["Property", "Tenant", "Phone", "Reference", "Rent", "Paid this month", "Balance owing"]
        rows = [[l["title"], l["tenant_name"], l["tenant_phone"], l["ref"], l["rent"], l["paid_month"], l["balance"]]
                for l in money_summary(u)["rent_roll"] if l["balance"] > 0]
    elif name == "maintenance":
        ws.title = "Maintenance"
        head = ["Ref", "Property", "Title", "Category", "Priority", "Status", "Responsible", "Contractor", "Cost", "Logged", "Completed", "Days open"]
        rows = []
        for t in tickets(u):
            end = t["completed_at"] or db.now()
            days = (datetime.fromisoformat(end[:19]) - datetime.fromisoformat(t["created_at"][:19])).days
            rows.append([t["ref"], t["ptitle"], t["title"], t["category"], t["priority"], t["status"], t["responsible"],
                         t["contractor_company"] or t["contractor_name"], t["cost"], t["created_at"][:10], (t["completed_at"] or "")[:10], days])
    elif name == "snags":
        ws.title = "Snag list"
        head = ["Ref", "Property", "Room", "Title", "Category", "Trade", "Contractor", "Priority", "Qty", "Unit", "Rate", "Amount", "Due", "Status", "Rework", "Raised", "Closed"]
        rows = [[s["ref"], s["ptitle"], s["room"], s["title"], s["category"], s["trade"], s["contractor_company"] or s["contractor_name"], s["priority"],
                 s["qty"], s["unit"], s["rate"], None, s["due_date"], s["status"], s["rework_count"], (s["raised_at"] or "")[:10], (s["closed_at"] or "")[:10]]
                for s in snags(u)]
    elif name == "owner-ledger":
        ws.title = "Owner ledger"
        head = ["Date", "Period", "Property", "Kind", "Description", "Amount"]
        rows = [[x["date"], x["period"], x["title"], x["kind"], x["description"], x["amount"]] for x in
                db.q(f"SELECT l.*, p.title FROM ledger l JOIN properties p ON p.id=l.property_id WHERE account='owner' AND property_id IN {il} ORDER BY date, l.id")]
    else:
        raise HTTPException(404, "Unknown report")
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0E5E52")
    for i, row_ in enumerate(rows, start=2):
        ws.append(row_)
        if name == "snags":
            ws.cell(i, 12, f"=IF(K{i}=\"\",\"\",I{i}*K{i})")
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(10, min(40, max(len(str(c.value or "")) for c in col) + 2))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="AVA-{name}-{db.today()}.xlsx"'})


# =================================================================== maintenance marketplace
@r.get("/pros")
def pros(trade: str = "", lat: float = None, lng: float = None, area: str = "", u=Depends(optional_user)):
    """Directory of listed maintenance companies with their ratings (owners compare before choosing)."""
    from . import marketplace
    rows = db.q("""SELECT u.id, u.company, u.name, c.trades, c.areas, c.lat, c.lng, c.base_address, c.radius_km, c.callout_fee, c.vetted,
                   c.insured, c.years, c.sub_until, c.bio FROM users u JOIN contractors c ON c.user_id=u.id WHERE u.active=1 AND c.approved=1""")
    out = []
    for r in rows:
        if not marketplace.active(r):
            continue
        if trade and not marketplace.trade_match(trade, r["trades"] or []):
            continue
        if area and area.lower() not in (" ".join(r["areas"] or []) + " " + (r["base_address"] or "")).lower():
            continue
        r["distance_km"] = marketplace.km(lat, lng, r["lat"], r["lng"]) if lat is not None else None
        r["rating"] = marketplace.rating(r["id"])
        r["jobs_done"] = db.val("SELECT COUNT(*) FROM tickets WHERE contractor_id=? AND status IN ('completed','closed')", r["id"])
        r.pop("sub_until")
        out.append(r)
    key = (lambda x: (x["distance_km"] if x["distance_km"] is not None else 9e9)) if lat is not None else (lambda x: -((x["rating"] or {}).get("avg") or 0))
    return sorted(out, key=key)


@r.get("/contractor/issues")
def contractor_issues(u=Depends(role("contractor"))):
    """Job map: open repair requests near the company, to the suburb only."""
    from . import marketplace
    return marketplace.open_issues(u["id"])


@r.post("/tickets/{tid}/apply")
def ticket_apply(tid: int, u=Depends(role("contractor"))):
    return sv.apply_to_quote(tid, u)


@r.get("/pros/stats")
def pros_stats():
    from . import marketplace
    rows = db.q("SELECT c.* FROM contractors c JOIN users u ON u.id=c.user_id WHERE c.approved=1 AND u.active=1")
    act = [x for x in rows if marketplace.active(x)]
    trades = sorted({t for x in act for t in (x["trades"] or [])})
    return {"companies": len(act), "trades": trades, "fee": fees.S("contractor_listing_fee"), "radius": fees.S("quote_radius_km"),
            "trial_days": fees.S("free_trial_days"), "requests_month": db.val("SELECT COUNT(*) FROM quotes WHERE created_at >= date('now','-30 day')"),
            "avg_rating": db.val("SELECT ROUND(AVG(rating),1) FROM reviews WHERE target_type='contractor' AND status='published'")}


@r.get("/pros/{cid}")
def pro(cid: int):
    from . import marketplace
    p = marketplace.profile(cid)
    if not p or not p["approved"]:
        raise HTTPException(404, "Company not found")
    p.pop("sub_until", None)
    return p


@r.post("/contractor/subscribe")
async def contractor_subscribe(request: Request, u=Depends(role("contractor"))):
    b = await body(request)
    months = max(1, min(12, int(b.get("months") or 1)))
    amt = fees.S("contractor_listing_fee") * months
    pay_id = db.ins("payments", lease_id=None, amount=amt, method="payfast", status="pending", created_by=u["id"], reference=f"SUB{u['id']}")
    mid, mkey = fees.S("payfast_merchant_id"), fees.S("payfast_merchant_key")
    if not (mid and mkey):
        return {"mode": "simulated", "payment_id": pay_id, "amount": amt, "months": months}
    base = fees.S("public_url") or str(request.base_url).rstrip("/")
    data = {"merchant_id": mid, "merchant_key": mkey, "return_url": f"{base}/#/app?paid=1", "cancel_url": f"{base}/#/app",
            "notify_url": f"{base}/api/payfast/itn", "name_first": u["name"].split()[0], "email_address": u["email"],
            "m_payment_id": str(pay_id), "amount": f"{amt:.2f}", "item_name": f"AVA maintenance listing x{months}"}
    data["signature"] = payfast_sig(data)
    return {"mode": "payfast", "url": "https://sandbox.payfast.co.za/eng/process" if fees.S("payfast_sandbox") else "https://www.payfast.co.za/eng/process", "fields": data}


@r.post("/contractor/subscribe/simulate/{pay_id}")
def contractor_subscribe_sim(pay_id: int, u=Depends(role("contractor"))):
    from . import marketplace
    pay = db.q1("SELECT * FROM payments WHERE id=? AND status='pending' AND reference=?", pay_id, f"SUB{u['id']}")
    if not pay:
        raise HTTPException(404)
    if fees.S("payfast_merchant_id"):
        raise HTTPException(400, "Live payments are configured")
    db.upd("payments", pay_id, status="complete", method="card")
    months = round(pay["amount"] / fees.S("contractor_listing_fee"))
    until = marketplace.extend_subscription(u["id"], months, pay["amount"], f"SIM-{pay_id}")
    return {"sub_until": until}


@r.post("/reviews/{rid}/reply")
async def review_reply(rid: int, request: Request, u=Depends(role("contractor"))):
    rv = db.q1("SELECT * FROM reviews WHERE id=? AND target_type='contractor' AND target_id=?", rid, u["id"])
    if not rv:
        raise HTTPException(404)
    b = await body(request)
    db.upd("reviews", rid, reply=(b.get("reply") or "").strip()[:600])
    return {"ok": True}


# =================================================================== trust accounting
from . import trust  # noqa: E402

ADMIN = role("admin")


@r.get("/trust")
def trust_overview(u=Depends(ADMIN)):
    trust.ensure_books()
    trust.sync()
    return trust.overview()


@r.get("/trust/trial-balance")
def trust_tb(as_at: str = "", u=Depends(ADMIN)):
    return trust.trial_balance(as_at or None)


@r.get("/trust/cashbook/{code}")
def trust_cashbook(code: str, period: str = "", u=Depends(ADMIN)):
    trust.book(code)
    per = period or date.today().isoformat()[:7]
    opening = trust.cash(code, (date.fromisoformat(per + "-01") - timedelta(days=1)).isoformat())
    tx = db.q("""SELECT t.*, l.date bank_date FROM cashbook_tx t LEFT JOIN bank_lines l ON l.id=t.bank_line_id
                 WHERE t.cashbook=? AND substr(t.date,1,7)=? ORDER BY t.date, t.id""", code, per)
    lines = db.q("SELECT * FROM bank_lines WHERE cashbook=? AND substr(date,1,7)=? ORDER BY date, id", code, per)
    return {"book": trust.book(code), "period": per, "opening": opening, "closing": trust.cash(code, tx[-1]["date"] if tx else None) if tx else opening,
            "tx": tx, "bank_lines": lines, "locked": trust.locked(per)}


@r.post("/trust/feed/{code}")
def trust_feed(code: str, u=Depends(ADMIN)):
    return trust.feed(code)


@r.post("/trust/import/{code}")
async def trust_import(code: str, request: Request, u=Depends(ADMIN)):
    b = await body(request)
    f = (b["_files"].get("file") or [None])[0]
    if not f:
        raise HTTPException(400, "Choose a bank statement file (OFX or CSV)")
    return trust.import_statement(code, await f.read(), f.filename)


@r.post("/trust/lines/{lid}/resolve")
async def trust_resolve(lid: int, request: Request, u=Depends(ADMIN)):
    b = await body(request)
    return trust.resolve_line(lid, b.get("action"), u, b.get("lease_id"), b.get("note") or "")


@r.post("/trust/lines/{lid}/match/{tid}")
def trust_match(lid: int, tid: int, u=Depends(ADMIN)):
    l = db.q1("SELECT * FROM bank_lines WHERE id=? AND status='unmatched'", lid)
    t = db.q1("SELECT * FROM cashbook_tx WHERE id=? AND bank_line_id IS NULL", tid)
    if not l or not t or l["cashbook"] != t["cashbook"] or abs(l["amount"] - t["amount"]) >= 1:
        raise HTTPException(400, "Only an unmatched line and transaction with the same amount can be matched")
    trust.match(lid, tid)
    return {"ok": True}


@r.post("/trust/suspense/{lid}/allocate")
async def trust_suspense(lid: int, request: Request, u=Depends(ADMIN)):
    b = await body(request)
    trust.allocate_suspense(lid, b.get("lease_id"), u)
    return {"ok": True}


@r.get("/trust/recon/{code}/{per}")
def trust_recon(code: str, per: str, u=Depends(ADMIN)):
    return trust.recon(code, per)


@r.post("/trust/recon/{code}/{per}")
def trust_recon_sign(code: str, per: str, u=Depends(ADMIN)):
    return trust.sign_recon(code, per, u)


@r.get("/trust/periods")
def trust_periods(u=Depends(ADMIN)):
    first = db.val("SELECT MIN(date) FROM cashbook_tx") or db.today()
    out, m = [], date.fromisoformat(first[:7] + "-01")
    while m.isoformat()[:7] <= date.today().isoformat()[:7]:
        per = m.isoformat()[:7]
        out.append({"period": per, "locked": trust.locked(per),
                    "reconciled": {c: bool(db.val("SELECT 1 FROM recons WHERE cashbook=? AND period=?", c, per)) for c in trust.BOOKS},
                    "activity": {c: trust.has_activity(c, per) for c in trust.BOOKS}})
        m = (m + timedelta(days=32)).replace(day=1)
    fy_m = int(fees.S("fy_end_month") or 2)
    t = date.today()
    last_fy = t.year if t.month > fy_m else t.year - 1
    return {"periods": out[::-1], "year_ends": db.q("SELECT id, fy, start_period, end_period, created_at FROM year_ends ORDER BY fy DESC"),
            "fy_end_month": fy_m, "closable": [y for y in (last_fy, last_fy - 1) if not db.val("SELECT 1 FROM year_ends WHERE fy=?", str(y))
                                               and trust.fy_bounds(y)[1] >= (out[-1]["period"] if out else "9999")]}


@r.post("/trust/periods/{per}/lock")
def trust_lock(per: str, u=Depends(ADMIN)):
    trust.lock_period(per, u)
    return {"ok": True}


@r.post("/trust/periods/{per}/unlock")
def trust_unlock(per: str, u=Depends(ADMIN)):
    trust.unlock_period(per, u)
    return {"ok": True}


@r.post("/trust/year-end/{fy}")
def trust_year_end(fy: int, u=Depends(ADMIN)):
    return trust.close_year(fy, u)


@r.get("/trust/year-end/{fy}")
def trust_year_end_get(fy: str, u=Depends(ADMIN)):
    y = db.q1("SELECT * FROM year_ends WHERE fy=?", fy)
    if not y:
        raise HTTPException(404)
    y["snapshot"] = json.loads(y["snapshot"])
    return y


@r.get("/trust/journals")
def trust_journals(u=Depends(ADMIN)):
    js = db.q("SELECT j.*, u.name by_name FROM journals j LEFT JOIN users u ON u.id=j.by_user ORDER BY j.id DESC LIMIT 100")
    for j in js:
        j["lines"] = db.q("SELECT g.*, p.title ptitle FROM ledger g LEFT JOIN properties p ON p.id=g.property_id WHERE journal_id=?", j["id"])
    return {"journals": js, "controls": trust.CONTROLS,
            "properties": db.q("SELECT p.id, p.title, (SELECT id FROM leases l WHERE l.property_id=p.id ORDER BY (status='active') DESC, id DESC LIMIT 1) lease_id FROM properties p WHERE kind='rental' ORDER BY title")}


@r.post("/trust/journals")
async def trust_journal_post(request: Request, u=Depends(ADMIN)):
    b = await body(request)
    return {"id": trust.journal(b.get("date") or db.today(), b.get("reason"), b.get("lines") or [], u)}


@r.get("/trust/batches")
def trust_batches(u=Depends(ADMIN)):
    return db.q("SELECT * FROM batches ORDER BY id DESC LIMIT 60")


@r.get("/trust/batches/{bid}")
def trust_batch(bid: int, u=Depends(ADMIN)):
    return trust.batch_full(bid)


@r.post("/trust/batches/fee-transfer")
def trust_fee_transfer(u=Depends(ADMIN)):
    bid = trust.create_fee_transfer(u)
    if not bid:
        raise HTTPException(400, "No fees or payables are waiting to be paid out")
    return trust.batch_full(bid)


@r.post("/trust/batches/{bid}/authorise")
def trust_authorise(bid: int, u=Depends(ADMIN)):
    return trust.authorise(bid, u)


@r.post("/trust/batches/{bid}/release")
def trust_release(bid: int, u=Depends(ADMIN)):
    return trust.release(bid, u)


@r.get("/trust/batches/{bid}/bank-file")
def trust_bank_file(bid: int, u=Depends(ADMIN)):
    b = trust.batch_full(bid)
    return Response(trust.bank_file(bid), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{b["ref"]}.csv"'})


@r.get("/trust/deposits")
def trust_deposits(u=Depends(ADMIN)):
    rows = db.q("""SELECT a.*, l.status lease_status, p.title, u.name tenant FROM deposit_accounts a JOIN leases l ON l.id=a.lease_id
                   JOIN properties p ON p.id=l.property_id JOIN users u ON u.id=l.tenant_id ORDER BY a.status, p.title""")
    for a in rows:
        a["balance"] = sv.balance("deposit", a["lease_id"])
        a["interest"] = sv.balance("deposit", a["lease_id"], kinds=["deposit_interest"])
    return rows


@r.get("/trust/debit-orders")
def trust_debits(u=Depends(ADMIN)):
    ms = db.q("""SELECT m.*, p.title, u.name tenant, l.rent FROM mandates m JOIN leases l ON l.id=m.lease_id JOIN properties p ON p.id=l.property_id
                 JOIN users u ON u.id=m.tenant_id WHERE m.status='active' ORDER BY p.title""")
    runs = db.q("SELECT id, ref, action_date, status, total, count, processed_at FROM debit_runs ORDER BY id DESC LIMIT 24")
    for x in runs:
        x["items"] = db.q("SELECT i.*, p.title FROM debit_items i JOIN leases l ON l.id=i.lease_id JOIN properties p ON p.id=l.property_id WHERE run_id=?", x["id"])
    return {"mandates": [{**trust.mandate_view(m), "title": m["title"], "tenant": m["tenant"], "rent": m["rent"]} for m in ms], "runs": runs,
            "netcash": bool(fees.S("netcash_service_key"))}


@r.post("/trust/debit-orders/run")
async def trust_debit_run(request: Request, u=Depends(ADMIN)):
    b = await body(request)
    rid = trust.debit_run(b.get("date") or None)
    if not rid:
        raise HTTPException(400, "No approved debit orders fall on that day")
    return {"id": rid}


@r.get("/trust/debit-orders/runs/{rid}/file")
def trust_debit_file(rid: int, u=Depends(ADMIN)):
    x = db.q1("SELECT * FROM debit_runs WHERE id=?", rid)
    return Response(x["file"] or "", media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{x["ref"]}-netcash.txt"'})


# ---- the tenant's own debit order, and payout bank details for owners and contractors
def my_lease(u):
    return db.q1("SELECT * FROM leases WHERE tenant_id=? AND status IN ('active','awaiting_signature') ORDER BY id DESC LIMIT 1", u["id"])


@r.get("/me/debit-order")
def my_debit(u=Depends(role("tenant"))):
    l = my_lease(u)
    m = db.q1("SELECT * FROM mandates WHERE lease_id=? AND status='active' ORDER BY id DESC LIMIT 1", l["id"]) if l else None
    return {"mandate": trust.mandate_view(m), "banks": list(trust.BANKS), "due_day": l["due_day"] if l else None, "rent": l["rent"] if l else None,
            "simulated": not fees.S("netcash_service_key")}


@r.post("/me/debit-order")
async def my_debit_set(request: Request, u=Depends(role("tenant"))):
    b = await body(request)
    l = my_lease(u)
    if not l:
        raise HTTPException(400, "No active lease")
    if not b.get("consent"):
        raise HTTPException(400, "Please accept the debit order mandate")
    trust.create_mandate(l["id"], u, b.get("holder") or u["name"], b.get("bank"), b.get("account_no"), b.get("account_type") or "cheque", b.get("debit_day"))
    return my_debit(u)


@r.post("/me/debit-order/approve")
def my_debit_approve(u=Depends(role("tenant"))):
    """DebiCheck approval happens in the tenant's banking app; in simulated mode this stands in for it."""
    if fees.S("netcash_service_key"):
        raise HTTPException(400, "Approve the mandate in your banking app")
    l = my_lease(u)
    m = db.q1("SELECT * FROM mandates WHERE lease_id=? AND status='active' ORDER BY id DESC LIMIT 1", l["id"]) if l else None
    if not m:
        raise HTTPException(404)
    trust.approve_mandate(m["id"])
    return my_debit(u)


@r.delete("/me/debit-order")
def my_debit_cancel(u=Depends(role("tenant"))):
    l = my_lease(u)
    if l:
        db.exe("UPDATE mandates SET status='cancelled', cancelled_at=? WHERE lease_id=? AND status='active'", db.now(), l["id"])
    return my_debit(u)


@r.get("/me/bank-account")
def my_bank(u=Depends(role("landlord", "contractor", "pm"))):
    a = trust.bank_of(u["id"])
    return {"account": ({**{k: a[k] for k in ("holder", "bank", "branch_code", "account_type", "verified")}, "account": trust.masked(a["account_no"])} if a else None),
            "banks": list(trust.BANKS)}


@r.post("/me/bank-account")
async def my_bank_set(request: Request, u=Depends(role("landlord", "contractor", "pm"))):
    b = await body(request)
    trust.set_bank(u["id"], b.get("holder") or u["name"], b.get("bank"), b.get("account_no"), b.get("account_type") or "cheque")
    return my_bank(u)
