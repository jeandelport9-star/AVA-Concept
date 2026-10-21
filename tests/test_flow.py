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
assert me["features"] == {"maintenance": False, "fixit_url": "https://fixit.example.co.za"}, me["features"]
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
print("ALL GOOD")
