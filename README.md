# Purchase Sync (Qobuz + Bandcamp)

A self-hosted background service that automatically downloads **the music you've
bought on Qobuz and Bandcamp** as owned, DRM-free files, and mirrors new purchases
on a schedule. Comes with a web UI for an overview, activity, and settings.

For **Qobuz** it uses `purchase/getUserPurchasesIds` to enumerate everything you
own, downloads missing tracks, tags them, and organizes them into a clean folder
tree. For **Bandcamp** it reads your fan collection and downloads each purchase in
your chosen format (albums arrive as zips and are extracted; files come already
tagged). Both land in the same library and can trigger a **Jellyfin** scan when
new files appear. Downloading your own purchases works without an active
subscription — you already own the music.

> This tool only downloads music **you have purchased**. Keep it for personal use.

> ⚠️ **Heads up: this is totally vibe-coded.** It was built quickly, mostly with
> an AI assistant, and published on the off chance someone else finds it useful.
> There are no guarantees, no promises of maintenance, and it might break the day
> Qobuz changes something. Read the code, use it at your own risk, and PRs welcome. ✌️

## Features

- 🔁 **Automatic sync** of all Qobuz + Bandcamp purchases on a schedule (default 6h)
- 🎵 **Full quality** — Qobuz up to Hi-Res 24-bit/192kHz; Bandcamp FLAC/ALAC/WAV/MP3 (configurable)
- 🏷️ **Tagged & organized** — `Artist/Album (Year)/…` with embedded cover art
- 🛒 **Two sources, one library** — both write to the same folder; source badge + filter in the UI
- 🖥️ **Web UI** — dashboard, searchable library, live activity, logs, settings
- 📺 **Jellyfin integration** — one library scan per sync that adds files
- 🔐 **Safe credentials** — connect with a browser token / cookie (no passwords stored);
  secrets encrypted at rest; UI behind an admin password
- 🐳 **Docker-first** — one container, two volumes

## Quick start (Docker)

```bash
git clone https://github.com/Cyberhofi/qozync.git && cd qozync
cp .env.example .env        # optional: set TZ, or a fixed SECRET_KEY
docker compose up -d --build
```

Open <http://localhost:8080>:

1. **Set an admin password** (first run).
2. Go to **Settings → Qobuz account** and connect with your **auth token** (see below).
3. (Optional) Fill in **Jellyfin** URL + API key and **Test connection**.
4. Click **Sync now** and watch **Activity**. Files appear under `./music`.

## Deploy to a Linux server

Recommended: **clone the repo on the server and build there** — the image is built
native to the server's CPU architecture (matters on ARM boxes like a Raspberry Pi).
You only need Docker with the Compose plugin installed.

```bash
git clone https://github.com/Cyberhofi/qozync.git /opt/qobuz-sync
cd /opt/qobuz-sync
cp .env.example .env            # optional — see the SECRET_KEY note below
# (optional) point /music at a real disk by editing docker-compose.yml, e.g.:
#   - /srv/media/music:/music
docker compose up -d --build
docker compose logs -f          # watch it boot; Ctrl-C to stop watching
```

Then open `http://<server-ip>:8080`, set an admin password, connect with a fresh
auth token (see below), and hit **Sync now**. You start clean on the server — no
need to copy anything from your dev machine.

**Updating later:** `git pull && docker compose up -d --build`. Your `config/`
(token, DB) and `music/` volumes survive updates.

**Private repo?** The server needs read access. Simplest over HTTPS:
`git clone https://<user>:<token>@github.com/Cyberhofi/qozync.git` — or add a
read-only **deploy key** to the repo. A public repo clones as-is.

**No git on the server?** Copy the source directly instead (skip `.venv/`,
`config/`, `music/`):

```bash
rsync -av --exclude='.venv' --exclude='config' --exclude='music' \
      --exclude='__pycache__' --exclude='.git' \
      ./  user@server:/opt/qobuz-sync/
```

### About `SECRET_KEY`

It's **optional**. If unset, a key is generated into `config/secret.key` on first
run and — because `./config` is a persisted volume — your encrypted token survives
restarts and rebuilds. Set it explicitly only if you'd rather the key live in
`.env` (e.g. so you can back it up separately):

```bash
echo "SECRET_KEY=$(openssl rand -base64 32 | tr '+/' '-_')" >> .env
```

### Notes for server deployments

- **Reverse proxy + HTTPS** — the UI holds your Qobuz credentials behind an admin
  password, but it's plain HTTP on `:8080`. For anything beyond your LAN, put it
  behind a reverse proxy (Caddy/Traefik/nginx) with TLS, or only expose it on a
  private network / VPN. To bind to localhost only (proxy in front):
  `ports: ["127.0.0.1:8080:8080"]`.
