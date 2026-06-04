import http.client
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


BACKEND_HOST = os.getenv("APP_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("APP_PORT", "5000"))
PROXY_HOST = os.getenv("PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.getenv("PROXY_PORT", "8080"))

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


class ProxyProtocolHTTPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.real_client_ip = self.client_address[0]
        self._prefetched_request_line = self.rfile.readline(65537)

        if self._prefetched_request_line.startswith(b"PROXY "):
            parts = self._prefetched_request_line.decode("ascii", "replace").strip().split()
            if len(parts) >= 6:
                self.real_client_ip = parts[2]
            self._prefetched_request_line = self.rfile.readline(65537)

    def handle_one_request(self):
        try:
            if self._prefetched_request_line:
                self.raw_requestline = self._prefetched_request_line
                self._prefetched_request_line = b""
            else:
                self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = ""
                self.request_version = ""
                self.command = ""
                self.send_error(414)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                return
            method_name = "do_" + self.command
            if not hasattr(self, method_name):
                self.send_error(501, f"Unsupported method ({self.command!r})")
                return
            getattr(self, method_name)()
            self.wfile.flush()
        except TimeoutError as exc:
            self.log_error("Request timed out: %r", exc)
            self.close_connection = True
            return

    def do_GET(self):
        self.forward_request()

    def do_PUT(self):
        self.forward_request()

    def do_PATCH(self):
        self.forward_request()

    def do_DELETE(self):
        self.forward_request()

    def do_HEAD(self):
        self.forward_request()

    def do_OPTIONS(self):
        self.forward_request()

    def do_POST(self):
        if self.path == "/__shutdown__":
            self.handle_shutdown_request()
            return
        self.forward_request()

    def forward_request(self):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        request_body = self.rfile.read(content_length) if content_length else None

        forward_headers = {}
        for key, value in self.headers.items():
            if key.lower() in HOP_BY_HOP_HEADERS:
                continue
            forward_headers[key] = value

        forward_headers["X-Forwarded-For"] = self.real_client_ip
        forward_headers["X-Real-IP"] = self.real_client_ip
        forward_headers["X-Forwarded-Proto"] = "https"
        forward_headers["X-Forwarded-Host"] = self.headers.get("Host", "")

        connection = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=300)
        try:
            connection.request(
                self.command,
                self.path,
                body=request_body,
                headers=forward_headers,
            )
            response = connection.getresponse()

            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() in HOP_BY_HOP_HEADERS:
                    continue
                self.send_header(key, value)

            if not any(key.lower() == "content-length" for key, _ in response.getheaders()):
                self.send_header("Connection", "close")
                self.close_connection = True

            self.end_headers()

            if self.command == "HEAD":
                return

            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except Exception as exc:
            self.send_error(502, f"Proxy error: {exc}")
        finally:
            connection.close()

    def handle_shutdown_request(self):
        if self.client_address[0] not in {"127.0.0.1", "::1"}:
            self.send_error(403, "Forbidden")
            return

        self.send_response(200, "Shutting down")
        self.send_header("Content-Length", "0")
        self.end_headers()
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, format_string, *args):
        print(
            "%s - - [%s] %s"
            % (
                self.real_client_ip,
                self.log_date_time_string(),
                format_string % args,
            )
        )


if __name__ == "__main__":
    print(f"Proxy listening on http://{PROXY_HOST}:{PROXY_PORT}")
    print(f"Forwarding traffic to http://{BACKEND_HOST}:{BACKEND_PORT}")
    print("Expecting Tailscale PROXY protocol v1 connections.")
    server = ThreadingHTTPServer((PROXY_HOST, PROXY_PORT), ProxyProtocolHTTPHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
