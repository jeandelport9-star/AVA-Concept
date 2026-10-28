"""Demo data: python -m server.seed [--reset]

A Pretoria portfolio run by one portfolio manager (Thandi), a small Cape Town book (Pieter), a new-build
snag project, and the real 360 panoramas of a Pretoria house captured with a Leica BLK360 G2 (from Site Inspect).
All logins use the password  demo1234
"""
import io
import json
import math
import random
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import automation, db, fees, services as sv
from .auth import hash_pw

ROOT = Path(__file__).resolve().parent.parent
PANOS = ROOT / "demo" / "panos"
TODAY = date.today()
random.seed(7)


# ------------------------------------------------------------------ images
def perspective(src, yaw, pitch=-4, fov=78, w=1400, h=930):
    """Rectilinear view out of an equirectangular panorama (yaw 0 = image centre)."""
    im = np.asarray(src)
    H, W = im.shape[:2]
    f = (w / 2) / math.tan(math.radians(fov) / 2)
    xs, ys = np.meshgrid(np.arange(w) - w / 2, h / 2 - np.arange(h))
    d = np.stack([xs, ys, np.full_like(xs, f, dtype=float)], -1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    p, y = math.radians(pitch), math.radians(yaw)
    y1 = d[..., 1] * math.cos(p) + d[..., 2] * math.sin(p)
    z1 = -d[..., 1] * math.sin(p) + d[..., 2] * math.cos(p)
    x2 = d[..., 0] * math.cos(y) + z1 * math.sin(y)
    z2 = -d[..., 0] * math.sin(y) + z1 * math.cos(y)
    lon, lat = np.arctan2(x2, z2), np.arcsin(np.clip(y1, -1, 1))
    u = ((lon / (2 * math.pi) + 0.5) * W).astype(int) % W
    v = np.clip(((0.5 - lat / math.pi) * H).astype(int), 0, H - 1)
    return Image.fromarray(im[v, u])


def save_img(img, sub, name, q=84):
    folder = db.UPLOADS / sub / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(folder / name, quality=q)
    return f"/uploads/{sub}/demo/{name}"


def pano_copy(name, damage=None):
    folder = db.UPLOADS / "panos" / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    im = Image.open(PANOS / f"{name}.jpg").convert("RGB")
    out = f"{name}{'-' + damage if damage else ''}.jpg"
    if damage:
        d = ImageDraw.Draw(im, "RGBA")
        W, H = im.size
        if damage == "stain":    # water stain on the wall/ceiling
            cx, cy = int(W * 0.62), int(H * 0.30)
            for r, a in ((140, 40), (110, 55), (80, 70)):
                d.ellipse([cx - r * 1.6, cy - r, cx + r * 1.6, cy + r], fill=(120, 95, 60, a))
            im = im.filter(ImageFilter.GaussianBlur(0.6))
        if damage == "scuff":    # scuffs, nail holes and a dent low on the wall
            cx, cy = int(W * 0.40), int(H * 0.47)
            for i in range(14):
                x, y = cx + random.randint(-160, 160), cy + random.randint(-50, 60)
                d.line([x, y, x + random.randint(20, 70), y + random.randint(-6, 6)], fill=(70, 60, 55, 150), width=5)
            for i in range(5):
                x, y = cx + random.randint(-200, 200), cy - random.randint(80, 140)
                d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=(40, 35, 30, 220))
        if damage == "crack":
            x, y = int(W * 0.15), int(H * 0.22)
            pts = [(x, y)]
            for i in range(18):
                x += random.randint(6, 18); y += random.randint(8, 22); pts.append((x, y))
            d.line(pts, fill=(60, 55, 50, 230), width=4)
    im.save(folder / out, quality=85)
    return f"/uploads/panos/demo/{out}"


def signature(name):
    im = Image.new("RGBA", (420, 140), (255, 255, 255, 0))
    d = ImageDraw.Draw(im)
    x, y, pts = 20, 80, []
    rnd = random.Random(name)
    for ch in name[:12]:
        for k in range(4):
            x += rnd.randint(4, 9); y = 70 + rnd.randint(-38, 30) * math.sin(k + ord(ch)); pts.append((x, y))
    d.line(pts, fill=(20, 30, 60, 255), width=3, joint="curve")
    d.line([(30, 115), (x, 108)], fill=(20, 30, 60, 255), width=2)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    import base64
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj 4 0 obj<</Length 60>>stream\nBT /F1 18 Tf 60 760 Td (AVA demo document - placeholder) Tj ET\nendstream endobj 5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"


def demo_pdf(name):
    folder = db.UPLOADS / "docs" / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(PDF)
    return f"/uploads/docs/demo/{name}"


# ------------------------------------------------------------------ data
def user(email, name, role, **kw):
    return db.ins("users", email=email, pw_hash=PW, name=name, role=role, verified=1, **kw)


PW = None
DEMO_VERSION = 11   # bump when the demo data changes; run.py rebuilds older demo databases

