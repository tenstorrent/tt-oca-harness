# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Op encoding, result layout and decode of the POKE Key Manager image.

The KM image ``cocotb/tests/km_fw/km_rom_poke.S`` (committed as
``cocotb/tests/km_rom_poke.parhex``) executes a list of KM bus operations as a
legal master of the KM bus and writes what the DUT returned to KM SRAM words 0
to 97, which ``km_sram_probe_o`` shows. The image grades nothing; every golden
lives in the test. ``seq_lib/sep_km_poke_seq.py`` posts a list and reads the
results back; this module holds the parts that need no simulator.

Op word 0 of each operation: ``[7:0]`` opcode, ``[8]`` RAW, ``[9]`` F (an
op-specific option), ``[31:16]`` imm16. The arguments follow.

==========  ===================  =====  ==========================================
op          arguments            slots  result
==========  ===================  =====  ==========================================
``nop``     -                    0      a re-arm point only
``rd``      addr                 1      data = load of addr
``wr``      addr, data           1      store; data slot 0
``wr2``     a1, d1, a2, d2       1      two stores back to back; ``readback``:
                                        data = load of a2 right after, else 0
``poll``    addr, mask, val, n   2      loads until ``(rd & mask) == val``
                                        (``ne``: ``!=``) or n loads; slot 0 the
                                        last load, slot 1 the loads made
``rdloop``  addr, count, stride  2      slot 0 the loads that were not 0 (an
                                        unknown word counts as not 0), slot 1
                                        the OR of every load
``rdblk``   addr, stride         n      n loads, one slot each, each with its
                                        own clear and report
``fill``    addr, value          1      n stores of value at addr, addr + 4, ...
``wrblk``   addr, words          1      the listed words stored from addr up
``copy``    src, dst             1      n words loaded at src, stored at dst
``jump``    addr, a0, a1         1      x10 = a0, x11 = a1, x1 = ENTRY_RESUME,
                                        armed lines unmasked; data = x12 when
                                        the target returns to ENTRY_RESUME
``exec_``   a0, a1               1      exec-table entry with every CPU IRQ
                                        masked, x10 = a0, x11 = a1; data = x12
``arm``     lines, action        0      CPU IRQ lines of {3, 4, 5}; ACT_*
``cnt``     -                    1      handler entries of one CPU IRQ line
``mark``    value                1      data = value (a list marker, no DUT data)
``delay``   n                    0      n re-arm points
``sync``    -                    1      waits for one host word; data = the word
``reseth``  value                0      counts = 0, HWORD = SPIN = value
==========  ===================  =====  ==========================================

Clear and report. A reporting op writes AXI_SLVERR | AXI_DECERR to
IRQ_STATUS (write one to clear) before its access and reads IRQ_STATUS back
once (``pre_slv``, ``pre_dec``). After the access it reads IRQ_STATUS
``SETTLE_READS`` times and ORs bits 4 and 5 of every read (``slv``, ``dec``).
``rd``, ``wr``, ``wr2``, ``poll``, ``rdloop``, ``rdblk``, ``fill``, ``wrblk``,
``copy``, ``jump`` and ``exec_`` report unless ``raw=True``; ``cnt``, ``mark``
and ``sync`` never report. A multi-slot op carries its flags on its first slot,
except ``rdblk``, which reports every slot.

CPU interrupts. Every CPU IRQ line is masked except at a re-arm point, where
the lines of the last ``arm`` are unmasked for one instruction: before every op,
in every ``delay`` iteration, in every mailbox poll while the image waits for a
list or a ``sync`` word, and for the whole time a ``jump`` target runs. The
handler (at the IRQ_ENTRY_ADDR reset value 0x10) counts one entry for each
served line, then masks every line until the next re-arm point. On a line 3
entry it also runs the action: ``ACT_COUNT`` nothing, ``ACT_CLEAR`` writes
IRQ_STATUS & IRQ_ENABLE to IRQ_STATUS, ``ACT_SPIN`` stores IRQ_STATUS to HWORD
and jumps to ENTRY_SPIN, ``ACT_EXEC`` runs an exec-table entry inside the
handler.

No cocotb import, so unit tests load this module without a simulator.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

WORD_MASK = 0xFFFF_FFFF

IMAGE_NAME = "km_rom_poke"
IMAGE_PATH = Path(__file__).resolve().parents[1] / "tests" / f"{IMAGE_NAME}.parhex"

