"""Trust accounting – the agency's real bank accounts behind AVA's ledger.

Three cashbooks:
  trust    – rent and other client money (Property Practitioners Act s54: a separate trust account)
  deposit  – tenants' deposits, each in its own interest-bearing investment (Rental Housing Act s5(3))
  business – the agency's own money: fees moved out of trust, contractor listing fees

The ledger says who owes whom; the cashbooks say what actually went through the bank.
* Receipts, deposit transfers, interest and refunds are mirrored from the ledger automatically (sync).
* Money only leaves trust through a payment batch: draft → authorised → released (with a bank file).
* Bank feeds (or OFX/CSV statements) bring in bank lines; AVA matches them to the cashbook and
  allocates rent it recognises by reference. Each month is reconciled, then locked.
* The trust trial balance proves trust cash = money owed to owners + fees and payables not yet paid out.
* Journals correct mistakes in open months only; the financial year is closed with a snapshot.
* Debit orders (DebiCheck through Netcash) collect rent; deposits sit in per-tenant investment accounts.
"""
import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from . import db, fees

BOOKS = {"trust": "Trust account", "deposit": "Deposit trust (investments)", "business": "Business account"}
# money held in trust that belongs to someone other than an owner, until a batch pays it out
CONTROLS = {
    "ava_fees": "AVA fees (to business account)",
    "pm_commission": "Portfolio manager commission (to business account)",
    "insurance": "Rental insurance (to insurer)",
    "contractors": "Contractors for repairs",
    "suspense": "Unidentified receipts (suspense)",
}
OWNER_KINDS = {"ava_fees": ("ava_fee", "admin_fee", "inspection_fee"), "pm_commission": ("pm_commission",),
               "insurance": ("insurance",), "contractors": ("maintenance",)}
TO_BUSINESS = ("ava_fees", "pm_commission")
BANKS = {"ABSA": "632005", "African Bank": "430000", "Capitec": "470010", "Discovery Bank": "679000", "FNB": "250655",
         "Investec": "580105", "Nedbank": "198765", "Standard Bank": "051001", "TymeBank": "678910"}
ACCOUNT_TYPES = {"cheque": "1", "savings": "2", "transmission": "3"}


# ------------------------------------------------------------------ cashbooks
def ensure_books(opening_date=None):
    for code, name in BOOKS.items():
        if not db.val("SELECT 1 FROM cashbooks WHERE code=?", code):
            acc = {"trust": ("FNB", "250655", "62845123001"), "deposit": ("FNB 3PIM", "250655", "62845123019"),
                   "business": ("FNB", "250655", "62845123027")}[code]
            db.ins("cashbooks", code=code, name=name, bank=acc[0], branch_code=acc[1], account_no=acc[2],
                   opening_balance=0, opening_date=opening_date or date.today().replace(day=1).isoformat(), feed="simulated")


def book(code):
    b = db.q1("SELECT * FROM cashbooks WHERE code=?", code)
    if not b:
        raise HTTPException(404, "Unknown cashbook")
    return b


def cash(code, upto=None):
    b = book(code)
    s = db.val("SELECT COALESCE(SUM(amount),0) FROM cashbook_tx WHERE cashbook=?" + (" AND date<=?" if upto else ""), code, *([upto] if upto else []))
    return db.rands((b["opening_balance"] or 0) + (s or 0))


def add_tx(code, d, amount, description, reference="", source="system", **kw):
    check_open(d)
    return db.ins("cashbook_tx", cashbook=code, date=d, amount=db.rands(amount), description=description,
                  reference=reference, source=source, **kw)


# ------------------------------------------------------------------ periods (locking)
def locked(per):
    return bool(db.val("SELECT 1 FROM periods WHERE period=? AND locked_at IS NOT NULL", per))


def check_open(d):
    if d and locked(str(d)[:7]):
        raise HTTPException(400, f"{db.month_name(str(d)[:7])} is locked. Post a correcting journal in an open month instead.")


def lock_period(per, u=None, force=False):
    if not force:
        for code in ("trust", "deposit"):
            if has_activity(code, per) and not db.val("SELECT 1 FROM recons WHERE cashbook=? AND period=?", code, per):
                raise HTTPException(400, f"Reconcile the {BOOKS[code].lower()} for {db.month_name(per)} before locking it.")
    db.exe("INSERT INTO periods (period, locked_at, locked_by) VALUES (?,?,?) ON CONFLICT(period) DO UPDATE SET locked_at=excluded.locked_at, locked_by=excluded.locked_by",
           per, db.now(), u["id"] if u else None)


def unlock_period(per, u):
    if db.val("SELECT 1 FROM year_ends WHERE ? BETWEEN start_period AND end_period", per):
        raise HTTPException(400, "That month belongs to a closed financial year.")
    db.exe("UPDATE periods SET locked_at=NULL WHERE period=?", per)


def has_activity(code, per):
    return bool(db.val("SELECT 1 FROM cashbook_tx WHERE cashbook=? AND substr(date,1,7)=?", code, per)
                or db.val("SELECT 1 FROM bank_lines WHERE cashbook=? AND substr(date,1,7)=?", code, per))


# ------------------------------------------------------------------ mirror the ledger into the cashbooks
def sync():
    """Create the bank movements that follow from ledger events (idempotent)."""
    n = 0
    have = {(r["ledger_id"], r["cashbook"]) for r in db.q("SELECT ledger_id, cashbook FROM cashbook_tx WHERE ledger_id IS NOT NULL")}

    def put(code, l, amount, desc, ref=""):
        nonlocal n
        if (l["id"], code) in have:
            return
        db.ins("cashbook_tx", cashbook=code, date=l["date"], amount=db.rands(amount), description=desc, reference=ref or l["ref"] or "",
               source="ledger", ledger_id=l["id"], payment_id=l["payment_id"], property_id=l["property_id"], lease_id=l["lease_id"])
        have.add((l["id"], code))
        n += 1

    rows = db.q("""SELECT g.*, p.method FROM ledger g LEFT JOIN payments p ON p.id=g.payment_id
                   WHERE (g.account='tenant' AND g.kind='payment' AND COALESCE(g.ref,'')!='from-deposit')
                      OR (g.account='deposit' AND g.kind IN ('deposit_received','deposit_interest','deposit_deduction','deposit_refund'))
                      OR (g.account='ava' AND g.kind='listing_fee')
                   ORDER BY g.id""")
    for l in rows:
        a = abs(l["amount"])
        if l["account"] == "tenant":
            if l["method"] == "suspense":     # already in trust as an unidentified receipt
                continue
            put("trust", l, a, f"Receipt {l['ref'] or ''} – {l['description']}".strip())
        elif l["kind"] == "deposit_received":
            put("trust", l, -a, "Deposit moved to the deposit investment account")
            put("deposit", l, a, "Deposit received from trust account")
            open_deposit_account(l["lease_id"], l["date"])
        elif l["kind"] == "deposit_interest":
            put("deposit", l, a, l["description"] or "Interest on deposit")
        elif l["kind"] == "deposit_deduction":
            put("deposit", l, -a, l["description"])
            put("trust", l, a, "From deposit: " + (l["description"] or "deduction"))
        elif l["kind"] == "deposit_refund":
            put("deposit", l, -a, "Deposit refunded to tenant")
            close_deposit_account(l["lease_id"], l["date"])
        elif l["kind"] == "listing_fee":
            put("business", l, a, l["description"] or "Maintenance listing fee")
    return n