PRETORIA = [
    # title, type, suburb, city, lat, lng, beds, baths, park, m2, rent, features
    ("Jacaranda House", "House", "Brooklyn", "Pretoria", -25.7712, 28.2391, 3, 2, 2, 210, 21500, ["Garden", "Fireplace", "Wooden floors", "Solar / inverter", "Staff quarters"]),
    ("14 Lynnwood Mews", "Townhouse", "Lynnwood", "Pretoria", -25.7651, 28.2858, 3, 2, 2, 145, 15800, ["Garden", "Pet friendly", "Fibre", "Complex security"]),
    ("The Hatfield Studio 304", "Apartment", "Hatfield", "Pretoria", -25.7489, 28.2365, 1, 1, 1, 42, 6200, ["Fibre", "Walk to Gautrain", "24h security"]),
    ("Menlo Garden Cottage", "Cottage", "Menlo Park", "Pretoria", -25.7718, 28.2603, 1, 1, 1, 55, 7400, ["Garden", "Furnished option", "Prepaid electricity"]),
    ("8 Waterkloof Heights", "House", "Waterkloof", "Pretoria", -25.7843, 28.2481, 4, 3, 2, 320, 32500, ["Pool", "Garden", "Solar / inverter", "Borehole", "Electric fence"]),
    ("Faerie Glen Village 12", "Townhouse", "Faerie Glen", "Pretoria", -25.7799, 28.3049, 2, 2, 2, 110, 12900, ["Garden", "Pet friendly", "Complex pool"]),
    ("Garsfontein Duplex 5", "Townhouse", "Garsfontein", "Pretoria", -25.7920, 28.2967, 3, 2, 2, 135, 14500, ["Garden", "Solar / inverter"]),
    ("Arcadia Lofts 9", "Apartment", "Arcadia", "Pretoria", -25.7454, 28.2133, 2, 1, 1, 70, 7900, ["Fibre", "Backup power"]),
    ("Moreleta Park Family Home", "House", "Moreleta Park", "Pretoria", -25.8195, 28.2936, 4, 2, 2, 260, 22800, ["Pool", "Garden", "Lapa / braai"]),
    ("Silver Lakes Golf Villa", "House", "Silver Lakes", "Pretoria", -25.7859, 28.3576, 3, 3, 2, 240, 27500, ["Golf estate", "Solar / inverter", "Pool"]),
    ("Centurion Gate 21", "Apartment", "Centurion", "Centurion", -25.8604, 28.1894, 2, 2, 1, 82, 9800, ["Fibre", "Gym", "24h security"]),
    ("Irene Farm Cottage", "Cottage", "Irene", "Centurion", -25.8792, 28.2240, 2, 1, 2, 90, 10500, ["Garden", "Pet friendly", "Borehole"]),
    ("Highveld Park 7", "Townhouse", "Highveld", "Centurion", -25.8670, 28.1810, 3, 2, 2, 128, 13900, ["Garden", "Complex pool"]),
    ("Eldoraigne Corner House", "House", "Eldoraigne", "Centurion", -25.8540, 28.1530, 3, 2, 2, 190, 17500, ["Garden", "Solar / inverter"]),
    ("Sunninghill Square 15", "Apartment", "Sunninghill", "Johannesburg", -26.0381, 28.0645, 2, 2, 1, 85, 12500, ["Fibre", "Backup power", "Gym"]),
    ("Bryanston Garden Flat", "Cottage", "Bryanston", "Johannesburg", -26.0560, 28.0225, 1, 1, 1, 60, 8900, ["Garden", "Pet friendly"]),
    ("Fourways View 33", "Apartment", "Fourways", "Johannesburg", -26.0170, 28.0080, 2, 1, 1, 74, 9600, ["Fibre", "Complex pool"]),
    ("Parkhurst Semi", "House", "Parkhurst", "Johannesburg", -26.1395, 28.0175, 2, 2, 1, 120, 16500, ["Garden", "Walk to 4th Ave"]),
    ("Rivonia Mews 4", "Townhouse", "Rivonia", "Johannesburg", -26.0565, 28.0596, 3, 2, 2, 140, 17900, ["Garden", "Solar / inverter"]),
    ("Linden Family Home", "House", "Linden", "Johannesburg", -26.1366, 27.9926, 3, 2, 2, 200, 18500, ["Garden", "Pool", "Pet friendly"]),
    ("Brooklyn Mall Apartments 6", "Apartment", "Brooklyn", "Pretoria", -25.7705, 28.2362, 1, 1, 1, 48, 7200, ["Fibre", "Walk to mall"]),
    ("Lynnwood Manor 2", "Townhouse", "Lynnwood Manor", "Pretoria", -25.7595, 28.2777, 2, 1, 1, 95, 10900, ["Garden"]),
]
EXTRA = [   # vacant homes listed on the portal (so search has some depth)
    ("Menlyn Maine Residences 1204", "Apartment", "Menlyn", "Pretoria", -25.7845, 28.2770, 2, 2, 1, 88, 16900, ["Fibre", "Gym", "24h security", "Backup power", "Air conditioning"]),
    ("Montana Park Simplex", "Townhouse", "Montana", "Pretoria", -25.6905, 28.2585, 2, 1, 2, 96, 9500, ["Garden", "Pet friendly", "Complex security"]),
    ("Waterkloof Ridge Family Home", "House", "Waterkloof Ridge", "Pretoria", -25.7950, 28.2390, 5, 4, 4, 420, 45000, ["Pool", "Garden", "Solar / inverter", "Borehole", "Staff quarters", "Study", "Flatlet"]),
    ("Sunnyside Studio 7", "Apartment", "Sunnyside", "Pretoria", -25.7530, 28.2050, 1, 1, 0, 34, 4900, ["Walk to shops"]),
    ("Equestria Security Estate 22", "House", "Equestria", "Pretoria", -25.7600, 28.3410, 3, 2, 2, 210, 21000, ["Security estate", "Garden", "Fibre", "Pet friendly", "Backup power"]),
    ("Olympus Country Estate 3", "House", "Olympus", "Pretoria", -25.8080, 28.3360, 4, 3, 3, 320, 34000, ["Security estate", "Pool", "Garden", "Study", "Solar / inverter"]),
    ("Hatfield Room – student", "Room", "Hatfield", "Pretoria", -25.7495, 28.2380, 1, 1, 0, 18, 3800, ["Furnished option", "Fibre", "Walk to campus"]),
    ("Rietondale Garden Cottage", "Cottage", "Rietondale", "Pretoria", -25.7260, 28.2390, 1, 1, 1, 50, 6500, ["Garden", "Pet friendly", "Prepaid electricity"]),
    ("Centurion Golf Estate Villa", "Townhouse", "Centurion Golf Estate", "Centurion", -25.8530, 28.1830, 3, 2, 2, 175, 24500, ["Golf estate", "Security estate", "Complex pool", "Backup power"]),
    ("Midstream Estate Home", "House", "Midstream", "Centurion", -25.9220, 28.1950, 4, 3, 2, 300, 32000, ["Security estate", "Pool", "Fibre", "Solar / inverter", "Study"]),
    ("Kosmosdal Starter Home", "Townhouse", "Kosmosdal", "Centurion", -25.9070, 28.1360, 2, 1, 1, 78, 8900, ["Garden", "Complex security"]),
    ("Fourways Gardens Retirement Flat", "Retirement", "Fourways", "Johannesburg", -26.0210, 28.0040, 2, 1, 1, 80, 11500, ["24h security", "Wheelchair accessible", "Frail care nearby"]),
    ("Melville Character House", "House", "Melville", "Johannesburg", -26.1770, 28.0090, 3, 2, 1, 180, 19500, ["Garden", "Fireplace", "Wooden floors", "Pet friendly"]),
    ("Sandton Skye 1801", "Apartment", "Sandton", "Johannesburg", -26.1040, 28.0560, 1, 1, 1, 55, 14500, ["Fibre", "Gym", "Backup power", "Air conditioning", "24h security"]),
    ("Hennops Smallholding Cottage", "Farm", "Hennops Park", "Centurion", -25.8650, 28.1310, 2, 1, 4, 110, 9900, ["Borehole", "Pet friendly", "Garden", "Water tank"]),
    ("Claremont Garden Flat", "Apartment", "Claremont", "Cape Town", -33.9800, 18.4650, 1, 1, 1, 52, 13900, ["Garden", "Fibre", "Mountain view"]),
]
NATIONAL = [  # (title, type, suburb, city, province, lat, lng, beds, baths, parking, m2, rent, features)
    # KwaZulu-Natal
    ("Umhlanga Ridge Apartment 502", "Apartment", "Umhlanga Ridge", "Durban", "KwaZulu-Natal", -29.7280, 31.0700, 2, 2, 2, 105, 17500, ["Sea view", "Pool", "24h security", "Backup power", "Air conditioning"]),
    ("Ballito Beach Villa", "House", "Ballito", "Ballito", "KwaZulu-Natal", -29.5390, 31.2140, 4, 3, 2, 280, 36000, ["Sea view", "Pool", "Security estate", "Solar / inverter", "Garden"]),
    ("Morningside Garden Flat", "Apartment", "Morningside", "Durban", "KwaZulu-Natal", -29.8270, 31.0050, 1, 1, 1, 58, 8500, ["Garden", "Pet friendly", "Fibre"]),
    ("Westville Family Home", "House", "Westville", "Durban", "KwaZulu-Natal", -29.8330, 30.9300, 3, 2, 2, 220, 19800, ["Pool", "Garden", "Study", "Borehole"]),
    ("Hillcrest Country Cottage", "Cottage", "Hillcrest", "Durban", "KwaZulu-Natal", -29.7810, 30.7580, 2, 1, 1, 85, 9200, ["Garden", "Pet friendly", "Fireplace"]),
    ("Scottsville Townhouse 9", "Townhouse", "Scottsville", "Pietermaritzburg", "KwaZulu-Natal", -29.6200, 30.4000, 3, 2, 2, 130, 11500, ["Complex pool", "Garden", "Complex security"]),
    # Western Cape
    ("Constantia Vineyard Home", "House", "Constantia", "Cape Town", "Western Cape", -34.0280, 18.4410, 4, 3, 3, 380, 55000, ["Pool", "Garden", "Mountain view", "Solar / inverter", "Borehole", "Study", "Flatlet"]),
    ("Stellenbosch Student Room", "Room", "Stellenbosch Central", "Stellenbosch", "Western Cape", -33.9360, 18.8610, 1, 1, 0, 16, 5200, ["Furnished option", "Fibre", "Walk to campus"]),
    ("Somerset West Lock-up-and-go", "Townhouse", "Somerset West", "Somerset West", "Western Cape", -34.0790, 18.8430, 2, 2, 2, 110, 15500, ["Security estate", "Garden", "Pet friendly", "Backup power"]),
    ("Bloubergstrand Sea Apartment", "Apartment", "Bloubergstrand", "Cape Town", "Western Cape", -33.8030, 18.4640, 2, 2, 1, 92, 21000, ["Sea view", "Fibre", "Gym", "24h security"]),
    ("George Garden Route Home", "House", "Heatherlands", "George", "Western Cape", -33.9650, 22.4550, 3, 2, 2, 210, 16500, ["Garden", "Mountain view", "Fireplace", "Water tank"]),
    ("Knysna Heads Cottage", "Cottage", "The Heads", "Knysna", "Western Cape", -34.0800, 23.0570, 2, 1, 1, 90, 14000, ["Sea view", "Fireplace", "Garden"]),
    ("Hermanus Retirement Flat", "Retirement", "Hermanus", "Hermanus", "Western Cape", -34.4180, 19.2350, 2, 1, 1, 78, 12500, ["Sea view", "Wheelchair accessible", "24h security"]),
    ("Paarl Winelands Smallholding", "Farm", "Paarl", "Paarl", "Western Cape", -33.7340, 18.9630, 3, 2, 4, 200, 18500, ["Borehole", "Pet friendly", "Mountain view", "Solar / inverter"]),
    # Eastern Cape
    ("Summerstrand Beach Flat", "Apartment", "Summerstrand", "Gqeberha", "Eastern Cape", -33.9900, 25.6600, 2, 1, 1, 80, 9800, ["Sea view", "Walk to beach", "Complex security"]),
    ("Walmer Family Home", "House", "Walmer", "Gqeberha", "Eastern Cape", -33.9800, 25.5900, 4, 2, 2, 260, 18500, ["Pool", "Garden", "Water tank", "Staff quarters"]),
    ("Vincent Townhouse 4", "Townhouse", "Vincent", "East London", "Eastern Cape", -32.9900, 27.9000, 3, 2, 2, 140, 11000, ["Garden", "Complex security", "Pet friendly"]),
    # Free State / Northern Cape / North West
    ("Westdene Duplex", "Townhouse", "Westdene", "Bloemfontein", "Free State", -29.1080, 26.2000, 2, 2, 2, 105, 8900, ["Garden", "Complex security"]),
    ("Langenhoven Park Home", "House", "Langenhoven Park", "Bloemfontein", "Free State", -29.0750, 26.1550, 3, 2, 2, 190, 12900, ["Garden", "Pool", "Solar / inverter"]),
    ("Kimberley Belgravia House", "House", "Belgravia", "Kimberley", "Northern Cape", -28.7440, 24.7680, 3, 2, 2, 200, 11000, ["Garden", "Borehole", "Pet friendly"]),
    ("Potchefstroom Student Apartment", "Apartment", "Potchefstroom Central", "Potchefstroom", "North West", -26.6900, 27.0920, 2, 1, 1, 65, 6800, ["Fibre", "Walk to campus", "Furnished option"]),
    ("Rustenburg Safari Gardens Home", "House", "Safari Gardens", "Rustenburg", "North West", -25.6550, 27.2550, 3, 2, 2, 210, 12500, ["Pool", "Garden", "Electric fence"]),
    # Limpopo / Mpumalanga
    ("Polokwane Bendor Townhouse", "Townhouse", "Bendor", "Polokwane", "Limpopo", -23.8880, 29.4800, 3, 2, 2, 145, 11800, ["Complex pool", "Garden", "Backup power"]),
    ("Mbombela Riverside Home", "House", "Sonheuwel", "Mbombela", "Mpumalanga", -25.4800, 30.9650, 4, 3, 2, 270, 17500, ["Pool", "Garden", "Lapa / braai", "Solar / inverter"]),
    ("White River Garden Cottage", "Cottage", "White River", "White River", "Mpumalanga", -25.3320, 31.0100, 1, 1, 1, 60, 7200, ["Garden", "Pet friendly", "Borehole"]),
    ("Dullstroom Trout Farm Cottage", "Farm", "Dullstroom", "Dullstroom", "Mpumalanga", -25.4170, 30.1040, 2, 1, 2, 95, 9500, ["Fireplace", "Borehole", "Pet friendly", "Mountain view"]),
]
CAPE = [
    ("Gardens Victorian 3", "Apartment", "Gardens", "Cape Town", -33.9343, 18.4115, 2, 1, 0, 78, 16500, ["Mountain view", "Fibre"]),
    ("Observatory Cottage", "Cottage", "Observatory", "Cape Town", -33.9377, 18.4719, 2, 1, 0, 70, 13500, ["Courtyard", "Pet friendly"]),
    ("Sea Point Studio", "Apartment", "Sea Point", "Cape Town", -33.9180, 18.3880, 1, 1, 1, 40, 12000, ["Sea view", "24h security"]),
    ("Durbanville Family Home", "House", "Durbanville", "Cape Town", -33.8320, 18.6470, 4, 2, 2, 230, 24500, ["Pool", "Garden", "Solar / inverter"]),
]

# ---------------------------------------------------------------- realistic rents, R15 000 – R30 000 per property
# Each rent is worked out from what the home is: floor area × the going rate per m² for that area, adjusted for the type of
# home and its features. Homes that would rent for less than R15 000 are described as the bigger home that the rent buys,
# so size, bedrooms, bathrooms, parking and price always agree with each other.
RATE_M2 = {"Cape Town": 175, "Ballito": 150, "Stellenbosch": 150, "Hermanus": 135, "Somerset West": 135, "Paarl": 125, "Knysna": 140,
           "George": 115, "Johannesburg": 135, "Pretoria": 120, "Centurion": 120, "Durban": 125, "Pietermaritzburg": 105,
           "Gqeberha": 110, "East London": 105, "Bloemfontein": 100, "Kimberley": 95, "Polokwane": 100, "Mbombela": 105,
           "White River": 100, "Dullstroom": 95, "Rustenburg": 100, "Potchefstroom": 100}
PREMIUM_SUBURB = {"Sandton": 1.25, "Waterkloof": 1.15, "Sea Point": 1.15, "Constantia": 1.1, "Umhlanga Ridge": 1.15, "Bloubergstrand": 1.05,
                  "Menlo Park": 1.05, "Brooklyn": 1.05, "Rivonia": 1.05, "Parkhurst": 1.05, "Silver Lakes": 1.05}
