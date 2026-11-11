"""Smoke test over real stdio: initialize, list tools, call list_endpoints (no key needed).

Usage: python scripts/stdio_smoke.py <command that starts the server...>
"""

import json
import os
import subprocess
import sys

cmd = sys.argv[1:]
env = {k: v for k, v in os.environ.items() if k != "GARMIN_API_KEY"}
p = subprocess.Popen(
    cmd,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=env,
    text=True,
)
init = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}},
}
p.stdin.write(json.dumps(init) + "\n")
p.stdin.flush()
line = p.stdout.readline()
reply = json.loads(line)  # fails if stdout carries anything but JSON-RPC
print("initialize ->", "result" in reply, reply.get("result", {}).get("serverInfo"))
p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
p.stdin.flush()
tools = json.loads(p.stdout.readline())
print("tools ->", [t["name"] for t in tools["result"]["tools"]])
p.stdin.write(
    json.dumps(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_endpoints", "arguments": {}}}
    )
    + "\n"
)
p.stdin.flush()
call = json.loads(p.stdout.readline())
print("list_endpoints ->", len(json.loads(call["result"]["content"][0]["text"])["endpoints"]), "endpoints")
p.stdin.close()
try:
    p.wait(timeout=5)
except subprocess.TimeoutExpired:
    p.kill()
print("stderr:", p.stderr.read()[:200].strip() or "(empty)")
if "result" not in reply or len(tools["result"]["tools"]) != 2:
    raise SystemExit(1)
