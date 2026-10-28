"""Bulk email/SMS campaigns, birthday and lease-anniversary messages.

Two kinds of message:
  service   – about the lease or account (rent increase notice, water outage, new debit order date). Sent to every
              tenant/landlord in the audience; no consent needed because it is part of the service.
  marketing – news, offers, 'refer a friend', owners we'd like to manage for. POPIA s69: only to people who opted in,
              each message says who it's from and how to opt out, and an opt-out takes effect at once.
Email goes out over SMTP and SMS through BulkSMS when those are set up under Settings; otherwise messages are recorded
as simulated sends so the outbox shows exactly what would have gone out.
"""
import hashlib
import hmac
import re
import smtplib
from datetime import date
from email.message import EmailMessage

from fastapi import HTTPException

from . import compliance, db, fees

GROUPS = {"tenants": "Tenants (active leases)", "landlords": "Property owners", "prospects": "Owner prospects (from prospecting)",
          "applicants": "Applicants who did not get a home yet"}
FIELDS = ["{first_name}", "{name}", "{property}", "{suburb}", "{rent}", "{pm_name}", "{pm_phone}", "{brochure}"]


def _scope(u):
    return "" if u["role"] == "admin" else f" AND p.pm_id={int(u['id'])}"


def recipients(u, audience, kind, channel):
    g = audience.get("group")
    if g not in GROUPS:
        raise HTTPException(400, "Choose who it goes to")
    if kind == "service" and g in ("prospects", "applicants"):
        raise HTTPException(400, "Service messages are only for current tenants and owners – use a marketing message (opt-in only)")
    where, args = _scope(u), []
    if audience.get("city"):
        where += " AND p.city=?"; args.append(audience["city"])
    if audience.get("suburb"):
        where += " AND p.suburb=?"; args.append(audience["suburb"])
    if audience.get("property_id"):
        where += " AND p.id=?"; args.append(int(audience["property_id"]))
    if g == "tenants":
        rows = db.q(f"""SELECT u.id user_id, u.name, u.email, u.phone, p.title property, p.suburb, l.rent, p.pm_id FROM leases l
                        JOIN users u ON u.id=l.tenant_id JOIN properties p ON p.id=l.property_id WHERE l.status='active' AND u.active=1{where}""", *args)
    elif g == "landlords":
        rows = db.q(f"""SELECT u.id user_id, u.name, u.email, u.phone, MIN(p.title) property, MIN(p.suburb) suburb, NULL rent, MIN(p.pm_id) pm_id
                        FROM properties p JOIN users u ON u.id=p.landlord_id WHERE p.kind='rental' AND u.active=1{where} GROUP BY u.id""", *args)
    elif g == "applicants":
        rows = db.q(f"""SELECT u.id user_id, u.name, u.email, u.phone, MIN(p.title) property, MIN(p.suburb) suburb, NULL rent, MIN(p.pm_id) pm_id
                        FROM applications a JOIN users u ON u.id=a.user_id JOIN properties p ON p.id=a.property_id
                        WHERE a.status IN ('submitted','declined','withdrawn') AND u.active=1
                        AND NOT EXISTS (SELECT 1 FROM leases x WHERE x.tenant_id=u.id AND x.status IN ('active','awaiting_signature')){where} GROUP BY u.id""", *args)
    else:
        w = "" if u["role"] == "admin" else f" AND p.pm_id={int(u['id'])}"
        if audience.get("suburb"):
            w += " AND p.suburb=?"
        rows = db.q(f"""SELECT NULL user_id, p.id prospect_id, p.owner_name name, CASE WHEN p.contact_revealed THEN p.email END email,
                        CASE WHEN p.contact_revealed THEN p.phone END phone, p.address property, p.suburb, NULL rent, p.pm_id, p.do_not_contact
                        FROM prospects p WHERE 1=1{w}""", *([audience["suburb"]] if audience.get("suburb") else []))
    seen, out = set(), []
    for r in rows:
        k = r.get("user_id") or f"p{r.get('prospect_id')}"
        if k in seen:
            continue
        seen.add(k)
        addr = r["email"] if channel == "email" else r["phone"]
        reason = None
        if not addr:
            reason = f"No {'email address' if channel == 'email' else 'mobile number'}" + (" (contact not revealed)" if g == "prospects" else "")
        elif r.get("do_not_contact"):
            reason = "Asked not to be contacted"
        elif kind == "marketing":
            if r.get("user_id"):
                ok = compliance.has_consent("marketing", user_id=r["user_id"])
            else:
                ok = compliance.has_consent("marketing", email=r["email"]) or compliance.has_consent("marketing", email=r["phone"])
            if not ok:
                reason = "No marketing consent (POPIA)"
        out.append({**r, "to": addr, "excluded": reason})
    return out


def token(oid):
    return hmac.new((fees.S("public_url") or "ava").encode() + b"|unsub", str(oid).encode(), hashlib.sha256).hexdigest()[:20]


