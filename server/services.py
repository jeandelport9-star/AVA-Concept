"""Business workflows shared by the API and the automation loop."""
import json
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from . import ai, db, fees


# ------------------------------------------------------------------ plumbing
def notify(user_id, title, body="", link="", kind="info"):
    if user_id:
        db.ins("notifications", user_id=user_id, title=title, body=body, link=link, kind=kind)


def log(pm_id, property_id, text, link="", actor="AVA Autopilot"):
    db.ins("activity", pm_id=pm_id, property_id=property_id, actor=actor, text=text, link=link)


def task(pm_id, property_id, kind, title, detail="", link="", priority=2, due=None, dedupe=None):
    if dedupe and db.val("SELECT 1 FROM tasks WHERE dedupe=?", dedupe):
        return None
    return db.ins("tasks", pm_id=pm_id, property_id=property_id, kind=kind, title=title, detail=detail, link=link,
                  priority=priority, due=due, dedupe=dedupe)


def close_tasks(prefix):
    db.exe("UPDATE tasks SET status='done', done_at=? WHERE status='open' AND dedupe LIKE ?", db.now(), prefix + "%")


def prop(pid):
    p = db.q1("SELECT * FROM properties WHERE id=?", pid)
    if not p:
        raise HTTPException(404, "Property not found")
    return p


def period(d=None):
    return (d or date.today()).isoformat()[:7]


def post(account, kind, amount, property_id, lease_id=None, description="", d=None, per=None, **kw):
    d = d or db.today()
    from . import trust
    trust.check_open(per + "-01" if per else d)      # locked months can't change – correct them with a journal
    return db.ins("ledger", account=account, kind=kind, amount=db.rands(amount), property_id=property_id, lease_id=lease_id,
                  description=description, date=d, period=per or d[:7], **kw)


def balance(account, lease_id=None, property_id=None, kinds=None):
    sql, args = "SELECT COALESCE(SUM(amount),0) FROM ledger WHERE account=?", [account]
    if lease_id:
        sql += " AND lease_id=?"; args.append(lease_id)
    if property_id:
        sql += " AND property_id=?"; args.append(property_id)
    if kinds:
        sql += " AND kind IN (%s)" % ",".join("?" * len(kinds)); args += list(kinds)
    return round(db.val(sql, *args) or 0, 2)


# ------------------------------------------------------------------ leases
LEASE_TERMS = """1. PARTIES. This lease is between the Landlord and the Tenant named above, managed through the AVA platform by the Portfolio Manager as the Landlord's agent.
2. PREMISES. The Landlord lets the premises described above to the Tenant for residential use only.
3. PERIOD. The lease runs from the start date to the end date. Either party may give 20 business days' written notice under the Consumer Protection Act s14; a reasonable cancellation penalty may apply to an early cancellation by the Tenant.
4. RENT. Rent is payable monthly in advance on or before the due day, into the AVA trust account with the reference shown in the app. Rent escalates by the agreed percentage on each anniversary.
5. DEPOSIT. The deposit is held in an interest-bearing account and refunded with interest after the outgoing inspection, less only the reasonable cost of repairing damage, within the periods set by the Rental Housing Act 50 of 1999 s5(3).
6. INSPECTIONS. A joint ingoing inspection is done before occupation and a joint outgoing inspection within 3 days before the Tenant vacates. AVA records both with 360° imagery and photos, and both parties sign the reports in the app.
7. MAINTENANCE. The Tenant reports defects through the app. The Landlord repairs fair wear and tear and structural defects. Damage caused by the Tenant, their household or guests is for the Tenant's account.
8. ACCESS. The Landlord, Portfolio Manager and appointed contractors may enter at reasonable times with reasonable notice to inspect or repair.
9. HOUSE RULES. The Tenant complies with any body corporate / HOA conduct rules, which form part of this lease.
10. BREACH. If the Tenant fails to pay or otherwise breaches the lease and does not remedy it within 20 business days of written notice, the Landlord may cancel. Eviction may only follow a court order under the PIE Act.
11. DOMICILIUM. Notices may be given through the AVA app and by email to the addresses on the parties' profiles.
12. SIGNATURE. The parties sign electronically in the AVA app (Electronic Communications and Transactions Act 25 of 2002)."""


def make_lease(property_id, tenant_id, start, months=12, rent=None, application_id=None, escalation=8, renewal_of=None):
    p = prop(property_id)
    rent = rent or p["rent"]
    s = date.fromisoformat(start)
    end = (s.replace(day=1) + timedelta(days=31 * months)).replace(day=1) - timedelta(days=1)
    lid = db.ins("leases", property_id=property_id, tenant_id=tenant_id, application_id=application_id, start_date=start,
                 end_date=end.isoformat(), rent=rent, base_rent=rent, deposit=round(rent * fees.S("deposit_months")),
                 escalation_pct=escalation, status="awaiting_signature", terms=LEASE_TERMS, renewal_of=renewal_of)
    notify(tenant_id, "Your lease is ready to sign", p["title"], f"#/app/lease/{lid}", "lease")
    notify(p["landlord_id"], "Lease ready for your signature", p["title"], f"#/app/lease/{lid}", "lease")
    log(p["pm_id"], property_id, f"Lease generated for {p['title']}", f"#/app/lease/{lid}")
    return lid


def sign_lease(lease_id, u, sig):
    l = db.q1("SELECT * FROM leases WHERE id=?", lease_id)
    p = prop(l["property_id"])
    if u["id"] == l["tenant_id"]:
        db.upd("leases", lease_id, tenant_sig=sig, tenant_signed_at=db.now())
    elif u["id"] == p["landlord_id"] or u["role"] in ("pm", "admin"):
        db.upd("leases", lease_id, landlord_sig=sig, landlord_signed_at=db.now())
    else:
        raise HTTPException(403, "Not a party to this lease")
    l = db.q1("SELECT * FROM leases WHERE id=?", lease_id)
    if l["tenant_sig"] and l["landlord_sig"] and l["status"] == "awaiting_signature":
        activate_lease(l)
    return db.q1("SELECT * FROM leases WHERE id=?", lease_id)


