#!/usr/bin/env python3
"""
Tupperware - Tailscale-connected LXC container provisioner.

Web UI that wraps tupperware-new with live streaming output.
Runs on the Proxmox host, listens on port 8080.
"""
import subprocess
import re
import os
import json
from flask import Flask, render_template_string, request, Response, stream_with_context

app = Flask(__name__)

CLONE_SCRIPT = "/usr/local/sbin/tupperware-new"
TEMPLATE_VMID = int(os.environ.get("TEMPLATE_VMID", "9000"))


def next_free_vmid(start=200):
    """Find the next unused VMID, scanning both LXC and QEMU."""
    used = set()
    for cmd in (["pct", "list"], ["qm", "list"]):
        try:
            out = subprocess.check_output(cmd, text=True, timeout=5)
            for line in out.strip().split("\n")[1:]:
                parts = line.split()
                if parts:
                    try:
                        used.add(int(parts[0]))
                    except ValueError:
                        pass
        except Exception:
            pass
    v = start
    while v in used:
        v += 1
    return v


def host_metrics():
    """Collect quick stats for the dashboard header."""
    try:
        ct_count = len(subprocess.check_output(["pct", "list"], text=True).strip().split("\n")) - 1
    except Exception:
        ct_count = "?"
    try:
        vm_count = len(subprocess.check_output(["qm", "list"], text=True).strip().split("\n")) - 1
    except Exception:
        vm_count = "?"
    try:
        ts_status = subprocess.check_output(["tailscale", "status", "--json"], text=True, timeout=3)
        ts_data = json.loads(ts_status)
        ts_self = ts_data.get("Self", {}).get("HostName", "?")
        ts_peers = len(ts_data.get("Peer", {}))
    except Exception:
        ts_self = "offline"
        ts_peers = "?"
    try:
        hostname = subprocess.check_output(["hostname"], text=True).strip()
    except Exception:
        hostname = "proxmox"
    return {
        "ct_count": ct_count,
        "vm_count": vm_count,
        "ts_self": ts_self,
        "ts_peers": ts_peers,
        "hostname": hostname,
        "next_vmid": next_free_vmid(),
    }


INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TUPPERWARE</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
:root {
  --c1: #0a0a0f; --c2: #0f0f1a; --c3: #14141f; --c4: #1a1a2e;
  --acc: #00d4ff; --acc2: #ff6b35; --acc3: #00ff88; --danger: #ff3366;
  --txt: #e8e8f0; --txt2: #8888aa; --txt3: #4444aa;
  --fmono: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  --fdisplay: 'Bebas Neue', sans-serif;
  --border: 1px solid rgba(0, 212, 255, 0.12);
  --border-strong: 1px solid rgba(0, 212, 255, 0.2);
  --border-subtle: 1px solid rgba(255, 255, 255, 0.05);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; background: var(--c1); color: var(--txt); font-family: var(--fmono); font-size: 12px; }
body { padding: 20px; max-width: 1400px; margin: 0 auto; }

.hdr { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 12px; border-bottom: var(--border-strong); }
.hdr-left  { display: flex; align-items: baseline; gap: 16px; }
.hdr-right { display: flex; align-items: center;  gap: 20px; }
.logo { font-family: var(--fdisplay); font-size: 42px; letter-spacing: 4px; color: var(--acc); line-height: 1; }
.subtitle { font-size: 10px; color: var(--txt2); letter-spacing: 2px; text-transform: uppercase; }
.clock { font-size: 16px; color: var(--txt2); letter-spacing: 2px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--acc3); box-shadow: 0 0 8px var(--acc3); animation: pulse 2s infinite; }
.status-txt { font-size: 10px; color: var(--acc3); letter-spacing: 1px; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

.metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 16px; }
.metric { background: var(--c2); border: var(--border); padding: 16px; position: relative; overflow: hidden; }
.metric::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; }
.metric.blue::before { background: var(--acc); }
.metric.orange::before { background: var(--acc2); }
.metric.green::before { background: var(--acc3); }
.metric.red::before { background: var(--danger); }
.metric-label { font-size: 9px; color: var(--txt2); letter-spacing: 2px; text-transform: uppercase; margin-bottom: 8px; }
.metric-val { font-family: var(--fdisplay); font-size: 36px; letter-spacing: 2px; line-height: 1; }
.metric.blue .metric-val { color: var(--acc); }
.metric.orange .metric-val { color: var(--acc2); }
.metric.green .metric-val { color: var(--acc3); }
.metric.red .metric-val { color: var(--danger); }
.metric-sub { font-size: 9px; color: var(--txt3); margin-top: 4px; }

.panel { background: var(--c2); border: var(--border); padding: 16px; margin-bottom: 16px; }
.panel-hdr { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding-bottom: 8px; border-bottom: var(--border-subtle); }
.panel-title { font-size: 9px; letter-spacing: 3px; text-transform: uppercase; color: var(--txt2); }
.panel-badge { font-size: 9px; padding: 2px 8px; border: 1px solid; letter-spacing: 1px; }
.panel-badge.live { color: var(--acc3); border-color: var(--acc3); }
.panel-badge.warn { color: var(--acc2); border-color: var(--acc2); }
.panel-badge.err  { color: var(--danger); border-color: var(--danger); }
.panel-badge.idle { color: var(--txt3); border-color: var(--txt3); }

