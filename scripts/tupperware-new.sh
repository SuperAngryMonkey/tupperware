#!/bin/bash
# tupperware-new
# Clones the Tupperware template, mints a fresh OAuth-based auth key,
# injects it into the new container, and triggers the firstboot service.
#
# Usage: tupperware-new <new-vmid> <hostname>
# Example: tupperware-new 201 lab-lxc-01
#
# Override defaults via env vars:
#   TEMPLATE_VMID=9001 TAG=tag:prod tupperware-new 201 prod-lxc-01

set -euo pipefail

TEMPLATE_VMID="${TEMPLATE_VMID:-9000}"
OAUTH_FILE="${OAUTH_FILE:-/root/.tailscale/oauth}"
TAG="${TAG:-tag:lxc}"
NETWORK_WAIT_RETRIES="${NETWORK_WAIT_RETRIES:-150}"

if [[ $# -lt 2 ]]; then
    cat >&2 <<USAGE
Usage: tupperware-new <new-vmid> <hostname>

Arguments:
  new-vmid    VMID for the new container (e.g., 201)
  hostname    Hostname for the new container (used as Tailscale hostname)

Environment overrides:
  TEMPLATE_VMID   VMID of the template (default: 9000)
  OAUTH_FILE      Path to OAuth credentials (default: /root/.tailscale/oauth)
  TAG             Tailscale tag for the device (default: tag:lxc)
USAGE
    exit 1
fi

NEW_VMID="$1"
NEW_HOST="$2"

# Validate hostname
if ! [[ "$NEW_HOST" =~ ^[a-zA-Z0-9-]+$ ]]; then
    echo "ERROR: Hostname must only contain letters, numbers, and hyphens." >&2
    exit 1
fi

# Validate VMID
if ! [[ "$NEW_VMID" =~ ^[0-9]+$ ]] || (( NEW_VMID < 100 )); then
    echo "ERROR: VMID must be a number >= 100." >&2
    exit 1
fi

# Verify OAuth credentials
if [[ ! -r "$OAUTH_FILE" ]]; then
    echo "ERROR: Cannot read OAuth file $OAUTH_FILE" >&2
    echo "       See README.md, Step 1, for OAuth setup." >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$OAUTH_FILE"

if [[ -z "${TS_OAUTH_CLIENT_ID:-}" || -z "${TS_OAUTH_CLIENT_SECRET:-}" ]]; then
    echo "ERROR: TS_OAUTH_CLIENT_ID or TS_OAUTH_CLIENT_SECRET missing in $OAUTH_FILE" >&2
    exit 1
fi

# Verify template exists
if ! pct status "$TEMPLATE_VMID" &>/dev/null; then
    echo "ERROR: Template VMID $TEMPLATE_VMID not found." >&2
    echo "       Run tupperware-build-template first." >&2
    exit 1
fi

# Mint a fresh single-use auth key
echo "[*] Requesting OAuth access token..."
ACCESS_TOKEN=$(curl -fsS \
    -d "client_id=${TS_OAUTH_CLIENT_ID}" \
    -d "client_secret=${TS_OAUTH_CLIENT_SECRET}" \
    -d "grant_type=client_credentials" \
    https://api.tailscale.com/api/v2/oauth/token \
    | grep -oE '"access_token":"[^"]+"' | cut -d'"' -f4)

if [[ -z "$ACCESS_TOKEN" ]]; then
    echo "ERROR: Failed to get OAuth access token. Check your credentials." >&2
    exit 1
fi

echo "[*] Minting single-use auth key for $TAG..."
TS_KEY=$(curl -fsS \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -X POST \
    -d "{
        \"capabilities\": {
            \"devices\": {
                \"create\": {
                    \"reusable\": false,
                    \"ephemeral\": false,
                    \"preauthorized\": true,
                    \"tags\": [\"${TAG}\"]
                }
            }
        },
        \"expirySeconds\": 600
    }" \
    "https://api.tailscale.com/api/v2/tailnet/-/keys" \
    | grep -oE '"key":"[^"]+"' | cut -d'"' -f4)

if [[ -z "$TS_KEY" ]]; then
    echo "ERROR: Failed to mint auth key." >&2
    echo "       Check that '$TAG' is in your tailnet's tagOwners and that your" >&2
    echo "       OAuth client is authorized for it." >&2
    exit 1
fi

# Clone
echo "[*] Cloning $TEMPLATE_VMID -> $NEW_VMID ($NEW_HOST)..."
pct clone "$TEMPLATE_VMID" "$NEW_VMID" --hostname "$NEW_HOST"

echo "[*] Starting container..."
pct start "$NEW_VMID"

echo "[*] Waiting for network..."
NET_OK=0
for ((i=1; i<=NETWORK_WAIT_RETRIES; i++)); do
    if pct exec "$NEW_VMID" -- getent hosts api.tailscale.com >/dev/null 2>&1; then
        NET_OK=1
        break
    fi
    sleep 2
done
if [[ $NET_OK -eq 0 ]]; then
    echo "WARNING: Network slow to come up; continuing anyway." >&2
fi

echo "[*] Injecting auth key..."
echo "$TS_KEY" | pct exec "$NEW_VMID" -- tee /etc/tailscale/authkey >/dev/null
pct exec "$NEW_VMID" -- chmod 600 /etc/tailscale/authkey

echo "[*] Triggering Tailscale join..."
pct exec "$NEW_VMID" -- systemctl start tailscale-firstboot.service

sleep 4
echo
echo "[✓] $NEW_HOST should be on the tailnet."
echo "    Verify: pct exec $NEW_VMID -- tailscale status"
