# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Valid-access recovery after runs of outside-window, gap and past-extent DECERR probes.

Spec sources: memmap.adoc Address Space Organization, fabric.adoc Fabric Transaction Limits.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    LOCAL_BASE_RESET,
    generated_decoded_extent,
    generated_window,
    smc_addr,
    smc_indexed_addr,
)
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
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)

AXI_RESP_OKAY = 0
AXI_RESP_DECERR = 3
BADCAB1E = 0xBADCAB1E
WRITE_PATTERN = 0xA5A55A5A
SCRATCH_PATTERN = 0x5A3C_96E1
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
ADMIT_POLL_BOUND_CYCLES = 6_000
AXI_TIMEOUT_NS = 50_000
RUNS = (1, 32, 33)
MIXED_RUN = 33
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

GLOBAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
LOCAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
REGION_SIZE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
CLOCK_GATE_CONTROL_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
SCRATCH_COLD_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
VALID_BASE_CONFIG = (
    ("GLOBAL_BASE", GLOBAL_BASE_REG, 0x4000_0000),
    ("LOCAL_BASE", LOCAL_BASE_REG, 0xC000_0000),
    ("REGION_SIZE", REGION_SIZE_REG, 0x0100_0000),
)
CLOCK_GATE_CONTROL_WORD = 0x1F00_0000

OUTSIDE_ADDRS = (0xBFFF_FFFC, 0x8000_0000, 0xD000_0000, 0x0000_0100_0000_0000)
_WDT0_FIRST, _ = generated_window("smc_cluster_core0_wdt")
GAP_ADDRS = (
    LOCAL_BASE_RESET + 0xC000,
    LOCAL_BASE_RESET + 0x3_8300,
    LOCAL_BASE_RESET + 0x1_6200,
    LOCAL_BASE_RESET + _WDT0_FIRST + generated_decoded_extent("smc_cluster_core0_wdt"),
)
MIXED_GAP_ADDRS = GAP_ADDRS[:3]

OUTSIDE_PORTS = ("SEP", "SYS")
GAP_PORTS = ("SEP", "SYS", "JTAG")

_STEPS = ("S1", "S2", "S3", "S4", "S5")
_FENCE = "SETUP<OUTSIDE_RUNS<GAP_RUNS<WRITE_READBACK<MIXED_RUN"
_CHECKERS = (
    "CHK-RECOVERY-OUTSIDE-WINDOW",
    "CHK-RECOVERY-GAP-PAST-EXTENT",
    "CHK-RECOVERY-WRITE-READBACK",
    "CHK-GAP-RUN-BOUNDED",
)
_CHECKER_STEPS = ("S2", "S3", "S4", "S5")


def _rname(code) -> str:
    return _RESP_NAMES.get(code, str(code))


