"""
Local HTTP Server for PUMPFUN ALPHA RESEARCH V2.2 7-View Dashboard.
Usage: python dashboard/serve_dashboard_v2_2.py
"""
import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path

PORT = 8789
DASH_DIR = Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASH_DIR), **kwargs)


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}/index.html"
    print(f"Serving V2.2 Dashboard at {url}")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        httpd.serve_forever()