- **File ownership / `Permission denied`** — by default the container runs as
  root. If your `/music` (or `/config`) maps to a folder owned by another user, a
  NAS/NFS share (root-squash), or a userns-remapped host, writes fail with
  `[Errno 13] Permission denied`. Fix it by running as the folder's owner: set
  `PUID`/`PGID` in `.env` (find them with `id <user>`) and make sure both host
  dirs are owned by that user (`sudo chown -R <uid>:<gid> <dir>`). Quick unblock
  on a local disk: `sudo chmod -R a+rwX <music-dir> <config-dir>`.
- **Jellyfin on the same host** — use the container/service name or host IP that's
  reachable from *inside* this container (e.g. `http://jellyfin:8096` if on the
  same Docker network, not `localhost`).
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

### Connecting Bandcamp

Bandcamp has no login API either, so — like the Qobuz token — you connect with the
`identity` cookie your browser already holds (it's stored encrypted; treat it like a
password):

1. Open <https://bandcamp.com> and log in normally.
2. Press <kbd>F12</kbd> → **Application** (Chrome) / **Storage** (Firefox) →
   **Cookies** → `https://bandcamp.com`.
3. Copy the full value of the cookie named `identity`.
4. Paste it into **Settings → Bandcamp account → Connect**, and pick your format.

Bandcamp albums download as a zip and are extracted into `Artist/Album/`; single-track
purchases are saved under `Artist/`. Files come already tagged with cover art.

## How it works

| Step | Qobuz | Bandcamp |
|------|-------|----------|
| Authenticate | browser `user_auth_token` (via `user/get`) | browser `identity` cookie |
| List purchases | `purchase/getUserPurchasesIds` → `album/get`+`track/get` | `fancollection/1/collection_items` |
| Resolve download | `track/getFileUrl` (MD5-signed) | redownload page `pagedata` → format URL |
| Save | stream → tag with `mutagen` → organize | stream zip/file → extract → organize |

Each source diffs its purchases against a local SQLite catalog (Qobuz at track grain,
Bandcamp at item grain), so re-runs only download what's missing. Bandcamp requests go
through `curl_cffi` (browser TLS impersonation) to avoid being blocked.

## Configuration

Set in the UI (**Settings**) or via env (`.env` / compose):

| Setting | Env | Default |
|---------|-----|---------|
| Qobuz quality | `QOBUZ_QUALITY` | `27` (Hi-Res ≤192k) |
| Bandcamp format | `BANDCAMP_FORMAT` | `flac` |
| Sync interval (hours) | `QOBUZ_SYNC_INTERVAL_HOURS` | `6` |
| Music directory | `QOBUZ_MUSIC_DIR` | `/music` |
| Config directory | `QOBUZ_CONFIG_DIR` | `/config` |
| Encryption key | `SECRET_KEY` | auto-generated into config volume |
| Jellyfin URL / key | `JELLYFIN_URL` / `JELLYFIN_API_KEY` | — |

Qobuz `format_id`s: `27` Hi-Res ≤192kHz · `7` Hi-Res ≤96kHz · `6` FLAC CD · `5` MP3 320
(capped to the best each track offers). Bandcamp formats: `flac`, `alac`, `wav`,
`aiff-lossless`, `mp3-320`, `mp3-v0`, `vorbis`, `aac-hi`.

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
- **Bandcamp "login expired" / auth errors** — the `identity` cookie rotates; grab a
  fresh one from your browser and reconnect under **Settings → Bandcamp account**.
- **Bandcamp downloads blocked / empty** — Bandcamp is TLS-fingerprinting-sensitive; the
  client already impersonates Chrome via `curl_cffi`. If a format isn't offered for an
  item it automatically falls back to the next-best lossless one.

## Project layout

```
app/
  qobuz/     bundle credential extraction, API client, JSON models
  bandcamp/  cookie client (curl_cffi), collection listing, download + zip extract, sync
  sync/      engine (runs each source: enumerate + diff + download), downloader
             (Qobuz tag/organize), scheduler, jellyfin notifier
  web/       FastAPI routes, Jinja templates, admin-password gate
  catalog.py source-agnostic views (counts, library, activity) over both tables
  config.py  typed settings store   ·   db.py  SQLAlchemy models + encryption
  paths.py   config/music dirs + key   ·   applog.py  logging to stdout + DB
tests/       signing, path building, bundle/model parsing, purchase enumeration,
             Bandcamp parsing + zip extraction
```
