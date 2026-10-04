# Crash reports

Kettle writes a crash report on the device whenever a game or part of the system crashes. The
player sees them in Game Mode (Quick Access > Crash Reports) and can share one, which uploads it
to Kettle's crash report server and gives a link (and a QR code) to open it on a phone and file
it on GitHub. Nothing leaves the device unless the player shares a report.

## On the device

`kettle-crashd` (`packages/kettle-crash`) writes one directory per crash to
`/var/log/kettle-crash` (on `/home`, so reports survive updates; the newest 50, at most 512 MB):

| Kind | Caught from | Report files |
|---|---|---|
| `coredump` | a process killed by a signal: systemd-coredump's journal entry | `backtrace.txt`, `environ.txt` |
| `game` | a Windows game's crash in Wine (`wine: Unhandled ...`, no core dump) or a lost GPU (`VK_ERROR_DEVICE_LOST`), in the game's output: games write it to Steam's, `~/.local/share/Steam/logs/steam_output.log` | `output.txt` (the 400 lines before, 4 s after), `environ.txt` |
| `devcoredump` | a driver's device dump (GPU hang, firmware crash), through udev | `devcoredump.bin.gz` |

Each also has `report.json` (what crashed; the game it belongs to or that was running, with the
engine it's built on (`gameengine.py`, shared with Game Settings) and the Kettle features on for
it; the Kettle build, slot, kernel and package versions), `journal.txt`
and `kernel.txt`. Core files stay where systemd-coredump keeps them (`coredumpctl`), compressed
and bounded (`/usr/lib/systemd/coredump.conf.d/60-kettle.conf`). A crash repeating within 30 s is
counted in the same report.

The Crash Reports plugin (`packages/kettle-decky-plugins/crash`) lists them, shows a toast for the
crashes a player notices (a game, gamescope, Steam, the desktop, the GPU), and opens each one on
its own page.

## Sharing

**Share…** on a report's page asks first, then uploads it. What is taken out on the device before
upload (`_bundle` in the plugin's `main.py`):

- `/home/<user>` paths (as `~`), SteamID64s, the Steam account and profile names signed in on the
  device (`loginusers.vdf`), MAC and IP addresses, and the hostname when it isn't `kettle`
- journal lines from NetworkManager, wpa_supplicant, iwd, bluetoothd, avahi, sshd, sudo,
  systemd-resolved, ModemManager and logind (network and device names, logins)
- the environment, except Proton, Wine, DXVK, vkd3d, Mesa/Turnip, FEX, Vulkan, gamescope, SDL and
  Steam's ids for the game
- core files and device dumps (never uploaded), and all but the last 256 KB of each log

The server answers with a link, `https://crash.kettlelinux.org/r/<id>`, which the plugin shows
as a QR code. The page lists the report and has **Report on GitHub**: a new issue with the
report's facts and link filled in. The id is 60 random bits: the page is public to anyone with
the link, and unlisted (`noindex`).

An image has the Share button only when it's built with `KETTLE_CRASH_URL` (in `local.env`); it
is written to `/usr/lib/kettle/crash.conf`.

## The server

`server/crash-reports`: a Cloudflare Worker in front of an R2 bucket, next to the update server
(UPDATES.md). It takes only gzipped Kettle reports in the plugin's format (1 MB compressed, 8 MB
unpacked, 256 KB per file), 10 uploads a minute per address, and keeps each as
`reports/<id>.json.gz`, with its kind, app id, build and device as metadata.

One-time setup:

1. R2: create a bucket `kettle-crash-reports`. Under *Settings > Object lifecycle rules*, add a
   rule deleting objects with prefix `reports/` 90 days after upload (the page says reports are
   kept 90 days).
2. `cd server/crash-reports && npm install && npx wrangler login`, then `npx wrangler deploy`.
   `wrangler.toml` puts it on the custom domain `crash.kettlelinux.org` (the `kettlelinux.org`
   zone is on Cloudflare already) and binds the bucket and the upload rate limit.
3. Check it: `curl -s https://crash.kettlelinux.org/r/aaaaaaaaaaaa` answers 404 "No such report".
4. In `local.env`: `KETTLE_CRASH_URL=https://crash.kettlelinux.org`, then build images as usual.

Locally: `npx wrangler dev` serves it on `http://127.0.0.1:8787` with a local bucket; point a
test at it with a `crash.conf` naming that address.

Reports can be listed and fetched with rclone (the `r2` remote, UPDATES.md):
`rclone ls r2:kettle-crash-reports/reports`, and `/r/<id>.json` gives one as uploaded.
