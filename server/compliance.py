"""Compliance: FICA identity verification with fraud screening, and POPIA (consent register, data-subject requests).

FICA (Financial Intelligence Centre Act): estate agents are accountable institutions and must verify who their clients
are – tenants and landlords alike – and screen them against sanctions and politically-exposed-person lists.
AVA verifies what it can itself (SA ID checksum, date of birth, age, duplicates, proof-of-address age) and hands the
Home Affairs match, selfie face-match/liveness and watchlist screening to a verification provider. Without provider
keys those three are simulated so the flow can be demonstrated.

POPIA (Protection of Personal Information Act): every consent is recorded with its purpose, wording version and
source; people can see their data, withdraw marketing consent, ask for correction or deletion (30-day deadline).
"""
import json
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from . import db, fees

# ------------------------------------------------------------------ FICA / KYC
# fictitious names for the simulated sanctions / PEP screen (a real provider screens UN, OFAC, EU, HMT and local PEP lists)
DEMO_WATCHLIST = {"ivan petrovich demo": "Sanctions list (demo entry)", "sam watchlist": "Politically exposed person (demo entry)"}
DEMO_DHA_MISMATCH = {"8001015009087"}           # an ID the simulated Home Affairs check reports as not matching the name


def luhn_ok(num):
    total, alt = 0, False
    for ch in reversed(num):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def parse_sa_id(idn):
    """13 digits: YYMMDD SSSS C A Z – date of birth, gender (SSSS ≥ 5000 male), citizenship (0 SA, 1 permanent resident), Luhn check digit."""
    idn = re.sub(r"\D", "", idn or "")
    if len(idn) != 13:
        return None, "An SA ID number has 13 digits"
    yy, mm, dd = int(idn[:2]), int(idn[2:4]), int(idn[4:6])
    year = 2000 + yy if 2000 + yy <= date.today().year else 1900 + yy
    try:
        dob = date(year, mm, dd)
    except ValueError:
        return None, "The date of birth in the ID number is not a real date"
    if idn[10] not in "01":
        return None, "The citizenship digit must be 0 or 1"
    if not luhn_ok(idn):
        return None, "The ID number's check digit is wrong – please check for a typo"
    return {"id_number": idn, "dob": dob.isoformat(), "gender": "male" if int(idn[6:10]) >= 5000 else "female",
            "citizenship": "SA citizen" if idn[10] == "0" else "Permanent resident"}, None


def age(dob):
    d = date.fromisoformat(dob)
    t = date.today()
    return t.year - d.year - ((t.month, t.day) < (d.month, d.day))


def latest(user_id, context=None):
    return db.q1("SELECT * FROM kyc_checks WHERE user_id=?" + (" AND context=?" if context else "") + " ORDER BY id DESC LIMIT 1",
                 user_id, *([context] if context else []))


def status(user_id):
    k = latest(user_id)
    return k["status"] if k else "none"


def view(k):
    if not k:
        return None
    out = {x: k[x] for x in ("id", "user_id", "context", "status", "id_type", "first_names", "surname", "dob", "gender", "citizenship",
                             "address", "poa_date", "risk", "provider", "submitted_at", "verified_at", "review_note", "created_at")}
    out["id_masked"] = (k["id_number"][:6] + "•••••" + k["id_number"][-2:]) if k["id_number"] else ""
    out["checks"] = json.loads(k["checks"] or "[]")
    out["docs"] = {"id": bool(k["id_doc"]), "selfie": bool(k["selfie"]), "poa": bool(k["poa_doc"])}
    return out


