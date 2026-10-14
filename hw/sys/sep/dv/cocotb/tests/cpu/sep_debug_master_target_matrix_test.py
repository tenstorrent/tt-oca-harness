# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The core JTAG TAP and DMI path: enable gates, the debug-module system bus and the debug reset.

The leaf drives the core TAP pins (added hook, ``jtag_bench_own_i`` = 1) through
``env/sep_jtag_dmi`` on the shared ``OcahJtagMasterDriver`` and reads the DMI
data from ``jtag_tdo_o``. It drives ``dmi_core_enable_i`` and
``dmi_uncore_enable_i`` (added hooks); the bench holds ``dmi_uncore_rdata`` at 0.
One module serves two testlist entries, both on the full-CPU build, because the
EL2 debug module exists only in the full ``sep_cpu``:

* Entry C (``cpu`` run mode, ``sep_debug_master_target_matrix_test``): the core
  runs a one-instruction spin loop at the boot ROM base (``jal x0, 0``, written
  into the ROM macro by backdoor before ``rst_ni`` rises). Steps 1 to 4 and 9 to
  12 of the procedure.
* Entry S (``no_cpu`` run mode on the ``default`` target,
  ``sep_debug_master_target_matrix_test_sba``): the core is held by
  ``mpc_reset_run_req`` = 0 and the bench LSU master on the LSU force splice is
  the independent register path. Steps 1 to 8, then the three local-alias legs.

Checks:
  CHK-DMI-GATE  : a write of ``dmcontrol.dmactive`` = 1 with
                  ``dmi_core_enable_i`` low does not land: after the enable
                  rises ``dmactive`` reads 0 (``hw/sys/sep/doc/port_table.adoc``,
                  ``dmi_core_enable_i``). Control: a write of 1 with the enable
                  high reads back 1. The read with the enable low is logged only.
  CHK-DBG-SBA   : (entry S) for each of the nine accesses (SRAM word 0 and its
                  local alias at 32 and 64 bits, ``WDOG_BARK_THOLD``, HMAC
                  ``MSG_LENGTH_LOWER``, ``SEP_SW_DEBUG``, cold scratch word 0,
                  secure DMA ``INTR_SRC_ADDR_0[0]`` at 32 bits), compared at the
                  full access width (field mask for a register): the
                  independent path (``sram_word0_probe_o`` or the bench LSU
                  master) reads the debug-master write value, and the value
                  before the write differs from it. The bench LSU master then
                  writes a second drawn value ``new`` that differs from the
                  write value in a graded bit and reads it back; the debug-master
                  read returns ``new`` in the one R beat on PR-DBG-SB (the lane
                  of the access) and in ``sbdata``, and the independent path
                  still reads ``new`` after it. ``sbdata`` holds the write value
                  from the write, so a read whose data never arrives fails.
                  ``sberror`` reads 0 after the write and after the read. On
                  PR-DBG-SB each access shows one write and one read record
                  with ID bits [2:1] = 0, and a 64-bit access one data beat in
                  each (``hw/sys/sep/doc/cpu.adoc``, chapter introduction).
  CHK-DMI-UNCORE: (entry C) with ``dmi_uncore_enable_i`` = 0,
                  ``dmi_uncore_en_o`` and ``dmi_uncore_wr_en_o`` are 0 on every
                  ``clk_i`` cycle from step 1 to the end of step 9, which holds
                  DMI reads and writes at 0x50 and 0x7F with the core enable
                  high and low (``hw/sys/sep/doc/port_table.adoc``). Control: in
                  the window with the enable at 1 ``dmi_uncore_en_o`` rises for a
                  read and a write and ``dmi_uncore_wr_en_o`` for the write.
  CHK-DBG-RST   : (entry C) after a ``dbg_rstb_i`` pulse ``dmactive`` reads 0, a
                  retirement follows on the trace port, and the
                  ``sep_cpu_reset_n`` and ``sep_reset_n`` taps stay high from
                  the start of the pulse to the readback
                  (``hw/sys/sep/doc/reset_controller.adoc``, SEP Reset
                  Controller). Controls: ``dmactive`` reads 1 before the pulse;
                  the ``wdt_rst_ni_i`` pulse of step 12 drops the
                  ``sep_cpu_reset_n`` tap; the cold reset holds the
                  ``sep_reset_n`` tap low until its release.
  CHK-DBG-ALIAS-MOVE : (entry S) after the bench LSU master moves
                  ``SEP_LOCAL_BASE_ADDR`` to the drawn base B, a debug-master
                  access at B (32 and 64 bits) reaches SRAM word 0: graded as
                  CHK-DBG-SBA, and on the PR-DBG-IN/PR-DBG-OUT tap pair at
                  ``u_dbg_local_alias_remap`` the input address B leaves as
                  0x1000_0000 (``hw/sys/sep/doc/memory_map.adoc``, local alias;
                  ``hw/sys/sep/doc/cpu.adoc``, chapter introduction).
  CHK-DBG-ALIAS-OLD  : (entry S) with the base at B, a debug-master read and
                  write at the old alias 0xD000_0000 pass the remap unchanged:
                  the PR-DBG-OUT address equals the PR-DBG-IN address.
  CHK-DBG-ALIAS-BELOW: (entry S) the same for B - 8, just below the moved window.
                  Control of both: in the CHK-DBG-ALIAS-MOVE leg the same tap
                  pair shows a rewritten address.

The expected values are the drawn write values, the addresses of the generated
register map and the alias rule of the specification; no expected value is
read from the DUT. The responses of the accesses outside the moved window
(OLD, BELOW) are logged only; the specification states no response for them.

