# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register fields, image layout, FIFO model and report decode of sep_km_mailbox_km_side_rand_test.

No cocotb import. Field masks and reset values come from the generated RDL
headers ``hw/ip/key_manager/regs/gen/c/km_mailbox_km.h`` and ``km_csr.h`` (KM
side) and from ``sep_reg_meta.KM_MAILBOX_SEP`` (SEP side). The image
``tests/km_fw/km_rom_mbox_km.S`` types some of the same masks; ``check_image``
compares its layout table with these values and with ``MboxPlan``, so a moved
field or offset stops the leaf before it grades.

The FIFO model follows ``architecture.adoc``, "Mailbox Transport": reads pop
words in order, writes push words, a write to a full FIFO and a read of an
empty one change nothing, and a flush from either side empties both FIFOs.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from env import sep_km_img_param as kip
from env.sep_reg_meta import KM_MAILBOX_SEP, CHeaderRegBlock

TEST = kip.T_MBOX_KM
DEPTH = kip.MBOX_DEPTH
WORD = 0xFFFF_FFFF

_HW = Path(__file__).resolve().parents[6]
_KM_C = _HW / "ip" / "key_manager" / "regs" / "gen" / "c"
TEMPLATE = Path(__file__).resolve().parents[1] / "km_rom_mbox_km.parhex"
STAGED_NAME = "km_rom_mbox_km.param.parhex"

KMB = CHeaderRegBlock("KM_MAILBOX_KM", _KM_C / "km_mailbox_km.h")
KCSR = CHeaderRegBlock("KM_CSR", _KM_C / "km_csr.h")


def _bm(blk: CHeaderRegBlock, reg: str, field: str) -> int:
    return blk.fields(reg)[field]["bm"]


def fmask(blk: CHeaderRegBlock, reg: str) -> int:
    """Union of the named (non-reserved) field bits of ``reg``."""
    return sum(m["bm"] for n, m in blk.fields(reg).items() if n != "RSVD")


def fld(value: int, mask: int) -> int:
    """Value of the field ``mask`` in ``value``."""
    return (value & mask) >> ((mask & -mask).bit_length() - 1)


# KM side (km_mailbox_km.adoc).
ST = "STATUS_REG"
ST_IN_EMPTY = _bm(KMB, ST, "INBOUND_EMPTY")
ST_IN_FULL = _bm(KMB, ST, "INBOUND_FULL")
ST_OUT_EMPTY = _bm(KMB, ST, "OUTBOUND_EMPTY")
ST_OUT_FULL = _bm(KMB, ST, "OUTBOUND_FULL")
ST_IN_DEPTH = _bm(KMB, ST, "INBOUND_DEPTH")
ST_OUT_DEPTH = _bm(KMB, ST, "OUTBOUND_DEPTH")
ST_IN_OVF = _bm(KMB, ST, "INBOUND_OVERFLOW")
ST_OUT_OVF = _bm(KMB, ST, "OUTBOUND_OVERFLOW")
ST_IN_UDF = _bm(KMB, ST, "INBOUND_UNDERFLOW")
ST_OUT_UDF = _bm(KMB, ST, "OUTBOUND_UNDERFLOW")
ST_IN_SEP = _bm(KMB, ST, "INBOUND_SEPARATOR")
ST_STICKY = ST_IN_OVF | ST_OUT_OVF | ST_IN_UDF | ST_OUT_UDF
ST_FIELDS = fmask(KMB, ST)
ST_RESET = KMB.reset(ST)

IRQ = "IRQ_STATUS_REG"
IRQ_SRC = (
    _bm(KMB, IRQ, "INBOUND_READ_DATA_AVAIL"),
    _bm(KMB, IRQ, "OUTBOUND_WRITE_SPACE_AVAIL"),
    _bm(KMB, IRQ, "OUTBOUND_OVERFLOW"),
    _bm(KMB, IRQ, "INBOUND_UNDERFLOW"),
    _bm(KMB, IRQ, "FLUSHED_BY_SEP"),
)
IRQ_LEVEL = IRQ_SRC[0] | IRQ_SRC[1]
IRQ_OUT_OVF = IRQ_SRC[2]
IRQ_IN_UDF = IRQ_SRC[3]
IRQ_FLUSHED = IRQ_SRC[4]
IRQ_STICKY = IRQ_OUT_OVF | IRQ_IN_UDF | IRQ_FLUSHED
IRQ_FIELDS = fmask(KMB, IRQ)

EN = "IRQ_ENABLE_REG"
EN_SRC = (
    _bm(KMB, EN, "INBOUND_READ_DATA_AVAIL_EN"),
    _bm(KMB, EN, "OUTBOUND_WRITE_SPACE_AVAIL_EN"),
    _bm(KMB, EN, "OUTBOUND_OVERFLOW_EN"),
    _bm(KMB, EN, "INBOUND_UNDERFLOW_EN"),
    _bm(KMB, EN, "FLUSHED_BY_SEP_EN"),
)
EN_FIELDS = fmask(KMB, EN)
EN_RESET = KMB.reset(EN)