class smc_invalid_probe_recovery_test_seq(SmcCsrSeq):
    """Run DECERR probe runs on the inbound ports and prove valid accesses still complete."""

    def __init__(self, name: str = "smc_invalid_probe_recovery_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"
        self.admit_state = "not polled"
        self.probes = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    def _sequencer(self, port: str):
        agent = {
            "SEP": self.env.sys_axi_agent,
            "SYS": self.env.sys_in_axi_agent,
            "JTAG": self.env.jtag_axi_agent,
        }[port]
        return agent.sequencer

    def _item(self, port, write, label, addr, wdata=0) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{port.lower()}_{'wr' if write else 'rd'}_{label}")
        item.op = SmcSysAxiOp.WRITE if write else SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.wdata = wdata
        return item

    async def _run_item(self, port: str, item: SmcSysAxiItem) -> SmcSysAxiItem:
        await _OneShot(item, f"{item.get_name()}_os").start(self._sequencer(port))
        self.accesses += 1
        assert item.resp_code is not None, f"{port} {item.get_name()}: no response recorded"
        return item

    async def _valid(self, port: str, label: str, addr: int, want: int, write_first=None) -> int:
        """Read ``addr`` (after writing ``write_first`` if given); require OKAY and ``want``."""
        if write_first is not None:
            wr = await self._run_item(port, self._item(port, True, label, addr, write_first))
            assert wr.resp_code == AXI_RESP_OKAY, (
                f"{port} {label} write @ 0x{addr:08x}: bresp {_rname(wr.resp_code)}, want OKAY"
            )
        item = self._item(port, False, label, addr)
        item.expected = want
        await self._run_item(port, item)
        got = item.rdata & 0xFFFF_FFFF
        assert item.resp_code == AXI_RESP_OKAY, (
            f"{port} {label} @ 0x{addr:08x}: rresp {_rname(item.resp_code)}, want OKAY"
        )
        assert got == want, f"{port} {label} @ 0x{addr:08x}: read 0x{got:08x}, want 0x{want:08x}"
        return got

    async def _probe_run(self, port: str, count: int, addrs, tag: str) -> dict:
        """Issue ``count`` alternating read/write probes, each required to answer DECERR."""
        if port == "SEP":
            self.env.axi_monitor.expected_decerr_addrs.update(addrs)
        rdata_seen: set[int] = set()
        worst_ns = 0.0
        for i in range(count):
            write = i % 2 == 1
            addr = addrs[(i // 2) % len(addrs)]
            item = self._item(port, write, f"{tag}_{i}", addr, WRITE_PATTERN)
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = AXI_RESP_DECERR
            start_ns = get_sim_time("ns")
            await self._run_item(port, item)
            worst_ns = max(worst_ns, get_sim_time("ns") - start_ns)
            self.probes += 1
            assert item.resp_code == AXI_RESP_DECERR, (
                f"{port} {tag} probe {i} {'write' if write else 'read'} @ 0x{addr:x}: "
                f"resp {_rname(item.resp_code)}, want DECERR (rdata 0x{item.rdata:x})"
            )
            if not write:
                rdata_seen.add(item.rdata & 0xFFFF_FFFF)
        return {"count": count, "rdata": rdata_seen, "worst_ns": worst_ns}

    async def _setup(self) -> str:
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, PASS_ALL_END, length=8)
        await self.csr_write(
            "INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        dut = cocotb.top
        item = self._item("SYS", False, "S1_ADMIT", CLOCK_GATE_CONTROL_REG)
        item.expected = CLOCK_GATE_CONTROL_WORD
        task = cocotb.start_soon(_OneShot(item, "sys_S1_ADMIT_os").start(self._sequencer("SYS")))
        cycles = 0
        hits = 0
        while not task.done():
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            cycles += 1
            self.admit_state = f"{cycles} cycles, read_hit[0] seen {hits}"
            assert cycles <= ADMIT_POLL_BOUND_CYCLES, (
                f"sys_axi_in admit read not answered in {cycles} cycles"
            )
            hit = dut.tb_inb_read_hit.value
            assert hit.is_resolvable, "tb_inb_read_hit is X/Z"
            hits += int(hit) & 1
        await RisingEdge(dut.clk_smc_i)
        await task
        self.accesses += 1
        assert item.resp_code == AXI_RESP_OKAY, (
            f"admit read answered {_rname(item.resp_code)}, want OKAY"
        )
        assert hits > 0, f"tb_inb_read_hit[0] never set in {cycles} cycles of the admit read"
        self.admit_state = f"{cycles} cycles, read_hit[0] seen {hits}"
        return (
            f"entry 0 pass-all programmed over sep_axi_in; sys_axi_in read of "
            f"CLOCK_GATE_CONTROL OKAY with tb_inb_read_hit[0] high for {hits} samples "
            f"in {cycles} cycles"
        )

    async def _restore(self) -> None:
        defaults = (
            ("CONFIG", INBOUND0_FILTER_CONFIG, FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT),
            ("END", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT),
            ("START", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT),
        )
        for name, addr, want in defaults:
            await self.csr_write(f"INBOUND0_{name}_RESTORE", addr, want, length=8)
        for name, addr, want in defaults:
            await self.csr_read(f"INBOUND0_{name}_RESTORE_RB", addr, expected=want, length=8)

    @staticmethod
    def _rdata_text(seen: set[int]) -> str:
        return "/".join(f"0x{v:08X}" for v in sorted(seen)) or "none"

    async def _outside_runs(self) -> str:
        parts = []
        for port in OUTSIDE_PORTS:
            for count in RUNS:
                run = await self._probe_run(port, count, OUTSIDE_ADDRS, f"OUT_{port}_{count}")
                regs = []
                for name, addr, want in VALID_BASE_CONFIG:
                    got = await self._valid(port, f"OUT_{port}_{count}_{name}", addr, want)
                    regs.append(f"{name}=0x{got:08X}")
                parts.append(
                    f"{port} run {count} {run['count']}/{run['count']} DECERR (read rdata "
                    f"{self._rdata_text(run['rdata'])}) then OKAY {' '.join(regs)}"
                )
        return "; ".join(parts)

    async def _gap_runs(self) -> str:
        parts = []
        for port in GAP_PORTS:
            for count in RUNS:
                run = await self._probe_run(port, count, GAP_ADDRS, f"GAP_{port}_{count}")
                got = await self._valid(
                    port, f"GAP_{port}_{count}_CGC", CLOCK_GATE_CONTROL_REG, CLOCK_GATE_CONTROL_WORD
                )
                parts.append(
                    f"{port} run {count} {run['count']}/{run['count']} DECERR (read rdata "
                    f"{self._rdata_text(run['rdata'])}) then OKAY CLOCK_GATE_CONTROL=0x{got:08X}"
                )
        return "; ".join(parts)

    async def _write_readback(self) -> str:
        parts = []
        first = True
        for port in GAP_PORTS:
            if first:
                got = await self._valid(
                    port, "SCRATCH_COLD_0_SEP", SCRATCH_COLD_0, SCRATCH_PATTERN, SCRATCH_PATTERN
                )
                first = False
            else:
                got = await self._valid(
                    port, f"SCRATCH_COLD_0_{port}", SCRATCH_COLD_0, SCRATCH_PATTERN
                )
            parts.append(f"{port} read 0x{got:08X}")
        await self._valid("SEP", "SCRATCH_COLD_0_RESTORE", SCRATCH_COLD_0, 0, write_first=0)
        return (
            f"SCRATCH_COLD[0] write 0x{SCRATCH_PATTERN:08X} OKAY over sep_axi_in, readback "
            f"{'; '.join(parts)}; restored to 0x00000000 and read back 0"
        )

    async def _mixed_run(self) -> str:
        self.env.axi_monitor.expected_decerr_addrs.update(MIXED_GAP_ADDRS)
        reads = writes = 0
        worst_ns = 0.0
        for i in range(MIXED_RUN):
            write = i % 2 == 1
            addr = MIXED_GAP_ADDRS[i % len(MIXED_GAP_ADDRS)]
            item = self._item("SEP", write, f"MIXED_{i}", addr, WRITE_PATTERN)
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = AXI_RESP_DECERR
            start_ns = get_sim_time("ns")
            await self._run_item("SEP", item)
            took_ns = get_sim_time("ns") - start_ns
            worst_ns = max(worst_ns, took_ns)
            self.probes += 1
            assert took_ns < AXI_TIMEOUT_NS, f"mixed probe {i} took {took_ns} ns"
            assert item.resp_code == AXI_RESP_DECERR, (
                f"mixed probe {i} {'write' if write else 'read'} @ 0x{addr:x}: resp "
                f"{_rname(item.resp_code)}, want DECERR"
            )
            if write:
                writes += 1
            else:
                reads += 1
                got = item.rdata & 0xFFFF_FFFF
                assert got == BADCAB1E, (
                    f"mixed probe {i} read @ 0x{addr:x}: rdata 0x{got:08x}, want 0x{BADCAB1E:08x}"
                )
        return (
            f"{MIXED_RUN} consecutive gap probes on sep_axi_in ({reads} reads rdata "
            f"0x{BADCAB1E:08X}, {writes} writes) all DECERR; worst measured "
            f"latency {worst_ns:.2f} ns under the {AXI_TIMEOUT_NS} ns guard"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)

        admit = await self._setup()
        self._mark_step("S1")

        text = await self._outside_runs()
        self._mark_step("S2")
        self._log_chk("CHK-RECOVERY-OUTSIDE-WINDOW", f"{text}; {admit}")

        text = await self._gap_runs()
        self._mark_step("S3")
        self._log_chk("CHK-RECOVERY-GAP-PAST-EXTENT", text)

        text = await self._write_readback()
        self._mark_step("S4")
        self._log_chk("CHK-RECOVERY-WRITE-READBACK", text)

        text = await self._mixed_run()
        self._mark_step("S5")
        self._log_chk("CHK-GAP-RUN-BOUNDED", text)

        await self._restore()

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, last "
            "observed %s; S1 admit poll bounded %d clk_smc_i rises, last observed %s; "
            "%d AXI accesses (%d probes) each bounded by the driver timeout %d ns "
            "(allow_timeout False), all answered; no other wait",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            ADMIT_POLL_BOUND_CYCLES,
            self.admit_state,
            self.accesses,
            self.probes,
            AXI_TIMEOUT_NS,
        )

    def nonvac_fence(self, floor: int) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), step in zip(self._chk_marks, _CHECKER_STEPS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self.accesses >= floor, f"{self.accesses} accesses, floor {floor}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; accesses %d >= floor %d; stamps %s",
            _FENCE,
            ",".join(chk_ids),
            self.accesses,
            floor,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
