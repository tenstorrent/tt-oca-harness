# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SPI data scoreboard: stimulus, wire and device compared byte for byte.

A leaf tells the scoreboard what it expects:

* ``expect_tx(addr, data, opcode=PAGE_PROGRAM)``: a program the stimulus
  sent from the DUT to the flash (the payload the leaf or its firmware
  queued); ``opcode`` names the program command, e.g. QUAD PAGE PROGRAM;
* ``expect_rx(opcode, data)``: bytes the DUT delivered from a read (what the
  leaf read from RXDATA or a DMA destination);
* ``expect_frame(mark, segments, delivered=...)``: one frame of raw command
  segments with no flash command behind it. ``mark`` is ``frame_mark()``
  taken before the leaf issued the frame; each segment is ``(lanes, "tx",
  bytes)``, ``(lanes, "rx", bytes)`` (the bytes the testbench drove) or
  ``(lanes, "dummy", clocks)``, and ``delivered`` is what the DUT returned for
  the rx segments, in order.

``finish()`` matches each expectation with one flash record and the monitor
frame at the same position (``SepSpiWireMonitor.finish`` grades
``CHK-SPI-LEDGER`` first, so the two lists line up). The wire bytes are the
monitor's own decode of the data phase at the command's lane width, from the
pad taps, so neither the flash model nor the leaf supplies them:

* ``CHK-SPI-SB-TX``: expected payload == monitor wire decode == flash
  ``data_in``, and the flash accepted the frame.
* ``CHK-SPI-SB-RX``: bytes the DUT delivered == flash ``data_out`` prefix ==
  monitor wire decode prefix.
* ``CHK-SPI-SB-FRAME``: the frame at ``mark`` has exactly the sample edges of
  its segments; each tx segment's wire decode equals its bytes, each rx
  segment's wire decode equals the bytes driven, and ``delivered`` equals the
  rx bytes. A lane-1 segment decodes lane 0 out and lane 1 in; a 2- or 4-lane
  segment decodes its low lanes, the least significant on lane 0.

A transmit decode (the TX payload from the lanes, and every tx segment) also
needs each beat's data lane output enables to equal the segment's lanes
exactly (x1 0001, x2 0011, x4 1111); a beat with another pattern is a
mismatch. Receive and dummy beats are not graded for their enables.

Each direction with expectations logs one line with its frame and byte
counts; a scoreboard with no expectation at all fails. A program or read is
matched to the first unused flash record with exactly its opcode (and address
for a program), so a record of another program command does not satisfy it;
a missing match fails. ``flash`` may be ``None`` for a leaf with raw
frames only; a program or read expectation then fails.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ocah_spi_vip import OcahSpiFlash, OcahSpiOpcode, command_format, lanes_to_bytes

from env.sep_spi_wire_monitor import SepSpiWireMonitor

__all__ = ["SepSpiScoreboard"]


@dataclass
class _Expect:
    kind: str  # "tx" or "rx"
    opcode: int | None
    addr: int | None
    data: bytes
    label: str


@dataclass
class _Frame:
    mark: int
    segments: tuple[tuple[int, str, Any], ...]
    delivered: bytes
    label: str


@dataclass
class _Tally:
    frames: int = 0
    bytes: int = 0
    lines: list[str] = field(default_factory=list)


