# Security — OAuth Credentials and Key Handling

Tupperware's whole design rests on one piece of long-lived credential: a Tailscale OAuth client stored at `/root/.tailscale/oauth` on your Proxmox host. This document explains what that credential does, what it can and can't do, and how to rotate it if anything ever feels off.

---

## The threat model in one paragraph

Tupperware uses your OAuth client to mint **single-use, 10-minute, pre-authorized, tag-restricted** Tailscale auth keys, one per container clone. The OAuth client itself never expires — that's why we use OAuth instead of a standing auth key. If a single minted key leaks, it expires in 10 minutes and can only join one device with `tag:lxc`. If your OAuth client leaks, an attacker can mint unlimited `tag:lxc` devices on your tailnet for as long as the client remains valid — they cannot do anything else (read other devices, modify ACLs, change DNS, etc.) because the client is scoped to `Auth Keys: Write` with tag restriction.

In short: the blast radius of a leaked OAuth client is "someone could add fake tag:lxc devices to your tailnet." Your tailnet ACLs determine what those fake devices could actually reach.

---

## What's in the credentials file

```
/root/.tailscale/oauth   (chmod 600, root-only)
```

Contains two variables:

```bash
TS_OAUTH_CLIENT_ID=k...          # public-ish identifier
TS_OAUTH_CLIENT_SECRET=tskey-client-...   # the actual secret
```

The client secret is the only sensitive value. The client ID is similar to a username — useful for auditing in the Tailscale admin console but not enough to authenticate alone.

---

## What the credentials can do

With Tupperware's recommended OAuth client configuration (`Auth Keys: Write`, restricted to `tag:lxc`), the credential can:

- Request an access token from `api.tailscale.com/api/v2/oauth/token`
- Use the access token to mint Tailscale auth keys (`POST /api/v2/tailnet/-/keys`) — but only keys for devices tagged `tag:lxc`

The credential **cannot**:

- Read any devices on your tailnet (no `Devices: Read` scope unless you added it for v0.2)
- Modify ACLs, tagOwners, DNS settings, or routing
- Mint keys for any tag other than `tag:lxc`
- Access tailnet member accounts, billing, or settings
- Authenticate as any user on the tailnet

---

## What an attacker could do with a leaked credential

If your OAuth client secret leaked, an attacker on the internet could:

1. Run `curl` against the Tailscale API to mint auth keys tagged `tag:lxc`
2. Spin up devices on your tailnet using those keys
3. Those devices would have whatever access your tailnet ACLs grant to `tag:lxc`

If your ACLs say `tag:lxc` can reach everything (the default open ACL), an attacker's fake device could reach everything on your tailnet.

If your ACLs say `tag:lxc` can only be reached *from* devices (the safer pattern), an attacker's fake `tag:lxc` device would be a dead-end — nothing on your tailnet would be reachable from it.

**Recommendation**: use directional ACLs. `src: autogroup:member, dst: tag:lxc` (members can reach containers) is much safer than `src: tag:lxc, dst: *` (containers can reach everything).

---

## How to rotate OAuth credentials

If you suspect your credentials may have been exposed (committed to a public repo, pasted in a shared document, screen-shared, etc.), rotate immediately. Takes ~5 minutes.

### Step 1 — Revoke the old client

1. Go to https://login.tailscale.com/admin/settings/oauth
2. Find your existing Tupperware OAuth client in the list
3. Click the trash icon to revoke it

The moment you click revoke, the old credential stops working. Any in-progress clones using the old credential will fail (worst case: a container exists but didn't join the tailnet — you can manually inject a fresh key later).

### Step 2 — Generate a replacement

1. Same page → **+ Generate credential**
2. Configure:
   - Description: `Tupperware provisioner` (or your preferred label)
   - Scopes: **Auth Keys: Write** only
   - Tags: `tag:lxc`
3. Click **Generate credential**
4. Copy the new Client ID and Client Secret immediately (shown once)

### Step 3 — Update every host running Tupperware

On EACH Proxmox host with Tupperware installed:

```bash
cat > /root/.tailscale/oauth <<'EOF'
TS_OAUTH_CLIENT_ID=<new-client-id>
TS_OAUTH_CLIENT_SECRET=<new-client-secret>
EOF
chmod 600 /root/.tailscale/oauth
```

No service restart needed. The clone script reads the file fresh on every invocation.

### Step 4 — Verify

Test a clone via the web UI or CLI:

```bash
tupperware-new 299 rotate-test
```

Should succeed. If it does, rotation is complete.

---

## What is NOT in the credentials file or anywhere on your hosts

To be explicit about what Tupperware does NOT store:

- **No user account credentials.** Tupperware never sees your Tailscale account password or 2FA tokens.
- **No standing auth keys.** Every clone gets a fresh single-use key that's shredded after use.
- **No SSH private keys.** Tupperware does not generate or store SSH keys.
- **No state file with persistent secrets.** All state lives in Proxmox config files and the OAuth credentials file.

The cloned containers themselves contain no credentials at all after first boot — the auth key is shredded once `tailscale up` succeeds.

---

## Frequently asked

**Q: I copied someone else's credentials from a script or screenshot. Am I using their tailnet?**

Yes. Whoever owns the OAuth client owns the tailnet those credentials authenticate to. If you used someone else's credentials, your containers are joining their tailnet, not yours. Rotate immediately (Step 2 above generates new credentials in *your* tailnet) and clean up containers that joined the wrong tailnet.

**Q: Can I use the same OAuth client on multiple Proxmox hosts?**

Yes. The credential is tailnet-scoped, not host-scoped. Putting the same `/root/.tailscale/oauth` on five Proxmox hosts is perfectly fine — they'll all mint keys against the same OAuth client, all containers will land on the same tailnet, all tagged `tag:lxc`.

**Q: Should I use separate OAuth clients per host for blast-radius isolation?**

Maybe. The trade-off:
- **Separate clients per host**: if one host is compromised, you only need to rotate that host's client. Slightly more setup overhead.
- **Shared client across hosts**: simpler to manage, but a compromise of one host's credentials affects every host using the same client.

For a homelab with a few Proxmox boxes, shared is fine. For a corporate or multi-tenant setup, separate per host.

**Q: How often should I rotate?**

There's no automatic expiry, so it's your call. Reasonable cadences:
- After any potential leak (immediately)
- After offboarding anyone who had access
- Annually as routine hygiene

The rotation procedure is short enough that there's no excuse not to rotate when in doubt.

**Q: Can I tell who's been using my OAuth client?**

Tailscale logs OAuth token requests in the audit log (https://login.tailscale.com/admin/settings/audit-logs). You can see when keys were minted, by which client, and which tag was applied. If you see key mints you don't recognize, rotate.

---

## Summary

- The OAuth client is the only long-lived secret. Protect it like any password.
- Each cloned container gets a fresh 10-minute key, shredded after use.
- Tag scoping (`tag:lxc`) limits blast radius even if the OAuth client leaks.
- Rotation takes 5 minutes and is the right response to any suspicion of exposure.
- Use directional tailnet ACLs (`autogroup:member -> tag:lxc`) for defense in depth.
