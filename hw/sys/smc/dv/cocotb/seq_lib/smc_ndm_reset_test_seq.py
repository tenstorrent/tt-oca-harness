# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""NDM request pin and AXI PROCESS CSR. No Force, no firmware."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

NDM_REQUEST = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_REQUEST_BASE_ADDR")
NDM_PROCESS = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_PROCESS_BASE_ADDR")
NDM_CLUSTERS = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR")
# smc_config_pkg::CPU_CLUSTER_COUNT — TB pin width tracks this.
_CLUSTERS = 4
_PIN_BOUND = 64


class smc_ndm_reset_test_seq(SmcCsrSeq):
    """Pin→CSR→IRQ→PROCESS handshake, one bit at a time."""

    def __init__(self, name: str = "smc_ndm_reset_test_seq") -> None:
        super().__init__(name)
        self.count_ok = False
        self.bits_ok = False

    async def _await_pins(self, dut, irq: int, process: int, label: str) -> None:
        last = {}
        for _ in range(_PIN_BOUND):
            await RisingEdge(dut.clk_smc_i)
            last = {
                "irq": int(dut.tb_ndmreset_irq.value),
                "process": int(dut.tb_ndmreset_process.value),
            }
            if last["irq"] == irq and last["process"] == process:
                return
        raise AssertionError(
            f"{label}: pin handshake expired irq={last.get('irq')} "
            f"process=0x{last.get('process', 0):x} want irq={irq} "
            f"process=0x{process:x}"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_ndmreset_request"), "tb_ndmreset_request missing"
        assert int(dut.tb_ndmreset_request.value) == 0, "NDM request must idle 0"

        nclu = await self.csr_read("NDM_CLUSTER_COUNT", NDM_CLUSTERS)
        assert (nclu & 0xFF) == _CLUSTERS, f"CLUSTER_COUNT=0x{nclu:x} want {_CLUSTERS}"
        self.count_ok = True
        cocotb.log.info("CHK-NDM-COUNT: CLUSTER_COUNT=%d", nclu & 0xFF)

        req0 = await self.csr_read("NDM_REQUEST_IDLE", NDM_REQUEST, expected=0)
        proc0 = await self.csr_read("NDM_PROCESS_IDLE", NDM_PROCESS, expected=0)
        await self._await_pins(dut, irq=0, process=0, label="IDLE")
        cocotb.log.info("CHK-NDM-IDLE: REQUEST=0x%x PROCESS=0x%x irq=0", req0, proc0)

        for bit in range(_CLUSTERS):
            mask = 1 << bit
            dut.tb_ndmreset_request.value = mask
            await self._await_pins(dut, irq=1, process=0, label=f"REQ{bit}")
            got_req = await self.csr_read(f"NDM_REQUEST_B{bit}", NDM_REQUEST, expected=mask)
            cocotb.log.info(
                "CHK-NDM-REQ-%d: pin=0x%x REQUEST=0x%x irq=1 process=0",
                bit,
                mask,
                got_req,
            )

            await self.csr_write(f"NDM_PROCESS_SET_B{bit}", NDM_PROCESS, mask)
            await self._await_pins(dut, irq=1, process=mask, label=f"PROC{bit}")
            got_proc = await self.csr_read(f"NDM_PROCESS_B{bit}", NDM_PROCESS, expected=mask)
            cocotb.log.info(
                "CHK-NDM-PROC-%d: PROCESS=0x%x process_o=0x%x",
                bit,
                got_proc,
                mask,
            )

            dut.tb_ndmreset_request.value = 0
            await self._await_pins(dut, irq=0, process=mask, label=f"DROP{bit}")
            got_req = await self.csr_read(f"NDM_REQUEST_DROP_B{bit}", NDM_REQUEST, expected=0)
            got_proc = await self.csr_read(f"NDM_PROCESS_HOLD_B{bit}", NDM_PROCESS, expected=mask)
            cocotb.log.info(
                "CHK-NDM-DROP-%d: REQUEST=0x%x PROCESS held 0x%x irq=0",
                bit,
                got_req,
                got_proc,
            )

            await self.csr_write(f"NDM_PROCESS_CLR_B{bit}", NDM_PROCESS, 0)
            await self._await_pins(dut, irq=0, process=0, label=f"CLR{bit}")
            got_proc = await self.csr_read(f"NDM_PROCESS_CLR_B{bit}", NDM_PROCESS, expected=0)
            cocotb.log.info("CHK-NDM-CLR-%d: PROCESS=0x%x process_o=0", bit, got_proc)

        self.bits_ok = True
        cocotb.log.info("CHK-NDM-BASIC: count=%s bits=%s", self.count_ok, self.bits_ok)
