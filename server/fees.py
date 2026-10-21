"""AVA fee model, taken from AVA_Pricing_20240827.xlsx. Every number is a setting the admin can change."""
from . import db

DEFAULTS = {
    "vat_pct": 15,
    "vat_registered": False,            # 'VAT?' is still open in the pricing sheet
    # tenant once-off
    "vetting_fee": 450,                 # 'TBD' in the sheet - placeholder
    "deposit_months": 1.0,              # 100% of monthly rental
    "key_deposit": 500,
    # inspection: R500 for <= 2 bed + 1 bath, + R125 per extra bedroom/room; split 50/50 landlord/tenant
    "inspection_base": 500,
    "inspection_extra_room": 125,
    "inspection_tenant_share": 0.5,
    # landlord
    "admin_fee": 500,                   # once-off per new contract, not on renewals
    "ava_tiers": [[5, 399], [20, 349], [50, 299], [999999, 249]],   # homes the landlord has on AVA -> platform fee R/month per let home
    "insurance_monthly": 250,           # Expello / TenRisk
    "own_admin_monthly": 50,
    # portfolio manager
    "pm_commission_mode": "tiered",     # 'tiered' (option 1) or 'chosen' (option 2: PM picks 3-5%)
    "pm_tiers": [[20, 3.0], [50, 4.0], [999999, 5.0]],
    "finders_fee": 50,
    # what a traditional rental agent charges for full management (for the savings comparison)
    "agent_fee_pct": 10.0,              # % of rent, plus VAT                  # per successfully rented listing per month, from rent
    # trust / deposit
    "deposit_interest_pct": 5.0,        # interest-bearing account, Rental Housing Act s5(3)(c)
    "payout_day": 7,
    # maintenance automation
    "quote_window_hours": 48,
    "quotes_to_request": 3,
    "auto_approve_limit": 1500,         # emergencies under this are dispatched without waiting for the landlord
    "shortlist_size": 3,
    # maintenance marketplace
    "contractor_listing_fee": 250,      # R/month for a maintenance company to receive requests
    "quote_radius_km": 10,              # only companies within this distance of the property get the request
    "owner_chooses_quote": True,
    "widen_steps_km": [15, 25, 50, 100],
    "max_quotes_per_job": 5,            # the 3 invited companies + up to 2 that apply from the job map  # choices offered when nobody is listed within the radius
    "auto_widen_km": 0,                 # >0: AVA widens by itself up to this distance when nobody is in range        # the owner (not the PM) picks the winning quote
    "free_trial_days": 30,
    "auto_close_hours": 72,             # a finished job (with photo proof) closes itself if the tenant doesn't object
    "contractor_pay_days": 2,           # trust pays the company this many days after the job is confirmed
    # snag lists
    "snag_due_days": {"Urgent": 2, "High": 7, "Medium": 14, "Low": 21},
    # AI
    "ai_provider": "rules",             # 'rules' or 'anthropic'
    "anthropic_api_key": "",
    "anthropic_model": "claude-sonnet-5-5",
    # payments
    "payfast_merchant_id": "",
    "payfast_merchant_key": "",
    "payfast_passphrase": "",
    "payfast_sandbox": True,
    "public_url": "",
    "trust_bank": "FNB Trust Account 62xxxxxxx · Branch 250655",
}


OLD_DEFAULTS = {"ava_tiers": [[[5, 299], [20, 249], [999999, 199]]]}   # superseded price lists: never let an untouched old copy win


def S(key):
    v = db.get_setting(key)
    if v is None or v in OLD_DEFAULTS.get(key, []):
        return DEFAULTS.get(key)
    return v


def all_settings():
    return {k: S(k) for k in DEFAULTS}


def tier(n, tiers):
    for upto, v in tiers:
        if n <= upto:
            return v
    return tiers[-1][1]


def inspection_fee(bedrooms, bathrooms):
    extra = max(0, int(round(bedrooms or 0)) - 2) + max(0, int(round(bathrooms or 0)) - 1)
    return S("inspection_base") + S("inspection_extra_room") * extra


def landlord_rented_count(landlord_id):
    return db.val("SELECT COUNT(DISTINCT l.property_id) FROM leases l JOIN properties p ON p.id=l.property_id "
                  "WHERE p.landlord_id=? AND l.status='active'", landlord_id) or 0


def pm_managed_count(pm_id):
    return db.val("SELECT COUNT(*) FROM properties WHERE pm_id=? AND kind='rental'", pm_id) or 0


def landlord_managed_count(landlord_id):
    """Homes the landlord has under AVA management (let or vacant; drafts and new-build projects don't count)."""
    return db.val("SELECT COUNT(*) FROM properties WHERE landlord_id=? AND kind='rental' AND listing_status!='draft'", landlord_id) or 0


