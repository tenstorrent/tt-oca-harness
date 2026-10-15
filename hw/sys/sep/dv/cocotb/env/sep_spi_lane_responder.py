# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SPI lane responder, raw lane frames and the SPI lane FCOV record.

``SepSpiLaneResponder`` is the device side of a raw SPI frame on the SEP SPI
host. It drives the four response lanes ``spi_sd_i[3:0]`` of ``tb_top``, which
the DUT receives only in a run with the plusarg ``+sep_spi_four_lane``
(``tb/tb_top.sv``). It never drives ``spi_miso_i``. ``start`` fails when the
plusarg is absent.

Bit order (OpenTitan SPI_HOST, "Input and Output Byte Ordering"): the most
significant bits of a byte go first; in an x2 or x4 segment each clock carries
one pair or nibble, with its least significant bit on ``sd[0]``. In an x1
segment the device sends on ``sd[1]`` (CIPO).

API::

    rsp = SepSpiLaneResponder(dut, cpol=0, cpha=0)
    await rsp.start()               # plusarg check, then the responder task
    rsp.set_mode(cpol, cpha)        # SPI mode of every frame that starts later
    rsp.queue_rx(data, lanes)       # bytes for the next RX segments of that width
    rsp.expect_segments(segs)       # layout of the next chip-select-low window
    rsp.load(segments)              # queue_rx + expect_segments in one call
    rsp.clear()                     # drop the queue and a pending layout
    rsp.driven                      # bytes driven per segment of the last window
    await rsp.stop()                # stop the task, all lanes to 0

``segs`` of ``expect_segments`` is a list of ``(direction, lanes, n)``:
``direction`` is ``"tx"``, ``"rx"``, ``"bidir"`` or ``"dummy"``; ``n`` is the
byte count of a data segment and the clock count of a dummy segment. Each
``"rx"`` or ``"bidir"`` segment takes its ``n`` bytes from the head of the
``queue_rx`` queue; the queued width must equal the segment width (``"bidir"``
is x1 only). The layout applies to the next chip-select fall only; a window
with no layout drives 0 on every lane. So the driven bytes are a pure function
of what the leaf queued.

``load(segments)`` takes the segment list of ``SepSpiScoreboard.expect_frame``:
``(lanes, "tx" | "rx" | "dummy", bytes | clocks)``. ``clear()`` drops the
queue and a pending layout, for a window that an abort stopped before its
chip-select fall.

The responder counts the sample edges of the SPI mode (SCK changes to the level
``1 if cpol == cpha else 0``) from chip-select fall. It puts beat ``k`` (the
``k``-th sample edge of the window, 0 first) on the lanes at the shift edge
before it: at the chip-select fall for beat 0 in CPHA 0, at each shift edge
after that. A TX or dummy beat drives 0. At chip-select rise all lanes go to 0.

``driven`` is the list, one entry per segment of the last finished window, of
the whole bytes the responder put on the lanes (``b""`` for TX and dummy
segments). A window cut early gives fewer bytes. Use it for logging; the grade
of a frame is the DUT side (``SepSpiScoreboard.expect_frame``).

``run_lane_frame`` issues one raw frame through ``SepSpiHostOps``. Each TX
segment gets its own TXDATA words and each RX segment starts word-aligned in
RXDATA (OpenTitan "Command Length and Alignment in DATA"); the byte order is
``ByteOrder = 1`` (first byte on the wire is TXDATA[7:0], first byte received
lands in RXDATA[7:0]).

``spi_lane_fcov`` writes one graded record into the ``spi_ln_*`` variables of
the FCOV sampler (``cov/sv/sep_fcov.sv``, docs/SEP_FCOV.adoc). Call it only
after the check of that record passed. It is a no-op that returns False on
Verilator.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import Any

import cocotb
from cocotb.triggers import ClockCycles, Edge, FallingEdge, First, RisingEdge, Timer
from seq_lib.sep_spi_host_ops import DIR_BIDIR, DIR_DUMMY, DIR_RX, DIR_TX, command_word

from env.sep_fcov_gate import fcov_present, owner_code

__all__ = [
    "SepSpiLaneResponder",
    "pack_tx_words",
    "run_lane_frame",
    "spi_lane_fcov",
    "unpack_rx_words",
]

