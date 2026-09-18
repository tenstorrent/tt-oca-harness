#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Worst-case stack-depth analyzer for the Key Manager ROM firmware.

Computes a sound upper bound on the *main* (synchronous) call-stack depth of a
linked KM ROM ELF by walking the disassembled call graph from a root symbol
(default ``_start_init``) and summing per-function stack frames along the
deepest path.

Why this exists
---------------
Mutable firmware is loaded into SRAM starting at 0x8000 and grows up, while the
ROM's stack grows *down* from the top of usable SRAM toward 0x8000.  After a
warm reset that follows mutable-firmware execution, the ROM re-runs (e.g. a
``CMD_SRAM_EXEC`` restart) and its stack may descend deeper than it did at the
moment the image was originally loaded.  The maximum mutable-firmware size must
therefore be bounded *statically* by the worst-case ROM stack depth, not by the
live stack pointer at load time.  This tool produces that worst-case number from
the actual production ELF so the linker can derive ``KM_FW_LOAD_LIMIT``.

Soundness model
---------------
* Per function, the static frame is the most-negative cumulative ``sp``
  displacement reached within the function from constant ``addi sp,sp,-N`` /
  ``c.addi16sp`` prologue/scratch adjustments.
* ``jal``/``c.jal`` (link in ra) are additive call edges.  Tail jumps
  (``j``/``jr`` with rd=zero) to a *different* function entry are also treated
  as additive call edges (a conservative over-approximation: a real tail call
  tears down the caller frame first, so additive never under-counts).
* The PicoRV32 IRQ handler switches to a dedicated IRQ stack before calling the
  C ISR (see crt0.s), so interrupts do not deepen the main stack and the ISR is
  not part of the ``_start_init`` tree.
* The ROM is required to have a fully *static* stack: any function containing a
  dynamic ``sp`` adjustment (``sub sp,sp,<reg>`` / ``add sp,sp,<reg>``, i.e. a
  VLA/alloca) is a hard error.  Replace VLAs with fixed-size or file-scope
  ``static`` buffers so the worst case can never depend on runtime values.
* An unresolved indirect *call* (``jalr`` that links ra) is a hard error.  An
  unresolved indirect *tail* (``jr <reg>`` with no resolvable target) is treated
  as an intra-function switch dispatch (no new frame) and reported as a note.

Exit status
-----------
0 on success; 1 if ``--limit`` is given and the worst case exceeds it, or if the
analysis is unsound (a dynamic/VLA frame, an unresolved indirect call, or a
call-graph cycle).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# objdump (with --no-show-raw-insn) emits, e.g.:
#   00000e90 <_start_init>:
#      e90:\tlui\tt0,0x8
#      eaa:\tjal\t196 <rom_kpv_read_slot>
#      f00:\tj\t13c <rom_cmd_validate_payload_length+0xc>
_FUNC_RE = re.compile(r"^([0-9a-fA-F]+)\s+<([^>]+)>:\s*$")
# The address column is left-padded only while addresses are short: a test image
# linked into VROM (0x1000_0000) fills the field, so leading space is optional.
_INSN_RE = re.compile(r"^\s*[0-9a-fA-F]+:\s+(\S+)(?:\s+(.*?))?\s*$")
# A target operand may carry an objdump comment: "196 <sym+0xNN>" or with "# ..".
_TARGET_RE = re.compile(r"<([^>+]+)(?:\+0x[0-9a-fA-F]+)?>")

# GCC clone suffixes to strip when comparing function names.
_CLONE_SUFFIX_RE = re.compile(r"\.(?:constprop|isra|part|lto_priv|cold)\.\d+$")

_REGS = {
    "zero",
    "ra",
    "sp",
    "gp",
    "tp",
    "fp",
    *(f"x{i}" for i in range(32)),
    *(f"t{i}" for i in range(0, 7)),
    *(f"a{i}" for i in range(0, 8)),
    *(f"s{i}" for i in range(0, 12)),
}


def _base_name(sym: str) -> str:
    return _CLONE_SUFFIX_RE.sub("", sym)