Randomization (``SepSeededRng`` from the run seed): the order of the seven
targets, the size order of each SRAM target, every write value (redrawn while
it equals the value before the write), the LSU value ``new`` of each access
(redrawn while it equals the write value in the graded bits), the set-up value
of SRAM word 0, the moved base B (16 MiB aligned, 0xD100_0000 to 0xEF00_0000,
so the reset alias and B - 8 are below the moved window and every moved alias
is below 2**32) and the size order of the moved-alias leg.

VCS only (``tools = ["vcs"]``), ``+skip_fuse_sense``. The leaf fails on a build
without the full ``sep_cpu``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_fabric_tap import SepFabricTap, TapMark
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare, lane32
from env.sep_jtag_dmi import (
    DM_DMCONTROL,
    DMCONTROL_DMACTIVE,
    IR_DMI,
    IR_WIDTH,
    PIN_MAP,
    DmiError,
    SepJtagDmi,
)
from env.sep_seeded_rng import SepSeededRng
from ocah_jtag_vip import OcahJtagMasterDriver
from sep_base_test import sep_base_test
from sep_reg_meta import RegBlock, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

TEST = "sep_debug_master_target_matrix_test"

_CPU_CTRL = RegBlock("SEP_CPU_CTRL")
_WDT = RegBlock("WDT_TIMER")
WDT_BARK = _WDT.addr("WDOG_BARK_THOLD")
_HMAC = RegBlock("HMAC")
_COLD = RegBlock("SEP_SCRATCH_COLD")
_DMA = RegBlock("SECURE_DMA")

ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
SRAM_WORD = sym("SEP_SRAM_MEM_BASE_ADDR")  # SRAM word 0: sram_word0_probe_o
# hw/sys/sep/doc/memory_map.adoc: 0xD000_0000 aliases 0x1000_0000; the alias of a
# direct address is the window base plus its offset from 0x1000_0000.
ALIAS_TARGET = 0x1000_0000
LOCAL_BASE_ADDR = _CPU_CTRL.addr("SEP_LOCAL_BASE_ADDR")
LOCAL_BASE_RESET = _CPU_CTRL.reset("SEP_LOCAL_BASE_ADDR")
OLD_ALIAS = LOCAL_BASE_RESET + (SRAM_WORD - ALIAS_TARGET)
if SRAM_WORD % 8:
    raise RuntimeError("SRAM word 0 is not 8-byte aligned")

# Moved window base B (16 MiB aligned in [MOVED_LO, MOVED_HI]).
MOVED_LO = 0xD100_0000
MOVED_HI = 0xEF00_0000
MOVED_ALIGN = 0x0100_0000
if MOVED_LO <= OLD_ALIAS:
    raise RuntimeError("the reset alias of the SRAM word is not below the moved window")

# The five register targets, 32-bit only: (name, address, RDL field mask of the word).
REG_TARGETS = (
    ("WDOG_BARK_THOLD", _WDT.addr("WDOG_BARK_THOLD"), _WDT.mask("WDOG_BARK_THOLD")),
    ("HMAC_MSG_LENGTH_LOWER", _HMAC.addr("MSG_LENGTH_LOWER"), _HMAC.mask("MSG_LENGTH_LOWER")),
    ("SEP_SW_DEBUG", _CPU_CTRL.addr("SEP_SW_DEBUG"), _CPU_CTRL.mask32("SEP_SW_DEBUG")),
    ("SCRATCH_COLD_0", _COLD.addr("SCRATCH_0_"), _COLD.mask("SCRATCH_0_")),
    (
        "DMA_INTR_SRC_ADDR_0_0",
        sym("SECURE_DMA_INTR_SRC_ADDR_0_0__REG_ADDR"),
        _DMA.mask("INTR_SRC_ADDR_0"),
    ),
)
SRAM_TARGETS = (("SRAM_WORD", SRAM_WORD), ("SRAM_ALIAS", OLD_ALIAS))
for _n, _a, _m in REG_TARGETS:
    if _a % 4 or (_m & 0xFFFF_FFFF) == 0:
        raise RuntimeError(f"{_n}: not a 32-bit register word")

# Environment choices (logged).
TCK_CLKS = 4  # clk_i periods per TCK period
TRST_TCK = 4  # TCK cycles of the jtag_trst_ni pulse
RETIRE_BOUND = 20_000  # clk_i cycles for a retirement on the trace port
PULSE_CLKS = 16  # clk_i cycles of the dbg_rstb_i and wdt_rst_ni_i pulses (test parameter)
TAP_BOUND = 2_000  # clk_i cycles for the sep_cpu_reset_n fall and rise
RST_HOLD = 20  # clk_i cycles of rst_ni low at bring-up
SETTLE = 8  # clk_i cycles after a system-bus access before a tap is read
# sbcs reads while sbbusy is 1 (and DMI busy retries). A watchdog register sits in
# the clk_wdt_i domain (5 us period on this bench), so its access waits for the
# register CDC; 1024 reads of about 0.5 us each bound it with margin.
SB_BUSY_READS = 1024
# Bench-LSU timeout for a watchdog register access, in clk_wdt_i periods: the access
# waits for the register CDC of the previous write (about 11 to 17 periods here).
WDT_CDC_CLKS = 50
UNCORE_ADDRS = (0x50, 0x7F)  # lowest and highest 7-bit DMI address at or above 0x50
SPIN_LOOP = 0x0000_006F  # jal x0, 0


@dataclass
class _Access:
    target: str
    addr: int
    size: int
    mask: int
    before: int = 0
    wr: int = 0
    mid: int = 0
    new: int = 0
    new_rb: int = 0
    rd: int | None = None
    after: int | None = None
    sberr: tuple[int, int] = (0, 0)
    sb: tuple = ()
    pair: tuple = ()