def activate_lease(l):
    p = prop(l["property_id"])
    db.upd("leases", l["id"], status="active")
    db.upd("properties", p["id"], listing_status="let")
    d = db.today()
    renewal = bool(l["renewal_of"])
    if not renewal:
        post("tenant", "deposit_charge", l["deposit"], p["id"], l["id"], "Deposit", d)
        post("tenant", "key_deposit_charge", fees.S("key_deposit"), p["id"], l["id"], "Key deposit", d)
        insp = fees.inspection_fee(p["bedrooms"], p["bathrooms"])
        tshare = db.rands(insp * fees.S("inspection_tenant_share"))
        post("tenant", "fee_charge", tshare, p["id"], l["id"], "Inspection fee (tenant 50%)", d)
        post("owner", "admin_fee", -fees.S("admin_fee"), p["id"], l["id"], "AVA admin fee (new contract)", d)
        post("owner", "inspection_fee", -(insp - tshare), p["id"], l["id"], "Inspection fee (landlord 50%)", d)
        post("ava", "fee_income", fees.S("admin_fee") + insp - tshare, p["id"], l["id"], "Admin + inspection fees", d)
    charge_rent(l, date.fromisoformat(max(l["start_date"], d)))
    # decline other open applications for this property
    for a in db.q("SELECT * FROM applications WHERE property_id=? AND status IN ('submitted','screening','shortlisted') AND id IS NOT ?",
                  p["id"], l["application_id"]):
        db.upd("applications", a["id"], status="declined", decision_note="Property has been let")
        notify(a["user_id"], "Application update", f"{p['title']} has been let. Similar homes are waiting for you.", "#/search", "application")
    if not renewal and not db.val("SELECT 1 FROM inspections WHERE lease_id=? AND type='ingoing'", l["id"]):
        iid = create_inspection(p["id"], "ingoing", l["id"], inspector_id=p["pm_id"], date_=l["start_date"])
        task(p["pm_id"], p["id"], "inspection", f"Ingoing inspection – {p['title']}", f"Lease starts {l['start_date']}. Book with the tenant.",
             f"#/app/inspection/{iid}", 1, l["start_date"], f"ingoing:{l['id']}")
    notify(l["tenant_id"], "Lease active – welcome home!", f"{p['title']}. Your move-in invoice is ready.", "#/app/pay", "lease")
    notify(p["landlord_id"], "Lease signed by both parties", p["title"], f"#/app/property/{p['id']}", "lease")
    log(p["pm_id"], p["id"], f"Lease #{l['id']} active; move-in invoice raised and ingoing inspection booked", f"#/app/lease/{l['id']}")


def month_rent(l, per):
    """Rent for one month of the lease, pro rata when the tenant moves in or out mid-month. Returns (amount, description, date)."""
    y, m = map(int, per.split("-"))
    first = date(y, m, 1)
    last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    s = max(first, date.fromisoformat(l["start_date"]))
    e = min(last, date.fromisoformat(l["end_date"])) if l.get("end_date") else last
    if e < s:
        return 0, "", first.isoformat()
    days, dim = (e - s).days + 1, last.day
    if days == dim:
        return l["rent"], f"Rent {db.month_name(per)}", first.isoformat()
    return db.rands(l["rent"] * days / dim), f"Rent {s.day}–{e.day} {db.month_name(per)} (pro rata, {days} of {dim} days)", s.isoformat()


def charge_rent(l, d=None):
    d = d or date.today()
    per = period(d)
    if db.val("SELECT 1 FROM ledger WHERE lease_id=? AND kind='rent_charge' AND period=?", l["id"], per):
        return False
    amt, desc, when = month_rent(l, per)
    if not amt:
        return False
    post("tenant", "rent_charge", amt, l["property_id"], l["id"], desc, when, per)
    return True


def apply_escalation(l, d=None):
    d = d or date.today()
    s = date.fromisoformat(l["start_date"])
    years = d.year - s.year - ((d.month, d.day) < (s.month, s.day))
    if years <= 0:
        return False
    new = round((l["base_rent"] or l["rent"]) * (1 + (l["escalation_pct"] or 0) / 100) ** years / 10) * 10
    if new != l["rent"]:
        db.upd("leases", l["id"], rent=new)
        db.upd("properties", l["property_id"], rent=new)     # the property shows what it actually rents for
        p = prop(l["property_id"])
        notify(l["tenant_id"], "Annual rent escalation", f"From this month your rent is R{new:,} ({l['escalation_pct']:g}% per your lease).", "#/app/lease", "lease")
        log(p["pm_id"], p["id"], f"Rent escalated to R{new:,} on lease #{l['id']}")
        return True
    return False


# ------------------------------------------------------------------ payments
METHOD = {"eft": "EFT", "card": "card", "payfast": "PayFast", "debit_order": "debit order", "cash": "cash"}


def record_payment(lease_id, amount, method="eft", reference="", created_by=None, d=None):
    l = db.q1("SELECT * FROM leases WHERE id=?", lease_id)
    if not l:
        raise HTTPException(404, "Lease not found")
    d = d or db.today()
    amount = db.rands(amount)
    pay_id = db.ins("payments", lease_id=lease_id, amount=amount, method=method, reference=reference, status="complete", created_by=created_by, created_at=d + "T10:00:00")
    pid = l["property_id"]
    post("tenant", "payment", -amount, pid, lease_id, f"Payment received ({METHOD.get(method, method)})", d, payment_id=pay_id, ref=reference)
    left = amount
    # 1. deposits are held in trust (interest-bearing)
    dep_owed = balance("tenant", lease_id, kinds=["deposit_charge", "key_deposit_charge"]) - balance("deposit", lease_id, kinds=["deposit_received"])
    if dep_owed > 0 and left > 0:
        x = min(left, dep_owed); left -= x
        post("deposit", "deposit_received", x, pid, lease_id, "Deposit received into trust", d, payment_id=pay_id)
    # 2. fees for AVA
    fee_owed = balance("tenant", lease_id, kinds=["fee_charge"]) - balance("ava", lease_id, kinds=["tenant_fee_received"])
    if fee_owed > 0 and left > 0:
        x = min(left, fee_owed); left -= x
        post("ava", "tenant_fee_received", x, pid, lease_id, "Tenant fees received", d, payment_id=pay_id)
    # 3. tenant-liable repairs go to the landlord who paid for them
    rep_owed = balance("tenant", lease_id, kinds=["repair_charge"]) - balance("owner", lease_id, kinds=["repair_recovered"])
    if rep_owed > 0 and left > 0:
        x = min(left, rep_owed); left -= x
        post("owner", "repair_recovered", x, pid, lease_id, "Tenant-liable repair recovered", d, payment_id=pay_id)
    # 4. the rest is rent for the landlord
    if left > 0:
        post("owner", "rent_received", left, pid, lease_id, f"Rent received {d[:7]}", d, payment_id=pay_id)
    p = prop(pid)
    bal = balance("tenant", lease_id)
    if bal <= 0:
        close_tasks(f"arrears:{lease_id}:")
    notify(l["tenant_id"], "Payment received – thank you", f"R{amount:,.0f} received. Balance R{max(bal,0):,.0f}.", "#/app/pay", "payment")
    log(p["pm_id"], pid, f"R{amount:,.0f} received from tenant ({method}) and allocated automatically", f"#/app/property/{pid}")
    return pay_id


