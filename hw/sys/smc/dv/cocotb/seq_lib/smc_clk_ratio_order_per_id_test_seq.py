# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-ID response order of outstanding SEP_IN groups over the scratch and UART SCR paths.

Spec sources: hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/fabric.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import LOCAL_BASE_RESET, smc_deadspace_ranges, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_SYMBOL = "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR"
UART_SCR_SYMBOL = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR"
AXI_TIMEOUT_NS = 50_000
FUSE_SENSE_MAX_CYCLES = 200_000
SAMPLER_CATCHUP_CYCLES = 64
OKAY = 0
#: A write between unit apertures answers DECERR, except BASE+0x17000..0x17FFF (memmap.adoc).
DECERR = 3
RESP_NAME = {OKAY: "OKAY", DECERR: "DECERR"}
SAME_ID = 0x21
DIFF_IDS = (0x31, 0x32, 0x33, 0x34)
PRELOAD = {
    "SCRATCH0": 0xA5A50001,
    "SCRATCH1": 0x5A5A0002,
    "UART0": 0x5A,
    "UART1": 0xA5,
}
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5")
FENCE_TERMS = {
    "S1": "SAMPLER_ARMED",
    "S2": "PRELOAD_DONE",
    "S3": "SAME_ID_READS",
    "S4": "SAME_ID_WRITES",
    "S5": "DIFFERENT_ID_READS",
}
CHK_ORDER = (
    "CHK-ORDER-READS-SAME-ID",
    "CHK-ORDER-WRITES-SAME-ID",
    "CHK-ORDER-DIFFERENT-IDS",
    "CHK-TIMEOUT-PATHS",
)
CHK_STEP = {
    "CHK-ORDER-READS-SAME-ID": "S3",
    "CHK-ORDER-WRITES-SAME-ID": "S4",
    "CHK-ORDER-DIFFERENT-IDS": "S5",
    "CHK-TIMEOUT-PATHS": "S5",
}
PORT_SIGNALS = (
    "clk_smc",
    "s_axi_arvalid",
    "s_axi_arready",
    "s_axi_arid",
    "s_axi_awvalid",
    "s_axi_awready",
    "s_axi_awid",
    "s_axi_rvalid",
    "s_axi_rready",
    "s_axi_rid",
    "s_axi_rdata",
    "s_axi_rresp",
    "s_axi_bvalid",
    "s_axi_bready",
    "s_axi_bid",
    "s_axi_bresp",
)


def _val(dut, name: str) -> int:
    value = getattr(dut, name).value
    assert value.is_resolvable, f"{name} is not resolvable: {value}"
    return int(value)


