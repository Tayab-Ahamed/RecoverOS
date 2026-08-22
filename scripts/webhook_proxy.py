"""Expose only the Razorpay webhook route to a public tunnel."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


BACKEND = "http://127.0.0.1:8000/api/webhooks/razorpay"


class WebhookOnlyHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        if self.path.split("?", 1)[0] != "/api/webhooks/razorpay":
            self.send_error(404, "Only the Razorpay webhook route is exposed")
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        headers = {"Content-Type": self.headers.get("Content-Type", "application/json")}
        signature = self.headers.get("X-Razorpay-Signature")
        if signature:
            headers["X-Razorpay-Signature"] = signature
        event_id = self.headers.get("X-Razorpay-Event-Id")
        if event_id:
            headers["X-Razorpay-Event-Id"] = event_id
        request = Request(BACKEND, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=15) as response:
                payload = response.read()
                self.send_response(response.status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                self.end_headers()
                self.wfile.write(payload)
        except HTTPError as error:
            payload = error.read()
            self.send_response(error.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
        except URLError:
            self.send_error(502, "Backend unavailable")

    def do_GET(self):  # noqa: N802
        self.send_error(404, "Only the Razorpay webhook route is exposed")

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8765), WebhookOnlyHandler)
    print("Webhook-only proxy listening on http://127.0.0.1:8765", flush=True)
    server.serve_forever()
