"""Local protocol demo. Its numbers are not model or hardware performance."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        payload = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            self.send_error(400)
            return
        body = json.dumps(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "Mock reply"}}
                ],
                "usage": {"completion_tokens": 2},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Synthetic demo endpoint: http://127.0.0.1:8000/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
