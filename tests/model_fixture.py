"""One local deterministic provider, configured in the project mdo itself."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading


class Model(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(value)
        text = f"member result {len(self.server.requests)}"
        chunks = [
            {"id": "mohists-test", "model": "mohists-local", "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}}]},
            {"id": "mohists-test", "model": "mohists-local", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}}]
        data = ("".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class LocalModel:
    def __enter__(self):
        self.server = HTTPServer(("127.0.0.1", 0), Model)
        self.server.requests = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def configure(self, call):
        cfg = call("product.models.config.get")
        patch = {k: v for k, v in cfg["data"].items() if k != "runtime_override"}
        patch["providers"] = [p for p in patch["providers"] if p["id"] != "mohists-local"]
        patch["providers"].append({"id": "mohists-local", "name": "Mohists local fixture", "builtin": False,
            "editable": True, "removable": True, "verify_peer": True, "timeout_ms": 5000,
            "endpoints": {"chat_completions": f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions"}})
        template = next(m for m in patch["items"] if m["id"] == "ornith-1.5-35b").copy()
        template.update({"id": "mohists-local", "name": "Mohists local fixture", "provider": "mohists-local",
            "wire_model": "mohists-local", "builtin": False, "free": False, "editable": True, "removable": True,
            "protocols": ["openai-chat-completions"], "default_protocol": "openai-chat-completions"})
        patch["items"] = [m for m in patch["items"] if m["id"] != "mohists-local"] + [template]
        call("product.settings.by_domain.put", {"path": {"domain": "models"}, "revision": cfg["revision"],
            "body": {"schema_version": 1, "patch": patch}})
