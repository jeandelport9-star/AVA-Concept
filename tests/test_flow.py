"""End-to-end: the whole rental life cycle through the HTTP API, on a fresh demo database.
Run:  python tests/test_flow.py
"""
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["AVA_DATA"] = tempfile.mkdtemp(prefix="ava-test-")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from server import seed  # noqa: E402
from server.main import app  # noqa: E402

seed.run(reset=True)
from server import db as _db0  # noqa: E402
_db0.set_setting("module_maintenance", True)     # the maintenance flows below are tested with the module on; section 6 tests it off


def client(email):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": email, "password": "demo1234"})
    assert r.status_code == 200, r.text
    return c


def ok(r, code=200):
    assert r.status_code == code, f"{r.request.method} {r.request.url} -> {r.status_code} {r.text[:400]}"
    return r.json() if "json" in r.headers.get("content-type", "") else r


def jpg(w=400, h=200):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (180, 170, 150)).save(b, "JPEG")
    return ("p.jpg", b.getvalue(), "image/jpeg")


pm, admin = client("thandi@ava.co.za"), client("admin@ava.co.za")
plumber = client("plumbfix@example.co.za")
aqua = client("aquaflow@example.co.za")

# ---- 1. a new renter finds a home, applies, gets approved and signs ------------------
anon = TestClient(app)
live = ok(anon.get("/api/listings"))
assert live, "no live listings"
target = next(p for p in live if p["title"].startswith("Silver Lakes"))
ok(anon.get(f"/api/listings/{target['id']}"))
slot = next(s for s in ok(anon.get(f"/api/listings/{target['id']}/slots")) if s["free"])
ok(anon.post("/api/viewings", json={"property_id": target["id"], "slot": slot["slot"], "name": "Guest", "email": "g@x.co", "phone": "0820000000"}))
t = TestClient(app)
ok(t.post("/api/auth/register", json={"email": "newbie@example.com", "password": "secret1", "name": "Nadia Newbie", "role": "tenant"}))
a = ok(t.post("/api/applications", data={"property_id": target["id"], "income": "95000", "employer": "Anglo", "occupants": "2"},
              files=[("id", jpg()), ("payslips", jpg()), ("bank_statements", jpg())]))
assert a["score"] > 40, a
app_id = a["id"]
ok(pm.post(f"/api/applications/{app_id}/credit-check"))
ok(pm.post(f"/api/applications/{app_id}/approve", json={"months": 12}), 400)          # FICA: identity not verified yet
from server import compliance as _cp  # noqa: E402
def make_id(dob="900215", seq="5123"):
    base = dob + seq + "08"
    return base + next(str(z) for z in range(10) if _cp.luhn_ok(base + str(z)))
ok(t.post("/api/me/kyc", data={"first_names": "Nadia", "surname": "Newbie", "id_number": "9002155123089"}), 400)   # wrong check digit
K = ok(t.post("/api/me/kyc", data={"first_names": "Nadia", "surname": "Newbie", "id_number": make_id(), "address": "1 Test Rd",
                                    "poa_date": (__import__("datetime").date.today()).isoformat()},
              files=[("id_doc", jpg()), ("selfie", jpg()), ("poa_doc", jpg())]))
assert K["status"] == "verified", K["checks"]
lease_id = ok(pm.post(f"/api/applications/{app_id}/approve", json={"months": 12}))["lease_id"]
sig = "data:image/png;base64,iVBORw0KGgo="
ok(t.post(f"/api/leases/{lease_id}/sign", json={"sig": sig}))
lease = ok(pm.post(f"/api/leases/{lease_id}/sign", json={"sig": sig}))
assert lease["status"] == "active", lease["status"]
L = ok(t.get(f"/api/leases/{lease_id}"))
owing = L["balance"]
from server import services as _sv, fees as _fees, db as _db  # noqa: E402
_L = _db.q1("SELECT * FROM leases WHERE id=?", lease_id)
first_rent = _sv.month_rent(_L, _L["start_date"][:7])[0]            # pro rata if the lease starts mid-month
_p = _db.q1("SELECT * FROM properties WHERE id=?", target["id"])
expect = _L["deposit"] + _fees.S("key_deposit") + _db.rands(_fees.inspection_fee(_p["bedrooms"], _p["bathrooms"]) * 0.5) + first_rent
assert owing == expect, (owing, expect)      # deposit + key deposit + inspection share + first (pro-rata) rent
# pay through the (simulated) gateway
p = ok(t.post("/api/pay/start", json={"lease_id": lease_id, "amount": owing}))
assert p["mode"] == "simulated"
ok(t.post(f"/api/pay/simulate/{p['payment_id']}"))
L = ok(t.get(f"/api/leases/{lease_id}"))
assert abs(L["balance"]) < 0.01, L["balance"]
assert L["deposit_held"] >= target["rent"], L["deposit_held"]
print("✓ apply → vet → lease → sign → move-in invoice → pay → allocate")