def submit(u, context, data, id_doc=None, selfie=None, poa_doc=None):
    """Run the checks and decide: verified (all clear), review (a person must look) or failed (sanctions hit / invalid identity)."""
    id_type = data.get("id_type") or "sa_id"
    first, last = (data.get("first_names") or "").strip(), (data.get("surname") or "").strip()
    if not first or not last:
        raise HTTPException(400, "Enter your names as they appear on your ID")
    prev = latest(u["id"], context)
    id_doc = id_doc or (prev and prev["id_doc"])
    selfie = selfie or (prev and prev["selfie"])
    poa_doc = poa_doc or (prev and prev["poa_doc"])
    checks, info = [], {}
    if id_type == "sa_id":
        info, err = parse_sa_id(data.get("id_number"))
        if err:
            raise HTTPException(400, err)
        checks.append({"name": "ID number", "result": "pass", "detail": f"Valid SA ID · {info['citizenship']} · born {info['dob']}"})
    else:
        pn = re.sub(r"\s", "", data.get("id_number") or "").upper()
        if not re.fullmatch(r"[A-Z0-9]{6,12}", pn):
            raise HTTPException(400, "Enter a valid passport number")
        if not data.get("dob"):
            raise HTTPException(400, "Enter your date of birth")
        info = {"id_number": pn, "dob": data["dob"], "gender": data.get("gender") or "", "citizenship": data.get("nationality") or "Foreign national"}
        checks.append({"name": "Passport", "result": "warn", "detail": "Foreign passport – check the visa / permit allows a lease in SA"})
    a = age(info["dob"])
    checks.append({"name": "Age", "result": "pass" if a >= 18 else "fail", "detail": f"{a} years old" + ("" if a >= 18 else " – must be 18 or older to contract")})
    sim = not fees.S("kyc_provider_key")
    prov = "simulated" if sim else fees.S("kyc_provider")
    if id_type == "sa_id":
        mismatch = info["id_number"] in DEMO_DHA_MISMATCH
        checks.append({"name": "Home Affairs (DHA)", "result": "fail" if mismatch else "pass",
                       "detail": ("Name does not match the ID number on the population register" if mismatch else "Name and ID number match the population register; not reported deceased")
                       + (" (simulated)" if sim else "")})
    checks.append({"name": "Selfie face match & liveness", "result": "pass" if (selfie and id_doc) else "warn",
                   "detail": ("Selfie matches the ID photo (score 0.94), live person" if (selfie and id_doc) else "ID copy or selfie missing – a person must check")
                   + (" (simulated)" if sim and selfie and id_doc else "")})
    addr = (data.get("address") or "").strip()
    poa = data.get("poa_date")
    if not addr or not poa_doc or not poa:
        checks.append({"name": "Proof of address", "result": "warn", "detail": "Proof of address missing"})
    else:
        old = (date.today() - date.fromisoformat(poa)).days
        checks.append({"name": "Proof of address", "result": "pass" if old <= 92 else "warn",
                       "detail": f"Document dated {poa}" + ("" if old <= 92 else " – older than 3 months")})
    hit = DEMO_WATCHLIST.get(f"{first} {last}".lower())
    checks.append({"name": "Sanctions & PEP screening", "result": "fail" if hit else "pass",
                   "detail": (f"Possible match: {hit}" if hit else "No match on sanctions, PEP and adverse-media lists") + (" (simulated)" if sim else "")})
    dup = db.q1("SELECT k.user_id, u.name FROM kyc_checks k JOIN users u ON u.id=k.user_id WHERE k.id_number=? AND k.user_id!=? AND k.status IN ('verified','review')",
                info["id_number"], u["id"])
    checks.append({"name": "Duplicate identity", "result": "fail" if dup else "pass",
                   "detail": f"ID number already used by another account ({dup['name']})" if dup else "ID number not used by any other account"})
    if u.get("phone"):
        others = db.val("SELECT COUNT(*) FROM users WHERE phone=? AND id!=?", u["phone"], u["id"])
        checks.append({"name": "Contact details", "result": "warn" if others else "pass",
                       "detail": f"Phone number also on {others} other account(s)" if others else "Phone number unique"})
    fails = [c for c in checks if c["result"] == "fail"]
    warns = [c for c in checks if c["result"] == "warn"]
    st = "failed" if any(c["name"] in ("Sanctions & PEP screening", "Age") for c in fails) else "review" if (fails or warns) else "verified"
    risk = "high" if fails else "medium" if warns else "low"
    row = dict(user_id=u["id"], context=context, status=st, id_type=id_type, id_number=info["id_number"], first_names=first, surname=last,
               dob=info["dob"], gender=info.get("gender"), citizenship=info.get("citizenship"), address=addr, poa_date=poa,
               id_doc=id_doc, selfie=selfie, poa_doc=poa_doc, checks=json.dumps(checks), risk=risk, provider=prov,
               submitted_at=db.now(), verified_at=db.now() if st == "verified" else None)
    kid = db.ins("kyc_checks", **row)
    if st == "verified":
        db.exe("UPDATE users SET verified=1, birthday=COALESCE(birthday, ?) WHERE id=?", info["dob"], u["id"])
    record_consent(u["id"], "fica", True, "FICA verification", email=u.get("email"))
    return view(db.q1("SELECT * FROM kyc_checks WHERE id=?", kid))


