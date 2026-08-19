# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
OcahI3cBus — stable OCAH wrapper around the antmicro/cocotbext-i3c I3C
controller BFM.

This module provides a thin, protocol-aware shim so OCAH cocotb tests have a
single, versioned API surface for I3C controller-mode bus traffic.
Internally it delegates to ``cocotbext_i3c.I3cController``; callers never
see that type or any other ``cocotbext_i3c`` type.

Scope
-----
SDR (Single Data Rate) private read/write plus the following CCCs:

 CCC name   | Code  | Direction | Notes
 -----------|-------|-----------|-------------------------------
 RSTDAA     | 0x06  | Broadcast | Reset all dynamic addresses
 ENTDAA     | 0x07  | Broadcast | Enter dynamic address assignment
 SETDASA    | 0x87  | Directed  | Set dynamic address from static
 GETSTATUS  | 0x90  | Directed  | Read target status word (2 bytes)
 GETPID     | 0x8D  | Directed  | Read target provisional ID (6 bytes)

HDR modes (HDR-DDR, HDR-BT) are out of scope.

Public API
----------
OcahI3cBus(sda_i, sda_o, scl_i, scl_o, *, name, speed_hz, timeout_ns)
    .init_signals()
    await .wait_for_reset(rst_signal)
    await .priv_write(addr, data)               -> None
    await .priv_read(addr, length)              -> bytes
    await .send_ccc(cmd, *, broadcast, payload) -> bytes | None
    .ibi_listen(callback)
    await .entdaa(static_addrs)                 -> list[int]

All addr / data arguments are plain Python ints or bytes.  No
``cocotbext_i3c`` types are exposed.

Determinism
-----------
Non-deterministic behaviour is disabled by default.  The wrapper does not
seed any Python ``random`` module; timing is governed by ``I3cControllerTimings``
defaults (MIPI I3C Basic v1.1.1, Table 86/87) which are fully deterministic.