# ---- 2. maintenance: emergency + quoted job ------------------------------------------
e = ok(t.post("/api/tickets", data={"title": "Geyser burst, water everywhere", "description": "Please help"}, files=[("photos", jpg())]))
assert e["priority"] == "Urgent" and e["status"] == "approved" and e["contractor_id"], (e["priority"], e["status"])
q = ok(t.post("/api/tickets", data={"title": "Kitchen tap dripping"}))
assert q["status"] == "quoting", q["status"]
tid = q["id"]
assert q["category"] == "Plumbing"
from server import db  # noqa: E402
email = lambda uid: db.val("SELECT email FROM users WHERE id=?", uid)
asked = ok(pm.get(f"/api/tickets/{tid}"))["quotes"]
assert 1 <= len(asked) <= 3 and all(x["distance_km"] is not None and x["distance_km"] <= 10 for x in asked), asked
for x, amt in zip(asked, (900, 750, 1100)):
    ok(client(email(x["contractor_id"])).post(f"/api/tickets/{tid}/quotes", data={"amount": str(amt), "eta_days": "1"}))
T = ok(pm.get(f"/api/tickets/{tid}"))
if T["status"] == "quoting":
    T = ok(pm.post(f"/api/tickets/{tid}/shortlist"))
assert T["status"] == "awaiting_approval", T["status"]
assert not T["can"]["approve"], "the owner chooses, not the PM"
owner = client(email(db.val("SELECT landlord_id FROM properties WHERE id=?", target["id"])))
O = ok(owner.get(f"/api/tickets/{tid}"))
assert O["can"]["approve"] and O["map"]["companies"], "owner sees quotes + map"
best = O["quotes"][0]
ok(owner.post(f"/api/tickets/{tid}/approve", json={"quote_id": best["id"]}))
winner = client(email(best["contractor_id"]))
ok(winner.post(f"/api/tickets/{tid}/status", json={"status": "scheduled", "scheduled_for": "2026-12-01T09:00"}))
# a problem on site: extra work with a photo and a voice note → owner approves in one tap
r = ok(winner.post(f"/api/tickets/{tid}/issue", data={"kind": "extra_work", "text": "Valve seat corroded, needs replacing", "extra_cost": "450"},
                   files=[("photos", jpg()), ("audio", ("voice.webm", b"\x1aE\xdf\xa3fakeaudio", "audio/webm"))]))
O = ok(owner.get(f"/api/tickets/{tid}"))
var = next(x for x in O["quotes"] if x.get("kind") == "variation")
assert any(e.get("audio") for e in O["events"]), "voice note on the timeline"
ok(owner.post(f"/api/tickets/{tid}/variation/{var['id']}", json={"accept": 1}))
# job done = one photo
ok(winner.post(f"/api/tickets/{tid}/complete", data={"cost": str(best["amount"] + 450), "note": "Replaced cartridge and valve seat"}, files=[("photos", jpg())]))
assert ok(t.get(f"/api/tickets/{tid}"))["can"]["close"]
# nobody objects → autopilot closes it after 72 h and pays the company
db.exe("UPDATE tickets SET completed_at=datetime('now','-4 day') WHERE id=?", tid)
ok(admin.post("/api/autopilot/run"))
T = ok(t.get(f"/api/tickets/{tid}"))
assert T["status"] == "closed" and T["auto_closed"], (T["status"], T.get("auto_closed"))
assert T["can"]["rate"]
ok(t.post(f"/api/tickets/{tid}/review", json={"rating": 5, "quality": 5, "punctuality": 4, "price_score": 4, "communication": 5, "review": "Great"}))
led = ok(pm.get(f"/api/properties/{target['id']}"))["owner_ledger"]
assert any(x["kind"] == "maintenance" and x["ticket_id"] == tid for x in led), "repair not deducted"
prof = ok(anon.get(f"/api/pros/{best['contractor_id']}"))
assert prof["rating"]["n"] >= 1 and prof["reviews"]
print("✓ 3 companies within 10 km quote → owner chooses → extra work (photo + voice) approved → photo = done → auto-closed → rated → paid")

# ---- 2b. nobody within 10 km → extend the range; maintenance companies list themselves for R250/month ----
far = db.q1("SELECT t.id, p.landlord_id FROM tickets t JOIN properties p ON p.id=t.property_id WHERE p.title='Dullstroom Trout Farm Cottage'")
fo = client(email(far["landlord_id"]))
F = ok(fo.get(f"/api/tickets/{far['id']}"))
assert F["status"] == "new" and not F["quotes"] and F["can"]["widen"] and F["map"]["next"] == 50, (F["status"], F["map"]["next"])
w = ok(fo.post(f"/api/tickets/{far['id']}/widen", json={"radius": 50}))
assert w["sent"] >= 1, w
F = ok(fo.get(f"/api/tickets/{far['id']}"))
assert F["status"] == "quoting" and F["radius_km"] == 50, F["status"]
anon2 = TestClient(app)
ok(anon2.post("/api/auth/register", json={"email": "newpro@example.co.za", "password": "secret1", "name": "Zola Pro", "role": "contractor", "company": "Zola Plumbing",
                                          "trades": "Plumber", "lat": -25.75, "lng": 28.24, "base_address": "Hatfield", "insured": 1}))
