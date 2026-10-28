"""Listing syndication: a live AVA listing is also advertised on Property24 and Private Property.

Both portals take listings from agencies through a feed: the agency is registered with the portal (agency/branch id plus a
feed key), and the portal pulls the agency's XML feed or receives pushes. AVA publishes one feed per portal at
/api/feeds/<portal>.xml?key=<feed key>; with the portal ids under Settings that is what the portal reads. Without
them the push is simulated (listing reference, views and enquiries) so the flow can be shown end to end.
Enquiries from the portals land in the AVA leads inbox; a listing that is let or switched off is withdrawn everywhere.
"""
import hashlib
import json
import random
from datetime import date, datetime, timedelta
from xml.sax.saxutils import escape

from fastapi import HTTPException

from . import db, fees

PORTALS = {"property24": {"name": "Property24", "prefix": "P24-", "id": "p24_agency_id", "key": "p24_feed_key"},
           "privateproperty": {"name": "Private Property", "prefix": "T", "id": "pp_agency_id", "key": "pp_feed_key"}}


def live_mode(portal):
    c = PORTALS[portal]
    return bool(fees.S(c["id"]) and fees.S(c["key"]))


def ready(p):
    """What the portals insist on before they accept a rental listing."""
    probs = []
    photos = db.val("SELECT COUNT(*) FROM media WHERE property_id=? AND kind='photo'", p["id"])
    if photos < 3:
        probs.append(f"at least 3 photos ({photos} now)")
    if not p["rent"]:
        probs.append("a rent")
    if len(p["description"] or "") < 80:
        probs.append("a description of 80+ characters")
    if not (p["suburb"] and p["city"]):
        probs.append("suburb and city")
    if not p["bedrooms"]:
        probs.append("bedrooms")
    return probs


def status(pid):
    rows = {r["portal"]: r for r in db.q("SELECT * FROM syndications WHERE property_id=?", pid)}
    return [{"portal": k, "name": c["name"], "mode": "live" if live_mode(k) else "simulated",
             **({x: rows[k][x] for x in ("status", "portal_ref", "views", "enquiries", "error", "pushed_at")} if k in rows else {"status": "off"}),
             "url": url(k, rows[k]["portal_ref"]) if k in rows and rows[k]["portal_ref"] and rows[k]["status"] == "live" else None}
            for k, c in PORTALS.items()]


def url(portal, ref):
    return (f"https://www.property24.com/to-rent/listing/{ref.removeprefix('P24-')}" if portal == "property24"
            else f"https://www.privateproperty.co.za/to-rent/listing/{ref}")


def set_portal(pid, portal, on):
    if portal not in PORTALS:
        raise HTTPException(400, "Unknown portal")
    p = db.q1("SELECT * FROM properties WHERE id=?", pid)
    row = db.q1("SELECT * FROM syndications WHERE property_id=? AND portal=?", pid, portal)
    if not on:
        if row:
            db.upd("syndications", row["id"], status="withdrawn", updated_at=db.now())
        return status(pid)
    if p["listing_status"] != "live":
        raise HTTPException(400, "Publish the listing on AVA first – the portals get the same listing")
    probs = ready(p)
    if probs:
        raise HTTPException(400, f"{PORTALS[portal]['name']} needs " + ", ".join(probs))
    ref = row["portal_ref"] if row and row["portal_ref"] else PORTALS[portal]["prefix"] + str(100000000 + int(hashlib.md5(f"{portal}{pid}".encode()).hexdigest()[:7], 16) % 899999999)
    kw = dict(status="live" if not live_mode(portal) else "queued", portal_ref=ref, error=None, pushed_at=db.now(), updated_at=db.now())
    if row:
        db.upd("syndications", row["id"], **kw)
    else:
        db.ins("syndications", property_id=pid, portal=portal, **kw)
    return status(pid)


