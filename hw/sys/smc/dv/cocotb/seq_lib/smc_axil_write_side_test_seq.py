# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Downstream AXI-Lite write-side traffic and the idle windows around it.

Spec sources: smc_external_mandatory.rdl efuse_shim_ctrl, regblock_udps.rdl external
registers, fabric.adoc Topology (AXI-Lite network), AMBA no-VALID-when-idle rule.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import EFUSE_BANK_INIT_TIME_RESET, EFUSE_SHIM_CTRL_WINDOW

EXTERNAL_WINDOW = smc_addr("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_GPIO_EXTRA_CTRL_BASE_ADDR")
PLL_WRAP_WINDOW = smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_SMC_PLL_WRAP_BASE_ADDR")
SS_CONFIG = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR")

PROBES = ("tb_axil_external_active", "tb_axil_efuse_bank_active", "tb_axil_any_master_active")
DTP_PROBE = "tb_axil_dtp_csr_active"
IDLE_RESET_CYCLES = 2000
IDLE_BURST_CYCLES = 64
# Bound of the post-access wait for a probe to fall back to 0, in clk_smc_i samples.
LOW_POLL_BOUND = 32
FUSE_WAIT_BOUND = 200_000
AXI_TIMEOUT_NS = 50_000
WRITE_PASSES = 8
INTERLEAVE_LAST = 0xE0 + WRITE_PASSES - 1
CONCURRENCY_PASSES = WRITE_PASSES
EXPECTED_ACCESSES = 2 + (2 * WRITE_PASSES + 1) + 8 + 6 + 1 + 2

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
_CHECKERS = (
    ("CHK-AXLWS-PROBE-ALIVE", "S2"),
    ("CHK-AXLWS-IDLE-AFTER-RESET", "S1"),
    ("CHK-AXLWS-WRITE-INTERLEAVE", "S3"),
    ("CHK-AXLWS-MIXED-RDWR", "S4"),
    ("CHK-AXLWS-EXT-WRITE-PENDING", "S5"),
    ("CHK-AXLWS-IDLE-AFTER-BURST", "S6"),
)


def _sample(name: str, label: str) -> int:
    sig = getattr(cocotb.top, name)
    assert sig.value.is_resolvable, f"{label}: {name} is X/Z ({sig.value})"
    return int(sig.value)


class _ProbeWatch:
    """Per-probe high-cycle counts and cycles with the two downstream ports high together."""

    def __init__(self) -> None:
        self.stop = False
        self.high = dict.fromkeys(PROBES + (DTP_PROBE,), 0)
        self.concurrent = 0

    async def run(self) -> None:
        clk = cocotb.top.clk_smc_i
        while not self.stop:
            await RisingEdge(clk)
            vals = {name: _sample(name, "watch") for name in self.high}
            for name, val in vals.items():
                self.high[name] += val
            if vals["tb_axil_external_active"] and vals["tb_axil_efuse_bank_active"]:
                self.concurrent += 1

    async def finish(self, task) -> None:
        self.stop = True
        await RisingEdge(cocotb.top.clk_smc_i)
        await task


