"""Landlord prospecting, 'what your property can earn with AVA' reports and the condition & finish score.

Prospect data (erf, owner, last sale, est. value) comes from a property-data provider such as LOOM, which sells deeds-office,
valuation and owner-contact data to agents in SA. With LOOM credentials under Settings the PM's own LOOM account is used
(contact reveals spend that account's credits); without them AVA simulates a realistic area so the flow can be shown.

POPIA: an owner found this way has not agreed to anything yet. A PM may phone them once to introduce AVA (they may
object at any time → do-not-contact), but email/SMS marketing needs their consent (s69), which the report's
'Contact me' form records.
"""
import hashlib
import json
import random
import secrets
from datetime import date, timedelta

from fastapi import HTTPException

from . import ai, compliance, db, fees

STREETS = ["Jacaranda", "Protea", "Acacia", "Marula", "Eland", "Kudu", "Disa", "Aloe", "Umdoni", "Wildevy", "Kiaat", "Tambotie",
           "Buffelsdoring", "Olienhout", "Bergvlei", "Rietbok", "Suikerbos", "Karee", "Witstinkhout", "Boekenhout"]
FIRST = ["Johan", "Nomsa", "Ruan", "Ayesha", "Kagiso", "Elna", "Mandla", "Priya", "Charl", "Zanele", "Hendrik", "Refilwe",
         "Brendan", "Palesa", "Willem", "Fatima", "Tumelo", "Annelie", "Sizwe", "Michelle"]
LAST = ["Botha", "Dlamini", "Naidoo", "Pretorius", "Mahlangu", "du Toit", "Khumalo", "Pillay", "Venter", "Nkosi", "Joubert",
        "Mokoena", "Steyn", "Molefe", "Coetzee", "Moodley", "Ndlovu", "Nel", "Sithole", "Ferreira"]
TYPES = [("House", 3, 2, 210, 900), ("House", 4, 3, 240, 1100), ("Townhouse", 3, 2, 165, 0), ("Townhouse", 3, 2, 150, 0),
         ("Apartment", 2, 2, 125, 0), ("House", 3, 2, 230, 1000)]


def provider():
    return "LOOM" if fees.S("loom_username") and fees.S("loom_password") else "simulated"


def credits_left():
    return int(fees.S("loom_credits") or 0)


def view(p, pm=None):
    out = dict(p)
    if not p["contact_revealed"]:
        out["phone"] = out["email"] = None
    out["investor"] = bool(p["owner_lives_elsewhere"] or p["owner_type"] != "Private person")
    out["est_rent"] = estimate(p)["estimate"] if estimate(p) else None
    out["reports"] = db.q("SELECT token, views, last_viewed_at, lead_at FROM earn_reports WHERE prospect_id=? ORDER BY id DESC", p["id"])
    return out


def search_area(pm, suburb, city, n=12):
    """Pull the erven in a suburb from the data provider and keep the likely letting candidates.
    Simulated: a stable set of homes per suburb (same suburb → same owners)."""
    suburb, city = suburb.strip().title(), (city or "").strip().title()
    if not suburb:
        raise HTTPException(400, "Choose a suburb")
    if provider() != "simulated":
        raise HTTPException(501, "LOOM API access is set up per agency – ask LOOM for API access for your account; until then leave the LOOM login empty to use demo data.")
    seed = int(hashlib.md5(f"{suburb}|{city}".encode()).hexdigest()[:8], 16)
    rnd = random.Random(seed)
    base = db.q1("SELECT AVG(lat) lat, AVG(lng) lng FROM properties WHERE suburb=? OR city=?", suburb, city or suburb)
    lat0, lng0 = (base["lat"], base["lng"]) if base and base["lat"] else (-25.77, 28.26)
    new = 0
    for i in range(n):
        # every random draw happens before the duplicate check, so the same suburb always yields the same erven
        typ, beds, baths, m2, erf = rnd.choice(TYPES)
        erf_no = f"{rnd.randint(100, 4999)}"
        owner_type = rnd.choices(["Private person", "Trust", "Company"], [7, 2, 1])[0]
        fn, ln = rnd.choice(FIRST), rnd.choice(LAST)
        owner = {"Private person": f"{fn} {ln}", "Trust": f"{ln} Family Trust", "Company": f"{ln} Property Investments (Pty) Ltd"}[owner_type]
        bought = date.today() - timedelta(days=rnd.randint(400, 6000))
        fallback, yld, sale_f = rnd.randint(15, 30) * 1000, rnd.uniform(0.075, 0.095), rnd.uniform(0.55, 0.95)
        addr = f"{rnd.randint(1, 180)} {rnd.choice(STREETS)} Street"
        dlat, dlng, away = rnd.uniform(-0.012, 0.012), rnd.uniform(-0.012, 0.012), rnd.random() < 0.45
        phone = f"08{rnd.randint(1, 4)} {rnd.randint(100, 999)} {rnd.randint(1000, 9999)}"
        email = f"{fn.lower()}.{ln.lower().replace(' ', '')}{rnd.randint(1, 99)}@example.co.za"
        if db.val("SELECT 1 FROM prospects WHERE erf=? AND suburb=? AND pm_id=?", erf_no, suburb, pm["id"]):
            continue
        rent = (ai.comparable_rent({"suburb": suburb, "city": city, "bedrooms": beds, "size_m2": m2}) or {}).get("estimate") or fallback
        value = round(rent * 12 / yld, -4)
        db.ins("prospects", pm_id=pm["id"], source=provider(), erf=erf_no, address=addr,
               suburb=suburb, city=city, province=None, lat=lat0 + dlat, lng=lng0 + dlng,
               type=typ, bedrooms=beds, bathrooms=baths, size_m2=m2, erf_size=erf or None, owner_name=owner, owner_type=owner_type,
               owner_lives_elsewhere=1 if away else 0, last_sale_date=bought.isoformat(),
               last_sale_price=round(value * sale_f, -4), est_value=value, phone=phone, email=email, updated_at=db.now())
        new += 1
    return new


