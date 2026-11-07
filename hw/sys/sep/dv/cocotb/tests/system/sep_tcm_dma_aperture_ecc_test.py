# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ICCM and DCCM aperture reach and the DMA-path ECC response, through the secure DMA.

ICCM (256 KiB at 0xC000_0000) and DCCM (128 KiB at 0xC004_0000) hold 32-bit
words with 7 ECC bits and do not alias (``hw/sys/sep/doc/cpu.adoc``, Local
Memory; ``hw/sys/sep/regs/gen/adoc/memory_map.adoc``, ICCM and DCCM rows). On an
externally initiated (DMA-path) read, a single-bit error returns the corrected
data and a two-bit error returns an error response; the error is not a CPU trap
(``hw/sys/sep/doc/interrupts.adoc``, Memory ECC Errors). A non-OKAY response to a
DMA transfer sets ``DMA_BUS_ERR_STATUS.host_path_err``
(``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc``, ``DMA_BUS_ERR_STATUS``).

Run mode: RAND-REP, no_cpu, VCS only, on the full-CPU ``default`` target: the
CPU stub has no TCM controller. The core is held off and the CPU-LSU master
(``s_axi`` force-splice) drives the secure DMA registers and the SRAM staging
words. ``+sep_require_full_cpu`` makes a build without the full CPU fail the
leaf. ``+skip_fuse_sense``. No firmware runs. The secure DMA is the master of
every TCM access, one 4-byte transfer per word.

