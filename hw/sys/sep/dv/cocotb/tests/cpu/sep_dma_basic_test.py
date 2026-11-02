# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure DMA CSRs, address modes, widths and error legs meet their contracts on SRAM copies.

OCAH provenance: ``reg_rw``, ``reg_reset``, ``cfg_regwen``, ``range_regwen``,
``addr_fixed``, ``addr_wrap``, ``addr_combo``, ``mem_copy`` and ``err_opcode``
check DMA CSRs, locks, address modes, widths, copies and opcode errors.

The test boots the VeeR EL2 core and runs the dma_basic firmware. The firmware drives the
Secure DMA over the CPU LSU and checks the DMA CSR and copy-datapath contracts on bare sep
(SRAM->SRAM transfers).

Distinct from the other DMA tests (sep_dma_hash_test: inline SHA-256, SRAM->DCCM and IRQ;
sep_dma_cpu_contention_test: mid-flight BUSY and dual master; sep_spi_ot_dma_rx_test: lsio
handshake): this test adds the CSR/REGWEN breadth, the FIXED/INCR/WRAP mode matrix, the
1B/2B/4B width sweep, the opcode/address/ASID/size error legs, the host-path integrity and
fabric-error legs, and an SRAM->ICCM->SRAM round trip.

SepDmaBasicCfg is the single source of truth for src/dst offsets, copy length
and fill seed. Discrete mode/width cells stay walked every invocation; the
continuous knobs come from the run seed (patched into the firmware param block).

Firmware-self-checking: the firmware returns its error count and fw/startup/crt0.s emits
the PASS (0xCAFEBABE) / FAIL (0xDEADBEEF) magic on the 0x8000_0000 mailbox, which
the boot scoreboard gates on. The firmware self-checks (each with a positive PASS
line in the console log): CHK-RESET (reset values), CHK-CFG-REGWEN (HW busy-lock),
CHK-RANGE-REGWEN (an unconfigured range raises range_valid_error alone, an
inverted range base_limit_error alone, then the rw0c lock), CHK-COPY-MODE (FIXED/INCR/WRAP
expected images + neighbor), CHK-WIDTH (1B/2B/4B), CHK-DONE-RW1C, CHK-ERR-OPCODE
(opcode_error + recovery), CHK-ERR-ADDR (four misaligned descriptors, each
raising its ERROR_CODE bit exclusively, then a recovery copy), CHK-HOSTINTG
(DMA-issued command under dma_host_intg_inject_i -> exclusive host_path_err
+ aggregator [41], CLEAR, recovery copy), CHK-HOSTFABRIC (fabric DECERR dest
-> exclusive host_path_err with the pin low, CLEAR, recovery), CHK-ERR-ASID (unencoded
ASID), CHK-ERR-SIZE (unencoded width), CHK-ICCM (SRAM->ICCM->SRAM round trip). The
scoreboard also checks the banner + ICCM execution. Every ERROR_CODE compare grades the
named fields; bits 31:8 have no stated reset and the firmware prints them on OBS-ERR-RSVD.
CHK-RESET grades the named fields of each register; its reserved bits print on OBS-RESET-RSVD.