CTRL = "CTRL_REG"
CTRL_OVF_RESP = _bm(KMB, CTRL, "OUTBOUND_OVERFLOW_RESP")
CTRL_UDF_RESP = _bm(KMB, CTRL, "INBOUND_UNDERFLOW_RESP")
CTRL_FLUSH = _bm(KMB, CTRL, "FLUSH")
CTRL_FIELDS = fmask(KMB, CTRL)
CTRL_RESET = KMB.reset(CTRL)

WSEP = "WRITE_SEPARATOR_REG"
WSEP_SET = _bm(KMB, WSEP, "SET")
WSEP_FIELDS = fmask(KMB, WSEP)
WSEP_RESET = KMB.reset(WSEP)

# KMCSR (km_csr.adoc).
CSR_SLVERR = _bm(KCSR, "IRQ_STATUS_REG", "AXI_SLVERR")
CSR_DECERR = _bm(KCSR, "IRQ_STATUS_REG", "AXI_DECERR")
CSR_DRBG = _bm(KCSR, "IRQ_STATUS_REG", "DRBG_ERR")
CSR_DRBG_EN = _bm(KCSR, "IRQ_ENABLE_REG", "DRBG_ERR_EN")
CSR_DRBG_SET = _bm(KCSR, "IRQ_SET_REG", "DRBG_ERR_SET")
CSR_IRQ_FIELDS = fmask(KCSR, "IRQ_STATUS_REG")
CSR_EN_FIELDS = fmask(KCSR, "IRQ_ENABLE_REG")

# SEP side (km_mailbox_sep.adoc).
_S = KM_MAILBOX_SEP
S_IN_EMPTY = _S.field_mask("SEP_STATUS", "inbound_empty")
S_IN_FULL = _S.field_mask("SEP_STATUS", "inbound_full")
S_OUT_EMPTY = _S.field_mask("SEP_STATUS", "outbound_empty")
S_OUT_FULL = _S.field_mask("SEP_STATUS", "outbound_full")
S_IN_DEPTH = _S.field_mask("SEP_STATUS", "inbound_depth")
S_OUT_DEPTH = _S.field_mask("SEP_STATUS", "outbound_depth")
S_OUT_SEP = _S.field_mask("SEP_STATUS", "outbound_separator")
S_FLUSHED_BY_KM = _S.field_mask("SEP_IRQ_STATUS", "flushed_by_km")
S_CTRL_FLUSH = _S.field_mask("SEP_CTRL", "flush")
S_CTRL_FIELDS = _S.mask32("SEP_CTRL")

# Image layout (tests/km_fw/km_rom_mbox_km.S).
SIG_WORD = 0x80 // 4
SIG_MAGIC = 0x4D42_4B4D
LAYOUT_VERSION = 1
STATE_MAGIC = 0x4D42_0000
SYNC_WORD = 0x5359_4E43
QUIET_ITERS = 64
SETTLE_READS = 32
W_STATE = 0
W_AUX = 1
W_CNT3 = 2
W_CNT4 = 3
W_BUS = 4
W_R = 5
N_R = 93
CYCLE_WORDS = 5
IRQ_RUN_CYCLE_BASE = 8
N_CYCLES = 11

PH_RST = 0x01
PH_OUT = 0x02
PH_IN_READY = 0x03
PH_IN_MID = 0x04
PH_IN = 0x05
PH_ERR = 0x06
PH_FL_FILLED = 0x07
PH_FL_PRE = 0x08
PH_FL_DONE = 0x09
PH_IRQ_START = 0x0A
PH_IRQ_NEED = 0x0B
PH_IRQ_RUN = 0x0C
PH_IRQ_CTL = 0x0D
PH_END = 0x0E
PH_ERROR = 0xEE
PHASE_NAMES = {
    PH_RST: "RST",
    PH_OUT: "OUT",
    PH_IN_READY: "IN_READY",
    PH_IN_MID: "IN_MID",
    PH_IN: "IN",
    PH_ERR: "ERR",
    PH_FL_FILLED: "FL_FILLED",
    PH_FL_PRE: "FL_PRE",
    PH_FL_DONE: "FL_DONE",
    PH_IRQ_START: "IRQ_START",
    PH_IRQ_NEED: "IRQ_NEED",
    PH_IRQ_RUN: "IRQ_RUN",
    PH_IRQ_CTL: "IRQ_CTL",
    PH_END: "END",
    PH_ERROR: "ERROR",
}
ERR_NAMES = {
    1: "bad parameter block",
    2: "sync word timeout",
    3: "wrong sync word",
    4: "inbound FIFO not empty after the sync word",
    5: "bounded wait ran out",
}

