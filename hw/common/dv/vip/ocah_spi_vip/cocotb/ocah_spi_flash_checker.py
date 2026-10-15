# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Flash command, state, and memory checker over the shared evidence core.

``OcahSpiFlashRefModel`` rebuilds the flash array and the write-enable latch
from the commands the device recorded on the wire: an accepted PAGE PROGRAM
clears bits inside one page, an accepted SECTOR ERASE returns one 4 KiB sector
to 0xFF, WRITE ENABLE and WRITE DISABLE move the latch, and a program or erase
consumes it. The model never reads the device's array, so a device that stores
or streams the wrong bytes disagrees with it.

``OcahSpiFlashChecker`` replays the device records through the model and
emits one ``CHK-SPI-*`` record per rule through ``ocah_checker.OcahChecker``:

===========================  ==============================================================
``CHK-SPI-JEDEC-ID``         READ JEDEC ID streamed the configured identifier
``CHK-SPI-STATUS-WEL``       READ STATUS REGISTER 1 reported the latch the model predicts
``CHK-SPI-STATUS-SR2``       READ STATUS REGISTER 2 reported the configured register
``CHK-SPI-WREN-ORDER``       a program or erase was accepted only with the latch set and
                             refused, taking no payload, only with it clear
``CHK-SPI-FRAME-BYTES``      a PAGE PROGRAM sent with the latch set carried a complete
                             address and at least one payload byte and ended on a
                             payload byte boundary
``CHK-SPI-FRAME-SHAPE``      every other frame had a complete command byte and the exact
                             length of its command: one byte for WRITE ENABLE and WRITE
                             DISABLE, the command and address bytes for SECTOR ERASE
                             with the latch set, and complete command, address and dummy
                             phases for a read
``CHK-SPI-LEDGER``           the device recorded every frame the monitor saw, in order,
                             with the same command byte and input clock count
``CHK-SPI-READ-DATA``        a read (single, dual or quad) streamed the model's bytes at
                             that address
``CHK-SPI-HOST-*``           what the controller received equals what the device sent
``CHK-SPI-CMD-ORDER``        the in-scope opcode sequence equals the expected one
``CHK-SPI-MEM-GOLDEN``       the device array equals the model over every touched byte
``CHK-SPI-MEM-SOURCE``       the model equals the source image the scenario programmed
``CHK-SPI-NONVAC-PROGRAM``   an accepted program cleared at least one bit
``CHK-SPI-NONVAC-READ``      a read returned at least one byte that is not 0xFF
``CHK-SPI-NONVAC-ERASE``     an accepted erase returned at least one programmed byte to 0xFF
``CHK-SPI-UNSUPPORTED``      the out-of-scope opcodes seen are exactly the expected ones
                             and the device gave none of them a response or a payload
===========================  ==============================================================

An opcode outside the baseline scope, or one the device refused as
``unknown_opcode`` (a dual or quad command on a single-lane binding), is
counted under ``unsupported`` and never credited. A frame with no complete
command byte (``opcode`` -1) is not an opcode: it fails
``CHK-SPI-FRAME-SHAPE``. For an accepted frame that carries ``input_clocks``,
the shape rules also compare that count with the command's length at its lane
widths, so a device that accepts a frame with extra clocks fails them.
``finalize()`` prints the opcode tally and fails on any failed
or missing record. The checker has no SV-UVM twin: the package ships the
cocotb realization only.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ocah_checker import OcahChecker

from .ocah_spi_types import (
    IN_SCOPE_OPCODES,
    PAGE_SIZE,
    SECTOR_SIZE,
    SR1_WEL,
    OcahSpiOpcode,
    command_format,
    opcode_name,
)


def _clocks_per_byte(opcode: int) -> int:
    """Clocks of one payload byte of a program command."""
    fmt = command_format(opcode)
    return 8 // (fmt.data_lanes if fmt else 1)


__all__ = ["OcahSpiFlashChecker", "OcahSpiFlashRecord", "OcahSpiFlashRefModel"]

