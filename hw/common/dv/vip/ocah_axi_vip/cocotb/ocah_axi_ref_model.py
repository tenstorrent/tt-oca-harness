# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stateful AXI/AXI-Lite reference model: shadow memory + response expectations.

Pure Python (no cocotb imports) so scoreboard mechanics can be validated without
a simulator. Follows the stateful-model contract of
``hw/common/dv/docs/vip-checker-model.adoc``: deterministic initial state,
explicit ``reset()``, defined update order (response resolved before any memory
commit), snapshot/query APIs, and bounded retained history.

One-shot expected errors mirror the alignment semantics of
``OcahFaultMixin.inject_error``: expectations are stored and consumed at
beat-aligned word addresses (``addr // beat_bytes * beat_bytes``), so a test
that arms the fault responder and the model with the same address always pairs
the injected and the predicted response.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .ocah_axi_types import RESP_EXOKAY, RESP_OKAY

_SUCCESS_RESPS = (RESP_OKAY, RESP_EXOKAY)

BURST_FIXED = 0
BURST_INCR = 1
BURST_WRAP = 2


@dataclass(frozen=True)
class OcahAxiRegionExpectation:
    """Address-region response policy for the reference model."""

    base: int
    size: int
    read_resp: int = RESP_OKAY
    write_resp: int = RESP_OKAY
    blocked: bool = False
    label: str = ""

    def contains(self, address: int) -> bool:
        return self.base <= int(address) < self.base + self.size

    def overlaps(self, lo: int, hi: int) -> bool:
        """True when the byte span [lo, hi) intersects this region."""
        return int(lo) < self.base + self.size and self.base < int(hi)

    def expected_resp(self, direction: str) -> int:
        return self.read_resp if direction == "read" else self.write_resp


@dataclass(frozen=True)
class OcahAxiPrediction:
    """Immutable expected outcome for one AXI transaction."""

    direction: str
    address: int
    resp: int
    resp_list: tuple[int, ...] = ()  # per beat (reads); single worst (writes)
    data_words: tuple[int, ...] = ()
    strobes: tuple[int, ...] = ()
    blocked: bool = False
    context: str = ""


class OcahAxiRefModel:
    """Sparse strobe-masked shadow memory with expected-response policy."""

    def __init__(
        self,
        *,
        name: str = "OcahAxiRefModel",
        beat_bytes: int = 8,
        fill: int = 0x00,
        max_history: int = 1024,
        logger: logging.Logger | None = None,
    ) -> None:
        if beat_bytes <= 0:
            raise ValueError(f"beat_bytes must be positive, got {beat_bytes}")
        if not 0 <= int(fill) <= 0xFF:
            raise ValueError(f"fill must be a byte value, got {fill}")
        self.name = name
        self.beat_bytes = int(beat_bytes)
        self.fill = int(fill)
        self.max_history = int(max_history)
        self.log = logger or logging.getLogger(name)
        self._mem: dict[int, int] = {}
        self._regions: list[OcahAxiRegionExpectation] = []
        self._read_errors: dict[int, int] = {}
        self._write_errors: dict[int, int] = {}
        self.history: list[OcahAxiPrediction] = []

    # ------------------------------------------------------------------
    # Expectation policy
    # ------------------------------------------------------------------

    def add_region(self, region: OcahAxiRegionExpectation) -> None:
        """Register an address-region response expectation (first match wins)."""
        self._regions.append(region)

    def clear_regions(self) -> None:
        self._regions.clear()

    def region_for(self, address: int) -> OcahAxiRegionExpectation | None:
        for region in self._regions:
            if region.contains(address):
                return region
        return None

    def expect_error(
        self,
        addr: int,
        resp: int,
        *,
        read: bool = True,
        write: bool = True,
    ) -> None:
        """Arm a one-shot expected non-OKAY response at a beat-aligned address."""
        aligned = self._align(addr)
        if read:
            self._read_errors[aligned] = int(resp)
        if write:
            self._write_errors[aligned] = int(resp)
        self.log.info(
            "%s: expecting resp=%d addr=0x%08x (aligned 0x%08x) read=%d write=%d",
            self.name,
            int(resp),
            int(addr),
            aligned,
            read,
            write,
        )

    def clear_expected_errors(self) -> None:
        self._read_errors.clear()
        self._write_errors.clear()

    def pending_expected_errors(self) -> int:
        """Count armed one-shot expectations not yet consumed by a prediction."""
        return len(self._read_errors) + len(self._write_errors)

    def expected_response(self, *, address: int, direction: str) -> int:
        """Peek the expected response without consuming one-shot expectations."""
        aligned = self._align(address)
        table = self._read_errors if direction == "read" else self._write_errors
        if aligned in table:
            return table[aligned]
        region = self.region_for(address)
        if region is not None:
            return region.expected_resp(direction)
        return RESP_OKAY

    def is_blocked(self, address: int) -> bool:
        """True when policy declares this address must never produce traffic."""
        return self.is_blocked_span(address, 1)

    def is_blocked_span(self, address: int, nbytes: int) -> bool:
        """True when ANY byte of [address, address+nbytes) is in a blocked region.

        Span overlap, not point lookup: a blocked region smaller than (or
        offset within) a bus word must still flag the beat that covers it.
        """
        lo = int(address)
        hi = lo + int(nbytes)
        return any(region.blocked and region.overlaps(lo, hi) for region in self._regions)

    # ------------------------------------------------------------------
    # Prediction (stateful; update order: resolve resp, then commit memory)
    # ------------------------------------------------------------------

    def predict_write(
        self,
        *,
        address: int,
        data_words,
        strobes=(),
        size: int | None = None,
        burst: int | None = None,
    ) -> OcahAxiPrediction:
        """Predict one write transaction and commit OKAY beats to shadow memory."""
        words = tuple(int(word) for word in data_words)
        strobe_list = tuple(int(strobe) for strobe in strobes)
        beat_addrs = self._beat_addresses(address, len(words), size, burst)
        # Blocked if any byte the burst ACTUALLY touches overlaps a blocked
        # region: precise per-beat spans, so a narrow transfer next to a
        # blocked byte in the same bus word is not falsely flagged, while a
        # sub-word blocked byte inside the touched span still is.
        blocked = any(
            self.is_blocked_span(lo, hi - lo)
            for lo, hi in self._beat_spans(address, len(words), size, burst)
        )
        beat_resps: list[int] = []
        commits: list[tuple[int, int, int]] = []

        for beat_index, word_addr in enumerate(beat_addrs):
            resp = self._write_errors.pop(word_addr, None)
            if resp is None:
                region = self.region_for(word_addr)
                resp = region.write_resp if region is not None else RESP_OKAY
            beat_resps.append(int(resp))
            if int(resp) in _SUCCESS_RESPS and not blocked and beat_index < len(words):
                strobe = (
                    strobe_list[beat_index]
                    if beat_index < len(strobe_list)
                    else (1 << self.beat_bytes) - 1
                )
                commits.append((word_addr, words[beat_index], strobe))

        worst = max(beat_resps) if beat_resps else RESP_OKAY
        for word_addr, word, strobe in commits:
            self._commit_word(word_addr, word, strobe)

        prediction = OcahAxiPrediction(
            direction="write",
            address=int(address),
            resp=worst,
            # The bus collapses the write burst to one B response.
            resp_list=(worst,),
            data_words=words,
            strobes=strobe_list,
            blocked=blocked,
            context=f"addr=0x{int(address):x} beats={len(words)} resp={worst}",
        )
        self._retain(prediction)
        return prediction

    def predict_read(
        self,
        *,
        address: int,
        beat_count: int = 1,
        size: int | None = None,
        burst: int | None = None,
    ) -> OcahAxiPrediction:
        """Predict one read transaction from shadow memory and armed expectations."""
        beat_addrs = self._beat_addresses(address, max(beat_count, 1), size, burst)
        blocked = any(
            self.is_blocked_span(lo, hi - lo)
            for lo, hi in self._beat_spans(address, max(beat_count, 1), size, burst)
        )
        beat_resps: list[int] = []
        words: list[int] = []

        for word_addr in beat_addrs:
            resp = self._read_errors.pop(word_addr, None)
            if resp is None:
                region = self.region_for(word_addr)
                resp = region.read_resp if region is not None else RESP_OKAY
            beat_resps.append(int(resp))
            if int(resp) in _SUCCESS_RESPS:
                # OKAY and EXOKAY are both success completions: predicted
                # readback data is checked for either.
                words.append(self.read_word(word_addr, self.beat_bytes))
            else:
                # Error beats return no valid data; the fault responder drives 0.
                words.append(0)

        worst = max(beat_resps) if beat_resps else RESP_OKAY
        prediction = OcahAxiPrediction(
            direction="read",
            address=int(address),
            resp=worst,
            resp_list=tuple(beat_resps),
            data_words=tuple(words),
            blocked=blocked,
            context=f"addr=0x{int(address):x} beats={beat_count} resp={worst}",
        )
        self._retain(prediction)
        return prediction

    # ------------------------------------------------------------------
    # Snapshot / query / backdoor mirror
    # ------------------------------------------------------------------

    def read_bytes(self, address: int, length: int) -> bytes:
        """Snapshot shadow-memory bytes (unwritten bytes read as fill)."""
        return bytes(
            self._mem.get(int(address) + offset, self.fill) for offset in range(int(length))
        )

    def read_word(self, address: int, nbytes: int) -> int:
        """Snapshot one little-endian shadow-memory word."""
        return int.from_bytes(self.read_bytes(address, nbytes), "little")

    def write_bytes(self, address: int, data: bytes | bytearray) -> None:
        """Backdoor mirror for test preloads (keeps model aligned with the RAM)."""
        for offset, value in enumerate(bytes(data)):
            self._mem[int(address) + offset] = value

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self, *, keep_regions: bool = True) -> None:
        """Clear memory, one-shot expectations, and history deterministically."""
        self._mem.clear()
        self._read_errors.clear()
        self._write_errors.clear()
        self.history.clear()
        if not keep_regions:
            self._regions.clear()

    def clear(self) -> None:
        self.reset()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _align(self, address: int) -> int:
        return (int(address) // self.beat_bytes) * self.beat_bytes

    def _beat_addresses(
        self,
        address: int,
        beats: int,
        size: int | None,
        burst: int | None,
    ) -> list[int]:
        """Word addresses touched by each beat (FIXED/INCR/WRAP arithmetic)."""
        num_bytes = 2 ** int(size) if size is not None else self.beat_bytes
        aligned = (int(address) // num_bytes) * num_bytes
        burst_code = BURST_INCR if burst is None else int(burst)
        transfer = num_bytes * max(beats, 1)
        lower_wrap = (int(address) // transfer) * transfer if transfer else aligned
        upper_wrap = lower_wrap + transfer

        addresses: list[int] = []
        cur = aligned
        for _ in range(max(beats, 1)):
            addresses.append(self._align(cur))
            if burst_code != BURST_FIXED:
                cur += num_bytes
                if burst_code == BURST_WRAP and cur == upper_wrap:
                    cur = lower_wrap
        return addresses

    def _beat_spans(
        self,
        address: int,
        beats: int,
        size: int | None,
        burst: int | None,
    ) -> list[tuple[int, int]]:
        """Byte spans [lo, hi) each beat actually touches (transfer-size wide).

        Beat 0 of an unaligned access touches [address, aligned+num_bytes);
        later INCR beats touch full size-aligned windows; FIXED re-touches the
        first window every beat. Used for blocked-region overlap so narrow
        transfers sharing a bus word with a blocked byte are judged by the
        bytes they touch, not the whole word.
        """
        num_bytes = 2 ** int(size) if size is not None else self.beat_bytes
        aligned = (int(address) // num_bytes) * num_bytes
        burst_code = BURST_INCR if burst is None else int(burst)
        transfer = num_bytes * max(beats, 1)
        lower_wrap = (int(address) // transfer) * transfer if transfer else aligned
        upper_wrap = lower_wrap + transfer

        spans: list[tuple[int, int]] = []
        cur = aligned
        first = True
        for _ in range(max(beats, 1)):
            lo = int(address) if (first or burst_code == BURST_FIXED) else cur
            spans.append((lo, cur + num_bytes))
            first = False
            if burst_code != BURST_FIXED:
                cur += num_bytes
                if burst_code == BURST_WRAP and cur == upper_wrap:
                    cur = lower_wrap
        return spans

    def _commit_word(self, word_addr: int, word: int, strobe: int) -> None:
        data = int(word).to_bytes(self.beat_bytes, "little")
        for lane in range(self.beat_bytes):
            if (int(strobe) >> lane) & 0x1:
                self._mem[word_addr + lane] = data[lane]

    def _retain(self, prediction: OcahAxiPrediction) -> None:
        self.history.append(prediction)
        if len(self.history) > self.max_history:
            self.history.pop(0)
