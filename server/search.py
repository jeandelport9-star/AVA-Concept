"""Listing search with the Property24 filter set:
location (several suburbs/cities), property type (several), price range, bedrooms, bathrooms, parking/garages,
floor size, erf size, pets, furnished, features (garden, pool, flatlet, security estate, backup power/water,
fibre, study, wheelchair access, staff quarters, aircon, fireplace, braai, gym), 360° tour, available by,
listed within N days, keywords, and sort by newest / price / size / availability.
The same filter runs saved alerts, so an alert matches exactly what the renter searched for.
"""
from datetime import date, timedelta

from . import db

TYPES = ["House", "Apartment", "Townhouse", "Cottage", "Room", "Farm", "Vacant land", "Commercial", "Industrial", "Retirement"]
TYPE_ALIASES = {"Apartment": ["Apartment", "Flat"], "Cottage": ["Cottage", "Garden cottage"], "Retirement": ["Retirement"]}

# key -> (label, feature names that count)
FEATURES = {
    "garden": ("Garden", ["Garden"]),
    "pool": ("Pool", ["Pool", "Complex pool"]),
    "flatlet": ("Flatlet / granny flat", ["Flatlet", "Granny flat", "Staff quarters"]),
    "security": ("Security estate / complex", ["Security estate", "Complex security", "24h security", "Golf estate", "Electric fence"]),
    "backup_power": ("Backup power", ["Solar / inverter", "Backup power", "Generator", "Solar panels"]),
    "backup_water": ("Backup water", ["Borehole", "Water tank", "JoJo tank"]),
    "fibre": ("Fibre", ["Fibre"]),
    "study": ("Study", ["Study"]),
    "staff": ("Staff quarters", ["Staff quarters"]),
    "aircon": ("Air conditioning", ["Air conditioning", "Aircon"]),
    "fireplace": ("Fireplace", ["Fireplace"]),
    "braai": ("Braai / lapa", ["Lapa / braai", "Built-in braai"]),
    "gym": ("Gym", ["Gym"]),
    "wheelchair": ("Wheelchair accessible", ["Wheelchair accessible"]),
    "garage": ("Garage", ["Garage", "Double garage"]),
}

SORTS = {
    "new": "featured DESC, COALESCE(published_at, created_at) DESC",
    "recent": "COALESCE(published_at, created_at) DESC",
    "low": "rent ASC", "high": "rent DESC",
    "size": "size_m2 DESC", "size_low": "size_m2 ASC",
    "available": "COALESCE(available_from, '0000') ASC",
    "beds": "bedrooms DESC, rent ASC",
}


def _num(v):
    try:
        return float(v) if v not in (None, "", "0", 0) else None
    except (TypeError, ValueError):
        return None


def _list(v):
    if not v:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v).split(",") if x.strip()]


