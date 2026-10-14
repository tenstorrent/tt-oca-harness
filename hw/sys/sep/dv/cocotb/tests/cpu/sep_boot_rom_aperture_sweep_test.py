# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot ROM aperture sweep: read sizes, store absorption, no ECC and a reset in flight.

The bench builds a ROM image of 8192 seeded 64-bit words (words 0 to 15 hold a
fixed boot stub with distinct words) and writes it into the ROM macro through
the backdoor before reset release. The stub jumps to code in the SEP SRAM,
which the bench generates (``env/sep_rv32_asm``) and stages through the same
backdoor together with its probe table. The code runs from the SRAM, so only
its data loads use the LSU ROM path. It stores every logged value as a 32-bit
word to the outbound mailbox; the PR-OUT tap decodes the records
(``env/sep_mbx_words``). The probe plan (addresses, sizes, stores, flips) is
drawn from the run seed and is part of the generated code and table.

Checks:
  CHK-ROM-SWEEP    : every logged 1, 2 and 4-byte load equals the image bytes at
                     word index (addr - 0x1004_0000) >> 3 and byte offset
                     addr & 7, little-endian; the ``ROM_CTL`` read is 0x0 on its
                     RDL field bits (rom.adoc ROM Architecture;
                     sep_efuse_map.adoc ``ROM_CTL``). Boundary words: word 0,
                     the 13 walking-one words and the top word 8191, each at
                     every aligned offset of every size.
  CHK-ROM-PORT     : each load of steps 7 to 11 appears once on PR-LSU-ROM and
                     once on PR-ROM with its word address and read intent, no
                     write-enable cycle, and PR-LSU-XBAR carries no ROM address.
                     Control: the SRAM word load of step 6 is on PR-LSU-XBAR
                     and not on PR-LSU-ROM.
  CHK-ROM-STORE    : each of 16 byte and halfword stores completes, and the word
                     reads back as the image before and after the store
                     (rom.adoc: stores receive a response and do not modify
                     the ROM).
  CHK-ROM-STORE-WE : in the store leg, PR-ROM-MACRO shows requests at a store
                     word only for its four readback loads.
  CHK-ROM-NOECC    : a 1-bit or 2-bit flip in a stored word reads back as the
                     flipped data with no trap and no NMI; the neighbour words
                     read exact. Control: one ``ecall`` raises the trap count by
                     one (rom.adoc Hardware Configuration and Integrity).
  CHK-ROM-OTF      : ``rst_ni`` falls after the PR-ROM handshake of the stub
                     fetch at word address 1 and before its response beat,
                     and PR-ROM-MACRO shows that fetch at the macro before the
                     fall; after ``sep_cpu_reset_n_o`` rises, the first PR-ROM
                     request is word 0, no response beat precedes it and the
                     first response carries image word 0 (reset_controller.adoc
                     SEP Reset Controller). The response window W comes from the
                     same fetch of the calibration boot, whose beat carries
                     image word 1.

The routine first sets ``mrac`` as the SEP firmware start-up does
(``fw/startup/crt0.s``), so each register store leaves the core at its own size.
The CSR number and the value are parsed from the first ``li t0`` and
``csrw <csr>, t0`` pair of ``_start`` in that file, and the routine reads the
CSR back into a mailbox record once the outbound filter entry for the mailbox
is open; a read-back that differs fails the leaf (``CTL-ROM-MRAC``).
The core can serve two pending loads of one doubleword with one bus read, and
it can merge two pending stores to one address. The 16 loads of a block are
therefore in 16 different words, the two loads of each store-leg readback have
a fence between them, and a fence follows each record store, so each load is
one ROM request and each record is one outbound write.

Fuse image: the run mode needs a staged image with ``ROM_CTL`` = 0. The default
preload holds a non-zero ``ROM_CTL``, so the testlist entry stages the PROD
configuration ``sep_efuse_lc_prod.toml`` (every field other than the life cycle
state is 0) with real fuse sense; the leaf checks that the golden image holds
``ROM_CTL`` = 0 before it boots.

Every expected value comes from the test-owned image and the drawn plan; no
expected value is read from the DUT. Bounds are environment choices and are
logged on the ``ENV`` line.

cpu run mode (real core), real fuse sense; Verilator and VCS.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_mbx_words import SepMbxWords
from env.sep_rom_image import ROM_WORDS, SepRomImage, rom_flip
from env.sep_rv32_asm import (
    A0,
    A1,
    A2,
    A3,
    CSR_MCAUSE,
    CSR_MDEAU,
    CSR_MDSEAC,
    CSR_MEPC,
    CSR_MTVEC,
    ECALL,
    FENCE,
    GP,
    MRET,
    S0,
    S1,
    S2,
    S3,
    S4,
    S11,
    T0,
    T1,
    T2,
    T3,
    T4,
    T6,
    ZERO,
    Asm,
    addi,
    andi,
    csrr,
    csrw,
    jalr,
    li,
    load,
    lw,
    or_,
    slli,
    store,
    sub,
    sw,
)
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import RegBlock, sym

TEST = "sep_boot_rom_aperture_sweep_test"

ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
ROM_BYTES = sym("SEP_BOOT_ROM_MEM_SIZE")
SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_WORDS = sym("SEP_SRAM_MEM_SIZE") // 8
if ROM_BYTES // 8 != ROM_WORDS:
    raise RuntimeError("the ROM image model and the memory map disagree on the ROM size")
TOP_WORD = ROM_WORDS - 1
WORD_BITS = (ROM_WORDS - 1).bit_length()  # 13 word-index bits

_CPU_CTRL = RegBlock("SEP_CPU_CTRL")
_EFUSE = RegBlock("SEP_EFUSE_MAP")
_OUTF = RegBlock("OUTBOUND_FILTER_CTRL_0_")
ROM_CTL_ADDR = _EFUSE.addr("ROM_CTL")
ROM_CTL_MASK = _EFUSE.mask32("ROM_CTL")
NMI_VEC_ADDR = _CPU_CTRL.addr("SEP_NMI_VEC")