class Func:
    __slots__ = ("name", "frame", "dynamic", "calls", "indirect", "notes")

    def __init__(self, name: str):
        self.name = name
        self.frame = 0  # static frame bytes (>= 0)
        self.dynamic = False  # has a runtime-sized sp adjustment
        self.calls: set[str] = set()
        self.indirect: list[str] = []  # unresolved indirect CALLS (jalr ra)
        self.notes: list[str] = []


def disassemble(elf: str, objdump: str) -> str:
    out = subprocess.run(
        [objdump, "-d", "--no-show-raw-insn", elf],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout


def parse(dis: str) -> tuple[dict[str, Func], list[str]]:
    """Parse disassembly into a {name: Func} map plus a list of hard errors."""
    funcs: dict[str, Func] = {}
    errors: list[str] = []
    cur: Func | None = None
    cur_sp = 0  # cumulative sp delta from function entry (<= 0 inside frame)

    for line in dis.splitlines():
        m = _FUNC_RE.match(line)
        if m:
            cur = funcs.setdefault(m.group(2), Func(m.group(2)))
            cur_sp = 0
            continue
        if cur is None:
            continue
        mi = _INSN_RE.match(line)
        if not mi:
            continue
        mnem = mi.group(1)
        ops = (mi.group(2) or "").strip()
        # Strip objdump trailing comments (" # 4000 <sym>") for operand parsing,
        # but keep the symbol that objdump resolves for jump targets.
        sym = None
        tm = _TARGET_RE.search(ops)
        if tm:
            sym = tm.group(1)

        # ---- stack pointer adjustments ----------------------------------
        if mnem in ("addi", "add", "c.addi16sp", "addi16sp") and ops.startswith("sp,sp,"):
            imm = ops.split(",", 2)[2].split()[0].split("#")[0].strip()
            if re.fullmatch(r"-?\d+", imm):
                cur_sp += int(imm)
                cur.frame = max(cur.frame, -cur_sp)
            else:
                cur.dynamic = True  # add sp,sp,<reg>
            continue
        if mnem in ("sub", "c.sub") and ops.startswith("sp,sp,"):
            cur.dynamic = True
            continue

        # ---- control transfer -------------------------------------------
        if mnem in ("jal", "c.jal"):
            # Operands are either "ADDR <sym>" (rd=ra) or "rd,ADDR <sym>".
            first = ops.split(",", 1)[0].strip().split()[0] if ops else ""
            rd = first if first in _REGS else "ra"
            if rd == "zero":
                # jal zero == plain jump; objdump prints this as 'j', so rare.
                if sym and _base_name(sym) != _base_name(cur.name):
                    cur.calls.add(sym)
            else:
                if sym is None:
                    errors.append(f"{cur.name}: unresolved jal target ({ops!r})")
                else:
                    cur.calls.add(sym)
            continue
        if mnem in ("j", "c.j"):
            # Tail jump. Edge only if it targets a *different* function entry
            # (offset 0); "<sym+0xNN>" is an intra-function branch.
            if sym is not None and "+0x" not in ops and _base_name(sym) != _base_name(cur.name):
                cur.calls.add(sym)
            continue
        if mnem in ("jalr",):
            # rd defaults to ra when only a register/target is given -> a real
            # indirect CALL. objdump prints 'ret' for 'jalr zero,0(ra)'.
            first = ops.split(",", 1)[0].strip().split()[0] if ops else ""
            rd = first if first in _REGS else "ra"
            if rd != "zero":
                if sym is not None:
                    cur.calls.add(sym)
                else:
                    # Recorded per-function; only fatal if this function turns
                    # out to be reachable from an analyzed root (see main()).
                    cur.indirect.append(f"jalr {ops}")
            else:
                if sym is not None and _base_name(sym) != _base_name(cur.name):
                    cur.calls.add(sym)
                else:
                    cur.notes.append(f"indirect tail 'jalr {ops}' (treated as switch)")
            continue
        if mnem in ("jr", "c.jr"):
            # jr == jalr zero (no link): tail jump / switch / return.
            if sym is not None and _base_name(sym) != _base_name(cur.name):
                cur.calls.add(sym)  # resolved tail call to another function
            elif sym is None:
                cur.notes.append(f"indirect tail 'jr {ops}' (treated as switch)")
            continue

    return funcs, errors


def longest_path(funcs: dict[str, Func], root: str):
    """Return (depth_bytes, path_list, cycles, reachable) from root."""
    memo: dict[str, tuple[int, list[str]]] = {}
    on_stack: set[str] = set()
    cycles: list[str] = []
    reachable: set[str] = set()

    def visit(name: str) -> tuple[int, list[str]]:
        if name in memo:
            return memo[name]
        f = funcs.get(name) or funcs.get(_base_name(name))
        if f is None:
            # External/leaf symbol (e.g. SRAM 0x8000 handover target): depth 0.
            return (0, [name])
        reachable.add(f.name)
        if name in on_stack:
            cycles.append(name)
            return (0, [f"{name} (CYCLE)"])
        on_stack.add(name)
        best_child: tuple[int, list[str]] = (0, [])
        for callee in f.calls:
            d, p = visit(callee)
            if d > best_child[0]:
                best_child = (d, p)
        on_stack.discard(name)
        res = (f.frame + best_child[0], [f"{name} (+{f.frame})"] + best_child[1])
        memo[name] = res
        return res

    depth, path = visit(root)
    return depth, path, cycles, reachable


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("elf", help="linked ROM ELF to analyze")
    ap.add_argument(
        "--objdump",
        default="riscv64-unknown-elf-objdump",
        help="objdump binary (default: %(default)s)",
    )
    ap.add_argument(
        "--root", action="append", default=None, help="root symbol(s) (default: _start_init)"
    )
    ap.add_argument(
        "--limit",
        type=lambda s: int(s, 0),
        default=None,
        help="fail (exit 1) if worst case exceeds this many bytes",
    )
    ap.add_argument("--verbose", action="store_true", help="print the deepest path")
    args = ap.parse_args()

    roots = args.root or ["_start_init"]

    dis = disassemble(args.elf, args.objdump)
    funcs, errors = parse(dis)

    for r in roots:
        if r not in funcs:
            errors.append(f"root symbol {r!r} not found in {args.elf}")

    dynamic = sorted(f.name for f in funcs.values() if f.dynamic)
    if dynamic:
        errors.append(
            "dynamic (VLA/alloca) stack frame(s) found: "
            + ", ".join(dynamic)
            + ".  ROM must use fixed-size or file-scope 'static' buffers so the "
            "stack stays statically bounded."
        )

    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 1

    worst = 0
    worst_path: list[str] = []
    worst_root = roots[0]
    all_cycles: list[str] = []
    all_reachable: set[str] = set()
    for r in roots:
        d, p, cyc, reach = longest_path(funcs, r)
        all_cycles += cyc
        all_reachable |= reach
        if d > worst:
            worst, worst_path, worst_root = d, p, r

    if all_cycles:
        print(
            f"error: call-graph cycle(s) detected: {', '.join(sorted(set(all_cycles)))}",
            file=sys.stderr,
        )
        return 1

    # Indirect calls only matter if they lie on an analyzed (reachable) path.
    indirect_err = [
        f"{name}: unresolved indirect call '{c}' (cannot bound stack)"
        for name in sorted(all_reachable)
        for c in funcs[name].indirect
    ]
    if indirect_err:
        for e in indirect_err:
            print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"worst-case ROM main stack: {worst} bytes (root {worst_root}, {len(funcs)} functions)")
    if args.verbose:
        print("deepest path:")
        for step in worst_path:
            print(f"  {step}")
    notes = [(f.name, n) for f in funcs.values() for n in f.notes]
    if notes and args.verbose:
        print("notes:")
        for fn, n in notes:
            print(f"  {fn}: {n}")

    if args.limit is not None:
        if worst > args.limit:
            print(
                f"error: worst case {worst} B exceeds budget {args.limit} B "
                f"(0x{args.limit:x}); raise ROM_KM_MAX_STACK_BYTES or reduce stack use",
                file=sys.stderr,
            )
            return 1
        print(
            f"within budget: {worst} B <= {args.limit} B "
            f"(0x{args.limit:x}); headroom {args.limit - worst} B"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