class SepSpiScoreboard:
    """Byte-for-byte compare of stimulus, the monitor wire decode, and the flash records."""

    def __init__(
        self,
        wire: SepSpiWireMonitor,
        flash: OcahSpiFlash | None,
        logger: logging.Logger,
        *,
        seed: int,
    ) -> None:
        self.wire = wire
        self.flash = flash
        self.logger = logger
        self.seed = seed
        self._expects: list[_Expect] = []
        self._frames: list[_Frame] = []
        self._addr_bytes = flash.addr_bytes if flash is not None else 0

    def expect_tx(
        self,
        addr: int,
        data: bytes,
        *,
        label: str = "",
        opcode: int = OcahSpiOpcode.PAGE_PROGRAM,
    ) -> None:
        """A program the stimulus sent: ``data`` must reach the wire and the flash at ``addr``.

        Only a flash record with exactly ``opcode`` (PAGE PROGRAM by default)
        matches.
        """
        if not data:
            raise ValueError(f"expect_tx addr=0x{addr:06x}: a program carries at least one byte")
        fmt = command_format(int(opcode))
        if fmt is None or fmt.response:
            raise ValueError(f"expect_tx opcode=0x{int(opcode):02x}: not a program command")
        self._expects.append(_Expect("tx", int(opcode), addr, bytes(data), label))

    def expect_rx(self, opcode: int, data: bytes, *, label: str = "") -> None:
        """Bytes the DUT delivered from a read with ``opcode``."""
        self._expects.append(_Expect("rx", int(opcode), None, bytes(data), label))

    def frame_mark(self) -> int:
        """Index the next monitor frame will take; pass it to ``expect_frame``."""
        return len(self.wire.monitor.get_transactions())

    def expect_frame(
        self,
        mark: int,
        segments: Sequence[tuple[int, str, Any]],
        *,
        delivered: bytes = b"",
        label: str = "",
    ) -> None:
        """A frame of raw segments: its wire decode must equal ``segments``."""
        for lanes, kind, _ in segments:
            if lanes not in (1, 2, 4) or kind not in ("tx", "rx", "dummy"):
                raise ValueError(f"bad segment lanes={lanes} kind={kind!r}")
        self._frames.append(_Frame(mark, tuple(segments), bytes(delivered), label))

    def finish(self) -> None:
        """Grade every expectation; raise on the first mismatch or on no expectation."""
        frames = self.wire.monitor.get_transactions()
        if not self._expects and not self._frames:
            raise AssertionError(f"CHK-SPI-SB FAIL seed={self.seed} no expectation was registered")
        if self._expects and self.flash is None:
            raise AssertionError(
                f"CHK-SPI-SB FAIL seed={self.seed} program or read expected with no flash model"
            )
        self._finish_frames(frames)
        if not self._expects:
            return
        records = self.flash.get_transactions() if self.flash is not None else []
        used: set[int] = set()
        tallies = {"tx": _Tally(), "rx": _Tally()}
        for exp in self._expects:
            index = self._match(exp, records, used)
            if index is None:
                raise AssertionError(
                    f"CHK-SPI-SB-{exp.kind.upper()} FAIL seed={self.seed} {exp.label} "
                    f"no flash record for opcode={exp.opcode} addr={exp.addr} "
                    f"records={len(records)}"
                )
            used.add(index)
            rec = records[index]
            frame = frames[index] if index < len(frames) else None
            n = len(exp.data)
            if exp.kind == "tx":
                got = _wire_data(frame, rec["opcode"], self._addr_bytes, response=False)
                device = bytes(rec["data_in"])
            else:
                got = _wire_data(frame, rec["opcode"], self._addr_bytes, response=True, limit=n)
                device = bytes(rec["data_out"])[:n]
            wire = b"" if got is None else got[:n] if exp.kind == "rx" else got
            ok = n > 0 and got is not None and wire == exp.data and device == exp.data
            if exp.kind == "tx":
                ok = ok and bool(rec["ok"])
            line = (
                f"{exp.label} record={index} opcode=0x{rec['opcode']:02x} addr=0x{rec['addr']:06x} "
                f"bytes={len(exp.data)} expected={exp.data.hex()} "
                f"wire={'X/Z' if got is None else wire.hex()} "
                f"device={device.hex()} accepted={rec['ok']}"
            )
            if not ok:
                raise AssertionError(f"CHK-SPI-SB-{exp.kind.upper()} FAIL seed={self.seed} {line}")
            tally = tallies[exp.kind]
            tally.frames += 1
            tally.bytes += len(exp.data)
            tally.lines.append(line)
        for kind, tally in tallies.items():
            if not tally.frames:
                continue
            for line in tally.lines:
                self.logger.info("SPI-SB %s %s", kind.upper(), line)
            self.logger.info(
                "CHK-SPI-SB-%s PASS seed=%d frames=%d bytes=%d",
                kind.upper(),
                self.seed,
                tally.frames,
                tally.bytes,
            )

    def _finish_frames(self, frames: list[dict]) -> None:
        """Grade every raw-segment frame (``CHK-SPI-SB-FRAME``)."""
        if not self._frames:
            return
        total = 0
        for exp in self._frames:
            frame = frames[exp.mark] if exp.mark < len(frames) else None
            beats = tuple(frame.get("beats") or ()) if frame is not None else ()
            need = sum(_segment_clocks(seg) for seg in exp.segments)
            wire: list[str] = []
            ok = frame is not None and len(beats) == need
            pos = 0
            rx_driven = bytearray()
            rx_wire = bytearray()
            for lanes, kind, value in exp.segments:
                clocks = _segment_clocks((lanes, kind, value))
                if kind != "dummy" and ok:
                    field_index = 0 if kind == "tx" else 2
                    shift = 0 if kind == "tx" or lanes > 1 else 1
                    got = _decode(beats[pos : pos + clocks], field_index, lanes, shift)
                    wire.append(f"{kind}x{lanes}:{'X/Z' if got is None else got.hex()}")
                    ok = ok and got == bytes(value)
                    if kind == "rx":
                        rx_driven += bytes(value)
                        rx_wire += got or b""
                pos += clocks
            ok = ok and exp.delivered == bytes(rx_driven)
            line = (
                f"{exp.label} frame={exp.mark} beats={len(beats)} expected_beats={need} "
                f"segments={_segments_text(exp.segments)} wire={','.join(wire) or '-'} "
                f"delivered={exp.delivered.hex()}"
            )
            if not ok:
                raise AssertionError(f"CHK-SPI-SB-FRAME FAIL seed={self.seed} {line}")
            self.logger.info("SPI-SB FRAME %s", line)
            total += len(rx_wire) + sum(len(v) for _, k, v in exp.segments if k == "tx")
        self.logger.info(
            "CHK-SPI-SB-FRAME PASS seed=%d frames=%d bytes=%d", self.seed, len(self._frames), total
        )

    @staticmethod
    def _match(exp: _Expect, records: list[dict], used: set[int]) -> int | None:
        for i, rec in enumerate(records):
            if i in used or rec["opcode"] < 0:
                continue
            fmt = command_format(rec["opcode"])
            if fmt is None:
                continue
            if exp.kind == "tx" and rec["opcode"] == exp.opcode and rec["addr"] == exp.addr:
                return i
            if exp.kind == "rx" and fmt.response and rec["opcode"] == exp.opcode:
                return i
        return None


