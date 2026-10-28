"""AVA Autopilot: the routine work one agent would otherwise do by hand.

tick() is idempotent: run it as often as you like (on start, every 10 minutes, or 'Run now').
Each rule either does the work itself or raises a task in the PM's inbox, so the PM only sees exceptions.
"""
import threading
import time
from datetime import date, datetime, timedelta

from . import trust, ai, db, fees, services as sv


def tick(today=None):
    t = today or date.today()
    out = {"rent_charged": 0, "escalations": 0, "arrears": 0, "renewals": 0, "outgoing": 0, "shortlisted": 0,
           "snags_overdue": 0, "viewing_reminders": 0, "interest": 0, "payouts_ready": 0, "alerts": 0}
    leases = db.q("SELECT l.*, p.pm_id, p.title, p.landlord_id FROM leases l JOIN properties p ON p.id=l.property_id WHERE l.status='active'")
    for l in leases:
        if sv.apply_escalation(l, t):
            out["escalations"] += 1
            l = {**l, **db.q1("SELECT rent FROM leases WHERE id=?", l["id"])}
        if l["start_date"] <= t.isoformat() and sv.charge_rent(l, t):
            out["rent_charged"] += 1
            sv.notify(l["tenant_id"], f"Rent for {t.isoformat()[:7]} is due", f"R{l['rent']:,} by day {l['due_day']}.", "#/app/pay", "payment")
        # arrears ladder: reminder (due+1), final reminder (due+5), letter of demand (due+10)
        bal = sv.balance("tenant", l["id"])
        if bal > 0 and t.day > (l["due_day"] or 1):
            late = t.day - (l["due_day"] or 1)
            stage = "letter of demand" if late >= 10 else "final reminder" if late >= 5 else "reminder"
            key = f"arrears:{l['id']}:{t.isoformat()[:7]}:{stage}"
            if sv.task(l["pm_id"], l["property_id"], "arrears", f"Arrears R{bal:,.0f} – {l['title']}",
                       f"{late} days late. AVA sent a {stage} to the tenant.", f"#/app/property/{l['property_id']}",
                       1 if stage != "reminder" else 2, t.isoformat(), key):
                sv.notify(l["tenant_id"], f"Payment {stage}", f"Your balance of R{bal:,.0f} is {late} days overdue. Pay in the app to avoid further action.", "#/app/pay", "payment")
                out["arrears"] += 1
        # renewals 60 days out
        end = date.fromisoformat(l["end_date"])
        leaving = db.val("SELECT 1 FROM inspections WHERE lease_id=? AND type='outgoing'", l["id"]) or db.val("SELECT 1 FROM leases WHERE renewal_of=?", l["id"])
        if t <= end <= t + timedelta(days=60) and not leaving:
            risk = ai.renewal_risk(l["id"])
            if sv.task(l["pm_id"], l["property_id"], "renewal", f"Lease ends {l['end_date']} – {l['title']}",
                       f"Renewal risk {risk['level']} ({risk['score']}). {risk['action']}.", f"#/app/lease/{l['id']}",
                       1 if risk["level"] == "high" else 2, (end - timedelta(days=40)).isoformat(), f"renewal:{l['id']}"):
                sv.notify(l["tenant_id"], "Would you like to renew?", f"Your lease ends on {l['end_date']}. Let us know in the app.", f"#/app/lease/{l['id']}", "lease")
                out["renewals"] += 1
        # outgoing inspection 10 days out
        if t <= end <= t + timedelta(days=10) and not db.val("SELECT 1 FROM inspections WHERE lease_id=? AND type='outgoing'", l["id"]):
            if not db.val("SELECT 1 FROM leases WHERE renewal_of=?", l["id"]):
                iid = sv.create_inspection(l["property_id"], "outgoing", l["id"], date_=(end - timedelta(days=2)).isoformat())
                sv.task(l["pm_id"], l["property_id"], "inspection", f"Outgoing inspection – {l['title']}", "Book with the tenant (within 3 days of moving out).",
                        f"#/app/inspection/{iid}", 1, (end - timedelta(days=2)).isoformat(), f"outgoing:{l['id']}")
                out["outgoing"] += 1
        # deposit interest, once a month
        per = t.isoformat()[:7]
        held = sv.balance("deposit", l["id"])
        if held > 0 and not db.val("SELECT 1 FROM ledger WHERE lease_id=? AND kind='deposit_interest' AND period=?", l["id"], per):
            trust.open_deposit_account(l["id"])      # each deposit has its own investment account
            if trust.post_interest(l["id"], per, t.isoformat()):
                out["interest"] += 1
    if fees.on("maintenance"):   # repairs run in Fixit while the module is off
        # quotes past their deadline -> shortlist and send to the landlord
        for tk in db.q("SELECT * FROM tickets WHERE status='quoting' AND quote_deadline<=?", datetime.combine(t, datetime.now().time()).isoformat(timespec="minutes")):
            if sv.shortlist(tk["id"]):
                out["shortlisted"] += 1
            else:
                p = sv.prop(tk["property_id"])
                sv.task(p["pm_id"], p["id"], "maintenance", f"No quotes yet: {tk['title']}", "Quote window closed with no quotes.", f"#/app/ticket/{tk['id']}", 1, dedupe=f"noquotes:{tk['id']}")
        # tickets with all requested quotes in -> shortlist early
        for tk in db.q("SELECT t.* FROM tickets t WHERE status='quoting' AND NOT EXISTS (SELECT 1 FROM quotes q WHERE q.ticket_id=t.id AND q.status='requested') "
                       "AND EXISTS (SELECT 1 FROM quotes q WHERE q.ticket_id=t.id AND q.status='submitted')"):
            if sv.shortlist(tk["id"]):
                out["shortlisted"] += 1
        # stalled jobs
        for tk in db.q("SELECT t.*, p.pm_id, p.title ptitle FROM tickets t JOIN properties p ON p.id=t.property_id WHERE t.status IN ('approved','scheduled') AND t.updated_at<?",
                       (datetime.combine(t, datetime.min.time()) - timedelta(days=5)).isoformat()):
            sv.task(tk["pm_id"], tk["property_id"], "maintenance", f"Stalled: {tk['title']}", "No update from the contractor for 5 days. AVA nudged them.",
                    f"#/app/ticket/{tk['id']}", 2, dedupe=f"stalled:{tk['id']}:{t.isoformat()[:7]}")
            sv.notify(tk["contractor_id"], "Update needed", f"{tk['ref']} {tk['title']} – please book or update.", f"#/app/ticket/{tk['id']}", "maintenance")
    # overdue snags
    for s in db.q("SELECT s.*, p.pm_id FROM snags s JOIN properties p ON p.id=s.property_id WHERE s.status IN ('open','in_progress') AND s.due_date<?", t.isoformat()):
        if sv.task(s["pm_id"], s["property_id"], "snag", f"Overdue snag {s['ref']}: {s['title']}",
                   f"{(t - date.fromisoformat(s['due_date'][:10])).days} days overdue · " + (db.val("SELECT company FROM users WHERE id=?", s["contractor_id"]) or "no contractor assigned") + (f" · R{s['qty'] * s['rate']:,.0f} to rectify" if s.get("rate") else ""), f"#/app/snags/{s['property_id']}",
                   2, s["due_date"], f"snagdue:{s['id']}"):
            sv.notify(s["contractor_id"], f"Snag {s['ref']} is overdue", s["title"], f"#/app/snags/{s['property_id']}", "snag")
            out["snags_overdue"] += 1
    # ready snags waiting for re-inspection
    for r in db.q("SELECT s.property_id, p.pm_id, p.title, COUNT(*) n FROM snags s JOIN properties p ON p.id=s.property_id WHERE s.status='ready' GROUP BY s.property_id"):
        sv.task(r["pm_id"], r["property_id"], "snag", f"{r['n']} snag(s) ready for re-inspection – {r['title']}", "Contractor marked them fixed.",
                f"#/app/snags/{r['property_id']}", 2, dedupe=f"ready:{r['property_id']}:{t.isoformat()}")
    # viewings tomorrow
    tm = (t + timedelta(days=1)).isoformat()
    for v in db.q("SELECT v.*, p.title, p.address FROM viewings v JOIN properties p ON p.id=v.property_id WHERE v.status='confirmed' AND substr(v.slot,1,10)=?", tm):
        if sv.task(None, v["property_id"], "_reminder", "", dedupe=f"viewrem:{v['id']}"):
            sv.notify(v["user_id"], "Viewing tomorrow", f"{v['title']} at {v['slot'][11:16]} – {v['address']}", f"#/p/{v['property_id']}", "viewing")
            out["viewing_reminders"] += 1
    # owner payouts ready from payout_day for last month
    if t.day >= fees.S("payout_day"):
        last = (t.replace(day=1) - timedelta(days=1)).isoformat()[:7]
        for pm in db.q("SELECT DISTINCT pm_id FROM properties WHERE pm_id IS NOT NULL"):
            n = db.val("""SELECT COUNT(DISTINCT property_id) FROM ledger l WHERE account='owner' AND kind='rent_received' AND period=?
                          AND property_id IN (SELECT id FROM properties WHERE pm_id=?)
                          AND NOT EXISTS (SELECT 1 FROM ledger x WHERE x.property_id=l.property_id AND x.kind='payout' AND x.period=?)""", last, pm["pm_id"], last)
            if n and sv.task(pm["pm_id"], None, "payout", f"Owner payouts for {last} ready ({n})", "Review and release in Money → Payouts.",
                             "#/app/money/payouts", 2, dedupe=f"payout:{pm['pm_id']}:{last}"):
                out["payouts_ready"] += 1
    # new applications -> score + inbox
    for a in db.q("SELECT a.*, p.rent, p.pm_id, p.title FROM applications a JOIN properties p ON p.id=a.property_id WHERE a.status='submitted' AND a.score IS NULL"):
        sc, notes = ai.score_application(a, a["rent"])
        db.upd("applications", a["id"], score=sc, score_notes="\n".join(notes), status="screening")
        sv.task(a["pm_id"], a["property_id"], "application", f"Application {sc}/100 – {a['title']}", f"{a['name']}: " + notes[0],
                f"#/app/applications", 1 if sc >= 70 else 3, dedupe=f"app:{a['id']}")
    if fees.on("maintenance"):
        # finished jobs with photo proof close themselves if nobody objects
        cutoff = (datetime.now() - timedelta(hours=fees.S("auto_close_hours"))).isoformat(timespec="seconds")
        for tk in db.q("SELECT id FROM tickets WHERE status='completed' AND completed_at<=?", cutoff):
            sv.close_job(tk["id"], auto=True)
            out["jobs_closed"] = out.get("jobs_closed", 0) + 1
        # maintenance listing subscriptions
        for c in db.q("SELECT c.user_id, c.sub_until, u.company FROM contractors c JOIN users u ON u.id=c.user_id WHERE c.approved=1 AND c.sub_until IS NOT NULL"):
            days = (date.fromisoformat(c["sub_until"]) - t).days
            if days in (3, 0, -1):
                key = f"sub:{c['user_id']}:{c['sub_until']}:{days}"
                if sv.task(None, None, "_sub", "", dedupe=key):
                    sv.notify(c["user_id"], "Your AVA listing expires soon" if days > 0 else "Your AVA listing has expired",
                              f"Renew for R{fees.S('contractor_listing_fee')}/month to keep receiving repair requests within {fees.S('quote_radius_km'):g} km.", "#/app", "subscription")
    # growth & compliance: portals, greetings, identity checks waiting for a person, POPIA deadlines
    from . import crm, syndicate
    out["portal_withdrawn"] = syndicate.withdraw_stale()
    out["portal_enquiries"] = syndicate.simulate_activity(t)
    out["greetings"] = crm.greetings(t)
    for k in db.q("""SELECT k.id, k.user_id, u.name, (SELECT p.pm_id FROM applications a JOIN properties p ON p.id=a.property_id WHERE a.user_id=k.user_id ORDER BY a.id DESC LIMIT 1) pm1,
                     (SELECT p.pm_id FROM leases l JOIN properties p ON p.id=l.property_id WHERE l.tenant_id=k.user_id ORDER BY l.id DESC LIMIT 1) pm2,
                     (SELECT p.pm_id FROM properties p WHERE p.landlord_id=k.user_id LIMIT 1) pm3
                     FROM kyc_checks k JOIN users u ON u.id=k.user_id WHERE k.status='review'
                     AND k.id=(SELECT MAX(id) FROM kyc_checks x WHERE x.user_id=k.user_id)"""):
        sv.task(k["pm1"] or k["pm2"] or k["pm3"], None, "fica", f"FICA check needs a look: {k['name']}", "Some identity checks could not be confirmed automatically.",
                f"#/app/compliance/kyc/{k['id']}", 1, t.isoformat(), f"kyc:{k['id']}")
    for d in db.q("SELECT d.*, u.name FROM dsr d LEFT JOIN users u ON u.id=d.user_id WHERE d.status='open' AND d.due_date<=?", (t + timedelta(days=7)).isoformat()):
        for a in db.q("SELECT id FROM users WHERE role='admin' AND active=1"):
            if sv.task(None, None, "_dsr", "", dedupe=f"dsr:{d['id']}:{a['id']}"):
                sv.notify(a["id"], "POPIA request due soon", f"{d['name'] or d['email']}: respond by {d['due_date']}", "#/app/compliance/popia", "privacy")
    # trust accounting: mirror today's money into the cashbooks, collect debit orders, pull the bank feeds
    trust.ensure_books()
    trust.sync()
    if trust.debit_run(t.isoformat()):
        out["debit_orders"] = out.get("debit_orders", 0) + 1
    trust.queue_owner_payouts()
    for code in trust.BOOKS:
        if trust.book(code)["feed"] == "simulated":
            r = trust.feed(code)
            out["bank_lines"] = out.get("bank_lines", 0) + r["new_lines"]
        db.set_setting("last_tick", datetime.now().isoformat(timespec="seconds"))
    return out


def area_alerts(prop_id):
    """A listing went live: tell everyone whose saved search (map area + all filters) matches it."""
    import json
    from . import search
    p = db.q1("SELECT * FROM properties WHERE id=?", prop_id)
    n = 0
    for a in db.q("SELECT * FROM alerts"):
        try:
            qd = json.loads(a["query"])
        except ValueError:
            continue
        if isinstance(qd.get("bounds"), list):
            qd["bounds"] = ",".join(str(x) for x in qd["bounds"])
        if not search.matches(qd, prop_id):
            continue
        sv.notify(a["user_id"], "New listing matches your alert", f"{p['headline'] or p['title']} – R{p['rent']:,}/month", f"#/p/{p['id']}", "alert")
        n += 1
    return n


def start_background(interval=600):
    def loop():
        while True:
            try:
                tick()
            except Exception as e:  # keep the loop alive
                print("autopilot error:", e)
            time.sleep(interval)
    threading.Thread(target=loop, daemon=True).start()