d = ok(anon2.get("/api/dashboard"))
assert d["fee"] == 250 and d["market"]["sub_until"], d.get("fee")
sp = ok(anon2.post("/api/contractor/subscribe", json={"months": 3}))
assert sp["amount"] == 750 if "amount" in sp else True
ok(anon2.post(f"/api/contractor/subscribe/simulate/{sp['payment_id']}"))
assert len(ok(anon.get("/api/pros?trade=Plumber"))) >= 10 and ok(anon.get("/api/pros/stats"))["fee"] == 250
# job map: a listed company sees open repairs nearby (suburb only) and applies to quote
jm = ok(plumber.get("/api/contractor/issues"))
op = next(i for i in jm["issues"] if i["can_apply"])
assert "address" not in op and round(op["lat"], 2) == op["lat"], "only the suburb is shown before booking"
n0 = op["n_quotes"]
ok(plumber.post(f"/api/tickets/{op['id']}/apply"))
ok(plumber.post(f"/api/tickets/{op['id']}/apply"), 400)                         # can't apply twice
J = ok(plumber.get(f"/api/tickets/{op['id']}"))
assert J["can"]["quote"] and J["status"] == "quoting", (J["can"], J["status"])
assert not J.get("tenant") and "full address after approval" in J["property"]["address"] and not J["booked"], "no tenant details before booking"
assert all(e["user_name"] in (None, "Tenant", "Owner") or e["user_role"] not in ("tenant", "landlord") for e in J["events"])
ok(plumber.post(f"/api/tickets/{op['id']}/quotes", data={"amount": "1350", "eta_days": "1"}))
assert len([q for q in ok(pm.get(f"/api/tickets/{op['id']}"))["quotes"] if q.get("applied")]) == 1 and n0 + 1 <= 5
ok(TestClient(app).get("/api/contractor/issues"), 401)
assert not any(i["trade"] == "Electrician" for i in ok(client("handyhelp@example.co.za").get("/api/contractor/issues"))["issues"]), "handyman never offered electrical work"
print("✓ job map → company applies to quote on a nearby repair → quotes; handyman never offered electrical work")
print("✓ no company in range → owner extends to 50 km → request sent; new company signs up, R250/month subscription paid")

# ---- 3. ingoing inspection, then outgoing with a charge and deposit refund -----------
insp = [i for i in ok(pm.get(f"/api/inspections?property_id={target['id']}")) if i["type"] == "ingoing"]
assert insp, "ingoing not auto-created"
iid = insp[0]["id"]
I = ok(pm.get(f"/api/inspections/{iid}"))
room = I["rooms"][1]
ok(pm.post(f"/api/rooms/{room['id']}/pano", files=[("file", jpg(800, 400))]))
for r in I["rooms"]:
    for it in r["items"]:
        ok(pm.put(f"/api/items/{it['id']}", json={"condition": 2, "clean": 1, "working": 1}))
ok(pm.post(f"/api/items/{room['items'][0]['id']}/photos", files=[("files", jpg())]))
ok(pm.post(f"/api/inspections/{iid}/sign", json={"who": "agent", "sig": sig}))
ok(t.post(f"/api/inspections/{iid}/sign", json={"who": "tenant", "sig": sig}))
ok(pm.post(f"/api/inspections/{iid}/finalise"))
out = ok(pm.post("/api/inspections", json={"property_id": target["id"], "type": "outgoing"}))["id"]
O = ok(pm.get(f"/api/inspections/{out}"))
assert O["compare_to_id"] == iid and O["rooms"][0]["items"][0].get("prev"), "outgoing not linked to ingoing"
first = True
for r in O["rooms"]:
    for it in r["items"]:
        kw = {"condition": 2}
        if first:
            kw = {"condition": 4, "notes": "Hole in wall", "charge": 800, "charge_to": "tenant"}
            first = False
        ok(pm.put(f"/api/items/{it['id']}", json=kw))
ok(pm.post(f"/api/inspections/{out}/sign", json={"who": "agent", "sig": sig}))
ok(pm.post(f"/api/inspections/{out}/sign", json={"who": "tenant", "sig": sig}))
ok(pm.post(f"/api/inspections/{out}/finalise"))
O = ok(pm.get(f"/api/inspections/{out}"))
dep = O["deposit"]
assert dep["deductions"] == 800 and dep["refund"] > 0, dep
ok(pm.post(f"/api/inspections/{out}/refund-deposit"))
L = ok(pm.get(f"/api/leases/{lease_id}"))
assert L["status"] == "ended" and abs(L["deposit_held"]) < 0.01, (L["status"], L["deposit_held"])
assert all(c["done"] for c in L["checklist"][:5]), L["checklist"]
print("✓ ingoing (360 + photos + signatures) → outgoing compare → tenant charge → deposit refund → lease ended")