# ------------------------------------------------------------------ what trust money belongs to
def accrued(control, upto=None):
    w, a = ("AND date<=?", [upto]) if upto else ("", [])
    v = db.val(f"SELECT COALESCE(SUM(amount),0) FROM ledger WHERE account='control' AND kind=? {w}", control, *a) or 0
    if control in OWNER_KINDS:
        k = OWNER_KINDS[control]
        v += -(db.val(f"SELECT COALESCE(SUM(amount),0) FROM ledger WHERE account='owner' AND kind IN ({','.join('?' * len(k))}) {w}", *k, *a) or 0)
    if control == "ava_fees":
        v += db.val(f"SELECT COALESCE(SUM(amount),0) FROM ledger WHERE account='ava' AND kind='tenant_fee_received' {w}", *a) or 0
    return db.rands(v)


def paid_out(control, upto=None):
    w, a = ("AND substr(b.released_at,1,10)<=?", [upto]) if upto else ("", [])
    return db.rands(db.val(f"""SELECT COALESCE(SUM(l.amount),0) FROM batch_lines l JOIN batches b ON b.id=l.batch_id
                               WHERE b.status='released' AND l.control=? {w}""", control, *a) or 0)


def payouts_pending(upto=None):
    """Owner payouts already on the statements but still sitting in the trust account (batch not released)."""
    w, a = ("AND g.date<=?", [upto]) if upto else ("", [])
    rel = ("AND substr(b.released_at,1,10)<=?", [upto]) if upto else ("", [])
    return db.rands(-(db.val(f"""SELECT COALESCE(SUM(g.amount),0) FROM ledger g WHERE g.account='owner' AND g.kind='payout' {w}
                                AND NOT EXISTS (SELECT 1 FROM batch_lines l JOIN batches b ON b.id=l.batch_id
                                                WHERE l.ledger_id=g.id AND b.status='released' {rel[0]})""", *a, *rel[1]) or 0))


def trial_balance(upto=None):
    upto = upto or date.today().isoformat()
    w, a = ("AND date<=?", [upto])
    owners = db.rands(db.val(f"SELECT COALESCE(SUM(amount),0) FROM ledger WHERE account='owner' {w}", *a) or 0)
    pend = payouts_pending(upto)
    ctl = {c: db.rands(accrued(c, upto) - paid_out(c, upto)) for c in CONTROLS}
    lines = [{"label": "Owners – rent held for owners", "amount": owners}, {"label": "Owner payouts awaiting release", "amount": pend}] + \
            [{"label": CONTROLS[c], "amount": v, "control": c} for c, v in ctl.items() if v]
    liab = db.rands(owners + pend + sum(ctl.values()))
    tcash = cash("trust", upto)
    dep_liab = db.rands(db.val(f"SELECT COALESCE(SUM(amount),0) FROM ledger WHERE account='deposit' {w}", *a) or 0)
    dcash = cash("deposit", upto)
    prepaid = db.rands(-(db.val(f"""SELECT COALESCE(SUM(b),0) FROM (SELECT SUM(amount) b FROM ledger WHERE account='tenant' {w}
                                  GROUP BY lease_id HAVING b<0)""", *a) or 0))
    return {"as_at": upto,
            "trust": {"cash": tcash, "liabilities": liab, "lines": lines, "difference": db.rands(tcash - liab),
                      "balanced": abs(tcash - liab) < 1, "tenant_prepayments": prepaid},
            "deposit": {"cash": dcash, "liabilities": dep_liab, "difference": db.rands(dcash - dep_liab), "balanced": abs(dcash - dep_liab) < 1,
                        "accounts": db.val("SELECT COUNT(*) FROM deposit_accounts WHERE status='open'")},
            "business": {"cash": cash("business", upto)}}


# ------------------------------------------------------------------ bank details
def bank_of(user_id):
    return db.q1("SELECT * FROM bank_accounts WHERE user_id=?", user_id)


def set_bank(user_id, holder, bank, account_no, account_type="cheque", branch_code=None):
    account_no = re.sub(r"\D", "", account_no or "")
    if bank not in BANKS:
        raise HTTPException(400, "Choose the bank")
    if not 7 <= len(account_no) <= 13:
        raise HTTPException(400, "Enter a valid account number")
    data = dict(holder=holder, bank=bank, branch_code=branch_code or BANKS[bank], account_no=account_no,
                account_type=account_type if account_type in ACCOUNT_TYPES else "cheque", verified=0, updated_at=db.now())
    if bank_of(user_id):
        db.exe("UPDATE bank_accounts SET " + ",".join(f"{k}=?" for k in data) + " WHERE user_id=?", *data.values(), user_id)
    else:
        db.ins("bank_accounts", user_id=user_id, **data)


def masked(no):
    return ("•••• " + no[-4:]) if no else ""


# ------------------------------------------------------------------ payment batches
def _ref(kind):
    n = (db.val("SELECT COUNT(*) FROM batches") or 0) + 1
    return {"owner_payout": "PO", "fee_transfer": "FT", "contractor": "CP"}.get(kind, "PB") + f"-{n:05d}"


def _draft(kind, period, u=None):
    b = db.q1("SELECT * FROM batches WHERE kind=? AND status='draft' AND COALESCE(period,'')=?", kind, period or "")
    return b["id"] if b else db.ins("batches", ref=_ref(kind), kind=kind, period=period, created_by=u["id"] if u else None)


def _retotal(bid):
    db.exe("UPDATE batches SET total=(SELECT COALESCE(SUM(amount),0) FROM batch_lines WHERE batch_id=?) WHERE id=?", bid, bid)