def payout_run(property_id, per=None):
    """Month-end owner statement: rent in, AVA fee, PM commission, insurance, maintenance, then pay out the balance."""
    p = prop(property_id)
    per = per or period()
    if db.val("SELECT 1 FROM ledger WHERE property_id=? AND account='owner' AND kind='payout' AND period=?", property_id, per):
        return None
    rent_in = db.val("SELECT COALESCE(SUM(amount),0) FROM ledger WHERE property_id=? AND account='owner' AND kind='rent_received' AND period=?", property_id, per) or 0
    d = db.today()
    if rent_in > 0:
        ava_fee = fees.ava_monthly(p["landlord_id"])
        post("owner", "ava_fee", -ava_fee, property_id, None, "AVA platform fee", d, per)
        post("ava", "fee_income", ava_fee, property_id, None, "AVA monthly fee", d, per)
        pct = fees.pm_commission_pct(p["pm_id"])
        com = db.rands(rent_in * pct / 100)
        post("owner", "pm_commission", -com, property_id, None, f"Portfolio manager commission {pct:g}%", d, per)
        post("pm", "commission", com, property_id, None, f"Commission {pct:g}% – {p['title']}", d, per)
        post("pm", "finders_fee", fees.S("finders_fee"), property_id, None, f"Finder's fee – {p['title']}", d, per)
        if p["insured"]:
            post("owner", "insurance", -fees.S("insurance_monthly"), property_id, None, "Rental insurance (Expello)", d, per)
    bal = round(db.val("SELECT COALESCE(SUM(amount),0) FROM ledger WHERE property_id=? AND account='owner' AND period<=?", property_id, per) or 0, 2)
    if bal <= 0:
        return {"property_id": property_id, "period": per, "payout": 0, "note": "Nothing to pay out"}
    post("owner", "payout", -bal, property_id, None, f"Paid to landlord – statement {db.month_name(per)}", d, per)
    notify(p["landlord_id"], f"Statement {db.month_name(per)} – R{bal:,.0f} paid", p["title"], f"#/app/statement/{property_id}/{per}", "payment")
    log(p["pm_id"], property_id, f"Owner payout R{bal:,.0f} for {db.month_name(per)}", f"#/app/statement/{property_id}/{per}")
    return {"property_id": property_id, "period": per, "payout": bal}


def statement(property_id, per):
    rows = db.q("SELECT * FROM ledger WHERE property_id=? AND account='owner' AND period=? ORDER BY date, id", property_id, per)
    opening = db.val("SELECT COALESCE(SUM(amount),0) FROM ledger WHERE property_id=? AND account='owner' AND period<?", property_id, per) or 0
    return {"property": prop(property_id), "period": per, "opening": round(opening, 2), "rows": rows,
            "income": round(sum(r["amount"] for r in rows if r["amount"] > 0), 2),
            "expenses": round(-sum(r["amount"] for r in rows if r["amount"] < 0 and r["kind"] != "payout"), 2),
            "payout": round(-sum(r["amount"] for r in rows if r["kind"] == "payout"), 2)}


# ------------------------------------------------------------------ maintenance
def next_ref(table, prefix):
    n = (db.val(f"SELECT COUNT(*) FROM {table}") or 0) + 1
    return f"{prefix}-{n:05d}"


def event(ticket_id, user_id, kind, text, photo=None, internal=0, audio=None):
    db.ins("ticket_events", ticket_id=ticket_id, user_id=user_id, kind=kind, text=text, photo=photo, internal=internal, audio=audio)
    db.exe("UPDATE tickets SET updated_at=? WHERE id=?", db.now(), ticket_id)


def create_ticket(u, property_id, title, description="", room="", photos=None, source="tenant", priority=None,
                  inspection_item_id=None, responsible=None, cost=None):
    p = prop(property_id)
    lease = db.q1("SELECT * FROM leases WHERE property_id=? AND status='active' ORDER BY id DESC LIMIT 1", property_id)
    tri = ai.triage(title, description)
    tid = db.ins("tickets", ref=next_ref("tickets", "MR"), property_id=property_id, lease_id=lease["id"] if lease else None,
                 reported_by=u["id"] if u else None, title=title, description=description, room=room, photos=photos or [],
                 category=tri["category"], trade=tri["trade"], priority=priority or tri["priority"],
                 responsible=responsible or tri["responsible"], sentiment=tri["sentiment"], source=source,
                 inspection_item_id=inspection_item_id, cost=cost,
                 ai_notes="; ".join(tri["why"]) or "No keywords matched – routed to a handyman for a look")
    t = db.q1("SELECT * FROM tickets WHERE id=?", tid)
    event(tid, u["id"] if u else None, "created", f"Logged by {u['name'] if u else 'AVA'}: {title}")
    event(tid, None, "ai", f"AVA triage: {t['category']} · {t['priority']} · {t['trade']} · {t['responsible']} responsible. {t['ai_notes']}", internal=1)
    if tri.get("advice"):
        event(tid, None, "advice", "Safety advice sent to tenant: " + tri["advice"])
    notify(p["pm_id"], f"{t['priority']}: {title}", p["title"], f"#/app/ticket/{tid}", "maintenance")
    dispatch(t, p)
    return tid


def dispatch(t, p, radius=None):
    """Emergency → straight to the nearest best contractor (within the auto-approve limit).
    Otherwise → the request goes to the 3 best paid-up companies within the quote radius (10 km) and the owner chooses.
    Nobody in range → the owner/PM can extend the range in one tap (or AVA does it, up to `auto_widen_km`)."""
    from . import marketplace
    radius = radius or fees.S("quote_radius_km")
    best = ai.best_contractors(t["trade"], p["city"], fees.S("quotes_to_request"), p["lat"], p["lng"]) if radius == fees.S("quote_radius_km") \
        else marketplace.nearby(t["trade"], p["lat"], p["lng"], fees.S("quotes_to_request"), radius=radius)
    auto = fees.S("auto_widen_km") or 0
    while not best and p["lat"] is not None:
        nxt = marketplace.next_radius(t["trade"], p["lat"], p["lng"], radius)
        if not nxt or nxt > auto:
            break
        event(t["id"], None, "rfq", f"No listed company within {radius:g} km – AVA widened the search to {nxt:g} km.")
        radius = nxt
        best = marketplace.nearby(t["trade"], p["lat"], p["lng"], fees.S("quotes_to_request"), radius=radius)
    db.upd("tickets", t["id"], radius_km=radius)
    if not best:
        nxt = marketplace.next_radius(t["trade"], p["lat"], p["lng"], radius) if p["lat"] is not None else None
        db.upd("tickets", t["id"], status="new")
        hint = f"The nearest is within {nxt:g} km – extend the range in one tap." if nxt else "No listed company anywhere for this trade yet – assign one by hand."
        task(p["pm_id"], p["id"], "maintenance", f"No {t['trade'].lower()} within {radius:g} km: {t['title']}",
             f"No listed, paid-up maintenance company within {radius:g} km of {p['suburb']}. {hint}",
             f"#/app/ticket/{t['id']}", 1, dedupe=f"nocontractor:{t['id']}")
        if p["landlord_id"]:
            notify(p["landlord_id"], f"No company within {radius:g} km yet", f"{t['title']} – {hint}", f"#/app/ticket/{t['id']}", "maintenance")
        event(t["id"], None, "rfq", f"No listed maintenance company for {t['trade']} within {radius:g} km. {hint}")
        return
    if t["priority"] == "Urgent":
        c = best[0]
        callout = c["callout_fee"] or 0
        if callout <= fees.S("auto_approve_limit"):
            db.upd("tickets", t["id"], status="approved", contractor_id=c["id"], scheduled_for=db.now())
            event(t["id"], None, "dispatch", f"Emergency: dispatched to {c['company'] or c['name']} ({c['distance_km']} km away, rated {round(c['rating'], 1) if c['rating'] else 'new'}) within the R{fees.S('auto_approve_limit'):,} auto-approve limit.")
            notify(c["id"], "EMERGENCY call-out", f"{t['title']} – {p['address']}", f"#/app/ticket/{t['id']}", "maintenance")
            notify(p["landlord_id"], "Emergency repair dispatched", f"{t['title']} at {p['title']}", f"#/app/ticket/{t['id']}", "maintenance")
            log(p["pm_id"], p["id"], f"Emergency {t['ref']} dispatched to {c['company'] or c['name']}", f"#/app/ticket/{t['id']}")
            return
    send_rfqs(t, p, best, radius)


