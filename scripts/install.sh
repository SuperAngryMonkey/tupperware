#!/bin/bash
# Tupperware installer v0.2

set -euo pipefail

REPO_RAW="${TUPPERWARE_REPO_RAW:-https://raw.githubusercontent.com/SuperAngryMonkey/tupperware/main}"

if [[ $EUID -ne 0 ]]; then echo "ERROR: must run as root" >&2; exit 1; fi

echo "[*] Tupperware installer v0.2"
echo

if ! command -v pct >/dev/null 2>&1; then echo "ERROR: pct not found. Proxmox VE required." >&2; exit 1; fi

# Cleanup legacy
for legacy in build-tailscale-template.sh new-tailscale-ct.sh; do
    [[ -f /usr/local/sbin/$legacy ]] && rm -f /usr/local/sbin/$legacy && echo "[*] Removed legacy: $legacy"
done

INSTALL_FROM_LOCAL=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/tupperware-new.sh" ]]; then
    INSTALL_FROM_LOCAL=1
    echo "[*] Installing from local: $SCRIPT_DIR"
else
    echo "[*] Installing from $REPO_RAW"
fi

install_script() {
    local name="$1" target="/usr/local/sbin/${1%.sh}"
    if [[ $INSTALL_FROM_LOCAL -eq 1 && -f "$SCRIPT_DIR/$name" ]]; then
        cp "$SCRIPT_DIR/$name" "$target"
    else
        curl -fsSL "$REPO_RAW/scripts/$name" -o "$target" || { echo "    [!] Failed: $name"; return 0; }
    fi
    chmod +x "$target"
    echo "    [+] $target"
}

echo "[*] Installing scripts..."
install_script tupperware-preflight.sh
install_script tupperware-new.sh
install_script tupperware-build-template.sh
install_script tupperware-import-template.sh
install_script tupperware-export-template.sh
install_script tupperware-transfer.sh
install_script tupperware-rejoin.sh
install_script tupperware-uninstall.sh

# Create log directory for transfer audit log
mkdir -p /var/log/tupperware
chmod 750 /var/log/tupperware

# Logrotate
cat > /etc/logrotate.d/tupperware <<'EOF'
/var/log/tupperware/*.log {
    monthly
    rotate 12
    compress
    missingok
    notifempty
}
EOF

echo
echo "[OK] Tupperware tooling installed."
echo
echo "==== NEXT STEPS ===="
echo "  1. Stash OAuth at /root/.tailscale/oauth (chmod 600)"
echo "  2. tupperware-import-template     # get a template"
echo "  3. Install web UI: curl -fsSL $REPO_RAW/scripts/install-webui.sh | bash"
echo
echo "For v0.2 transfer:"
echo "  - Tag BOTH Proxmox hosts as 'tag:prox-host' in Tailscale admin"
echo "  - Add ACL grant for tag:prox-host SSH"
echo "  - See docs/v0.2-transfer.md"