def queue_owner_payouts(u=None):
    """Every owner payout on a statement goes into a payment batch for release from the trust account."""
    rows = db.q("""SELECT g.*, p.landlord_id, p.title FROM ledger g JOIN properties p ON p.id=g.property_id
                   WHERE g.account='owner' AND g.kind='payout' AND NOT EXISTS (SELECT 1 FROM batch_lines l WHERE l.ledger_id=g.id)
                   ORDER BY g.period, g.id""")
    made = set()
    from . import compliance, fees
    hold = fees.S("fica_hold_payouts")
    for g in rows:
        if hold and compliance.status(g["landlord_id"]) != "verified":
            from .services import task
            pm = db.val("SELECT pm_id FROM properties WHERE id=?", g["property_id"])
            task(pm, g["property_id"], "fica", f"Payout held: owner of {g['title']} is not FICA-verified",
                 "The owner must complete the identity check in the app before the payout can be released.", "#/app/compliance", 1, None, f"fica-hold:{g['landlord_id']}")
            continue
        bid = _draft("owner_payout", g["period"], u)
        ll = db.q1("SELECT id, name, company FROM users WHERE id=?", g["landlord_id"])
        ba = bank_of(g["landlord_id"]) or {}
        db.ins("batch_lines", batch_id=bid, payee=(ll["company"] or ll["name"]) if ll else "Owner", payee_user=g["landlord_id"], ledger_id=g["id"],
               property_id=g["property_id"], amount=-g["amount"], reference=f"AVA {g['period']} {g['title']}"[:30],
               bank=ba.get("bank"), branch_code=ba.get("branch_code"), account_no=ba.get("account_no"), account_type=ba.get("account_type"))
        made.add(bid)
    for bid in made:
        _retotal(bid)
    return list(made)


REF = {"ava_fees": "AVA fees", "pm_commission": "PM commission", "insurance": "Rental insurance"}


def create_fee_transfer(u=None, upto=None, ref_period=None):
    """Move fees earned out of trust (to the business account), pay the insurer and the contractors."""
    upto = upto or date.today().isoformat()
    bid = None
    biz = book("business")
    for c in ("ava_fees", "pm_commission", "insurance"):
        queued = db.val("""SELECT COALESCE(SUM(l.amount),0) FROM batch_lines l JOIN batches b ON b.id=l.batch_id
                           WHERE l.control=? AND b.status IN ('draft','authorised')""", c) or 0
        amt = db.rands(accrued(c, upto) - paid_out(c, upto) - queued)
        if amt <= 0:
            continue
        bid = bid or _draft("fee_transfer", ref_period or upto[:7], u)
        if c in TO_BUSINESS:
            payee, bank = "AVA business account", dict(bank=biz["bank"], branch_code=biz["branch_code"], account_no=biz["account_no"], account_type="cheque")
        else:
            payee, bank = "Expello rental insurance", dict(bank="Standard Bank", branch_code="051001", account_no="000000000", account_type="cheque")
        db.ins("batch_lines", batch_id=bid, payee=payee, control=c, amount=amt, reference=f"{REF[c]} {ref_period or upto[:7]}"[:30],
               note=CONTROLS[c], **bank)
    # contractors: one payment per repair, to the company that did it
    for g in db.q("""SELECT g.*, t.contractor_id, t.ref tref, u.company, u.name FROM ledger g LEFT JOIN tickets t ON t.id=g.ticket_id
                     LEFT JOIN users u ON u.id=t.contractor_id WHERE g.account='owner' AND g.kind='maintenance' AND g.date<=?
                     AND NOT EXISTS (SELECT 1 FROM batch_lines l WHERE l.ledger_id=g.id)""", upto):
        bid = bid or _draft("fee_transfer", upto[:7], u)
        ba = bank_of(g["contractor_id"]) or {} if g["contractor_id"] else {}
        db.ins("batch_lines", batch_id=bid, payee=g["company"] or g["name"] or "Contractor", payee_user=g["contractor_id"], control="contractors",
               ledger_id=g["id"], property_id=g["property_id"], amount=-g["amount"], reference=f"AVA {g['tref'] or 'repair'}"[:30],
               note=g["description"], bank=ba.get("bank"), branch_code=ba.get("branch_code"), account_no=ba.get("account_no"), account_type=ba.get("account_type"))
    if bid:
        _retotal(bid)
    return bid


def batch_full(bid):
    b = db.q1("SELECT * FROM batches WHERE id=?", bid)
    if not b:
        raise HTTPException(404, "Batch not found")
    b["lines"] = db.q("SELECT * FROM batch_lines WHERE batch_id=? ORDER BY id", bid)
    for l in b["lines"]:
        l["account_masked"] = masked(l["account_no"])
        l["missing_bank"] = not (l["account_no"] and l["branch_code"])
    b["missing_bank"] = sum(1 for l in b["lines"] if l["missing_bank"])
    for k in ("created_by", "authorised_by", "released_by"):
        b[k + "_name"] = db.val("SELECT name FROM users WHERE id=?", b[k]) if b[k] else None
    return b


def refresh_bank_details(bid):
    for l in db.q("SELECT * FROM batch_lines WHERE batch_id=? AND payee_user IS NOT NULL", bid):
        ba = bank_of(l["payee_user"])
        if ba:
            db.exe("UPDATE batch_lines SET bank=?, branch_code=?, account_no=?, account_type=? WHERE id=?",
                   ba["bank"], ba["branch_code"], ba["account_no"], ba["account_type"], l["id"])


def authorise(bid, u):
    b = batch_full(bid)
    if b["status"] != "draft":
        raise HTTPException(400, "Only a draft batch can be authorised")
    if fees.S("require_second_authoriser") and b["created_by"] == u["id"]:
        raise HTTPException(400, "A second person must authorise this batch (two-person rule)")
    refresh_bank_details(bid)
    db.upd("batches", bid, status="authorised", authorised_by=u["id"], authorised_at=db.now())
    return batch_full(bid)


def release(bid, u, d=None):
    b = batch_full(bid)
    if b["status"] != "authorised":
        raise HTTPException(400, "Authorise the batch first")
    refresh_bank_details(bid)
    b = batch_full(bid)
    if b["missing_bank"]:
        raise HTTPException(400, f"{b['missing_bank']} payee(s) have no bank details yet")
    d = d or db.today()
    for l in b["lines"]:
        db.ins("cashbook_tx", cashbook="trust", date=d, amount=-l["amount"], description=f"{b['ref']} {l['payee']}", reference=l["reference"],
               source="batch", batch_id=bid, ledger_id=l["ledger_id"], property_id=l["property_id"])
        if l["control"] in TO_BUSINESS:
            db.ins("cashbook_tx", cashbook="business", date=d, amount=l["amount"], description=f"{b['ref']} {l['note'] or l['payee']} from trust",
                   reference=l["reference"], source="batch", batch_id=bid)
    db.upd("batches", bid, status="released", released_by=u["id"] if u else None, released_at=d + "T" + (datetime.now().strftime("%H:%M:%S") if d == db.today() else "10:00:00"))
    return batch_full(bid)


