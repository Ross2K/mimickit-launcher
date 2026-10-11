# Watching training from your phone (Tailscale)

The launcher can serve a small **read-only** dashboard (status, session/total time, speed, VRAM, progress estimate,
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
2. Tick **Enable**, keep port **8765**, *Listen on* **0.0.0.0** (needed so the Tailscale address can reach it), **Apply**.
3. The dialog shows the link with its access token (and a QR code if `pip install qrcode` is done in the launcher's
   Python). The token is required on every request; **New token** invalidates old links.

## 3. Windows Firewall

The first time the dashboard starts, Windows asks whether Python may communicate on networks. Allow **Private
networks** (Tailscale counts as one). If you clicked *Cancel* by accident: Windows Security -> Firewall & network
protection -> Allow an app through firewall -> tick *Private* for `python.exe` (or `pythonw.exe`).

## 4. Open it on the phone

With Tailscale connected on the phone, open:

    http://<pc-tailscale-name>:8765/?t=<token>

e.g. `http://my-pc:8765/?t=Ab3...`. Add it to the home screen for one-tap access. The page refreshes every 10 s.
Pinch or drag a chart to zoom/pan the time axis, double-tap to reset. The preview video streams (HTTP range requests).

## Do NOT port-forward

Don't forward port 8765 on your router or expose it to the internet. The dashboard is plain HTTP (no TLS) and is
meant for your private network only; Tailscale encrypts the traffic end to end. Treat the link like a password.

## Notifications instead (optional)

In the same dialog you can enter a **Discord webhook URL** and/or a **Telegram bot token + chat id**. The launcher then
posts a chart picture + status every N hours (default 3; 0 = off) and, if ticked, each new preview MP4 (skipped with a
note when it is larger than the service's upload limit: Discord 10 MB, Telegram 50 MB). **Send test** checks the setup.
These secrets are stored only in your local launcher settings file, never in the repository. Failures are logged
and never interrupt training.
