# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared SPI VIP selftest: every malformed controller frame is one refused record.

The controller programs a page in a target sector and one in its neighbour,
then walks every malformed frame shape bit by bit through ``raw_frame``:

* ``CHK-SPI-SHAPE-OPCODE``: a frame of 1 to 7 command bits, latch clear and
  latch set, is refused as ``partial_opcode`` with ``opcode`` -1.
* ``CHK-SPI-SHAPE-ADDRESS``: PAGE PROGRAM and SECTOR ERASE, latch set, ending
  after 0 to 23 address bits, are refused as ``partial_address``.
* ``CHK-SPI-SHAPE-PAYLOAD``: PAGE PROGRAM, latch set, ending 1 to 7 bits into
  the first or second payload byte is refused as ``partial_byte``; with no
  payload byte it is refused as ``no_payload``.
* ``CHK-SPI-SHAPE-NOPAYLOAD``: WRITE ENABLE with the latch clear and WRITE
  DISABLE with it set, each followed by 1 to 7 bits or one byte, are refused
  as ``unexpected_payload``.
* ``CHK-SPI-SHAPE-ERASE``: SECTOR ERASE, latch set, followed by 1 to 7 bits
  or one byte, is refused as ``unexpected_payload``.
* ``CHK-SPI-SHAPE-READ``: READ and FAST READ ending after 0 to 23 address bits
  are refused as ``partial_address``; FAST READ ending after 0 to 7 dummy bits
  as ``partial_dummy``.

Each refused record carries its exact ``input_bits`` and ``tail_bits``; the
latch and the sha256 of both sectors stay unchanged. The live controls are
exact: WRITE ENABLE sets and WRITE DISABLE clears the latch
(``CHK-SPI-SHAPE-LATCH``), and SECTOR ERASE returns exactly the target sector
to 0xFF and consumes the latch (``CHK-SPI-SHAPE-ERASE-CTRL``).
``CHK-SPI-READ-ABORT``: READ JEDEC ID, READ STATUS REGISTER 1, READ and FAST
READ ended at every bit of their first output bytes are accepted with the
complete bytes sent and no state change.

