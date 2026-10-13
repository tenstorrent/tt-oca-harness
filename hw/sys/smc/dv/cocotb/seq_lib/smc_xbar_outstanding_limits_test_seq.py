# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outstanding access groups at, above and across subordinates of the two crossbars.

Contract SMC_XBAR_OUTSTANDING_LIMITS_TEST, anchor smc_xbar_outstanding_limits_test.
Allocated scenarios: AXI-LITE-XBAR-LIMIT.S1-S4, AXI-LOCAL-XBAR-LIMIT.S1-S4.
Spec sources: fabric.adoc Configuration Parameters, scratch.rdl SCRATCH, chip_config.rdl.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge, with_timeout
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_axi_port_watch import SmcAxiPortWatch
from .smc_csr_seq_utils import SmcCsrSeq

FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
GROUP_BOUND_NS = 50_000
WATCH_JOIN_BOUND_NS = 1_000

SCRATCH_WORDS = 8
SPM_WORDS = 16
SCRATCH_SEED = 0xC0DE_0500
WARM_SEED = 0xC0DE_0600
SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x8_0000
CHIP_CONFIG_NAMES = ("VERSION_LO", "VERSION_HI", "CHIP_ID", "LC_STATE")
CHIP_CONFIG_ADDRS = tuple(
    smc_addr(f"SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_{name}_BASE_ADDR") for name in CHIP_CONFIG_NAMES
)
MASK32 = 0xFFFF_FFFF

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")
_CHECKERS = (
    "CHK-XLIM-LITE-N4",
    "CHK-XLIM-LITE-OVER",
    "CHK-XLIM-LITE-MULTI",
    "CHK-XLIM-LITE-TWO-MGR",
    "CHK-XLIM-LOCAL-N8",
    "CHK-XLIM-LOCAL-OVER",
    "CHK-XLIM-LOCAL-MULTI",
    "CHK-XLIM-LOCAL-MIXED",
)
# Reads that carry an exact expected value, S2 through S9.
EXPECTED_READS = 110