def reveal(pid, pm):
    p = mine(pid, pm)
    if p["contact_revealed"]:
        return view(p)
    if p["do_not_contact"]:
        raise HTTPException(400, "This owner asked not to be contacted")
    left = credits_left()
    if left <= 0:
        raise HTTPException(400, "No contact credits left – top up your LOOM account")
    db.set_setting("loom_credits", left - 1)
    db.upd("prospects", pid, contact_revealed=1, updated_at=db.now())
    db.ins("activity", pm_id=pm["id"], actor=pm["name"], text=f"Revealed owner contact for {p['address']}, {p['suburb']} (1 {p['source']} credit)", link="#/app/growth")
    return view(db.q1("SELECT * FROM prospects WHERE id=?", pid))


def mine(pid, pm):
    p = db.q1("SELECT * FROM prospects WHERE id=?", pid)
    if not p or (pm["role"] != "admin" and p["pm_id"] != pm["id"]):
        raise HTTPException(404, "Prospect not found")
    return p


STATUSES = ["new", "contacted", "report_sent", "interested", "signed", "not_interested"]


def update(pid, pm, b):
    p = mine(pid, pm)
    kw = {}
    if b.get("status") in STATUSES:
        kw["status"] = b["status"]
    if "note" in b:
        kw["note"] = (b.get("note") or "")[:2000]
    if b.get("do_not_contact") in (True, 1, "1", "true"):
        kw.update(do_not_contact=1, status="not_interested")
        compliance.record_consent(None, "prospecting", False, f"Owner objected by phone (logged by {pm['name']})", email=p["email"])
    db.upd("prospects", pid, updated_at=db.now(), **kw)
    return view(db.q1("SELECT * FROM prospects WHERE id=?", pid))


# ------------------------------------------------------------------ the report
def estimate(p):
    return ai.comparable_rent({"id": p.get("property_id") or 0, "suburb": p["suburb"], "city": p["city"], "bedrooms": p["bedrooms"],
                               "size_m2": p["size_m2"], "condition_score": p.get("condition_score")})


def build_report(pm, prospect=None, prop=None, extra=None):
    """Numbers for the owner: likely rent, what a traditional agent charges, what AVA costs, what's left over."""
    src = dict(prospect or prop or extra)
    if extra:
        src.update({k: v for k, v in extra.items() if v not in (None, "")})
    est = estimate(src)
    if not est:
        raise HTTPException(400, "Not enough comparable rentals in that area for an estimate yet")
    rent = est["estimate"]
    cmp = fees.agent_comparison(rent)
    ll = fees.landlord_monthly(rent, n_rented=1, pm_id=pm["id"] if pm and pm["role"] == "pm" else None, insured=True)
    comps = db.q("""SELECT title, suburb, bedrooms, size_m2, rent FROM properties WHERE kind='rental' AND rent>0 AND listing_status IN ('live','let')
                    AND (suburb=? OR city=?) AND ABS(bedrooms-?)<0.6 ORDER BY (suburb=?) DESC, ABS(rent-?) LIMIT 5""",
                 src["suburb"], src["city"], src["bedrooms"] or 0, src["suburb"], rent)
    vac = db.q1("""SELECT AVG(julianday(l.start_date)-julianday(p.published_at)) d FROM leases l JOIN properties p ON p.id=l.property_id
                   WHERE p.published_at IS NOT NULL AND l.start_date>=date(p.published_at) AND (p.suburb=? OR p.city=?)""", src["suburb"], src["city"])
    value = src.get("est_value")
    return {"address": src.get("address"), "suburb": src["suburb"], "city": src["city"], "type": src.get("type"), "bedrooms": src["bedrooms"],
            "bathrooms": src.get("bathrooms"), "size_m2": src["size_m2"], "owner": src.get("owner_name") or src.get("name"),
            "rent": est, "gross_yield": round(rent * 12 / value * 100, 1) if value else None, "est_value": value,
            "agent": cmp, "ava": ll, "comparables": comps, "days_to_let": round(vac["d"]) if vac and vac["d"] else 21,
            "pm": pm_public(pm["id"]) if pm and pm["role"] == "pm" else None, "made": date.today().isoformat()}


