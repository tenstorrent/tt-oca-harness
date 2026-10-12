# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Concurrent and overlapping accesses to SMC_EFUSE_MAP over a distinct-word image.

Contract SMC_EFUSE_MAP_020, anchor smc_efuse_map_concurrency_test.
Scenarios EMAP-CONCURRENCY.S1, S2, S3, S5.
Sources: smc_efuse_map.rdl (LOCKS), port_table.adoc axil_smc_otp_jtag, architecture.adoc.

The SEP_IN master is the s_axi port through ``sys_axi_agent``. The JTAG master is the ej_axi
AXI-Lite master of ``axil_smc_otp_jtag_req_i``; it presents the full SMC-local address
(``SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR`` + 4 * word). A bus monitor samples both ports one
half-clock before each capturing edge and supplies the handshake times, the request order and
the response order.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, SimTimeoutError, with_timeout
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import (
    SmcSysAxiGroupItem,
    SmcSysAxiItem,
    SmcSysAxiOp,
    idle_axil_master_inputs,
)
from ocah_axi_vip import OcahAxiLiteMasterAgent

from ._one_shot import _OneShot
from .smc_addr_map import smc_addr, smc_efuse_map_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_image_pattern_test_seq import EFUSE_MAP_WORDS, EfuseImage

_MASK32 = 0xFFFF_FFFF
_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CHK_STEP = {
    "CHK-EMAP-CONC-SAME-READ": "S2",
    "CHK-EMAP-CONC-WR-RD": "S3",
    "CHK-EMAP-CONC-ALTERNATE": "S4",
    "CHK-EMAP-CONC-OUTSTANDING": "S5",
}
_SENSE_BOUND_CYCLES = 200_000
_JTAG_BOUND_NS = 400
_CLK_PS = 1250
_AXI_OKAY = 0
_PATTERN_X = 0xC3A5_1E7B
_ALTERNATIONS = 16
_OUTSTANDING = 8
_SPARE_WORDS = 8
_PORT_SIGNALS = {
    "s_axi": ("arvalid", "arready", "arid", "araddr", "rvalid", "rready", "rid", "rdata"),
    "ej_axi": ("arvalid", "arready", "araddr", "rvalid", "rready", "rdata"),
}
_SEP_WRITE_SIGNALS = ("awvalid", "awready", "awaddr")


def _resp_code(resp) -> int | None:
    code = getattr(resp, "resp", None)
    if code is None:
        return None
    codes = code if isinstance(code, (list, tuple)) else [code]
    return int(codes[0]) if codes else None