TYPE_F = {"Apartment": 1.12, "Townhouse": 1.0, "House": 0.95, "Cottage": 1.0, "Farm": 0.8, "Retirement": 1.0, "Room": 1.2}
FEAT_R = {"Pool": 900, "Sea view": 1500, "Security estate": 1200, "Solar / inverter": 900, "Backup power": 600, "Air conditioning": 500,
          "Gym": 500, "Mountain view": 600, "Furnished option": 1500, "Borehole": 300, "Staff quarters": 700}
RENAME = {"Hatfield Room – student": "Hatfield Park Apartment 12", "Stellenbosch Student Room": "Stellenbosch Central Apartment",
          "Potchefstroom Student Apartment": "Potchefstroom Garden Apartment", "Sunnyside Studio 7": "Sunnyside Terraces 7",
          "Sea Point Studio": "Sea Point Promenade Flat", "The Hatfield Studio 304": "The Hatfield 304", "Bryanston Garden Flat": "Bryanston Garden Cottage"}


def _wobble(title, lo, hi):
    """Deterministic 'random' number per property so a rebuild gives the same rents."""
    h = sum(ord(c) * (i + 1) for i, c in enumerate(title)) % 1000 / 1000
    return lo + (hi - lo) * h


def fair_rent(title, typ, sub, city, beds, baths, park, m2, feats, max_rent=30000):
    """Returns (title, type, beds, baths, parking, m2, rent) – all consistent with each other and with R15k–R30k."""
    title = RENAME.get(title, title)
    if typ == "Room":
        typ = "Apartment"
    rate = RATE_M2.get(city, 105) * PREMIUM_SUBURB.get(sub, 1.0) * TYPE_F.get(typ, 1.0)
    extras = sum(FEAT_R.get(f, 0) for f in feats)
    rent = m2 * rate + extras
    floor = _wobble(title, 15000, 18500)
    if rent < floor:                                   # describe the home that this rent actually buys
        m2 = int(round((floor - extras) / rate / 5) * 5)
    beds = max(beds, 1 if m2 < 60 else 2 if m2 < 125 else 3 if m2 < 220 else 4)
    if m2 >= 60 and beds < 2:
        beds = 2
    baths = max(baths, 1 if beds <= 2 else 2 if beds == 3 else 3)
    park = max(park, 1 if typ == "Apartment" else 2)
    rent = m2 * rate + extras
    knee = max_rent - 6000                            # top end: still rises with size and quality, but flattens towards the R30k ceiling
    if rent > knee:
        import math
        rent = knee + (max_rent - knee) * (1 - math.exp(-(rent - knee) / 14000))
    rent = int(min(max_rent, max(15000, round(rent / 500) * 500)))
    return title, typ, beds, baths, park, m2, rent


def _fit(rows, natl=False):
    o = 1 if natl else 0
    out = []
    for r in rows:
        r = list(r)
        title, typ, beds, baths, park, m2, rent = fair_rent(r[0], r[1], r[2], r[3], r[6 + o], r[7 + o], r[8 + o], r[9 + o], r[11 + o])
        r[0], r[1], r[6 + o], r[7 + o], r[8 + o], r[9 + o], r[10 + o] = title, typ, beds, baths, park, m2, rent
        out.append(tuple(r))
    return out


PRETORIA, CAPE, EXTRA, NATIONAL = _fit(PRETORIA), _fit(CAPE), _fit(EXTRA), _fit(NATIONAL, natl=True)

FIRST = ["Lerato", "Johan", "Ayesha", "Sipho", "Mia", "Kagiso", "Liezl", "Naledi", "Ruan", "Zanele", "Priya", "Thabo", "Chantelle",
         "Mpho", "Annika", "Bongani", "Fatima", "Werner", "Nomsa", "Tristan", "Palesa", "Ettienne", "Karabo", "Megan"]
LAST = ["Dlamini", "Botha", "Patel", "Nkosi", "van der Merwe", "Molefe", "Pretorius", "Khumalo", "Smit", "Mahlangu", "Naidoo",
        "Mokoena", "Jacobs", "Sithole", "Venter", "Ndlovu", "Cassim", "Steyn", "Zulu", "du Plessis", "Mabena", "Kruger", "Shabalala", "Adams"]


