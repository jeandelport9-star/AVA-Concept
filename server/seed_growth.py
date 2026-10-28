"""Demo data for compliance (FICA, POPIA) and growth (prospecting, reports, portals, campaigns)."""
import json
import random
from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from . import compliance, crm, db, fees, prospect, syndicate

rnd = random.Random(11)


def sa_id(dob, male=True):
    seq = rnd.randint(5000, 9999) if male else rnd.randint(0, 4999)
    base = f"{dob:%y%m%d}{seq:04d}08"
    for z in range(10):
        if compliance.luhn_ok(base + str(z)):
            return base + str(z)


def selfie(name):
    folder = db.UPLOADS / "kyc" / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (360, 440), (222, 228, 232))
    d = ImageDraw.Draw(im)
    tone = rnd.choice([(141, 85, 36), (198, 134, 66), (224, 172, 105), (241, 194, 125), (90, 56, 37)])
    d.ellipse([110, 90, 250, 260], fill=tone)
    d.rectangle([80, 300, 280, 440], fill=rnd.choice([(40, 70, 110), (120, 40, 50), (50, 90, 70)]))
    d.ellipse([140, 300 - 60, 220, 320], fill=tone)
    fn = f"selfie_{abs(hash(name)) % 10**8}.jpg"
    im.save(folder / fn, quality=80)
    return f"/uploads/kyc/demo/{fn}"


def doc(name):
    from .seed import demo_pdf
    return demo_pdf(name)


def kyc(u, status="verified", days_ago=None, poa_age=20, note=None):
    first, *rest = u["name"].split()
    dob = date(rnd.randint(1962, 1998), rnd.randint(1, 12), rnd.randint(1, 28))
    when = datetime.now() - timedelta(days=days_ago if days_ago is not None else rnd.randint(30, 400))
    idn = sa_id(dob, rnd.random() < 0.5)
    poa = (when.date() - timedelta(days=poa_age)).isoformat()
    checks = [{"name": "ID number", "result": "pass", "detail": f"Valid SA ID · SA citizen · born {dob}"},
              {"name": "Age", "result": "pass", "detail": f"{compliance.age(dob.isoformat())} years old"},
              {"name": "Home Affairs (DHA)", "result": "pass", "detail": "Name and ID number match the population register; not reported deceased (simulated)"},
              {"name": "Selfie face match & liveness", "result": "pass", "detail": "Selfie matches the ID photo (score 0.94), live person (simulated)"},
              {"name": "Proof of address", "result": "pass" if poa_age <= 92 else "warn", "detail": f"Document dated {poa}" + ("" if poa_age <= 92 else " – older than 3 months")},
              {"name": "Sanctions & PEP screening", "result": "pass", "detail": "No match on sanctions, PEP and adverse-media lists (simulated)"},
              {"name": "Duplicate identity", "result": "pass", "detail": "ID number not used by any other account"}]
    db.ins("kyc_checks", user_id=u["id"], context=u["role"], status=status, id_type="sa_id", id_number=idn, first_names=first, surname=" ".join(rest) or first,
           dob=dob.isoformat(), gender="male" if int(idn[6:10]) >= 5000 else "female", citizenship="SA citizen", address=f"{rnd.randint(1, 99)} {rnd.choice(prospect.STREETS)} Street",
           poa_date=poa, id_doc=doc(f"id_{u['id']}.pdf"), selfie=selfie(u["name"]), poa_doc=doc(f"poa_{u['id']}.pdf"), checks=json.dumps(checks),
           risk="low" if status == "verified" else "medium", provider="simulated", submitted_at=when.isoformat(timespec="seconds"),
           verified_at=when.isoformat(timespec="seconds") if status == "verified" else None, review_note=note, created_at=when.isoformat(timespec="seconds"))
    db.ins("consents", user_id=u["id"], email=u["email"], purpose="fica", granted=1, source="FICA verification", version="2026-01", created_at=when.isoformat(timespec="seconds"))
    db.exe("UPDATE users SET birthday=?, verified=? WHERE id=?", dob.isoformat(), 1 if status == "verified" else 0, u["id"])
    return dob


