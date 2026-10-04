#!/usr/bin/python3
"""steamapi-map: what a game's x86-64 libsteam_api.so does, for Kettle's ARM64 one.

A game's .NET or C++ code calls the Steam API through libsteam_api.so, which it ships for x86-64
only. Kettle's ARM64 libsteam_api.so (steam_api.c) passes those calls to Steam's own ARM64
client, and this reads from the game's library what to pass them as:

  forward  SteamAPI_ISteam<I>_<M>: a call of the interface's virtual method at this byte offset
           in its vtable (the x86-64 code is `mov (%rdi),%rax; jmp *off(%rax)`, or call/ret).
           The vtable layout is the same on ARM64 (Itanium C++ ABI on both), so the ARM64
           version is the same jump.
  user/gs  SteamAPI_Steam<I>_v<N> accessors: the interface version string they ask for, for
           the user or the game server.
  client   the SteamClient version the library was built against.

Only the library's own code is read (ELF symbols, relocations, a few x86-64 instruction
patterns); nothing of Valve's is copied. Functions it can't map are listed as `unmapped`.

  steamapi-map.py <x86-64 libsteam_api.so>     prints the map (one entry per line)
"""
import re
import struct
import sys


class Elf:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.b = f.read()
        b = self.b
        if b[:4] != b"\x7fELF" or b[4] != 2 or b[5] != 1 or struct.unpack_from("<H", b, 18)[0] != 0x3E:
            raise ValueError("not an x86-64 ELF")
        phoff, shoff = struct.unpack_from("<QQ", b, 0x20)
        phentsize, phnum, shentsize, shnum, shstrndx = struct.unpack_from("<HHHHH", b, 0x36)
        self.loads = []
        for i in range(phnum):
            p_type, _, p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<IIQQQQ", b, phoff + i * phentsize)
            if p_type == 1:
                self.loads.append((p_vaddr, p_offset, p_filesz))
        self.sections = []
        for i in range(shnum):
            name, typ, _, addr, off, size, link, _, _, entsize = struct.unpack_from("<IIQQQQIIQQ", b, shoff + i * shentsize)
            self.sections.append(dict(name=name, type=typ, addr=addr, off=off, size=size, link=link, entsize=entsize))
        strtab = self.sections[shstrndx]
        for s in self.sections:
            s["name"] = self._cstr(strtab["off"] + s["name"])
        self.syms = {}      # name -> address (defined functions)
        self.symaddr = {}   # address -> name
        dynsym = next(s for s in self.sections if s["name"] == ".dynsym")
        dynstr = self.sections[dynsym["link"]]
        dynsyms = []
        for i in range(dynsym["size"] // 24):
            st_name, st_info, _, st_shndx, st_value, _ = struct.unpack_from("<IBBHQQ", b, dynsym["off"] + i * 24)
            name = self._cstr(dynstr["off"] + st_name)
            dynsyms.append(name)
            if st_shndx and st_info & 0xF == 2 and st_value:
                self.syms[name] = st_value
                self.symaddr[st_value] = name
        self.relative = {}  # address -> addend (R_X86_64_RELATIVE)
        self.plt = {}       # GOT slot -> symbol name (R_X86_64_JUMP_SLOT / GLOB_DAT)
        for s in self.sections:
            if s["type"] == 4:  # SHT_RELA
                for i in range(s["size"] // 24):
                    r_off, r_info, r_add = struct.unpack_from("<QQq", b, s["off"] + i * 24)
                    typ, sym = r_info & 0xFFFFFFFF, r_info >> 32
                    if typ == 8:
                        self.relative[r_off] = r_add
                    elif typ in (6, 7) and sym < len(dynsyms):
                        self.plt[r_off] = dynsyms[sym]

    def _cstr(self, off):
        return self.b[off:self.b.index(b"\0", off)].decode(errors="replace")

    def at(self, addr, n):
        for vaddr, off, size in self.loads:
            if vaddr <= addr < vaddr + size:
                return self.b[off + addr - vaddr: off + min(addr - vaddr + n, size)]
        return b""

    def cstr_at(self, addr):
        data = self.at(addr, 256)
        return data[:data.index(b"\0")].decode(errors="replace") if b"\0" in data else None

    def call_target(self, addr):
        """The symbol a `call rel32` at addr goes to, through the PLT if need be."""
        code = self.at(addr, 5)
        if len(code) < 5 or code[0] != 0xE8:
            return None
        dest = addr + 5 + struct.unpack_from("<i", code, 1)[0]
        if dest in self.symaddr:
            return self.symaddr[dest]
        stub = self.at(dest, 6)  # PLT stub: jmp *slot(%rip)
        if stub[:2] == b"\xff\x25":
            return self.plt.get(dest + 6 + struct.unpack_from("<i", stub, 2)[0])
        return None


# The instructions a flat function may have around its one virtual call and still be only
# that call: stack and callee-saved register bookkeeping, widening an argument (bool, int8,
# int16, int32) in its own register (on ARM64 the callee widens its arguments itself), and
# keeping a struct return pointer to return it (x86-64 returns it in %rax, ARM64 needn't).
_FRAME = re.compile(rb"\x48\x83[\xec\xc4][\x00-\x7f]|\x41[\x54-\x57\x5c-\x5f]|[\x53\x55\x5b\x5d]|"
                    rb"[\x48\x49]\x89[\xfb\xfc\xfd]|[\x48\x4c]\x89[\xd8\xe0\xe8]")


def _widen(code, i):
    """movzbl/movzwl/movsbl/movswl, movslq or a 32-bit mov of a register into itself: its length,
    or 0."""
    j = i
    rex = code[j] if j < len(code) and 0x40 <= code[j] <= 0x4F else None
    if rex is not None:
        j += 1
    if code[j:j + 1] == b"\x0f" and j + 2 < len(code) and code[j + 1] in (0xB6, 0xB7, 0xBE, 0xBF):
        m = code[j + 2]
    elif code[j:j + 1] == b"\x63" and rex is not None and rex & 8 and j + 1 < len(code):
        m = code[j + 1]
        j -= 1
    elif code[j:j + 1] in (b"\x89", b"\x8b") and not (rex or 0) & 8 and j + 1 < len(code):
        m = code[j + 1]  # mov %e?x,%e?x: zero-extends a 32-bit argument
        j -= 1
    else:
        return 0
    r = rex or 0
    if m >> 6 == 3 and ((m >> 3) & 7) | ((r & 4) << 1) == (m & 7) | ((r & 1) << 3):
        return j + 3 - i
    return 0


# Copying a stack-passed argument from the caller's frame to the outgoing area, through %r8 or
# %r10: x86-64 passes arguments after the sixth (and structs over 16 bytes) on the stack; ARM64
# passes eight in registers and big structs by pointer, so there the plain jump is the same call.
_STACK_COPY = re.compile(rb"[\x44\x4c][\x8b\x89](?:[\x04\x14]\x24|[\x44\x54]\x24[\x00-\x7f])")

# Functions whose x86-64 code only re-packs the (packed, at most 16-byte) struct the virtual method
# returns: on ARM64 it comes back in registers the same way from both, so the jump is the same.
PACKED_RETURNS = {"SteamAPI_ISteamInput_GetAnalogActionData", "SteamAPI_ISteamController_GetAnalogActionData"}


def _disp(code, i, base):
    """The displacement of a ModRM byte at code[i] addressing %rax: (disp, length) or None."""
    if i >= len(code):
        return None
    m = code[i]
    if m & 7 != 0 or m >> 6 == 3:
        return None
    if m >> 6 == 0:
        return 0, 1
    if m >> 6 == 1 and i + 1 < len(code):
        return code[i + 1], 2
    if m >> 6 == 2 and i + 4 < len(code):
        return struct.unpack_from("<I", code, i + 1)[0], 5
    return None


def forward_offset(code):
    """The vtable offset if the function does nothing but pass its call on to its object's
    virtual method (or None): `mov (%rdi|%rsi),%rax`, then `jmp/call *off(%rax)` or
    `mov off(%rax),%rax; jmp/call *%rax`, with only _FRAME and _widen instructions besides and,
    after a call, a `ret`. %rsi is the object when %rdi is a struct return pointer, which ARM64
    passes in x8: the object is in x0 there either way."""
    i, off, vtable, called = 0, None, False, False
    while i < len(code):
        if code[i] == 0xC3:
            return off if called else None
        m = _FRAME.match(code, i)
        if m:
            i = m.end()
            continue
        n = _widen(code, i)
        if n:
            i += n
            continue
        m = _STACK_COPY.match(code, i)
        if m:
            i = m.end()
            continue
        if not vtable and code[i:i + 3] in (b"\x48\x8b\x07", b"\x48\x8b\x06"):
            vtable, i = True, i + 3
            continue
        if vtable and off is None and code[i:i + 2] == b"\x48\x8b" and code[i + 2:i + 3] and (code[i + 2] >> 3) & 7 == 0:
            d = _disp(code, i + 2, 0)
            if d:
                off, i = d[0], i + 2 + d[1]
                continue
        if vtable and code[i:i + 1] == b"\xff" and i + 1 < len(code):
            op = (code[i + 1] >> 3) & 7
            if code[i + 1] in (0xE0, 0xD0) and off is not None:  # jmp/call *%rax
                n = 2
            elif op in (2, 4) and off is None:
                d = _disp(code, i + 1, 0)
                if not d:
                    return None
                off, n = d[0], 1 + d[1]
            else:
                return None
            if op == 4 or code[i + 1] == 0xE0:
                return off if not called else None
            called, i = True, i + n
            continue
        return None
    return None


def rip_leas(code, base):
    """Addresses `lea disp(%rip),%reg` instructions in code load: [(reg, address)]."""
    out = []
    for m in re.finditer(rb"[\x48\x4c]\x8d([\x05\x0d\x15\x1d\x25\x2d\x35\x3d])", code):
        i = m.start()
        if i + 7 <= len(code):
            reg = (m.group(1)[0] >> 3) & 7
            out.append((reg, base + i + 7 + struct.unpack_from("<i", code, i + 3)[0]))
    return out


def accessor_version(elf, addr):
    """The interface version an accessor asks for: directly (`lea str(%rip),%rsi`), or in the
    init function of the SteamInternal_ContextInit data it passes (`lea data(%rip),%rdi`)."""
    code = elf.at(addr, 64)
    for reg, a in rip_leas(code, addr):
        if reg == 6:  # %rsi
            s = elf.cstr_at(a)
            if s and re.fullmatch(r"[A-Za-z_]+\d{3}", s):
                return s
    for reg, a in rip_leas(code, addr):
        if reg == 7 and a in elf.relative:  # %rdi: ContextInitData, its first word the init function
            fn = elf.relative[a]
            for r2, a2 in rip_leas(elf.at(fn, 96), fn):
                s = elf.cstr_at(a2)
                if s and re.fullmatch(r"[A-Za-z_]+\d{3}", s):
                    return s
    return None


ACCESSOR = re.compile(r"SteamAPI_Steam(\w+?)(_SteamAPI)?_v\d{3}")


def packed_return_offset(code):
    """The vtable offset a PACKED_RETURNS function calls: `mov (%rdi),%rax` then `call *off(%rax)`."""
    m = re.match(rb"\x48\x83\xec[\x00-\x7f]\x48\x8b\x07\xff(\x50.|\x90....)", code, re.S)
    if not m:
        return None
    g = m.group(1)
    return g[1] if g[0] == 0x50 else struct.unpack_from("<I", g, 1)[0]


def build(path):
    elf = Elf(path)
    out = {"forward": {}, "user": {}, "gs": {}, "unmapped": []}
    clients = sorted({m for m in re.findall(rb"SteamClient0\d\d\0", elf.b)})
    out["client"] = clients[-1][:-1].decode() if clients else None
    for name, addr in sorted(elf.syms.items()):
        if name.startswith("SteamAPI_ISteam"):
            code = elf.at(addr, 64)
            off = forward_offset(code)
            if off is None and name in PACKED_RETURNS:
                off = packed_return_offset(code)
            if off is None:
                out["unmapped"].append(name)
            else:
                out["forward"][name] = off
        elif ACCESSOR.fullmatch(name):
            ver = accessor_version(elf, addr)
            if ver is None:
                out["unmapped"].append(name)
            else:
                out["gs" if name.startswith("SteamAPI_SteamGameServer") else "user"][name] = ver
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: steamapi-map.py <x86-64 libsteam_api.so>")
    m = build(sys.argv[1])
    print(f"client {m['client']}")
    for name, off in m["forward"].items():
        print(f"forward {name} {off}")
    for kind in ("user", "gs"):
        for name, ver in m[kind].items():
            print(f"{kind} {name} {ver}")
    for name in m["unmapped"]:
        print(f"unmapped {name}")


if __name__ == "__main__":
    main()
