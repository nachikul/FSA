"""Minimal synchronous client for INDmoney's remote MCP server.

Implements just enough of the MCP "Streamable HTTP" transport (JSON-RPC 2.0
over HTTP POST, with the `Mcp-Session-Id` header threading requests
together after `initialize`) to call the handful of read-only portfolio
tools this app needs. Deliberately hand-rolled rather than pulling in the
full `mcp` SDK: the SDK is async-first (which means bridging into
Streamlit's synchronous execution model on every call), and the actual
protocol surface used here is small enough that a ~150-line client is both
easier to reason about and one less dependency to track.

If INDmoney's server ever needs more of the protocol than this covers
(resources, prompts, streaming tool results), reach for the official `mcp`
package instead of extending this by hand.
"""
from __future__ import annotations

import itertools
import json
from typing import Any, Optional

import httpx

MCP_ENDPOINT = "https://mcp.indmoney.com/mcp"
PROTOCOL_VERSION = "2025-06-18"

_ID_COUNTER = itertools.count(1)


class MCPError(Exception):
    pass


class IndmoneyMCPClient:
    def __init__(self, access_token: str):
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._session_id: Optional[str] = None
        self._client = httpx.Client(timeout=30)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "IndmoneyMCPClient":
        self.initialize()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- protocol plumbing ---------------------------------------------

    def _post(self, payload: dict) -> Optional[dict]:
        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        resp = self._client.post(MCP_ENDPOINT, headers=headers, content=json.dumps(payload))
        if resp.status_code == 401:
            raise MCPError("INDmoney rejected the access token (expired or revoked) — reconnect.")
        if resp.status_code >= 400:
            raise MCPError(f"MCP request failed ({resp.status_code}): {resp.text[:300]}")

        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid

        if resp.status_code == 202 or not resp.content:
            return None  # notifications get no body

        return _parse_json_or_sse(resp)

    def initialize(self) -> None:
        result = self._post(
            {
                "jsonrpc": "2.0",
                "id": next(_ID_COUNTER),
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "financial-statement-analyser", "version": "1.0"},
                },
            }
        )
        if result is None or "result" not in result:
            raise MCPError(f"Unexpected response to initialize: {result}")
        # Complete the handshake — required by the spec before any other call.
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> Any:
        result = self._post(
            {
                "jsonrpc": "2.0",
                "id": next(_ID_COUNTER),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        if result is None:
            raise MCPError(f"No response calling tool '{name}'.")
        if "error" in result:
            raise MCPError(f"Tool '{name}' returned an error: {result['error']}")

        tool_result = result.get("result", {})
        if tool_result.get("isError"):
            raise MCPError(f"Tool '{name}' reported an error: {tool_result}")

        content = tool_result.get("content", [])
        texts = [block.get("text", "") for block in content if block.get("type") == "text"]
        joined = "\n".join(t for t in texts if t)
        try:
            return json.loads(joined)
        except (json.JSONDecodeError, TypeError):
            return joined


def _parse_json_or_sse(resp: httpx.Response) -> dict:
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:"):].strip())
        raise MCPError("SSE response had no data: line to parse.")
    return resp.json()


# The asset types worth checking networth_holdings for — matches what the
# live networth_snapshot's `investments[].asset_type` values map to. A type
# with no meaningful row-level breakdown (ESOPs/RSUs, the US stock cash
# wallet) is left out; call_tool simply returns an empty list for anything
# that genuinely has nothing to show.
HOLDINGS_ASSET_TYPES = ["MF", "IND_STOCK", "US_STOCK", "EPF", "PPF", "FD", "RE", "SA", "BOND", "RD"]


def fetch_live_snapshot(access_token: str) -> dict:
    """Calls the same handful of tools the manual export prompt in
    README.md asks Claude to call, and assembles the identical JSON
    envelope `src/sources/indmoney.py` already knows how to parse — so the
    live path and the upload-a-file path share every line of parsing and
    UI code downstream of this function."""
    import datetime

    with IndmoneyMCPClient(access_token) as client:
        snapshot = client.call_tool("networth_snapshot")

        present_types = {inv.get("asset_type") for inv in snapshot.get("investments", [])}
        holdings: dict[str, list] = {}
        for asset_type in HOLDINGS_ASSET_TYPES:
            try:
                result = client.call_tool("networth_holdings", {"asset_type": asset_type})
            except MCPError:
                continue
            rows = result.get("holdings", []) if isinstance(result, dict) else []
            if rows:
                holdings[asset_type] = rows

        try:
            mf_sips = client.call_tool("mf_sips").get("mf_sips", [])
        except MCPError:
            mf_sips = []
        try:
            stock_sips = client.call_tool("indian_stocks_sips").get("indian_stocks_sips", [])
        except MCPError:
            stock_sips = []

    return {
        "exported_at": datetime.datetime.now().astimezone().isoformat(),
        "networth_snapshot": snapshot,
        "holdings": holdings,
        "sips": {"mf": mf_sips, "stocks": stock_sips},
    }