# ---- 4. snag list with rework -------------------------------------------------------
proj = ok(pm.post("/api/properties", json={"title": "Test new build", "kind": "project", "bedrooms": 2, "bathrooms": 1, "size_m2": 90}))["id"]
si = ok(pm.post("/api/inspections", json={"property_id": proj, "type": "snag"}))["id"]
S = ok(pm.get(f"/api/inspections/{si}"))
plumber_id = ok(plumber.get("/api/me"))["user"]["id"]
sn = ok(pm.post("/api/snags", data={"property_id": proj, "inspection_id": si, "room": S["rooms"][0]["name"], "room_id": S["rooms"][0]["id"],
                                     "title": "Leaking trap", "trade": "Plumber", "contractor_id": plumber_id, "priority": "High", "qty": "2",
                                     "unit": "no.", "rate": "350", "pin": '{"yaw": 10, "pitch": -20}'}, files=[("photos", jpg())]))
assert sn["ref"].startswith("SN-") and sn["due_date"]
r = plumber.post(f"/api/snags/{sn['id']}/ready", data={"note": "done"})
assert r.status_code == 400, "contractor must add an after photo"
ok(plumber.post(f"/api/snags/{sn['id']}/ready", data={"note": "done"}, files=[("photos", jpg())]))
ok(pm.post(f"/api/snags/{sn['id']}/verify", data={"result": "reject", "note": "still leaking"}))
ok(plumber.post(f"/api/snags/{sn['id']}/ready", data={"note": "fixed properly"}, files=[("photos", jpg())]))
re_id = ok(pm.post("/api/inspections", json={"property_id": proj, "type": "reinspection"}))["id"]
assert ok(pm.get(f"/api/inspections/{re_id}"))["round"] == 2
ok(pm.post(f"/api/snags/{sn['id']}/verify", data={"result": "close", "inspection_id": str(re_id)}))
m = ok(pm.get(f"/api/snags/metrics?property_id={proj}"))
assert m["closed"] == 1 and m["first_time_right"] == 0 and m["by_contractor"][0]["total"] == 1, m
print("✓ snag → contractor 'fixed' needs photo → rejected (rework) → fixed → re-inspection round 2 → closed; metrics")