.form-grid { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr 1fr; gap: 12px; }
.form-grid.row2 { grid-template-columns: 2fr 1fr; margin-top: 12px; }
.form-field { display: flex; flex-direction: column; gap: 6px; }
.form-label { font-size: 9px; color: var(--txt2); letter-spacing: 2px; text-transform: uppercase; }
.form-input { background: var(--c3); border: var(--border); color: var(--txt); font-family: var(--fmono); font-size: 11px; padding: 10px 14px; outline: none; transition: border-color 0.2s; }
.form-input:focus { border-color: var(--acc); }
.form-input::placeholder { color: var(--txt3); }

.btn-row { margin-top: 16px; display: flex; gap: 8px; }
.btn { background: transparent; border: 1px solid var(--acc); color: var(--acc); font-family: var(--fmono); font-size: 11px; padding: 12px 28px; cursor: pointer; letter-spacing: 3px; text-transform: uppercase; transition: background 0.2s; }
.btn:hover { background: rgba(0, 212, 255, 0.1); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

.console { background: #000; border: var(--border); padding: 14px; min-height: 200px; max-height: 480px; overflow-y: auto; font-family: var(--fmono); font-size: 11px; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; }
.console .ok   { color: var(--acc3); }
.console .info { color: var(--acc); }
.console .warn { color: var(--acc2); }
.console .err  { color: var(--danger); }
.console .dim  { color: var(--txt3); }
.console-empty { color: var(--txt3); font-style: italic; }

@media (max-width: 900px) {
  .metrics { grid-template-columns: repeat(2, 1fr); }
  .form-grid { grid-template-columns: 1fr 1fr; }
  .form-grid.row2 { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<div class="hdr">
  <div class="hdr-left">
    <div class="logo">TUPPERWARE</div>
    <div class="subtitle">LXC PROVISIONER // {{ m.hostname }}</div>
  </div>
  <div class="hdr-right">
    <div class="clock" id="clock">--:--:--</div>
    <div class="status-dot"></div>
    <div class="status-txt">OPERATIONAL</div>
  </div>
</div>

<div class="metrics">
  <div class="metric blue">
    <div class="metric-label">CONTAINERS</div>
    <div class="metric-val">{{ m.ct_count }}</div>
    <div class="metric-sub">LXC running on host</div>
  </div>
  <div class="metric orange">
    <div class="metric-label">VIRTUAL MACHINES</div>
    <div class="metric-val">{{ m.vm_count }}</div>
    <div class="metric-sub">QEMU on host</div>
  </div>
  <div class="metric green">
    <div class="metric-label">TAILNET PEERS</div>
    <div class="metric-val">{{ m.ts_peers }}</div>
    <div class="metric-sub">visible from {{ m.ts_self }}</div>
  </div>
  <div class="metric blue">
    <div class="metric-label">NEXT VMID</div>
    <div class="metric-val">{{ m.next_vmid }}</div>
    <div class="metric-sub">auto-pick available</div>
  </div>
</div>

<div class="panel">
  <div class="panel-hdr">
    <div class="panel-title">CLONE PARAMETERS</div>
    <div class="panel-badge idle" id="form-status">READY</div>
  </div>
  <form id="clone-form">
    <div class="form-grid">
      <div class="form-field">
        <div class="form-label">HOSTNAME</div>
        <input class="form-input" type="text" name="hostname" required placeholder="lab-lxc-01" pattern="[a-zA-Z0-9-]+" autofocus>
      </div>
      <div class="form-field">
        <div class="form-label">VMID</div>
        <input class="form-input" type="number" name="vmid" placeholder="{{ m.next_vmid }}" min="100" max="999999">
      </div>
      <div class="form-field">
        <div class="form-label">CORES</div>
        <input class="form-input" type="number" name="cores" placeholder="1" min="1" max="16">
      </div>
      <div class="form-field">
        <div class="form-label">MEMORY MB</div>
        <input class="form-input" type="number" name="memory" placeholder="512" min="128">
      </div>
      <div class="form-field">
        <div class="form-label">DISK GB</div>
        <input class="form-input" type="number" name="disk" placeholder="4" min="4">
      </div>
    </div>
    <div class="form-grid row2">
      <div class="form-field">
        <div class="form-label">ROOT PASSWORD (OPTIONAL)</div>
        <input class="form-input" type="password" name="rootpw" placeholder="leave blank for tailscale ssh only" autocomplete="new-password">
      </div>
    </div>
    <div class="btn-row">
      <button class="btn" type="submit" id="submit-btn">CLONE & JOIN TAILNET</button>
    </div>
  </form>
</div>

<div class="panel">
  <div class="panel-hdr">
    <div class="panel-title">PROVISIONING CONSOLE</div>
    <div class="panel-badge idle" id="console-status">IDLE</div>
  </div>
  <div class="console" id="console"><div class="console-empty">Awaiting clone request...</div></div>
</div>

<script>
function tick() {
  const d = new Date();
  const pad = n => String(n).padStart(2,'0');
  document.getElementById('clock').textContent = pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds());
}
setInterval(tick, 1000); tick();

const form = document.getElementById('clone-form');
const submitBtn = document.getElementById('submit-btn');
const consoleEl = document.getElementById('console');
const formStatus = document.getElementById('form-status');
const consoleStatus = document.getElementById('console-status');

function setStatus(el, cls, text) {
  el.className = 'panel-badge ' + cls;
  el.textContent = text;
}

function appendLine(text, cls) {
  if (consoleEl.querySelector('.console-empty')) consoleEl.innerHTML = '';
  const span = document.createElement('span');
  span.className = cls || '';
  span.textContent = text + '\\n';
  consoleEl.appendChild(span);
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

function classifyLine(line) {
  if (/\\[\\u2713\\]|\\[OK\\]|All done|ready|success/i.test(line)) return 'ok';
  if (/\\[\\!\\]|ERROR|failed|exception/i.test(line)) return 'err';
  if (/WARN|warning|abandoning|conflict/i.test(line)) return 'warn';
  if (/^\\[\\*\\]/.test(line)) return 'info';
  return 'dim';
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  consoleEl.innerHTML = '';
  submitBtn.disabled = true;
  setStatus(formStatus, 'warn', 'BUSY');
  setStatus(consoleStatus, 'live', 'STREAMING');

  const fd = new FormData(form);
  const params = new URLSearchParams();
  for (const [k,v] of fd.entries()) params.append(k, v);

  try {
    const resp = await fetch('/clone-stream', { method: 'POST', body: params });
    if (!resp.ok || !resp.body) throw new Error('Stream init failed: ' + resp.status);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buffer.indexOf('\\n')) >= 0) {
        const line = buffer.slice(0, nl);
        buffer = buffer.slice(nl+1);
        if (line.length) appendLine(line, classifyLine(line));
      }
    }
    if (buffer.length) appendLine(buffer, classifyLine(buffer));
    setStatus(formStatus, 'live', 'COMPLETE');
    setStatus(consoleStatus, 'live', 'DONE');
  } catch (err) {
    appendLine('[!] ' + err.message, 'err');
    setStatus(formStatus, 'err', 'FAILED');
    setStatus(consoleStatus, 'err', 'ERROR');
  } finally {
    submitBtn.disabled = false;
  }
});
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX, m=host_metrics())


