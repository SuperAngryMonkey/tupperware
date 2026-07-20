#!/usr/bin/env python3
"""Tupperware MCP — provision Tailscale-joined LXCs on Proxmox from Claude Code.

A thin stdio MCP wrapper over the Tupperware Flask app (webui/app.py). It does
NOT run `pct` or SSH anything itself — every action goes through the same tested
HTTP surface the web UI uses, so the server holds no direct root power.

Env:
  TUPPERWARE_URL      Base URL of the Tupperware web app.
                      Default: http://10.0.1.9:8080
                      (use the tailnet IP / MagicDNS name if your Mac isn't on
                      the same LAN as proxlab, e.g. http://100.x.y.z:8080)
  TUPPERWARE_TIMEOUT  Provision timeout in seconds. Default: 600.

Register with Claude Code (see mcp/README.md):
  claude mcp add tupperware -- \
    /Users/jamessmith/Projects/tupperware/mcp/.venv/bin/python \
    /Users/jamessmith/Projects/tupperware/mcp/tupperware_mcp.py
"""
import os
import re
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("TUPPERWARE_URL", "http://10.0.1.9:8080").rstrip("/")
PROVISION_TIMEOUT = float(os.environ.get("TUPPERWARE_TIMEOUT", "600"))
READ_TIMEOUT = 15.0

HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9-]+$")
STORAGE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

mcp = FastMCP("tupperware")


async def _get(path: str, timeout: float = READ_TIMEOUT) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(f"{BASE_URL}{path}")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def tupperware_host_status() -> dict:
    """Return proxlab host status: container/VM counts, tailnet peer count, the
    next free VMID (the auto-pick target), available container storage backends,
    and whether the golden LXC template is ready. Read-only. Call this before
    provisioning to see exactly which VMID and storage a clone would land on."""
    try:
        return await _get("/api/status")
    except Exception as e:
        return {"error": f"Could not reach Tupperware at {BASE_URL}: {e}"}


@mcp.tool()
async def tupperware_list_containers() -> dict:
    """List the LXC containers currently on proxlab: VMID, hostname, status,
    cores/memory/disk, storage backend, LAN + tailnet IP, and notes. Read-only.
    The golden template is excluded."""
    try:
        return await _get("/api/containers")
    except Exception as e:
        return {"error": f"Could not reach Tupperware at {BASE_URL}: {e}"}


@mcp.tool()
async def tupperware_provision(
    hostname: str,
    cores: Optional[int] = None,
    memory: Optional[int] = None,
    disk: Optional[int] = None,
    storage: Optional[str] = None,
    vmid: Optional[int] = None,
    dry_run: bool = True,
) -> dict:
    """Provision a new Tailscale-joined LXC on proxlab by cloning the golden
    template.

    SAFETY: dry_run defaults to True. A dry run resolves and returns the plan
    (target VMID, storage, sizing) WITHOUT creating anything. To actually create
    the container, call again with the SAME arguments plus dry_run=False.

    Args:
      hostname: Container hostname (letters, digits, hyphens only). Becomes the
                Tailscale hostname.
      cores:    CPU cores. Omit for the template default (1).
      memory:   RAM in MB. Omit for the template default (512).
      disk:     Root disk in GB. Omit for the template default (4). Grow-only.
      storage:  Proxmox storage backend. Omit to use the host default.
      vmid:     Explicit VMID (>=100). Omit to auto-pick the next free one.
      dry_run:  True (default) = plan only. False = actually clone & join tailnet.
    """
    hostname = (hostname or "").strip()
    if not HOSTNAME_RE.match(hostname):
        return {"error": "Invalid hostname: letters, digits, and hyphens only."}
    if storage is not None and not STORAGE_RE.match(storage):
        return {"error": f"Invalid storage name: {storage!r}"}
    if vmid is not None and (not isinstance(vmid, int) or vmid < 100):
        return {"error": "vmid must be an integer >= 100."}
    for label, val in (("cores", cores), ("memory", memory), ("disk", disk)):
        if val is not None and (not isinstance(val, int) or val <= 0):
            return {"error": f"{label} must be a positive integer."}

    # Resolve current host state (doubles as the reachability check).
    try:
        status = await _get("/api/status")
    except Exception as e:
        return {"error": f"Could not reach Tupperware at {BASE_URL}: {e}"}
    if not status.get("template_ready", True):
        return {"error": "Golden template not ready on host; build it first "
                         "(tupperware-build-template)."}

    resolved_vmid = vmid if vmid is not None else status.get("next_vmid")
    resolved_storage = storage or status.get("default_storage")
    plan = {
        "hostname": hostname,
        "vmid": resolved_vmid,
        "cores": cores if cores is not None else "template default (1)",
        "memory_mb": memory if memory is not None else "template default (512)",
        "disk_gb": disk if disk is not None else "template default (4)",
        "storage": resolved_storage,
        "target": BASE_URL,
    }

    if dry_run:
        return {
            "dry_run": True,
            "plan": plan,
            "next_step": "Call tupperware_provision again with the same args plus "
                         "dry_run=false to create it.",
        }

    # Execute: same form contract as the web UI's POST /clone-stream.
    form = {"hostname": hostname}
    if vmid is not None:
        form["vmid"] = str(vmid)
    if cores is not None:
        form["cores"] = str(cores)
    if memory is not None:
        form["memory"] = str(memory)
    if disk is not None:
        form["disk"] = str(disk)
    if storage is not None:
        form["storage"] = storage

    lines: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=PROVISION_TIMEOUT) as client:
            async with client.stream("POST", f"{BASE_URL}/clone-stream", data=form) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if line:
                        lines.append(line)
    except Exception as e:
        return {"error": f"Provision request failed: {e}", "console": "\n".join(lines)}

    console = "\n".join(lines)
    ok = any(("[OK]" in ln) or ("All done" in ln) for ln in lines)
    failed = any(ln.startswith("[!]") or ("ERROR" in ln) for ln in lines)
    return {
        "dry_run": False,
        "success": ok and not failed,
        "plan": plan,
        "console": console,
    }


if __name__ == "__main__":
    mcp.run()
