# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive AXI protocol/integrity monitor for the SEP AXI buses.

Snoops a top-level AXI bus directly (by signal prefix) -- independent of the
cocotbext-axi master.
This is the in-testbench substitute for the RTL SVA assertions, which the OSS
Verilator build cannot run (gated off by ``VERILATOR``). It
checks, per accepted bus beat:

  * **read-data integrity** -- an accepted R beat (``rvalid && rready``) that
    returns OKAY/EXOKAY must not carry an X/Z bit in the byte lanes the read
    accesses. The monitor records every AR handshake on the bus (address, ARLEN,
    ARSIZE, ARBURST, ARID) and joins each R beat to its AR by RID, so it knows
    which lanes each beat carries (AMBA IHI 0022, "Transfer address" and
    "Data read and write structure"). Lanes outside the transfer are not
    checked. cocotbext-axi raises on an X/Z bit of a beat it converts, so a
    read issued through the SEP driver with unknown data already fails at the
    read; this check is the independent net on the bus, and the only one for
    beats that no SEP driver read issued. An R beat with no
    recorded AR (for example CPU traffic on the shared response path) gets the
    weaker whole-bus check: it fails only when every data bit is X/Z. Error
    responses (SLVERR/DECERR) may legitimately carry X data, so both checks
    are gated to successful beats. A read that must accept unknown data sets
    ``SepAxiItem.allow_unknown_rdata``; the driver then opens an exemption
    window (``open_unknown_rdata_window``) around that access.
  * **decode legality** -- flags ``DECERR`` on R/B responses (address never
    decoded), but only when ``fail_decerr`` is set. ``SLVERR`` is tallied but not
    failed (it can be intentional). A test that *intentionally* drives an
    undecoded address on this bus (a negative-path decode-error probe) arms the
    expected count via ``arm_expected_decerr(n)``: the next ``n`` DECERR beats are
    then tallied as expected instead of failing, while an UNEXPECTED DECERR still
    fails -- so the monitor stays a real decode-bug guard on the CPU-LSU bus.
  * **slave ready wait** -- a held ``VALID`` with ``READY`` low is legal AXI
    (IHI 0022 does not bound READY) and satisfies X-known, so a permanent
    ``1'b0`` has no protocol net. The monitor counts consecutive
    ``valid && !ready`` cycles on AW, W and AR (slave readys) and fails
    when the run reaches the same time budget as ``cfg.axi_timeout_ns``.
    Master-side B/R READY is not this check.