def render(text, r, pm):
    first = (r["name"] or "").split()[0] if r.get("name") else "there"
    base = (fees.S("public_url") or "").rstrip("/")
    vals = {"{first_name}": first, "{name}": r.get("name") or "", "{property}": r.get("property") or "", "{suburb}": r.get("suburb") or "",
            "{rent}": f"R{r['rent']:,.0f}".replace(",", " ") if r.get("rent") else "", "{pm_name}": pm["name"] if pm else "AVA",
            "{pm_phone}": (pm or {}).get("phone") or "", "{brochure}": f"{base}/#/pm/{pm['id']}" if pm and pm["role"] == "pm" else f"{base}/"}
    for k, v in vals.items():
        text = text.replace(k, str(v))
    return text


def preview(u, b):
    rs = recipients(u, b.get("audience") or {}, b.get("kind") or "service", b.get("channel") or "email")
    ok = [r for r in rs if not r["excluded"]]
    sample = ok[0] if ok else (rs[0] if rs else None)
    pm = pm_for(sample, u) if sample else None
    reasons = {}
    for r in rs:
        if r["excluded"]:
            reasons[r["excluded"]] = reasons.get(r["excluded"], 0) + 1
    return {"total": len(rs), "sending": len(ok), "excluded": reasons, "sms_parts": sms_parts(b.get("body") or "") if b.get("channel") == "sms" else None,
            "sample": {"to": sample["to"] if sample else None, "subject": render(b.get("subject") or "", sample, pm) if sample else "",
                       "body": decorate(render(b.get("body") or "", sample, pm), b.get("kind"), b.get("channel"), 0) if sample else ""},
            "people": [{"name": r["name"], "to": r["to"], "excluded": r["excluded"]} for r in rs[:200]]}


