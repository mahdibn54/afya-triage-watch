"""Test-only HTTP fault boundary. No production service imports this module."""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

STATE = {"mode": "off", "method": "GET", "path": "", "remaining": 0, "matched": 0}
LOCK = threading.Lock()


class Proxy(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # no request bodies, headers or credentials in test logs

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_request(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/control":
            with LOCK:
                if self.command == "PUT":
                    STATE.update(mode="off", method="GET", path="", remaining=0, matched=0)
                    STATE.update(json.loads(body))
                snapshot = dict(STATE)
            return self.reply(200, snapshot)
        if self.path == "/healthz":
            return self.reply(200, {"group_a_fault_proxy": True})
        with LOCK:
            mode = "off"
            if (STATE["remaining"] > 0 and self.command == STATE["method"]
                    and self.path.split("?", 1)[0] == STATE["path"]):
                mode = STATE["mode"]
                STATE["remaining"] -= 1
                STATE["matched"] += 1
        if mode == "unavailable":
            return self.reply(503, {"resourceType": "OperationOutcome", "issue": [
                {"severity": "error", "code": "transient", "diagnostics": "Group A injected outage"}]})
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "content-length", "connection", "accept-encoding")}
        request = Request("http://hapi:8080" + self.path, data=body or None, headers=headers, method=self.command)
        try:
            response = urlopen(request, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            data, code = response.read(), response.code
            if mode == "lost_response" and 200 <= code < 300:
                # HAPI has committed the Flag; only its response is lost on the wire.
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(code)
            for key, value in response.headers.items():
                if key.lower() not in ("connection", "transfer-encoding", "content-length"):
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_request


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8081), Proxy).serve_forever()
