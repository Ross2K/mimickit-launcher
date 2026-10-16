# Watching training from your phone (Tailscale)

The launcher can serve a small dashboard (**read-only** unless *Allow phone control* is on: then Stop / Resume need a PIN session + per-tap confirmation) (status, session/total time, speed, VRAM, progress estimate,
both charts with touch zoom, the newest preview video, and a rate-limited *Render preview* button). Training can't be
started or stopped from the web. It is **off by default**.

The safe way to reach it from anywhere is **Tailscale**: a private network between your own devices, no open ports.

## 1. Install Tailscale

1. On the training PC: download Tailscale from <https://tailscale.com/download> (Windows installer), sign in.
2. On your phone: install the Tailscale app (App Store / Google Play) and sign in with the **same account**.
3. In the Tailscale app or admin page, note the PC's name (e.g. `my-pc`) or its `100.x.y.z` address.
   With MagicDNS on (the default) the name works directly.

## 2. Turn on the dashboard

1. In the launcher: **Settings -> Phone + notifications...**
2. Tick **Enable**, keep port **8765**, *Who can open it* **My phone and other devices (Tailscale recommended)** (needed so the Tailscale address can reach it), **Apply**.
3. The dialog lists the links - Tailscale addresses first, each labelled (Tailscale / LAN / hostname) with a
   Copy button - with the access token (and a QR code if `pip install qrcode` is done in the launcher's
   Python; installed while the dialog is open? press **Refresh**). The QR code uses the Tailscale link. The token is required on every request; **New token** invalidates old links.

## 3. Windows Firewall

The first time the dashboard starts, Windows asks whether Python may communicate on networks. Allow **Private
networks** (Tailscale counts as one). If you clicked *Cancel* by accident: Windows Security -> Firewall & network
protection -> Allow an app through firewall -> tick *Private* for `python.exe` (or `pythonw.exe`).

## 4. Open it on the phone

With Tailscale connected on the phone, open:

    http://<pc-tailscale-name>:8765/?t=<token>

e.g. `http://my-pc:8765/?t=Ab3...`. Add it to the home screen for one-tap access. The page refreshes every 10 s.
Pinch or drag a chart to zoom/pan the time axis, double-tap to reset. The preview video streams (HTTP range requests).

**Runs and patches (a0.8.0).** The Controls panel has two more closed sections:
- *Runs*: pick a config (the same list as the PC), num_envs and an output folder (`output/...`), then hold
  *Start new training*. To continue an earlier run, pick it under *Continue from* and hold *Continue from run*.
  A folder that already has a run is only replaced if you tick *Overwrite*.
- *MimicKit patches*: each patch with its state, plus Apply / Revert (hold to confirm).

The PC checks everything again and refuses with a plain reason, which also goes in its log:
- something is already running;
- unknown config or run;
- bad folder name;
- patches while training runs.

**Preview card (a0.8.0).** Play/Pause and a scrub bar sit under the video. Nothing plays until you press Play. The
closed *Preview options* section has:
- the clip (the last 12 previews);
- speed 0.25x / 0.5x / 1x;
- *Loop* (remembered on the phone);
- *Download MP4*.

*Render new preview* shows a progress bar while it works. Previews you request from the phone never open a player
on the PC.

## Do NOT port-forward

Don't forward port 8765 on your router or expose it to the internet. The dashboard is plain HTTP (no TLS) and is
meant for your private network only; Tailscale encrypts the traffic end to end. Treat the link like a password.

## Notifications instead (optional)

In the same dialog you can enter a **Discord webhook URL** and/or a **Telegram bot token + chat id**. The launcher then
posts a chart picture + status every N hours (default 3; 0 = off) and, if ticked, each new preview MP4 (skipped with a
note when it is larger than the service's upload limit: Discord 10 MB, Telegram 50 MB). **Send test** checks the setup.
These secrets are stored only in your local launcher settings file, never in the repository. Failures are logged
and never interrupt training.
