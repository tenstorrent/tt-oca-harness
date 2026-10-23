# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A CPU-only reset keeps the SEP state; a cold reset clears it, also mid-copy.

What the test proves. A ``wdt_rst_ni`` pulse (and, on the full-CPU build, a
``dbg_rstb_i`` pulse) leaves the software reset requests, the engine state, the
DMA and peripheral fault latches, the SPI and DMA registers and a running
Secure DMA copy intact; the two fault latches keep their aggregator sources 41
and 43 pending. A pulse before, inside or after a pending ``SW_RESET_N``
sequence leaves the sequence intact: the domain isolates, resets and returns
released after the write of 1. A cold reset clears all of them, also in the
middle of a DMA copy, and a later copy completes. After a ``wdt_rst_ni`` pulse
that cuts a write, the cold reset clears what the pulse left on the bus, and
the next write completes.

Sources: ``hw/sys/sep/doc/clk_rst.adoc`` (Reset Architecture);
``hw/sys/sep/doc/reset_controller.adoc`` (SEP Reset Controller, Isolation and
Reset Sequencing); ``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc``
(``DMA_BUS_ERR_STATUS``, ``PERIPH_BUS_ERR_STATUS``, ``DMA_BUS_ERR_CLEAR``,
``PERIPH_BUS_ERR_CLEAR``); ``hw/sys/sep/regs/gen/adoc/blocks/sep_reset_ctrl.adoc``
(``SW_RESET_N``); ``hw/sys/sep/doc/interrupts.adoc`` (SEP CPU Interrupt Vector
Map, sources 41 and 43); ``hw/sys/sep/doc/cpu.adoc`` (CPU: the run-request
synchronizer); ``vendor/lowRISC/opentitan/overlay/regs/secure_dma/regs/gen/adoc/secure_dma.adoc``
(reset values); ``doc/trm/src/reset.adoc`` (Watchdog timeout: the watchdog
reset does not drain transactions, and a cold reset follows every watchdog
timeout).

Legs. Calibration (isolation latency Tiso, write-handshake latency, clean copy
time C), arming, a fault-latch inject, the WDT sequence of 2 to 6 pulses and
its retention reads, the overlap leg (every pulse class against every position
band: before the ``SW_RESET_N`` write, between the write and the
``ip_rst_n[D]`` fall, after the fall), the DMA leg (a pulse against a running
and an idle copy), the cold-reset leg (``rst_ni`` in the middle of a copy) and
a recovery copy. The full-CPU build adds the DBG sequence, the DBG overlap
runs, the DBG DMA leg (a ``dbg_rstb_i`` pulse against a running and an idle
copy) and the run-request synchronizer leg (CHK-DBG-SYNC). The cold-recover
leg (a ``wdt_rst_ni`` pulse with a write in flight, then ``rst_ni``) runs last on
every build. The leaf selects
these legs from the build it runs on (the full ``sep_cpu`` present), not from
the simulator, and sets ``required_evidence`` to match.

Probes. Approved: ``dbg_sep_reset_n_o``, ``sep_cpu_reset_n_o``,
``sep_internal_interrupts_probe_o`` bits 40 to 42, ``ip_rst_n[6:1]``, the
HMAC, KMAC and Adams Bridge isolate-complete probes. Observation taps: the
OTBN and AES bits of the isolate-complete vector (``env/sep_reset_taps.py``)
and ``mpc_run_sync_probe_o``. Drives: ``wdt_rst_ni_i``, ``dbg_rstb_i``,
``rst_ni``, ``mpc_reset_run_req``. Register path: the CPU-LSU master. Every
expected value is an RDL reset value, a value the leaf wrote, or a word of the
copy model (source snapshot against the destination).

Checkers (log shape ``CHK-<ID> PASS|FAIL: ...``):
  CHK-RETAIN              per sequence: every armed register keeps its value,
                          ``RANGE_REGWEN`` reads Lk, ``SW_RESET_N`` reads 0x76
                          and the HMAC isolated window answers SLVERR with
                          ``0x1501A7ED``. Control: the cold leg returns every
                          armed register to its RDL default.
  CHK-AGG-SURVIVE         per sequence: bits 40 and 42 stay 1 through every
                          pulse with no new fault, both latches read 1 before
                          the clear and the bits read 0 after the clear writes.
  CHK-DBG-SYNC            full-CPU build: ``mpc_run_sync`` is constant while
                          ``dbg_rstb_i`` is low although ``mpc_reset_run_req``
                          toggles, and follows within 2 + 2 clocks after the
                          release. Control: it follows a toggle with
                          ``dbg_rstb_i`` high.
  CHK-OVL                 each overlap run: the domain isolates, resets, returns
                          released after the write of 1 and reads its probe at
                          the RDL default; the sibling keeps its value and
                          ``SW_RESET_N`` reads 0x76; the release write shows
                          its AW and an OKAY B on the bus. A B of the cut write,
                          when one shows, is OKAY. Its timing against the
                          ``sep_cpu_reset_n`` fall (drained, late, dropped) is
                          logged, not graded (OBS-OVL-CUT-B). A WDT run with a
                          late or dropped B applies the cold reset before the
                          release write (``cold_before_release=1``): then
                          ``ip_rst_n[D]`` holds low from its fall to the cold
                          reset, the cold reset drops ``sep_reset_n``, and the
                          sibling reads its RDL default.
  CHK-DMA-CPURST          each pulse class and DMA mode: the copy completes,
                          the programmed registers, ``RANGE_REGWEN`` and both
                          latches are kept. The WDT runs also need the
                          ``sep_cpu_reset_n`` tap low in the pulse; the DBG runs
                          (full-CPU build) take credit only with CHK-DBG-SYNC.
  CHK-DMA-COLDRST         the cold reset in the middle of a copy returns every
                          moved Secure DMA register, both status registers and
                          ``SW_RESET_N`` to their reset values; the destination
                          does not change after the reset when its control holds.
  CHK-DMA-COLDRST-RECOVER a new copy after the cold reset completes and matches.
  CHK-WDT-COLD-RECOVER    last leg, every seed and build: a ``wdt_rst_ni`` pulse
                          lands while an accepted ``SW_RESET_N`` write has its B
                          outstanding and is released before the calibrated B
                          latency. ``sep_cpu_reset_n`` falls and rises with
                          ``sep_reset_n`` high. Then an ``rst_ni`` pulse drops
                          ``sep_reset_n``, and the next ``SW_RESET_N`` write on
                          ID 0 shows its AW and an OKAY B on the bus within the
                          bound, with no other ID-0 B from the cold reset to the
                          bound after that B. The B of the cut write is logged,
                          not graded (OBS-WDT-INFLIGHT).

Controls (not counted): ``CTL-CPU-RST`` (a ``wdt_rst_ni`` pulse drops
``sep_cpu_reset_n`` with ``sep_reset_n`` high, and the ``rst_ni`` pulse drops
``sep_reset_n``), ``CTL-BANK`` (the scratch banks after each event),
``OBS-CPU-RST-DBG``.

Environment choices (logged): the placement of each pulse in clocks from the
calibrated latencies, the allowance of CHK-DBG-SYNC (2 clocks), and the bound
of every wait. The CPU-LSU master stands in for the CPU, whose load-store port
is in the ``sep_cpu_reset_n`` domain, so it issues no request while a
``wdt_rst_ni`` pulse holds that reset: in the WDT before band a drawn width that
covers the drawn offset moves the write to the falling edge after the pulse,
and the realized offset is logged.

Run mode: no_cpu with ``+skip_fuse_sense`` and ``ext_boot_seq_done_i`` at 1.
Testlist target ``lsu_stub_all_live``; the full-CPU legs run in the
``sep_cpu_reset_retention_test_dbg`` entry (VCS, target ``default``,
``+sep_require_full_cpu``). Four seeds.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import FallingEdge, NextTimeStep, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_axi_chan_mon import SepAxiChanMon
from env.sep_bit_watch import SepBitWatch
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_reset_taps import SepResetTaps, iso_name
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import (
    HMAC,
    SEP_CPU_CTRL,
    SEP_RESET_CTRL,
    iter_registers,
    register_fields,
    sym,
    word_reset,
)
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_dma_ops import (
    SECURE_DMA,
    ST_CHUNK_DONE,
    ST_DONE,
    SepDmaOps,
    SepMemWords,
    control_word,
)
from seq_lib.sep_irq_aggregator_seq import (
    DMA_CLEAR_ADDR,
    DMA_CLR_BIT,
    DMA_REG_PATH_BIT,
    DMA_STATUS_ADDR,
    IRQ_DMA_HOST_PATH,
    IRQ_DMA_REG_PATH,
    IRQ_PERIPH_OR,
    PERIPH_CLEAR_ADDR,
    PERIPH_STATUS_ADDR,
    dma_reg_unmapped_addr,
    kmac_reg_unmapped_addr,
    otbn_reg_unmapped_addr,
)
from seq_lib.sep_reset_mid_transfer_seq import PROBES, ResetProbe, SepResetProbeDriver, other_value
from seq_lib.sep_scratch_reset_seq import (
    SCRATCH_COLD_ADDRS,
    SCRATCH_RESET_DEFAULT,
    SCRATCH_WARM_ADDRS,
)
from seq_lib.sep_sw_reset_seq import SEP_RESET_CTRL_SW_RESET_N, SW_RESET_N_BIT

TEST = "sep_cpu_reset_retention_test"
RESP_OKAY, RESP_SLVERR = 0, 2
RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", -1: "NONE"}
ISO_DATA = 0x1501_A7ED  # reset_controller.adoc, Isolation and Reset Sequencing, step 2

SW = SEP_RESET_CTRL_SW_RESET_N
SW_FIELDS = SEP_RESET_CTRL.mask32("SW_RESET_N")
SW_DEFAULT = SEP_RESET_CTRL.reset32("SW_RESET_N")  # 0x7E
IPRST = dict(SW_RESET_N_BIT)
SW_HMAC_HELD = SW_DEFAULT & ~(1 << IPRST["hmac"])  # 0x76

D_CHOICES = ("otbn", "aes", "kmac", "abr")
_BY_NAME = {p.name: p for p in PROBES}
# Host-path and Key Manager key-path isolate stages (bench index of env/sep_reset_taps.py).
HOST_X = {"otbn": 0, "aes": 1, "hmac": 2, "kmac": 3, "abr": 4}
KEY_X = {"otbn": 8, "aes": 9, "hmac": 10, "kmac": 11, "abr": 12}

