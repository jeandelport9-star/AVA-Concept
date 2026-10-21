import hashlib
import hmac
import os
import secrets

from fastapi import Depends, HTTPException, Request

from . import db

ROLES = ("admin", "pm", "landlord", "tenant", "contractor")


def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 120_000)
    return salt.hex() + "$" + h.hex()


def check_pw(pw: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 120_000).hex(), h)


def new_session(user_id: int) -> str:
    tok = secrets.token_urlsafe(32)
    db.ins("sessions", token=tok, user_id=user_id)
    return tok


def public_user(u):
    if not u:
        return None
    return {k: u[k] for k in ("id", "email", "name", "phone", "role", "company", "verified", "pm_id", "commission_pct") if k in u}


def optional_user(request: Request):
    tok = request.cookies.get("ava_session") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not tok:
        return None
    return db.q1("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND u.active=1", tok)


def user(u=Depends(optional_user)):
    if not u:
        raise HTTPException(401, "Please sign in")
    return u


def role(*roles):
    def dep(u=Depends(user)):
        if u["role"] not in roles:
            raise HTTPException(403, "Not allowed for your account type")
        return u
    return dep


# ---- who may see what -------------------------------------------------------
def prop_ids(u):
    """Property ids a user may see in the back office."""
    r = u["role"]
    if r == "admin":
        return [x["id"] for x in db.q("SELECT id FROM properties")]
    if r == "pm":
        return [x["id"] for x in db.q("SELECT id FROM properties WHERE pm_id=?", u["id"])]
    if r == "landlord":
        return [x["id"] for x in db.q("SELECT id FROM properties WHERE landlord_id=?", u["id"])]
    if r == "tenant":
        return [x["property_id"] for x in db.q("SELECT DISTINCT property_id FROM leases WHERE tenant_id=?", u["id"])]
    if r == "contractor":
        a = db.q("SELECT DISTINCT t.property_id FROM tickets t LEFT JOIN quotes q ON q.ticket_id=t.id "
                 "WHERE t.contractor_id=? OR q.contractor_id=?", u["id"], u["id"])
        b = db.q("SELECT DISTINCT property_id FROM snags WHERE contractor_id=?", u["id"])
        return list({x["property_id"] for x in a + b})
    return []


def can_prop(u, pid, write=False):
    ok = pid in prop_ids(u)
    if write and u["role"] not in ("admin", "pm", "landlord"):
        ok = False
    if not ok:
        raise HTTPException(403, "You don't have access to this property")


def in_list(ids):
    return "(" + ",".join(str(int(i)) for i in ids) + ")" if ids else "(NULL)"
