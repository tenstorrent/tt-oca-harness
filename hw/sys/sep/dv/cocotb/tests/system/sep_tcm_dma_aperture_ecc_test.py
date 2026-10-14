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
  CHK-TCM-DBE    for 16 drawn bit pairs of each memory (at least 4 each of
                 data-data, data-ECC and ECC-ECC), the DMA read ends with
                 ``host_path_err`` set. Control: the flag reads 0 after the clear
                 and after the clean read of the same word, and the stored word
                 differs from the written word in the two flipped bits.
Observations (not graded): OBS-TCM-EXCL (whether the other memory's clock-enable
tap rose), OBS-TCM-DBG (``ext_debug_bus_o[367:364]`` during each DMA read),
OBS-TCM-SBE-STATUS (``DMA_BUS_ERR_STATUS`` after a corrected read).

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
``tb/tb_top.sv``, ``tb_backdoor_mem``).

The graded window (owner code of this test) is open around the aperture copies
and around each flip and its read. Set-up, clears, writes before a flip and the
clean control reads run with the window closed.
"""

from __future__ import annotations

import os

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
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
RANGE_REGS = (
    ("ENABLED_MEMORY_RANGE_BASE", 0x0),
    ("ENABLED_MEMORY_RANGE_LIMIT", 0xFFFF_FFFF),
    ("RANGE_VALID", 0x1),
)
WIDTH_ENC = 2  # TRANSFER_WIDTH: 4-byte beats
WORD_BYTES = 4
DBG_HI, DBG_LO = 367, 364
ROW_BITS = 14
ROW_MASK = (1 << ROW_BITS) - 1


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

    def draw_lines(self) -> list[str]:
        out = []
        for mem, rows in self.apert.items():
            out.append(
                f"apert_{mem} words={len(rows)} bits={self.bits[mem]} drawn="
                + ",".join(f"0x{a:08x}" for a, _ in rows[2 + self.bits[mem] :])
            )
        out.append("sbe=" + " ".join(f"{m}/k={k}/@0x{a:08x}" for m, k, a, _ in self.sbe))
        out.append(
            "dbe="
            + " ".join(
                f"{m}/{a},{b}/{pair_class(a, b)}/@0x{addr:08x}" for m, a, b, addr, _ in self.dbe
            )
        )
        return out


class _TapSampler:
    """Per-clock sampler of the TCM clock-enable taps and the debug-bus nibble.

    ``arm`` opens a window; ``take`` closes it and returns whether each tap rose
    (a 0 to 1 change inside the window) and the OR of the nibble samples.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.task = None
        self._reset()

    def _reset(self) -> None:
        self.rose = {"ICCM": False, "DCCM": False}
        self.prev = {"ICCM": None, "DCCM": None}
        self.nibble = 0
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
            self.nibble |= int(nib, 2) if all(c in "01" for c in nib) else 0

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

    def take(self) -> tuple[dict[str, bool], int]:
        self.armed = False
        return dict(self.rose), self.nibble


