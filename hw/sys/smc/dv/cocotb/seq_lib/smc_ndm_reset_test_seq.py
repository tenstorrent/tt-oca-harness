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
# NDMRESET_CLUSTER_COUNT carries no golden here: `ndm_reset.rdl:33-39` declares
# it `sw = r; hw = w` with reset 0x0, i.e. the value is driven by the
# integration's cluster count and no SPEC table in this repository pins it to a
# number ([INDEPENDENT-EXPECTED-MODEL]).
#
# What the RDL DOES state is the register's contract, and that is what is
# checked instead:
#   * the field is `ndmreset_cluster_count[7:0]`, and REQUEST/PROCESS
#     "Supports up to 32 CPU Clusters" -- so 1 <= count <= 32;
#   * "Number of NDM Clusters supported. Can be read to mask the
#     ndmreset_request register" -- so driving every request line high must
#     make NDMRESET_REQUEST read exactly the count's mask, no more and no less.
# The scope of the second property is bounded by the bench: the TB can only
# drive the request lines it declares, so the leg proves that every request
# line the bench can drive reaches NDMRESET_REQUEST and that the bits above the
# reported count read zero. It detects a count that over-reports the request
# bits the DUT actually implements; it cannot detect a DUT that implements more
# request bits than the bench drives.
_NDM_CLUSTER_COUNT_MASK = 0xFF  # ndm_reset.rdl ndmreset_cluster_count[7:0]
_NDM_MAX_CLUSTERS = 32  # ndm_reset.rdl "Supports up to 32 CPU Clusters"
_PIN_BOUND = 64


