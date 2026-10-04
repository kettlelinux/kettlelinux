# Running Steam games natively on ARM64

Most Steam games are x86-64 code, run by FEX (Proton's ARM64EC FEX for Windows builds, Valve's
FEX tool for Linux builds). Some engines' game code isn't x86 code at all: FNA, XNA and
MonoGame games are .NET, so only the native libraries around their code are x86-64. For those
Kettle can run the game's own code natively on ARM64, with no emulation.

## In Game Settings

Game Settings shows the game's engine (`shared/gameengine.py`). For an engine Kettle can run
natively (`shared/engines.json` `"native"`), on a Linux build, it offers **Run natively on
ARM64**, which adds `kettle-native` to the game's launch options. Off takes it out again.

| Game built as | Runs with | Tested |
|---|---|---|
| .NET Framework (FNA, XNA, MonoGame on Mono: Linux builds with an `.exe`) | Mono (SteamOS repos), `sdl3`, `faudio`, `fna3d` (ours, built from source) | Terraria 1.4.5.8 on the Thor |
| .NET Core / 5+ (MonoGame and other .NET games: a `<name>.runtimeconfig.json`) | .NET 10 (`dotnet-runtime-bin`), the system's SDL2, OpenAL and FAudio | Stardew Valley 1.6 (.NET 6) on the Thor |

Engines offered: FNA, XNA, MonoGame and plain .NET (`"native"`); which runtime runs a game
depends on how it was built, not on the engine.

## .NET Core / 5+ games

These games usually ship self-contained: their own x86-64 .NET runtime beside their code.
kettle-native runs their code on the system's ARM64 .NET instead, which games roll forward to
(one LTS runtime serves .NET 6, 7, 8 and 10 games). The game's folder stays as Steam installed
it; kettle-native runs a shadow of it (`~/.cache/kettle-native/dotnet/<appid>`, rebuilt after
an update) of symlinks to the game's files, except:

- `<name>.runtimeconfig.json` and `<name>.deps.json` say framework-dependent: the bundled
  runtime's files are left out of what the host loads.
- IL-only assemblies marked x86-64 (the compiler's `x64` platform target; their code is still IL)
  are copies with an ARM64 mark, which ARM64 .NET otherwise refuses.
- x86-64 native libraries are left out, so the system's ARM64 ones load by name (SDL2, OpenAL,
  FAudio, `libsteam_api.so` from kettle-steam-api), or replaced by kettle-native's
  (`/usr/lib/kettle-native`): `liblwjgl_lz4.so` (a shim over the system liblz4 for the LWJGL
  functions games call: Stardew's co-op compression) and `libSkiaSharp.so` (SkiaSharp's ARM64
  release for the game's milestone, 2.80 or 2.88: Stardew's map screenshots).

The .NET runtime and SkiaSharp are upstream's ARM64 releases (MIT): .NET's source build needs
a .NET SDK to bootstrap and hours per build, and Skia's is similar. Not available: GOG Galaxy
(`libGalaxy64.so`, proprietary and x86-64 only; Stardew uses it for invite-code co-op, Steam
co-op doesn't need it), and games needing ASP.NET Core or Windows Desktop frameworks.

## kettle-native

`packages/kettle-native`: `kettle-native %command%` finds the game (SteamAppId), checks its
engine, and starts its code with a native runtime (.NET for a `runtimeconfig.json`, else Mono),
with the arguments Steam gives the game. Anything it can't run natively (another engine, a Windows build, a missing
runtime) runs Steam's command unchanged, so the switch can't keep a game from starting. Its
messages start with `kettle-native:` in the game's output.

Two more things make a native game a proper Steam game:

- **Steam's overlay** (and Steam Input with it: without it the controller drives Steam's UI
  through the game): Steam preloads its x86-64 `gameoverlayrenderer.so` for the x86-64 build it
  thinks it starts; kettle-native preloads Steam's ARM64 one (`steamrtarm64/`) instead.
- **The Steam API**, below.

## kettle-steam-api

Games ship `libsteam_api.so` for x86-64 only, and Steam has none for ARM64, only its ARM64
client (`linuxarm64/steamclient.so`). `packages/kettle-steam-api` is our own ARM64
`libsteam_api.so` that passes the game's calls to that client, so ownership, achievements and
Steam Cloud are Steam's own:

- Most of the API is flat functions that call one virtual method of a Steam interface.
  `steamapi-map` reads from the game's own x86-64 library which vtable offset each calls (its
  code is `mov (%rdi),%rax; jmp *off(%rax)` and a few variants) and which interface version each
  accessor asks for. The vtable layout is the same on ARM64, so each becomes a three-instruction
  jump (`gen-flat.py`, from `names.txt`). kettle-native builds the map once per library
  (`~/.cache/kettle-native/steamapi/`) and passes it in `KETTLE_STEAM_API_MAP`.
- `steam_api.c` does the rest: connecting to Steam, interfaces, the context cache C++ games use,
  callbacks and call results (both `SteamAPI_RunCallbacks` and manual dispatch).

A few flat helpers aren't one virtual call: the networking ones games use (config values,
`InitRelayNetworkAccess`, `IsFakeIPv4`) are written out in `steam_api.c` on the methods they
wrap, and `steamapi-map` also follows functions that widen 32-bit arguments, copy stack
arguments or return a packed struct. No Steamworks SDK files are used. Not covered yet: game
servers, and the remaining helpers that aren't a plain virtual call; a game that calls one stops
with `kettle-steam-api: <function>: not passed through`. A flat function newer than
`names.txt` isn't exported at all: add it from the game's map.
