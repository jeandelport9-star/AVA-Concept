"""AVA Virtual Agent – does the talking a rental agent would do, 24/7.

* Prospects (on a listing or the home page): answers questions about the home from its data, finds similar homes,
  pre-qualifies on affordability, offers open viewing slots and books them, starts the application, or hands over
  to the portfolio manager with the lead's details.
* Tenants / landlords / contractors: everything AVA Assist does (balance, payments, repairs, lease, rights) plus
  notice, renewal, inspections, deposit, statements, approvals and job status.
Every turn is logged so the PM sees what the agent said and what it could not handle.
Works offline with rules; with an Anthropic key the reply text is written by Claude from the same facts.
"""
import json
import re
from datetime import date

from . import ai, db, fees, services as sv
from .search import FEATURES


FEATURE_WORDS = {
    r"solar|inverter|load.?shed|backup|power cut": ["Solar / inverter", "Backup power"],
    r"pool|swim": ["Pool", "Complex pool"], r"garden|yard|lawn": ["Garden"], r"fibre|internet|wifi": ["Fibre"],
    r"fire ?place": ["Fireplace"], r"braai|lapa": ["Lapa / braai"], r"borehole|water tank|jojo": ["Borehole"],
    r"gym": ["Gym"], r"security|safe|guard|electric fence": ["24h security", "Electric fence", "Complex security"],
}


def money(v):
    return f"R{v:,.0f}".replace(",", " ")


def parse_money(t):
    m = re.search(r"r?\s?(\d[\d\s,]*(?:\.\d+)?)\s*(k|000)?", t.replace(" ", ""))
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    if m.group(2) == "k" or (v < 200 and "k" in t):
        v *= 1000
    return v


def search_from_text(t):
    q = {}
    m = re.search(r"(\d)\s*(?:-|\s)?(?:bed|bedroom|br)", t)
    if m:
        q["beds"] = int(m.group(1))
    m = re.search(r"(?:under|below|max|less than|up to|budget(?: of)?)\s*r?\s?(\d[\d\s,]*k?)", t)
    if m:
        q["max_rent"] = parse_money(m.group(1))
    for c in db.q("SELECT DISTINCT suburb s FROM properties UNION SELECT DISTINCT city FROM properties"):
        if c["s"] and c["s"].lower() in t:
            q["city"] = c["s"]
            break
    if re.search(r"\bpet|dog|cat\b", t):
        q["pets"] = 1

    words = {"backup_power": r"solar|inverter|load.?shed|backup power|generator", "pool": r"pool", "garden": r"garden|yard",
             "flatlet": r"flatlet|granny", "security": r"security|estate|secure|gated", "backup_water": r"borehole|water tank|jojo",
             "fibre": r"fibre|internet", "study": r"study|home office", "aircon": r"aircon|air con", "garage": r"garage",
             "fireplace": r"fireplace", "braai": r"braai|lapa", "wheelchair": r"wheelchair|accessible", "staff": r"staff quarters|domestic"}
    feats = [k for k, pat in words.items() if k in FEATURES and re.search(pat, t)]
    if feats:
        q["features"] = ",".join(feats)
    for typ in ("house", "townhouse", "apartment", "flat", "cottage"):
        if typ in t:
            q["type"] = {"flat": "Apartment"}.get(typ, typ.title())
    return q