ERASED_BYTE = 0xFF
_ADDR_MASK_24 = 0xFFFFFF
_READ_OPCODES = frozenset(
    int(op)
    for op in (
        OcahSpiOpcode.READ,
        OcahSpiOpcode.FAST_READ,
        OcahSpiOpcode.DUAL_OUTPUT_READ,
        OcahSpiOpcode.QUAD_OUTPUT_READ,
        OcahSpiOpcode.DUAL_IO_READ,
        OcahSpiOpcode.QUAD_IO_READ,
    )
)
_PROGRAM_OPCODES = frozenset(
    (int(OcahSpiOpcode.PAGE_PROGRAM), int(OcahSpiOpcode.QUAD_PAGE_PROGRAM))
)
# Refusal reasons that grade a latch-set PAGE PROGRAM's shape.
_PROGRAM_SHAPE_REASONS = frozenset(("partial_byte", "partial_address", "no_payload"))
_HOST_CHECK_IDS = {
    int(OcahSpiOpcode.READ): "CHK-SPI-HOST-READBACK",
    int(OcahSpiOpcode.FAST_READ): "CHK-SPI-HOST-READBACK",
    int(OcahSpiOpcode.JEDEC_ID): "CHK-SPI-HOST-JEDEC",
    int(OcahSpiOpcode.READ_SR1): "CHK-SPI-HOST-STATUS",
    int(OcahSpiOpcode.READ_SR2): "CHK-SPI-HOST-STATUS",
}


@dataclass(frozen=True)
class OcahSpiFlashRecord:
    """One chip-select frame as the device recorded it."""

    opcode: int
    addr: int
    data_out: bytes
    data_in: bytes
    ok: bool
    reason: str
    input_bits: int | None = None
    tail_bits: int = 0
    input_clocks: int | None = None

    @classmethod
    def from_mapping(cls, record: Mapping[str, Any]) -> OcahSpiFlashRecord:
        """Normalize a ``OcahSpiFlash.get_transactions()`` entry; ``opcode`` -1 stays -1."""
        opcode = int(record["opcode"])
        bits = record.get("input_bits")
        clocks = record.get("input_clocks", bits)
        return cls(
            opcode=opcode if opcode < 0 else opcode & 0xFF,
            addr=int(record.get("addr", 0)),
            data_out=bytes(record.get("data_out") or b""),
            data_in=bytes(record.get("data_in") or b""),
            ok=bool(record.get("ok", True)),
            reason=str(record.get("reason", "")),
            input_bits=None if bits is None else int(bits),
            tail_bits=int(record.get("tail_bits", 0)),
            input_clocks=None if clocks is None else int(clocks),
        )


class OcahSpiFlashRefModel:
    """Sparse flash array plus write-enable latch, rebuilt from accepted commands.

    A byte never programmed reads as 0xFF. Addresses at or beyond ``flash_size``
    read as 0xFF and take no program, as the device does; a read address wraps
    at 24 bits.
    """

    def __init__(self, *, flash_size: int, status_reg1: int = 0, status_reg2: int = 0) -> None:
        self.flash_size = flash_size
        self.status_reg1_base = status_reg1 & 0xFF & ~SR1_WEL
        self.status_reg2 = status_reg2 & 0xFF
        self.write_enabled = False
        self._mem: dict[int, int] = {}
        self.touched: set[int] = set()

    def clear(self) -> None:
        """Forget every programmed byte and clear the latch."""
        self.write_enabled = False
        self._mem.clear()
        self.touched.clear()

    def byte_at(self, addr: int) -> int:
        """Value the array holds at ``addr``."""
        if addr >= self.flash_size:
            return ERASED_BYTE
        return self._mem.get(addr, ERASED_BYTE)

    def read(self, addr: int, length: int) -> bytes:
        """Bytes a READ at ``addr`` streams for ``length`` clocks of data."""
        return bytes(self.byte_at((addr + i) & _ADDR_MASK_24) for i in range(length))

    def status1(self) -> int:
        """READ STATUS REGISTER 1 value the device must report at this point of the replay."""
        return self.status_reg1_base | (SR1_WEL if self.write_enabled else 0)

    def write_enable(self) -> None:
        self.write_enabled = True

    def write_disable(self) -> None:
        self.write_enabled = False

    def page_program(self, addr: int, data: bytes) -> int:
        """Apply an accepted PAGE PROGRAM; return how many bytes changed value.

        Bits only clear, and the address wraps inside the 256-byte page.
        """
        page_base = addr & ~(PAGE_SIZE - 1)
        page_off = addr & (PAGE_SIZE - 1)
        changed = 0
        for index, value in enumerate(data):
            target = page_base + ((page_off + index) % PAGE_SIZE)
            if target >= self.flash_size:
                continue
            before = self.byte_at(target)
            after = before & value
            self._mem[target] = after
            self.touched.add(target)
            changed += int(after != before)
        self.write_enabled = False
        return changed

    def sector_erase(self, addr: int) -> int:
        """Apply an accepted SECTOR ERASE; return how many bytes were not 0xFF before."""
        sector_base = addr & ~(SECTOR_SIZE - 1)
        end = min(sector_base + SECTOR_SIZE, self.flash_size)
        flipped = 0
        for target in range(sector_base, end):
            if self._mem.get(target, ERASED_BYTE) != ERASED_BYTE:
                flipped += 1
            self._mem[target] = ERASED_BYTE
            self.touched.add(target)
        self.write_enabled = False
        return flipped

    def spans(self) -> list[tuple[int, int]]:
        """Contiguous ``(start, end)`` ranges of touched addresses, ascending."""
        result: list[tuple[int, int]] = []
        for addr in sorted(self.touched):
            if result and result[-1][1] == addr:
                result[-1] = (result[-1][0], addr + 1)
            else:
                result.append((addr, addr + 1))
        return result