Configuration (set by the env after construction, like the agent's ``axi_prefix``):
  * ``bus_prefix`` -- AXI signal prefix to snoop (default ``s_axi``, the CPU-LSU
    master). Set to ``m_axi`` for the external SMN-inbound master.
  * ``fail_decerr`` -- whether a DECERR beat fails the test. True for the CPU-LSU
    bus (no inbound filter, a DECERR is a real decode bug); False for the external
    bus, whose inbound filter routes blocked accesses to
    axi_err_slv with DECERR (the inbound-filter-gating test asserts that).

It tallies beats + response codes so a clean run reports positive evidence.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from pyuvm import ConfigDB, uvm_component


def _hi(sig) -> bool:
    """A handshake bit is asserted only if it resolves to 1 (X => not asserted)."""
    try:
        return int(sig.value) == 1
    except Exception:
        return False


def _resp(sig):
    try:
        return int(sig.value)
    except Exception:
        return None


def _bits(sig) -> str:
    """The per-bit string of a signal, MSB first (cocotb 1.x ``binstr``, 2.x ``str``)."""
    value = sig.value
    bits = getattr(value, "binstr", None)
    return (bits if bits is not None else str(value)).strip()


def _to_int(sig):
    """The signal as an int, or None when any bit is not 0/1 or it is unbound."""
    if sig is None:
        return None
    try:
        return int(sig.value)
    except Exception:
        return None


def _beat_lanes(ar: dict, beat: int, bus_bytes: int) -> range:
    """Byte lanes that carry data on beat ``beat`` (0-based) of a recorded AR.

    AMBA IHI 0022 A3.4.1: the first beat starts at the (possibly unaligned)
    start address; each later beat of an INCR or WRAP burst is at the aligned
    address plus ``beat * 2**ARSIZE``; a WRAP burst wraps at the
    ``2**ARSIZE * (ARLEN + 1)`` boundary; a FIXED burst repeats the first
    beat's address. An AR whose fields did not resolve selects every lane.
    """
    addr, size, burst, length = ar["addr"], ar["size"], ar["burst"], ar["len"]
    if addr is None or size is None or burst is None or length is None:
        return range(bus_bytes)
    nbytes = 1 << size
    aligned = (addr // nbytes) * nbytes
    if beat == 0 or burst == 0:
        beat_addr = addr
    else:
        beat_addr = aligned + beat * nbytes
        if burst == 2:
            span = nbytes * (length + 1)
            lower = (addr // span) * span
            if beat_addr >= lower + span:
                beat_addr -= span
    beat_aligned = (beat_addr // nbytes) * nbytes
    base = (beat_addr // bus_bytes) * bus_bytes
    lo = beat_addr - base
    hi = beat_aligned + nbytes - 1 - base
    return range(max(0, lo), min(bus_bytes - 1, hi) + 1)


def _is_all_x(sig) -> bool:
    """True only if every bit of the data bus is X/Z (fully unresolved)."""
    try:
        int(sig.value)  # fully resolved -> definitely not all-X
        return False
    except Exception:
        s = str(sig.value).lower()
        return len(s) > 0 and all(c in "xz" for c in s)


_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "unparsable"}


class SepAxiMonitor(uvm_component):
    """Independent protocol/integrity monitor on one AXI bus' read + write-resp
    channels. Configure ``bus_prefix`` / ``fail_decerr`` before run_phase."""

    # Overridable per instance (set in the env's build_phase, top-down).
    bus_prefix = "s_axi"
    fail_decerr = True
    # Fail if the prefix resolved to nothing. The s_axi instance is live on
    # every env; m_axi ports exist too, but that instance idles on most tests.
    require_attach = True

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.errors: list[str] = []
        self.r_beats = 0
        self.b_resps = 0
        self.resp_tally = {0: 0, 1: 0, 2: 0, 3: 0, None: 0}
        # Ordered RRESP capture window; None when closed. See start_beat_capture.
        # Entries are None when a beat's rresp does not resolve to an int.
        self._beat_capture: list[int | None] | None = None
        # Credits for intentional negative-path DECERR beats (see arm_expected_decerr).
        self._armed_decerr = 0
        # AR handshakes waiting for their R beats, per ARID, in issue order.
        # Each entry carries the fields `_beat_lanes` needs, the next beat
        # index, and whether the read is exempt from the unknown-lane check.
        self._ar_pending: dict[int | None, list[dict]] = {}
        self._unknown_rdata_window = 0
        self._error_rdata_window = 0
        self.ar_tracked = 0
        self.r_beats_joined = 0
        self.r_beats_lane_checked = 0
        self.r_beats_exempt = 0
        # The driver finds this monitor by bus prefix to open the exemption
        # window for a read that sets allow_unknown_rdata.
        ConfigDB().set(None, "*", f"sep_axi_monitor_{self.bus_prefix}", self)
        # Write-channel ordering. VALID assertion is the stimulus this bench
        # controls; the handshake is the slave's answer, and a slave that
        # holds wready until AW makes a W-first handshake impossible however
        # the master drives. The two are measured separately.
        self.cycles = 0
        self._aw_valid_cycle: int | None = None
        self._w_valid_cycle: int | None = None
        self._aw_hs_cycle: int | None = None
        self._w_hs_cycle: int | None = None
        self.last_write_stim: str | None = None
        self.last_write_hs: str | None = None
        self.expected_decerr_seen = 0
        # Consecutive slave-ready-low cycles while the matching VALID is held.
        self._ready_wait = {"aw": 0, "w": 0, "ar": 0}
        self.max_ready_wait = {"aw": 0, "w": 0, "ar": 0}
        period = self.cfg.sys_clk_period_ns
        self.max_ready_wait_cycles = max(1, int(self.cfg.axi_timeout_ns / period))

    def start_beat_capture(self) -> None:
        """Record the ordered RRESP of every following R beat until taken.

        The tally answers how many beats carried each code; it cannot answer
        WHICH beat carried which, and a per-beat extent rule needs the order.
        The AXI master collapses a read burst to one response (the cocotbext
        beat loop keeps the last non-OKAY RRESP), so the ordered sequence has to
        come from the bus.

        The caller owns quiescence: any R beat on this bus while capture is open
        is appended, so a capture spanning unrelated traffic returns a sequence
        longer than the burst. Compare the length against the beats issued and
        treat a mismatch as no evidence rather than as a verdict.
        """
        self._beat_capture = []

    def take_beat_capture(self) -> list[int | None]:
        """Return the captured RRESP sequence and close the window."""
        captured: list[int | None] = self._beat_capture or []
        self._beat_capture = None
        return captured

    def arm_expected_decerr(self, n: int = 1) -> None:
        """Tolerate the next ``n`` DECERR beats on this bus as intentional.

        A decode-error probe (e.g. the fabric decode-error test reading an
        unmapped local address) produces a DECERR that is the expected outcome,
        not a decode bug. Arm exactly the count the test will drive so an
        UNEXPECTED extra DECERR still fails. No-op effect when fail_decerr=False
        (that bus never fails on DECERR anyway)."""
        self._armed_decerr += n

    def release_expected_decerr(self, n: int = 1) -> None:
        """Return ``n`` armed credits that no DECERR beat consumed.

        Arming is per-probe and speculative: a negative-path probe expects
        DECERR, but a DUT that answers OKAY or SLVERR produces no DECERR beat
        and leaves the credit standing. A standing credit would silently
        absorb the next UNEXPECTED DECERR anywhere on this bus, so a probe
        that did not see one must hand the credit back."""
        self._armed_decerr = max(0, self._armed_decerr - n)

    def open_unknown_rdata_window(self) -> None:
        """Exempt reads whose AR handshakes before the matching close call.

        For a caller that must read data that is legitimately partly unknown.
        The exemption is per AR, so a read split into several bursts is
        covered while the window is open, and traffic after the close is
        checked again.
        """
        self._unknown_rdata_window += 1

    def close_unknown_rdata_window(self) -> None:
        self._unknown_rdata_window = max(0, self._unknown_rdata_window - 1)

    def open_error_rdata_window(self) -> None:
        """Also check error-response beats of reads whose AR handshakes before the close.

        By default only OKAY/EXOKAY beats are lane-checked for X/Z. A caller that
        grades the data of an error response (a specified error payload, or 0)
        opens this window so an X/Z in that payload fails the run.
        """
        self._error_rdata_window += 1

    def close_error_rdata_window(self) -> None:
        self._error_rdata_window = max(0, self._error_rdata_window - 1)

    def forget_pending_reads(self, axi_id: int) -> None:
        """Drop the recorded ARs of ``axi_id`` that are still waiting for R beats.

        The driver calls this after a read it issued timed out. That read's AR
        never gets its beats, and a later read with the same ID would
        otherwise join to it and be checked against the wrong lanes.
        """
        self._ar_pending.pop(axi_id, None)

    def _record_ar(self, sig) -> None:
        entry = {
            "addr": _to_int(sig["araddr"]),
            "len": _to_int(sig["arlen"]) if sig["arlen"] is not None else 0,
            "size": _to_int(sig["arsize"]),
            "burst": _to_int(sig["arburst"]) if sig["arburst"] is not None else 1,
            "beat": 0,
            "exempt": self._unknown_rdata_window > 0,
            "check_error_beats": self._error_rdata_window > 0,
        }
        if entry["size"] is None and sig["arsize"] is None:
            entry["size"] = self._bus_bytes.bit_length() - 1
        arid = _to_int(sig["arid"]) if sig["arid"] is not None else 0
        self._ar_pending.setdefault(arid, []).append(entry)
        self.ar_tracked += 1

    def _check_r_lanes(self, sig, code) -> bool:
        """Join an R beat to its AR and check its lanes. False if no AR was recorded."""
        rid = _to_int(sig["rid"]) if sig["rid"] is not None else 0
        queue = self._ar_pending.get(rid)
        if not queue:
            return False
        ar = queue[0]
        beat = ar["beat"]
        ar["beat"] += 1
        if ar["len"] is None or ar["beat"] > ar["len"]:
            queue.pop(0)
        self.r_beats_joined += 1
        if code not in (0, 1) and not ar["check_error_beats"]:
            return True
        if ar["exempt"]:
            self.r_beats_exempt += 1
            return True
        self.r_beats_lane_checked += 1
        bits = _bits(sig["rdata"])
        nbits = len(bits)
        unknown = []
        for lane in _beat_lanes(ar, beat, self._bus_bytes):
            for j in range(8):
                i = lane * 8 + j
                if i < nbits and bits[nbits - 1 - i] not in "01":
                    unknown.append(i)
        if unknown:
            where = f"0x{ar['addr']:08x}" if ar["addr"] is not None else "unresolved address"
            self._fail(
                f"R beat {beat} (resp={code}) of the read at {where} (RID {rid}) carries X/Z "
                f"in accessed bit(s) {unknown[:16]}{' ...' if len(unknown) > 16 else ''}: "
                f"rdata={bits!r}: the read returned an unknown value"
            )
        return True

    def arm_write_order(self) -> None:
        """Measure the next write on its own, discarding the previous one."""
        self._aw_valid_cycle = None
        self._w_valid_cycle = None
        self._aw_hs_cycle = None
        self._w_hs_cycle = None
        self.last_write_stim = None
        self.last_write_hs = None

    @staticmethod
    def _order(a, w) -> str | None:
        if a is None or w is None:
            return None
        return "same-cycle" if a == w else "aw-first" if a < w else "w-first"

    @property
    def write_order_cycles(self) -> tuple:
        """(aw_valid, w_valid, aw_handshake, w_handshake) cycle numbers."""
        return (self._aw_valid_cycle, self._w_valid_cycle, self._aw_hs_cycle, self._w_hs_cycle)

    def _decerr(self, chan: str) -> None:
        """Handle a DECERR beat: consume an armed credit or fail."""
        if self._armed_decerr > 0:
            self._armed_decerr -= 1
            self.expected_decerr_seen += 1
            self.logger.info(
                "%s beat returned DECERR -- expected (armed negative-path probe)", chan
            )
        else:
            self._fail(f"{chan} beat returned DECERR (address decode error)")

    def _tick_ready_wait(self, chan: str, waiting: bool) -> None:
        """Count a slave-ready-low cycle, or clear the run on handshake/idle."""
        run = self._ready_wait[chan] + 1 if waiting else 0
        self._ready_wait[chan] = run
        if run > self.max_ready_wait[chan]:
            self.max_ready_wait[chan] = run
        if run == self.max_ready_wait_cycles:
            self._fail(
                f"{chan} valid held with {chan}ready low for "
                f"{run} cycles (bound {self.max_ready_wait_cycles}, "
                f"{self.cfg.axi_timeout_ns} ns) -- a stable 1'b0 on "
                f"READY is legal AXI and not X, so this is the liveness net"
            )

    def _fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.logger.error("AXI MONITOR [%s] FAIL: %s", self.bus_prefix, msg)

    async def run_phase(self) -> None:
        dut = cocotb.top
        p = self.bus_prefix
        sig = {
            n: getattr(dut, f"{p}_{n}", None)
            for n in (
                "rvalid",
                "rready",
                "rdata",
                "rresp",
                "bvalid",
                "bready",
                "bresp",
                "araddr",
                "awvalid",
                "awready",
                "wvalid",
                "wready",
                "arvalid",
                "arready",
                "arlen",
                "arsize",
                "arburst",
                "arid",
                "rid",
            )
        }
        if any(sig[n] is None for n in ("rvalid", "rready", "rdata")):
            msg = f"{p} read channel not found; AXI monitor idle"
            if self.require_attach:
                self._fail(msg)
                return
            self.logger.info(msg)
            return
        self._bus_bytes = max(1, len(_bits(sig["rdata"])) // 8)
        await self.cfg.reset_done.wait()
        self.logger.info(
            "SEP AXI monitor active on %s bus (fail_decerr=%s, max slave ready-wait %d cycles)",
            p,
            self.fail_decerr,
            self.max_ready_wait_cycles,
        )
        has_b = sig["bvalid"] is not None and sig["bready"] is not None

        has_aw = all(sig[n] is not None for n in ("awvalid", "awready", "wvalid", "wready"))
        has_ar = sig["arvalid"] is not None and sig["arready"] is not None

        while True:
            await RisingEdge(dut.clk_i)
            self.cycles += 1
            if has_aw:
                self._tick_ready_wait("aw", _hi(sig["awvalid"]) and not _hi(sig["awready"]))
                self._tick_ready_wait("w", _hi(sig["wvalid"]) and not _hi(sig["wready"]))
            if has_ar:
                self._tick_ready_wait("ar", _hi(sig["arvalid"]) and not _hi(sig["arready"]))
                if _hi(sig["arvalid"]) and _hi(sig["arready"]) and sig["araddr"] is not None:
                    self._record_ar(sig)
            if has_aw:
                if _hi(sig["awvalid"]) and self._aw_valid_cycle is None:
                    self._aw_valid_cycle = self.cycles
                if _hi(sig["wvalid"]) and self._w_valid_cycle is None:
                    self._w_valid_cycle = self.cycles
                if _hi(sig["awvalid"]) and _hi(sig["awready"]) and self._aw_hs_cycle is None:
                    self._aw_hs_cycle = self.cycles
                if _hi(sig["wvalid"]) and _hi(sig["wready"]) and self._w_hs_cycle is None:
                    self._w_hs_cycle = self.cycles
                self.last_write_stim = self._order(self._aw_valid_cycle, self._w_valid_cycle)
                self.last_write_hs = self._order(self._aw_hs_cycle, self._w_hs_cycle)
            if _hi(sig["rvalid"]) and _hi(sig["rready"]):
                self.r_beats += 1
                code = _resp(sig["rresp"]) if sig["rresp"] is not None else None
                self.resp_tally[code if code in (0, 1, 2, 3) else None] += 1
                if self._beat_capture is not None:
                    self._beat_capture.append(code)
                # Lane check for a beat joined to its AR; whole-bus all-X check
                # otherwise. Both only on a *successful* response (an error
                # beat may legitimately carry X data).
                joined = self._check_r_lanes(sig, code)
                if not joined and code in (0, 1) and _is_all_x(sig["rdata"]):
                    addr = _resp(sig["araddr"]) if sig["araddr"] is not None else None
                    where = f" (last AR addr ~0x{addr:08x})" if addr is not None else ""
                    self._fail(
                        f"OKAY R beat returned all-X data{where} -- "
                        "non-responding/uninitialised register path"
                    )
                if code == 3 and self.fail_decerr:
                    self._decerr("R")
            if has_b and _hi(sig["bvalid"]) and _hi(sig["bready"]):
                self.b_resps += 1
                if _resp(sig["bresp"]) == 3 and self.fail_decerr:
                    self._decerr("B")

    def check_phase(self) -> None:
        assert not self.errors, (
            f"SEP AXI monitor [{self.bus_prefix}] found {len(self.errors)} "
            f"protocol error(s): " + "; ".join(self.errors[:8])
        )
        # The lane check joins R to AR by ID. Recorded ARs with R beats on the
        # bus but no beat ever joined means the join is broken, and the lane
        # check graded nothing.
        assert not (self.ar_tracked and self.r_beats and not self.r_beats_joined), (
            f"SEP AXI monitor [{self.bus_prefix}] recorded {self.ar_tracked} AR "
            f"handshake(s) and saw {self.r_beats} R beat(s), but joined none by "
            "RID -- the read-data lane check did not run"
        )
        sb = getattr(self.parent, "scoreboard", None)
        if (
            self.bus_prefix == "s_axi"
            and sb is not None
            and getattr(sb, "checks", 0) > 0
            and (self.r_beats + self.b_resps) == 0
        ):
            raise AssertionError(
                f"SEP AXI monitor [{self.bus_prefix}] saw 0 R/B beats while the "
                f"scoreboard graded {sb.checks} transaction(s) -- the prefix "
                "did not observe the live bus"
            )
        self.logger.info(
            "SEP AXI monitor [%s]: %d R beats, %d B resps; R-resp tally %s; "
            "%d expected DECERR; rdata lane check %d beat(s) (%d joined to an AR, "
            "%d exempt by allow_unknown_rdata); max slave ready-wait aw=%d w=%d ar=%d "
            "(bound %d); 0 errors",
            self.bus_prefix,
            self.r_beats,
            self.b_resps,
            ", ".join(f"{_RESP_NAME[k]}={v}" for k, v in self.resp_tally.items() if v),
            self.expected_decerr_seen,
            self.r_beats_lane_checked,
            self.r_beats_joined,
            self.r_beats_exempt,
            self.max_ready_wait["aw"],
            self.max_ready_wait["w"],
            self.max_ready_wait["ar"],
            self.max_ready_wait_cycles,
        )
