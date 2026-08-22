# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
OcahI3cTarget — stable OCAH wrapper around the antmicro/cocotbext-i3c
``I3CTarget`` class.

This module provides a target-mode I3C device model for use in cocotb
testbenches where the DUT is an I3C controller (e.g. the SMC).  The OCAH
wrapper keeps the API stable against upstream changes in ``cocotbext_i3c``.

Scope
-----
- Static address assignment (the target responds to a fixed 7-bit address).
- IBI registration: the target can be configured to assert an IBI.
- Response override: set the bytes the target returns on the next read.

SDR private read/write and basic CCC reception are handled by the underlying
``I3CTarget``.  HDR modes are out of scope.

Public API
----------
OcahI3cTarget(sda_i, sda_o, scl_i, scl_o, *, name, static_addr)
    .set_static_address(addr)
    .register_ibi(mdb, *, payload)
    .set_response(data)

All parameters and return values are plain Python ints or bytes objects.
No ``cocotbext_i3c`` types are exposed.

cocotbext-i3c import guard
--------------------------
If ``cocotbext_i3c`` is not importable an ``OcahI3cImportError`` is raised at
construction time.  See ``ocah_i3c_vip.OcahI3cImportError`` for fix
instructions.
"""

import logging
from typing import Optional

from .ocah_i3c_bus import OcahI3cImportError

__all__ = ["OcahI3cTarget", "OcahI3cTargetError"]


class OcahI3cTargetError(RuntimeError):
    """Raised on target-side configuration or runtime errors."""


class OcahI3cTarget:
    """
    OCAH-stable I3C target-mode device model.

    Wraps ``cocotbext_i3c.I3CTarget`` so OCAH tests have a single, stable
    API surface.  Accepts and returns plain Python ints and bytes.

    Typical use: instantiate one ``OcahI3cTarget`` per simulated target
    device, set its static address and optional read response, then let it
    run in the background while the ``OcahI3cBus`` (controller) drives traffic.

    Parameters
    ----------
    sda_i:
        Cocotb handle for the SDA input signal (bus -> target).
    sda_o:
        Cocotb handle for the SDA output signal (target -> bus).
    scl_i:
        Cocotb handle for the SCL input signal.
    scl_o:
        Cocotb handle for the SCL output signal.
    name:
        Instance label used in log messages.
    static_addr:
        7-bit static address.  Passed to the underlying ``I3CTarget``.
        If None, call ``set_static_address`` before starting the target.
    speed_hz:
        Bus speed in Hz.  Must match the controller speed.
    """

    def __init__(
        self,
        sda_i,
        sda_o,
        scl_i,
        scl_o,
        *,
        name: str = "OcahI3cTarget",
        static_addr: Optional[int] = None,
        speed_hz: float = 12.5e6,
    ):
        self.name = name
        self.log = logging.getLogger(name)
        self._static_addr = static_addr

        # Lazy import with clear error message.
        try:
            from cocotbext_i3c.i3c_target import I3CTarget
            from cocotbext_i3c.common import I3cTargetTimings
        except ModuleNotFoundError as exc:
            raise OcahI3cImportError(
                f"{name}: cocotbext_i3c is not importable.\n"
                "Add the checked-in copy to PYTHONPATH:\n"
                "  export PYTHONPATH=$PYTHONPATH:"
                "<repo>/vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/src\n"
                "or install it:\n"
                "  pip install <repo>/vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/"
            ) from exc

        timings = I3cTargetTimings()
        self._tgt = I3CTarget(
            sda_i=sda_i,
            sda_o=sda_o,
            scl_i=scl_i,
            scl_o=scl_o,
            target_address=static_addr if static_addr is not None else 0x00,
            timings=timings,
            speed=speed_hz,
        )
        self.log.debug(
            "%s: I3CTarget created static_addr=0x%02X",
            name, static_addr if static_addr is not None else 0,
        )

    # ------------------------------------------------------------------
    # Address configuration
    # ------------------------------------------------------------------

    def set_static_address(self, addr: int) -> None:
        """
        Set the 7-bit static address the target responds to.

        Parameters
        ----------
        addr:
            7-bit I3C static address (0x00–0x7F, excluding reserved values).

        Notes
        -----
        This updates the ``target_address`` attribute of the underlying
        ``I3CTarget``.  Call this before any bus activity begins.
        """
        if not (0 <= addr <= 0x7F):
            raise ValueError(
                f"{self.name}: static_addr must be 0x00–0x7F, got 0x{addr:02X}"
            )
        self._static_addr = addr
        self._tgt.target_address = addr
        self.log.debug("%s: static address set to 0x%02X", self.name, addr)

    # ------------------------------------------------------------------
    # IBI configuration
    # ------------------------------------------------------------------

    def register_ibi(self, mdb: int, *, payload: bytes = b"") -> None:
        """
        Configure and queue an IBI (In-Band Interrupt) for the target.

        The target will issue the IBI during the next available bus idle
        window.  The MDB (Mandatory Data Byte) and optional data payload
        are queued for delivery when the controller polls for IBIs.

        Parameters
        ----------
        mdb:
            Mandatory Data Byte (0x00–0xFF).  Value 0x00 means no MDB.
        payload:
            Additional bytes after the MDB.  Empty by default.

        Notes
        -----
        ``I3CTarget`` IBI initiation is implementation-dependent in
        ``cocotbext-i3c`` v1.1.0.  This method queues data into the target's
        send buffer.  The underlying target must have IBI capability bit set
        in its BCR; this wrapper sets BCR[2] (IBI payload) when payload is
        non-empty and BCR[1] (IBI-request capable) unconditionally.

        TODO: Verify the I3CTarget IBI initiation API when cocotbext-i3c
        provides a first-class ``send_ibi()`` coroutine.
        """
        if not (0 <= mdb <= 0xFF):
            raise ValueError(f"{self.name}: mdb must be 0–255, got {mdb}")

        # Set BCR IBI-request capable bit.
        ibi_payload_flag = bool(payload)
        # Update BCR fields on the underlying target object.
        # I3CTarget exposes a bcr attribute directly.
        bcr = getattr(self._tgt, "bcr", 0)
        bcr |= (1 << 1)  # IBI-request capable
        if ibi_payload_flag:
            bcr |= (1 << 2)  # IBI payload present
        else:
            bcr &= ~(1 << 2)
        self._tgt.bcr = bcr

        # Queue the MDB + payload into the target write memory so it will
        # be sent as IBI data when the controller ACKs the interrupt.
        ibi_data = bytes([mdb]) + payload
        if hasattr(self._tgt, "memory") and hasattr(self._tgt.memory, "write"):
            self._tgt.memory.write(list(ibi_data), len(ibi_data))
        else:
            self.log.warning(
                "%s: register_ibi — underlying target has no writable memory; "
                "IBI data not queued.  Check cocotbext_i3c version.", self.name
            )

        self.log.debug(
            "%s: IBI registered mdb=0x%02X payload_len=%d",
            self.name, mdb, len(payload),
        )

    # ------------------------------------------------------------------
    # Response configuration
    # ------------------------------------------------------------------

    def set_response(self, data: bytes) -> None:
        """
        Pre-load the bytes the target will return on the next private read.

        The data is written directly into the underlying ``I3CMemory``
        write buffer.  The next ``priv_read`` from the controller will
        consume exactly ``len(data)`` bytes from this buffer.

        Parameters
        ----------
        data:
            Bytes to return on the next read request.

        Notes
        -----
        The underlying ``I3CMemory`` is a circular buffer.  Back-to-back
        calls to ``set_response`` append to the buffer rather than replacing
        it.  Call ``clear_response()`` first to discard stale data.
        """
        if not data:
            raise ValueError(f"{self.name}: set_response called with empty data")

        if not (hasattr(self._tgt, "memory") and hasattr(self._tgt.memory, "write")):
            raise OcahI3cTargetError(
                f"{self.name}: underlying I3CTarget has no accessible 'memory' attribute. "
                "Check cocotbext_i3c version."
            )
        self._tgt.memory.write(list(data), len(data))
        self.log.debug(
            "%s: set_response len=%d data=%s",
            self.name, len(data), data.hex(),
        )

    def clear_response(self) -> None:
        """Discard any pre-loaded response data in the target memory buffer."""
        if hasattr(self._tgt, "memory") and hasattr(self._tgt.memory, "clear"):
            self._tgt.memory.clear()
            self.log.debug("%s: response buffer cleared", self.name)
        else:
            self.log.warning(
                "%s: clear_response — no accessible memory.clear(); "
                "check cocotbext_i3c version.", self.name
            )