class _CountingDmi(SepJtagDmi):
    """SepJtagDmi that records every DMI read and write with the enable levels."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.log_accesses: list[tuple[int, int, int, int]] = []

    async def _dmi_access(self, addr: int, data: int, op: int) -> int:
        dut = self.dut
        self.log_accesses.append(
            (addr, op, int(dut.dmi_core_enable_i.value), int(dut.dmi_uncore_enable_i.value))
        )
        return await super()._dmi_access(addr, data, op)


@pyuvm.test()
class sep_debug_master_target_matrix_test(sep_base_test):
    """DMI enable gates, debug-module system-bus targets and the debug reset."""

    def build_phase(self) -> None:
        # Entry S uses the bench LSU master as the independent register path; in
        # entry C the core owns the LSU.
        self.entry_c = "cpu_boot" in cocotb.plusargs
        self.build_env = not self.entry_c
        super().build_phase()

    # ---------------------------------------------------------------- set-up
    def _draw(self) -> None:
        seed = self.random_seed()
        self.rng = SepSeededRng(seed)
        self.logger.info("SEED seed=%d", seed)
        rng = self.rng
        targets = [n for n, _ in SRAM_TARGETS] + [n for n, _, _ in REG_TARGETS]
        rng.shuffle(targets)
        self.sram_sizes = {}
        for name, _ in SRAM_TARGETS:
            sizes = [4, 8]
            rng.shuffle(sizes)
            self.sram_sizes[name] = sizes
        self.target_order = targets
        self.sram_init = rng.getrandbits(64)
        self.moved_base = MOVED_LO + MOVED_ALIGN * rng.randrange(
            (MOVED_HI - MOVED_LO) // MOVED_ALIGN + 1
        )
        moved_sizes = [4, 8]
        rng.shuffle(moved_sizes)
        self.moved_sizes = moved_sizes
        self.logger.info("DRAW target_order=%s", ",".join(targets))
        self.logger.info(
            "DRAW sram_sizes=%s",
            " ".join(f"{n}:{'/'.join(str(s) for s in v)}" for n, v in self.sram_sizes.items()),
        )
        self.logger.info("DRAW sram_init=0x%016x", self.sram_init)
        self.logger.info(
            "DRAW moved_base=0x%08x moved_sizes=%s",
            self.moved_base,
            "/".join(str(s) for s in moved_sizes),
        )
        self.logger.info(
            "ENV tck_clks=%d trst_tck=%d retire_bound=%d pulse_clks=%d tap_bound=%d "
            "rst_hold=%d settle=%d sb_busy_reads=%d uncore_addrs=%s",
            TCK_CLKS,
            TRST_TCK,
            RETIRE_BOUND,
            PULSE_CLKS,
            TAP_BOUND,
            RST_HOLD,
            SETTLE,
            SB_BUSY_READS,
            ",".join(f"0x{a:02x}" for a in UNCORE_ADDRS),
        )

    def _draw_value(self, size: int, before: int) -> int:
        """A write value of the full access width that differs from ``before``."""
        bits = 8 * size
        while True:
            v = self.rng.getrandbits(bits)
            if v != before:
                return v

    # ---------------------------------------------------------------- sampler
    async def _sampler(self) -> None:
        """Per clk_i: reset taps, trace port, DMI uncore outputs."""
        dut = cocotb.top
        prev_cpu = None
        while not self._stop:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.clk += 1
            cpu_tap = self.rd(dut.sep_cpu_reset_n_o)
            sep_tap = self.rd(dut.dbg_sep_reset_n_o)
            if not self.released:
                self.cold_sep_low += sep_tap == 0
            if self.entry_c and self.rd(dut.cpu_trace_valid_o):
                self.retired += 1
            if self.dbg_window:
                self.dbg_samples += 1
                self.dbg_cpu_low += cpu_tap == 0
                self.dbg_sep_low += sep_tap == 0
            if prev_cpu == 1 and cpu_tap == 0:
                self.cpu_falls += 1
            if prev_cpu == 0 and cpu_tap == 1:
                self.cpu_rises += 1
            prev_cpu = cpu_tap
            if self.uncore_armed:
                en = self.rd(dut.dmi_uncore_en_o)
                wr = self.rd(dut.dmi_uncore_wr_en_o)
                if self.uncore_never:
                    self.never_cycles += 1
                    self.never_en += en
                    self.never_wr += wr
                if self.uncore_ctl is not None:
                    self.uncore_ctl["en"] += en and not self.prev_en
                    self.uncore_ctl["wr"] += wr and not self.prev_wr
                self.prev_en, self.prev_wr = en, wr

    def _pair_mark(self) -> tuple[TapMark, TapMark]:
        return self.din_tap.mark(), self.dout_tap.mark()

    def _pair_since(self, mark: tuple[TapMark, TapMark]) -> tuple[list, list]:
        pin = [(b.ch, b.addr) for b in self.din_tap.since(mark[0])]
        pout = [(b.ch, b.addr) for b in self.dout_tap.since(mark[1])]
        return pin, pout

    # ---------------------------------------------------------------- grading
    def _grade(self, chk: str, ok: bool, text: str) -> None:
        self.n_checks += 1
        if ok:
            self.logger.info("%s PASS: %s", chk, text)
        else:
            self.logger.error("%s FAIL: %s", chk, text)
            self.failures.append(f"{chk}: {text}")

    # ---------------------------------------------------------------- bring-up
    def _stage_rom(self) -> None:
        mem = cocotb.top.u_dut.u_sep_ip_integration.u_sep_boot_rom.mem
        mem[0].value = (SPIN_LOOP << 32) | SPIN_LOOP
        self.logger.info(
            "STAGE rom word0=0x%016x (jal x0, 0 at 0x%08x)", int(mem[0].value), ROM_BASE
        )

    async def _bring_up(self) -> None:
        """Step 1: cold reset with dbg_rstb_i low until the rst_ni release."""
        dut = cocotb.top
        if self.entry_c:

            async def _hook() -> None:
                self._stage_rom()
                cocotb.start_soon(self._sampler())

            await self.bring_up_cpu_boot(0, pre_reset_hook=_hook)
        else:
            self.drive_idle_defaults(dut, cpu_run=False)
            await self.assert_cold_reset(dut)
            self._set_pin(dut, "dbg_rstb_i", 0)
            self.start_clocks(dut)
            cocotb.start_soon(self._sampler())
            await ClockCycles(dut.clk_i, RST_HOLD)
            dut.rst_ni.value = 1
            self._set_pin(dut, "dbg_rstb_i", 1)
            await ClockCycles(dut.clk_i, 2)
            self.cfg.reset_done.set()
            await self.wait_fuse_sense()
        # The sampler counts the sep_reset_n tap low cycles until here.
        self.released = True
        self.logger.info(
            "CTL-COLD: sep_reset_n tap low for %d clk_i cycles of the cold reset",
            self.cold_sep_low,
        )

    async def _tap_setup(self) -> None:
        """Step 1: TAP pins to the bench, TRST pulse, Run-Test/Idle, DMI selected."""
        dut = cocotb.top
        tap = OcahJtagMasterDriver(
            dut,
            name="sep_core_tap",
            tck_period_ns=int(round(TCK_CLKS * self.cfg.sys_clk_period_ns * 1000)),
            ir_width=IR_WIDTH,
            tap_type="dtm",
            signal_map=dict(PIN_MAP),
            time_unit="ps",
        )
        self.dmi = _CountingDmi(tap, dut=dut, log=self.logger, busy_bound=SB_BUSY_READS)
        self.dmi.take_pins()
        await self.dmi.trst_pulse(tck_cycles=TRST_TCK)
        await tap.goto_state("RUN_TEST_IDLE")
        await tap.shift_ir(IR_DMI, IR_WIDTH, back_to_rti=True)
        dtmcs = await self.dmi.read_dtmcs()
        self.logger.info("OBS-DTMCS: dtmcs=0x%08x (logged only)", dtmcs)

    async def _wait_retire(self, after: int, what: str) -> int:
        for _ in range(RETIRE_BOUND):
            if self.retired > after:
                return self.retired
            await RisingEdge(cocotb.top.clk_i)
        raise AssertionError(f"{what}: no retirement within {RETIRE_BOUND} clk_i cycles")

    # ---------------------------------------------------------------- steps 2-4
    async def _gate(self) -> None:
        dut = cocotb.top
        open_graded_window(TEST, self.logger)
        # Step 2: the write with the enable low; the read is logged only.
        dut.dmi_core_enable_i.value = 0
        await self.dmi.dmi_write(DM_DMCONTROL, DMCONTROL_DMACTIVE)
        gated_rd = await self.dmi.dmi_read(DM_DMCONTROL)
        # Step 3.
        dut.dmi_core_enable_i.value = 1
        await ClockCycles(dut.clk_i, 2)
        after = await self.dmi.dmi_read(DM_DMCONTROL)
        close_graded_window(self.logger)
        # Step 4: control with the enable high.
        await self.dmi.dmi_write(DM_DMCONTROL, DMCONTROL_DMACTIVE)
        ctl = await self.dmi.dmi_read(DM_DMCONTROL)
        enabled_rd_after = after & DMCONTROL_DMACTIVE
        control_rd = ctl & DMCONTROL_DMACTIVE
        self._grade(
            "CHK-DMI-GATE",
            enabled_rd_after == 0 and control_rd == 1,
            f"gated_wr=1 enabled_rd_after={enabled_rd_after} control_wr=1 "
            f"control_rd={control_rd} gated_rd_obs=0x{gated_rd:08x} "
            f"dmcontrol_after=0x{after:08x} dmcontrol_control=0x{ctl:08x}",
        )

    # ---------------------------------------------------------------- entry S
    async def _lsu(self, op: SepAxiOp, addr: int, data: int = 0, length: int = 4) -> int:
        seq = SepAxiAccessSeq(
            f"dbgm_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=data,
            length=length,
            size=2 if length == 4 else 3,
            allow_unverified_write_resp=op is SepAxiOp.WRITE,
            allow_ungraded_read_resp=op is SepAxiOp.READ,
        )
        # A watchdog register access waits for the clk_wdt_i register CDC of the
        # previous write, which is longer than the default bus timeout.
        saved = self.cfg.axi_timeout_ns
        if addr == WDT_BARK:
            self.cfg.axi_timeout_ns = max(saved, WDT_CDC_CLKS * self.cfg.wdt_clk_period_ns)
        try:
            await self.start_seq(seq)
        finally:
            self.cfg.axi_timeout_ns = saved
        if seq.timed_out:
            raise AssertionError(f"LSU {op.value} @0x{addr:08x} got no response")
        if seq.resp_code != 0:
            raise AssertionError(f"LSU {op.value} @0x{addr:08x} resp={seq.resp_code}")
        return int(seq.rdata) & ((1 << (8 * length)) - 1)

    def _probe(self, size: int) -> int:
        word = self.rd(cocotb.top.sram_word0_probe_o)
        return word & ((1 << (8 * size)) - 1)

    @staticmethod
    def _is_sram(acc: _Access) -> bool:
        return acc.target in ("SRAM_WORD", "SRAM_ALIAS", "MOVED_ALIAS")

    async def _independent(self, acc: _Access) -> int:
        if self._is_sram(acc):
            return self._probe(acc.size)
        return await self._lsu(SepAxiOp.READ, acc.addr)

    async def _independent_write(self, acc: _Access, value: int) -> None:
        """Write the location by the bench LSU master (SRAM word at its direct address)."""
        addr = SRAM_WORD if self._is_sram(acc) else acc.addr
        await self._lsu(SepAxiOp.WRITE, addr, value, length=acc.size)
        await ClockCycles(cocotb.top.clk_i, SETTLE)

    def _draw_new(self, acc: _Access) -> int:
        """A value that differs from the debug-master write value in a graded bit."""
        while True:
            v = self.rng.getrandbits(8 * acc.size)
            if (v ^ acc.wr) & acc.mask:
                return v

    async def _sba_access(self, acc: _Access) -> None:
        """Step 7: before, debug write, CPU-path value, LSU write, debug read, after.

        Between the debug-master write and the debug-master read the bench LSU
        master writes a second drawn value, so the read value differs from the
        value that ``sbdata`` holds from the write.
        """
        acc.before = await self._independent(acc)
        acc.wr = self._draw_value(acc.size, acc.before)
        sb_mark = self.sb_tap.mark()
        lx_mark = self.lx_tap.mark()
        pair_mark = self._pair_mark()
        try:
            werr = await self.dmi.sba_write(acc.addr, acc.wr, size=acc.size)
            await ClockCycles(cocotb.top.clk_i, SETTLE)
            acc.mid = await self._independent(acc)
            acc.new = self._draw_new(acc)
            await self._independent_write(acc, acc.new)
            acc.new_rb = await self._independent(acc)
            acc.rd, rerr = await self.dmi.sba_read(acc.addr, size=acc.size)
        except DmiError:
            pin, pout = self._pair_since(pair_mark)
            self.logger.error(
                "SBA-STALL FAIL: target=%s addr=0x%08x size=%d dbg_sb=%s dbg_in=%s dbg_out=%s",
                acc.target,
                acc.addr,
                acc.size,
                " ".join(x.fmt() for x in self.sb_tap.since(sb_mark)) or "-",
                pin,
                pout,
            )
            self.logger.error(
                "SBA-STALL FAIL: lsu_xbar=%s rvalid=%s rready=%s",
                " ".join(x.fmt() for x in self.lx_tap.since(lx_mark)) or "-",
                cocotb.top.pr_dbg_sb_rvalid_o.value,
                cocotb.top.pr_dbg_sb_rready_o.value,
            )
            raise
        acc.sberr = (werr, rerr)
        await ClockCycles(cocotb.top.clk_i, SETTLE)
        acc.after = await self._independent(acc)
        acc.sb = tuple(self.sb_tap.since(sb_mark))
        acc.pair = self._pair_since(pair_mark)

    def _sb_shape(self, acc: _Access) -> tuple[bool, str]:
        beats = acc.sb
        aw = [b for b in beats if b.ch == "aw"]
        ar = [b for b in beats if b.ch == "ar"]
        w = [b for b in beats if b.ch == "w"]
        r = [b for b in beats if b.ch == "r"]
        bb = [b for b in beats if b.ch == "b"]
        ids = [b.id for b in aw + ar + bb + r]
        id_hi = 0
        for i in ids:
            id_hi |= 0b11 if i is None else (i >> 1) & 0b11
        ok = len(aw) == 1 and len(ar) == 1 and bool(ids) and id_hi == 0
        if acc.size == 8:
            ok = ok and len(w) == 1 and len(r) == 1
        text = (
            f"id_hi=0b{id_hi:02b} beats=w{len(w)}/r{len(r)} records=aw{len(aw)}/ar{len(ar)} "
            f"bus_aw=0x{(aw[0].addr or 0) if aw else 0:08x} "
            f"bus_ar=0x{(ar[0].addr or 0) if ar else 0:08x} "
            f"axsize={aw[0].size if aw else 'X'}"
        )
        return ok, text

    @staticmethod
    def _r_beat(acc: _Access) -> tuple[int | None, int | None]:
        """(data, resp) of the one R beat of the access on PR-DBG-SB.

        The data is the lane of the access (``lane32`` for 4 bytes, the whole
        beat for 8). None when the access has no R beat, more than one, or a
        data or response field that holds X or Z.
        """
        r = [b for b in acc.sb if b.ch == "r"]
        if len(r) != 1:
            return None, None
        data, resp = r[0].data, r[0].resp
        if data is not None and acc.size == 4:
            data = lane32(data, acc.addr)
        return data, resp

    def _value_ok(self, acc: _Access) -> tuple[bool, str]:
        # Write leg: the CPU path reads the debug-master write value. Read leg:
        # the bench LSU master then writes ``new``, and the R beat of the
        # debug-master read on PR-DBG-SB and the sbdata readback both carry
        # ``new``. sbdata holds ``wr`` from the write, and ``new`` differs from
        # ``wr`` in a graded bit, so a read whose data never arrives fails.
        r_data, r_resp = self._r_beat(acc)
        mask = acc.mask
        pairs = (
            ("cpu_path", acc.mid, acc.wr),
            ("new_rb", acc.new_rb, acc.new),
            ("r_data", r_data, acc.new),
            ("rd", acc.rd, acc.new),
            ("cpu_path_end", acc.after, acc.new),
        )
        ok = True
        rsvd = []
        for name, got, exp in pairs:
            if got is None:
                ok = False
                rsvd.append(f"rsvd_{name}=X")
                continue
            c = field_compare(got, exp, mask)
            ok = ok and c.ok
            rsvd.append(f"rsvd_{name}=0x{c.rsvd:x}")
        if self._is_sram(acc):
            cmp = f"mask=0x{mask:x}"
        else:
            cmp = f"field_mask=0x{mask:x} " + " ".join(rsvd)
        ok = ok and acc.before != acc.wr and acc.sberr == (0, 0)
        w = 2 * acc.size

        def h(v: int | None) -> str:
            return "X" if v is None else f"0x{v:0{w}x}"

        text = (
            f"target={acc.target} addr=0x{acc.addr:08x} size={acc.size} "
            f"before={h(acc.before)} wr={h(acc.wr)} cpu_path={h(acc.mid)} "
            f"new={h(acc.new)} new_rb={h(acc.new_rb)} r_data={h(r_data)} rd={h(acc.rd)} "
            f"cpu_path_end={h(acc.after)} sberror_wr={acc.sberr[0]} sberror_rd={acc.sberr[1]} "
            f"rresp_obs={'X' if r_resp is None else r_resp} {cmp}"
        )
        return ok, text

    async def _sba_matrix(self) -> None:
        """Steps 5 to 8: nine accesses in the drawn order, graded after the monitor stops."""
        dut = cocotb.top
        dut.dmi_core_enable_i.value = 1
        # Set-up: SRAM word 0 holds a known value before the first access.
        await self._lsu(SepAxiOp.WRITE, SRAM_WORD, self.sram_init, length=8)
        await ClockCycles(dut.clk_i, SETTLE)
        got = self._probe(8)
        if got != self.sram_init:
            raise AssertionError(
                f"set-up: SRAM word 0 reads 0x{got:016x}, wrote 0x{self.sram_init:016x}"
            )
        self.logger.info("CTL-SRAM-INIT: sram_word0=0x%016x", got)
        # Step 5.
        self.sb_tap = SepFabricTap("PR-DBG-SB").start()
        self.lx_tap = SepFabricTap("PR-LSU-XBAR").start()
        self.din_tap = SepFabricTap("PR-DBG-IN").start()
        self.dout_tap = SepFabricTap("PR-DBG-OUT").start()
        open_graded_window(TEST, self.logger)
        accs: list[_Access] = []
        addrs = dict(SRAM_TARGETS)
        regs = {n: (a, m) for n, a, m in REG_TARGETS}
        for name in self.target_order:
            if name in addrs:
                for size in self.sram_sizes[name]:
                    acc = _Access(name, addrs[name], size, (1 << (8 * size)) - 1)
                    await self._sba_access(acc)
                    accs.append(acc)
            else:
                a, m = regs[name]
                acc = _Access(name, a, 4, m & 0xFFFF_FFFF)
                await self._sba_access(acc)
                accs.append(acc)
        close_graded_window(self.logger)
        # Step 8.
        await self.sb_tap.stop()
        if len(accs) != 9:
            raise AssertionError(f"{len(accs)} accesses ran, expected 9")
        for acc in accs:
            v_ok, v_text = self._value_ok(acc)
            s_ok, s_text = self._sb_shape(acc)
            self._grade("CHK-DBG-SBA", v_ok and s_ok, f"{v_text} {s_text}")
            pin, pout = acc.pair
            self.logger.info(
                "OBS-DBG-PAIR: target=%s in=%s out=%s",
                acc.target,
                ",".join(f"{c}:0x{a:08x}" for c, a in pin),
                ",".join(f"{c}:0x{a:08x}" for c, a in pout),
            )

    @staticmethod
    def _rewritten(acc: _Access) -> bool:
        pin, pout = acc.pair
        return bool(pin) and len(pin) == len(pout) and any(i[1] != o[1] for i, o in zip(pin, pout))

    async def _alias_legs(self) -> None:
        """The moved local-alias legs: MOVE, OLD and BELOW."""
        base = self.moved_base
        # Set-up: move the window with the bench LSU master and read it back.
        await self._lsu(SepAxiOp.WRITE, LOCAL_BASE_ADDR, base)
        rb = await self._lsu(SepAxiOp.READ, LOCAL_BASE_ADDR)
        if rb != base:
            raise AssertionError(
                f"set-up: SEP_LOCAL_BASE_ADDR reads 0x{rb:08x}, wrote 0x{base:08x}"
            )
        self.logger.info("CTL-BASE-MOVE: SEP_LOCAL_BASE_ADDR=0x%08x readback=0x%08x", base, rb)
        self.sb_tap = SepFabricTap("PR-DBG-SB").start()
        open_graded_window(TEST, self.logger)
        moved_addr = base + (SRAM_WORD - ALIAS_TARGET)
        moved: list[_Access] = []
        for size in self.moved_sizes:
            acc = _Access("MOVED_ALIAS", moved_addr, size, (1 << (8 * size)) - 1)
            await self._sba_access(acc)
            moved.append(acc)
        legs = {}
        for chk, addr in (
            ("CHK-DBG-ALIAS-OLD", OLD_ALIAS),
            ("CHK-DBG-ALIAS-BELOW", base - 8),
        ):
            probe0 = self._probe(8)
            pair_mark = self._pair_mark()
            val = self.rng.getrandbits(32)
            werr = await self.dmi.sba_write(addr, val, size=4)
            rd, rerr = await self.dmi.sba_read(addr, size=4)
            await ClockCycles(cocotb.top.clk_i, SETTLE)
            legs[chk] = (
                addr,
                val,
                werr,
                rd,
                rerr,
                probe0,
                self._probe(8),
                self._pair_since(pair_mark),
            )
        close_graded_window(self.logger)
        await self.sb_tap.stop()
        await self.din_tap.stop()
        await self.dout_tap.stop()

        for acc in moved:
            v_ok, v_text = self._value_ok(acc)
            s_ok, s_text = self._sb_shape(acc)
            pin, pout = acc.pair
            exp_out = SRAM_WORD
            p_ok = (
                sorted(c for c, _ in pin) == ["ar", "aw"]
                and sorted(c for c, _ in pout) == ["ar", "aw"]
                and all(a == acc.addr for _, a in pin)
                and all(a == exp_out for _, a in pout)
            )
            self._grade(
                "CHK-DBG-ALIAS-MOVE",
                v_ok and s_ok and p_ok,
                f"base=0x{base:08x} {v_text} {s_text} "
                f"dbg_in={','.join(f'{c}:0x{a:08x}' for c, a in pin)} "
                f"dbg_out={','.join(f'{c}:0x{a:08x}' for c, a in pout)} "
                f"expected_out=0x{exp_out:08x}",
            )
        control = int(all(self._rewritten(a) for a in moved) and bool(moved))
        for chk, (addr, val, werr, rd, rerr, p0, p1, (pin, pout)) in legs.items():
            ok = (
                sorted(c for c, _ in pin) == ["ar", "aw"]
                and sorted(c for c, _ in pout) == ["ar", "aw"]
                and all(a == addr for _, a in pin)
                and pout == pin
                and control == 1
            )
            self._grade(
                chk,
                ok,
                f"base=0x{base:08x} addr=0x{addr:08x} "
                f"dbg_in={','.join(f'{c}:0x{a:08x}' for c, a in pin)} "
                f"dbg_out={','.join(f'{c}:0x{a:08x}' for c, a in pout)} "
                f"control_rewrite={control}",
            )
            self.logger.info(
                "OBS-ALIAS-OUTSIDE: %s addr=0x%08x wr=0x%08x sberror_wr=%d rd=0x%08x sberror_rd=%d "
                "sram_word0=0x%016x->0x%016x",
                chk,
                addr,
                val,
                werr,
                rd,
                rerr,
                p0,
                p1,
            )
        # Clean-up: the window back at its reset base.
        await self._lsu(SepAxiOp.WRITE, LOCAL_BASE_ADDR, LOCAL_BASE_RESET & 0xFFFF_FFFF)
        rb = await self._lsu(SepAxiOp.READ, LOCAL_BASE_ADDR)
        self.logger.info("CTL-BASE-RESTORE: SEP_LOCAL_BASE_ADDR readback=0x%08x", rb)

    # ---------------------------------------------------------------- entry C
    async def _uncore_never(self) -> None:
        """Step 9: accesses at 0x50 and 0x7F with the core enable high, then low."""
        dut = cocotb.top
        open_graded_window(TEST, self.logger)
        for core_en in (1, 0):
            dut.dmi_core_enable_i.value = core_en
            await ClockCycles(dut.clk_i, 2)
            for addr in UNCORE_ADDRS:
                rd = await self.dmi.dmi_read(addr)
                await self.dmi.dmi_write(addr, self.rng.getrandbits(32))
                self.logger.info(
                    "OBS-UNCORE-RD: core_en=%d addr=0x%02x rdata=0x%08x", core_en, addr, rd
                )
        dut.dmi_core_enable_i.value = 1
        await ClockCycles(dut.clk_i, SETTLE)
        close_graded_window(self.logger)
        self.uncore_never = False

    async def _uncore_control(self) -> dict[str, int]:
        """Step 10: the read and the write at 0x50 with dmi_uncore_enable_i at 1."""
        dut = cocotb.top
        dut.dmi_uncore_enable_i.value = 1
        await ClockCycles(dut.clk_i, 2)
        res = {}
        self.uncore_ctl = {"en": 0, "wr": 0}
        rd = await self.dmi.dmi_read(UNCORE_ADDRS[0])
        await ClockCycles(dut.clk_i, SETTLE)
        res["rd_en"], res["rd_wr"] = self.uncore_ctl["en"], self.uncore_ctl["wr"]
        self.uncore_ctl = {"en": 0, "wr": 0}
        await self.dmi.dmi_write(UNCORE_ADDRS[0], self.rng.getrandbits(32))
        await ClockCycles(dut.clk_i, SETTLE)
        res["wr_en"], res["wr_wr"] = self.uncore_ctl["en"], self.uncore_ctl["wr"]
        self.uncore_ctl = None
        dut.dmi_uncore_enable_i.value = 0
        await ClockCycles(dut.clk_i, 2)
        self.logger.info("OBS-UNCORE-CTL-RD: rdata=0x%08x (bench holds 0)", rd)
        return res

    def _grade_uncore(self, ctl: dict[str, int]) -> None:
        never = [a for a in self.dmi.log_accesses[: self.n_never_acc] if a[3] == 0]
        upper = [a for a in never if a[0] >= 0x50]
        upper_core = sorted({a[2] for a in upper})
        ok = (
            self.never_en == 0
            and self.never_wr == 0
            and self.never_cycles > 0
            and len(upper) == 4 * len(UNCORE_ADDRS)
            and upper_core == [0, 1]
            and ctl["rd_en"] >= 1
            and ctl["wr_en"] >= 1
            and ctl["wr_wr"] >= 1
        )
        self._grade(
            "CHK-DMI-UNCORE",
            ok,
            f"en_o_cycles={self.never_en} wr_en_o_cycles={self.never_wr} "
            f"accesses={len(never)} at_or_above_0x50={len(upper)} "
            f"control_en_o_rise={ctl['rd_en'] + ctl['wr_en']} "
            f"control_wr_en_o_rise={ctl['wr_wr']} window_cycles={self.never_cycles} "
            f"control_read_en_o_rise={ctl['rd_en']} control_read_wr_en_o_rise={ctl['rd_wr']} "
            f"control_write_en_o_rise={ctl['wr_en']} upper_core_enable={upper_core}",
        )

    async def _dbg_reset(self) -> dict[str, int]:
        """Step 11: dbg_rstb_i pulse with dmactive set."""
        dut = cocotb.top
        before = await self.dmi.dmi_read(DM_DMCONTROL)
        open_graded_window(TEST, self.logger)
        await RisingEdge(dut.clk_i)
        self.dbg_window = True
        dut.dbg_rstb_i.value = 0
        await ClockCycles(dut.clk_i, PULSE_CLKS)
        dut.dbg_rstb_i.value = 1
        at_release = self.retired
        await self._wait_retire(at_release, "after dbg_rstb_i")
        after = await self.dmi.dmi_read(DM_DMCONTROL)
        self.dbg_window = False
        close_graded_window(self.logger)
        return {
            "before": before & DMCONTROL_DMACTIVE,
            "after": after & DMCONTROL_DMACTIVE,
            "pc_advance": self.retired - at_release,
            "cpu_low": self.dbg_cpu_low,
            "sep_low": self.dbg_sep_low,
            "samples": self.dbg_samples,
        }

    async def _wdt_control(self) -> int:
        """Step 12: wdt_rst_ni_i pulse; the sep_cpu_reset_n tap falls and rises."""
        dut = cocotb.top
        falls0, rises0 = self.cpu_falls, self.cpu_rises
        await RisingEdge(dut.clk_i)
        dut.wdt_rst_ni_i.value = 0
        await ClockCycles(dut.clk_i, PULSE_CLKS)
        dut.wdt_rst_ni_i.value = 1
        for _ in range(TAP_BOUND):
            if self.cpu_falls > falls0 and self.cpu_rises > rises0:
                return 1
            await RisingEdge(dut.clk_i)
        self.logger.info(
            "OBS-WDT-CONTROL: sep_cpu_reset_n tap falls=%d rises=%d within %d clk_i cycles",
            self.cpu_falls - falls0,
            self.cpu_rises - rises0,
            TAP_BOUND,
        )
        return 0

    # ---------------------------------------------------------------- scenario
    async def run_scenario(self) -> None:
        dut = cocotb.top
        if not self.full_cpu_build():
            msg = "CTL-FULL-CPU FAIL: the build has the CPU stub, which has no EL2 debug module"
            self.logger.error(msg)
            raise AssertionError(msg)
        self.clk = 0
        self._stop = False
        self.released = False
        self.cold_sep_low = 0
        self.retired = 0
        self.dbg_window = False
        self.dbg_samples = self.dbg_cpu_low = self.dbg_sep_low = 0
        self.cpu_falls = self.cpu_rises = 0
        self.uncore_armed = False
        self.uncore_never = False
        self.uncore_ctl = None
        self.never_cycles = self.never_en = self.never_wr = 0
        self.prev_en = self.prev_wr = 0
        self.failures: list[str] = []
        self.n_checks = 0
        if self.entry_c:
            self.required_evidence = ("CHK-DMI-GATE", "CHK-DMI-UNCORE", "CHK-DBG-RST")
        else:
            self.required_evidence = (
                "CHK-DMI-GATE",
                "CHK-DBG-SBA",
                "CHK-DBG-ALIAS-MOVE",
                "CHK-DBG-ALIAS-OLD",
                "CHK-DBG-ALIAS-BELOW",
            )
        self.logger.info(
            "OBS-BUILD: entry=%s full_cpu=1 required_evidence=%s",
            "C" if self.entry_c else "S",
            ",".join(self.required_evidence),
        )
        self._draw()

        await self._bring_up()
        await self._tap_setup()
        if self.entry_c:
            # The uncore never window covers every DMI access from step 1.
            self.uncore_armed = True
            self.uncore_never = True
            first = await self._wait_retire(0, "first retirement after the cold reset")
            self.logger.info("CTL-RETIRE: first retirement seen (count %d)", first)
        await self._gate()
        if self.entry_c:
            await self._uncore_never()
            self.n_never_acc = len(self.dmi.log_accesses)
            ctl = await self._uncore_control()
            self._grade_uncore(ctl)
            dbg = await self._dbg_reset()
            wdt_low = await self._wdt_control()
            ok = (
                dbg["before"] == 1
                and dbg["after"] == 0
                and dbg["pc_advance"] > 0
                and dbg["cpu_low"] == 0
                and dbg["sep_low"] == 0
                and dbg["samples"] > 0
                and wdt_low == 1
                and self.cold_sep_low > 0
            )
            self._grade(
                "CHK-DBG-RST",
                ok,
                f"dmactive {dbg['before']}->{dbg['after']} after dbg_rstb_i; "
                f"pc_advance={dbg['pc_advance']} sep_cpu_reset_n_low={dbg['cpu_low']} "
                f"sep_reset_n_low={dbg['sep_low']} control_wdt_sep_cpu_reset_n_low={wdt_low} "
                f"window_samples={dbg['samples']} control_cold_sep_reset_n_low={self.cold_sep_low}",
            )
        else:
            await self._sba_matrix()
            await self._alias_legs()
        dut.dmi_core_enable_i.value = 0
        self.dmi.release_pins()
        self._stop = True
        await ClockCycles(dut.clk_i, 2)
        close_graded_window(self.logger)
        if self.failures:
            raise AssertionError("; ".join(self.failures))
        self.result_pass(TEST, self.random_seed(), self.n_checks)