def where(f):
    """Filters (dict of strings/numbers) -> SQL where clause + args. Unknown keys are ignored."""
    w, a = ["listing_status='live'", "kind='rental'"], []
    areas = _list(f.get("areas")) + _list(f.get("city"))
    if areas:
        w.append("(" + " OR ".join(["(suburb LIKE ? OR city LIKE ? OR province LIKE ?)"] * len(areas)) + ")")
        for x in areas:
            a += [f"%{x}%"] * 3
    kw = (f.get("q") or f.get("keywords") or "").strip()
    for word in kw.split()[:6]:
        w.append("(title LIKE ? OR headline LIKE ? OR description LIKE ? OR features LIKE ? OR suburb LIKE ? OR address LIKE ?)")
        a += [f"%{word}%"] * 6
    types = _list(f.get("types")) + _list(f.get("type"))
    if types:
        names = [n for t in types for n in TYPE_ALIASES.get(t, [t])]
        w.append("type IN (%s)" % ",".join("?" * len(names))); a += names
    for key, col, op in (("min_rent", "rent", ">="), ("max_rent", "rent", "<="), ("beds", "bedrooms", ">="), ("max_beds", "bedrooms", "<="),
                         ("baths", "bathrooms", ">="), ("parking", "parking", ">="), ("min_size", "size_m2", ">="), ("max_size", "size_m2", "<="),
                         ("min_erf", "erf_size", ">="), ("max_erf", "erf_size", "<=")):
        v = _num(f.get(key))
        if v is not None:
            w.append(f"{col} {op} ?"); a.append(v)
    if str(f.get("pets")) in ("1", "true", "on"):
        w.append("pets=1")
    fur = str(f.get("furnished") or "")
    if fur in ("1", "true", "on", "yes"):
        w.append("furnished=1")
    elif fur == "no":
        w.append("furnished=0")
    feats = _list(f.get("features"))
    if str(f.get("backup")) in ("1", "true", "on"):
        feats.append("backup_power")
    for k in dict.fromkeys(feats):
        names = FEATURES.get(k, (None, [k]))[1]
        w.append("(" + " OR ".join(["features LIKE ?"] * len(names)) + ")"); a += [f'%"{n}"%' for n in names]
    if str(f.get("tour")) in ("1", "true", "on"):
        w.append("EXISTS (SELECT 1 FROM media m WHERE m.property_id=properties.id AND m.kind='pano')")
    if f.get("available_by"):
        w.append("(available_from IS NULL OR available_from <= ?)"); a.append(str(f["available_by"])[:10])
    days = _num(f.get("listed_within"))
    if days:
        w.append("COALESCE(published_at, created_at) >= ?"); a.append((date.today() - timedelta(days=int(days))).isoformat())
    if f.get("bounds"):
        s, wl, n, e = [float(x) for x in str(f["bounds"]).split(",")]
        w.append("lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?"); a += [s, n, wl, e]
    return " AND ".join(w), a


def run(f, cols, limit=60):
    wsql, a = where(f)
    order = SORTS.get(f.get("sort") or "new", SORTS["new"])
    total = db.val(f"SELECT COUNT(*) FROM properties WHERE {wsql}", *a)
    rows = db.q(f"SELECT {cols} FROM properties WHERE {wsql} ORDER BY {order} LIMIT ?", *a, int(limit))
    return rows, total


def matches(f, pid):
    wsql, a = where(f)
    return bool(db.val(f"SELECT 1 FROM properties WHERE id=? AND {wsql}", pid, *a))


def facets():
    """Counts that drive the filter panel (like P24's numbers next to each option)."""
    base = "listing_status='live' AND kind='rental'"
    areas = db.q(f"SELECT suburb name, city, COUNT(*) n FROM properties WHERE {base} GROUP BY suburb, city ORDER BY n DESC, suburb")
    cities = db.q(f"SELECT city name, province, COUNT(*) n FROM properties WHERE {base} GROUP BY city ORDER BY n DESC")
    types = {r["type"]: r["n"] for r in db.q(f"SELECT type, COUNT(*) n FROM properties WHERE {base} GROUP BY type")}
    feats = {}
    for k, (label, names) in FEATURES.items():
        feats[k] = db.val(f"SELECT COUNT(*) FROM properties WHERE {base} AND (" + " OR ".join(["features LIKE ?"] * len(names)) + ")", *[f'%"{n}"%' for n in names])
    pr = db.q1(f"SELECT MIN(rent) lo, MAX(rent) hi FROM properties WHERE {base}")
    return {"areas": areas, "cities": cities, "types": [{"type": t, "n": types.get(t, 0)} for t in TYPES],
            "features": [{"key": k, "label": FEATURES[k][0], "n": feats[k]} for k in FEATURES], "price": pr,
            "tour": db.val(f"SELECT COUNT(*) FROM properties WHERE {base} AND EXISTS (SELECT 1 FROM media m WHERE m.property_id=properties.id AND m.kind='pano')")}
