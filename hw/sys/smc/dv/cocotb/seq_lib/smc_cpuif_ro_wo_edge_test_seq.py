# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Generated cpuif edges over SEP_IN: partial strobe, write-only, unreadable, past extent.

Spec sources: smc.rdl chip_config VERSION_LO sw=r, scratch.rdl SCRATCH[7] sw=rw.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_field_catalog import misc_wrap_reset
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import rdl_contract

FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
AXI_RESP_OKAY = 0
CONTROL_VALUE = 0xC0DE_0007
WRITE_ALL_ONES = 0xFFFF_FFFF
PARTIAL_STROBES = (0x3, 0xC, 0x1)
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

VERSION_LO_RESET = misc_wrap_reset("CHIP_CONFIG__VERSION_LO__VERSION_LO_reset")
VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")
SCRATCH_COLD_7 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 7)
PAST_EXTENT = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR") + smc_addr(
    "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SIZE"
)
INTR_TEST = rdl_contract("smc_uart_wrap/uart_log_engine_wrap/log_engine/INTR_TEST")
AVS_INTERRUPT_CLEAR = rdl_contract("smc_avsbus_controller/AVS_INTERRUPT_CLEAR")

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
# (checker id, last step it depends on), in declaration order.
_CHECKERS = (
    ("CHK-EDGE-RO-PARTIAL", "S2"),
    ("CHK-EDGE-WO-WRITE-READ-OBS", "S3"),
    ("CHK-EDGE-UNREADABLE-OBS", "S4"),
    ("CHK-EDGE-PAST-EXTENT-OBS", "S6"),
    ("CHK-EDGE-RECOVERY", "S6"),
)


def _name(resp: int | None) -> str:
    return _RESP_NAMES.get(resp, str(resp))


