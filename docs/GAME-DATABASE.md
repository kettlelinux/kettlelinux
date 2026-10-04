# Game Settings and the game database

Game Settings (Game Mode: Quick Access > Game Settings) lets a player try settings to get a game
running without typing launch options, keeps what they chose as the game's profile, and shares
settings that worked to the Kettle game database, where other players find and apply them.

## On the device

`packages/kettle-decky-plugins/game-settings`. For the selected game (the running one first):

- **Proton version**: Steam's compatibility tool for the game (`SteamClient.Apps.SpecifyCompatTool`).
  The tool Steam had before is kept, so "Steam's choice" or a reset puts it back.
- **Presets**: starting points (FEX fastest / safer / most accurate, DirectX 11 and 12 GPU checks,
  GPU hangs). A FEX preset replaces all FEX settings; the others set only their own.
- **Saved profiles**: the game's settings under a name, to load on other games (without the
  Proton version).
- **Kettle fixes**: the game fixes Welcome applies (`shared/gameFixes.ts`), shown for the games they
  are for and can be turned off or back on.
- **FEX, Graphics, Proton**: every option in the catalog, each "Default" until chosen.
- **Engine**: what the game is built on, found from the files in its install folder
  (`shared/gameengine.py`): the engine (`shared/engines.json`: Unity IL2CPP or Mono, Unreal,
  Source, Godot, GameMaker, RPG Maker, .NET, ...), whether Steam installed a Windows build (run
  through Proton and its ARM64EC FEX) or a native Linux one (FEX's Linux build), the main
  program's CPU (32 or 64-bit x86), and anti-cheat it ships (Easy Anti-Cheat, BattlEye), with a
  warning. Kept per Steam build in the plugin's `engines.json`, so it's looked up again after an
  update.
- **Suggested**: settings for the game's engine, each applied only when the player selects
  Apply (into the launch options, like any other setting). Two kinds: the catalog's presets with
  a `for` (engines, platforms, archs) the game matches, kept to well-founded ones (full x87
  precision for 32-bit games: FEX runs x87 at reduced precision, which only 32-bit code really
  uses); and "Worked for other <engine> games", from the game database (below), once there's
  enough to go by. Nothing is applied by itself: Steam's Proton and its FEX tool for native
  Linux games keep their own FEX config (Valve can send per-game TSO and Multiblock values),
  and the launch options' `FEX_*` variables, which both read, stay the player's choice.
- **Custom**: environment variables (`PROTON_`, `DXVK_`, `VKD3D_`, `WINE`, `FEX_`, `MESA_`, `SDL_`,
  `STAGING_`; not the ones the options above or the other plugins manage) and Wine DLL overrides.

Everything goes into the game's launch options through `shared/launchOptions.ts`, next to the
player's own options and the other plugins' (Frame Generation, Upscaling). The plugin records
which entries it wrote (`owned` in `games.json`) and only ever takes those out; Reset takes out
all of them. If the launch options lose the profile (edited by hand), the panel offers to
re-apply it.

### The catalog

`packages/kettle-decky-plugins/shared/game-options.json` lists every option: its section, label,
help text, choices, and target, one of:

| Target | Written as |
|---|---|
| `{"env": "NAME"}` | `NAME=value` |
| `{"flags": "NAME", "flag": "f"}` | `f` in the comma-separated `NAME` (`TU_DEBUG`, `VKD3D_CONFIG`) |
| `{"dxvk": "key"}` | `key=value` in `DXVK_CONFIG` |

The plugin, its backend and the server all validate against this one file, so the database can
only hold options Game Settings offers; a new option needs a plugin update and a server deploy.

FEX reads `FEX_<OPTION>` variables in the Windows (ARM64EC/WoW64) build too
(`FEX::Config::LoadConfig(..., _environ, ...)` in `Source/Windows/ARM64EC/Module.cpp`), which is
how Steam's FEX and Kettle's own Wine (`fex-emu-wine`) both pick up the per-game settings.

## The game database

Settings can be shared only once they've been tested: the player played the game for 5 minutes
with exactly those settings (the plugin counts play time per profile from Steam's app lifetime
notifications; any change starts the count again) and answered "Do these settings work?" with
yes. What is sent: the game's app id and name, the settings and the Proton version it ran with,
the device model, image variant and Kettle build, a rating (great / playable), an optional note,
the game's engine, platform, CPU and anti-cheat as above (not the names of its files), and a
random id made for the install (`install-id` in the plugin's settings; the server keeps
only its SHA-256), so each device counts once. Nothing is sent unless the player shares or
answers. The engine goes with votes too, so the database knows it for games whose settings
someone confirmed.

**Use verified settings automatically** (Game Settings > All games; off until the player turns
it on, and only on images with the database): games the player hasn't changed get the best
verified entry for this device type (same image variant; most confirmations net of reports).
Each installed game is looked up when the switch is turned on, when Game Mode starts, every 10
minutes for games installed since, and otherwise once a day (`auto_checked` in `games.json`).
What it doesn't do:

- touch a game whose settings the player set or changed (only an empty profile, or one it
  applied itself and nobody changed since, `auto_eligible`)
- put back an entry the player took off with Reset (`auto_skip`); a different verified entry
  still can be applied later
- apply an entry that needs a Proton version that isn't installed, or change the running game

An entry applied this way shows as "From the game database (verified, applied automatically)",
with the same "Works here" / "Doesn't work" answers as one applied by hand.

A player who applies an entry (Known good settings > Apply) can answer whether it worked for
them: "Doesn't work" after any launch, "Works here" after 5 minutes. Sharing settings someone on
the same kind of device already shared counts as a "works" for that entry.

Entries are **community** until the Kettle team approves them (**verified**). Community entries
show their counts; one reported broken 3 more times than confirmed is hidden. Notes show only on
verified entries.

An image has the database only when it's built with `KETTLE_GAMES_URL` (in `local.env`); it is
written to `/usr/lib/kettle/games.conf`. Without it the panel has no database rows.

## The web pages

**Public:** [kettlelinux.org/games.html](https://kettlelinux.org/games.html) (`site/games.html`,
`site/games.js`, published with the rest of the site by `.github/workflows/pages.yml`). It lists
the games with entries (search, device, verified only), and `games.html?app=<id>` shows a game's
entries: what they change, grouped as in the plugin, the note on verified ones, and the same
settings as launch options to paste into Steam by hand. It reads the server's public API, which
allows any origin; served from `localhost`, it reads a local server on port 8787 instead.
`games.kettlelinux.org/` and `/g/<app id>` (the links the plugin shows) redirect there.

**Admin:** [games.kettlelinux.org/admin](https://games.kettlelinux.org/admin)
(`server/game-db/src/admin/`). Sign in with the admin token; it's kept in that browser tab only.

- stats: entries by status, games, votes, shared in the last week, banned devices
- **Engines**: per engine, its games (32-bit, native Linux, with anti-cheat), their entries and
  votes, and every setting in those entries with how often it's there and how its entries'
  votes went: where FEX defaults per engine are to come from (`GET /v1/admin/engines`)
- Pending (oldest first), Approved, Rejected, All, searchable by game name or app id
- per entry: approve, reject, back to pending, delete, edit its note and rating, its votes
  (which device and build said it works or not)
- select several (or all shown) to approve, reject or delete at once
- every entry names the device that shared it (a hash of its install id) and how many entries it
  shared; select that to see them all. **Ban device** rejects all its entries, removes its votes
  and refuses anything more from it; Banned devices lists them, with Unban

The page only holds markup and script: everything goes through the admin API with the token,
and the page's Content-Security-Policy lets it load nothing from elsewhere but Steam's game
images.

## The server

`server/game-db`: a Cloudflare Worker with a D1 database, next to the crash report server
(CRASH-REPORTS.md).

| Request | |
|---|---|
| `GET /v1/catalog` | the plugin's options (labels, choices, launch option targets) |
| `GET /v1/games` | games with entries: verified / community counts, devices, last update |
| `GET /v1/games/<app id>` | a game's entries, verified first, and its engine (the one most devices reported) |
| `GET /v1/engines/<engine>` | FEX settings in entries for at least 3 of the engine's games, confirmed at least 3 times as often as reported broken (one value per option): Game Settings' "Worked for other games" |
| `POST /v1/profiles` | share (5 a minute per address) |
| `POST /v1/profiles/<id>/votes` | works / doesn't work (30 a minute per address) |
| `GET /`, `GET /g/<app id>` | redirect to the site's Games page |
| `/admin`, `/v1/admin/...` | the admin page and its API (bearer token) |

One-time setup:

1. `cd server/game-db && npm install && npx wrangler login`
2. `npx wrangler d1 create kettle-games`, and put the `database_id` it prints in `wrangler.toml`.
3. `npx wrangler d1 execute kettle-games --remote --file schema.sql`
4. `npx wrangler secret put ADMIN_TOKEN` (a long random string, for reviewing)
5. `npx wrangler deploy` (custom domain `games.kettlelinux.org`).
6. In `local.env`: `KETTLE_GAMES_URL=https://games.kettlelinux.org`, then build images as usual.

After an update that changes `schema.sql` (it only adds tables: `engine_reports` is the latest),
run step 3 again, then deploy.

Locally: `npx wrangler d1 execute kettle-games --local --file schema.sql`, `ADMIN_TOKEN=test` in
`.dev.vars`, then `npx wrangler dev` serves it on `http://127.0.0.1:8787`; point a device at it
with a `games.conf` naming that address.

### Reviewing

In the admin page, or with curl:

```sh
T=<admin token>; U=https://games.kettlelinux.org
curl -s -H "Authorization: Bearer $T" "$U/v1/admin/profiles?status=pending" | jq .
curl -s -H "Authorization: Bearer $T" -X POST "$U/v1/admin/profiles/<id>" -d '{"status":"approved"}'
curl -s -H "Authorization: Bearer $T" -X POST "$U/v1/admin/profiles/<id>" -d '{"status":"rejected"}'
curl -s -H "Authorization: Bearer $T" -X DELETE "$U/v1/admin/profiles/<id>"
```

Approve an entry once its settings check out (ideally confirmed on a device of your own) and its
note is fit to show. Rejected entries stay in the database (so the same settings shared again
don't come back as new) but are never shown.