# --- layout (km_rom_poke.S; checked against the image signature) -------------
LAYOUT_VERSION = 1
SIG_ADDR = 0x80
SIG_MAGIC = 0x504F_4B45  # "POKE"
ENTRY_SPIN = 0x20  # ROM spin loop: IRQ_STATUS -> SPIN on every pass
ENTRY_RESUME = 0x40  # continue the list after a jump target returns
EXEC_BASE = 0x100
EXEC_ENTRY_BYTES = 8
EXEC_COUNT = 22
W_STATE = 0
W_PROG = 1
W_CNT3 = 2
W_CNT4 = 3
W_CNT5 = 4
W_HWORD = 5
W_SPIN = 6
W_ERR = 7
W_FLAGS = 8
W_DATA = 18
N_SLOTS = 80
RESULT_WORDS = W_DATA + N_SLOTS  # 98: km_sram_probe_o
W_BUF = 128
BUF_WORDS = 128
SETTLE_READS = 32
SLOTS_PER_FLAG_WORD = 8

# KM SRAM byte address of a result word (region 0; never locked by a test),
# from the generated KM memory map header.
_KM_ADDR_H = (
    Path(__file__).resolve().parents[5]
    / "ip"
    / "key_manager"
    / "regs"
    / "gen"
    / "c"
    / "key_manager_addr.h"
)


def _km_addr_define(name: str) -> int:
    for line in _KM_ADDR_H.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "#define" and parts[1] == name:
            return int(parts[2], 0)
    raise KeyError(f"{name} not found in {_KM_ADDR_H}")


KM_SRAM_BASE = _km_addr_define("KEY_MANAGER_SRAM_BASE_ADDR")


def sram_addr(word: int) -> int:
    """KM bus byte address of KM SRAM word ``word``."""
    return KM_SRAM_BASE + 4 * word


ADDR_HWORD = sram_addr(W_HWORD)
ADDR_SPIN = sram_addr(W_SPIN)

STATE_MAGIC = 0x504B_0000
ST_BOOT = 0x1
ST_RUN = 0x2
ST_DONE = 0x3
ST_SYNC = 0x4
ST_JUMP = 0x5
ST_ERROR = 0xE
STATE_NAMES = {
    ST_BOOT: "BOOT",
    ST_RUN: "RUN",
    ST_DONE: "DONE",
    ST_SYNC: "SYNC",
    ST_JUMP: "JUMP",
    ST_ERROR: "ERROR",
}

LIST_MAGIC = 0x50
F_RAW = 1 << 8
F_OPT = 1 << 9

ERR_NAMES = {
    1: "list header [31:24] is not 0x50",
    2: "list longer than BUF_WORDS",
    3: "unknown opcode",
    4: "more than N_SLOTS result slots",
    5: "exec-table index out of range",
    6: "cnt line not 3, 4 or 5",
    7: "op arguments run past the list end",
}

OP_NOP = 0x00
OP_RD = 0x01
OP_WR = 0x02
OP_WR2 = 0x03
OP_POLL = 0x04
OP_RDLOOP = 0x05
OP_RDBLK = 0x06
OP_FILL = 0x07
OP_WRBLK = 0x08
OP_COPY = 0x09
OP_JUMP = 0x0A
OP_EXEC = 0x0B
OP_ARM = 0x0C
OP_CNT = 0x0D
OP_MARK = 0x0E
OP_DELAY = 0x0F
OP_SYNC = 0x10
OP_RESETH = 0x11

ACT_COUNT = 0
ACT_CLEAR = 1
ACT_SPIN = 2
ACT_EXEC = 3

# CPU IRQ lines (architecture.adoc, "Key Manager CPU Interrupt Processing").
IRQ_LINE_KMCSR = 3
IRQ_LINE_MBOX = 4
IRQ_LINE_ABR_SK = 5
IRQ_LINES = (IRQ_LINE_KMCSR, IRQ_LINE_MBOX, IRQ_LINE_ABR_SK)

