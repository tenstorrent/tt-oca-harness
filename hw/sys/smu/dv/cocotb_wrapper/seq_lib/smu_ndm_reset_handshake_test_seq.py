# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_ndm_reset_handshake_test. No Force.

Steps S1-S8, checkers CHK-NDM-REQUEST-S1..S4 and CHK-NDM-PROCESS-S1..S3.
Spec: hw/sys/smc/regs/blocks/ndm_reset/ndm_reset.rdl,
doc/integrator/src/smu-smc.adoc (External CPU cluster NDM reset),
hw/sys/smu/doc/port_table.adoc.

``NDMRESET_REQUEST`` is the read-only mirror of ``smc_ndmreset_request_i``.
``NDMRESET_PROCESS`` is a 32-bit register whose low lanes drive
``smc_ndmreset_process_o``. The harness has four clusters, and
``NDMRESET_CLUSTER_COUNT`` reads that count back.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_boundary_regs import ndm_reset_u32
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_pack32,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

NDMRESET_REQUEST = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_REQUEST_BASE_ADDR")
NDMRESET_PROCESS = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_PROCESS_BASE_ADDR")
NDMRESET_CLUSTER_COUNT = smc_addr(
    "SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR"
)

REQUEST_BM = ndm_reset_u32("NDM_RESET__NDMRESET_REQUEST__NDMRESET_REQUEST_bm")
REQUEST_RESET = ndm_reset_u32("NDM_RESET__NDMRESET_REQUEST__NDMRESET_REQUEST_reset")
PROCESS_BM = ndm_reset_u32("NDM_RESET__NDMRESET_PROCESS__NDMRESET_PROCESS_bm")
PROCESS_RESET = ndm_reset_u32("NDM_RESET__NDMRESET_PROCESS__NDMRESET_PROCESS_reset")

CLUSTER_COUNT = 4
CLUSTER_MASK = (1 << CLUSTER_COUNT) - 1
LANES = (0, 3)

RESET_PULSE_REF_CYCLES = 64
RESET_RELEASE_BOUND_REF_CYCLES = 8192
POLL_BOUND_SMU_CYCLES = 64
POLL_BOUND_CSR_READS = 64
SYNC_CYCLES = 32

STEP_ORDER = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "PASS"]


