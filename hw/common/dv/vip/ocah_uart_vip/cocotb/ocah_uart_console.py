# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""``OcahUartConsole``: the active UART console host.

One versioned API for console traffic in cocotb tests. The backend is native
to this package: ``OcahUartMasterDriver`` transmits on TXD and
``OcahUartLineMonitor`` samples RXD. Data crossing the API is plain Python
``str``, ``bytes``, ``int``, or ``OcahUartFrame``.

Timeouts are per operation and deterministic: a read on a silent line ends
exactly ``timeout_us`` microseconds of simulation time after it started, and
either raises ``OcahUartError`` or returns ``None`` (``raise_on_timeout``).
Frames a timed-out ``read_bytes`` or ``read_line`` had already taken stay
readable by the next read. A frame with a framing, parity, or break flag is
delivered as data and counted (``frame_errors``), or raised as
``OcahUartError`` when ``raise_on_frame_error`` is set.

The default format is 8-N-1; ``bits``, ``parity``, and ``stop_bits`` follow
the line engines. The baud rate defaults to 115200 and may be changed with
``set_baud()`` or the ``+uart_baud=<N>`` plusarg; a rate at or above 1 Mbaud
depends on the DUT clock and the simulation time resolution.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from typing import Any

from cocotb.triggers import SimTimeoutError, Timer, with_timeout

from .ocah_uart_master_driver import OcahUartMasterDriver
from .ocah_uart_monitor import OcahUartLineMonitor
from .ocah_uart_types import DEFAULT_BAUD, DEFAULT_TIMEOUT_US, OcahUartFrame, OcahUartParity

__all__ = ["OcahUartConsole", "OcahUartError", "OcahUartImportError"]


class OcahUartError(RuntimeError):
    """Raised on a UART timeout or, when enabled, on a flagged frame."""


class OcahUartImportError(ImportError):
    """Exported but never raised: the native backend has no import that can fail."""


_LINE_TERMINATOR = ord("\n")
_LOG_ENV_KEY = "COCOTB_PLUSARG_uart_log"
_BAUD_ENV_KEY = "COCOTB_PLUSARG_uart_baud"