def send_rfqs(t, p, best, radius):
    deadline = (datetime.now() + timedelta(hours=fees.S("quote_window_hours"))).isoformat(timespec="minutes")
    db.upd("tickets", t["id"], status="quoting", quote_deadline=deadline, radius_km=radius)
    for c in best:
        db.ins("quotes", ticket_id=t["id"], contractor_id=c["id"], status="requested", distance_km=c["distance_km"])
        notify(c["id"], "New quote request near you", f"{t['title']} – {p['suburb']} ({c['distance_km']} km)", f"#/app/ticket/{t['id']}", "quote")
    event(t["id"], None, "rfq", f"Sent to {len(best)} listed compan{'y' if len(best) == 1 else 'ies'} within {radius:g} km: " +
          ", ".join(f"{c['company'] or c['name']} ({c['distance_km']} km)" for c in best) + f". Quotes close {deadline.replace('T', ' ')}; the owner then chooses.")
    if len(best) < fees.S("quotes_to_request"):
        task(p["pm_id"], p["id"], "maintenance", f"Only {len(best)} compan{'y' if len(best) == 1 else 'ies'} within {radius:g} km: {t['title']}",
             "Fewer than 3 quotes will come in. Extend the range on the request if the owner wants more choice.", f"#/app/ticket/{t['id']}", 3, dedupe=f"fewrfq:{t['id']}")
    log(p["pm_id"], p["id"], f"{t['ref']} triaged ({t['category']}) and sent to {len(best)} companies within {radius:g} km for quotes", f"#/app/ticket/{t['id']}")


def apply_to_quote(ticket_id, u):
    """A listed company spotted the job on its map and asks to quote. It joins the invited companies (up to max_quotes_per_job)."""
    from . import marketplace
    issue = next((x for x in marketplace.open_issues(u["id"])["issues"] if x["id"] == ticket_id), None)
    if not issue:
        raise HTTPException(404, "This job is no longer open, or it is outside your area or trade")
    if not issue["can_apply"]:
        raise HTTPException(400, issue["why_not"] or "You can't apply for this job")
    t = db.q1("SELECT * FROM tickets WHERE id=?", ticket_id)
    p = prop(t["property_id"])
    db.ins("quotes", ticket_id=ticket_id, contractor_id=u["id"], status="requested", distance_km=issue["distance_km"], applied=1)
    if t["status"] == "new":       # nobody was in range – this company's application starts the quoting
        deadline = (datetime.now() + timedelta(hours=fees.S("quote_window_hours"))).isoformat(timespec="minutes")
        db.upd("tickets", ticket_id, status="quoting", quote_deadline=deadline)
        close_tasks(f"nocontractor:{ticket_id}")
    company = u.get("company") or u["name"]
    event(ticket_id, None, "rfq", f"{company} ({issue['distance_km']} km away) saw this job on the AVA job map and asked to quote.")
    notify(p["landlord_id"], "Another company wants to quote", f"{company} – {t['title']}", f"#/app/ticket/{ticket_id}", "quote")
    log(p["pm_id"], p["id"], f"{company} applied to quote on {t['ref']}", f"#/app/ticket/{ticket_id}")
    return {"ok": True, "ticket_id": ticket_id}


def widen(ticket_id, radius, u=None):
    """Extend the search range: ask more companies (up to 3 new ones) between the old and the new radius."""
    from . import marketplace
    t = db.q1("SELECT * FROM tickets WHERE id=?", ticket_id)
    p = prop(t["property_id"])
    if t["contractor_id"] or t["status"] not in ("new", "quoting", "awaiting_approval"):
        raise HTTPException(400, "A company is already booked for this job")
    radius = float(radius)
    old = t["radius_km"] or fees.S("quote_radius_km")
    if radius <= old:
        raise HTTPException(400, f"Choose a range wider than {old:g} km")
    asked = [r["contractor_id"] for r in db.q("SELECT contractor_id FROM quotes WHERE ticket_id=?", ticket_id)]
    best = marketplace.nearby(t["trade"], p["lat"], p["lng"], fees.S("quotes_to_request"), radius=radius, exclude=asked)
    who = (u or {}).get("name") or "AVA"
    if not best:
        db.upd("tickets", ticket_id, radius_km=radius)
        nxt = marketplace.next_radius(t["trade"], p["lat"], p["lng"], radius, asked)
        event(ticket_id, u and u["id"], "rfq", f"{who} extended the range to {radius:g} km – still no other listed company." + (f" The nearest is within {nxt:g} km." if nxt else ""))
        return {"sent": 0, "radius": radius, "next": nxt}
    event(ticket_id, u and u["id"], "rfq", f"{who} extended the range from {old:g} km to {radius:g} km.")
    if t["status"] == "awaiting_approval":    # quotes already shortlisted: re-open quoting for the new companies
        db.upd("tickets", ticket_id, status="quoting")
    send_rfqs(t, p, best, radius)
    close_tasks(f"nocontractor:{ticket_id}")
    close_tasks(f"fewrfq:{ticket_id}")
    return {"sent": len(best), "radius": radius, "companies": [c["company"] or c["name"] for c in best]}


def shortlist(ticket_id):
    t = db.q1("SELECT * FROM tickets WHERE id=?", ticket_id)
    p = prop(t["property_id"])
    qs = db.q("""SELECT q.*, (SELECT AVG(rating) FROM reviews r WHERE r.target_type='contractor' AND r.target_id=q.contractor_id AND r.status='published') rating
                 FROM quotes q WHERE ticket_id=? AND status IN ('submitted','shortlisted')""", ticket_id)
    ranked = ai.rank_quotes(qs)
    if not ranked:
        return []
    top = ranked[:fees.S("shortlist_size")]
    for q in ranked:
        db.upd("quotes", q["id"], rank_score=q["rank_score"], status="shortlisted" if q in top else "submitted")
    db.exe("UPDATE quotes SET status='expired' WHERE ticket_id=? AND status='requested'", ticket_id)
    db.upd("tickets", ticket_id, status="awaiting_approval")
    event(ticket_id, None, "shortlist", f"Quotes closed. Shortlist: " + ", ".join(f"R{q['amount']:,.0f} (score {q['rank_score']})" for q in top))
    notify(p["landlord_id"], f"Choose a company: {len(top)} quote{'s' if len(top) != 1 else ''} in", f"{t['title']} – from R{min(q['amount'] for q in top):,.0f}", f"#/app/ticket/{ticket_id}", "quote")
    task(p["pm_id"], p["id"], "approval", f"Waiting for the owner to choose: {t['title']}", f"{len(top)} quotes compared on price, rating and distance",
         f"#/app/ticket/{ticket_id}", 3, dedupe=f"approval:{ticket_id}")
    return top


