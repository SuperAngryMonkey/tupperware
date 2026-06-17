#!/usr/bin/env python3
"""Tupperware - Tailscale-connected LXC container provisioner."""
import subprocess
import re
import os
import json
from flask import Flask, render_template_string, request, Response, stream_with_context

app = Flask(__name__)

CLONE_SCRIPT = "/usr/local/sbin/tupperware-new"
DEFAULT_STORAGE = "local-lvm"
TEMPLATE_VMID = int(os.environ.get("TEMPLATE_VMID", "9000"))
SAMPLE_TEMPLATE_URL = "https://github.com/SuperAngryMonkey/tupperware/releases/latest/download/tupperware-template.tar.zst"


def template_exists():
    """Return True if TEMPLATE_VMID exists and is a template."""
    try:
        subprocess.check_output(
            ["pct", "status", str(TEMPLATE_VMID)],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    # status exists; check it's actually a template
    try:
        out = subprocess.check_output(
            ["pct", "config", str(TEMPLATE_VMID)],
            text=True,
            timeout=5,
        )
        for line in out.split("\n"):
            if line.startswith("template:"):
                val = line.split(":", 1)[1].strip()
                return val == "1"
    except Exception:
        pass
    return False


def next_free_vmid(start=200):
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


def list_storage_backends():
    backends = []
    try:
        out = subprocess.check_output(
            ["pvesm", "status", "-content", "rootdir"],
            text=True, timeout=5
        )
        for line in out.strip().split("\n")[1:]:
            parts = line.split()
            if len(parts) >= 2:
                backends.append({
                    "name": parts[0],
                    "type": parts[1],
                    "active": parts[2] if len(parts) > 2 else "?",
                })
    except Exception:
        pass
    return backends


def host_metrics():
    try:
        ct_count = len(subprocess.check_output(["pct", "list"], text=True).strip().split("\n")) - 1
    except Exception:
        ct_count = "?"
    try:
        vm_count = len(subprocess.check_output(["qm", "list"], text=True).strip().split("\n")) - 1
    except Exception:
        vm_count = "?"
    try:
        ts_data = json.loads(subprocess.check_output(["tailscale", "status", "--json"], text=True, timeout=3))
        ts_self = ts_data.get("Self", {}).get("HostName", "?")
        ts_peers = len(ts_data.get("Peer", {}))
    except Exception:
        ts_self = "offline"
        ts_peers = "?"
    try:
        hostname = subprocess.check_output(["hostname"], text=True).strip()
    except Exception:
        hostname = "proxmox"
    return {"ct_count": ct_count, "vm_count": vm_count, "ts_self": ts_self,
            "ts_peers": ts_peers, "hostname": hostname, "next_vmid": next_free_vmid()}


def parse_pct_config(vmid):
    cfg = {}
    try:
        out = subprocess.check_output(["pct", "config", str(vmid)], text=True, timeout=5)
        for line in out.strip().split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                cfg[k.strip()] = v.strip()
    except Exception:
        pass
    return cfg


def container_ip(vmid):
    try:
        out = subprocess.check_output(
            ["pct", "exec", str(vmid), "--", "hostname", "-I"],
            text=True, timeout=3, stderr=subprocess.DEVNULL
        )
        ips = out.strip().split()
        for ip in ips:
            if not ip.startswith("100."):
                return ip
        return ips[0] if ips else ""
    except Exception:
        return ""


def container_tailnet_ip(vmid):
    try:
        out = subprocess.check_output(
            ["pct", "exec", str(vmid), "--", "tailscale", "ip", "-4"],
            text=True, timeout=3, stderr=subprocess.DEVNULL
        )
        return out.strip().split("\n")[0] if out.strip() else ""
    except Exception:
        return ""


def container_storage(cfg):
    rootfs = cfg.get("rootfs", "")
    if ":" in rootfs:
        return rootfs.split(":", 1)[0]
    return ""


def list_containers():
    containers = []
    try:
        out = subprocess.check_output(["pct", "list"], text=True, timeout=5)
        lines = out.strip().split("\n")[1:]
        for line in lines:
            parts = line.split(None, 3)
            if len(parts) < 3:
                continue
            vmid = parts[0]
            status = parts[1]
            name = parts[2] if len(parts) > 2 else ""
            cfg = parse_pct_config(vmid)
            if cfg.get("template") == "1":
                continue
            desc = cfg.get("description", "")
            desc = desc.replace("%0A", "\n").replace("%20", " ")
            tags = cfg.get("tags", "")
            rootfs = cfg.get("rootfs", "")
            disk_size = ""
            disk_match = re.search(r"size=(\S+)", rootfs)
            if disk_match:
                disk_size = disk_match.group(1)
            lan_ip = container_ip(vmid) if status == "running" else ""
            ts_ip = container_tailnet_ip(vmid) if status == "running" else ""
            containers.append({
                "vmid": vmid,
                "name": name,
                "status": status,
                "cores": cfg.get("cores", "?"),
                "memory": cfg.get("memory", "?"),
                "disk": disk_size,
                "storage": container_storage(cfg),
                "lan_ip": lan_ip,
                "ts_ip": ts_ip,
                "description": desc,
                "tags": tags,
            })
    except Exception:
        pass
    return containers


SHARED_STYLE = r"""
:root{--c1:#0a0a0f;--c2:#0f0f1a;--c3:#14141f;--acc:#00d4ff;--acc2:#ff6b35;--acc3:#00ff88;--danger:#ff3366;--txt:#e8e8f0;--txt2:#8888aa;--txt3:#4444aa;--fmono:'IBM Plex Mono',monospace;--fdisplay:'Bebas Neue',sans-serif;--border:1px solid rgba(0,212,255,0.12);--border-strong:1px solid rgba(0,212,255,0.2);--border-subtle:1px solid rgba(255,255,255,0.05);}
*{box-sizing:border-box;margin:0;padding:0;}
html,body{height:100%;background:var(--c1);color:var(--txt);font-family:var(--fmono);font-size:12px;}
body{padding:20px;max-width:1400px;margin:0 auto;}
.hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:12px;border-bottom:var(--border-strong);}
.hdr-left{display:flex;align-items:baseline;gap:16px;}
.hdr-right{display:flex;align-items:center;gap:20px;}
.logo{font-family:var(--fdisplay);font-size:42px;letter-spacing:4px;color:var(--acc);line-height:1;}
.subtitle{font-size:10px;color:var(--txt2);letter-spacing:2px;text-transform:uppercase;}
.clock{font-size:16px;color:var(--txt2);letter-spacing:2px;}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--acc3);box-shadow:0 0 8px var(--acc3);animation:pulse 2s infinite;}
.status-dot.warn{background:var(--acc2);box-shadow:0 0 8px var(--acc2);}
.status-txt{font-size:10px;color:var(--acc3);letter-spacing:1px;}
.status-txt.warn{color:var(--acc2);}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:0.4;}}
.panel{background:var(--c2);border:var(--border);padding:16px;margin-bottom:16px;}
.panel-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:8px;border-bottom:var(--border-subtle);}
.panel-title{font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--txt2);}
"""


SETUP_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>TUPPERWARE - SETUP REQUIRED</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
""" + SHARED_STYLE + r"""
.setup-banner{background:var(--c2);border:1px solid var(--acc2);padding:24px;margin-bottom:20px;}
.setup-title{font-family:var(--fdisplay);font-size:28px;letter-spacing:3px;color:var(--acc2);margin-bottom:8px;}
.setup-msg{color:var(--txt);font-size:13px;line-height:1.6;margin-bottom:12px;}
.setup-detail{color:var(--txt2);font-size:11px;line-height:1.6;}
.opt-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:16px;}
@media (max-width:900px){.opt-grid{grid-template-columns:1fr;}}
.opt{background:var(--c2);border:var(--border);padding:20px;}
.opt-num{font-family:var(--fdisplay);font-size:36px;color:var(--acc);line-height:1;margin-bottom:8px;}
.opt-name{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--txt);margin-bottom:8px;font-weight:500;}
.opt-desc{font-size:11px;color:var(--txt2);line-height:1.5;margin-bottom:12px;}
.opt-time{font-size:9px;color:var(--txt3);letter-spacing:1px;text-transform:uppercase;margin-bottom:12px;}
.opt-cmd{background:#000;border:var(--border);padding:10px 12px;font-family:var(--fmono);font-size:10px;color:var(--acc3);word-break:break-all;line-height:1.5;}
.opt-cmd-comment{color:var(--txt3);}
.detail-panel{background:var(--c2);border:var(--border);padding:16px;}
.detail-title{font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--txt2);margin-bottom:12px;padding-bottom:8px;border-bottom:var(--border-subtle);}
.detail-body{color:var(--txt2);font-size:11px;line-height:1.6;}
.detail-body code{background:var(--c3);padding:2px 6px;border:var(--border-subtle);color:var(--acc);font-size:10px;}
</style></head><body>
<div class="hdr">
  <div class="hdr-left"><div class="logo">TUPPERWARE</div><div class="subtitle">LXC PROVISIONER // {{ hostname }}</div></div>
  <div class="hdr-right"><div class="status-dot warn"></div><div class="status-txt warn">SETUP REQUIRED</div></div>
