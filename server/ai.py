"""AVA Assist: the automation brain.

Everything works offline with transparent rules. When an Anthropic API key is set under Settings,
the tenant/landlord assistant and listing copy use Claude, with the same rule results as context
and as the fallback if the call fails.
"""
import json
import re
import statistics
from datetime import date, datetime, timedelta

from . import db, fees

# ---------------------------------------------------------------- maintenance triage
TRIAGE = [
    # (pattern, category, trade, priority, responsible)
    (r"burst|flood|water everywhere|gushing|geyser (burst|leak)|pipe (burst|leak)", "Plumbing", "Plumber", "Urgent", "landlord"),
    (r"gas (smell|leak)|smell gas", "Gas", "Gas installer (SAQCC)", "Urgent", "landlord"),
    (r"spark|smok|burning smell|electric shock|no power|tripping|trips|db board|earth leakage", "Electrical", "Electrician", "Urgent", "landlord"),
    (r"locked out|lockout|lost (my )?key|break[- ]?in|burglar|broken lock|gate motor|alarm", "Security", "Locksmith / security", "High", "landlord"),
    (r"sewer|sewage|blocked toilet|toilet (blocked|overflow)|drain", "Plumbing", "Plumber", "High", "landlord"),
    (r"geyser|hot water|no hot", "Plumbing", "Plumber", "High", "landlord"),
    (r"leak|drip|tap|toilet|cistern|shower|basin|plumb", "Plumbing", "Plumber", "Medium", "landlord"),
    (r"roof|ceiling (stain|damp|leak)|gutter|damp|mould|mold|rising damp|waterproof", "Roofing & damp", "Roofer / waterproofer", "Medium", "landlord"),
    (r"light|plug|socket|switch|bulb|stove|oven|hob|extractor", "Electrical", "Electrician", "Medium", "landlord"),
    (r"fridge|dishwasher|washing machine|appliance|microwave", "Appliances", "Appliance repair", "Medium", "landlord"),
    (r"aircon|air con|heat pump|hvac", "HVAC", "HVAC technician", "Medium", "landlord"),
    (r"door|window|handle|hinge|cupboard|drawer|glass|pane", "Carpentry & glazing", "Handyman", "Low", "landlord"),
    (r"paint|wall|crack|plaster|tile|floor|carpet", "Finishes", "Painter / builder", "Low", "landlord"),
    (r"pest|cockroach|rat|mice|ants|termite|bees", "Pest control", "Pest control", "Medium", "landlord"),
    (r"pool|garden|irrigation|lawn", "Garden & pool", "Garden / pool service", "Low", "landlord"),
    (r"inverter|solar|battery|load ?shedding", "Backup power", "Solar / inverter installer", "Medium", "landlord"),
]
TENANT_FAULT = r"(i|we|my (son|daughter|kids?|dog)) (broke|dropped|damaged|lost|spilled)|by accident|accidentally|my fault"
NEG = r"(unacceptable|disgusting|angry|furious|still not|again|third time|nobody|no one|ignored|terrible|worst|lawyer|tribunal|ridiculous|fed up|useless|frustrat)"


def triage(title, description=""):
    text = f"{title} {description}".lower()
    out = {"category": "General", "trade": "Handyman", "priority": "Medium", "responsible": "landlord", "why": []}
    for pat, cat, trade, pri, resp in TRIAGE:
        if re.search(pat, text):
            out.update(category=cat, trade=trade, priority=pri, responsible=resp)
            out["why"].append(f"matched '{re.search(pat, text).group(0)}' → {cat}, {pri}")
            break
    if re.search(TENANT_FAULT, text):
        out["responsible"] = "tenant"
        out["why"].append("wording suggests tenant damage → tenant may be liable")
    out["sentiment"] = sentiment(text)
    if out["sentiment"] == "negative" and out["priority"] in ("Low", "Medium"):
        out["priority"] = "High"
        out["why"].append("frustrated tenant → raised to High")
    out["emergency"] = out["priority"] == "Urgent"
    out["advice"] = SAFETY.get(out["category"]) if out["emergency"] else None
    return out