def listing_reply(p, t, u, ctx):
    """Prospect asking about one listing."""
    acts, intent = [], "faq"
    feats = p["features"] or []
    mi = fees.move_in_costs(p["rent"] or 0, p["bedrooms"], p["bathrooms"])
    if re.search(r"human|person|agent|call me|speak|talk to|phone", t):
        intent = "handoff"
        return intent, (f"Of course – I've asked {(db.val('SELECT name FROM users WHERE id=?', p['pm_id']) or 'the portfolio manager').split()[0]}, "
                        "the portfolio manager for this home, to contact you. Leave your number below if you're not signed in."), [{"label": "Leave my number", "action": "handoff"}]
    if re.search(r"view|see it|visit|show me|appointment|when can i|look at it|book", t):
        intent = "viewing"
        from .api import slots as get_slots
        free = [s["slot"] for s in get_slots(p["id"]) if s["free"]][:6]
        acts = [{"label": s.replace("T", " "), "action": "book", "slot": s} for s in free]
        acts.append({"label": "Take the 360° tour first", "action": "tour"})
        return intent, "Here are the next open viewing times – tap one and I'll confirm it straight away:" if free else "No open slots in the next two weeks – I'll ask the manager to add some.", acts
    if re.search(r"apply|application|how do i get|rent it|take it|interested", t):
        intent = "apply"
        return intent, ("You can apply online in about 5 minutes: ID, 3 months' payslips and bank statements. AVA checks affordability, credit and "
                        "rental history immediately and the landlord usually decides within a day."), [{"label": "Apply now", "action": "apply"}]
    m = re.search(r"(earn|salary|income|make|take home|net)\D{0,20}(r?\s?\d[\d\s,]*k?)", t) or (re.search(r"(r?\s?\d[\d\s,]*k)\b", t) if "afford" in t or "qualify" in t else None)
    if m or "afford" in t or "qualify" in t:
        intent = "qualify"
        inc = parse_money(m.group(m.lastindex)) if m else None
        if not inc:
            return intent, f"The rent is {money(p['rent'])}. Landlords look for rent to be at most about a third of gross income – so roughly {money(p['rent'] * 3)} a month. What's your gross monthly income?", []
        r = p["rent"] / inc
        verdict = ("comfortably within the guideline" if r <= .30 else "within the guideline" if r <= .335 else
                   "a little above the usual one-third guideline – a co-applicant or a strong credit record helps" if r <= .40 else
                   "above what most landlords accept; a co-applicant would be needed")
        acts = [{"label": "Apply now", "action": "apply"}] if r <= .40 else [{"label": "Show cheaper similar homes", "action": "similar"}]
        return intent, f"At {money(inc)} gross a month the rent would be {r:.0%} of your income – {verdict}.", acts
    if re.search(r"similar|other|cheaper|alternatives|else", t):
        intent = "similar"
        from .api import listings
        sim = [x for x in listings(city=p["city"], max_rent=p["rent"] * 1.1, limit=6) if x["id"] != p["id"]][:3]
        return intent, "Here are similar homes nearby:" if sim else "Nothing similar is listed right now – save an alert and I'll tell you when one comes up.", \
            [{"label": f"{x['headline'] or x['title']} – {money(x['rent'])}", "href": f"#/p/{x['id']}"} for x in sim]
    if re.search(r"360|virtual|tour|photos|video", t):
        intent = "tour"
        n = db.val("SELECT COUNT(*) FROM media WHERE property_id=? AND kind='pano'", p["id"])
        return intent, f"{'There is a 360° walk-through of ' + str(n) + ' rooms' if n else 'There are photos of every room'} – you can look around every room from your phone.", \
            [{"label": "Open 360° tour", "action": "tour"}] if n else []
    answers = []
    if re.search(r"price|rent|cost|how much|deposit|move.?in|fees|upfront", t):
        intent = "costs"
        answers.append(f"Rent is {money(p['rent'])} a month and the deposit is {money(p['deposit'] or p['rent'])}. Total to move in is {money(mi['total'])} "
                       f"({', '.join(l['label'].lower() + ' ' + money(l['amount']) for l in mi['lines'][1:])}). No agent commission is charged to tenants.")
    if re.search(r"availab|move in|when|vacant|free from", t):
        answers.append(f"It's available from {p['available_from'] or 'now'}.")
    if re.search(r"\bpet|dog|cat\b", t):
        answers.append("Pets are welcome on application (a pet addendum is added to the lease)." if p["pets"] else "Unfortunately this landlord doesn't allow pets.")
    if re.search(r"park|garage|car", t):
        answers.append(f"There {'is' if p['parking'] == 1 else 'are'} {p['parking']} parking bay{'s' if p['parking'] != 1 else ''}.")
    if re.search(r"size|big|m2|m²|square", t):
        answers.append(f"It's about {p['size_m2']:.0f} m² with {p['bedrooms']:g} bedrooms and {p['bathrooms']:g} bathrooms." if p["size_m2"] else f"{p['bedrooms']:g} bedrooms, {p['bathrooms']:g} bathrooms.")
    if re.search(r"bed|room", t) and not answers:
        answers.append(f"{p['bedrooms']:g} bedrooms and {p['bathrooms']:g} bathrooms.")
    if re.search(r"furnish", t):
        answers.append("It's furnished." if p["furnished"] else "It's unfurnished.")
    if re.search(r"where|location|area|address|near|school|shops|gautrain|safe", t):
        answers.append(f"It's in {p['suburb']}, {p['city']}. The exact address is sent when your viewing is confirmed.")
    for pat, names in FEATURE_WORDS.items():
        if re.search(pat, t):
            has = [f for f in feats if f in names]
            answers.append(f"Yes – {', '.join(has).lower()}." if has else f"The listing doesn't mention {names[0].lower()}.")
    if re.search(r"electric|prepaid|water|utilit", t):
        answers.append("Electricity and water are for the tenant's account (prepaid or by meter reading, as set out in the lease).")
    if re.search(r"lease|how long|term|month.?to.?month", t):
        answers.append("The standard lease is 12 months, with a 20-business-day notice period under the CPA. Renewals carry no admin fee.")
    if answers:
        return intent, " ".join(answers), [{"label": "Book a viewing", "action": "ask", "text": "When can I view it?"}]
    return "unknown", None, []


