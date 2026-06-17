#!/bin/bash
# Tupperware installer — drops CLI scripts into /usr/local/sbin.
# Safe to re-run; overwrites existing scripts in place.

set -euo pipefail

REPO_RAW="${TUPPERWARE_REPO_RAW:-https://raw.githubusercontent.com/SuperAngryMonkey/tupperware/main}"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: must run as root" >&2
    exit 1
fi

echo "[*] Tupperware installer"
echo

if ! command -v pct >/dev/null 2>&1; then
    echo "ERROR: pct not found. This must run on a Proxmox VE host." >&2
    exit 1
fi
if ! command -v pveam >/dev/null 2>&1; then
    echo "ERROR: pveam not found. This must run on a Proxmox VE host." >&2
    exit 1
fi

# Clean up legacy install (older versions used different script names)
if [[ -f /usr/local/sbin/build-tailscale-template.sh ]]; then
    echo "[*] Removing legacy script: build-tailscale-template.sh"
    rm -f /usr/local/sbin/build-tailscale-template.sh
fi
if [[ -f /usr/local/sbin/new-tailscale-ct.sh ]]; then
    echo "[*] Removing legacy script: new-tailscale-ct.sh"
    rm -f /usr/local/sbin/new-tailscale-ct.sh
fi

INSTALL_FROM_LOCAL=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/tupperware-build-template.sh" && -f "$SCRIPT_DIR/tupperware-new.sh" ]]; then
    INSTALL_FROM_LOCAL=1
    echo "[*] Installing from local checkout: $SCRIPT_DIR"
else
    echo "[*] Installing from $REPO_RAW"
fi

install_script() {
    local name="$1"
    local target="/usr/local/sbin/${name%.sh}"
    if [[ $INSTALL_FROM_LOCAL -eq 1 && -f "$SCRIPT_DIR/$name" ]]; then
        cp "$SCRIPT_DIR/$name" "$target"
    else
        curl -fsSL "$REPO_RAW/scripts/$name" -o "$target"
    fi
    chmod +x "$target"
    echo "    [+] $target"
}

echo "[*] Installing scripts..."
install_script tupperware-preflight.sh
install_script tupperware-build-template.sh
install_script tupperware-new.sh
install_script tupperware-uninstall.sh

echo
echo "[OK] Tupperware tooling installed."
echo
echo "Next steps:"
echo "  1. Stash OAuth credentials in /root/.tailscale/oauth (see README)"
echo "  2. Run preflight:         tupperware-preflight"
echo "  3. Build the template:    tupperware-build-template"
echo "  4. Install the web UI:    curl -fsSL $REPO_RAW/scripts/install-webui.sh | bash"
echo
echo "To remove later:            tupperware-uninstall"
