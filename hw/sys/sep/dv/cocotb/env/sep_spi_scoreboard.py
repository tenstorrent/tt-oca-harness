# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SPI data scoreboard: stimulus, wire and device compared byte for byte.

A leaf tells the scoreboard what it expects:

* ``expect_tx(addr, data)``: a program the stimulus sent from the DUT to the
  flash (the payload the leaf or its firmware queued);
* ``expect_rx(opcode, data)``: bytes the DUT delivered from a read (what the
  leaf read from RXDATA or a DMA destination).

``finish()`` matches each expectation with one flash record and the monitor
frame at the same position (``SepSpiWireMonitor.finish`` grades
``CHK-SPI-LEDGER`` first, so the two lists line up). The wire bytes are the
monitor's own decode of the data phase at the command's lane width, from the
pad taps, so neither the flash model nor the leaf supplies them:

* ``CHK-SPI-SB-TX``: expected payload == monitor wire decode == flash
  ``data_in``, and the flash accepted the frame.
* ``CHK-SPI-SB-RX``: bytes the DUT delivered == flash ``data_out`` prefix ==
  monitor wire decode prefix.

Each direction with expectations logs one line with its frame and byte
counts; a scoreboard with no expectation at all fails. A program or read is
matched to the first unused flash record with its opcode (and address for a
program); a missing match fails.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ocah_spi_vip import OcahSpiFlash, command_format, lanes_to_bytes

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
class _Tally:
    frames: int = 0
    bytes: int = 0
    lines: list[str] = field(default_factory=list)


class SepSpiScoreboard:
    """Byte-for-byte compare of stimulus, the monitor wire decode, and the flash records."""

    def __init__(
        self, wire: SepSpiWireMonitor, flash: OcahSpiFlash, logger: logging.Logger, *, seed: int
    ) -> None:
        self.wire = wire
        self.flash = flash
        self.logger = logger
        self.seed = seed
        self._expects: list[_Expect] = []

    def expect_tx(self, addr: int, data: bytes, *, label: str = "") -> None:
        """A program the stimulus sent: ``data`` must reach the wire and the flash at ``addr``."""
        self._expects.append(_Expect("tx", None, addr, bytes(data), label))

    def expect_rx(self, opcode: int, data: bytes, *, label: str = "") -> None:
        """Bytes the DUT delivered from a read with ``opcode``."""
        self._expects.append(_Expect("rx", int(opcode), None, bytes(data), label))

    def finish(self) -> None:
        """Grade every expectation; raise on the first mismatch or on no expectation."""
        records = self.flash.get_transactions()
        frames = self.wire.monitor.get_transactions()
        if not self._expects:
            raise AssertionError(f"CHK-SPI-SB FAIL seed={self.seed} no expectation was registered")
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
            if exp.kind == "tx":
                wire = _wire_data(frame, rec["opcode"], self.flash.addr_bytes, response=False)
                device = bytes(rec["data_in"])
                ok = bool(rec["ok"]) and wire == exp.data and device == exp.data
            else:
                n = len(exp.data)
                wire = _wire_data(frame, rec["opcode"], self.flash.addr_bytes, response=True)[:n]
                device = bytes(rec["data_out"])[:n]
                ok = n > 0 and wire == exp.data and device == exp.data
            line = (
                f"{exp.label} record={index} opcode=0x{rec['opcode']:02x} addr=0x{rec['addr']:06x} "
                f"bytes={len(exp.data)} expected={exp.data.hex()} wire={wire.hex()} "
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

    @staticmethod
    def _match(exp: _Expect, records: list[dict], used: set[int]) -> int | None:
        for i, rec in enumerate(records):
            if i in used or rec["opcode"] < 0:
                continue
            fmt = command_format(rec["opcode"])
            if fmt is None:
                continue
            if exp.kind == "tx" and not fmt.response and rec["addr"] == exp.addr:
                return i
            if exp.kind == "rx" and fmt.response and rec["opcode"] == exp.opcode:
                return i
        return None


def _wire_data(frame: dict | None, opcode: int, addr_bytes: int, *, response: bool) -> bytes:
    """The monitor's decode of a frame's data phase at the command's lane width."""
    if frame is None:
        return b""
    fmt = command_format(opcode)
    if fmt is None:
        return b""
    beats = frame.get("beats") or ()
    if fmt.data_lanes == 1 or not beats:
        return bytes(frame["data_miso"] if response else frame["data_mosi"])
    start = fmt.input_clocks(addr_bytes) if response else 8 * (1 + addr_bytes)
    field_index = 2 if response else 0
    values = [beat[field_index] or 0 for beat in beats[start:]]
    return lanes_to_bytes(values, fmt.data_lanes)[0]
