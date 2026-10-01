# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cycle-level AXI4/AXI4-Lite protocol-rule watchers (practical subset).

Pure-Python signal sampling (RisingEdge + ReadOnly) that sleeps while every
VALID is low, Verilator-friendly — no SVA. Rule provenance: implemented from
the public AMBA AXI4 specification (ARM IHI 0022) rule descriptions; no
third-party protocol-checker source was consulted or copied.

Rules
-----
AXI-<CH>-STABLE   payload signals unchanged while VALID && !READY
AXI-<CH>-HOLD     VALID stays asserted until the READY handshake
AXI-RESET-VALID   VALID low while reset is asserted
AXI-W-LAST        WLAST asserted exactly on beat AWLEN+1 of the paired AW
AXI-R-LAST        RLAST asserted exactly on the final beat of the per-ID AR

The AXI-Lite watcher applies the STABLE/HOLD/RESET-VALID subset only.
Findings are retained (never raised from the sampling task); the owning test
or scoreboard reports them once through ``report()`` and finalizes.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

import cocotb
from cocotb.task import Task
from cocotb.triggers import FallingEdge, RisingEdge
from cocotb.utils import get_sim_time
from cocotbext.axi import AxiBus, AxiLiteBus

from .ocah_axi_sampling import is_high, next_sample, valid_handles

__all__ = [
    "OcahAxiWatchFinding",
    "OcahAxiProtocolWatcher",
    "OcahAxiLiteProtocolWatcher",
]

_MAX_FINDINGS = 256

_AXI4_PAYLOAD = {
    "aw": (
        "awaddr",
        "awid",
        "awlen",
        "awsize",
        "awburst",
        "awlock",
        "awcache",
        "awprot",
        "awqos",
        "awregion",
        "awuser",
    ),
    "w": ("wdata", "wstrb", "wlast", "wuser"),
    "b": ("bid", "bresp", "buser"),
    "ar": (
        "araddr",
        "arid",
        "arlen",
        "arsize",
        "arburst",
        "arlock",
        "arcache",
        "arprot",
        "arqos",
        "arregion",
        "aruser",
    ),
    "r": ("rid", "rdata", "rresp", "rlast", "ruser"),
}

_LITE_PAYLOAD = {
    "aw": ("awaddr", "awprot"),
    "w": ("wdata", "wstrb"),
    "b": ("bresp",),
    "ar": ("araddr", "arprot"),
    "r": ("rdata", "rresp"),
}


@dataclass(frozen=True)
class OcahAxiWatchFinding:
    """One retained cycle-level protocol finding."""

    rule: str
    channel: str
    time_ns: float
    message: str


def _sig(obj, name: str):
    return getattr(obj, name, None)


def _sig_int(obj, name: str, default: int = 0) -> int:
    sig = _sig(obj, name)
    if sig is None:
        return default
    try:
        return int(sig.value)
    except Exception:  # noqa: BLE001 - unresolved simulator handles
        return default


def _payload_tuple(obj, names: tuple[str, ...]) -> tuple[int, ...]:
    return tuple(_sig_int(obj, name, -1) for name in names if _sig(obj, name) is not None)