</div>

<div class="setup-banner">
  <div class="setup-title">NO TEMPLATE FOUND</div>
  <div class="setup-msg">Tupperware needs an LXC template at VMID {{ template_vmid }} to clone containers from.</div>
  <div class="setup-detail">Pick one of the three options below. Once a template exists at VMID {{ template_vmid }}, refresh this page and Tupperware is ready.</div>
</div>

<div class="opt-grid">

  <div class="opt">
    <div class="opt-num">1</div>
    <div class="opt-name">Download sample template</div>
    <div class="opt-time">Fastest &mdash; ~2 minutes</div>
    <div class="opt-desc">Download a pre-built Tupperware-ready Debian 12 template from GitHub Releases. Ready to clone immediately.</div>
    <div class="opt-cmd"><span class="opt-cmd-comment"># On this Proxmox host:</span><br>
tupperware-import-template
    </div>
  </div>

  <div class="opt">
    <div class="opt-num">2</div>
    <div class="opt-name">Build from scratch</div>
    <div class="opt-time">~4 minutes</div>
    <div class="opt-desc">Build a fresh template using the standard Debian 12 LXC template, with Tailscale and the firstboot service injected.</div>
    <div class="opt-cmd"><span class="opt-cmd-comment"># On this Proxmox host:</span><br>