class smc_ndm_reset_test_seq(SmcCsrSeq):
    """Pin→CSR→IRQ→PROCESS handshake, one bit at a time."""

    def __init__(self, name: str = "smc_ndm_reset_test_seq") -> None:
        super().__init__(name)
        # Measured values, published for the testcase module's zero-activity
        # guard and for the evidence tokens.
        self.cluster_count: int | None = None
        self.all_request_readback: int | None = None
        self.bits_swept: list[int] = []

    async def _await_pins(self, dut, irq: int, process: int, label: str) -> dict[str, int]:
        """Return the SAMPLE that matched so tokens print measured pin values."""
        last = {}
        for _ in range(_PIN_BOUND):
            await RisingEdge(dut.clk_smc_i)
            last = {
                "irq": int(dut.tb_ndmreset_irq.value),
                "process": int(dut.tb_ndmreset_process.value),
            }
            if last["irq"] == irq and last["process"] == process:
                return last
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
        count = nclu & _NDM_CLUSTER_COUNT_MASK
        assert 1 <= count <= _NDM_MAX_CLUSTERS, (
            f"NDMRESET_CLUSTER_COUNT=0x{nclu:x} -> {count} clusters, outside the "
            f"1..{_NDM_MAX_CLUSTERS} range ndm_reset.rdl declares for the "
            f"REQUEST/PROCESS registers"
        )
        port_width = len(dut.tb_ndmreset_request.value)
        # `port_width` is the width of the TB observation port
        # `tb_ndmreset_request`, a hard-coded `[3:0]` in tb_top.sv that mirrors
        # `smc_config_pkg.sv`, not the DUT's parameterised `smc.sv` port. The
        # compare is a TB/DUT integration check -- the bench cannot observe more
        # lines than it declares -- and, with no spec value for the count in
        # the tree (module comment above), it does not claim the count is
        # correct; the all-lines leg below proves the count agrees with the
        # request bits that reach the register.
        assert count == port_width, (
            f"NDMRESET_CLUSTER_COUNT reports {count} cluster(s) but the TB "
            f"observation port tb_ndmreset_request is {port_width} bit(s) wide "
            f"(tb_top.sv:149, hard-coded [3:0]) -- the bench cannot observe the "
            f"lines the DUT says exist"
        )
        self.cluster_count = count

        req0 = await self.csr_read("NDM_REQUEST_IDLE", NDM_REQUEST, expected=0)
        proc0 = await self.csr_read("NDM_PROCESS_IDLE", NDM_PROCESS, expected=0)
        idle_pins = await self._await_pins(dut, irq=0, process=0, label="IDLE")
        cocotb.log.info(
            "CHK-NDM-IDLE: REQUEST=0x%x PROCESS=0x%x process_o=0x%x irq=%d",
            req0,
            proc0,
            idle_pins["process"],
            idle_pins["irq"],
        )

        # The RDL's stated use of CLUSTER_COUNT -- "can be read to mask the
        # ndmreset_request register" -- made falsifiable: with every request
        # line driven high, NDMRESET_REQUEST must read exactly that mask.
        #
        # The STIMULUS is all-ones across the whole TB port, independent of
        # `count`. Deriving the drive value from `count` as well would make the
        # leg blind in one direction: a CSR that under-reports would drive only
        # the bits it claims, read them back and pass. Driving every line the
        # bench has makes the readback report how many request bits reach the
        # register, so `expected=all_mask` separates a count that over-reports
        # (extra bits read 0) from one that matches. Both sides of the compare
        # are DUT-sourced -- the CSR count against the CSR request reflection --
        # rather than a DUT value against a TB literal
        # ([INDEPENDENT-EXPECTED-MODEL]).
        all_mask = (1 << count) - 1
        drive_all = (1 << len(dut.tb_ndmreset_request.value)) - 1
        dut.tb_ndmreset_request.value = drive_all
        await self._await_pins(dut, irq=1, process=0, label="COUNT_ALL")
        self.all_request_readback = await self.csr_read(
            "NDM_REQUEST_ALL", NDM_REQUEST, expected=all_mask
        )
        dut.tb_ndmreset_request.value = 0
        await self._await_pins(dut, irq=0, process=0, label="COUNT_ALL_DROP")
        await self.csr_read("NDM_REQUEST_ALL_DROP", NDM_REQUEST, expected=0)
        cocotb.log.info(
            "CHK-NDM-COUNT: NDMRESET_CLUSTER_COUNT=%d (ndm_reset.rdl field "
            "[7:0]; the RDL reset is 0x0 and hw-driven, so the RDL supplies NO "
            "expected count -- this testcase does not claim the count is "
            "correct). TB observation port tb_ndmreset_request is %d bits "
            "(tb_top.sv:149 hard-coded [3:0], an RTL mirror, NOT the DUT's "
            "parameterised port). With ALL %d bench-driven lines high, "
            "NDMRESET_REQUEST read exactly 0x%x == (1<<%d)-1, so every request "
            "line the bench drives reaches the register and bits above the "
            "reported count read zero. Request bits beyond the bench's port "
            "width are outside this leg's reach",
            count,
            port_width,
            drive_all.bit_count(),
            self.all_request_readback,
            count,
        )

        for bit in range(count):
            mask = 1 << bit
            dut.tb_ndmreset_request.value = mask
            req_pins = await self._await_pins(dut, irq=1, process=0, label=f"REQ{bit}")
            got_req = await self.csr_read(f"NDM_REQUEST_B{bit}", NDM_REQUEST, expected=mask)
            cocotb.log.info(
                "CHK-NDM-REQ-%d: pin=0x%x REQUEST=0x%x irq=%d process_o=0x%x",
                bit,
                mask,
                got_req,
                req_pins["irq"],
                req_pins["process"],
            )

            await self.csr_write(f"NDM_PROCESS_SET_B{bit}", NDM_PROCESS, mask)
            proc_pins = await self._await_pins(dut, irq=1, process=mask, label=f"PROC{bit}")
            got_proc = await self.csr_read(f"NDM_PROCESS_B{bit}", NDM_PROCESS, expected=mask)
            cocotb.log.info(
                "CHK-NDM-PROC-%d: PROCESS=0x%x process_o=0x%x (measured pin sample, irq=%d)",
                bit,
                got_proc,
                proc_pins["process"],
                proc_pins["irq"],
            )

            dut.tb_ndmreset_request.value = 0
            drop_pins = await self._await_pins(dut, irq=0, process=mask, label=f"DROP{bit}")
            got_req = await self.csr_read(f"NDM_REQUEST_DROP_B{bit}", NDM_REQUEST, expected=0)
            got_proc = await self.csr_read(f"NDM_PROCESS_HOLD_B{bit}", NDM_PROCESS, expected=mask)
            cocotb.log.info(
                "CHK-NDM-DROP-%d: REQUEST=0x%x PROCESS held 0x%x process_o=0x%x irq=%d",
                bit,
                got_req,
                got_proc,
                drop_pins["process"],
                drop_pins["irq"],
            )

            await self.csr_write(f"NDM_PROCESS_CLR_B{bit}", NDM_PROCESS, 0)
            clr_pins = await self._await_pins(dut, irq=0, process=0, label=f"CLR{bit}")
            got_proc = await self.csr_read(f"NDM_PROCESS_CLR_B{bit}", NDM_PROCESS, expected=0)
            cocotb.log.info(
                "CHK-NDM-CLR-%d: PROCESS=0x%x process_o=0x%x irq=%d",
                bit,
                got_proc,
                clr_pins["process"],
                clr_pins["irq"],
            )
            self.bits_swept.append(bit)
