# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive AXI protocol/integrity monitor for the SMU boundary buses.

Snoops one AXI bus of ``tb_wrapper_top`` directly, independent of the
cocotbext-axi master and of the bench responder. The Verilator targets run
without --assert, so the RTL SVA rules do not fire there; this monitor runs
the same checks on every simulator. Per accepted bus beat it checks:

  * **read-data integrity** -- an accepted R beat (``rvalid && rready``) that
    returns OKAY/EXOKAY must not carry an X/Z bit in the byte lanes the read
    accesses. The monitor records every AR handshake (ARADDR, ARLEN, ARSIZE,
    ARBURST, ARID) and joins each R beat to its AR by RID, so it knows which
    lanes each beat carries (AMBA IHI 0022 A3.4.1). Lanes outside the transfer
    are not checked. An R beat with no recorded AR gets the weaker whole-bus
    check: it fails only when every data bit is X/Z. Error responses may carry
    X data, so both checks are gated to successful beats unless the caller
    opens ``open_error_rdata_window``. A read that must accept unknown data is
    issued inside ``open_unknown_rdata_window`` / ``close_unknown_rdata_window``.
  * **decode legality** -- a DECERR beat on R or B consumes one credit armed
    through ``arm_expected_decerr(n)`` and is tallied as expected. A DECERR with
    no credit is tallied as unexpected, and fails the test only when
    ``fail_decerr`` is set. Arming is exact: a probe returns the credits no
    DECERR consumed through ``release_expected_decerr(n)``, or arms through the
    ``expected_decerr`` context manager, which does both.
  * **slave ready wait** -- a held ``VALID`` with ``READY`` low is legal AXI and
    satisfies X-known, so a permanent ``1'b0`` has no protocol net. The monitor
    counts consecutive ``valid && !ready`` cycles on AW, W and AR and fails when
    the run exceeds ``cfg.axi_timeout_ns`` of ``clk_smu_i`` cycles. On ``ext_in``
    the DUT is the slave; on ``ext_out`` the bench responder is. A leaf whose
    stimulus holds a slave's READY low past the budget on purpose turns
    ``ready_budget`` off on that instance.
  * **VALID known** -- every VALID resolves to 0 or 1 out of reset. A VALID that
    stays X/Z is reported once per signal and its cycles are counted in the
    tally.
  * **response known** -- RRESP / BRESP of an accepted beat carries no X/Z.

While the bus reset is low the monitor drops its recorded ARs, clears the
ready-wait runs and skips the VALID-known check. On a Verilator (two-state)
build no net is X/Z, so the read-data, VALID-known and response-known rules
cannot fire on bus data there; they grade on a four-state simulator.

One coroutine samples every instance on one clock: ``sample_with`` makes the
leader instance sample a follower. Each cycle reads the VALIDs first and reads
nothing else when all of them are 0.

Configuration (set by the test after construction, before build_phase):
  * ``bus_name`` -- the instance label: ConfigDB key ``smu_axi_monitor_<bus_name>``
    and the ``CHK-AXI-MON-<BUS>`` tally line.
  * ``scope_path`` -- dotted path of an interface instance under ``cocotb.top``
    whose members are the AXI signals; empty for flat top-level pins.
  * ``signal_prefix`` -- prefix of flat pins (``<prefix>_awvalid`` ...); empty for
    interface members.
  * ``member_widths`` -- configured width of a member narrower than its net; the
    monitor reads only those low bits.
  * ``reset_name`` -- the active-low reset of the bus on ``cocotb.top``.
  * ``fail_decerr``, ``ready_budget``, ``require_attach``.
  * ``requires_responder`` -- the instance idles when the test built no
    ``cfg.axi_out_mem`` responder, whose VALIDs are then undriven.

At check_phase it prints one tally line, pass or fail, so a passing run carries
positive evidence:
``CHK-AXI-MON-<BUS>: beats=<r> b=<b> x_lane=<n> decerr_unexpected=<n>
decerr_expected=<n> ready_wait_max=aw:<n>,w:<n>,ar:<n> bound=<cycles> errors=<n>
valid_unknown=<cycles>``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge
from pyuvm import ConfigDB, uvm_component

_SIGNALS = (
    "rvalid",
    "rready",
    "rdata",
    "rresp",
    "rid",
    "bvalid",
    "bready",
    "bresp",
    "awvalid",
    "awready",
    "wvalid",
    "wready",
    "arvalid",
    "arready",
    "araddr",
    "arlen",
    "arsize",
    "arburst",
    "arid",
)


