# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outstanding groups at the fabric limits and simultaneous reads from the three inbound ports.

Spec sources: fabric.adoc Fabric Transaction Limits and Fabric Topology, memmap.adoc Address Space.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge, with_timeout
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    CLOCK_GATE_CONTROL_RESET,
    REGION_SIZE_RESET,
    smc_addr,
    smc_indexed_addr,
)
from .smc_axi_port_watch import SmcAxiPortWatch
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT,
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
    GPIO_INTF_ACCESS_FILTER_REG_DEFAULT,
    SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT,
)

FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
GROUP_BOUND_NS = 50_000
WATCH_JOIN_BOUND_NS = 1_000

AXI_RESP_DECERR = 3
INBOUND_PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
REGION_SIZE_WORD = 0x0100_0000
SCRATCH_WORDS = 8
SPM_WORDS = 16
SCRATCH_SEED = 0xC0DE_0900
WARM_SEED = 0xC0DE_0A00
WRITE_PATTERN = 0xC0DE_0B11
SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x8_0000
REGION_SIZE_ADDR = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
CLOCK_GATE_ADDR = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
GPIO0_FILTER = smc_indexed_addr("SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", 0)
AVS_CFG_0 = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR")
OCTS_CTRL = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR")
UNMAPPED_ADDR = smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR") - 0x1000
OUTSIDE_ADDR = 0x8000_0000
SAME_ID = 5

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")
_FENCE = (
    "SETUP",
    "LIMIT_32",
    "ERRSLV_32",
    "LOCAL_8",
    "AXIL_4",
    "SAME_PORT",
    "CONCURRENT_DISTINCT",
    "CONCURRENT_SAME",
    "DECERR_BESIDE_VALID",
    "READ_WRITE",
)
_CHECKERS = (
    "CHK-LIMIT-FABRIC-32",
    "CHK-LIMIT-ERRSLV-32",
    "CHK-LIMIT-LOCAL-XBAR-8",
    "CHK-LIMIT-AXIL-XBAR-4",
    "CHK-SAME-PORT-OUTSTANDING",
    "CHK-CONCURRENT-DISTINCT-TARGETS",
    "CHK-CONCURRENT-SAME-TARGET",
    "CHK-CONCURRENT-DECERR-BESIDE-VALID",
    "CHK-CONCURRENT-READ-WRITE",
)
# Reads that carry an exact expected value, S2 through S10.
EXPECTED_READS = 115
PORTS = ("SEP", "SYS", "JTAG")


