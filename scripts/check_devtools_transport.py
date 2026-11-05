"""Check installed DevTools MCP against an isolated Chrome for Testing process."""
import argparse
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolkit", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    args = parser.parse_args()
    package = args.toolkit / "node_modules" / "chrome-devtools-mcp"
    metadata = json.loads((package / "package.json").read_text("utf-8"))
    binary = package / metadata["bin"]["chrome-devtools-mcp"]
    child = subprocess.Popen([shutil.which("node"), str(binary), "--headless", "--isolated",
        "--executablePath", str(args.chrome), "--no-usage-statistics", "--no-performance-crux"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", env={**os.environ, "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS": "1"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    responses = queue.Queue()
    def read():
        for line in child.stdout:
            responses.put(json.loads(line))
    threading.Thread(target=read, daemon=True).start()
    next_id = 0
    def request(method, params=None):
        nonlocal next_id
        next_id += 1
        value = {"jsonrpc": "2.0", "id": next_id, "method": method, "params": params or {}}
        child.stdin.write(json.dumps(value) + "\n")
        child.stdin.flush()
        while True:
            response = responses.get(timeout=45)
            if response.get("id") == next_id:
                if "error" in response:
                    raise RuntimeError("DevTools MCP rejected the check")
                return response["result"]
    try:
        initialized = request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                             "clientInfo": {"name": "veridex-isolated-check", "version": "0.1"}})
        child.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        child.stdin.flush()
        tools = request("tools/list")["tools"]
        if not any(row["name"] == "list_pages" for row in tools):
            raise RuntimeError("Installed server does not expose list_pages")
        pages = request("tools/call", {"name": "list_pages", "arguments": {}})
        if pages.get("isError"):
            raise RuntimeError("DevTools could not connect to isolated Chrome")
        print(json.dumps({"status": "passed", "server_version": metadata["version"],
            "protocol": initialized["protocolVersion"], "tool_count": len(tools),
            "list_pages": "passed", "signed_in_profile": False, "global_mcp_configuration_changed": False}))
    finally:
        child.stdin.close()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.wait(timeout=5)


if __name__ == "__main__":
    main()