class _BaseProtocolWatcher:
    """Shared sampling loop and finding retention."""

    _payload_map: dict[str, tuple[str, ...]] = {}
    _check_bursts = False

    def __init__(
        self,
        intf,
        clock,
        *,
        reset=None,
        reset_active_level: bool = True,
        prefix: str | None = None,
        name: str = "OcahAxiProtocolWatcher",
        max_findings: int = _MAX_FINDINGS,
        logger: logging.Logger | None = None,
    ) -> None:
        self.name = name
        self.clock = clock
        self.reset = reset
        self.reset_active_level = reset_active_level
        self.max_findings = max_findings
        self.log = logger or logging.getLogger(name)
        self.bus = self._coerce_bus(intf, prefix)
        self.errors: list[OcahAxiWatchFinding] = []
        self._rule_totals: dict[str, int] = {}
        self._task: Task[None] | None = None
        self._running = False
        # Per-channel previous-cycle shadow: (valid, ready, payload tuple); the
        # payload is None on a cycle that sampled none.
        self._shadow: dict[str, tuple[int, int, tuple[int, ...] | None]] = {}
        # Burst tracking (AXI4 only)
        self._aw_lengths: deque[int] = deque()
        self._early_wburst_lens: deque[int] = deque()
        self._w_beats = 0
        self._ar_lengths: dict[int, deque[int]] = {}
        self._r_beats: dict[int, int] = {}
        self._valid_handles: list[Any] | None = None

    @classmethod
    def from_prefix(cls, dut, prefix: str, clock, **kwargs: Any):
        """Construct from flattened bus signals."""
        return cls(dut, clock, prefix=prefix, **kwargs)

    @staticmethod
    def _coerce_bus(intf, prefix: str | None):
        raise NotImplementedError

    async def start(self) -> None:
        """Start passive rule watching."""
        if self._running:
            return
        self._running = True
        self._task = cocotb.start_soon(self._run())
        self.log.info("%s: protocol watching started", self.name)

    def halt(self) -> None:
        """Synchronously stop rule watching; retained findings survive."""
        self._running = False
        if self._task is not None:
            self._task.kill()
            self._task = None
        self.log.info("%s: protocol watching stopped", self.name)

    async def stop(self) -> None:
        """Stop passive rule watching (async wrapper around halt())."""
        self.halt()

    def rule_counts(self) -> dict[str, int]:
        """Return total finding counts per rule (including beyond retention)."""
        return dict(self._rule_totals)

    def finding_count(self) -> int:
        return sum(self._rule_totals.values())

    def clear(self) -> None:
        """Discard retained findings and rule counts."""
        self.errors.clear()
        self._rule_totals.clear()

    def assert_clean(self) -> None:
        """Raise if any protocol findings were retained."""
        if not self.finding_count():
            return
        joined = "\n".join(finding.message for finding in self.errors)
        raise AssertionError(
            f"{self.name}: {self.finding_count()} protocol rule violation(s):\n{joined}"
        )

    def report(
        self,
        evidence,
        *,
        check_id: str = "CHK-AXI-PROTOCOL",
        context: str = "",
    ) -> bool:
        """Emit one named evidence check requiring zero findings."""
        rules = self.rule_counts()
        return evidence.expect_equal(
            check_id,
            self.finding_count(),
            0,
            context=f"{context} rules={rules if rules else '{}'}".strip(),
        )

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def _in_reset(self) -> bool:
        if self.reset is None:
            return False
        try:
            value = int(self.reset.value)
        except Exception:  # noqa: BLE001
            return False
        return bool(value) == bool(self.reset_active_level)

    def _channels(self) -> dict[str, Any]:
        return {
            "aw": self.bus.write.aw,
            "w": self.bus.write.w,
            "b": self.bus.write.b,
            "ar": self.bus.read.ar,
            "r": self.bus.read.r,
        }

    def _idle_wake(self) -> list[Any] | None:
        """Return the wake triggers while every VALID is low, else None.

        A cycle with every VALID low changes no watcher state; a reset that
        asserts meanwhile still clears the shadow and burst state.
        """
        if self._valid_handles is None:
            self._valid_handles = valid_handles(self.bus)
        if any(is_high(handle) for handle in self._valid_handles):
            return None
        wake: list[Any] = [RisingEdge(handle) for handle in self._valid_handles]
        if self.reset is not None:
            wake.append(
                RisingEdge(self.reset) if self.reset_active_level else FallingEdge(self.reset)
            )
        return wake

    async def _run(self) -> None:
        valid_names = {
            "aw": "awvalid",
            "w": "wvalid",
            "b": "bvalid",
            "ar": "arvalid",
            "r": "rvalid",
        }
        ready_names = {
            "aw": "awready",
            "w": "wready",
            "b": "bready",
            "ar": "arready",
            "r": "rready",
        }

        sampled = False
        while self._running:
            await next_sample(self.clock, self._idle_wake() if sampled else None)
            sampled = True

            channels = self._channels()
            in_reset = self._in_reset()

            if in_reset:
                for channel, obj in channels.items():
                    if _sig_int(obj, valid_names[channel]):
                        self._record(
                            "AXI-RESET-VALID",
                            channel,
                            f"{valid_names[channel]} asserted while reset is active",
                        )
                self._shadow.clear()
                self._flush_burst_state()
                continue

            for channel, obj in channels.items():
                valid = _sig_int(obj, valid_names[channel])
                ready = _sig_int(obj, ready_names[channel])
                previous = self._shadow.get(channel)
                stalled = previous is not None and bool(previous[0]) and not previous[1]
                # STABLE compares payloads only across a stall, so a beat is
                # sampled only while it stalls or was stalled the cycle before.
                payload = (
                    _payload_tuple(obj, self._payload_map[channel])
                    if valid and (stalled or not ready)
                    else None
                )

                if previous is not None:
                    prev_valid, prev_ready, prev_payload = previous
                    if prev_valid and not prev_ready:
                        if not valid:
                            self._record(
                                "AXI-" + channel.upper() + "-HOLD",
                                channel,
                                "VALID deasserted before READY handshake",
                            )
                        elif payload != prev_payload:
                            self._record(
                                "AXI-" + channel.upper() + "-STABLE",
                                channel,
                                f"payload changed while stalled: {prev_payload} -> {payload}",
                            )
                self._shadow[channel] = (valid, ready, payload)

            if self._check_bursts:
                self._track_bursts(channels)

    def _flush_burst_state(self) -> None:
        self._aw_lengths.clear()
        self._early_wburst_lens.clear()
        self._w_beats = 0
        self._ar_lengths.clear()
        self._r_beats.clear()

    def _track_bursts(self, channels: dict[str, Any]) -> None:
        aw = channels["aw"]
        w = channels["w"]
        ar = channels["ar"]
        r = channels["r"]

        if _sig_int(aw, "awvalid") and _sig_int(aw, "awready"):
            if self._early_wburst_lens:
                # A W burst completed before this AW (legal): check its
                # length retroactively against AWLEN+1.
                early_len = self._early_wburst_lens.popleft()
                expected = _sig_int(aw, "awlen") + 1
                if early_len != expected:
                    self._record(
                        "AXI-W-LAST",
                        "w",
                        f"early W burst had {early_len} beats, AWLEN+1 = {expected}",
                    )
            else:
                self._aw_lengths.append(_sig_int(aw, "awlen") + 1)

        if _sig_int(w, "wvalid") and _sig_int(w, "wready"):
            self._w_beats += 1
            last = _sig_int(w, "wlast", 1)
            expected = self._aw_lengths[0] if self._aw_lengths else None
            if last:
                if expected is not None and self._w_beats != expected:
                    self._record(
                        "AXI-W-LAST",
                        "w",
                        f"WLAST on beat {self._w_beats}, expected beat {expected}",
                    )
                if self._aw_lengths:
                    self._aw_lengths.popleft()
                else:
                    # No AW yet: retro-checked at AW acceptance above.
                    self._early_wburst_lens.append(self._w_beats)
                self._w_beats = 0
            elif expected is not None and self._w_beats >= expected:
                self._record(
                    "AXI-W-LAST",
                    "w",
                    f"missing WLAST: beat {self._w_beats} reached AWLEN+1 = {expected}",
                )

        if _sig_int(ar, "arvalid") and _sig_int(ar, "arready"):
            arid = _sig_int(ar, "arid")
            self._ar_lengths.setdefault(arid, deque()).append(_sig_int(ar, "arlen") + 1)

        if _sig_int(r, "rvalid") and _sig_int(r, "rready"):
            rid = _sig_int(r, "rid")
            self._r_beats[rid] = self._r_beats.get(rid, 0) + 1
            beats = self._r_beats[rid]
            per_id = self._ar_lengths.get(rid)
            expected = per_id[0] if per_id else None
            if _sig_int(r, "rlast", 1):
                if expected is not None and beats != expected:
                    self._record(
                        "AXI-R-LAST",
                        "r",
                        f"RLAST on beat {beats} for id={rid}, expected beat {expected}",
                    )
                if per_id:
                    per_id.popleft()
                self._r_beats[rid] = 0
            elif expected is not None and beats >= expected:
                self._record(
                    "AXI-R-LAST",
                    "r",
                    f"missing RLAST: beat {beats} for id={rid} reached ARLEN+1 = {expected}",
                )

    def _record(self, rule: str, channel: str, detail: str) -> None:
        self._rule_totals[rule] = self._rule_totals.get(rule, 0) + 1
        time_ns = float(get_sim_time("ns"))
        message = f"{rule}: {detail} (channel={channel} time={time_ns}ns)"
        if len(self.errors) < self.max_findings:
            self.errors.append(
                OcahAxiWatchFinding(rule=rule, channel=channel, time_ns=time_ns, message=message)
            )
        self.log.error("%s: %s", self.name, message)


class OcahAxiProtocolWatcher(_BaseProtocolWatcher):
    """AXI4 cycle-level rule watcher (full practical subset)."""

    _payload_map = _AXI4_PAYLOAD
    _check_bursts = True

    @staticmethod
    def _coerce_bus(intf, prefix: str | None):
        if isinstance(intf, AxiBus):
            return intf
        if prefix is not None:
            return AxiBus.from_prefix(intf, prefix)
        return AxiBus.from_entity(intf)


class OcahAxiLiteProtocolWatcher(_BaseProtocolWatcher):
    """AXI4-Lite cycle-level rule watcher (STABLE/HOLD/RESET-VALID subset)."""

    _payload_map = _LITE_PAYLOAD
    _check_bursts = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("name", "OcahAxiLiteProtocolWatcher")
        super().__init__(*args, **kwargs)

    @staticmethod
    def _coerce_bus(intf, prefix: str | None):
        if isinstance(intf, AxiLiteBus):
            return intf
        if prefix is not None:
            return AxiLiteBus.from_prefix(intf, prefix)
        return AxiLiteBus.from_entity(intf)
