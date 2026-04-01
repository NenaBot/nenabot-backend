# Raspberry Pi Remote Access

This document describes the Raspberry Pi remote access setup that already exists and how to connect to it.

## Current state

The Raspberry Pi is set up as follows:

- It was provisioned with a `user-data` file containing an SSH public key.
- SSH access is intended to be key-based for the configured Pi user.
- `cloudflared` runs on the Raspberry Pi.
- A Cloudflare Tunnel exposes the Pi's SSH service through `nenapi.jeanbaptistevanparys.be`.
- Cloudflare Access protects that hostname, so users must authenticate through the Access login flow before the SSH session is allowed.

In practice, the traffic path is:

```text
Your machine -> cloudflared on your machine -> Cloudflare Access -> Cloudflare Tunnel -> Raspberry Pi SSH service
```

## What you need on your machine

To connect, your machine needs:

- The SSH private key file named `Nenabot`, shared with users over Discord, matching the public key that was placed in the Pi `user-data`.
- `cloudflared` available locally.
- Access to the Cloudflare Access application that protects `nenapi.jeanbaptistevanparys.be`.

## Install `cloudflared` on your machine

Install `cloudflared` before configuring SSH.

### Linux (Debian/Ubuntu with `apt`)

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-public-v2.gpg | sudo tee /usr/share/keyrings/cloudflare-public-v2.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-public-v2.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install cloudflared
cloudflared --version
```

### macOS (Homebrew)

```bash
brew install cloudflared
cloudflared --version
```

### Windows (`winget`)

```powershell
winget install --id Cloudflare.cloudflared
cloudflared --version
```

## SSH hostname

The public SSH hostname for the Raspberry Pi is:

```text
nenapi.jeanbaptistevanparys.be
```

## SSH config

Add a host entry to your SSH config.

Save the shared private key locally as `Nenabot` inside your SSH directory.

SSH config file locations:

- Linux: `~/.ssh/config`
- macOS: `~/.ssh/config`
- Windows OpenSSH: `C:\Users\<you>\.ssh\config`

Typical key file locations:

- Linux: `~/.ssh/Nenabot`
- macOS: `~/.ssh/Nenabot`
- Windows: `C:\Users\<you>\.ssh\Nenabot`

Recommended entry:

```sshconfig
Host nenapi-pi
    HostName nenapi.jeanbaptistevanparys.be
    User ubuntu
    IdentityFile ~/.ssh/Nenabot
    ProxyCommand cloudflared access ssh --hostname %h
```

If `cloudflared` is not available on `PATH`, use the full executable path instead.

Example (`cloudflared` on `PATH`):

```sshconfig
Host nenapi-pi
    HostName nenapi.jeanbaptistevanparys.be
    User ubuntu
    IdentityFile ~/.ssh/Nenabot
    ProxyCommand cloudflared access ssh --hostname %h
```

Windows example:

```sshconfig
Host nenapi-pi
    HostName nenapi.jeanbaptistevanparys.be
    User ubuntu
    IdentityFile C:/Users/<you>/.ssh/Nenabot
    ProxyCommand cloudflared access ssh --hostname %h
```

Full-path fallback examples:

```sshconfig
ProxyCommand /usr/bin/cloudflared access ssh --hostname %h
ProxyCommand /opt/homebrew/bin/cloudflared access ssh --hostname %h
ProxyCommand "C:/Program Files/cloudflared/cloudflared.exe" access ssh --hostname %h
```

## Connect from the terminal

If you added the SSH config entry above, connect with:

```bash
ssh nenapi-pi
```

Without a host alias, the direct form is:

```bash
ssh -i ~/.ssh/Nenabot ubuntu@nenapi.jeanbaptistevanparys.be
```

## Cloudflare Access login flow

When you connect:

1. Run `ssh nenapi-pi`.
2. `cloudflared` starts on your machine.
3. A browser window opens for Cloudflare Access.
4. Sign in with the identity provider configured for the Access application.
5. Complete MFA if required.
6. After authentication succeeds, the SSH session to the Raspberry Pi is established.

If your Access session expires, you will be asked to authenticate again on the next connection.

## Connect from VS Code

VS Code Remote-SSH uses the same SSH config as your terminal.

Once `ssh nenapi-pi` works locally:

1. Open VS Code.
2. Install the `Remote - SSH` extension if it is not already installed.
3. Open the Command Palette.
4. Run `Remote-SSH: Connect to Host...`.
5. Select `nenapi-pi`.
6. Open the folder you want to work on.

If VS Code does not pick up the correct SSH config, set `remote.SSH.configFile` to the config file you are using.

## Quick checks

Useful local checks:

```bash
cloudflared --version
ssh nenapi-pi
```

Useful checks on the Raspberry Pi after login:

```bash
hostname
systemctl status ssh
systemctl status cloudflared
```

## References

- Cloudflare Tunnel downloads: <https://developers.cloudflare.com/tunnel/downloads/>
- SSH with client-side `cloudflared`: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/use-cases/ssh/ssh-cloudflared-authentication/>
- Cloudflare Access self-hosted applications: <https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/>
- VS Code Remote - SSH: <https://code.visualstudio.com/docs/remote/ssh>