# Exec-table entries. Each is one instruction followed by a return through x1.
# Register use: x10 = a0, x11 = a1, the result in x12.
EX_EBREAK = 0
EX_ZERO_WORD = 1
EX_LW_PLUS1 = 2  # lw x12, 1(x10)
EX_LW_PLUS2 = 3  # lw x12, 2(x10)
EX_SW_PLUS1 = 4  # sw x11, 1(x10)
EX_SW_PLUS2 = 5  # sw x11, 2(x10)
EX_CRC_FUNCT3 = {f3: 6 + f3 - 3 for f3 in range(3, 8)}  # custom0 funct7 0101100
EX_CRC32C_WORD = 11  # custom0 funct7 0101100 funct3 0
EX_CRC32C_BYTE = 12  # funct3 1
EX_CRC8_ROHC = 13  # funct3 2
# Words of major opcodes outside RV32IMC: rd x12, rs1 x10, rs2 x11, funct3 2.
EX_MAJOR_OPCODE = {
    "custom-1": 14,
    "custom-2": 15,
    "custom-3": 16,
    "OP-FP": 17,
    "OP-V": 18,
    "LOAD-FP": 19,
    "STORE-FP": 20,
    "AMO": 21,
}


def exec_entry_addr(entry: int) -> int:
    """ROM byte address of exec-table entry ``entry``."""
    if not 0 <= entry < EXEC_COUNT:
        raise ValueError(f"exec entry {entry} not in [0, {EXEC_COUNT})")
    return EXEC_BASE + EXEC_ENTRY_BYTES * entry


# --- ops ----------------------------------------------------------------------


@dataclass(frozen=True)
class PokeOp:
    """One encoded operation: its words, its result slots and whether it reports."""

    name: str
    words: tuple[int, ...]
    slots: int
    reports: bool

    @property
    def code(self) -> int:
        return self.words[0] & 0xFF

    @property
    def raw(self) -> bool:
        return bool(self.words[0] & F_RAW)


def _w(value: int, what: str) -> int:
    if not 0 <= value <= WORD_MASK:
        raise ValueError(f"{what}=0x{value:x} is not a 32-bit word")
    return value


def _imm16(value: int, what: str) -> int:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"{what}={value} not in [0, 0xFFFF]")
    return value


def _op(
    code: int,
    name: str,
    args: Iterable[int],
    slots: int,
    *,
    reports: bool,
    raw: bool = False,
    opt: bool = False,
    imm: int = 0,
) -> PokeOp:
    if raw and not reports:
        raise ValueError(f"{name}: raw applies only to an op that reports")
    head = code | (F_RAW if raw else 0) | (F_OPT if opt else 0) | (_imm16(imm, "imm16") << 16)
    words = (head, *(_w(a, f"{name} arg") for a in args))
    return PokeOp(name, words, slots, reports and not raw)


def nop() -> PokeOp:
    return _op(OP_NOP, "nop", (), 0, reports=False)


def rd(addr: int, *, raw: bool = False) -> PokeOp:
    return _op(OP_RD, "rd", (addr,), 1, reports=True, raw=raw)


def wr(addr: int, data: int, *, raw: bool = False) -> PokeOp:
    return _op(OP_WR, "wr", (addr, data), 1, reports=True, raw=raw)


def wr2(a1: int, d1: int, a2: int, d2: int, *, readback: bool = False, raw: bool = False) -> PokeOp:
    return _op(OP_WR2, "wr2", (a1, d1, a2, d2), 1, reports=True, raw=raw, opt=readback)


def poll(
    addr: int, mask: int, value: int, bound: int, *, ne: bool = False, raw: bool = False
) -> PokeOp:
    if bound < 1:
        raise ValueError("poll bound must be at least one load")
    return _op(OP_POLL, "poll", (addr, mask, value, bound), 2, reports=True, raw=raw, opt=ne)


def rdloop(addr: int, count: int, stride: int = 4, *, raw: bool = False) -> PokeOp:
    return _op(OP_RDLOOP, "rdloop", (addr, count, stride & WORD_MASK), 2, reports=True, raw=raw)


def rdblk(addr: int, n: int, stride: int = 4, *, raw: bool = False) -> PokeOp:
    return _op(OP_RDBLK, "rdblk", (addr, stride & WORD_MASK), n, reports=True, raw=raw, imm=n)


def fill(addr: int, value: int, n: int, *, raw: bool = False) -> PokeOp:
    return _op(OP_FILL, "fill", (addr, value), 1, reports=True, raw=raw, imm=n)


def wrblk(addr: int, words: Sequence[int], *, raw: bool = False) -> PokeOp:
    return _op(OP_WRBLK, "wrblk", (addr, *words), 1, reports=True, raw=raw, imm=len(words))


def copy(src: int, dst: int, n: int, *, raw: bool = False) -> PokeOp:
    return _op(OP_COPY, "copy", (src, dst), 1, reports=True, raw=raw, imm=n)


def jump(addr: int, a0: int = 0, a1: int = 0, *, raw: bool = False) -> PokeOp:
    return _op(OP_JUMP, "jump", (addr, a0, a1), 1, reports=True, raw=raw)


