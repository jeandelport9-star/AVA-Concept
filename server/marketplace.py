"""Maintenance marketplace.

* Maintenance companies list themselves for R250/month (setting `contractor_listing_fee`), with a base location and trades.
* A repair request goes to the 3 best-matched, approved, paid-up companies within 10 km of the property (`quote_radius_km`).
* They quote; the owner compares price, rating, distance and ETA and chooses.
* After the job, the tenant and the owner rate the company on quality, punctuality, price and communication.
  Low ratings (< 3) are moderated before they count; the company can reply publicly.
"""
import math
from datetime import date, timedelta

from . import db, fees


def km(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lng2 - lng1) * p)) / 2
    return round(12742 * math.asin(math.sqrt(a)), 1)


def active(c):
    return bool(c.get("sub_until")) and c["sub_until"] >= date.today().isoformat()


def rating(cid):
    r = db.q1("""SELECT ROUND(AVG(rating),1) avg, COUNT(*) n, ROUND(AVG(quality),1) quality, ROUND(AVG(punctuality),1) punctuality,
                 ROUND(AVG(price_score),1) price, ROUND(AVG(communication),1) communication
                 FROM reviews WHERE target_type='contractor' AND target_id=? AND status='published'""", cid)
    return r


REGULATED = ("electric", "gas", "solar", "inverter")   # needs a qualified, certificated trade – never a general handyman


def handyman_ok(trade, trades):
    return "Handyman" in (trades or []) and not any(k in (trade or "").lower() for k in REGULATED)


def trade_match(trade, trades):
    t = (trade or "").lower()
    return any(x and (x.lower() in t or t.split(" ")[0] in x.lower()) for x in trades)


def candidates(trade, lat, lng, include_handyman=True, also=()):
    """Every approved company for the trade with its distance to (lat, lng) – used for the map and for widening."""
    rows = db.q("""SELECT u.id, u.name, u.company, c.trades, c.lat, c.lng, c.base_address, c.sub_until, c.callout_fee,
                   (SELECT ROUND(AVG(rating),1) FROM reviews r WHERE r.target_type='contractor' AND r.target_id=u.id AND r.status='published') rating,
                   (SELECT COUNT(*) FROM reviews r WHERE r.target_type='contractor' AND r.target_id=u.id AND r.status='published') reviews
                   FROM users u JOIN contractors c ON c.user_id=u.id WHERE u.active=1 AND c.approved=1""")
    out = []
    for r in rows:
        exact = trade_match(trade, r["trades"] or [])
        if not exact and not (include_handyman and handyman_ok(trade, r["trades"])) and r["id"] not in also:
            continue
        r["distance_km"] = km(lat, lng, r["lat"], r["lng"])
        r["active"] = active(r)
        r["exact"] = exact
        r.pop("sub_until")
        out.append(r)
    return sorted(out, key=lambda x: x["distance_km"] if x["distance_km"] is not None else 9e9)


def next_radius(trade, lat, lng, radius, exclude=()):
    """Smallest widening step that reaches at least one more paid-up company (None if there is none at all)."""
    from . import fees
    for step in fees.S("widen_steps_km"):
        if step > radius and any(c["active"] and c["id"] not in exclude and c["distance_km"] is not None and c["distance_km"] <= step
                                 for c in candidates(trade, lat, lng)):
            return step
    return None


def nearby(trade, lat, lng, n=3, radius=None, include_handyman=True, exclude=()):
    """Best `n` companies within `radius` km of (lat, lng): trade match, paid-up, approved; ranked by rating, distance and workload."""
    radius = radius or fees.S("quote_radius_km")
    rows = db.q("""SELECT u.id, u.name, u.company, u.phone, c.*,
                   (SELECT AVG(rating) FROM reviews r WHERE r.target_type='contractor' AND r.target_id=u.id AND r.status='published') rating,
                   (SELECT COUNT(*) FROM reviews r WHERE r.target_type='contractor' AND r.target_id=u.id AND r.status='published') reviews,
                   (SELECT COUNT(*) FROM tickets t WHERE t.contractor_id=u.id AND t.status IN ('approved','scheduled','in_progress')) load
                   FROM users u JOIN contractors c ON c.user_id=u.id WHERE u.active=1 AND c.approved=1""")
    out = []
    for r in rows:
        trades = r["trades"] or []
        exact = trade_match(trade, trades)
        if not exact and not (include_handyman and handyman_ok(trade, trades)):
            continue
        if not active(r) or r["id"] in exclude:
            continue
        d = km(lat, lng, r["lat"], r["lng"])
        if d is None or d > radius:
            continue
        s = (r["rating"] or 3.5) * 2 + (3 if exact else 0) - d * 0.15 - (r["load"] or 0) * 0.6
        out.append({**r, "distance_km": d, "score": round(s, 2), "exact": exact})
    return sorted(out, key=lambda x: -x["score"])[:n]


