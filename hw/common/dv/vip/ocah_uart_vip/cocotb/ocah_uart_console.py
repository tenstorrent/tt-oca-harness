# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
OcahUartConsole — OCAH-stable active UART console wrapper.

Provides a single, versioned API for driving UART serial traffic (8N1) in
OCAH cocotb tests.  The backend is native to this package:
``OcahUartMasterDriver`` transmits on TXD and ``OcahUartLineMonitor``
samples RXD.  No external UART library is required.

Public API
----------
OcahUartConsole(txd, rxd, clock, *, name, baud, timeout_us)
    .init_signals()
    await .set_baud(rate)
    await .send_byte(b)
    await .send_bytes(data)
    await .send_string(s, encoding="ascii")
    await .read_byte(timeout_us=None)   -> int
    await .read_bytes(n, timeout_us=None) -> bytes
    await .read_line(timeout_us=None)   -> str
    await .expect(pattern, timeout_us=None) -> str
    .get_statistics() -> dict
    .reset_statistics()

All data crossing the API boundary is plain Python ``str``, ``bytes``, or
``int``; backend engine objects are not part of the console contract.

Protocol
--------
Standard 8N1 UART (8 data bits, no parity, 1 stop bit).  Baud rate defaults
to 115200 but is configurable via ``set_baud()`` or the ``+uart_baud=<N>``
plusarg.  High-speed modes (e.g. 4 Mbaud) are accepted but not validated
against DUT clock constraints — the caller is responsible.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional, Union

from cocotb.triggers import SimTimeoutError, Timer, with_timeout

from .ocah_uart_master_driver import OcahUartMasterDriver
from .ocah_uart_monitor import OcahUartLineMonitor

__all__ = ["OcahUartConsole", "OcahUartError", "OcahUartImportError"]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class OcahUartError(RuntimeError):
    """Raised on UART framing errors, timeouts, or unexpected data."""


class OcahUartImportError(ImportError):
    """Retained for backward compatibility.

    Earlier package versions delegated to an external UART library and raised
    this at construction time when it was missing.  The backend is now native
    to this package, so the console never raises it; existing callers that
    catch it keep working unchanged.
    """


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_BAUD = 115200
_DEFAULT_TIMEOUT_US = 1_000  # 1 ms default per-operation timeout
_LINE_TERMINATOR = "\n"
_LOG_ENV_KEY = "COCOTB_PLUSARG_uart_log"
_BAUD_ENV_KEY = "COCOTB_PLUSARG_uart_baud"


# ---------------------------------------------------------------------------
# OcahUartConsole
# ---------------------------------------------------------------------------


