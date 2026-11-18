# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A read the I2C peripheral has accepted completes once when its clock-gate enable is set.

``clk_rst.adoc`` "Subsystem Controls and Clock Gating": the leg is redirected as soon as the
``CLOCK_GATE_CONTROL`` write completes; an access the peripheral has already accepted finishes
there, since its clock stops only after the enable has crossed into its domain.

The I2C leg is the one the bench probes on the peripheral side of the AXI-Lite CDC
(``tb_periph_cdc_arvalid``, ``tb_periph_cdc_arready`` and ``tb_periph_cdc_rvalid`` on
``clk_periph_i``). The arm leg reads I2C_CTRL over JTAG AXI with the gate open and then closed:
the open read handshakes one AR at the peripheral, answers OKAY with the reset word and leaves
the leg idle; the closed read handshakes nothing there and answers SLVERR with 0xBADCAB1E. Each
trial then issues one I2C_CTRL read on JTAG AXI and the ``I2C_CG_EN`` set on SEP_IN, with the
read launched a swept number of ``clk_smc_i`` cycles before or after the write. The
peripheral-side AR handshake decides which rule the read is held to: accepted there, it must
answer OKAY with the reset word; not accepted, it must answer SLVERR with 0xBADCAB1E. A read
that gets no response within its bound fails, and so does a leg that is still presenting a
response after the read has completed: that response belongs to no outstanding read, and the
I2C_STATUS word read after the enable is cleared shows whether later reads receive it. Both
outcomes must occur within the sweep, and after every trial the window reads SLVERR until the
enable is cleared and its reset word afterwards.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import CLOCK_GATE_CONTROL, smc_indexed_addr
from .smc_clock_gated_window_slverr_test_seq import (
    AXI_RESP_OKAY,
    AXI_RESP_SLVERR,
    GATED_RDATA,
    PERIPHERALS,
    POLL_BOUND_CYCLES,
    POLL_SPACING_CYCLES,
)
from .smc_csr_seq_utils import SmcCsrSeq

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import I2C_STATUS_REG_DEFAULT  # noqa: E402

_I2C_NAME, I2C_CG_EN, I2C_WINDOW, I2C_RESET = PERIPHERALS[2]
#: I2C0 STATUS, a read-only word with a non-zero reset on the same CDC leg; a read of it that
#: returns another register's word shows a response delivered to the wrong read.
I2C_STATUS = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", 0)
#: Launch offsets of the JTAG read relative to the SEP_IN enable write, in clk_smc_i cycles;
#: negative launches the read first.
_OFFSETS = tuple(range(-64, 65, 4))
#: Bound on one trial read; expiry is a hang and fails the trial.
_READ_TIMEOUT_NS = 20_000
#: Consecutive idle clk_periph_i rises the I2C leg must show after a read has completed, and
#: the ceiling on reaching them.
_QUIET_PERIPH = 16
_QUIET_BOUND_PERIPH = 512

CHK = "CHK-ACCEPTED-ACCESS-COMPLETES-ACROSS-GATE"
CHK_ARM = "CHK-CG-INFLIGHT-ARM"


def _int(sig) -> int:
    assert sig.value.is_resolvable, f"X/Z on {sig._name}: {sig.value}"
    return int(sig.value)


class _CdcMon:
    """clk_periph_i counter of AR and R handshakes on the I2C leg of the peripheral CDC."""

    def __init__(self) -> None:
        self.edge = 0
        self.ar_edges: list[int] = []
        self.r_edges: list[int] = []
        self._task = None

    def arm(self) -> None:
        self.edge = 0
        self.ar_edges = []
        self.r_edges = []

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_periph_i)
            self.edge += 1
            if _int(dut.tb_periph_cdc_arvalid) and _int(dut.tb_periph_cdc_arready):
                self.ar_edges.append(self.edge)
            if _int(dut.tb_periph_cdc_rvalid):
                self.r_edges.append(self.edge)