Checkers:
  CHK-TCM-APERT  every aperture word (first, last, each word-address bit, 64
                 drawn words of each memory; all written before the first read)
                 reads back its own data through the DMA. Control: each copy to
                 or from an ICCM word raises ``dbg_iccm_active_o``, and each copy
                 of a DCCM word raises ``dbg_dccm_active_o``; each readback
                 staging word holds the complement of the expected data before
                 its copy.
  CHK-TCM-CLEAN  ``DMA_BUS_ERR_STATUS`` reads its RDL reset value at the start,
                 and every read with no flip returns the written data with
                 ``host_path_err`` at 0 and no DMA error. Control: CHK-TCM-DBE
                 sets ``host_path_err`` in the same leaf.
  CHK-TCM-SBE    for each memory and each stored bit 0 to 38, a DMA read of the
                 flipped word returns the written data. Control: the stored word
                 on the PR-TCM response differs from the written word (PR-TCM
                 request) in bit k only.
  CHK-TCM-SBE-WB after each CHK-TCM-SBE read, the PR-TCM tap shows a write of
                 the flipped word whose 39-bit word (data and ECC bits) equals
                 the word of the original write
                 (VeeR EL2 PRM at tt-Cores-VeeR-EL2@07a51d817,
                 ``docs/source/memory-map.md``, "Correctable Ecc/Parity Errors"
                 ``:638-639`` ICCM, ``:646-647`` DCCM: a DMA read error is
                 corrected in line and
                 the corrected data is written back). No write, or another
                 data or ECC value, fails.
  CHK-TCM-DBE    for 16 drawn bit pairs of each memory (at least 4 each of
                 data-data, data-ECC and ECC-ECC), the read of the flipped word
                 is one AR at its 8-byte word on PR-XBAR-TCM, every R beat with
                 the ID of that AR answers SLVERR or DECERR, the DMA transfer
                 ends with STATUS.error at 1, and ``host_path_err`` is set.
                 No text states STATUS.done on an error, so done is logged
                 (OBS-TCM-DBE-DONE) and not graded. Control: the clean read of the same
                 word is one AR on PR-XBAR-TCM answered OKAY, the flag reads 0
                 after the clear and after that clean read, and the stored word
                 differs from the written word in the two flipped bits.
  CHK-TCM-DMA-DBG    the OR of ``ext_debug_bus_o[367:364]`` over every clock of
                 each DMA read copy (clean, single-bit and double-bit flip, and
                 the aperture reads) equals the lane of the error the read
                 meets: none 0b0000, ICCM single 0b1000, ICCM double 0b0100,
                 DCCM single 0b0010, DCCM double 0b0001
                 (``hw/sys/sep/doc/interrupts.adoc:413-415``: the ICCM and DCCM
                 single- and double-bit error signals are mirrored there, most
                 significant first; the DMA-path errors of ``:401-403`` are in
                 the same section). An X or Z sample of the nibble fails. The
                 core is held off, so no CPU access drives the lanes. Control:
                 CHK-TCM-SBE and CHK-TCM-DBE show the stored bits flipped.
  CHK-TCM-SUBWORD-WR a 1- or 2-byte DMA copy into one drawn word of each
                 memory ends with STATUS.error at 1, the BUS_ERROR bit of
                 ERROR_CODE set and ``host_path_err`` set
                 (``hw/sys/sep/doc/dma.adoc:118-121``: ICCM and DCCM take only
                 whole 32-bit words from the DMA, any other write ends in
                 BUS_ERROR and sets the host-path fault; ``:95-96``: error
                 reporting is the same for a copy; VeeR EL2 PRM at
                 tt-Cores-VeeR-EL2@07a51d817, ``docs/source/memory-map.md``,
                 "Write Alignment Rules" ``:1203-1204`` and "Misaligned
                 Accesses" ``:422-427``). The spec states no other bit of
                 ERROR_CODE, so the whole code is logged (OBS-TCM-SUBWORD-CODE)
                 and not graded. Control: the ICCM and DCCM copies are both
                 graded (count 2), and before each GO, after the STATUS and
                 ``DMA_BUS_ERR_CLEAR`` clears, ERROR_CODE and
                 ``DMA_BUS_ERR_STATUS`` read 0 (CTRL-TCM-SUBWORD-PRE; ERROR_CODE
                 "is cleared by writing the RW1C STATUS.error register",
                 ``vendor/lowRISC/opentitan/upstream/hw/ip/dma/data/
                 dma.hjson:669-670``; the faults are "cleared through
                 ``DMA_BUS_ERR_CLEAR``", ``hw/sys/sep/doc/dma.adoc:66-68``), so
                 a stale code or flag cannot pass the check.
  CHK-TCM-DMA-T2T one multi-word DMA copy ICCM -> DCCM and one DCCM -> ICCM
                 (4 to 16 words, 4-byte width, one chunk, 8-byte aligned)
                 end with DONE at 1, ERROR at 0 and ``host_path_err`` at 0, and
                 each destination word, read back by a DMA copy to an SRAM
                 staging word that holds its complement, equals its source
                 word (``hw/sys/sep/doc/dma.adoc:58-59``: the TCM backdoor
                 range is available to the DMA; ``:118-121``: whole 32-bit
                 words; ``hw/sys/sep/doc/cpu.adoc:46-47``). The source words
                 are written by single-word DMA copies from the SRAM. Control:
                 both ``dbg_iccm_active_o`` and ``dbg_dccm_active_o`` rise
                 during each copy.
  CHK-TCM-ABORT-RECOVER  CONTROL.ABORT written while a 32- to 64-word copy from
                 the SRAM to the DCCM runs sets STATUS.ABORTED; after the STATUS
                 clear, a full copy of new words to the same DCCM words ends with
                 DONE at 1, ERROR at 0, ERROR_CODE at 0 and ``host_path_err``
                 at 0, and every DCCM word reads back its new source word
                 (``secure_dma.adoc``, CONTROL.ABORT and STATUS.ABORTED;
                 ``doc/programmer/src/sep-programming.adoc:805-806``). Control:
                 ABORTED reads 0 before the GO, and the PR-TCM tap shows at
                 least one DCCM write and fewer DCCM writes than the copy has
                 words when the ABORT write returns, so the copy runs at the
                 abort.
Observations (not graded): OBS-DMA-TCM-SEAM (STATUS, ERROR_CODE,
``DMA_BUS_ERR_STATUS`` and the four words read back after a 16-byte copy from
the SRAM to the two last ICCM words and the two first DCCM words; no text
states a DMA transfer across the ICCM end; the four words hold known values
before the copy; CTRL-TCM-SEAM-ADJ requires the ICCM end to equal the DCCM
base), OBS-TCM-EXCL (whether the other memory's clock-enable
tap rose), OBS-TCM-SBE-STATUS (``DMA_BUS_ERR_STATUS`` after a corrected read),
OBS-TCM-SUBWORD-CODE (the whole ERROR_CODE after the sub-word copy into a word,
and its bits other than BUS_ERROR), OBS-TCM-DBE-DONE (STATUS.done and
STATUS.error after each double-bit read),
OBS-TCM-SUBWORD (done, staging word and the word read back after the 1- or
2-byte copy into one drawn word of each memory, and every field of the copy out
of it; the word is not a flip target of the single- or double-bit legs, so it
holds a clean code word; it runs after CHK-TCM-CLEAN).

Bench: the TCM bit-flip hook (error inject, ``env/sep_tcm_flip.py``) XORs a mask
into the stored 39-bit word (bits 31:0 data, 38:32 ECC). Flips land only on
aperture words this leaf wrote. Before the first DMA access the leaf loads an
all-zero image through ``tcm_load_i``, so every TCM word holds a valid code word
and a DMA read of a bank pair never meets an unwritten neighbour. The leaf logs and
checks that the core reset (``core_rst_l``, which the debug module's
``dmcontrol`` gates) and the reset vector are known after bring-up. The PR-TCM
tap (``env/sep_fabric_tap.py``, read per bank with ``TapBeat.lane``) packs the
banks with bank 0 in the low bits: ICCM bank ``off[3:2]``, row
``off[17:4]``; DCCM bank ``off[2]``, row ``off[16:3]`` (the bank map of
``tb/tb_top.sv``, ``tb_backdoor_mem``). The PR-XBAR-TCM tap
(``env/sep_fabric_tap.py``) is the local crossbar ``cpu_tcm`` target, the DMA
path into the core DMA slave port: the AXI read response of each TCM read.

The graded window (owner code of this test) is open around the aperture copies
and around each flip and its read. Set-up, clears, writes before a flip and the
clean control reads run with the window closed.
"""

from __future__ import annotations

import os

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from env.sep_tcm_flip import DATA_BITS, WORD_BITS, bit_mask, tcm_flip
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL, sym
from seq_lib.sep_dma_ops import _D, SepDmaOps, SepMemWords
from seq_lib.sep_irq_aggregator_seq import DMA_CLEAR_ADDR, DMA_HOST_PATH_BIT, DMA_STATUS_ADDR

TEST = "sep_tcm_dma_aperture_ecc_test"
M32 = 0xFFFF_FFFF

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
# SRAM staging: the source words of the aperture writes, the source word of the
# flip legs, and the readback words.
SRC_STAGE = SRAM_BASE + 0x0_8000
FLIP_STAGE = SRAM_BASE + 0x0_9000
RB_STAGE = SRAM_BASE + 0x1_0000
# Source and readback words of the logged sub-word copies.
SUB_STAGE = SRAM_BASE + 0x0_A000
# Source words of the TCM-to-TCM, seam and abort legs, and their readback words.
T2T_STAGE = SRAM_BASE + 0x0_B000
SEAM_STAGE = SRAM_BASE + 0x0_B100
ABORT_STAGE = SRAM_BASE + 0x0_C000
RECOVER_STAGE = SRAM_BASE + 0x0_C100
MW_RB_STAGE = SRAM_BASE + 0x1_C000

MEMS = {
    "ICCM": (sym("SEP_ICCM_MEM_BASE_ADDR"), sym("SEP_ICCM_MEM_SIZE")),
    "DCCM": (sym("SEP_DCCM_MEM_BASE_ADDR"), sym("SEP_DCCM_MEM_SIZE")),
}
N_DRAWN = 64
N_PAIRS = 16
PAIR_MIN_PER_CLASS = 4
ECC_LO = DATA_BITS  # stored bits 32..38 are ECC
CLASSES = ("data-data", "data-ECC", "ECC-ECC")

DMA_STATUS_MASK = SEP_CPU_CTRL.mask32("DMA_BUS_ERR_STATUS")
DMA_STATUS_RESET = SEP_CPU_CTRL.reset("DMA_BUS_ERR_STATUS") & DMA_STATUS_MASK
DMA_CLR = SEP_CPU_CTRL.field_mask("DMA_BUS_ERR_CLEAR", "clr")
EC_MASK = _D.mask32("ERROR_CODE")
EC_BUS_ERROR = _D.field_mask("ERROR_CODE", "bus_error")
RANGE_REGS = (
    ("ENABLED_MEMORY_RANGE_BASE", 0x0),
    ("ENABLED_MEMORY_RANGE_LIMIT", 0xFFFF_FFFF),
    ("RANGE_VALID", 0x1),
)
WIDTH_ENC = 2  # TRANSFER_WIDTH: 4-byte beats
WORD_BYTES = 4
DBG_HI, DBG_LO = 367, 364
# ext_debug_bus_o[367:364] lanes: ICCM single, ICCM double, DCCM single, DCCM double.
DBG_WANT = {
    ("ICCM", "single"): 0b1000,
    ("ICCM", "double"): 0b0100,
    ("DCCM", "single"): 0b0010,
    ("DCCM", "double"): 0b0001,
}
T2T_PAIRS = (2, 8)  # TCM-to-TCM copy: 4 to 16 words, in 8-byte pairs
ABORT_PAIRS = (16, 32)  # aborted copy: 32 to 64 words, in 8-byte pairs
ABORT_WAIT = 2_000  # clk_i cycles from GO to the first DCCM write of the aborted copy
ROW_BITS = 14
ROW_MASK = (1 << ROW_BITS) - 1
RESP_OKAY = 0
RESP_ERR = (2, 3)  # SLVERR, DECERR


def bank_row(mem: str, addr: int) -> tuple[int, int]:
    """PR-TCM bank and row of a TCM byte address (bench table, tb_backdoor_mem)."""
    off = addr - MEMS[mem][0]
    if mem == "ICCM":
        return (off >> 2) & 0x3, (off >> 4) & ROW_MASK
    return (off >> 2) & 0x1, (off >> 3) & ROW_MASK


def pair_class(a: int, b: int) -> str:
    n = (a >= ECC_LO) + (b >= ECC_LO)
    return CLASSES[n]


class _Cfg:
    """Seed-drawn configuration of the leaf (single source of truth)."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        used: set[int] = set()

        def uniq32() -> int:
            while True:
                v = rng.getrandbits(32)
                if v and v not in used:
                    used.add(v)
                    return v

        self.apert: dict[str, list[tuple[int, int]]] = {}
        for mem, (base, size) in MEMS.items():
            n_words = size // WORD_BYTES
            bits = n_words.bit_length() - 1
            idx = [0, n_words - 1] + [1 << k for k in range(bits)]
            pool = set(idx)
            while len(idx) < 2 + bits + N_DRAWN:
                i = rng.randrange(n_words)
                if i not in pool:
                    pool.add(i)
                    idx.append(i)
            self.apert[mem] = [(base + WORD_BYTES * i, uniq32()) for i in idx]
        self.bits = {mem: (size // WORD_BYTES).bit_length() - 1 for mem, (_, size) in MEMS.items()}

        # Single-bit legs: every position 0..38 for each memory, drawn order.
        self.sbe: list[tuple[str, int, int, int]] = []
        for mem in MEMS:
            ks = list(range(WORD_BITS))
            rng.shuffle(ks)
            for k in ks:
                addr = rng.choice(self.apert[mem])[0]
                self.sbe.append((mem, k, addr, uniq32()))

        # Double-bit legs: 16 pairs per memory, at least 4 of each class.
        data_bits = list(range(ECC_LO))
        ecc_bits = list(range(ECC_LO, WORD_BITS))
        self.dbe: list[tuple[str, int, int, int, int]] = []
        for mem in MEMS:
            pairs: list[tuple[int, int]] = []

            def draw(cls: str) -> tuple[int, int]:
                if cls == "data-data":
                    a, b = rng.sample(data_bits, 2)
                elif cls == "data-ECC":
                    a, b = rng.choice(data_bits), rng.choice(ecc_bits)
                else:
                    a, b = rng.sample(ecc_bits, 2)
                return (min(a, b), max(a, b))

            plan = [c for c in CLASSES for _ in range(PAIR_MIN_PER_CLASS)]
            plan += [rng.choice(CLASSES) for _ in range(N_PAIRS - len(plan))]
            for cls in plan:
                while True:
                    p = draw(cls)
                    if p not in pairs:
                        pairs.append(p)
                        break
            rng.shuffle(pairs)
            for a, b in pairs:
                addr = rng.choice(self.apert[mem])[0]
                self.dbe.append((mem, a, b, addr, uniq32()))

        # Sub-word copies (logged): per memory a word that no flip leg targets,
        # a width (1 or 2 bytes) and a width-aligned byte offset in the word.
        flipped = {a for _, _, a, _ in self.sbe} | {a for *_, a, _ in self.dbe}
        self.sub: dict[str, tuple[int, int, int, int]] = {}
        for mem in MEMS:
            enc = rng.randrange(2)
            nbytes = 1 << enc
            off = nbytes * rng.randrange(WORD_BYTES // nbytes)
            clean = [a for a, _ in self.apert[mem] if a not in flipped]
            assert clean, f"every {mem} aperture word is a flip target"
            self.sub[mem] = (rng.choice(clean), enc, off, uniq32())

        # TCM-to-TCM copies: one block per direction, 8-byte aligned, the ICCM
        # source and destination in different halves and both DCCM blocks
        # clear of the first DCCM pair at the seam.
        iccm_sz, dccm_sz = MEMS["ICCM"][1], MEMS["DCCM"][1]
        self.t2t_words = 2 * rng.randrange(T2T_PAIRS[0], T2T_PAIRS[1] + 1)

        def block(lo: int, hi: int, n_words: int) -> int:
            return 8 * rng.randrange(lo // 8, (hi - WORD_BYTES * n_words) // 8 + 1)

        self.t2t = [
            (
                ("ICCM", MEMS["ICCM"][0] + block(0, iccm_sz // 2, self.t2t_words)),
                ("DCCM", MEMS["DCCM"][0] + block(0x40, dccm_sz // 2, self.t2t_words)),
            ),
            (
                ("DCCM", MEMS["DCCM"][0] + block(dccm_sz // 2, dccm_sz, self.t2t_words)),
                ("ICCM", MEMS["ICCM"][0] + block(iccm_sz // 2, iccm_sz - 0x40, self.t2t_words)),
            ),
        ]
        self.t2t_data = [[uniq32() for _ in range(self.t2t_words)] for _ in self.t2t]
        # Seam copy: the words before it and the words it writes.
        self.seam_before = [uniq32() for _ in range(4)]
        self.seam_data = [uniq32() for _ in range(4)]
        # Aborted copy into the DCCM and its recovery copy.
        self.abort_words = 2 * rng.randrange(ABORT_PAIRS[0], ABORT_PAIRS[1] + 1)
        self.abort_dst = MEMS["DCCM"][0] + block(0x40, dccm_sz, self.abort_words)
        self.abort_data = [uniq32() for _ in range(self.abort_words)]
        self.recover_data = [uniq32() for _ in range(self.abort_words)]

    def draw_lines(self) -> list[str]:
        out = []
        for mem, rows in self.apert.items():
            out.append(
                f"apert_{mem} words={len(rows)} bits={self.bits[mem]} drawn="
                + ",".join(f"0x{a:08x}" for a, _ in rows[2 + self.bits[mem] :])
            )
        out.append("sbe=" + " ".join(f"{m}/k={k}/@0x{a:08x}" for m, k, a, _ in self.sbe))
        out.append(
            "sub=" + " ".join(f"{m}/enc={e}/@0x{a + o:08x}" for m, (a, e, o, _) in self.sub.items())
        )
        out.append(
            "dbe="
            + " ".join(
                f"{m}/{a},{b}/{pair_class(a, b)}/@0x{addr:08x}" for m, a, b, addr, _ in self.dbe
            )
        )
        out.append(
            f"t2t words={self.t2t_words} "
            + " ".join(f"{sm}@0x{sa:08x}->{dm}@0x{da:08x}" for (sm, sa), (dm, da) in self.t2t)
        )
        out.append(f"abort words={self.abort_words} dst=0x{self.abort_dst:08x}")
        return out


class _TapSampler:
    """Per-clock sampler of the TCM clock-enable taps and the debug-bus nibble.

    ``arm`` opens a window; ``take`` closes it and returns whether each tap rose
    (a 0 to 1 change inside the window) and the OR of the nibble samples, or
    None when a nibble sample was X or Z.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.task = None
        self._reset()

    def _reset(self) -> None:
        self.rose = {"ICCM": False, "DCCM": False}
        self.prev = {"ICCM": None, "DCCM": None}
        self.nibble = 0
        self.nibble_x = False
        self.armed = False

    @staticmethod
    def _bit(sig) -> int | None:
        v = sig.value
        return int(v) if v.is_resolvable else None

    async def _run(self) -> None:
        while True:
            await RisingEdge(self.dut.clk_i)
            await ReadOnly()
            if not self.armed:
                continue
            for mem, sig in (
                ("ICCM", self.dut.dbg_iccm_active_o),
                ("DCCM", self.dut.dbg_dccm_active_o),
            ):
                v = self._bit(sig)
                if v == 1 and self.prev[mem] == 0:
                    self.rose[mem] = True
                self.prev[mem] = v
            bus = self.dut.ext_debug_bus_o.value
            s = str(bus)
            nib = s[len(s) - 1 - DBG_HI : len(s) - DBG_LO]
            if all(c in "01" for c in nib):
                self.nibble |= int(nib, 2)
            else:
                self.nibble_x = True

    def start(self) -> None:
        self.task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self.task is not None:
            self.task.kill()
            self.task = None

    def arm(self) -> None:
        self._reset()
        self.prev = {
            "ICCM": self._bit(self.dut.dbg_iccm_active_o),
            "DCCM": self._bit(self.dut.dbg_dccm_active_o),
        }
        self.armed = True

    def take(self) -> tuple[dict[str, bool], int | None]:
        """Close the window; raises if the sampler task ended while it was open."""
        self.armed = False
        if self.task is None or self.task.done():
            raise AssertionError("MONITOR-LIFE FAIL: TCM clock-enable sampler task is not running")
        return dict(self.rose), None if self.nibble_x else self.nibble


@pyuvm.test()
class sep_tcm_dma_aperture_ecc_test(sep_base_test):
    """DMA-path TCM aperture reach and ECC response."""

    required_evidence = (
        "CHK-TCM-APERT",
        "CHK-TCM-CLEAN",
        "CHK-TCM-SBE",
        "CHK-TCM-SBE-WB",
        "CHK-TCM-SUBWORD-WR",
        "CHK-TCM-DBE",
        "CHK-TCM-DMA-DBG",
        "CHK-TCM-DMA-T2T",
        "CHK-TCM-ABORT-RECOVER",
    )

    # ---- primitives --------------------------------------------------------------
    async def _bus_err(self) -> int:
        return await self.dma.rd(DMA_STATUS_ADDR) & DMA_STATUS_MASK

    async def _clear_bus_err(self) -> int:
        await self.dma.wr(DMA_CLEAR_ADDR, DMA_CLR)
        return await self._bus_err()

    async def _copy(self, src: int, dst: int, what: str):
        """One 4-byte secure DMA copy; returns (STATUS, taps, debug nibble)."""
        await self.dma.clean_state()
        await self.dma.program_transfer(
            src=src,
            dst=dst,
            total=WORD_BYTES,
            chunk=WORD_BYTES,
            width_enc=WIDTH_ENC,
            order=("SRC_ADDR_LO", "DST_ADDR_LO"),
        )
        self.sampler.arm()
        await self.dma.go()
        st = await self.dma.poll_status(
            lambda s: bool(s.done or s.error), self.dma.done_bound(WORD_BYTES), what
        )
        await ClockCycles(cocotb.top.clk_i, 2)
        rose, nib = self.sampler.take()
        self.n_copies += 1
        return st, rose, nib

    async def _write_tcm(self, mem: str, addr: int, data: int, src: int, what: str):
        """Stage ``data`` in SRAM and copy it to ``addr``; returns (rose, PR-TCM write word)."""
        await self.mem.fill(src, [data])
        mark = self.tcm_tap.mark()
        st, rose, _ = await self._copy(src, addr, what)
        if st.error or not st.done:
            raise AssertionError(f"{what}: DMA write to 0x{addr:08x} ended {st.fmt()}")
        return rose, self._written_word(mem, addr, mark)

    async def _read_tcm(self, mem: str, addr: int, expect: int, rb: int, what: str):
        """Copy ``addr`` to the readback word that holds ``~expect``; read the word back.

        Returns (STATUS, staging before, staging after, taps, nibble, PR-TCM mark).
        """
        comp = ~expect & M32
        await self.mem.fill(rb, [comp])
        before = (await self.mem.read(rb, 1))[0]
        if before != comp:
            raise AssertionError(
                f"{what}: readback word 0x{rb:08x} reads 0x{before:08x} after a write of the "
                f"complement 0x{comp:08x}"
            )
        mark = self.tcm_tap.mark()
        st, rose, nib = await self._copy(addr, rb, what)
        after = (await self.mem.read(rb, 1))[0]
        return st, before, after, rose, nib, mark

    def _written_word(self, mem: str, addr: int, mark) -> int | None:
        """39-bit word (data | ECC << 32) of the last PR-TCM write at ``addr`` since ``mark``."""
        bank, row = bank_row(mem, addr)
        hit = None
        for b in self.tcm_tap.since(mark, mem.lower()):
            if (
                b.lane("clken", bank, 1) == 1
                and b.lane("wren", bank, 1) == 1
                and b.lane("addr", bank, ROW_BITS) == row
            ):
                hit = b
        if hit is None:
            return None
        data, ecc = hit.lane("wdata", bank, 32), hit.lane("wecc", bank, 7)
        return None if data is None or ecc is None else data | (ecc << 32)

    def _stored_word(self, mem: str, addr: int, mark) -> int | None:
        """39-bit stored word on the PR-TCM response of the first read of ``addr`` since ``mark``.

        The response beat is the clock after the request beat; only the lane
        of the bank the request read is used.
        """
        bank, row = bank_row(mem, addr)
        ch = mem.lower()
        beats = self.tcm_tap.since(mark)
        for i, b in enumerate(beats):
            if b.ch != ch:
                continue
            if not (
                b.lane("clken", bank, 1) == 1
                and b.lane("wren", bank, 1) == 0
                and b.lane("addr", bank, ROW_BITS) == row
            ):
                continue
            for r in beats[i + 1 :]:
                if r.ch == f"{ch}_rsp":
                    data, ecc = r.lane("rdata", bank, 32), r.lane("recc", bank, 7)
                    return None if data is None or ecc is None else data | (ecc << 32)
            return None
        return None

    def _xbar_read(self, addr: int, mark) -> tuple[list[int | None], str]:
        """R responses of the one PR-XBAR-TCM read of ``addr`` since ``mark``.

        Returns ([], why) unless exactly one AR shows, at the 8-byte word of
        ``addr``; else the RRESP of every R beat with the ID of that AR.
        """
        ars = self.xbar_tap.since(mark, "ar")
        desc = "ar=" + ",".join(b.fmt() for b in ars)
        if len(ars) != 1 or ars[0].addr is None or (ars[0].addr & ~7) != (addr & ~7):
            return [], desc
        rs = [b for b in self.xbar_tap.since(mark, "r") if b.id == ars[0].id]
        desc += " r=" + ",".join(b.fmt() for b in rs)
        if not rs or rs[-1].last != 1:
            return [], desc
        return [b.resp for b in rs], desc

    def _chk_dbg(self, mem: str, kind: str, nib: int | None) -> None:
        """CHK-TCM-DMA-DBG: the debug-bus nibble of one DMA read against the error it meets."""
        want = DBG_WANT.get((mem, kind), 0)
        got = "X" if nib is None else format(nib, "04b")
        line = f"mem={mem} kind={kind} bus367_364=0b{got} want=0b{want:04b}"
        if nib != want:
            self._fail("CHK-TCM-DMA-DBG", line)
        self.logger.info("CHK-TCM-DMA-DBG PASS: %s", line)
        self.n_checks += 1

    def _missing(self, chk: str, line: str) -> None:
        msg = f"CTRL-MISSING {chk}: {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL: {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    # ---- steps 1 and 2 -------------------------------------------------------------
    async def _setup(self) -> None:
        top = cocotb.top
        # The no_cpu bring-up pulses dbg_rstb_i with the cold reset and tb_top
        # gives the core TAP a TRST edge, so the held core leaves reset with a
        # known state; the leaf logs that state.
        w = top.u_dut.u_sep.u_sep_cpu.u_el2_veer_wrapper
        state = {
            "core_rst_l": str(w.veer.core_rst_l.value),
            "dbg_core_rst_l": str(w.veer.dbg_core_rst_l.value),
            "rst_vec": str(w.veer.rst_vec.value),
        }
        self.logger.info("CTRL-TCM-RESET: core reset state after bring-up %s", state)
        if any(c not in "01" for v in state.values() for c in v):
            raise AssertionError(f"CTRL-TCM-RESET FAIL: core reset state not known {state}")
        # All-zero TCM image: every word a valid code word (tb_backdoor_mem).
        for name in ("sep_itcm.hex", "sep_dtcm.hex"):
            with open(os.path.join(os.getcwd(), name), "w") as fh:
                fh.write("@0\n00\n")
        top.tcm_load_i.value = 1
        await ClockCycles(top.clk_i, 4)
        top.tcm_load_i.value = 0
        await ClockCycles(top.clk_i, 4)
        self.logger.info("INFO-TCM-INIT: all-zero ICCM and DCCM image loaded through tcm_load_i")

        first = await self._bus_err()
        fc = field_compare(first, DMA_STATUS_RESET, DMA_STATUS_MASK)
        self.clean_start = fc
        if not fc.ok:
            self._fail("CHK-TCM-CLEAN", f"DMA_BUS_ERR_STATUS at the start {fc.fields()}")
        await self.dma.program_range(0x0, 0xFFFF_FFFF, valid=True)
        parts = []
        for name, want in RANGE_REGS:
            got = await self.dma.rd(_D.addr(name))
            fc = field_compare(got, want, _D.mask32(name))
            parts.append(f"{name}: {fc.fields()}")
            if not fc.ok:
                raise AssertionError(f"CTRL-TCM-RANGE FAIL: {name} readback {fc.fields()}")
        self.logger.info("CTRL-TCM-RANGE: %s", " | ".join(parts))
        await self._word_xfer()

    async def _word_xfer(self) -> None:
        """Program and read back the one-word transfer that ``_copy`` relies on."""
        written = await self.dma.program_transfer(
            src=SRC_STAGE, dst=RB_STAGE, total=WORD_BYTES, chunk=WORD_BYTES, width_enc=WIDTH_ENC
        )
        for name, val in written.items():
            got = await self.dma.rd(_D.addr(name))
            fc = field_compare(got, val, _D.mask32(name))
            if not fc.ok:
                raise AssertionError(f"CTRL-TCM-XFER FAIL: {name} readback {fc.fields()}")
        self.logger.info(
            "CTRL-TCM-XFER: transfer registers read back %s",
            " ".join(f"{n}=0x{v:x}" for n, v in written.items()),
        )

    # ---- steps 3 to 6: aperture ---------------------------------------------------
    async def _aperture(self) -> None:
        c = self.plan
        rows = [(mem, a, d) for mem in MEMS for a, d in c.apert[mem]]
        await self.mem.fill(SRC_STAGE, [d for _, _, d in rows])
        open_graded_window(TEST, self.logger)
        miss_tap: list[str] = []
        other = {"ICCM": False, "DCCM": False}
        for j, (mem, addr, data) in enumerate(rows):
            try:
                st, rose, _ = await self._copy(SRC_STAGE + 4 * j, addr, f"apert write {mem}")
            except AssertionError as exc:
                self._fail("CHK-TCM-APERT", f"write copy to 0x{addr:08x}: {exc}")
            if st.error or not st.done:
                self._fail("CHK-TCM-APERT", f"write copy to 0x{addr:08x} ended {st.fmt()}")
            if not rose[mem]:
                miss_tap.append(f"write {mem} 0x{addr:08x}")
            other[mem] |= rose["DCCM" if mem == "ICCM" else "ICCM"]
        aliases: list[str] = []
        clean_bad: list[str] = []
        per_mem = {m: 0 for m in MEMS}
        for j, (mem, addr, data) in enumerate(rows):
            rb = RB_STAGE + 4 * j
            try:
                st, before, got, rose, nib, _ = await self._read_tcm(
                    mem, addr, data, rb, f"apert read {mem}"
                )
            except AssertionError as exc:
                self._fail("CHK-TCM-APERT", f"read copy of 0x{addr:08x}: {exc}")
            berr = await self._bus_err()
            self._chk_dbg(mem, "none", nib)
            if not rose[mem]:
                miss_tap.append(f"read {mem} 0x{addr:08x}")
            other[mem] |= rose["DCCM" if mem == "ICCM" else "ICCM"]
            if got != data:
                aliases.append(
                    f"{mem} 0x{addr:08x} read 0x{got:08x} expected 0x{data:08x} "
                    f"(staging before 0x{before:08x})"
                )
            else:
                per_mem[mem] += 1
            self.n_clean_reads += 1
            if berr & DMA_HOST_PATH_BIT or st.error or got != data:
                clean_bad.append(
                    f"{mem} 0x{addr:08x} host_path_err={int(bool(berr & DMA_HOST_PATH_BIT))} "
                    f"{st.fmt()} data_match={int(got == data)}"
                )
        close_graded_window(self.logger)
        for mem in MEMS:
            self.logger.info("OBS-TCM-EXCL: mem=%s other_tap_rose=%d", mem, int(other[mem]))
        line = (
            f"iccm_words={per_mem['ICCM']} dccm_words={per_mem['DCCM']} aliases={len(aliases)} "
            f"control_each_tap_rose={int(not miss_tap)} copies={2 * len(rows)}"
        )
        if aliases or miss_tap:
            self._fail("CHK-TCM-APERT", f"{line} first: {(aliases + miss_tap)[:4]}")
        self.logger.info("CHK-TCM-APERT PASS: %s", line)
        self.n_checks += 1
        self.clean_bad += clean_bad

    # ---- step 7: single-bit flips ---------------------------------------------------
    async def _sbe(self, mem: str, k: int, addr: int, data: int, j: int) -> None:
        tag = f"SBE {mem} k={k} @0x{addr:08x}"
        flag = await self._clear_bus_err()
        if flag & DMA_HOST_PATH_BIT:
            self._fail("CHK-TCM-SBE", f"{tag} DMA_BUS_ERR_STATUS=0x{flag:x} after the clear")
        rose, written = await self._write_tcm(mem, addr, data, FLIP_STAGE, f"{tag} write")
        rb = RB_STAGE + 0x4000 + 4 * (j % 256)
        st, _, got, _, nib, _ = await self._read_tcm(mem, addr, data, rb, f"{tag} clean read")
        berr = await self._bus_err()
        self._chk_dbg(mem, "none", nib)
        self.n_clean_reads += 1
        if berr & DMA_HOST_PATH_BIT or st.error or got != data:
            self.clean_bad.append(f"{tag} clean read {st.fmt()} data=0x{got:08x} berr=0x{berr:x}")
        open_graded_window(TEST, self.logger)
        mask = bit_mask(k)
        await tcm_flip(cocotb.top, addr, mask)
        st, before, got, _, nib, mark = await self._read_tcm(mem, addr, data, rb, f"{tag} read")
        close_graded_window(self.logger)
        stored = self._stored_word(mem, addr, mark)
        berr = await self._bus_err()
        self._chk_dbg(mem, "single", nib)
        self.logger.info("OBS-TCM-SBE-STATUS: mem=%s k=%d dma_bus_err_status=0x%x", mem, k, berr)
        flipped = int(written is not None and stored is not None and (stored ^ written) == mask)
        line = (
            f"mem={mem} addr=0x{addr:08x} k={k} staging_before=0x{before:08x} data=0x{got:08x} "
            f"stored_bit_flipped={flipped} expected=0x{data:08x} "
            f"written={'X' if written is None else hex(written)} "
            f"stored={'X' if stored is None else hex(stored)} dma={st.fmt()}"
        )
        if got != data or not flipped or before != (~data & M32):
            self._fail("CHK-TCM-SBE", line)
        self.logger.info("CHK-TCM-SBE PASS: %s", line)
        self.n_checks += 1
        wb = self._written_word(mem, addr, mark)
        line = (
            f"contract=PRM tt-Cores-VeeR-EL2@07a51d817 memory-map.md 'Correctable Ecc/Parity Errors' "
            f":638-639,646-647 mem={mem} addr=0x{addr:08x} k={k} "
            f"written_data={'X' if wb is None else hex(wb & M32)} "
            f"written_ecc={'X' if wb is None else hex(wb >> DATA_BITS)} expect=0x{data:08x} "
            f"expect_ecc={'X' if written is None else hex(written >> DATA_BITS)}"
        )
        # The corrected word is the stored word before the flip: data and ECC bits.
        if wb is None or written is None or wb & M32 != data or wb != written:
            self._fail("CHK-TCM-SBE-WB", line)
        self.logger.info("CHK-TCM-SBE-WB PASS: %s", line)
        self.n_checks += 1
        await self.dma.clean_state()
        await self._clear_bus_err()

    # ---- step 8: double-bit flips ---------------------------------------------------
    async def _dbe(self, mem: str, a: int, b: int, addr: int, data: int, j: int) -> None:
        tag = f"DBE {mem} k1={a} k2={b} @0x{addr:08x}"
        flag = await self._clear_bus_err()
        rose, written = await self._write_tcm(mem, addr, data, FLIP_STAGE, f"{tag} write")
        rb = RB_STAGE + 0x8000 + 4 * (j % 256)
        xmark = self.xbar_tap.mark()
        st, _, got, _, nib, _ = await self._read_tcm(mem, addr, data, rb, f"{tag} clean read")
        clean_resp, clean_desc = self._xbar_read(addr, xmark)
        clean_flag = await self._bus_err()
        self._chk_dbg(mem, "none", nib)
        self.n_clean_reads += 1
        if clean_flag & DMA_HOST_PATH_BIT or st.error or got != data:
            self.clean_bad.append(
                f"{tag} clean read {st.fmt()} data=0x{got:08x} berr=0x{clean_flag:x}"
            )
        open_graded_window(TEST, self.logger)
        mask = bit_mask(a, b)
        await tcm_flip(cocotb.top, addr, mask)
        xmark = self.xbar_tap.mark()
        st, _, got, _, nib, mark = await self._read_tcm(mem, addr, data, rb, f"{tag} read")
        resp, desc = self._xbar_read(addr, xmark)
        berr = await self._bus_err()
        close_graded_window(self.logger)
        stored = self._stored_word(mem, addr, mark)
        self._chk_dbg(mem, "double", nib)
        hpe = int(bool(berr & DMA_HOST_PATH_BIT))
        self.dbe_flag_seen |= hpe
        flipped = int(written is not None and stored is not None and (stored ^ written) == mask)
        cf = int(bool((flag | clean_flag) & DMA_HOST_PATH_BIT))
        err_resp = int(bool(resp) and all(r in RESP_ERR for r in resp))
        clean_okay = int(bool(clean_resp) and all(r == RESP_OKAY for r in clean_resp))
        dma_err = int(bool(st.error))
        self.logger.info(
            "OBS-TCM-DBE-DONE: mem=%s addr=0x%08x k1=%d k2=%d done=%d error=%d",
            mem,
            addr,
            a,
            b,
            st.done,
            st.error,
        )
        line = (
            f"mem={mem} addr=0x{addr:08x} k1={a} k2={b} class={pair_class(a, b)} "
            f"rresp_err={err_resp} clean_rresp_okay={clean_okay} dma_error={dma_err} "
            f"host_path_err={hpe} clean_flag={cf} stored_bits_flipped={flipped} "
            f"written={'X' if written is None else hex(written)} "
            f"stored={'X' if stored is None else hex(stored)} dma={st.fmt()} "
            f"xbar_tcm=[{desc}] clean_xbar_tcm=[{clean_desc}]"
        )
        if not (err_resp and clean_okay and dma_err and hpe) or cf or not flipped:
            self._fail("CHK-TCM-DBE", line)
        self.logger.info("CHK-TCM-DBE PASS: %s", line)
        self.n_checks += 1
        await self.dma.clean_state()
        await self._clear_bus_err()

    # ---- sub-word copies ----------------------------------------------------------------
    async def _sub_copy(self, src: int, dst: int, nbytes: int, enc: int) -> tuple:
        """One DMA copy of ``nbytes`` at TRANSFER_WIDTH ``enc``; returns (STATUS, ERROR_CODE, bus err)."""
        await self.dma.clean_state()
        pre_berr = await self._clear_bus_err()
        pre_ecode = await self.dma.rd(_D.addr("ERROR_CODE")) & EC_MASK
        pre = (
            f"contract=dma.hjson:669-670,hw/sys/sep/doc/dma.adoc:66-68 src=0x{src:08x} "
            f"dst=0x{dst:08x} bytes={nbytes} error_code=0x{pre_ecode:x} "
            f"dma_bus_err_status=0x{pre_berr:x} expect=0x0/0x0"
        )
        if pre_ecode or pre_berr:
            msg = f"CTRL-MISSING CTRL-TCM-SUBWORD-PRE: {pre}"
            self.logger.error(msg)
            raise AssertionError(msg)
        self.logger.info("CTRL-TCM-SUBWORD-PRE PASS: %s", pre)
        await self.dma.program_transfer(src=src, dst=dst, total=nbytes, chunk=nbytes, width_enc=enc)
        await self.dma.go()
        st = await self.dma.poll_status(
            lambda s: bool(s.done or s.error), self.dma.done_bound(WORD_BYTES), "sub-word copy"
        )
        ecode = await self.dma.rd(_D.addr("ERROR_CODE"))
        return st, ecode, await self._bus_err()

    def _chk_subword_wr(self, mem: str, addr: int, nbytes: int, st, ecode: int, berr: int) -> None:
        """CHK-TCM-SUBWORD-WR: a sub-word DMA write into a TCM word sets ERROR_CODE.BUS_ERROR."""
        hpe = int(bool(berr & DMA_HOST_PATH_BIT))
        code = ecode & EC_MASK
        bus_error = int(bool(code & EC_BUS_ERROR))
        self.logger.info(
            "OBS-TCM-SUBWORD-CODE: mem=%s addr=0x%08x bytes=%d error_code=0x%x other_bits=0x%x",
            mem,
            addr,
            nbytes,
            code,
            code & ~EC_BUS_ERROR & EC_MASK,
        )
        line = (
            f"contract=hw/sys/sep/doc/dma.adoc:118-121 mem={mem} dir=write addr=0x{addr:08x} bytes={nbytes} "
            f"error={st.error} bus_error={bus_error} bus_error_mask=0x{EC_BUS_ERROR:x} "
            f"host_path_err={hpe}"
        )
        if not st.error or not bus_error or not hpe:
            self._fail("CHK-TCM-SUBWORD-WR", line)
        self.logger.info("CHK-TCM-SUBWORD-WR PASS: %s", line)
        self.n_checks += 1
        self.n_sub_wr += 1

    async def _subword(self) -> None:
        self.n_sub_wr = 0
        for mem, (addr, enc, off, data) in self.plan.sub.items():
            nbytes = 1 << enc
            src, rb = SUB_STAGE, SUB_STAGE + 0x10
            await self.mem.fill(src, [data])
            for direction, s_a, d_a in (("write", src, addr + off), ("read", addr + off, rb)):
                await self.mem.fill(rb, [~data & M32])
                st, ecode, berr = await self._sub_copy(s_a, d_a, nbytes, enc)
                if direction == "write":
                    self._chk_subword_wr(mem, addr + off, nbytes, st, ecode, berr)
                rb_sub = (await self.mem.read(rb, 1))[0]
                wst, _, wberr = await self._sub_copy(addr, rb, WORD_BYTES, 2)
                word = (await self.mem.read(rb, 1))[0]
                self.logger.info(
                    "OBS-TCM-SUBWORD: mem=%s dir=%s addr=0x%08x bytes=%d enc=%d done=%d "
                    "error=%d error_code=0x%x dma_bus_err_status=0x%x staging=0x%08x "
                    "word_read_done=%d word_read_error=%d word_read_bus_err=0x%x word=0x%08x "
                    "src_word=0x%08x",
                    mem,
                    direction,
                    addr + off,
                    nbytes,
                    enc,
                    st.done,
                    st.error,
                    ecode,
                    berr,
                    rb_sub,
                    wst.done,
                    wst.error,
                    wberr,
                    word,
                    data,
                )
        if self.n_sub_wr != len(MEMS):
            msg = f"CTRL-MISSING CHK-TCM-SUBWORD-WR: graded={self.n_sub_wr} expect={len(MEMS)}"
            self.logger.error(msg)
            raise AssertionError(msg)
        await self.dma.clean_state()
        await self._clear_bus_err()

    # ---- multi-word legs ---------------------------------------------------------------
    async def _copy_n(self, src: int, dst: int, n_words: int, what: str):
        """One multi-word copy; returns (STATUS, ERROR_CODE, bus err, taps).

        Restores the one-word transfer before it returns.
        """
        nbytes = WORD_BYTES * n_words
        await self.dma.clean_state()
        await self.dma.program_transfer(
            src=src, dst=dst, total=nbytes, chunk=nbytes, width_enc=WIDTH_ENC
        )
        self.sampler.arm()
        await self.dma.go()
        st = await self.dma.poll_status(
            lambda s: bool(s.done or s.error), self.dma.done_bound(nbytes), what
        )
        await ClockCycles(cocotb.top.clk_i, 2)
        rose, _ = self.sampler.take()
        ecode = await self.dma.rd(_D.addr("ERROR_CODE")) & EC_MASK
        berr = await self._bus_err()
        self.n_copies += 1
        await self._word_xfer()
        return st, ecode, berr, rose

    async def _read_words(self, mem: str, base: int, expect: list[int], what: str) -> list[str]:
        """Read each word through ``_read_tcm``; returns one entry per word that differs."""
        bad = []
        for i, want in enumerate(expect):
            addr = base + WORD_BYTES * i
            st, _, got, _, _, _ = await self._read_tcm(
                mem, addr, want, MW_RB_STAGE + WORD_BYTES * i, what
            )
            if got != want or st.error or not st.done:
                bad.append(f"0x{addr:08x}=0x{got:08x}/exp=0x{want:08x}/{st.fmt()}")
        return bad

    async def _t2t(self) -> None:
        """CHK-TCM-DMA-T2T: ICCM -> DCCM and DCCM -> ICCM multi-word copies."""
        c = self.plan
        n = c.t2t_words
        for ((smem, src), (dmem, dst)), data in zip(c.t2t, c.t2t_data):
            tag = f"T2T {smem}->{dmem}"
            await self.mem.fill(T2T_STAGE, data)
            for i in range(n):
                await self._write_tcm(
                    smem, src + WORD_BYTES * i, data[i], T2T_STAGE + WORD_BYTES * i, f"{tag} source"
                )
            await self._clear_bus_err()
            open_graded_window(TEST, self.logger)
            st, ecode, berr, rose = await self._copy_n(src, dst, n, tag)
            bad = await self._read_words(dmem, dst, data, f"{tag} readback")
            close_graded_window(self.logger)
            hpe = int(bool(berr & DMA_HOST_PATH_BIT))
            line = (
                f"contract=hw/sys/sep/doc/dma.adoc:58-59,118-121 dir={smem}->{dmem} "
                f"src=0x{src:08x} dst=0x{dst:08x} words={n} done={st.done} error={st.error} "
                f"error_code=0x{ecode:x} host_path_err={hpe} iccm_rose={int(rose['ICCM'])} "
                f"dccm_rose={int(rose['DCCM'])} mismatches={len(bad)} first={bad[:2]}"
            )
            if not (rose["ICCM"] and rose["DCCM"]):
                self._missing("CHK-TCM-DMA-T2T", line)
            if not st.done or st.error or hpe or bad:
                self._fail("CHK-TCM-DMA-T2T", line)
            self.logger.info("CHK-TCM-DMA-T2T PASS: %s", line)
            self.n_checks += 1
            await self.dma.clean_state()
            await self._clear_bus_err()

    async def _seam(self) -> None:
        """OBS-DMA-TCM-SEAM: a 16-byte copy from the SRAM over the ICCM end."""
        c = self.plan
        iccm_base, iccm_sz = MEMS["ICCM"]
        seam = iccm_base + iccm_sz
        adj = f"iccm_end=0x{seam:08x} dccm_base=0x{MEMS['DCCM'][0]:08x}"
        if seam != MEMS["DCCM"][0]:
            self._missing("CTRL-TCM-SEAM-ADJ", adj)
        self.logger.info("CTRL-TCM-SEAM-ADJ: %s", adj)
        start = seam - 8
        mems = ("ICCM", "ICCM", "DCCM", "DCCM")
        await self.mem.fill(SEAM_STAGE, c.seam_before)
        for i, mem in enumerate(mems):
            await self._write_tcm(
                mem,
                start + WORD_BYTES * i,
                c.seam_before[i],
                SEAM_STAGE + WORD_BYTES * i,
                "seam before",
            )
        await self.mem.fill(SEAM_STAGE, c.seam_data)
        await self._clear_bus_err()
        st, ecode, berr, _ = await self._copy_n(SEAM_STAGE, start, len(mems), "seam copy")
        await self._clear_bus_err()
        words = []
        for i, mem in enumerate(mems):
            addr = start + WORD_BYTES * i
            rst, _, got, _, _, _ = await self._read_tcm(
                mem, addr, c.seam_data[i], MW_RB_STAGE + WORD_BYTES * i, "seam readback"
            )
            words.append(
                f"0x{addr:08x}=0x{got:08x}/before=0x{c.seam_before[i]:08x}/"
                f"src=0x{c.seam_data[i]:08x}/read_error={rst.error}"
            )
            await self._clear_bus_err()
        self.logger.info(
            "OBS-DMA-TCM-SEAM LOG %s error_code=0x%x dma_bus_err_status=0x%x words=%s",
            st.fmt(),
            ecode,
            berr,
            " ".join(words),
        )
        await self.dma.clean_state()
        await self._clear_bus_err()

    def _dccm_writes(self, mark) -> int:
        """DCCM bank writes on PR-TCM since ``mark``."""
        return sum(
            1
            for b in self.tcm_tap.since(mark, "dccm")
            for bank in (0, 1)
            if b.lane("clken", bank, 1) == 1 and b.lane("wren", bank, 1) == 1
        )

    async def _abort_recover(self) -> None:
        """CHK-TCM-ABORT-RECOVER: ABORT during an SRAM -> DCCM copy, then a full copy."""
        c = self.plan
        top = cocotb.top
        n, dst = c.abort_words, c.abort_dst
        nbytes = WORD_BYTES * n
        await self.mem.fill(ABORT_STAGE, c.abort_data)
        await self.mem.fill(RECOVER_STAGE, c.recover_data)
        await self.dma.clean_state()
        await self._clear_bus_err()
        await self.dma.program_transfer(
            src=ABORT_STAGE, dst=dst, total=nbytes, chunk=nbytes, width_enc=WIDTH_ENC
        )
        st0 = await self.dma.read_status()
        if st0.aborted:
            self._missing("CHK-TCM-ABORT-RECOVER", f"ABORTED before GO {st0.fmt()}")
        mark = self.tcm_tap.mark()
        await self.dma.go()
        first = 0
        for _ in range(ABORT_WAIT):
            await RisingEdge(top.clk_i)
            await ReadOnly()
            first = self._dccm_writes(mark)
            if first:
                break
        await FallingEdge(top.clk_i)
        if not first:
            self._missing(
                "CHK-TCM-ABORT-RECOVER",
                f"no DCCM write within {ABORT_WAIT} clk_i cycles of GO",
            )
        await self.dma.abort()
        at_abort = self._dccm_writes(mark)
        if at_abort >= n:
            self._missing(
                "CHK-TCM-ABORT-RECOVER",
                f"the copy wrote {at_abort} of {n} DCCM words before the ABORT write returned",
            )
        st = await self.dma.poll_status(
            lambda s: bool(s.aborted or s.done or s.error), self.dma.done_bound(nbytes), "abort"
        )
        await ClockCycles(top.clk_i, 16)
        total = self._dccm_writes(mark)
        await self.dma.clean_state()
        await self._clear_bus_err()
        st_clr = await self.dma.read_status()
        if st_clr.aborted:
            self._missing("CHK-TCM-ABORT-RECOVER", f"ABORTED after the W1C {st_clr.fmt()}")
        rst, ecode, berr, _ = await self._copy_n(RECOVER_STAGE, dst, n, "recovery copy")
        bad = await self._read_words("DCCM", dst, c.recover_data, "recovery readback")
        hpe = int(bool(berr & DMA_HOST_PATH_BIT))
        line = (
            f"contract=secure_dma.adoc CONTROL.ABORT,STATUS.ABORTED;sep-programming.adoc:805-806 "
            f"dst=0x{dst:08x} words={n} dccm_writes_first={first} dccm_writes_at_abort={at_abort} "
            f"dccm_writes_aborted_run={total} abort_{st.fmt()} recovery_done={rst.done} "
            f"recovery_error={rst.error} recovery_error_code=0x{ecode:x} host_path_err={hpe} "
            f"mismatches={len(bad)} first={bad[:2]}"
        )
        if not st.aborted or not rst.done or rst.error or ecode or hpe or bad:
            self._fail("CHK-TCM-ABORT-RECOVER", line)
        self.logger.info("CHK-TCM-ABORT-RECOVER PASS: %s", line)
        self.n_checks += 1
        await self.dma.clean_state()
        await self._clear_bus_err()

    # ---- scenario ---------------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("INFO-SEED seed=%d", seed)
        plan = _Cfg(seed)
        self.plan = plan
        for line in plan.draw_lines():
            self.logger.info("INFO-DRAW %s", line)

        await self.bring_up_no_cpu()
        full = self.full_cpu_build()
        self.logger.info("INFO-BUILD: full_cpu=%d", int(full))
        if not full:
            self._fail(
                "CTRL-FULL-CPU",
                "the build has the CPU stub, which has no TCM controller; run the leaf on the "
                "full-CPU default target (+sep_require_full_cpu)",
            )
        top = cocotb.top
        self.dma = SepDmaOps(self)
        self.mem = SepMemWords(self)
        self.n_checks = 0
        self.n_copies = 0
        self.n_clean_reads = 0
        self.clean_bad: list[str] = []
        self.dbe_flag_seen = 0
        self.sampler = _TapSampler(top)
        self.sampler.start()
        self.tcm_tap = SepFabricTap("PR-TCM").start()
        self.xbar_tap = SepFabricTap("PR-XBAR-TCM").start()

        await self._setup()
        await self._aperture()
        for j, (mem, k, addr, data) in enumerate(plan.sbe):
            await self._sbe(mem, k, addr, data, j)
        for j, (mem, a, b, addr, data) in enumerate(plan.dbe):
            await self._dbe(mem, a, b, addr, data, j)
        close_graded_window(self.logger)

        line = (
            f"reads={self.n_clean_reads} data_match={int(not self.clean_bad)} "
            f"host_path_err={int(bool(self.clean_bad))} control_dbe_flag={self.dbe_flag_seen} "
            f"start={self.clean_start.fields()}"
        )
        if self.clean_bad or not self.dbe_flag_seen:
            self._fail("CHK-TCM-CLEAN", f"{line} first: {self.clean_bad[:4]}")
        self.logger.info("CHK-TCM-CLEAN PASS: %s", line)
        self.n_checks += 1
        await self._subword()
        await self._t2t()
        await self._seam()
        await self._abort_recover()

        self.sampler.stop()
        await self.tcm_tap.stop()
        await self.xbar_tap.stop()
        self.logger.info("INFO-TCM-COPIES: %d secure DMA copies", self.n_copies)
        self.result_pass(TEST, seed, self.n_checks)
