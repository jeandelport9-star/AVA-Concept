"""HTTP routes for compliance (FICA, POPIA), growth (prospecting, earnings reports, syndication, PM brochure) and CRM."""
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from . import compliance, crm, db, fees, prospect, syndicate
from . import services as sv
from .api import OFFICE, STAFF, body, save_files
from .auth import can_prop, optional_user, prop_ids, role, user

g = APIRouter(prefix="/api")
ADMIN = role("admin")


# =================================================================== FICA
@g.get("/me/kyc")
def my_kyc(u=Depends(user)):
    return {"check": compliance.view(compliance.latest(u["id"])), "required": bool(fees.S("fica_required")) and u["role"] in ("tenant", "landlord"),
            "provider": "simulated" if not fees.S("kyc_provider_key") else fees.S("kyc_provider")}


@g.post("/me/kyc")
async def my_kyc_submit(request: Request, u=Depends(user)):
    b = await body(request)
    files = b.pop("_files", {})
    up = {}
    for k in ("id_doc", "selfie", "poa_doc"):
        if files.get(k):
            up[k] = (await save_files(files[k][:1], "kyc"))[0]
    return compliance.submit(u, u["role"], b, **up)


def kyc_scope(u):
    if u["role"] == "admin":
        return ""
    ids = prop_ids(u) or [0]
    il = ",".join(map(str, ids))
    return (f" AND (u.id IN (SELECT tenant_id FROM leases WHERE property_id IN ({il})) OR u.id IN (SELECT landlord_id FROM properties WHERE id IN ({il}))"
            f" OR u.id IN (SELECT user_id FROM applications WHERE property_id IN ({il})))")


@g.get("/compliance/kyc")
def kyc_register(u=Depends(role(*STAFF)), status: str = ""):
    rows = db.q(f"""SELECT u.id user_id, u.name, u.email, u.role, k.id, k.status, k.risk, k.submitted_at, k.verified_at, k.provider, k.review_note
                    FROM users u LEFT JOIN kyc_checks k ON k.id=(SELECT MAX(id) FROM kyc_checks WHERE user_id=u.id)
                    WHERE u.role IN ('tenant','landlord') AND u.active=1{kyc_scope(u)} ORDER BY
                    CASE COALESCE(k.status,'none') WHEN 'review' THEN 0 WHEN 'failed' THEN 1 WHEN 'none' THEN 2 ELSE 3 END, u.name""")
    if status:
        rows = [r for r in rows if (r["status"] or "none") == status]
    counts = {}
    for r in rows:
        counts[r["status"] or "none"] = counts.get(r["status"] or "none", 0) + 1
    return {"rows": rows, "counts": counts}


@g.get("/compliance/kyc/{kid}")
def kyc_get(kid: int, u=Depends(role(*STAFF))):
    k = db.q1("SELECT * FROM kyc_checks WHERE id=?", kid)
    if not k or not db.q1(f"SELECT 1 FROM users u WHERE u.id=?{kyc_scope(u)}", k["user_id"]):
        raise HTTPException(404)
    v = compliance.view(k)
    v["files"] = {"id": k["id_doc"], "selfie": k["selfie"], "poa": k["poa_doc"]}
    v["id_number"] = k["id_number"]
    v["user"] = db.q1("SELECT id, name, email, phone, role FROM users WHERE id=?", k["user_id"])
    v["history"] = [compliance.view(x) for x in db.q("SELECT * FROM kyc_checks WHERE user_id=? AND id!=? ORDER BY id DESC", k["user_id"], kid)]
    return v


@g.post("/compliance/kyc/{kid}/review")
async def kyc_review(kid: int, request: Request, u=Depends(role(*STAFF))):
    kyc_get(kid, u)
    b = await body(request)
    return compliance.review(kid, b.get("decision"), b.get("note"), u)


# =================================================================== POPIA
@g.get("/me/privacy")
def my_privacy(u=Depends(user)):
    return {"consents": compliance.my_consents(u["id"]), "requests": db.q("SELECT * FROM dsr WHERE user_id=? ORDER BY id DESC", u["id"]),
            "kinds": compliance.DSR_KINDS, "officer": {"name": fees.S("info_officer_name"), "email": fees.S("info_officer_email")}}