class OcahUartConsole:
    """
    OCAH-stable UART console host (8N1, configurable baud).

    Wraps the native ``OcahUartMasterDriver`` (TX) and ``OcahUartLineMonitor``
    (RX) line engines with a fixed API so OCAH tests are insulated from
    backend changes.  Accepts and returns plain Python ``str``, ``bytes``,
    and ``int``.

    Parameters
    ----------
    txd :
        Cocotb signal handle for the UART TX line (console host drives this).
    rxd :
        Cocotb signal handle for the UART RX line (console host reads this).
    clock :
        Cocotb clock handle.  Informational; the line engines time frames
        from the baud rate, not from this clock.
    name :
        Instance label used in log messages.
    baud :
        Initial baud rate.  Overridden by ``+uart_baud=<N>`` plusarg if set.
        Standard values: 9600, 19200, 38400, 57600, 115200, 921600.
    timeout_us :
        Default per-operation timeout in microseconds.  Overridden per-call
        when an explicit ``timeout_us`` argument is supplied.
    log_file :
        Optional path for a plaintext console log.  Overridden by the
        ``+uart_log=<file>`` plusarg.  When set, every received line is
        appended to the file in addition to the cocotb logger.
    raise_on_timeout :
        If ``True`` (default), ``read_byte`` / ``read_line`` / ``expect``
        raise ``OcahUartError`` on timeout.  If ``False``, return ``None``
        instead.
    """

    def __init__(
        self,
        txd,
        rxd,
        clock,
        *,
        name: str = "OcahUartConsole",
        baud: int = _DEFAULT_BAUD,
        timeout_us: int = _DEFAULT_TIMEOUT_US,
        log_file: Optional[str] = None,
        raise_on_timeout: bool = True,
    ):
        self.name = name
        self._clock = clock
        self._default_timeout = timeout_us
        self._raise_on_timeout = raise_on_timeout
        self.log = logging.getLogger(name)

        # Resolve plusargs: baud rate.
        env_baud = os.environ.get(_BAUD_ENV_KEY)
        if env_baud is not None:
            try:
                baud = int(env_baud)
                self.log.info("%s: baud overridden by plusarg to %d", name, baud)
            except ValueError:
                self.log.warning("%s: invalid +uart_baud value %r; using %d", name, env_baud, baud)
        self._baud = baud

        # Resolve plusargs: log file.
        env_log = os.environ.get(_LOG_ENV_KEY)
        if env_log is not None:
            log_file = env_log
        self._log_file: Optional[str] = log_file
        self._log_fh = None
        if log_file:
            try:
                self._log_fh = open(log_file, "a", encoding="utf-8")  # noqa: WPS515
                self.log.info("%s: console output logged to %s", name, log_file)
            except OSError as exc:
                self.log.warning("%s: cannot open log file %s: %s", name, log_file, exc)

        # Native line engines: the master driver transmits on TXD; the line
        # monitor samples RXD.
        self._source = OcahUartMasterDriver(txd, name=f"{name}.tx", baud=baud)
        self._sink = OcahUartLineMonitor(rxd, name=f"{name}.rx", baud=baud)

        # Line buffer: bytes accumulated since last read_line / expect call.
        self._rx_buf: bytes = b""

        # Statistics.
        self._stats: Dict[str, int] = {
            "bytes_sent": 0,
            "bytes_received": 0,
            "lines_received": 0,
            "timeouts": 0,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init_signals(self) -> None:
        """Drive TXD to idle (mark / logic-1) before the first clock edge.

        Call this immediately after construction to avoid X-propagation on
        the UART TX pin.  ``OcahUartMasterDriver`` already holds the line at
        logic-1 (MARK state) from construction; this method makes the intent
        explicit and logs the initial baud setting.
        """
        self.log.info("%s: UART initialised — baud=%d, 8N1", self.name, self._baud)

    async def set_baud(self, rate: int) -> None:
        """Change the baud rate.

        Both the TX source and RX sink are reconfigured.  There is no hardware
        handshake; callers must ensure no transaction is in progress when
        calling this method.

        Parameters
        ----------
        rate :
            New baud rate (e.g. 9600, 115200, 921600).
        """
        if rate <= 0:
            raise ValueError(f"{self.name}: baud rate must be positive, got {rate}")
        self._baud = rate
        self._source.baud = rate
        self._sink.baud = rate
        self.log.info("%s: baud changed to %d", self.name, rate)
        # Yield one delta cycle so signals settle.
        await Timer(1, "step")

    # ------------------------------------------------------------------
    # Transmit
    # ------------------------------------------------------------------

    async def send_byte(self, b: int) -> None:
        """Send a single byte over UART TX.

        Parameters
        ----------
        b :
            Byte value 0–255.
        """
        if not 0 <= b <= 255:
            raise ValueError(f"{self.name}: byte value out of range: {b}")
        await self._source.write(bytes([b]))
        self._stats["bytes_sent"] += 1
        self.log.debug("%s: sent byte 0x%02X", self.name, b)

    async def send_bytes(self, data: Union[bytes, bytearray, List[int]]) -> None:
        """Send a sequence of bytes over UART TX.

        Parameters
        ----------
        data :
            Byte sequence as ``bytes``, ``bytearray``, or a list of ints.
        """
        if isinstance(data, list):
            data = bytes(data)
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(
                f"{self.name}: send_bytes expects bytes/bytearray/list[int], "
                f"got {type(data).__name__}"
            )
        await self._source.write(bytes(data))
        self._stats["bytes_sent"] += len(data)
        self.log.debug("%s: sent %d bytes", self.name, len(data))

    async def send_string(self, s: str, encoding: str = "ascii") -> None:
        """Encode ``s`` and send it over UART TX.

        Parameters
        ----------
        s :
            String to transmit.  Newlines are sent as-is (``\\n`` = 0x0A).
        encoding :
            Python codec to use for encoding (default ``"ascii"``).
        """
        raw = s.encode(encoding)
        await self.send_bytes(raw)
        self.log.debug("%s: sent string %r", self.name, s)

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def read_byte(self, timeout_us: Optional[int] = None) -> Optional[int]:
        """Wait for and return the next received byte.

        Parameters
        ----------
        timeout_us :
            Timeout in microseconds.  Uses the instance default when ``None``.

        Returns
        -------
        int
            Received byte value 0–255.

        Raises
        ------
        OcahUartError
            If no byte arrives within ``timeout_us`` and
            ``raise_on_timeout=True``.
        """
        t_us = timeout_us if timeout_us is not None else self._default_timeout
        try:
            data = await with_timeout(
                self._sink.read(1),
                timeout_time=t_us,
                timeout_unit="us",
            )
        except SimTimeoutError:
            self._stats["timeouts"] += 1
            if self._raise_on_timeout:
                raise OcahUartError(f"{self.name}: read_byte timed out after {t_us} µs")
            return None

        self._stats["bytes_received"] += 1
        b = data[0]
        self.log.debug("%s: received byte 0x%02X", self.name, b)
        return b

    async def read_bytes(self, n: int, timeout_us: Optional[int] = None) -> Optional[bytes]:
        """Wait for and return exactly ``n`` bytes.

        Parameters
        ----------
        n :
            Number of bytes to read.
        timeout_us :
            Per-byte timeout budget (microseconds).  The total timeout is
            ``n * timeout_us``.

        Returns
        -------
        bytes
            Received bytes.
        """
        t_us = timeout_us if timeout_us is not None else self._default_timeout
        total_timeout = t_us * n
        try:
            data = await with_timeout(
                self._sink.read(n),
                timeout_time=total_timeout,
                timeout_unit="us",
            )
        except SimTimeoutError:
            self._stats["timeouts"] += 1
            if self._raise_on_timeout:
                raise OcahUartError(
                    f"{self.name}: read_bytes({n}) timed out after {total_timeout} µs"
                )
            return None

        self._stats["bytes_received"] += len(data)
        return bytes(data)

    async def read_line(
        self, timeout_us: Optional[int] = None, encoding: str = "ascii"
    ) -> Optional[str]:
        """Accumulate bytes until a newline (``\\n``) and return the line.

        The newline character is stripped from the returned string.  Bytes are
        decoded with ``encoding``; decoding errors replace the offending byte
        with ``?``.

        Parameters
        ----------
        timeout_us :
            Maximum wait per byte.  The total time may exceed this value if
            many bytes arrive.
        encoding :
            Python codec for decoding (default ``"ascii"``).

        Returns
        -------
        str
            Decoded line without trailing newline.
        """
        t_us = timeout_us if timeout_us is not None else self._default_timeout
        line_bytes = bytearray()

        while True:
            b = await self.read_byte(timeout_us=t_us)
            if b is None:
                # Timeout.
                if self._raise_on_timeout:
                    raise OcahUartError(
                        f"{self.name}: read_line timed out after {t_us} µs "
                        f"(partial: {line_bytes!r})"
                    )
                return None
            if b == ord("\n"):
                break
            line_bytes.append(b)

        line = line_bytes.decode(encoding, errors="replace")
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
        timeout_us: Optional[int] = None,
        encoding: str = "ascii",
    ) -> str:
        """Read lines until one matches ``pattern`` (regex) or timeout.

        Parameters
        ----------
        pattern :
            Regular expression to match against each received line.
        timeout_us :
            Per-line timeout budget in microseconds.
        encoding :
            Python codec for decoding received bytes.

        Returns
        -------
        str
            The first matching line (without trailing newline).

        Raises
        ------
        OcahUartError
            If no matching line arrives within budget.
        """
        t_us = timeout_us if timeout_us is not None else self._default_timeout
        regexp = re.compile(pattern)

        while True:
            line = await self.read_line(timeout_us=t_us, encoding=encoding)
            if line is None:
                raise OcahUartError(f"{self.name}: expect({pattern!r}) timed out")
            if regexp.search(line):
                self.log.info("%s: expect(%r) matched line: %r", self.name, pattern, line)
                return line

    # ------------------------------------------------------------------
    # Statistics / diagnostics
    # ------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        """Return a copy of the cumulative statistics counters."""
        return dict(self._stats)

    def reset_statistics(self) -> None:
        """Zero all cumulative counters."""
        for key in self._stats:
            self._stats[key] = 0

    def __del__(self) -> None:
        if self._log_fh:
            try:
                self._log_fh.close()
            except OSError:
                pass