def approve_quote(ticket_id, quote_id, u):
    t = db.q1("SELECT * FROM tickets WHERE id=?", ticket_id)
    q = db.q1("SELECT * FROM quotes WHERE id=? AND ticket_id=?", quote_id, ticket_id)
    if not q:
        raise HTTPException(404, "Quote not found")
    p = prop(t["property_id"])
    db.exe("UPDATE quotes SET status='rejected' WHERE ticket_id=? AND id!=? AND status IN ('submitted','shortlisted')", ticket_id, quote_id)
    db.upd("quotes", quote_id, status="approved")
    db.upd("tickets", ticket_id, status="approved", contractor_id=q["contractor_id"], approved_quote_id=quote_id, cost=q["amount"])
    c = db.q1("SELECT name, company FROM users WHERE id=?", q["contractor_id"])
    event(ticket_id, u["id"], "approved", f"{u['name']} chose {c['company'] or c['name']} at R{q['amount']:,.0f}")
    notify(q["contractor_id"], "You won the job – please book it", t["title"], f"#/app/ticket/{ticket_id}", "quote")
    for lost in db.q("SELECT contractor_id FROM quotes WHERE ticket_id=? AND id!=? AND status='rejected'", ticket_id, quote_id):
        notify(lost["contractor_id"], "Quote not selected this time", f"{t['title']} – the owner chose another company. Thanks for quoting.", "#/app", "quote")
    if t["lease_id"]:
        ten = db.val("SELECT tenant_id FROM leases WHERE id=?", t["lease_id"])
        notify(ten, "Repair approved", f"{t['title']}: {c['company'] or c['name']} will contact you to book.", f"#/app/ticket/{ticket_id}", "maintenance")
    close_tasks(f"approval:{ticket_id}")
    log(p["pm_id"], p["id"], f"{t['ref']} quote approved (R{q['amount']:,.0f})", f"#/app/ticket/{ticket_id}", u["name"])


def complete_ticket(ticket_id, u, cost=None, note="", photos=None):
    t = db.q1("SELECT * FROM tickets WHERE id=?", ticket_id)
    p = prop(t["property_id"])
    cost = db.rands(cost) if cost not in (None, "") else (t["cost"] or 0)
    db.upd("tickets", ticket_id, status="completed", completed_at=db.now(), cost=cost,
           after_photos=(t["after_photos"] or []) + (photos or []))
    event(ticket_id, u["id"], "completed", f"Work completed{': ' + note if note else ''}. Invoice R{cost:,.0f}.")
    if t["lease_id"]:
        ten = db.val("SELECT tenant_id FROM leases WHERE id=?", t["lease_id"])
        notify(ten, "Repair done – see the photo", f"{t['title']}. Nothing to do if you're happy – it closes itself in {fees.S('auto_close_hours')} h. Tap 'Not fixed' if there's a problem.",
               f"#/app/ticket/{ticket_id}", "maintenance")
    p_ = prop(t["property_id"])
    notify(p_["landlord_id"], "Repair completed", f"{t['title']} – R{cost:,.0f}, photo proof attached", f"#/app/ticket/{ticket_id}", "maintenance")
    notify(p["pm_id"], f"Completed: {t['title']}", f"R{cost:,.0f}", f"#/app/ticket/{ticket_id}", "maintenance")
    settle_ticket(ticket_id)


def settle_ticket(ticket_id):
    t = db.q1("SELECT * FROM tickets WHERE id=?", ticket_id)
    if t["deducted"] or not t["cost"]:
        return
    p = prop(t["property_id"])
    post("owner", "maintenance", -t["cost"], p["id"], t["lease_id"], f"{t['ref']} {t['title']}", ticket_id=ticket_id)
    if t["responsible"] == "tenant" and t["lease_id"]:
        post("tenant", "repair_charge", t["cost"], p["id"], t["lease_id"], f"{t['ref']} {t['title']} (tenant liable)", ticket_id=ticket_id)
    db.upd("tickets", ticket_id, deducted=1)
    log(p["pm_id"], p["id"], f"{t['ref']} R{t['cost']:,.0f} deducted from rent" + (" and charged to tenant" if t["responsible"] == "tenant" else ""))


# ------------------------------------------------------------------ inspections
ROOM_ITEMS = {
    "Entrance": ["Front door & lock", "Security gate", "Walls", "Floor", "Light fittings", "Alarm panel"],
    "Lounge": ["Walls", "Ceiling", "Floor", "Windows & burglar bars", "Curtain rails / blinds", "Light fittings", "Plugs & switches"],
    "Dining room": ["Walls", "Ceiling", "Floor", "Windows", "Light fittings", "Plugs & switches"],
    "Kitchen": ["Walls", "Ceiling", "Floor", "Cupboards & drawers", "Counter tops", "Sink & taps", "Stove / hob", "Oven", "Extractor",
                "Splashback tiles", "Windows", "Light fittings", "Plugs & switches"],
    "Bedroom": ["Door & handle", "Walls", "Ceiling", "Floor / carpet", "Built-in cupboards", "Windows & burglar bars", "Curtain rails / blinds",
                "Light fittings", "Plugs & switches"],
    "Bathroom": ["Door & handle", "Walls & tiles", "Ceiling", "Floor", "Bath", "Shower & screen", "Basin & taps", "Toilet & seat",
                 "Mirror & cabinet", "Towel rails", "Extractor fan", "Light fittings"],
    "Laundry": ["Walls", "Floor", "Tub & taps", "Washing machine point", "Geyser"],
    "Garage": ["Garage door & motor", "Remotes", "Walls", "Floor", "Light fittings"],
    "Garden & exterior": ["Boundary walls", "Gate & motor", "Electric fence", "Lawn & beds", "Paving", "Outside lights", "Washing line",
                          "Gutters & downpipes", "Pool"],
    "Keys & meters": ["Keys handed over", "Remotes / tags", "Prepaid electricity units", "Water meter reading"],
}


def room_plan(p):
    beds = max(1, int(round(p["bedrooms"] or 1)))
    baths = max(1, int(round(p["bathrooms"] or 1)))
    rooms = ["Entrance", "Lounge", "Kitchen"]
    if beds >= 3:
        rooms.insert(2, "Dining room")
    rooms += [f"Bedroom {i}" if beds > 1 else "Bedroom" for i in range(1, beds + 1)]
    rooms += [f"Bathroom {i}" if baths > 1 else "Bathroom" for i in range(1, baths + 1)]
    if p["type"] in ("House", "Townhouse", "Cottage"):
        rooms += ["Laundry", "Garage", "Garden & exterior"] if p["type"] == "House" else ["Garden & exterior"]
    rooms.append("Keys & meters")
    return rooms


