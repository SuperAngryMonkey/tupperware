# Tupperware MCP

The `mcp/` directory ships a Model Context Protocol server that lets an AI client
(Claude Code, Claude Desktop, or any MCP-compatible client) drive provisioning —
listing containers and cloning the golden template — without the web UI or a shell.

## What it is

A stdio MCP server (`mcp/tupperware_mcp.py`, built on FastMCP) that is a **thin
HTTP client** over the Tupperware web app. It runs no `pct` or SSH itself; every
action goes through the same HTTP endpoints the browser UI uses. That is the whole
security posture: the server has no more reach than a web-UI user on the tailnet,
and far less code in which to get it wrong.

```
┌──────────────┐  stdio   ┌────────────────────┐  HTTP    ┌───────────────────────┐
│  Claude Code │ ───────→ │  tupperware_mcp.py │ ───────→ │  Tupperware (Flask)   │
│  / Desktop   │  (MCP)   │  (HTTP client)     │          │  /api/*, /clone-stream│
└──────────────┘          └────────────────────┘          └───────────┬───────────┘
                                                                       ▼
                                                            pct clone → tailnet join
```

## Tools

| Tool | Kind | Backing endpoint | Notes |
|---|---|---|---|
| `tupperware_host_status` | read | `GET /api/status` | counts, tailnet peers, next free VMID, storage backends, template readiness |
| `tupperware_list_containers` | read | `GET /api/containers` | LXC inventory (template excluded) |
| `tupperware_provision` | write | `POST /clone-stream` | clone + join tailnet; **dry-run by default** |

No destroy or transfer tool is exposed — provisioning and reads only, by design.

### `tupperware_provision` safety

`dry_run` defaults to `True`. A dry run resolves the plan (target VMID, storage,
sizing) from `/api/status` and returns it **without creating anything**. To
actually clone, the client calls again with `dry_run=False`. In Claude Desktop
each call is separately user-approved, so a real provision is two deliberate
approvals — plan, then execute.

## Endpoints added to the web app (v0.2.1)

The MCP needs machine-readable reads, so `webui/app.py` gained:

- `GET /api/status` — `host_metrics()` plus `storages`, `default_storage`, `template_ready`
- `GET /api/containers` — `{"containers": [...]}`

Both are read-only JSON wrappers around functions the dashboard already used. They
are unauthenticated, consistent with the rest of the web UI's tailnet-only access
model — do not expose the web app to untrusted networks.

## Configuration

| Env | Default | Notes |
|---|---|---|
| `TUPPERWARE_URL` | _(required)_ | Base URL of the web app, e.g. `http://192.0.2.9:8080` (placeholder address). Use the tailnet IP / MagicDNS name if the client isn't on the app's LAN. |
| `TUPPERWARE_TIMEOUT` | `600` | Provision timeout (s). A clone plus network wait can take minutes. |

## Setup

See [`mcp/README.md`](../mcp/README.md) for venv install and client registration
(Claude Code `claude mcp add`, or the `claude_desktop_config.json` block for
Claude Desktop).

## Verifying independently of a client

`mcp/check_mcp.py` performs a real MCP handshake against the server and prints the
tool list. If it prints the three tools, the server is good and any failure is
client-side registration:

```bash
cd mcp && ./.venv/bin/python check_mcp.py
```
