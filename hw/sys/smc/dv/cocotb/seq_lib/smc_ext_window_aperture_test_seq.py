# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_ext_window_aperture_test: external window pass-through and aperture.

Sources: hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/fabric.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import LOCAL_BASE_RESET, REGION_SIZE_RESET, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

FUSE_SENSE_MAX_CYCLES = 200_000
AXI_RESP_DECERR = 3
RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
WINDOW = smc_addr("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_BASE_ADDR")
SHIM = smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_EFUSE_SHIM_CTRL_BASE_ADDR")
WINDOW_OFFSET = 0x40_4000
SHIM_OFFSET = 0x40_0000
SIZE_4M = 0x40_0000
SIZE_2M = 0x20_0000
assert WINDOW - LOCAL_BASE_RESET == WINDOW_OFFSET, hex(WINDOW - LOCAL_BASE_RESET)
assert SHIM - LOCAL_BASE_RESET == SHIM_OFFSET, hex(SHIM - LOCAL_BASE_RESET)
assert REGION_SIZE_RESET > WINDOW_OFFSET > SIZE_4M > SIZE_2M

FULL_STROBE = 0xF
PARTIAL_STROBE = 0x3
WRITE_PATTERN = 0xA5C3_5A3C

FENCE = (
    "BRINGUP_SENSE_DONE",
    "REGION_RESET_READ",
    "EXT_READ_ONE_AR",
    "EXT_WRITE_ONE_AW_EACH",
    "SHIM_NO_EXTERNAL_REQUEST",
    "SHIM_BANK_ACTIVE",
    "DECERR_0x400000",
    "DECERR_0x200000",
    "RESTORED_REACHES_EXTERNAL",
    "INFLIGHT_OVERLAP_MEASURED",
)
CHK_AFTER = {
    "CHK-EXT-READ-REQ": "EXT_READ_ONE_AR",
    "CHK-EXT-WRITE-REQ": "EXT_WRITE_ONE_AW_EACH",
    "CHK-EXT-SHIM-ISOLATION": "SHIM_BANK_ACTIVE",
    "CHK-EXT-REGION-DECERR": "RESTORED_REACHES_EXTERNAL",
    "CHK-EXT-INFLIGHT": "INFLIGHT_OVERLAP_MEASURED",
}
CHK_ORDER = tuple(CHK_AFTER)