SAFETY = {
    "Plumbing": "Close the main water stopcock (usually at the meter or where the pipe enters the house) and switch off the geyser at the DB board.",
    "Gas": "Do not switch anything on or off. Close the gas cylinder valve, open windows and leave the property. Call 10177 if you feel unwell.",
    "Electrical": "Switch off the main switch at the DB board if it is safe. Do not touch exposed wires or wet sockets.",
}


def sentiment(text):
    t = (text or "").lower()
    if re.search(NEG, t) or t.count("!") >= 3:
        return "negative"
    if re.search(r"thank|great|appreciate|awesome|perfect|happy", t):
        return "positive"
    return "neutral"


def best_contractors(trade, city=None, n=3, lat=None, lng=None):
    """Companies to ask for quotes: within the quote radius of the property (marketplace rules)."""
    from . import marketplace
    if lat is not None:
        return marketplace.nearby(trade, lat, lng, n)
    rows = marketplace.nearby(trade, -26.2, 28.0, n, radius=20000)   # no coordinates: best-rated anywhere
    return [r for r in rows if not city or city in (r.get("areas") or [])][:n] or rows


def rank_quotes(quotes):
    """Lowest price and best rating win. 60% price, 40% rating; slow ETAs cost a little."""
    qs = [q for q in quotes if q.get("amount")]
    if not qs:
        return []
    lo = min(q["amount"] for q in qs)
    for q in qs:
        rating = q.get("rating") or 3.5
        q["rank_score"] = round(55 * lo / q["amount"] + 35 * rating / 5 + 10 * max(0, 1 - (q.get("distance_km") or 0) / 10)
                                - min(10, (q.get("eta_days") or 0)), 1)
    return sorted(qs, key=lambda q: -q["rank_score"])


# ---------------------------------------------------------------- tenant scoring
def score_application(a, rent):
    notes, s = [], 0
    income = (a.get("income") or 0) + (a.get("other_income") or 0)
    ratio = rent / income if income else 9
    # affordability (max 40): 40 at 20% of income or less, sliding to 0 at 53%
    aff = max(0.0, min(40.0, 40 - (ratio - 0.20) * 120))
    s += aff
    if ratio <= 0.30:
        notes.append(f"Affordability strong: rent is {ratio:.0%} of income")
    elif ratio <= 0.35:
        notes.append(f"Affordability OK: rent is {ratio:.0%} of income")
    elif ratio <= 0.40:
        notes.append(f"Affordability stretched: rent is {ratio:.0%} of income")
    else:
        notes.append(f"Affordability risk: rent is {ratio:.0%} of income (guide is ≤ 33%)")
    cs = a.get("credit_score")
    if cs:
        # credit (max 30): 0 at 550, 30 at 760+
        s += max(0.0, min(30.0, (cs - 550) / 7)); notes.append(f"Credit score {cs}")
    else:
        notes.append("No credit check yet")
    docs = a.get("docs") or []
    need = {"id", "payslips", "bank_statements"}
    have = {d.get("kind") for d in docs if isinstance(d, dict)}
    s += round(20 * len(need & have) / len(need))
    if not need <= have:
        notes.append("Missing documents: " + ", ".join(sorted(need - have)))
    rh = (a.get("rental_history") or "").lower()
    if "good" in rh or "paid on time" in rh:
        s += 10; notes.append("Positive rental history")
    elif "arrears" in rh or "evict" in rh:
        s -= 15; notes.append("Adverse rental history")
    return int(round(max(0, min(100, s)))), notes


# ---------------------------------------------------------------- pricing + copy
def comparable_rent(prop):
    rows = db.q("SELECT rent, bedrooms, size_m2 FROM properties WHERE id!=? AND rent>0 AND kind='rental' AND (suburb=? OR city=?)",
                prop.get("id") or 0, prop.get("suburb"), prop.get("city"))
    same = [r["rent"] for r in rows if abs((r["bedrooms"] or 0) - (prop.get("bedrooms") or 0)) < 0.6]
    per_m2 = [r["rent"] / r["size_m2"] for r in rows if r["size_m2"]]
    est = None
    basis = []
    if same:
        est = statistics.median(same); basis.append(f"{len(same)} comparable {int(prop.get('bedrooms') or 0)}-bed listings nearby, median R{est:,.0f}")
    if per_m2 and prop.get("size_m2"):
        e2 = statistics.median(per_m2) * prop["size_m2"]
        basis.append(f"R{statistics.median(per_m2):,.0f}/m² × {prop['size_m2']:.0f} m² = R{e2:,.0f}")
        est = (est + e2) / 2 if est else e2
    if est is None:
        return None
    est = round(est / 50) * 50
    return {"estimate": est, "low": round(est * 0.93 / 50) * 50, "high": round(est * 1.07 / 50) * 50, "basis": basis}


