# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
OcahSpiFlash — OCAH-stable NOR-flash device BFM for SPI / QSPI / OSPI.

This module provides a self-contained, cocotb-native flash device behavioural
model.  It does NOT depend on any external cocotb extension package.

Supported commands
------------------
  0x9F — READ JEDEC ID            (single, dual, quad, octal)
  0x03 — READ (slow, 1-1-1)
  0x0B — FAST READ                (1-1-1 with 8-bit dummy)
  0x05 — READ STATUS REGISTER 1
  0x35 — READ STATUS REGISTER 2
  0x06 — WRITE ENABLE
  0x04 — WRITE DISABLE
  0x02 — PAGE PROGRAM
  0x20 — SECTOR ERASE (4 KB)

Out of scope
------------
  Suspend/resume, OTP, security registers, lock registers, larger-erase
  variants, ECC, differential OSPI, DDR mode toggle signalling, and any
  silicon-specific behaviour.  An out-of-scope opcode is drained to the end
  of the frame and recorded with ``ok=False``.

Mode mapping
------------
  "single" — CS_N, SCK, MOSI (DQ0 out), MISO (DQ1 in)
  "quad"   — CS_N, SCK, DQ[3:0] bidirectional
  "octal"  — CS_N, SCK, DQ[7:0] bidirectional  (single-bit data timing; see below)

The model is deterministic by default.  All memory is initialised to 0xFF
(erased state).  The device is instant-ready: the BUSY bit of status register
1 never sets, and a program or erase completes when chip-select rises.

Transaction records
-------------------
``get_transactions()`` returns one dict per chip-select frame::

    {
        "opcode":   int,    # command byte
        "addr":     int,    # decoded address (0 when the command has none)
        "data_out": bytes,  # bytes the device sent, complete bytes only
        "data_in":  bytes,  # payload bytes the device accepted
        "ok":       bool,   # True when the command was in scope and accepted
        "reason":   str,    # "" | "wel_clear" | "unknown_opcode"
    }