tupperware-build-template
    </div>
  </div>

  <div class="opt">
    <div class="opt-num">3</div>
    <div class="opt-name">Use your own template</div>
    <div class="opt-time">Manual</div>
    <div class="opt-desc">If you have an existing template at a different VMID, point Tupperware at it. (Must have Tailscale + tailscale-firstboot.service installed.)</div>
    <div class="opt-cmd"><span class="opt-cmd-comment"># Edit /etc/systemd/system/tupperware.service:</span><br>
Environment=TEMPLATE_VMID=&lt;your-vmid&gt;<br>
<span class="opt-cmd-comment"># Then:</span><br>
systemctl daemon-reload<br>
systemctl restart tupperware
    </div>
  </div>

</div>

<div class="detail-panel">
  <div class="detail-title">WHAT'S A TUPPERWARE-READY TEMPLATE?</div>
  <div class="detail-body">
    Any Proxmox LXC template that has:<br>
    &nbsp;&nbsp;1. Tailscale installed (<code>apt install tailscale</code>)<br>
    &nbsp;&nbsp;2. A <code>tailscale-firstboot.service</code> systemd unit that reads <code>/etc/tailscale/authkey</code> on boot, runs <code>tailscale up</code>, then self-disables<br>
    &nbsp;&nbsp;3. Network configured for DHCP on <code>eth0</code><br>
    &nbsp;&nbsp;4. <code>/dev/net/tun</code> passthrough enabled in the LXC config<br>
    <br>
    Both <code>tupperware-import-template</code> (Option 1) and <code>tupperware-build-template</code> (Option 2) produce templates that meet these requirements.
  </div>