def extend_subscription(cid, months=1, paid=None, ref=""):
    c = db.q1("SELECT * FROM contractors WHERE user_id=?", cid)
    start = max(date.fromisoformat(c["sub_until"]) if c and c["sub_until"] else date.today(), date.today())
    until = (start + timedelta(days=30 * months)).isoformat()
    db.exe("UPDATE contractors SET sub_until=? WHERE user_id=?", until, cid)
    if paid:
        d = date.today().isoformat()
        db.ins("ledger", account="ava", kind="listing_fee", amount=paid, date=d, period=d[:7], description=f"Maintenance listing – {db.val('SELECT company FROM users WHERE id=?', cid)}", ref=ref)
        db.ins("ledger", account="contractor", kind="listing_fee", amount=-paid, date=d, period=d[:7], description="AVA listing subscription", ref=f"contractor:{cid}")
    return until


def profile(cid):
    u = db.q1("SELECT id, name, company, phone, email, created_at FROM users WHERE id=?", cid)
    c = db.q1("SELECT * FROM contractors WHERE user_id=?", cid)
    if not u or not c:
        return None
    jobs = db.q1("""SELECT COUNT(*) done, ROUND(AVG(julianday(completed_at)-julianday(created_at)),1) avg_days
                    FROM tickets WHERE contractor_id=? AND status IN ('completed','closed')""", cid)
    won = db.val("SELECT COUNT(*) FROM quotes WHERE contractor_id=? AND status='approved'", cid) or 0
    quoted = db.val("SELECT COUNT(*) FROM quotes WHERE contractor_id=? AND status NOT IN ('requested','expired')", cid) or 0
    asked = db.val("SELECT COUNT(*) FROM quotes WHERE contractor_id=?", cid) or 0
    reviews = db.q("""SELECT r.*, a.name author FROM reviews r LEFT JOIN users a ON a.id=r.author_id
                      WHERE r.target_type='contractor' AND r.target_id=? AND r.status='published' ORDER BY r.id DESC LIMIT 50""", cid)
    dist = {i: sum(1 for r in reviews if r["rating"] == i) for i in range(1, 6)}
    return {**{k: c[k] for k in ("trades", "areas", "approved", "vetted", "callout_fee", "bio", "bee_level", "registration", "base_address",
                                 "radius_km", "website", "years", "insured", "lat", "lng", "sub_until")},
            "id": cid, "name": u["name"], "company": u["company"], "member_since": u["created_at"][:10], "active": active(c),
            "radius": fees.S("quote_radius_km"), "rating": rating(cid), "jobs_done": jobs["done"], "avg_days": jobs["avg_days"], "won": won, "quoted": quoted,
            "response_rate": round(100 * quoted / asked) if asked else None, "reviews": reviews, "distribution": dist}


OPEN = ("new", "quoting", "awaiting_approval")


def open_issues(cid):
    """Repair requests a company can see on its job map: open, nobody booked yet, its trade, within its working radius.
    Location is shown to the suburb only (about 1 km) – the address is released when the owner books the company."""
    c = db.q1("SELECT c.*, u.company FROM contractors c JOIN users u ON u.id=c.user_id WHERE c.user_id=?", cid)
    if not c or c["lat"] is None:
        return {"base": None, "issues": []}
    reach = max(c["radius_km"] or 25, fees.S("quote_radius_km"))
    rows = db.q(f"""SELECT t.id, t.ref, t.title, t.category, t.trade, t.priority, t.status, t.created_at, t.quote_deadline, t.photos, t.room,
                   p.suburb, p.city, p.lat, p.lng,
                   (SELECT COUNT(*) FROM quotes q WHERE q.ticket_id=t.id AND COALESCE(q.kind,'quote')='quote') n_quotes,
                   (SELECT status FROM quotes q WHERE q.ticket_id=t.id AND q.contractor_id=? AND COALESCE(q.kind,'quote')='quote') mine
                   FROM tickets t JOIN properties p ON p.id=t.property_id
                   WHERE t.status IN {OPEN} AND t.contractor_id IS NULL ORDER BY t.priority='Urgent' DESC, t.id DESC""", cid)
    trades = c["trades"] or []
    out = []
    for t in rows:
        d = km(c["lat"], c["lng"], t["lat"], t["lng"])
        if d is None or d > reach:
            continue
        exact = trade_match(t["trade"], trades)
        if not exact and not handyman_ok(t["trade"], trades):
            continue
        full = t["n_quotes"] >= fees.S("max_quotes_per_job")
        t.update(distance_km=d, lat=round(t["lat"], 2), lng=round(t["lng"], 2), exact=exact, photo=(t["photos"] or [None])[0],
                 can_apply=not t["mine"] and not full and active(c) and bool(c["approved"]),
                 why_not=None if t["mine"] else "Listing not active" if not active(c) else "Being vetted" if not c["approved"] else "Enough quotes" if full else None)
        t.pop("photos")
        out.append(t)
    return {"base": {"lat": c["lat"], "lng": c["lng"], "radius": reach, "address": c["base_address"]}, "issues": out,
            "max_quotes": fees.S("max_quotes_per_job")}
