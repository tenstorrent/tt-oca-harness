# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
OcahSpiMonitor — passive SPI bus monitor.

Observes SPI transactions without driving any signals.  Decodes the command
byte, address bytes, and data bytes from the MOSI/DQ line and fires callbacks
when a complete transaction (CS_N low → high) is observed.

Supported transaction fields
-----------------------------
Each completed transaction is reported as a plain dict::

    {
        "opcode":    int,          # 8-bit command byte
        "addr":      int,          # decoded address (0 if no address)
        "has_addr":  bool,         # True if command carries an address
        "data_mosi": bytes,        # payload bytes on MOSI/DQ0 after the address (PAGE PROGRAM)
        "data_miso": bytes,        # response bytes on MISO/DQ0 after the command, address, and dummy phases
        "bit_count": int,          # total bits observed in this transaction
        "start_ns":  float or None,
        "end_ns":    float or None,
    }

``data_miso`` is empty for a command that carries no response phase, and
``data_mosi`` is empty for a command that carries no payload phase, so a byte
the line held during the command phase is never reported as data.  Known
command codes are decoded to symbolic names for logging; unknown codes are
logged as ``UNKNOWN(0xNN)`` and carry neither data field.

Usage
-----
::

    mon = OcahSpiMonitor(
        cs_n = dut.spi_cs_n,
        sclk = dut.spi_sclk,
        mosi = dut.spi_mosi,
        miso = dut.spi_miso,
        name = "spi_mon",
        addr_bytes = 3,
    )
    mon.add_transaction_callback(lambda txn: print(txn))
    await mon.start()
    # ... run traffic ...
    await mon.stop()
    txns = mon.get_transactions()
