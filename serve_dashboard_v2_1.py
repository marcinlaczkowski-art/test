"""
Local HTTP Server for PUMPFUN ALPHA RESEARCH V2.1 Interactive Dashboard.
Usage:
    python serve_dashboard_v2_1.py
Opens http://127.0.0.1:8788 in your default browser (or serves standalone without opening if `--no-browser` passed).
"""
import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path

PORT = 8788
DASH_DIR = Path(__file__).resolve().parent / "dashboard"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASH_DIR), **kwargs)


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}/index.html"
    print(f"Serving PUMPFUN ALPHA V2.1 Dashboard at {url}")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    with socketserver.TCPServer(("127.0.0.1", PORT), QuietHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped V2.1 dashboard server.")
