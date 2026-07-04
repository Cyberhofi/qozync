# Qobuz Purchase Sync

A self-hosted background service that automatically downloads **the music you've
bought on Qobuz** as owned, DRM-free FLAC/MP3 files, and mirrors new purchases on
a schedule. Comes with a web UI for an overview, activity, and settings.

It uses Qobuz's `purchase/getUserPurchasesIds` API to enumerate everything you
own, downloads anything missing from disk, tags it, organizes it into a clean
folder tree, and (optionally) triggers a **Jellyfin** library scan afterwards.
Downloading your own purchases works even without an active streaming subscription.

> This tool only downloads music **you have purchased**. Keep it for personal use.

> ⚠️ **Heads up: this is totally vibe-coded.** It was built quickly, mostly with
> an AI assistant, and published on the off chance someone else finds it useful.
> There are no guarantees, no promises of maintenance, and it might break the day
> Qobuz changes something. Read the code, use it at your own risk, and PRs welcome. ✌️

## Features

- 🔁 **Automatic sync** of all Qobuz purchases on a configurable interval (default 6h)
- 🎵 **Full quality** — up to Hi-Res 24-bit/192kHz FLAC (configurable)
- 🏷️ **Tagged & organized** — `Artist/Album (Year)/01 - Title.flac` with embedded cover art
- 🖥️ **Web UI** — dashboard, searchable library, live activity, logs, settings
- 📺 **Jellyfin integration** — one library scan per sync that adds files
- 🔐 **Safe credentials** — password used once to mint a token; secrets encrypted at rest;
  UI behind an admin password
- 🐳 **Docker-first** — one container, two volumes

## Quick start (Docker)

```bash
git clone <this repo> qobuz-sync && cd qobuz-sync
cp .env.example .env        # optional: set SECRET_KEY and TZ
docker compose up -d
```

Open <http://localhost:8080>:

1. **Set an admin password** (first run).
2. Go to **Settings → Qobuz account** and connect with your **auth token** (see below).
3. (Optional) Fill in **Jellyfin** URL + API key and **Test connection**.
4. Click **Sync now** and watch **Activity**. Files appear under `./music`.

## Deploy to a Linux server

Build the image **on the server** (native to its CPU architecture). You only need
Docker with the Compose plugin installed.

**1. Copy the project to the server** (from your Windows dev machine). You only
need the source — not `.venv/`, `config/`, or `music/`:

```bash
# via rsync (Git Bash / WSL / any shell with ssh):
rsync -av --exclude='.venv' --exclude='config' --exclude='music' \
      --exclude='__pycache__' --exclude='.git' \
      /c/Claude/Qobuz/  user@server:/opt/qobuz-sync/
```

Or push to a git repo and `git clone` it on the server, or `scp -r` the folder.
The files that matter: `app/`, `pyproject.toml`, `Dockerfile`, `docker-compose.yml`.

**2. On the server**, set a persistent encryption key and choose where music lands:

```bash
cd /opt/qobuz-sync
cp .env.example .env
echo "SECRET_KEY=$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" >> .env
# edit docker-compose.yml volumes if you want music on a specific disk, e.g.:
#   - /srv/media/music:/music
```

Setting `SECRET_KEY` in `.env` matters: it lets stored secrets (your Qobuz token,
Jellyfin key) survive container re-creation and image updates.

**3. Build and start:**

```bash
docker compose up -d --build
docker compose logs -f          # watch it boot
```

**4. Open it** at `http://<server-ip>:8080`, set an admin password, and connect
with a fresh auth token (grab a new one from your browser — see below). Then
**Sync now**. You start clean on the server; no need to copy your dev `config/`.

### Notes for server deployments

- **Reverse proxy + HTTPS** — the UI holds your Qobuz credentials behind an admin
  password, but it's plain HTTP on `:8080`. For anything beyond your LAN, put it
  behind a reverse proxy (Caddy/Traefik/nginx) with TLS, or only expose it on a
  private network / VPN. To bind to localhost only (proxy in front):
  `ports: ["127.0.0.1:8080:8080"]`.
- **File ownership** — the container runs as root, so downloaded files are
  root-owned. That's fine for a personal server; if another app (e.g. Jellyfin)
  needs a specific owner, `chown` the music dir or run the container with a
  matching `user:` in compose.