def create_report(pm, prospect_id=None, property_id=None, extra=None):
    prospect = mine(prospect_id, pm) if prospect_id else None
    prop = db.q1("SELECT * FROM properties WHERE id=?", property_id) if property_id else None
    data = build_report(pm, prospect, prop, extra)
    tok = secrets.token_urlsafe(9)
    db.ins("earn_reports", token=tok, pm_id=pm["id"] if pm else None, prospect_id=prospect_id, property_id=property_id, data=json.dumps(data))
    if prospect and prospect["status"] in ("new", "contacted"):
        db.upd("prospects", prospect_id, status="report_sent", updated_at=db.now())
    return {"token": tok, "link": f"#/r/{tok}", **data}


def public_report(token):
    r = db.q1("SELECT * FROM earn_reports WHERE token=?", token)
    if not r:
        raise HTTPException(404, "This report has expired")
    db.exe("UPDATE earn_reports SET views=views+1, last_viewed_at=? WHERE id=?", db.now(), r["id"])
    if r["views"] == 0 and r["pm_id"]:
        from .services import notify
        notify(r["pm_id"], "Your earnings report was opened", json.loads(r["data"]).get("address") or "", "#/app/growth", "lead")
    return {"token": token, **json.loads(r["data"]), "lead_sent": bool(r["lead_at"])}


def report_lead(token, b, ip=None):
    r = db.q1("SELECT * FROM earn_reports WHERE token=?", token)
    if not r:
        raise HTTPException(404)
    name, phone, email = (b.get("name") or "").strip(), (b.get("phone") or "").strip(), (b.get("email") or "").strip().lower()
    if not name or not (phone or email):
        raise HTTPException(400, "Leave your name and a phone number or email")
    if not b.get("consent"):
        raise HTTPException(400, "Tick the box so we may contact you")
    db.upd("earn_reports", r["id"], lead_name=name, lead_phone=phone, lead_email=email, lead_at=db.now())
    compliance.record_consent(None, "prospecting", True, f"Earnings report {token} – contact form", email=email or phone, ip=ip)
    if b.get("marketing"):
        compliance.record_consent(None, "marketing", True, f"Earnings report {token} – contact form", email=email or phone, ip=ip)
    if r["prospect_id"]:
        db.upd("prospects", r["prospect_id"], status="interested", updated_at=db.now())
    if r["pm_id"]:
        from .services import notify, task
        d = json.loads(r["data"])
        task(r["pm_id"], None, "lead", f"Owner wants to talk: {name}", f"{d.get('address') or d['suburb']} · {phone or email} · est. rent R{d['rent']['estimate']:,.0f}",
             "#/app/growth", 1, date.today().isoformat(), f"lead:{r['id']}")
        notify(r["pm_id"], "New landlord lead", f"{name} wants to talk about {d.get('address') or d['suburb']}", "#/app/growth", "lead")
    return {"ok": True}