SPEED = {1: 0, 2: 1, 4: 2}
DIRECTION = {"dummy": DIR_DUMMY, "rx": DIR_RX, "tx": DIR_TX, "bidir": DIR_BIDIR}

_KIND = {"data": 1, "opcode": 2, "oe": 3, "trigger": 4, "abort": 5, "chain": 6}

Segment = tuple[int, str, bytes | int]


def _seg_len(kind: str, value: bytes | int) -> int:
    """Byte count of a data segment, clock count of a dummy segment."""
    if kind == "dummy":
        if not isinstance(value, int):
            raise ValueError("a dummy segment takes a clock count")
        return value
    if kind not in ("tx", "rx"):
        raise ValueError(f"segment kind {kind!r}: one of tx, rx, dummy")
    if isinstance(value, int):
        raise ValueError(f"a {kind} segment takes bytes")
    return len(value)


class SepSpiLaneResponder:
    """Device side of raw x1/x2/x4 SPI frames on ``spi_sd_i[3:0]``."""

    def __init__(self, dut: Any, *, cpol: int = 0, cpha: int = 0) -> None:
        self._dut = dut
        self._cpol = cpol & 1
        self._cpha = cpha & 1
        self._queue: deque[tuple[int, int]] = deque()  # (lanes, byte)
        self._pending: list[tuple[str, int, bytes | int]] | None = None
        self._task: Any = None
        self.driven: list[bytes] = []
        self.windows = 0

    def set_mode(self, cpol: int, cpha: int) -> None:
        """SPI mode of every window that starts after this call."""
        self._cpol = cpol & 1
        self._cpha = cpha & 1

    def queue_rx(self, data: bytes, lanes: int) -> None:
        """Queue ``data`` for the next RX (or bidir) segments of width ``lanes``."""
        if lanes not in SPEED:
            raise ValueError(f"lanes={lanes}: must be 1, 2 or 4")
        self._queue.extend((lanes, b) for b in bytes(data))

    def expect_segments(self, segs: Sequence[tuple[str, int, int]]) -> None:
        """Layout of the next chip-select-low window: ``(direction, lanes, n)`` each."""
        if self._pending is not None:
            raise RuntimeError("a window layout is already pending; no chip-select fall used it")
        layout: list[tuple[str, int, bytes | int]] = []
        for direction, lanes, n in segs:
            if direction not in DIRECTION or lanes not in SPEED:
                raise ValueError(f"segment ({direction!r}, {lanes}, {n}) is not legal")
            if direction == "bidir" and lanes != 1:
                raise ValueError("a bidir segment is x1 only")
            if direction in ("rx", "bidir"):
                if len(self._queue) < n:
                    raise ValueError(
                        f"{direction} x{lanes} segment needs {n} bytes, {len(self._queue)} queued"
                    )
                data = bytearray()
                for _ in range(n):
                    q_lanes, byte = self._queue.popleft()
                    if q_lanes != lanes:
                        raise ValueError(f"queued x{q_lanes} byte for an x{lanes} segment")
                    data.append(byte)
                layout.append((direction, lanes, bytes(data)))
            else:
                layout.append((direction, lanes, int(n)))
        self._pending = layout

    def load(self, segments: Sequence[Segment]) -> None:
        """``expect_segments`` from a ``SepSpiScoreboard.expect_frame`` segment list."""
        segs: list[tuple[str, int, int]] = []
        for lanes, kind, value in segments:
            n = _seg_len(kind, value)
            if kind == "rx" and not isinstance(value, int):
                self.queue_rx(bytes(value), lanes)
            segs.append((kind, lanes, n))
        self.expect_segments(segs)

    def clear(self) -> None:
        """Drop the queued RX bytes and a pending layout (e.g. after an abort)."""
        self._queue.clear()
        self._pending = None

    async def start(self) -> SepSpiLaneResponder:
        """Check that the DUT receives ``spi_sd_i`` (``+sep_spi_four_lane``), then run."""
        dut = self._dut
        for probe in (0b1010, 0b0101):
            dut.spi_sd_i.value = probe
            await Timer(1, unit="ns")
            got = dut.spi_sd_rsp_o.value
            if not got.is_resolvable or int(got) != probe:
                dut.spi_sd_i.value = 0
                raise RuntimeError(
                    f"spi_sd_rsp_o={got} with spi_sd_i=0b{probe:04b}: the lane responder "
                    "needs the plusarg +sep_spi_four_lane"
                )
        dut.spi_sd_i.value = 0
        if self._task is None:
            self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        """Stop the responder and drive 0 on every lane."""
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._dut.spi_sd_i.value = 0

    @staticmethod
    def _beats(layout: list[tuple[str, int, bytes | int]]) -> tuple[dict[int, int], list]:
        """Lane value per beat index, and per segment its (first beat, beats, lanes, rx)."""
        beats: dict[int, int] = {}
        spans: list[tuple[int, int, int, bool]] = []
        pos = 0
        for direction, lanes, value in layout:
            if isinstance(value, int):
                n = value if direction == "dummy" else value * 8 // lanes
                spans.append((pos, n, lanes, False))
                pos += n
                continue
            mask = (1 << lanes) - 1
            k = pos
            for byte in value:
                for shift in range(8 - lanes, -1, -lanes):
                    group = (byte >> shift) & mask
                    beats[k] = group << 1 if lanes == 1 else group
                    k += 1
            spans.append((pos, k - pos, lanes, True))
            pos = k
        return beats, spans

    @staticmethod
    def _rebuild(record: dict[int, int], spans: list) -> list[bytes]:
        """Whole bytes put on the lanes, per segment."""
        out: list[bytes] = []
        for first, count, lanes, rx in spans:
            if not rx:
                out.append(b"")
                continue
            data = bytearray()
            per_byte = 8 // lanes
            for b in range(count // per_byte):
                idx = [first + b * per_byte + i for i in range(per_byte)]
                if any(i not in record for i in idx):
                    break
                byte = 0
                for i in idx:
                    group = record[i] >> 1 if lanes == 1 else record[i]
                    byte = (byte << lanes) | (group & ((1 << lanes) - 1))
                data.append(byte)
            out.append(bytes(data))
        return out

    async def _run(self) -> None:
        dut = self._dut
        cs_n, sck = dut.spi_cs_n_o, dut.spi_sck_o
        while True:
            await FallingEdge(cs_n)
            layout, self._pending = self._pending or [], None
            beats, spans = self._beats(layout)
            sample_level = 1 if self._cpol == self._cpha else 0
            record: dict[int, int] = {}
            samples = 0

            def drive(k: int) -> None:
                value = beats.get(k, 0)
                dut.spi_sd_i.value = value
                if k in beats:
                    record[k] = value

            if self._cpha == 0:
                drive(0)
            while True:
                await First(Edge(sck), RisingEdge(cs_n))
                cs = cs_n.value
                if cs.is_resolvable and int(cs) == 1:
                    break
                level = sck.value
                if not level.is_resolvable:
                    continue
                if int(level) == sample_level:
                    samples += 1
                else:
                    drive(samples)
            dut.spi_sd_i.value = 0
            self.driven = self._rebuild(record, spans)
            self.windows += 1


def pack_tx_words(data: bytes) -> list[int]:
    """TXDATA words of one TX segment (ByteOrder 1), the last word zero-padded."""
    padded = bytes(data) + b"\0" * (-len(data) % 4)
    return [int.from_bytes(padded[i : i + 4], "little") for i in range(0, len(padded), 4)]


def unpack_rx_words(words: Sequence[int], n: int) -> bytes:
    """The ``n`` bytes of one RX segment from its RXDATA words (ByteOrder 1)."""
    return b"".join((int(w) & 0xFFFF_FFFF).to_bytes(4, "little") for w in words)[:n]


async def run_lane_frame(
    ops: Any,
    segments: Sequence[Segment],
    *,
    responder: SepSpiLaneResponder | None = None,
    bound: int = 20_000,
) -> bytes:
    """Issue one raw frame and return the RX bytes the DUT delivered.

    ``segments`` is the ``SepSpiScoreboard.expect_frame`` list. Every segment
    but the last has CSAAT = 1. With ``responder`` the RX bytes of the
    segments are loaded into it first. The leaf takes ``sb.frame_mark()``
    before the call and grades the frame with ``expect_frame`` after it.
    The RX bytes of the segments before the last must fit the RX FIFO.
    The return value is the RX bytes of every RX segment in order, each
    segment cut from its own word-aligned RXDATA words. A frame that leaves
    an RXDATA word after the last expected one raises ``AssertionError``.
    """
    if responder is not None:
        responder.load(segments)
    rx_lens: list[int] = []
    for i, (lanes, kind, value) in enumerate(segments):
        n = _seg_len(kind, value)
        if n < 1:
            raise ValueError(f"segment {i} ({kind} x{lanes}) has length 0")
        cmd = command_word(
            n - 1, speed=SPEED[lanes], direction=DIRECTION[kind], csaat=int(i < len(segments) - 1)
        )
        await ops.issue_command(cmd)
        if kind == "tx" and not isinstance(value, int):
            for word in pack_tx_words(value):
                await ops.push_tx(word)
        if kind == "rx":
            rx_lens.append(n)
    need = sum((n + 3) // 4 for n in rx_lens)
    words: list[int] = []
    for _ in range(bound):
        st = await ops.read_status()
        if len(words) < need and not st.rxempty:
            words.append(await ops.pop_rx())
            continue
        if len(words) == need and st.active == 0 and st.cmdqd == 0:
            # The frame is done, so an RXDATA word left now is one too many.
            if not st.rxempty:
                raise AssertionError(
                    f"SPI lane frame left RXEMPTY=0 after {need} RXDATA words: rxqd={st.rxqd}"
                )
            break
    else:
        raise AssertionError(
            f"SPI lane frame not done after {bound} STATUS reads: rx_words={len(words)}/{need}"
        )
    delivered = bytearray()
    pos = 0
    for n in rx_lens:
        count = (n + 3) // 4
        delivered += unpack_rx_words(words[pos : pos + count], n)
        pos += count
    return bytes(delivered)


async def spi_lane_fcov(
    test: str,
    kind: str,
    *,
    lanes: int = 1,
    rx: bool = False,
    opcode: int = 0,
    oe_win: int = 0,
    abort: int = 0,
    chain: int = 0,
) -> bool:
    """Record one graded SPI lane/OE event; call only after its check passed.

    ``kind``: ``data`` (``lanes``, ``rx``), ``opcode`` (``opcode``), ``oe``
    (``oe_win``: 0 cold reset, 1 OUTPUT_EN = 0, 2 CS high, 3 CS low),
    ``trigger`` (RXQD == RX_WATERMARK), ``abort`` (``abort``: 0 SW_RST,
    1 rst_ni; with ``lanes``), ``chain`` (``chain``: 0 same width, 1 width
    changes). Returns False on Verilator (no sampler). On any other simulator
    a sampler without ``spi_ln_seq`` is a testbench error.
    """
    if kind not in _KIND:
        raise ValueError(f"spi_lane_fcov kind={kind!r}: one of {sorted(_KIND)}")
    if lanes not in SPEED:
        raise ValueError(f"spi_lane_fcov lanes={lanes}: must be 1, 2 or 4")
    code = owner_code(test)
    if not fcov_present():
        return False
    top: Any = cocotb.top
    fcov = top.u_sep_fcov
    if not hasattr(fcov, "spi_ln_seq"):
        raise AttributeError("u_sep_fcov has no spi_ln_seq variable (cov/sv/sep_fcov.sv)")
    fcov.spi_ln_owner.value = code
    fcov.spi_ln_kind.value = _KIND[kind]
    fcov.spi_ln_width.value = SPEED[lanes]
    fcov.spi_ln_dir.value = int(bool(rx))
    fcov.spi_ln_opcode.value = opcode & 0xFF
    fcov.spi_ln_oe_win.value = oe_win & 0x3
    fcov.spi_ln_abort.value = abort & 1
    fcov.spi_ln_chain.value = chain & 1
    fcov.spi_ln_seq.value = (int(fcov.spi_ln_seq.value) + 1) & 0xFFFF_FFFF
    await ClockCycles(top.clk_i, 2)
    return True