OUT_COUNTS = (DEPTH, 1, DEPTH - 1)
IN_COUNTS = (DEPTH, 1, DEPTH - 1)
# Flush cells (MboxPlan): 0-2 KM, 3-5 SEP; fill 0 empty, 1 one FIFO, 2 both.
CELL_INIT = ("km", "km", "km", "sep", "sep", "sep")
CELL_FILL = (0, 1, 2, 0, 1, 2)
SRC_NAMES = ("in_data", "out_space", "out_ovf", "in_udf", "flushed")


def image_table() -> list[tuple[str, int]]:
    """The layout table the image must hold at SIG_ADDR, in its order."""
    p = kip.MboxPlan
    return [
        ("magic", SIG_MAGIC),
        ("version", LAYOUT_VERSION),
        ("param_base", kip.PARAM_BASE_WORD * 4),
        ("param_id", (kip.PARAM_VERSION << 16) | kip.BLOCK_MBOX_KM),
        ("payload_words", p.PAYLOAD_WORDS),
        ("off_n", p.OFF_N),
        ("off_m", p.OFF_M),
        ("off_err_first", p.OFF_ERR_FIRST),
        ("off_flush_order", p.OFF_FLUSH_ORDER),
        ("off_flush_one", p.OFF_FLUSH_ONE),
        ("off_irq_s", p.OFF_IRQ_S),
        ("off_src_order", p.OFF_SRC_ORDER),
        ("off_out_pass", p.OFF_OUT_PASS),
        ("off_overflow", p.OFF_OVERFLOW),
        ("off_out_flush", p.OFF_OUT_FLUSH),
        ("off_out_irq", p.OFF_OUT_IRQ),
        ("irq_run_words", p.IRQ_RUN_WORDS),
        ("flush_fill", p.FLUSH_FILL),
        ("sync_word", SYNC_WORD),
        ("quiet_iters", QUIET_ITERS),
        ("settle_reads", SETTLE_READS),
        ("w_r", W_R),
        ("st_in_empty", ST_IN_EMPTY),
        ("st_out_full", ST_OUT_FULL),
        ("st_in_depth_lsb", (ST_IN_DEPTH & -ST_IN_DEPTH).bit_length() - 1),
        ("st_depth_field", fld(ST_IN_DEPTH, ST_IN_DEPTH)),
        ("st_out_ovf", ST_OUT_OVF),
        ("st_in_udf", ST_IN_UDF),
        ("st_sticky", ST_STICKY),
        ("irq_out_ovf", IRQ_OUT_OVF),
        ("irq_in_udf", IRQ_IN_UDF),
        ("irq_flushed", IRQ_FLUSHED),
        ("ctrl_ovf_resp", CTRL_OVF_RESP),
        ("ctrl_udf_resp", CTRL_UDF_RESP),
        ("ctrl_flush", CTRL_FLUSH),
        ("sep_set", WSEP_SET),
        ("csr_slverr", CSR_SLVERR),
        ("csr_drbg", CSR_DRBG),
        ("csr_drbg_en", CSR_DRBG_EN),
        ("csr_drbg_set", CSR_DRBG_SET),
        ("csr_irq_all", CSR_IRQ_FIELDS),
        ("state_magic", STATE_MAGIC),
    ]


def read_parhex(text: str) -> dict[int, int]:
    """Word index -> 32-bit word of a KM ROM .parhex text."""
    words: dict[int, int] = {}
    addr = 0
    for raw in text.splitlines():
        tok = raw.strip()
        if not tok or tok.startswith("//"):
            continue
        if tok.startswith("@"):
            addr = int(tok[1:], 16)
            continue
        words[addr] = int(tok, 16) & WORD
        addr += 1
    return words


def check_image(text: str) -> list[str]:
    """Differences between the image layout table and the host layout."""
    rom = read_parhex(text)
    bad = []
    for i, (name, want) in enumerate(image_table()):
        got = rom.get(SIG_WORD + i)
        if got != want:
            bad.append(f"{name}: image {got if got is None else hex(got)} host {want:#x}")
    # The image writes the drawn subset S as the raw KM_IRQ_ENABLE value and
    # reads source i as KM_IRQ_STATUS bit i.
    if EN_SRC != tuple(1 << i for i in range(5)) or IRQ_SRC != EN_SRC:
        bad.append("KM_IRQ_ENABLE / KM_IRQ_STATUS sources are not bits 0-4")
    last = max(rom) if rom else -1
    if last >= kip.PARAM_BASE_WORD:
        bad.append(f"template reaches ROM word {last:#x}")
    return bad