# Outbound mailbox (tb/sep_outbound_mbx.sv, the SMU_GLOBAL_BASE_ADDR reset value).
MBX = _CPU_CTRL.reset("SMU_GLOBAL_BASE_ADDR") & _CPU_CTRL.mask("SMU_GLOBAL_BASE_ADDR")
FILTER_CFG_OPEN = (
    _OUTF.field_mask("FILTER_CONFIG", "read_allowed")
    | _OUTF.field_mask("FILTER_CONFIG", "write_allowed")
    | _OUTF.field_mask("FILTER_CONFIG", "entry_enabled")
    | _OUTF.field_mask("FILTER_CONFIG", "allow_burst")
    | (_OUTF.reset("FILTER_CONFIG") & _OUTF.field_mask("FILTER_CONFIG", "data_bus_width"))
)

# Mailbox record offsets. Each marker has its own 8-byte slot, so its store is
# found by address on the LSU taps.
OFF_ROMCTL = 0x10
OFF_FAIL = 0x18
OFF_CTL_B = 0x20
OFF_CTL_V = 0x28
OFF_CTL_E = 0x30
OFF_SWEEP_B = 0x38
OFF_LA = 0x40  # (addr - ROM base) | size << 16
OFF_LV = 0x48
OFF_SWEEP_E = 0x50
OFF_ST_B = 0x58
OFF_SB = 0x60  # +0 low word, +4 high word
OFF_SDONE = 0x68
OFF_SA = 0x70  # +0 low word, +4 high word
OFF_ST_E = 0x78
OFF_TCNT = 0x80
OFF_FLIP_READY = 0x88
OFF_FA = 0x90
OFF_FV = 0x98  # +0 low word, +4 high word
OFF_DONE = 0xA0
OFF_TRAP = 0xA8
OFF_NMI = 0xB0
OFF_NMI_ADDR = 0xB8
OFF_MRAC = 0xC0
FAIL_ROMCTL, FAIL_FLAG = 1, 2

# SRAM layout of the generated image.
FW_BASE = SRAM_BASE
TABLE = SRAM_BASE + 0x8000
FLAG = SRAM_BASE + 0xC000
CTL_LO = SRAM_BASE + 0xD000

N_SEEDED = 512
N_SEQ = 512
SEQ_BASE_MAX = ROM_WORDS - N_SEQ  # 7680
N_BLOCKS, BLOCK_LEN = 8, 16
N_STORES = 16
N_FLIP1 = N_FLIP2 = 8
SIZES = (1, 2, 4)
BLOCK_REGS = tuple(range(5, 21))  # x5..x20
TAG_REG = 21

CRT0 = Path(__file__).resolve().parents[3] / "fw" / "startup" / "crt0.s"


def _crt0_mrac(path: Path) -> tuple[int, int]:
    """(CSR number, value) of the first ``li t0, V`` / ``csrw C, t0`` pair of ``_start``.

    That pair is the VeeR EL2 ``mrac`` write of the SEP firmware start-up.
    """
    text = path.read_text()
    equ = {m[1]: int(m[2], 0) for m in re.finditer(r"^\s*\.equ\s+(\w+)\s*,\s*(\w+)", text, re.M)}
    body = text.split("_start:", 1)[1]
    m = re.search(r"^\s*li\s+t0\s*,\s*(\w+)\s*\n\s*csrw\s+(\w+)\s*,\s*t0\b", body, re.M)
    if m is None:
        raise RuntimeError(f"{path}: no li t0 / csrw t0 pair in _start")
    csr = equ.get(m[2])
    if csr is None:
        csr = int(m[2], 0)
    return csr, int(m[1], 0)


# VeeR EL2 mrac (region access control) as fw/startup/crt0.s writes it.
CSR_MRAC, MRAC_SEP = _crt0_mrac(CRT0)

# Environment choices (logged).
RST_HOLD = 20  # clk_i cycles of each rst_ni pulse
ROMCTL_BOUND = 200_000  # clk_i cycles from the boot to the ROM_CTL record
SWEEP_BOUND = 2_000_000  # clk_i cycles for steps 6 to 11
STORE_BOUND = 20_000  # clk_i cycles from one store completion marker to the next
FLIP_POLL = 100_000  # firmware poll iterations for the release flag
LEG_BOUND = 400_000  # clk_i cycles for the flip leg and the done record
CPU_LOW_BOUND = 1_000  # clk_i cycles for sep_cpu_reset_n_o to fall after rst_ni falls
RELEASE_BOUND = 200_000  # clk_i cycles for sep_cpu_reset_n_o to rise (fuse sense runs)
ANCHOR_BOUND = 200_000  # clk_i cycles for the anchor fetch after a release
FIRST_REQ_BOUND = 50_000  # clk_i cycles for the first PR-ROM request after the release
RSP_BOUND = 64  # clk_i cycles for a PR-ROM response beat after its request


def _cells(word: int) -> list[tuple[int, int]]:
    """(address, size) of every aligned offset of every size in one word (14 cells)."""
    base = ROM_BASE + 8 * word
    return [(base + off, s) for s in SIZES for off in range(0, 8, s)]


def _tag(addr: int, size: int) -> int:
    return (addr - ROM_BASE) | (size << 16)