def exec_(entry: int, a0: int = 0, a1: int = 0, *, raw: bool = False) -> PokeOp:
    exec_entry_addr(entry)
    return _op(OP_EXEC, "exec", (a0, a1), 1, reports=True, raw=raw, imm=entry)


def arm(lines: Iterable[int], action: int = ACT_COUNT, entry: int = 0) -> PokeOp:
    """Arm the counting handler on CPU IRQ ``lines``; ``arm(())`` disarms."""
    mask = 0
    for line in lines:
        if line not in IRQ_LINES:
            raise ValueError(f"CPU IRQ line {line} not in {IRQ_LINES}")
        mask |= 1 << line
    if action not in (ACT_COUNT, ACT_CLEAR, ACT_SPIN, ACT_EXEC):
        raise ValueError(f"unknown handler action {action}")
    if action == ACT_EXEC:
        exec_entry_addr(entry)
    return _op(OP_ARM, "arm", (mask, action | (entry << 8)), 0, reports=False)


def disarm() -> PokeOp:
    return arm(())


def cnt(line: int) -> PokeOp:
    if line not in IRQ_LINES:
        raise ValueError(f"CPU IRQ line {line} not in {IRQ_LINES}")
    return _op(OP_CNT, "cnt", (), 1, reports=False, imm=line)


def mark(value: int) -> PokeOp:
    return _op(OP_MARK, "mark", (value,), 1, reports=False)


def delay(n: int) -> PokeOp:
    return _op(OP_DELAY, "delay", (n,), 0, reports=False)


def sync() -> PokeOp:
    return _op(OP_SYNC, "sync", (), 1, reports=False)


def reseth(value: int = 0) -> PokeOp:
    return _op(OP_RESETH, "reseth", (value,), 0, reports=False)


def list_words(ops: Sequence[PokeOp]) -> int:
    return sum(len(op.words) for op in ops)


def list_slots(ops: Sequence[PokeOp]) -> int:
    return sum(op.slots for op in ops)


def encode_list(ops: Sequence[PokeOp], tag: int) -> list[int]:
    """The words the host posts: the list header, then every op word."""
    if not 1 <= tag <= 0xFF:
        raise ValueError(f"tag {tag} not in [1, 255]")
    n = list_words(ops)
    if n > BUF_WORDS:
        raise ValueError(f"list of {n} words exceeds the {BUF_WORDS}-word buffer")
    slots = list_slots(ops)
    if slots > N_SLOTS:
        raise ValueError(f"list needs {slots} result slots, the image has {N_SLOTS}")
    header = (LIST_MAGIC << 24) | (tag << 16) | n
    return [header] + [w for op in ops for w in op.words]


def list_header(ops: Sequence[PokeOp], tag: int) -> int:
    """The header word of the list ``ops`` with ``tag`` (word 0 of ``encode_list``).

    A host may post this word ahead of the rest of the list, for example while
    the image runs a ``delay`` op of the previous list. The image takes the
    header as the start of its next list and then waits for the remaining
    ``encode_list(ops, tag)[1:]`` words.
    """
    return encode_list(ops, tag)[0]


# --- results ------------------------------------------------------------------


@dataclass(frozen=True)
class SlotFlags:
    """The report nibble of one slot, as the image read it from IRQ_STATUS."""

    slv: int
    dec: int
    pre_slv: int
    pre_dec: int

    @property
    def clean(self) -> bool:
        """The read after the clear showed neither bit."""
        return self.pre_slv == 0 and self.pre_dec == 0


@dataclass(frozen=True)
class PokeResult:
    """What the DUT returned for one op, read from the KM SRAM result words."""

    index: int
    op: PokeOp
    data: tuple[int, ...]
    flags: tuple[SlotFlags | None, ...]
    known: bool = True
    # The slv/dec flag words alone held no unknown bit (the data words may).
    flags_known: bool = True

    @property
    def value(self) -> int:
        return self.data[0]

    def _first_flags(self) -> SlotFlags:
        f = self.flags[0] if self.flags else None
        if f is None:
            raise AssertionError(f"op {self.index} ({self.op.name}) does not report slv/dec")
        return f

    @property
    def slv(self) -> int:
        return self._first_flags().slv

    @property
    def dec(self) -> int:
        return self._first_flags().dec

    @property
    def clean(self) -> bool:
        return self._first_flags().clean