def scratch_addr(i: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", i)


def warm_addr(i: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", i)


def spm_addr(i: int) -> int:
    return SPM_BASE + 8 * i


def spm_word(i: int) -> int:
    return 0xC1A0_0000_0000_0000 | (i << 16) | 0x7E57


def spm_rewrite_word(i: int) -> int:
    return 0xC1A1_0000_0000_0000 | (i << 16) | 0x7E57


class smc_xbar_outstanding_limits_test_seq(SmcCsrSeq):
    """Outstanding read groups of 4 to 24 over scratch, CHIP_CONFIG and SPM words."""

    def __init__(self, name: str = "smc_xbar_outstanding_limits_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"
        self.waits: list[str] = []
        self.chip_config: list[int] = []
        self.value_checks_start = 0
        self.value_checks: int | None = None
        self.stalls: dict[str, int] = {}
        self._watch: SmcAxiPortWatch | None = None
        self._watcher = None

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _read(label: str, addr: int, want: int, length: int) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.expected = want
        return item

    @staticmethod
    def _write(label: str, addr: int, data: int, length: int) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.wdata = data
        return item

    def _scratch_read(self, i: int) -> SmcSysAxiItem:
        return self._read(f"SCRATCH_COLD_{i}", scratch_addr(i), SCRATCH_SEED + i, 4)

    def _warm_read(self, i: int) -> SmcSysAxiItem:
        return self._read(f"SCRATCH_COLD_WARM_{i}", warm_addr(i), WARM_SEED + i, 4)

    def _spm_read(self, i: int) -> SmcSysAxiItem:
        return self._read(f"SPMW_{i}", spm_addr(i), spm_word(i), 8)

    def _stall_snapshot(self) -> dict[str, int]:
        assert self._watch is not None
        return dict(self._watch.stalls)

    def _stall_delta(self, before: dict[str, int]) -> str:
        now = self._stall_snapshot()
        return ",".join(f"{ch}={now[ch] - before[ch]}" for ch in ("ar", "r", "aw", "b"))

    async def _group(self, name: str, items: list[SmcSysAxiItem]) -> None:
        group = SmcSysAxiGroupItem(name, items)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(items)
        self.waits.append(f"{name} bound {AXI_TIMEOUT_NS} ns per member (driver), all answered")

    def _verify(self, name: str, items: list[SmcSysAxiItem]) -> None:
        for item in items:
            assert item.resp_code == 0, (
                f"{name} {item.get_name()} @ 0x{item.addr:08x}: resp {item.resp_code}, want OKAY"
            )
            if item.op == SmcSysAxiOp.READ:
                mask = (1 << (8 * item.length)) - 1
                assert item.rdata & mask == item.expected, (
                    f"{name} {item.get_name()} @ 0x{item.addr:08x}: read "
                    f"0x{item.rdata & mask:X}, want 0x{item.expected:X}"
                )

    async def _run_group(self, name: str, items: list[SmcSysAxiItem]) -> str:
        before = self._stall_snapshot()
        await self._group(name, items)
        self._verify(name, items)
        return self._stall_delta(before)

    async def _setup(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(cocotb.top, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        self.value_checks_start = self.env.scoreboard.sys_axi_value_checks_seen
        for i in range(SCRATCH_WORDS):
            await self.csr_write(f"SCRATCH_COLD_{i}_SEED", scratch_addr(i), SCRATCH_SEED + i)
        for i in range(SCRATCH_WORDS):
            await self.csr_write(f"SCRATCH_COLD_WARM_{i}_SEED", warm_addr(i), WARM_SEED + i)
        for i in range(SPM_WORDS):
            await self.csr_write(f"SPMW_{i}_SEED", spm_addr(i), spm_word(i), length=8)
        for name, addr in zip(CHIP_CONFIG_NAMES, CHIP_CONFIG_ADDRS):
            self.chip_config.append(await self.csr_read(f"CHIP_CONFIG_{name}", addr) & MASK32)
        self._watch = SmcAxiPortWatch(cocotb.top, "s_axi")
        self._watcher = cocotb.start_soon(self._watch.run())

    async def body(self) -> None:
        await self._setup()
        self._mark_step("S1")
        await self._step_n4()
        await self._step_lite_over()
        await self._step_lite_multi()
        await self._step_two_managers()
        await self._step_n8()
        await self._step_local_over()
        await self._step_local_multi()
        await self._step_mixed()
        await self._step_teardown()

    async def _step_n4(self) -> None:
        stall = await self._run_group("lite_n4", [self._scratch_read(i) for i in range(4)])
        self._mark_step("S2")
        self._log_chk(
            "CHK-XLIM-LITE-N4",
            f"4 outstanding SEP_IN reads of SCRATCH_COLD(0..3) completed OKAY within "
            f"{AXI_TIMEOUT_NS} ns, each 0x{SCRATCH_SEED:X}+i; stall cycles {stall}",
        )

    async def _step_lite_over(self) -> None:
        stall5 = await self._run_group("lite_n5", [self._scratch_read(i) for i in range(5)])
        stall8 = await self._run_group("lite_n8", [self._scratch_read(i) for i in range(8)])
        self._mark_step("S3")
        self._log_chk(
            "CHK-XLIM-LITE-OVER",
            f"5-read and 8-read SCRATCH_COLD groups completed OKAY, each read its own word; "
            f"limit 4 not asserted, stall cycles 5-group {stall5}, 8-group {stall8} "
            f"(observed, SF-015)",
        )

    async def _step_lite_multi(self) -> None:
        items = []
        for k in range(4):
            items.append(self._scratch_read(k))
            items.append(self._warm_read(k))
            items.append(
                self._read(
                    f"CHIP_CONFIG_{CHIP_CONFIG_NAMES[k]}",
                    CHIP_CONFIG_ADDRS[k],
                    self.chip_config[k],
                    4,
                )
            )
        stall = await self._run_group("lite_multi", items)
        self._mark_step("S4")
        words = ",".join(f"0x{w:08X}" for w in self.chip_config)
        self._log_chk(
            "CHK-XLIM-LITE-MULTI",
            f"12 interleaved reads over SCRATCH_COLD(0..3), SCRATCH_COLD_WARM(0..3) and "
            f"CHIP_CONFIG completed OKAY; scratch 0x{SCRATCH_SEED:X}+i, warm 0x{WARM_SEED:X}+i, "
            f"CHIP_CONFIG equal to the S1 values {words}; stall cycles {stall}",
        )

    async def _step_two_managers(self) -> None:
        sep_items = [self._scratch_read(i) for i in range(4)]
        jtag_items = [self._warm_read(i) for i in range(4)]
        before = self._stall_snapshot()
        await RisingEdge(cocotb.top.clk_smc_i)
        sep_task = cocotb.start_soon(
            _OneShot(SmcSysAxiGroupItem("two_mgr_sep", sep_items), "two_mgr_sep_os").start(
                self.env.sys_axi_agent.sequencer
            )
        )
        jtag_task = cocotb.start_soon(
            _OneShot(SmcSysAxiGroupItem("two_mgr_jtag", jtag_items), "two_mgr_jtag_os").start(
                self.env.jtag_axi_agent.sequencer
            )
        )
        for name, task, items in (("sep", sep_task, sep_items), ("jtag", jtag_task, jtag_items)):
            await with_timeout(task, GROUP_BOUND_NS, "ns")
            self.accesses += len(items)
            self.waits.append(f"two_mgr_{name}_join bound {GROUP_BOUND_NS} ns, last all answered")
            self._verify(f"two_mgr_{name}", items)
        stall = self._stall_delta(before)
        self._mark_step("S5")
        self._log_chk(
            "CHK-XLIM-LITE-TWO-MGR",
            f"SEP_IN group of 4 SCRATCH_COLD reads and JTAG group of 4 SCRATCH_COLD_WARM reads "
            f"started in one clk_smc_i cycle both completed OKAY within {GROUP_BOUND_NS} ns, "
            f"each read 0x{SCRATCH_SEED:X}+i or 0x{WARM_SEED:X}+i; SEP_IN stall cycles {stall}",
        )

    async def _step_n8(self) -> None:
        stall = await self._run_group("local_n8", [self._spm_read(i) for i in range(8)])
        self._mark_step("S6")
        self._log_chk(
            "CHK-XLIM-LOCAL-N8",
            f"8 outstanding SEP_IN reads of SPMW(0..7) completed OKAY within "
            f"{AXI_TIMEOUT_NS} ns, each SPMW(i); stall cycles {stall}",
        )

    async def _step_local_over(self) -> None:
        stall9 = await self._run_group("local_n9", [self._spm_read(i) for i in range(9)])
        stall16 = await self._run_group("local_n16", [self._spm_read(i) for i in range(16)])
        self._mark_step("S7")
        self._log_chk(
            "CHK-XLIM-LOCAL-OVER",
            f"9-read and 16-read SPM groups completed OKAY, each read SPMW(i); limit 8 not "
            f"asserted, stall cycles 9-group {stall9}, 16-group {stall16} (observed, SF-015)",
        )

    async def _step_local_multi(self) -> None:
        items = []
        for k in range(8):
            items.append(self._spm_read(k))
            items.append(self._scratch_read(k))
            items.append(self._warm_read(k))
        stall = await self._run_group("local_multi", items)
        self._mark_step("S8")
        self._log_chk(
            "CHK-XLIM-LOCAL-MULTI",
            f"24 interleaved reads over SPMW(0..7), SCRATCH_COLD(0..7) and SCRATCH_COLD_WARM(0..7) "
            f"completed OKAY, each read the word of its own address; stall cycles {stall}",
        )

    async def _step_mixed(self) -> None:
        items = []
        for i in range(8):
            items.append(self._spm_read(i))
            items.append(
                self._write(f"SPMW_{8 + i}_REWRITE", spm_addr(8 + i), spm_rewrite_word(8 + i), 8)
            )
        stall = await self._run_group("local_mixed", items)
        for i in range(8):
            await self.csr_read(
                f"SPMW_{8 + i}_RB", spm_addr(8 + i), expected=spm_rewrite_word(8 + i), length=8
            )
        self._mark_step("S9")
        self._log_chk(
            "CHK-XLIM-LOCAL-MIXED",
            f"16-member group of 8 SPMW(0..7) reads and 8 SPMW(8..15) writes completed OKAY; "
            f"reads returned SPMW(i), the 8 words read back singly equal "
            f"0xC1A1000000000000|i<<16|0x7E57; stall cycles {stall}",
        )

    async def _step_teardown(self) -> None:
        for i in range(SCRATCH_WORDS):
            await self.csr_write(f"SCRATCH_COLD_{i}_RESTORE", scratch_addr(i), 0)
        for i in range(SCRATCH_WORDS):
            await self.csr_write(f"SCRATCH_COLD_WARM_{i}_RESTORE", warm_addr(i), 0)
        assert self._watch is not None
        self._watch.stop = True
        await RisingEdge(cocotb.top.clk_smc_i)
        await with_timeout(self._watcher, WATCH_JOIN_BOUND_NS, "ns")
        self.waits.append(f"stall_watch_join bound {WATCH_JOIN_BOUND_NS} ns, last joined")
        self.stalls = dict(self._watch.stalls)
        self.value_checks = self.env.scoreboard.sys_axi_value_checks_seen - self.value_checks_start
        self._mark_step("S10")
        cocotb.log.info(
            "SEP_IN stall cycles over the run aw=%d ar=%d b=%d r=%d (printed, not asserted)",
            self.stalls["aw"],
            self.stalls["ar"],
            self.stalls["b"],
            self.stalls["r"],
        )

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, "
            "last observed %s; %d AXI accesses each bounded by the driver timeout %d ns "
            "(allow_timeout False), all answered; own waits: %s",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.accesses,
            AXI_TIMEOUT_NS,
            "; ".join(self.waits),
        )

    def nonvac_fence(self, floor: int) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), step in zip(self._chk_marks, _STEPS[1:]):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self.accesses >= floor, f"{self.accesses} accesses, floor {floor}"
        assert self.value_checks is not None and self.value_checks >= EXPECTED_READS, (
            f"scoreboard booked {self.value_checks} exact-value compares, "
            f"want at least {EXPECTED_READS}"
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5<S6<S7<S8<S9<S10; checker lines %s; "
            "accesses %d >= floor %d; scoreboard exact-value compares %d >= %d; stamps %s",
            ",".join(chk_ids),
            self.accesses,
            floor,
            self.value_checks,
            EXPECTED_READS,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