def bank_file(bid):
    """Bulk payment file for online banking import (map the columns once in your bank's import screen)."""
    b = batch_full(bid)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Recipient name", "Bank", "Branch code", "Account number", "Account type", "Amount", "Own reference", "Recipient reference"])
    for l in b["lines"]:
        w.writerow([l["payee"], l["bank"] or "", l["branch_code"] or "", l["account_no"] or "", l["account_type"] or "",
                    f"{l['amount']:.2f}", b["ref"], l["reference"]])
    w.writerow(["TOTAL", "", "", "", "", f"{b['total']:.2f}", f"{len(b['lines'])} payments", ""])
    return out.getvalue()


# ------------------------------------------------------------------ bank feeds and statement import
def _fp(code, d, amount, desc, extra=""):
    return hashlib.sha1(f"{code}|{d}|{amount}|{desc}|{extra}".encode()).hexdigest()[:20]


def add_line(code, d, amount, desc, reference="", source="feed", fingerprint=None, balance=None):
    fp = fingerprint or _fp(code, d, amount, desc, reference)
    if db.val("SELECT 1 FROM bank_lines WHERE fingerprint=?", fp):
        return None
    return db.ins("bank_lines", cashbook=code, date=d, amount=db.rands(amount), description=desc, reference=reference,
                  source=source, fingerprint=fp, balance=balance)


def feed(code, upto=None):
    """Pull the bank feed. Live FNB / Netcash feeds need the bank's API credentials (Settings); without them AVA
    simulates the bank: every cashbook movement clears a day later, plus the bank's own charges at month end."""
    b = book(code)
    upto = upto or (date.today() - timedelta(days=1)).isoformat()
    n = 0
    if b["feed"] == "simulated":
        for t in db.q("SELECT * FROM cashbook_tx WHERE cashbook=? AND date<=? AND bank_line_id IS NULL AND source!='manual_only'", code, upto):
            lid = add_line(code, t["date"], t["amount"], (t["description"] or "")[:60], t["reference"] or "", "feed (simulated)", f"sim:{t['id']}")
            if lid:
                n += 1
        if code == "trust":   # the bank's monthly service fee, charged to the trust account
            first = db.val("SELECT MIN(date) FROM cashbook_tx WHERE cashbook='trust'")
            if first:
                m = date.fromisoformat(first).replace(day=1)
                while True:
                    end = (m + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                    if end.isoformat() > upto:
                        break
                    if add_line("trust", end.isoformat(), -186, "#SERVICE FEES TRUST ACC", "", "feed (simulated)", f"simfee:{end.isoformat()}"):
                        n += 1
                    m = end + timedelta(days=1)
        db.upd("cashbooks", b["id"], last_feed_at=db.now())
    _running_balance(code)
    return {"new_lines": n, **auto_match(code)}


def import_statement(code, content, filename=""):
    """OFX (any SA bank's 'download for accounting software') or CSV with date, description, amount[, balance]."""
    text = content.decode("utf-8", "ignore") if isinstance(content, bytes) else content
    n = 0
    if "<STMTTRN>" in text.upper():
        for blk in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.S | re.I):
            g = lambda t: (re.search(rf"<{t}>([^<\r\n]*)", blk, re.I) or [None, ""])[1].strip()
            d = g("DTPOSTED")[:8]
            d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            amt = float(g("TRNAMT") or 0)
            desc = (g("NAME") + " " + g("MEMO")).strip()
            if add_line(code, d, amt, desc[:80], g("CHECKNUM") or g("REFNUM"), "OFX " + filename, "ofx:" + (g("FITID") or _fp(code, d, amt, desc))):
                n += 1
    else:
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 3:
                continue
            ds = row[0].strip()
            m = re.match(r"(\d{4})[/-](\d{2})[/-](\d{2})", ds) or re.match(r"(\d{2})[/-](\d{2})[/-](\d{4})", ds)
            if not m:
                continue
            y, mo, dd = (m.group(1), m.group(2), m.group(3)) if len(m.group(1)) == 4 else (m.group(3), m.group(2), m.group(1))
            try:
                amt = float(row[2].replace(" ", "").replace(",", ""))
            except ValueError:
                continue
            bal = None
            if len(row) > 3:
                try:
                    bal = float(row[3].replace(" ", "").replace(",", ""))
                except ValueError:
                    bal = None
            if add_line(code, f"{y}-{mo}-{dd}", amt, row[1].strip()[:80], "", "CSV " + filename, None, bal):
                n += 1
    _running_balance(code)
    return {"new_lines": n, **auto_match(code)}


def _running_balance(code):
    run = book(code)["opening_balance"] or 0
    for l in db.q("SELECT id, amount FROM bank_lines WHERE cashbook=? ORDER BY date, id", code):
        run += l["amount"]
        db.exe("UPDATE bank_lines SET balance=? WHERE id=?", db.rands(run), l["id"])


def match(line_id, tx_id):
    db.exe("UPDATE bank_lines SET matched_tx=?, status='matched' WHERE id=?", tx_id, line_id)
    db.exe("UPDATE cashbook_tx SET bank_line_id=? WHERE id=?", line_id, tx_id)


def auto_match(code):
    from . import services as sv
    sync()
    m = alloc = 0
    for l in db.q("SELECT * FROM bank_lines WHERE cashbook=? AND status='unmatched' ORDER BY date, id", code):
        if l["fingerprint"].startswith("sim:"):
            t = db.q1("SELECT * FROM cashbook_tx WHERE id=? AND bank_line_id IS NULL", int(l["fingerprint"][4:]))
        else:
            t = db.q1("""SELECT * FROM cashbook_tx WHERE cashbook=? AND bank_line_id IS NULL AND amount=?
                         AND ABS(julianday(date)-julianday(?))<=4 ORDER BY ABS(julianday(date)-julianday(?)) LIMIT 1""",
                      code, l["amount"], l["date"], l["date"])
        if t:
            match(l["id"], t["id"])
            m += 1
            continue
        ref = re.search(r"AVA\s?0*(\d{1,6})", f"{l['description']} {l['reference']}", re.I)
        if code == "trust" and l["amount"] > 0 and ref:      # rent we recognise: allocate it to the lease straight away
            lease = db.q1("SELECT * FROM leases WHERE id=?", int(ref.group(1)))
            if lease and not locked(l["date"][:7]):
                sv.record_payment(lease["id"], l["amount"], "eft", (l["description"] or "")[:60], None, l["date"])
                sync()
                t = db.q1("SELECT * FROM cashbook_tx WHERE cashbook='trust' AND bank_line_id IS NULL AND amount=? AND date=? ORDER BY id DESC LIMIT 1",
                          l["amount"], l["date"])
                if t:
                    match(l["id"], t["id"])
                    alloc += 1
    left = db.val("SELECT COUNT(*) FROM bank_lines WHERE cashbook=? AND status='unmatched'", code)
    return {"matched": m, "allocated": alloc, "unmatched": left}