"""

import logging
from typing import Any, Callable, Dict, List, Optional

import cocotb
from cocotb.triggers import FallingEdge, First, RisingEdge

from .ocah_spi_types import OcahSpiOpcode, opcode_name

__all__ = ["OcahSpiMonitor"]


def _cancel_task(task: Any) -> None:
    """Stop a background task on cocotb 1.x (``kill``) and 2.x (``cancel``) alike."""
    cancel = getattr(task, "cancel", None)
    if cancel is not None:
        cancel()
    else:
        task.kill()


# Commands that carry an address phase
_ADDR_COMMANDS = frozenset(
    int(op)
    for op in (
        OcahSpiOpcode.READ,
        OcahSpiOpcode.FAST_READ,
        OcahSpiOpcode.PAGE_PROGRAM,
        OcahSpiOpcode.SECTOR_ERASE,
    )
)

# Commands that have a MISO data phase after the address/dummy
_MISO_COMMANDS = frozenset(
    int(op)
    for op in (
        OcahSpiOpcode.JEDEC_ID,
        OcahSpiOpcode.READ,
        OcahSpiOpcode.FAST_READ,
        OcahSpiOpcode.READ_SR1,
        OcahSpiOpcode.READ_SR2,
    )
)

# Commands that have a MOSI data phase after the address
_MOSI_COMMANDS = frozenset([int(OcahSpiOpcode.PAGE_PROGRAM)])


class OcahSpiMonitor:
    """
    Passive SPI bus monitor.

    Observes CS_N, SCLK, and MOSI/MISO without driving anything.  Fires
    registered callbacks and maintains a transaction history.

    Parameters
    ----------
    cs_n : cocotb handle
        Active-low chip-select (DUT → flash direction).
    sclk : cocotb handle
        Serial clock (DUT → flash direction).
    mosi : cocotb handle, optional
        Master-out / slave-in data line (or DQ0 of the DQ bus).
    miso : cocotb handle, optional
        Master-in / slave-out data line (or DQ0 of the response bus).
    name : str
        Instance label for log messages.
    addr_bytes : int
        Number of address bytes expected after the command opcode.  Default 3.
    fast_read_dummies : int
        Number of dummy bytes consumed by FAST_READ (0x0B) before data phase.
        Default 1 (= 8 dummy bits).
    max_history : int
        Maximum number of transactions retained in history.  Default 2000.
    verbose : bool
        Log individual bit transitions when True.  Default False.
    """

    def __init__(
        self,
        cs_n,
        sclk,
        *,
        mosi=None,
        miso=None,
        name: str = "OcahSpiMonitor",
        addr_bytes: int = 3,
        fast_read_dummies: int = 1,
        max_history: int = 2000,
        verbose: bool = False,
    ):
        self.name = name
        self.log = logging.getLogger(name)

        self._cs_n = cs_n
        self._sclk = sclk
        self._mosi = mosi
        self._miso = miso

        self._addr_bytes = addr_bytes
        self._fast_read_dummies = fast_read_dummies
        self._max_history = max_history
        self._verbose = verbose

        self._callbacks: List[Callable] = []
        self._history: List[Dict[str, Any]] = []

        self._task: Optional[Any] = None
        self._running = False

        self._stats = {
            "transactions_seen": 0,
            "bytes_mosi": 0,
            "bytes_miso": 0,
            "callback_errors": 0,
        }

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def add_transaction_callback(self, fn: Callable) -> None:
        """Register a callback fired on each completed transaction.

        Signature: ``fn(txn: dict) -> None``

        The ``txn`` dict is a plain-int/bytes record; see module docstring
        for the field list.  Exceptions in the callback are caught and logged.
        """
        self._callbacks.append(fn)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start passive monitoring.  Safe to call multiple times."""
        if self._running:
            return
        self._running = True
        self._task = cocotb.start_soon(self._monitor_loop())
        self.log.info("%s: started", self.name)

    async def stop(self) -> None:
        """Stop monitoring and drain any in-flight transaction."""
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            _cancel_task(self._task)
            self._task = None
        self.log.info("%s: stopped (transactions=%d)", self.name, self._stats["transactions_seen"])

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_transactions(self) -> List[Dict[str, Any]]:
        """Return a copy of the completed transaction history."""
        return list(self._history)

    def clear_history(self) -> None:
        """Discard all retained transaction records."""
        self._history.clear()

    def get_statistics(self) -> Dict[str, Any]:
        """Return cumulative monitor statistics."""
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Monitor loop
    # ------------------------------------------------------------------

    async def _monitor_loop(self) -> None:
        """Main async loop — wait for CS assertion, observe one transaction."""
        while self._running:
            await FallingEdge(self._cs_n)
            if not self._running:
                break
            try:
                await self._observe_transaction()
            except Exception as exc:  # noqa: BLE001
                self.log.error("%s: exception while observing: %s", self.name, exc)

    async def _observe_transaction(self) -> None:
        """Observe one SPI transaction from CS_N low to CS_N high."""
        start_ns = _sim_time_ns()

        mosi_bits: List[int] = []
        miso_bits: List[int] = []

        # Sample bits on rising SCLK edges until CS_N goes high.
        while True:
            await First(RisingEdge(self._sclk), RisingEdge(self._cs_n))
            if int(self._cs_n.value) != 0:
                break  # CS deasserted

            if self._mosi is not None:
                mosi_bits.append(int(self._mosi.value) & 0x1)
            if self._miso is not None:
                miso_bits.append(int(self._miso.value) & 0x1)

        end_ns = _sim_time_ns()

        txn = self._decode(mosi_bits, miso_bits, start_ns, end_ns)
        self._history.append(txn)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        self._stats["transactions_seen"] += 1
        self._stats["bytes_mosi"] += len(txn["data_mosi"])
        self._stats["bytes_miso"] += len(txn["data_miso"])

        self._stats["callback_errors"] += _fire_callbacks(self.log, self._callbacks, txn)

        self.log.info(
            "%s: %s addr=0x%06X mosi=%dB miso=%dB",
            self.name,
            opcode_name(txn["opcode"]),
            txn["addr"],
            len(txn["data_mosi"]),
            len(txn["data_miso"]),
        )

    # ------------------------------------------------------------------
    # Decode bit stream
    # ------------------------------------------------------------------

    def _decode(
        self,
        mosi_bits: List[int],
        miso_bits: List[int],
        start_ns,
        end_ns,
    ) -> Dict[str, Any]:
        """Convert raw bit lists into a structured transaction record."""
        mosi_bytes = _bits_to_bytes(mosi_bits)
        miso_bytes = _bits_to_bytes(miso_bits)

        opcode = mosi_bytes[0] if mosi_bytes else 0
        has_addr = opcode in _ADDR_COMMANDS
        addr = 0

        if has_addr and len(mosi_bytes) > 1:
            for i in range(1, min(1 + self._addr_bytes, len(mosi_bytes))):
                addr = (addr << 8) | mosi_bytes[i]

        # The response phase starts after the opcode, the address bytes of an
        # addressed command, and the dummy bytes of a FAST READ.
        data_start = 1 + (self._addr_bytes if has_addr else 0)
        if opcode == OcahSpiOpcode.FAST_READ:
            data_start += self._fast_read_dummies

        return {
            "opcode": opcode,
            "addr": addr,
            "has_addr": has_addr,
            "data_mosi": mosi_bytes[data_start:] if opcode in _MOSI_COMMANDS else b"",
            "data_miso": miso_bytes[data_start:] if opcode in _MISO_COMMANDS else b"",
            "bit_count": len(mosi_bits),
            "start_ns": start_ns,
            "end_ns": end_ns,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sim_time_ns() -> Optional[float]:
    """Simulation time in ns, ``None`` when the simulator exposes none."""
    try:
        return cocotb.utils.get_sim_time("ns")
    except Exception:  # noqa: BLE001
        return None


def _bits_to_bytes(bits: List[int]) -> bytes:
    """Pack a list of 1/0 bits (MSB-first) into bytes, right-padding partial byte."""
    out: List[int] = []
    i = 0
    while i < len(bits):
        byte_val = 0
        for j in range(8):
            if i + j < len(bits):
                byte_val = (byte_val << 1) | (bits[i + j] & 0x1)
            else:
                byte_val <<= 1  # zero-pad last partial byte
        out.append(byte_val)
        i += 8
    return bytes(out)


def _fire_callbacks(log: logging.Logger, callbacks: list, *args) -> int:
    """Call each callback; a checker verdict propagates, any other exception is logged and counted."""
    errors = 0
    for fn in callbacks:
        try:
            fn(*args)
        except AssertionError:
            raise
        except Exception as exc:  # noqa: BLE001
            errors += 1
            log.error("Exception in SpiMonitor callback %s: %s", fn, exc)
    return errors