``CHK-SPI-LEDGER`` matches every device record against the monitor's frames.
The checker replays the frames the device accepted (``CHK-SPI-FRAME-SHAPE``
and the command, read and memory rules), and a fail-fast probe checker handed
the first refused record must raise (``CHK-SPI-NEG-SHAPE``).
``CHK-SPI-ENGINE-STOP``: a registered callback that raises inside the
protocol engine makes ``stop()`` raise ``OcahSpiFlashError`` with that
exception as its cause.
"""

from __future__ import annotations

import hashlib
import logging

import cocotb
from ocah_spi_vip import (
    FRAME_SHAPE_REASONS,
    PAGE_SIZE,
    SECTOR_SIZE,
    SR1_WEL,
    OcahSpiFlashError,
    OcahSpiOpcode,
)
from ocah_spi_vip_harness import (
    FLASH_SIZE,
    JEDEC_ID,
    build_stack,
    random_payload,
    rejects,
    scenario_rng,
)

log = logging.getLogger("cocotb.tb.ocah_spi_frame_shape_test")

REQUIRED_IDS = (
    "CHK-SPI-SHAPE-OPCODE",
    "CHK-SPI-SHAPE-ADDRESS",
    "CHK-SPI-SHAPE-PAYLOAD",
    "CHK-SPI-SHAPE-NOPAYLOAD",
    "CHK-SPI-SHAPE-ERASE",
    "CHK-SPI-SHAPE-READ",
    "CHK-SPI-SHAPE-LATCH",
    "CHK-SPI-SHAPE-ERASE-CTRL",
    "CHK-SPI-READ-ABORT",
    "CHK-SPI-LEDGER",
    "CHK-SPI-FRAME-SHAPE",
    "CHK-SPI-FRAME-BYTES",
    "CHK-SPI-WREN-ORDER",
    "CHK-SPI-STATUS-WEL",
    "CHK-SPI-JEDEC-ID",
    "CHK-SPI-READ-DATA",
    "CHK-SPI-MEM-GOLDEN",
    "CHK-SPI-NONVAC-PROGRAM",
    "CHK-SPI-NONVAC-READ",
    "CHK-SPI-NONVAC-ERASE",
    "CHK-SPI-NEG-SHAPE",
    "CHK-SPI-ENGINE-STOP",
)

ADDR_BYTES = 3
_ENGINE_FAULT_OPCODE = 0xA5


def bits_of(data: bytes, count: int | None = None) -> list[int]:
    """MSB-first bits of ``data``, cut to ``count`` bits."""
    bits = [(byte >> i) & 1 for byte in data for i in range(7, -1, -1)]
    return bits if count is None else bits[:count]


def _record_view(rec: dict) -> tuple:
    return (
        rec["opcode"],
        rec["ok"],
        rec["reason"],
        rec["input_bits"],
        rec["tail_bits"],
        len(rec["data_in"]),
        bytes(rec["data_out"]),
    )


@cocotb.test()
async def ocah_spi_frame_shape_test(dut) -> None:
    rng = scenario_rng("frame_shape")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    host, flash, checker, monitor = harness.host, harness.flash, harness.checker, harness.monitor

    sectors = FLASH_SIZE // SECTOR_SIZE
    target = rng.randrange(0, sectors - 1) * SECTOR_SIZE
    neighbour = target + SECTOR_SIZE
    page_addr = target + rng.randrange(0, SECTOR_SIZE // PAGE_SIZE) * PAGE_SIZE
    payload = random_payload(rng, PAGE_SIZE)
    # The page head the reads stream is not erased, so every read grades real data.
    payload = bytes([payload[0] & 0x7F]) + payload[1:]
    neighbour_payload = random_payload(rng, 16)
    addr_bytes = page_addr.to_bytes(ADDR_BYTES, "big")
    tail_byte = rng.randrange(256)
    log.info(
        "start: target sector=0x%06x neighbour=0x%06x page=0x%06x", target, neighbour, page_addr
    )

    await host.write_enable()
    await host.page_program(page_addr, payload)
    await host.write_enable()
    await host.page_program(neighbour, neighbour_payload)

    def digest() -> str:
        return hashlib.sha256(flash.read_memory(target, 2 * SECTOR_SIZE)).hexdigest()[:16]

    async def frame(bits: list[int]) -> dict:
        before = len(flash.get_transactions())
        await host.raw_frame(bits)
        records = flash.get_transactions()[before:]
        if len(records) != 1:
            raise AssertionError(f"one frame gave {len(records)} device records")
        return dict(records[0])

    async def refuse_walk(check_id: str, cases: list[tuple[str, int, list[int], str]], latch: bool):
        """Each case: label, opcode, bits, reason. Every frame is refused with no state change."""
        if latch:
            await host.write_enable()
        else:
            await host.write_disable()
        start_digest = digest()
        observed, expected, lines = [], [], []
        for label, opcode, bits, reason in cases:
            latch_before = flash.write_enabled
            rec = await frame(bits)
            complete = len(bits) // 8
            payload_bytes = complete - 1 - ADDR_BYTES if reason == "partial_byte" else 0
            observed.append((label, *_record_view(rec)[:6], flash.write_enabled, digest()))
            expected.append(
                (
                    label,
                    opcode,
                    False,
                    reason,
                    len(bits),
                    len(bits) % 8,
                    max(payload_bytes, 0),
                    latch_before,
                    start_digest,
                )
            )
            lines.append(
                f"{label}:bits={len(bits)} complete_bytes={complete} tail={len(bits) % 8} "
                f"latch={int(latch_before)}->{int(flash.write_enabled)}"
            )
        log.info("%s cases=%d %s", check_id, len(cases), " ".join(lines))
        checker.expect_equal(
            check_id,
            observed,
            expected,
            context=f"frames={len(cases)} latch={int(latch)} sectors_sha256={start_digest}",
        )

    wren = bytes([OcahSpiOpcode.WRITE_ENABLE])
    wrdi = bytes([OcahSpiOpcode.WRITE_DISABLE])
    pp = bytes([OcahSpiOpcode.PAGE_PROGRAM]) + addr_bytes
    se = bytes([OcahSpiOpcode.SECTOR_ERASE]) + addr_bytes
    rd = bytes([OcahSpiOpcode.READ]) + addr_bytes
    fr = bytes([OcahSpiOpcode.FAST_READ]) + addr_bytes + b"\x00"

    # Command byte: 1 to 7 bits, latch clear then set.
    await refuse_walk(
        "CHK-SPI-SHAPE-OPCODE",
        [(f"wren{n}", -1, bits_of(wren, n), "partial_opcode") for n in range(1, 8)],
        latch=False,
    )
    await refuse_walk(
        "CHK-SPI-SHAPE-OPCODE",
        [(f"wrdi{n}", -1, bits_of(wrdi, n), "partial_opcode") for n in range(1, 8)],
        latch=True,
    )
    # Address phase of every mutating command: 0 to 23 address bits.
    await refuse_walk(
        "CHK-SPI-SHAPE-ADDRESS",
        [
            (f"{name}a{j}", opcode, bits_of(head, 8 + j), "partial_address")
            for name, opcode, head in (
                ("pp", OcahSpiOpcode.PAGE_PROGRAM, pp),
                ("se", OcahSpiOpcode.SECTOR_ERASE, se),
            )
            for j in range(8 * ADDR_BYTES)
        ],
        latch=True,
    )
    # Payload phase: 1 to 7 bits into the first or second byte, and no byte at all.
    await refuse_walk(
        "CHK-SPI-SHAPE-PAYLOAD",
        [
            (
                f"pp{k}b{t}",
                OcahSpiOpcode.PAGE_PROGRAM,
                bits_of(pp + bytes([tail_byte] * (k + 1)), 8 * (len(pp) + k) + t),
                "partial_byte",
            )
            for k in (0, 1)
            for t in range(1, 8)
        ]
        + [("pp_empty", OcahSpiOpcode.PAGE_PROGRAM, bits_of(pp), "no_payload")],
        latch=True,
    )
    # Commands without a payload: any bit after the last command or address bit.
    extra = bytes([tail_byte])
    await refuse_walk(
        "CHK-SPI-SHAPE-NOPAYLOAD",
        [
            (
                f"wren+{t}",
                OcahSpiOpcode.WRITE_ENABLE,
                bits_of(wren + extra, 8 + t),
                "unexpected_payload",
            )
            for t in range(1, 9)
        ],
        latch=False,
    )
    await refuse_walk(
        "CHK-SPI-SHAPE-NOPAYLOAD",
        [
            (
                f"wrdi+{t}",
                OcahSpiOpcode.WRITE_DISABLE,
                bits_of(wrdi + extra, 8 + t),
                "unexpected_payload",
            )
            for t in range(1, 9)
        ],
        latch=True,
    )
    await refuse_walk(
        "CHK-SPI-SHAPE-ERASE",
        [
            (
                f"se+{t}",
                OcahSpiOpcode.SECTOR_ERASE,
                bits_of(se + extra, 32 + t),
                "unexpected_payload",
            )
            for t in range(1, 9)
        ],
        latch=True,
    )
    # Read input phases: address and FAST READ dummy.
    await refuse_walk(
        "CHK-SPI-SHAPE-READ",
        [
            (f"{name}a{j}", opcode, bits_of(head, 8 + j), "partial_address")
            for name, opcode, head in (
                ("rd", OcahSpiOpcode.READ, rd),
                ("fr", OcahSpiOpcode.FAST_READ, fr),
            )
            for j in range(8 * ADDR_BYTES)
        ]
        + [
            (f"frd{d}", OcahSpiOpcode.FAST_READ, bits_of(fr, 32 + d), "partial_dummy")
            for d in range(8)
        ],
        latch=False,
    )

    # Latch controls: exact one-byte frames set and clear the latch.
    latch = []
    for name, data, want in (("wren", wren, True), ("wrdi", wrdi, False), ("wren", wren, True)):
        rec = await frame(bits_of(data))
        latch.append((name, rec["ok"], rec["reason"], rec["input_bits"], flash.write_enabled))
    checker.expect_equal(
        "CHK-SPI-SHAPE-LATCH",
        latch,
        [
            ("wren", True, "", 8, True),
            ("wrdi", True, "", 8, False),
            ("wren", True, "", 8, True),
        ],
        context="exact WRITE ENABLE / WRITE DISABLE / WRITE ENABLE frames",
    )

    # Read-output aborts, latch set: every bit of the first output bytes.
    status = SR1_WEL
    page_head = payload[:2]
    aborts_observed, aborts_expected = [], []
    latch_before, digest_before = flash.write_enabled, digest()
    for name, head, opcode, stream, outputs in (
        (
            "jedec",
            bytes([OcahSpiOpcode.JEDEC_ID]),
            OcahSpiOpcode.JEDEC_ID,
            JEDEC_ID.to_bytes(3, "big"),
            24,
        ),
        ("rdsr", bytes([OcahSpiOpcode.READ_SR1]), OcahSpiOpcode.READ_SR1, bytes([status]), 8),
        ("rd", rd, OcahSpiOpcode.READ, page_head, 16),
        ("fr", fr, OcahSpiOpcode.FAST_READ, page_head, 16),
    ):
        for o in range(outputs + 1):
            rec = await frame(bits_of(head) + [0] * o)
            aborts_observed.append((f"{name}o{o}", *_record_view(rec)))
            aborts_expected.append(
                (f"{name}o{o}", opcode, True, "", 8 * len(head), 0, 0, stream[: o // 8])
            )
    checker.expect_equal(
        "CHK-SPI-READ-ABORT",
        (aborts_observed, flash.write_enabled, digest()),
        (aborts_expected, latch_before, digest_before),
        context=f"frames={len(aborts_observed)} latch={int(latch_before)} sectors_sha256={digest_before}",
    )

    # Erase control: exactly the target sector returns to 0xFF and the latch is consumed.
    neighbour_before = flash.read_memory(neighbour, SECTOR_SIZE)
    rec = await frame(bits_of(se))
    checker.expect_equal(
        "CHK-SPI-SHAPE-ERASE-CTRL",
        (
            rec["ok"],
            rec["reason"],
            rec["input_bits"],
            flash.write_enabled,
            flash.read_memory(target, SECTOR_SIZE) == b"\xff" * SECTOR_SIZE,
            flash.read_memory(neighbour, SECTOR_SIZE) == neighbour_before,
        ),
        (True, "", 32, False, True, True),
        context=f"SECTOR ERASE 0x{target:06x} neighbour 0x{neighbour:06x}",
    )
    await host.read(page_addr, len(page_head))

    # Engine fault: a raising callback must surface at stop().
    async def faulty(opcode, addr, data):
        raise RuntimeError("selftest fault inside the protocol engine")

    flash.register_command_callback(_ENGINE_FAULT_OPCODE, faulty)
    await host.raw_frame(bits_of(bytes([_ENGINE_FAULT_OPCODE]) + addr_bytes))
    flash.unregister_command_callback(_ENGINE_FAULT_OPCODE)

    await monitor.stop()
    stop_error: BaseException | None = None
    try:
        await flash.stop()
    except OcahSpiFlashError as exc:
        stop_error = exc
    checker.expect_true(
        "CHK-SPI-ENGINE-STOP",
        stop_error is not None and isinstance(stop_error.__cause__, RuntimeError),
        context=f"stop() raised {stop_error!r} cause={getattr(stop_error, '__cause__', None)!r}",
    )

    # The faulted frame leaves no device record; the monitor saw it last.
    records = flash.get_transactions()
    frames = monitor.get_transactions()
    checker.check_ledger(
        frames[:-1], records, context=f"faulted_frame_opcode=0x{frames[-1]['opcode']:02x}"
    )
    refused = [i for i, rec in enumerate(records) if rec["reason"] in FRAME_SHAPE_REASONS]
    checker.replay([rec for rec in records if rec["reason"] not in FRAME_SHAPE_REASONS])
    checker.check_memory(context="programs and the erase control")
    checker.check_nonvacuous()
    checker.expect_true(
        "CHK-SPI-NEG-SHAPE",
        rejects("shape", flash, lambda probe: probe.replay(records[: refused[0] + 1])),
        context=f"a probe checker handed refused record {refused[0]} must fail",
    )
    log.info(
        "FRAME_SHAPE_SUMMARY records=%d refused=%d monitor_frames=%d",
        len(records),
        len(refused),
        len(monitor.get_transactions()),
    )
    checker.finalize()