def items_for(room):
    base = room.rstrip(" 0123456789")
    return ROOM_ITEMS.get(base, ["Walls", "Ceiling", "Floor", "Light fittings"])


def create_inspection(property_id, type_, lease_id=None, inspector_id=None, date_=None, compare_to_id=None):
    p = prop(property_id)
    if type_ in ("outgoing", "interim") and not compare_to_id:
        compare_to_id = db.val("SELECT id FROM inspections WHERE property_id=? AND type IN ('ingoing','interim') AND status='final' "
                               "AND (lease_id=? OR ? IS NULL) ORDER BY date DESC, id DESC LIMIT 1", property_id, lease_id, lease_id)
    if type_ == "reinspection" and not compare_to_id:
        compare_to_id = db.val("SELECT id FROM inspections WHERE property_id=? AND type IN ('snag','reinspection','handover') ORDER BY id DESC LIMIT 1", property_id)
    rnd = 1
    if type_ == "reinspection":
        rnd = (db.val("SELECT MAX(round) FROM inspections WHERE property_id=? AND type IN ('snag','handover','reinspection')", property_id) or 1) + 1
    iid = db.ins("inspections", property_id=property_id, lease_id=lease_id, type=type_, date=date_ or db.today(), status="draft",
                 inspector_id=inspector_id or p["pm_id"], compare_to_id=compare_to_id, round=rnd,
                 tenant_present=1 if type_ in ("ingoing", "outgoing", "interim") else 0)
    if compare_to_id:
        prev_rooms = db.q("SELECT * FROM insp_rooms WHERE inspection_id=? ORDER BY sort, id", compare_to_id)
        for r in prev_rooms:
            rid = db.ins("insp_rooms", inspection_id=iid, name=r["name"], sort=r["sort"], pano_yaw=r["pano_yaw"])
            for it in db.q("SELECT * FROM insp_items WHERE room_id=? ORDER BY sort, id", r["id"]):
                db.ins("insp_items", room_id=rid, inspection_id=iid, name=it["name"], sort=it["sort"])
    else:
        for i, room in enumerate(room_plan(p)):
            rid = db.ins("insp_rooms", inspection_id=iid, name=room, sort=i)
            if type_ not in ("snag", "handover", "reinspection"):
                for j, it in enumerate(items_for(room)):
                    db.ins("insp_items", room_id=rid, inspection_id=iid, name=it, sort=j)
    return iid


def inspection_full(iid):
    i = db.q1("SELECT * FROM inspections WHERE id=?", iid)
    if not i:
        raise HTTPException(404, "Inspection not found")
    i["property"] = prop(i["property_id"])
    i["rooms"] = db.q("SELECT * FROM insp_rooms WHERE inspection_id=? ORDER BY sort, id", iid)
    items = db.q("SELECT * FROM insp_items WHERE inspection_id=? ORDER BY sort, id", iid)
    prev = {}
    if i["compare_to_id"]:
        pr = {r["id"]: r for r in db.q("SELECT * FROM insp_rooms WHERE inspection_id=?", i["compare_to_id"])}
        for it in db.q("SELECT * FROM insp_items WHERE inspection_id=?", i["compare_to_id"]):
            prev[(pr[it["room_id"]]["name"], it["name"])] = it
        i["prev_rooms"] = {r["name"]: r for r in pr.values()}
        i["compare_to"] = db.q1("SELECT id, type, date FROM inspections WHERE id=?", i["compare_to_id"])
    rooms_by = {r["id"]: r for r in i["rooms"]}
    for r in i["rooms"]:
        r["items"] = []
    for it in items:
        room = rooms_by.get(it["room_id"])
        if not room:
            continue
        pv = prev.get((room["name"], it["name"]))
        if pv:
            it["prev"] = {k: pv[k] for k in ("condition", "clean", "working", "notes", "photos", "pin")}
            if pv["condition"] and it["condition"] and it["condition"] > pv["condition"]:
                it["worse"] = it["condition"] - pv["condition"]
        room["items"].append(it)
    i["snags"] = db.q("SELECT * FROM snags WHERE property_id=? AND (inspection_id=? OR (? IN ('reinspection') AND status!='closed') OR closed_inspection_id=?) ORDER BY id",
                      i["property_id"], iid, i["type"], iid)
    if i["lease_id"]:
        i["lease"] = db.q1("SELECT l.*, u.name tenant_name FROM leases l JOIN users u ON u.id=l.tenant_id WHERE l.id=?", i["lease_id"])
    if i["type"] == "outgoing":
        i["deposit"] = deposit_reconciliation(i)
    return i


def deposit_reconciliation(i):
    lid = i["lease_id"]
    if not lid:
        return None
    held = balance("deposit", lid)
    charges = db.q("SELECT it.id, it.name, it.charge, it.notes, r.name room FROM insp_items it JOIN insp_rooms r ON r.id=it.room_id "
                   "WHERE it.inspection_id=? AND it.charge_to='tenant' AND it.charge>0", i["id"])
    arrears = max(0, balance("tenant", lid))
    ded = round(sum(c["charge"] for c in charges), 2)
    refund = round(max(0, held - ded - arrears), 2)
    days = 7 if not charges else 14
    if not i["tenant_present"]:
        days = 21
    base = date.fromisoformat((i["finalised_at"] or i["date"])[:10])
    return {"held": held, "charges": charges, "deductions": ded, "arrears": round(arrears, 2), "refund": refund,
            "refund_by": (base + timedelta(days=days)).isoformat(), "rule": f"{days} days (Rental Housing Act s5(3))",
            "refunded": bool(db.val("SELECT 1 FROM ledger WHERE lease_id=? AND kind='deposit_refund'", lid))}