def listing_copy(p):
    feats = p.get("features") or []
    if isinstance(feats, str):
        feats = json.loads(feats or "[]")
    beds = int(p.get("bedrooms") or 0)
    baths = p.get("bathrooms") or 0
    t = (p.get("type") or "home").lower()
    head = f"{beds}-bedroom {t} in {p.get('suburb') or p.get('city') or 'a sought-after area'}"
    if "Solar / inverter" in feats or "Backup power" in feats:
        head += " with backup power"
    elif "Pool" in feats:
        head += " with pool"
    elif "Garden" in feats:
        head += " with garden"
    bits = [f"This {beds}-bedroom, {baths:g}-bathroom {t} in {p.get('suburb')}, {p.get('city')}"]
    if p.get("size_m2"):
        bits[0] += f" offers {p['size_m2']:.0f} m² of living space"
    bits[0] += "."
    if feats:
        bits.append("Highlights: " + ", ".join(feats[:-1]).lower() + (" and " if len(feats) > 1 else "") + feats[-1].lower() + ".")
    if p.get("parking"):
        bits.append(f"{p['parking']} parking bay{'s' if p['parking'] > 1 else ''}.")
    bits.append("Pets considered on application." if p.get("pets") else "Sorry, no pets.")
    if p.get("available_from"):
        bits.append(f"Available from {p['available_from']}.")
    bits.append("View it in 360° from home, book a viewing in a few taps and apply online - AVA handles the vetting, lease, "
                "deposit and inspections so nothing gets missed.")
    out = {"headline": head[0].upper() + head[1:], "description": " ".join(bits)}
    llm = ask_llm(f"Write a warm, factual South African rental listing (max 90 words, no exaggeration) for: {json.dumps({k: p.get(k) for k in ('type','bedrooms','bathrooms','size_m2','suburb','city','features','pets','furnished','parking','rent')})}. "
                  "Return JSON {\"headline\":..., \"description\":...}", json_out=True)
    if isinstance(llm, dict) and llm.get("description"):
        out = llm
    return out


# ---------------------------------------------------------------- risk
def renewal_risk(lease_id):
    l = db.q1("SELECT * FROM leases WHERE id=?", lease_id)
    if not l:
        return None
    late = db.val("SELECT COUNT(*) FROM tasks WHERE kind='arrears' AND dedupe LIKE ?", f"arrears:{lease_id}:%") or 0
    tickets = db.q("SELECT sentiment, status, created_at, completed_at FROM tickets WHERE lease_id=?", lease_id)
    neg = sum(1 for t in tickets if t["sentiment"] == "negative")
    slow = sum(1 for t in tickets if t["completed_at"] and (datetime.fromisoformat(t["completed_at"][:19]) - datetime.fromisoformat(t["created_at"][:19])).days > 10)
    open_ = sum(1 for t in tickets if t["status"] not in ("completed", "closed", "cancelled"))
    score = min(100, 15 + late * 15 + neg * 15 + slow * 10 + open_ * 8)
    reasons = []
    if late: reasons.append(f"{late} late payment month(s)")
    if neg: reasons.append(f"{neg} frustrated maintenance request(s)")
    if slow: reasons.append(f"{slow} slow repair(s)")
    if open_: reasons.append(f"{open_} open request(s)")
    action = ("Offer renewal at CPI-linked escalation and fix open requests first" if score >= 50
              else "Send standard renewal offer 60 days before end")
    return {"score": score, "level": "high" if score >= 60 else "medium" if score >= 35 else "low", "reasons": reasons or ["Clean history"], "action": action}


