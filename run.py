"""Start AVA:  python run.py  ->  http://localhost:8780
Set AVA_RESEED=1 (reset_demo.bat does) to rebuild the demo data first. The demo is also rebuilt
automatically when a newer demo version ships, as long as the database is still the demo one."""
import os
import socket
import sys
import time
import webbrowser

import uvicorn

# Cloud hosts (Render, Railway, Fly, Docker…) hand the app a port in $PORT; on a PC it is 8780.
PORT = int(os.environ.get("PORT") or os.environ.get("AVA_PORT") or 8780)
CLOUD = bool(os.environ.get("PORT")) or bool(os.environ.get("AVA_NO_BROWSER"))


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def port_busy():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def maybe_seed():
    from server import db, seed
    db.init()
    have = db.get_setting("demo_version")
    empty = not db.val("SELECT COUNT(*) FROM users")
    is_demo = db.get_setting("demo_seeded") is not None
    if os.environ.get("AVA_RESEED") or empty or (is_demo and have != seed.DEMO_VERSION):
        print("  Building the demo data (about 15 seconds)…")
        for attempt in range(5):
            try:
                seed.run(reset=True)
                return
            except PermissionError:
                print("  The database is still in use – waiting for the old server to close…")
                time.sleep(2)
        sys.exit("  Could not rebuild the demo: close any other AVA window and try again.")


if __name__ == "__main__":
    if CLOUD:   # on a server: build the demo if needed, then serve – no browser, no LAN hints
        maybe_seed()
        print(f"  AVA is running on port {PORT}")
        uvicorn.run("server.main:app", host="0.0.0.0", port=PORT, log_level="warning", proxy_headers=True, forwarded_allow_ips="*")
        sys.exit(0)
    if port_busy():
        print(f"\n  AVA is already running on port {PORT}. Close that window first (or open http://localhost:{PORT}).")
        if not os.environ.get("AVA_NO_BROWSER"):
            webbrowser.open(f"http://localhost:{PORT}")
        time.sleep(4)
        sys.exit(1)
    maybe_seed()
    print(f"\n  AVA is running:  http://localhost:{PORT}")
    print(f"  Phones on the same Wi-Fi:  http://{lan_ip()}:{PORT}   (open, then 'Add to Home screen')\n")
    if not os.environ.get("AVA_NO_BROWSER"):
        webbrowser.open(f"http://localhost:{PORT}")
    uvicorn.run("server.main:app", host="0.0.0.0", port=PORT, log_level="warning")