def finalise_inspection(iid, u):
    i = inspection_full(iid)
    p = i["property"]
    if i["type"] in ("ingoing", "outgoing", "interim"):
        if i["tenant_present"] and not i["tenant_sig"]:
            raise HTTPException(400, "The tenant still has to sign (or untick 'tenant present').")
        unrated = [f"{r['name']}: {it['name']}" for r in i["rooms"] for it in r["items"] if not it["condition"]]
        if unrated:
            raise HTTPException(400, f"{len(unrated)} items have no condition yet, e.g. {unrated[0]}")
    if not i["agent_sig"]:
        raise HTTPException(400, "Sign as inspector first.")
    db.upd("inspections", iid, status="final", finalised_at=db.now())
    close_tasks(f"ingoing:{i['lease_id']}") if i["type"] == "ingoing" else None
    close_tasks(f"outgoing:{i['lease_id']}") if i["type"] == "outgoing" else None
    created = 0
    found = [(r, it) for r in i["rooms"] for it in r["items"] if it["charge_to"] in ("landlord", "tenant") and it["charge"] and not it["ticket_id"]]
    if found and not fees.on("maintenance"):   # repairs run in Fixit: hand the list to the PM/owner instead of raising requests here
        task(p["pm_id"], p["id"], "inspection", f"{len(found)} repair{'s' if len(found) != 1 else ''} found at the {i['type']} inspection – {p['title']}",
             "; ".join(f"{r['name']}: {it['name']} (R{it['charge']:,.0f}, {it['charge_to']})" for r, it in found)[:400] + ". The owner decides which to do – log them in Fixit.",
             f"#/app/inspection/{iid}", 2, dedupe=f"repairs:{iid}")
        found = []
    for r, it in found:
        tid = create_ticket(u, p["id"], f"{r['name']}: {it['name']}", it["notes"] or "Found at inspection", r["name"],
                            it["photos"], "inspection", None, it["id"], it["charge_to"])
        db.upd("insp_items", it["id"], ticket_id=tid)
        created += 1
    if i["type"] == "outgoing" and i["lease_id"]:
        dep = deposit_reconciliation(inspection_full(iid))
        task(p["pm_id"], p["id"], "deposit", f"Refund deposit – {p['title']}", f"R{dep['refund']:,.0f} by {dep['refund_by']}",
             f"#/app/inspection/{iid}", 1, dep["refund_by"], f"deposit:{i['lease_id']}")
    if i["lease_id"]:
        ten = db.val("SELECT tenant_id FROM leases WHERE id=?", i["lease_id"])
        notify(ten, f"{i['type'].title()} inspection report", p["title"], f"#/app/inspection/{iid}", "inspection")
    notify(p["landlord_id"], f"{i['type'].title()} inspection report", p["title"], f"#/app/inspection/{iid}", "inspection")
    log(p["pm_id"], p["id"], f"{i['type'].title()} inspection finalised" + (f"; {created} repair request(s) raised" if created else ""), f"#/app/inspection/{iid}", u["name"])
    return created


def refund_deposit(iid, u):
    i = inspection_full(iid)
    dep = i["deposit"]
    if dep["refunded"]:
        raise HTTPException(400, "Already refunded")
    lid, pid = i["lease_id"], i["property_id"]
    if dep["deductions"]:
        post("deposit", "deposit_deduction", -dep["deductions"], pid, lid, "Deductions per outgoing inspection")
        post("owner", "deposit_compensation", dep["deductions"], pid, lid, "Damage recovered from deposit")
    if dep["arrears"]:
        x = min(dep["arrears"], dep["held"] - dep["deductions"])
        if x > 0:
            post("deposit", "deposit_deduction", -x, pid, lid, "Arrears settled from deposit")
            post("tenant", "payment", -x, pid, lid, "Arrears settled from deposit", ref="from-deposit")
            post("owner", "rent_received", x, pid, lid, "Arrears recovered from deposit")
    post("deposit", "deposit_refund", -dep["refund"], pid, lid, "Deposit + interest refunded to tenant")
    db.upd("leases", lid, status="ended", ended_at=db.now())
    db.upd("properties", pid, listing_status="draft")
    close_tasks(f"deposit:{lid}")
    ten = db.val("SELECT tenant_id FROM leases WHERE id=?", lid)
    notify(ten, "Deposit refunded", f"R{dep['refund']:,.0f} has been paid to you, with a full breakdown.", f"#/app/inspection/{iid}", "payment")
    log(i["property"]["pm_id"], pid, f"Deposit refunded R{dep['refund']:,.0f} (deductions R{dep['deductions']:,.0f})", f"#/app/inspection/{iid}", u["name"])


# ------------------------------------------------------------------ snags
def add_snag(u, property_id, inspection_id, **kw):
    p = prop(property_id)
    pri = kw.get("priority") or "Medium"
    due = kw.get("due_date") or (date.today() + timedelta(days=fees.S("snag_due_days").get(pri, 14))).isoformat()
    n = (db.val("SELECT COUNT(*) FROM snags WHERE property_id=?", property_id) or 0) + 1
    prefix = "HS" if kw.get("category") == "Health & safety" else "NCR" if kw.get("category") == "Non-conformance" else "SN"
    sid = db.ins("snags", ref=f"{prefix}-{property_id:03d}-{n:03d}", property_id=property_id, inspection_id=inspection_id,
                 due_date=due, priority=pri, **{k: v for k, v in kw.items() if k not in ("priority", "due_date")})
    s = db.q1("SELECT * FROM snags WHERE id=?", sid)
    if s["contractor_id"]:
        notify(s["contractor_id"], f"New snag {s['ref']}", f"{s['title']} – due {due}", f"#/app/snags/{property_id}", "snag")
    return sid


def snag_metrics(property_ids=None):
    from .auth import in_list
    where = f"WHERE s.property_id IN {in_list(property_ids)}" if property_ids is not None else ""
    rows = db.q(f"SELECT s.*, u.company, u.name cname FROM snags s LEFT JOIN users u ON u.id=s.contractor_id {where}")
    t = db.today()
    tot = len(rows)
    closed = [r for r in rows if r["status"] == "closed"]
    open_ = [r for r in rows if r["status"] in ("open", "in_progress")]
    ready = [r for r in rows if r["status"] == "ready"]
    overdue = [r for r in rows if r["status"] != "closed" and r["due_date"] and r["due_date"] < t]
    days = [(datetime.fromisoformat(r["closed_at"][:19]) - datetime.fromisoformat(r["raised_at"][:19])).days for r in closed if r["closed_at"]]
    ftr = [r for r in closed if not r["rework_count"]]
    cost_open = sum((r["qty"] or 1) * (r["rate"] or 0) for r in rows if r["status"] != "closed")
    by_trade, by_con = {}, {}
    for r in rows:
        k = r["trade"] or "Unassigned"
        d = by_trade.setdefault(k, {"trade": k, "total": 0, "open": 0, "overdue": 0, "closed": 0})
        d["total"] += 1; d["closed"] += r["status"] == "closed"; d["open"] += r["status"] != "closed"; d["overdue"] += r in overdue
        c = r["company"] or r["cname"] or "Unassigned"
        e = by_con.setdefault(c, {"contractor": c, "total": 0, "closed": 0, "overdue": 0, "rework": 0, "days": []})
        e["total"] += 1; e["closed"] += r["status"] == "closed"; e["overdue"] += r in overdue; e["rework"] += r["rework_count"] or 0
        if r["status"] == "closed" and r["closed_at"]:
            e["days"].append((datetime.fromisoformat(r["closed_at"][:19]) - datetime.fromisoformat(r["raised_at"][:19])).days)
    for e in by_con.values():
        e["avg_days"] = round(sum(e["days"]) / len(e["days"]), 1) if e["days"] else None
        e["ftr"] = round(100 * (e["closed"] - min(e["closed"], e["rework"])) / e["closed"]) if e["closed"] else None
        del e["days"]
    area = 0
    if property_ids:
        area = db.val(f"SELECT COALESCE(SUM(size_m2),0) FROM properties WHERE id IN {in_list(property_ids)}") or 0
    sev = {"Urgent": 4, "High": 3, "Medium": 2, "Low": 1}
    return {"total": tot, "open": len(open_), "ready": len(ready), "closed": len(closed), "overdue": len(overdue),
            "close_rate": round(100 * len(closed) / tot) if tot else 0,
            "avg_days_to_close": round(sum(days) / len(days), 1) if days else None,
            "first_time_right": round(100 * len(ftr) / len(closed)) if closed else None,
            "cost_to_rectify": round(cost_open, 2),
            "density_per_100m2": round(100 * tot / area, 1) if area else None,
            "severity_index": round(sum(sev.get(r["priority"], 2) for r in rows if r["status"] != "closed"), 1),
            "by_trade": sorted(by_trade.values(), key=lambda x: -x["open"]),
            "by_contractor": sorted(by_con.values(), key=lambda x: -x["total"])}