</div>

</body></html>
"""


INDEX = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>TUPPERWARE</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
""" + SHARED_STYLE + r"""
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px;}
.metric{background:var(--c2);border:var(--border);padding:16px;position:relative;overflow:hidden;}
.metric::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;}
.metric.blue::before{background:var(--acc);}
.metric.orange::before{background:var(--acc2);}
.metric.green::before{background:var(--acc3);}
.metric-label{font-size:9px;color:var(--txt2);letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;}
.metric-val{font-family:var(--fdisplay);font-size:36px;letter-spacing:2px;line-height:1;}
.metric.blue .metric-val{color:var(--acc);}
.metric.orange .metric-val{color:var(--acc2);}
.metric.green .metric-val{color:var(--acc3);}
.metric-sub{font-size:9px;color:var(--txt3);margin-top:4px;}
.panel-badge{font-size:9px;padding:2px 8px;border:1px solid;letter-spacing:1px;}
.panel-badge.live{color:var(--acc3);border-color:var(--acc3);}
.panel-badge.warn{color:var(--acc2);border-color:var(--acc2);}
.panel-badge.err{color:var(--danger);border-color:var(--danger);}
.panel-badge.idle{color:var(--txt3);border-color:var(--txt3);}
.form-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1fr 1fr;gap:12px;}
.form-grid.row2{grid-template-columns:1fr 1fr 1fr;margin-top:12px;}
.form-field{display:flex;flex-direction:column;gap:6px;}
.form-label{font-size:9px;color:var(--txt2);letter-spacing:2px;text-transform:uppercase;}
.form-input{background:var(--c3);border:var(--border);color:var(--txt);font-family:var(--fmono);font-size:11px;padding:10px 14px;outline:none;}
.form-input:focus{border-color:var(--acc);}
.form-input::placeholder{color:var(--txt3);}
.form-select{background:var(--c3);border:var(--border);color:var(--txt);font-family:var(--fmono);font-size:11px;padding:10px 14px;outline:none;appearance:none;cursor:pointer;}
.form-select:focus{border-color:var(--acc);}
.btn-row{margin-top:16px;display:flex;gap:8px;}
.btn{background:transparent;border:1px solid var(--acc);color:var(--acc);font-family:var(--fmono);font-size:11px;padding:12px 28px;cursor:pointer;letter-spacing:3px;text-transform:uppercase;}
.btn:hover{background:rgba(0,212,255,0.1);}
.btn:disabled{opacity:0.4;cursor:not-allowed;}
.btn-small{padding:6px 14px;font-size:9px;letter-spacing:2px;}
.console{background:#000;border:var(--border);padding:14px;min-height:200px;max-height:480px;overflow-y:auto;font-family:var(--fmono);font-size:11px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;}
.console .ok{color:var(--acc3);}
.console .info{color:var(--acc);}
.console .warn{color:var(--acc2);}
.console .err{color:var(--danger);}
.console .dim{color:var(--txt3);}
.console-empty{color:var(--txt3);font-style:italic;}
.inv-table{width:100%;border-collapse:collapse;font-size:11px;}
.inv-table th{text-align:left;padding:8px 10px;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--txt2);border-bottom:var(--border);font-weight:normal;}
.inv-table td{padding:10px;border-bottom:var(--border-subtle);vertical-align:top;}
.inv-table tr:hover td{background:rgba(0,212,255,0.03);}
.inv-vmid{color:var(--acc);font-weight:500;}
.inv-name{color:var(--txt);font-weight:500;}
.inv-status{display:inline-block;padding:2px 8px;border:1px solid;font-size:9px;letter-spacing:1px;}
.inv-status.running{color:var(--acc3);border-color:var(--acc3);}
.inv-status.stopped{color:var(--txt3);border-color:var(--txt3);}
.inv-ip{font-size:10px;color:var(--txt2);}
.inv-ip-ts{color:var(--acc);}
.inv-tags{display:inline-block;padding:1px 6px;border:1px solid var(--acc2);color:var(--acc2);font-size:9px;margin-right:4px;}
.inv-storage{font-size:10px;color:var(--txt2);}
.inv-notes{color:var(--txt2);font-size:10px;font-style:italic;max-width:280px;white-space:pre-wrap;}
.inv-notes-empty{color:var(--txt3);font-style:italic;}
.inv-empty{text-align:center;color:var(--txt3);font-style:italic;padding:30px;}
@media (max-width:900px){.metrics{grid-template-columns:repeat(2,1fr);}.form-grid{grid-template-columns:1fr 1fr;}.form-grid.row2{grid-template-columns:1fr;}.inv-table{font-size:10px;}}
</style></head><body>
<div class="hdr">
  <div class="hdr-left"><div class="logo">TUPPERWARE</div><div class="subtitle">LXC PROVISIONER // {{ m.hostname }}</div></div>
  <div class="hdr-right"><div class="clock" id="clock">--:--:--</div><div class="status-dot"></div><div class="status-txt">OPERATIONAL</div></div>
</div>
<div class="metrics">
  <div class="metric blue"><div class="metric-label">CONTAINERS</div><div class="metric-val">{{ m.ct_count }}</div><div class="metric-sub">LXC on host</div></div>
  <div class="metric orange"><div class="metric-label">VIRTUAL MACHINES</div><div class="metric-val">{{ m.vm_count }}</div><div class="metric-sub">QEMU on host</div></div>
  <div class="metric green"><div class="metric-label">TAILNET PEERS</div><div class="metric-val">{{ m.ts_peers }}</div><div class="metric-sub">visible from {{ m.ts_self }}</div></div>
  <div class="metric blue"><div class="metric-label">NEXT VMID</div><div class="metric-val">{{ m.next_vmid }}</div><div class="metric-sub">auto-pick available</div></div>
</div>
<div class="panel">
  <div class="panel-hdr"><div class="panel-title">CLONE PARAMETERS</div><div class="panel-badge idle" id="form-status">READY</div></div>
  <form id="clone-form">
    <div class="form-grid">
      <div class="form-field"><div class="form-label">HOSTNAME</div><input class="form-input" type="text" name="hostname" required placeholder="lab-lxc-01" pattern="[a-zA-Z0-9\-]+" autofocus></div>
      <div class="form-field"><div class="form-label">VMID</div><input class="form-input" type="number" name="vmid" placeholder="{{ m.next_vmid }}" min="100" max="999999"></div>
      <div class="form-field"><div class="form-label">CORES</div><input class="form-input" type="number" name="cores" placeholder="1" min="1" max="16"></div>
      <div class="form-field"><div class="form-label">MEMORY MB</div><input class="form-input" type="number" name="memory" placeholder="512" min="128"></div>
      <div class="form-field"><div class="form-label">DISK GB</div><input class="form-input" type="number" name="disk" placeholder="4" min="4"></div>
    </div>
    <div class="form-grid row2">
      <div class="form-field"><div class="form-label">STORAGE BACKEND</div>
        <select class="form-select" name="storage">
          {% for s in storages %}
            <option value="{{ s.name }}"{% if s.name == default_storage %} selected{% endif %}>{{ s.name }} ({{ s.type }})</option>
          {% endfor %}
          {% if not storages %}
            <option value="local-lvm">local-lvm (default)</option>
          {% endif %}
        </select>
      </div>
      <div class="form-field"><div class="form-label">ROOT PASSWORD (OPTIONAL)</div><input class="form-input" type="password" name="rootpw" placeholder="leave blank for tailscale ssh only" autocomplete="new-password"></div>
    </div>
    <div class="btn-row"><button class="btn" type="submit" id="submit-btn">CLONE &amp; JOIN TAILNET</button></div>
  </form>
</div>
<div class="panel">
  <div class="panel-hdr"><div class="panel-title">PROVISIONING CONSOLE</div><div class="panel-badge idle" id="console-status">IDLE</div></div>
  <div class="console" id="console"><div class="console-empty">Awaiting clone request...</div></div>
</div>
<div class="panel">
  <div class="panel-hdr"><div class="panel-title">INVENTORY &mdash; {{ containers|length }} CONTAINER{{ '' if containers|length == 1 else 'S' }}</div>
    <button class="btn btn-small" type="button" onclick="window.location.reload()">REFRESH</button>
  </div>
  {% if containers %}
  <table class="inv-table">
    <thead>
      <tr>
        <th>VMID</th>
        <th>HOSTNAME</th>
        <th>STATUS</th>
        <th>CPU / MEM / DISK</th>
        <th>STORAGE</th>
        <th>NETWORK</th>
        <th>TAGS</th>
        <th>NOTES</th>
      </tr>
    </thead>
    <tbody>
    {% for c in containers %}
      <tr>
        <td class="inv-vmid">{{ c.vmid }}</td>
        <td class="inv-name">{{ c.name }}</td>
        <td><span class="inv-status {{ c.status }}">{{ c.status }}</span></td>
        <td>{{ c.cores }}c / {{ c.memory }}MB / {{ c.disk }}</td>
        <td class="inv-storage">{{ c.storage or '—' }}</td>
        <td class="inv-ip">
          {% if c.lan_ip %}{{ c.lan_ip }}<br>{% endif %}
          {% if c.ts_ip %}<span class="inv-ip-ts">{{ c.ts_ip }}</span>{% endif %}
        </td>
        <td>
          {% if c.tags %}
            {% for t in c.tags.split(';') %}
              {% if t %}<span class="inv-tags">{{ t }}</span>{% endif %}
            {% endfor %}
          {% else %}<span class="inv-notes-empty">&mdash;</span>{% endif %}
        </td>
        <td class="inv-notes">{% if c.description %}{{ c.description }}{% else %}<span class="inv-notes-empty">&mdash;</span>{% endif %}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <div class="inv-empty">No containers found.</div>
  {% endif %}
</div>
<script>
const NL = String.fromCharCode(10);
function tick(){var d=new Date();var p=function(n){return String(n).padStart(2,'0');};document.getElementById('clock').textContent=p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());}
setInterval(tick,1000);tick();
var form=document.getElementById('clone-form');
var submitBtn=document.getElementById('submit-btn');
var consoleEl=document.getElementById('console');
var formStatus=document.getElementById('form-status');
var consoleStatus=document.getElementById('console-status');
function setStatus(el,cls,text){el.className='panel-badge '+cls;el.textContent=text;}
function appendLine(text,cls){if(consoleEl.querySelector('.console-empty'))consoleEl.innerHTML='';var span=document.createElement('span');span.className=cls||'';span.textContent=text+NL;consoleEl.appendChild(span);consoleEl.scrollTop=consoleEl.scrollHeight;}
function classifyLine(line){if(/All done|ready|success|\[OK\]/i.test(line))return 'ok';if(/ERROR|failed|exception/i.test(line))return 'err';if(/WARN|warning|abandoning|conflict/i.test(line))return 'warn';if(/^\[\*\]/.test(line))return 'info';return 'dim';}
form.addEventListener('submit',async function(e){
  e.preventDefault();
  consoleEl.innerHTML='';
  submitBtn.disabled=true;
  setStatus(formStatus,'warn','BUSY');
  setStatus(consoleStatus,'live','STREAMING');
  var fd=new FormData(form);
  var params=new URLSearchParams();
  fd.forEach(function(v,k){params.append(k,v);});
  try{
    var resp=await fetch('/clone-stream',{method:'POST',body:params});
    if(!resp.ok||!resp.body)throw new Error('Stream init failed: '+resp.status);
    var reader=resp.body.getReader();
    var decoder=new TextDecoder();
    var buffer='';
    while(true){
      var chunk=await reader.read();
      if(chunk.done)break;
      buffer+=decoder.decode(chunk.value,{stream:true});
      var nl;
      while((nl=buffer.indexOf(NL))>=0){
        var line=buffer.slice(0,nl);
        buffer=buffer.slice(nl+1);
        if(line.length)appendLine(line,classifyLine(line));
      }
    }
    if(buffer.length)appendLine(buffer,classifyLine(buffer));
    setStatus(formStatus,'live','COMPLETE');
    setStatus(consoleStatus,'live','DONE');
  }catch(err){
    appendLine('[!] '+err.message,'err');
    setStatus(formStatus,'err','FAILED');
    setStatus(consoleStatus,'err','ERROR');
  }finally{
    submitBtn.disabled=false;
  }
});
</script>
</body></html>
"""


