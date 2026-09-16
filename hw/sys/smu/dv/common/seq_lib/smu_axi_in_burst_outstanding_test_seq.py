# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI-IN depth and burst type on the inbound SMN port, through an open window.

Every enrolled inbound test issues one single-beat transfer at a time and
expects OKAY or DECERR, so the inbound port has never had more than one
transaction in flight and has never been offered a burst type the SMC
register path does not implement.

S1: a train of reads and a train of writes, each launched without waiting for
    the one before it and with the matching response channel held back so the
    trains queue up inside the DUT. The reads must all return the RDL reset
    value, and the writes, which share one AWID so the ordering is fixed, must
    leave the last value they wrote in the register.
S2: a WRAP burst and a multi-beat FIXED burst at the same register target.
    The AXI4-to-AXI-Lite conversion in front of the SMC register blocks
    implements INCR only and answers an unsupported burst with SLVERR, which
    is a different verdict from the DECERR a filter or decode miss returns --
    the transfer reached a subordinate and was refused there.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_axi_vip import RESP_OKAY, RESP_SLVERR, AxiTimingProfile, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    smc_addr,
)
from seq_lib.smu_axi_helpers import AXI_TIMEOUT_NS, make_smu_axi_master
from seq_lib.smu_filter_helpers import PASS_ALL_END, await_smn_resp, program_inbound0_window
from seq_lib.smu_jtag_helpers import DTP_DEFAULT_IDCODE, make_smu_jtag_tap
from seq_lib.smu_tb_pins import smc_primary_reset

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
SCRATCH_COLD = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")

# Transactions launched before the first response is collected.
OUTSTANDING = 64
# Cycles the master keeps BREADY / RREADY low once a train is armed, so the
# responses back up into the address channels while the train is still being
# offered. The pause releases itself, so every transfer still completes.
RESP_BACKPRESSURE_CYCLES = 600
# One AWID for the whole write train, so AXI orders them and the last value
# written is the one the register must hold.
WRITE_ID = 0x27
SCRATCH_PATTERN_BASE = 0x51D0_0000

# 4 beats x 4 bytes = a 16-byte wrapping window, and VERSION_LO is 16-byte
# aligned, so the burst is legal AXI and only its type is unsupported.
BURST_BEATS = 4
BURST_SIZE = 2
AXI_BURST_FIXED = 0
AXI_BURST_WRAP = 2