# ------------------------------------------------------------------ job closure (minimal human input)
def close_job(ticket_id, by_user=None, auto=False):
    """Close a finished job: ask tenant and owner to rate, and schedule the company's payment from trust."""
    t = db.q1("SELECT * FROM tickets WHERE id=?", ticket_id)
    if t["status"] == "closed":
        return
    p = prop(t["property_id"])
    db.upd("tickets", ticket_id, status="closed", auto_closed=1 if auto else 0)
    event(ticket_id, by_user, "closed", "Closed automatically – photo proof submitted and no objection within "
          f"{fees.S('auto_close_hours')} h" if auto else "Confirmed fixed")
    pay_contractor(ticket_id)
    ten = db.val("SELECT tenant_id FROM leases WHERE id=?", t["lease_id"]) if t["lease_id"] else None
    for uid in (ten, p["landlord_id"]):
        if uid and not db.val("SELECT 1 FROM reviews WHERE ticket_id=? AND author_id=?", ticket_id, uid):
            notify(uid, "How did they do? Rate the repair", f"{t['ref']} {t['title']} – 30 seconds, helps everyone choose", f"#/app/ticket/{ticket_id}", "review")


def pay_contractor(ticket_id):
    t = db.q1("SELECT * FROM tickets WHERE id=?", ticket_id)
    if t["paid_contractor"] or not t["cost"] or not t["contractor_id"]:
        return
    d = (date.today() + timedelta(days=fees.S("contractor_pay_days"))).isoformat()
    db.ins("ledger", account="contractor", kind="job_payment", amount=t["cost"], date=d, period=d[:7], property_id=t["property_id"],
           description=f"Payment {t['ref']} {t['title']}", ref=f"contractor:{t['contractor_id']}", ticket_id=ticket_id)
    db.upd("tickets", ticket_id, paid_contractor=1)
    notify(t["contractor_id"], f"Payment scheduled – R{t['cost']:,.0f}", f"{t['ref']} confirmed. Paid from the AVA trust account on {d}.", "#/app", "payment")


ISSUE_KINDS = {"extra_work": "Extra work needed", "no_access": "Couldn't get access", "parts": "Waiting for parts",
               "safety": "Safety concern", "other": "Other issue"}


def report_issue(ticket_id, u, kind, text, extra_cost=None, eta=None, photos=None, audio=None):
    """The company records a problem on site (photo and/or voice note). AVA routes it so nobody has to phone around."""
    t = db.q1("SELECT * FROM tickets WHERE id=?", ticket_id)
    p = prop(t["property_id"])
    label = ISSUE_KINDS.get(kind, "Issue")
    msg = f"{label}: {text}".strip(": ")
    photos = photos or []
    event(ticket_id, u["id"], "issue", msg + (f" · extra R{extra_cost:,.0f}" if extra_cost else "") + (f" · expected {eta}" if eta else ""),
          photos[0] if photos else None, 0, audio)
    for ph in photos[1:]:
        event(ticket_id, u["id"], "photo", "", ph)
    ten = db.val("SELECT tenant_id FROM leases WHERE id=?", t["lease_id"]) if t["lease_id"] else None
    if kind == "extra_work" and extra_cost:
        qid = db.ins("quotes", ticket_id=ticket_id, contractor_id=t["contractor_id"], amount=extra_cost, notes=text, status="variation", kind="variation",
                     submitted_at=db.now(), file=photos[0] if photos else None)
        notify(p["landlord_id"], f"Extra work needs your OK – R{extra_cost:,.0f}", f"{t['title']}: {text[:80]}", f"#/app/ticket/{ticket_id}", "quote")
        task(p["pm_id"], p["id"], "approval", f"Owner to approve extra work: {t['title']}", f"R{extra_cost:,.0f} – {text[:80]}", f"#/app/ticket/{ticket_id}", 2,
             dedupe=f"variation:{qid}")
    elif kind == "no_access":
        db.upd("tickets", ticket_id, status="approved", scheduled_for=None)
        if ten:
            notify(ten, "The contractor couldn't get in", f"{t['title']} – please choose a new time in the app.", f"#/app/ticket/{ticket_id}", "maintenance")
    elif kind == "parts" and eta:
        db.upd("tickets", ticket_id, scheduled_for=eta)
        if ten:
            notify(ten, "Waiting for parts", f"{t['title']} – they'll be back around {eta.replace('T', ' ')}.", f"#/app/ticket/{ticket_id}", "maintenance")
    elif kind == "safety":
        task(p["pm_id"], p["id"], "escalation", f"Safety concern at {p['title']}", f"{t['ref']}: {text[:120]}", f"#/app/ticket/{ticket_id}", 1)
        notify(p["landlord_id"], "Safety concern reported", f"{t['title']}: {text[:80]}", f"#/app/ticket/{ticket_id}", "maintenance")
    else:
        notify(p["pm_id"], f"{t['ref']}: issue reported", msg[:90], f"#/app/ticket/{ticket_id}", "maintenance")
    log(p["pm_id"], p["id"], f"{t['ref']} – {label.lower()} reported by the contractor and routed automatically", f"#/app/ticket/{ticket_id}", u["name"])


def decide_variation(ticket_id, quote_id, accept, u):
    q = db.q1("SELECT * FROM quotes WHERE id=? AND ticket_id=? AND kind='variation' AND status='variation'", quote_id, ticket_id)
    if not q:
        raise HTTPException(404, "No extra-work request waiting")
    t = db.q1("SELECT * FROM tickets WHERE id=?", ticket_id)
    db.upd("quotes", quote_id, status="approved" if accept else "rejected")
    if accept:
        db.upd("tickets", ticket_id, cost=(t["cost"] or 0) + q["amount"])
    event(ticket_id, u["id"], "variation", f"{u['name']} {'approved' if accept else 'declined'} extra work of R{q['amount']:,.0f}")
    notify(q["contractor_id"], "Extra work " + ("approved – go ahead" if accept else "declined"), t["title"], f"#/app/ticket/{ticket_id}", "quote")
    close_tasks(f"variation:{quote_id}")