@g.put("/me/consents")
async def my_consents_set(request: Request, u=Depends(user)):
    b = await body(request)
    for p, v in b.items():
        if p in compliance.PURPOSES and p != "service":
            cur = compliance.has_consent(p, user_id=u["id"])
            if bool(v) != cur:
                compliance.record_consent(u["id"], p, bool(v), "Privacy settings", email=u["email"], ip=request.client.host if request.client else None)
    return compliance.my_consents(u["id"])


@g.get("/me/export")
def my_export(u=Depends(user)):
    data = json.dumps(compliance.export_user(u["id"]), indent=2, default=str)
    return Response(data, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="ava-my-data-{date.today()}.json"'})


@g.post("/me/requests")
async def my_request(request: Request, u=Depends(user)):
    b = await body(request)
    r = compliance.open_request(u, b.get("kind"), b.get("detail") or "")
    for a in db.q("SELECT id FROM users WHERE role='admin' AND active=1"):
        sv.notify(a["id"], "POPIA request", f"{u['name']}: {compliance.DSR_KINDS[r['kind']]} – respond by {r['due_date']}", "#/app/compliance/popia", "privacy")
    return r


@g.get("/compliance/requests")
def dsr_list(u=Depends(ADMIN)):
    rows = db.q("SELECT d.*, u.name, u.role FROM dsr d LEFT JOIN users u ON u.id=d.user_id ORDER BY (d.status='open') DESC, d.due_date")
    for r in rows:
        r["overdue"] = r["status"] == "open" and r["due_date"] < date.today().isoformat()
        r["kind_label"] = compliance.DSR_KINDS.get(r["kind"], r["kind"])
    return rows


@g.post("/compliance/requests/{rid}")
async def dsr_act(rid: int, request: Request, u=Depends(ADMIN)):
    b = await body(request)
    r = db.q1("SELECT * FROM dsr WHERE id=?", rid)
    if not r or r["status"] != "open":
        raise HTTPException(400, "This request is already closed")
    act = b.get("action")
    if act == "delete":
        out = compliance.process_deletion(rid, u)
    elif act in ("done", "declined"):
        if not (b.get("response") or "").strip():
            raise HTTPException(400, "Write the reply to the person")
        compliance.close_request(rid, u, b["response"].strip(), act)
        out = db.q1("SELECT * FROM dsr WHERE id=?", rid)
    else:
        raise HTTPException(400, "Unknown action")
    sv.notify(r["user_id"], "Your privacy request", out["response"][:200], "#/app/privacy", "privacy")
    return out


@g.get("/compliance/consents")
def consent_register(u=Depends(ADMIN), purpose: str = ""):
    rows = db.q(f"""SELECT c.*, u.name FROM consents c LEFT JOIN users u ON u.id=c.user_id {"WHERE c.purpose=?" if purpose else ""}
                    ORDER BY c.id DESC LIMIT 300""", *([purpose] if purpose else []))
    summary = db.q("""SELECT purpose, SUM(granted) granted, COUNT(*)-SUM(granted) withdrawn FROM consents c
                      WHERE id=(SELECT MAX(id) FROM consents x WHERE x.purpose=c.purpose AND COALESCE(x.user_id,x.email)=COALESCE(c.user_id,c.email))
                      GROUP BY purpose""")
    return {"rows": rows, "summary": summary, "purposes": compliance.PURPOSES}


@g.get("/compliance")
def compliance_overview(u=Depends(role(*STAFF))):
    k = kyc_register(u)
    out = {"kyc": k["counts"], "fica_required": bool(fees.S("fica_required")), "hold_payouts": bool(fees.S("fica_hold_payouts")),
           "provider": "simulated" if not fees.S("kyc_provider_key") else fees.S("kyc_provider"),
           "officer": {"name": fees.S("info_officer_name"), "email": fees.S("info_officer_email")}}
    if u["role"] == "admin":
        out["dsr_open"] = db.val("SELECT COUNT(*) FROM dsr WHERE status='open'")
        out["dsr_overdue"] = db.val("SELECT COUNT(*) FROM dsr WHERE status='open' AND due_date<?", date.today().isoformat())
        out["marketing_optins"] = db.val("""SELECT COUNT(*) FROM consents c WHERE purpose='marketing' AND granted=1 AND
                                            id=(SELECT MAX(id) FROM consents x WHERE x.purpose='marketing' AND COALESCE(x.user_id,x.email)=COALESCE(c.user_id,c.email))""")
    return out


# =================================================================== prospecting & earnings reports
@g.get("/growth/prospects")
def prospects(u=Depends(role(*STAFF)), status: str = "", suburb: str = ""):
    w, a = ("" if u["role"] == "admin" else " AND pm_id=?"), ([] if u["role"] == "admin" else [u["id"]])
    if status:
        w += " AND status=?"; a.append(status)
    if suburb:
        w += " AND suburb=?"; a.append(suburb)
    rows = [prospect.view(p) for p in db.q(f"SELECT * FROM prospects WHERE 1=1{w} ORDER BY owner_lives_elsewhere DESC, est_value DESC LIMIT 300", *a)]
    pipe = db.q(f"SELECT status, COUNT(*) n FROM prospects WHERE 1=1{'' if u['role'] == 'admin' else ' AND pm_id=' + str(int(u['id']))} GROUP BY status")
    suburbs = [r["suburb"] for r in db.q(f"SELECT DISTINCT suburb FROM prospects WHERE 1=1{'' if u['role'] == 'admin' else ' AND pm_id=' + str(int(u['id']))} ORDER BY suburb")]
    my_areas = db.q(f"""SELECT suburb, city, COUNT(*) n FROM properties WHERE kind='rental'{'' if u['role'] == 'admin' else ' AND pm_id=' + str(int(u['id']))}
                        GROUP BY suburb, city ORDER BY n DESC LIMIT 20""")
    return {"rows": rows, "pipeline": {r["status"]: r["n"] for r in pipe}, "suburbs": suburbs, "areas": my_areas,
            "provider": prospect.provider(), "credits": prospect.credits_left(), "statuses": prospect.STATUSES}


@g.post("/growth/prospects/search")
async def prospects_search(request: Request, u=Depends(role(*STAFF))):
    b = await body(request)
    return {"added": prospect.search_area(u, b.get("suburb") or "", b.get("city") or "")}


@g.post("/growth/prospects/{pid}/reveal")
def prospect_reveal(pid: int, u=Depends(role(*STAFF))):
    return prospect.reveal(pid, u)


@g.put("/growth/prospects/{pid}")
async def prospect_update(pid: int, request: Request, u=Depends(role(*STAFF))):
    return prospect.update(pid, u, await body(request))


@g.post("/growth/reports")
async def report_create(request: Request, u=Depends(role(*STAFF))):
    b = await body(request)
    if b.get("property_id"):
        can_prop(u, int(b["property_id"]))
    extra = None
    if not b.get("prospect_id") and not b.get("property_id"):
        extra = {k: b.get(k) for k in ("address", "suburb", "city", "type", "name")}
        extra.update(bedrooms=float(b.get("bedrooms") or 0), bathrooms=float(b.get("bathrooms") or 0), size_m2=float(b.get("size_m2") or 0) or None,
                     condition_score=int(b["condition_score"]) if b.get("condition_score") else None)
        if not extra["suburb"] or not extra["bedrooms"]:
            raise HTTPException(400, "Give at least the suburb and bedrooms")
    return prospect.create_report(u, int(b["prospect_id"]) if b.get("prospect_id") else None, int(b["property_id"]) if b.get("property_id") else None, extra)


@g.get("/growth/reports")
def reports(u=Depends(role(*STAFF))):
    rows = db.q(f"""SELECT r.id, r.token, r.views, r.last_viewed_at, r.lead_name, r.lead_phone, r.lead_email, r.lead_at, r.created_at, r.data
                    FROM earn_reports r WHERE 1=1{'' if u['role'] == 'admin' else ' AND r.pm_id=' + str(int(u['id']))} ORDER BY r.id DESC LIMIT 100""")
    for r in rows:
        d = json.loads(r.pop("data"))
        r.update(address=d.get("address"), suburb=d["suburb"], rent=d["rent"]["estimate"], owner=d.get("owner"))
    return rows


@g.get("/public/report/{token}")
def public_report(token: str):
    return prospect.public_report(token)


@g.post("/public/report/{token}/lead")
async def public_report_lead(token: str, request: Request):
    return prospect.report_lead(token, await body(request), request.client.host if request.client else None)


@g.post("/public/earn")
async def public_earn(request: Request):
    """Owner self-service: 'what can my property earn?' on the public site."""
    b = await body(request)
    city = (b.get("city") or "").strip()
    pm_id = db.val("SELECT pm_id FROM properties WHERE city=? AND pm_id IS NOT NULL GROUP BY pm_id ORDER BY COUNT(*) DESC LIMIT 1", city) \
        or db.val("SELECT id FROM users WHERE role='pm' AND active=1 ORDER BY id LIMIT 1")
    pm = db.q1("SELECT * FROM users WHERE id=?", pm_id)
    extra = {"address": b.get("address"), "suburb": (b.get("suburb") or "").strip().title(), "city": city.title(), "type": b.get("type"),
             "bedrooms": float(b.get("bedrooms") or 0), "bathrooms": float(b.get("bathrooms") or 0), "size_m2": float(b.get("size_m2") or 0) or None,
             "condition_score": int(b["condition_score"]) if b.get("condition_score") else None}
    if not extra["suburb"] or not extra["bedrooms"]:
        raise HTTPException(400, "Tell us the suburb and number of bedrooms")
    return prospect.create_report(pm, extra=extra)


@g.get("/public/pm/{pm_id}")
def public_pm(pm_id: int):
    p = prospect.pm_public(pm_id)
    if not p:
        raise HTTPException(404, "Not found")
    return p


@g.get("/growth/summary")
def growth_summary(u=Depends(role(*STAFF))):
    me = "" if u["role"] == "admin" else f" AND pm_id={int(u['id'])}"
    ids = prop_ids(u)
    return {"prospects": db.val(f"SELECT COUNT(*) FROM prospects WHERE 1=1{me}"),
            "interested": db.val(f"SELECT COUNT(*) FROM prospects WHERE status='interested'{me}"),
            "reports": db.val(f"SELECT COUNT(*) FROM earn_reports WHERE 1=1{me}"),
            "report_views": db.val(f"SELECT COALESCE(SUM(views),0) FROM earn_reports WHERE 1=1{me}"),
            "report_leads": db.val(f"SELECT COUNT(*) FROM earn_reports WHERE lead_at IS NOT NULL{me}"),
            "syndication": syndicate.overview(ids), "brochure": f"#/pm/{u['id']}" if u["role"] == "pm" else None}


# =================================================================== condition score
@g.post("/properties/{pid}/condition")
async def property_condition(pid: int, request: Request, u=Depends(role(*OFFICE))):
    can_prop(u, pid, True)
    b = await body(request)
    return prospect.score_property(pid, u, b.get("score"), b.get("note"))


# =================================================================== syndication
@g.get("/properties/{pid}/portals")
def portals(pid: int, u=Depends(role(*OFFICE))):
    can_prop(u, pid)
    return syndicate.status(pid)


@g.post("/properties/{pid}/portals/{portal}")
async def portal_set(pid: int, portal: str, request: Request, u=Depends(role(*OFFICE))):
    can_prop(u, pid, True)
    b = await body(request)
    out = syndicate.set_portal(pid, portal, b.get("on", True) not in (False, 0, "0", "false"))
    sv.log(sv.prop(pid)["pm_id"], pid, f"{'Listed on' if b.get('on', True) else 'Withdrawn from'} {syndicate.PORTALS[portal]['name']}", f"#/p/{pid}", u["name"])
    return out


@g.get("/growth/syndication")
def syndication(u=Depends(role(*OFFICE))):
    return syndicate.overview(prop_ids(u))


@g.get("/growth/leads")
def portal_leads(u=Depends(role(*OFFICE)), status: str = ""):
    return syndicate.leads(prop_ids(u), status)


@g.put("/growth/leads/{lid}")
async def portal_lead_update(lid: int, request: Request, u=Depends(role(*OFFICE))):
    l = db.q1("SELECT * FROM portal_leads WHERE id=?", lid)
    if not l:
        raise HTTPException(404)
    can_prop(u, l["property_id"])
    b = await body(request)
    if b.get("slot"):
        vid = db.ins("viewings", property_id=l["property_id"], name=l["name"], email=l["email"], phone=l["phone"], slot=b["slot"],
                     status="confirmed", notes=f"From {syndicate.PORTALS.get(l['portal'], {}).get('name', l['portal'])}: {l['message'] or ''}"[:500])
        db.upd("portal_leads", lid, status="viewing")
        return {"viewing_id": vid}
    if b.get("status") in ("new", "contacted", "viewing", "closed"):
        db.upd("portal_leads", lid, status=b["status"])
    return db.q1("SELECT * FROM portal_leads WHERE id=?", lid)


@g.get("/feeds/{portal}.xml")
def portal_feed(portal: str, key: str = ""):
    return Response(syndicate.feed_xml(portal, key), media_type="application/xml")


# =================================================================== CRM
@g.get("/crm/campaigns")
def campaigns(u=Depends(role(*STAFF))):
    rows = db.q(f"SELECT c.*, u.name author FROM campaigns c LEFT JOIN users u ON u.id=c.created_by "
                f"{'' if u['role'] == 'admin' else 'WHERE c.created_by=' + str(int(u['id']))} ORDER BY c.id DESC LIMIT 100")
    for r in rows:
        r["counts"] = json.loads(r["counts"] or "{}")
        r["audience"] = json.loads(r["audience"] or "{}")
    me = "" if u["role"] == "admin" else f" AND (o.campaign_id IN (SELECT id FROM campaigns WHERE created_by={int(u['id'])}) OR o.user_id IN (SELECT tenant_id FROM leases l JOIN properties p ON p.id=l.property_id WHERE p.pm_id={int(u['id'])}))"
    auto = db.q(f"""SELECT o.*, u.name FROM outbox o LEFT JOIN users u ON u.id=o.user_id WHERE o.campaign_id IS NULL{me} ORDER BY o.id DESC LIMIT 30""")
    sim = {"email": not fees.S("smtp_host"), "sms": not fees.S("sms_api_key")}
    return {"campaigns": rows, "automatic": auto, "groups": crm.GROUPS, "fields": crm.FIELDS, "simulated": sim,
            "greetings": {"birthday": bool(fees.S("birthday_messages")), "anniversary": bool(fees.S("anniversary_messages")), "channel": fees.S("greeting_channel")}}


@g.post("/crm/preview")
async def campaign_preview(request: Request, u=Depends(role(*STAFF))):
    return crm.preview(u, await body(request))


@g.post("/crm/campaigns")
async def campaign_create(request: Request, u=Depends(role(*STAFF))):
    b = await body(request)
    cid = crm.create(u, b)
    if b.get("send"):
        return {"id": cid, "counts": crm.send(cid, u)}
    return {"id": cid}


@g.post("/crm/campaigns/{cid}/send")
def campaign_send(cid: int, u=Depends(role(*STAFF))):
    return crm.send(cid, u)


@g.get("/crm/campaigns/{cid}")
def campaign_get(cid: int, u=Depends(role(*STAFF))):
    c = db.q1("SELECT * FROM campaigns WHERE id=?", cid)
    if not c or (u["role"] != "admin" and c["created_by"] != u["id"]):
        raise HTTPException(404)
    c["counts"] = json.loads(c["counts"] or "{}")
    c["audience"] = json.loads(c["audience"] or "{}")
    c["outbox"] = db.q("SELECT o.*, u.name FROM outbox o LEFT JOIN users u ON u.id=o.user_id WHERE campaign_id=? ORDER BY o.status, o.id", cid)
    return c


@g.get("/public/unsubscribe/{oid}/{tok}", response_class=HTMLResponse)
def unsubscribe(oid: int, tok: str):
    import html
    to = html.escape(crm.unsubscribe(oid, tok) or "")
    return f"""<!doctype html><meta name=viewport content="width=device-width"><title>Unsubscribed</title>
<body style="font-family:system-ui;max-width:520px;margin:60px auto;padding:0 16px;color:#1d2a3a"><h2>You're unsubscribed</h2>
<p>{to} won't get news or offers from AVA again. You'll still hear from us about a lease or account you have with us.</p>
<p><a href="/">Back to AVA</a></p></body>"""


@g.get("/compliance-public")
def compliance_public():
    return {"name": fees.S("info_officer_name"), "email": fees.S("info_officer_email")}
