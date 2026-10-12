# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Counted SEP_IN accesses to scratch, UART SCR and a mixed outstanding group.

Contract SMC_CLOCK_RATIO_011, anchor smc_clk_ratio_resp_once_test.
Allocated scenarios: RATIO-RESP-ONCE.S1, RATIO-RESP-ONCE.S2, RATIO-RESP-ONCE.S3.
Spec sources: hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/clk_rst.adoc, hw/sys/smc/doc/fabric.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_SYMBOL = "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR"
UART_NUM = smc_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_NUM")
SCRATCH_COUNT = 8
UART_SCR_COUNT = 8
GROUP_WRITES = 16
GROUP_READS = 16
AXI_TIMEOUT_NS = 50_000
FUSE_SENSE_MAX_CYCLES = 200_000
SAMPLER_CATCHUP_CYCLES = 64
QUIET_REF_PERIODS = 1024
OKAY = 0
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5")
FENCE_TERMS = {
    "S1": "SAMPLER_ARMED",
    "S2": "SMC_SEQUENCE_COUNTED",
    "S3": "PERIPH_SEQUENCE_COUNTED",
    "S4": "MIXED_GROUP_COUNTED",
    "S5": "QUIET_WINDOW_CLOSED",
}
CHK_ORDER = (
    "CHK-RESP-ONCE-SMC",
    "CHK-RESP-ONCE-PERIPH",
    "CHK-RESP-ONCE-MIXED",
    "CHK-TIMEOUT-PATHS",
)
CHK_STEP = {
    "CHK-RESP-ONCE-SMC": "S5",
    "CHK-RESP-ONCE-PERIPH": "S5",
    "CHK-RESP-ONCE-MIXED": "S5",
    "CHK-TIMEOUT-PATHS": "S5",
}
PORT_SIGNALS = (
    "clk_smc",
    "clk_ref",
    "s_axi_arvalid",
    "s_axi_arready",
    "s_axi_awvalid",
    "s_axi_awready",
    "s_axi_wvalid",
    "s_axi_wready",
    "s_axi_rvalid",
    "s_axi_rready",
    "s_axi_rresp",
    "s_axi_bvalid",
    "s_axi_bready",
    "s_axi_bresp",
)


def scratch_addr(k: int) -> int:
    return smc_indexed_addr(SCRATCH_SYMBOL, k)