def run(reset=False):
    global PW
    if reset and db.DB_PATH.exists():
        try:
            db.conn().close()
        except Exception:
            pass
        db._local.c = None
        for f in db.DATA.glob("ava.db*"):
            f.unlink()
        shutil.rmtree(db.UPLOADS, ignore_errors=True)
    db.init()
    if db.val("SELECT COUNT(*) FROM users"):
        print("Database already has data. Use --reset to rebuild the demo.")
        return
    PW = hash_pw("demo1234")
    print("Seeding AVA demo…")

    admin = user("admin@ava.co.za", "AVA Admin", "admin", company="AVA Rentals")
    thandi = user("thandi@ava.co.za", "Thandi Mokoena", "pm", phone="082 555 0101", company="AVA · Pretoria East", commission_pct=4.0)
    pieter = user("pieter@ava.co.za", "Pieter van Wyk", "pm", phone="083 555 0202", company="AVA · Cape Town", commission_pct=3.5)

    landlords = [user(e, n, "landlord", phone=p, company=c) for e, n, p, c in [
        ("emgee@example.co.za", "Emgee van der Merwe", "082 410 1111", "EVM Property Holdings"),
        ("wynand@example.co.za", "Wynand Kotze", "083 410 2222", None),
        ("sarah@example.co.za", "Sarah Govender", "084 410 3333", "Govender Family Trust"),
        ("andre@example.co.za", "André Fourie", "082 410 4444", None),
        ("lindiwe@example.co.za", "Lindiwe Zungu", "072 410 5555", "LZ Investments"),
        ("david@example.co.za", "David Cohen", "082 410 6666", None),
        ("marelize@example.co.za", "Marelize Swart", "076 410 7777", None),
        ("devco@example.co.za", "Menlo Mews Developments", "012 410 8888", "Menlo Mews Developments (Pty) Ltd")]]

    contractors = []
    # (email, contact, company, trades, areas, call-out, base lat, lng, base address, months paid ahead (negative = lapsed))
    CONTRACTORS = [
        ("plumbfix@example.co.za", "Kobus Nel", "PlumbFix Pretoria", ["Plumber", "Geyser"], ["Pretoria", "Centurion"], 450, -25.7520, 28.2410, "Hatfield, Pretoria", 6),
        ("aquaflow@example.co.za", "Siya Mthembu", "AquaFlow Plumbing", ["Plumber"], ["Pretoria", "Centurion"], 395, -25.7800, 28.2750, "Lynnwood, Pretoria", 2),
        ("sparkpro@example.co.za", "Riaan Botes", "SparkPro Electrical", ["Electrician", "Solar / inverter installer"], ["Pretoria", "Centurion"], 500, -25.7700, 28.2800, "Lynnwood, Pretoria", 3),
        ("voltsafe@example.co.za", "Lebo Maseko", "VoltSafe Electrical", ["Electrician"], ["Johannesburg"], 550, -26.1050, 28.0520, "Sandton, Johannesburg", 1),
        ("handyhelp@example.co.za", "Gerrit Visser", "HandyHelp Maintenance", ["Handyman", "Painter / builder", "Carpentry"], ["Pretoria"], 300, -25.7700, 28.2400, "Brooklyn, Pretoria", 4),
        ("roofright@example.co.za", "Ahmed Essop", "RoofRight Waterproofing", ["Roofer / waterproofer", "Painter / builder"], ["Pretoria"], 650, -25.7730, 28.2580, "Menlo Park, Pretoria", 2),
        ("lockit@example.co.za", "Themba Ngcobo", "LockIt Security", ["Locksmith / security"], ["Pretoria"], 350, -25.7800, 28.3000, "Faerie Glen, Pretoria", 1),
        ("tilecraft@example.co.za", "Jaco Erasmus", "TileCraft Finishes", ["Tiler", "Painter / builder"], ["Pretoria"], 400, -25.7900, 28.2900, "Garsfontein, Pretoria", 2),
        ("capeplumb@example.co.za", "Yusuf Abrahams", "Cape Plumb & Drain", ["Plumber"], ["Cape Town"], 450, -33.9380, 18.4700, "Observatory, Cape Town", 3),
        ("newco@example.co.za", "Sam Pillay", "Pillay Appliance Repairs", ["Appliance repair"], ["Pretoria"], 380, -25.7230, 28.2200, "Pretoria Moot", 0),
        ("pipedreams@example.co.za", "Hennie Koen", "Pipe Dreams Plumbing", ["Plumber", "Geyser"], ["Centurion"], 420, -25.8600, 28.1900, "Centurion CBD", 2),
        ("brightsparks@example.co.za", "Nandi Zulu", "Bright Sparks Centurion", ["Electrician"], ["Centurion"], 480, -25.8700, 28.1700, "Highveld, Centurion", 1),
        ("fixitjhb@example.co.za", "Craig Daniels", "FixIt Joburg", ["Handyman", "Painter / builder", "Plumber"], ["Johannesburg"], 350, -26.0950, 28.0100, "Bryanston, Johannesburg", 2),
        ("randburgplumb@example.co.za", "Musa Khoza", "Randburg Plumbing Co.", ["Plumber"], ["Johannesburg"], 400, -26.0950, 27.9950, "Randburg", 1),
        ("coastal@example.co.za", "Reggie Pillay", "Coastal Plumbing Durban", ["Plumber", "Geyser"], ["Durban"], 450, -29.7300, 31.0700, "Umhlanga, Durban", 2),
        ("kznelec@example.co.za", "Sibusiso Dube", "KZN Electrical Services", ["Electrician", "Solar / inverter installer"], ["Durban"], 520, -29.8300, 30.9400, "Westville, Durban", 1),
        ("capehandy@example.co.za", "Liam Jacobs", "Cape Handyman Co.", ["Handyman", "Painter / builder", "Carpentry"], ["Cape Town"], 320, -33.9300, 18.4200, "Gardens, Cape Town", 3),
        ("bayfix@example.co.za", "Thando Mali", "Bay Maintenance", ["Handyman", "Plumber"], ["Gqeberha"], 300, -33.9800, 25.6200, "Walmer, Gqeberha", 1),
        ("bloemfix@example.co.za", "Pieter Smit", "Bloem Home Repairs", ["Handyman", "Plumber", "Electrician"], ["Bloemfontein"], 280, -29.1000, 26.1900, "Westdene, Bloemfontein", 1),
        ("lapsed@example.co.za", "Jan Venter", "Venter Plumbing (listing lapsed)", ["Plumber"], ["Pretoria"], 350, -25.7650, 28.2450, "Brooklyn, Pretoria", -1),
        # --- more listed companies across South Africa
        ("eastsideelec@example.co.za", "Mpho Ramela", "Eastside Electrical", ["Electrician"], ["Pretoria"], 450, -25.7900, 28.3100, "Moreleta Park, Pretoria", 3),
        ("jacarandapaint@example.co.za", "Wim de Bruyn", "Jacaranda Painters & Builders", ["Painter / builder", "Roofer / waterproofer", "Tiler"], ["Pretoria"], 350, -25.7420, 28.2300, "Arcadia, Pretoria", 2),
        ("ptagarden@example.co.za", "Lindiwe Khumalo", "GreenThumb Garden & Pool", ["Garden / pool service", "Pest control"], ["Pretoria"], 250, -25.7600, 28.2900, "Lynnwood Ridge, Pretoria", 4),
        ("pestaway@example.co.za", "Bongani Shabalala", "PestAway Gauteng", ["Pest control"], ["Pretoria", "Johannesburg"], 380, -25.8300, 28.2000, "Lyttelton, Centurion", 2),
        ("applianceguy@example.co.za", "Rajesh Naidoo", "Appliance Doctor", ["Appliance repair", "Electrician"], ["Pretoria", "Centurion"], 420, -25.8050, 28.2550, "Waterkloof Glen, Pretoria", 1),
        ("centhandy@example.co.za", "Andries du Toit", "Centurion Home Care", ["Handyman", "Painter / builder", "Carpentry", "Plumber"], ["Centurion"], 300, -25.8780, 28.2150, "Irene, Centurion", 3),
        ("solarsure@example.co.za", "Karabo Molefe", "SolarSure Inverters", ["Solar / inverter installer", "Electrician"], ["Centurion", "Pretoria"], 650, -25.9000, 28.1500, "Eldoraigne, Centurion", 2),
        ("rivoniaelec@example.co.za", "Dineo Mokoena", "Rivonia Electrical Works", ["Electrician", "Solar / inverter installer"], ["Johannesburg"], 500, -26.0570, 28.0600, "Rivonia, Johannesburg", 2),
        ("jhbpest@example.co.za", "Trevor Adams", "Joburg Pest & Termite", ["Pest control"], ["Johannesburg"], 400, -26.1450, 28.0100, "Parkhurst, Johannesburg", 1),
        ("fourwaysroof@example.co.za", "Grant Mitchell", "Fourways Roof & Paint", ["Roofer / waterproofer", "Painter / builder"], ["Johannesburg"], 550, -26.0100, 28.0050, "Fourways, Johannesburg", 3),
        ("lindenlock@example.co.za", "Farouk Moosa", "Linden Lock & Gate", ["Locksmith / security", "Handyman"], ["Johannesburg"], 350, -26.1350, 27.9850, "Linden, Johannesburg", 2),
        ("atlanticplumb@example.co.za", "Shaun Petersen", "Atlantic Plumbing", ["Plumber", "Geyser"], ["Cape Town"], 480, -33.9200, 18.3850, "Sea Point, Cape Town", 2),
        ("southernelec@example.co.za", "Nomsa Jacobs", "Southern Suburbs Electrical", ["Electrician", "Solar / inverter installer"], ["Cape Town"], 520, -33.9850, 18.4650, "Claremont, Cape Town", 3),
        ("capewaterproof@example.co.za", "Dawid Hendricks", "Cape Waterproofing & Paint", ["Roofer / waterproofer", "Painter / builder", "Tiler"], ["Cape Town"], 450, -33.9400, 18.4500, "Woodstock, Cape Town", 2),
        ("northelec@example.co.za", "Corné Louw", "Northern Suburbs Electrical", ["Electrician"], ["Cape Town"], 480, -33.8300, 18.6500, "Durbanville, Cape Town", 1),
        ("bloubergfix@example.co.za", "Ryan Smith", "Blouberg Handyman & Plumbing", ["Handyman", "Plumber"], ["Cape Town"], 330, -33.8050, 18.4750, "Bloubergstrand, Cape Town", 2),
        ("winelandsplumb@example.co.za", "Hendrik Joubert", "Winelands Plumbing", ["Plumber", "Geyser"], ["Stellenbosch", "Paarl"], 420, -33.9350, 18.8600, "Stellenbosch", 2),
        ("helderbergfix@example.co.za", "Anwar Davids", "Helderberg Home Services", ["Handyman", "Electrician", "Painter / builder"], ["Somerset West"], 350, -34.0800, 18.8450, "Somerset West", 1),
        ("overbergfix@example.co.za", "Marius Steyn", "Overberg Maintenance", ["Handyman", "Plumber", "Roofer / waterproofer"], ["Hermanus"], 380, -34.4150, 19.2400, "Hermanus", 2),
        ("gardenroute@example.co.za", "Johan Kriel", "Garden Route Repairs", ["Handyman", "Plumber", "Electrician"], ["George", "Knysna"], 400, -33.9650, 22.4600, "George", 2),
        ("berearepairs@example.co.za", "Sanele Ngubane", "Berea Home Repairs", ["Handyman", "Plumber", "Painter / builder"], ["Durban"], 320, -29.8350, 31.0000, "Morningside, Durban", 2),
        ("northcoastelec@example.co.za", "Kevin Moodley", "North Coast Electrical", ["Electrician", "Solar / inverter installer"], ["Ballito", "Durban"], 500, -29.5400, 31.2100, "Ballito", 1),
        ("pmbplumb@example.co.za", "Zanele Mkhize", "Midlands Plumbing PMB", ["Plumber", "Geyser"], ["Pietermaritzburg"], 400, -29.6150, 30.3950, "Scottsville, Pietermaritzburg", 2),
        ("bayelec@example.co.za", "Luthando Gqeba", "Bay Electrical", ["Electrician"], ["Gqeberha"], 450, -33.9900, 25.6500, "Summerstrand, Gqeberha", 1),
        ("elfix@example.co.za", "Andile Sono", "Buffalo City Maintenance", ["Handyman", "Plumber", "Electrician"], ["East London"], 320, -32.9900, 27.9000, "Vincent, East London", 2),
        ("polokwanefix@example.co.za", "Tshepo Mabunda", "Limpopo Home Services", ["Handyman", "Plumber", "Electrician"], ["Polokwane"], 300, -23.8900, 29.4700, "Bendor, Polokwane", 1),
        ("lowveldfix@example.co.za", "Marnus Coetzee", "Lowveld Maintenance", ["Handyman", "Plumber", "Electrician", "Garden / pool service"], ["Mbombela", "White River"], 350, -25.4700, 30.9700, "Sonheuwel, Mbombela", 3),
        ("highlandsplumb@example.co.za", "Piet Grobler", "Highlands Plumbing & Borehole", ["Plumber", "Handyman"], ["Belfast", "Dullstroom"], 480, -25.6900, 30.0300, "Belfast (eMakhazeni)", 1),
        ("rustenburgfix@example.co.za", "Kagiso Seane", "Platinum Home Repairs", ["Handyman", "Plumber", "Electrician"], ["Rustenburg"], 300, -25.6600, 27.2500, "Safari Gardens, Rustenburg", 1),
        ("potchfix@example.co.za", "Ruan Pretorius", "Potch Maintenance", ["Handyman", "Plumber"], ["Potchefstroom"], 280, -26.7100, 27.1000, "Potchefstroom", 2),
        ("kimberleyfix@example.co.za", "Gift Motaung", "Diamond City Repairs", ["Handyman", "Plumber", "Electrician"], ["Kimberley"], 300, -28.7400, 24.7700, "Belgravia, Kimberley", 1),
        ("lonehillplumb@example.co.za", "Bradley Fourie", "Lonehill Plumbing", ["Plumber", "Geyser"], ["Johannesburg"], 450, -26.0200, 28.0300, "Lonehill, Johannesburg", 2),
        ("rooihuisplumb@example.co.za", "Elsabe Kruger", "Rooihuiskraal Plumbing", ["Plumber", "Geyser"], ["Centurion"], 400, -25.8900, 28.1500, "Rooihuiskraal, Centurion", 2),
        ("bellvilleplumb@example.co.za", "Mogamat Isaacs", "Bellville Plumbers", ["Plumber", "Geyser"], ["Cape Town"], 420, -33.8800, 18.6300, "Bellville, Cape Town", 1),
        ("constantiaplumb@example.co.za", "Greg Walters", "Constantia Plumbing & Geysers", ["Plumber", "Geyser"], ["Cape Town"], 500, -34.0200, 18.4500, "Constantia, Cape Town", 2),
        ("dbnnorthplumb@example.co.za", "Prakash Govender", "Durban North Plumbers", ["Plumber", "Geyser"], ["Durban"], 420, -29.7800, 31.0300, "Durban North", 2),
        ("pretorianorth@example.co.za", "Willem Botha", "Pretoria North-East Plumbing", ["Plumber", "Handyman"], ["Pretoria"], 380, -25.7300, 28.3300, "Equestria, Pretoria", 1),
        ("bloemelec@example.co.za", "Nthabiseng Moloi", "Mangaung Electrical", ["Electrician", "Solar / inverter installer"], ["Bloemfontein"], 420, -29.1100, 26.2000, "Brandwag, Bloemfontein", 2),
    ]
    for email, name, comp, trades, areas, fee, clat, clng, base, months in CONTRACTORS:
        uid = user(email, name, "contractor", company=comp, phone=f"08{random.randint(1,4)} {random.randint(100,999)} {random.randint(1000,9999)}",
                   created_at=(TODAY - timedelta(days=random.randint(60, 700))).isoformat())
        db.ins("contractors", user_id=uid, trades=trades, areas=areas, approved=0 if comp.startswith("Pillay") else 1,
               vetted=0 if comp.startswith("Pillay") else 1, callout_fee=fee, bee_level=random.choice(["Level 1", "Level 2", "Level 4"]),
               registration=f"{random.randint(2009, 2021)}/{random.randint(100000, 999999)}/07", lat=clat, lng=clng, base_address=base,
               radius_km=random.choice([15, 20, 25, 30]), years=random.randint(3, 25), insured=random.choice([0, 1, 1]),
               bio=f"{comp} – {', '.join(trades).lower()} in and around {base}. Fixed quotes, photo proof on every job.",
               sub_until=(TODAY + timedelta(days=30 * months - (5 if months > 0 else 0))).isoformat() if months else (TODAY + timedelta(days=20)).isoformat())
        if months > 0:
            for k in range(min(months, 3)):
                d = (TODAY - timedelta(days=30 * k + 3)).isoformat()
                db.ins("ledger", account="ava", kind="listing_fee", amount=fees.S("contractor_listing_fee"), date=d, period=d[:7], description=f"Maintenance listing – {comp}")
        contractors.append(uid)
    CON = dict(zip([c[0].split("@")[0].replace("handyhelp", "handy").replace("roofright", "roof").replace("lockit", "lock").replace("tilecraft", "tile") for c in CONTRACTORS], contractors))
    tenants = []
    for i in range(24):
        n = f"{FIRST[i]} {LAST[i]}"
        tenants.append(user(f"{FIRST[i].lower()}.{LAST[i].split()[-1].lower()}@example.com", n, "tenant", phone=f"07{random.randint(1,9)} {random.randint(100,999)} {random.randint(1000,9999)}"))
    db.exe("UPDATE users SET email='lerato@example.com' WHERE id=?", tenants[0])
    db.exe("UPDATE users SET email='johan@example.com' WHERE id=?", tenants[1])

    # contractor reputations (tenants and owners rate quality, punctuality, price and communication)
    raters = tenants[:12] + landlords[:6]
    comments = {5: ["Arrived on time, fixed it first time and cleaned up.", "Excellent – sent photos of the finished work.", "Quick, fair and friendly."],
                4: ["Good work, a day later than promised.", "Neat job, price was fair.", "Sorted it, communication could be better."],
                3: ["Fixed eventually – needed a second visit.", "OK job, quite expensive."]}
    rep = {"plumbfix": [5, 5, 4, 5, 5, 4], "aquaflow": [4, 4, 3, 4], "sparkpro": [5, 4, 5, 5], "voltsafe": [3, 4, 4], "handy": [4, 5, 4, 4, 5, 5, 4],
           "roof": [4, 3, 4], "lock": [5, 5, 4], "tile": [4, 4, 5], "capeplumb": [5, 4], "pipedreams": [4, 4, 5], "brightsparks": [5, 4],
           "fixitjhb": [4, 3, 4, 4], "randburgplumb": [4], "coastal": [5, 5, 4], "kznelec": [4, 4], "capehandy": [5, 4, 4], "bayfix": [4], "bloemfix": [4, 5]}
    for c in CONTRACTORS[20:]:   # the wider network: a few genuine-looking ratings each
        rep[c[0].split("@")[0]] = [random.choice([3, 4, 4, 4, 5, 5, 5]) for _ in range(random.randint(1, 6))]
    for key, ratings in rep.items():
        for rt in ratings:
            j = lambda: max(1, min(5, rt + random.choice([-1, 0, 0, 0, 1])))
            a_ = random.choice(raters)
            db.ins("reviews", target_type="contractor", target_id=CON[key], author_id=a_, author_role="tenant" if a_ in tenants else "landlord",
                   rating=rt, quality=j(), punctuality=j(), price_score=j(), communication=j(), text=random.choice(comments[rt]),
                   created_at=(TODAY - timedelta(days=random.randint(5, 300))).isoformat(),
                   reply="Thank you – we appreciate the feedback!" if random.random() < .25 else None)
    db.ins("reviews", target_type="contractor", target_id=CON["voltsafe"], author_id=landlords[1], rating=2, text="Left the DB cover off and didn't return calls.", status="pending")


    # ---------------------------------------------------------- media
    pano_rooms = [("Entrance", "011"), ("Lounge", "001"), ("Dining room", "003"), ("Kitchen", "008"), ("Bedroom 1", "004"),
                  ("Passage", "010"), ("Laundry", "035")]
    pano_url = {code: pano_copy(code) for _, code in pano_rooms}
    photo_pool = []
    for code, yaws in {"001": [-60, 0, 110], "003": [0, 150, -120], "004": [-100, 0, 90], "008": [-130, 20, 120], "009": [10, -60],
                       "010": [0, 120], "034": [30, -60], "011": [-20], "035": [60]}.items():
        src = Image.open(PANOS / f"{code}.jpg").convert("RGB")
        for y in yaws:
            photo_pool.append(save_img(perspective(src, y), "media", f"p{code}_{y}.jpg"))
    print(f"  {len(photo_pool)} listing photos cut from the BLK360 panoramas")

    # ---------------------------------------------------------- properties
    props = []
    owners = landlords[:7]
    for i, (title, typ, sub, city, lat, lng, beds, baths, park, m2, rent, feats) in enumerate(PRETORIA + CAPE):
        pm = thandi if i < len(PRETORIA) else pieter
        ll = owners[i % 7] if i else landlords[0]
        num = random.randint(3, 140)
        pid = db.ins("properties", pm_id=pm, landlord_id=ll, title=title, type=typ, suburb=sub, city=city,
                     province="Western Cape" if city == "Cape Town" else "Gauteng", lat=lat, lng=lng,
                     address=f"{num} {random.choice(['Jacaranda', 'Protea', 'Acacia', 'Marula', 'Disa', 'Kiaat', 'Yellowwood'])} {random.choice(['Street', 'Avenue', 'Road', 'Crescent'])}, {sub}",
                     erf=f"Erf {random.randint(100, 4999)} {sub}", bedrooms=beds, bathrooms=baths, parking=park, size_m2=m2,
                     features=feats, pets=1 if "Pet friendly" in feats else 0, rent=rent, deposit=rent, insured=1 if i % 5 else 0,
                     created_at=(TODAY - timedelta(days=400 - i * 9)).isoformat())
        p = sv.prop(pid)
        from .ai import listing_copy
        c = listing_copy(p)
        db.upd("properties", pid, headline=c["headline"], description=c["description"])
        from .photos import set_for
        for k, (url, cap) in enumerate(set_for(typ, 7, pid)):
            db.ins("media", property_id=pid, kind="photo", url=url, caption=cap, sort=k)
        props.append(pid)
    P = props
    jac = P[0]
    db.exe("DELETE FROM media WHERE property_id=?", jac)
    for k, url in enumerate(photo_pool[:12]):
        db.ins("media", property_id=jac, kind="photo", url=url, sort=k)
    for k, (room, code) in enumerate(pano_rooms):
        db.ins("media", property_id=jac, kind="pano", url=pano_url[code], room=room, caption=room, sort=k)
    # a second home with a short 360 tour
    for k, (room, code) in enumerate(pano_rooms[1:4]):
        db.ins("media", property_id=P[1], kind="pano", url=pano_url[code], room=room, caption=room, sort=k)

    regional = {}
    for prov, (email, name, phone) in {"KwaZulu-Natal": ("sizwe@ava.co.za", "Sizwe Ndlovu", "083 555 0303"),
                                       "Eastern Cape": ("anel@ava.co.za", "Anel Botha", "082 555 0404"),
                                       "Free State": ("kabelo@ava.co.za", "Kabelo Mothibi", "072 555 0505")}.items():
        regional[prov] = user(email, name, "pm", phone=phone, company=f"AVA · {prov}", commission_pct=4.0)
    region_pm = {"KwaZulu-Natal": regional["KwaZulu-Natal"], "Eastern Cape": regional["Eastern Cape"], "Western Cape": pieter,
                 "Free State": regional["Free State"], "Northern Cape": regional["Free State"], "North West": regional["Free State"]}
    gauteng_listings = user("naledi@ava.co.za", "Naledi Sithole", "pm", phone="071 555 0606", company="AVA · Gauteng North & Johannesburg", commission_pct=4.0)
    EXTRA[:] = [row + ("Gauteng", gauteng_listings) if row[3] != "Cape Town" else row for row in EXTRA]
    for (title, typ, sub, city, prov, lat, lng, beds, baths, park, m2, rent, feats) in NATIONAL:
        EXTRA.append((title, typ, sub, city, lat, lng, beds, baths, park, m2, rent, feats, prov, region_pm.get(prov, gauteng_listings)))
    for i, row in enumerate(EXTRA):
        title, typ, sub, city, lat, lng, beds, baths, park, m2, rent, feats = row[:12]
        prov = row[12] if len(row) > 12 else ("Western Cape" if city == "Cape Town" else "Gauteng")
        pm_for = row[13] if len(row) > 13 else (pieter if city == "Cape Town" else thandi)
        pid = db.ins("properties", pm_id=pm_for, landlord_id=owners[i % 7], title=title, type=typ, suburb=sub, city=city,
                     province=prov, lat=lat, lng=lng,
                     address=f"{random.randint(2, 90)} {random.choice(['Acacia', 'Kiaat', 'Disa', 'Protea'])} Street, {sub}", bedrooms=beds, bathrooms=baths,
                     parking=park, size_m2=m2, features=feats, pets=1 if "Pet friendly" in feats else 0, furnished=1 if "Furnished option" in feats else 0,
                     rent=rent, deposit=rent, insured=1, listing_status="live", views=random.randint(10, 400),
                     erf_size=random.choice([e for e in (600, 800, 1000, 1250, 1500, 2000) if e >= m2 * 2.2] or [2500]) if typ == "House" else (random.choice([8500, 10000, 21000]) if typ == "Farm" else None),
                     available_from=(TODAY + timedelta(days=random.choice([0, 0, 7, 14, 30, 45]))).isoformat(),
                     published_at=(datetime.now() - timedelta(days=random.randint(0, 40), hours=random.randint(0, 20))).isoformat(timespec="seconds"),
                     created_at=(TODAY - timedelta(days=60)).isoformat())
        from .ai import listing_copy
        c = listing_copy(sv.prop(pid))
        db.upd("properties", pid, headline=c["headline"], description=c["description"])
        from .photos import set_for
        for k, (url, cap) in enumerate(set_for(typ, 7, pid)):
            db.ins("media", property_id=pid, kind="photo", url=url, caption=cap, sort=k)

    # projects (construction snag lists)
    proj = db.ins("properties", pm_id=thandi, landlord_id=landlords[7], title="Menlo Mews – Unit 3 (new build)", kind="project",
                  type="Townhouse", suburb="Menlo Park", city="Pretoria", province="Gauteng", lat=-25.7735, lng=28.2588,
                  address="Unit 3, Menlo Mews, 41 Atterbury Road, Menlo Park", bedrooms=3, bathrooms=2, parking=2, size_m2=165, rent=20500,
                  features=["New build", "Solar / inverter", "Garden"], insured=0)
    proj2 = db.ins("properties", pm_id=thandi, landlord_id=landlords[7], title="Menlo Mews – Unit 4 (new build)", kind="project",
                   type="Townhouse", suburb="Menlo Park", city="Pretoria", province="Gauteng", lat=-25.7737, lng=28.2592,
                   address="Unit 4, Menlo Mews, 41 Atterbury Road, Menlo Park", bedrooms=3, bathrooms=2, parking=2, size_m2=165, rent=20500,
                   features=["New build"], insured=0)

    # ---------------------------------------------------------- leases + money history
    def months_between(a, b):
        out, d = [], a.replace(day=1)
        while d <= b:
            out.append(d)
            d = (d + timedelta(days=32)).replace(day=1)
        return out

    HIST_FROM = (TODAY.replace(day=1) - timedelta(days=330)).replace(day=1)   # 12 months of statements
    lease_plan = [  # property index, tenant index, start offset (days ago), months, behaviour
        (0, 0, 215, 7, "good"),        # Jacaranda: ends mid Oct, tenant gave notice -> outgoing
        (1, 1, 300, 12, "good"),
        (2, 2, 120, 12, "late"),
        (3, 3, 400, 24, "good"),
        (4, 4, 330, 12, "good"),       # ends in ~35 days -> renewal
        (5, 5, 90, 12, "arrears"),
        (6, 6, 250, 12, "good"),
        (7, 7, 45, 12, "partial"),
        (8, 8, 500, 24, "good"),
        (10, 9, 200, 12, "good"),
        (11, 10, 330, 12, "good"),     # renewal
        (12, 11, 150, 12, "good"),
        (14, 12, 60, 12, "good"),
        (16, 13, 280, 12, "late"),
        (17, 14, 380, 24, "good"),
        (19, 15, 170, 12, "good"),
        (22, 16, 210, 12, "good"),
        (23, 17, 100, 12, "good"),
        (25, 18, 260, 12, "arrears"),
    ]
    leases = {}
    for pi, ti, ago, months, beh in lease_plan:
        pid, tid = P[pi], tenants[ti]
        p = sv.prop(pid)
        start = (TODAY - timedelta(days=ago)).replace(day=1)
        if pi == 0:
            start = date(TODAY.year, 3, 16) if TODAY.month > 3 else TODAY - timedelta(days=200)
        end = (start + timedelta(days=31 * months)).replace(day=1) - timedelta(days=1)
        if pi == 0:
            end = TODAY + timedelta(days=13)
        if pi in (4, 11):
            end = TODAY + timedelta(days=38 if pi == 4 else 52)
        if ago > 365:   # second year of the lease: year-one rent + the 8% anniversary escalation
            base = min(p["rent"], 27500)
            rent_now = round(base * 1.08 / 10) * 10
            db.upd("properties", pid, rent=rent_now, deposit=rent_now)
            p = sv.prop(pid)
        else:
            base = rent_now = p["rent"]
        anniversary = start.replace(year=start.year + 1)
        aid = db.ins("applications", property_id=pid, user_id=tid, name=db.val("SELECT name FROM users WHERE id=?", tid),
                     email=db.val("SELECT email FROM users WHERE id=?", tid), employer=random.choice(["Absa", "Netcare", "Deloitte", "Dept of Health", "Vodacom", "Self-employed", "Tuks"]),
                     income=int(base * random.uniform(3.1, 4.2)), occupants=random.randint(1, 4), credit_score=random.randint(640, 760),
                     rental_history="Good – paid on time (TPN rental profile)", status="approved", score=random.randint(72, 92),
                     docs=[{"kind": k, "url": demo_pdf(f"{k}.pdf")} for k in ("id", "payslips", "bank_statements")],
                     created_at=(start - timedelta(days=20)).isoformat())
        lid = db.ins("leases", property_id=pid, tenant_id=tid, application_id=aid, start_date=start.isoformat(), end_date=end.isoformat(),
                     rent=rent_now, base_rent=base, deposit=base, escalation_pct=8, due_day=1 if pi % 3 else 3, status="active",
                     terms=sv.LEASE_TERMS, tenant_sig=signature(str(tid)), tenant_signed_at=(start - timedelta(days=9)).isoformat(),
                     landlord_sig=signature(str(p["landlord_id"])), landlord_signed_at=(start - timedelta(days=8)).isoformat(),
                     created_at=(start - timedelta(days=10)).isoformat())
        db.upd("properties", pid, listing_status="let", available_from=None)
        leases[pi] = lid
        sd = start.isoformat()
        insp = fees.inspection_fee(p["bedrooms"], p["bathrooms"])
        sv.post("tenant", "deposit_charge", base, pid, lid, "Deposit", sd)
        sv.post("tenant", "key_deposit_charge", 500, pid, lid, "Key deposit", sd)
        sv.post("tenant", "fee_charge", insp / 2, pid, lid, "Inspection fee (tenant 50%)", sd)
        sv.post("deposit", "deposit_received", base + 500, pid, lid, "Deposit received into trust", sd)
        sv.post("tenant", "payment", -(base + 500 + insp / 2), pid, lid, "Move-in payment (EFT)", sd)
        sv.post("ava", "tenant_fee_received", insp / 2, pid, lid, "Tenant fees received", sd)
        if start >= HIST_FROM:   # older move-in fees were settled before the history window
            sv.post("owner", "admin_fee", -500, pid, lid, "AVA admin fee (new contract)", sd)
            sv.post("owner", "inspection_fee", -insp / 2, pid, lid, "Inspection fee (landlord 50%)", sd)
        # monthly history: the last 12 months (or since move-in)
        for m in months_between(max(start, HIST_FROM), TODAY):
            per = m.isoformat()[:7]
            rent_this = base if m < anniversary.replace(day=1) else rent_now
            month_rent, desc, when = sv.month_rent({"rent": rent_this, "start_date": start.isoformat(), "end_date": end.isoformat()}, per)
            sv.post("tenant", "rent_charge", month_rent, pid, lid, desc, when, per)
            cur = per == TODAY.isoformat()[:7]
            if cur and beh in ("arrears",):
                continue
            if cur and beh == "partial":
                amt = db.rands(month_rent * 0.55)
            else:
                amt = month_rent
            day = min(28, 1 + random.randint(0, 3) + (9 if beh == "late" else 0))
            if cur:
                day = 1 if beh in ("good", "partial") else day
                if m.replace(day=day) > TODAY:
                    continue
            pd = max(m.replace(day=day), start).isoformat()
            sv.post("tenant", "payment", -amt, pid, lid, "Payment received (EFT)", pd, per, ref=f"AVA{lid:05d}")
            sv.post("owner", "rent_received", amt, pid, lid, f"Rent received {db.month_name(per)}", pd, per)
            db.ins("payments", lease_id=lid, amount=amt, method=random.choice(["eft", "eft", "debit_order", "card"]), reference=f"AVA{lid:05d}",
                   status="complete", created_at=pd + "T09:30:00")
        # deposit interest
        for m in months_between(start, TODAY)[1:]:
            sv.post("deposit", "deposit_interest", round((base + 500) * 0.05 / 12, 2), pid, lid, "Interest on deposit", m.isoformat(), m.isoformat()[:7])
    # owner payouts for past months
    for m in months_between(HIST_FROM, (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1) - timedelta(days=1)):
        per = m.isoformat()[:7]
        for pid in P:
            if db.val("SELECT 1 FROM ledger WHERE property_id=? AND kind='rent_received' AND period=?", pid, per):
                payday = min((m + timedelta(days=32)).replace(day=7), TODAY).isoformat()
                res = sv.payout_run(pid, per)
                db.exe("UPDATE ledger SET date=? WHERE property_id=? AND period=? AND kind IN ('ava_fee','pm_commission','insurance','payout','commission','finders_fee','fee_income') AND date=?",
                       payday, pid, per, db.today())
    # last month: leave Pieter's payouts unrun so the autopilot raises a task
    db.exe("DELETE FROM notifications")
    db.exe("DELETE FROM activity")

    # richer Property24-style attributes: erf size, extra features, publish dates
    extras = ["Study", "Flatlet", "Air conditioning", "Garage", "Security estate", "Water tank", "Wheelchair accessible", "Built-in braai", "Double garage"]
    for pid in P:
        p = sv.prop(pid)
        f = list(p["features"] or [])
        if p["type"] in ("House", "Cottage"):     # a stand comfortably bigger than the house on it
            db.upd("properties", pid, erf_size=random.choice([e for e in (450, 600, 800, 1000, 1250, 1500, 2000) if e >= p["size_m2"] * 2.2] or [2500]))
        elif p["type"] == "Townhouse":
            db.upd("properties", pid, erf_size=random.choice([e for e in (250, 320, 400, 500) if e >= p["size_m2"] * 1.4] or [600]))
        for e in random.sample(extras, random.randint(1, 3)):
            if e == "Study" and p["bedrooms"] < 3: continue
            if e in ("Flatlet",) and p["type"] != "House": continue
            if e not in f: f.append(e)
        db.upd("properties", pid, features=f)

    # live listings (vacant)
    live = [9, 13, 15, 18, 20, 21, 24]
    for k, pi in enumerate(live):
        db.upd("properties", P[pi], listing_status="live", available_from=(TODAY + timedelta(days=random.choice([0, 7, 14, 30]))).isoformat(),
               featured=1 if pi in (9, 18) else 0, views=random.randint(40, 600),
               published_at=(datetime.now() - timedelta(days=[0, 1, 3, 6, 12, 20, 35][k], hours=random.randint(1, 9))).isoformat(timespec="seconds"))
    db.upd("properties", jac, listing_status="live", available_from=(TODAY + timedelta(days=16)).isoformat(), featured=1, views=812,
           published_at=(datetime.now() - timedelta(days=2)).isoformat(timespec="seconds"))
    db.upd("properties", P[1], featured=0)

    # ---------------------------------------------------------- Jacaranda: ingoing (final) + outgoing (in progress)
    jl = leases[0]
    ing_date = db.val("SELECT start_date FROM leases WHERE id=?", jl)
    iid = db.ins("inspections", property_id=jac, lease_id=jl, type="ingoing", date=ing_date, status="final", inspector_id=thandi,
                 tenant_present=1, summary="House handed over clean and freshly painted. Fireplace grate present. 3 sets of keys, 2 gate remotes.",
                 tenant_sig=signature("lerato"), tenant_signed_at=ing_date + "T10:40:00", agent_sig=signature("thandi"),
                 agent_signed_at=ing_date + "T10:42:00", finalised_at=ing_date + "T10:45:00")
    room_codes = {"Entrance": "011", "Lounge": "001", "Dining room": "003", "Kitchen": "008", "Bedroom 1": "004", "Passage": "010", "Laundry": "035"}
    rooms = ["Entrance", "Lounge", "Dining room", "Kitchen", "Bedroom 1", "Bedroom 2", "Bedroom 3", "Bathroom 1", "Bathroom 2", "Passage", "Laundry",
             "Garden & exterior", "Keys & meters"]
    ing_items = {}
    for k, room in enumerate(rooms):
        code = room_codes.get(room)
        rid = db.ins("insp_rooms", inspection_id=iid, name=room, sort=k, pano_url=pano_url.get(code) if code else None)
        for j, it in enumerate(sv.items_for(room) if room != "Passage" else ["Walls", "Ceiling", "Floor", "Light fittings", "Linen cupboard"]):
            cond = random.choice([1, 1, 2, 2, 2]) if it not in ("Keys handed over",) else 1
            note = {"Floor": "Sealed wooden floor, light wear", "Walls": "Freshly painted", "Keys handed over": "3 sets front door, 2 security gate",
                    "Remotes / tags": "2 gate remotes", "Prepaid electricity units": "142 kWh", "Water meter reading": "04512 kl"}.get(it)
            photos = [random.choice(photo_pool)] if code and j < 3 else []
            iid_ = db.ins("insp_items", room_id=rid, inspection_id=iid, name=it, condition=cond, clean=1, working=1, notes=note, photos=photos, sort=j)
            ing_items[(room, it)] = iid_
    out_id = db.ins("inspections", property_id=jac, lease_id=jl, type="outgoing", date=(TODAY + timedelta(days=11)).isoformat(), status="draft",
                    inspector_id=thandi, compare_to_id=iid, tenant_present=1)
    damage = {"Lounge": "scuff", "Dining room": "stain", "Bedroom 1": "crack"}
    for k, room in enumerate(rooms):
        code = room_codes.get(room)
        purl = (pano_copy(code, damage[room]) if room in damage else pano_url[code]) if code else None
        rid = db.ins("insp_rooms", inspection_id=out_id, name=room, sort=k, pano_url=purl if k < 6 else None)
        for j, it in enumerate(sv.items_for(room) if room != "Passage" else ["Walls", "Ceiling", "Floor", "Light fittings", "Linen cupboard"]):
            kw = {}
            if k < 5:
                prev = db.val("SELECT condition FROM insp_items WHERE id=?", ing_items[(room, it)])
                kw = dict(condition=prev, clean=1, working=1)
                if room == "Lounge" and it == "Walls":
                    kw = dict(condition=4, clean=1, working=1, notes="Scuffs and 5 nail holes on east wall (picture hooks). Not fair wear and tear.",
                              pin={"yaw": -36, "pitch": -2}, charge=1450, charge_to="tenant")
                if room == "Dining room" and it == "Ceiling":
                    kw = dict(condition=4, clean=1, working=1, notes="Water stain ~0.8 m² near cornice – roof leak (landlord, not tenant).",
                              pin={"yaw": 44, "pitch": 34}, charge=2800, charge_to="landlord")
                if room == "Bedroom 1" and it == "Walls":
                    kw = dict(condition=3, clean=1, working=1, notes="Hairline settlement crack above door – fair wear and tear.", pin={"yaw": -125, "pitch": 30})
                if room == "Kitchen" and it == "Oven":
                    kw = dict(condition=3, clean=0, working=1, notes="Oven not cleaned – grease build-up.", charge=450, charge_to="tenant")
            db.ins("insp_items", room_id=rid, inspection_id=out_id, name=it, sort=j, **kw)
    db.exe("UPDATE leases SET end_date=? WHERE id=?", (TODAY + timedelta(days=13)).isoformat(), jl)
    db.ins("messages", thread=f"lease:{jl}", from_id=tenants[0], body="Hi Thandi, as discussed I'm moving to Cape Town for work, so I won't renew. Can we do the outgoing inspection on the 13th?", created_at=(TODAY - timedelta(days=30)).isoformat())
    db.ins("messages", thread=f"lease:{jl}", from_id=thandi, body="Thanks Lerato – noted. I've booked the outgoing inspection; you'll get a reminder. Please fill the nail holes or we'll have to deduct.", created_at=(TODAY - timedelta(days=29)).isoformat())

    # ---------------------------------------------------------- maintenance in every state
    def T(pi, title, desc, room, status, contractor=None, cost=None, days=3, quotes=None, rating=None, responsible=None, pid=None):
        pid = pid or P[pi]
        lid = leases.get(pi)
        tri = __import__("server.ai", fromlist=["triage"]).triage(title, desc)
        created = (datetime.now() - timedelta(days=days, hours=random.randint(1, 8))).isoformat(timespec="seconds")
        tid = db.ins("tickets", ref=sv.next_ref("tickets", "MR"), property_id=pid, lease_id=lid,
                     reported_by=db.val("SELECT tenant_id FROM leases WHERE id=?", lid) if lid else thandi, title=title, description=desc,
                     room=room, category=tri["category"], trade=tri["trade"], priority=tri["priority"], responsible=responsible or tri["responsible"],
                     sentiment=tri["sentiment"], status=status, contractor_id=contractor, cost=cost, created_at=created, updated_at=created,
                     ai_notes="; ".join(tri["why"]), photos=[random.choice(photo_pool)],
                     completed_at=(datetime.now() - timedelta(days=max(0, days - 2))).isoformat(timespec="seconds") if status in ("completed", "closed") else None,
                     scheduled_for=(datetime.now() + timedelta(days=1)).replace(hour=9, minute=0).isoformat(timespec="minutes") if status == "scheduled" else None,
                     quote_deadline=(datetime.now() + timedelta(hours=20)).isoformat(timespec="minutes") if status == "quoting" else None)
        sv.event(tid, db.val("SELECT reported_by FROM tickets WHERE id=?", tid), "created", f"Logged: {title}")
        db.exe("UPDATE ticket_events SET created_at=? WHERE ticket_id=?", created, tid)
        sv.event(tid, None, "ai", f"AVA triage: {tri['category']} · {tri['priority']} · {tri['trade']}. " + "; ".join(tri["why"]), internal=1)
        for cid, amt, st in quotes or []:
            from .marketplace import km as _km
            _c = db.q1("SELECT lat, lng FROM contractors WHERE user_id=?", cid); _p = sv.prop(pid)
            db.ins("quotes", ticket_id=tid, contractor_id=cid, amount=amt, eta_days=random.randint(1, 4), status=st, distance_km=_km(_p["lat"], _p["lng"], _c["lat"], _c["lng"]),
                   notes=random.choice(["Includes parts and labour.", "Callout included. 3-month guarantee.", "Excl. any hidden damage found."]) if amt else None,
                   submitted_at=db.now() if amt else None)
        if status in ("completed", "closed") and cost:
            sv.settle_ticket(tid)
        if rating and contractor:
            db.ins("reviews", target_type="contractor", target_id=contractor, author_id=db.val("SELECT reported_by FROM tickets WHERE id=?", tid), rating=rating, ticket_id=tid, text="Sorted quickly, thanks!")
        return tid

    T(5, "Geyser burst – water coming through the ceiling", "Water is pouring out of the ceiling in the passage! Please help urgently", "Passage", "approved", CON["plumbfix"], None, 0)
    t2 = T(6, "Kitchen tap dripping constantly", "The mixer tap drips even when closed tight.", "Kitchen", "quoting", days=1,
           quotes=[(CON["plumbfix"], 850, "submitted"), (CON["aquaflow"], 690, "submitted"), (CON["handy"], None, "requested")])
    t3 = T(2, "Damp patch and mould on bedroom ceiling", "There is a growing damp patch with black mould above the window.", "Bedroom", "awaiting_approval", days=4,
           quotes=[(CON["roof"], 4200, "shortlisted"), (CON["handy"], 3600, "shortlisted"), (CON["tile"], 5100, "shortlisted")])
    from .ai import rank_quotes
    for q in rank_quotes(db.q("""SELECT q.*, (SELECT AVG(rating) FROM reviews r WHERE r.target_type='contractor' AND r.target_id=q.contractor_id) rating FROM quotes q WHERE ticket_id=?""", t3)):
        db.upd("quotes", q["id"], rank_score=q["rank_score"])
    T(10, "Stove plate not working", "Front left plate on the stove doesn't heat up.", "Kitchen", "scheduled", CON["sparkpro"], 780, 3)
    T(11, "Garage door motor stuck", "Gate/garage motor makes a noise but door won't open.", "Garage", "in_progress", CON["lock"], 1250, 2)
    T(12, "Bathroom extractor fan noisy", "Rattles loudly.", "Bathroom", "completed", CON["handy"], 620, 6)
    T(14, "Blocked toilet in main bathroom", "Toilet is blocked and overflowing a bit.", "Bathroom 1", "closed", CON["plumbfix"], 950, 20, rating=5)
    T(16, "Light fitting in lounge flickers", "", "Lounge", "closed", CON["sparkpro"], 540, 35, rating=4)
    T(17, "Still no hot water – third time I'm reporting this!", "This is unacceptable, nobody has come out and I have kids. Geyser keeps tripping.", "Bathroom", "new", days=0)
    T(8, "Pool pump leaking", "Small leak at the pump housing.", "Garden & exterior", "closed", CON["aquaflow"], 1900, 50, rating=3)
    T(1, "Broken window pane – my son kicked a ball through it", "Accidentally broke the lounge window, sorry!", "Lounge", "closed", CON["handy"], 1150, 25, rating=5, responsible="tenant")
    T(19, "Ants in kitchen", "Lots of ants along the counter.", "Kitchen", "closed", CON["handy"], 4800, 60, rating=4)
    # open jobs on the maintenance job map ("Browse jobs"): some with room for more quotes, one that nobody has quoted yet
    R_ = "requested"
    T(1, "Shower mixer leaking behind the wall", "Water stain spreading on the passage side of the shower wall.", "Bathroom", "quoting", days=1,
      quotes=[(CON["aquaflow"], None, R_), (CON["pipedreams"], None, R_)])
    T(3, "Bathroom wall tiles cracked and loose", "Three tiles above the bath are cracked and two are loose.", "Bathroom", "quoting", days=2,
      quotes=[(CON["tile"], None, R_)])
    T(4, "Gutter leaking over the front door", "When it rains the gutter overflows right at the front door.", "Garden & exterior", "quoting", days=1,
      quotes=[(CON["roof"], 1850, "submitted"), (CON["jacarandapaint"], None, R_)])
    T(7, "Geyser making a banging noise", "Loud banging from the geyser in the roof when the water heats up.", "Roof", "quoting", days=0,
      quotes=[(CON["plumbfix"], None, R_), (CON["aquaflow"], 980, "submitted")])
    T(8, "Plug point sparks when used", "The plug next to the kitchen counter sparks when the kettle is plugged in.", "Kitchen", "quoting", days=0,
      quotes=[(CON["sparkpro"], None, R_), (CON["eastsideelec"], None, R_)])
    T(11, "Garden tap leaking at the wall", "Outside tap drips constantly and the wall below is wet.", "Garden & exterior", "new", days=1)
    T(14, "Toilet cistern keeps running", "The toilet keeps refilling all night.", "Bathroom", "quoting", days=1,
      quotes=[(CON["lonehillplumb"], None, R_)])
    T(22, "Damp patch on bedroom wall", "Damp and peeling paint on the outside wall of the main bedroom.", "Bedroom", "quoting", days=2,
      quotes=[(CON["capewaterproof"], None, R_)])
    # a farm outside town: no listed company within 10 km, so the owner/PM can extend the range in one tap
    far = db.val("SELECT id FROM properties WHERE title='Dullstroom Trout Farm Cottage'")
    if far:
        db.upd("properties", far, pm_id=thandi, landlord_id=landlords[0])
        tf = T(None, "Kitchen sink drain blocked", "The kitchen sink drains very slowly and smells. Plunger didn't help.", "Kitchen", "quoting", days=0, pid=far)
        db.exe("DELETE FROM quotes WHERE ticket_id=?", tf)
        sv.dispatch(db.q1("SELECT * FROM tickets WHERE id=?", tf), sv.prop(far))

    # ---------------------------------------------------------- snag list project
    si = db.ins("inspections", property_id=proj, type="snag", date=(TODAY - timedelta(days=24)).isoformat(), status="final", inspector_id=thandi,
                round=1, tenant_present=0, summary="Practical completion snag list, round 1. Joint inspection with site agent (Menlo Mews Developments).",
                agent_sig=signature("thandi"), agent_signed_at=(TODAY - timedelta(days=24)).isoformat() + "T15:00:00",
                contractor_sig=signature("devco"), contractor_signed_at=(TODAY - timedelta(days=24)).isoformat() + "T15:05:00",
                finalised_at=(TODAY - timedelta(days=24)).isoformat() + "T15:10:00")
    srooms = {}
    for k, (room, code) in enumerate([("Entrance", "011"), ("Lounge", "001"), ("Dining room", "003"), ("Kitchen", "034"), ("Bedroom 1", "004"),
                                      ("Passage", "010"), ("Scullery", "035"), ("Bathroom 1", None), ("Exterior", None)]):
        srooms[room] = db.ins("insp_rooms", inspection_id=si, name=room, sort=k, pano_url=pano_url.get(code) or (pano_copy(code) if code else None))
    snaglist = [
        # room, title, cat, trade, contractor, priority, qty, unit, rate, status, days_raised_ago, rework, pin
        ("Lounge", "Paint drips and roller marks on east wall", "Workmanship", "Painter / builder", CON["handy"], "Low", 12, "m²", 65, "closed", 24, 0, (-40, 5)),
        ("Lounge", "Skirting gap 4 mm at window wall", "Workmanship", "Carpentry", CON["handy"], "Low", 3.2, "m", 120, "closed", 24, 1, (20, -30)),
        ("Lounge", "Burglar bar weld not ground smooth", "Workmanship", "Handyman", CON["handy"], "Medium", 2, "no.", 180, "ready", 24, 0, (-70, 0)),
        ("Dining room", "Cornice joint cracked above door", "Workmanship", "Painter / builder", CON["handy"], "Low", 1.5, "m", 140, "open", 24, 0, (95, 30)),
        ("Kitchen", "Countertop joint not sealed at sink", "Workmanship", "Tiler", CON["tile"], "Medium", 1.2, "m", 220, "closed", 24, 0, (40, -20)),
        ("Kitchen", "Oven isolator not labelled at DB", "Non-conformance", "Electrician", CON["sparkpro"], "High", 1, "no.", 150, "closed", 24, 0, (-20, -5)),
        ("Kitchen", "Cupboard door misaligned (2 no.)", "Workmanship", "Carpentry", CON["handy"], "Low", 2, "no.", 90, "open", 24, 1, (130, -15)),
        ("Bedroom 1", "Floor tile cracked near built-in cupboard", "Workmanship", "Tiler", CON["tile"], "Medium", 1, "no.", 380, "open", 24, 0, (10, -55)),
        ("Bedroom 1", "Window handle loose", "Workmanship", "Handyman", CON["handy"], "Low", 1, "no.", 80, "closed", 24, 0, (-90, 0)),
        ("Passage", "Light switch cover plate missing", "Non-conformance", "Electrician", CON["sparkpro"], "High", 1, "no.", 60, "closed", 24, 0, (60, -5)),
        ("Scullery", "Waste pipe weeping under sink", "Workmanship", "Plumber", CON["plumbfix"], "High", 1, "no.", 450, "in_progress", 24, 0, (-60, -40)),
        ("Bathroom 1", "Shower screen silicone incomplete", "Workmanship", "Tiler", CON["tile"], "Medium", 2.4, "m", 55, "open", 24, 0, None),
        ("Bathroom 1", "Hot water < 50 °C at basin (SANS 10254 setting)", "Non-conformance", "Plumber", CON["plumbfix"], "High", 1, "no.", 0, "ready", 24, 0, None),
        ("Exterior", "Downpipe not connected to stormwater", "Workmanship", "Roofer / waterproofer", CON["roof"], "Medium", 1, "no.", 350, "open", 24, 0, None),
        ("Exterior", "Unprotected trench at boundary wall (open excavation)", "Health & safety", "Painter / builder", CON["handy"], "Urgent", 6, "m", 0, "closed", 24, 0, None),
        ("Entrance", "Front door threshold sealant missing", "Workmanship", "Handyman", CON["handy"], "Medium", 1, "m", 95, "open", 10, 0, (0, -40)),
    ]
    for room, title, cat, trade, cid, pri, qty, unit, rate, st, ago, rework, pin in snaglist:
        raised = TODAY - timedelta(days=ago)
        due = raised + timedelta(days=fees.S("snag_due_days")[pri])
        n = (db.val("SELECT COUNT(*) FROM snags WHERE property_id=?", proj) or 0) + 1
        prefix = "HS" if cat == "Health & safety" else "NCR" if cat == "Non-conformance" else "SN"
        closed_at = (raised + timedelta(days=random.randint(3, 12))).isoformat() + "T12:00:00" if st == "closed" else None
        code = {"Lounge": "001", "Dining room": "003", "Kitchen": "034", "Bedroom 1": "004", "Passage": "010", "Scullery": "035", "Entrance": "011"}.get(room)
        before = []
        if pin and code:
            src = Image.open(PANOS / f"{code}.jpg").convert("RGB")
            before = [save_img(perspective(src, pin[0], pin[1], 55, 900, 640), "snags", f"s{proj}_{n}.jpg")]
        db.ins("snags", ref=f"{prefix}-{proj:03d}-{n:03d}", property_id=proj, inspection_id=si, room=room, room_id=srooms[room],
               pin={"yaw": pin[0], "pitch": pin[1]} if pin else None, title=title, category=cat, trade=trade, contractor_id=cid,
               priority=pri, qty=qty, unit=unit, rate=rate or None, due_date=due.isoformat(), status=st, rework_count=rework,
               raised_at=raised.isoformat() + "T15:00:00", closed_at=closed_at, closed_by=thandi if closed_at else None,
               ready_at=(TODAY - timedelta(days=1)).isoformat() + "T10:00:00" if st == "ready" else None,
               contractor_note="Fixed, please check." if st == "ready" else ("Rework: still misaligned at 2nd inspection" if rework and st == "open" else None),
               photos_before=before, photos_after=before if st in ("closed", "ready") else [])
    sv.create_inspection(proj, "reinspection", inspector_id=thandi, date_=(TODAY + timedelta(days=2)).isoformat())
    si2 = sv.create_inspection(proj2, "snag", inspector_id=thandi, date_=(TODAY + timedelta(days=5)).isoformat())

    # ---------------------------------------------------------- pipeline: applications + viewings
    for pi, ti, inc, docs, cs in [(9, 19, 98000, 3, 742), (9, 20, 61000, 2, None), (18, 21, 52000, 3, 688), (13, 22, 41000, 1, None), (0, 23, 88000, 3, 715)]:
        pid = P[pi]
        a = db.ins("applications", property_id=pid, user_id=tenants[ti], name=db.val("SELECT name FROM users WHERE id=?", tenants[ti]),
                   email=db.val("SELECT email FROM users WHERE id=?", tenants[ti]), phone="072 000 1234",
                   employer=random.choice(["PwC", "Discovery", "Sasol", "University of Pretoria", "Own business"]), income=inc, occupants=random.randint(1, 3),
                   move_in=(TODAY + timedelta(days=20)).isoformat(), message="Hi, I love the house and can move in at the start of next month.",
                   docs=[{"kind": k, "url": demo_pdf(f"{k}.pdf")} for k in ("id", "payslips", "bank_statements")[:docs]],
                   credit_score=cs, rental_history="Good – paid on time (TPN rental profile)" if cs else None, status="submitted",
                   created_at=(datetime.now() - timedelta(hours=random.randint(2, 60))).isoformat(timespec="seconds"))
    for pi in (9, 18, 0, 13, 20):
        for k in range(random.randint(1, 3)):
            d = TODAY + timedelta(days=random.randint(0, 6))
            ti = random.randint(19, 23)
            db.ins("viewings", property_id=P[pi], user_id=tenants[ti], name=db.val("SELECT name FROM users WHERE id=?", tenants[ti]),
                   email=db.val("SELECT email FROM users WHERE id=?", tenants[ti]), slot=f"{d.isoformat()}T{random.choice(['09:00', '10:00', '16:30', '17:15'])}",
                   status="confirmed")

    # ---------------------------------------------------------- conversations
    db.ins("messages", thread=f"owner:{P[2]}", from_id=landlords[2], body="Hi Thandi, please go ahead with the cheapest reasonable quote for the damp – just make sure they fix the cause, not only paint over it.")
    db.ins("messages", thread=f"lease:{leases[17]}", from_id=tenants[14], body="Morning, the hot water is still not working. This is the third time and nobody came. Really fed up!", sentiment="negative")
    db.ins("messages", thread=f"lease:{leases[7]}", from_id=tenants[7], body="Hi, I paid half the rent today, the rest will come on the 15th when I get my bonus. Sorry!")
    db.ins("messages", thread=f"owner:{P[4]}", from_id=landlords[4], body="Is the tenant renewing at Waterkloof Heights? I'd like to keep them if possible.")

    # ---------------------------------------------------------- AVA Learn badges (kept as settings for the demo)
    # ---------------------------------------------------------- virtual agent history
    from . import agent
    for sess, pid, lines in [("v1", jac, ["What does it cost to move in?", "Is there backup power for load shedding?", "I earn R72 000, can I afford it?", "When can I view it?"]),
                             ("v2", P[9], ["Are pets allowed?", "Speak to a person"]), ("v3", None, ["3 bed in Pretoria with a pool under 25k"]),
                             ("v4", P[18], ["How big is it and is there parking?", "Show me similar homes"])]:
        for line in lines:
            agent.respond(None, line, {"property_id": pid, "session": sess})
    lu = db.q1("SELECT * FROM users WHERE id=?", tenants[1])
    for line in ("What do I owe?", "Status of my repair"):
        agent.respond(lu, line, {"session": "t1"})
    # trust accounting: a year of payouts, fee transfers, bank feed, reconciliations, locked months, debit orders
    from . import trust
    behaviour = {leases[pi]: beh for pi, _, _, _, beh in lease_plan if pi in leases}
    tb = trust.bootstrap_demo(admin, behaviour)
    print(f"  trust: cash R{tb['trust']['cash']:,.0f} = liabilities R{tb['trust']['liabilities']:,.0f} · deposits R{tb['deposit']['cash']:,.0f}")
    from . import seed_growth
    gr = seed_growth.run(admin, thandi, pieter)
    print(f"  growth: {gr}")
    db.set_setting("demo_seeded", db.now())
    db.set_setting("demo_version", DEMO_VERSION)
    res = automation.tick()
    db.exe("DELETE FROM notifications WHERE created_at < ?", (datetime.now() - timedelta(minutes=5)).isoformat())
    for uid, title, body, link in [
        (thandi, "Morning brief", "3 arrears, 1 emergency dispatched, 2 quotes ready for landlords, 2 snags ready to verify.", "#/app"),
        (tenants[0], "Outgoing inspection booked", "Your outgoing inspection is booked. We'll compare with your 360° ingoing report.", "#/app"),
        (landlords[2], "Approve a repair quote", "Damp patch and mould on bedroom ceiling – 3 quotes shortlisted", f"#/app/ticket/{t3}"),
    ]:
        sv.notify(uid, title, body, link)
    print("  autopilot:", res)
    print("Done. Sign in with any of:")
    for e in ("thandi@ava.co.za (portfolio manager)", "emgee@example.co.za (landlord)", "lerato@example.com (tenant)",
              "plumbfix@example.co.za (contractor)", "admin@ava.co.za (admin)"):
        print("   ", e, " / demo1234")


if __name__ == "__main__":
    run("--reset" in sys.argv)