def ava_monthly(landlord_id):
    """Sliding scale: the more homes a landlord manages on AVA, the lower the platform fee per home."""
    return tier(max(1, landlord_managed_count(landlord_id)), S("ava_tiers"))


def pm_commission_pct(pm_id):
    if not pm_id:
        return 0.0
    if S("pm_commission_mode") == "chosen":
        v = db.val("SELECT commission_pct FROM users WHERE id=?", pm_id)
        return float(v if v is not None else 4.0)
    return float(tier(pm_managed_count(pm_id), S("pm_tiers")))


def move_in_costs(rent, bedrooms, bathrooms):
    insp = inspection_fee(bedrooms, bathrooms)
    tshare = db.rands(insp * S("inspection_tenant_share"))
    lines = [
        ("First month's rent (pro rata if you move in mid-month)", rent),
        ("Deposit", round(rent * S("deposit_months"))),
        ("Key deposit", S("key_deposit")),
        ("Ingoing/outgoing inspection (tenant 50%)", tshare),
        ("Application vetting", S("vetting_fee")),
    ]
    return {"lines": [{"label": a, "amount": b} for a, b in lines], "total": sum(b for _, b in lines)}


def landlord_monthly(rent, landlord_id=None, pm_id=None, insured=True, n_rented=None):
    n = n_rented if n_rented is not None else (landlord_managed_count(landlord_id) if landlord_id else 1)
    ava = tier(max(1, n), S("ava_tiers"))
    pct = pm_commission_pct(pm_id) if pm_id else 3.0
    lines = [("AVA platform", ava), ("PM commission (%.1f%%)" % pct, db.rands(rent * pct / 100))]
    if insured:
        lines.append(("Rental insurance", S("insurance_monthly")))
    cost = sum(b for _, b in lines)
    return {"lines": [{"label": a, "amount": b} for a, b in lines], "total": cost, "net": rent - cost,
            "pct_of_rent": round(cost / rent * 100, 1) if rent else 0}


def agent_fee(rent):
    """Traditional SA rental agent: ~10% of rent + 15% VAT for full management."""
    return db.rands(rent * S("agent_fee_pct") * (100 + S("vat_pct")) / 10000)


def agent_comparison(rent, homes=1):
    """Like for like, per home: management cost with AVA (platform fee + PM commission) vs a traditional agent. Insurance is optional cover."""
    ava = landlord_monthly(rent, n_rented=max(1, homes), insured=False)
    trad = agent_fee(rent)
    return {"traditional_monthly": trad, "ava_monthly": ava["total"], "saving_month": trad - ava["total"],
            "saving_year": (trad - ava["total"]) * 12, "agent_pct": S("agent_fee_pct")}


def landlord_savings(landlord_id):
    """Per let home: what a traditional agent would charge vs what AVA costs, per month and per year."""
    rows = db.q("""SELECT p.id, p.title, p.pm_id, l.rent FROM properties p JOIN leases l ON l.property_id=p.id AND l.status='active'
                   WHERE p.landlord_id=? ORDER BY p.title""", landlord_id)
    ava_fee = ava_monthly(landlord_id)
    out = []
    for r in rows:
        agent = agent_fee(r["rent"])
        com = db.rands(r["rent"] * pm_commission_pct(r["pm_id"]) / 100)
        ava = ava_fee + com
        out.append({"id": r["id"], "title": r["title"], "rent": r["rent"], "agent": agent, "ava": ava, "ava_fee": ava_fee, "commission": com,
                    "pct": pm_commission_pct(r["pm_id"]), "saving_month": agent - ava, "saving_year": (agent - ava) * 12})
    m = sum(x["saving_month"] for x in out)
    # what has actually been saved over the last 12 months, from the statements
    paid = db.q1("""SELECT COALESCE(SUM(CASE WHEN g.kind='rent_received' THEN g.amount END),0) rent_in,
                    -COALESCE(SUM(CASE WHEN g.kind IN ('ava_fee','pm_commission') THEN g.amount END),0) fees
                    FROM ledger g JOIN properties p ON p.id=g.property_id WHERE p.landlord_id=? AND g.account='owner'
                    AND g.period >= strftime('%Y-%m', date('now','-12 month')) AND g.period IN
                    (SELECT period FROM ledger x WHERE x.property_id=g.property_id AND x.kind='payout')""", landlord_id)
    so_far = agent_fee(paid["rent_in"]) - db.rands(paid["fees"]) if paid["rent_in"] else 0
    return {"rows": out, "month": m, "year": m * 12, "agent_month": sum(x["agent"] for x in out), "ava_month": sum(x["ava"] for x in out),
            "saved_12m": so_far, "agent_pct": S("agent_fee_pct"), "vat_pct": S("vat_pct")}
