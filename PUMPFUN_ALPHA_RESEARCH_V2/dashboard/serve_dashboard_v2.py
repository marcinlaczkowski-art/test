import http.server, socketserver, webbrowser
from pathlib import Path
PORT = 8766
DIR = Path(__file__).parent
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw): super().__init__(*a, directory=str(DIR), **kw)
if __name__ == "__main__":
    with socketserver.TCPServer(("127.0.0.1", PORT), H) as s:
        print(f"Serving V2 Dashboard at http://127.0.0.1:{PORT}/index.html")
        try: webbrowser.open(f"http://127.0.0.1:{PORT}/index.html")
        except Exception: pass
        s.serve_forever()