CHK-RAS-DMA_HOST_INTG_ERR grades ``sep_ras_o.dma_host_intg_err`` on the bench tap
``sep_ras_probe_o`` against ``hw/sys/sep/doc/dma.adoc:67-69`` ("The register and host bridges
latch faults on ``dma_reg_bus_err_o`` and ``dma_host_intg_err_o``, cleared through
``DMA_BUS_ERR_CLEAR``") as four checks, each on its own line:
CHK-RAS-DMA_HOST_INTG_ERR-IDLE (0 on every clock from the CPU release to
``dma_host_intg_inject_i`` = 1), -RISE (a rise before the firmware prints
CHK-HOSTINTG-RELEASE), -SHAPE (no fall from the rise through the first DMA_BUS_ERR_CLEAR
clear pulse of the host-path latch, across the pin release) and -CLEAR (a fall within
``_PIC_POLL`` clocks of that pulse). Each logs PASS or FAIL; the leaf raises once after
all four are logged. The rise and fall delays and the field in the fabric-DECERR leg
are logged only (OBS-RAS-DMA_HOST_INTG_ERR-*): no document states them.

CTRL-HOSTINTG-ARM-PIN requires ``dma_host_intg_inject_i`` = 1 on the clock of the
firmware control read of DMA_BUS_ERR_STATUS before GO and of the read after the
injected command, from the CPU reads of that register on the PR-LSU-XBAR tap
(``env/sep_fabric_tap.py``). CHK-HOSTINTG-STICKY requires sep_internal_interrupts[41]
to stay 1 from the pin release to the firmware CHK-HOSTINTG-HELD marker, which the
firmware prints after it reads DMA_BUS_ERR_STATUS = host_path_err and before it
writes DMA_BUS_ERR_CLEAR.

FCOV: the graded window of this leaf opens when the CPU is released and closes after
the host has parsed the console. ``cp_error_class_exclusive`` holds each cell at the
ERROR_CODE read of its error leg; the firmware check of that leg also grades
STATUS.done 0, the W1C clear and a recovery copy after that read, so the leaf
releases a cell (``set_dma_basic_pass``) only when CHK-ERR-CLASS finds the PASS
line of the firmware check that owns the cell.

cpu / +skip_fuse_sense (no fuse data is read).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_bit_watch import BitMark, BitWatchTimeout, SepBitWatch
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import (
    DMA_BASIC_PASS_ASID,
    DMA_BASIC_PASS_BASE_LIMIT,
    DMA_BASIC_PASS_DST,
    DMA_BASIC_PASS_RANGE_VALID,
    DMA_BASIC_PASS_SIZE,
    DMA_BASIC_PASS_SRC,
    close_graded_window,
    open_graded_window,
    set_dma_basic_pass,
)
from env.sep_ras_map import PERIPH_BUS_ERR_BLOCKS, RasChkLines, check_tap_width, ras_bit
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_irq_aggregator_seq import IRQ_DMA_HOST_PATH, IRQ_DMA_REG_PATH

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_basic_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_basic_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_basic_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 4_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP DMA basic test"

_PARAM_MAGIC = 0xDA0A11C0
_BUSY_LEN = 0x100
_PIC_POLL = 200_000
_DMA_PATH_BITS = (1 << IRQ_DMA_HOST_PATH) | (1 << IRQ_DMA_REG_PATH)
# DMA_BUS_ERR_STATUS is alone in its 8-byte word of the 64-bit LSU port.
_STATUS_WORD = sym("SEP_CPU_CTRL_DMA_BUS_ERR_STATUS_REG_ADDR") // 8

# The firmware check that grades each error leg, and the cp_error_class_exclusive
# cells those legs hold. A cell is released only after that PASS line is found.
_CLASS_CHECKS = (
    ("CHK-RANGE-REGWEN PASS:", (DMA_BASIC_PASS_RANGE_VALID, DMA_BASIC_PASS_BASE_LIMIT)),
    ("CHK-ERR-ADDR PASS:", (DMA_BASIC_PASS_SRC, DMA_BASIC_PASS_DST)),
    ("CHK-ERR-ASID PASS:", (DMA_BASIC_PASS_ASID,)),
    ("CHK-ERR-SIZE PASS:", (DMA_BASIC_PASS_SIZE,)),
)
# Firmware OBS lines: reserved register bits that no document states.
_OBS_LINES = ("OBS-RESET-RSVD:", "OBS-ERR-RSVD:")

_RAS = "RAS-DMA_HOST_INTG_ERR"
_RAS_HALVES = ("IDLE", "RISE", "SHAPE", "CLEAR")
# sep_cpu_ctrl_err_pulse_probe_o (tb/sep_tb_signal_list.svh): the low half holds the set
# term of each bridge-fault latch in periph_bus_err_e order, then DMA reg_path_err and
# host_path_err; the high half holds the clear pulse of the same latches.
_PULSE_HOST_SET = len(PERIPH_BUS_ERR_BLOCKS) + 1
_PULSE_HOST_CLR = _PULSE_HOST_SET + len(PERIPH_BUS_ERR_BLOCKS) + 2


@dataclass(frozen=True)
class SepDmaBasicCfg:
    """Single source of truth for DMA basic-breadth continuous knobs.

    Discrete cells (INCR/FIXED/WRAP x 1B/2B/4B) are walked every invocation.
    src/dst offsets, copy length and fill seed come from the run seed.
    """

    seed: int
    src_off: int
    dst_off: int
    nbytes: int
    fill_seed: int

    @classmethod
    def from_seed(cls, seed: int) -> "SepDmaBasicCfg":
        # The stimulus is a pure function of the seed, so a failing leaf replays
        # with `--stage sim --seed N`.
        rng = SepSeededRng(seed)
        nbytes = rng.choice((16, 32))
        src_off = rng.randrange(0, 0x10000, 16)
        dst_off = rng.randrange(0x20000, 0x30000, 16)
        fill = rng.getrandbits(32) or 0x1234567
        return cls(seed=seed, src_off=src_off, dst_off=dst_off, nbytes=nbytes, fill_seed=fill)

    def param_words(self) -> list[int]:
        return [_PARAM_MAGIC, self.src_off, self.dst_off, self.nbytes, self.fill_seed]


@pyuvm.test()
class sep_dma_basic_test(sep_base_test):
    """DMA CSR, copy-mode, width and error-leg checks pass; a host-path error reaches sep_internal_interrupts[41] (PIC source 42)."""

    build_env = False
    # The leaf's own graded records; the base-class records do not count.
    required_evidence = (
        "CHK-HOSTINTG-PIC",
        "CHK-HOSTINTG-STICKY",
        "CHK-HOSTINTG-CLR",
        "CHK-ERR-CLASS",
        "CHK-RAND-REP",
        *(f"CHK-{_RAS}-{half}" for half in _RAS_HALVES),
    )

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)
        self._ras_task = None
        self._ras_logged: set[str] = set()
        self._ras_chk = RasChkLines(self.logger, self.random_seed())
        self._status_reads: list[tuple[int, int | None]] = []

    def _stage_dtcm(self) -> str:
        cfg = SepDmaBasicCfg.from_seed(self.random_seed())
        # The source and destination windows must not overlap, or a copy would
        # read bytes it has already written and the golden compare would pass on
        # a DMA that did nothing. The ranges the config draws from are disjoint;
        # this fails if either is widened into the other.
        src_hi = cfg.src_off + _BUSY_LEN
        dst_hi = cfg.dst_off + _BUSY_LEN
        assert src_hi <= cfg.dst_off or dst_hi <= cfg.src_off, (
            f"DMA windows overlap: src 0x{cfg.src_off:x}..0x{src_hi:x} "
            f"dst 0x{cfg.dst_off:x}..0x{dst_hi:x}"
        )
        patched = os.path.join(os.getcwd(), "sep_dtcm_dma.hex")
        patch_param_block(_DTCM_HEX, patched, _PARAM_MAGIC, cfg.param_words())
        self.logger.info(
            "DMA basic RANDCFG seed=%d src_off=0x%x dst_off=0x%x nbytes=%d fill=0x%08x",
            cfg.seed,
            cfg.src_off,
            cfg.dst_off,
            cfg.nbytes,
            cfg.fill_seed,
        )
        self._dma_cfg = cfg
        return patched

    async def _drive_host_intg_inject(self) -> None:
        """Drive ``dma_host_intg_inject_i`` for the integrity copy.

        Pin high from CHK-HOSTINTG-ARM until CHK-HOSTINTG-RELEASE.
        Aggregator bit 41 must be 1 and exclusive of bit 40 while the pin
        is high, and 0 after CLEAR.
        """
        dut = cocotb.top
        for _ in range(_MAX_RUN_CYCLES):
            text = self.sb.console_text()
            if "CHK-HOSTINTG-ARM" in text:
                break
            if self.sb.fw_done:
                raise AssertionError("firmware finished without printing CHK-HOSTINTG-ARM")
            await RisingEdge(dut.clk_i)
        else:
            raise AssertionError("firmware never printed CHK-HOSTINTG-ARM")

        dut.dma_host_intg_inject_i.value = 1
        self.logger.info("STEP host-intg: dma_host_intg_inject_i=1")

        # Bit 41 asserts only on a DMA-issued a_valid. RELEASE with the bit
        # still low means the injected command did not set host_path_err.
        for _ in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            # Both bits must be known 0/1: rd() raises on X/Z, so an unknown
            # register-path bit cannot read as "stays clear".
            vec = self.rd(dut.sep_internal_interrupts_probe_o, mask=_DMA_PATH_BITS)
            if (vec >> IRQ_DMA_HOST_PATH) & 1:
                reg_bit = (vec >> IRQ_DMA_REG_PATH) & 1
                assert reg_bit == 0, (
                    f"register-path [40] is {reg_bit}, not 0, on host-path inject (vec=0x{vec:x})"
                )
                self.logger.info(
                    "CHK-HOSTINTG-PIC PASS: sep_internal_interrupts[41]=1 exclusive (vec=0x%x)",
                    vec,
                )
                break
            if self.sb.fw_done or "CHK-HOSTINTG-RELEASE" in self.sb.console_text():
                raise AssertionError(
                    "sep_internal_interrupts[41] stayed 0 through the injected DMA command"
                )
        else:
            raise AssertionError("sep_internal_interrupts[41] stayed 0 after host-path inject")

        for _ in range(_MAX_RUN_CYCLES):
            if "CHK-HOSTINTG-RELEASE" in self.sb.console_text():
                break
            if self.sb.fw_done:
                raise AssertionError("firmware finished without printing CHK-HOSTINTG-RELEASE")
            await RisingEdge(dut.clk_i)
        else:
            raise AssertionError("firmware never printed CHK-HOSTINTG-RELEASE")

        # The last two DMA_BUS_ERR_STATUS reads before CHK-HOSTINTG-RELEASE are the
        # control read before GO and the read after the injected command. The
        # control read proves the pin alone does not set the latch only if the pin
        # is high at that read.
        release_ps = get_sim_time("ps")
        reads = [r for r in self._status_reads if r[0] <= release_ps]
        ctrl, after = ([(None, None)] * 2 + reads)[-2:]
        arm_ok = ctrl[1] == 1 and after[1] == 1
        arm_line = (
            f"CTRL-HOSTINTG-ARM-PIN {'PASS' if arm_ok else 'FAIL'}: "
            f"seed={self.random_seed()} status_reads={len(reads)} "
            f"control_read_ps={ctrl[0]} pin_at_control_read={ctrl[1]} "
            f"after_cmd_read_ps={after[0]} pin_at_after_cmd_read={after[1]}"
        )
        if not arm_ok:
            self.logger.error(arm_line)
            raise AssertionError(arm_line)
        self.logger.info(arm_line)
        dut.dma_host_intg_inject_i.value = 0
        self.logger.info("STEP host-intg: dma_host_intg_inject_i=0")

        # The latch is sticky until DMA_BUS_ERR_CLEAR (hw/sys/sep/doc/dma.adoc:67-69):
        # bit 41 holds 1 after the pin falls, through the firmware STATUS read that
        # precedes the CLEAR write (CHK-HOSTINTG-HELD).
        held_clocks = 0
        for _ in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            if "CHK-HOSTINTG-HELD" in self.sb.console_text():
                break
            bit = (
                self.rd(dut.sep_internal_interrupts_probe_o, mask=1 << IRQ_DMA_HOST_PATH)
                >> IRQ_DMA_HOST_PATH
            )
            if bit != 1:
                raise AssertionError(
                    f"CHK-HOSTINTG-STICKY FAIL: sep_internal_interrupts[41]={bit} "
                    f"{held_clocks} clocks after the pin release, before CHK-HOSTINTG-HELD"
                )
            held_clocks += 1
            if self.sb.fw_done:
                raise AssertionError("firmware finished without printing CHK-HOSTINTG-HELD")
        else:
            raise AssertionError("firmware never printed CHK-HOSTINTG-HELD")
        self.logger.info(
            "CHK-HOSTINTG-STICKY PASS: sep_internal_interrupts[41]=1 on %d clocks from the "
            "pin release to CHK-HOSTINTG-HELD",
            held_clocks,
        )

        # rd() raises on X/Z, so only a known 0 counts as a cleared bit.
        bit = None
        for _ in range(_PIC_POLL):
            await RisingEdge(dut.clk_i)
            bit = (
                self.rd(dut.sep_internal_interrupts_probe_o, mask=1 << IRQ_DMA_HOST_PATH)
                >> IRQ_DMA_HOST_PATH
            )
            if bit == 0:
                self.logger.info(
                    "CHK-HOSTINTG-CLR PASS: sep_internal_interrupts[41] resolved 0 "
                    "after DMA_BUS_ERR_CLEAR"
                )
                return
        raise AssertionError(
            f"sep_internal_interrupts[41] not a resolved 0 after DMA_BUS_ERR_CLEAR "
            f"(last value {bit!r})"
        )

    async def _check_host_fabric_pin(self) -> None:
        """Require the integrity inject pin low at the fabric-DECERR arm."""
        dut = cocotb.top
        for _ in range(_MAX_RUN_CYCLES):
            if "CHK-HOSTFABRIC-ARM" in self.sb.console_text():
                pin = self.rd_known(dut.dma_host_intg_inject_i)
                assert pin == 0, f"CHK-HOSTFABRIC-ARM: dma_host_intg_inject_i={pin}, expected 0"
                self.logger.info(
                    "CTRL-HOSTFABRIC-ARM-PIN PASS: dma_host_intg_inject_i=0 at firmware "
                    "CHK-HOSTFABRIC-ARM"
                )
                return
            if self.sb.fw_done:
                raise AssertionError("firmware finished without printing CHK-HOSTFABRIC-ARM")
            await RisingEdge(dut.clk_i)
        raise AssertionError("firmware never printed CHK-HOSTFABRIC-ARM")

    async def _sample_status_reads(self, tap: SepFabricTap) -> None:
        """Record the inject pin level on the edge of each CPU read of DMA_BUS_ERR_STATUS."""
        dut = cocotb.top
        pin_at: dict[int, int] = {}
        seen = 0
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            pin_at[get_sim_time("ps")] = self.rd_known(dut.dma_host_intg_inject_i)
            for beat in tap.beats[seen:]:
                addr = beat.fields.get("addr")
                if beat.ch == "ar" and addr is not None and addr // 8 == _STATUS_WORD:
                    self._status_reads.append((beat.t_ps, pin_at.get(beat.t_ps)))
            seen = len(tap.beats)
            if len(pin_at) > 4:
                del pin_at[next(iter(pin_at))]

    def _ras_start(self) -> None:
        """Start the CHK-RAS-DMA_HOST_INTG_ERR watchers and grader at the CPU release."""
        dut = cocotb.top
        check_tap_width(dut.sep_ras_probe_o)
        # Both watchers start on the same clock, so their clock counts name the same edges.
        self._ras = SepBitWatch(
            dut.sep_ras_probe_o, {"host_intg": ras_bit("dma_host_intg_err")}, name="sep_ras_o"
        ).start()
        self._pulse = SepBitWatch(
            dut.sep_cpu_ctrl_err_pulse_probe_o, {"set": _PULSE_HOST_SET, "clr": _PULSE_HOST_CLR}
        ).start()
        self._ras_task = cocotb.start_soon(self._check_ras_host_intg(self._ras.mark()))
        self._lsu_tap = SepFabricTap("PR-LSU-XBAR").start()
        self._status_task = cocotb.start_soon(self._sample_status_reads(self._lsu_tap))

    def _ras_verdict(self, half: str, ok: bool, **fields) -> None:
        self._ras_logged.add(half)
        self._ras_chk.ok(f"{_RAS}-{half}", ok, **fields)

    async def _wait_console(self, needle: str) -> None:
        dut = cocotb.top
        for _ in range(_MAX_RUN_CYCLES):
            if needle in self.sb.console_text():
                return
            if self.sb.fw_done:
                raise AssertionError(f"firmware finished without printing {needle}")
            await RisingEdge(dut.clk_i)
        raise AssertionError(f"firmware never printed {needle}")

    async def _grade_ras_host_intg(self, m0: BitMark) -> None:
        dut = cocotb.top
        ras, pulse = self._ras, self._pulse
        for _ in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            if self.rd_known(dut.dma_host_intg_inject_i):
                break
            if self.sb.fw_done:
                raise AssertionError("firmware finished before dma_host_intg_inject_i rose")
        else:
            raise AssertionError("dma_host_intg_inject_i never rose")
        m1, mp = ras.mark(), pulse.mark()
        high = ras.high_clocks_since(m0)
        self._ras_verdict("IDLE", high == 0, high_clocks=high, inject_clk=m1.clk, exp=0)

        await self._wait_console("CHK-HOSTINTG-RELEASE")
        rises = ras.rise_clks_since(m1)
        self._ras_verdict(
            "RISE", bool(rises), rises=len(rises), inject_clk=m1.clk, release_clk=ras.clk, exp=">=1"
        )
        if rises:
            sets = pulse.rise_clks_since(mp, "set")
            self._ras_chk.obs(
                f"{_RAS}-DELAY",
                rise_clk=rises[0],
                after_inject=rises[0] - m1.clk,
                after_set_term=rises[0] - sets[0] if sets else "n/a",
            )

        clr = await pulse.wait_rise(mp, _PIC_POLL, "clr")
        rise = rises[0] if rises else None
        held_falls = [f for f in ras.fall_clks_since(m1) if f <= clr]
        self._ras_verdict(
            "SHAPE",
            rise is not None and rise <= clr and not held_falls,
            rise_clk=rise,
            clear_pulse_clk=clr,
            falls_to_pulse=held_falls,
            exp="rise_before_pulse_no_fall",
        )

        try:
            await ras.wait_level(0, _PIC_POLL, "host_intg")
        except BitWatchTimeout:
            pass
        after = [f for f in ras.fall_clks_since(m1) if f > clr]
        self._ras_verdict(
            "CLEAR",
            bool(after) and after[0] - clr <= _PIC_POLL,
            clear_pulse_clk=clr,
            fall_clk=after[0] if after else None,
            bound=_PIC_POLL,
        )
        if after:
            self._ras_chk.obs(f"{_RAS}-FALL", after_clear_pulse=after[0] - clr)

    async def _check_ras_host_intg(self, m0: BitMark) -> None:
        """Grade the four CHK-RAS-DMA_HOST_INTG_ERR halves, then log the fabric-leg field."""
        try:
            await self._grade_ras_host_intg(m0)
        except AssertionError as exc:
            for half in _RAS_HALVES:
                if half not in self._ras_logged:
                    self._ras_verdict(half, False, not_reached=str(exc))
            return
        # The host-path latch also sets on a non-OKAY fabric response; the cited spec text
        # names only the integrity fault, so this leg is logged and not graded.
        await self._wait_console("CHK-HOSTFABRIC-ARM")
        mf = self._ras.mark()
        dut = cocotb.top
        for _ in range(_MAX_RUN_CYCLES):
            if self.sb.fw_done:
                break
            await RisingEdge(dut.clk_i)
        self._ras_chk.obs(
            f"{_RAS}-FABRIC",
            span="CHK-HOSTFABRIC-ARM_to_fw_end",
            rises=self._ras.rises_since(mf),
            falls=len(self._ras.fall_clks_since(mf)),
            level=self._ras.level(),
        )
        await self._ras.stop()
        await self._pulse.stop()

    def _class_release_mask(self, console: str) -> int:
        """CHK-ERR-CLASS: every firmware check that grades an error leg printed its PASS line."""
        lines = console.splitlines()
        mask = 0
        for needle, cells in _CLASS_CHECKS:
            if not any(ln.startswith(needle) for ln in lines):
                raise AssertionError(
                    f"CHK-ERR-CLASS FAIL: firmware console has no {needle!r} line, so its "
                    "error legs did not pass"
                )
            for cell in cells:
                mask |= 1 << cell
        self.logger.info(
            "CHK-ERR-CLASS PASS: firmware reported %s; release mask=0x%02x",
            ", ".join(needle.split()[0] for needle, _ in _CLASS_CHECKS),
            mask,
        )
        return mask

    def _parse_console(self) -> int:
        """Grade the firmware console after the run; returns the cell release mask."""
        cfg = self._dma_cfg
        needle = (
            f"SCENARIO src=0x{_SRAM_BASE + cfg.src_off:08x} "
            f"dst=0x{_SRAM_BASE + cfg.dst_off:08x} "
            f"nbytes=0x{cfg.nbytes:08x} "
            f"fill=0x{cfg.fill_seed:08x}"
        )
        console = self.sb.console_text()
        if needle not in console:
            raise AssertionError(
                "firmware did not consume the patched DMA cfg "
                f"(missing {needle!r} in console; patch was inert or the image is stale)"
            )
        mask = self._class_release_mask(console)
        if "CHK-HOSTINTG PASS:" not in console:
            raise AssertionError(
                "firmware console missing CHK-HOSTINTG PASS "
                "(host-path integrity contract was not proven)"
            )
        if "CHK-HOSTFABRIC PASS:" not in console:
            raise AssertionError(
                "firmware console missing CHK-HOSTFABRIC PASS "
                "(host-path fabric non-OKAY contract was not proven)"
            )
        # The two checkers that actually walk the modes and the widths. Logging
        # CHK-RAND-REP without them would put a PASS record in the kept log on a
        # run where the walk failed -- poll_boot returns normally on a firmware
        # FAIL, and the scoreboard verdict lands later.
        for needle, what in (
            ("CHK-COPY-MODE PASS:", "the INCR/FIXED/WRAP walk"),
            ("CHK-WIDTH PASS:", "the 1B/2B/4B width walk"),
            ("CHK-ERR-ASID PASS:", "the unencoded-ASID error legs"),
            ("CHK-ERR-SIZE PASS:", "the unencoded-width error leg"),
            ("CHK-ICCM PASS:", "the SRAM->ICCM->SRAM round trip"),
        ):
            if needle not in console:
                raise AssertionError(
                    f"firmware console missing {needle} ({what} did not pass), so "
                    "CHK-RAND-REP has nothing to report"
                )
        # Logged only: no document states the reserved register bits, so no check grades them.
        for tag in _OBS_LINES:
            obs = [ln for ln in console.splitlines() if ln.startswith(tag)]
            if not obs:
                raise AssertionError(f"firmware console has no {tag!r} line (stale image)")
            self.logger.info("%s firmware: %s", tag[:-1], obs[-1][len(tag) :].strip())
        return mask

    async def _release_cells(self, mask: int) -> None:
        """Release the held cp_error_class_exclusive cells of the passed checks."""
        dut = cocotb.top
        await RisingEdge(dut.clk_i)
        set_dma_basic_pass(mask, self.logger)
        await ClockCycles(dut.clk_i, 2)
        set_dma_basic_pass(0, self.logger)
        await RisingEdge(dut.clk_i)

    async def run_scenario(self) -> None:
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER
        dtcm = self._stage_dtcm()

        async def _open_window() -> None:
            # The CPU is released; every error leg the firmware runs from here
            # is graded stimulus of this leaf.
            set_dma_basic_pass(0, self.logger)
            open_graded_window("sep_dma_basic_test", self.logger)
            self._ras_start()

        try:
            inj = cocotb.start_soon(self._drive_host_intg_inject())
            fabric = cocotb.start_soon(self._check_host_fabric_pin())
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                dtcm,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
                after_bring_up_hook=_open_window,
            )
            if self._ras_task is None:
                for half in _RAS_HALVES:
                    self._ras_verdict(half, False, not_reached="the CPU was not released")
            else:
                await self._ras_task
            await inj
            await fabric
            if self._ras_task is not None:
                self._status_task.cancel()
                await self._lsu_tap.stop()
            mask = self._parse_console()
            if self._ras_chk.fails:
                raise AssertionError(
                    f"{len(self._ras_chk.fails)} RAS check(s) failed: "
                    + "; ".join(self._ras_chk.fails)
                )
        except BaseException:
            close_graded_window(self.logger)
            raise
        await self._release_cells(mask)
        close_graded_window(self.logger)
        cfg = self._dma_cfg
        self.logger.info(
            "CHK-RAND-REP PASS: walked INCR/FIXED/WRAP at 4B, widths 1B/2B/4B at INCR; "
            "seed=%d nbytes=%d",
            cfg.seed,
            cfg.nbytes,
        )