def withdraw_stale():
    """A listing that is let, switched off or back in draft comes down from every portal."""
    return db.exe("""UPDATE syndications SET status='withdrawn', updated_at=? WHERE status IN ('live','queued')
                  AND property_id IN (SELECT id FROM properties WHERE listing_status!='live')""", db.now()).rowcount


def simulate_activity(day=None):
    """Simulated portal traffic: views every day, an enquiry now and then (stable per listing and day)."""
    day = day or date.today()
    made = 0
    for s in db.q("SELECT s.*, p.title, p.pm_id, p.rent FROM syndications s JOIN properties p ON p.id=s.property_id WHERE s.status='live'"):
        if live_mode(s["portal"]):
            continue
        key = f"{s['id']}|{day.isoformat()}"
        if db.val("SELECT 1 FROM settings WHERE key=?", "synd:" + key):
            continue
        rnd = random.Random(key)
        db.set_setting("synd:" + key, 1)
        views = rnd.randint(8, 45) if s["portal"] == "property24" else rnd.randint(4, 25)
        enq = 1 if rnd.random() < (0.03 if s["portal"] == "property24" else 0.015) else 0
        db.exe("UPDATE syndications SET views=views+?, enquiries=enquiries+? WHERE id=?", views, enq, s["id"])
        if enq:
            fn = rnd.choice(["Kabelo", "Megan", "Riaan", "Naledi", "Imran", "Chantel", "Lwazi", "Bianca", "Sipho", "Tanya"])
            ln = rnd.choice(["Mokoena", "Smith", "Pretorius", "Ndlovu", "Patel", "Jacobs", "Zulu", "Kruger", "Dube", "Naidoo"])
            add_lead(s["property_id"], s["portal"], f"{fn} {ln}", f"{fn.lower()}.{ln.lower()}@example.com", f"07{rnd.randint(1, 9)} {rnd.randint(100, 999)} {rnd.randint(1000, 9999)}",
                     rnd.choice(["Is this still available? I'd like to view it this week.", "Hi, are pets allowed? We have a small dog.",
                                 "Can I view on Saturday morning? Two adults, both working.", "What is the earliest move-in date?",
                                 "Is the deposit negotiable? I can pay 1.5 months."]), created=f"{day.isoformat()} {rnd.randint(7, 20):02d}:{rnd.randint(0, 59):02d}:00")
            made += 1
    return made


def add_lead(pid, portal, name, email, phone, message, created=None):
    lid = db.ins("portal_leads", property_id=pid, portal=portal, name=name, email=email, phone=phone, message=message,
                 **({"created_at": created} if created else {}))
    p = db.q1("SELECT pm_id, title FROM properties WHERE id=?", pid)
    if p and p["pm_id"]:
        from .services import notify
        notify(p["pm_id"], f"{PORTALS.get(portal, {}).get('name', portal)} enquiry", f"{name} about {p['title']}", "#/app/growth/leads", "lead")
    return lid