def resolve_line(line_id, action, u, lease_id=None, note=""):
    """Explain a bank line AVA could not match: rent from a tenant, bank charges, or an unidentified receipt."""
    from . import services as sv
    l = db.q1("SELECT * FROM bank_lines WHERE id=? AND status='unmatched'", line_id)
    if not l:
        raise HTTPException(404, "Line not found or already matched")
    check_open(l["date"])
    if action == "tenant":
        if l["amount"] <= 0 or not lease_id:
            raise HTTPException(400, "Choose the lease this payment is for")
        sv.record_payment(int(lease_id), l["amount"], "eft", (l["description"] or "")[:60], u["id"], l["date"])
        sync()
        t = db.q1("SELECT * FROM cashbook_tx WHERE cashbook=? AND bank_line_id IS NULL AND amount=? AND date=? ORDER BY id DESC LIMIT 1",
                  l["cashbook"], l["amount"], l["date"])
        match(line_id, t["id"])
    elif action == "bank_charges":
        if l["amount"] >= 0:
            raise HTTPException(400, "Bank charges are debits")
        t = add_tx(l["cashbook"], l["date"], l["amount"], "Bank charges", "", "bank", created_by=u["id"])
        match(line_id, t)
        # the agency – not its clients – pays trust bank charges: the business account refunds the trust account
        add_tx("business", l["date"], l["amount"], f"Refund trust bank charges {l['date'][:7]}", "", "transfer", created_by=u["id"])
        add_tx(l["cashbook"], l["date"], -l["amount"], f"Business account refunds bank charges {l['date'][:7]}", "", "transfer", created_by=u["id"])
    elif action == "suspense":
        if l["amount"] <= 0:
            raise HTTPException(400, "Only money received can go to suspense")
        lid = db.ins("ledger", account="control", kind="suspense", amount=l["amount"], date=l["date"], period=l["date"][:7],
                     description=f"Unidentified receipt: {l['description']}"[:120], ref=f"bank:{line_id}")
        t = add_tx(l["cashbook"], l["date"], l["amount"], f"Unidentified receipt (suspense): {l['description']}"[:120], "", "suspense", ledger_id=lid, created_by=u["id"])
        match(line_id, t)
    else:
        raise HTTPException(400, "Unknown action")
    db.exe("UPDATE bank_lines SET note=? WHERE id=?", note or action, line_id)
    return db.q1("SELECT * FROM bank_lines WHERE id=?", line_id)


def allocate_suspense(ledger_id, lease_id, u):
    """An unidentified receipt turns out to be rent: take it out of suspense and allocate it to the lease."""
    from . import services as sv
    s = db.q1("SELECT * FROM ledger WHERE id=? AND account='control' AND kind='suspense' AND amount>0", ledger_id)
    if not s:
        raise HTTPException(404, "Not a suspense receipt")
    if db.val("SELECT 1 FROM ledger WHERE account='control' AND kind='suspense' AND ref=?", f"alloc:{ledger_id}"):
        raise HTTPException(400, "Already allocated")
    d = db.today()
    check_open(d)
    db.ins("ledger", account="control", kind="suspense", amount=-s["amount"], date=d, period=d[:7], description="Allocated to lease", ref=f"alloc:{ledger_id}")
    sv.record_payment(int(lease_id), s["amount"], "suspense", f"From suspense {s['date']}", u["id"], d)


# ------------------------------------------------------------------ reconciliation
def recon(code, per):
    """Month-end bank reconciliation: bank statement vs cashbook, with the items still outstanding on either side."""
    end = ((date.fromisoformat(per + "-01") + timedelta(days=32)).replace(day=1) - timedelta(days=1)).isoformat()
    b = book(code)
    stmt = db.rands((b["opening_balance"] or 0) + (db.val("SELECT COALESCE(SUM(amount),0) FROM bank_lines WHERE cashbook=? AND date<=?", code, end) or 0))
    bank_reported = db.val("SELECT balance FROM bank_lines WHERE cashbook=? AND date<=? ORDER BY date DESC, id DESC LIMIT 1", code, end)
    cb = cash(code, end)
    unpresented = db.q("""SELECT t.* FROM cashbook_tx t LEFT JOIN bank_lines l ON l.id=t.bank_line_id
                          WHERE t.cashbook=? AND t.date<=? AND (t.bank_line_id IS NULL OR l.date>?) ORDER BY t.date""", code, end, end)
    unexplained = db.q("""SELECT l.* FROM bank_lines l LEFT JOIN cashbook_tx t ON t.id=l.matched_tx
                          WHERE l.cashbook=? AND l.date<=? AND (l.matched_tx IS NULL OR t.date>?) ORDER BY l.date""", code, end, end)
    adj = db.rands(stmt + sum(t["amount"] for t in unpresented) - sum(l["amount"] for l in unexplained))
    done = db.q1("SELECT * FROM recons WHERE cashbook=? AND period=?", code, per)
    return {"cashbook": code, "name": b["name"], "period": per, "end": end, "statement_balance": stmt,
            "bank_reported_balance": bank_reported, "cashbook_balance": cb, "adjusted_statement": adj,
            "difference": db.rands(adj - cb), "unpresented": unpresented,
            "unexplained": [l for l in unexplained if l["date"][:7] <= per],
            "can_sign": not [l for l in unexplained if l["matched_tx"] is None] and abs(adj - cb) < 1,
            "reconciled": done, "locked": locked(per)}


def sign_recon(code, per, u):
    r = recon(code, per)
    if not r["can_sign"]:
        raise HTTPException(400, "Explain every bank line first – match it, allocate it or mark it as bank charges / suspense.")
    db.exe("INSERT OR REPLACE INTO recons (cashbook, period, statement_balance, cashbook_balance, difference, outstanding, by_user) VALUES (?,?,?,?,?,?,?)",
           code, per, r["statement_balance"], r["cashbook_balance"], r["difference"],
           json.dumps([{"date": t["date"], "amount": t["amount"], "description": t["description"]} for t in r["unpresented"]]), u["id"] if u else None)
    return recon(code, per)