class smc_axil_write_side_test_seq(SmcCsrSeq):
    """Write-side traffic to the eFuse-shim and external windows, with idle windows."""

    def __init__(self, name: str = "smc_axil_write_side_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.bounded_waits: list[tuple[str, str, str]] = []
        self.last_access = "none"
        self.group_items = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    def _note(self, item: SmcSysAxiItem) -> None:
        self.last_access = f"{item.op.value}@0x{item.addr:08x} resp={item.resp_code}"

    def _item(
        self,
        label: str,
        op: SmcSysAxiOp,
        addr: int,
        *,
        wdata: int = 0,
        expected: int | None = None,
        tolerate_error: bool = False,
        beats: int = 1,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value}_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.beats = beats
        item.wdata = wdata
        item.expected = expected
        item.allow_error = tolerate_error
        return item

    async def _run_item(self, item: SmcSysAxiItem) -> SmcSysAxiItem:
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._note(item)
        return item

    async def _run_group(self, name: str, members: list[SmcSysAxiItem]) -> None:
        group = SmcSysAxiGroupItem(name, members)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(members)
        self.group_items += len(members)
        self._note(members[-1])

    async def _poll_all_low(self, label: str) -> int:
        clk = cocotb.top.clk_smc_i
        last = {name: _sample(name, label) for name in PROBES}
        for n in range(1, LOW_POLL_BOUND + 1):
            if not any(last.values()):
                self.bounded_waits.append(
                    (f"low_poll_{label}", f"{LOW_POLL_BOUND}clk_smc_i", f"low after {n - 1}")
                )
                return n - 1
            await RisingEdge(clk)
            last = {name: _sample(name, f"{label}[{n}]") for name in PROBES}
        raise AssertionError(
            f"{label}: probes did not return to 0 within {LOW_POLL_BOUND} clk_smc_i samples "
            f"(last {last})"
        )

    async def _wait_fuse_sense(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND)
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            self.bounded_waits.append(
                (name, f"{FUSE_WAIT_BOUND}clk_smc_i", f"last={_sample(name, 'fuse wait')}")
            )

    async def _idle_window(self, cycles: int, label: str) -> tuple[dict[str, int], int]:
        clk = cocotb.top.clk_smc_i
        high = dict.fromkeys(PROBES, 0)
        dtp = 0
        for n in range(cycles):
            await RisingEdge(clk)
            for name in PROBES:
                high[name] += _sample(name, f"{label}[{n}]")
            dtp += _sample(DTP_PROBE, f"{label}[{n}]")
        return high, dtp

    async def _positive_controls(self) -> str:
        for name in PROBES:
            assert _sample(name, "S2 precondition") == 0, f"{name} already 1 before S2"
        results = []
        for label, addr, expect_efuse in (
            ("EFUSE_SHIM", EFUSE_SHIM_CTRL_WINDOW, True),
            ("PLL_WRAP", PLL_WRAP_WINDOW, False),
        ):
            watch = _ProbeWatch()
            task = cocotb.start_soon(watch.run())
            item = self._item(
                f"S2_{label}",
                SmcSysAxiOp.READ,
                addr,
                expected=EFUSE_BANK_INIT_TIME_RESET if expect_efuse else None,
                tolerate_error=not expect_efuse,
            )
            await self._run_item(item)
            await watch.finish(task)
            low = await self._poll_all_low(f"S2_{label}")
            if expect_efuse:
                needed = ("tb_axil_efuse_bank_active", "tb_axil_any_master_active")
            else:
                needed = ("tb_axil_external_active",)
            for name in needed:
                assert watch.high[name] > 0, (
                    f"{name} never read 1 while the SEP_IN read of 0x{addr:08x} was in flight "
                    f"(high cycles {watch.high})"
                )
            results.append(
                f"{label}@0x{addr:08x} resp={item.resp_code} rdata=0x{item.rdata & 0xFFFFFFFF:08x} "
                f"high cycles {watch.high} low after {low}"
            )
        return "; ".join(results)

    async def body(self) -> None:
        await self._wait_fuse_sense()
        self.env.axi_monitor.expected_decerr_addrs.update(
            {EXTERNAL_WINDOW, PLL_WRAP_WINDOW, SS_CONFIG, EFUSE_SHIM_CTRL_WINDOW}
        )

        idle_high, idle_dtp = await self._idle_window(IDLE_RESET_CYCLES, "S1")
        self.bounded_waits.append(
            ("idle_window_after_reset", f"{IDLE_RESET_CYCLES}clk_smc_i fixed", f"high {idle_high}")
        )
        assert not any(idle_high.values()), (
            f"AXI-Lite activity in the {IDLE_RESET_CYCLES}-cycle window after reset, before "
            f"any access: per-probe high cycles {idle_high}"
        )
        self._mark_step("S1")

        alive = await self._positive_controls()
        self._mark_step("S2")
        self._log_chk(
            "CHK-AXLWS-PROBE-ALIVE",
            f"the three backable probes read 1 during their positive control and 0 after: {alive}",
        )
        self._log_chk(
            "CHK-AXLWS-IDLE-AFTER-RESET",
            f"all of tb_axil_external_active, tb_axil_efuse_bank_active and "
            f"tb_axil_any_master_active read 0 in each of {IDLE_RESET_CYCLES} consecutive "
            f"clk_smc_i cycles after wait_fuse_sense_done and before any access "
            f"(high cycles {idle_high}; {DTP_PROBE} reported only: {idle_dtp} high cycle(s))",
        )

        await self._step_interleave()
        self._mark_step("S3")
        await self._step_mixed()
        self._mark_step("S4")
        await self._step_pending()
        self._mark_step("S5")
        await self._step_burst()
        self._mark_step("S6")
        await self._step_teardown()
        self._mark_step("S7")

        self.assert_all_reachable(EXPECTED_ACCESSES, "AXI-Lite write side")
        self._finish()

    async def _step_interleave(self) -> None:
        watch = _ProbeWatch()
        task = cocotb.start_soon(watch.run())
        members: list[SmcSysAxiItem] = []
        efuse_writes: list[SmcSysAxiItem] = []
        ext_writes: list[SmcSysAxiItem] = []
        for i in range(WRITE_PASSES):
            efuse = self._item(
                f"EFUSE_{i}", SmcSysAxiOp.WRITE, EFUSE_SHIM_CTRL_WINDOW, wdata=0xE0 + i
            )
            ext = self._item(
                f"EXT_{i}",
                SmcSysAxiOp.WRITE,
                EXTERNAL_WINDOW,
                wdata=0xA5A50000 + i,
                tolerate_error=True,
            )
            efuse_writes.append(efuse)
            ext_writes.append(ext)
            members.extend((efuse, ext))
        await self._run_group("axlws_write_group", members)
        await watch.finish(task)
        readback = await self._run_item(
            self._item("EFUSE_READBACK", SmcSysAxiOp.READ, EFUSE_SHIM_CTRL_WINDOW)
        )
        value = readback.rdata & 0xFFFFFFFF
        assert all(w.resp_code == 0 for w in efuse_writes), (
            f"eFuse-shim write responses {[w.resp_code for w in efuse_writes]}, want all OKAY"
        )
        assert watch.concurrent > 0, (
            f"no cycle had the eFuse-shim and external ports high together "
            f"(high cycles {watch.high})"
        )
        assert value == INTERLEAVE_LAST, (
            f"eFuse-shim register reads 0x{value:08x} after the group, want 0x{INTERLEAVE_LAST:08x}"
        )
        self.bounded_waits.append(("axi_access_S3", f"{AXI_TIMEOUT_NS}ns", self.last_access))
        self._s3 = (
            f"all {len(members)} writes completed; eFuse-shim readback 0x{value:08x} "
            f"(last write wins), all {WRITE_PASSES} eFuse-shim writes OKAY; "
            f"{watch.concurrent} cycle(s) with the eFuse-shim and external ports high together "
            f"(any_master is their OR); high cycles {watch.high}; external-window write "
            f"responses (printed, not asserted, owner value pending) "
            f"{[w.resp_code for w in ext_writes]}"
        )

    async def _step_mixed(self) -> None:
        watch = _ProbeWatch()
        task = cocotb.start_soon(watch.run())
        members: list[SmcSysAxiItem] = []
        efuse_reads: list[SmcSysAxiItem] = []
        efuse_writes: list[SmcSysAxiItem] = []
        ext_items: list[SmcSysAxiItem] = []
        for i in range(2):
            rd = self._item(
                f"MIX_EFUSE_RD_{i}",
                SmcSysAxiOp.READ,
                EFUSE_SHIM_CTRL_WINDOW,
                expected=INTERLEAVE_LAST,
            )
            wr = self._item(
                f"MIX_EXT_WR_{i}",
                SmcSysAxiOp.WRITE,
                EXTERNAL_WINDOW,
                wdata=0xA5A51000 + i,
                tolerate_error=True,
            )
            efuse_reads.append(rd)
            ext_items.append(wr)
            members.extend((rd, wr))
        for i in range(2, 4):
            rd = self._item(
                f"MIX_EXT_RD_{i}", SmcSysAxiOp.READ, EXTERNAL_WINDOW, tolerate_error=True
            )
            wr = self._item(
                f"MIX_EFUSE_WR_{i}", SmcSysAxiOp.WRITE, EFUSE_SHIM_CTRL_WINDOW, wdata=0xF0 + i
            )
            ext_items.append(rd)
            efuse_writes.append(wr)
            members.extend((rd, wr))
        await self._run_group("axlws_mixed_group", members)
        await watch.finish(task)
        assert all(w.resp_code == 0 for w in efuse_writes + efuse_reads), (
            f"eFuse-shim responses {[w.resp_code for w in efuse_writes + efuse_reads]}, "
            "want all OKAY"
        )
        reads = [r.rdata & 0xFFFFFFFF for r in efuse_reads]
        assert all(v == INTERLEAVE_LAST for v in reads), (
            f"eFuse-shim reads {[hex(v) for v in reads]}, want 0x{INTERLEAVE_LAST:08x}"
        )
        assert watch.concurrent > 0, (
            f"no cycle had the eFuse-shim and external ports high together "
            f"(high cycles {watch.high})"
        )
        self.bounded_waits.append(("axi_access_S4", f"{AXI_TIMEOUT_NS}ns", self.last_access))
        ext = [(it.op.value, it.resp_code, hex(it.rdata & 0xFFFFFFFF)) for it in ext_items]
        self._s4 = (
            f"all {len(members)} mixed members completed; eFuse-shim reads "
            f"{[hex(v) for v in reads]} equal the last value written, eFuse-shim writes OKAY; "
            f"{watch.concurrent} cycle(s) with the two downstream ports high together; "
            f"external-window (op, resp, rdata) printed, not asserted (owner value pending): {ext}"
        )

    async def _step_pending(self) -> None:
        first = await self._run_item(self._item("SS_CONFIG_H", SmcSysAxiOp.READ, SS_CONFIG))
        held = first.rdata & 0xFFFFFFFF
        members = [
            self._item(
                f"SS_CONFIG_WR_{i}",
                SmcSysAxiOp.WRITE,
                SS_CONFIG,
                wdata=held,
                tolerate_error=True,
            )
            for i in range(3)
        ]
        members.append(
            self._item("SS_CONFIG_GRP_RD", SmcSysAxiOp.READ, SS_CONFIG, tolerate_error=True)
        )
        await self._run_group("axlws_ss_config_group", members)
        after = await self._run_item(
            self._item("SS_CONFIG_AFTER", SmcSysAxiOp.READ, SS_CONFIG, expected=held)
        )
        got = after.rdata & 0xFFFFFFFF
        assert got == held, f"SS_CONFIG reads 0x{got:08x} after the writes of 0x{held:08x}"
        self.bounded_waits.append(("axi_access_S5", f"{AXI_TIMEOUT_NS}ns", self.last_access))
        self._s5 = (
            f"all 4 group requests answered (write resp {[m.resp_code for m in members[:3]]}, "
            f"read resp {members[3].resp_code} rdata 0x{members[3].rdata & 0xFFFFFFFF:08x}); "
            f"SS_CONFIG H=0x{held:08x} reads 0x{got:08x} after the group"
        )

    async def _step_burst(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i
        samples: list[tuple[int, tuple[int, ...]]] = []
        stop = [False]

        async def record() -> None:
            while not stop[0]:
                await RisingEdge(clk)
                last = (
                    1
                    if (
                        _sample("s_axi_rvalid", "S6")
                        and _sample("s_axi_rready", "S6")
                        and _sample("s_axi_rlast", "S6")
                    )
                    else 0
                )
                samples.append((last, tuple(_sample(n, "S6") for n in PROBES)))

        task = cocotb.start_soon(record())
        burst = await self._run_item(
            self._item(
                "BURST4", SmcSysAxiOp.READ, EFUSE_SHIM_CTRL_WINDOW, beats=4, tolerate_error=True
            )
        )
        for _ in range(IDLE_BURST_CYCLES + 2):
            await RisingEdge(clk)
        stop[0] = True
        await RisingEdge(clk)
        await task
        self.bounded_waits.append(("axi_access_S6", f"{AXI_TIMEOUT_NS}ns", self.last_access))
        last_idx = max((i for i, (hs, _) in enumerate(samples) if hs), default=None)
        assert last_idx is not None, "no R handshake with RLAST seen during the 4-beat read"
        window = samples[last_idx + 1 : last_idx + 1 + IDLE_BURST_CYCLES]
        assert len(window) == IDLE_BURST_CYCLES, f"only {len(window)} cycles after the last beat"
        busy = [(i, p) for i, (_, p) in enumerate(window) if any(p)]
        assert not busy, f"AXI-Lite activity after the burst's last R beat: {busy[:4]}"
        self.bounded_waits.append(
            ("idle_window_after_burst", f"{IDLE_BURST_CYCLES}clk_smc_i fixed", "all low")
        )
        self._s6 = (
            f"the 4-beat INCR read completed (resp={burst.resp_code}); in each of "
            f"{IDLE_BURST_CYCLES} clk_smc_i cycles after its last R beat the three probes read 0"
        )

    async def _step_teardown(self) -> None:
        await self._run_item(
            self._item(
                "EFUSE_RESTORE",
                SmcSysAxiOp.WRITE,
                EFUSE_SHIM_CTRL_WINDOW,
                wdata=EFUSE_BANK_INIT_TIME_RESET,
            )
        )
        got = await self._run_item(
            self._item(
                "EFUSE_RESTORE_RD",
                SmcSysAxiOp.READ,
                EFUSE_SHIM_CTRL_WINDOW,
                expected=EFUSE_BANK_INIT_TIME_RESET,
            )
        )
        assert got.rdata & 0xFFFFFFFF == EFUSE_BANK_INIT_TIME_RESET, (
            f"EFUSE_BANK_INIT_TIME reads 0x{got.rdata & 0xFFFFFFFF:08x} after teardown, "
            f"want 0x{EFUSE_BANK_INIT_TIME_RESET:08x}"
        )

    def _finish(self) -> None:
        self._log_chk("CHK-AXLWS-WRITE-INTERLEAVE", self._s3)
        self._log_chk("CHK-AXLWS-MIXED-RDWR", self._s4)
        self._log_chk("CHK-AXLWS-EXT-WRITE-PENDING", self._s5)
        self._log_chk("CHK-AXLWS-IDLE-AFTER-BURST", self._s6)
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        marks = tuple(c for c, _ in self._chk_marks)
        assert marks == tuple(c for c, _ in _CHECKERS), f"checker lines {marks}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step}"
        sb = self.env.scoreboard
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; scoreboard checked %d "
            "item(s) for %d issued access(es) (%d group member(s))",
            "<".join(ids),
            ",".join(marks),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            sb.sys_axi_checks_seen,
            self.accesses,
            self.group_items,
        )
        self.bounded_waits.append(
            ("sep_in_axi_accesses", f"{AXI_TIMEOUT_NS}ns each x{self.accesses}", self.last_access)
        )
        self.bounded_waits.append(("sys_out_responder_polls", "none", "not used"))
        waits = " ".join(f"{n}={b} last={s};" for n, b, s in self.bounded_waits)
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s expiry raises AssertionError",
            len(self.bounded_waits),
            waits,
        )