def feed_xml(portal, key):
    c = PORTALS.get(portal)
    if not c or not fees.S(c["key"]) or key != fees.S(c["key"]):
        raise HTTPException(403, "Feed key required")
    rows = db.q("""SELECT p.*, s.portal_ref FROM syndications s JOIN properties p ON p.id=s.property_id
                   WHERE s.portal=? AND s.status IN ('live','queued') AND p.listing_status='live'""", portal)
    db.exe("UPDATE syndications SET status='live' WHERE portal=? AND status='queued'", portal)
    base = (fees.S("public_url") or "").rstrip("/")
    out = [f'<?xml version="1.0" encoding="UTF-8"?>\n<listings agency="{escape(str(fees.S(c["id"])))}" generated="{datetime.now().isoformat(timespec="seconds")}">']
    for p in rows:
        photos = [m["url"] for m in db.q("SELECT url FROM media WHERE property_id=? AND kind='photo' ORDER BY sort", p["id"])]
        feats = p["features"] if isinstance(p["features"], list) else json.loads(p["features"] or "[]")
        out.append(f"""  <listing id="AVA{p['id']}" ref="{escape(p['portal_ref'] or '')}" type="rental">
    <title>{escape(p['headline'] or p['title'])}</title><propertyType>{escape(p['type'] or '')}</propertyType>
    <price currency="ZAR" period="month">{int(p['rent'] or 0)}</price><deposit>{int(p['deposit'] or 0)}</deposit>
    <bedrooms>{p['bedrooms'] or 0:g}</bedrooms><bathrooms>{p['bathrooms'] or 0:g}</bathrooms><parking>{p['parking'] or 0}</parking>
    <floorSize unit="m2">{p['size_m2'] or ''}</floorSize><erfSize unit="m2">{p['erf_size'] or ''}</erfSize>
    <suburb>{escape(p['suburb'] or '')}</suburb><city>{escape(p['city'] or '')}</city><province>{escape(p['province'] or '')}</province>
    <latitude>{p['lat'] or ''}</latitude><longitude>{p['lng'] or ''}</longitude><availableFrom>{p['available_from'] or ''}</availableFrom>
    <petsAllowed>{'true' if p['pets'] else 'false'}</petsAllowed><furnished>{'true' if p['furnished'] else 'false'}</furnished>
    <description>{escape(p['description'] or '')}</description>
    <features>{''.join(f'<feature>{escape(f)}</feature>' for f in feats)}</features>
    <photos>{''.join(f'<photo>{escape(base + u)}</photo>' for u in photos)}</photos>
    <link>{escape(base)}/#/listing/{p['id']}</link>
  </listing>""")
    out.append("</listings>")
    return "\n".join(out)


def leads(pids, status=None):
    il = ",".join(map(str, pids)) or "0"
    return db.q(f"""SELECT l.*, p.title FROM portal_leads l JOIN properties p ON p.id=l.property_id WHERE l.property_id IN ({il})
                    {"AND l.status=?" if status else ""} ORDER BY l.created_at DESC LIMIT 200""", *([status] if status else []))


def overview(pids):
    il = ",".join(map(str, pids)) or "0"
    rows = db.q(f"""SELECT s.*, p.title, p.suburb, p.rent FROM syndications s JOIN properties p ON p.id=s.property_id
                    WHERE s.property_id IN ({il}) ORDER BY p.title, s.portal""")
    by = {}
    for r in rows:
        by.setdefault(r["portal"], {"live": 0, "views": 0, "enquiries": 0})
        if r["status"] == "live":
            by[r["portal"]]["live"] += 1
        by[r["portal"]]["views"] += r["views"]
        by[r["portal"]]["enquiries"] += r["enquiries"]
    ava_views = db.val(f"SELECT COALESCE(SUM(views),0) FROM properties WHERE id IN ({il}) AND listing_status='live'")
    ava_leads = db.val(f"SELECT COUNT(*) FROM viewings WHERE property_id IN ({il}) AND created_at>=date('now','-30 day')")
    live = db.q(f"""SELECT id, title, suburb, rent FROM properties WHERE id IN ({il}) AND listing_status='live' ORDER BY title""")
    for p in live:
        p["portals"] = {s["portal"]: s["status"] for s in rows if s["property_id"] == p["id"]}
        p["problems"] = ready(db.q1("SELECT * FROM properties WHERE id=?", p["id"]))
    return {"portals": [{"portal": k, "name": c["name"], "mode": "live" if live_mode(k) else "simulated", **by.get(k, {"live": 0, "views": 0, "enquiries": 0})}
                        for k, c in PORTALS.items()],
            "ava": {"views": ava_views, "viewings_30d": ava_leads}, "listings": live,
            "new_leads": db.val(f"SELECT COUNT(*) FROM portal_leads WHERE status='new' AND property_id IN ({il})")}