PERIPH_BIT = {n: SEP_CPU_CTRL.field_mask("PERIPH_BUS_ERR_STATUS", n) for n in ("kmac", "otbn")}
PERIPH_CLR = {n: SEP_CPU_CTRL.field_mask("PERIPH_BUS_ERR_CLEAR", n) for n in ("kmac", "otbn")}
PERIPH_HOLE = {"kmac": kmac_reg_unmapped_addr(), "otbn": otbn_reg_unmapped_addr()}
DMA_HOLE = dma_reg_unmapped_addr()
PERIPH_MASK = SEP_CPU_CTRL.mask32("PERIPH_BUS_ERR_STATUS")
DMA_ST_MASK = SEP_CPU_CTRL.mask32("DMA_BUS_ERR_STATUS")
HMAC_ISO_ADDR = HMAC.addr("CFG")

# Secure DMA copy inside the SEP SRAM (memory_map.adoc: 0x1000_0000, 256 KiB).
SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
RANGE_LO = SRAM_BASE
RANGE_HI = SRAM_BASE + 0x1_FFFF
COPY_SRC = SRAM_BASE + 0x0_8000
COPY_DST = SRAM_BASE + 0x1_0000
COPY_BYTES = 1024
COPY_WORDS = COPY_BYTES // 4
WIDTH_ENC = 2  # 4-byte beats

_D = SECURE_DMA
DMA_REGS = [
    r for r in iter_registers() if r.block == "SECURE_DMA" and "write-only" not in r.access.access
]
DMA_REG_BY_NAME = {r.name: r for r in DMA_REGS}
# CONTROL mixes write-only and readable fields, so DMA_REGS leaves it out. The
# cold-reset check grades its readable fields (RDL access other than write-only).
CONTROL_ADDR = _D.addr("CONTROL")
CONTROL_RD_MASK = sum(f.mask for f in register_fields(CONTROL_ADDR)[1] if f.access != "write-only")
CONTROL_RESET = word_reset(CONTROL_ADDR) & CONTROL_RD_MASK
INTR_STATE_ADDR = _D.addr("INTR_STATE")
INTR_STATE_MASK = _D.mask32("INTR_STATE")
INTR_STATE_RESET = _D.reset32("INTR_STATE")
# INTR_TEST forces each INTR_STATE status bit and holds it until a write of 0
# (OpenTitan status-type interrupt), so the cold reset has set bits to clear.
INTR_TEST_ADDR = _D.addr("INTR_TEST")
INTR_TEST_MASK = _D.mask32("INTR_TEST")
# The copy configuration the leaf programs, and the range registers.
COPY_CFG = (
    "SRC_ADDR_LO",
    "SRC_ADDR_HI",
    "DST_ADDR_LO",
    "DST_ADDR_HI",
    "TOTAL_DATA_SIZE",
    "CHUNK_DATA_SIZE",
    "TRANSFER_WIDTH",
    "SRC_CONFIG",
    "DST_CONFIG",
)
RANGE_REGS = ("ENABLED_MEMORY_RANGE_BASE", "ENABLED_MEMORY_RANGE_LIMIT", "RANGE_VALID")
RANGE_ARMED = {
    "ENABLED_MEMORY_RANGE_BASE": RANGE_LO,
    "ENABLED_MEMORY_RANGE_LIMIT": RANGE_HI,
    "RANGE_VALID": 1,
}
RANGE_PROBES = tuple(ResetProbe(n, _D.addr(n), _D.reset32(n), _D.mask32(n)) for n in RANGE_REGS)
RANGE_REGWEN = _D.addr("RANGE_REGWEN")
RANGE_REGWEN_RESET = _D.reset32("RANGE_REGWEN")  # 0x6, RW0C
HSIE = _D.addr("HANDSHAKE_INTR_ENABLE")
HSIE_RESET = _D.reset32("HANDSHAKE_INTR_ENABLE")  # 0x7FF

# Environment choices, clk_i cycles.
TAP_BOUND = 4_000
DBG_ALLOW = 2  # CHK-DBG-SYNC allowance beyond the two-flop synchronizer
SYNC_LAT = 2
WRITE_BOUND = 4_000
# Cold-recover leg: the pulse asserts this many clocks after the write's AW handshake
# and lasts INFLIGHT_WIDTH clocks. The leg checks that the release comes before the
# calibrated B latency (CAL-TISO) and fails otherwise.
INFLIGHT_OFFSET = 1
INFLIGHT_WIDTH = 2


@dataclass
class OvlRun:
    cls: str  # "WDT" or "DBG"
    band: str  # "before", "between", "after"
    f_o: float
    width: int