A PAGE PROGRAM or SECTOR ERASE issued with the write-enable latch clear is
refused: the address is decoded and recorded, no payload is taken, memory is
unchanged, and the record carries ``ok=False, reason="wel_clear"``.
"""

import logging
import os
from typing import Any, Callable, Dict, List, Optional

import cocotb
from cocotb.triggers import FallingEdge, First, RisingEdge

from .ocah_spi_types import PAGE_SIZE, SECTOR_SIZE, SR1_WEL, OcahSpiOpcode, SpiMode

__all__ = ["OcahSpiFlash", "OcahSpiFlashError", "SpiMode"]

_ADDR_MASK_24 = 0xFFFFFF


def _cancel_task(task: Any) -> None:
    """Stop a background task on cocotb 1.x (``kill``) and 2.x (``cancel``) alike."""
    cancel = getattr(task, "cancel", None)
    if cancel is not None:
        cancel()
    else:
        task.kill()


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class OcahSpiFlashError(RuntimeError):
    """Raised when the flash BFM encounters an unrecoverable protocol error."""


# ---------------------------------------------------------------------------
# Main flash device BFM
# ---------------------------------------------------------------------------


class OcahSpiFlash:
    """
    OCAH-stable NOR-flash device BFM.

    Acts as the *slave* on the SPI bus.  The DUT (controller) drives CS_N and
    SCLK; this BFM samples incoming data on MOSI/DQ and drives response data
    back on MISO/DQ.

    The protocol engine is built on cocotb triggers alone.

    Parameters
    ----------
    cs_n : cocotb handle
        Active-low chip-select input from the controller.
    sclk : cocotb handle
        Serial clock input from the controller.
    mosi : cocotb handle, optional
        Master-out slave-in (DQ0 output from controller).  Required for
        ``mode="single"``.  For quad/octal, use ``dq_out``/``dq_in`` instead.
    miso : cocotb handle, optional
        Master-in slave-out (DQ1 output from flash to controller).  Required
        for ``mode="single"``.
    dq_out : cocotb handle, optional
        Multi-bit output from controller to flash (DQ bus, driven by DUT).
        Used for quad/octal modes.
    dq_in : cocotb handle, optional
        Multi-bit input to controller from flash (DQ bus, driven by this BFM).
        Used for quad/octal modes.
    name : str
        Instance label for log messages.
    mode : str or SpiMode
        ``"single"`` (default), ``"quad"``, or ``"octal"``.
    jedec_id : int
        3-byte JEDEC ID returned for command 0x9F.  Default 0x20BA18.
    flash_size : int
        Flash capacity in bytes.  Default 16 MB (128 Mbit).  A read that runs
        past the end returns 0xFF and a program past the end is dropped; the
        address does not wrap to zero.
    addr_bytes : int
        Number of address bytes in read/write commands.  Default 3 (24-bit).
    status_reg1 : int
        Initial value of Status Register 1.  Bit 0 = BUSY, bit 1 = WEL.
    status_reg2 : int
        Initial value of Status Register 2.  Default 0x00.
    verbose : bool
        Log every sampled bit when True.  Default False.
    """

    def __init__(
        self,
        cs_n,
        sclk,
        *,
        mosi=None,
        miso=None,
        dq_out=None,
        dq_in=None,
        name: str = "OcahSpiFlash",
        mode: str = "single",
        jedec_id: int = 0x20BA18,
        flash_size: int = 16 * 1024 * 1024,
        addr_bytes: int = 3,
        status_reg1: int = 0x00,
        status_reg2: int = 0x00,
        verbose: bool = False,
    ):
        self.name = name
        self.log = logging.getLogger(name)

        self._cs_n = cs_n
        self._sclk = sclk
        self._mosi = mosi
        self._miso = miso
        self._dq_out = dq_out
        self._dq_in = dq_in

        self._mode = SpiMode(mode)
        if self._mode == SpiMode.SINGLE and (mosi is None or miso is None):
            raise OcahSpiFlashError(f"{name}: mode='single' requires mosi and miso handles")
        if self._mode in (SpiMode.QUAD, SpiMode.OCTAL) and (dq_out is None or dq_in is None):
            raise OcahSpiFlashError(f"{name}: mode='{mode}' requires dq_out and dq_in handles")

        self._jedec_id = jedec_id & _ADDR_MASK_24
        self._flash_size = flash_size
        self._addr_bytes = addr_bytes
        self._verbose = verbose

        # Flash memory storage — initialised to erased state (0xFF).
        self._mem: bytearray = bytearray(b"\xff" * flash_size)

        # Status registers
        self._sr1 = status_reg1 & 0xFF
        self._sr2 = status_reg2 & 0xFF
        self._wel = False  # Write Enable Latch

        # Command callbacks (extensible by subclasses or tests)
        self._cmd_callbacks: Dict[int, Callable] = {}

        # Runtime state
        self._task: Optional[Any] = None
        self._running = False
        self._transactions: List[Dict[str, Any]] = []

        # Apply plusargs
        self._apply_plusargs()

    # ------------------------------------------------------------------
    # Read-only configuration view (what a checker predicts against)
    # ------------------------------------------------------------------

    @property
    def jedec_id(self) -> int:
        """3-byte JEDEC ID the device answers to READ JEDEC ID."""
        return self._jedec_id

    @property
    def flash_size(self) -> int:
        """Capacity in bytes."""
        return self._flash_size

    @property
    def addr_bytes(self) -> int:
        """Address bytes per addressed command."""
        return self._addr_bytes

    @property
    def status_reg1(self) -> int:
        """Status register 1 as READ STATUS REGISTER 1 reports it, write-enable latch included."""
        return self._sr1 | (SR1_WEL if self._wel else 0x00)

    @property
    def status_reg2(self) -> int:
        """Status register 2 as READ STATUS REGISTER 2 returns it."""
        return self._sr2

    @property
    def write_enabled(self) -> bool:
        """State of the write-enable latch."""
        return self._wel

    # ------------------------------------------------------------------
    # Plusarg processing
    # ------------------------------------------------------------------

    def _apply_plusargs(self) -> None:
        """Apply simulation plusargs if present."""
        jedec_env = os.environ.get("COCOTB_PLUSARG_spi_flash_jedec_id")
        if jedec_env:
            try:
                self._jedec_id = int(jedec_env, 16) & _ADDR_MASK_24
                self.log.info(
                    "%s: JEDEC ID overridden by plusarg: 0x%06X", self.name, self._jedec_id
                )
            except ValueError:
                self.log.warning(
                    "%s: invalid +spi_flash_jedec_id=%s (ignored)", self.name, jedec_env
                )

        preload_env = os.environ.get("COCOTB_PLUSARG_spi_flash_preload")
        if preload_env:
            try:
                self.preload(preload_env)
            except Exception as exc:  # noqa: BLE001
                self.log.warning(
                    "%s: +spi_flash_preload=%s failed: %s", self.name, preload_env, exc
                )

    # ------------------------------------------------------------------
    # Public configuration API
    # ------------------------------------------------------------------

    def set_jedec_id(self, jedec_id: int) -> None:
        """Set the 3-byte JEDEC ID returned by command 0x9F.

        Parameters
        ----------
        jedec_id : int
            24-bit JEDEC ID (manufacturer byte in bits [23:16]).
        """
        self._jedec_id = jedec_id & _ADDR_MASK_24
        self.log.info("%s: JEDEC ID set to 0x%06X", self.name, self._jedec_id)

    def preload(self, source: "str | bytes | bytearray") -> None:
        """Load flash memory contents from a file path or bytes-like object.

        Parameters
        ----------
        source : str or bytes-like
            If a string, treated as a file path.  The file is read as raw
            binary and written starting at address 0.  If bytes-like, copied
            directly.

        Raises
        ------
        OcahSpiFlashError
            If the source is too large for the configured flash size.
        """
        if isinstance(source, str):
            with open(source, "rb") as fh:
                data = fh.read()
            self.log.info("%s: preloaded %d bytes from %s", self.name, len(data), source)
        else:
            data = bytes(source)
            self.log.info("%s: preloaded %d bytes from object", self.name, len(data))

        if len(data) > self._flash_size:
            raise OcahSpiFlashError(
                f"{self.name}: preload data ({len(data)} B) exceeds "
                f"flash size ({self._flash_size} B)"
            )
        self._mem[: len(data)] = data

    def register_command_callback(self, opcode: int, fn: Callable) -> None:
        """Register a callback for a custom or overridden command.

        Parameters
        ----------
        opcode : int
            8-bit command opcode.
        fn : callable
            Async coroutine: ``async def handler(opcode, addr, data_in)``
            that returns ``bytes`` to transmit back, or ``None``.
        """
        self._cmd_callbacks[opcode & 0xFF] = fn

    def unregister_command_callback(self, opcode: int) -> None:
        """Remove a command callback; the built-in handling resumes for the opcode."""
        self._cmd_callbacks.pop(opcode & 0xFF, None)

    # ------------------------------------------------------------------
    # Signal initialisation
    # ------------------------------------------------------------------

    def init_signals(self) -> None:
        """Drive all BFM output signals to their idle/reset state.

        Call this before the first clock edge to prevent X propagation on
        MISO / DQ outputs.
        """
        if self._mode == SpiMode.SINGLE:
            if self._miso is not None:
                self._miso.value = 0
        else:
            if self._dq_in is not None:
                self._dq_in.value = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the flash device BFM.

        Spawns the internal protocol engine as a cocotb background task.
        The engine runs until ``stop()`` is called.
        """
        if self._running:
            self.log.warning("%s: start() called while already running", self.name)
            return
        self._running = True
        self._task = cocotb.start_soon(self._protocol_engine())
        self.log.info(
            "%s: started (mode=%s, JEDEC=0x%06X, size=%dMB)",
            self.name,
            self._mode.value,
            self._jedec_id,
            self._flash_size // (1024 * 1024),
        )

    async def stop(self) -> None:
        """Stop the flash device BFM.  The transaction history survives."""
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            _cancel_task(self._task)
            self._task = None
        self.log.info("%s: stopped (%d transactions served)", self.name, len(self._transactions))

    # ------------------------------------------------------------------
    # Transaction history
    # ------------------------------------------------------------------

    def get_transactions(self) -> List[Dict[str, Any]]:
        """Return a copy of all completed transaction records (module docstring lists the keys)."""
        return list(self._transactions)

    def clear_transactions(self) -> None:
        """Discard the transaction history."""
        self._transactions.clear()

    # ------------------------------------------------------------------
    # Memory helpers (accessible to subclasses / tests)
    # ------------------------------------------------------------------

    def read_memory(self, addr: int, length: int) -> bytes:
        """Read bytes directly from flash memory (does not use SPI bus)."""
        end = addr + length
        if end > self._flash_size:
            raise OcahSpiFlashError(
                f"{self.name}: read_memory addr=0x{addr:X} len={length} exceeds flash size"
            )
        return bytes(self._mem[addr:end])

    def write_memory(self, addr: int, data: bytes) -> None:
        """Write bytes directly to flash memory (bypasses program semantics)."""
        end = addr + len(data)
        if end > self._flash_size:
            raise OcahSpiFlashError(
                f"{self.name}: write_memory addr=0x{addr:X} len={len(data)} exceeds flash size"
            )
        self._mem[addr:end] = data

    # ------------------------------------------------------------------
    # Protocol engine
    # ------------------------------------------------------------------

    async def _protocol_engine(self) -> None:
        """Main async loop — wait for CS assertion, then handle one transfer."""
        while self._running:
            # Wait for CS_N to go low (transaction start).
            await FallingEdge(self._cs_n)
            if not self._running:
                break
            try:
                await self._handle_transaction()
            except Exception as exc:  # noqa: BLE001
                self.log.error("%s: exception in transaction handler: %s", self.name, exc)

    async def _handle_transaction(self) -> None:
        """Handle a single SPI transaction (CS low to CS high)."""
        opcode = await self._recv_byte_single()
        addr = 0
        rx_data: bytearray = bytearray()
        tx_data: bytes = b""
        ok = True
        reason = ""

        if self._verbose:
            self.log.debug("%s: opcode=0x%02X", self.name, opcode)

        # Check for registered callback override first.
        if opcode in self._cmd_callbacks:
            addr = await self._recv_addr() if self._addr_bytes > 0 else 0
            payload = await self._recv_remaining()
            result = await self._cmd_callbacks[opcode](opcode, addr, payload)
            if result:
                await self._send_bytes(result)
            self._log_transaction(opcode, addr, result or b"", payload)
            return

        # --- JEDEC ID ---
        if opcode == OcahSpiOpcode.JEDEC_ID:
            jedec_bytes = bytes(
                [
                    (self._jedec_id >> 16) & 0xFF,
                    (self._jedec_id >> 8) & 0xFF,
                    (self._jedec_id) & 0xFF,
                ]
            )
            await self._send_bytes_active(jedec_bytes)
            tx_data = jedec_bytes

        # --- READ STATUS REGISTER 1 ---
        elif opcode == OcahSpiOpcode.READ_SR1:
            sr1_val = self.status_reg1
            await self._send_bytes_active(bytes([sr1_val]))
            tx_data = bytes([sr1_val])

        # --- READ STATUS REGISTER 2 ---
        elif opcode == OcahSpiOpcode.READ_SR2:
            await self._send_bytes_active(bytes([self._sr2]))
            tx_data = bytes([self._sr2])

        # --- WRITE ENABLE ---
        elif opcode == OcahSpiOpcode.WRITE_ENABLE:
            self._wel = True
            self.log.debug("%s: WRITE ENABLE set", self.name)

        # --- WRITE DISABLE ---
        elif opcode == OcahSpiOpcode.WRITE_DISABLE:
            self._wel = False
            self.log.debug("%s: WRITE DISABLE set", self.name)

        # --- READ (slow, 1-1-1) ---
        elif opcode == OcahSpiOpcode.READ:
            addr = await self._recv_addr()
            tx_data = await self._do_read(addr)

        # --- FAST READ (1-1-1 + 8-bit dummy) ---
        elif opcode == OcahSpiOpcode.FAST_READ:
            addr = await self._recv_addr()
            await self._recv_byte_single()  # consume 8 dummy bits
            tx_data = await self._do_read(addr)

        # --- PAGE PROGRAM ---
        elif opcode == OcahSpiOpcode.PAGE_PROGRAM:
            if not self._wel:
                self.log.warning("%s: PAGE PROGRAM while WEL=0 — ignored", self.name)
                addr = await self._recv_addr_lenient()
                await self._drain_to_cs_high()
                ok, reason = False, "wel_clear"
            else:
                addr = await self._recv_addr()
                rx_data = await self._recv_remaining()
                self._do_page_program(addr, rx_data)
                self._wel = False

        # --- SECTOR ERASE (4 KB) ---
        elif opcode == OcahSpiOpcode.SECTOR_ERASE:
            if not self._wel:
                self.log.warning("%s: SECTOR ERASE while WEL=0 — ignored", self.name)
                addr = await self._recv_addr_lenient()
                await self._drain_to_cs_high()
                ok, reason = False, "wel_clear"
            else:
                addr = await self._recv_addr()
                self._do_sector_erase(addr)
                self._wel = False

        else:
            self.log.warning(
                "%s: unknown opcode 0x%02X — draining to CS deassert", self.name, opcode
            )
            await self._drain_to_cs_high()
            ok, reason = False, "unknown_opcode"

        self._log_transaction(opcode, addr, tx_data, bytes(rx_data), ok=ok, reason=reason)

    # ------------------------------------------------------------------
    # Flash operation helpers
    # ------------------------------------------------------------------

    async def _do_read(self, addr: int) -> bytes:
        """Stream memory to MISO until CS deasserts; return the complete bytes sent.

        The byte in flight when chip-select rises is not part of the record:
        the controller clocked none or only some of its bits.
        """
        out: bytearray = bytearray()
        while int(self._cs_n.value) == 0:
            if addr >= self._flash_size:
                byte_val = 0xFF
            else:
                byte_val = self._mem[addr]
            if not await self._send_byte_single(byte_val):
                break
            out.append(byte_val)
            addr = (addr + 1) & _ADDR_MASK_24
        return bytes(out)

    def _do_page_program(self, addr: int, data: bytearray) -> None:
        """Program bytes into flash, respecting page-program OR semantics."""
        page_base = addr & ~(PAGE_SIZE - 1)
        page_off = addr & (PAGE_SIZE - 1)
        for i, byte_val in enumerate(data):
            page_addr = page_base + ((page_off + i) % PAGE_SIZE)
            if page_addr < self._flash_size:
                # NOR program: can only clear bits (AND semantics)
                self._mem[page_addr] &= byte_val
        self.log.debug("%s: PAGE PROGRAM addr=0x%06X len=%d", self.name, addr, len(data))

    def _do_sector_erase(self, addr: int) -> None:
        """Erase a 4 KB sector (set all bytes to 0xFF)."""
        sector_base = addr & ~(SECTOR_SIZE - 1)
        end = min(sector_base + SECTOR_SIZE, self._flash_size)
        for i in range(sector_base, end):
            self._mem[i] = 0xFF
        self.log.debug("%s: SECTOR ERASE base=0x%06X", self.name, sector_base)

    # ------------------------------------------------------------------
    # Serial I/O helpers — single-bit (Mode 0: CPOL=0 CPHA=0)
    # ------------------------------------------------------------------

    async def _recv_byte_single(self) -> int:
        """Receive one byte MSB-first on MOSI, sampling on rising SCK edge.

        Races each clock edge against CS deassertion: after the controller
        sends the final byte of a TX phase, the clock simply stops and CS
        rises, so waiting on ``RisingEdge(sclk)`` alone would block forever
        (the byte boundary is signalled only by CS). When CS deasserts first,
        raise the standard error so callers (e.g. ``_recv_remaining``) end the
        transfer cleanly.
        """
        byte_val = 0
        for _ in range(8):
            await First(RisingEdge(self._sclk), RisingEdge(self._cs_n))
            if int(self._cs_n.value) != 0:
                raise OcahSpiFlashError(f"{self.name}: CS deasserted during byte receive")
            mosi_sig = self._mosi if self._mode == SpiMode.SINGLE else self._dq_out
            bit = int(mosi_sig.value) & 0x1
            byte_val = (byte_val << 1) | bit
        return byte_val

    async def _send_byte_single(self, byte_val: int) -> bool:
        """Send one byte MSB-first on MISO, changing on falling SCK edge.

        Races each clock edge against CS deassertion: after the controller
        clocks in the final RX byte it stops the clock and raises CS, so
        waiting on ``FallingEdge(sclk)`` alone would block forever. Returns
        True when all eight bits were driven, False when CS deasserted first.
        """
        for bit_idx in range(7, -1, -1):
            await First(FallingEdge(self._sclk), RisingEdge(self._cs_n))
            if int(self._cs_n.value) != 0:
                return False
            bit = (byte_val >> bit_idx) & 0x1
            miso_sig = self._miso if self._mode == SpiMode.SINGLE else self._dq_in
            miso_sig.value = bit
        return True

    async def _send_bytes(self, data: bytes) -> None:
        """Send all bytes and wait for CS to deassert."""
        for byte_val in data:
            if int(self._cs_n.value) != 0:
                return
            await self._send_byte_single(byte_val)

    async def _send_bytes_active(self, data: bytes) -> None:
        """Send all bytes, then drain remaining clocks until CS deasserts."""
        await self._send_bytes(data)
        await self._drain_to_cs_high()

    async def _recv_addr(self) -> int:
        """Receive addr_bytes bytes and assemble into an integer address."""
        addr = 0
        for _ in range(self._addr_bytes):
            byte_val = await self._recv_byte_single()
            addr = (addr << 8) | byte_val
        return addr

    async def _recv_addr_lenient(self) -> int:
        """Address of a refused command; 0 when the controller ended the frame early."""
        try:
            return await self._recv_addr()
        except OcahSpiFlashError:
            return 0

    async def _recv_remaining(self) -> bytearray:
        """Receive all remaining bytes until CS deasserts."""
        buf: bytearray = bytearray()
        while int(self._cs_n.value) == 0:
            try:
                byte_val = await self._recv_byte_single()
                buf.append(byte_val)
            except OcahSpiFlashError:
                break
        return buf

    async def _drain_to_cs_high(self) -> None:
        """Consume clock edges until CS_N returns high."""
        while int(self._cs_n.value) == 0:
            await RisingEdge(self._cs_n)

    # ------------------------------------------------------------------
    # Quad / Octal modes
    # ------------------------------------------------------------------
    # mode="quad" and mode="octal" bind the DQ bus but run the single-bit
    # engine: the command byte, the address bytes, and the data phase all use
    # DQ0 (bit 0 of dq_out / dq_in), one bit per SCK. Multi-bit data lanes
    # and the bidirectional bus turnaround are not modeled.

    # ------------------------------------------------------------------
    # Internal bookkeeping
    # ------------------------------------------------------------------

    def _log_transaction(
        self,
        opcode: int,
        addr: int,
        data_out: bytes,
        data_in: bytes,
        *,
        ok: bool = True,
        reason: str = "",
    ) -> None:
        """Append a transaction record to the history list."""
        rec = {
            "opcode": opcode,
            "addr": addr,
            "data_out": bytes(data_out),  # bytes sent from flash to controller
            "data_in": bytes(data_in),  # payload bytes accepted from the controller
            "ok": ok,
            "reason": reason,
        }
        self._transactions.append(rec)
        if self._verbose:
            self.log.debug(
                "%s: txn opcode=0x%02X addr=0x%06X out=%d B in=%d B ok=%s%s",
                self.name,
                opcode,
                addr,
                len(data_out),
                len(data_in),
                ok,
                f" reason={reason}" if reason else "",
            )
