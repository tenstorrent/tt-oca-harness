# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xbar_decerr_burst_response_test (SMU_AXI_FAB_017).

DV-CARD:          SMU_AXI_FAB_017   ANCHOR: smu_xbar_decerr_burst_response_test

An ``ext_in`` request that matches neither aperture returns ``DECERR``, which
the crossbar generates itself without reaching a subordinate
(``hw/sys/smu/doc/index.adoc``, "SMU aperture decode and routing"). The
response keeps the AXI4 shape of the request: ARLEN + 1 read beats with RLAST
on the last only (IHI 0022 A3.4.1), every write beat accepted and exactly one
write response after WLAST (IHI 0022 A3.3), and the issued ID echoed.

S1: the four aperture ports are sampled after the bench reset; the miss
    address M and the bit-55 alias A55 = SMC base + 2^55 must lie in neither
    aperture. SMC inbound filter entry 0 is opened over the whole space, which
    covers the SMC window, over JTAG2AXI for the S8 readback.
S2: a single-beat read and write at A55, then a read at the SMC base as the
    positive control.
S3: INCR reads at M of ARLEN 1, 7, 15 and 255.
S4: WRAP reads of ARLEN 1, 3, 7, 15 and FIXED reads of ARLEN 3, 15 at M.
S5: a single-beat write at M with its W beat handshaken before AW is driven.
S6: INCR writes at M of AWLEN 1, 7, 15 and 255 with WVALID continuous.
S7: the AWLEN 15 write again with a seeded WVALID gap of 0..8 cycles before
    each beat.
S8: SCRATCH_COLD written with Q through the SMC window, P written to its bit-55
    alias, SCRATCH_COLD read back.
S9: thirty-two single-beat reads at M with RREADY held low for 2000 cycles.

RDATA of a DECERR beat, the codes of later burst beats and the number of reads
the responder accepts while RREADY is held are recorded as OBS lines and not
compared (SF-003, SF-004, SF-011). Every handshake is sampled on the ext_in
pins each clk_smu_i cycle; the subordinate counters and the sep_in AR tap are
read from the bench top. No force or deposit.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from ocah_axi_vip import (
    PROT_NONSECURE,
    RESP_DECERR,
    RESP_OKAY,
    AxiTimingProfile,
    clear_profile,
    resp_name,
)
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_filter_helpers import (
    PASS_ALL_END,
    SCRATCH_COLD_ADDR,
    SMC_APERTURE_LOCAL_BASE,
    program_inbound0_window,
)
from seq_lib.smu_jtag_helpers import DTP_DEFAULT_IDCODE, make_smu_jtag_tap
from seq_lib.smu_tb_pins import smc_primary_reset

# Probe addresses stated by the contract.
MISS_ADDR = 0x0000_0000_8000_0000
BIT55 = 1 << 55
ADDR_SPACE = 1 << 56

AXI_BURST_FIXED = 0
AXI_BURST_INCR = 1
AXI_BURST_WRAP = 2
BURST_NAMES = {AXI_BURST_FIXED: "FIXED", AXI_BURST_INCR: "INCR", AXI_BURST_WRAP: "WRAP"}
SIZE_8B = 3
SIZE_4B = 2
BEAT_BYTES = 8

A55_ARID = 0x2D
A55_AWID = 0xD2
CTRL_ARID = 0x2E
INCR_READS = ((1, 0x01), (7, 0x7E), (15, 0x80), (255, 0xFF))
WRAP_FIXED_READS = (
    (AXI_BURST_WRAP, 1, 0x10),
    (AXI_BURST_WRAP, 3, 0x11),
    (AXI_BURST_WRAP, 7, 0x12),
    (AXI_BURST_WRAP, 15, 0x13),
    (AXI_BURST_FIXED, 3, 0x14),
    (AXI_BURST_FIXED, 15, 0x15),
)
W_FIRST_AWID = 0x5A
INCR_WRITES = ((1, 0x02), (7, 0x7D), (15, 0x81), (255, 0xFE))
GAP_AWID = 0x3F
GAP_AWLEN = 15
GAP_MAX = 8
SCRATCH_Q = 0x5C0D_A11A
SCRATCH_P = 0xA3F2_5EE5
Q_AWID = 0x51
P_AWID = 0x52
RB_ARID = 0x53
CAP_READS = 32
CAP_HOLD_CYCLES = 2000
CAP_DRAIN_BOUND = 4000
NO_SECOND_B_CYCLES = 2000

# Cycle bounds of the waits. A DECERR beat costs a few clk_smu_i cycles and the
# longest burst is 256 beats, so every bound is far above the expected count.
XFER_BOUND = 20_000
W_FIRST_BOUND = 200
RELEASE_MARGIN = 64
J2A_POLL_LIMIT = 128

COUNTS = (
    "sep_xbar_in_aw_count_o",
    "sep_xbar_in_ar_count_o",
    "smc_xbar_in_ar_count_o",
    "smc_xbar_in_aw_count_o",
    "smu_axi_out_write_count_o",
    "smu_axi_out_read_count_o",
)
PORTS = {
    "sep_xbar_global_base_o": "sep_base",
    "sep_xbar_region_size_o": "sep_size",
    "smc_global_base_o": "smc_base",
    "smc_region_size_o": "smc_size",
}
MARKERS = (
    "APERTURES_SAMPLED",
    "BIT55_DONE",
    "RD_BURST_DONE",
    "WRAP_FIXED_DONE",
    "WR_SINGLE_DONE",
    "WR_BURST_DONE",
    "SIDE_EFFECT_DONE",
    "ERR_CAPACITY_DONE",
)
BADCAB1E = 0xBADC_AB1E