class smc_cpuif_ro_wo_edge_test_seq(SmcCsrSeq):
    """Drive the five cpuif edge accesses and read a control register after each."""

    def __init__(self, name: str = "smc_cpuif_ro_wo_edge_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"
        self.control_reads: list[tuple[str, int, int]] = []

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _read(self, label: str, addr: int, length: int = 4) -> tuple[int, int]:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label} @ 0x{addr:08x}: no rresp recorded"
        assert item.rdata is not None, f"{label} @ 0x{addr:08x}: no rdata recorded"
        return item.resp_code, item.rdata

    async def _write(
        self, label: str, addr: int, data: int, length: int = 4, wstrb: int | None = None
    ) -> int:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.wdata = data
        if wstrb is not None:
            item.wstrb = wstrb
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label} @ 0x{addr:08x}: no bresp recorded"
        return item.resp_code

    async def _control(self, after: str) -> None:
        resp, data = await self._read(f"CONTROL_AFTER_{after}", SCRATCH_COLD_7)
        assert resp == AXI_RESP_OKAY, (
            f"control SCRATCH_COLD(7) after {after}: rresp {_name(resp)}, want OKAY"
        )
        assert data & 0xFFFF_FFFF == CONTROL_VALUE, (
            f"control SCRATCH_COLD(7) after {after}: read 0x{data:x}, want 0x{CONTROL_VALUE:x}"
        )
        self.control_reads.append((after, resp, data & 0xFFFF_FFFF))

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)

        resp, v0 = await self._read("VERSION_LO_V0", VERSION_LO)
        assert resp == AXI_RESP_OKAY, f"VERSION_LO baseline rresp {_name(resp)}, want OKAY"
        assert v0 == VERSION_LO_RESET, f"VERSION_LO read 0x{v0:x}, reset 0x{VERSION_LO_RESET:x}"
        resp = await self._write("SCRATCH_COLD7_SETUP", SCRATCH_COLD_7, CONTROL_VALUE)
        assert resp == AXI_RESP_OKAY, f"SCRATCH_COLD(7) setup bresp {_name(resp)}, want OKAY"
        self._mark_step("S1")

        partial = []
        for strb in PARTIAL_STROBES:
            bresp = await self._write(
                f"VERSION_LO_WSTRB{strb:X}", VERSION_LO, WRITE_ALL_ONES, wstrb=strb
            )
            rresp, got = await self._read(f"VERSION_LO_AFTER_WSTRB{strb:X}", VERSION_LO)
            assert rresp == AXI_RESP_OKAY, (
                f"VERSION_LO read after wstrb 0x{strb:x}: rresp {_name(rresp)}, want OKAY"
            )
            assert got == v0, (
                f"VERSION_LO read 0x{got:x} after a write with wstrb 0x{strb:x}, baseline 0x{v0:x}"
            )
            partial.append(f"wstrb=0x{strb:X} bresp={_name(bresp)} readback=0x{got:08X}")
        self._mark_step("S2")
        self._log_chk(
            "CHK-EDGE-RO-PARTIAL",
            f"VERSION_LO @ 0x{VERSION_LO:08X} baseline V0=0x{v0:08X} unchanged after "
            f"{'; '.join(partial)} (BRESP printed not asserted, not specified, measured)",
        )

        wo_addr = INTR_TEST.addr
        wo_len = INTR_TEST.width_bytes
        wo_bresp = await self._write("LOG_ENGINE_INTR_TEST_WR", wo_addr, 0, length=wo_len)
        wo_resp, wo_data = await self._read("LOG_ENGINE_INTR_TEST_RD", wo_addr, length=wo_len)
        await self._control("INTR_TEST_READ")
        self._mark_step("S3")
        self._log_chk(
            "CHK-EDGE-WO-WRITE-READ-OBS",
            f"log_engine INTR_TEST @ 0x{wo_addr:08X}: write of 0 bresp={_name(wo_bresp)}, "
            f"read rresp={_name(wo_resp)} rdata=0x{wo_data:X}, both completed within the "
            f"guard (not specified, measured)",
        )

        un_addr = AVS_INTERRUPT_CLEAR.addr
        un_resp, un_data = await self._read(
            "AVS_INTERRUPT_CLEAR_RD", un_addr, length=AVS_INTERRUPT_CLEAR.width_bytes
        )
        await self._control("AVS_INTERRUPT_CLEAR_READ")
        self._mark_step("S4")
        self._log_chk(
            "CHK-EDGE-UNREADABLE-OBS",
            f"AVS_INTERRUPT_CLEAR @ 0x{un_addr:08X}: read "
            f"rresp={_name(un_resp)} rdata=0x{un_data:X}, completed within the guard "
            f"(not specified, measured)",
        )

        self.env.axi_monitor.expected_decerr_addrs.add(PAST_EXTENT)
        pe_resp, pe_data = await self._read("PAST_EXTENT_RD", PAST_EXTENT)
        await self._control("PAST_EXTENT_READ")
        self._mark_step("S5")
        pe_bresp = await self._write("PAST_EXTENT_WR", PAST_EXTENT, 0)
        await self._control("PAST_EXTENT_WRITE")
        resp = await self._write("SCRATCH_COLD7_TEARDOWN", SCRATCH_COLD_7, 0)
        assert resp == AXI_RESP_OKAY, f"SCRATCH_COLD(7) teardown bresp {_name(resp)}, want OKAY"
        self._mark_step("S6")
        self._log_chk(
            "CHK-EDGE-PAST-EXTENT-OBS",
            f"past SCRATCH_COLD @ 0x{PAST_EXTENT:08X}: read rresp={_name(pe_resp)} "
            f"rdata=0x{pe_data:X}, write bresp={_name(pe_bresp)}, both completed within the "
            f"guard (not specified, measured)",
        )
        assert len(self.control_reads) == 4, f"{len(self.control_reads)} control reads, want 4"
        self._log_chk(
            "CHK-EDGE-RECOVERY",
            "SCRATCH_COLD(7) read 0x%08X with OKAY after each of %s"
            % (CONTROL_VALUE, ",".join(a for a, _, _ in self.control_reads)),
        )

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, last "
            "observed %s; %d AXI accesses each bounded by the driver timeout %d ns "
            "(allow_timeout False), all answered; no other wait",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.accesses,
            AXI_TIMEOUT_NS,
        )

    def nonvac_fence(self, floor: int) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == tuple(c for c, _ in _CHECKERS), f"checker lines {chk_ids}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self.accesses >= floor, f"{self.accesses} accesses, floor {floor}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5<S6; checker lines %s; control reads %d; "
            "accesses %d >= floor %d; stamps %s",
            ",".join(chk_ids),
            len(self.control_reads),
            self.accesses,
            floor,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