def run(admin, thandi, pieter):
    today = date.today()
    users = {r["id"]: r for r in db.q("SELECT * FROM users")}
    tenants = [u for u in users.values() if u["role"] == "tenant"]
    landlords = [u for u in users.values() if u["role"] == "landlord"]
    active_t = {r["tenant_id"] for r in db.q("SELECT tenant_id FROM leases WHERE status IN ('active','awaiting_signature','ended')")}

    # ---------------------------------------------------------- FICA
    for u in landlords[:-1]:
        kyc(u)
    review_t = None
    for i, u in enumerate(sorted(tenants, key=lambda x: x["id"])):
        if u["id"] not in active_t:
            continue            # applicants without a home yet: not checked
        if review_t is None and i >= 3:
            review_t = u
            kyc(u, "review", days_ago=2, poa_age=140)
        else:
            kyc(u)
    # one applicant has done it, another hasn't
    apps = db.q("SELECT DISTINCT user_id FROM applications WHERE status IN ('submitted','screening','shortlisted') AND user_id IS NOT NULL")
    if apps:
        kyc(users[apps[0]["user_id"]], days_ago=1)
    # a birthday today and a lease anniversary today, so the automatic greetings show
    bt = next((u for u in tenants if u["id"] in active_t and (not review_t or u["id"] != review_t["id"])), None)
    if bt:
        b = db.val("SELECT birthday FROM users WHERE id=?", bt["id"])
        if b:
            db.exe("UPDATE users SET birthday=? WHERE id=?", f"{b[:4]}-{today:%m-%d}", bt["id"])
    an = db.q1("SELECT id, start_date FROM leases WHERE status='active' AND start_date < ? ORDER BY start_date LIMIT 1", (today - timedelta(days=400)).isoformat())

    # ---------------------------------------------------------- POPIA consents
    for u in users.values():
        if u["role"] in ("tenant", "landlord", "pm"):
            when = (datetime.fromisoformat(u["created_at"]) if u["created_at"] else datetime.now()).isoformat(timespec="seconds")
            db.ins("consents", user_id=u["id"], email=u["email"], purpose="service", granted=1, source="Sign-up (privacy notice accepted)", version="2026-01", created_at=when)
            if u["role"] == "tenant":
                db.ins("consents", user_id=u["id"], email=u["email"], purpose="credit_check", granted=1, source="Rental application", version="2026-01", created_at=when)
            if rnd.random() < 0.6:
                db.ins("consents", user_id=u["id"], email=u["email"], purpose="marketing", granted=1, source="Sign-up form", version="2026-01", created_at=when)
    # someone changed their mind
    if tenants:
        t = tenants[-1]
        compliance.record_consent(t["id"], "marketing", True, "Sign-up form", email=t["email"])
        db.ins("consents", user_id=t["id"], email=t["email"], purpose="marketing", granted=0, source="Unsubscribe link", version=compliance.VERSION,
               created_at=(datetime.now() - timedelta(days=9)).isoformat(timespec="seconds"))
    # data-subject requests: one open, one answered
    if len(tenants) > 4:
        a, b = tenants[2], tenants[4]
        db.ins("dsr", user_id=a["id"], email=a["email"], kind="access", detail="Please send me everything you keep about me.", due_date=(today + timedelta(days=24)).isoformat(),
               created_at=(datetime.now() - timedelta(days=6)).isoformat(timespec="seconds"))
        db.ins("dsr", user_id=b["id"], email=b["email"], kind="correction", detail="My surname is spelled wrong on the lease.", status="done",
               due_date=(today - timedelta(days=10)).isoformat(), response="Corrected on your profile and the lease addendum – thank you.", handled_by=admin,
               completed_at=(datetime.now() - timedelta(days=36)).isoformat(timespec="seconds"), created_at=(datetime.now() - timedelta(days=40)).isoformat(timespec="seconds"))

    # ---------------------------------------------------------- PM bio
    db.upd("users", thandi, bio="I've managed rentals in Pretoria East for eleven years. On AVA I look after homes in Brooklyn, Lynnwood, Waterkloof and Menlo Park: "
                              "I vet every tenant myself, inspect in 360° so there are no arguments at move-out, and owners are paid on the 7th with a statement they can read. "
                              "Call me – I answer my own phone.")

    # ---------------------------------------------------------- condition scores from inspections
    for p in db.q("SELECT DISTINCT property_id FROM inspections WHERE status='final'"):
        r = prospect.condition_from_inspection(p["property_id"])
        if r:
            db.upd("properties", p["property_id"], condition_score=r[0], condition_notes=r[1])

    # ---------------------------------------------------------- prospecting
    pm_t = db.q1("SELECT * FROM users WHERE id=?", thandi)
    pm_p = db.q1("SELECT * FROM users WHERE id=?", pieter)
    for sub, city in (("Brooklyn", "Pretoria"), ("Waterkloof", "Pretoria"), ("Lynnwood", "Pretoria")):
        prospect.search_area(pm_t, sub, city, n=12)
    prospect.search_area(pm_p, "Gardens", "Cape Town", n=10)
    rows = db.q("SELECT * FROM prospects WHERE pm_id=? ORDER BY owner_lives_elsewhere DESC, est_value DESC", thandi)
    for i, p in enumerate(rows[:7]):
        prospect.reveal(p["id"], pm_t)
        st = ["contacted", "report_sent", "report_sent", "interested", "signed", "not_interested", "contacted"][i]
        db.upd("prospects", p["id"], status=st, note=["Left a voicemail.", "Spoke to the owner – tenant leaving in March.", "Sent the report on WhatsApp.",
                                                          "Wants a call after the report.", "Signed – listing next month.", "Happy with current agent.", "Call back Friday."][i])
        if st == "not_interested":
            db.upd("prospects", p["id"], do_not_contact=1)
            compliance.record_consent(None, "prospecting", False, "Owner objected by phone (logged by Thandi Mokoena)", email=p["email"])
        if st in ("report_sent", "interested", "signed"):
            r = prospect.create_report(pm_t, prospect_id=p["id"])
            tok = r["token"]
            db.exe("UPDATE earn_reports SET views=?, last_viewed_at=?, created_at=? WHERE token=?", rnd.randint(1, 6),
                   (datetime.now() - timedelta(hours=rnd.randint(2, 90))).isoformat(timespec="seconds"), (datetime.now() - timedelta(days=rnd.randint(3, 20))).isoformat(timespec="seconds"), tok)
            db.upd("prospects", p["id"], status=st)
            if st in ("interested", "signed"):
                db.exe("UPDATE earn_reports SET lead_name=?, lead_phone=?, lead_email=?, lead_at=? WHERE token=?", p["owner_name"] if p["owner_type"] == "Private person" else "Trustee",
                       p["phone"], p["email"], (datetime.now() - timedelta(days=rnd.randint(1, 5))).isoformat(timespec="seconds"), tok)
                compliance.record_consent(None, "prospecting", True, f"Earnings report {tok} – contact form", email=p["email"])
                compliance.record_consent(None, "marketing", True, f"Earnings report {tok} – contact form", email=p["email"])
    fees_credits = fees.S("loom_credits")
    db.set_setting("loom_credits", fees_credits)

    # ---------------------------------------------------------- syndication: the live listings on both portals for 3 weeks
    for p in db.q("SELECT * FROM properties WHERE listing_status='live' AND kind='rental'"):
        if syndicate.ready(p):
            continue
        for portal in ("property24", "privateproperty"):
            if portal == "privateproperty" and p["id"] % 3 == 0:
                continue
            syndicate.set_portal(p["id"], portal, True)
            db.exe("UPDATE syndications SET pushed_at=? WHERE property_id=? AND portal=?", (datetime.now() - timedelta(days=21)).isoformat(timespec="seconds"), p["id"], portal)
    for d in range(21, 0, -1):
        syndicate.simulate_activity(today - timedelta(days=d))
    old = db.q("SELECT id FROM portal_leads ORDER BY created_at LIMIT 100")
    for i, l in enumerate(old[:-4]):
        db.upd("portal_leads", l["id"], status="closed" if i % 3 else "viewing")

    # ---------------------------------------------------------- campaigns (sent through the simulated outbox)
    def camp(u, name, kind, channel, aud, subject, body, days):
        cid = crm.create(u, {"name": name, "kind": kind, "channel": channel, "audience": aud, "subject": subject, "body": body})
        crm.send(cid, u)
        when = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        db.exe("UPDATE campaigns SET sent_at=?, created_at=? WHERE id=?", when, when, cid)
        db.exe("UPDATE outbox SET created_at=?, sent_at=? WHERE campaign_id=?", when, when, cid)
    camp(pm_t, "Water outage – Brooklyn", "service", "sms", {"group": "tenants", "suburb": "Brooklyn"}, "",
         "Hi {first_name}, Tshwane has announced a water outage in Brooklyn on Thursday 08:00–18:00 for pipe repairs. Please store water. – {pm_name}, AVA", 12)
    camp(pm_t, "New debit order date", "service", "email", {"group": "tenants"}, "Your rent debit order moves to the 1st",
         "Hi {first_name},\n\nFrom next month your rent of {rent} for {property} is collected by DebiCheck on the 1st instead of the 3rd, so owners are paid on time. "
         "You don't need to do anything – your bank already approved the mandate.\n\nQuestions? Reply here or call me on {pm_phone}.\n\n{pm_name}", 30)
    camp(pm_t, "Refer an owner", "marketing", "email", {"group": "landlords"}, "Know someone with a rental? R1 000 thank-you",
         "Hi {first_name},\n\nThank you for trusting AVA with {property}. If you know an owner who's paying an agent 10% + VAT, send them my profile: {brochure}\n\n"
         "When their home is let through AVA we'll send you R1 000 as a thank-you.\n\n{pm_name}", 18)
    crm.create(pm_t, {"name": "Winter tips", "kind": "marketing", "channel": "email", "audience": {"group": "tenants"}, "subject": "Five ways to cut your winter electricity bill",
                            "body": "Hi {first_name},\n\nWinter is here – here are five quick ways to keep {property} warm for less…"})
    # last year's greetings so the list isn't empty on day one
    if an:
        r = db.q1("SELECT u.id user_id, u.name, u.email, u.phone, p.title property, p.suburb, l.rent, p.pm_id, l.start_date, l.id lease_id FROM leases l JOIN users u ON u.id=l.tenant_id "
                  "JOIN properties p ON p.id=l.property_id WHERE l.id=?", an["id"])
        crm._greet(r, "sms", "Lease anniversary", crm.ANNIVERSARY.replace("{years}", "a year"), today - timedelta(days=rnd.randint(20, 60)))
    return {"kyc": db.val("SELECT COUNT(*) FROM kyc_checks"), "prospects": db.val("SELECT COUNT(*) FROM prospects"),
            "syndicated": db.val("SELECT COUNT(*) FROM syndications WHERE status='live'"), "portal_leads": db.val("SELECT COUNT(*) FROM portal_leads"),
            "messages": db.val("SELECT COUNT(*) FROM outbox")}