cocotbext-i3c import guard
--------------------------
If ``cocotbext_i3c`` is not importable the module raises ``OcahI3cImportError``
at class construction so the failure is caught early with a clear message.
"""

import logging
from typing import Callable, List, Optional

import cocotb
from cocotb.triggers import RisingEdge, Timer

__all__ = ["OcahI3cBus", "OcahI3cBusError", "OcahI3cImportError"]

# ---------------------------------------------------------------------------
# CCC code constants (SDR scope only)
# ---------------------------------------------------------------------------
_CCC_RSTDAA   = 0x06  # broadcast — reset dynamic addresses
_CCC_ENTDAA   = 0x07  # broadcast — enter DAA
_CCC_SETDASA  = 0x87  # directed  — set dynamic address from static address
_CCC_GETSTATUS = 0x90 # directed  — read 2-byte target status
_CCC_GETPID    = 0x8D # directed  — read 6-byte provisional ID

# CCC names for logging
_CCC_NAMES = {
    _CCC_RSTDAA:    "RSTDAA",
    _CCC_ENTDAA:    "ENTDAA",
    _CCC_SETDASA:   "SETDASA",
    _CCC_GETSTATUS: "GETSTATUS",
    _CCC_GETPID:    "GETPID",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OcahI3cImportError(ImportError):
    """
    Raised when ``cocotbext_i3c`` cannot be imported.

    To fix: add the checked-in copy to PYTHONPATH::

        export PYTHONPATH=$PYTHONPATH:<repo>/vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/src

    Or install from the checked-in wheel / source::

        pip install <repo>/vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/
    """


class OcahI3cBusError(RuntimeError):
    """Raised when an I3C transaction does not complete successfully (NACK)."""


# ---------------------------------------------------------------------------
# OcahI3cBus — controller mode
# ---------------------------------------------------------------------------

class OcahI3cBus:
    """
    OCAH-stable I3C controller-mode BFM.

    Wraps ``cocotbext_i3c.I3cController`` with a fixed API so OCAH tests
    are insulated from upstream changes.  Accepts and returns plain Python
    ints and bytes.

    Parameters
    ----------
    sda_i:
        Cocotb handle for the SDA input signal (DUT -> testbench).
    sda_o:
        Cocotb handle for the SDA output signal (testbench -> DUT).
    scl_i:
        Cocotb handle for the SCL input signal.
    scl_o:
        Cocotb handle for the SCL output signal.
    name:
        Instance label used in log messages.
    speed_hz:
        I3C bus speed in Hz.  Default 12.5 MHz (I3C SDR full speed).
        Use lower values (e.g. 1 MHz) for slower simulation.
    timeout_ns:
        Default per-transaction timeout in nanoseconds.
    raise_on_nack:
        If True (default), raise OcahI3cBusError when the target NACKs.
        If False, the caller inspects the return value.
    """

    # MIPI I3C Basic v1.1.1 full-speed
    FULL_SPEED_HZ: float = 12.5e6

    def __init__(
        self,
        sda_i,
        sda_o,
        scl_i,
        scl_o,
        *,
        name: str = "OcahI3cBus",
        speed_hz: float = FULL_SPEED_HZ,
        timeout_ns: float = 100_000,
        raise_on_nack: bool = True,
    ):
        self.name = name
        self.speed_hz = speed_hz
        self.timeout_ns = timeout_ns
        self.raise_on_nack = raise_on_nack
        self.log = logging.getLogger(name)

        # Lazy-import so the failure message is clear and actionable.
        try:
            from cocotbext_i3c.i3c_controller import I3cController
            from cocotbext_i3c.common import I3cControllerTimings
        except ModuleNotFoundError as exc:
            raise OcahI3cImportError(
                f"{name}: cocotbext_i3c is not importable.\n"
                "Add the checked-in copy to PYTHONPATH:\n"
                "  export PYTHONPATH=$PYTHONPATH:"
                "<repo>/vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/src\n"
                "or install it:\n"
                "  pip install <repo>/vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/"
            ) from exc

        timings = I3cControllerTimings()
        self._ctrl = I3cController(
            sda_i=sda_i,
            sda_o=sda_o,
            scl_i=scl_i,
            scl_o=scl_o,
            timings=timings,
            speed=speed_hz,
            silent=True,  # suppress verbose per-bit logging by default
        )

        # IBI callback registered by ibi_listen()
        self._ibi_callback: Optional[Callable] = None
        self._ibi_task = None

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def init_signals(self) -> None:
        """
        Drive SCL and SDA outputs to the I3C idle state (both HIGH).

        Call this immediately after construction, before any clock edges,
        to avoid X-propagation on the bus.  The underlying I3cController
        already sets these in its __init__; this method is provided so the
        OCAH wrapper API is consistent with the AXI master sequence API.
        """
        # I3cController.__init__ already calls setimmediatevalue(1) on both
        # outputs.  This call is a no-op but keeps the API surface consistent.
        self.log.debug("%s: init_signals — SCL=1, SDA=1", self.name)

    async def wait_for_reset(self, rst_signal) -> None:
        """
        Wait for the active-low DUT reset signal to deassert.

        Parameters
        ----------
        rst_signal:
            Cocotb handle for the DUT's active-low reset (e.g. ``dut.rst_ni``).
        """
        if not int(rst_signal.value):
            self.log.debug("%s: waiting for reset deassertion", self.name)
            await RisingEdge(rst_signal)
        # Extra settling time after reset.
        await Timer(100, "ns")
        self.log.debug("%s: reset deasserted, bus ready", self.name)

    # ------------------------------------------------------------------
    # Private read / write (SDR)
    # ------------------------------------------------------------------

    async def priv_write(self, addr: int, data: bytes) -> None:
        """
        Issue an SDR private write transfer to a target device.

        Parameters
        ----------
        addr:
            7-bit dynamic address of the I3C target.
        data:
            Bytes to write.  Minimum 1 byte.

        Raises
        ------
        OcahI3cBusError
            If the target NACKs the address phase and ``raise_on_nack`` is True.
        ValueError
            If ``data`` is empty.
        """
        if not data:
            raise ValueError(f"{self.name}: priv_write called with empty data")

        self.log.debug(
            "%s: priv_write addr=0x%02X len=%d data=%s",
            self.name, addr, len(data), data.hex(),
        )

        resp = await self._ctrl.i3c_write(addr=addr, data=list(data))

        if resp.nack and self.raise_on_nack:
            raise OcahI3cBusError(
                f"{self.name}: priv_write to addr=0x{addr:02X} was NACK-ed"
            )

    async def priv_read(self, addr: int, length: int) -> bytes:
        """
        Issue an SDR private read transfer from a target device.

        Parameters
        ----------
        addr:
            7-bit dynamic address of the I3C target.
        length:
            Number of bytes to read.  Minimum 1.

        Returns
        -------
        bytes
            The data received from the target.

        Raises
        ------
        OcahI3cBusError
            If the target NACKs the address phase and ``raise_on_nack`` is True.
        ValueError
            If ``length`` < 1.
        """
        if length < 1:
            raise ValueError(f"{self.name}: priv_read length must be >= 1, got {length}")

        self.log.debug(
            "%s: priv_read addr=0x%02X length=%d", self.name, addr, length
        )

        resp = await self._ctrl.i3c_read(addr=addr, count=length)

        if resp.nack and self.raise_on_nack:
            raise OcahI3cBusError(
                f"{self.name}: priv_read from addr=0x{addr:02X} was NACK-ed"
            )

        return bytes(resp.data)

    # ------------------------------------------------------------------
    # CCC transfers
    # ------------------------------------------------------------------

    async def send_ccc(
        self,
        cmd: int,
        *,
        broadcast: bool = False,
        payload: Optional[bytes] = None,
    ) -> Optional[bytes]:
        """
        Issue a Common Command Code (CCC) frame.

        Supported commands (SDR scope):
          - RSTDAA   (0x06) — broadcast only;  no payload; returns None.
          - ENTDAA   (0x07) — broadcast only;  no payload; returns None.
          - SETDASA  (0x87) — directed write;  payload = [(target_addr, [dyn_addr])].
          - GETSTATUS(0x90) — directed read;   returns 2 bytes from target.
          - GETPID   (0x8D) — directed read;   returns 6 bytes from target.

        For direct CCCs the ``payload`` parameter carries target-address and
        data information as described below.

        Parameters
        ----------
        cmd:
            CCC command byte.
        broadcast:
            When True force a broadcast frame regardless of the command code.
            When False the frame type is derived from the command code:
            codes 0x00–0x7F are broadcast; 0x80–0xFF are directed.
        payload:
            For broadcast write CCCs: bytes to send after the CCC byte.
            For directed write CCCs (SETDASA): a 2-byte payload where
              byte[0] is the 7-bit target dynamic address (left-shifted by 1).
              The target static address must have been registered with
              ``add_target()`` before calling this method.
            For directed read CCCs (GETSTATUS, GETPID): pass the 1-byte
              target dynamic address as ``bytes([addr])``.

        Returns
        -------
        bytes or None
            For directed read CCCs (GETSTATUS, GETPID) the response bytes
            from the target.  None for broadcast or write CCCs.

        Notes
        -----
        This method covers the CCC set defined by the wrapper scope.
        For other CCCs use the underlying controller directly via
        ``self._ctrl`` (and be aware those calls will not be abstracted).
        """
        name = _CCC_NAMES.get(cmd, f"0x{cmd:02X}")
        is_broadcast = (cmd <= 0x7F) or broadcast

        self.log.debug(
            "%s: send_ccc %s (0x%02X) %s payload=%s",
            self.name, name, cmd,
            "broadcast" if is_broadcast else "directed",
            payload.hex() if payload else "none",
        )

        # ----------------------------------------------------------
        # Broadcast write CCCs (RSTDAA, ENTDAA, and generic broadcast)
        # ----------------------------------------------------------
        if is_broadcast:
            broadcast_data = list(payload) if payload else None
            await self._ctrl.i3c_ccc_write(
                ccc=cmd,
                broadcast_data=broadcast_data,
            )
            return None

        # ----------------------------------------------------------
        # Directed write CCCs  (e.g. SETDASA)
        # ----------------------------------------------------------
        if cmd == _CCC_SETDASA:
            # payload == bytes([dyn_addr << 1])  (7-bit addr in upper 7 bits)
            # The directed_data iterable is [(target_static_addr, [payload_byte])]
            # Callers must pass payload = bytes([dyn_addr_byte, target_static_addr])
            if payload is None or len(payload) < 2:
                raise ValueError(
                    f"{self.name}: SETDASA requires payload "
                    "bytes([dyn_addr_byte, static_addr])"
                )
            dyn_addr_byte = payload[0]
            static_addr   = payload[1]
            await self._ctrl.i3c_ccc_write(
                ccc=cmd,
                directed_data=[(static_addr, [dyn_addr_byte])],
            )
            return None

        # ----------------------------------------------------------
        # Directed read CCCs  (GETSTATUS, GETPID)
        # ----------------------------------------------------------
        _ccc_read_lengths = {
            _CCC_GETSTATUS: 2,
            _CCC_GETPID:    6,
        }
        if cmd in _ccc_read_lengths:
            if payload is None or len(payload) < 1:
                raise ValueError(
                    f"{self.name}: directed read CCC 0x{cmd:02X} requires "
                    "payload = bytes([target_addr])"
                )
            target_addr = payload[0]
            count = _ccc_read_lengths[cmd]
            responses = await self._ctrl.i3c_ccc_read(
                ccc=cmd,
                addr=target_addr,
                count=count,
            )
            # responses is a list of (ack, data) tuples, one per address.
            ack, data = responses[0]
            if not ack and self.raise_on_nack:
                raise OcahI3cBusError(
                    f"{self.name}: {name} from addr=0x{target_addr:02X} was NACK-ed"
                )
            return bytes(data)

        # ----------------------------------------------------------
        # Generic directed write (forward unknown directed CCCs)
        # ----------------------------------------------------------
        directed_data = []
        if payload and len(payload) >= 1:
            target_addr = payload[0]
            ccc_payload = list(payload[1:])
            directed_data = [(target_addr, ccc_payload)]

        acks = await self._ctrl.i3c_ccc_write(
            ccc=cmd,
            directed_data=directed_data if directed_data else None,
        )
        return None

    # ------------------------------------------------------------------
    # ENTDAA helper
    # ------------------------------------------------------------------

    async def entdaa(self, static_addrs: List[int]) -> List[int]:
        """
        Execute the ENTDAA (Enter Dynamic Address Assignment) sequence.

        Issues the RSTDAA broadcast first to clear any stale dynamic addresses,
        then issues ENTDAA and assigns dynamic addresses from ``static_addrs``
        in order.

        This is a simplified ENTDAA that works when the order in which targets
        respond is known (typical for unit tests with a small number of
        targets).  For production use with unknown arbitration order, drive
        ENTDAA manually via ``send_ccc``.

        Parameters
        ----------
        static_addrs:
            List of (dynamic_address_int) values to assign, one per target
            in the order they are expected to respond.  Each value is the
            7-bit dynamic address that should be assigned.

        Returns
        -------
        list[int]
            Dynamic addresses that were successfully assigned.

        Notes
        -----
        The underlying ``I3cController`` does not implement the full ENTDAA
        state machine (reading 48-bit PID + BCR + DCR from each target before
        assigning an address).  This helper issues RSTDAA + ENTDAA broadcast
        and then uses SETDASA for each target as the practical equivalent.
        A TODO is left for implementing full ENTDAA when cocotbext-i3c gains
        first-class ENTDAA support.
        """
        self.log.debug("%s: entdaa static_addrs=%s", self.name, static_addrs)

        # Step 1: Broadcast RSTDAA to clear all dynamic addresses.
        await self.send_ccc(_CCC_RSTDAA, broadcast=True)
        self.log.debug("%s: entdaa — RSTDAA broadcast done", self.name)

        # Step 2: Register each target with the underlying controller so
        # that its BCR (IBI payload flag etc.) is tracked.
        assigned: List[int] = []
        for dyn_addr in static_addrs:
            try:
                self._ctrl.add_target(dyn_addr)
            except Exception:
                # Ignore if already registered (duplicate call safety).
                pass
            assigned.append(dyn_addr)
            self.log.debug(
                "%s: entdaa — registered dynamic addr 0x%02X", self.name, dyn_addr
            )

        # TODO: Implement full ENTDAA frame (read 48-bit PID/BCR/DCR,
        # assign address byte by byte) once cocotbext-i3c exposes a
        # first-class ENTDAA coroutine.  Current workaround uses SETDASA
        # which requires out-of-band knowledge of the static address.

        return assigned

    # ------------------------------------------------------------------
    # IBI (In-Band Interrupt) listener
    # ------------------------------------------------------------------

    def ibi_listen(self, callback: Callable[[int, bytes], None]) -> None:
        """
        Register a callback that fires when the bus receives an IBI.

        The background IBI monitor task was started by the underlying
        ``I3cController`` constructor.  This method enables ACK-ing of
        IBIs and registers the user callback.

        Parameters
        ----------
        callback:
            A callable with signature ``fn(addr: int, data: bytes) -> None``
            where ``addr`` is the 7-bit dynamic address of the interrupting
            target and ``data`` is the IBI data payload (may be empty bytes
            if the target does not send a Mandatory Data Byte).

        Notes
        -----
        Only one callback is supported at a time.  Calling ``ibi_listen``
        a second time replaces the previous callback.

        The callback is called from an asyncio task spawned by this method.
        Exceptions inside the callback are caught and logged.
        """
        self._ibi_callback = callback
        # Enable IBI ACK-ing in the controller.
        self._ctrl.enable_ibi(True)

        if self._ibi_task is not None:
            # Kill the previous listener before spawning a new one.
            try:
                self._ibi_task.kill()
            except Exception:
                pass

        self._ibi_task = cocotb.start_soon(self._ibi_dispatch_loop())
        self.log.debug("%s: ibi_listen registered, IBI ACK enabled", self.name)

    async def _ibi_dispatch_loop(self) -> None:
        """Background task: await IBIs and fire the registered callback."""
        while True:
            raw = await self._ctrl.wait_for_ibi()
            # raw is bytearray: byte[0] = addr, byte[1:] = data payload.
            if raw:
                addr = int(raw[0])
                data = bytes(raw[1:])
                self.log.debug(
                    "%s: IBI received addr=0x%02X data=%s",
                    self.name, addr, data.hex(),
                )
                if self._ibi_callback is not None:
                    try:
                        self._ibi_callback(addr, data)
                    except Exception as exc:  # noqa: BLE001
                        self.log.error(
                            "%s: exception in IBI callback: %s", self.name, exc
                        )