def respond(u, text, ctx=None):
    ctx = ctx or {}
    t = (text or "").lower().strip()
    pid = ctx.get("property_id")
    reply, acts, intent, handoff = None, [], "unknown", 0
    p = db.q1("SELECT * FROM properties WHERE id=?", int(pid)) if pid else None
    if p:
        intent, reply, acts = listing_reply(p, t, u, ctx)
    if not reply and (not u or u["role"] == "tenant") and re.search(r"looking for|find|search|need a|want a|\d\s*-?\s*bed|to rent|under r|budget", t):
        q = search_from_text(t)
        from .api import listings
        rows = listings(limit=5, **q)
        intent = "search"
        desc = ", ".join(x for x in [f"{q['beds']}+ bed" if q.get("beds") else "", q.get("type", "").lower(), f"in {q['city']}" if q.get("city") else "",
                                      f"under {money(q['max_rent'])}" if q.get("max_rent") else "", "pet friendly" if q.get("pets") else "",
                                      ("with " + ", ".join(FEATURES[k][0].lower() for k in q["features"].split(","))) if q.get("features") else ""] if x)
        reply = f"I found {len(rows)} match{'es' if len(rows) != 1 else ''} ({desc}):" if rows else f"Nothing {desc} is listed right now. Save an area alert and I'll message you the moment one is."
        acts = [{"label": f"{x['headline'] or x['title']} – {money(x['rent'])}", "href": f"#/p/{x['id']}"} for x in rows[:4]]
        from urllib.parse import urlencode
        acts.append({"label": "See all results with these filters", "href": "#/search?" + urlencode({("areas" if k == "city" else k): v for k, v in q.items()})})
    if not reply and u:
        intent, reply, acts = signed_in(u, t, text)
    if not reply:
        r = ai.assistant(u, text) if u else {"reply": None, "actions": []}
        if r.get("reply") and not r["reply"].startswith("I can help with"):
            reply, acts, intent = r["reply"], r["actions"], intent if intent != "unknown" else "assist"
    if not reply:
        for pat, ans in ai.LEARN:
            if re.search(pat, t):
                reply, intent = ans, "rights"
                break
    if intent == "handoff" or not reply:
        handoff = 1
        target_pm = p["pm_id"] if p else (db.val("SELECT p.pm_id FROM leases l JOIN properties p ON p.id=l.property_id WHERE l.tenant_id=? ORDER BY l.id DESC LIMIT 1", u["id"]) if u else None)
        target_pm = target_pm or db.val("SELECT id FROM users WHERE role='pm' ORDER BY id LIMIT 1")
        who = (u["name"] + " " + (u.get("phone") or u["email"])) if u else (ctx.get("contact") or "a website visitor")
        sv.task(target_pm, p["id"] if p else None, "escalation", f"Virtual agent hand-over: {who}", f"“{text[:120]}”" + (f" – about {p['title']}" if p else ""),
                f"#/app/ai", 1, dedupe=f"handoff:{ctx.get('session')}:{date.today()}:{text[:40]}")
        if not reply:
            reply = "Good question – I've passed it to your portfolio manager, who will reply shortly. Anything else I can help with meanwhile?"
    llm = ai.ask_llm("You are AVA's virtual rental agent in South Africa. Reply in max 70 words, warm and factual. Never invent facts beyond these. "
                     f"Facts/draft: {reply}\nListing: {json.dumps({k: p[k] for k in ('title','rent','deposit','suburb','city','bedrooms','bathrooms','pets','available_from')}) if p else 'none'}\n"
                     f"User: {text}") if reply else None
    if isinstance(llm, str) and llm.strip():
        reply = llm.strip()
    db.ins("agent_log", session=ctx.get("session"), user_id=u["id"] if u else None, property_id=p["id"] if p else None,
           role=u["role"] if u else "visitor", text=text[:500], reply=reply[:1000], intent=intent, handoff=handoff)
    return {"reply": reply, "actions": acts, "intent": intent, "handoff": bool(handoff)}