# ------------------------------------------------------------------ PM brochure
def pm_public(pm_id):
    u = db.q1("SELECT id, name, phone, email, company, bio, created_at FROM users WHERE id=? AND role='pm' AND active=1", pm_id)
    if not u:
        return None
    ids = [r["id"] for r in db.q("SELECT id FROM properties WHERE pm_id=? AND kind='rental' AND listing_status!='draft'", pm_id)]
    il = ",".join(map(str, ids)) or "0"
    let = db.val(f"SELECT COUNT(DISTINCT property_id) FROM leases WHERE status='active' AND property_id IN ({il})") or 0
    paid = db.q1(f"""SELECT COUNT(*) n, SUM(CASE WHEN g.date <= date(substr(g.period,1,7)||'-07') THEN 1 ELSE 0 END) ok
                     FROM ledger g WHERE g.account='tenant' AND g.kind='payment' AND g.property_id IN ({il}) AND g.date>=date('now','-12 month')""")
    areas = [r["suburb"] for r in db.q(f"SELECT suburb, COUNT(*) c FROM properties WHERE id IN ({il}) GROUP BY suburb ORDER BY c DESC LIMIT 8")]
    listings = db.q(f"""SELECT id, title, suburb, bedrooms, bathrooms, rent, (SELECT url FROM media WHERE property_id=properties.id ORDER BY sort LIMIT 1) photo
                        FROM properties WHERE id IN ({il}) AND listing_status='live' ORDER BY featured DESC, published_at DESC LIMIT 6""")
    rev = db.q1("SELECT AVG(rating) r, COUNT(*) n FROM reviews WHERE target_type='pm' AND target_id=? AND status='published'", pm_id)
    return {"id": u["id"], "name": u["name"], "phone": u["phone"], "email": u["email"], "company": u["company"],
            "bio": u["bio"] or f"{u['name'].split()[0]} manages rental homes in {', '.join(areas[:3]) or 'your area'} on AVA – tenants vetted, rent collected by debit order, "
                              "owners paid on the 7th with a statement, and every inspection in 360°.",
            "homes": len(ids), "occupancy": round(let / len(ids) * 100) if ids else None,
            "on_time": round((paid["ok"] or 0) / paid["n"] * 100) if paid and paid["n"] else None, "areas": areas, "listings": listings,
            "rating": round(rev["r"], 1) if rev and rev["r"] else None, "reviews": rev["n"] if rev else 0,
            "commission_pct": fees.pm_commission_pct(pm_id), "ava_fee_from": min(v for _, v in fees.S("ava_tiers")),
            "agent_pct": fees.S("agent_fee_pct"), "since": (u["created_at"] or "")[:4]}


# ------------------------------------------------------------------ condition & finish score
def condition_from_inspection(pid):
    """Average of the item conditions (C1–C5) on the latest finalised inspection, rescaled to C1–C6."""
    ins = db.q1("SELECT id, type, date FROM inspections WHERE property_id=? AND status='final' ORDER BY COALESCE(finalised_at, date) DESC LIMIT 1", pid)
    if not ins:
        return None
    rows = db.q("SELECT condition FROM insp_items WHERE inspection_id=? AND condition IS NOT NULL", ins["id"])
    if not rows:
        return None
    avg = sum(r["condition"] for r in rows) / len(rows)
    score = max(1, min(6, round(1 + (avg - 1) * 1.25)))
    return score, f"From the {ins['type']} inspection of {ins['date'] or ''}: {len(rows)} items, average C{avg:.1f} on the 5-point inspection scale"


def score_property(pid, u, manual=None, note=None):
    if manual:
        s = int(manual)
        if not 1 <= s <= 6:
            raise HTTPException(400, "Score is C1 to C6")
        db.upd("properties", pid, condition_score=s, condition_notes=(note or f"Set by {u['name']}")[:600])
        return result(pid)
    photos = [m["url"] for m in db.q("SELECT url FROM media WHERE property_id=? AND kind='photo' ORDER BY sort LIMIT 8", pid)]
    got = ai.ask_vision(photos, "You are a South African residential valuer. Rate the condition and quality of finishes of this home from the photos on "
                                "the C1–C6 scale: C1 new/fully renovated, C2 excellent modern finishes, C3 well kept average finishes, C4 dated with normal wear, "
                                "C5 worn and needs repairs, C6 needs major work. Reply only with JSON: "
                                '{"score": n, "kitchen": "...", "bathrooms": "...", "floors": "...", "notes": "one sentence"}') if photos else None
    if got and str(got.get("score", "")).isdigit():
        s = max(1, min(6, int(got["score"])))
        notes = f"Claude, from {len(photos)} photos: " + "; ".join(f"{k} – {got[k]}" for k in ("kitchen", "bathrooms", "floors", "notes") if got.get(k))
    else:
        r = condition_from_inspection(pid)
        if not r:
            raise HTTPException(400, "No finalised inspection yet and no AI key set – pick a score by hand, or add an Anthropic key under Settings to score from photos")
        s, notes = r
    db.upd("properties", pid, condition_score=s, condition_notes=notes[:600])
    return result(pid)


def result(pid):
    p = db.q1("SELECT * FROM properties WHERE id=?", pid)
    return {"score": p["condition_score"], "word": ai.CONDITION_WORD.get(int(p["condition_score"] or 0)), "notes": p["condition_notes"],
            "adjust_pct": ai.CONDITION_ADJ.get(int(p["condition_score"] or 0)), "price": ai.comparable_rent(p)}