def scratch_addr(i: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", i)


def warm_addr(i: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", i)


def spm_addr(i: int) -> int:
    return SPM_BASE + 8 * i


def spm_word(i: int) -> int:
    return 0xC1B0_0000_0000_0000 | (i << 16) | 0x7E57


class smc_inbound_concurrency_limits_test_seq(SmcCsrSeq):
    """Outstanding groups on SEP_IN and simultaneous reads from SEP_IN, SYS_IN and JTAG."""

    def __init__(self, name: str = "smc_inbound_concurrency_limits_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"
        self.waits: list[str] = []
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
    def _read(
        label: str,
        addr: int,
        want: int | None,
        length: int = 4,
        axi_id: int | None = None,
        decerr: bool = False,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.axi_id = axi_id
        if decerr:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = AXI_RESP_DECERR
        else:
            item.expected = want
        return item

    @staticmethod
    def _write(label: str, addr: int, data: int, length: int = 4) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.wdata = data
        return item

    def _decerr_read(self, label: str, addr: int, axi_id: int | None = None) -> SmcSysAxiItem:
        self.env.axi_monitor.expected_decerr_addrs.add(addr)
        return self._read(label, addr, None, axi_id=axi_id, decerr=True)

    def _sequencer(self, port: str):
        return {
            "SEP": self.env.sys_axi_agent,
            "SYS": self.env.sys_in_axi_agent,
            "JTAG": self.env.jtag_axi_agent,
        }[port].sequencer

    def _stall_snapshot(self) -> dict[str, int]:
        assert self._watch is not None
        return dict(self._watch.stalls)

    def _stall_delta(self, before: dict[str, int]) -> str:
        now = self._stall_snapshot()
        return ",".join(f"{ch}={now[ch] - before[ch]}" for ch in ("ar", "r", "aw", "b"))

    @staticmethod
    def _verify(name: str, items: list[SmcSysAxiItem]) -> None:
        for item in items:
            where = f"{name} {item.get_name()} @ 0x{item.addr:08x}"
            if item.expect_error:
                assert item.resp_code == AXI_RESP_DECERR, (
                    f"{where}: resp {item.resp_code}, want DECERR"
                )
                continue
            assert item.resp_code == 0, f"{where}: resp {item.resp_code}, want OKAY"
            if item.op == SmcSysAxiOp.READ:
                mask = (1 << (8 * item.length)) - 1
                assert item.rdata & mask == item.expected, (
                    f"{where}: read 0x{item.rdata & mask:X}, want 0x{item.expected:X}"
                )

    async def _group(self, name: str, items: list[SmcSysAxiItem], port: str = "SEP") -> None:
        group = SmcSysAxiGroupItem(name, items)
        await _OneShot(group, f"{name}_os").start(self._sequencer(port))
        self.accesses += len(items)
        self.waits.append(
            f"{name} ({port}) bound {AXI_TIMEOUT_NS} ns per member (driver), all answered"
        )
        self._verify(name, items)

    async def _run_group(self, name: str, items: list[SmcSysAxiItem]) -> str:
        before = self._stall_snapshot()
        await self._group(name, items)
        return self._stall_delta(before)

    async def _parallel(self, name: str, jobs: dict[str, list[SmcSysAxiItem]]) -> None:
        """Start one group per port in the same clk_smc_i cycle and join every port."""
        await RisingEdge(cocotb.top.clk_smc_i)
        tasks = {
            port: cocotb.start_soon(
                _OneShot(SmcSysAxiGroupItem(f"{name}_{port}", items), f"{name}_{port}_os").start(
                    self._sequencer(port)
                )
            )
            for port, items in jobs.items()
        }
        for port, task in tasks.items():
            await with_timeout(task, GROUP_BOUND_NS, "ns")
            self.accesses += len(jobs[port])
            self._verify(f"{name}_{port}", jobs[port])
        self.waits.append(
            f"{name} join {'+'.join(jobs)} bound {GROUP_BOUND_NS} ns, last all answered"
        )

    async def _setup(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(cocotb.top, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        assert REGION_SIZE_RESET == REGION_SIZE_WORD, f"REGION_SIZE reset 0x{REGION_SIZE_RESET:X}"
        for i in range(SCRATCH_WORDS):
            await self.csr_write(f"SCRATCH_COLD_{i}_SEED", scratch_addr(i), SCRATCH_SEED + i)
        for i in range(SCRATCH_WORDS):
            await self.csr_write(f"WARM_{i}_SEED", warm_addr(i), WARM_SEED + i)
        for i in range(SPM_WORDS):
            await self.csr_write(f"SPMW_{i}_SEED", spm_addr(i), spm_word(i), length=8)
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, INBOUND_PASS_ALL_END, length=8)
        await self.csr_write(
            "INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_PASS_ALL_RB",
            INBOUND0_FILTER_CONFIG,
            expected=PASS_ALL_CONFIG,
            length=8,
        )
        self._watch = SmcAxiPortWatch(cocotb.top, "s_axi")
        self._watcher = cocotb.start_soon(self._watch.run())
        self.value_checks_start = self.env.scoreboard.sys_axi_value_checks_seen

    def _distinct_reads(self, count: int, axi_id: int | None) -> list[SmcSysAxiItem]:
        """Reads cycling through the 32 seeded registers (scratch, warm scratch, SPM words)."""
        table = [(f"SCRATCH_COLD_{i}", scratch_addr(i), SCRATCH_SEED + i, 4) for i in range(8)]
        table += [(f"WARM_{i}", warm_addr(i), WARM_SEED + i, 4) for i in range(8)]
        table += [(f"SPMW_{i}", spm_addr(i), spm_word(i), 8) for i in range(SPM_WORDS)]
        return [
            self._read(
                f"{table[k % 32][0]}_{k}",
                table[k % 32][1],
                table[k % 32][2],
                table[k % 32][3],
                axi_id,
            )
            for k in range(count)
        ]

    async def body(self) -> None:
        await self._setup()
        self._mark_step("S1")
        try:
            await self._step_fabric_32()
            await self._step_errslv_32()
            await self._step_local_8()
            await self._step_axil_4()
            await self._step_same_port()
            await self._step_distinct_targets()
            await self._step_same_target()
            await self._step_decerr_beside_valid()
            await self._step_read_write()
        finally:
            await self._teardown()

    async def _step_fabric_32(self) -> None:
        stall32 = await self._run_group("fabric_32", self._distinct_reads(32, None))
        stall33 = await self._run_group("fabric_33_one_id", self._distinct_reads(33, SAME_ID))
        self._mark_step("S2")
        self._log_chk(
            "CHK-LIMIT-FABRIC-32",
            f"32 outstanding SEP_IN reads of 32 distinct registers and 33 reads on axi_id "
            f"{SAME_ID} all completed OKAY within {AXI_TIMEOUT_NS} ns, each its own register "
            f"value; limit not asserted, stall cycles 32-group {stall32}, 33-group {stall33} "
            f"(observed)",
        )

    async def _step_errslv_32(self) -> None:
        stalls = []
        for count in (32, 33):
            items = [
                self._decerr_read(f"UNMAPPED_{count}_{i}", UNMAPPED_ADDR + 8 * i, axi_id=1 + i)
                for i in range(count)
            ]
            stalls.append(await self._run_group(f"errslv_{count}", items))
        self._mark_step("S3")
        self._log_chk(
            "CHK-LIMIT-ERRSLV-32",
            f"32 and 33 outstanding SEP_IN reads of the unmapped page 0x{UNMAPPED_ADDR:08X} on "
            f"distinct axi_id values all answered DECERR within {AXI_TIMEOUT_NS} ns; stall "
            f"cycles 32-group {stalls[0]}, 33-group {stalls[1]} (observed)",
        )

    async def _step_local_8(self) -> None:
        def reads(count: int) -> list[SmcSysAxiItem]:
            return [
                self._read(f"SCRATCH_COLD_0_{k}", scratch_addr(0), SCRATCH_SEED)
                for k in range(count)
            ]

        stall8 = await self._run_group("local_8", reads(8))
        stall9 = await self._run_group("local_9", reads(9))
        self._mark_step("S4")
        self._log_chk(
            "CHK-LIMIT-LOCAL-XBAR-8",
            f"8 and 9 outstanding SEP_IN reads of SCRATCH_COLD[0] all returned "
            f"0x{SCRATCH_SEED:X} within {AXI_TIMEOUT_NS} ns; stall cycles 8-group {stall8}, "
            f"9-group {stall9} (observed)",
        )

    async def _step_axil_4(self) -> None:
        table = (
            ("GPIO0_ACCESS_FILTER", GPIO0_FILTER, GPIO_INTF_ACCESS_FILTER_REG_DEFAULT),
            ("AVS_CFG_0", AVS_CFG_0, AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT),
            ("OCTS_CTRL", OCTS_CTRL, SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT),
            ("CLOCK_GATE_CONTROL", CLOCK_GATE_ADDR, CLOCK_GATE_CONTROL_RESET),
        )

        def reads(count: int) -> list[SmcSysAxiItem]:
            return [
                self._read(f"{table[k % 4][0]}_{k}", table[k % 4][1], table[k % 4][2])
                for k in range(count)
            ]

        stall4 = await self._run_group("axil_4", reads(4))
        stall5 = await self._run_group("axil_5", reads(5))
        self._mark_step("S5")
        words = ",".join(f"{name}=0x{want:X}" for name, _, want in table)
        self._log_chk(
            "CHK-LIMIT-AXIL-XBAR-4",
            f"4 and 5 outstanding SEP_IN reads of the four registers all returned their RDL "
            f"reset ({words}) within {AXI_TIMEOUT_NS} ns; stall cycles 4-group {stall4}, "
            f"5-group {stall5} (observed)",
        )

    async def _step_same_port(self) -> None:
        for port in ("SYS", "SEP"):
            for order in ("out_first", "in_first"):
                out = self._decerr_read(f"{port}_{order}_OUT", OUTSIDE_ADDR)
                inside = self._read(f"{port}_{order}_IN", REGION_SIZE_ADDR, REGION_SIZE_WORD)
                items = [out, inside] if order == "out_first" else [inside, out]
                await self._group(f"same_port_{port}_{order}", items, port)
        self._mark_step("S6")
        self._log_chk(
            "CHK-SAME-PORT-OUTSTANDING",
            f"on SYS_IN and on SEP_IN a REGION_SIZE read (OKAY 0x{REGION_SIZE_WORD:X}) and a "
            f"read of the outside-window address 0x{OUTSIDE_ADDR:08X} (DECERR) in the same "
            f"outstanding group were each answered by their own address, out-of-window first "
            f"and second",
        )

    def _target(self, name: str) -> SmcSysAxiItem:
        table = {
            "REGION_SIZE": (REGION_SIZE_ADDR, REGION_SIZE_WORD),
            "SCRATCH_COLD_0": (scratch_addr(0), SCRATCH_SEED),
            "CLOCK_GATE_CONTROL": (CLOCK_GATE_ADDR, CLOCK_GATE_CONTROL_RESET),
        }
        addr, want = table[name]
        return self._read(name, addr, want)

    async def _step_distinct_targets(self) -> None:
        base = {"SEP": "REGION_SIZE", "SYS": "SCRATCH_COLD_0", "JTAG": "CLOCK_GATE_CONTROL"}
        rotated = {"SEP": "CLOCK_GATE_CONTROL", "SYS": "REGION_SIZE", "JTAG": "SCRATCH_COLD_0"}
        combos = [("SEP", "SYS"), ("SEP", "JTAG"), ("SYS", "JTAG")]
        for pair in combos:
            await self._parallel(
                f"distinct_{'_'.join(pair)}", {p: [self._target(base[p])] for p in pair}
            )
        await self._parallel("distinct_all", {p: [self._target(rotated[p])] for p in PORTS})
        self._mark_step("S7")
        self._log_chk(
            "CHK-CONCURRENT-DISTINCT-TARGETS",
            "simultaneous reads from SEP_IN+SYS_IN, SEP_IN+JTAG, SYS_IN+JTAG (REGION_SIZE, "
            "SCRATCH_COLD[0], CLOCK_GATE_CONTROL by port) and from all three with the targets "
            "rotated each returned the value of its own target",
        )

    async def _step_same_target(self) -> None:
        await self._parallel("same_target", {p: [self._target("REGION_SIZE")] for p in PORTS})
        self._mark_step("S8")
        self._log_chk(
            "CHK-CONCURRENT-SAME-TARGET",
            f"simultaneous REGION_SIZE reads from SEP_IN, SYS_IN and JTAG all returned OKAY with "
            f"0x{REGION_SIZE_WORD:08X}",
        )

    async def _step_decerr_beside_valid(self) -> None:
        pairs = [(a, b) for a in PORTS for b in PORTS if a != b]
        for bad, good in pairs:
            bad_addr = UNMAPPED_ADDR if bad == "JTAG" else OUTSIDE_ADDR
            bad_item = self._decerr_read(f"{bad}_BESIDE", bad_addr)
            await self._parallel(
                f"beside_{bad}_{good}",
                {bad: [bad_item], good: [self._target("REGION_SIZE")]},
            )
        self._mark_step("S9")
        self._log_chk(
            "CHK-CONCURRENT-DECERR-BESIDE-VALID",
            f"for each of the {len(pairs)} ordered port pairs a read answered DECERR (SEP_IN and "
            f"SYS_IN at outside-window 0x{OUTSIDE_ADDR:08X}, JTAG at in-window gap "
            f"0x{UNMAPPED_ADDR:08X}) while the other port's simultaneous "
            f"REGION_SIZE read returned OKAY 0x{REGION_SIZE_WORD:X}",
        )

    async def _step_read_write(self) -> None:
        read = self._target("REGION_SIZE")
        write = self._write("SCRATCH_COLD_1_RW", scratch_addr(1), WRITE_PATTERN)
        await self._group("read_write", [read, write])
        await self.csr_read("SCRATCH_COLD_1_RW_RB", scratch_addr(1), expected=WRITE_PATTERN)
        self.value_checks = self.env.scoreboard.sys_axi_value_checks_seen - self.value_checks_start
        self._mark_step("S10")
        self._log_chk(
            "CHK-CONCURRENT-READ-WRITE",
            f"a REGION_SIZE read and a SCRATCH_COLD[1] write issued together on SEP_IN were both "
            f"answered OKAY, the read 0x{REGION_SIZE_WORD:X} and the write read back "
            f"0x{WRITE_PATTERN:X}",
        )

    async def _teardown(self) -> None:
        for i in range(SCRATCH_WORDS):
            await self.csr_write(f"SCRATCH_COLD_{i}_RESTORE", scratch_addr(i), 0)
        for i in range(SCRATCH_WORDS):
            await self.csr_write(f"WARM_{i}_RESTORE", warm_addr(i), 0)
        await self.csr_write(
            "INBOUND0_CONFIG_RESTORE",
            INBOUND0_FILTER_CONFIG,
            FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=8,
        )
        await self.csr_write(
            "INBOUND0_START_RESTORE", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_write(
            "INBOUND0_END_RESTORE", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_RESTORE_RB",
            INBOUND0_FILTER_CONFIG,
            expected=FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=8,
        )
        assert self._watch is not None
        self._watch.stop = True
        await RisingEdge(cocotb.top.clk_smc_i)
        await with_timeout(self._watcher, WATCH_JOIN_BOUND_NS, "ns")
        self.waits.append(f"stall_watch_join bound {WATCH_JOIN_BOUND_NS} ns, last joined")
        self.stalls = dict(self._watch.stalls)
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
            "CHK-NONVAC: ordered fence %s; checker lines %s; accesses %d >= floor %d; "
            "scoreboard exact-value compares %d >= %d; stamps %s",
            "<".join(_FENCE),
            ",".join(chk_ids),
            self.accesses,
            floor,
            self.value_checks,
            EXPECTED_READS,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