# ------------------------------------------------------------------ journals
JOURNAL_ACCOUNTS = ("owner", "tenant", "deposit", "control")


def journal(d, reason, lines, u):
    """A correcting journal: lines must balance within trust (owners + controls), tenant and deposit ledgers."""
    if not reason or len(reason.strip()) < 5:
        raise HTTPException(400, "Say why this journal is needed")
    check_open(d)
    if len(lines) < 2:
        raise HTTPException(400, "A journal needs at least two lines")
    tot = {"trust": 0, "tenant": 0, "deposit": 0}
    for l in lines:
        if l.get("account") not in JOURNAL_ACCOUNTS:
            raise HTTPException(400, "Journals can only move money between owner, tenant, deposit and control accounts")
        if l["account"] == "control" and l.get("kind") not in CONTROLS:
            raise HTTPException(400, "Choose the control account")
        if l["account"] in ("owner", "tenant", "deposit") and not l.get("property_id"):
            raise HTTPException(400, "Each owner/tenant/deposit line needs a property")
        tot["trust" if l["account"] in ("owner", "control") else l["account"]] += db.rands(l.get("amount") or 0)
    if any(abs(v) >= 1 for v in tot.values()):
        raise HTTPException(400, "The journal does not balance: " + ", ".join(f"{k} R{v:,.0f}" for k, v in tot.items() if abs(v) >= 1))
    n = (db.val("SELECT COUNT(*) FROM journals") or 0) + 1
    jid = db.ins("journals", ref=f"JNL-{n:05d}", date=d, reason=reason.strip(), by_user=u["id"])
    for l in lines:
        db.ins("ledger", account=l["account"], kind=l.get("kind") if l["account"] == "control" else "journal", amount=db.rands(l["amount"]),
               date=d, period=d[:7], property_id=l.get("property_id"), lease_id=l.get("lease_id"),
               description=(l.get("description") or reason)[:120], ref=f"JNL-{n:05d}", journal_id=jid)
    return jid


# ------------------------------------------------------------------ financial year
def fy_bounds(fy_end_year):
    m = int(fees.S("fy_end_month") or 2)
    end = date(fy_end_year, m, 1)
    start = date(fy_end_year - 1, m % 12 + 1, 1) if m != 12 else date(fy_end_year, 1, 1)
    return start.isoformat()[:7], end.isoformat()[:7]


def close_year(fy_end_year, u, force=False):
    sp, ep = fy_bounds(fy_end_year)
    if ep >= date.today().isoformat()[:7]:
        raise HTTPException(400, "This financial year has not ended yet")
    if db.val("SELECT 1 FROM year_ends WHERE fy=?", str(fy_end_year)):
        raise HTTPException(400, "Already closed")
    m = date.fromisoformat(sp + "-01")
    while m.isoformat()[:7] <= ep:
        per = m.isoformat()[:7]
        if not locked(per):
            lock_period(per, u, force=force)
        m = (m + timedelta(days=32)).replace(day=1)
    end = ((date.fromisoformat(ep + "-01") + timedelta(days=32)).replace(day=1) - timedelta(days=1)).isoformat()
    snap = trial_balance(end)
    db.ins("year_ends", fy=str(fy_end_year), start_period=sp, end_period=ep, snapshot=json.dumps(snap), by_user=u["id"] if u else None)
    return snap


# ------------------------------------------------------------------ deposit investment accounts (one per tenant)
def open_deposit_account(lease_id, d=None):
    if not lease_id or db.val("SELECT 1 FROM deposit_accounts WHERE lease_id=?", lease_id):
        return
    db.ins("deposit_accounts", lease_id=lease_id, bank=fees.S("deposit_bank"), account_no=f"7{lease_id:08d}",
           rate=fees.S("deposit_interest_pct"), opened_at=d or db.today())


def close_deposit_account(lease_id, d=None):
    db.exe("UPDATE deposit_accounts SET status='closed', closed_at=? WHERE lease_id=? AND status='open'", d or db.today(), lease_id)


def post_interest(lease_id, per, d):
    """Interest as credited by the investment account (simulated feed: balance × the account's rate / 12)."""
    from . import services as sv
    acc = db.q1("SELECT * FROM deposit_accounts WHERE lease_id=? AND status='open'", lease_id)
    if not acc:
        return 0
    held = sv.balance("deposit", lease_id)
    if held <= 0 or db.val("SELECT 1 FROM ledger WHERE lease_id=? AND kind='deposit_interest' AND period=?", lease_id, per):
        return 0
    amt = db.rands(held * (acc["rate"] or 0) / 1200)
    if amt <= 0:
        return 0
    sv.post("deposit", "deposit_interest", amt, db.val("SELECT property_id FROM leases WHERE id=?", lease_id), lease_id,
            f"Interest per {acc['bank']} statement ({acc['rate']:g}% p.a.)", d, per)
    return amt


# ------------------------------------------------------------------ debit orders (DebiCheck through Netcash)
def create_mandate(lease_id, u, holder, bank, account_no, account_type="cheque", debit_day=None):
    l = db.q1("SELECT * FROM leases WHERE id=?", lease_id)
    if not l or l["status"] not in ("active", "awaiting_signature"):
        raise HTTPException(400, "No active lease")
    account_no = re.sub(r"\D", "", account_no or "")
    if bank not in BANKS or not 7 <= len(account_no) <= 13:
        raise HTTPException(400, "Choose the bank and enter a valid account number")
    db.exe("UPDATE mandates SET status='replaced', cancelled_at=? WHERE lease_id=? AND status='active'", db.now(), lease_id)
    day = int(debit_day or l["due_day"] or 1)
    mid = db.ins("mandates", lease_id=lease_id, tenant_id=l["tenant_id"], ref=f"AVA{lease_id:05d}", holder=holder.strip(), bank=bank,
                 branch_code=BANKS[bank], account_no=account_no, account_type=account_type if account_type in ACCOUNT_TYPES else "cheque",
                 debit_day=day, max_amount=db.rands(l["rent"] * 1.5), debicheck="pending")
    return mid


def approve_mandate(mid, approved=True):
    """DebiCheck: the tenant confirms the mandate in their banking app. Netcash reports the result; simulated here."""
    db.exe("UPDATE mandates SET debicheck=?, approved_at=? WHERE id=?", "approved" if approved else "declined", db.now() if approved else None, mid)


