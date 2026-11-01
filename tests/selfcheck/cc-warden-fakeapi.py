#!/usr/bin/env python3
"""A local Messages API for cc-warden's selfcheck, so the REAL claude binary resolves the run's settings and its
permission checks answer the tool calls below. A flag list can't show what a run may do; these calls can.
  cc-warden-fakeapi.py <port file> <calls.json> <requests file, each body appended>
The first model turn asks for every call in calls.json, each a {"name": tool, "input": {...}}; the next one answers the
decision schema (StructuredOutput). The real claude's other requests (a title, a token count) get a plain text turn."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

CALLS = json.load(open(sys.argv[2]))


def blocks(req):
    tools = [t.get("name") for t in req.get("tools") or []]
    if "StructuredOutput" not in tools:
        return [], "end_turn"
    done = any(isinstance(c, dict) and c.get("type") == "tool_result"
               for m in req["messages"] if isinstance(m.get("content"), list) for c in m["content"])
    if done:
        return [{"name": "StructuredOutput", "input": {"decision": "tribunal", "note": "probe"}}], "tool_use"
    return CALLS, "tool_use"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}"
        open(sys.argv[3], "ab").write(body + b"\n")
        req = json.loads(body)
        if "count_tokens" in self.path:
            return self.answer("application/json", json.dumps({"input_tokens": 1}))
        calls, stop = blocks(req)
        ev = [("message_start", {"message": {"id": "m", "type": "message", "role": "assistant", "model": req.get("model"),
              "content": [], "stop_reason": None, "usage": {"input_tokens": 1, "output_tokens": 1}}})]
        for i, c in enumerate(calls or [None]):
            start = {"type": "tool_use", "id": f"toolu_{c['name']}_{i}", "name": c["name"], "input": {}} if c else {"type": "text", "text": ""}
            delta = {"type": "input_json_delta", "partial_json": json.dumps(c["input"])} if c else {"type": "text_delta", "text": "ok"}
            ev += [("content_block_start", {"index": i, "content_block": start}), ("content_block_delta", {"index": i, "delta": delta}),
                   ("content_block_stop", {"index": i})]
        ev += [("message_delta", {"delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 1}}), ("message_stop", {})]
        self.answer("text/event-stream", "".join(f"event: {n}\ndata: {json.dumps(dict(d, type=n))}\n\n" for n, d in ev))

    def answer(self, ctype, body):
        self.send_response(200)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body.encode())))
        self.end_headers()
        self.wfile.write(body.encode())


srv = HTTPServer(("127.0.0.1", 0), H)
open(sys.argv[1], "w").write(str(srv.server_port))
srv.serve_forever()