class _Sampler:
    """Logs (id, data, resp) of every AR, R, AW and B handshake on clk_smc."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.ar: list[int] = []
        self.aw: list[int] = []
        self.r: list[tuple[int, int, int]] = []
        self.b: list[tuple[int, int]] = []

    async def run(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_smc)
            if _val(dut, "s_axi_arvalid") & _val(dut, "s_axi_arready"):
                self.ar.append(_val(dut, "s_axi_arid"))
            if _val(dut, "s_axi_awvalid") & _val(dut, "s_axi_awready"):
                self.aw.append(_val(dut, "s_axi_awid"))
            if _val(dut, "s_axi_rvalid") & _val(dut, "s_axi_rready"):
                self.r.append(
                    (_val(dut, "s_axi_rid"), _val(dut, "s_axi_rdata"), _val(dut, "s_axi_rresp"))
                )
            if _val(dut, "s_axi_bvalid") & _val(dut, "s_axi_bready"):
                self.b.append((_val(dut, "s_axi_bid"), _val(dut, "s_axi_bresp")))


class smc_clk_ratio_order_per_id_test_seq(SmcCsrSeq):
    """Sampler-checked same-ID and different-ID outstanding groups."""

    def __init__(self, name: str = "smc_clk_ratio_order_per_id_test_seq") -> None:
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

    @staticmethod
    def _addr(label: str) -> int:
        if label.startswith("SCRATCH"):
            return smc_indexed_addr(SCRATCH_SYMBOL, int(label[-1]))
        return smc_indexed_addr(UART_SCR_SYMBOL, int(label[-1]))

    async def _catch_up(self, sampler, n_r: int, n_b: int, tag: str) -> None:
        for _ in range(SAMPLER_CATCHUP_CYCLES):
            if len(sampler.r) >= n_r and len(sampler.b) >= n_b:
                return
            await RisingEdge(cocotb.top.clk_smc)
        raise AssertionError(
            f"{tag}: sampler saw R={len(sampler.r)}/{n_r} B={len(sampler.b)}/{n_b} after "
            f"{SAMPLER_CATCHUP_CYCLES} clk_smc cycles; last access {self._last_access}"
        )

    @staticmethod
    def _member(label, op, addr, data, axi_id) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"order_per_id_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.axi_id = axi_id
        return item

    @staticmethod
    def _witness_addrs(count: int) -> list[int]:
        """Word addresses inside a generated deadspace gap between unit apertures."""
        lo, hi = next(
            (lo, hi)
            for lo, hi in smc_deadspace_ranges()
            if lo >= LOCAL_BASE_RESET + 0x40000 and hi - lo >= 4 * count
        )
        return [lo + 4 * k for k in range(count)]

    async def _run_group(self, name: str, members: list[SmcSysAxiItem]) -> None:
        self._last_access = f"{name} group of {len(members)} accesses"
        group = SmcSysAxiGroupItem(name, members)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(members)
        codes = [m.resp_code for m in members]
        want = [m.expected_resp if m.expect_error else OKAY for m in members]
        assert codes == want, f"{name}: member response codes {codes}, want {want}"

    def _lane_data(self, raw: int, addr: int) -> int:
        lanes = len(cocotb.top.s_axi_rdata) // 8
        return (raw >> ((addr % lanes) * 8)) & 0xFFFFFFFF

    async def body(self) -> None:
        dut = cocotb.top
        for sig in PORT_SIGNALS:
            assert hasattr(dut, sig), f"tb_top has no {sig}"
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        self._bounded_waits.append(
            ("fuse_sense_done", f"{FUSE_SENSE_MAX_CYCLES}smc_cycles", "done")
        )
        sampler = _Sampler(dut)
        sampler_task = cocotb.start_soon(sampler.run())
        await ClockCycles(dut.clk_smc, 2)
        self._mark_step("S1")

        for label, value in PRELOAD.items():
            self._last_access = f"preload {label}=0x{value:x}"
            await self.csr_write(f"PRELOAD_{label}", self._addr(label), value)
        for label, value in PRELOAD.items():
            self._last_access = f"preload readback {label}"
            got = await self.csr_read(f"PRELOAD_RD_{label}", self._addr(label), expected=value)
            assert got == value, f"{self._last_access}: got 0x{got:x}, want 0x{value:x}"
        self._mark_step("S2")

        # S3: eight same-ID reads, SCRATCH0, UART0, SCRATCH1, UART1 twice.
        rd_labels = ["SCRATCH0", "UART0", "SCRATCH1", "UART1"] * 2
        want = [PRELOAD[lab] for lab in rd_labels]
        r0, ar0 = len(sampler.r), len(sampler.ar)
        members = [
            self._member(f"RD{i}", SmcSysAxiOp.READ, self._addr(lab), 0, SAME_ID)
            for i, lab in enumerate(rd_labels)
        ]
        await self._run_group("same_id_reads", members)
        await self._catch_up(sampler, r0 + 8, 0, "S3")
        beats = sampler.r[r0:]
        assert len(beats) == 8 and len(sampler.ar) - ar0 == 8, (
            f"S3: {len(beats)} R beats and {len(sampler.ar) - ar0} AR beats, want 8 and 8"
        )
        assert all(i == SAME_ID for i in sampler.ar[ar0:]), f"S3: ARID {sampler.ar[ar0:]}"
        got = [self._lane_data(d, self._addr(lab)) for (_, d, _), lab in zip(beats, rd_labels)]
        assert [b[0] for b in beats] == [SAME_ID] * 8, f"S3: RID {[b[0] for b in beats]}"
        assert [b[2] for b in beats] == [OKAY] * 8, f"S3: RRESP {[b[2] for b in beats]}"
        assert sorted(got) == sorted(want), (
            f"S3: R data multiset {sorted(hex(x) for x in got)} != preload multiset "
            f"{sorted(hex(x) for x in want)}; last access {self._last_access}"
        )
        read_order_match = got == want
        self._mark_step("S3")
        self._emit_chk(
            "CHK-ORDER-READS-SAME-ID",
            f"8 reads under id=0x{SAME_ID:x} alternating {','.join(rd_labels[:4])} twice: "
            f"R data multiset equals the preload multiset, order_match={read_order_match}, "
            f"RID={[hex(b[0]) for b in beats]}, data={[hex(x) for x in got]}, "
            f"want={[hex(x) for x in want]}, RRESP all OKAY",
        )

        # S4: eight same-ID writes alternating the domains, interleaved with eight witness
        # writes into unit-aperture gaps, which answer DECERR.
        wr_labels = ["SCRATCH0", "UART0", "SCRATCH1", "UART1"] * 2
        wr_vals = [
            0xC0DE0000 + j if lab.startswith("SCRATCH") else 0x10 + j
            for j, lab in enumerate(wr_labels)
        ]
        assert len(set(wr_vals)) == 8
        dec_addrs = self._witness_addrs(8)
        members = []
        issued = []
        for j, (lab, v) in enumerate(zip(wr_labels, wr_vals)):
            members.append(self._member(f"WR{j}", SmcSysAxiOp.WRITE, self._addr(lab), v, SAME_ID))
            issued.append(OKAY)
            wit = self._member(
                f"WIT{j}",
                SmcSysAxiOp.WRITE,
                dec_addrs[j],
                0xBAD00000 + j,
                SAME_ID,
            )
            wit.expect_error = True
            wit.expected_resp = DECERR
            members.append(wit)
            issued.append(wit.expected_resp)
        n_members = len(members)
        b0, aw0 = len(sampler.b), len(sampler.aw)
        await self._run_group("same_id_writes", members)
        await self._catch_up(sampler, 0, b0 + n_members, "S4")
        bbeats = sampler.b[b0:]
        assert len(bbeats) == n_members and len(sampler.aw) - aw0 == n_members, (
            f"S4: {len(bbeats)} B beats and {len(sampler.aw) - aw0} AW beats, "
            f"want {n_members} and {n_members}"
        )
        assert all(i == SAME_ID for i in sampler.aw[aw0:]), f"S4: AWID {sampler.aw[aw0:]}"
        assert [b[0] for b in bbeats] == [SAME_ID] * n_members, f"S4: BID {[b[0] for b in bbeats]}"
        seen_resp = [b[1] for b in bbeats]
        assert sorted(seen_resp) == sorted(issued), (
            f"S4: BRESP multiset {sorted(seen_resp)} != issued {sorted(issued)}"
        )
        order_match = seen_resp == issued
        last = dict(zip(wr_labels, wr_vals))
        back = {}
        for lab, v in last.items():
            self._last_access = f"S4 readback {lab}"
            back[lab] = await self.csr_read(f"S4_RD_{lab}", self._addr(lab), expected=v)
            assert back[lab] == v, f"{self._last_access}: got 0x{back[lab]:x}, want 0x{v:x}"
        self._mark_step("S4")
        names = lambda seq: [RESP_NAME[r] for r in seq]  # noqa: E731
        self._emit_chk(
            "CHK-ORDER-WRITES-SAME-ID",
            f"{n_members} writes under id=0x{SAME_ID:x} (8 listed writes alternating domains, "
            f"8 gap witnesses): issued response pattern {names(issued)}, observed BRESP in "
            f"arrival order {names(seen_resp)}, order_match={order_match}, "
            f"BID={[hex(b[0]) for b in bbeats]}, multiset equal, "
            f"values={[hex(v) for v in wr_vals]}, "
            f"readback {{{', '.join(f'{k}=0x{v:x}' for k, v in back.items())}}}",
        )

        # S5: four reads under four IDs, two per domain.
        id_labels = list(zip(DIFF_IDS, ["SCRATCH0", "UART0", "SCRATCH1", "UART1"]))
        r1, ar1 = len(sampler.r), len(sampler.ar)
        members = [
            self._member(f"IDRD{i}", SmcSysAxiOp.READ, self._addr(lab), 0, axi_id)
            for i, (axi_id, lab) in enumerate(id_labels)
        ]
        await self._run_group("different_id_reads", members)
        await self._catch_up(sampler, r1 + 4, 0, "S5")
        dbeats = sampler.r[r1:]
        assert len(dbeats) == 4 and len(sampler.ar) - ar1 == 4, (
            f"S5: {len(dbeats)} R beats and {len(sampler.ar) - ar1} AR beats, want 4 and 4"
        )
        assert sorted(sampler.ar[ar1:]) == sorted(DIFF_IDS), f"S5: ARID {sampler.ar[ar1:]}"
        seen_ids = [b[0] for b in dbeats]
        assert sorted(seen_ids) == sorted(DIFF_IDS), f"S5: RID {seen_ids} not each of {DIFF_IDS}"
        by_id = {rid: (d, resp) for rid, d, resp in dbeats}
        parts = []
        for axi_id, lab in id_labels:
            data, resp = by_id[axi_id]
            data = self._lane_data(data, self._addr(lab))
            assert resp == OKAY, f"S5: id 0x{axi_id:x} RRESP {resp}"
            assert data == last[lab], (
                f"S5: id 0x{axi_id:x} {lab} data 0x{data:x} != 0x{last[lab]:x}; "
                f"arrival order {[hex(i) for i in seen_ids]}"
            )
            parts.append(f"0x{axi_id:x}->{lab}=0x{data:x}")
        self._mark_step("S5")
        self._emit_chk(
            "CHK-ORDER-DIFFERENT-IDS",
            f"4 reads under 4 ids, arrival order {[hex(i) for i in seen_ids]}, "
            f"each RID/data matches its request: {', '.join(parts)}, RRESP all OKAY",
        )
        sampler_task.cancel()

        self._bounded_waits.append(("sep_in_axi_access", f"{AXI_TIMEOUT_NS}ns", self._last_access))
        self._bounded_waits.append(
            (
                "sampler_catch_up",
                f"{SAMPLER_CATCHUP_CYCLES}smc_cycles",
                f"R={len(sampler.r)} B={len(sampler.b)}",
            )
        )
        waits = " ".join(f"{n}={b} last={s}" for n, b, s in self._bounded_waits)
        self._emit_chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(self._bounded_waits)} bounded waits: {waits}; expiry raises AssertionError",
        )
        self._assert_fence()

    def _assert_fence(self) -> None:
        ids = tuple(s for s, _ in self._steps)
        assert ids == STEP_ORDER, f"step ids {ids} != expected order {STEP_ORDER}"
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