def sms_parts(text):
    n = len(text) + 30
    return 1 if n <= 160 else -(-n // 153)


def pm_for(r, u):
    if u["role"] == "pm":
        return u
    return db.q1("SELECT * FROM users WHERE id=?", r.get("pm_id")) if r and r.get("pm_id") else u


def decorate(body, kind, channel, oid):
    if kind != "marketing":
        return body
    base = (fees.S("public_url") or "").rstrip("/")
    link = f"{base}/api/public/unsubscribe/{oid}/{token(oid)}"
    return body + (f"\n\n—\nYou're getting this because you said AVA may send you news and offers. Unsubscribe: {link}"
                   if channel == "email" else " Reply STOP to opt out")


def create(u, b):
    if not (b.get("body") or "").strip():
        raise HTTPException(400, "Write the message")
    if b.get("channel") == "email" and not (b.get("subject") or "").strip():
        raise HTTPException(400, "Add a subject")
    import json
    return db.ins("campaigns", name=(b.get("name") or b.get("subject") or b["body"][:40]).strip(), kind=b.get("kind") or "service",
                  channel=b.get("channel") or "email", audience=json.dumps(b.get("audience") or {}), subject=b.get("subject"), body=b["body"],
                  created_by=u["id"])


def send(cid, u):
    import json
    c = db.q1("SELECT * FROM campaigns WHERE id=?", cid)
    if not c or (u["role"] != "admin" and c["created_by"] != u["id"]):
        raise HTTPException(404)
    if c["status"] != "draft":
        raise HTTPException(400, "Already sent")
    rs = recipients(u, json.loads(c["audience"] or "{}"), c["kind"], c["channel"])
    counts = {"sent": 0, "excluded": 0, "failed": 0}
    for r in rs:
        if r["excluded"]:
            db.ins("outbox", campaign_id=cid, channel=c["channel"], user_id=r.get("user_id"), prospect_id=r.get("prospect_id"), to_addr=r["to"],
                   subject=c["subject"], body="", status="skipped", reason=r["excluded"])
            counts["excluded"] += 1
            continue
        pm = pm_for(r, u)
        oid = db.ins("outbox", campaign_id=cid, channel=c["channel"], user_id=r.get("user_id"), prospect_id=r.get("prospect_id"), to_addr=r["to"],
                     subject=render(c["subject"] or "", r, pm), body="")
        db.upd("outbox", oid, body=decorate(render(c["body"], r, pm), c["kind"], c["channel"], oid))
        counts["sent" if deliver(oid) else "failed"] += 1
    db.upd("campaigns", cid, status="sent", sent_at=db.now(), counts=json.dumps(counts))
    return counts


def deliver(oid):
    o = db.q1("SELECT * FROM outbox WHERE id=?", oid)
    try:
        if o["channel"] == "email" and fees.S("smtp_host"):
            m = EmailMessage()
            m["From"], m["To"], m["Subject"] = fees.S("smtp_from") or fees.S("smtp_user"), o["to_addr"], o["subject"] or "AVA"
            m.set_content(o["body"])
            with smtplib.SMTP(fees.S("smtp_host"), int(fees.S("smtp_port") or 587), timeout=20) as s:
                s.starttls()
                if fees.S("smtp_user"):
                    s.login(fees.S("smtp_user"), fees.S("smtp_password"))
                s.send_message(m)
            ref = "smtp"
        elif o["channel"] == "sms" and fees.S("sms_api_key"):
            import httpx
            to = re.sub(r"\D", "", o["to_addr"])
            to = "27" + to[1:] if to.startswith("0") else to
            r = httpx.post("https://api.bulksms.com/v1/messages", auth=(fees.S("sms_api_key"), fees.S("sms_api_secret") or ""),
                           json={"to": to, "body": o["body"]}, timeout=20)
            r.raise_for_status()
            ref = "bulksms:" + str((r.json() or [{}])[0].get("id", ""))
        else:
            ref = f"SIM-{oid:06d}"
        db.upd("outbox", oid, status="sent", provider_ref=ref, sent_at=db.now())
        return True
    except Exception as e:
        db.upd("outbox", oid, status="failed", reason=str(e)[:200])
        return False


def unsubscribe(oid, tok):
    if not hmac.compare_digest(tok, token(oid)):
        raise HTTPException(404)
    o = db.q1("SELECT * FROM outbox WHERE id=?", oid)
    if not o:
        raise HTTPException(404)
    if o["user_id"]:
        compliance.record_consent(o["user_id"], "marketing", False, "Unsubscribe link")
    else:
        compliance.record_consent(None, "marketing", False, "Unsubscribe link", email=o["to_addr"])
        if o["prospect_id"]:
            db.upd("prospects", o["prospect_id"], do_not_contact=1, status="not_interested")
    return o["to_addr"]


# ------------------------------------------------------------------ automatic greetings
BIRTHDAY = "Happy birthday, {first_name}! 🎂 Wishing you a wonderful day and a great year ahead. – {pm_name} and the AVA team"
ANNIVERSARY = ("Hi {first_name}, it's {years} since you moved into {property}. Thank you for being a great tenant! "
               "If anything in the home needs attention, just let us know. – {pm_name}, AVA")


def greetings(today=None):
    """Daily: birthday wishes (date of birth from the FICA check) and lease anniversaries. Anyone who opted out is skipped."""
    today = today or date.today()
    md = today.strftime("%m-%d")
    ch = fees.S("greeting_channel") or "sms"
    sent = 0
    if fees.S("birthday_messages"):
        for r in db.q("""SELECT DISTINCT u.id user_id, u.name, u.email, u.phone, p.title property, p.suburb, l.rent, p.pm_id FROM users u
                         JOIN leases l ON l.tenant_id=u.id AND l.status='active' JOIN properties p ON p.id=l.property_id
                         WHERE substr(u.birthday,6,5)=? AND u.active=1
                         UNION SELECT DISTINCT u.id, u.name, u.email, u.phone, p.title, p.suburb, NULL, p.pm_id FROM users u
                         JOIN properties p ON p.landlord_id=u.id WHERE substr(u.birthday,6,5)=? AND u.active=1""", md, md):
            sent += _greet(r, ch, "Happy birthday", BIRTHDAY, today)
    if fees.S("anniversary_messages"):
        for r in db.q("""SELECT u.id user_id, u.name, u.email, u.phone, p.title property, p.suburb, l.rent, p.pm_id, l.start_date, l.id lease_id
                         FROM leases l JOIN users u ON u.id=l.tenant_id JOIN properties p ON p.id=l.property_id
                         WHERE l.status='active' AND substr(l.start_date,6,5)=? AND l.start_date < ?""", md, today.isoformat()):
            years = today.year - int(r["start_date"][:4])
            if years < 1:
                continue
            n = _greet(r, ch, "Lease anniversary", ANNIVERSARY.replace("{years}", "a year" if years == 1 else f"{years} years"), today)
            if n:
                from .services import task
                task(r["pm_id"], None, "crm", f"{r['name']}: {years}-year lease anniversary", "A good moment to check in – and to ask about renewing.",
                     f"#/app/lease/{r['lease_id']}", 3, today.isoformat(), f"anniv:{r['lease_id']}:{today.year}")
            sent += n
    return sent


def _greet(r, ch, subject, text, today):
    if db.val("SELECT 1 FROM outbox WHERE user_id=? AND subject=? AND substr(created_at,1,10)=?", r["user_id"], subject, today.isoformat()):
        return 0
    last = db.q1("SELECT granted FROM consents WHERE user_id=? AND purpose='marketing' ORDER BY id DESC LIMIT 1", r["user_id"])
    if last and not last["granted"]:      # objected to non-essential messages
        return 0
    to = r["phone"] if ch == "sms" else r["email"]
    if not to:
        return 0
    pm = db.q1("SELECT * FROM users WHERE id=?", r["pm_id"]) if r.get("pm_id") else None
    oid = db.ins("outbox", channel=ch, user_id=r["user_id"], to_addr=to, subject=subject, body=render(text, r, pm or {"name": "AVA", "role": "admin", "id": 0}),
                 created_at=f"{today.isoformat()} 08:00:00")
    deliver(oid)
    return 1