def mandate_view(m):
    if not m:
        return None
    return {**{k: m[k] for k in ("id", "lease_id", "ref", "holder", "bank", "branch_code", "account_type", "debit_day", "max_amount", "debicheck", "status",
                                 "created_at", "approved_at")}, "account": masked(m["account_no"])}


def netcash_file(run_id):
    """Netcash debit order batch (tab-delimited: header, key, transactions, footer). Check field codes against the
    current Netcash batch-file specification before going live."""
    r = db.q1("SELECT * FROM debit_runs WHERE id=?", run_id)
    items = db.q("SELECT i.*, m.holder, m.account_no, m.branch_code, m.account_type, m.ref FROM debit_items i JOIN mandates m ON m.id=i.mandate_id WHERE run_id=?", run_id)
    key = fees.S("netcash_service_key") or "SERVICE-KEY"
    rows = [["H", key, "1", "TwoDay", r["ref"], r["action_date"].replace("-", ""), fees.S("netcash_vendor_key") or "VENDOR-KEY"],
            ["K", "101", "102", "131", "132", "133", "134", "135", "136", "162"]]
    for i in items:
        rows.append(["T", i["ref"], i["holder"][:30], "1", i["holder"][:30], ACCOUNT_TYPES.get(i["account_type"], "1"), i["branch_code"], "0",
                     i["account_no"], str(int(round(i["amount"] * 100)))])
    rows.append(["F", str(len(items)), str(int(round(sum(i["amount"] for i in items) * 100))), "9999"])
    return "\n".join("\t".join(r_) for r_ in rows) + "\n"


def debit_run(action_date=None):
    """Collect rent by debit order on each mandate's debit day: the amount due, capped at the mandate maximum."""
    from . import services as sv
    d = date.fromisoformat(action_date) if action_date else date.today()
    ms = db.q("""SELECT m.* FROM mandates m JOIN leases l ON l.id=m.lease_id WHERE m.status='active' AND m.debicheck='approved'
                 AND l.status='active' AND m.debit_day=? AND NOT EXISTS (SELECT 1 FROM debit_items i JOIN debit_runs r ON r.id=i.run_id
                 WHERE i.mandate_id=m.id AND substr(r.action_date,1,7)=?)""", d.day, d.isoformat()[:7])
    items = []
    for m in ms:
        due = sv.balance("tenant", m["lease_id"])
        amt = db.rands(min(max(due, 0), m["max_amount"] or due))
        if amt > 0:
            items.append((m, amt))
    if not items:
        return None
    n = (db.val("SELECT COUNT(*) FROM debit_runs") or 0) + 1
    rid = db.ins("debit_runs", ref=f"DO-{n:05d}", action_date=d.isoformat(), status="submitted", total=sum(a for _, a in items), count=len(items))
    for m, a in items:
        db.ins("debit_items", run_id=rid, mandate_id=m["id"], lease_id=m["lease_id"], amount=a)
    db.upd("debit_runs", rid, file=netcash_file(rid))
    if not fees.S("netcash_service_key"):
        process_run(rid)
    return rid


def process_run(rid, results=None):
    """Netcash result: paid items are receipted into trust; unpaids go to arrears with the bank's reason."""
    from . import services as sv
    r = db.q1("SELECT * FROM debit_runs WHERE id=?", rid)
    for i in db.q("SELECT i.*, m.sim_result, m.ref, l.tenant_id, l.property_id FROM debit_items i JOIN mandates m ON m.id=i.mandate_id JOIN leases l ON l.id=i.lease_id WHERE run_id=? AND i.status='pending'", rid):
        res = (results or {}).get(i["ref"]) or (("unpaid", "Insufficient funds (02)") if i["sim_result"] == "unpaid" else ("paid", ""))
        if res[0] == "paid":
            pid = sv.record_payment(i["lease_id"], i["amount"], "debit_order", f"{r['ref']} {i['ref']}", None, r["action_date"])
            db.upd("debit_items", i["id"], status="paid", payment_id=pid)
        else:
            db.upd("debit_items", i["id"], status="unpaid", reason=res[1])
            p = sv.prop(i["property_id"])
            sv.task(p["pm_id"], p["id"], "arrears", f"Debit order unpaid – {p['title']}", f"R{i['amount']:,.0f}: {res[1]}",
                    f"#/app/lease/{i['lease_id']}", 1, dedupe=f"unpaid:{i['id']}")
            sv.notify(i["tenant_id"], "Your debit order was returned", f"R{i['amount']:,.0f} – {res[1]}. Please pay in the app today.", "#/app/pay", "payment")
    db.upd("debit_runs", rid, status="processed", processed_at=db.now())
    sync()


def overview():
    tb = trial_balance()
    last = (date.today().replace(day=1) - timedelta(days=1)).isoformat()[:7]
    return {"tb": tb, "books": [{**b, "cash": cash(b["code"]), "unmatched": db.val("SELECT COUNT(*) FROM bank_lines WHERE cashbook=? AND status='unmatched'", b["code"]),
                                 "bank_balance": db.val("SELECT balance FROM bank_lines WHERE cashbook=? ORDER BY date DESC, id DESC LIMIT 1", b["code"]),
                                 "account_masked": masked(b["account_no"])} for b in db.q("SELECT * FROM cashbooks ORDER BY id")],
            "last_period": last, "last_reconciled": {c: db.val("SELECT MAX(period) FROM recons WHERE cashbook=?", c) for c in BOOKS},
            "last_locked": db.val("SELECT MAX(period) FROM periods WHERE locked_at IS NOT NULL"),
            "batches_waiting": db.q("SELECT id, ref, kind, status, total, period FROM batches WHERE status IN ('draft','authorised') ORDER BY id"),
            "mandates": {"active": db.val("SELECT COUNT(*) FROM mandates WHERE status='active' AND debicheck='approved'"),
                         "pending": db.val("SELECT COUNT(*) FROM mandates WHERE status='active' AND debicheck='pending'")},
            "feeds": {"mode": "simulated" if not fees.S("fnb_client_id") else "fnb", "netcash": bool(fees.S("netcash_service_key"))}}