@app.route("/")
def index():
    if not template_exists():
        try:
            hostname = subprocess.check_output(["hostname"], text=True).strip()
        except Exception:
            hostname = "proxmox"
        return render_template_string(
            SETUP_PAGE,
            hostname=hostname,
            template_vmid=TEMPLATE_VMID,
            sample_url=SAMPLE_TEMPLATE_URL,
        )
    return render_template_string(
        INDEX,
        m=host_metrics(),
        containers=list_containers(),
        storages=list_storage_backends(),
        default_storage=DEFAULT_STORAGE,
    )


@app.route("/clone-stream", methods=["POST"])
def clone_stream():
    if not template_exists():
        return Response("[!] No template found at VMID " + str(TEMPLATE_VMID) + ". Cannot clone.\n", mimetype="text/plain")

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
    storage = request.form.get("storage", "").strip() or DEFAULT_STORAGE

    if not re.match(r"^[a-zA-Z0-9_\-]+$", storage):
        return Response("[!] Invalid storage name.\n", mimetype="text/plain")

    def generate():
        yield "[*] Tupperware: cloning " + hostname + " as VMID " + str(vmid_int) + " on storage '" + storage + "'\n"
        try:
            proc = subprocess.Popen(
                [CLONE_SCRIPT, str(vmid_int), hostname, "--storage", storage],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
            for line in iter(proc.stdout.readline, ""):
                yield line
            proc.wait()
            if proc.returncode != 0:
                yield "[!] Clone script exited with code " + str(proc.returncode) + "\n"
                return
            if cores or memory:
                args = ["pct", "set", str(vmid_int)]
                if cores: args += ["-cores", cores]
                if memory: args += ["-memory", memory]
                yield "[*] Applying CPU/memory overrides...\n"
                r = subprocess.run(args, capture_output=True, text=True)
                if r.stdout: yield r.stdout
                if r.stderr: yield r.stderr
            if disk and int(disk) > 4:
                yield "[*] Resizing rootfs to " + disk + "G...\n"
                r = subprocess.run(["pct", "resize", str(vmid_int), "rootfs", disk + "G"], capture_output=True, text=True)
                if r.stdout: yield r.stdout
                if r.stderr: yield r.stderr
            if rootpw:
                yield "[*] Setting root password...\n"
                r = subprocess.run(
                    ["pct", "exec", str(vmid_int), "--", "bash", "-c", "echo 'root:" + rootpw + "' | chpasswd"],
                    capture_output=True, text=True,
                )
                yield "    Password set.\n" if r.returncode == 0 else "    Failed: " + r.stderr + "\n"
            yield "\n[OK] All done. " + hostname + " (VMID " + str(vmid_int) + ") should be on the tailnet.\n"
        except Exception as e:
            yield "\n[!] Exception: " + str(e) + "\n"

    return Response(stream_with_context(generate()), mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), threaded=True)
