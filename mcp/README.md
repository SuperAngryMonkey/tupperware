# Tupperware MCP

A local **stdio** MCP server that lets Claude Code provision Tailscale-joined
LXCs on proxlab through Tupperware — no copy-pasting `tupperware-new` commands.

It's a thin HTTP client over the Tupperware Flask app. It does **not** run `pct`
or SSH anything itself; every action goes through the same tested endpoints the
web UI uses. Nothing new is exposed to the internet — the MCP runs on your Mac
and talks to `http://10.0.1.9:8080` over the tailnet/LAN.

## Tools

| Tool | Kind | What it does |
|---|---|---|
| `tupperware_host_status` | read | Counts, tailnet peers, next free VMID, storage backends, template readiness |
| `tupperware_list_containers` | read | Inventory of LXCs on proxlab |
| `tupperware_provision` | write | Clone the golden template + join tailnet. **`dry_run=True` by default** |

No destroy tool by design.

## Prerequisite: deploy the read-only API routes

This MCP needs two JSON routes added to `webui/app.py` in this repo
(`/api/status`, `/api/containers`). Deploy the updated app to proxlab and
restart the service:

```bash
scp webui/app.py root@10.0.1.9:/opt/tupperware/app.py
ssh root@10.0.1.9 systemctl restart tupperware
# verify:
curl -s http://10.0.1.9:8080/api/status | head
```

## Install

```bash
cd /Users/jamessmith/Projects/tupperware/mcp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Register with Claude Code

```bash
claude mcp add tupperware -- \
  /Users/jamessmith/Projects/tupperware/mcp/.venv/bin/python \
  /Users/jamessmith/Projects/tupperware/mcp/tupperware_mcp.py
```

If your Mac isn't on the same LAN as proxlab, point it at the tailnet address:

```bash
claude mcp add tupperware \
  --env TUPPERWARE_URL=http://100.x.y.z:8080 -- \
  /Users/jamessmith/Projects/tupperware/mcp/.venv/bin/python \
  /Users/jamessmith/Projects/tupperware/mcp/tupperware_mcp.py
```

Then in Claude Code: `/mcp` to confirm `tupperware` is connected.

## Usage (from Claude Code)

- "What's the tupperware host status?" → `tupperware_host_status`
- "List the LXCs on proxlab." → `tupperware_list_containers`
- "Spin up an LXC called `lab-redis` with 2 cores and 1GB." → `tupperware_provision`
  runs a **dry run** first and shows the plan (VMID, storage, sizing).
- "Looks good, create it." → same call with `dry_run=false`.

## Config

| Env | Default | Notes |
|---|---|---|
| `TUPPERWARE_URL` | `http://10.0.1.9:8080` | LAN IP; use tailnet IP/MagicDNS if remote |
| `TUPPERWARE_TIMEOUT` | `600` | Provision timeout (s). Clone + network wait can take a few minutes |
