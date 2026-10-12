# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
Contract SMC_CLOCK_RATIO_006 ANCHOR: smc_clk_ratio_base_config_test
Scenarios: RATIO-BASECFG-XFER.S1, RATIO-BASECFG-XFER.S2, RATIO-BASECFG-XFER.S3
Sources: hw/sys/smc/regs/blocks/smc_base_config/smc_base_config.rdl, hw/sys/smc/doc/memmap.adoc
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr
from .smc_base_test_seq import wait_fuse_sense_done
from .smc_cg_obs_utils import emit_chk, log_step
from .smc_csr_seq_utils import SmcCsrSeq

GLOBAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
LOCAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
THR_SYS = smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR")
THR_SEP = smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD_BASE_ADDR")
THR_ACCEL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD_BASE_ADDR")

GLOBAL_BASE_RESET = 0x4000_0000
LOCAL_BASE_RESET = 0xC000_0000
REGION_SIZE_RESET = 0x0100_0000
THRESHOLD_RESET = 0x1000
THRESHOLD_PATTERN = 0x5A5A5
LOCAL_BASE_WRITE_DATA = 0xB000_0000

FUSE_SENSE_MAX_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
RESP_OKAY = 0

FENCE_ORDER = (
    "BRINGUP_DONE",
    "BASECFG_RESET_READS",
    "THRESHOLD_WRITE_READ",
    "LOCAL_BASE_BEFORE",
    "LOCAL_BASE_WRITE",
    "LOCAL_BASE_AFTER",
)
CHK_ORDER = (
    ("CHK-BASECFG-RESET-READ", "BASECFG_RESET_READS"),
    ("CHK-BASECFG-THRESHOLD-WRITE", "THRESHOLD_WRITE_READ"),
    ("CHK-BASECFG-RO-IGNORED", "LOCAL_BASE_AFTER"),
)