_CHANNELS = {
    "aw": ("awvalid", "awready", ("awid", "awaddr", "awlen", "awsize", "awburst")),
    "w": ("wvalid", "wready", ("wlast",)),
    "b": ("bvalid", "bready", ("bid", "bresp")),
    "ar": ("arvalid", "arready", ("arid", "araddr", "arlen", "arsize", "arburst")),
    "r": ("rvalid", "rready", ("rid", "rresp", "rlast", "rdata")),
}


def _val(signal) -> int | None:
    """The integer value of a handle, or None when it is X or Z."""
    value = signal.value
    if hasattr(value, "is_resolvable") and not value.is_resolvable:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _rn(code: int | None) -> str:
    return "X" if code is None else resp_name(code)


def _hx(value: int | None) -> str:
    return "X" if value is None else f"0x{value:x}"


def _kv(fields: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in fields.items())


def _inside(addr: int, base: int, size: int) -> bool:
    """[base, base + size) in unbounded integers, so a 57-bit sum does not wrap."""
    return size != 0 and base <= addr < base + size


def _ranges(cycles: list[int]) -> str:
    """Consecutive cycle numbers folded into a-b runs."""
    out = []
    for cyc in cycles:
        if out and cyc == out[-1][1] + 1:
            out[-1][1] = cyc
        else:
            out.append([cyc, cyc])
    return ",".join(f"{a}" if a == b else f"{a}-{b}" for a, b in out) or "-"


