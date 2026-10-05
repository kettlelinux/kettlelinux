# Game Stores

The Game Stores plugin puts Epic Games, GOG and Amazon Games into Game Mode. A player signs in to
a store, browses their games, installs one, and plays it from the Steam library like any other
game, without going to the desktop. It's in Quick Access > Game Stores.

It uses the store tools Heroic uses, built for ARM64 in `packages/heroic-games-launcher`:
[legendary](https://github.com/legendary-gl/legendary) (Epic),
[gogdl](https://github.com/Heroic-Games-Launcher/heroic-gogdl) (GOG) and
[nile](https://github.com/imLinguin/nile) (Amazon). It also uses Heroic's config, so desktop Heroic
sees the same sign-ins and installed games, and the other way round.

## Signing in

The store's login page opens in Steam's own browser, with the on-screen keyboard and any captcha
the store asks for. The plugin's backend (`main.py`) watches the page through Steam's browser
DevTools port, 127.0.0.1:8080, which Decky Loader turns on (`py_modules/cdp.py`). It waits until
the store sends the browser to its "signed in" address, then:

| Store | Login page | The code comes from | Handed to |
|---|---|---|---|
| Epic | `epicgames.com/id/login`, redirecting to `/id/api/redirect` (legendary's client) | the `authorizationCode` in the redirect page's JSON | `legendary auth --code` |
| GOG | `auth.gog.com/auth` (Galaxy's client) | `code=` in `embed.gog.com/on_login_success` | `gogdl auth --code` |
| Amazon | the URL from `nile auth --login --non-interactive` | `openid.oa2.authorization_code=` in the redirect | `nile register` |

The page is then blanked (Epic's shows the code), and the frontend leaves the browser.
Nothing logs what the tools print while signing in, because gogdl prints its tokens. For GOG, the
plugin also sets `isLoggedIn` and `userData` in Heroic's `gog_store/config.json`, because Heroic
doesn't treat GOG as signed in from `auth.json` alone.

## Files

All of them are Heroic's, under `~/.config/heroic`:

| | Sign-in | Installed games |
|---|---|---|
| Epic | `legendaryConfig/legendary/user.json` | `legendaryConfig/legendary/installed.json` |
| GOG | `gog_store/auth.json`, `gog_store/config.json` | `gog_store/installed.json` (written by the plugin: gogdl keeps none), `gogdlConfig/heroic_gogdl/manifests/` |
| Amazon | `nile_config/nile/*.enc`, `current_user.json` | `nile_config/nile/installed.json` |

New games go to `~/Games/Heroic` (Heroic's default), or to an SD card or USB drive chosen under
Downloads. The plugin's own state is in `~/homebrew/settings/kettle-stores/`:
- `stores.json`: the Steam shortcut of each game, the queue and the running job
- `library-<store>.json`: each store's game list, refreshed daily or with Refresh
- `job.log`: the running job's output

## A game's page

Each game's page shows its size and its buttons (Install, Play, Update, Uninstall). Under them, in
About, are the game's summary, developer, publisher, release date, genres, play modes and the DLC
the player owns. For Epic
and GOG games these come from GOG's game database (`gamesdb.gog.com`, which knows Epic games by
their app name), and for Amazon games from Amazon's library (`nile_config/nile/library.json`).

## Installing

The DLC the player owns comes with the game and its updates (`--with-dlcs` for legendary and
gogdl), and is listed in the game's About. Amazon has no separate DLC in nile.

Installs and updates run one at a time as a user systemd unit, `kettle-stores-job`, at a lower
priority, so they keep going if Decky restarts. The plugin reads the tool's progress lines from
`job.log`. When an install finishes, the frontend adds the game to Steam (`src/shortcuts.ts`):
- the shortcut points at the game's .exe:
  - Epic: legendary's `executable`
  - GOG: the primary play task in `goggame-<id>.info`
  - Amazon: `fuel.json`'s `Command`
- its compatibility tool is the newest Proton-CachyOS, then GE-Proton, then Valve's ARM64 Proton
- artwork comes from the store: Epic's key images, GOG's game database, Amazon's product images
- launch options are `kettle-store-run <store> <id> %command%`

Updates:
- **Epic:** compares the installed version with the library's build.
- **Amazon:** `nile list-updates`.
- **GOG:** compares the installed build ID with the newest one, when the game's page opens.

## Starting a game

`kettle-store-run` (installed to `/usr/bin`) runs with Steam's whole command and adds what the
store needs to it:

- **Epic:** the login arguments from `legendary launch --json`, including a new one-time code at
  each start, plus the game's own arguments. Offline, it falls back to `--offline`, or starts the
  game without them.
- **GOG:** the primary play task's arguments.
- **Amazon:** `nile launch --json`'s arguments and the Amazon Games SDK variables (`FUEL_DIR` …).

It logs each start, with Epic's code left out, to `~/.local/state/kettle-stores/run.log`.

## GOG setup

Many GOG games come with an install script and a list of redistributables, which GOG Galaxy (and
Heroic) runs in the game's Windows prefix: registry entries the game looks for, DirectX, Visual
C++ runtimes, PhysX. The install job downloads what the game's manifest
(`gogdlConfig/heroic_gogdl/manifests/<id>`) lists after the game itself
(`kettle-store-run gog-redist <id>`, which runs `gogdl redist`), into Heroic's
`tools/redist/gog`. On the game's first start in a prefix, and again after it updates,
`kettle-store-run` runs them before the game:
- **How:** it uses the same Steam command (the runtime, Proton, the prefix), with `cmd.exe` and a
  batch file (`compatdata/<appid>/kettle-gog-setup.bat`) in place of the game.
- **What runs:** GOG's script interpreter (ISI) for the game and its installed DLC, with the
  arguments Heroic gives it, then each redistributable's silent installer from GOG's redist
  manifest.
- **Left out:** .NET's installers. Proton has wine-mono in .NET's place, and Microsoft's .NET
  installers don't install under Wine.
- **Recorded:** `compatdata/<appid>/kettle-gog-setup.json` holds the build each game was set up
  for. A redistributable that fails doesn't hold up later starts.

## Cloud saves

Epic and GOG games sync their saves with the store, unless **Cloud saves** under Downloads is
off (`cloud_saves` in `stores.json`, which `kettle-store-run` reads). Before the game starts,
newer saves are downloaded. The wrapper then runs the game and waits for it, rather than handing
over to it, so that after the game exits it can upload the new saves. That includes a game closed
with Steam's Exit game: the wrapper passes Steam's signal on to the game and uploads after it.

The save folders are the store's, resolved in the shortcut's Proton prefix
(`compatdata/<appid>/pfx/drive_c/users/steamuser`):

| Store | Where the folder comes from | Synced with |
|---|---|---|
| Epic | the game's `CloudSaveFolder` (`{AppData}`, `{UserDir}`, `{InstallDir}`, `{EpicID}` …, as legendary resolves them on Windows) | `legendary sync-saves --save-path` |
| GOG | the locations in the game's cloud storage config (`remote-config.gog.com`, by the game's client id), as Heroic resolves them | `gogdl save-sync`, with the last sync time per location in Heroic's `gog_store/saveTimestamps.json` |

A game's first start downloads its saves into a prefix that doesn't exist yet. That's safe:
Proton keeps any file already there when it creates the prefix. Amazon games keep their saves
themselves.

Game Settings, Frame Generation, Upscaling and Power list these games, and every other non-Steam
shortcut, next to Steam's: `shared/steamlib.py` reads the shortcuts from Steam's
`userdata/*/config/shortcuts.vdf`, and uses the .exe's folder as the game's install folder (for
engine detection and OptiScaler). They add their options around the wrapper in the launch
options. The game database is left out for shortcuts: it knows games by Steam appid, and a
shortcut's appid is only this device's.

## Not done yet

- **GOG Galaxy features:** achievements and other Galaxy online features (comet) aren't
  available.
- **Anti-cheat:** games with anti-cheat (EAC, BattlEye) mostly won't run under FEX.
- **Third-party launchers:** games that need another launcher (the EA app, Ubisoft Connect) are
  listed but can't be installed.