class smc_clk_ratio_base_config_test_seq(SmcCsrSeq):
    """smc_base_config reset values, threshold round trip and the LOCAL_BASE write."""

    def __init__(self, name: str = "smc_clk_ratio_base_config_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: dict[str, str] = {}
        self.fence: list[tuple[str, int]] = []
        self.chk_order: list[tuple[str, int]] = []
        self.bounded_waits: list[tuple[str, str, str]] = []
        self.last_access = "none"

    def _stamp(self, step: str) -> None:
        self.fence.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, line: str) -> None:
        emit_chk(self.chk_seen, chk_id, line)
        self.chk_order.append((chk_id, len(self.fence)))

    async def _access(
        self,
        name: str,
        addr: int,
        op: SmcSysAxiOp,
        length: int,
        data: int | None = None,
        tolerate_error: bool = False,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{'rd' if op == SmcSysAxiOp.READ else 'wr'}_{name}")
        item.op = op
        item.addr = addr
        item.length = length
        if data is not None:
            item.wdata = data
        item.allow_error = tolerate_error
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.last_access = f"{name}@0x{addr:08x} resp={item.resp_code}"
        return item

    async def _read(self, name: str, addr: int, length: int) -> tuple[int, int]:
        item = await self._access(name, addr, SmcSysAxiOp.READ, length)
        assert item.resp_code == RESP_OKAY, f"{self.last_access}: read not OKAY"
        assert item.rdata is not None, f"{self.last_access}: read data missing"
        return int(item.rdata), item.resp_code

    async def _write(self, name: str, addr: int, data: int, length: int) -> int:
        item = await self._access(name, addr, SmcSysAxiOp.WRITE, length, data)
        assert item.resp_code == RESP_OKAY, f"{self.last_access}: write not OKAY"
        return item.resp_code

    async def body(self) -> None:
        log_step("S1", "bring-up at ref / smc / periph 10 / 1.25 / 5 ns; fuse sense done")
        await wait_fuse_sense_done(FUSE_SENSE_MAX_SMC_CYCLES)
        self.bounded_waits.append(
            ("fuse_sense", f"{FUSE_SENSE_MAX_SMC_CYCLES}smc_cycles", "tb_fuse_sense_done=1")
        )
        self._stamp("BRINGUP_DONE")

        log_step("S2", "reset reads of the base registers and the three thresholds")
        reads = (
            ("GLOBAL_BASE", GLOBAL_BASE, 8, GLOBAL_BASE_RESET),
            ("LOCAL_BASE", LOCAL_BASE, 8, LOCAL_BASE_RESET),
            ("REGION_SIZE", REGION_SIZE, 8, REGION_SIZE_RESET),
            ("HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD", THR_SYS, 4, THRESHOLD_RESET),
            ("HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD", THR_SEP, 4, THRESHOLD_RESET),
            ("HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD", THR_ACCEL, 4, THRESHOLD_RESET),
        )
        assert len({addr for _, addr, _, _ in reads}) == len(reads), "aliased read addresses"
        parts = []
        for name, addr, length, expected in reads:
            got, resp = await self._read(name, addr, length)
            assert got == expected, f"{name} @ 0x{addr:08x}: expected 0x{expected:x}, got 0x{got:x}"
            parts.append(f"{name}@0x{addr:08x}=0x{got:x}/resp{resp}")
        self._stamp("BASECFG_RESET_READS")
        self._chk("CHK-BASECFG-RESET-READ", "CHK-BASECFG-RESET-READ: " + " ".join(parts))

        log_step("S3", "threshold write 0x5A5A5, read, restore 0x1000, read")
        wresp = await self._write("THR_ACCEL_PATTERN", THR_ACCEL, THRESHOLD_PATTERN, 4)
        got, rresp = await self._read("THR_ACCEL_PATTERN", THR_ACCEL, 4)
        assert got == THRESHOLD_PATTERN, (
            f"threshold read 0x{got:x}, expected 0x{THRESHOLD_PATTERN:x}"
        )
        assert got >> 20 == 0, f"threshold bits above 19 set: 0x{got:x}"
        wresp2 = await self._write("THR_ACCEL_RESTORE", THR_ACCEL, THRESHOLD_RESET, 4)
        got2, rresp2 = await self._read("THR_ACCEL_RESTORE", THR_ACCEL, 4)
        assert got2 == THRESHOLD_RESET, f"threshold restore read 0x{got2:x}"
        self._stamp("THRESHOLD_WRITE_READ")
        self._chk(
            "CHK-BASECFG-THRESHOLD-WRITE",
            f"CHK-BASECFG-THRESHOLD-WRITE: wrote 0x{THRESHOLD_PATTERN:x} (resp{wresp}) read "
            f"0x{got:x} (resp{rresp}); restored 0x{THRESHOLD_RESET:x} (resp{wresp2}) read "
            f"0x{got2:x} (resp{rresp2})",
        )

        log_step("S4", "LOCAL_BASE read, write 0xB0000000 tolerated, read again")
        before, bresp = await self._read("LOCAL_BASE_BEFORE", LOCAL_BASE, 8)
        assert before == LOCAL_BASE_RESET, f"LOCAL_BASE before 0x{before:x}"
        self._stamp("LOCAL_BASE_BEFORE")
        item = await self._access(
            "LOCAL_BASE_WRITE",
            LOCAL_BASE,
            SmcSysAxiOp.WRITE,
            8,
            LOCAL_BASE_WRITE_DATA,
            tolerate_error=True,
        )
        write_resp = item.resp_code
        assert write_resp is not None, "LOCAL_BASE write returned no response code"
        self._stamp("LOCAL_BASE_WRITE")
        after, aresp = await self._read("LOCAL_BASE_AFTER", LOCAL_BASE, 8)
        assert after == before, f"LOCAL_BASE changed: before 0x{before:x}, after 0x{after:x}"
        self._stamp("LOCAL_BASE_AFTER")
        self._chk(
            "CHK-BASECFG-RO-IGNORED",
            f"CHK-BASECFG-RO-IGNORED: LOCAL_BASE before 0x{before:x} (resp{bresp}); write "
            f"0x{LOCAL_BASE_WRITE_DATA:x} write_resp={write_resp} (printed, owner answers SF-005); "
            f"after 0x{after:x} (resp{aresp})",
        )

        self.bounded_waits.append(("sep_in_axi_access", f"{AXI_TIMEOUT_NS}ns", self.last_access))
        waits = " ".join(f"{n}={b} last={s}" for n, b, s in self.bounded_waits)
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"CHK-TIMEOUT-PATHS: {len(self.bounded_waits)} bounded waits: {waits}; "
            "expiry raises AssertionError",
        )
        self._fence_check()

    def _fence_check(self) -> None:
        order = [s for s, _ in self.fence]
        assert order == list(FENCE_ORDER), f"NONVAC fence order {order}"
        stamps = [t for _, t in self.fence]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        pos = {s: i + 1 for i, s in enumerate(FENCE_ORDER)}
        seen = [c for c, _ in self.chk_order if c != "CHK-TIMEOUT-PATHS"]
        assert seen == [c for c, _ in CHK_ORDER], f"checker lines out of order {seen}"
        for chk_id, step in CHK_ORDER:
            printed_after = dict(self.chk_order)[chk_id]
            assert printed_after >= pos[step], f"{chk_id} printed before step {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(order),
            ",".join(c for c, _ in self.chk_order),
            ",".join(str(t) for t in stamps),
        )
        self.chk_seen["CHK-NONVAC"] = "ordered"