class _Plan:
    """The seed-drawn stimulus, in the contract draw order."""

    def __init__(self, rng: SepSeededRng) -> None:
        # Image.
        self.img = SepRomImage(stub=self._stub())
        self.img.randomize(rng, first=16, last=TOP_WORD)
        # Probes.
        self.top = _cells(TOP_WORD)
        self.walk_words = [0] + [1 << b for b in range(WORD_BITS)]
        self.walk = [c for w in self.walk_words for c in _cells(w)]
        self.seeded = []
        for _ in range(N_SEEDED):
            s = rng.choice(SIZES)
            self.seeded.append((ROM_BASE + s * rng.randrange(ROM_BYTES // s), s))
        self.seq_base = rng.randrange(SEQ_BASE_MAX + 1)
        self.seq_size = rng.choice(SIZES)
        self.seq_off = self.seq_size * rng.randrange(8 // self.seq_size)
        self.seq = [
            (ROM_BASE + 8 * (self.seq_base + k) + self.seq_off, self.seq_size) for k in range(N_SEQ)
        ]
        self.blocks = []
        # The 16 loads of a block are in 16 different words: the core can
        # serve two pending loads of one doubleword with one bus read, and the
        # port check counts one request per load.
        for _ in range(N_BLOCKS):
            blk: list[tuple[int, int]] = []
            while len(blk) < BLOCK_LEN:
                s = rng.choice(SIZES)
                addr = ROM_BASE + s * rng.randrange(ROM_BYTES // s)
                if all((addr >> 3) != (a >> 3) for a, _s in blk):
                    blk.append((addr, s))
            self.blocks.append(blk)
        self.sram_ctl = CTL_LO + 4 * rng.randrange((SRAM_BASE + 8 * SRAM_WORDS - CTL_LO) // 4)
        self.sram_ctl_val = rng.getrandbits(32)
        # Stores: a byte or halfword in words 16..8191, data different from the
        # image in every stored byte.
        self.stores = []
        for _ in range(N_STORES):
            s = rng.choice((1, 2))
            addr = ROM_BASE + 8 * 16 + s * rng.randrange((ROM_BYTES - 8 * 16) // s)
            data = 0
            for b in range(s):
                data |= (self.img.read(addr + b, 1) ^ (1 + rng.randrange(255))) << (8 * b)
            self.stores.append((addr, s, data))
        # Flips: 16 words in 16..8190, no two adjacent; 8 with one bit, 8 with two.
        words: list[int] = []
        while len(words) < N_FLIP1 + N_FLIP2:
            w = 16 + rng.randrange(TOP_WORD - 16)
            if all(abs(w - x) > 1 for x in words):
                words.append(w)
        self.flips = []
        for k, w in enumerate(words):
            if k < N_FLIP1:
                mask = 1 << rng.randrange(64)
            else:
                b1, b2 = rng.sample(range(64), 2)
                mask = (1 << b1) | (1 << b2)
            self.flips.append((w, mask))
        # Reset offset fraction u_o = u / 2^16.
        self.u = rng.randrange(1 << 16)

    @staticmethod
    def _stub() -> list[int]:
        """li t0, FW_BASE; jalr x0, 0(t0); then distinct ``addi x0, x0, k`` words."""
        insns = li(T0, FW_BASE) + [jalr(ZERO, T0, 0)]
        insns += [addi(ZERO, ZERO, k) for k in range(1, 32 - len(insns) + 1)]
        return insns

    def sweep(self) -> list[tuple[int, int, str]]:
        """Loads of steps 7 to 11 in program order: (addr, size, step)."""
        out = [(a, s, "top") for a, s in self.top]
        out += [(a, s, "walk") for a, s in self.walk]
        out += [(a, s, "seeded") for a, s in self.seeded]
        out += [(a, s, "seq") for a, s in self.seq]
        out += [(a, s, "block") for blk in self.blocks for a, s in blk]
        return out

    def table(self) -> list[tuple[int, int]]:
        """Table-driven loads (steps 7 to 10)."""
        return self.top + self.walk + self.seeded + self.seq


def _mark(a: Asm, off: int) -> None:
    a.op(FENCE, sw(ZERO, GP, off), FENCE)


def _fail(a: Asm, code: int) -> None:
    a.li(T0, code).op(sw(T0, GP, OFF_FAIL), FENCE).j("halt")


def build_code(p: _Plan) -> Asm:
    """The SRAM routine of steps 4 to 13."""
    a = Asm(FW_BASE)
    a.li(T0, MRAC_SEP).op(csrw(CSR_MRAC, T0))
    a.li(GP, MBX)
    for reg, val in (
        ("START_ADDR", MBX),
        ("END_ADDR", MBX + 0xFF),
        ("FILTER_CONFIG", FILTER_CFG_OPEN),
    ):
        a.li(T1, _OUTF.addr(reg)).li(T2, val & 0xFFFF_FFFF).op(sw(T2, T1, 0))
        a.li(T2, val >> 32).op(sw(T2, T1, 4))
    a.li(T1, NMI_VEC_ADDR).la(T2, "nmi").op(sw(T2, T1, 0))
    a.la(T0, "trap").op(csrw(CSR_MTVEC, T0), addi(S11, ZERO, 0), FENCE)
    # The mailbox store comes after the outbound filter entry that admits it.
    a.op(csrr(T0, CSR_MRAC), sw(T0, GP, OFF_MRAC), FENCE)
    # Step 4: ROM_CTL; any field bit set stops the routine.
    a.li(T0, ROM_CTL_ADDR).op(lw(A0, T0, 0), sw(A0, GP, OFF_ROMCTL), FENCE)
    a.op(andi(A1, A0, ROM_CTL_MASK)).br("beq", A1, ZERO, "ctl_ok")
    _fail(a, FAIL_ROMCTL)
    a.label("ctl_ok")
    # Step 6: SRAM control load.
    _mark(a, OFF_CTL_B)
    a.li(T0, p.sram_ctl).op(lw(A0, T0, 0), sw(A0, GP, OFF_CTL_V))
    _mark(a, OFF_CTL_E)
    # Steps 7 to 10: the table loop.
    _mark(a, OFF_SWEEP_B)
    a.li(S0, TABLE).li(S1, TABLE + 8 * len(p.table())).li(S2, ROM_BASE)
    a.op(addi(S3, ZERO, 1), addi(S4, ZERO, 2))
    a.label("tl").op(lw(A0, S0, 0), lw(A1, S0, 4))
    a.br("beq", A1, S3, "tb1").br("beq", A1, S4, "tb2")
    a.op(load(4, A2, A0, 0)).j("tlog")
    a.label("tb1").op(load(1, A2, A0, 0)).j("tlog")
    a.label("tb2").op(load(2, A2, A0, 0))
    a.label("tlog").op(sub(T3, A0, S2), slli(T4, A1, 16), or_(T3, T3, T4))
    # A fence after each record pair keeps the core from merging two stores
    # to one mailbox slot.
    a.op(sw(T3, GP, OFF_LA), sw(A2, GP, OFF_LV), FENCE, addi(S0, S0, 8))
    a.br("bne", S0, S1, "tl")
    # Step 11: eight blocks of 16 loads with no other instruction between them.
    for blk in p.blocks:
        for r, (addr, _s) in zip(BLOCK_REGS, blk):
            a.li(r, addr)
        for r, (_addr, s) in zip(BLOCK_REGS, blk):
            a.op(load(s, r, r, 0))
        for r, (addr, s) in zip(BLOCK_REGS, blk):
            a.li(TAG_REG, _tag(addr, s)).op(sw(TAG_REG, GP, OFF_LA), sw(r, GP, OFF_LV), FENCE)
    _mark(a, OFF_SWEEP_E)
    # Step 12: stores, each between two readbacks of its word.
    _mark(a, OFF_ST_B)
    for i, (addr, s, data) in enumerate(p.stores):
        # A fence between the two loads of a readback keeps them two bus reads.
        a.li(S0, addr & ~7).op(lw(A0, S0, 0), FENCE, lw(A1, S0, 4))
        a.op(sw(A0, GP, OFF_SB), sw(A1, GP, OFF_SB + 4), FENCE)
        a.li(S1, addr).li(A2, data).op(store(s, A2, S1, 0), FENCE)
        a.li(A3, i).op(sw(A3, GP, OFF_SDONE), FENCE)
        a.op(lw(A0, S0, 0), FENCE, lw(A1, S0, 4))
        a.op(sw(A0, GP, OFF_SA), sw(A1, GP, OFF_SA + 4), FENCE)
    _mark(a, OFF_ST_E)
    # Step 13: wait for the flips, one ecall, then read each flipped word and
    # its neighbours.
    a.op(sw(S11, GP, OFF_TCNT))
    _mark(a, OFF_FLIP_READY)
    a.li(T0, FLAG).li(T1, FLIP_POLL)
    a.label("poll").op(lw(T2, T0, 0)).br("bne", T2, ZERO, "go")
    a.op(addi(T1, T1, -1)).br("bne", T1, ZERO, "poll")
    _fail(a, FAIL_FLAG)
    a.label("go").op(ECALL, FENCE, sw(S11, GP, OFF_TCNT), FENCE)
    for w, _m in p.flips:
        for x in (w - 1, w, w + 1):
            a.li(S0, ROM_BASE + 8 * x).op(lw(A0, S0, 0), lw(A1, S0, 4))
            a.li(T3, x).op(sw(T3, GP, OFF_FA), sw(A0, GP, OFF_FV), sw(A1, GP, OFF_FV + 4), FENCE)
    a.op(FENCE, sw(S11, GP, OFF_TCNT))
    _mark(a, OFF_DONE)
    a.label("halt").j("halt")
    # Trap handler: log mcause, count, resume after the trapping instruction.
    a.align(64).label("trap")
    a.op(csrr(T6, CSR_MCAUSE), sw(T6, GP, OFF_TRAP), addi(S11, S11, 1))
    a.op(csrr(T6, CSR_MEPC), addi(T6, T6, 4), csrw(CSR_MEPC, T6), FENCE, MRET)
    # NMI handler: log mcause and the D-bus error address, unlock it, return.
    a.align(64).label("nmi")
    a.op(csrr(T6, CSR_MCAUSE), sw(T6, GP, OFF_NMI), csrr(T6, CSR_MDSEAC))
    a.op(sw(T6, GP, OFF_NMI_ADDR), csrw(CSR_MDEAU, ZERO), FENCE, MRET)
    if FW_BASE + a.nbytes > TABLE:
        raise RuntimeError(f"the generated code ({a.nbytes} bytes) overlaps the probe table")
    return a


@pyuvm.test()
class sep_boot_rom_aperture_sweep_test(sep_base_test):
    """Boot ROM reads at every size, stores absorbed, no ECC, a reset in flight."""

    build_env = False
    required_evidence = (
        "CHK-ROM-SWEEP",
        "CHK-ROM-PORT",
        "CHK-ROM-STORE",
        "CHK-ROM-STORE-WE",
        "CHK-ROM-NOECC",
        "CHK-ROM-OTF",
    )

    # ---------------------------------------------------------------- helpers
    def _grade(self, chk: str, ok: bool, text: str) -> None:
        if ok:
            self.logger.info("%s PASS: %s", chk, text)
            self.n_checks += 1
        else:
            self.logger.error("%s FAIL: %s", chk, text)
            self.failures.append(f"{chk}: {text}")

    def _sram_mem(self):
        sram = cocotb.top.u_dut.u_sep_ip_integration.u_sep_sram
        try:
            return sram.gen_ram_inst[0].u_mem.mem
        except (IndexError, AttributeError):
            # VCS lists the instance as the child ``gen_ram_inst[0].u_mem``.
            return sram._id("gen_ram_inst[0].u_mem", extended=False).mem

    def _stage_sram(self, blobs: dict[int, bytes]) -> None:
        img: dict[int, bytearray] = {}
        for addr, data in blobs.items():
            for i, b in enumerate(data):
                widx, lane = divmod(addr + i - SRAM_BASE, 8)
                if not 0 <= widx < SRAM_WORDS:
                    raise ValueError(f"image byte 0x{addr + i:08x} is outside the SRAM")
                img.setdefault(widx, bytearray(8))[lane] = b
        mem = self._sram_mem()
        for widx, word in sorted(img.items()):
            mem[widx].value = int.from_bytes(bytes(word), "little")
        self.logger.info("STAGE sram words=%d", len(img))

    def _stage_rom(self) -> None:
        mem = cocotb.top.u_dut.u_sep_ip_integration.u_sep_boot_rom.mem
        for i, w in enumerate(self.plan.img.words):
            mem[i].value = w
        self.logger.info("STAGE rom words=%d", ROM_WORDS)

    def _period_ps(self) -> int:
        return int(round(self.cfg.sys_clk_period_ns * 1000))

    @staticmethod
    def _in(beats, t0: int, t1: int, ch: str | None = None) -> list:
        return [b for b in beats if t0 <= b.t_ps <= t1 and (ch is None or b.ch == ch)]

    def _marker_t(self, off: int) -> int:
        """Time of the AW handshake of a marker store on PR-LSU-XBAR."""
        hits = [
            b.t_ps
            for b in self.lsu_xbar.beats
            if b.ch == "aw" and b.addr is not None and (b.addr & ~7) == MBX + off
        ]
        if len(hits) != 1:
            raise AssertionError(f"marker +0x{off:x}: {len(hits)} AW handshakes on PR-LSU-XBAR")
        return hits[0]

    # ---------------------------------------------------------------- set-up
    def _draw(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        p = self.plan = _Plan(SepSeededRng(seed))
        digest = hashlib.sha256(b"".join(w.to_bytes(8, "little") for w in p.img.words))
        self.logger.info(
            "DRAW image sha256=%s word16=0x%016x word%d=0x%016x",
            digest.hexdigest()[:16],
            p.img.word(16),
            TOP_WORD,
            p.img.word(TOP_WORD),
        )
        self.logger.info(
            "DRAW probes seeded=%d sizes=%s seq_base=%d seq_size=%d seq_off=%d blocks=%d "
            "sram_ctl=0x%08x",
            N_SEEDED,
            "/".join(str(sum(1 for _a, s in p.seeded if s == z)) for z in SIZES),
            p.seq_base,
            p.seq_size,
            p.seq_off,
            N_BLOCKS,
            p.sram_ctl,
        )
        self.logger.info(
            "DRAW stores=%s",
            " ".join(f"0x{a:08x}/{s}/0x{d:x}" for a, s, d in p.stores),
        )
        self.logger.info("DRAW flips=%s", " ".join(f"{w}/0x{m:x}" for w, m in p.flips))
        self.logger.info("DRAW u_o=%d/65536", p.u)
        self.logger.info(
            "ENV rst_hold=%d romctl_bound=%d sweep_bound=%d store_bound=%d flip_poll=%d "
            "leg_bound=%d cpu_low_bound=%d release_bound=%d anchor_bound=%d "
            "first_req_bound=%d rsp_bound=%d",
            RST_HOLD,
            ROMCTL_BOUND,
            SWEEP_BOUND,
            STORE_BOUND,
            FLIP_POLL,
            LEG_BOUND,
            CPU_LOW_BOUND,
            RELEASE_BOUND,
            ANCHOR_BOUND,
            FIRST_REQ_BOUND,
            RSP_BOUND,
        )

    def _fuse_image(self) -> None:
        image = self.select_efuse_image()
        rom_ctl = image.field_int("ROM_CTL")
        if rom_ctl != 0:
            raise AssertionError(
                f"the staged fuse image holds ROM_CTL=0x{rom_ctl:x}; the run mode needs 0x0"
            )
        self.logger.info("CFG fuse image ROM_CTL=0x0 lc_raw=0x%x (real fuse sense)", image.lc_raw())
        self.write_efuse_image(image)

    async def _tap_default(self) -> None:
        """Reset the core TAP so the reset-vector TDR holds its default.

        The bench owns the TAP pins: ``jtag_trst_ni`` presents 1 and then 0, so
        the asynchronous TAP reset fires (a level that is low from time 0 has no
        falling edge), and it stays low for the rest of the leaf. The first fetch
        is then at the default vector, the boot ROM base (cpu.adoc, Reset Vector).
        """
        dut = cocotb.top
        for pin, val in (("jtag_tck_i", 0), ("jtag_tms_i", 1), ("jtag_tdi_i", 0)):
            self._set_pin(dut, pin, val)
        self._set_pin(dut, "jtag_trst_n_i", 1)
        self._set_pin(dut, "jtag_bench_own_i", 1)
        await Timer(1, units="ns")
        self._set_pin(dut, "jtag_trst_n_i", 0)
        await Timer(1, units="ns")
        self.logger.info("CFG core TAP reset by jtag_trst_ni 1->0; reset vector TDR at its default")

    # ---------------------------------------------------------------- scenario
    async def run_scenario(self) -> None:
        self.failures: list[str] = []
        self.n_checks = 0
        self._draw()
        self._fuse_image()
        p = self.plan
        code = build_code(p)
        table = b"".join(a.to_bytes(4, "little") + s.to_bytes(4, "little") for a, s in p.table())
        self.logger.info(
            "CFG code=0x%08x+%d table=0x%08x+%d loads=%d",
            FW_BASE,
            code.nbytes,
            TABLE,
            len(table),
            len(p.sweep()),
        )
        self.out = SepFabricTap("PR-OUT")
        self.rom = SepFabricTap("PR-ROM")
        self.macro = SepFabricTap("PR-ROM-MACRO")
        self.lsu_rom = SepFabricTap("PR-LSU-ROM")
        self.lsu_xbar = SepFabricTap("PR-LSU-XBAR")
        self.taps = (self.out, self.rom, self.macro, self.lsu_rom, self.lsu_xbar)
        self.mbx = SepMbxWords(self.out, MBX)

        async def _stage() -> None:
            await self._tap_default()
            self._stage_rom()
            self._stage_sram(
                {
                    FW_BASE: code.to_bytes(),
                    TABLE: table,
                    FLAG: bytes(8),
                    p.sram_ctl: p.sram_ctl_val.to_bytes(4, "little"),
                }
            )
            for t in self.taps:
                t.start()

        # Steps 1 to 3: stage, release, calibration boot.
        await self.bring_up_cpu_boot(0, pre_reset_hook=_stage)
        try:
            await self._legs()
        finally:
            close_graded_window(self.logger)
            for t in self.taps:
                await t.stop()
        if self.failures:
            raise AssertionError("; ".join(self.failures))
        self.result_pass(TEST, self.random_seed(), self.n_checks)

    async def _legs(self) -> None:
        p = self.plan
        mbx = self.mbx
        await self._calibrate()
        mrac = await mbx.wait(OFF_MRAC, ROMCTL_BOUND, what="mrac record")
        line = f"csr=0x{CSR_MRAC:03x} readback=0x{mrac.val:08x} crt0=0x{MRAC_SEP:08x}"
        if mrac.val != MRAC_SEP:
            self.logger.error("CTL-ROM-MRAC FAIL: %s", line)
            raise AssertionError(f"CTL-ROM-MRAC FAIL: {line}")
        self.logger.info("CTL-ROM-MRAC: %s", line)
        # Step 4.
        ctl = await mbx.wait(OFF_ROMCTL, ROMCTL_BOUND, what="ROM_CTL record")
        await self._check_fail()
        # Steps 6 to 11.
        await mbx.wait(OFF_SWEEP_B, SWEEP_BOUND, what="sweep begin")
        open_graded_window(TEST, self.logger)
        await mbx.wait(OFF_SWEEP_E, SWEEP_BOUND, what="sweep end")
        self._grade_sweep(ctl.val)
        self._grade_port()
        # Step 12.
        await mbx.wait(OFF_ST_B, LEG_BOUND, what="store begin")
        done = []
        for i in range(N_STORES):
            try:
                done.append(await mbx.wait(OFF_SDONE, STORE_BOUND, val=i, what=f"store {i}"))
            except AssertionError as exc:
                self._grade("CHK-ROM-STORE", False, f"store={i} {exc}")
                raise
        await mbx.wait(OFF_ST_E, LEG_BOUND, what="store end")
        self._grade_store()
        # Step 13.
        await mbx.wait(OFF_FLIP_READY, LEG_BOUND, what="FLIP_READY")
        for w, m in p.flips:
            await rom_flip(cocotb.top, w, m)
        self._sram_mem()[(FLAG - SRAM_BASE) // 8].value = 1
        self.logger.info("CTL-FLIP: %d flips applied, release flag set", len(p.flips))
        await mbx.wait(OFF_DONE, LEG_BOUND, what="done record")
        await self._check_fail()
        close_graded_window(self.logger)
        self._grade_noecc()
        # Step 14.
        await self._otf()

    async def _check_fail(self) -> None:
        f = self.mbx.find(OFF_FAIL)
        if f is not None:
            what = {FAIL_ROMCTL: "ROM_CTL not 0x0", FAIL_FLAG: "release flag timeout"}
            raise AssertionError(f"routine fail marker: {what.get(f.val, hex(f.val))}")

    # ---------------------------------------------------------------- step 3
    async def _calibrate(self) -> None:
        """W: clk_i cycles from the PR-ROM handshake of word 1 to its response beat."""
        for _ in range(ANCHOR_BOUND):
            req = next(
                (
                    b
                    for b in self.rom.beats
                    if b.ch == "req" and b.addr is not None and b.addr >> 3 == 1
                ),
                None,
            )
            rsp = None
            if req is not None:
                rsp = next((b for b in self.rom.beats if b.ch == "rsp" and b.t_ps > req.t_ps), None)
            if rsp is not None:
                break
            await RisingEdge(cocotb.top.clk_i)
        else:
            raise AssertionError("calibration: no PR-ROM fetch of word 1 with a response beat")
        self.W = round((rsp.t_ps - req.t_ps) / self._period_ps())
        self.cal_word1 = rsp.rdata
        if self.W < 1:
            raise AssertionError(f"calibration: W={self.W} cycles")
        self.o = (self.plan.u * self.W) >> 16
        self.logger.info(
            "CTL-ROM-OTF-CAL: word=1 W=%d cycles rsp=0x%016x image_word1=0x%016x u_o=%d/65536 o=%d",
            self.W,
            rsp.rdata if rsp.rdata is not None else 0,
            self.plan.img.word(1),
            self.plan.u,
            self.o,
        )

    # ---------------------------------------------------------------- grading
    def _sweep_records(self) -> list[tuple[int, int, int]]:
        """(addr, size, value) of each logged load of steps 7 to 11."""
        recs = [r for r in self.mbx.records() if r.off in (OFF_LA, OFF_LV)]
        out = []
        for k in range(0, len(recs) - 1, 2):
            la, lv = recs[k], recs[k + 1]
            if la.off != OFF_LA or lv.off != OFF_LV:
                raise AssertionError(f"load record {k // 2}: address and value out of order")
            out.append((ROM_BASE + (la.val & 0xFFFF), la.val >> 16, lv.val))
        return out

    def _grade_sweep(self, rom_ctl: int) -> None:
        p = self.plan
        plan = p.sweep()
        got = self._sweep_records()
        fc = field_compare(rom_ctl, 0, ROM_CTL_MASK)
        mismatches = []
        ok_cells: Counter = Counter()
        if len(got) != len(plan):
            mismatches.append(f"records={len(got)} expected={len(plan)}")
        for k, ((pa, ps, step), (ga, gs, gv)) in enumerate(zip(plan, got)):
            exp = p.img.read(pa, ps)
            if (ga, gs) != (pa, ps) or gv != exp:
                if len(mismatches) < 8:
                    mismatches.append(
                        f"#{k} {step} addr=0x{ga:08x}/{gs} plan=0x{pa:08x}/{ps} "
                        f"value=0x{gv:x} exp=0x{exp:x}"
                    )
                else:
                    mismatches.append("")
            elif step in ("top", "walk"):
                ok_cells[(pa - ROM_BASE) >> 3] += 1
        boundary = set(p.walk_words) | {TOP_WORD}
        boundary_ok = sum(1 for w in boundary if ok_cells[w] >= 14)
        drawn = {(a - ROM_BASE) >> 3 for a, _s, st in plan if st in ("seeded", "seq", "block")}
        by_size = [sum(1 for _a, s, _st in plan if s == z) for z in SIZES]
        ok = fc.ok and not mismatches and boundary_ok == len(boundary)
        self._grade(
            "CHK-ROM-SWEEP",
            ok,
            f"rom_ctl=0x{rom_ctl & ROM_CTL_MASK:x} probes={len(got)} sizes=1,2,4 "
            f"probes_by_size={by_size[0]}/{by_size[1]}/{by_size[2]} "
            f"boundary_words={boundary_ok}/{len(boundary)} drawn_words={len(drawn)} "
            f"mismatches={len(mismatches)} rom_ctl_{fc.fields().replace(' ', ' rom_ctl_')}"
            + ("" if not mismatches else " first=" + "; ".join(m for m in mismatches if m)),
        )

    def _grade_port(self) -> None:
        plan = self.plan.sweep()
        t0, t1 = self._marker_t(OFF_SWEEP_B), self._marker_t(OFF_SWEEP_E)
        exp = Counter((a - ROM_BASE) >> 3 for a, _s, _st in plan)
        lr = self._in(self.lsu_rom.beats, t0, t1)
        lr_ar = [b for b in lr if b.ch == "ar"]
        lr_aw = [b for b in lr if b.ch in ("aw", "w")]
        lr_words = Counter(None if b.addr is None else (b.addr - ROM_BASE) >> 3 for b in lr_ar)
        rq = self._in(self.rom.beats, t0, t1, "req")
        rq_words = Counter(None if b.addr is None else b.addr >> 3 for b in rq)
        we = sum(1 for b in rq if b.we != 0)
        xbar_rom = [
            b
            for b in self._in(self.lsu_xbar.beats, t0, t1)
            if b.ch in ("ar", "aw")
            and (b.addr is None or ROM_BASE <= b.addr < ROM_BASE + ROM_BYTES)
        ]
        word_ok = sum(min(lr_words[w], rq_words[w], n) for w, n in exp.items())
        # Control: the SRAM load of step 6.
        c0, c1 = self._marker_t(OFF_CTL_B), self._marker_t(OFF_CTL_E)
        sram_w = self.plan.sram_ctl & ~7
        ctl_xbar = sum(
            1
            for b in self._in(self.lsu_xbar.beats, c0, c1, "ar")
            if b.addr is not None and (b.addr & ~7) == sram_w
        )
        ctl_rom = len(self._in(self.lsu_rom.beats, c0, c1))
        ok = (
            lr_words == exp
            and rq_words == exp
            and we == 0
            and not lr_aw
            and not xbar_rom
            and ctl_xbar >= 1
            and ctl_rom == 0
        )
        text = (
            f"loads={len(plan)} lsu_rom_req={len(lr_ar)} rom_req={len(rq)} word_addr_ok={word_ok} "
            f"we_cycles={we} lsu_rom_writes={len(lr_aw)} lsu_xbar_rom_addr={len(xbar_rom)} "
            f"control_lsu_xbar={ctl_xbar} control_lsu_rom_for_sram={ctl_rom}"
        )
        if lr_words != exp:
            text += f" lsu_rom_diff={dict(list(((lr_words - exp) + (exp - lr_words)).items())[:6])}"
        if rq_words != exp:
            text += f" rom_req_diff={dict(list(((rq_words - exp) + (exp - rq_words)).items())[:6])}"
        self._grade("CHK-ROM-PORT", ok, text)

    def _grade_store(self) -> None:
        p = self.plan
        recs = self.mbx.records()
        b0 = self.mbx.find(OFF_ST_B)
        e0 = self.mbx.find(OFF_ST_E)
        seg = recs[b0.seq : e0.seq + 1]
        bad = []
        traps = 0
        # Each store: SB lo, SB hi, [TRAP/NMI...], SDONE i, SA lo, SA hi.
        idx = 0
        for i, (addr, s, data) in enumerate(p.stores):
            w = (addr - ROM_BASE) >> 3
            exp = p.img.word(w)
            while idx < len(seg) and seg[idx].off != OFF_SB:
                idx += 1
            before = [r.val for r in seg[idx : idx + 2]]
            j = idx + 2
            k_traps = 0
            while j < len(seg) and seg[j].off != OFF_SDONE:
                k_traps += seg[j].off in (OFF_TRAP, OFF_NMI)
                j += 1
            after = [r.val for r in seg[j + 1 : j + 3]]
            traps += k_traps
            got_b = before[0] | (before[1] << 32) if len(before) == 2 else None
            got_a = after[0] | (after[1] << 32) if len(after) == 2 else None
            sdone = seg[j].val if j < len(seg) else None
            if got_b != exp or got_a != exp or sdone != i:
                bad.append(
                    f"#{i} 0x{addr:08x}/{s} data=0x{data:x} word={w} exp=0x{exp:016x} "
                    f"before={'X' if got_b is None else hex(got_b)} "
                    f"after={'X' if got_a is None else hex(got_a)} done={sdone}"
                )
            idx = j + 3
        sizes = sorted({s for _a, s, _d in p.stores})
        self._grade(
            "CHK-ROM-STORE",
            not bad,
            f"n={N_STORES} sizes={','.join(map(str, sizes))} responses={N_STORES - len(bad)} "
            f"traps={traps} readback={'image' if not bad else 'mismatch'}"
            + ("" if not bad else " " + "; ".join(bad[:4])),
        )
        # CHK-ROM-STORE-WE: macro requests at the store words in the store leg.
        t0, t1 = self._marker_t(OFF_ST_B), self._marker_t(OFF_ST_E)
        exp_n = Counter((a - ROM_BASE) >> 3 for a, _s, _d in p.stores)
        exp_n = Counter({w: 4 * n for w, n in exp_n.items()})
        got_n = Counter(b.addr for b in self._in(self.macro.beats, t0, t1, "req"))
        extra = sum((got_n - exp_n).values())
        missing = sum((exp_n - got_n).values())
        matched = sum(min(got_n[w], n) for w, n in exp_n.items())
        rq_n = Counter(
            None if b.addr is None else b.addr >> 3 for b in self._in(self.rom.beats, t0, t1, "req")
        )
        self.logger.info(
            "OBS-ROM-STORE-WE LOG per_word(macro/rom_req/exp)=%s",
            " ".join(f"{w}:{got_n[w]}/{rq_n[w]}/{n}" for w, n in sorted(exp_n.items())),
        )
        self._grade(
            "CHK-ROM-STORE-WE",
            extra == 0 and missing == 0,
            f"stores={N_STORES} extra_macro_req={extra} control_readback_macro_req={matched} "
            f"expected_readback_macro_req={sum(exp_n.values())} missing={missing}",
        )

    def _grade_noecc(self) -> None:
        p = self.plan
        recs = self.mbx.records()
        tcnt = [r for r in recs if r.off == OFF_TCNT]
        if len(tcnt) != 3:
            self._grade("CHK-ROM-NOECC", False, f"trap-count records={len(tcnt)} expected 3")
            return
        c0, c1, c2 = (r.val for r in tcnt)
        seg = recs[tcnt[1].seq + 1 : tcnt[2].seq]
        nmi = sum(1 for r in seg if r.off in (OFF_NMI, OFF_TRAP))
        reads = []
        k = 0
        while k + 2 < len(seg):
            if seg[k].off == OFF_FA and seg[k + 1].off == OFF_FV and seg[k + 2].off == OFF_FV + 4:
                reads.append((seg[k].val, seg[k + 1].val | (seg[k + 2].val << 32)))
                k += 3
            else:
                k += 1
        flipped = dict(p.flips)
        bad = []
        neigh = 0
        n1 = n2 = 0
        exp_reads = [x for w, _m in p.flips for x in (w - 1, w, w + 1)]
        if [x for x, _v in reads] != exp_reads:
            bad.append(f"read order {len(reads)} records vs {len(exp_reads)} planned")
        for x, v in reads:
            exp = p.img.flipped(x, flipped[x]) if x in flipped else p.img.word(x)
            if v != exp:
                bad.append(f"word={x} got=0x{v:016x} exp=0x{exp:016x}")
            elif x in flipped:
                if bin(flipped[x]).count("1") == 1:
                    n1 += 1
                else:
                    n2 += 1
            else:
                neigh += 1
        ok = not bad and c1 - c0 == 1 and c2 - c1 == 0 and nmi == 0
        self._grade(
            "CHK-ROM-NOECC",
            ok,
            f"flips1={n1} flips2={n2} data={'stored' if not bad else 'mismatch'} "
            f"resp={'OKAY' if c2 == c1 and nmi == 0 else 'ERR'} traps={c2 - c1 + nmi} "
            f"neighbours_exact={neigh} control_ecall_traps={c1 - c0}"
            + ("" if not bad else " " + "; ".join(bad[:4])),
        )

    # ---------------------------------------------------------------- step 14
    async def _wait_level(self, sig, level: int, bound: int, what: str) -> int:
        dut = cocotb.top
        for _ in range(bound):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(sig) == level:
                return get_sim_time("ps")
        raise AssertionError(f"{what}: not {level} within {bound} clk_i cycles")

    async def _otf(self) -> None:
        dut = cocotb.top
        img = self.plan.img
        # Set-up reset (not graded).
        await RisingEdge(dut.clk_i)
        dut.rst_ni.value = 0
        await self._wait_level(dut.sep_cpu_reset_n_o, 0, CPU_LOW_BOUND, "setup reset")
        await ClockCycles(dut.clk_i, RST_HOLD)
        dut.rst_ni.value = 1
        # Anchor: the PR-ROM handshake of the stub fetch at word address 1.
        for _ in range(ANCHOR_BOUND):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if (
                self.rd(dut.pr_rom_req_o)
                and self.rd(dut.pr_rom_gnt_o)
                and self.rd(dut.pr_rom_addr_o) >> 3 == 1
            ):
                break
        else:
            raise AssertionError(f"CHK-ROM-OTF: no anchor fetch within {ANCHOR_BOUND} cycles")
        t_hs = get_sim_time("ps")
        for _ in range(self.o):
            await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        open_graded_window(TEST, self.logger)
        dut.rst_ni.value = 0
        t_fall = get_sim_time("ps")
        cpu_low = await self._wait_level(dut.sep_cpu_reset_n_o, 0, CPU_LOW_BOUND, "OTF reset")
        await ClockCycles(dut.clk_i, RST_HOLD)
        dut.rst_ni.value = 1
        t_rel = await self._wait_level(dut.sep_cpu_reset_n_o, 1, RELEASE_BOUND, "OTF release")
        first = None
        for _ in range(FIRST_REQ_BOUND):
            first = next((b for b in self.rom.beats if b.ch == "req" and b.t_ps >= t_rel), None)
            if first is not None:
                break
            await RisingEdge(dut.clk_i)
        rsp = None
        if first is not None:
            for _ in range(RSP_BOUND):
                rsp = next(
                    (b for b in self.rom.beats if b.ch == "rsp" and b.t_ps > first.t_ps), None
                )
                if rsp is not None:
                    break
                await RisingEdge(dut.clk_i)
        await ClockCycles(dut.clk_i, 2)
        close_graded_window(self.logger)
        period = self._period_ps()
        beats = self.rom.beats
        early_rsp = [b for b in beats if b.ch == "rsp" and t_hs < b.t_ps <= t_fall]
        # The word-1 fetch counts as in flight only when it reached the ROM macro
        # (PR-ROM-MACRO request at word 1) at or after the anchor and before the fall.
        macro_w1 = sum(
            1
            for b in self.macro.beats
            if b.ch == "req" and t_hs <= b.t_ps <= t_fall and b.addr == 1
        )
        midflight = int(t_fall < t_hs + self.W * period and not early_rsp and macro_w1 >= 1)
        t_first = first.t_ps if first is not None else None
        replay = (
            -1
            if first is None
            else sum(
                1
                for b in beats
                if b.ch == "req"
                and t_rel <= b.t_ps < t_first
                and b.addr is not None
                and b.addr >> 3 == 1
            )
        )
        before = (
            -1
            if first is None
            else sum(1 for b in beats if b.ch == "rsp" and t_rel <= b.t_ps < t_first)
        )
        pre_rel = [b for b in beats if t_fall < b.t_ps < t_rel]
        self.logger.info(
            "OBS-ROM-OTF LOG beats_between_fall_and_release=%d %s cpu_low_t=%d",
            len(pre_rel),
            " ".join(f"{b.ch}@{b.t_ps}" for b in pre_rel[:6]),
            cpu_low,
        )
        first_word = None if first is None or first.addr is None else first.addr >> 3
        ok = (
            midflight == 1
            and first_word == 0
            and replay == 0
            and before == 0
            and rsp is not None
            and rsp.rdata == img.word(0)
            and self.cal_word1 == img.word(1)
        )
        self._grade(
            "CHK-ROM-OTF",
            ok,
            f"offset={self.o}/{self.W} midflight={midflight} macro_req_word1={macro_w1} "
            f"first_req_word={first_word} "
            f"replay_word1={replay} beats_before_req={before} "
            f"first_rsp=0x{(rsp.rdata if rsp is not None and rsp.rdata is not None else 0):016x} "
            f"image_word0=0x{img.word(0):016x} control_cal_word1="
            f"0x{(self.cal_word1 or 0):016x}/0x{img.word(1):016x} "
            f"t_hs={t_hs} t_fall={t_fall} t_release={t_rel}",
        )