def _bits(sig) -> str:
    """The per-bit string of a signal, MSB first (cocotb 2.x ``str`` of the value)."""
    return str(sig.value).strip()


class _Narrow:
    """A signal handle read through its low ``width`` bits."""

    def __init__(self, handle, width: int) -> None:
        self._handle = handle
        self._width = width

    @property
    def value(self) -> str:
        return _bits(self._handle)[-self._width :]


def _hi(sig) -> bool:
    """A handshake bit is asserted only if it resolves to 1 (X => not asserted)."""
    return _bits(sig) == "1"


def _known_bit(sig) -> bool:
    """The signal resolves to 0 or 1."""
    return _bits(sig) in ("0", "1")


def _to_int(sig):
    """The signal as an int, or None when any bit is not 0/1 or it is unbound."""
    if sig is None:
        return None
    bits = _bits(sig)
    if not bits or any(c not in "01" for c in bits):
        return None
    return int(bits, 2)


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


def _is_all_x(bits: str) -> bool:
    """True only if every bit of the data bus is X/Z (fully unresolved)."""
    return len(bits) > 0 and all(c in "xzXZ" for c in bits)


def smu_axi_monitor(bus_name: str) -> SmuAxiMonitor | None:
    """The monitor registered for ``bus_name``, or None when the leaf opted out."""
    return ConfigDB().get(None, "", f"smu_axi_monitor_{bus_name}", None)


@contextlib.contextmanager
def expected_decerr(bus_name: str, n: int) -> Iterator[SmuAxiMonitor | None]:
    """Arm ``n`` DECERR credits on ``bus_name`` and return the unconsumed ones on exit.

    ``n`` is the most DECERR beats the enclosed accesses can return. A leaf
    without the monitor gets a no-op.
    """
    mon = smu_axi_monitor(bus_name)
    credit = mon.arm_expected_decerr(n) if mon is not None else None
    try:
        yield mon
    finally:
        if mon is not None:
            mon.release_expected_decerr(n, credit=credit)


_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "unparsable"}