class Plan:
    """Every draw of the leaf, in the order of the contract, logged as DRAW lines."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.lines: list[str] = []

        def frac() -> float:
            return rng.getrandbits(32) / float(1 << 32)

        self.seq: dict[str, list[tuple[int, int]]] = {}
        for cls in ("WDT", "DBG"):
            n = rng.randrange(2, 7)
            self.seq[cls] = [(rng.randrange(2, 33), rng.randrange(0, 65)) for _ in range(n)]
            self.lines.append(
                f"DRAW seq={cls} events={n} (width,spacing)="
                + ",".join(f"({w},{s})" for w, s in self.seq[cls])
            )
        self.d = rng.choice(D_CHOICES)
        self.sibling = "otbn" if self.d == "aes" else "aes"
        self.lines.append(f"DRAW overlap_domain D={self.d} sibling={self.sibling}")
        runs = [(c, b) for c in ("WDT", "DBG") for b in ("before", "between", "after")]
        rng.shuffle(runs)
        self.ovl = [OvlRun(c, b, frac(), rng.randrange(2, 33)) for c, b in runs]
        self.lines.append(
            "DRAW overlap_order="
            + ",".join(f"{r.cls}:{r.band}:f_o={r.f_o:.6f}:width={r.width}" for r in self.ovl)
        )
        self.dma_modes = ["RUNNING", "IDLE"]
        rng.shuffle(self.dma_modes)
        self.f_c = frac()
        self.dma_width = rng.randrange(2, 33)
        self.lines.append(
            f"DRAW dma_mode_order={','.join(self.dma_modes)} f_c={self.f_c:.6f} "
            f"dma_pulse_width={self.dma_width}"
        )
        self.latch = rng.choice(tuple(x for x in ("kmac", "otbn") if x != self.d))
        self.lines.append(f"DRAW latched_block L={self.latch}")
        self.cold_width = rng.randrange(8, 33)
        self.dbg_sync_width = rng.randrange(8, 33)
        self.lines.append(
            f"DRAW cold_rst_ni_width={self.cold_width} dbg_sync_width={self.dbg_sync_width}"
        )
        # Armed values: non-default, each different from the one before it.
        self.values: dict[str, list[int]] = {}
        for p in PROBES:
            vals: list[int] = []
            for _ in range(4):
                vals.append(other_value(rng, p.mask, (p.reset, *vals[-1:])))
            self.values[p.name] = vals
            self.lines.append(
                f"DRAW armed {p.name} @0x{p.addr:08x} = "
                + ",".join(f"0x{x:08x}" for x in vals)
                + f" (RDL reset 0x{p.reset:08x})"
            )
        self.scratch = {
            "cold": [
                other_value(rng, 0xFFFF_FFFF, (SCRATCH_RESET_DEFAULT,)) for _ in SCRATCH_COLD_ADDRS
            ],
            "warm": [
                other_value(rng, 0xFFFF_FFFF, (SCRATCH_RESET_DEFAULT,)) for _ in SCRATCH_WARM_ADDRS
            ],
        }
        self.lines.append(
            "DRAW scratch cold="
            + ",".join(f"0x{v:08x}" for v in self.scratch["cold"])
            + " warm="
            + ",".join(f"0x{v:08x}" for v in self.scratch["warm"])
        )
        self.data_seed = rng.getrandbits(32)
        self.lines.append(f"DRAW copy_data_seed=0x{self.data_seed:08x}")
        self.rng = rng

    def words(self, n: int, avoid: list[int] | None = None) -> list[int]:
        """Seeded non-zero words; word i differs from ``avoid[i]``."""
        out = []
        for i in range(n):
            while True:
                w = self.rng.getrandbits(32)
                if w and (avoid is None or w != avoid[i]):
                    break
            out.append(w)
        return out


@pyuvm.test()
class sep_cpu_reset_retention_test(sep_base_test):
    """CPU-only resets keep the SEP state and a running copy; a cold reset clears them."""

    required_evidence = (
        "CHK-RETAIN",
        "CHK-AGG-SURVIVE",
        "CHK-OVL",
        "CHK-DMA-CPURST",
        "CHK-DMA-COLDRST",
        "CHK-DMA-COLDRST-RECOVER",
        "CHK-WDT-COLD-RECOVER",
    )

    # ---- log helpers --------------------------------------------------------
    def _chk(self, chk: str, ok: bool, values: str) -> None:
        line = f"{chk} {'PASS' if ok else 'FAIL'}: {values}"
        if not ok:
            self.logger.error(line)
            raise AssertionError(line)
        self.logger.info(line)
        self.k += 1

    def _ctl(self, ctl: str, ok: bool, values: str) -> None:
        if not ok:
            self.logger.error("%s FAIL (control not met): %s", ctl, values)
            raise AssertionError(f"{ctl} control not met: {values}")
        self.logger.info("%s: %s", ctl, values)

    async def _open(self) -> None:
        await self._gate(True)

    async def _close(self) -> None:
        await self._gate(False)

    async def _gate(self, on: bool) -> None:
        """Write the graded-window gate outside the read-only phase of a clock."""
        await NextTimeStep()
        if on:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)

    async def _cycles(self, n: int) -> None:
        for _ in range(n):
            await RisingEdge(cocotb.top.clk_i)

    @property
    def clk(self) -> int:
        return self.taps.iso_req.clk

    # ---- register access ----------------------------------------------------
    async def _acc(self, op: SepAxiOp, addr: int, data: int = 0) -> SepAxiAccessSeq:
        seq = SepAxiAccessSeq(
            f"ret_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=data,
            size=2,
            allow_unverified_write_resp=op is SepAxiOp.WRITE,
            allow_ungraded_read_resp=op is SepAxiOp.READ,
        )
        await self.start_seq(seq)
        if seq.timed_out:
            raise AssertionError(f"{op.value} @0x{addr:08x} got no response")
        return seq

    async def _wr(self, addr: int, data: int) -> None:
        seq = await self._acc(SepAxiOp.WRITE, addr, data)
        if seq.resp_code != RESP_OKAY:
            raise AssertionError(f"write @0x{addr:08x} resp={RESP_NAME[seq.resp_code]}")

    async def _rd(self, addr: int) -> int:
        seq = await self._acc(SepAxiOp.READ, addr)
        if seq.resp_code != RESP_OKAY:
            raise AssertionError(f"read @0x{addr:08x} resp={RESP_NAME[seq.resp_code]}")
        return int(seq.rdata) & 0xFFFF_FFFF

    def _irq(self, bit: int) -> int:
        return (self.rd(cocotb.top.sep_internal_interrupts_probe_o, 1 << bit) >> bit) & 1

    # ---- clock-placed stimulus ----------------------------------------------
    def _pin(self, cls: str):
        return cocotb.top.wdt_rst_ni_i if cls == "WDT" else cocotb.top.dbg_rstb_i

    async def _pulse(self, cls: str, width: int) -> int:
        """Drive the pulse pin low for ``width`` rising edges. Returns the first low edge."""
        dut = cocotb.top
        pin = self._pin(cls)
        await FallingEdge(dut.clk_i)
        pin.value = 0
        first = self.clk + 1
        for _ in range(width):
            await RisingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)
        pin.value = 1
        return first

    def _sw_issue(self, value: int):
        return self.axi.init_write(
            address=SW, data=(value & 0xFFFF_FFFF).to_bytes(4, "little"), size=2, awid=0
        )

    async def _wait_ev(self, ev, what: str) -> None:
        for _ in range(WRITE_BOUND):
            if ev.is_set():
                code = ev.data.resp
                code = max(code) if isinstance(code, (list, tuple)) else int(code)
                if code != RESP_OKAY:
                    raise AssertionError(f"{what}: resp={RESP_NAME.get(code, code)}")
                return
            await RisingEdge(cocotb.top.clk_i)
        raise AssertionError(f"{what}: no response within {WRITE_BOUND} clocks")

    async def _wait_ip(self, d: str, level: int, what: str) -> int:
        try:
            return await self.taps.ip_rst[IPRST[d]].wait_level(level, TAP_BOUND)
        except AssertionError as exc:
            raise AssertionError(f"{what}: ip_rst_n[{IPRST[d]}] {exc}") from exc

    def _aw_after(self, cm, ids=(0,)) -> list[int]:
        return [b.clk - self.off for b in self.chan.since(cm, "aw") if b.axi_id in ids]

    # ---- scenario -----------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.k = 0
        self.plan = Plan(self.seed)
        self.logger.info("SEED %s seed=%d", TEST, self.seed)
        for line in self.plan.lines:
            self.logger.info(line)
        await self.bring_up_no_cpu()
        dut = cocotb.top
        self.full_cpu = self.full_cpu_build()
        # The full-CPU testlist entry passes +sep_require_full_cpu: there the DBG legs and
        # CHK-DBG-SYNC are required, so a stub build fails the leaf.
        if "sep_require_full_cpu" in cocotb.plusargs and not self.full_cpu:
            msg = "CTL-FULL-CPU FAIL: +sep_require_full_cpu and the build has the CPU stub"
            self.logger.error(msg)
            raise AssertionError(msg)
        self.classes = ("WDT", "DBG") if self.full_cpu else ("WDT",)
        if self.full_cpu:
            self.required_evidence = (*type(self).required_evidence, "CHK-DBG-SYNC")
        self.logger.info(
            "OBS-BUILD: full_cpu=%d pulse_classes=%s required_evidence=%s",
            int(self.full_cpu),
            ",".join(self.classes),
            ",".join(self.required_evidence),
        )
        self.logger.info(
            "ENV tap_bound=%d write_bound=%d dbg_sync_allow=%d sync_latency=%d copy_bytes=%d "
            "(clk_i cycles)",
            TAP_BOUND,
            WRITE_BOUND,
            DBG_ALLOW,
            SYNC_LAT,
            COPY_BYTES,
        )
        self.taps = SepResetTaps(dut).start()
        self.chan = SepAxiChanMon("s_axi", dut).start()
        self.irq = SepBitWatch(
            dut.sep_internal_interrupts_probe_o,
            {"src41": IRQ_DMA_REG_PATH, "src42": IRQ_DMA_HOST_PATH, "src43": IRQ_PERIPH_OR},
            name="agg",
        ).start()
        self.pins = {
            "WDT": SepBitWatch(dut.wdt_rst_ni_i, name="wdt_rst_ni_i").start(),
            "DBG": SepBitWatch(dut.dbg_rstb_i, name="dbg_rstb_i").start(),
        }
        self.mpc = SepBitWatch(dut.mpc_run_sync_probe_o, name="mpc_run_sync").start()
        self.pd = SepResetProbeDriver(self)
        self.dma = SepDmaOps(self)
        self.mem = SepMemWords(self)
        self.axi = self.env.axi_agent.driver.axi
        self.armed: dict[str, int] = {}
        self.retain: dict[str, str] = {}
        self.agg: dict[str, str] = {}
        self.ovl_dbg: list[str] = []
        self.cpurst_dbg: list[str] = []
        self.cpu_rst = {"wdt_events": 0, "low": 0, "sep_high": True}
        try:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.off = self.chan.clk - self.taps.iso_req.clk
            self.logger.info("OBS-CLOCKS: chan_mon_clk_offset=%d", self.off)
            await FallingEdge(dut.clk_i)
            for name in ("sep_reset_n", "sep_cpu_reset_n"):
                await self.taps.resets[name].wait_level(1, TAP_BOUND)
            await self._calibrate()
            await self._arm_state()
            for cls in self.classes:
                await self._latch_faults(f"{cls} sequence")
                await self._sequence(cls)
                await self._retention_reads(cls)
            # Every DMA run, the DBG runs too, comes before the overlap leg.
            for cls in self.classes:
                for mode in self.plan.dma_modes:
                    await self._dma_leg(cls, mode)
            await self._overlap_leg()
            r1 = await self._cold_leg()
            await self._after_cold(r1)
            await self._close()
            await self._recovery()
            if self.full_cpu:
                await self._dbg_sync_leg()
                for line in self.ovl_dbg:
                    self._chk("CHK-OVL", True, line)
                for line in self.cpurst_dbg:
                    self._chk("CHK-DMA-CPURST", True, line)
                for key in ("DBG",):
                    self._chk("CHK-RETAIN", True, self.retain[key])
                    self._chk("CHK-AGG-SURVIVE", True, self.agg[key])
            # Last, after every other check: a CPU reset with a write in flight,
            # then the cold reset that clears what it leaves.
            await self._wdt_cold_recover_leg()
        finally:
            await self._close()
            for w in (self.irq, self.mpc, *self.pins.values()):
                await w.stop()
            await self.taps.stop()
            await self.chan.stop()
        self.result_pass(TEST, self.seed, self.k)

    # ---- step 2: calibration -------------------------------------------------
    async def _calibrate(self) -> None:
        d = self.plan.d
        dut = cocotb.top
        await FallingEdge(dut.clk_i)
        m = self.taps.mark()
        cm = self.chan.mark()
        base = self.clk
        ev = self._sw_issue(SW_DEFAULT & ~(1 << IPRST[d]))
        await self._wait_ev(ev, "calibration SW_RESET_N write")
        await self._wait_ip(d, 0, "calibration")
        h = self._aw_after(cm)[0]
        fall = self.taps.ip_rst[IPRST[d]].fall_clks_since(m[f"ip_rst_{IPRST[d]}"])[0]
        ack = self.taps.iso_ack.rise_clks_since(m["iso_ack"], iso_name(HOST_X[d]))
        self.lat_aw = h - base
        self.tiso = fall - h
        self.pf_ack = (ack[0] - h) if ack else None
        b_beats = [b.clk - self.off for b in self.chan.since(cm, "b") if b.axi_id == 0]
        self.lat_b = (b_beats[0] - h) if b_beats else None
        # The B latency places the cold-recover leg and proves the s_axi B tap live.
        self._ctl(
            "CTL-CAL-B",
            self.lat_b is not None and self.lat_b > 0,
            f"calibration write id=0 b_after_aw={self.lat_b}",
        )
        ev = self._sw_issue(SW_DEFAULT)
        await self._wait_ev(ev, "calibration release")
        await self._wait_ip(d, 1, "calibration release")
        self.logger.info(
            "CAL-TISO: dom=%s issue_to_aw=%d tiso=%d host_iso_ack_after_aw=%s b_after_aw=%s",
            d,
            self.lat_aw,
            self.tiso,
            self.pf_ack,
            self.lat_b,
        )
        if self.tiso < 1 or self.pf_ack is None:
            raise AssertionError("calibration: no ip_rst_n fall or no isolate-complete rise")
        # (b) a clean copy in a programmed range, before any RANGE_REGWEN write.
        await self.dma.program_range(RANGE_LO, RANGE_HI, valid=True)
        src = self.plan.words(COPY_WORDS)
        await self.mem.fill(COPY_SRC, src)
        await self.mem.fill(COPY_DST, [0] * COPY_WORDS)
        await self.dma.wr(_D.addr("STATUS"), ST_DONE | ST_CHUNK_DONE)
        await self._program_copy()
        t0 = None
        await self.dma.go()
        t0 = self.clk
        st = await self.dma.poll_status(
            lambda s: s.done or s.error, self.dma.done_bound(COPY_BYTES), "cal"
        )
        self.c = self.clk - t0
        if st.error:
            raise AssertionError(f"calibration copy ended with ERROR: {st.fmt()}")
        await self.dma.wr(_D.addr("STATUS"), ST_DONE | ST_CHUNK_DONE)
        widest = max(
            [w for cls in ("WDT", "DBG") for w, _ in self.plan.seq[cls]]
            + [r.width for r in self.plan.ovl]
            + [self.plan.dma_width]
        )
        self.logger.info(
            "CAL-COPY: C=%d clocks widest_pulse=%d bytes=%d", self.c, widest, COPY_BYTES
        )
        if self.c <= 8 * widest:
            raise AssertionError(
                f"calibration: C={self.c} does not exceed 8 x widest pulse {widest}"
            )
        self.copy_delay = self.c // 4 + int(self.plan.f_c * (self.c // 2))
        self.logger.info(
            "DRAW-SCALED copy_delay=%d (f_c=%.6f C=%d)", self.copy_delay, self.plan.f_c, self.c
        )

    async def _program_copy(self) -> dict[str, int]:
        written = await self.dma.program_transfer(
            src=COPY_SRC, dst=COPY_DST, total=COPY_BYTES, chunk=COPY_BYTES, width_enc=WIDTH_ENC
        )
        for name, val in written.items():
            got = await self.dma.rd(_D.addr(name))
            fc = field_compare(got, val, _D.mask32(name))
            if not fc.ok:
                raise AssertionError(f"copy register {name} readback: {fc.fields()}")
        return written

    # ---- step 3: arm ---------------------------------------------------------
    def _armed_probes(self) -> list[ResetProbe]:
        names = ["otbn", "aes", "kmac", "csrng", "edn", "spi", "dma"]
        if self.plan.d == "abr":
            names.append("abr")
        return [_BY_NAME[n] for n in names]

    async def _arm_probe(self, p: ResetProbe, idx: int) -> None:
        val = self.plan.values[p.name][idx]
        await self.pd.write(p, val)
        self.armed[p.name] = val

    async def _arm_state(self) -> None:
        await self._wr(SW, SW_HMAC_HELD)
        await self._wait_ip("hmac", 0, "arm HMAC hold")
        for x in (HOST_X["hmac"], KEY_X["hmac"]):
            await self.taps.iso_ack.wait_level(1, TAP_BOUND, bit=iso_name(x))
        await self._open()
        for p in self._armed_probes():
            await self._arm_probe(p, 0)
        await self.dma.program_range(RANGE_LO, RANGE_HI, valid=True)
        for n, v in RANGE_ARMED.items():
            self.armed[n] = v
        await self._wr(RANGE_REGWEN, 0)
        self.lk = await self._rd(RANGE_REGWEN)
        self._ctl(
            "CTL-LK",
            self.lk == 0,
            f"RANGE_REGWEN=0x{self.lk:x} after the write of 0 (RW0C, reset 0x6)",
        )
        await self._write_banks()
        for p in (*self._armed_probes(), *RANGE_PROBES):
            got = await self.pd.read(p)
            fc = field_compare(got, self.armed[p.name], p.mask)
            if not fc.ok or (self.armed[p.name] & p.mask) == (p.reset & p.mask):
                raise AssertionError(f"arm readback {p.name}: {fc.fields()}")

    async def _write_banks(self, warm_only: bool = False) -> None:
        banks = (
            (("warm", SCRATCH_WARM_ADDRS),)
            if warm_only
            else (
                ("cold", SCRATCH_COLD_ADDRS),
                ("warm", SCRATCH_WARM_ADDRS),
            )
        )
        for name, addrs in banks:
            for a, v in zip(addrs, self.plan.scratch[name]):
                await self._wr(a, v)

    async def _bank_ctl(self, event: str) -> None:
        await self._close()
        out = {}
        for name, addrs in (("warm", SCRATCH_WARM_ADDRS), ("cold", SCRATCH_COLD_ADDRS)):
            vals = [await self._rd(a) for a in addrs]
            if vals == list(self.plan.scratch[name]):
                out[name] = "retained"
            elif all(v == SCRATCH_RESET_DEFAULT for v in vals):
                out[name] = "cleared"
            else:
                out[name] = "mixed:" + ",".join(f"0x{v:x}" for v in vals)
        self.logger.info("CTL-BANK: event=%s warm=%s cold=%s", event, out["warm"], out["cold"])
        await self._write_banks(warm_only=True)
        await self._open()

    # ---- step 4: fault latches ----------------------------------------------
    async def _latch_faults(self, what: str) -> None:
        lat = self.plan.latch
        seq = await self._acc(SepAxiOp.READ, DMA_HOLE)
        if seq.resp_code != RESP_SLVERR:
            raise AssertionError(f"{what}: DMA hole read resp={RESP_NAME[seq.resp_code]}")
        dst = await self._rd(DMA_STATUS_ADDR)
        seq = await self._acc(SepAxiOp.READ, PERIPH_HOLE[lat])
        if seq.resp_code != RESP_SLVERR:
            raise AssertionError(f"{what}: {lat} hole read resp={RESP_NAME[seq.resp_code]}")
        pst = await self._rd(PERIPH_STATUS_ADDR)
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        b40, b42 = self._irq(IRQ_DMA_REG_PATH), self._irq(IRQ_PERIPH_OR)
        await FallingEdge(cocotb.top.clk_i)
        ok = (dst & DMA_REG_PATH_BIT) and (pst & PERIPH_BIT[lat]) and b40 and b42
        self._ctl(
            "CTL-LATCH",
            bool(ok),
            f"{what}: DMA_BUS_ERR_STATUS=0x{dst:x} PERIPH_BUS_ERR_STATUS=0x{pst:x} "
            f"latch={lat} src41={b40} src43={b42}",
        )

    # ---- step 5: the pulse sequence -------------------------------------------
    async def _sequence(self, cls: str) -> None:
        mi = self.irq.mark()
        events = self.plan.seq[cls]
        stay = True
        mins = [1, 1]
        for i, (w, s) in enumerate(events):
            mr = self.taps.mark()
            first = await self._pulse(cls, w)
            await self.taps.resets["sep_cpu_reset_n"].wait_level(1, TAP_BOUND)
            await self._cycles(s)
            cpu = self.taps.resets["sep_cpu_reset_n"]
            sep = self.taps.resets["sep_reset_n"]
            n = cpu.clk - mr["sep_cpu_reset_n"].clk
            cpu_low = n - cpu.high_clocks_since(mr["sep_cpu_reset_n"])
            sep_low = n - sep.high_clocks_since(mr["sep_reset_n"])
            if cls == "WDT":
                self.cpu_rst["wdt_events"] += 1
                self.cpu_rst["low"] += int(cpu_low > 0)
                self.cpu_rst["sep_high"] &= sep_low == 0
            else:
                self.logger.info(
                    "OBS-CPU-RST-DBG: pulse=%d width=%d sep_cpu_reset_n_low=%d sep_reset_n_low=%d",
                    i,
                    w,
                    cpu_low,
                    sep_low,
                )
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            b40, b42 = self._irq(IRQ_DMA_REG_PATH), self._irq(IRQ_PERIPH_OR)
            await FallingEdge(cocotb.top.clk_i)
            stay &= bool(b40 and b42)
            mins = [min(mins[0], b40), min(mins[1], b42)]
            self.logger.info(
                "SEQ %s event=%d width=%d spacing=%d first_low_clk=%d src41=%d src43=%d",
                cls,
                i,
                w,
                s,
                first,
                b40,
                b42,
            )
            await self._bank_ctl(cls)
        falls = len(self.irq.fall_clks_since(mi, "src41")) + len(
            self.irq.fall_clks_since(mi, "src43")
        )
        new = self.irq.rises_since(mi, "src42")
        self.seq_res = {
            "stay": stay,
            "falls": falls,
            "new": new,
            "events": len(events),
            "src41": mins[0],
            "src43": mins[1],
        }

    # ---- step 6: retention reads -----------------------------------------------
    async def _retention_reads(self, cls: str) -> None:
        kept = 0
        bad = []
        regs = (*self._armed_probes(), *RANGE_PROBES)
        for p in regs:
            got = await self.pd.read(p)
            fc = field_compare(got, self.armed[p.name], p.mask)
            kept += int(fc.ok)
            if not fc.ok:
                bad.append(f"{p.name}:{fc.fields()}")
        lk = await self._rd(RANGE_REGWEN)
        swv = await self._rd(SW)
        iso = await self._acc(SepAxiOp.READ, HMAC_ISO_ADDR)
        iso_ok = iso.resp_code == RESP_SLVERR and (int(iso.rdata) & 0xFFFF_FFFF) == ISO_DATA
        ok = kept == len(regs) and lk == self.lk and (swv & SW_FIELDS) == SW_HMAC_HELD and iso_ok
        self.retain[cls] = (
            f"event={cls} regs_retained={kept}/{len(regs)} RANGE_REGWEN=0x{lk:x} "
            f"SW_RESET_N=0x{swv & SW_FIELDS:02x} hmac_iso_rd4=0x{int(iso.rdata) & 0xFFFF_FFFF:08x}/"
            f"{RESP_NAME[iso.resp_code]}" + (f" mismatch={bad}" if bad else "")
        )
        self._retain_ok = getattr(self, "_retain_ok", {})
        self._retain_ok[cls] = ok
        if not ok:
            self.logger.error("CHK-RETAIN FAIL: %s", self.retain[cls])
            raise AssertionError(f"CHK-RETAIN FAIL: {self.retain[cls]}")
        lat = self.plan.latch
        dst = await self._rd(DMA_STATUS_ADDR)
        pst = await self._rd(PERIPH_STATUS_ADDR)
        await self._wr(DMA_CLEAR_ADDR, DMA_CLR_BIT)
        await self._wr(PERIPH_CLEAR_ADDR, PERIPH_CLR[lat])
        await self._cycles(2)
        await ReadOnly()
        a40, a42 = self._irq(IRQ_DMA_REG_PATH), self._irq(IRQ_PERIPH_OR)
        await FallingEdge(cocotb.top.clk_i)
        dst2 = await self._rd(DMA_STATUS_ADDR)
        pst2 = await self._rd(PERIPH_STATUS_ADDR)
        r = self.seq_res
        ok = (
            r["stay"]
            and r["falls"] == 0
            and r["new"] == 0
            and (dst & DMA_ST_MASK) == DMA_REG_PATH_BIT
            and (pst & PERIPH_MASK) == PERIPH_BIT[lat]
            and a40 == 0
            and a42 == 0
            and (dst2 & DMA_ST_MASK) == 0
            and (pst2 & PERIPH_MASK) == 0
        )
        self.agg[cls] = (
            f"event={cls} latch={lat} src41={r['src41']} src43={r['src43']} new_faults={r['new']} "
            f"falls_during_pulses={r['falls']} pulses={r['events']} "
            f"DMA_BUS_ERR_STATUS=0x{dst:x} PERIPH_BUS_ERR_STATUS=0x{pst:x} "
            f"after_clear={a40 | a42} status_after_clear=0x{dst2:x},0x{pst2:x}"
        )
        if not ok:
            self.logger.error("CHK-AGG-SURVIVE FAIL: %s", self.agg[cls])
            raise AssertionError(f"CHK-AGG-SURVIVE FAIL: {self.agg[cls]}")
        if cls == "WDT":
            self._chk("CHK-AGG-SURVIVE", True, self.agg[cls])

    # ---- step 7: overlap leg ----------------------------------------------------
    async def _overlap_leg(self) -> None:
        d, sib = self.plan.d, self.plan.sibling
        for n, run in enumerate(r for r in self.plan.ovl if r.cls in self.classes):
            dut = cocotb.top
            await self._arm_probe(_BY_NAME[d], (n % 3) + 1)
            await self._arm_probe(_BY_NAME[sib], (n % 3) + 1)
            await self._write_banks()
            off = int(run.f_o * self.tiso)
            if run.band == "before":
                target = -(1 + off)
            elif run.band == "between":
                target = off
            else:
                target = self.tiso + off
            # Schedule from a common falling edge: the write AW handshake lands
            # lat_aw clocks after its issue, the pulse pin reads low from the
            # edge after the falling edge on which it is driven.
            t_issue = max(0, -(self.lat_aw + target) + 1)
            t_pin = t_issue + self.lat_aw + target - 1
            legal_note = ""
            if run.cls == "WDT" and run.band == "before" and -target <= run.width:
                # The CPU-LSU master stands in for the CPU. wdt_rst_ni drops
                # sep_cpu_reset_n, which resets the EL2 core (hw/sys/sep/doc/clk_rst.adoc,
                # Reset Architecture, CPU reset row; hw/sys/sep/doc/reset_controller.adoc,
                # sep_cpu_reset_no). A core held in reset issues no load or store, so the
                # write issues on the falling edge after the pulse ends; the assertion
                # edge stays before the write handshake.
                t_pin = 0
                t_issue = run.width + 1
                legal_note = (
                    f" drawn_offset={target} realized_after_pulse=1 (width {run.width} "
                    f">= offset {-target})"
                )
            self.logger.info(
                "DRAW-SCALED overlap run=%d pulse=%s band=%s f_o=%.6f tiso=%d offset=%d "
                "(clocks from the write handshake%s) width=%d",
                n,
                run.cls,
                run.band,
                run.f_o,
                self.tiso,
                target if run.band != "after" else off,
                ", from the ip_rst_n fall" if run.band == "after" else "",
                run.width,
            )
            pre_iso = self.taps.iso_ack.level(iso_name(HOST_X[d]))
            pre_key = self.taps.iso_ack.level(iso_name(KEY_X[d]))
            await FallingEdge(dut.clk_i)
            m = self.taps.mark()
            cm = self.chan.mark()
            mp = self.pins[run.cls].mark()
            base = self.clk
            pulse_task = None
            # The response of the write is watched from its issue, so its outcome
            # against the CPU reset is logged on the clock it shows.
            cut_task = cocotb.start_soon(
                self._watch_cut_b(cm, m["sep_cpu_reset_n"], f"run={n} pulse={run.cls}")
            )
            for t in range(max(t_issue, t_pin) + 1):
                if t == t_issue:
                    self._sw_issue(SW_HMAC_HELD & ~(1 << IPRST[d]))
                if t == t_pin:
                    pulse_task = cocotb.start_soon(self._pulse_now(run.cls, run.width))
                await FallingEdge(dut.clk_i)
            await pulse_task
            try:
                await self._wait_ip(d, 0, f"CHK-OVL run={n}")
            except AssertionError as exc:
                self.logger.error("CHK-OVL FAIL: run=%d no ip_rst_n fall: %s", n, exc)
                raise
            cut = await cut_task
            if not cut["ok"]:
                msg = (
                    f"CHK-OVL FAIL: dom={d} pulse={run.cls} band={run.band} the response of the "
                    f"SW_RESET_N write: {cut['text']}"
                )
                self.logger.error(msg)
                raise AssertionError(msg)
            if cut["outcome"] == "dropped":
                self._reset_cpu_master(f"overlap run={n}")
            h = cut["aw"]
            fall = self.taps.ip_rst[IPRST[d]].fall_clks_since(m[f"ip_rst_{IPRST[d]}"])[0]
            low = self.pins[run.cls].fall_clks_since(mp)
            p_first = low[0] if low else None
            ack = self.taps.iso_ack.rise_clks_since(m["iso_ack"], iso_name(HOST_X[d]))
            ack_c = ack[0] if ack else None
            meas = (p_first - h) if run.band != "after" else (p_first - fall)
            want = target if run.band != "after" else off
            band_ok = {
                "before": p_first is not None and p_first < h,
                "between": p_first is not None and h <= p_first < fall,
                "after": p_first is not None and p_first >= fall,
            }[run.band]
            self.logger.info(
                "OVL-PLACE run=%d pulse=%s band=%s issue=%d aw=%d fall=%d pulse_first_low=%s "
                "offset_measured=%s offset_target=%d band_ok=%d%s",
                n,
                run.cls,
                run.band,
                base,
                h,
                fall,
                p_first,
                meas,
                want,
                int(band_ok),
                legal_note,
            )
            if not band_ok:
                raise AssertionError(f"overlap run={n}: pulse not in band {run.band}")
            # Release after the pulse. A WDT pulse that cut the write (late or
            # dropped B) is followed by the cold reset before the release write: the
            # platform follows every watchdog timeout with a cold reset, which clears
            # the state the watchdog reset leaves (doc/trm/src/reset.adoc, Watchdog
            # timeout).
            await self.taps.resets["sep_cpu_reset_n"].wait_level(1, TAP_BOUND)
            cold = run.cls == "WDT" and cut["outcome"] in ("late", "dropped")
            cold_clk = cold_low = None
            if cold:
                await FallingEdge(dut.clk_i)
                sep = self.taps.resets["sep_reset_n"]
                mk = sep.mark()
                cold_clk = self.clk
                await self.pulse_rst_ni(hold_cycles=self.plan.cold_width)
                for name in ("sep_reset_n", "sep_cpu_reset_n"):
                    await self.taps.resets[name].wait_level(1, TAP_BOUND)
                cold_low = bool(sep.fall_clks_since(mk))
            await FallingEdge(dut.clk_i)
            nxt, rel_aw = await self._bus_write(SW_HMAC_HELD)
            if nxt != "OKAY":
                msg = (
                    f"CHK-OVL FAIL: dom={d} pulse={run.cls} band={run.band} the SW_RESET_N write "
                    f"after the pulse: {nxt} cut_b={cut['outcome']}; the CPU-LSU write path does not "
                    "recover"
                )
                self.logger.error(msg)
                raise AssertionError(msg)
            await self._wait_ip(d, 1, f"CHK-OVL run={n} release")
            rise = self.taps.ip_rst[IPRST[d]].rise_clks_since(m[f"ip_rst_{IPRST[d]}"])
            rise_c = rise[0] if rise else None
            # ip_rst_n[D] holds low on every clock from its fall to the AW handshake
            # of the release write, and its first rise comes after that handshake.
            # With the cold reset before the release write, the cold reset releases
            # the domain (SW_RESET_N returns to 0x7E): ip_rst_n[D] holds low from its
            # fall to the cold reset, and its first rise comes at or after it.
            if cold:
                held = rise_c is not None and fall < cold_clk <= rise_c and bool(cold_low)
            else:
                held = rise_c is not None and fall < rel_aw < rise_c
            pd_, ps_ = _BY_NAME[d], _BY_NAME[sib]
            got_d = await self.pd.read(pd_)
            got_s = await self.pd.read(ps_)
            swv = await self._rd(SW)
            fd = field_compare(got_d, pd_.reset, pd_.mask)
            # The cold reset returns the sibling to its RDL reset value.
            sib_want = ps_.reset if cold else self.armed[ps_.name]
            fs = field_compare(got_s, sib_want, ps_.mask)
            iso_order = pre_iso == 0 and pre_key == 1 and ack_c is not None and ack_c < fall
            ok = iso_order and held and fd.ok and fs.ok and (swv & SW_FIELDS) == SW_HMAC_HELD
            line = (
                f"dom={d} pulse={run.cls} band={run.band} iso_ack={ack_c - h if ack_c else None} "
                f"rst_assert={fall - h} rst_fall_clk={fall} release_aw_clk={rel_aw} "
                f"first_rise_clk={rise_c} held_to_release={int(held)} "
                f"host_iso_before_write={pre_iso} key_iso_before_write={pre_key} "
                f"engine_default_after_release={int(fd.ok)} sibling_retained={int(fs.ok)} "
                f"SW_RESET_N=0x{swv & SW_FIELDS:02x} pulse_free_ack={self.pf_ack} "
                f"pulse_free_fall={self.tiso} cut_b={cut['outcome']} "
                f"cold_before_release={int(cold)} cold_clk={cold_clk} "
                f"cold_sep_reset_n_low={'na' if cold_low is None else int(cold_low)}"
            )
            if not ok:
                self.logger.error("CHK-OVL FAIL: %s %s %s", line, fd.fields(), fs.fields())
                raise AssertionError(f"CHK-OVL FAIL: {line}")
            if run.cls == "WDT":
                self._chk("CHK-OVL", True, line)
            else:
                self.ovl_dbg.append(line)
            self.armed[pd_.name] = pd_.reset
            if cold:
                await self._rearm_after_cold()
            await self._bank_ctl(run.cls)

    async def _rearm_after_cold(self) -> None:
        """Restore the armed state the later legs start from after an overlap cold reset.

        The release write holds HMAC again; this waits for the HMAC hold, records
        every armed probe at its RDL reset value (the cold reset cleared them), and
        programs and locks the range registers again.
        """
        await self._wait_ip("hmac", 0, "re-arm HMAC hold")
        for x in (HOST_X["hmac"], KEY_X["hmac"]):
            await self.taps.iso_ack.wait_level(1, TAP_BOUND, bit=iso_name(x))
        for p in self._armed_probes():
            self.armed[p.name] = p.reset
        await self.dma.program_range(RANGE_LO, RANGE_HI, valid=True)
        for n, v in RANGE_ARMED.items():
            self.armed[n] = v
        await self._wr(RANGE_REGWEN, 0)
        self.lk = await self._rd(RANGE_REGWEN)
        self._ctl(
            "CTL-LK",
            self.lk == 0,
            f"RANGE_REGWEN=0x{self.lk:x} after the write of 0 (RW0C, reset 0x6), re-arm",
        )

    # ---- cold-recover leg: a CPU reset with a write in flight, then a cold reset ----
    async def _wdt_cold_recover_leg(self) -> None:
        """A ``wdt_rst_ni`` pulse with a write in flight, then a cold reset.

        The write is a ``SW_RESET_N`` write of its present value. The pulse asserts
        ``INFLIGHT_OFFSET`` clocks after the AW handshake and is released before the
        calibrated B latency, so the B of the write is outstanding across the CPU
        reset. The watchdog reset does not drain transactions, and the platform
        follows every watchdog timeout with a cold reset, which clears that state
        (``doc/trm/src/reset.adoc``, Watchdog timeout). The B outcome (drained,
        late or dropped) is logged and not graded. CHK-WDT-COLD-RECOVER grades:
        ``sep_cpu_reset_n`` falls and rises on the pulse while ``sep_reset_n``
        stays high; the ``rst_ni`` pulse drops ``sep_reset_n``; after it, the next
        ``SW_RESET_N`` write on the same ID shows its AW and an OKAY B on the
        ``s_axi`` bus within ``WRITE_BOUND`` clocks, and no other ID-0 B shows on
        the bus from the cold reset to ``WRITE_BOUND`` clocks after that B. The
        stand-in master is reset by ``rst_ni``, so the cold reset also clears its
        open write.
        """
        dut = cocotb.top
        await self._open()
        sw_now = await self._rd(SW)
        cpu = self.taps.resets["sep_cpu_reset_n"]
        sep = self.taps.resets["sep_reset_n"]
        await FallingEdge(dut.clk_i)
        cm = self.chan.mark()
        mp = self.pins["WDT"].mark()
        mc = cpu.mark()
        ms = sep.mark()
        self._sw_issue(sw_now & SW_FIELDS)
        aw = None
        for _ in range(WRITE_BOUND):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            got = self._aw_after(cm)
            if got:
                aw = got[0]
                break
        if aw is None:
            raise AssertionError("cold-recover leg: the SW_RESET_N write got no AW handshake")
        await FallingEdge(dut.clk_i)
        for _ in range(INFLIGHT_OFFSET - 1):
            await FallingEdge(dut.clk_i)
        b_before = [b for b in self.chan.since(cm, "b") if b.axi_id == 0]
        pulse = cocotb.start_soon(self._pulse_now("WDT", INFLIGHT_WIDTH))
        await pulse
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        low = self.pins["WDT"].fall_clks_since(mp)
        rel = self.pins["WDT"].rise_clks_since(mp)
        p_first = low[0] if low else None
        p_rel = rel[0] if rel else None
        b_open = not b_before
        b_due = None if self.lat_b is None else aw + self.lat_b
        self.logger.info(
            "WDT-INFLIGHT-PLACE: aw_clk=%d pulse_first_low=%s pulse_release=%s width=%d "
            "b_outstanding_at_pulse=%d calibrated_b_after_aw=%s calibrated_b_clk=%s",
            aw,
            p_first,
            p_rel,
            INFLIGHT_WIDTH,
            int(b_open),
            self.lat_b,
            b_due,
        )
        # The pulse lands with the B outstanding and is released before the clock
        # the pulse-free B returns.
        if not (
            b_open
            and p_first is not None
            and p_first > aw
            and p_rel is not None
            and b_due is not None
            and p_rel < b_due
        ):
            raise AssertionError(
                "cold-recover leg: the pulse did not land with the B outstanding and end "
                f"before the calibrated B (pulse_release={p_rel} calibrated_b_clk={b_due})"
            )
        # Watch the write's B and the CPU reset for the bound; log the B outcome.
        b_clk = b_resp = c_fall = c_rise = None
        for _ in range(WRITE_BOUND):
            if b_clk is None:
                beats = [b for b in self.chan.since(cm, "b") if b.axi_id == 0]
                if beats:
                    b_clk, b_resp = beats[0].clk - self.off, beats[0].resp
            falls = cpu.fall_clks_since(mc)
            rises = cpu.rise_clks_since(mc)
            c_fall = falls[0] if falls else None
            c_rise = rises[0] if rises else None
            if b_clk is not None and c_rise is not None:
                break
            await RisingEdge(dut.clk_i)
            await ReadOnly()
        if b_clk is None:
            outcome = "dropped"
        elif c_fall is not None and b_clk >= c_fall:
            outcome = "late"
        else:
            outcome = "drained"
        sep_high = not sep.fall_clks_since(ms)
        cpu_ok = c_fall is not None and c_rise is not None and c_rise > c_fall
        self.logger.info(
            "OBS-WDT-INFLIGHT: write id=0 aw_clk=%d b_clk=%s b_resp=%s b_outcome=%s "
            "(not graded: the watchdog reset does not drain transactions)",
            aw,
            b_clk,
            RESP_NAME.get(b_resp, b_resp),
            outcome,
        )
        # The cold reset, then the next write on the same ID.
        await FallingEdge(dut.clk_i)
        mk = sep.mark()
        ck = self.chan.mark()
        res = await self.pulse_rst_ni(hold_cycles=self.plan.cold_width)
        for name in ("sep_reset_n", "sep_cpu_reset_n"):
            await self.taps.resets[name].wait_level(1, TAP_BOUND)
        cold_low = bool(sep.fall_clks_since(mk))
        await FallingEdge(dut.clk_i)
        nxt, nxt_aw = await self._bus_write(SW_DEFAULT)
        # Any ID-0 B other than the next write's own is a B the cold reset left.
        for _ in range(WRITE_BOUND):
            await RisingEdge(dut.clk_i)
        await ReadOnly()
        b_after = [b for b in self.chan.since(ck, "b") if b.axi_id == 0]
        stale = len(b_after) - (1 if nxt == "OKAY" else 0)
        await FallingEdge(dut.clk_i)
        self._chk(
            "CHK-WDT-COLD-RECOVER",
            cpu_ok and sep_high and cold_low and nxt == "OKAY" and stale == 0,
            f"write id=0 aw_clk={aw} pulse_first_low={p_first} pulse_release={p_rel} "
            f"cpu_reset_fall={c_fall} cpu_reset_rise={c_rise} sep_reset_n_high_on_wdt="
            f"{int(sep_high)} b_outcome={outcome} cold_sep_reset_n_low={int(cold_low)} "
            f"cold_release_clks={res['release_clks']} next_write={nxt} next_aw_clk={nxt_aw} "
            f"other_id0_b_after_cold={stale} bound={WRITE_BOUND}",
        )

    def _reset_cpu_master(self, where: str) -> None:
        """Reset the write side of the stand-in CPU master after a dropped B.

        The stand-in master is reset by ``rst_ni`` only, while the CPU it stands
        in for is reset by ``sep_cpu_reset_n``, which clears the CPU's open
        writes. After the CPU reset cut a write and its B stayed absent for the
        whole bound, the master still holds that write open on its ID, and it
        would complete it with the B of the next write of the same ID. This
        clears the open writes (``assert_reset`` of the write interface), as
        the CPU reset does. It runs only after a dropped B in the overlap leg: a
        late B completes the open write as it is.
        """
        wr = self.env.axi_agent.driver.axi.driver.backend.write_if
        wr.assert_reset()
        self.logger.info(
            "OBS-MASTER-RESET: %s the CPU reset dropped the B of an open write; "
            "the stand-in master write state is cleared",
            where,
        )

    async def _bus_write(self, value: int) -> tuple[str, int | None]:
        """Issue a ``SW_RESET_N`` write; grade its AW and B on the ``s_axi`` bus.

        Returns (``OKAY``, the non-OKAY response name or ``none (...)``; the AW
        clock or None). The stand-in master pairs a B with the oldest open write
        of its ID and is not reset by ``sep_cpu_reset_n``, so its event is not used.
        """
        dut = cocotb.top
        cm = self.chan.mark()
        self._sw_issue(value)
        aw = None
        for _ in range(WRITE_BOUND):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if aw is None:
                got = self._aw_after(cm)
                if got:
                    aw = got[0]
            if aw is not None:
                beats = [
                    b for b in self.chan.since(cm, "b") if b.axi_id == 0 and b.clk - self.off > aw
                ]
                if beats:
                    resp = beats[0].resp
                    return ("OKAY" if resp == RESP_OKAY else str(RESP_NAME.get(resp, resp))), aw
        what = "no AW handshake" if aw is None else f"aw_clk={aw}, no B"
        return f"none ({what} within {WRITE_BOUND} clocks)", aw

    async def _watch_cut_b(self, cm, mc, label: str) -> dict:
        """Watch the B of the ID-0 write issued after ``cm`` against the CPU reset tap.

        ``mc`` is a mark of the ``sep_cpu_reset_n`` tap taken before the write. A
        fall of the tap on or after the AW clock cuts the write. The outcome is
        logged: a B before that fall (drained), a B on or after it (late) or no B
        (dropped). The watchdog reset does not drain transactions
        (``doc/trm/src/reset.adoc``, Watchdog timeout), so each of the three is
        accepted. A write the CPU reset does not cut needs its B, and every B
        taken must be OKAY.
        """
        dut = cocotb.top
        cpu = self.taps.resets["sep_cpu_reset_n"]
        aw = b_clk = b_resp = c_fall = None
        for _ in range(2 * WRITE_BOUND):
            # Query the channel monitor only after it has sampled past the mark.
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if aw is None:
                got = self._aw_after(cm)
                aw = got[0] if got else None
            if aw is not None:
                if b_clk is None:
                    beats = [
                        b
                        for b in self.chan.since(cm, "b")
                        if b.axi_id == 0 and b.clk - self.off > aw
                    ]
                    if beats:
                        b_clk, b_resp = beats[0].clk - self.off, beats[0].resp
                falls = [c for c in cpu.fall_clks_since(mc) if c >= aw]
                c_fall = falls[0] if falls else None
                # A B is final: a later fall cannot change its outcome.
                if b_clk is not None:
                    break
        if aw is None:
            outcome = "no_aw"
        elif b_clk is not None:
            if c_fall is None:
                outcome = "completed"
            else:
                outcome = "late" if b_clk >= c_fall else "drained"
        else:
            outcome = "dropped" if c_fall is not None else "missing"
        ok = outcome in ("drained", "late", "completed", "dropped") and (
            b_clk is None or b_resp == RESP_OKAY
        )
        rises = [c for c in cpu.rise_clks_since(mc) if c_fall is not None and c > c_fall]
        c_rise = rises[0] if rises else None
        text = (
            f"{label} write id=0 aw_clk={aw} cpu_reset_fall={c_fall} cpu_reset_rise={c_rise} "
            f"b_clk={b_clk} "
            f"b_resp={RESP_NAME.get(b_resp, b_resp)} b_outcome={outcome}"
        )
        self.logger.info("OBS-OVL-CUT-B: %s", text)
        return {"ok": ok, "outcome": outcome, "aw": aw, "text": text}

    async def _pulse_now(self, cls: str, width: int) -> None:
        """Drive the pin low now (a falling edge) for ``width`` rising edges."""
        dut = cocotb.top
        pin = self._pin(cls)
        pin.value = 0
        for _ in range(width):
            await RisingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)
        pin.value = 1

    # ---- step 8: DMA leg --------------------------------------------------------
    async def _dma_leg(self, cls: str, mode: str) -> None:
        dut = cocotb.top
        await self._latch_faults(f"DMA {cls} {mode}")
        st_addr = _D.addr("STATUS")
        await self.dma.wr(st_addr, ST_DONE | ST_CHUNK_DONE)
        st0 = await self.dma.read_status()
        if st0.done or st0.chunk_done:
            raise AssertionError(f"DMA {mode}: DONE/CHUNK_DONE not 0 after W1C: {st0.fmt()}")
        src = self.plan.words(COPY_WORDS)
        pat_a = self.plan.words(COPY_WORDS, avoid=src)
        await self.mem.fill(COPY_SRC, src)
        await self.mem.fill(COPY_DST, pat_a)
        written = await self._program_copy()
        await self.dma.go()
        t_go = self.clk
        mr = self.taps.mark()
        mp = self.pins[cls].mark()
        if mode == "RUNNING":
            while self.clk < t_go + self.copy_delay:
                await RisingEdge(dut.clk_i)
            await self._pulse(cls, self.plan.dma_width)
            await self.taps.resets["sep_cpu_reset_n"].wait_level(1, TAP_BOUND)
            first = await self.dma.read_status()
            busy_after = first.busy
            if not busy_after:
                raise AssertionError(
                    f"DMA {cls} RUNNING: the first STATUS read after the pulse shows BUSY=0 "
                    f"({first.fmt()}); the pulse did not land on a running copy"
                )
        else:
            await self.dma.poll_status(
                lambda s: s.done, self.dma.done_bound(COPY_BYTES), "idle done"
            )
            await self._pulse(cls, self.plan.dma_width)
            await self.taps.resets["sep_cpu_reset_n"].wait_level(1, TAP_BOUND)
            busy_after = (await self.dma.read_status()).busy
        cpu = self.taps.resets["sep_cpu_reset_n"]
        n = cpu.clk - mr["sep_cpu_reset_n"].clk
        cpu_low = n - cpu.high_clocks_since(mr["sep_cpu_reset_n"])
        pin_fall = len(self.pins[cls].fall_clks_since(mp))
        if cls == "WDT":
            self.cpu_rst["wdt_events"] += 1
            self.cpu_rst["low"] += int(cpu_low > 0)
            self.cpu_rst["sep_high"] &= (
                self.taps.resets["sep_reset_n"].high_clocks_since(mr["sep_reset_n"]) == n
            )
        else:
            self.logger.info(
                "OBS-CPU-RST-DBG: dma_mode=%s width=%d sep_cpu_reset_n_low=%d",
                mode,
                self.plan.dma_width,
                cpu_low,
            )
        st = await self.dma.poll_status(
            lambda s: s.done or s.error, 4 * self.dma.done_bound(COPY_BYTES), f"{mode} done"
        )
        regs_ok = True
        for name, val in {**written, **RANGE_ARMED}.items():
            got = await self.dma.rd(_D.addr(name))
            regs_ok &= field_compare(got, val, _D.mask32(name)).ok
        lk = await self._rd(RANGE_REGWEN)
        dst_st = await self._rd(DMA_STATUS_ADDR)
        pst = await self._rd(PERIPH_STATUS_ADDR)
        dest = await self.mem.read(COPY_DST, COPY_WORDS)
        mism = sum(1 for a, b in zip(dest, src) if a != b)
        ok = (
            st.done == 1
            and st.error == 0
            and mism == 0
            and regs_ok
            and lk == self.lk
            and (dst_st & DMA_REG_PATH_BIT)
            and (pst & PERIPH_BIT[self.plan.latch])
            and pin_fall == 1
            and (cpu_low > 0 or cls == "DBG")
        )
        line = (
            f"pulse={cls} mode={mode} pin_fall={pin_fall} cpu_rst_pulse={int(cpu_low > 0)} "
            f"busy_after_pulse={busy_after} "
            f"done={st.done} error={st.error} regs_kept={int(regs_ok)} RANGE_REGWEN=0x{lk:x} "
            f"mem_mismatch={mism} bus_err_status=0x{dst_st:x} periph_status=0x{pst:x} "
            f"delay={self.copy_delay if mode == 'RUNNING' else 'na'}"
        )
        if ok and cls == "DBG":
            # The DBG half takes credit only after CHK-DBG-SYNC passes.
            self.cpurst_dbg.append(line)
        else:
            self._chk("CHK-DMA-CPURST", bool(ok), line)
        await self.dma.wr(st_addr, ST_DONE | ST_CHUNK_DONE)

    # ---- step 9: cold-reset leg ---------------------------------------------------
    async def _cold_leg(self) -> dict:
        dut = cocotb.top
        for p in self._armed_probes():
            await self._arm_probe(p, 3)
        await self._write_banks()
        st_addr = _D.addr("STATUS")
        await self.dma.wr(st_addr, ST_DONE | ST_CHUNK_DONE)
        st0 = await self.dma.read_status()
        if st0.done or st0.chunk_done:
            raise AssertionError(f"cold leg: DONE/CHUNK_DONE not 0 after W1C: {st0.fmt()}")
        src = self.plan.words(COPY_WORDS)
        pat_b = self.plan.words(COPY_WORDS, avoid=src)
        await self.mem.fill(COPY_SRC, src)
        await self.mem.fill(COPY_DST, pat_b)
        await self.dma.wr(HSIE, 0)
        written = await self._program_copy()
        # CONTROL with GO=0 and INITIAL_TRANSFER=1, then the INTR_STATE force: both
        # read a value other than their RDL reset before the reset.
        await self.dma.wr(CONTROL_ADDR, control_word(initial=1))
        await self.dma.wr(INTR_TEST_ADDR, INTR_TEST_MASK)
        # Both bus-error latches set before the reset (the step 4 error injection: a
        # read of the DMA hole and of the drawn peripheral hole, each SLVERR), so the
        # zero read after the reset shows the reset clears them.
        lat = self.plan.latch
        for addr, what in ((DMA_HOLE, "DMA"), (PERIPH_HOLE[lat], lat)):
            seq = await self._acc(SepAxiOp.READ, addr)
            if seq.resp_code != RESP_SLVERR:
                raise AssertionError(
                    f"cold leg: {what} hole read resp={RESP_NAME.get(seq.resp_code)}"
                )
        dst_pre = await self._rd(DMA_STATUS_ADDR)
        pst_pre = await self._rd(PERIPH_STATUS_ADDR)
        pre: dict[str, int] = {}
        for r in DMA_REGS:
            if r.name in ("STATUS", "INTR_STATE"):
                continue
            pre[r.name] = await self.dma.rd(r.addr)
        ctl_pre = await self.dma.rd(CONTROL_ADDR)
        intr_pre = await self.dma.rd(INTR_STATE_ADDR)
        if pre["HANDSHAKE_INTR_ENABLE"] & HSIE_RESET:
            raise AssertionError("cold leg: HANDSHAKE_INTR_ENABLE did not take the write of 0")
        sw_pre = await self._rd(SW)
        armed_pre = {}
        at_default = []
        for p in (*self._armed_probes(), *RANGE_PROBES):
            armed_pre[p.name] = await self.pd.read(p)
            if (armed_pre[p.name] & p.mask) == (p.reset & p.mask):
                at_default.append(f"{p.name}=0x{armed_pre[p.name]:x}")
        for name, got, rst, msk in (
            ("CONTROL", ctl_pre, CONTROL_RESET, CONTROL_RD_MASK),
            ("INTR_STATE", intr_pre, INTR_STATE_RESET, INTR_STATE_MASK),
        ):
            if (got & msk) == (rst & msk):
                at_default.append(f"{name}=0x{got:x}")
        for name, got, bit in (
            ("DMA_BUS_ERR_STATUS", dst_pre, DMA_REG_PATH_BIT),
            ("PERIPH_BUS_ERR_STATUS", pst_pre, PERIPH_BIT[lat]),
        ):
            if not got & bit:
                at_default.append(f"{name}=0x{got:x}")
        # Every register the cold reset grades must read a value other than its RDL
        # reset first, or a missing reset could not show.
        self._ctl(
            "CTL-COLD-ARMED",
            not at_default,
            f"registers={len(armed_pre) + 4} at_rdl_default={at_default or 'none'} "
            f"CONTROL_pre=0x{ctl_pre & CONTROL_RD_MASK:08x} "
            f"INTR_STATE_pre=0x{intr_pre & INTR_STATE_MASK:x} "
            f"DMA_BUS_ERR_STATUS_pre=0x{dst_pre & DMA_ST_MASK:02x} "
            f"PERIPH_BUS_ERR_STATUS_pre=0x{pst_pre & PERIPH_MASK:02x} latch={lat}",
        )
        await self.dma.go()
        t_go = self.clk
        while self.clk < t_go + self.copy_delay:
            await RisingEdge(dut.clk_i)
        m = self.taps.mark()
        res = await self.pulse_rst_ni(hold_cycles=self.plan.cold_width)
        for name in ("sep_reset_n", "sep_cpu_reset_n"):
            await self.taps.resets[name].wait_level(1, TAP_BOUND)
        sep = self.taps.resets["sep_reset_n"]
        n = sep.clk - m["sep_reset_n"].clk
        cold_low = n - sep.high_clocks_since(m["sep_reset_n"])
        self._ctl(
            "CTL-CPU-RST",
            self.cpu_rst["low"] >= 1 and self.cpu_rst["sep_high"] and cold_low > 0,
            f"wdt_events={self.cpu_rst['wdt_events']} sep_cpu_reset_n_low_on_wdt="
            f"{self.cpu_rst['low']} sep_reset_n_high_on_wdt={int(self.cpu_rst['sep_high'])} "
            f"control_cold_sep_reset_n_low={int(cold_low > 0)}",
        )
        self.logger.info(
            "COLD rst_ni width=%d delay=%d release_clks=%d",
            self.plan.cold_width,
            self.copy_delay,
            res["release_clks"],
        )
        return {
            "src": src,
            "pat_b": pat_b,
            "pre": pre,
            "written": written,
            "sw_pre": sw_pre,
            "armed_pre": armed_pre,
            "intr_pre": intr_pre,
            "ctl_pre": ctl_pre,
            "dst_pre": dst_pre,
            "pst_pre": pst_pre,
        }

    async def _after_cold(self, c: dict) -> None:
        r1 = await self.mem.read(COPY_DST, COPY_WORDS)
        graded, unmoved, mism = [], [], []
        for r in DMA_REGS:
            if r.name not in c["pre"]:
                continue
            got = await self.dma.rd(r.addr)
            fc = field_compare(got, r.reset, r.mask)
            moved = (c["pre"][r.name] & r.mask) != (r.reset & r.mask)
            in_set = r.name in (*COPY_CFG, *RANGE_REGS, "RANGE_REGWEN", "HANDSHAKE_INTR_ENABLE")
            if in_set and moved:
                graded.append(r.name)
                if not fc.ok:
                    mism.append(f"{r.name}:{fc.fields()}")
            else:
                unmoved.append(f"{r.name}={got:#x}{'' if fc.ok else '(!=reset)'}")
        self.logger.info("OBS-DMA-COLD-UNMOVED: %s", " ".join(unmoved))
        # CONTROL (readable fields) and INTR_STATE are graded on every seed:
        # CTL-COLD-ARMED read both at a value other than their RDL reset.
        ctl = await self.dma.rd(CONTROL_ADDR)
        intr = await self.dma.rd(INTR_STATE_ADDR)
        for name, got, exp, msk in (
            ("CONTROL", ctl, CONTROL_RESET, CONTROL_RD_MASK),
            ("INTR_STATE", intr, INTR_STATE_RESET, INTR_STATE_MASK),
        ):
            graded.append(name)
            fc = field_compare(got, exp, msk)
            if not fc.ok:
                mism.append(f"{name}:{fc.fields()}")
        dst_st = await self._rd(DMA_STATUS_ADDR)
        pst = await self._rd(PERIPH_STATUS_ADDR)
        swv = await self._rd(SW)
        self.logger.info("OBS-SWRST-COLD-UNMOVED: fields=km,otbn,aes,kmac,trng,abr")
        # Control of CHK-RETAIN: every armed register reads its RDL default.
        defaults = 0
        regs = (*self._armed_probes(), *RANGE_PROBES)
        for p in regs:
            got = await self.pd.read(p)
            defaults += int(field_compare(got, p.reset, p.mask).ok)
        self.cold_defaults = (defaults, len(regs))
        await self._bank_ctl("COLD")
        await self._cycles(self.c)
        r2 = await self.mem.read(COPY_DST, COPY_WORDS)
        src_m = sum(1 for a, b in zip(r1, c["src"]) if a == b)
        b_m = sum(1 for a, b in zip(r1, c["pat_b"]) if a == b)
        dest_graded = src_m >= 1 and b_m >= 1
        unchanged = r1 == r2
        if not dest_graded:
            self.logger.info("OBS-DMA-COLD-MEM: src_match=%d patB_match=%d", src_m, b_m)
        ok = (
            not mism
            and (dst_st & DMA_ST_MASK) == 0
            and (pst & PERIPH_MASK) == 0
            and (swv & SW_FIELDS) == SW_DEFAULT
            and (c["sw_pre"] & SW_FIELDS) == SW_HMAC_HELD
            and (unchanged or not dest_graded)
        )
        self._chk(
            "CHK-DMA-COLDRST",
            ok,
            f"delay={self.copy_delay} regs={len(graded)} unmoved_logged={len(unmoved)} "
            f"mismatch={len(mism)} bus_err_status_pre=0x{c['dst_pre'] & DMA_ST_MASK:02x} "
            f"bus_err_status=0x{dst_st & DMA_ST_MASK:02x} "
            f"periph_status_pre=0x{c['pst_pre'] & PERIPH_MASK:02x} "
            f"periph_latch={self.plan.latch} periph_status=0x{pst & PERIPH_MASK:02x} "
            f"SW_RESET_N=0x{swv & SW_FIELDS:02x} dest_graded={int(dest_graded)} "
            f"dest_unchanged_after_reset={int(unchanged) if dest_graded else 'na'} "
            f"control_src_words={src_m} control_patB_words={b_m} "
            f"CONTROL_pre=0x{c['ctl_pre'] & CONTROL_RD_MASK:08x} "
            f"CONTROL=0x{ctl & CONTROL_RD_MASK:08x} INTR_STATE_pre=0x{c['intr_pre'] & INTR_STATE_MASK:x} "
            f"INTR_STATE=0x{intr & INTR_STATE_MASK:x} graded_regs={','.join(graded)}"
            + (f" {mism}" if mism else ""),
        )
        cd, cn = self.cold_defaults
        for cls in self.classes:
            if not self._retain_ok.get(cls):
                continue
            line = f"{self.retain[cls]} cold_leg_defaults={cd}/{cn}"
            if cls == "WDT":
                self._chk("CHK-RETAIN", cd == cn, line)
            else:
                self.retain[cls] = line
                if cd != cn:
                    raise AssertionError(f"CHK-RETAIN control: cold_leg_defaults={cd}/{cn}")

    # ---- step 11: recovery --------------------------------------------------------
    async def _recovery(self) -> None:
        lk = await self._rd(RANGE_REGWEN)
        rng_ok = lk == RANGE_REGWEN_RESET
        for p in RANGE_PROBES:
            got = await self.pd.read(p)
            rng_ok &= field_compare(got, p.reset, p.mask).ok
        self._ctl("CTL-RANGE-RESET", rng_ok, f"RANGE_REGWEN=0x{lk:x} range registers at reset")
        await self._open()
        src = self.plan.words(COPY_WORDS)
        pat_a = self.plan.words(COPY_WORDS, avoid=src)
        await self.mem.fill(COPY_SRC, src)
        await self.mem.fill(COPY_DST, pat_a)
        await self.dma.program_range(RANGE_LO, RANGE_HI, valid=True)
        await self._program_copy()
        st_addr = _D.addr("STATUS")
        await self.dma.wr(st_addr, ST_DONE | ST_CHUNK_DONE)
        st0 = await self.dma.read_status()
        if st0.done or st0.chunk_done:
            raise AssertionError(f"recovery: DONE/CHUNK_DONE not 0 after W1C: {st0.fmt()}")
        await self.dma.go()
        st = await self.dma.poll_status(
            lambda s: s.done or s.error, 4 * self.dma.done_bound(COPY_BYTES), "recovery"
        )
        dest = await self.mem.read(COPY_DST, COPY_WORDS)
        mism = sum(1 for a, b in zip(dest, src) if a != b)
        self._chk(
            "CHK-DMA-COLDRST-RECOVER",
            st.done == 1 and st.error == 0 and mism == 0,
            f"done={st.done} error={st.error} mem_mismatch={mism} words={COPY_WORDS}",
        )
        await self.dma.wr(st_addr, ST_DONE | ST_CHUNK_DONE)
        await self._close()

    # ---- step 12: run-request synchronizer (full-CPU build) ----------------------
    async def _follow(self, value: int, what: str) -> int:
        """Clocks until ``mpc_run_sync`` reads ``value`` (bounded)."""
        start = self.mpc.clk
        bound = SYNC_LAT + DBG_ALLOW + 8
        for _ in range(bound):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if self.mpc.level() == value:
                c = self.mpc.clk - start
                await FallingEdge(cocotb.top.clk_i)
                return c
        await FallingEdge(cocotb.top.clk_i)
        raise AssertionError(f"{what}: mpc_run_sync did not read {value} within {bound} clocks")

    async def _dbg_sync_leg(self) -> None:
        dut = cocotb.top
        lim = SYNC_LAT + DBG_ALLOW
        # Control, dbg_rstb_i high.
        ctl = []
        for v in (1, 0):
            await FallingEdge(dut.clk_i)
            dut.mpc_reset_run_req.value = v
            ctl.append(await self._follow(v, f"control toggle to {v}"))
        control_follow = all(c <= lim for c in ctl)
        self._ctl("CTL-DBG-SYNC", control_follow, f"follow_cycles={ctl} limit={lim}")
        # Error injection: toggle the input while dbg_rstb_i is low.
        await self._open()
        w = self.plan.dbg_sync_width
        await FallingEdge(dut.clk_i)
        dut.dbg_rstb_i.value = 0
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        held = self.mpc.level()
        await FallingEdge(dut.clk_i)
        toggles = 0
        constant = 0
        for i in range(w):
            if i == w // 2:
                dut.mpc_reset_run_req.value = 1
                toggles += 1
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            constant += int(self.mpc.level() == held)
            await FallingEdge(dut.clk_i)
        dut.dbg_rstb_i.value = 1
        f1 = await self._follow(1, "after the dbg_rstb_i release")
        await FallingEdge(dut.clk_i)
        dut.mpc_reset_run_req.value = 0
        f2 = await self._follow(0, "toggle after the release")
        self._chk(
            "CHK-DBG-SYNC",
            constant == w and toggles >= 1 and f1 <= lim and f2 <= lim and control_follow,
            f"constant_cycles={constant}/{w} toggles_in_window={toggles} held={held} "
            f"follow_cycles={f1},{f2} limit={lim} control_follow={int(control_follow)}",
        )
        await self._close()
