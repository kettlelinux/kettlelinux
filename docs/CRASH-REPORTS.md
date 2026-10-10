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
- core files and device dumps (never uploaded), and all but the last 256 KB (of UTF-8) of each log

The server answers with a link, `https://crash.kettlelinux.org/r/<id>`, which the plugin shows
as a QR code. The page lists the report and has **Report on GitHub**: a new issue with the
report's facts and link filled in. The id is 60 random bits: the page is public to anyone with
the link, unlisted (`noindex`), and kept only in the browser's cache (`private`, 5 minutes), so
a removed report is gone at once.

An image has the Share button only when it's built with `KETTLE_CRASH_URL` (in `local.env`); it
is written to `/usr/lib/kettle/crash.conf`.

## The server

`server/crash-reports`: a Cloudflare Worker in front of an R2 bucket, next to the update server
(UPDATES.md). It takes only gzipped Kettle reports in the plugin's format (1 MB compressed, 8 MB
unpacked), 10 uploads a minute per address, and 30 a day per address and 400 a day in all
(counted in a KV namespace under a hash of the address, kept two days). It keeps each as
`reports/<id>.json.gz`, with its kind, app id, build and device as metadata. What it keeps is
the report cut down to the fields `kettle-crashd` writes, each to a set size (anything else is
dropped), and the end of each file, 256 KB of UTF-8 at most. A report more than 90 days old is
never served, even if the bucket still has it.

One-time setup:

1. R2: create a bucket `kettle-crash-reports`.
2. `cd server/crash-reports && npm install && npx wrangler login`.
3. `./setup-lifecycle.sh`: the bucket's lifecycle rule deleting `reports/` 90 days after upload
   (the page and the site's legal page say reports are kept 90 days). `npx wrangler r2 bucket
   lifecycle list kettle-crash-reports` shows it.
4. `npx wrangler kv namespace create kettle-crash-counts`, and put the id it prints in
   `wrangler.toml` (`COUNTS`, the daily caps).
5. `npx wrangler secret put ADMIN_TOKEN` (a long random string, for removals, below).
6. `npx wrangler deploy`. `wrangler.toml` puts it on the custom domain `crash.kettlelinux.org`
   (the `kettlelinux.org` zone is on Cloudflare already) and binds the bucket, the KV namespace
   and the upload rate limit.
7. Check it: `curl -s https://crash.kettlelinux.org/r/aaaaaaaaaaaa` answers 404 "No such report".
8. In `local.env`: `KETTLE_CRASH_URL=https://crash.kettlelinux.org`, then build images as usual.

Updating a server set up before the daily caps and removals: steps 3 to 6.

Locally: `npx wrangler dev` serves it on `http://127.0.0.1:8787` with a local bucket; point a
test at it with a `crash.conf` naming that address.

Reports can be listed and fetched with rclone (the `r2` remote, UPDATES.md):
`rclone ls r2:kettle-crash-reports/reports`, and `/r/<id>.json` gives one as kept.

### Removal requests

Someone who shared a report can ask for it to be removed (kettlelinux.org/legal.html). With the
report's id (the end of its link):

```sh
curl -s -X DELETE -H "Authorization: Bearer <admin token>" https://crash.kettlelinux.org/v1/admin/reports/<id>
```

It answers `{"ok":true}`, or 404 if there's no such report. Wrong tokens count against the
address's upload rate limit.