class OcahSpiFlashChecker:
    """Replays device records through the reference model and records ``CHK-SPI-*`` evidence."""

    def __init__(
        self,
        *,
        name: str = "OcahSpiFlashChecker",
        flash: Any | None = None,
        flash_size: int | None = None,
        jedec_id: int | None = None,
        status_reg1: int | None = None,
        status_reg2: int | None = None,
        addr_bytes: int | None = None,
        raise_on_error: bool = True,
        required_ids: Iterable[str] = (),
        logger: logging.Logger | None = None,
    ) -> None:
        self.name = name
        self.log = logger or logging.getLogger(name)
        self.flash = flash
        size = flash_size if flash_size is not None else getattr(flash, "flash_size", None)
        if size is None:
            raise ValueError(f"{name}: flash_size is needed when no flash is attached")
        self.jedec_id = jedec_id if jedec_id is not None else getattr(flash, "jedec_id", None)
        sr1 = status_reg1 if status_reg1 is not None else getattr(flash, "status_reg1", 0)
        sr2 = status_reg2 if status_reg2 is not None else getattr(flash, "status_reg2", 0)
        self.addr_bytes = int(
            addr_bytes if addr_bytes is not None else getattr(flash, "addr_bytes", 3)
        )
        self.ref_model = OcahSpiFlashRefModel(
            flash_size=size, status_reg1=int(sr1), status_reg2=int(sr2)
        )
        self.evidence = OcahChecker(
            name=name, required_ids=required_ids, fail_fast=raise_on_error, logger=self.log
        )
        self.records: list[OcahSpiFlashRecord] = []
        self.opcodes: list[int] = []
        self.unsupported: list[OcahSpiFlashRecord] = []
        self._consumed = 0
        self._program_count = 0
        self._program_changed = 0
        self._erase_count = 0
        self._erase_flipped = 0
        self._read_count = 0
        self._nonerased_reads = 0

    # ------------------------------------------------------------------
    # Record replay
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Forget every record, tally, and evidence entry."""
        self.evidence.clear()
        self.ref_model.clear()
        self.records.clear()
        self.opcodes.clear()
        self.unsupported.clear()
        self._consumed = 0
        self._program_count = self._program_changed = 0
        self._erase_count = self._erase_flipped = 0
        self._read_count = self._nonerased_reads = 0

    def replay(self, records: Sequence[Mapping[str, Any]] | None = None) -> int:
        """Check the records added since the last call; return how many were consumed.

        With no argument the attached flash's history is used. Calling again
        with a longer history continues from the last consumed record.
        """
        if records is None:
            if self.flash is None:
                raise ValueError(f"{self.name}: replay() needs records when no flash is attached")
            records = self.flash.get_transactions()
        fresh = list(records)[self._consumed :]
        for record in fresh:
            self.check_record(record)
        self._consumed += len(fresh)
        return len(fresh)

    def check_record(self, record: Mapping[str, Any] | OcahSpiFlashRecord) -> None:
        """Replay one device record through the model and its rules."""
        rec = (
            record
            if isinstance(record, OcahSpiFlashRecord)
            else OcahSpiFlashRecord.from_mapping(record)
        )
        self.records.append(rec)
        opcode = rec.opcode
        if opcode < 0:
            self.expect_true(
                "CHK-SPI-FRAME-SHAPE",
                False,
                context=f"frame ended {rec.tail_bits} bit(s) into the command byte reason={rec.reason}",
            )
            return
        if opcode not in IN_SCOPE_OPCODES or rec.reason == "unknown_opcode":
            self.unsupported.append(rec)
            self.log.info(
                "%s: %s is outside the baseline scope and earns no credit (ok=%s out=%d B in=%d B)",
                self.name,
                opcode_name(opcode),
                rec.ok,
                len(rec.data_out),
                len(rec.data_in),
            )
            return
        self.opcodes.append(opcode)
        if opcode == OcahSpiOpcode.JEDEC_ID:
            self._check_jedec(rec)
        elif opcode in (OcahSpiOpcode.READ_SR1, OcahSpiOpcode.READ_SR2) and not rec.data_out:
            self.log.info(
                "%s: %s ended before its first complete output byte (legal read termination); "
                "no byte to judge",
                self.name,
                opcode_name(opcode),
            )
        elif opcode == OcahSpiOpcode.READ_SR1:
            self.expect_equal(
                "CHK-SPI-STATUS-WEL",
                rec.data_out[:1],
                bytes([self.ref_model.status1()]),
                context=f"latch={'set' if self.ref_model.write_enabled else 'clear'}",
            )
        elif opcode == OcahSpiOpcode.READ_SR2:
            self.expect_equal(
                "CHK-SPI-STATUS-SR2", rec.data_out[:1], bytes([self.ref_model.status_reg2])
            )
        elif opcode in (OcahSpiOpcode.WRITE_ENABLE, OcahSpiOpcode.WRITE_DISABLE):
            if not self._check_shape(rec, 8):
                return
            if opcode == OcahSpiOpcode.WRITE_ENABLE:
                self.ref_model.write_enable()
            else:
                self.ref_model.write_disable()
        elif opcode in _PROGRAM_OPCODES:
            self._check_program(rec)
        elif opcode == OcahSpiOpcode.SECTOR_ERASE:
            self._check_erase(rec)
        elif opcode in _READ_OPCODES:
            self._check_read(rec)

    # ------------------------------------------------------------------
    # Scenario-level rules
    # ------------------------------------------------------------------

    def check_command_order(
        self,
        expected: Sequence[int],
        *,
        check_id: str = "CHK-SPI-CMD-ORDER",
        context: str = "",
    ) -> bool:
        """The in-scope opcode sequence the device saw equals ``expected``."""
        return self.expect_equal(
            check_id,
            [opcode_name(op) for op in self.opcodes],
            [opcode_name(int(op)) for op in expected],
            context=f"frames={len(self.records)} unsupported={len(self.unsupported)} {context}",
        )

    def check_host_responses(
        self,
        opcode: int,
        observed: Sequence[bytes],
        *,
        check_id: str | None = None,
        context: str = "",
    ) -> bool:
        """The controller received, frame by frame, the bytes the device sent for ``opcode``."""
        resolved = check_id or _HOST_CHECK_IDS.get(int(opcode), "CHK-SPI-HOST-RX")
        sent = [rec.data_out for rec in self.records if rec.opcode == int(opcode)]
        received = [bytes(item) for item in observed]
        label = f"{opcode_name(int(opcode))} frames={len(sent)} host_frames={len(received)}"
        if not received:
            return self.expect_true(
                resolved, False, context=f"{label} no host observation {context}"
            )
        return self.expect_equal(resolved, received, sent, context=f"{label} {context}")

    def check_ledger(
        self,
        monitor_records: Sequence[Mapping[str, Any]],
        records: Sequence[Mapping[str, Any]] | None = None,
        *,
        context: str = "",
    ) -> bool:
        """The device recorded every frame the monitor saw: same order, command byte, input bits.

        ``records`` defaults to the attached flash's whole history. A frame
        without a complete command byte is -1 on both sides.
        """
        if records is None:
            if self.flash is None:
                raise ValueError(
                    f"{self.name}: check_ledger() needs records when no flash is attached"
                )
            records = self.flash.get_transactions()
        device = [
            (
                int(rec["opcode"]) if int(rec["opcode"]) >= 0 else -1,
                rec.get("input_clocks", rec.get("input_bits")),
            )
            for rec in records
        ]
        wire = [
            (int(txn["opcode"]) if txn["opcode_complete"] else -1, txn["input_clocks"])
            for txn in monitor_records
        ]
        first = next(
            (i for i, (got, want) in enumerate(zip(device, wire)) if got != want),
            min(len(device), len(wire)),
        )
        return self.expect_equal(
            "CHK-SPI-LEDGER",
            device,
            wire,
            context=(
                f"device_frames={len(device)} monitor_frames={len(wire)} "
                f"first_difference={first} {context}"
            ),
        )

    def check_host_jedec(self, observed_id: int, *, context: str = "") -> bool:
        """The controller decoded the identifier the device streamed."""
        return self.check_host_responses(
            OcahSpiOpcode.JEDEC_ID,
            [(int(observed_id) & _ADDR_MASK_24).to_bytes(3, "big")],
            context=f"host_id=0x{int(observed_id) & _ADDR_MASK_24:06x} {context}",
        )

    def check_memory(
        self,
        *,
        source: bytes | None = None,
        addr: int = 0,
        context: str = "",
    ) -> bool:
        """The device array equals the model over every touched byte; the model equals ``source``.

        ``CHK-SPI-MEM-GOLDEN`` needs an attached flash and at least one
        programmed or erased byte; a scenario that touched nothing fails it.
        ``CHK-SPI-MEM-SOURCE`` is recorded when ``source`` is given: the model's
        bytes at ``addr`` must equal the image the scenario meant to program.
        """
        passed = True
        if self.flash is not None:
            passed &= self._check_golden(context)
        if source is not None:
            image = bytes(source)
            passed &= self.expect_equal(
                "CHK-SPI-MEM-SOURCE",
                self.ref_model.read(addr, len(image)),
                image,
                context=f"addr=0x{addr:06x} len={len(image)} {context}",
            )
        return passed

    def check_nonvacuous(
        self,
        *,
        require_program: bool = True,
        require_read: bool = True,
        require_erase: bool | None = None,
        context: str = "",
    ) -> bool:
        """The scenario changed, read, and erased real data.

        ``require_erase`` defaults to whether an erase was accepted, so a
        scenario without erases records nothing for it while an erase of an
        already blank sector fails ``CHK-SPI-NONVAC-ERASE``.
        """
        passed = True
        if require_program:
            passed &= self.expect_true(
                "CHK-SPI-NONVAC-PROGRAM",
                self._program_changed > 0,
                context=(
                    f"programs={self._program_count} bytes_changed={self._program_changed} "
                    f"{context}"
                ),
            )
        if require_read:
            passed &= self.expect_true(
                "CHK-SPI-NONVAC-READ",
                self._nonerased_reads > 0,
                context=f"reads={self._read_count} non_erased={self._nonerased_reads} {context}",
            )
        if require_erase is None:
            require_erase = self._erase_count > 0
        if require_erase:
            passed &= self.expect_true(
                "CHK-SPI-NONVAC-ERASE",
                self._erase_flipped > 0,
                context=f"erases={self._erase_count} bytes_flipped={self._erase_flipped} {context}",
            )
        return passed

    def check_unsupported(
        self,
        expected: Iterable[int],
        *,
        frames: Sequence[Mapping[str, Any]],
        context: str = "",
    ) -> bool:
        """The out-of-scope opcodes seen are exactly ``expected`` and drew no response.

        ``frames`` are the monitor's frames of the same bus. The device drew
        no response when, in the monitor frame of each out-of-scope opcode,
        the response lane resolved and held its level from the chip-select
        fall at every sample edge: what the controller sampled, not the
        device's own record.
        """
        seen = sorted(rec.opcode for rec in self.unsupported)
        wanted = sorted(int(op) & 0xFF for op in expected)
        refused = all(not rec.ok for rec in self.unsupported)
        on_wire = [
            frame
            for frame in frames
            if frame["opcode_complete"] and int(frame["opcode"]) in set(seen)
        ]
        driven = [
            f"0x{int(frame['opcode']):02x}@{frame['start_ns']}"
            for frame in on_wire
            if frame["miso_idle"] is None
            or any(level != frame["miso_idle"] for level in frame["miso_raw"])
        ]
        samples = sum(len(frame["miso_raw"]) for frame in on_wire)
        silent = len(on_wire) == len(seen) and samples > 0 and not driven
        return self.expect_true(
            "CHK-SPI-UNSUPPORTED",
            seen == wanted and refused and silent,
            context=(
                f"seen={[f'0x{op:02x}' for op in seen]} "
                f"expected={[f'0x{op:02x}' for op in wanted]} refused={refused} "
                f"wire_frames={len(on_wire)} miso_samples={samples} driven={driven} {context}"
            ),
        )

    # ------------------------------------------------------------------
    # Evidence passthrough and finalization
    # ------------------------------------------------------------------

    def expect_equal(
        self, check_id: str, observed: Any, expected: Any, *, context: str = ""
    ) -> bool:
        """Emit one exact-value evidence record through the common core."""
        return bool(self.evidence.expect_equal(check_id, observed, expected, context=context))

    def expect_true(self, check_id: str, condition: Any, *, context: str = "") -> bool:
        """Emit one boolean evidence record through the common core."""
        return bool(self.evidence.expect_true(check_id, condition, context=context))

    def finalize(self) -> None:
        """Log the opcode tally and finalize the evidence; raises on failed or missing records."""
        tally: dict[str, int] = {}
        for opcode in self.opcodes:
            tally[opcode_name(opcode)] = tally.get(opcode_name(opcode), 0) + 1
        self.log.info(
            "SPI_CHECKER_SUMMARY name=%s frames=%d in_scope=%d unsupported=%d "
            "programs=%d erases=%d reads=%d tally=%s",
            self.name,
            len(self.records),
            len(self.opcodes),
            len(self.unsupported),
            self._program_count,
            self._erase_count,
            self._read_count,
            tally,
        )
        self.evidence.finalize()

    # ------------------------------------------------------------------
    # Per-record rules
    # ------------------------------------------------------------------

    def _check_jedec(self, rec: OcahSpiFlashRecord) -> None:
        if self.jedec_id is None:
            self.log.info("%s: no JEDEC ID configured; identifier not judged", self.name)
            return
        if not rec.data_out:
            self.log.info(
                "%s: READ JEDEC ID ended before its first complete output byte "
                "(legal read termination); no byte to judge",
                self.name,
            )
            return
        expected = (self.jedec_id & _ADDR_MASK_24).to_bytes(3, "big")
        self.expect_equal(
            "CHK-SPI-JEDEC-ID",
            rec.data_out[:3],
            expected[: len(rec.data_out)],
            context=f"bytes_streamed={len(rec.data_out)}",
        )

    def _check_write_gate(self, rec: OcahSpiFlashRecord, what: str) -> bool:
        latch = "set" if self.ref_model.write_enabled else "clear"
        if rec.ok:
            return self.expect_true(
                "CHK-SPI-WREN-ORDER",
                self.ref_model.write_enabled,
                context=f"{what} accepted addr=0x{rec.addr:06x} latch={latch}",
            )
        return self.expect_true(
            "CHK-SPI-WREN-ORDER",
            not self.ref_model.write_enabled and rec.reason == "wel_clear" and not rec.data_in,
            context=(
                f"{what} refused addr=0x{rec.addr:06x} latch={latch} reason={rec.reason} "
                f"payload_taken={len(rec.data_in)}"
            ),
        )

    @staticmethod
    def _expected_clocks(rec: OcahSpiFlashRecord, clocks: int) -> bool:
        """True when the record carries no clock count or the count is ``clocks``."""
        return rec.input_clocks is None or rec.input_clocks == clocks

    def _check_shape(self, rec: OcahSpiFlashRecord, clocks: int) -> bool:
        """``CHK-SPI-FRAME-SHAPE``: accepted, with ``clocks`` input clocks and no more."""
        return self.expect_true(
            "CHK-SPI-FRAME-SHAPE",
            rec.ok and self._expected_clocks(rec, clocks),
            context=(
                f"{opcode_name(rec.opcode)} ok={rec.ok} reason={rec.reason} "
                f"input_clocks={rec.input_clocks} expected_clocks={clocks}"
            ),
        )

    def _check_program(self, rec: OcahSpiFlashRecord) -> None:
        if self.ref_model.write_enabled:
            if not self.expect_true(
                "CHK-SPI-FRAME-BYTES",
                rec.reason not in _PROGRAM_SHAPE_REASONS
                and (
                    not rec.ok
                    or self._expected_clocks(
                        rec,
                        8 * (1 + self.addr_bytes) + _clocks_per_byte(rec.opcode) * len(rec.data_in),
                    )
                ),
                context=(
                    f"PAGE PROGRAM addr=0x{rec.addr:06x} complete_bytes={len(rec.data_in)} "
                    f"reason={rec.reason} input_clocks={rec.input_clocks}"
                ),
            ):
                return
        self._check_write_gate(rec, "PAGE PROGRAM")
        if not rec.ok:
            self.ref_model.write_disable()
            return
        self._program_count += 1
        self._program_changed += self.ref_model.page_program(rec.addr, rec.data_in)

    def _check_erase(self, rec: OcahSpiFlashRecord) -> None:
        if self.ref_model.write_enabled and not self._check_shape(rec, 8 * (1 + self.addr_bytes)):
            return
        self._check_write_gate(rec, "SECTOR ERASE")
        if not rec.ok:
            self.ref_model.write_disable()
            return
        self._erase_count += 1
        self._erase_flipped += self.ref_model.sector_erase(rec.addr)

    def _check_read(self, rec: OcahSpiFlashRecord) -> None:
        fmt = command_format(rec.opcode)
        assert fmt is not None
        if not self._check_shape(rec, fmt.input_clocks(self.addr_bytes)):
            return
        if not rec.data_out:
            self.log.info(
                "%s: %s at 0x%06x ended before its first complete output byte "
                "(legal read termination); no byte to judge",
                self.name,
                opcode_name(rec.opcode),
                rec.addr,
            )
            return
        self._read_count += 1
        if any(value != ERASED_BYTE for value in rec.data_out):
            self._nonerased_reads += 1
        self.expect_equal(
            "CHK-SPI-READ-DATA",
            rec.data_out,
            self.ref_model.read(rec.addr, len(rec.data_out)),
            context=f"{opcode_name(rec.opcode)} addr=0x{rec.addr:06x} len={len(rec.data_out)}",
        )

    def _check_golden(self, context: str) -> bool:
        flash = self.flash
        if flash is None:
            raise ValueError(f"{self.name}: the memory golden needs an attached flash")
        spans = self.ref_model.spans()
        if not spans:
            return self.expect_true(
                "CHK-SPI-MEM-GOLDEN", False, context=f"no programmed or erased byte {context}"
            )
        mismatches = 0
        first: str = "-"
        total = 0
        for start, end in spans:
            device = bytes(flash.read_memory(start, end - start))
            model = self.ref_model.read(start, end - start)
            total += end - start
            for offset, (got, want) in enumerate(zip(device, model)):
                if got != want:
                    if mismatches == 0:
                        first = f"0x{start + offset:06x}:0x{got:02x}!=0x{want:02x}"
                    mismatches += 1
        return self.expect_equal(
            "CHK-SPI-MEM-GOLDEN",
            mismatches,
            0,
            context=f"spans={len(spans)} bytes={total} first_mismatch={first} {context}",
        )