class _ExtInMonitor:
    """Every ext_in handshake, sampled on the pins at each clk_smu_i edge.

    Each event carries the cycle number of the edge that took it. A trace of
    the valid/ready levels per cycle is kept while ``trace`` is a list.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.cyc = 0
        self.events: dict[str, list[dict]] = {ch: [] for ch in _CHANNELS}
        self.last_hs: dict[str, dict] = {}
        self.levels: dict[str, tuple] = {}
        self.trace: list[tuple[int, dict]] | None = None
        self.reset = smc_primary_reset(dut)
        self._pins = {
            ch: (
                getattr(dut, f"ext_in_{valid}"),
                getattr(dut, f"ext_in_{ready}"),
                {f: getattr(dut, f"ext_in_{f}") for f in fields},
            )
            for ch, (valid, ready, fields) in _CHANNELS.items()
        }
        self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        clk = self.dut.clk_smu_i
        while True:
            await RisingEdge(clk)
            self.cyc += 1
            levels = {}
            for ch, (valid, ready, fields) in self._pins.items():
                v, r = _val(valid), _val(ready)
                levels[ch] = (v, r)
                if v == 1 and r == 1:
                    event = {"cyc": self.cyc}
                    event.update({f: _val(h) for f, h in fields.items()})
                    self.events[ch].append(event)
                    self.last_hs[ch] = event
            self.levels = levels
            if self.trace is not None:
                self.trace.append((self.cyc, levels))

    def mark(self) -> dict[str, int]:
        return {ch: len(evs) for ch, evs in self.events.items()}

    def since(self, mark: dict[str, int], ch: str, until: dict[str, int] | None = None) -> list:
        end = None if until is None else until[ch]
        return self.events[ch][mark[ch] : end]

    def state(self) -> str:
        return (
            f"cycle={self.cyc} valid_ready={self.levels} last_handshake={self.last_hs} "
            f"rst_primary_smc_clk_no={_hx(_val(self.reset))}"
        )


class smu_xbar_decerr_burst_response_test_seq:
    """Multi-beat ext_in decode-error responses from the SMU crossbar."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.seed = test.random_seed()
        self.rng = random.Random(self.seed ^ 0x0AF0_0017)
        self.mon: _ExtInMonitor | None = None
        self.master = None
        self.ports: dict[str, int] = {}
        self.a55 = 0
        self.sites: list[dict] = []
        self.markers: list[tuple[str, int]] = []
        self.steps: dict[str, bool] = {}
        self.burst_captures: list[tuple[str, int, int]] = []

    # ------------------------------------------------------------------ helpers

    def _info(self, msg: str) -> None:
        self.log.info("INFO-%s", msg)

    def _mark(self, name: str) -> None:
        self.markers.append((name, self.mon.cyc))
        self.log.info("CTRL-%s: cycle=%d", name, self.mon.cyc)

    def _check(self, chk: str, observed: dict, expected: dict, desc: str) -> None:
        self._info(f"{chk} {desc}")
        self.sb.expect_eq(chk, _kv(observed), _kv(expected), evidence=chk)

    def _counts(self) -> dict[str, int | None]:
        return {name: _val(getattr(self.dut, name)) for name in COUNTS}

    @staticmethod
    def _delta(before: dict, after: dict) -> dict[str, int | str]:
        return {
            name: (
                "X" if before[name] is None or after[name] is None else after[name] - before[name]
            )
            for name in COUNTS
        }

    def _site(self, site: str, bound: int, unit: str, used, status: str) -> None:
        self.sites.append(
            {"site": site, "bound": bound, "unit": unit, "used": used, "status": status}
        )
        self._info(
            f"TIMEOUT-PATH site={site} bound={bound} {unit} used={used} status={status} "
            "on_expiry=fail"
        )

    async def _until(self, site: str, cond, bound: int, *, fatal: bool = True) -> int | None:
        """Wait, one clk_smu_i edge at a time, for ``cond``; ``bound`` edges at most."""
        if cond():
            self._site(site, bound, "cycles", 0, "ok")
            return 0
        for used in range(1, bound + 1):
            await RisingEdge(self.dut.clk_smu_i)
            if cond():
                self._site(site, bound, "cycles", used, "ok")
                return used
        self._site(site, bound, "cycles", bound, "EXPIRED")
        self._info(f"TIMEOUT-STATE site={site} {self.mon.state()}")
        if fatal:
            raise AssertionError(f"TIMEOUT {site}: bound={bound} cycles; {self.mon.state()}")
        return None

    async def _xfer(self, site: str, *, write: bool, addr: int, payload, size: int, **attrs):
        if write:
            event = self.master.init_write(addr, payload, size=size, prot=PROT_NONSECURE, **attrs)
        else:
            event = self.master.init_read(addr, payload, size=size, prot=PROT_NONSECURE, **attrs)
        await self._until(site, event.is_set, XFER_BOUND)
        return event.data

    # ------------------------------------------------------------------ steps

    async def _s1_setup(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        self.mon = _ExtInMonitor(dut)
        await RisingEdge(dut.clk_smu_i)
        sb.expect_eq("S1 SEP=1 build with the crossbar elaborated", _val(dut.sep_enabled_o), 1)
        self.ports = {short: _val(getattr(dut, name)) for name, short in PORTS.items()}
        self._info(f"APERTURES {_kv({k: _hx(v) for k, v in self.ports.items()})}")
        if any(v is None for v in self.ports.values()):
            raise AssertionError(f"S1 X/Z on an aperture port: {self.ports}")
        sep = (self.ports["sep_base"], self.ports["sep_size"])
        smc = (self.ports["smc_base"], self.ports["smc_size"])
        self.a55 = self.ports["smc_base"] + BIT55
        scratch_alias = self._smc_window(SCRATCH_COLD_ADDR) + BIT55
        probes = {"M": MISS_ADDR, "A55": self.a55, "SCRATCH_COLD_A55": scratch_alias}
        placement = {
            name: (addr < ADDR_SPACE, _inside(addr, *sep), _inside(addr, *smc))
            for name, addr in probes.items()
        }
        self._info(
            "PROBES "
            + " ".join(f"{n}=0x{a:014x}" for n, a in probes.items())
            + f" (in_space, in_sep, in_smc)={placement}"
        )
        sb.expect_eq(
            "S1 M, A55 and the SCRATCH_COLD bit-55 alias lie in the address space and in "
            "neither aperture",
            placement,
            {name: (True, False, False) for name in probes},
        )
        self._mark("APERTURES_SAMPLED")

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        self._site("S1_jtag_idcode", 1, "scan", "done", "ok")
        sb.expect_eq("S1 DTP IDCODE", idcode, DTP_DEFAULT_IDCODE)
        sb.expect_eq(
            "S1 SMC JTAG2AXI open",
            _val(dut.tb_smc_jtag2axi_security_disable),
            0,
        )
        await program_inbound0_window(jtag, 0, PASS_ALL_END, scoreboard=sb, tag="S1_INBOUND0")
        for name in ("START", "END", "CONFIG"):
            self._site(f"S1_j2a_inbound0_{name.lower()}", J2A_POLL_LIMIT, "polls", "done", "ok")
        self._info(f"S1 SMC inbound filter entry 0 open over [0x0, 0x{PASS_ALL_END:x}]")

        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        self._info(f"S1 counters {self._counts()}")
        self.steps["S1"] = True

    def _smc_window(self, local: int) -> int:
        return self.ports["smc_base"] + (local - SMC_APERTURE_LOCAL_BASE)

    async def _s2_bit55(self) -> None:
        mon = self.mon
        c0 = self._counts()
        mk = mon.mark()
        await self._xfer(
            "S2_a55_read",
            write=False,
            addr=self.a55,
            payload=BEAT_BYTES,
            size=SIZE_8B,
            arid=A55_ARID,
        )
        r = mon.since(mk, "r")
        rdata = r[0]["rdata"] if r else None
        if rdata is None:
            self.log.info("OBS-DECERR-RDATA-SINGLE: arid=0x%x beats=%d rdata=X", A55_ARID, len(r))
        else:
            lo, hi = rdata & 0xFFFF_FFFF, rdata >> 32
            self.log.info(
                "OBS-DECERR-RDATA-SINGLE: arid=0x%x beats=%d rdata=0x%016x lo_is_badcab1e=%s "
                "hi_is_badcab1e=%s",
                A55_ARID,
                len(r),
                rdata,
                lo == BADCAB1E,
                hi == BADCAB1E,
            )
        obs_printed = True
        c1 = self._counts()
        mk = mon.mark()
        await self._xfer(
            "S2_a55_write",
            write=True,
            addr=self.a55,
            payload=bytes(range(0xA0, 0xA8)),
            size=SIZE_8B,
            awid=A55_AWID,
        )
        b = mon.since(mk, "b")
        c2 = self._counts()
        mk = mon.mark()
        ctrl = await self._xfer(
            "S2_smc_base_read",
            write=False,
            addr=self.ports["smc_base"],
            payload=4,
            size=SIZE_4B,
            arid=CTRL_ARID,
        )
        ctrl_r = mon.since(mk, "r")
        c3 = self._counts()
        self._info(
            f"S2 positive control smc_base=0x{self.ports['smc_base']:x} "
            f"rresp={_rn(ctrl_r[0]['rresp']) if ctrl_r else 'none'} vip_resp={getattr(ctrl, 'resp', None)} "
            f"counts {c2}->{c3}"
        )
        r0 = r[0] if r else {}
        b0 = b[0] if b else {}
        d01, d12, d23 = self._delta(c0, c1), self._delta(c1, c2), self._delta(c2, c3)
        self._check(
            "CHK-BIT55-MISS",
            {
                "rd_beats": len(r),
                "rd_rresp": _rn(r0.get("rresp")),
                "rd_rlast": _hx(r0.get("rlast")),
                "rd_rid": _hx(r0.get("rid")),
                "wr_b": len(b),
                "wr_bresp": _rn(b0.get("bresp")),
                "wr_bid": _hx(b0.get("bid")),
                "smc_ar_delta": (d01["smc_xbar_in_ar_count_o"], d12["smc_xbar_in_ar_count_o"]),
                "smc_aw_delta": (d01["smc_xbar_in_aw_count_o"], d12["smc_xbar_in_aw_count_o"]),
                "ctrl_smc_ar_delta": d23["smc_xbar_in_ar_count_o"],
            },
            {
                "rd_beats": 1,
                "rd_rresp": _rn(RESP_DECERR),
                "rd_rlast": "0x1",
                "rd_rid": _hx(A55_ARID),
                "wr_b": 1,
                "wr_bresp": _rn(RESP_DECERR),
                "wr_bid": _hx(A55_AWID),
                "smc_ar_delta": (0, 0),
                "smc_aw_delta": (0, 0),
                "ctrl_smc_ar_delta": 1,
            },
            f"A55=0x{self.a55:014x}: crossbar DECERR with the ID echoed, nothing counted at "
            "smc_in, the SMC-base read counted once",
        )
        self._check(
            "CHK-RDATA-SINGLE-OBS",
            {"beats_captured": len(r), "obs_printed": obs_printed, "completed": True},
            {"beats_captured": 1, "obs_printed": True, "completed": True},
            "the A55 DECERR beat was captured and its RDATA logged without a verdict",
        )
        self._mark("BIT55_DONE")
        self.steps["S2"] = True

    def _log_burst_beats(self, tag: str, arid: int, beats: list[dict]) -> int:
        """One OBS-DECERR-RDATA-BURST line per beat; returns the lines printed."""
        printed = 0
        for idx, beat in enumerate(beats):
            self.log.info(
                "OBS-DECERR-RDATA-BURST: step=%s arid=0x%x beat=%d rdata=%s",
                tag,
                arid,
                idx,
                "X" if beat["rdata"] is None else f"0x{beat['rdata']:016x}",
            )
            printed += 1
        return printed

    @staticmethod
    def _later_codes(beats: list[dict]) -> str:
        counts: dict[str, int] = {}
        for beat in beats[1:]:
            name = _rn(beat["rresp"])
            counts[name] = counts.get(name, 0) + 1
        return ",".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "-"

    def _burst_shape(self, ars: list[dict], beats: list[dict], arid: int, arlen: int, burst: int):
        ar0 = ars[0] if ars else {}
        return {
            "ar_hs": len(ars),
            "ar": (_hx(ar0.get("arid")), ar0.get("arlen"), ar0.get("arburst"), ar0.get("arsize")),
            "beats": len(beats),
            "rlast_at": [i for i, b in enumerate(beats) if b["rlast"] != 0],
            "rid_mismatch": sum(1 for b in beats if b["rid"] != arid),
            "first_rresp": _rn(beats[0]["rresp"]) if beats else "none",
            "x_beats": sum(1 for b in beats if None in (b["rresp"], b["rlast"], b["rid"])),
        }, {
            "ar_hs": 1,
            "ar": (_hx(arid), arlen, burst, SIZE_8B),
            "beats": arlen + 1,
            "rlast_at": [arlen],
            "rid_mismatch": 0,
            "first_rresp": _rn(RESP_DECERR),
            "x_beats": 0,
        }

    async def _s3_incr_reads(self) -> None:
        mon = self.mon
        c0 = self._counts()
        for arlen, arid in INCR_READS:
            mk = mon.mark()
            await self._xfer(
                f"S3_incr_read_len{arlen}",
                write=False,
                addr=MISS_ADDR,
                payload=(arlen + 1) * BEAT_BYTES,
                size=SIZE_8B,
                burst=AXI_BURST_INCR,
                arid=arid,
            )
            beats, ars = mon.since(mk, "r"), mon.since(mk, "ar")
            printed = self._log_burst_beats("S3", arid, beats)
            self.burst_captures.append((f"S3/0x{arid:x}", len(beats), printed))
            self.log.info(
                "OBS-RD-BURST-RESP: arid=0x%x arlen=%d later_beat_codes=%s",
                arid,
                arlen,
                self._later_codes(beats),
            )
            self._info(f"S3 arid=0x{arid:x} r_hs_cycles={_ranges([b['cyc'] for b in beats])}")
            observed, expected = self._burst_shape(ars, beats, arid, arlen, AXI_BURST_INCR)
            self._check(
                "CHK-RD-BURST",
                {"arid": _hx(arid), **observed},
                {"arid": _hx(arid), **expected},
                f"INCR ARLEN {arlen} at M: ARLEN+1 beats, RLAST on the last only, RID echoed, "
                "first beat DECERR",
            )
        c1 = self._counts()
        self._check(
            "CHK-RD-BURST",
            {"counter_deltas": self._delta(c0, c1)},
            {"counter_deltas": {name: 0 for name in COUNTS}},
            "no subordinate counter and no sep_in AR handshake across the S3 reads",
        )
        self._mark("RD_BURST_DONE")
        self.steps["S3"] = True

    async def _s4_wrap_fixed_reads(self) -> None:
        mon = self.mon
        for burst, arlen, arid in WRAP_FIXED_READS:
            mk = mon.mark()
            await self._xfer(
                f"S4_{BURST_NAMES[burst].lower()}_read_len{arlen}",
                write=False,
                addr=MISS_ADDR,
                payload=(arlen + 1) * BEAT_BYTES,
                size=SIZE_8B,
                burst=burst,
                arid=arid,
            )
            beats, ars = mon.since(mk, "r"), mon.since(mk, "ar")
            printed = self._log_burst_beats("S4", arid, beats)
            self.burst_captures.append((f"S4/0x{arid:x}", len(beats), printed))
            self.log.info(
                "OBS-RD-WRAP-FIXED-RESP: arid=0x%x burst=%s arlen=%d later_beat_codes=%s",
                arid,
                BURST_NAMES[burst],
                arlen,
                self._later_codes(beats),
            )
            observed, expected = self._burst_shape(ars, beats, arid, arlen, burst)
            self._check(
                "CHK-RD-WRAP-FIXED",
                {"arid": _hx(arid), "burst": BURST_NAMES[burst], **observed},
                {"arid": _hx(arid), "burst": BURST_NAMES[burst], **expected},
                f"{BURST_NAMES[burst]} ARLEN {arlen} at M: ARLEN+1 beats, RLAST on the last only, "
                "RID echoed, first beat DECERR",
            )
        mismatched = [tag for tag, beats, printed in self.burst_captures if beats != printed]
        self._check(
            "CHK-RDATA-BURST-OBS",
            {
                "bursts": len(self.burst_captures),
                "beats": sum(b for _, b, _ in self.burst_captures),
                "captures": sum(p for _, _, p in self.burst_captures),
                "mismatched": mismatched,
            },
            {
                "bursts": len(INCR_READS) + len(WRAP_FIXED_READS),
                "beats": sum(n + 1 for n, _ in INCR_READS)
                + sum(n + 1 for _, n, _ in WRAP_FIXED_READS),
                "captures": sum(n + 1 for n, _ in INCR_READS)
                + sum(n + 1 for _, n, _ in WRAP_FIXED_READS),
                "mismatched": [],
            },
            "one RDATA capture and one OBS line per counted DECERR beat of S3 and S4",
        )
        self._mark("WRAP_FIXED_DONE")
        self.steps["S4"] = True

    async def _s5_w_first(self) -> None:
        mon = self.mon
        drv = self.master.driver
        clear_profile(drv)
        aw_chan = drv.channels["aw_delay"]
        aw_chan.pause = True
        mk = mon.mark()
        event = self.master.init_write(
            MISS_ADDR,
            bytes(range(0x50, 0x58)),
            size=SIZE_8B,
            prot=PROT_NONSECURE,
            awid=W_FIRST_AWID,
        )
        await self._until(
            "S5_w_before_aw", lambda: len(mon.events["w"]) > mk["w"], W_FIRST_BOUND, fatal=False
        )
        aw_chan.pause = False
        await self._until("S5_write_done", event.is_set, XFER_BOUND)
        # The contract's quiet window: no second B may follow within it.
        await ClockCycles(self.dut.clk_smu_i, NO_SECOND_B_CYCLES)
        self._info(f"S5 observation window {NO_SECOND_B_CYCLES} cycles after the B")
        w, aw, b = mon.since(mk, "w"), mon.since(mk, "aw"), mon.since(mk, "b")
        w_cyc = w[0]["cyc"] if w else None
        aw_cyc = aw[0]["cyc"] if aw else None
        b_after = [x for x in b if aw_cyc is not None and x["cyc"] > aw_cyc]
        self._info(
            f"S5 w_hs_cycle={w_cyc} aw_hs_cycle={aw_cyc} b_hs_cycles={[x['cyc'] for x in b]}"
        )
        self._check(
            "CHK-WR-W-FIRST",
            {
                "w_hs": len(w),
                "aw_hs": len(aw),
                "w_before_aw": w_cyc is not None and aw_cyc is not None and w_cyc < aw_cyc,
                "b_total": len(b),
                "b_after_aw": len(b_after),
                "bresp": _rn(b_after[0]["bresp"]) if b_after else "none",
                "bid": _hx(b_after[0]["bid"]) if b_after else "none",
            },
            {
                "w_hs": 1,
                "aw_hs": 1,
                "w_before_aw": True,
                "b_total": 1,
                "b_after_aw": 1,
                "bresp": _rn(RESP_DECERR),
                "bid": _hx(W_FIRST_AWID),
            },
            "the W beat is accepted before AW and exactly one DECERR B follows the AW",
        )
        self._mark("WR_SINGLE_DONE")
        self.steps["S5"] = True

    def _write_shape(self, aw: list, w: list, b: list, awid: int, awlen: int) -> tuple[dict, dict]:
        wlast_cyc = w[-1]["cyc"] if w else None
        aw0 = aw[0] if aw else {}
        return {
            "aw_hs": len(aw),
            "aw": (_hx(aw0.get("awid")), aw0.get("awlen"), aw0.get("awburst"), aw0.get("awsize")),
            "w_hs": len(w),
            "wlast_at": [i for i, x in enumerate(w) if x["wlast"] != 0],
            "b_hs": len(b),
            "b_before_wlast": sum(1 for x in b if wlast_cyc is None or x["cyc"] <= wlast_cyc),
            "bresp": [_rn(x["bresp"]) for x in b],
            "bid": [_hx(x["bid"]) for x in b],
        }, {
            "aw_hs": 1,
            "aw": (_hx(awid), awlen, AXI_BURST_INCR, SIZE_8B),
            "w_hs": awlen + 1,
            "wlast_at": [awlen],
            "b_hs": 1,
            "b_before_wlast": 0,
            "bresp": [_rn(RESP_DECERR)],
            "bid": [_hx(awid)],
        }

    async def _s6_incr_writes(self) -> None:
        mon = self.mon
        clear_profile(self.master.driver)
        c0 = self._counts()
        marks = []
        for awlen, awid in INCR_WRITES:
            marks.append(mon.mark())
            payload = bytes((awid + i) & 0xFF for i in range((awlen + 1) * BEAT_BYTES))
            await self._xfer(
                f"S6_incr_write_len{awlen}",
                write=True,
                addr=MISS_ADDR,
                payload=payload,
                size=SIZE_8B,
                burst=AXI_BURST_INCR,
                awid=awid,
            )
        marks.append(mon.mark())
        c1 = self._counts()
        for idx, (awlen, awid) in enumerate(INCR_WRITES):
            mk, end = marks[idx], marks[idx + 1]
            aw, w, b = mon.since(mk, "aw", end), mon.since(mk, "w", end), mon.since(mk, "b", end)
            self._info(
                f"S6 awid=0x{awid:x} awlen={awlen} w_hs_cycles={_ranges([x['cyc'] for x in w])} "
                f"b_hs_cycles={[x['cyc'] for x in b]}"
            )
            observed, expected = self._write_shape(aw, w, b, awid, awlen)
            self._check(
                "CHK-WR-BURST",
                {"awid": _hx(awid), **observed},
                {"awid": _hx(awid), **expected},
                f"INCR AWLEN {awlen} at M: every W beat accepted, one DECERR B after WLAST",
            )
        self._check(
            "CHK-WR-BURST",
            {"counter_deltas": self._delta(c0, c1)},
            {"counter_deltas": {name: 0 for name in COUNTS}},
            "no subordinate counter and no sep_in AR handshake across the S6 writes",
        )
        self.steps["S6"] = True

    async def _w_gap_driver(self, w_chan, gaps: list[int], bound: int) -> bool:
        """Hold WVALID low for gaps[k] cycles before beat k.

        Decided at each falling edge for the next rising edge, where the W
        source samples ``pause``: gaps[0] counts from the AW handshake and
        gaps[k] from the handshake of beat k - 1.
        """
        dut = self.dut
        k = 0
        countdown = None
        for used in range(1, bound + 1):
            await FallingEdge(dut.clk_smu_i)
            if countdown is None:
                if k == 0:
                    event = _val(dut.ext_in_awvalid) == 1 and _val(dut.ext_in_awready) == 1
                else:
                    event = _val(dut.ext_in_wvalid) == 1 and _val(dut.ext_in_wready) == 1
                if not event:
                    continue
                countdown = gaps[k]
                w_chan.pause = countdown > 0
            else:
                countdown -= 1
            if countdown == 0:
                w_chan.pause = False
                k += 1
                countdown = None
                if k == len(gaps):
                    self._site("S7_w_gap_driver", bound, "cycles", used, "ok")
                    return True
        self._site("S7_w_gap_driver", bound, "cycles", bound, "EXPIRED")
        self._info(f"TIMEOUT-STATE site=S7_w_gap_driver released={k} {self.mon.state()}")
        w_chan.pause = False
        return False

    async def _s7_w_gaps(self) -> None:
        mon = self.mon
        dut = self.dut
        beats = GAP_AWLEN + 1
        gaps = [self.rng.randint(0, GAP_MAX) for _ in range(beats)]
        self._info(f"SEED: RANDOM_SEED={self.seed} S7 drawn wvalid_gaps={gaps}")
        drv = self.master.driver
        clear_profile(drv)
        w_chan = drv.channels["w_delay"]
        w_chan.pause = True
        mon.trace = []
        mk = mon.mark()
        bound = beats * (GAP_MAX + 1) + XFER_BOUND
        driver = cocotb.start_soon(self._w_gap_driver(w_chan, gaps, bound))
        payload = bytes((0x30 + i) & 0xFF for i in range(beats * BEAT_BYTES))
        event = self.master.init_write(
            MISS_ADDR, payload, size=SIZE_8B, prot=PROT_NONSECURE, awid=GAP_AWID
        )
        await self._until("S7_write_done", event.is_set, bound)
        released = await driver
        await RisingEdge(dut.clk_smu_i)
        trace, mon.trace = mon.trace, None
        aw, w, b = mon.since(mk, "aw"), mon.since(mk, "w"), mon.since(mk, "b")
        low = {cyc for cyc, levels in trace if levels["w"][0] != 1}
        edges = ([aw[0]["cyc"]] if aw else [None]) + [x["cyc"] for x in w]
        measured = [
            None
            if edges[i] is None
            else sum(1 for cyc in range(edges[i] + 1, edges[i + 1]) if cyc in low)
            for i in range(len(w))
        ]
        self._info(
            f"S7 applied wvalid_gaps={measured} w_hs_cycles={[x['cyc'] for x in w]} "
            f"aw_hs_cycle={edges[0]} b_hs_cycles={[x['cyc'] for x in b]}"
        )
        observed, expected = self._write_shape(aw, w, b, GAP_AWID, GAP_AWLEN)
        self._check(
            "CHK-WR-GAPS",
            {"awid": _hx(GAP_AWID), "gaps": measured, "driver_done": released, **observed},
            {"awid": _hx(GAP_AWID), "gaps": gaps, "driver_done": True, **expected},
            "sixteen W beats each after its seeded WVALID gap, then one DECERR B",
        )
        self._mark("WR_BURST_DONE")
        self.steps["S7"] = True

    async def _s8_side_effect(self) -> None:
        mon = self.mon
        clear_profile(self.master.driver)
        q_addr = self._smc_window(SCRATCH_COLD_ADDR)
        p_addr = q_addr + BIT55
        self._info(
            f"S8 SCRATCH_COLD window=0x{q_addr:014x} alias=0x{p_addr:014x} "
            f"Q=0x{SCRATCH_Q:08x} P=0x{SCRATCH_P:08x}"
        )
        c0 = self._counts()
        mk = mon.mark()
        await self._xfer(
            "S8_write_q",
            write=True,
            addr=q_addr,
            payload=SCRATCH_Q.to_bytes(4, "little"),
            size=SIZE_4B,
            awid=Q_AWID,
        )
        bq = mon.since(mk, "b")
        c1 = self._counts()
        mk = mon.mark()
        await self._xfer(
            "S8_write_p_alias",
            write=True,
            addr=p_addr,
            payload=SCRATCH_P.to_bytes(4, "little"),
            size=SIZE_4B,
            awid=P_AWID,
        )
        bp = mon.since(mk, "b")
        c2 = self._counts()
        mk = mon.mark()
        await self._xfer(
            "S8_readback", write=False, addr=q_addr, payload=4, size=SIZE_4B, arid=RB_ARID
        )
        r = mon.since(mk, "r")
        rdata = r[0]["rdata"] if r else None
        word = None if rdata is None else (rdata >> (8 * (q_addr % BEAT_BYTES))) & 0xFFFF_FFFF
        self._info(
            f"S8 bq={[(_rn(x['bresp']), _hx(x['bid'])) for x in bq]} "
            f"bp={[(_rn(x['bresp']), _hx(x['bid'])) for x in bp]} "
            f"readback={_hx(word)} rresp={[_rn(x['rresp']) for x in r]} P=0x{SCRATCH_P:08x} "
            f"Q=0x{SCRATCH_Q:08x}"
        )
        d01, d12 = self._delta(c0, c1), self._delta(c1, c2)
        self._check(
            "CHK-NO-SIDE-EFFECT",
            {
                "q_b": [(_rn(x["bresp"]), _hx(x["bid"])) for x in bq],
                "q_smc_aw_delta": d01["smc_xbar_in_aw_count_o"],
                "p_b": [(_rn(x["bresp"]), _hx(x["bid"])) for x in bp],
                "p_counter_deltas": d12,
                "rb_r": [(_rn(x["rresp"]), _hx(x["rid"]), _hx(x["rlast"])) for x in r],
                "rb_word": _hx(word),
            },
            {
                "q_b": [(_rn(RESP_OKAY), _hx(Q_AWID))],
                "q_smc_aw_delta": 1,
                "p_b": [(_rn(RESP_DECERR), _hx(P_AWID))],
                "p_counter_deltas": {name: 0 for name in COUNTS},
                "rb_r": [(_rn(RESP_OKAY), _hx(RB_ARID), "0x1")],
                "rb_word": _hx(SCRATCH_Q),
            },
            "the routed write of Q lands, the bit-55 alias write of P is DECERR and reaches no "
            "subordinate, SCRATCH_COLD still reads Q",
        )
        self._mark("SIDE_EFFECT_DONE")
        self.steps["S8"] = True

    async def _s9_capacity(self) -> None:
        mon = self.mon
        drv = self.master.driver
        clear_profile(drv)
        mon.trace = []
        mk = mon.mark()
        drv.set_timing(AxiTimingProfile(r_ready_delay=CAP_HOLD_CYCLES))
        arm_cyc = mon.cyc
        events = [
            self.master.init_read(
                MISS_ADDR, BEAT_BYTES, size=SIZE_8B, prot=PROT_NONSECURE, arid=arid
            )
            for arid in range(CAP_READS)
        ]
        held = {"low": None, "release": None}

        def released() -> bool:
            rready = mon.levels.get("r", (None, None))[1]
            if held["low"] is None:
                if rready == 0:
                    held["low"] = mon.cyc
                return False
            if rready == 1:
                held["release"] = mon.cyc
                return True
            return False

        await self._until("S9_rready_release", released, CAP_HOLD_CYCLES + RELEASE_MARGIN)
        release = held["release"]
        accepted = sum(1 for x in mon.since(mk, "ar") if x["cyc"] < release)
        low_cycles = release - held["low"]
        self.log.info(
            "OBS-ERR-ACCEPTED: accepted=%d of %d rready_low_cycles=%d armed_cycle=%d "
            "release_cycle=%d",
            accepted,
            CAP_READS,
            low_cycles,
            arm_cyc,
            release,
        )
        drain = await self._until(
            "S9_drain_after_release", lambda: all(e.is_set() for e in events), CAP_DRAIN_BOUND
        )
        clear_profile(drv)
        await RisingEdge(self.dut.clk_smu_i)
        trace, mon.trace = mon.trace, None
        hold = [levels["r"] for cyc, levels in trace if held["low"] <= cyc < release]
        rvalid_first = next((i for i, (v, _) in enumerate(hold) if v == 1), None)
        held_span = [] if rvalid_first is None else hold[rvalid_first:]
        rready_low = sum(1 for _, rr in hold if rr == 0)
        rvalid_held = sum(1 for v, rr in held_span if v == 1 and rr == 0)
        self.log.info(
            "CTRL-ERR-HOLD: rready_low_cycles=%d of %d sampled from cycle %d to the release at "
            "cycle %d; rvalid_high_rready_low_cycles=%d of %d from the first RVALID",
            rready_low,
            len(hold),
            held["low"],
            release,
            rvalid_held,
            len(held_span),
        )
        r = mon.since(mk, "r")
        rids = [x["rid"] for x in r]
        self._info(
            f"S9 r_hs_cycles={_ranges([x['cyc'] for x in r])} drain_cycles={drain} "
            f"rids={[_hx(i) for i in rids]}"
        )
        self._check(
            "CHK-ERR-CAPACITY",
            {
                "r_beats": len(r),
                "rresp": sorted({_rn(x["rresp"]) for x in r}),
                "rlast_low": sum(1 for x in r if x["rlast"] != 1),
                "rid_missing": [i for i in range(CAP_READS) if i not in rids],
                "rid_repeated": sorted({_hx(i) for i in rids if rids.count(i) > 1}),
                "rid_extra": [_hx(i) for i in rids if i is None or i >= CAP_READS],
                "r_before_release": sum(1 for x in r if x["cyc"] < release),
                "rready_low_whole_hold": rready_low == len(hold) >= CAP_HOLD_CYCLES,
                "rvalid_held_to_release": len(held_span) > 0 and rvalid_held == len(held_span),
            },
            {
                "r_beats": CAP_READS,
                "rresp": [_rn(RESP_DECERR)],
                "rlast_low": 0,
                "rid_missing": [],
                "rid_repeated": [],
                "rid_extra": [],
                "r_before_release": 0,
                "rready_low_whole_hold": True,
                "rvalid_held_to_release": True,
            },
            f"RREADY is low on the pins for at least {CAP_HOLD_CYCLES} cycles and RVALID stays high "
            "from its first assertion to the release (CTRL-ERR-HOLD); after RREADY releases all "
            f"{CAP_READS} reads complete within {CAP_DRAIN_BOUND} cycles: one DECERR beat each "
            "with RLAST, every RID 0x00..0x1f once",
        )
        self._mark("ERR_CAPACITY_DONE")
        self.steps["S9"] = True

    def _fences(self) -> None:
        names = [n for n, _ in self.markers]
        cycles = [c for _, c in self.markers]
        increasing = all(a < b for a, b in zip(cycles, cycles[1:]))
        self._info(f"NONVAC markers={self.markers}")
        self._check(
            "CHK-NONVAC",
            {"order": names, "strictly_increasing": increasing, "steps": sorted(self.steps)},
            {
                "order": list(MARKERS),
                "strictly_increasing": True,
                "steps": [f"S{i}" for i in range(1, 10)],
            },
            "ordered markers " + " < ".join(f"{n}@{c}" for n, c in self.markers),
        )
        expired = [s["site"] for s in self.sites if s["status"] != "ok"]
        unbounded = [s["site"] for s in self.sites if not s["bound"]]
        self._check(
            "CHK-TIMEOUT-PATHS",
            {"expired": expired, "unbounded": unbounded},
            {"expired": [], "unbounded": []},
            f"every wait ({len(self.sites)}) has a finite bound and none expired: "
            + ", ".join(f"{s['site']}<={s['bound']}{s['unit'][0]}" for s in self.sites),
        )

    async def run(self) -> None:
        await self._s1_setup()
        await self._s2_bit55()
        await self._s3_incr_reads()
        await self._s4_wrap_fixed_reads()
        await self._s5_w_first()
        await self._s6_incr_writes()
        await self._s7_w_gaps()
        await self._s8_side_effect()
        await self._s9_capacity()
        self._fences()