class _ProbeSampler:
    """Per-clk_smc cycle sampler of the external request probes and the SEP_IN handshakes."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.cycle = 0
        self.error: str | None = None
        self.counts = dict.fromkeys(
            ("ar_rise", "aw_rise", "ext_active", "bank_active", "bank_rise", "overlap"), 0
        )
        self.last_ar_addr: int | None = None
        self.last_aw_addr: int | None = None
        self.ar_addrs: list[int] = []
        self.aw_addrs: list[int] = []
        self.events: list[tuple[int, str]] = []
        self.outstanding = 0
        self._prev = {"ar": 0, "aw": 0, "bank": 0}
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        self._task.cancel()

    def snapshot(self) -> dict:
        return {
            **self.counts,
            "cycle": self.cycle,
            "n_ar": len(self.ar_addrs),
            "n_aw": len(self.aw_addrs),
            "n_ev": len(self.events),
        }

    def _bit(self, name: str) -> int | None:
        value = getattr(self.dut, name).value
        if not value.is_resolvable:
            self.error = self.error or f"{name} unresolved ({value}) at cycle {self.cycle}"
            return None
        return int(value)

    async def _run(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            self.cycle += 1
            ar = self._bit("tb_axil_external_arvalid")
            aw = self._bit("tb_axil_external_awvalid")
            act = self._bit("tb_axil_external_active")
            bank = self._bit("tb_axil_efuse_bank_active")
            if None in (ar, aw, act, bank):
                continue
            if ar and not self._prev["ar"]:
                addr = dut.tb_axil_external_araddr.value
                if not addr.is_resolvable:
                    self.error = self.error or f"araddr unresolved at cycle {self.cycle}"
                else:
                    self.counts["ar_rise"] += 1
                    self.last_ar_addr = int(addr)
                    self.ar_addrs.append(int(addr))
                    self.events.append((self.cycle, f"EXT_AR@0x{int(addr):x}"))
            if aw and not self._prev["aw"]:
                addr = dut.tb_axil_external_awaddr.value
                if not addr.is_resolvable:
                    self.error = self.error or f"awaddr unresolved at cycle {self.cycle}"
                else:
                    self.counts["aw_rise"] += 1
                    self.last_aw_addr = int(addr)
                    self.aw_addrs.append(int(addr))
                    self.events.append((self.cycle, f"EXT_AW@0x{int(addr):x}"))
            if bank and not self._prev["bank"]:
                self.counts["bank_rise"] += 1
            self.counts["ext_active"] += act
            self.counts["bank_active"] += bank
            self._prev = {"ar": ar, "aw": aw, "bank": bank}
            self._sep_in_handshakes()
            if self.outstanding >= 2:
                self.counts["overlap"] += 1

    def _sep_in_handshakes(self) -> None:
        dut = self.dut
        names = (
            ("s_axi_arvalid", "s_axi_arready", "SEP_AR", 1),
            ("s_axi_awvalid", "s_axi_awready", "SEP_AW", 1),
            ("s_axi_rvalid", "s_axi_rready", "SEP_R", -1),
            ("s_axi_bvalid", "s_axi_bready", "SEP_B", -1),
        )
        for valid, ready, label, delta in names:
            v, r = getattr(dut, valid).value, getattr(dut, ready).value
            if not (v.is_resolvable and r.is_resolvable):
                self.error = self.error or f"{valid}/{ready} unresolved at cycle {self.cycle}"
                continue
            if int(v) and int(r):
                if label == "SEP_R":
                    last = dut.s_axi_rlast.value
                    if not (last.is_resolvable and int(last)):
                        continue
                self.outstanding += delta
                self.events.append((self.cycle, label))


class smc_ext_window_aperture_test_seq(SmcCsrSeq):
    """SEP_IN accesses at the supplementary external window, the eFuse SHIM and REGION_SIZE."""

    def __init__(self, name: str = "smc_ext_window_aperture_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._last_access = "none"
        self.sampler: _ProbeSampler | None = None

    async def _stamp(self, term: str) -> None:
        await RisingEdge(cocotb.top.clk_smc_i)
        self._stamps.append((term, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    def _probes_clean(self) -> None:
        assert self.sampler.error is None, f"X/Z on a probe: {self.sampler.error}"

    async def _acc(
        self,
        op: SmcSysAxiOp,
        label: str,
        addr: int,
        data: int = 0,
        wstrb: int | None = None,
        expect_decerr: bool = False,
        expected: int | None = None,
    ) -> tuple[int, int, dict, dict]:
        """One SEP_IN access; returns ``(resp, rdata, before, after)`` sampler snapshots."""
        item = SmcSysAxiItem(f"{op.value}_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.wstrb = wstrb
        item.expected = expected
        item.allow_error = True
        if expect_decerr:
            item.expect_error = True
            item.expected_resp = AXI_RESP_DECERR
        before = self.sampler.snapshot()
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        await RisingEdge(cocotb.top.clk_smc_i)
        after = self.sampler.snapshot()
        resp = RESP_NAMES.get(item.resp_code, f"resp={item.resp_code}")
        shown = data if op is SmcSysAxiOp.WRITE else item.rdata
        self._last_access = f"{op.value} {label}@0x{addr:08x} data=0x{shown:x} resp={resp}"
        assert not item.timed_out, f"access timed out: {self._last_access}"
        assert item.resp_code is not None, f"no response: {self._last_access}"
        self._probes_clean()
        if expect_decerr:
            assert item.resp_code == AXI_RESP_DECERR, f"expected DECERR: {self._last_access}"
        return item.resp_code, item.rdata, before, after

    @staticmethod
    def _delta(before: dict, after: dict, key: str) -> int:
        return after[key] - before[key]

    async def _read_region_size(self, label: str) -> None:
        await self.csr_read(label, REGION_SIZE, expected=REGION_SIZE_RESET)

    async def _set_region_size(self, label: str, size: int) -> None:
        await self.csr_write(label, REGION_SIZE, size)
        await self.csr_read(f"{label}_RB", REGION_SIZE, expected=size)

    async def _restore_region_size(self, label: str) -> None:
        await self.csr_write(label, REGION_SIZE, REGION_SIZE_RESET)
        await self._read_region_size(f"{label}_RB")

    async def _read_leg(self) -> int:
        resp, rdata, before, after = await self._acc(SmcSysAxiOp.READ, "EXT_WINDOW", WINDOW)
        ars = self._delta(before, after, "ar_rise")
        assert ars == 1, f"external AR requests {ars}, expected exactly 1: {self._last_access}"
        assert self._delta(before, after, "aw_rise") == 0, "AW request during the read leg"
        ar_addr = self.sampler.last_ar_addr
        await self._stamp("EXT_READ_ONE_AR")
        self._chk(
            "CHK-EXT-READ-REQ",
            f"read @0x{WINDOW:08x} (BASE+0x{WINDOW_OFFSET:x}) produced {ars} external AR rising "
            f"edge, completed resp={RESP_NAMES.get(resp, resp)} rdata=0x{rdata:x}; "
            f"AR address printed 0x{ar_addr:x} against the expected window offset (window offset "
            f"0x{WINDOW_OFFSET:x}, full address 0x{WINDOW:x}); response and data are the "
            f"reference terminator's (owner value pending)",
        )
        return ar_addr

    async def _write_leg(self, ar_addr: int) -> None:
        rows = []
        for label, wstrb in (("FULL", FULL_STROBE), ("PARTIAL", PARTIAL_STROBE)):
            resp, _, before, after = await self._acc(
                SmcSysAxiOp.WRITE, f"EXT_WINDOW_{label}", WINDOW, WRITE_PATTERN, wstrb=wstrb
            )
            aws = self._delta(before, after, "aw_rise")
            assert aws == 1, (
                f"external AW requests {aws} for the {label} write: {self._last_access}"
            )
            assert self._delta(before, after, "ar_rise") == 0, "AR request during a write leg"
            aw_addr = self.sampler.last_aw_addr
            assert aw_addr == ar_addr, (
                f"{label} write AW address 0x{aw_addr:x} differs from the read leg AR address "
                f"0x{ar_addr:x}"
            )
            rows.append(
                f"{label} wstrb=0x{wstrb:x} aw_edges={aws} awaddr=0x{aw_addr:x} resp="
                f"{RESP_NAMES.get(resp, resp)}"
            )
        await self._stamp("EXT_WRITE_ONE_AW_EACH")
        self._chk(
            "CHK-EXT-WRITE-REQ",
            f"two writes @0x{WINDOW:08x} each produced one external AW rising edge with the AR "
            f"address of the read leg 0x{ar_addr:x}: "
            + "; ".join(rows)
            + "; write data and strobes are not exported (owner value pending)",
        )

    async def _shim_leg(self) -> None:
        resp_r, rdata, before_r, after_r = await self._acc(SmcSysAxiOp.READ, "SHIM", SHIM)
        resp_w, _, before_w, after_w = await self._acc(
            SmcSysAxiOp.WRITE, "SHIM", SHIM, rdata, wstrb=FULL_STROBE
        )
        ext_cycles = self._delta(before_r, after_w, "ext_active")
        assert ext_cycles == 0, (
            f"tb_axil_external_active high for {ext_cycles} cycles during the SHIM accesses"
        )
        await self._stamp("SHIM_NO_EXTERNAL_REQUEST")
        bank_rise = self._delta(before_r, after_w, "bank_rise")
        bank_cycles = self._delta(before_r, after_w, "bank_active")
        assert bank_rise >= 1, (
            f"tb_axil_efuse_bank_active never rose during the SHIM accesses ({self._last_access})"
        )
        await self._stamp("SHIM_BANK_ACTIVE")
        self._chk(
            "CHK-EXT-SHIM-ISOLATION",
            f"read and write @0x{SHIM:08x} (BASE+0x{SHIM_OFFSET:x}, EFUSE_SHIM_CTRL_WINDOW): "
            f"read resp={RESP_NAMES.get(resp_r, resp_r)} data=0x{rdata:x}, write resp="
            f"{RESP_NAMES.get(resp_w, resp_w)}; tb_axil_external_active high {ext_cycles} cycles; "
            f"tb_axil_efuse_bank_active rose {bank_rise} time(s) over {bank_cycles} cycles",
        )

    async def _aperture_leg(self, ar_addr: int) -> None:
        rows = []
        for size, term in ((SIZE_4M, "DECERR_0x400000"), (SIZE_2M, "DECERR_0x200000")):
            await self._set_region_size(f"REGION_SIZE_{size:#x}", size)
            _, _, b_r, a_r = await self._acc(
                SmcSysAxiOp.READ, f"WINDOW_{size:#x}", WINDOW, expect_decerr=True
            )
            _, _, b_w, a_w = await self._acc(
                SmcSysAxiOp.WRITE, f"WINDOW_{size:#x}", WINDOW, WRITE_PATTERN, expect_decerr=True
            )
            ext = self._delta(b_r, a_w, "ext_active")
            reqs = self._delta(b_r, a_w, "ar_rise") + self._delta(b_r, a_w, "aw_rise")
            assert ext == 0 and reqs == 0, (
                f"external request at REGION_SIZE {size:#x}: active cycles {ext}, edges {reqs}"
            )
            await self._stamp(term)
            rows.append(f"size {size:#x}: read and write DECERR, external_active {ext} cycles")
        await self._restore_region_size("REGION_SIZE_RESTORE")
        _, _, before, after = await self._acc(SmcSysAxiOp.READ, "WINDOW_RESTORED", WINDOW)
        ars = self._delta(before, after, "ar_rise")
        assert ars == 1, f"after restore external AR requests {ars}, expected exactly 1"
        assert self.sampler.last_ar_addr == ar_addr, (
            f"restored read AR address 0x{self.sampler.last_ar_addr:x} != 0x{ar_addr:x}"
        )
        await self._stamp("RESTORED_REACHES_EXTERNAL")
        self._chk(
            "CHK-EXT-REGION-DECERR",
            "; ".join(rows) + f"; restored REGION_SIZE 0x{REGION_SIZE_RESET:x} read drove "
            f"{ars} external AR edge at 0x{ar_addr:x}",
        )

    def _group_item(self, op: SmcSysAxiOp, label: str, addr: int, data: int = 0) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value}_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.allow_error = True
        return item

    async def _inflight_group(self, label: str, op: SmcSysAxiOp) -> str:
        window = self._group_item(op, f"WINDOW_{label}", WINDOW, WRITE_PATTERN)
        shrink = self._group_item(SmcSysAxiOp.WRITE, f"REGION_SIZE_{label}", REGION_SIZE, SIZE_2M)
        group = SmcSysAxiGroupItem(f"inflight_{label}", [window, shrink])
        before = self.sampler.snapshot()
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += 2
        await RisingEdge(cocotb.top.clk_smc_i)
        after = self.sampler.snapshot()
        for member in (window, shrink):
            assert not member.timed_out and member.resp_code is not None, (
                f"group member {member.get_name()} did not complete"
            )
            assert member.resp_code in (0, AXI_RESP_DECERR), (
                f"group member {member.get_name()} answered resp={member.resp_code}"
            )
        self._probes_clean()
        overlap = self._delta(before, after, "overlap")
        assert overlap > 0, f"{label}: no cycle had two SEP_IN accesses outstanding"
        events = self.sampler.events[before["n_ev"] :]
        cycles = " ".join(f"{name}@{cyc - before['cycle']}" for cyc, name in events)
        self._last_access = f"group {label} window resp={window.resp_code}"
        _, _, b_n, a_n = await self._acc(
            SmcSysAxiOp.READ, f"AFTER_GROUP_{label}", WINDOW, expect_decerr=True
        )
        next_ext = self._delta(b_n, a_n, "ext_active")
        next_reqs = self._delta(b_n, a_n, "ar_rise") + self._delta(b_n, a_n, "aw_rise")
        assert next_ext == 0 and next_reqs == 0, (
            f"{label}: window read after the REGION_SIZE shrink reached the external port: "
            f"active cycles {next_ext}, request edges {next_reqs}"
        )
        await self._restore_region_size(f"REGION_SIZE_RESTORE_{label}")
        return (
            f"{label}: window {op.value} resp={RESP_NAMES.get(window.resp_code)} and REGION_SIZE "
            f"write resp={RESP_NAMES.get(shrink.resp_code)} completed, both outstanding for "
            f"{overlap} cycle(s), handshake cycles [{cycles}], "
            f"next window read DECERR with {next_ext} external active cycles and "
            f"{next_reqs} request edges"
        )

    async def _inflight_leg(self) -> None:
        rows = [
            await self._inflight_group("READ_GROUP", SmcSysAxiOp.READ),
            await self._inflight_group("WRITE_GROUP", SmcSysAxiOp.WRITE),
        ]
        await self._stamp("INFLIGHT_OVERLAP_MEASURED")
        self._chk("CHK-EXT-INFLIGHT", "; ".join(rows))

    async def body(self) -> None:
        dut = cocotb.top
        for probe in (
            "tb_axil_external_active",
            "tb_axil_external_arvalid",
            "tb_axil_external_araddr",
            "tb_axil_external_awvalid",
            "tb_axil_external_awaddr",
            "tb_axil_efuse_bank_active",
        ):
            assert hasattr(dut, probe), f"{probe} not exported by tb_top"
        axi_bound = self.cfg.axi_timeout_ns

        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        self._waits.append(
            ("fuse_sense_done", f"{FUSE_SENSE_MAX_CYCLES}smc_clk", "tb_fuse_sense_done high")
        )
        self.sampler = _ProbeSampler(dut)
        try:
            self.env.axi_monitor.expected_decerr_addrs.update({WINDOW})
            await self._stamp("BRINGUP_SENSE_DONE")
            await self._read_region_size("REGION_SIZE_AT_RESET")
            await self._stamp("REGION_RESET_READ")

            ar_addr = await self._read_leg()
            await self._write_leg(ar_addr)
            await self._shim_leg()
            await self._aperture_leg(ar_addr)
            await self._inflight_leg()
            self._waits.append(("sep_in_access", f"{axi_bound}ns", self._last_access))
            self._waits.append(("sep_in_group", f"{axi_bound}ns", self._last_access))
            self._probes_clean()
        finally:
            self.sampler.stop()

        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError with the last "
            "access state",
            len(self._waits),
            " ".join(f"{n}={b} last={s}" for n, b, s in self._waits),
        )
        self.chk_seen.add("CHK-TIMEOUT-PATHS")
        self._fence()

    def _fence(self) -> None:
        terms = [t for t, _ in self._stamps]
        assert tuple(terms) == FENCE, f"fence terms {terms}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        order = [c for c, _ in self._chk_order]
        assert tuple(order) == CHK_ORDER, f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            assert n_stamps >= FENCE.index(CHK_AFTER[chk_id]) + 1, f"{chk_id} printed early"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(terms),
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
