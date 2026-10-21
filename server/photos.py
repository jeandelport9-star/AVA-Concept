"""Demo listing photos: free-to-use Unsplash images, picked by property type so every listing looks different.
They load from images.unsplash.com when online; the page falls back to local photos if a link fails."""
import random

U = "https://images.unsplash.com/{}?auto=format&fit=crop&w=1400&q=70"
HOUSE = ["photo-1721815693498-cc28507c0ba2", "photo-1628012209120-d9db7abf7eab", "photo-1698994705178-d244d73ea573", "photo-1600596542815-ffad4c1539a9",
         "photo-1558661091-5cc1b64d0dc5", "photo-1719887805632-de5be825f72b", "photo-1633354747567-e0682586f082", "photo-1580587771525-78b9dba3b914",
         "photo-1691425700585-c108acad6467", "photo-1613977257363-707ba9348227", "photo-1706808849802-8f876ade0d1f", "photo-1627141234469-24711efb373c",
         "photo-1660361339436-ddd4b85372da", "photo-1706808849780-7a04fbac83ef", "photo-1523217582562-09d0def993a6", "photo-1564013799919-ab600027ffc6",
         "photo-1613490493576-7fde63acd811", "photo-1670589953882-b94c9cb380f5", "photo-1711114378455-b1f479d94a19", "photo-1544984243-ec57ea16fe25",
         "photo-1711114435495-76503f9f3181", "photo-1721222205991-d74bcb224330", "photo-1623298460174-371443cc45f0", "photo-1602343168117-bb8ffe3e2e9f"]
FLAT = ["photo-1515263487990-61b07816b324", "photo-1545324418-cc1a3fa10c00", "photo-1624204386084-dd8c05e32226", "photo-1580216643062-cf460548a66a",
        "photo-1628592102751-ba83b0314276", "photo-1580041065738-e72023775cdc", "photo-1613575831056-0acd5da8f085", "photo-1488972685288-c3fd157d7c7a",
        "photo-1630699144867-37acec97df5a", "photo-1612320648993-61c1cd604b71", "photo-1556020685-ae41abfc9365", "photo-1665249934445-1de680641f50",
        "photo-1516501312919-d0cb0b7b60b8", "photo-1527465094057-db061fdbfaf7", "photo-1702014862053-946a122b920d"]
LIVING = ["photo-1583847268964-b28dc8f51f92", "photo-1631679706909-1844bbd07221", "photo-1618220179428-22790b461013", "photo-1616047006789-b7af5afb8c20",
          "photo-1598928506311-c55ded91a20c", "photo-1564078516393-cf04bd966897", "photo-1586023492125-27b2c045efd7", "photo-1605774337664-7a846e9cdf17",
          "photo-1632829882891-5047ccc421bc", "photo-1618221195710-dd6b41faaea6", "photo-1615800002234-05c4d488696c", "photo-1560448204-e02f11c3d0e2",
          "photo-1600121848594-d8644e57abab", "photo-1554995207-c18c203602cb", "photo-1560185007-cde436f6a4d0"]
KITCHEN = ["photo-1628797285815-453c1d0d21e3", "photo-1502005097973-6a7082348e28", "photo-1722605090433-41d1183a792d", "photo-1556912167-f556f1f39fdf",
           "photo-1663811396777-05505d999151", "photo-1635321350281-e2a91ecffd00", "photo-1725905803121-dd123b058a5c", "photo-1663811397261-916af74a9363",
           "photo-1687946939402-a02bfa7af289", "photo-1725257928373-dc6d2ac7b145"]
BEDROOM = ["photo-1649083048770-82e8ffd80431", "photo-1616594039964-ae9021a400a0", "photo-1649083048337-4aeb6dda80bb", "photo-1696762932825-2737db830bbe",
           "photo-1649083048597-d7b4f1e8a386", "photo-1616486029423-aaa4789e8c9a", "photo-1600210491305-7396500b5b31", "photo-1625334782252-da92af3ad887",
           "photo-1720420021124-4e18564e070f", "photo-1633948393301-d43e3ec0e5cd", "photo-1631048501851-4aa85ffc3be8", "photo-1632119580908-ae947d4c7691",
           "photo-1649083048428-3d8ed23a3ce0", "photo-1648634158203-199accfd7afc", "photo-1663811397207-418a92396ad5"]
BATH = ["photo-1620626011761-996317b8d101", "photo-1576698483491-8c43f0862543", "photo-1733426107854-ee00a25d72a7", "photo-1650894622076-e09ab837c502",
        "photo-1642755622932-d1e0cb783dc5", "photo-1643949700215-e61cdca053f7", "photo-1742134131017-44d377a611b1", "photo-1644421439741-712c7fde7e95",
        "photo-1691036365036-71da57ac5919", "photo-1737233523182-99e287258d58", "photo-1733425844220-feab971190ff", "photo-1722923400899-af08ffc715c6",
        "photo-1737233536991-8ee3f92b7781", "photo-1631889993959-41b4e9c6e3c5"]


def set_for(prop_type, n, seed):
    """Cover (exterior) + living, kitchen, bedroom(s), bathroom - like a real listing."""
    r = random.Random(seed)
    ext = FLAT if prop_type in ("Apartment", "Room", "Retirement") else HOUSE
    shots = [(r.choice(ext), "Exterior"), (r.choice(LIVING), "Lounge"), (r.choice(KITCHEN), "Kitchen"), (r.choice(BEDROOM), "Main bedroom"),
             (r.choice(BATH), "Bathroom"), (r.choice(LIVING), "Living area"), (r.choice(BEDROOM), "Bedroom 2")]
    if prop_type in ("House", "Townhouse", "Farm"):
        shots.insert(5, (r.choice(HOUSE), "Garden"))
    out, seen = [], set()
    for pid, cap in shots:
        if pid not in seen:
            seen.add(pid)
            out.append((U.format(pid), cap))
    return out[:n]