class SmuAxiMonitor(uvm_component):
    """Independent protocol/integrity monitor on one SMU boundary AXI bus.

    Configure the class attributes per instance before build_phase.
    """

    bus_name = "ext_in"
    scope_path = ""
    signal_prefix = "ext_in"
    member_widths: dict[str, int] = {}
    reset_name = "rst_primary_smc_clk_n_o"
    clock_name = "clk_smu_i"
    fail_decerr = False
    ready_budget = True
    require_attach = False
    requires_responder = False
    # Instances this one samples from its own coroutine, and whether another
    # instance samples this one.
    followers: tuple[SmuAxiMonitor, ...] = ()
    _led = False

    def sample_with(self, follower: SmuAxiMonitor) -> None:
        """Sample ``follower`` from this instance's coroutine; both use one clock."""
        if follower.clock_name != self.clock_name:
            raise ValueError(
                f"{follower.bus_name} samples on {follower.clock_name}, "
                f"{self.bus_name} on {self.clock_name}"
            )
        self.followers = (*self.followers, follower)
        follower._led = True

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.errors: list[str] = []
        self.r_beats = 0
        self.b_resps = 0
        self.resp_tally = {0: 0, 1: 0, 2: 0, 3: 0, None: 0}
        self.x_lane_beats = 0
        self.decerr_unexpected = 0
        self.expected_decerr_seen = 0
        # One [remaining] list per arm_expected_decerr call, consumed oldest first.
        self._credits: list[list[int]] = []
        # Releases are applied after the beats of the monitor's next sample, so
        # a DECERR handshaking on the edge the caller resumes on still consumes
        # its credit first.
        self._releases: list[tuple[int, list[int] | None]] = []
        # AR handshakes waiting for their R beats, per ARID, in issue order.
        self._ar_pending: dict[int | None, list[dict]] = {}
        self._unknown_rdata_window = 0
        self._error_rdata_window = 0
        self.ar_tracked = 0
        self.r_beats_joined = 0
        self.r_beats_lane_checked = 0
        self.r_beats_exempt = 0
        self._ready_wait = {"aw": 0, "w": 0, "ar": 0}
        self.max_ready_wait = {"aw": 0, "w": 0, "ar": 0}
        self.max_ready_wait_cycles = 0
        self.attached = False
        self._bus_bytes = 8
        self._valid_unknown_reported: set[str] = set()
        self.valid_unknown_cycles = 0
        self._reset_fell = False
        ConfigDB().set(None, "*", f"smu_axi_monitor_{self.bus_name}", self)

    def arm_expected_decerr(self, n: int = 1) -> list[int]:
        """Tally the next ``n`` DECERR beats on this bus as expected.

        Arm exactly the count of DECERR beats the probe can return, so an
        UNEXPECTED extra DECERR is still counted (and fails when fail_decerr).
        Returns the credit handle ``release_expected_decerr`` accepts.
        """
        credit = [n]
        self._credits.append(credit)
        return credit

    def release_expected_decerr(self, n: int = 1, *, credit: list[int] | None = None) -> None:
        """Return up to ``n`` armed credits that no DECERR beat consumed.

        A standing credit would absorb the next UNEXPECTED DECERR anywhere on
        this bus, so a probe that did not see its DECERR hands the credit back:
        the unconsumed part of ``credit``, or ``n`` credits oldest first.
        """
        self._releases.append((n, credit))

    @property
    def armed_decerr(self) -> int:
        return sum(c[0] for c in self._credits)

    def _apply_released_decerr(self) -> None:
        for n, credit in self._releases:
            for c in [credit] if credit is not None else list(self._credits):
                take = min(n, c[0])
                c[0] -= take
                n -= take
        self._releases = []
        self._credits = [c for c in self._credits if c[0] > 0]

    def open_unknown_rdata_window(self) -> None:
        """Exempt reads whose AR handshakes before the matching close call."""
        self._unknown_rdata_window += 1

    def close_unknown_rdata_window(self) -> None:
        self._unknown_rdata_window = max(0, self._unknown_rdata_window - 1)

    def open_error_rdata_window(self) -> None:
        """Also check error-response beats of reads whose AR handshakes before the close.

        A caller that grades the data of an error response opens this window so
        an X/Z in that payload fails the run.
        """
        self._error_rdata_window += 1

    def close_error_rdata_window(self) -> None:
        self._error_rdata_window = max(0, self._error_rdata_window - 1)

    def forget_pending_reads(self, axi_id: int) -> None:
        """Drop the recorded ARs of ``axi_id`` that are still waiting for R beats.

        A read that timed out never gets its beats, and a later read with the
        same ID would otherwise join to it and be checked against the wrong lanes.
        """
        self._ar_pending.pop(axi_id, None)

    def _rdata_bits(self, sig) -> str:
        return _bits(sig["rdata"])

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

    def _check_r_lanes(self, sig, code, bits: str) -> bool:
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
        nbits = len(bits)
        unknown = []
        for lane in _beat_lanes(ar, beat, self._bus_bytes):
            for j in range(8):
                i = lane * 8 + j
                if i < nbits and bits[nbits - 1 - i] not in "01":
                    unknown.append(i)
        if unknown:
            self.x_lane_beats += 1
            where = f"0x{ar['addr']:014x}" if ar["addr"] is not None else "unresolved address"
            self._fail(
                f"R beat {beat} (resp={code}) of the read at {where} (RID {rid}) carries X/Z "
                f"in accessed bit(s) {unknown[:16]}{' ...' if len(unknown) > 16 else ''}: "
                f"rdata={bits!r}: the read returned an unknown value"
            )
        return True

    def _decerr(self, chan: str) -> None:
        """Handle a DECERR beat: consume an armed credit, else tally (and fail) it."""
        if self._credits:
            self._credits[0][0] -= 1
            if self._credits[0][0] == 0:
                self._credits.pop(0)
            self.expected_decerr_seen += 1
            return
        self.decerr_unexpected += 1
        if self.fail_decerr:
            self._fail(f"{chan} beat returned DECERR with no armed credit (address decode error)")

    def _tick_ready_wait(self, chan: str, waiting: bool) -> None:
        """Count a slave-ready-low cycle, or clear the run on handshake/idle."""
        run = self._ready_wait[chan] + 1 if waiting else 0
        self._ready_wait[chan] = run
        if run > self.max_ready_wait[chan]:
            self.max_ready_wait[chan] = run
        if self.ready_budget and run == self.max_ready_wait_cycles + 1:
            self._fail(
                f"{chan}valid held with {chan}ready low for {run} cycles "
                f"(bound {self.max_ready_wait_cycles}, {self.cfg.axi_timeout_ns} ns): "
                "a stable 1'b0 on READY is legal AXI and not X, so this is the liveness net"
            )

    def _fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.logger.error("AXI MONITOR [%s] FAIL: %s", self.bus_name, msg)

    def _lookup(self) -> dict:
        scope = cocotb.top
        for part in filter(None, self.scope_path.split(".")):
            scope = getattr(scope, part, None)
            if scope is None:
                return dict.fromkeys(_SIGNALS)
        sig = {}
        for n in _SIGNALS:
            name = f"{self.signal_prefix}_{n}" if self.signal_prefix else n
            handle = getattr(scope, name, None)
            width = self.member_widths.get(n)
            if handle is not None and width is not None and width < len(handle):
                handle = _Narrow(handle, width)
            sig[n] = handle
        return sig

    def _attach(self) -> bool:
        """Look the bus up; False (and a failure with ``require_attach``) if R is missing."""
        self._where = self.scope_path or f"{self.signal_prefix}_*"
        self._sig = self._lookup()
        if any(self._sig[n] is None for n in ("rvalid", "rready", "rdata")):
            msg = f"{self._where} read channel not found; AXI monitor idle"
            if self.require_attach:
                self._fail(msg)
            else:
                self.logger.info(msg)
            return False
        self._bus_bytes = max(1, len(_bits(self._sig["rdata"])) // 8)
        return True

    def _start(self) -> bool:
        """Set the READY bound after reset; False when the instance idles."""
        period = self.cfg.smu_clk_period_ns
        self.max_ready_wait_cycles = max(1, int(self.cfg.axi_timeout_ns / period))
        if self.requires_responder and getattr(self.cfg, "axi_out_mem", None) is None:
            self.logger.info(
                "SMU AXI monitor [%s] idle: the test built no ext_out responder (cfg.axi_out_mem)",
                self.bus_name,
            )
            return False
        sig = self._sig
        self._rst = getattr(cocotb.top, self.reset_name, None)
        self._has_b = sig["bvalid"] is not None and sig["bready"] is not None
        self._has_aw = all(sig[n] is not None for n in ("awvalid", "awready", "wvalid", "wready"))
        self._has_ar = sig["arvalid"] is not None and sig["arready"] is not None
        self._valids = [
            n for n in ("rvalid", "bvalid", "arvalid", "awvalid", "wvalid") if sig[n] is not None
        ]
        self.attached = True
        missing = [n for n in _SIGNALS if sig[n] is None]
        self.logger.info(
            "SMU AXI monitor [%s] attached to %s (reset %s, fail_decerr=%s, ready budget %s, "
            "bound %d cycles of %s ns, missing nets %s)",
            self.bus_name,
            self._where,
            self.reset_name if self._rst is not None else "none",
            self.fail_decerr,
            "on" if self.ready_budget else "off",
            self.max_ready_wait_cycles,
            period,
            missing or "none",
        )
        if self._rst is not None:
            cocotb.start_soon(self._watch_reset())
        return True

    async def _watch_reset(self) -> None:
        """Flag each fall of the bus reset, which an all-idle cycle does not read."""
        while True:
            await FallingEdge(self._rst)
            self._reset_fell = True

    def _clear_for_reset(self) -> None:
        """A reset drops every read in flight and ends every READY wait."""
        self._ar_pending.clear()
        self._ready_wait = {"aw": 0, "w": 0, "ar": 0}
        self._reset_fell = False

    def _sample(self) -> None:
        """One clock edge: the VALIDs first, the other nets only when one is not 0."""
        sig = self._sig
        if self._reset_fell:
            self._clear_for_reset()
        valid = {n: _bits(sig[n]) for n in self._valids}
        if all(b == "0" for b in valid.values()):
            self._ready_wait = {"aw": 0, "w": 0, "ar": 0}
            self._apply_released_decerr()
            return
        if self._rst is not None and _bits(self._rst) != "1":
            self._clear_for_reset()
            self._apply_released_decerr()
            return
        for n, b in valid.items():
            if b not in ("0", "1"):
                self.valid_unknown_cycles += 1
                if n not in self._valid_unknown_reported:
                    self._valid_unknown_reported.add(n)
                    self._fail(
                        f"{n}={b} out of reset (VALID must be 0 or 1); "
                        "its later X/Z cycles are counted in valid_unknown"
                    )
        if self._has_aw:
            aw = valid["awvalid"] == "1"
            self._tick_ready_wait("aw", aw and _bits(sig["awready"]) != "1")
            w = valid["wvalid"] == "1"
            self._tick_ready_wait("w", w and _bits(sig["wready"]) != "1")
        if self._has_ar:
            ar = valid["arvalid"] == "1"
            ar_ready = ar and _bits(sig["arready"]) == "1"
            self._tick_ready_wait("ar", ar and not ar_ready)
            if ar_ready and sig["araddr"] is not None:
                self._record_ar(sig)
        if valid["rvalid"] == "1" and _hi(sig["rready"]):
            self.r_beats += 1
            code = _to_int(sig["rresp"])
            if sig["rresp"] is not None and code is None:
                self._fail(f"R beat RRESP={_bits(sig['rresp'])} (X/Z on an accepted beat)")
            self.resp_tally[code if code in (0, 1, 2, 3) else None] += 1
            bits = self._rdata_bits(sig)
            # Lane check for a beat joined to its AR; whole-bus all-X check
            # otherwise. Both only on a successful response.
            joined = self._check_r_lanes(sig, code, bits)
            if not joined and code in (0, 1) and _is_all_x(bits):
                self.x_lane_beats += 1
                self._fail("OKAY R beat with no recorded AR returned all-X data")
            if code == 3:
                self._decerr("R")
        if self._has_b and valid["bvalid"] == "1" and _hi(sig["bready"]):
            self.b_resps += 1
            bcode = _to_int(sig["bresp"])
            if sig["bresp"] is not None and bcode is None:
                self._fail(f"B beat BRESP={_bits(sig['bresp'])} (X/Z on an accepted beat)")
            if bcode == 3:
                self._decerr("B")
        self._apply_released_decerr()

    async def run_phase(self) -> None:
        if self._led:
            return
        group = [m for m in (self, *self.followers) if m._attach()]
        if not group:
            return
        await self.cfg.reset_done.wait()
        active = [m for m in group if m._start()]
        if not active:
            return
        clk = getattr(cocotb.top, self.clock_name)
        while True:
            await RisingEdge(clk)
            for m in active:
                m._sample()

    def check_phase(self) -> None:
        self._apply_released_decerr()
        self.logger.info(
            "CHK-AXI-MON-%s: beats=%d b=%d x_lane=%d decerr_unexpected=%d decerr_expected=%d "
            "ready_wait_max=aw:%d,w:%d,ar:%d bound=%d errors=%d valid_unknown=%d",
            self.bus_name.upper().replace("_", "-"),
            self.r_beats,
            self.b_resps,
            self.x_lane_beats,
            self.decerr_unexpected,
            self.expected_decerr_seen,
            self.max_ready_wait["aw"],
            self.max_ready_wait["w"],
            self.max_ready_wait["ar"],
            self.max_ready_wait_cycles,
            len(self.errors),
            self.valid_unknown_cycles,
        )
        self.logger.info(
            "SMU AXI monitor [%s]: attached=%s R-resp tally %s; rdata lane check %d beat(s) "
            "(%d joined to an AR, %d exempt); ready budget %s",
            self.bus_name,
            self.attached,
            ", ".join(f"{_RESP_NAME[k]}={v}" for k, v in self.resp_tally.items() if v) or "none",
            self.r_beats_lane_checked,
            self.r_beats_joined,
            self.r_beats_exempt,
            "on" if self.ready_budget else "off",
        )
        assert not self.errors, (
            f"SMU AXI monitor [{self.bus_name}] found {len(self.errors)} "
            f"protocol error(s): " + "; ".join(self.errors[:8])
        )
        # A standing credit means a probe expected DECERR, got another answer,
        # and did not release it.
        assert self.armed_decerr == 0, (
            f"SMU AXI monitor [{self.bus_name}] ended with {self.armed_decerr} "
            "armed DECERR credit(s) unconsumed and unreleased"
        )
        # Recorded ARs and R beats with none joined by RID means the lane check
        # graded nothing.
        assert not (self.ar_tracked and self.r_beats and not self.r_beats_joined), (
            f"SMU AXI monitor [{self.bus_name}] recorded {self.ar_tracked} AR "
            f"handshake(s) and saw {self.r_beats} R beat(s), but joined none by "
            "RID: the read-data lane check did not run"
        )