class smc_clock_gate_inflight_completes_test_seq(SmcCsrSeq):
    """Sweep the read launch against the enable write and hold each read to its rule."""

    def __init__(self, name: str = "smc_clock_gate_inflight_completes_test_seq") -> None:
        super().__init__(name)
        self.trials: list[dict] = []
        self.jtag_accesses = 0
        self._edges = 0
        self._mon = _CdcMon()

    async def _count_edges(self) -> None:
        while True:
            await RisingEdge(cocotb.top.clk_smc_i)
            self._edges += 1

    async def _read_any(self, name: str, addr: int) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{name}: read returned no response code"
        return item

    async def _poll(self, name: str, want_resp: int) -> tuple[SmcSysAxiItem, int]:
        """Re-read the I2C window until it answers ``want_resp``; fail after the bound."""
        start = self._edges
        while True:
            item = await self._read_any(f"{name}_POLL", I2C_WINDOW)
            elapsed = self._edges - start
            done = item.resp_code == want_resp and (
                want_resp != AXI_RESP_SLVERR or item.rdata == GATED_RDATA
            )
            if done:
                return item, elapsed
            assert elapsed < POLL_BOUND_CYCLES, (
                f"{name}: I2C window did not reach resp={want_resp} within {POLL_BOUND_CYCLES} "
                f"clk_smc_i cycles; last resp={item.resp_code} rdata=0x{item.rdata:08x}"
            )
            await ClockCycles(cocotb.top.clk_smc_i, POLL_SPACING_CYCLES)

    async def _ungate(self, label: str) -> None:
        await self.csr_write(f"CGC_CLR_{label}", CLOCK_GATE_CONTROL, self.base)
        await self.csr_read(f"CGC_CLR_RB_{label}", CLOCK_GATE_CONTROL, expected=self.base)
        item, _ = await self._poll(f"UNGATED_{label}", AXI_RESP_OKAY)
        assert item.rdata == I2C_RESET, (
            f"{label}: I2C window read 0x{item.rdata:08x} after the enable cleared, "
            f"reset 0x{I2C_RESET:08x}"
        )

    async def _await_quiet(self, label: str) -> dict | None:
        """None once the leg idles for the required rises; else the levels seen in the bound."""
        dut = cocotb.top
        idle = 0
        high = {"arvalid": 0, "arready": 0, "rvalid": 0, "cg_en": 0, "rises": 0}
        for _ in range(_QUIET_BOUND_PERIPH):
            await RisingEdge(dut.clk_periph_i)
            arvalid = _int(dut.tb_periph_cdc_arvalid)
            rvalid = _int(dut.tb_periph_cdc_rvalid)
            high["arvalid"] += arvalid
            high["arready"] += _int(dut.tb_periph_cdc_arready)
            high["rvalid"] += rvalid
            high["cg_en"] += _int(dut.tb_i2c_cg_en)
            high["rises"] += 1
            idle = 0 if (arvalid or rvalid) else idle + 1
            if idle >= _QUIET_PERIPH:
                return None
        return high

    async def _jtag_read(self, label: str) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"rd_jtag_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = I2C_WINDOW
        item.length = 4
        item.allow_error = True
        item.allow_timeout = True
        item.timeout_ns = _READ_TIMEOUT_NS
        await _OneShot(item, f"jtag_{label}").start(self.env.jtag_axi_agent.sequencer)
        self.jtag_accesses += 1
        return item

    async def _arm(self) -> None:
        """Gate open: one AR at the peripheral, OKAY, idle after. Gate closed: none, SLVERR."""
        self._mon.arm()
        item = await self._jtag_read("ARM_OPEN")
        busy = await self._await_quiet("ARM_OPEN")
        open_ar = list(self._mon.ar_edges)
        open_r = len(self._mon.r_edges)
        assert not item.timed_out and item.resp_code == AXI_RESP_OKAY and item.rdata == I2C_RESET, (
            f"{CHK_ARM} FAIL: gate open: JTAG read timed_out={item.timed_out} resp={item.resp_code} "
            f"rdata=0x{item.rdata:08x}, want OKAY 0x{I2C_RESET:08x}"
        )
        assert len(open_ar) == 1 and open_r >= 1 and busy is None, (
            f"{CHK_ARM} FAIL: gate open: AR handshakes at the peripheral {open_ar} (want one), "
            f"rvalid seen on {open_r} rises (want at least one) and the leg after the read "
            f"{busy or 'idle'}"
        )
        await self.csr_write("CGC_ARM_SET", CLOCK_GATE_CONTROL, self.base | I2C_CG_EN)
        await self._poll("ARM_GATED", AXI_RESP_SLVERR)
        self._mon.arm()
        item = await self._jtag_read("ARM_CLOSED")
        busy = await self._await_quiet("ARM_CLOSED")
        closed_ar = list(self._mon.ar_edges)
        closed_r = len(self._mon.r_edges)
        assert (
            not item.timed_out and item.resp_code == AXI_RESP_SLVERR and item.rdata == GATED_RDATA
        ), (
            f"{CHK_ARM} FAIL: gate closed: JTAG read timed_out={item.timed_out} "
            f"resp={item.resp_code} rdata=0x{item.rdata:08x}, want SLVERR 0x{GATED_RDATA:08x}"
        )
        assert not closed_ar and closed_r == 0 and busy is None, (
            f"{CHK_ARM} FAIL: gate closed: AR handshakes at the peripheral {closed_ar} (want none), "
            f"rvalid seen on {closed_r} rises (want none) and the leg after the read "
            f"{busy or 'idle'}"
        )
        await self._ungate("ARM")
        cocotb.log.info(
            "%s: gate open: JTAG I2C_CTRL read OKAY 0x%08x with one AR handshake at the "
            "peripheral (clk_periph_i rise %d), rvalid seen on %d rises and the leg idle for %d "
            "rises after it; gate closed: SLVERR 0x%08x with no AR handshake and no rvalid there "
            "and the leg idle; enable cleared, window reads its reset word",
            CHK_ARM,
            I2C_RESET,
            open_ar[0],
            open_r,
            _QUIET_PERIPH,
            GATED_RDATA,
        )

    async def _trial(self, offset: int) -> dict:
        dut = cocotb.top
        label = f"OFF{offset:+d}"
        item = SmcSysAxiItem(f"rd_jtag_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = I2C_WINDOW
        item.length = 4
        item.allow_error = True
        item.allow_timeout = True
        item.timeout_ns = _READ_TIMEOUT_NS

        async def launch_read() -> None:
            if offset > 0:
                await ClockCycles(dut.clk_smc_i, offset)
            await _OneShot(item, f"jtag_{label}").start(self.env.jtag_axi_agent.sequencer)

        async def launch_write() -> None:
            if offset < 0:
                await ClockCycles(dut.clk_smc_i, -offset)
            await self.csr_write(f"CGC_SET_{label}", CLOCK_GATE_CONTROL, self.base | I2C_CG_EN)

        self._mon.arm()
        read_task = cocotb.start_soon(launch_read())
        await launch_write()
        await read_task
        self.jtag_accesses += 1
        busy = await self._await_quiet(label)
        row = {
            "offset": offset,
            "accepted_periph": bool(self._mon.ar_edges),
            "ar_edges": list(self._mon.ar_edges),
            "r_edges": len(self._mon.r_edges),
            "timed_out": item.timed_out,
            "resp": item.resp_code,
            "rdata": item.rdata,
        }
        if busy is not None:
            await self.csr_write(f"CGC_CLR_{label}", CLOCK_GATE_CONTROL, self.base)
            await self.csr_read(f"CGC_CLR_RB_{label}", CLOCK_GATE_CONTROL, expected=self.base)
            status = await self.csr_read(f"I2C_STATUS_AFTER_{label}", I2C_STATUS)
            if item.timed_out or busy["arvalid"] or not busy["rvalid"]:
                what = "a request or no response still pending"
            else:
                what = "a completed read left r_valid still presented"
            raise AssertionError(
                f"{CHK} FAIL: read launched {offset:+d} clk_smc_i cycles from the I2C_CG_EN write "
                f"completed timed_out={item.timed_out} resp={item.resp_code} "
                f"rdata=0x{item.rdata:08x} with AR handshakes at the peripheral "
                f"{row['ar_edges']}, then the peripheral side of the I2C CDC never idled: {what}, "
                f"rises high {busy}; with the enable cleared the I2C0 STATUS read returned "
                f"0x{status:08x}, reset 0x{I2C_STATUS_REG_DEFAULT:08x}; trials before this one: "
                f"{len(self.trials)} completed with the leg idle"
            )
        _, gated_after = await self._poll(f"GATED_{label}", AXI_RESP_SLVERR)
        row["slverr_after_cycles"] = gated_after
        await self._ungate(label)
        return row

    @staticmethod
    def _verdict(row: dict) -> str:
        if row["timed_out"]:
            return "HANG"
        if row["accepted_periph"]:
            ok = row["resp"] == AXI_RESP_OKAY and row["rdata"] == I2C_RESET
            return "ACCEPTED-OKAY" if ok else "ACCEPTED-WRONG"
        ok = row["resp"] == AXI_RESP_SLVERR and row["rdata"] == GATED_RDATA
        return "REDIRECTED-SLVERR" if ok else "REDIRECTED-WRONG"

    async def body(self) -> None:
        dut = cocotb.top
        for name in (
            "tb_periph_cdc_arvalid",
            "tb_periph_cdc_arready",
            "tb_periph_cdc_rvalid",
            "tb_i2c_cg_en",
        ):
            assert hasattr(dut, name), f"{name} missing from tb_top"
        cocotb.start_soon(self._count_edges())
        await self.wait_fuse_sense_done()
        original = await self.csr_read("CGC_SAVE", CLOCK_GATE_CONTROL)
        self.base = original & ~I2C_CG_EN
        if original != self.base:
            await self.csr_write("CGC_BASE", CLOCK_GATE_CONTROL, self.base)
        await self.csr_read("I2C_UNGATED", I2C_WINDOW, expected=I2C_RESET)

        self._mon.start()
        try:
            await self._arm()
            for offset in _OFFSETS:
                self.trials.append(await self._trial(offset))
        finally:
            self._mon.stop()
        await self.csr_write("CGC_RESTORE", CLOCK_GATE_CONTROL, original)
        await self.csr_read("CGC_RESTORE_RB", CLOCK_GATE_CONTROL, expected=original)

        verdicts = [self._verdict(r) for r in self.trials]
        table = "; ".join(
            f"off={r['offset']:+d} ar={r['ar_edges']} rvalid_rises={r['r_edges']} "
            f"resp={r['resp']} rdata=0x{r['rdata']:08x} {v}"
            for r, v in zip(self.trials, verdicts)
        )
        accepted = verdicts.count("ACCEPTED-OKAY")
        redirected = verdicts.count("REDIRECTED-SLVERR")
        bad = [
            (r["offset"], v) for r, v in zip(self.trials, verdicts) if v.endswith(("WRONG", "HANG"))
        ]
        assert not bad, (
            f"{CHK} FAIL: {len(bad)} of {len(self.trials)} trials broke the rule: {bad}; "
            f"accepted-and-OKAY {accepted}, redirected-SLVERR {redirected}; {table}"
        )
        assert accepted >= 1 and redirected >= 1, (
            f"{CHK} FAIL: the sweep of {len(self.trials)} launch offsets {_OFFSETS[0]:+d}.."
            f"{_OFFSETS[-1]:+d} clk_smc_i did not produce both outcomes (accepted-and-OKAY "
            f"{accepted}, redirected-SLVERR {redirected}); {table}"
        )
        cocotb.log.info(
            "%s: %d trials, read launched %+d..%+d clk_smc_i cycles around the I2C_CG_EN write: "
            "%d reads accepted at the peripheral-side AR of the CDC answered OKAY 0x%08x, %d "
            "reads not accepted there answered SLVERR 0x%08x, 0 hung within %d ns, the leg idled "
            "after every read; after every trial the window read SLVERR within %d cycles and its "
            "reset word once the enable cleared; %s",
            CHK,
            len(self.trials),
            _OFFSETS[0],
            _OFFSETS[-1],
            accepted,
            I2C_RESET,
            redirected,
            GATED_RDATA,
            _READ_TIMEOUT_NS,
            POLL_BOUND_CYCLES,
            table,
        )
