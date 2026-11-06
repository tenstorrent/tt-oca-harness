# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive AXI protocol/integrity monitor for one SMC inbound AXI port.

One instance snoops one top-level bus by signal prefix, independently from the
active cocotbext-axi master on that bus. The env builds one per inbound port:
SEP_IN (``s_axi``), SYS_IN (``sys_axi``) and JTAG_IN (``jtag_axi``). Per
accepted beat it checks:

  * **read-data integrity** -- every AR handshake is recorded in an ARID-keyed
    table (address, ARLEN, ARSIZE, ARBURST, beats seen) and each R beat joins
    the oldest AR of its RID. An OKAY/EXOKAY beat must not carry an X/Z bit in
    the byte lanes the beat accesses, computed from the beat address and ARSIZE
    (AMBA IHI 0022, "Transfer address" and "Data read and write structure");
    lanes outside the transfer are not checked. A beat with no recorded AR gets
    the whole-bus rule: it fails only when every data bit is X/Z. With
    ``all_x_any_resp`` the whole-bus rule also judges error beats.
  * **decode legality** -- with ``fail_decerr`` a DECERR beat fails unless the
    address of its own transaction is deadspace, outside the map, or registered
    in ``expected_decerr_addrs``. Without it DECERR is tallied only, which is
    the behaviour of a port whose inbound filter answers blocked accesses with
    DECERR.
  * **slave READY wait** -- a held VALID with READY low is legal AXI and
    resolves to a known value, so a READY stuck at 0 has no protocol net. The
    monitor counts consecutive ``valid && !ready`` cycles on AW, W and AR and
    fails when a run reaches the agent's timeout budget,
    ``cfg.axi_timeout_ns`` in sys-clock cycles.

A read that must accept unknown data opens ``open_unknown_rdata_window``
around its AR handshake; its beats are then exempt from both X rules.
``declared_unknown_rdata`` does that and, for the length of the read, also
holds the bench's ``tb_rdata_known_hold``, which keeps the R-data-known SVA
on this port's links from judging the same beats. The monitor's exemption is
per AR; the bench hold is by time (the SVA instances on the SEP_IN and
peripheral links are off while it is held), so a declaring sequence issues
one read at a time inside the block and compares ``ar_exempt`` and
``r_beats_exempt`` with the number of reads it declared.

