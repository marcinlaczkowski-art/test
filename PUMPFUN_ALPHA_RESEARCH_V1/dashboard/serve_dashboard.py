import http.server, socketserver, webbrowser
from pathlib import Path

PORT = 8765
DIRECTORY = Path(__file__).parent

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

if __name__ == "__main__":
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        url = f"http://127.0.0.1:{PORT}/index.html"
        print(f"Serving PUMPFUN ALPHA INTELLIGENCE Dashboard at {url}")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        httpd.serve_forever()