def ledger_anomalies(pids):
    from .auth import in_list
    out = []
    dup = db.q(f"""SELECT lease_id, amount, date, COUNT(*) n FROM ledger WHERE account='tenant' AND kind='payment'
                  AND property_id IN {in_list(pids)} GROUP BY lease_id, amount, date HAVING n>1""")
    for d in dup:
        out.append({"kind": "duplicate", "text": f"Possible duplicate payment R{-d['amount']:,.0f} on {d['date']} (lease #{d['lease_id']})"})
    costs = db.q(f"SELECT id, ref, category, cost FROM tickets WHERE cost>0 AND property_id IN {in_list(pids)}")
    by = {}
    for c in costs:
        by.setdefault(c["category"], []).append(c["cost"])
    for c in costs:
        arr = by[c["category"]]
        if len(arr) >= 3 and c["cost"] > 2.5 * statistics.median(arr):
            out.append({"kind": "cost", "text": f"{c['ref']} cost R{c['cost']:,.0f} is {c['cost']/statistics.median(arr):.1f}× the usual {c['category']} job"})
    return out


# ---------------------------------------------------------------- assistant
LEARN = [
    ("deposit", "Under the Rental Housing Act the deposit must be kept in an interest-bearing account. At the end of the lease it is refunded with interest, less only the cost of damage found in the outgoing inspection, within 7 days if there is no damage, 14 days after repairs if there is, or 21 days if the tenant did not attend the outgoing inspection."),
    ("inspection", "A joint ingoing inspection is required before you move in, and a joint outgoing inspection within 3 days before you move out. AVA records each room in 360° and photos so the two can be compared fairly."),
    ("notice|cancel|terminate|break", "Under the Consumer Protection Act a tenant on a fixed-term lease may cancel with 20 business days' written notice; a reasonable cancellation penalty may apply. Give notice in writing through the app so it is dated."),
    ("escalat|increase", "Rent may only increase as the lease allows (usually once a year on the anniversary). AVA shows the escalation percentage and date on your lease."),
    ("evict", "Only a court can order an eviction (PIE Act). Locks may not be changed and services may not be cut off to force a tenant out."),
    ("pet", "Pets need the landlord's written consent. Ask through Messages and AVA will add a pet addendum to the lease."),
]