class smu_ndm_reset_handshake_test_seq:
    """NDM reset request and process paths between the SMC registers and the boundary pins."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.steps: list[str] = []

    def _sample(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _rd32(self, addr: int, what: str) -> int:
        status, rdata = await jtag2axi_single_read(
            self.jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, rdata)

    async def _wr32(self, addr: int, data: int, what: str) -> None:
        wstrb, beat = axi64_pack32(addr, data)
        status, _ = await jtag2axi_single_write(
            self.jtag,
            addr,
            beat,
            wstrb=wstrb,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} write @0x{addr:08x} status={status}")

    async def _wait_level(self, name: str, level: int, bound: int, what: str) -> None:
        for _ in range(bound):
            if self._sample(name) & 1 == level:
                return
            await RisingEdge(self.dut.clk_ref_i)
        raise AssertionError(f"TIMEOUT {what}: {name} never read {level} within {bound} clk_ref")

    def _require_csr_path(self) -> None:
        if self._sample("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI gated; the NDM reset CSRs cannot be accessed")

    async def _open_tap(self) -> None:
        self.jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        self._require_csr_path()

    async def _poll_request_bit(self, lane: int, level: int) -> int:
        """Read NDMRESET_REQUEST until bit ``lane`` reads ``level``; return that read."""
        for _ in range(POLL_BOUND_CSR_READS):
            value = await self._rd32(NDMRESET_REQUEST, "NDMRESET_REQUEST")
            if (value >> lane) & 1 == level:
                return value
        raise AssertionError(
            f"TIMEOUT NDMRESET_REQUEST[{lane}] never read {level} in {POLL_BOUND_CSR_READS} reads"
        )

    async def _poll_process_port(self, lane: int, level: int) -> int:
        """Sample the process port each clk_smu cycle until bit ``lane`` reads ``level``."""
        for _ in range(POLL_BOUND_SMU_CYCLES):
            value = self._sample("tb_smc_ndmreset_process")
            if (value >> lane) & 1 == level:
                return value
            await RisingEdge(self.dut.clk_smu_i)
        raise AssertionError(
            f"TIMEOUT smc_ndmreset_process_o[{lane}] never read {level} within "
            f"{POLL_BOUND_SMU_CYCLES} clk_smu"
        )

    async def _poll_process_value(self, want: int) -> int:
        """Sample the process port each clk_smu cycle until it reads ``want``."""
        value = -1
        for _ in range(POLL_BOUND_SMU_CYCLES):
            value = self._sample("tb_smc_ndmreset_process")
            if value == want:
                return value
            await RisingEdge(self.dut.clk_smu_i)
        return value

    async def _cold_reset(self) -> None:
        dut = self.dut
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, RESET_PULSE_REF_CYCLES)
        dut.rst_cold_ni.value = 1
        await self._wait_level(
            "rst_cold_n_o", 1, RESET_RELEASE_BOUND_REF_CYCLES, "cold reset release"
        )
        await self._wait_level(
            "obs_smc_rst_n_o", 1, RESET_RELEASE_BOUND_REF_CYCLES, "cold reset SMC release"
        )
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        await self._open_tap()

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        await self._open_tap()
        dut.tb_smc_ndmreset_request.value = 0
        self.steps.append("S1")

        # S2: single request lanes rise and fall in the register.
        for lane in LANES:
            vector = 1 << lane
            dut.tb_smc_ndmreset_request.value = vector
            seen = await self._poll_request_bit(lane, 1)
            sb.expect_eq(
                f"NDMRESET_REQUEST reads 0x{vector:x} while smc_ndmreset_request_i[{lane}] is high",
                seen & REQUEST_BM,
                vector,
                evidence="NDM_REQUEST_S1",
            )
            dut.tb_smc_ndmreset_request.value = 0
            seen = await self._poll_request_bit(lane, 0)
            sb.expect_eq(
                f"NDMRESET_REQUEST reads 0 after smc_ndmreset_request_i[{lane}] falls",
                seen & REQUEST_BM,
                0,
                evidence="NDM_REQUEST_S1",
            )
        self.steps.append("S2")

        # S3: all four request lanes high; bits above the cluster count read 0.
        dut.tb_smc_ndmreset_request.value = CLUSTER_MASK
        for lane in range(CLUSTER_COUNT):
            await self._poll_request_bit(lane, 1)
        seen = await self._rd32(NDMRESET_REQUEST, "NDMRESET_REQUEST")
        sb.expect_eq(
            "NDMRESET_REQUEST reads 0x0000000F with all four request pins high",
            seen & REQUEST_BM,
            CLUSTER_MASK,
            evidence="NDM_REQUEST_S2",
        )
        self.steps.append("S3")

        # S4: the cluster count register.
        count = await self._rd32(NDMRESET_CLUSTER_COUNT, "NDMRESET_CLUSTER_COUNT")
        sb.expect_eq(
            f"NDMRESET_CLUSTER_COUNT reads {CLUSTER_COUNT}",
            count,
            CLUSTER_COUNT,
            evidence="NDM_REQUEST_S3",
        )
        self.steps.append("S4")

        # S5: NDMRESET_REQUEST read after a cold reset with the request pins low.
        dut.tb_smc_ndmreset_request.value = 0
        await self._cold_reset()
        seen = await self._rd32(NDMRESET_REQUEST, "NDMRESET_REQUEST")
        sb.expect_eq(
            "NDMRESET_REQUEST reads 0 with all request pins low after a cold reset",
            seen & REQUEST_BM,
            REQUEST_RESET,
            evidence="NDM_REQUEST_S4",
        )
        dut.tb_smc_ndmreset_request.value = 1
        seen = await self._poll_request_bit(0, 1)
        sb.expect_eq(
            "NDMRESET_REQUEST follows request pin 0 after the cold reset",
            seen & REQUEST_BM,
            0x1,
            evidence="NDM_REQUEST_S4",
        )
        dut.tb_smc_ndmreset_request.value = 0
        await self._poll_request_bit(0, 0)
        self.steps.append("S5")

        # S6: single process lanes reach the port and clear again.
        for lane in LANES:
            vector = 1 << lane
            await self._wr32(NDMRESET_PROCESS, vector, "NDMRESET_PROCESS")
            seen = await self._poll_process_port(lane, 1)
            sb.expect_eq(
                f"smc_ndmreset_process_o reads 0x{vector:x} after NDMRESET_PROCESS=0x{vector:x}",
                seen,
                vector,
                evidence="NDM_PROCESS_S1",
            )
            await self._wr32(NDMRESET_PROCESS, 0, "NDMRESET_PROCESS")
            seen = await self._poll_process_port(lane, 0)
            sb.expect_eq(
                f"smc_ndmreset_process_o reads 0 after NDMRESET_PROCESS[{lane}] clears",
                seen,
                0,
                evidence="NDM_PROCESS_S1",
            )
        self.steps.append("S6")

        # S7: bits at and above the cluster count are stored and have no lane.
        for written, lanes in ((0xFFFF_FFF0, 0x0), (0xFFFF_FFFF, CLUSTER_MASK)):
            await self._wr32(NDMRESET_PROCESS, written, "NDMRESET_PROCESS")
            readback = await self._rd32(NDMRESET_PROCESS, "NDMRESET_PROCESS")
            sb.expect_eq(
                f"NDMRESET_PROCESS reads back 0x{written & PROCESS_BM:08x}",
                readback,
                written & PROCESS_BM,
                evidence="NDM_PROCESS_S2",
            )
            sb.expect_eq(
                f"smc_ndmreset_process_o reads 0x{lanes:x} with NDMRESET_PROCESS=0x{written:08x}",
                await self._poll_process_value(lanes),
                lanes,
                evidence="NDM_PROCESS_S2",
            )
        self.steps.append("S7")

        # S8: cold reset clears NDMRESET_PROCESS and the port.
        dut.tb_smc_ndmreset_request.value = 0
        await self._cold_reset()
        readback = await self._rd32(NDMRESET_PROCESS, "NDMRESET_PROCESS")
        sb.expect_eq(
            f"NDMRESET_PROCESS reads its reset value {PROCESS_RESET} after the cold reset",
            readback,
            PROCESS_RESET,
            evidence="NDM_PROCESS_S3",
        )
        sb.expect_eq(
            "smc_ndmreset_process_o reads 0 after the cold reset",
            self._sample("tb_smc_ndmreset_process"),
            0,
            evidence="NDM_PROCESS_S3",
        )
        self.steps.append("S8")

        self.steps.append("PASS")
        if self.steps != STEP_ORDER:
            raise AssertionError(f"CHK-NONVAC order fail: {self.steps} != {STEP_ORDER}")
        self.log.info("CHK-NONVAC: PASS (ordered fence S1<S2<S3<S4<S5<S6<S7<S8<PASS)")