def signed_in(u, t, raw):
    r = u["role"]
    if r == "tenant":
        lease = db.q1("SELECT * FROM leases WHERE tenant_id=? ORDER BY (status='active') DESC, id DESC LIMIT 1", u["id"])
        if re.search(r"application|applied|status of my app", t):
            apps = db.q("SELECT a.status, a.score, p.title FROM applications a JOIN properties p ON p.id=a.property_id WHERE a.user_id=? ORDER BY a.id DESC LIMIT 3", u["id"])
            if apps:
                return "application", "Your applications: " + "; ".join(f"{a['title']} – {a['status']} (score {a['score'] or '…'})" for a in apps) + ".", []
        if lease and re.search(r"notice|move out|moving out|leave|vacate|cancel", t):
            return "notice", (f"You can give notice in the app: under the Consumer Protection Act a fixed-term lease can be cancelled with 20 business days' written notice "
                              f"(a reasonable penalty may apply before {lease['end_date']}). I'll book your outgoing inspection automatically."), [{"label": "Give notice", "href": f"#/app/lease/{lease['id']}"}]
        if lease and re.search(r"renew|extend|stay longer", t):
            sv.task(db.val("SELECT pm_id FROM properties WHERE id=?", lease["property_id"]), lease["property_id"], "renewal", f"Tenant wants to renew – lease #{lease['id']}",
                    raw[:120], f"#/app/lease/{lease['id']}", 1, dedupe=f"wantrenew:{lease['id']}")
            return "renew", f"Great – I've told your portfolio manager you'd like to renew. The new rent would be about R{lease['rent'] * (1 + lease['escalation_pct'] / 100):,.0f} ({lease['escalation_pct']:g}% escalation); you'll get the renewal to sign in the app.", []
        if lease and re.search(r"inspection", t):
            i = db.q1("SELECT * FROM inspections WHERE lease_id=? ORDER BY id DESC LIMIT 1", lease["id"])
            if i:
                return "inspection", f"Your {i['type']} inspection is {('on ' + i['date']) if i['status'] != 'final' else 'signed off'}. It's done jointly – you'll sign on the inspector's phone or in the app.", [{"label": "Open inspection", "href": f"#/app/inspection/{i['id']}"}]
        if lease and re.search(r"deposit back|refund|my deposit", t):
            held = sv.balance("deposit", lease["id"])
            return "deposit", f"AVA holds R{held:,.0f} for you (deposit plus interest). After the outgoing inspection it's refunded within 7 days if there's no damage, or within 14 days of repairs, with a breakdown of any deduction.", []
    if r == "landlord":
        ids = [x["id"] for x in db.q("SELECT id FROM properties WHERE landlord_id=?", u["id"])]
        from .auth import in_list
        if re.search(r"earn|income|statement|paid|payout|how much", t):
            x = db.q1(f"SELECT period, -SUM(amount) s FROM ledger WHERE account='owner' AND kind='payout' AND property_id IN {in_list(ids)} GROUP BY period ORDER BY period DESC LIMIT 1")
            if x:
                return "statement", f"Your last payout was R{x['s']:,.0f} for {db.month_name(x['period'])}. Statements per property are under Statements.", [{"label": "Open statements", "href": "#/app/money?tab=payouts"}]
        if re.search(r"approv|quote|repair|maintenance", t):
            n = db.val(f"SELECT COUNT(*) FROM tickets WHERE status='awaiting_approval' AND property_id IN {in_list(ids)}")
            return "approvals", f"{n} repair{'s are' if n != 1 else ' is'} waiting for your approval." if n else "Nothing is waiting for your approval.", [{"label": "Review", "href": "#/app/maintenance"}] if n else []
        if re.search(r"vacan|tenant|occup|arrears|late", t):
            k = db.q(f"SELECT p.title, l.id FROM properties p LEFT JOIN leases l ON l.property_id=p.id AND l.status='active' WHERE p.id IN {in_list(ids)}")
            vac = [x["title"] for x in k if not x["id"]]
            late = [x["title"] for x in k if x["id"] and sv.balance("tenant", x["id"]) > 0]
            return "portfolio", f"{len(k) - len(vac)} of {len(k)} homes are let." + (f" Vacant: {', '.join(vac)}." if vac else "") + (f" Behind on rent: {', '.join(late)} – AVA is sending reminders." if late else " Everyone is up to date."), []
    if r == "contractor":
        if re.search(r"job|quote|work|snag", t):
            n1 = db.val("SELECT COUNT(*) FROM quotes WHERE contractor_id=? AND status='requested'", u["id"])
            n2 = db.val("SELECT COUNT(*) FROM tickets WHERE contractor_id=? AND status IN ('approved','scheduled','in_progress')", u["id"])
            n3 = db.val("SELECT COUNT(*) FROM snags WHERE contractor_id=? AND status IN ('open','in_progress')", u["id"])
            return "jobs", f"You have {n1} quote request(s), {n2} active job(s) and {n3} open snag(s).", [{"label": "Open my jobs", "href": "#/app"}]
    return "unknown", None, []