@pyuvm.test()
class sep_tcm_dma_aperture_ecc_test(sep_base_test):
    """DMA-path TCM aperture reach and ECC response."""

    required_evidence = ("CHK-TCM-APERT", "CHK-TCM-CLEAN", "CHK-TCM-SBE", "CHK-TCM-DBE")

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
        self.logger.info("CTL-TCM-RESET: core reset state after bring-up %s", state)
        if any(c not in "01" for v in state.values() for c in v):
            raise AssertionError(f"CTL-TCM-RESET FAIL: core reset state not known {state}")
        # All-zero TCM image: every word a valid code word (tb_backdoor_mem).
        for name in ("sep_itcm.hex", "sep_dtcm.hex"):
            with open(os.path.join(os.getcwd(), name), "w") as fh:
                fh.write("@0\n00\n")
        top.tcm_load_i.value = 1
        await ClockCycles(top.clk_i, 4)
        top.tcm_load_i.value = 0
        await ClockCycles(top.clk_i, 4)
        self.logger.info("CTL-TCM-INIT: all-zero ICCM and DCCM image loaded through tcm_load_i")

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
                raise AssertionError(f"CTL-TCM-RANGE FAIL: {name} readback {fc.fields()}")
        self.logger.info("CTL-TCM-RANGE: %s", " | ".join(parts))
        written = await self.dma.program_transfer(
            src=SRC_STAGE, dst=RB_STAGE, total=WORD_BYTES, chunk=WORD_BYTES, width_enc=WIDTH_ENC
        )
        for name, val in written.items():
            got = await self.dma.rd(_D.addr(name))
            fc = field_compare(got, val, _D.mask32(name))
            if not fc.ok:
                raise AssertionError(f"CTL-TCM-XFER FAIL: {name} readback {fc.fields()}")
        self.logger.info(
            "CTL-TCM-XFER: transfer registers read back %s",
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
            self.logger.info(
                "OBS-TCM-DBG: mem=%s kind=none bus367_364=0b%s", mem, format(nib, "04b")
            )
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
        self.logger.info("OBS-TCM-DBG: mem=%s kind=none bus367_364=0b%s", mem, format(nib, "04b"))
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
        self.logger.info("OBS-TCM-DBG: mem=%s kind=single bus367_364=0b%s", mem, format(nib, "04b"))
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
        await self.dma.clean_state()
        await self._clear_bus_err()

    # ---- step 8: double-bit flips ---------------------------------------------------
    async def _dbe(self, mem: str, a: int, b: int, addr: int, data: int, j: int) -> None:
        tag = f"DBE {mem} k1={a} k2={b} @0x{addr:08x}"
        flag = await self._clear_bus_err()
        rose, written = await self._write_tcm(mem, addr, data, FLIP_STAGE, f"{tag} write")
        rb = RB_STAGE + 0x8000 + 4 * (j % 256)
        st, _, got, _, nib, _ = await self._read_tcm(mem, addr, data, rb, f"{tag} clean read")
        clean_flag = await self._bus_err()
        self.logger.info("OBS-TCM-DBG: mem=%s kind=none bus367_364=0b%s", mem, format(nib, "04b"))
        self.n_clean_reads += 1
        if clean_flag & DMA_HOST_PATH_BIT or st.error or got != data:
            self.clean_bad.append(
                f"{tag} clean read {st.fmt()} data=0x{got:08x} berr=0x{clean_flag:x}"
            )
        open_graded_window(TEST, self.logger)
        mask = bit_mask(a, b)
        await tcm_flip(cocotb.top, addr, mask)
        st, _, got, _, nib, mark = await self._read_tcm(mem, addr, data, rb, f"{tag} read")
        berr = await self._bus_err()
        close_graded_window(self.logger)
        stored = self._stored_word(mem, addr, mark)
        self.logger.info("OBS-TCM-DBG: mem=%s kind=double bus367_364=0b%s", mem, format(nib, "04b"))
        hpe = int(bool(berr & DMA_HOST_PATH_BIT))
        self.dbe_flag_seen |= hpe
        flipped = int(written is not None and stored is not None and (stored ^ written) == mask)
        cf = int(bool((flag | clean_flag) & DMA_HOST_PATH_BIT))
        line = (
            f"mem={mem} addr=0x{addr:08x} k1={a} k2={b} class={pair_class(a, b)} "
            f"host_path_err={hpe} clean_flag={cf} stored_bits_flipped={flipped} "
            f"written={'X' if written is None else hex(written)} "
            f"stored={'X' if stored is None else hex(stored)} dma={st.fmt()}"
        )
        if not hpe or cf or not flipped:
            self._fail("CHK-TCM-DBE", line)
        self.logger.info("CHK-TCM-DBE PASS: %s", line)
        self.n_checks += 1
        await self.dma.clean_state()
        await self._clear_bus_err()

    # ---- scenario ---------------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        plan = _Cfg(seed)
        self.plan = plan
        for line in plan.draw_lines():
            self.logger.info("DRAW %s", line)

        await self.bring_up_no_cpu()
        full = self.full_cpu_build()
        self.logger.info("OBS-BUILD: full_cpu=%d", int(full))
        if not full:
            self._fail(
                "CTL-FULL-CPU",
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

        self.sampler.stop()
        await self.tcm_tap.stop()
        self.logger.info("OBS-TCM-COPIES: %d secure DMA copies", self.n_copies)
        self.result_pass(TEST, seed, self.n_checks)