A leaf that names the port with the bench's ``+axi_sva_need_<port>`` plusarg
(``sep_in``, ``sys_in``, ``jtag_in``) fails unless the monitor saw at least one
AR handshake and checked the lanes of at least one beat, so an idle or
mis-bound monitor cannot pass a leaf that drives the port. A configured bus
prefix without its response-channel signals fails.
"""

from __future__ import annotations

import contextlib
from collections import deque

import cocotb
from cocotb.triggers import RisingEdge
from pyuvm import ConfigDB, uvm_component
from seq_lib.smc_addr_map import (
    check_rdl_windows,
    smc_addr_is_deadspace,
    smc_deadspace_ranges,
    smc_map_extent,
    smc_rdl_windows,
)


def _hi(sig) -> bool:
    """A handshake bit is asserted only if it resolves to 1."""
    try:
        return int(sig.value) == 1
    except Exception:
        return False


def _value(sig):
    if sig is None:
        return None
    try:
        return int(sig.value)
    except Exception:
        return None


def _bits(sig) -> str:
    """The per-bit string of a signal, MSB first."""
    value = sig.value
    bits = getattr(value, "binstr", None)
    return (bits if bits is not None else str(value)).strip()


def _is_all_x(sig) -> bool:
    """True only if every bit of a bus is X/Z."""
    try:
        int(sig.value)
        return False
    except Exception:
        text = str(sig.value).lower()
        return len(text) > 0 and all(ch in "xz" for ch in text)


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


_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "unparsable"}

_SIGNALS = (
    "arvalid",
    "arready",
    "araddr",
    "arlen",
    "arsize",
    "arburst",
    "arid",
    "awvalid",
    "awready",
    "awaddr",
    "awid",
    "wvalid",
    "wready",
    "rvalid",
    "rready",
    "rdata",
    "rresp",
    "rid",
    "rlast",
    "bvalid",
    "bready",
    "bresp",
    "bid",
)


class SmcAxiMonitor(uvm_component):
    """Independent AXI read/write-response monitor on one SMC inbound port.

    Every response beat is judged against the transaction it belongs to. AR
    and AW handshakes are queued per ID; a B beat, or the last R beat of a
    burst, retires the oldest transaction of its ID, so with several accesses
    outstanding a DECERR is excused only where that transaction's address
    allows it and the lane rule uses that transaction's ARADDR/ARSIZE. The
    queues and the READY wait runs clear whenever the primary reset asserts,
    as the manager abandons its outstanding accesses then.
    """

    def __init__(
        self,
        name: str,
        parent,
        bus_prefix: str = "s_axi",
        port_name: str = "SEP-IN",
        fail_decerr: bool = True,
        fail_unmatched: bool = True,
        all_x_any_resp: bool = True,
    ) -> None:
        self.bus_prefix = bus_prefix
        self.port_name = port_name
        self.fail_decerr = fail_decerr
        self.fail_unmatched = fail_unmatched
        self.all_x_any_resp = all_x_any_resp
        super().__init__(name, parent)

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.errors: list[str] = []
        self.ar_count = 0
        self.r_beats = 0
        self.b_resps = 0
        self.unmatched_resps = 0
        self.lanes_checked = 0
        self.r_beats_exempt = 0
        self.ar_exempt = 0
        self.declared_reads = 0
        self.pending_ar: dict[int | None, deque[dict]] = {}
        self.pending_aw: dict[int | None, deque[int | None]] = {}
        self.resp_tally = {0: 0, 1: 0, 2: 0, 3: 0, None: 0}
        self._unknown_rdata_window = 0
        self._ready_wait = {"aw": 0, "w": 0, "ar": 0}
        self.max_ready_wait = {"aw": 0, "w": 0, "ar": 0}
        self.ready_wait_budget = 0
        self._bus_bytes = 8
        # DECERR is a protocol failure inside any RDL-declared window. Deadspace
        # -- the gaps between the generated map's windows and everything outside
        # the map -- is derived from the RDL windows (smc_deadspace_ranges). A
        # test that provokes DECERR inside a declared window (an unimplemented
        # `external` region, an integration error slave) registers those
        # addresses in `expected_decerr_addrs`.
        check_rdl_windows()
        self.rdl_windows = smc_rdl_windows()
        self.deadspace_ranges = smc_deadspace_ranges()
        self.expected_decerr_addrs: set[int] = set()
        self.allow_decerr = False
        lo, hi = smc_map_extent()
        self.logger.info(
            "SMC AXI monitor %s (%s): %d RDL windows and %d deadspace gaps in 0x%08x-0x%08x; "
            "fail_decerr=%s: DECERR is expected only in deadspace, outside the map, "
            "or at registered addresses",
            self.port_name,
            self.bus_prefix,
            len(self.rdl_windows),
            len(self.deadspace_ranges),
            lo,
            hi,
            self.fail_decerr,
        )

    def open_unknown_rdata_window(self) -> None:
        """Exempt reads whose AR handshakes before the matching close call.

        For a read that legitimately returns partly unknown data. The exemption
        is per AR, so traffic after the close is checked again.
        """
        self._unknown_rdata_window += 1

    def close_unknown_rdata_window(self) -> None:
        self._unknown_rdata_window = max(0, self._unknown_rdata_window - 1)

    @contextlib.contextmanager
    def declared_unknown_rdata(self):
        """Exempt the reads issued inside from both X rules, here and in the bench SVA.

        The monitor's exemption covers only the ARs that handshake inside the
        block (``ar_exempt`` counts them, ``r_beats_exempt`` their beats). The
        bench hold is by time, not per read: ``tb_rdata_known_hold`` disables the
        whole SEP_IN and peripheral R-data-known SVA instance while the block is
        open, so any other R beat on those two links inside the block goes
        unjudged by the SVA (the monitor still judges every SEP_IN beat whose AR
        handshook outside a block). A sequence therefore issues exactly one read
        inside each block, awaits it, and asserts that the exempt tallies equal
        the number of blocks it opened. The hold is released on exit, including
        on an exception, after the read's last beat has been sampled.
        """
        hold = getattr(cocotb.top, "tb_rdata_known_hold", None)
        self.declared_reads += 1
        self.open_unknown_rdata_window()
        if hold is not None:
            hold.value = 1
        try:
            yield
        finally:
            if hold is not None:
                hold.value = 0
            self.close_unknown_rdata_window()

    def _decerr_expected(self, addr: int | None) -> bool:
        if self.allow_decerr:
            return True
        if addr is None:
            return False
        if addr in self.expected_decerr_addrs:
            return True
        return smc_addr_is_deadspace(addr & 0xFFFF_FFFF)

    def _fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.logger.error("SMC AXI MONITOR %s FAIL: %s", self.port_name, msg)

    @staticmethod
    def _key(id_sig) -> int | None:
        return _value(id_sig) if id_sig is not None else None

    def _unmatched(self, channel: str, key) -> None:
        self.unmatched_resps += 1
        if self.fail_unmatched:
            self._fail(f"{channel} beat on ID {key} with no request outstanding")

    def _record_ar(self, sig) -> None:
        size = _value(sig["arsize"])
        if size is None and sig["arsize"] is None:
            size = self._bus_bytes.bit_length() - 1
        entry = {
            "addr": _value(sig["araddr"]),
            "len": _value(sig["arlen"]) if sig["arlen"] is not None else 0,
            "size": size,
            "burst": _value(sig["arburst"]) if sig["arburst"] is not None else 1,
            "beats": 0,
            "exempt": self._unknown_rdata_window > 0,
        }
        self.pending_ar.setdefault(self._key(sig["arid"]), deque()).append(entry)
        self.ar_count += 1
        if entry["exempt"]:
            self.ar_exempt += 1

    def _join_r(self, sig) -> dict | None:
        """The AR an R beat belongs to, with its beat index; retired on its last beat."""
        key = self._key(sig["rid"])
        queue = self.pending_ar.get(key)
        if not queue:
            self._unmatched("R", key)
            return None
        ar = queue[0]
        beat = ar["beats"]
        ar["beats"] += 1
        if sig["rlast"] is not None:
            last = _hi(sig["rlast"])
        else:
            last = ar["len"] is None or ar["beats"] > ar["len"]
        if last:
            queue.popleft()
        return {**ar, "beat": beat}

    def _check_lanes(self, sig, ar: dict, where: str) -> None:
        self.lanes_checked += 1
        bits = _bits(sig["rdata"])
        nbits = len(bits)
        unknown = []
        for lane in _beat_lanes(ar, ar["beat"], self._bus_bytes):
            for j in range(8):
                i = lane * 8 + j
                if i < nbits and bits[nbits - 1 - i] not in "01":
                    unknown.append(i)
        if unknown:
            self._fail(
                f"R beat {ar['beat']} X in accessed lane: bit(s) {unknown[:16]}"
                f"{' ...' if len(unknown) > 16 else ''} of rdata={bits!r}{where} "
                f"(ARSIZE {ar['size']}, ARLEN {ar['len']}, ARBURST {ar['burst']})"
            )

    def _tick_ready_wait(self, chan: str, waiting: bool) -> None:
        """Count a slave-READY-low cycle, or clear the run on handshake or idle."""
        run = self._ready_wait[chan] + 1 if waiting else 0
        self._ready_wait[chan] = run
        if run > self.max_ready_wait[chan]:
            self.max_ready_wait[chan] = run
        if run == self.ready_wait_budget:
            self._fail(
                f"{chan.upper()} channel: {chan}valid held with {chan}ready low for {run} "
                f"cycles reached the READY wait budget ({self.ready_wait_budget} cycles = "
                f"{self.cfg.axi_timeout_ns} ns agent timeout)"
            )

    @staticmethod
    def _where(channel: str, addr: int | None) -> str:
        return f" @ {channel} 0x{addr:014x}" if addr is not None else f" (no {channel} recorded)"

    async def run_phase(self) -> None:
        dut = cocotb.top
        p = self.bus_prefix
        sig = {name: getattr(dut, f"{p}_{name}", None) for name in _SIGNALS}
        required = ("rvalid", "rready", "rdata", "rresp", "bvalid", "bready", "bresp")
        missing = [f"{p}_{name}" for name in required if sig[name] is None]
        if missing:
            self._fail(f"response-channel signal(s) {', '.join(missing)} not found on the top")
            return
        self._bus_bytes = max(1, len(_bits(sig["rdata"])) // 8)

        await self.cfg.reset_done.wait()
        self.ready_wait_budget = max(1, int(self.cfg.axi_timeout_ns / self.cfg.smc_clk_period_ns))
        self.logger.info(
            "SMC AXI monitor active on %s %s bus (READY wait budget %d cycles)",
            self.port_name,
            p,
            self.ready_wait_budget,
        )
        has_aw = all(sig[n] is not None for n in ("awvalid", "awready", "wvalid", "wready"))
        has_ar = sig["arvalid"] is not None and sig["arready"] is not None

        rst = getattr(dut, "rst_primary_smc_clk_no", None)
        while True:
            await RisingEdge(dut.clk_smc_i)
            if rst is not None and _value(rst) == 0:
                self.pending_ar.clear()
                self.pending_aw.clear()
                for chan in self._ready_wait:
                    self._ready_wait[chan] = 0
                continue
            if has_aw:
                self._tick_ready_wait("aw", _hi(sig["awvalid"]) and not _hi(sig["awready"]))
                self._tick_ready_wait("w", _hi(sig["wvalid"]) and not _hi(sig["wready"]))
            if has_ar:
                self._tick_ready_wait("ar", _hi(sig["arvalid"]) and not _hi(sig["arready"]))
                if _hi(sig["arvalid"]) and _hi(sig["arready"]):
                    self._record_ar(sig)
            if sig["awvalid"] is not None and _hi(sig["awvalid"]) and _hi(sig["awready"]):
                self.pending_aw.setdefault(self._key(sig["awid"]), deque()).append(
                    _value(sig["awaddr"])
                )

            if _hi(sig["rvalid"]) and _hi(sig["rready"]):
                self.r_beats += 1
                ar = self._join_r(sig)
                addr = ar["addr"] if ar is not None else None
                where = self._where("AR", addr)
                code = _value(sig["rresp"])
                self.resp_tally[code if code in (0, 1, 2, 3) else None] += 1
                exempt = ar is not None and ar["exempt"]
                if exempt:
                    self.r_beats_exempt += 1
                elif ar is not None and code in (0, 1):
                    self._check_lanes(sig, ar, where)
                elif (self.all_x_any_resp or code in (0, 1)) and _is_all_x(sig["rdata"]):
                    self._fail(f"R beat returned all-X data{where}")
                if code == 3:
                    self._decerr("R", addr, where)

            if _hi(sig["bvalid"]) and _hi(sig["bready"]):
                self.b_resps += 1
                key = self._key(sig["bid"])
                queue = self.pending_aw.get(key)
                if queue:
                    addr = queue.popleft()
                else:
                    self._unmatched("B", key)
                    addr = None
                where = self._where("AW", addr)
                if _value(sig["bresp"]) == 3:
                    self._decerr("B", addr, where)

    def _decerr(self, channel: str, addr: int | None, where: str) -> None:
        if not self.fail_decerr or self._decerr_expected(addr):
            self.logger.info("%s %s beat DECERR (expected)%s", self.port_name, channel, where)
        else:
            self._fail(f"{channel} beat returned DECERR{where}")

    def _need_plusarg(self) -> str:
        return "axi_sva_need_" + self.port_name.lower().replace("-", "_")

    def check_phase(self) -> None:
        self.logger.info(
            "OBS-AXI-MON-BUDGET: port=%s aw=%d w=%d ar=%d budget=%d sf=SF-016",
            self.port_name,
            self.max_ready_wait["aw"],
            self.max_ready_wait["w"],
            self.max_ready_wait["ar"],
            self.ready_wait_budget,
        )
        need = self._need_plusarg()
        if need in cocotb.plusargs and (self.ar_count == 0 or self.lanes_checked == 0):
            self._fail(
                f"+{need} names this port but the monitor saw ar={self.ar_count} "
                f"lanes_checked={self.lanes_checked}: the port was not driven or the "
                f"monitor is not bound to it"
            )
        assert not self.errors, (
            f"SMC AXI monitor {self.port_name} found {len(self.errors)} protocol error(s): "
            + "; ".join(self.errors[:8])
        )
        self.logger.info(
            "CHK-AXI-MON-%s: ar=%d r_beats=%d b=%d lanes_checked=%d max_ready_wait=%d",
            self.port_name,
            self.ar_count,
            self.r_beats,
            self.b_resps,
            self.lanes_checked,
            max(self.max_ready_wait.values()),
        )
        self.logger.info(
            "SMC AXI monitor %s: %d R beats (%d exempt, from %d exempt ARs in %d declared "
            "reads), %d B resps, %d without a matching request; R-resp tally %s; 0 errors",
            self.port_name,
            self.r_beats,
            self.r_beats_exempt,
            self.ar_exempt,
            self.declared_reads,
            self.b_resps,
            self.unmatched_resps,
            ", ".join(f"{_RESP_NAME[k]}={v}" for k, v in self.resp_tally.items() if v),
        )