# ------------------------------------------------------------------ demo: a year of trust history
def bootstrap_demo(admin_id, lease_behaviour):
    """Builds believable trust history: payouts and fee transfers released through payment batches, the bank feed,
    every month up to two months ago reconciled and locked, the last financial year closed – and last month left
    open with two bank lines to explain. Bank account numbers are made up."""
    import random
    rnd = random.Random(7)
    u = {"id": admin_id}
    first = db.val("SELECT MIN(date) FROM ledger") or db.today()
    ensure_books(first[:7] + "-01")
    banks = list(BANKS)
    for x in db.q("SELECT id, name, company, role FROM users WHERE role IN ('landlord','pm') OR (role='contractor' AND id IN (SELECT user_id FROM contractors WHERE approved=1))"):
        b = rnd.choice(banks)
        set_bank(x["id"], x["company"] or x["name"], b, str(rnd.randint(10**9, 10**10 - 1)), "cheque")
        db.exe("UPDATE bank_accounts SET verified=1 WHERE user_id=?", x["id"])
    sync()
    today = date.today()
    open_from = (today.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat()[:7]      # last month stays open
    # owner payouts: one batch per month, released on payout day
    for bid in queue_owner_payouts(u):
        b = batch_full(bid)
        d = max(db.val(f"SELECT MAX(date) FROM ledger WHERE id IN ({','.join(str(l['ledger_id']) for l in b['lines'])})"), b["period"] + "-28")
        authorise(bid, u)
        release(bid, u, min(d, (today - timedelta(days=1)).isoformat()))
    # fee transfers to the business account (and insurer, contractors) the day after each payout run
    for per in [r["period"] for r in db.q("SELECT DISTINCT period FROM batches WHERE kind='owner_payout' ORDER BY period")]:
        payday = db.val("SELECT MAX(substr(released_at,1,10)) FROM batches WHERE kind='owner_payout' AND period=?", per)
        d = min((date.fromisoformat(payday) + timedelta(days=1)).isoformat(), (today - timedelta(days=1)).isoformat())
        bid = create_fee_transfer(u, d, per)
        if bid:
            authorise(bid, u)
            release(bid, u, d)
    for b in db.q("SELECT id, released_at FROM batches WHERE status='released'"):     # history: prepared and authorised on the day
        db.exe("UPDATE batches SET created_at=?, authorised_at=? WHERE id=?", b["released_at"][:10] + "T08:30:00", b["released_at"][:10] + "T09:10:00", b["id"])
    # debit orders: most good payers are on DebiCheck; one bounces this month
    good = [lid for lid, beh in lease_behaviour.items() if beh == "good"]
    for i, lid in enumerate(good[:9] + [lid for lid, beh in lease_behaviour.items() if beh == "arrears"][:1]):
        l = db.q1("SELECT l.*, u.name FROM leases l JOIN users u ON u.id=l.tenant_id WHERE l.id=?", lid)
        mid = create_mandate(lid, None, l["name"], rnd.choice(banks), str(rnd.randint(10**9, 10**10 - 1)), "cheque", l["due_day"])
        db.exe("UPDATE mandates SET created_at=?, approved_at=? WHERE id=?", l["start_date"], l["start_date"], mid)
        if i == 8:
            continue                                   # waiting for the tenant to approve in the banking app
        approve_mandate(mid)
        db.exe("UPDATE mandates SET approved_at=? WHERE id=?", l["start_date"], mid)
        if lease_behaviour[lid] == "arrears":
            db.upd("mandates", mid, sim_result="unpaid")
    # past collections: the rent those tenants paid on the 1st–4th came in by debit order
    for m in db.q("SELECT * FROM mandates WHERE debicheck='approved'"):
        for p in db.q("SELECT * FROM payments WHERE lease_id=? AND status='complete' AND CAST(substr(created_at,9,2) AS INT)<=4 AND created_at>=?",
                      m["lease_id"], m["approved_at"] or ""):
            ad = p["created_at"][:10]
            run = db.q1("SELECT * FROM debit_runs WHERE action_date=?", ad) or db.q1("SELECT * FROM debit_runs WHERE id=?", db.ins(
                "debit_runs", ref=f"DO-{(db.val('SELECT COUNT(*) FROM debit_runs') or 0) + 1:05d}", action_date=ad, status="processed", total=0, count=0, processed_at=ad))
            db.ins("debit_items", run_id=run["id"], mandate_id=m["id"], lease_id=m["lease_id"], amount=p["amount"], status="paid", payment_id=p["id"])
            db.exe("UPDATE payments SET method='debit_order' WHERE id=?", p["id"])
            db.exe("UPDATE ledger SET description='Payment received (debit order)' WHERE account='tenant' AND kind='payment' AND lease_id=? AND date=? AND amount=?",
                   m["lease_id"], ad, -p["amount"])
        if m["sim_result"] == "unpaid":
            ad = today.replace(day=min(m["debit_day"], 28)).isoformat()
            rid = db.ins("debit_runs", ref=f"DO-{(db.val('SELECT COUNT(*) FROM debit_runs') or 0) + 1:05d}", action_date=ad, status="processed",
                         total=0, count=0, processed_at=ad)
            db.ins("debit_items", run_id=rid, mandate_id=m["id"], lease_id=m["lease_id"], amount=db.val("SELECT rent FROM leases WHERE id=?", m["lease_id"]),
                   status="unpaid", reason="Insufficient funds (02)")
    for run in db.q("SELECT id FROM debit_runs"):
        db.exe("""UPDATE debit_runs SET total=(SELECT COALESCE(SUM(amount),0) FROM debit_items WHERE run_id=?),
                  count=(SELECT COUNT(*) FROM debit_items WHERE run_id=?) WHERE id=?""", run["id"], run["id"], run["id"])
        db.upd("debit_runs", run["id"], file=netcash_file(run["id"]))
    # the bank: feed everything up to yesterday, then explain the bank's own charges in the closed months
    for code in BOOKS:
        feed(code)
    for l in db.q("SELECT * FROM bank_lines WHERE fingerprint LIKE 'simfee:%' AND status='unmatched' AND substr(date,1,7)<? ORDER BY date", open_from):
        resolve_line(l["id"], "bank_charges", u)
    last_day = (today.replace(day=1) - timedelta(days=1))
    add_line("trust", (last_day - timedelta(days=3)).isoformat(), 2500, "ACB CREDIT M SITHOLE", "", "feed (simulated)", "demo:unidentified")
    for code in BOOKS:
        feed(code)
    # reconcile and lock every month before last month; close the last financial year that has ended
    m = date.fromisoformat(first[:7] + "-01")
    while m.isoformat()[:7] < open_from:
        per = m.isoformat()[:7]
        for code in BOOKS:
            if has_activity(code, per) and recon(code, per)["can_sign"]:
                sign_recon(code, per, u)
        lock_period(per, u, force=True)
        m = (m + timedelta(days=32)).replace(day=1)
    fy_m = int(fees.S("fy_end_month") or 2)
    last_fy = today.year if today.month > fy_m else today.year - 1
    if fy_bounds(last_fy)[1] < open_from:
        close_year(last_fy, u, force=True)
    return trial_balance()