def uart_scr_addr(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR", idx)


def _bit(dut, name: str) -> int:
    value = getattr(dut, name).value
    assert value.is_resolvable, f"{name} is not resolvable: {value}"
    return int(value)


class _HandshakeSampler:
    """Counts s_axi handshakes (valid and ready both high) on every clk_smc rising edge."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.ar = self.aw = self.w = self.r = self.b = 0
        self.r_resp: list[int] = []
        self.b_resp: list[int] = []

    async def run(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_smc)
            if _bit(dut, "s_axi_arvalid") & _bit(dut, "s_axi_arready"):
                self.ar += 1
            if _bit(dut, "s_axi_awvalid") & _bit(dut, "s_axi_awready"):
                self.aw += 1
            if _bit(dut, "s_axi_wvalid") & _bit(dut, "s_axi_wready"):
                self.w += 1
            if _bit(dut, "s_axi_rvalid") & _bit(dut, "s_axi_rready"):
                self.r += 1
                self.r_resp.append(_bit(dut, "s_axi_rresp"))
            if _bit(dut, "s_axi_bvalid") & _bit(dut, "s_axi_bready"):
                self.b += 1
                self.b_resp.append(_bit(dut, "s_axi_bresp"))

    def snap(self) -> tuple[int, int, int, int, int]:
        return (self.ar, self.aw, self.w, self.r, self.b)


class smc_clk_ratio_resp_once_test_seq(SmcCsrSeq):
    """Sampler-counted scratch, UART SCR and mixed outstanding accesses."""

    def __init__(self, name: str = "smc_clk_ratio_resp_once_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: list[str] = []
        self._steps: list[tuple[str, int]] = []
        self._chk_lines: list[tuple[str, int]] = []
        self._last_access = "none"
        self._bounded_waits: list[tuple[str, str, str]] = []

    def _mark_step(self, step_id: str) -> None:
        self._steps.append((step_id, int(get_sim_time("ps"))))

    def _emit_chk(self, chk_id: str, text: str) -> None:
        self._chk_lines.append((chk_id, int(get_sim_time("ps"))))
        self.chk_seen.append(chk_id)
        cocotb.log.info("%s: %s", chk_id, text)

    async def _read(self, tag: str, addr: int, label: str, want: int) -> None:
        self._last_access = f"read {tag} {label} addr=0x{addr:08x}"
        got = await self.csr_read(tag, addr, expected=want)
        assert got == want, f"{self._last_access}: got 0x{got:08x}, want 0x{want:08x}"

    async def _write(self, tag: str, addr: int, label: str, data: int) -> None:
        self._last_access = f"write {tag} {label}=0x{data:08x} addr=0x{addr:08x}"
        await self.csr_write(tag, addr, data)

    async def _catch_up(self, sampler: _HandshakeSampler, want_r: int, want_b: int, tag: str):
        """Wait until the sampler has seen the master-side responses; bounded by clk_smc cycles."""
        for _ in range(SAMPLER_CATCHUP_CYCLES):
            if sampler.r >= want_r and sampler.b >= want_b:
                return
            await RisingEdge(cocotb.top.clk_smc)
        raise AssertionError(
            f"{tag}: sampler saw R={sampler.r}/{want_r} B={sampler.b}/{want_b} after "
            f"{SAMPLER_CATCHUP_CYCLES} clk_smc cycles; last access {self._last_access}"
        )

    def _check_counts(self, tag, before, after, req_ar, req_aw, resp_r, resp_b, sampler, r0, b0):
        got = tuple(a - b for a, b in zip(after, before))
        want = (req_ar, req_aw, req_aw, resp_r, resp_b)
        assert got == want, (
            f"{tag}: sampler AR/AW/W/R/B {got} != requests/responses {want}; "
            f"last access {self._last_access}"
        )
        bad_r = [c for c in sampler.r_resp[r0 : r0 + resp_r] if c != OKAY]
        bad_b = [c for c in sampler.b_resp[b0 : b0 + resp_b] if c != OKAY]
        assert not bad_r and not bad_b, f"{tag}: non-OKAY R {bad_r} B {bad_b}"
        return got

    async def body(self) -> None:
        dut = cocotb.top
        for sig in PORT_SIGNALS:
            assert hasattr(dut, sig), f"tb_top has no {sig}"
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        self._bounded_waits.append(
            ("fuse_sense_done", f"{FUSE_SENSE_MAX_CYCLES}smc_cycles", "done")
        )
        sampler = _HandshakeSampler(dut)
        sampler_task = cocotb.start_soon(sampler.run())
        await ClockCycles(dut.clk_smc, 2)
        self._mark_step("S1")
        assert sampler.snap() == (0, 0, 0, 0, 0), f"traffic before arming: {sampler.snap()}"

        scratch_pat = [0x11111111 * (k + 1) for k in range(SCRATCH_COUNT)]
        s0 = sampler.snap()
        r0, b0 = len(sampler.r_resp), len(sampler.b_resp)
        for k in range(SCRATCH_COUNT):
            await self._write("SMC_WR", scratch_addr(k), f"SCRATCH[{k}]", scratch_pat[k])
        for k in range(SCRATCH_COUNT):
            await self._read("SMC_RD", scratch_addr(k), f"SCRATCH[{k}]", scratch_pat[k])
        await self._catch_up(sampler, s0[3] + 8, s0[4] + 8, "S2")
        smc_counts = self._check_counts("S2", s0, sampler.snap(), 8, 8, 8, 8, sampler, r0, b0)
        self._mark_step("S2")

        uart_pat = [0x5A, 0xA5, 0x3C, 0xC3, 0x96, 0x69, 0x0F, 0xF0]
        uart_final = {}
        s1 = sampler.snap()
        r1, b1 = len(sampler.r_resp), len(sampler.b_resp)
        for i in range(UART_SCR_COUNT):
            uart_final[i % UART_NUM] = uart_pat[i]
            await self._write(
                "PERIPH_WR", uart_scr_addr(i % UART_NUM), f"UART{i % UART_NUM}_SCR", uart_pat[i]
            )
        for i in range(UART_SCR_COUNT):
            u = i % UART_NUM
            await self._read("PERIPH_RD", uart_scr_addr(u), f"UART{u}_SCR", uart_final[u])
        await self._catch_up(sampler, s1[3] + 8, s1[4] + 8, "S3")
        periph_counts = self._check_counts("S3", s1, sampler.snap(), 8, 8, 8, 8, sampler, r1, b1)
        self._mark_step("S3")

        members: list[SmcSysAxiItem] = []
        for j in range(GROUP_WRITES):
            if j % 2 == 0:
                k = (j // 2) % SCRATCH_COUNT
                addr, data = scratch_addr(k), scratch_pat[k]
            else:
                u = (j // 2) % UART_NUM
                addr, data = uart_scr_addr(u), uart_final[u]
            members.append(self._member(f"MIX_WR{j}", SmcSysAxiOp.WRITE, addr, data, None))
            if j % 2 == 0:
                u = (j // 2) % UART_NUM
                members.append(
                    self._member(f"MIX_RD{j}", SmcSysAxiOp.READ, uart_scr_addr(u), 0, uart_final[u])
                )
            else:
                k = (j // 2) % SCRATCH_COUNT
                members.append(
                    self._member(f"MIX_RD{j}", SmcSysAxiOp.READ, scratch_addr(k), 0, scratch_pat[k])
                )
        assert len(members) == GROUP_WRITES + GROUP_READS
        s2 = sampler.snap()
        r2, b2 = len(sampler.r_resp), len(sampler.b_resp)
        self._last_access = "mixed outstanding group of 32 accesses"
        group = SmcSysAxiGroupItem("resp_once_mixed_group", members)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(members)
        codes = [m.resp_code for m in members]
        assert all(c == OKAY for c in codes), f"S4: member response codes {codes}"
        await self._catch_up(sampler, s2[3] + 16, s2[4] + 16, "S4")
        mixed_counts = self._check_counts("S4", s2, sampler.snap(), 16, 16, 16, 16, sampler, r2, b2)
        self._mark_step("S4")

        final = sampler.snap()
        await ClockCycles(dut.clk_ref, QUIET_REF_PERIODS)
        self._bounded_waits.append(
            ("quiet_window", f"{QUIET_REF_PERIODS}clk_ref_periods", f"R={sampler.r} B={sampler.b}")
        )
        late = tuple(a - b for a, b in zip(sampler.snap(), final))
        assert late == (0, 0, 0, 0, 0), (
            f"S5: handshakes after the last response AR/AW/W/R/B {late}; "
            f"last access {self._last_access}"
        )
        self._mark_step("S5")
        sampler_task.cancel()

        def line(name, c):
            return (
                f"{name} sampler AR={c[0]} AW={c[1]} W={c[2]} R={c[3]} B={c[4]} for "
                f"{c[0]} reads and {c[1]} writes, every R/B resp OKAY, "
                f"late beats in {QUIET_REF_PERIODS} clk_ref periods={sum(late)}"
            )

        self._emit_chk("CHK-RESP-ONCE-SMC", line("SCRATCH 8 writes+8 reads", smc_counts))
        self._emit_chk("CHK-RESP-ONCE-PERIPH", line("UART SCR 8 writes+8 reads", periph_counts))
        self._emit_chk(
            "CHK-RESP-ONCE-MIXED",
            line("32 outstanding mixed accesses", mixed_counts) + f", member resp codes {codes}",
        )
        self._bounded_waits.append(("sep_in_axi_access", f"{AXI_TIMEOUT_NS}ns", self._last_access))
        self._bounded_waits.append(
            (
                "sampler_catch_up",
                f"{SAMPLER_CATCHUP_CYCLES}smc_cycles",
                f"R={final[3]} B={final[4]}",
            )
        )
        waits = " ".join(f"{n}={b} last={s}" for n, b, s in self._bounded_waits)
        self._emit_chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(self._bounded_waits)} bounded waits: {waits}; expiry raises AssertionError",
        )
        self._assert_fence()

    @staticmethod
    def _member(label, op, addr, data, expected) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"resp_once_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.expected = expected
        return item

    def _assert_fence(self) -> None:
        ids = tuple(s for s, _ in self._steps)
        assert ids == STEP_ORDER, f"step ids {ids} != contract order {STEP_ORDER}"
        stamps = [t for _, t in self._steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing: {stamps}"
        chk_ids = tuple(c for c, _ in self._chk_lines)
        assert chk_ids == CHK_ORDER, f"checker lines {chk_ids} != order {CHK_ORDER}"
        step_stamp = dict(self._steps)
        for chk_id, t in self._chk_lines:
            assert t >= step_stamp[CHK_STEP[chk_id]], f"{chk_id} printed before its step stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            "<".join(FENCE_TERMS[s] for s in STEP_ORDER),
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._steps),
        )