class smc_efuse_map_concurrency_test_seq(SmcCsrSeq):
    """Same-edge SEP_IN and JTAG reads, a racing write, alternating writes, outstanding reads."""

    def __init__(self, name: str = "smc_efuse_map_concurrency_test_seq") -> None:
        super().__init__(name)
        self.image: EfuseImage | None = None
        self.access_floor = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._bus: list[tuple[int, str, str, int, int]] = []
        self._ejm = None
        self._aw_cycles: list[tuple[int, int, int]] = []

    # --- fence ----------------------------------------------------------
    def _done(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))
        self._events.append(("step", step))

    def _chk(self, chk_id: str, fmt: str, *args) -> None:
        self._events.append(("chk", chk_id))
        cocotb.log.info("%s: " + fmt, chk_id, *args)

    # --- probes ---------------------------------------------------------
    @staticmethod
    def _sig(name: str) -> int:
        dut = cocotb.top
        assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        value = getattr(dut, name).value
        assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(value)

    def _sense_state(self) -> str:
        return (
            f"tb_fuse_sense_done={self._sig('tb_fuse_sense_done')},"
            f"tb_fuse_reset_n={self._sig('tb_fuse_reset_n')},"
            f"tb_rst_warm_smc_clk_n={self._sig('tb_rst_warm_smc_clk_n')}"
        )

    def _ej_state(self) -> str:
        return ",".join(
            f"ej_axi_{n}={self._sig('ej_axi_' + n)}"
            for n in ("arvalid", "arready", "rvalid", "rready", "awvalid", "awready", "bvalid")
        )

    def _s_state(self) -> str:
        return ",".join(
            f"s_axi_{n}={self._sig('s_axi_' + n)}"
            for n in ("arvalid", "arready", "rvalid", "rready", "awvalid", "awready", "bvalid")
        )

    async def _sense_wait(self, label: str) -> None:
        try:
            await self.wait_fuse_sense_done(_SENSE_BOUND_CYCLES)
        except AssertionError as exc:
            raise AssertionError(f"{label}: {exc}; {self._sense_state()}") from exc
        self._waits.append((label, f"{_SENSE_BOUND_CYCLES}smc_clk", self._sense_state()))

    # --- bus monitor ----------------------------------------------------
    async def _monitor(self) -> None:
        dut = cocotb.top
        for prefix, names in _PORT_SIGNALS.items():
            for n in names:
                assert hasattr(dut, f"{prefix}_{n}"), f"{prefix}_{n} is not a signal of the top"
        for n in _SEP_WRITE_SIGNALS:
            assert hasattr(dut, f"s_axi_{n}"), f"s_axi_{n} is not a signal of the top"
        while True:
            await FallingEdge(dut.clk_smc_i)
            now = int(get_sim_time("ps"))
            for prefix in _PORT_SIGNALS:
                if self._sig(f"{prefix}_arvalid") and self._sig(f"{prefix}_arready"):
                    rid = self._sig(f"{prefix}_arid") if prefix == "s_axi" else 0
                    self._bus.append((now, prefix, "AR", rid, self._sig(f"{prefix}_araddr")))
                if self._sig(f"{prefix}_rvalid") and self._sig(f"{prefix}_rready"):
                    rid = self._sig(f"{prefix}_rid") if prefix == "s_axi" else 0
                    self._bus.append((now, prefix, "R", rid, self._sig(f"{prefix}_rdata")))
            if self._sig("s_axi_awvalid") and self._sig("s_axi_awready"):
                self._bus.append((now, "s_axi", "AW", 0, self._sig("s_axi_awaddr")))

    async def _aw_sampler(self) -> None:
        dut = cocotb.top
        while True:
            await FallingEdge(dut.clk_smc_i)
            self._aw_cycles.append(
                (
                    int(get_sim_time("ps")),
                    self._sig("s_axi_awvalid"),
                    self._sig("s_axi_awready"),
                )
            )

    def _events_of(self, start: int, port: str, kind: str) -> list[tuple[int, int, int]]:
        return [(t, i, v) for t, p, k, i, v in self._bus[start:] if p == port and k == kind]

    # --- masters --------------------------------------------------------
    async def _sep_run(self, label: str, item) -> tuple[int, int]:
        bound = self.cfg.axi_timeout_ns
        start = int(get_sim_time("ps"))
        try:
            await with_timeout(
                _OneShot(item, f"{label}_os").start(self.env.sys_axi_agent.sequencer),
                bound,
                "ns",
            )
        except SimTimeoutError as exc:
            raise AssertionError(
                f"{label}: SEP_IN access did not complete within {bound} ns; {self._s_state()}"
            ) from exc
        end = int(get_sim_time("ps"))
        self._waits.append((label, f"{bound}ns", f"completed_at={end}ps {self._s_state()}"))
        return start, end

    async def _jtag_read(self, label: str, addr: int) -> tuple[int, int, int, int]:
        start = int(get_sim_time("ps"))
        event = self._ejm.init_read(address=addr, length=4)
        try:
            await with_timeout(event.wait(), _JTAG_BOUND_NS, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"{label}: JTAG read of 0x{addr:x} did not complete within {_JTAG_BOUND_NS} ns; "
                f"{self._ej_state()}"
            ) from exc
        end = int(get_sim_time("ps"))
        resp = event.data
        code = _resp_code(resp)
        assert code == _AXI_OKAY, f"{label}: JTAG read of 0x{addr:x} resp={code}"
        state = f"completed_at={end}ps {self._ej_state()}"
        self._waits.append((label, f"{_JTAG_BOUND_NS}ns", state))
        return start, end, int.from_bytes(resp.data, "little") & _MASK32, code

    def _sep_item(self, name: str, op: SmcSysAxiOp, addr: int, **kw) -> SmcSysAxiItem:
        item = SmcSysAxiItem(name)
        item.op = op
        item.addr = addr
        item.length = 4
        for key, value in kw.items():
            setattr(item, key, value)
        self.accesses += 1
        return item

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        image = self.image
        assert image is not None, "the testcase module sets the image before starting"
        dut = cocotb.top
        words = image.words
        base = smc_addr("SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR")

        def spare(k: int) -> int:
            return smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", k)

        spare0, spare1 = spare(0), spare(1)
        w0, w1 = (spare0 - base) // 4, (spare1 - base) // 4
        assert (w0, w1) == (32, 40), f"SPARE[0]/SPARE[1] first words are {w0}/{w1}"
        outstanding = [spare(k) for k in range(2, 2 + _SPARE_WORDS)]
        owords = [(a - base) // 4 for a in outstanding]
        locks_addr = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
        wlock = smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__SPARE0_WRITE_LOCK_bm")
        assert wlock == 1 << 8, f"SPARE0_WRITE_LOCK mask 0x{wlock:x}"

        assert len(words) == EFUSE_MAP_WORDS and words[0] == 0 and words[1] == 0, (
            f"LOCKS words 0x{words[0]:08x}/0x{words[1]:08x}"
        )
        data_words = words[2:]
        assert len(set(data_words)) == len(data_words), (
            f"image holds {len(set(data_words))} distinct words of {len(data_words)} "
            "non-LOCKS words"
        )
        assert image.locks == 0, f"image LOCKS 0x{image.locks:x}"
        assert len({words[w] for w in owords}) == _OUTSTANDING, "outstanding words not distinct"
        y_pat = [0x7E00_005A | (i << 8) for i in range(0, _ALTERNATIONS, 2)]
        z_pat = [0x2D00_003C | (k << 8) for k in range(_ALTERNATIONS // 2)]
        assert _PATTERN_X not in (words[w0], ~words[w0] & _MASK32, 0), "pattern X is not fresh"
        assert all(y != _PATTERN_X for y in y_pat), "a Y pattern equals X"
        assert len(set(z_pat)) == len(z_pat) and words[w1] not in z_pat, "Z patterns collide"
        assert all(0 not in (y, z) for y, z in zip(y_pat, z_pat)), "a pattern is zero"

        # S1
        await self._sense_wait("sense1")
        idle_axil_master_inputs(dut, "ej_axi")
        self._ejm = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "ej_axi",
            dut.clk_smc_i,
            dut.rst_primary_smc_clk_no,
            name="smc_ej_axil",
            reset_active_level=False,
        ).sequence
        monitor = cocotb.start_soon(self._monitor())
        self._done("S1")

        # S2
        mark = len(self._bus)
        await RisingEdge(dut.clk_smc_i)
        rd_item = self._sep_item("rd_S2_SEP", SmcSysAxiOp.READ, spare0, expected=words[w0])
        sep_task = cocotb.start_soon(self._sep_run("S2_SEP", rd_item))
        jtag_task = cocotb.start_soon(self._jtag_read("S2_JTAG", spare0))
        s_start, s_end = await sep_task
        j_start, j_end, j_val, j_code = await jtag_task
        assert rd_item.resp_code == _AXI_OKAY, f"S2: SEP_IN resp={rd_item.resp_code}"
        sep_val = rd_item.rdata & _MASK32
        assert sep_val == words[w0], f"S2: SEP_IN read 0x{sep_val:08x} != 0x{words[w0]:08x}"
        assert j_val == words[w0], f"S2: JTAG read 0x{j_val:08x} != 0x{words[w0]:08x}"
        sep_ar = self._events_of(mark, "s_axi", "AR")
        ej_ar = self._events_of(mark, "ej_axi", "AR")
        assert sep_ar and ej_ar, f"S2: AR handshakes SEP_IN {sep_ar} JTAG {ej_ar}"
        assert s_start == j_start, f"S2: starts differ, SEP_IN {s_start} ps, JTAG {j_start} ps"
        assert sep_ar[0][0] >= s_start and ej_ar[0][0] >= j_start, (
            f"S2: AR handshakes SEP_IN {sep_ar[0][0]} ps JTAG {ej_ar[0][0]} ps precede the start "
            f"{s_start} ps"
        )
        ar_diff = (ej_ar[0][0] - sep_ar[0][0]) // _CLK_PS
        self._done("S2")
        self._chk(
            "CHK-EMAP-CONC-SAME-READ",
            "SEP_IN and JTAG reads of SPARE[0] word 0 (map word %d, JTAG address 0x%x) started "
            "on one clk_smc_i edge at %d ps; SEP_IN complete %d ps value 0x%08x, JTAG complete "
            "%d ps value 0x%08x, both = image word 0x%08x; AR handshakes seen at SEP_IN %d ps, "
            "JTAG %d ps (JTAG minus SEP_IN %d clk_smc_i cycles)",
            w0,
            spare0,
            s_start,
            s_end,
            sep_val,
            j_end,
            j_val,
            words[w0],
            sep_ar[0][0],
            ej_ar[0][0],
            ar_diff,
        )

        # S3
        mark = len(self._bus)
        await RisingEdge(dut.clk_smc_i)
        wr_item = self._sep_item("wr_S3_SEP", SmcSysAxiOp.WRITE, spare0, wdata=_PATTERN_X)
        sep_task = cocotb.start_soon(self._sep_run("S3_SEP", wr_item))
        jtag_task = cocotb.start_soon(self._jtag_read("S3_JTAG", spare0))
        s_start, s_end = await sep_task
        j_start, j_end, j_val, j_code = await jtag_task
        assert s_start == j_start, f"S3: starts differ, SEP_IN {s_start} ps, JTAG {j_start} ps"
        sep_aw = self._events_of(mark, "s_axi", "AW")
        ej_ar = self._events_of(mark, "ej_axi", "AR")
        assert sep_aw and ej_ar, f"S3: handshakes SEP_IN AW {sep_aw} JTAG AR {ej_ar}"
        assert sep_aw[0][0] >= s_start and ej_ar[0][0] >= j_start, (
            f"S3: handshakes SEP_IN AW {sep_aw[0][0]} ps JTAG AR {ej_ar[0][0]} ps precede the "
            f"start {s_start} ps"
        )
        wr_diff = (ej_ar[0][0] - sep_aw[0][0]) // _CLK_PS
        assert wr_item.resp_code == _AXI_OKAY, f"S3: SEP_IN write resp={wr_item.resp_code}"
        assert j_val in (words[w0], _PATTERN_X), (
            f"S3: JTAG read 0x{j_val:08x} is neither image word 0x{words[w0]:08x} nor "
            f"X 0x{_PATTERN_X:08x}"
        )
        which = "image word" if j_val == words[w0] else "X"
        later = await self.csr_read("S3_LATER", spare0, expected=_PATTERN_X)
        assert later & _MASK32 == _PATTERN_X, f"S3: later SEP_IN read 0x{later:x}"
        self._done("S3")
        self._chk(
            "CHK-EMAP-CONC-WR-RD",
            "SEP_IN write of X=0x%08x and JTAG read of SPARE[0] word 0 started on one edge at "
            "%d ps; write complete %d ps resp=%d, JTAG complete %d ps value 0x%08x (%s, image "
            "word 0x%08x); later SEP_IN read 0x%08x = X; "
            "AW handshake at SEP_IN %d ps, AR handshake at JTAG %d ps (JTAG minus SEP_IN %d "
            "clk_smc_i cycles)",
            _PATTERN_X,
            s_start,
            s_end,
            wr_item.resp_code,
            j_end,
            j_val,
            which,
            words[w0],
            later & _MASK32,
            sep_aw[0][0],
            ej_ar[0][0],
            wr_diff,
        )

        # S4
        await self.csr_write("S4_LOCKS_SET", locks_addr, wlock, length=8)
        locks_lo = await self.csr_read("S4_LOCKS_LO", locks_addr, expected=wlock)
        locks_hi = await self.csr_read("S4_LOCKS_HI", locks_addr + 4, expected=0)
        assert (locks_lo, locks_hi) == (wlock, 0), f"S4: LOCKS 0x{locks_hi:x}/0x{locks_lo:x}"
        mark = len(self._bus)
        self._aw_cycles.clear()
        sampler = cocotb.start_soon(self._aw_sampler())
        members = []
        for i in range(_ALTERNATIONS):
            if i % 2 == 0:
                members.append(
                    self._sep_item(
                        f"wr_S4_LOCKED_{i}",
                        SmcSysAxiOp.WRITE,
                        spare0,
                        wdata=y_pat[i // 2],
                        allow_error=True,
                    )
                )
            else:
                members.append(
                    self._sep_item(
                        f"wr_S4_OPEN_{i}", SmcSysAxiOp.WRITE, spare1, wdata=z_pat[i // 2]
                    )
                )
        start4, end4 = await self._sep_run("S4_GROUP", SmcSysAxiGroupItem("S4_GROUP", members))
        aws = self._events_of(mark, "s_axi", "AW")
        assert [v for _t, _i, v in aws] == [spare0, spare1] * (_ALTERNATIONS // 2), (
            f"S4: AW handshake addresses {[hex(v) for _t, _i, v in aws]}"
        )
        sampler.kill()
        gaps = [b[0] - a[0] for a, b in zip(aws, aws[1:])]
        assert len(aws) == _ALTERNATIONS, f"S4: {len(aws)} AW handshakes"
        window = [c for c in self._aw_cycles if aws[0][0] <= c[0] <= aws[-1][0]]
        idle = backpressure = 0
        prev_valid, prev_ready = 1, 1
        for _t, valid, ready in window:
            if not valid and not (prev_valid and not prev_ready):
                idle += 1
            backpressure += int(bool(valid and not ready))
            prev_valid, prev_ready = valid, ready
        valid_cycles = sum(1 for c in window if c[1])
        locked_resp = sorted({m.resp_code for m in members[0::2]})
        assert all(m.resp_code == _AXI_OKAY for m in members[1::2]), (
            f"S4: unlocked write responses {[m.resp_code for m in members[1::2]]}"
        )
        held = await self.csr_read("S4_HELD", spare0, expected=_PATTERN_X)
        last = await self.csr_read("S4_LAST", spare1, expected=z_pat[-1])
        assert held & _MASK32 == _PATTERN_X, f"S4: SPARE[0] word 0 0x{held:x}"
        assert last & _MASK32 == z_pat[-1], f"S4: SPARE[1] word 0 0x{last:x}"
        self._done("S4")
        self._chk(
            "CHK-EMAP-CONC-ALTERNATE",
            "LOCKS 0x%08x%08x after setting SPARE0_WRITE_LOCK; %d writes alternating SPARE[0] "
            "word 0 (Y_i) and SPARE[1] word 0 (Z_k) issued as one outstanding group from %d to "
            "%d ps with AW handshake gaps %d..%d ps; AW sampler over %d cycles: "
            "awvalid-high %d, awready-low-with-awvalid %d, idle %d; locked write "
            "responses %s; SPARE[0] word 0 = 0x%08x = X, SPARE[1] word 0 = 0x%08x = Z_7",
            locks_hi,
            locks_lo,
            _ALTERNATIONS,
            start4,
            end4,
            min(gaps),
            max(gaps),
            len(window),
            valid_cycles,
            backpressure,
            idle,
            locked_resp,
            held & _MASK32,
            last & _MASK32,
        )

        # S5
        mark = len(self._bus)
        reads = [
            self._sep_item(f"rd_S5_{n}", SmcSysAxiOp.READ, a, expected=words[w])
            for n, (a, w) in enumerate(zip(outstanding, owords))
        ]
        start5, end5 = await self._sep_run("S5_GROUP", SmcSysAxiGroupItem("S5_GROUP", reads))
        ars = self._events_of(mark, "s_axi", "AR")
        rs = self._events_of(mark, "s_axi", "R")
        assert [v for _t, _i, v in ars] == outstanding, (
            f"S5: AR addresses {[hex(v) for _t, _i, v in ars]}"
        )
        assert [v & _MASK32 for _t, _i, v in rs] == [words[w] for w in owords], (
            f"S5: response data {[hex(v & _MASK32) for _t, _i, v in rs]}"
        )
        r_times = [t for t, _i, _v in rs]
        assert r_times == sorted(r_times), f"S5: response times not in order {r_times}"
        assert all(r.resp_code == _AXI_OKAY for r in reads), (
            f"S5: response codes {[r.resp_code for r in reads]}"
        )
        for n, r in enumerate(reads):
            assert r.rdata & _MASK32 == words[owords[n]], f"S5: item {n} rdata 0x{r.rdata:x}"
        timeline = sorted(
            [(t, 1) for t, _i, _v in ars] + [(t, -1) for t, _i, _v in rs],
            key=lambda e: (e[0], e[1]),
        )
        depth = peak = 0
        for _t, delta in timeline:
            depth += delta
            peak = max(peak, depth)
        assert peak > 1, f"S5: measured peak outstanding depth {peak}"
        self._done("S5")
        self._chk(
            "CHK-EMAP-CONC-OUTSTANDING",
            "%d SEP_IN reads of SPARE[2..9] word 0 (map words %s) issued as one group from %d to "
            "%d ps; AR handshakes %s ps; R handshakes %s ps in request order with data %s, each "
            "= its image word; measured peak outstanding depth %d",
            _OUTSTANDING,
            ",".join(str(w) for w in owords),
            start5,
            end5,
            ",".join(str(t) for t, _i, _v in ars),
            ",".join(str(t) for t in r_times),
            ",".join(f"0x{v & _MASK32:08x}" for _t, _i, v in rs),
            peak,
        )
        monitor.kill()
        self.access_floor = self.accesses

        # fence
        assert [s for s, _t in self._stamps] == list(_STEPS), (
            f"steps completed {[s for s, _t in self._stamps]}, expected {list(_STEPS)}"
        )
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed = [ident for kind, ident in self._events if kind == "chk"]
        assert printed == list(_CHK_STEP), f"checker lines printed {printed}"
        for index, (kind, ident) in enumerate(self._events):
            if kind == "chk":
                assert ("step", _CHK_STEP[ident]) in self._events[:index], (
                    f"{ident} printed before step {_CHK_STEP[ident]} completed"
                )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence SAME-READ < WR-RD < ALTERNATE < OUTSTANDING; checker "
            "lines %s; stamps %s ps",
            ", ".join(printed),
            ", ".join(f"{s}={t}" for s, t in self._stamps),
        )
        self._waits.append(
            (
                "sep_in_last_item",
                f"{self.cfg.axi_timeout_ns}ns",
                f"completed_at={end5}ps resp={reads[-1].resp_code} {self._s_state()}",
            )
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(
                f"{name}={bound}(fails with AssertionError on expiry) last={state}"
                for name, bound, state in self._waits
            ),
        )