def slot_flags(words: Sequence[int], slot: int) -> SlotFlags:
    word = words[W_FLAGS + slot // SLOTS_PER_FLAG_WORD]
    nib = (word >> (4 * (slot % SLOTS_PER_FLAG_WORD))) & 0xF
    return SlotFlags(nib & 1, (nib >> 1) & 1, (nib >> 2) & 1, (nib >> 3) & 1)


def slot_words(slot: int) -> tuple[int, int]:
    """The result-word indices that hold slot ``slot``: data, flags."""
    return W_DATA + slot, W_FLAGS + slot // SLOTS_PER_FLAG_WORD


def decode(
    ops: Sequence[PokeOp],
    words: Sequence[int],
    *,
    count: int | None = None,
    unknown: Iterable[int] = (),
) -> list[PokeResult]:
    """Results of the first ``count`` ops (all by default) from result words 0..97.

    ``unknown`` names result words that held an unknown bit; a result that uses
    one has ``known=False``.
    """
    if len(words) < RESULT_WORDS:
        raise ValueError(f"need {RESULT_WORDS} result words, got {len(words)}")
    bad = set(unknown)
    out: list[PokeResult] = []
    slot = 0
    for i, op in enumerate(ops[: len(ops) if count is None else count]):
        data = tuple(words[W_DATA + slot + k] for k in range(op.slots))
        if op.reports:
            per = op.slots if op.code == OP_RDBLK else min(op.slots, 1)
            flags = tuple(slot_flags(words, slot + k) if k < per else None for k in range(op.slots))
        else:
            flags = tuple(None for _ in range(op.slots))
        used: set[int] = set()
        used_flags: set[int] = set()
        for k in range(op.slots):
            d, f = slot_words(slot + k)
            used.add(d)
            if flags[k] is not None:
                used_flags.add(f)
        used |= used_flags
        out.append(
            PokeResult(
                i, op, data, flags, known=not (used & bad), flags_known=not (used_flags & bad)
            )
        )
        slot += op.slots
    return out


def state_of(word0: int) -> tuple[int, int] | None:
    """(state, tag) of STATE word 0, or None when it holds no POKE state."""
    if word0 & 0xFFFF_0000 != STATE_MAGIC:
        return None
    return (word0 >> 8) & 0xFF, word0 & 0xFF


def progress_of(word1: int) -> tuple[int, int]:
    """(ops completed, slots written) of PROG word 1."""
    return word1 & 0xFFFF, (word1 >> 16) & 0xFFFF


def error_text(err_word: int) -> str:
    code = (err_word >> 24) & 0xFF
    return (
        f"code={code} ({ERR_NAMES.get(code, 'unknown code')}) word_low=0x{err_word & 0xFF_FFFF:06x}"
    )


# --- the committed image ------------------------------------------------------


def read_parhex(path: str | Path = IMAGE_PATH) -> dict[int, int]:
    """ROM byte address -> 32-bit word of a KM ROM ``.parhex`` image.

    Each data line is ``{parity[3:0]}{word[31:0]}``; ``@<word address>`` sets the
    address; ``//`` lines are comments.
    """
    words: dict[int, int] = {}
    addr = 0
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("@"):
            addr = int(line[1:], 16)
            continue
        words[4 * addr] = int(line, 16) & WORD_MASK
        addr += 1
    return words


def rom_word(addr: int, path: str | Path = IMAGE_PATH) -> int:
    """The image word at ROM byte address ``addr`` (0 outside the image).

    This is the stimulus file, the golden of a ROM data read.
    """
    if addr % 4:
        raise ValueError(f"ROM address 0x{addr:x} is not word aligned")
    return read_parhex(path).get(addr, 0)


def check_image(path: str | Path = IMAGE_PATH) -> None:
    """Raise if the image signature does not match the layout of this module."""
    words = read_parhex(path)
    expect = (
        SIG_MAGIC,
        LAYOUT_VERSION,
        ENTRY_SPIN,
        ENTRY_RESUME,
        EXEC_BASE,
        EXEC_COUNT,
        W_FLAGS,
        W_DATA,
        N_SLOTS,
        W_BUF,
        BUF_WORDS,
        SETTLE_READS,
    )
    got = tuple(words.get(SIG_ADDR + 4 * i, 0) for i in range(len(expect)))
    if got != expect:
        raise AssertionError(
            f"{path}: POKE signature {[hex(w) for w in got]} does not match the host "
            f"layout {[hex(w) for w in expect]}; rebuild the image or update sep_km_poke.py"
        )
