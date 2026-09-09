"""Loopback-only static preview. Never serve source files or directory listings."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class PreviewHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.webp': 'image/webp', '.avif': 'image/avif', '.svg': 'image/svg+xml', '.woff2': 'font/woff2'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_head(self):
        parts = Path(unquote(urlsplit(self.path).path)).parts
        if any(p.startswith('.') or p in {'tools', 'reports', 'node_modules', 'tmp', 'test-results'} for p in parts):
            self.send_error(404)
            return None
        return super().send_head()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 4315), PreviewHandler)
    print('Local preview: http://127.0.0.1:4315/', flush=True)
    server.serve_forever()