def state_of(word: int) -> tuple[int, int] | None:
    """(seq, phase) of a STATE word, or None when the magic is absent."""
    if (word & 0xFFFF_0000) != STATE_MAGIC:
        return None
    return (word >> 8) & 0xFF, word & 0xFF


def err_text(aux: int) -> str:
    code = aux >> 24
    return f"{ERR_NAMES.get(code, 'unknown error')} (code {code}, detail {aux & 0xFFFFFF:#x})"


def check_word(item: str, seed: int) -> int:
    """The XOR check word of the block the leaf stages."""
    return kip.block_words(item, seed)[-1]


@dataclass
class HostDraws:
    """Words that only the host writes, drawn from a host stream of the seed."""

    extra: list[int]
    irq_in: list[int]


# A second SepSeededRng stream for the host-only words. It is a fixed
# function of the leaf seed and does not touch the plan stream.
HOST_STREAM = 0x7330_0000_0000


def host_draws(rng) -> HostDraws:
    """The extra inbound word of each pass and the source-0 word of each run."""
    taken = {SYNC_WORD}

    def fresh() -> int:
        for _ in range(64):
            v = rng.getrandbits(32)
            if v and v not in taken:
                taken.add(v)
                return v
        raise RuntimeError("no fresh host word")

    return HostDraws(extra=[fresh() for _ in range(4)], irq_in=[fresh() for _ in range(2)])


class Fifo:
    """One mailbox FIFO: depth DEPTH, a separator bit per word."""

    def __init__(self) -> None:
        self.q: deque[tuple[int, bool]] = deque()
        self.last_sep = False

    @property
    def depth(self) -> int:
        return len(self.q)

    def push(self, word: int, sep: bool = False) -> bool:
        if len(self.q) >= DEPTH:
            return False
        self.q.append((word & WORD, sep))
        return True

    def pop(self) -> int | None:
        if not self.q:
            return None
        word, sep = self.q.popleft()
        self.last_sep = sep
        return word

    def flush(self) -> None:
        self.q.clear()


class Mailbox:
    """Both FIFOs. ``inb`` is SEP -> KM, ``outb`` is KM -> SEP."""

    def __init__(self) -> None:
        self.inb = Fifo()
        self.outb = Fifo()

    def flush(self) -> None:
        self.inb.flush()
        self.outb.flush()


def km_depths(st: int) -> tuple[int, int]:
    """(outbound, inbound) depth of a KM_STATUS value."""
    return fld(st, ST_OUT_DEPTH), fld(st, ST_IN_DEPTH)


def sep_depths(st: int) -> tuple[int, int]:
    """(outbound, inbound) depth of a SEP_STATUS value."""
    return fld(st, S_OUT_DEPTH), fld(st, S_IN_DEPTH)


def src_vector(state: dict[str, int]) -> int:
    """KM_IRQ_STATUS[4:0] that the register text gives for a mailbox state."""
    v = 0
    if state["in"] > 0:
        v |= IRQ_SRC[0]
    if state["out"] < DEPTH:
        v |= IRQ_SRC[1]
    if state["ovf"]:
        v |= IRQ_SRC[2]
    if state["udf"]:
        v |= IRQ_SRC[3]
    if state["flushed"]:
        v |= IRQ_SRC[4]
    return v


def enabled(src_vec: int, en: int) -> bool:
    """The model line: the OR over the sources of (status bit AND enable bit)."""
    return any((src_vec & s) and (en & e) for s, e in zip(IRQ_SRC, EN_SRC))


def run_steps(src_order: list[int]) -> list[tuple[str, int, int]]:
    """The 11 check cycles of one run: (kind, source, expected KM_IRQ_STATUS[4:0])."""
    st = {"in": 0, "out": DEPTH, "ovf": 0, "udf": 0, "flushed": 0}
    steps = [("idle", -1, src_vector(st))]
    for src in [*src_order, 4]:
        if src == 0:
            st["in"] = 1
        elif src == 1:
            st["out"] = DEPTH - 1
        elif src == 2:
            st["ovf"] = 1
        elif src == 3:
            st["udf"] = 1
        else:
            st["in"] = 0
            st["out"] = 0
            st["flushed"] = 1
        steps.append(("raise", src, src_vector(st)))
        if src == 0:
            st["in"] = 0
        elif src == 1:
            st["out"] = DEPTH
        elif src == 2:
            st["ovf"] = 0
        elif src == 3:
            st["udf"] = 0
        else:
            st["flushed"] = 0
        steps.append(("clear", src, src_vector(st)))
    return steps


def en_value(mask5: int) -> int:
    """KM_IRQ_ENABLE value of a five-bit source subset (bit i = source i)."""
    return sum(e for i, e in enumerate(EN_SRC) if (mask5 >> i) & 1)