def stats(pm_id=None):
    w = ""
    if pm_id:
        w = f" AND (property_id IN (SELECT id FROM properties WHERE pm_id={int(pm_id)}) OR property_id IS NULL)"
    week = f"created_at >= date('now','-7 day')"
    return {
        "conversations": db.val(f"SELECT COUNT(DISTINCT COALESCE(session, user_id)) FROM agent_log WHERE {week} {w}") or 0,
        "messages": db.val(f"SELECT COUNT(*) FROM agent_log WHERE {week} {w}") or 0,
        "handoffs": db.val(f"SELECT COUNT(*) FROM agent_log WHERE handoff=1 AND {week} {w}") or 0,
        "viewings_booked": db.val(f"SELECT COUNT(*) FROM agent_log WHERE intent='booked' AND {week} {w}") or 0,
        "by_intent": db.q(f"SELECT intent, COUNT(*) n FROM agent_log WHERE {week} {w} GROUP BY intent ORDER BY n DESC"),
        "recent": db.q(f"SELECT a.*, u.name, p.title FROM agent_log a LEFT JOIN users u ON u.id=a.user_id LEFT JOIN properties p ON p.id=a.property_id WHERE 1=1 {w} ORDER BY a.id DESC LIMIT 60"),
        "tickets_triaged": db.val("SELECT COUNT(*) FROM tickets WHERE ai_notes IS NOT NULL" + (f" AND property_id IN (SELECT id FROM properties WHERE pm_id={int(pm_id)})" if pm_id else "")) or 0,
        "emergencies": db.val("SELECT COUNT(*) FROM ticket_events WHERE kind='dispatch'") or 0,
        "apps_scored": db.val("SELECT COUNT(*) FROM applications WHERE score IS NOT NULL") or 0,
        "quotes_ranked": db.val("SELECT COUNT(*) FROM quotes WHERE rank_score IS NOT NULL") or 0,
        "autopilot_actions": db.val("SELECT COUNT(*) FROM activity WHERE actor='AVA Autopilot'" + (f" AND pm_id={int(pm_id)}" if pm_id else "")) or 0,
        "escalations": db.val("SELECT COUNT(*) FROM tasks WHERE kind='escalation'" + (f" AND pm_id={int(pm_id)}" if pm_id else "")) or 0,
    }