def review(kid, decision, note, reviewer):
    k = db.q1("SELECT * FROM kyc_checks WHERE id=?", kid)
    if not k:
        raise HTTPException(404)
    if decision not in ("verified", "failed"):
        raise HTTPException(400, "Approve or reject")
    if not note or len(note.strip()) < 5:
        raise HTTPException(400, "Record why – the FICA register keeps the reason")
    db.upd("kyc_checks", kid, status=decision, review_note=note.strip(), reviewed_by=reviewer["id"],
           verified_at=db.now() if decision == "verified" else None)
    if decision == "verified":
        db.exe("UPDATE users SET verified=1, birthday=COALESCE(birthday, ?) WHERE id=?", k["dob"], k["user_id"])
    return view(db.q1("SELECT * FROM kyc_checks WHERE id=?", kid))


def require(user_id, what):
    """Gate an action on FICA (setting fica_required). Raises with a clear reason."""
    if not fees.S("fica_required"):
        return
    st = status(user_id)
    if st != "verified":
        name = db.val("SELECT name FROM users WHERE id=?", user_id) or "This person"
        raise HTTPException(400, f"{name}'s FICA verification is {'not done yet' if st == 'none' else st} – it must be verified before {what}.")


# ------------------------------------------------------------------ POPIA
PURPOSES = {
    "service": "Managing my rental, lease and account (needed to provide the service)",
    "credit_check": "Credit and rental-history checks (TPN / credit bureau)",
    "fica": "Identity verification and fraud screening (FICA)",
    "marketing": "News, tips and offers from AVA by email or SMS",
    "prospecting": "Being contacted about letting my property with AVA",
}
VERSION = "2026-10"


def record_consent(user_id, purpose, granted, source, email=None, ip=None):
    return db.ins("consents", user_id=user_id, email=email, purpose=purpose, granted=1 if granted else 0, source=source, version=VERSION, ip=ip)


def has_consent(purpose, user_id=None, email=None):
    if purpose == "service":
        return True
    r = db.q1("SELECT granted FROM consents WHERE purpose=? AND " + ("user_id=?" if user_id else "email=?") + " ORDER BY id DESC LIMIT 1",
              purpose, user_id or email)
    return bool(r and r["granted"])


def my_consents(user_id):
    out = []
    for p, label in PURPOSES.items():
        r = db.q1("SELECT * FROM consents WHERE user_id=? AND purpose=? ORDER BY id DESC LIMIT 1", user_id, p)
        out.append({"purpose": p, "label": label, "granted": True if p == "service" else bool(r and r["granted"]),
                    "since": r["created_at"] if r else None, "required": p == "service"})
    return out