def _wire_data(
    frame: dict | None, opcode: int, addr_bytes: int, *, response: bool, limit: int | None = None
) -> bytes | None:
    """The monitor's decode of a frame's data phase at the command's lane width.

    ``None`` when a bit of the first ``limit`` bytes (all bytes by default)
    was sampled as X/Z, or, for a payload decoded from the lanes, was sampled
    with data lane output enables other than exactly its lanes.
    """
    if frame is None:
        return b""
    fmt = command_format(opcode)
    if fmt is None:
        return b""
    beats = frame.get("beats") or ()
    if not beats or (response and fmt.data_lanes == 1):
        if response and any(limit is None or i < limit for i in frame.get("data_miso_xz", ())):
            return None
        return bytes(frame["data_miso"] if response else frame["data_mosi"])
    start = fmt.input_clocks(addr_bytes) if response else 8 * (1 + addr_bytes)
    stop = None if limit is None else start + limit * 8 // fmt.data_lanes
    return _decode(beats[start:stop], 2 if response else 0, fmt.data_lanes, 0)


def _segment_clocks(segment: tuple[int, str, Any]) -> int:
    lanes, kind, value = segment
    return int(value) if kind == "dummy" else len(bytes(value)) * 8 // lanes


def _decode(beats: Sequence[tuple], field_index: int, lanes: int, shift: int) -> bytes | None:
    """Bytes of ``beats`` on ``lanes`` lanes of one beat field, lane ``shift`` first.

    ``None`` when the field is X/Z at one of the beats, or, for the controller
    output field, when a beat's data lane output enables are not exactly the
    segment's lanes (x1 0001, x2 0011, x4 1111). Receive fields are not graded
    for their enables.
    """
    if any(beat[field_index] is None for beat in beats):
        return None
    mask = (1 << lanes) - 1
    if field_index == 0 and any(beat[1] != mask for beat in beats):
        return None
    values = [beat[field_index] >> shift for beat in beats]
    return bytes(lanes_to_bytes(values, lanes)[0])


def _segments_text(segments: Sequence[tuple[int, str, Any]]) -> str:
    return "+".join(
        f"{kind}x{lanes}:{value if kind == 'dummy' else len(bytes(value))}"
        for lanes, kind, value in segments
    )