- **Jellyfin on the same host** — use the container/service name or host IP that's
  reachable from *inside* this container (e.g. `http://jellyfin:8096` if on the
  same Docker network, not `localhost`).
- **Updating later** — re-copy the source (or `git pull`) and run
  `docker compose up -d --build` again. Your `config/` and `music/` volumes persist.
- **Auto-start on boot** — `restart: unless-stopped` is already set, so the
  container comes back after a reboot as long as the Docker service is enabled
  (`sudo systemctl enable docker`).

### Connecting with an auth token (recommended)

> Since **April 2026** Qobuz blocks programmatic email/password logins (returns
> `401 User authentication is required`). This affects every third-party tool,
> not just this one. The reliable way to connect is with the token your browser
> already holds after you log in:

1. Open <https://play.qobuz.com> and log in normally.
2. Press <kbd>F12</kbd> → **Network** tab, then reload the page.
3. Click any request to `api.json`, open **Headers**, and find
   `x-user-auth-token` under *Request Headers*. (Or: **Application → Local Storage**.)
4. Copy the value and paste it into **Settings → Connect with token**.

The token is validated, then stored encrypted; your password is never involved.
The email/password field is still available as a fallback in case Qobuz restores
app logins, but it usually fails today.

Downloads land in `./music`; state lives in `./config` (SQLite DB + encryption key).

## How it works

| Step | Qobuz API |
|------|-----------|
| Get app credentials | scraped from the public web-player bundle (override in Settings) |
| Authenticate | browser `user_auth_token` (validated via `user/get`) |
| List purchases | `purchase/getUserPurchases` (albums expanded via `album/get`) |
| Resolve download | `track/getFileUrl` (MD5-signed with the app secret) |
| Save | stream file → tag with `mutagen` → organize |

The engine diffs the purchase list against a local SQLite catalog, so re-runs only
fetch new purchases. A track Qobuz serves as a sample (not owned) is marked
`skipped` and not retried.

## Configuration

Set in the UI (**Settings**) or via env (`.env` / compose):

| Setting | Env | Default |
|---------|-----|---------|
| Preferred quality | `QOBUZ_QUALITY` | `27` (Hi-Res ≤192k) |
| Sync interval (hours) | `QOBUZ_SYNC_INTERVAL_HOURS` | `6` |
| Music directory | `QOBUZ_MUSIC_DIR` | `/music` |
| Config directory | `QOBUZ_CONFIG_DIR` | `/config` |
| Encryption key | `SECRET_KEY` | auto-generated into config volume |
| Jellyfin URL / key | `JELLYFIN_URL` / `JELLYFIN_API_KEY` | — |

Quality `format_id`s: `27` Hi-Res ≤192kHz · `7` Hi-Res ≤96kHz · `6` FLAC CD · `5` MP3 320.
The request is automatically capped to the best quality each track offers.

## Local development

```bash
python -m venv .venv && . .venv/Scripts/activate    # ./.venv/bin/activate on Linux/mac
pip install -e ".[dev]"
export QOBUZ_CONFIG_DIR=./config QOBUZ_MUSIC_DIR=./music
uvicorn app.main:app --reload --port 8080
pytest
```

## Troubleshooting

- **"could not find app_id / secrets in bundle"** — Qobuz changed their web player.
  Obtain an `app_id`/`app_secret` and set them under **Settings → Advanced**.
- **Auth fails / token expired** — auth tokens expire; grab a fresh `x-user-auth-token`
  from the browser and reconnect under **Settings → Qobuz account**.
- **"User authentication is required" / email+password rejected** — expected since April 2026;
  use the auth-token method instead (see above).
- **Jellyfin not scanning** — confirm URL + API key with **Test connection**; the scan
  only fires when a sync run actually downloaded new files.

## Project layout

```
app/
  qobuz/     bundle credential extraction, API client, JSON models
  sync/      engine (diff + download), downloader (tag/organize), scheduler, jellyfin
  web/       FastAPI routes, Jinja templates, admin-password gate
  db.py      SQLAlchemy models + secret encryption
tests/       signing, path building, bundle parsing, model parsing
```