class smu_axi_in_burst_outstanding_test_seq:
    """Inbound SMN depth and unsupported burst types behind an open window."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_int(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _open_window(self, sb):
        dut = self.dut
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        await program_inbound0_window(jtag, 0, PASS_ALL_END, scoreboard=sb, tag="AXIIN_WIDE")
        return jtag

    async def _step_outstanding(self, master, sb) -> None:
        """S1: a train of reads and a train of writes, all in flight at once."""
        dut = self.dut

        master.driver.set_timing(AxiTimingProfile(r_ready_delay=RESP_BACKPRESSURE_CYCLES))
        read_tasks = [
            cocotb.start_soon(
                master.read_bytes_result(
                    VERSION_LO,
                    4,
                    id=idx,
                    check_response=False,
                    timeout_ns=AXI_TIMEOUT_NS,
                    allow_timeout=True,
                )
            )
            for idx in range(OUTSTANDING)
        ]
        reads = [await task for task in read_tasks]
        for idx, result in enumerate(reads):
            if result.timed_out:
                raise AssertionError(f"TIMEOUT s1 read {idx}: bound={AXI_TIMEOUT_NS}ns")
        resps = {resp_name(r.resp) for r in reads}
        words = {int(r.data) & 0xFFFF_FFFF for r in reads}
        sb.expect_eq(
            "CHK-AXIIN-DEPTH-RD every concurrent read is OKAY",
            resps,
            {resp_name(RESP_OKAY)},
        )
        sb.expect_eq(
            "CHK-AXIIN-DEPTH-RD every concurrent read returns the reset value",
            words,
            {VERSION_LO_RESET},
            evidence="CHK-AXIIN-DEPTH",
        )

        master.driver.set_timing(AxiTimingProfile(b_ready_delay=RESP_BACKPRESSURE_CYCLES))
        payloads = [(SCRATCH_PATTERN_BASE + idx) & 0xFFFF_FFFF for idx in range(OUTSTANDING)]
        write_tasks = [
            cocotb.start_soon(
                master.write_bytes_result(
                    SCRATCH_COLD,
                    value.to_bytes(4, byteorder="little"),
                    id=WRITE_ID,
                    check_response=False,
                    timeout_ns=AXI_TIMEOUT_NS,
                    allow_timeout=True,
                )
            )
            for value in payloads
        ]
        writes = [await task for task in write_tasks]
        for idx, result in enumerate(writes):
            if result.timed_out:
                raise AssertionError(f"TIMEOUT s1 write {idx}: bound={AXI_TIMEOUT_NS}ns")
        sb.expect_eq(
            "CHK-AXIIN-DEPTH-WR every concurrent write is OKAY",
            {resp_name(w.resp) for w in writes},
            {resp_name(RESP_OKAY)},
        )
        master.driver.set_timing(AxiTimingProfile())
        await ClockCycles(dut.clk_smu_i, 32)
        settled = await master.read_bytes_result(
            SCRATCH_COLD, 4, check_response=False, timeout_ns=AXI_TIMEOUT_NS, allow_timeout=True
        )
        if settled.timed_out:
            raise AssertionError(f"TIMEOUT s1 scratch readback: bound={AXI_TIMEOUT_NS}ns")
        sb.expect_eq(
            "CHK-AXIIN-DEPTH-WR same-ID train leaves the last value written",
            int(settled.data) & 0xFFFF_FFFF,
            payloads[-1],
            evidence="CHK-AXIIN-DEPTH-ORDER",
        )
        self._log(
            f"CHK-AXIIN-DEPTH: {OUTSTANDING} reads and {OUTSTANDING} writes in flight; "
            f"scratch=0x{int(settled.data) & 0xFFFF_FFFF:08x} last_written=0x{payloads[-1]:08x}"
        )
        self.s1_ok = True

    async def _step_burst_type(self, master, sb) -> None:
        """S2: WRAP and multi-beat FIXED at a register target are refused."""
        wrap = await master.burst_read_result(
            VERSION_LO,
            BURST_BEATS * (1 << BURST_SIZE),
            size=BURST_SIZE,
            burst=AXI_BURST_WRAP,
            check_response=False,
            timeout_ns=AXI_TIMEOUT_NS,
            allow_timeout=True,
        )
        if wrap.timed_out:
            raise AssertionError(f"TIMEOUT s2 wrap read: bound={AXI_TIMEOUT_NS}ns")
        sb.expect_eq(
            "CHK-AXIIN-BURST-WRAP read refused with SLVERR",
            resp_name(wrap.resp),
            resp_name(RESP_SLVERR),
            evidence="CHK-AXIIN-BURST",
        )

        fixed = await master.burst_write_result(
            SCRATCH_COLD,
            [SCRATCH_PATTERN_BASE ^ (idx + 1) for idx in range(BURST_BEATS)],
            size=BURST_SIZE,
            burst=AXI_BURST_FIXED,
            check_response=False,
            timeout_ns=AXI_TIMEOUT_NS,
            allow_timeout=True,
        )
        if fixed.timed_out:
            raise AssertionError(f"TIMEOUT s2 fixed write: bound={AXI_TIMEOUT_NS}ns")
        sb.expect_eq(
            "CHK-AXIIN-BURST-FIXED multi-beat write refused with SLVERR",
            resp_name(fixed.resp),
            resp_name(RESP_SLVERR),
            evidence="CHK-AXIIN-BURST-FIXED",
        )
        self._log(
            f"CHK-AXIIN-BURST: wrap_read={resp_name(wrap.resp)} fixed_write={resp_name(fixed.resp)}"
        )
        self.s2_ok = True

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard
        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)

        await self._open_window(sb)
        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        await await_smn_resp(
            master, VERSION_LO, RESP_OKAY, clk=dut.clk_smu_i, label="axiin_window_ready"
        )

        await self._step_outstanding(master, sb)
        await self._step_burst_type(master, sb)