@app.route("/clone-stream", methods=["POST"])
def clone_stream():
    hostname = request.form.get("hostname", "").strip()
    if not re.match(r"^[a-zA-Z0-9-]+$", hostname):
        return Response("[!] Invalid hostname.\n", mimetype="text/plain")

    vmid = request.form.get("vmid", "").strip()
    if not vmid:
        vmid = str(next_free_vmid())
    try:
        vmid_int = int(vmid)
    except ValueError:
        return Response("[!] Invalid VMID.\n", mimetype="text/plain")

    cores = request.form.get("cores", "").strip()
    memory = request.form.get("memory", "").strip()
    disk = request.form.get("disk", "").strip()
    rootpw = request.form.get("rootpw", "")

    def generate():
        yield f"[*] Tupperware: cloning {hostname} as VMID {vmid_int}\n"
        try:
            proc = subprocess.Popen(
                [CLONE_SCRIPT, str(vmid_int), hostname],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in iter(proc.stdout.readline, ""):
                yield line
            proc.wait()

            if proc.returncode != 0:
                yield f"[!] Clone script exited with code {proc.returncode}\n"
                return

            if cores or memory:
                args = ["pct", "set", str(vmid_int)]
                if cores:
                    args += ["-cores", cores]
                if memory:
                    args += ["-memory", memory]
                yield "[*] Applying CPU/memory overrides...\n"
                r = subprocess.run(args, capture_output=True, text=True)
                if r.stdout:
                    yield r.stdout
                if r.stderr:
                    yield r.stderr

            if disk and int(disk) > 4:
                yield f"[*] Resizing rootfs to {disk}G...\n"
                r = subprocess.run(
                    ["pct", "resize", str(vmid_int), "rootfs", f"{disk}G"],
                    capture_output=True,
                    text=True,
                )
                if r.stdout:
                    yield r.stdout
                if r.stderr:
                    yield r.stderr

            if rootpw:
                yield "[*] Setting root password...\n"
                r = subprocess.run(
                    [
                        "pct",
                        "exec",
                        str(vmid_int),
                        "--",
                        "bash",
                        "-c",
                        f"echo 'root:{rootpw}' | chpasswd",
                    ],
                    capture_output=True,
                    text=True,
                )
                yield "    Password set.\n" if r.returncode == 0 else f"    Failed: {r.stderr}\n"

            yield f"\n[\u2713] All done. {hostname} (VMID {vmid_int}) should be on the tailnet.\n"

        except Exception as e:
            yield f"\n[!] Exception: {e}\n"

    return Response(stream_with_context(generate()), mimetype="text/plain")


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        threaded=True,
    )