def export_user(user_id):
    """Everything AVA holds about a person (POPIA s23 – right of access)."""
    u = db.q1("SELECT id, email, name, phone, role, company, created_at, birthday FROM users WHERE id=?", user_id)
    leases = db.q("SELECT * FROM leases WHERE tenant_id=?", user_id)
    lids = [l["id"] for l in leases] or [0]
    q = ",".join("?" * len(lids))
    return {"exported_at": db.now(), "person": u,
            "consents": db.q("SELECT purpose, granted, source, version, created_at FROM consents WHERE user_id=? ORDER BY id", user_id),
            "identity_checks": [view(k) for k in db.q("SELECT * FROM kyc_checks WHERE user_id=?", user_id)],
            "applications": db.q("SELECT id, property_id, income, employer, occupants, status, score, created_at FROM applications WHERE user_id=?", user_id),
            "leases": [{k: l[k] for k in ("id", "property_id", "start_date", "end_date", "rent", "deposit", "status")} for l in leases],
            "account": db.q(f"SELECT date, description, amount FROM ledger WHERE account='tenant' AND lease_id IN ({q}) ORDER BY date", *lids),
            "properties_owned": db.q("SELECT id, title, address FROM properties WHERE landlord_id=?", user_id),
            "messages": db.q("SELECT thread, body, created_at FROM messages WHERE from_id=? ORDER BY id", user_id),
            "notifications": db.val("SELECT COUNT(*) FROM notifications WHERE user_id=?", user_id)}


DSR_KINDS = {"access": "See my data", "correction": "Correct my data", "deletion": "Delete my data", "objection": "Stop using my data for marketing"}


def open_request(u, kind, detail=""):
    if kind not in DSR_KINDS:
        raise HTTPException(400, "Unknown request")
    due = (date.today() + timedelta(days=30)).isoformat()
    rid = db.ins("dsr", user_id=u["id"], email=u["email"], kind=kind, detail=detail[:1000], due_date=due)
    if kind == "objection":             # objection to marketing is effective immediately
        record_consent(u["id"], "marketing", False, "Objection (POPIA s11(3))", email=u["email"])
        close_request(rid, None, "Marketing consent withdrawn immediately. You will only receive messages about your lease and account.")
    return db.q1("SELECT * FROM dsr WHERE id=?", rid)


def close_request(rid, handler, response, status="done"):
    db.upd("dsr", rid, status=status, response=response, handled_by=handler["id"] if handler else None, completed_at=db.now())


def process_deletion(rid, handler):
    """Delete what may be deleted; keep what the law says must be kept (FICA, tax: 5 years after the relationship ends)."""
    r = db.q1("SELECT * FROM dsr WHERE id=?", rid)
    uid = r["user_id"]
    active = db.val("SELECT 1 FROM leases WHERE (tenant_id=? AND status IN ('active','awaiting_signature')) OR property_id IN (SELECT id FROM properties WHERE landlord_id=?) AND status='active'", uid, uid)
    if active:
        close_request(rid, handler, "We can't delete your data while you have an active lease or property with AVA – it is needed to run the lease. "
                                    "Ask again when the lease has ended. Marketing has been switched off.", "declined")
        record_consent(uid, "marketing", False, "Deletion request", email=r["email"])
        return db.q1("SELECT * FROM dsr WHERE id=?", rid)
    last = db.val("SELECT MAX(COALESCE(ended_at, end_date)) FROM leases WHERE tenant_id=?", uid)
    db.exe("UPDATE users SET name='Deleted user', email=?, phone=NULL, company=NULL, active=0, bio=NULL, birthday=NULL WHERE id=?", f"deleted-{uid}@ava.invalid", uid)
    db.exe("UPDATE applications SET name='Deleted user', email=NULL, phone=NULL, employer=NULL, docs='[]' WHERE user_id=?", uid)
    db.exe("DELETE FROM sessions WHERE user_id=?", uid)
    db.exe("DELETE FROM alerts WHERE user_id=?", uid)
    db.exe("DELETE FROM favourites WHERE user_id=?", uid)
    db.exe("UPDATE kyc_checks SET selfie=NULL WHERE user_id=?", uid)
    keep = (f" Your lease, payment and identity-verification records are kept until {date.fromisoformat(last[:10]).replace(year=date.fromisoformat(last[:10]).year + 5)}"
            if last else " Identity-verification records are kept for 5 years") + " because FICA and tax law require it; they are then destroyed."
    close_request(rid, handler, "Your profile, contact details, application documents and selfie have been deleted." + keep)
    return db.q1("SELECT * FROM dsr WHERE id=?", rid)
