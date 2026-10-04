# Running Steam games natively on ARM64

Most Steam games are x86-64 code, run by FEX (Proton's ARM64EC FEX for Windows builds, Valve's
FEX tool for Linux builds). Some engines' game code isn't x86 code at all: FNA, XNA and
MonoGame games are .NET, so only the native libraries around their code are x86-64. For those
Kettle can run the game's own code natively on ARM64, with no emulation.

## In Game Settings

Game Settings shows the game's engine (`shared/gameengine.py`). For an engine Kettle can run
natively (`shared/engines.json` `"native"`), on a Linux build, it offers **Run natively on
ARM64**, which adds `kettle-native` to the game's launch options. Off takes it out again.

| Engine | Runs with | Tested |
|---|---|---|
| FNA (Linux builds) | Mono (SteamOS repos), `sdl3`, `faudio`, `fna3d` (ours, built from source) | Terraria 1.4.5.8 on the Thor |

## kettle-native

`packages/kettle-native`: `kettle-native %command%` finds the game (SteamAppId), checks its
engine, and starts its code with the native runtime in its folder, with the arguments Steam
gives the game. Anything it can't run natively (another engine, a Windows build, a missing
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

No Steamworks SDK files are used. Not covered yet: game servers, the flat helpers that aren't a
plain virtual call (some networking ones, about 25 per library); a game that calls one stops
with `kettle-steam-api: <function>: not passed through`. A flat function newer than
`names.txt` isn't exported at all: add it from the game's map.