def assistant(u, text):
    """Answer a tenant's question from their own data. Returns {reply, actions}."""
    t = text.lower().strip()
    lease = db.q1("SELECT l.*, p.title, p.address FROM leases l JOIN properties p ON p.id=l.property_id WHERE l.tenant_id=? "
                  "ORDER BY (l.status='active') DESC, l.id DESC LIMIT 1", u["id"]) if u["role"] == "tenant" else None
    facts = {}
    if lease:
        bal = db.val("SELECT COALESCE(SUM(amount),0) FROM ledger WHERE lease_id=? AND account='tenant'", lease["id"]) or 0
        nxt = next_due(lease)
        facts = {"property": lease["title"], "rent": lease["rent"], "balance": round(bal, 2), "next_due": nxt,
                 "lease_end": lease["end_date"], "lease_status": lease["status"], "escalation_pct": lease["escalation_pct"],
                 "open_requests": [dict(ref=r["ref"], title=r["title"], status=r["status"]) for r in
                                   db.q("SELECT ref,title,status FROM tickets WHERE lease_id=? AND status NOT IN ('closed','cancelled') ORDER BY id DESC", lease["id"])]}
    actions = []
    reply = None
    if re.search(r"\b(balance|owe|arrears|outstanding|how much)\b", t) and lease:
        b = facts["balance"]
        reply = (f"Your account is up to date (balance R{-b:,.0f} in credit)." if b < 0 else
                 "Your account is up to date." if b == 0 else f"You owe R{b:,.0f}. Next rent of R{facts['rent']:,} is due on {facts['next_due']}.")
        if b > 0:
            actions.append({"label": "Pay now", "href": "#/app/pay"})
    elif re.search(r"\b(pay|payment|eft|bank|reference|debit order)\b", t) and lease:
        reply = (f"Pay by card or Instant EFT in the app, or by EFT to {fees.S('trust_bank')} with reference AVA{lease['id']:05d}. "
                 "Payments are matched automatically and you get a receipt.")
        actions.append({"label": "Pay now", "href": "#/app/pay"})
    elif re.search(r"\b(status|update|when will|request|ticket|repair|fix)\b", t) and lease and not facts.get("open_requests") and not re.search(r"broke|leak|not working|burst|blocked", t):
        last = db.q1("SELECT ref, title, status, completed_at FROM tickets WHERE lease_id=? ORDER BY id DESC LIMIT 1", lease["id"])
        reply = ("You have no open repair requests." + (f" Your last one, {last['ref']} {last['title']}, is {STATUS_WORDS.get(last['status'], last['status'])}." if last else "")
                 + " Describe anything that's broken and I'll log it straight away.")
        actions.append({"label": "Report a problem", "href": "#/app/maintenance/new"})
    elif re.search(r"\b(status|update|when will|request|ticket|repair|fix)\b", t) and facts.get("open_requests"):
        r = facts["open_requests"][0]
        reply = "Your open requests: " + "; ".join(f"{x['ref']} {x['title']} – {STATUS_WORDS.get(x['status'], x['status'])}" for x in facts["open_requests"][:4]) + "."
        actions.append({"label": "View requests", "href": "#/app/maintenance"})
    elif re.search(r"\b(lease|contract|end|expire|renew)\b", t) and lease:
        reply = f"Your lease for {facts['property']} runs until {facts['lease_end']}. Rent escalates {facts['escalation_pct']:g}% on each anniversary. AVA will send a renewal offer 60 days before it ends."
        actions.append({"label": "Open lease", "href": "#/app/lease"})
    else:
        tri = triage(text)
        if tri["category"] != "General" and len(t) > 8:
            reply = f"That sounds like a {tri['category'].lower()} problem ({tri['priority'].lower()} priority). I can log it now and send it to a {tri['trade'].lower()}."
            if tri.get("advice"):
                reply += " In the meantime: " + tri["advice"]
            actions.append({"label": "Log this request", "action": "ticket", "title": text[:80]})
        else:
            for pat, ans in LEARN:
                if re.search(pat, t):
                    reply = ans
                    break
    llm = ask_llm(
        "You are AVA Assist, the in-app helper of AVA, a South African rental platform. Be brief (max 80 words), friendly, factual. "
        "Use only these account facts: " + json.dumps(facts) + ". If they report a fault, say you will log it. "
        "Draft from rules (may be empty): " + json.dumps(reply) + "\nTenant: " + text)
    if isinstance(llm, str) and llm.strip():
        reply = llm.strip()
    if not reply:
        reply = ("I can help with your balance and payments, your lease, repair requests and your rights as a tenant. "
                 "Your portfolio manager has also been sent your message.")
    return {"reply": reply, "actions": actions, "facts": facts}


STATUS_WORDS = {"new": "received", "quoting": "getting quotes", "awaiting_approval": "waiting for landlord approval",
                "approved": "approved, contractor booking", "scheduled": "contractor booked", "in_progress": "being fixed",
                "completed": "done – please confirm", "info_needed": "we need more info from you"}


def next_due(lease):
    d = date.today()
    day = min(lease.get("due_day") or 1, 28)
    due = d.replace(day=day)
    if due < d:
        due = (due.replace(day=1) + timedelta(days=32)).replace(day=day)
    return due.isoformat()


def suggest_reply(thread_msgs, facts=None):
    last = next((m for m in reversed(thread_msgs) if not m.get("mine")), None)
    if not last:
        return ""
    s = sentiment(last["body"])
    tri = triage(last["body"])
    if s == "negative":
        return "I'm sorry this has been frustrating. I've escalated it and will update you by end of day with a confirmed date."
    if tri["category"] != "General":
        return f"Thanks for letting us know. I've logged this as a {tri['category'].lower()} request and a contractor will contact you to arrange access."
    return "Thanks for your message - I'll look into it and get back to you shortly."


# ---------------------------------------------------------------- optional LLM
def ask_llm(prompt, json_out=False):
    if fees.S("ai_provider") != "anthropic" or not fees.S("anthropic_api_key"):
        return None
    try:
        import httpx
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=20,
                       headers={"x-api-key": fees.S("anthropic_api_key"), "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": fees.S("anthropic_model"), "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        txt = "".join(b.get("text", "") for b in r.json().get("content", []))
        if json_out:
            m = re.search(r"\{.*\}", txt, re.S)
            return json.loads(m.group(0)) if m else None
        return txt
    except Exception:
        return None