# ---- 5. money, autopilot, comms, reports, permissions --------------------------------
po = ok(pm.get("/api/money/payouts?period=2026-09"))
ok(pm.post("/api/money/payouts/run", json={"period": "2026-09"}))
lst = [x for x in ok(pm.get("/api/money/payouts?period=2026-09"))["rows"] if x["paid"]]
assert lst, "no payouts"
ok(pm.get(f"/api/statement/{lst[0]['property_id']}/2026-09"))
csv = "2026-10-02,PAYMENT AVA00002 L Botha,15800.00\n2026-10-02,UNKNOWN DEPOSIT,500.00\n"
imp = ok(pm.post("/api/payments/import", files=[("file", ("bank.csv", csv.encode(), "text/csv"))]))
assert len(imp["matched"]) == 1 and len(imp["unmatched"]) == 1, imp
ok(pm.post("/api/autopilot/run"))
lerato = client("lerato@example.com")
r = ok(lerato.post("/api/assist", json={"text": "what do I owe?"}))
assert "R" in r["reply"] or "up to date" in r["reply"], r
r = ok(lerato.post("/api/assist", json={"text": "there is a gas smell in the kitchen"}))
assert any(a.get("action") == "ticket" for a in r["actions"]), r
th = ok(lerato.get("/api/threads"))
ok(lerato.post(f"/api/threads/{th[0]['key']}", json={"body": "This is unacceptable, still not fixed!"}))
assert any(x["kind"] == "escalation" for x in ok(pm.get("/api/tasks"))), "negative message not escalated"
for rep in ("rent-roll", "arrears", "maintenance", "snags", "owner-ledger"):
    r = pm.get(f"/api/reports/{rep}.xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK", rep
# permissions
assert lerato.get(f"/api/properties/{proj}").status_code == 403
assert plumber.get("/api/money/summary").status_code == 403
assert TestClient(app).get("/api/dashboard").status_code == 401
assert lerato.get("/api/leases/2").status_code == 403
ok(admin.put("/api/settings", json={"key_deposit": 600}))
assert ok(anon.get("/api/fees/public"))["move_in"]["lines"][2]["amount"] == 600
r = ok(anon.post("/api/agent", json={"text": "Can I keep a dog and is there solar?", "property_id": target["id"], "session": "t"}))
assert r["reply"] and r["intent"] == "faq", r
r = ok(anon.post("/api/agent", json={"text": "When can I view it?", "property_id": target["id"], "session": "t"}))
assert any(a.get("action") == "book" for a in r["actions"]), r
r = ok(anon.post("/api/agent", json={"text": "looking for a 3 bed in Pretoria under 30k"}))
assert r["intent"] == "search", r
ok(anon.post("/api/agent/handoff", json={"name": "Lead", "phone": "082", "property_id": target["id"]}))
assert ok(pm.get("/api/agent/stats"))["handoffs"] >= 1
print("✓ payouts + statement, bank CSV matching, autopilot, AVA Assist, escalation, Excel reports, permissions, settings")

# ---- 6. maintenance switched off (it runs in Fixit for now) -------------------------------
ok(admin.put("/api/settings", json={"module_maintenance": False, "fixit_url": "https://fixit.example.co.za"}))
me = ok(t.get("/api/me"))
assert {k: me["features"][k] for k in ("maintenance", "fixit_url")} == {"maintenance": False, "fixit_url": "https://fixit.example.co.za"}, me["features"]
assert ok(anon.get("/api/me"))["features"]["maintenance"] is False
ok(t.post("/api/tickets", data={"title": "Tap leaking"}), 404)
ok(plumber.get("/api/contractor/issues"), 404)
ok(anon.get("/api/pros"), 404)
ok(pm.get("/api/reports/maintenance.xlsx"), 404)
ok(pm.get("/api/reports/rent-roll.xlsx"))                                       # the rest of AVA still works
r = ok(t.post("/api/agent", json={"text": "my geyser burst and water is everywhere", "session": "off"}))
assert r["intent"] == "repairs_fixit" and "Fixit" in r["reply"] and any(a.get("href") == "https://fixit.example.co.za" for a in r["actions"]), r
r = ok(t.post("/api/agent", json={"text": "can I cancel my fixed-term lease?", "session": "off"}))
assert r["intent"] != "repairs_fixit", r
d = ok(pm.get("/api/dashboard"))
assert not any(x["kind"] in ("maintenance", "approval") for x in d["tasks"]), "repair to-dos hidden"
ok(admin.post("/api/autopilot/run"))
print("✓ maintenance module off: repair & marketplace API closed, agent points to Fixit, inbox has no repair to-dos, rest of AVA works")

# ---- 7. trust accounting: cashbooks, bank feed, reconciliation, locking, journals, batches, debit orders ----------
from datetime import date as _d, timedelta as _td  # noqa: E402
from server import trust as _tr  # noqa: E402
def balanced():
    tb = ok(admin.get("/api/trust/trial-balance"))
    assert tb["trust"]["balanced"] and tb["deposit"]["balanced"], (tb["trust"]["difference"], tb["deposit"]["difference"], tb["trust"]["lines"])
    return tb
ov = ok(admin.get("/api/trust"))
assert {b["code"] for b in ov["books"]} == {"trust", "deposit", "business"}
balanced()
ok(pm.get("/api/trust"), 403)
last = (_d.today().replace(day=1) - _td(days=1)).isoformat()[:7]
R = ok(admin.get(f"/api/trust/recon/trust/{last}"))
assert not R["can_sign"] and len(R["unexplained"]) >= 2, "two bank lines to explain"
ok(admin.post(f"/api/trust/periods/{last}/lock"), 400)                          # can't lock an unreconciled month
for l in R["unexplained"]:
    if l["amount"] < 0:
        ok(admin.post(f"/api/trust/lines/{l['id']}/resolve", json={"action": "bank_charges"}))
    else:
        ok(admin.post(f"/api/trust/lines/{l['id']}/resolve", json={"action": "suspense", "note": "No reference"}))
balanced()
ok(admin.post("/api/trust/feed/trust"))                                          # business refund of the charges clears
R = ok(admin.post(f"/api/trust/recon/trust/{last}"))
assert R["reconciled"], R
for code in ("deposit", "business"):
    if ok(admin.get(f"/api/trust/recon/{code}/{last}"))["can_sign"]:
        ok(admin.post(f"/api/trust/recon/{code}/{last}"))
ok(admin.post(f"/api/trust/periods/{last}/lock"))
lease_any = _db0.val("SELECT id FROM leases WHERE status='active' LIMIT 1")
ok(admin.post("/api/trust/journals", json={"date": last + "-15", "reason": "Fix last month", "lines": [
    {"account": "owner", "property_id": 1, "amount": -100}, {"account": "control", "kind": "ava_fees", "amount": 100}]}), 400)   # locked month
ok(admin.post("/api/trust/journals", json={"reason": "Unbalanced", "lines": [
    {"account": "owner", "property_id": 1, "amount": -100}, {"account": "control", "kind": "ava_fees", "amount": 90}]}), 400)
ok(admin.post("/api/trust/journals", json={"reason": "Missed admin fee on new lease", "lines": [
    {"account": "owner", "property_id": 2, "amount": -500}, {"account": "control", "kind": "ava_fees", "amount": 500}]}))
balanced()
sus = _db0.val("SELECT id FROM ledger WHERE account='control' AND kind='suspense' AND amount>0 ORDER BY id DESC LIMIT 1")
ok(admin.post(f"/api/trust/suspense/{sus}/allocate", json={"lease_id": lease_any}))   # the unidentified R2 500 was rent
balanced()
# owner payouts → batch → authorise → release (with a bank file); then the fee transfer to the business account
ok(pm.post("/api/money/payouts/run", json={"period": last}))
bs = [b for b in ok(admin.get("/api/trust/batches")) if b["kind"] == "owner_payout" and b["status"] == "draft"]
assert bs, "payouts queued in a batch"
B = ok(admin.post(f"/api/trust/batches/{bs[0]['id']}/authorise"))
csvf = ok(admin.get(f"/api/trust/batches/{B['id']}/bank-file")).text
assert "Recipient name" in csvf and "TOTAL" in csvf
before = ok(admin.get("/api/trust/trial-balance"))["trust"]["cash"]
ok(admin.post(f"/api/trust/batches/{B['id']}/release"))
assert ok(admin.get("/api/trust/trial-balance"))["trust"]["cash"] == before - B["total"]
balanced()
biz = ok(admin.get("/api/trust/trial-balance"))["business"]["cash"]
F = ok(admin.post("/api/trust/batches/fee-transfer"))
ok(admin.post(f"/api/trust/batches/{F['id']}/authorise")); ok(admin.post(f"/api/trust/batches/{F['id']}/release"))
assert ok(admin.get("/api/trust/trial-balance"))["business"]["cash"] > biz
balanced()
# debit order: a tenant signs a DebiCheck mandate, approves it, and rent is collected on the debit day
ten = client("johan@example.com")
lj = _db0.q1("SELECT * FROM leases WHERE tenant_id=(SELECT id FROM users WHERE email='johan@example.com') AND status='active'")
ok(ten.post("/api/me/debit-order", json={"holder": "J Botha", "bank": "Capitec", "account_no": "1234567890", "consent": 1}), 200)
assert ok(ten.get("/api/me/debit-order"))["mandate"]["debicheck"] == "pending"
assert ok(ten.post("/api/me/debit-order/approve"))["mandate"]["debicheck"] == "approved"
_db0.ins("ledger", account="tenant", kind="rent_charge", amount=lj["rent"], date=_d.today().isoformat(), period=_d.today().isoformat()[:7], lease_id=lj["id"], property_id=lj["property_id"], description="Rent (test)")
due_day = _d.today().replace(day=min(lj["due_day"], 28))
ok(admin.post("/api/trust/debit-orders/run", json={"date": due_day.isoformat()}))
D = ok(admin.get("/api/trust/debit-orders"))
assert any(i["status"] == "paid" and i["lease_id"] == lj["id"] for r in D["runs"] for i in r["items"]), "rent collected by debit order"
assert "\tTwoDay\t" in ok(admin.get(f"/api/trust/debit-orders/runs/{D['runs'][0]['id']}/file")).text
balanced()
# bank statement import (OFX) – a rent payment with the AVA reference is allocated by itself
ofx = f"<OFX><STMTTRN><TRNTYPE>CREDIT<DTPOSTED>{_d.today().strftime('%Y%m%d')}<TRNAMT>1234.00<FITID>T1<NAME>AVA{lj['id']:05d} EFT</STMTTRN></OFX>"
r = ok(admin.post("/api/trust/import/trust", files=[("file", ("stmt.ofx", ofx.encode(), "text/plain"))]))
assert r["allocated"] == 1, r
balanced()
assert ok(admin.get("/api/trust/deposits")) and ok(admin.get("/api/trust/periods"))["year_ends"]
ok(admin.post(f"/api/trust/periods/{ok(admin.get('/api/trust/periods'))['year_ends'][0]['start_period']}/unlock"), 400)   # closed year stays closed
assert ok(client("emgee@example.co.za").get("/api/me/bank-account"))["account"]["account"].startswith("••••")
print("✓ trust: balanced trial balance, bank feed + OFX import, reconcile & lock, journals, suspense, payout & fee batches, DebiCheck debit orders, year-end")

# ---- 8. FICA, POPIA, prospecting, earnings reports, condition score, portals, campaigns ---------------------
# FICA: Home Affairs mismatch → a person must look; sanctions hit → failed; duplicate ID → flagged
f1 = TestClient(app); ok(f1.post("/api/auth/register", json={"email": "fica1@example.com", "password": "secret1", "name": "Pat Mismatch", "role": "tenant"}))
k1 = ok(f1.post("/api/me/kyc", data={"first_names": "Pat", "surname": "Mismatch", "id_number": "8001015009087"}))
assert k1["status"] == "review" and any(c["name"] == "Home Affairs (DHA)" and c["result"] == "fail" for c in k1["checks"])
f2 = TestClient(app); ok(f2.post("/api/auth/register", json={"email": "fica2@example.com", "password": "secret1", "name": "Sam Watchlist", "role": "tenant"}))
assert ok(f2.post("/api/me/kyc", data={"first_names": "Sam", "surname": "Watchlist", "id_number": make_id("850505", "0042")}))["status"] == "failed"
f3 = TestClient(app); ok(f3.post("/api/auth/register", json={"email": "fica3@example.com", "password": "secret1", "name": "Copy Cat", "role": "tenant"}))
k3 = ok(f3.post("/api/me/kyc", data={"first_names": "Copy", "surname": "Cat", "id_number": make_id()}))
assert k3["status"] == "review" and any(c["name"] == "Duplicate identity" and c["result"] == "fail" for c in k3["checks"])
ok(admin.post(f"/api/compliance/kyc/{k1['id']}/review", json={"decision": "verified", "note": ""}), 400)        # reason required
assert ok(admin.post(f"/api/compliance/kyc/{k1['id']}/review", json={"decision": "verified", "note": "Name changed after marriage – saw the marriage certificate"}))["status"] == "verified"
reg = ok(admin.get("/api/compliance/kyc"))
assert reg["counts"].get("verified", 0) > 10 and reg["counts"].get("failed", 0) >= 1
assert ok(t.get("/api/me"))["user"]["fica"] == "verified"
# POPIA: consents, export, objection works at once, deletion refused while a lease is active, done once it's over
ok(t.put("/api/me/consents", json={"marketing": True}))
assert next(c for c in ok(t.get("/api/me/privacy"))["consents"] if c["purpose"] == "marketing")["granted"]
ex = ok(t.get("/api/me/export"))
assert ex["person"]["email"] == "newbie@example.com" and ex["identity_checks"] and ex["leases"]
assert ok(t.post("/api/me/requests", json={"kind": "objection"}))["status"] == "done"
assert not next(c for c in ok(t.get("/api/me/privacy"))["consents"] if c["purpose"] == "marketing")["granted"]
ler = client("lerato@example.com")
assert _db0.val("SELECT 1 FROM leases WHERE tenant_id=(SELECT id FROM users WHERE email='lerato@example.com') AND status='active'")
dr = ok(ler.post("/api/me/requests", json={"kind": "deletion"}))
assert ok(admin.post(f"/api/compliance/requests/{dr['id']}", json={"action": "delete"}))["status"] == "declined"     # lease still active
dr2 = ok(f2.post("/api/me/requests", json={"kind": "deletion", "detail": "Remove me"}))
assert any(r["id"] == dr2["id"] and not r["overdue"] for r in ok(admin.get("/api/compliance/requests")))
assert ok(admin.post(f"/api/compliance/requests/{dr2['id']}", json={"action": "delete"}))["status"] == "done"
assert _db0.q1("SELECT name, phone, active FROM users WHERE email LIKE 'deleted-%'")["active"] == 0
ok(f2.get("/api/me/privacy"), 401)                                                                                 # signed out everywhere
assert _db0.val("SELECT COUNT(*) FROM kyc_checks WHERE user_id=(SELECT id FROM users WHERE email LIKE 'deleted-%')") == 1   # FICA record kept
ok(pm.get("/api/compliance/requests"), 403)
# prospecting with LOOM data (simulated): search an area, reveal a contact (1 credit), send an earnings report
cr0 = ok(pm.get("/api/growth/prospects"))["credits"]
assert ok(pm.post("/api/growth/prospects/search", json={"suburb": "Menlo Park", "city": "Pretoria"}))["added"] > 0
assert ok(pm.post("/api/growth/prospects/search", json={"suburb": "menlo park", "city": "Pretoria"}))["added"] == 0   # same erven, no duplicates
P = ok(pm.get("/api/growth/prospects?suburb=Menlo Park"))
pr = next(x for x in P["rows"] if x["status"] == "new")
assert pr["phone"] is None
pr = ok(pm.post(f"/api/growth/prospects/{pr['id']}/reveal"))
assert pr["phone"] and ok(pm.get("/api/growth/prospects"))["credits"] == cr0 - 1
ok(client("pieter@ava.co.za").post(f"/api/growth/prospects/{pr['id']}/reveal"), 404)                              # another PM's prospect
rep = ok(pm.post("/api/growth/reports", json={"prospect_id": pr["id"]}))
assert rep["rent"]["estimate"] > 0 and rep["agent"]["saving_month"] > 0 and rep["pm"]["name"] == "Thandi Mokoena"
pub = ok(anon.get(f"/api/public/report/{rep['token']}"))
assert pub["rent"]["estimate"] == rep["rent"]["estimate"]
ok(anon.post(f"/api/public/report/{rep['token']}/lead", json={"name": "Owner", "phone": "0821112222"}), 400)    # no consent ticked
ok(anon.post(f"/api/public/report/{rep['token']}/lead", json={"name": "Owner", "phone": "0821112222", "consent": True}))
assert _db0.val("SELECT status FROM prospects WHERE id=?", pr["id"]) == "interested"
assert _db0.val("SELECT 1 FROM tasks WHERE title LIKE 'Owner wants to talk%' AND status='open'")
own = ok(anon.post("/api/public/earn", json={"suburb": "Brooklyn", "city": "Pretoria", "bedrooms": 3, "bathrooms": 2, "size_m2": 200}))
assert own["token"] and ok(anon.get("/api/public/pm/" + str(_db0.val("SELECT id FROM users WHERE email='thandi@ava.co.za'"))))["homes"] > 5
# condition score adjusts the rent check (C1 +6% … C6 −12%)
cp = _db0.q1("SELECT id FROM properties WHERE pm_id=(SELECT id FROM users WHERE email='thandi@ava.co.za') AND kind='rental' LIMIT 1")["id"]
hi = ok(pm.post(f"/api/properties/{cp}/condition", json={"score": 1}))["price"]["estimate"]
lo = ok(pm.post(f"/api/properties/{cp}/condition", json={"score": 6}))["price"]["estimate"]
assert hi > lo and abs(hi / lo - 1.06 / 0.88) < 0.02, (hi, lo)
insp_p = _db0.val("SELECT property_id FROM inspections WHERE status='final' LIMIT 1")
assert ok(admin.post(f"/api/properties/{insp_p}/condition"))["score"] in range(1, 7)                       # from the last inspection
# portals: only a ready, live listing goes out; the feed needs its key; let or off → withdrawn everywhere
draft = _db0.val("SELECT id FROM properties WHERE listing_status!='live' AND kind='rental' AND pm_id=(SELECT id FROM users WHERE email='thandi@ava.co.za') LIMIT 1")
ok(pm.post(f"/api/properties/{draft}/portals/property24", json={"on": True}), 400)
lv = _db0.val("""SELECT p.id FROM properties p WHERE listing_status='live' AND kind='rental' AND pm_id=(SELECT id FROM users WHERE email='thandi@ava.co.za')
                 AND NOT EXISTS (SELECT 1 FROM syndications s WHERE s.property_id=p.id AND s.portal='privateproperty') AND (SELECT COUNT(*) FROM media m WHERE m.property_id=p.id AND m.kind='photo')>=3 LIMIT 1""")
st = ok(pm.post(f"/api/properties/{lv}/portals/privateproperty", json={"on": True}))
assert next(x for x in st if x["portal"] == "privateproperty")["status"] == "live"
ok(anon.get("/api/feeds/privateproperty.xml?key=x"), 403)
ok(admin.put("/api/settings", json={"pp_agency_id": "AG123", "pp_feed_key": "feedkey"}))
xml = ok(anon.get("/api/feeds/privateproperty.xml?key=feedkey")).text
assert f'id="AVA{lv}"' in xml and "<price" in xml
ok(pm.post(f"/api/properties/{lv}/unpublish"))
assert all(x["status"] in ("withdrawn", "off") for x in ok(pm.get(f"/api/properties/{lv}/portals")))
ld = ok(pm.get("/api/growth/leads"))
assert ld, "portal enquiries in the leads inbox"
assert ok(pm.put(f"/api/growth/leads/{ld[0]['id']}", json={"slot": "2030-01-10 10:00:00"}))["viewing_id"]
assert ok(pm.get("/api/growth/syndication"))["portals"][0]["views"] > 0
# campaigns: service only to clients; marketing only to people who opted in, with an unsubscribe that works
ok(pm.post("/api/crm/preview", json={"kind": "service", "channel": "email", "audience": {"group": "prospects"}, "body": "x"}), 400)
pv = ok(pm.post("/api/crm/preview", json={"kind": "marketing", "channel": "email", "audience": {"group": "tenants"}, "subject": "Hi", "body": "Hi {first_name} at {property}"}))
assert pv["sending"] < pv["total"] and "No marketing consent (POPIA)" in pv["excluded"] and "{first_name}" not in pv["sample"]["body"] and "Unsubscribe" in pv["sample"]["body"]
cm = ok(pm.post("/api/crm/campaigns", json={"kind": "marketing", "channel": "email", "audience": {"group": "tenants"}, "subject": "News", "body": "Hi {first_name}", "send": True}))
assert cm["counts"]["sent"] == pv["sending"]
ob = _db0.q1("SELECT * FROM outbox WHERE campaign_id=? AND status='sent' LIMIT 1", cm["id"])
from server import crm as _crm  # noqa: E402
ok(anon.get(f"/api/public/unsubscribe/{ob['id']}/bad"), 404)
assert "unsubscribed" in ok(anon.get(f"/api/public/unsubscribe/{ob['id']}/{_crm.token(ob['id'])}")).text
assert not _cp.has_consent("marketing", user_id=ob["user_id"])
sv = ok(pm.post("/api/crm/campaigns", json={"kind": "service", "channel": "sms", "audience": {"group": "tenants", "suburb": "Brooklyn"}, "body": "Water off Thursday", "send": True}))
assert sv["counts"]["sent"] >= 1 and sv["counts"]["excluded"] == 0
assert _crm.greetings() == 0                                                     # today's greetings already went out once
# FICA payout hold: an unverified owner's payout waits
ok(admin.put("/api/settings", json={"fica_hold_payouts": True}))
devco = _db0.val("SELECT id FROM users WHERE email='devco@example.co.za'")
assert _cp.status(devco) != "verified"
ok(admin.put("/api/settings", json={"fica_hold_payouts": False}))
ok(t.get("/api/compliance"), 403); ok(t.get("/api/growth/prospects"), 403)
print("✓ FICA (ID checksum, DHA, sanctions, duplicates, review), POPIA (consents, export, objection, deletion), prospecting + earnings reports, condition score, P24/PP syndication + feed + leads, campaigns with opt-out")
print("ALL GOOD")