class OcahUartConsole:
    """Active UART console host.

    Parameters
    ----------
    txd :
        Signal handle the console drives (the DUT's receive line).
    rxd :
        Signal handle the console samples (the DUT's transmit line).
    clock :
        Accepted for call-site symmetry; the line engines time frames from
        the baud rate.
    name :
        Instance label used in log messages.
    baud :
        Initial baud rate; ``+uart_baud=<N>`` overrides it.
    bits, parity, stop_bits :
        Frame format of both directions.
    timeout_us :
        Default per-operation timeout in microseconds.
    log_file :
        Optional path for a plaintext console log of received lines;
        ``+uart_log=<file>`` overrides it.
    raise_on_timeout :
        Raise ``OcahUartError`` on a timeout (``True``) or return ``None``.
        A public attribute; a test may change it between operations.
    raise_on_frame_error :
        Raise ``OcahUartError`` when a received frame carries a framing,
        parity, or break flag instead of delivering its data. A public
        attribute as well.
    """

    def __init__(
        self,
        txd: Any,
        rxd: Any,
        clock: Any = None,
        *,
        name: str = "OcahUartConsole",
        baud: int = DEFAULT_BAUD,
        bits: int = 8,
        parity: OcahUartParity | str = OcahUartParity.NONE,
        stop_bits: float = 1,
        timeout_us: int = DEFAULT_TIMEOUT_US,
        log_file: str | None = None,
        raise_on_timeout: bool = True,
        raise_on_frame_error: bool = False,
    ) -> None:
        self.name = name
        self._clock = clock
        self._default_timeout = int(timeout_us)
        self.raise_on_timeout = raise_on_timeout
        self.raise_on_frame_error = raise_on_frame_error
        self.log = logging.getLogger(name)

        env_baud = os.environ.get(_BAUD_ENV_KEY)
        if env_baud is not None:
            try:
                baud = int(env_baud)
                self.log.info("%s: baud overridden by plusarg to %d", name, baud)
            except ValueError:
                self.log.warning("%s: invalid +uart_baud value %r; using %d", name, env_baud, baud)
        self._baud = int(baud)

        env_log = os.environ.get(_LOG_ENV_KEY)
        if env_log is not None:
            log_file = env_log
        self._log_fh: Any = None
        if log_file:
            try:
                self._log_fh = open(log_file, "a", encoding="utf-8")  # noqa: SIM115
                self.log.info("%s: console output logged to %s", name, log_file)
            except OSError as exc:
                self.log.warning("%s: cannot open log file %s: %s", name, log_file, exc)

        fmt: dict[str, Any] = {
            "baud": self._baud,
            "bits": bits,
            "parity": parity,
            "stop_bits": stop_bits,
        }
        self._source = OcahUartMasterDriver(txd, name=f"{name}.tx", **fmt)
        self._sink = OcahUartLineMonitor(rxd, name=f"{name}.rx", **fmt)
        self._pending: list[OcahUartFrame] = []

        self._stats: dict[str, int] = {
            "bytes_sent": 0,
            "bytes_received": 0,
            "lines_received": 0,
            "timeouts": 0,
            "frame_errors": 0,
        }

    @classmethod
    def from_prefix(
        cls,
        dut: Any,
        prefix: str,
        *,
        clock: Any = None,
        rx_name: str | None = None,
        tx_name: str | None = None,
        **kwargs: Any,
    ) -> OcahUartConsole:
        """Bind to flattened DUT ports named from the DUT's point of view.

        ``<prefix>_rx`` is the DUT's receive line, which the console drives;
        ``<prefix>_tx`` is the DUT's transmit line, which the console samples.
        ``rx_name`` and ``tx_name`` replace either full port name.
        """
        rx = getattr(dut, rx_name or f"{prefix}_rx")
        tx = getattr(dut, tx_name or f"{prefix}_tx")
        return cls(rx, tx, clock, **kwargs)

    # ------------------------------------------------------------------
    # Engines and lifecycle
    # ------------------------------------------------------------------

    @property
    def source(self) -> OcahUartMasterDriver:
        """The line driver behind the transmit path."""
        return self._source

    @property
    def sink(self) -> OcahUartLineMonitor:
        """The sampler behind the receive path."""
        return self._sink

    @property
    def baud(self) -> int:
        return self._baud

    def init_signals(self) -> None:
        """Log the format; the line driver already holds TXD at idle from construction."""
        self.log.info(
            "%s: UART initialised: baud=%d bits=%d parity=%s stop=%g",
            self.name,
            self._baud,
            self._source.bits,
            self._source.parity.value,
            self._source.stop_bits,
        )

    async def set_baud(self, rate: int) -> None:
        """Change the baud rate of both directions; no frame may be in flight."""
        if rate <= 0:
            raise ValueError(f"{self.name}: baud rate must be positive, got {rate}")
        self._baud = int(rate)
        self._source.baud = self._baud
        self._sink.baud = self._baud
        self.log.info("%s: baud changed to %d", self.name, self._baud)
        await Timer(1, "step")

    def configure(
        self,
        *,
        bits: int | None = None,
        parity: OcahUartParity | str | None = None,
        stop_bits: float | None = None,
    ) -> None:
        """Change the frame format of both directions; lands on the next frame."""
        self._source.configure(bits=bits, parity=parity, stop_bits=stop_bits)
        self._sink.configure(bits=bits, parity=parity, stop_bits=stop_bits)

    # ------------------------------------------------------------------
    # Transmit
    # ------------------------------------------------------------------

    async def send_byte(self, b: int) -> None:
        """Queue one frame value."""
        await self._source.write([int(b)])
        self._stats["bytes_sent"] += 1
        self.log.debug("%s: sent 0x%02X", self.name, b)

    async def send_bytes(self, data: bytes | bytearray | Iterable[int]) -> None:
        """Queue a sequence of frame values."""
        values = [int(value) for value in data]
        await self._source.write(values)
        self._stats["bytes_sent"] += len(values)
        self.log.debug("%s: sent %d frames", self.name, len(values))

    async def send_string(self, s: str, encoding: str = "ascii") -> None:
        """Encode ``s`` and queue it; a newline is sent as 0x0A."""
        await self.send_bytes(s.encode(encoding))
        self.log.debug("%s: sent string %r", self.name, s)

    async def send_framing_error(self, b: int) -> None:
        """Queue a frame of ``b`` whose stop bit is low."""
        await self._source.inject_framing_error(int(b))

    async def send_parity_error(self, b: int) -> None:
        """Queue a frame of ``b`` whose parity bit is inverted; needs a parity format."""
        await self._source.inject_parity_error(int(b))

    async def send_break(self, periods: float | None = None) -> None:
        """Queue a break: the line low for ``periods`` bit periods (default: one frame plus one)."""
        await self._source.send_break(periods)

    async def send_glitch(self, width_ns: int) -> None:
        """Queue a low pulse shorter than half a bit."""
        await self._source.send_glitch(width_ns)

    async def flush(self) -> None:
        """Wait until every queued frame has left the wire and TXD idles."""
        await self._source.wait()

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def read_frame(self, timeout_us: int | None = None) -> OcahUartFrame | None:
        """The next received frame with its flags; ``None`` or a raise on timeout."""
        t_us = self._budget(timeout_us)
        frame = await self._next_frame(t_us)
        if frame is None:
            self._timed_out(f"read_frame timed out after {t_us} us")
            return None
        self._account(frame)
        return frame

    async def read_byte(self, timeout_us: int | None = None) -> int | None:
        """The next received value; ``None`` or a raise on timeout."""
        t_us = self._budget(timeout_us)
        frame = await self._next_frame(t_us)
        if frame is None:
            self._timed_out(f"read_byte timed out after {t_us} us")
            return None
        self._deliver(frame)
        self.log.debug("%s: received 0x%02X", self.name, frame.data)
        return frame.data

    async def read_bytes(self, n: int, timeout_us: int | None = None) -> bytes | None:
        """Exactly ``n`` values, each awaited under ``timeout_us``.

        On a timeout the frames already taken stay readable by the next read.
        """
        t_us = self._budget(timeout_us)
        taken: list[OcahUartFrame] = []
        for _ in range(n):
            frame = await self._next_frame(t_us)
            if frame is None:
                self._pending[:0] = taken
                self._timed_out(
                    f"read_bytes({n}) timed out after {t_us} us with {len(taken)} taken"
                )
                return None
            taken.append(frame)
        for frame in taken:
            self._deliver(frame)
        return bytes(frame.data & 0xFF for frame in taken)

    async def read_line(self, timeout_us: int | None = None, encoding: str = "ascii") -> str | None:
        """Values up to a newline, decoded; the newline is stripped.

        ``timeout_us`` bounds the wait for each value. On a timeout the
        frames already taken stay readable by the next read. An undecodable
        value becomes ``?``.
        """
        t_us = self._budget(timeout_us)
        taken: list[OcahUartFrame] = []
        while True:
            frame = await self._next_frame(t_us)
            if frame is None:
                partial = bytes(f.data & 0xFF for f in taken)
                self._pending[:0] = taken
                self._timed_out(f"read_line timed out after {t_us} us (partial: {partial!r})")
                return None
            taken.append(frame)
            if frame.data == _LINE_TERMINATOR:
                break
        for frame in taken:
            self._deliver(frame)
        line = bytes(f.data & 0xFF for f in taken[:-1]).decode(encoding, errors="replace")
        self._stats["lines_received"] += 1
        self.log.info("%s: RX line: %r", self.name, line)
        if self._log_fh:
            try:
                self._log_fh.write(line + "\n")
                self._log_fh.flush()
            except OSError:
                pass
        return line

    async def expect(
        self,
        pattern: str,
        timeout_us: int | None = None,
        encoding: str = "ascii",
    ) -> str:
        """Lines until one matches ``pattern`` (a regular expression); raises on timeout."""
        t_us = self._budget(timeout_us)
        regexp = re.compile(pattern)
        while True:
            line = await self.read_line(timeout_us=t_us, encoding=encoding)
            if line is None:
                raise OcahUartError(f"{self.name}: expect({pattern!r}) timed out after {t_us} us")
            if regexp.search(line):
                self.log.info("%s: expect(%r) matched line: %r", self.name, pattern, line)
                return line

    # ------------------------------------------------------------------
    # History and statistics
    # ------------------------------------------------------------------

    def tx_frames(self) -> list[OcahUartFrame]:
        """Frames the console drove, oldest first."""
        return self._source.get_frames()

    def rx_frames(self) -> list[OcahUartFrame]:
        """Frames the console sampled, oldest first, read or not."""
        return self._sink.get_frames()

    def get_statistics(self) -> dict[str, Any]:
        """Copy of the cumulative counters."""
        return dict(self._stats)

    def reset_statistics(self) -> None:
        """Zero every counter."""
        for key in self._stats:
            self._stats[key] = 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _budget(self, timeout_us: int | None) -> int:
        return int(timeout_us) if timeout_us is not None else self._default_timeout

    async def _next_frame(self, t_us: int) -> OcahUartFrame | None:
        if self._pending:
            return self._pending.pop(0)
        try:
            frame: OcahUartFrame = await with_timeout(self._sink.read_frame(), t_us, "us")
        except SimTimeoutError:
            self._stats["timeouts"] += 1
            return None
        return frame

    def _timed_out(self, message: str) -> None:
        """Raise when the console raises on timeouts; otherwise the caller returns ``None``."""
        if self.raise_on_timeout:
            raise OcahUartError(f"{self.name}: {message}")

    def _account(self, frame: OcahUartFrame) -> None:
        self._stats["bytes_received"] += 1
        if not frame.clean:
            self._stats["frame_errors"] += 1

    def _deliver(self, frame: OcahUartFrame) -> None:
        self._account(frame)
        if not frame.clean and self.raise_on_frame_error:
            kind = "break" if frame.is_break else "framing" if frame.framing_error else "parity"
            raise OcahUartError(
                f"{self.name}: {kind} error on 0x{frame.data:02X} at {frame.start_ns} ns"
            )

    def __del__(self) -> None:
        if self._log_fh:
            try:
                self._log_fh.close()
            except OSError:
                pass
