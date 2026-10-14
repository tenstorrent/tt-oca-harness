# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
OcahSpiFlash — OCAH-stable NOR-flash device BFM for SPI / QSPI / OSPI.

A self-contained flash device behavioural model built on cocotb triggers alone.

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
``get_transactions()`` returns one dict per chip-select frame, malformed
frames included::

    {
        "opcode":     int,    # command byte; -1 when no complete byte arrived
        "addr":       int,    # decoded address (0 when the command has none
                              # or the address is incomplete)
        "data_out":   bytes,  # bytes the device sent, complete bytes only
        "data_in":    bytes,  # complete payload bytes the device received
        "ok":         bool,   # True when the command was in scope and accepted
        "reason":     str,    # see below; "" when accepted
        "input_bits": int,    # controller-output bits sampled as input
        "tail_bits":  int,    # input bits after the last complete input byte
    }

``input_bits`` counts every clock the device sampled as controller input: the
whole frame for a command without a response phase, and the command, address
and dummy phases for one with a response phase.

Frame acceptance
----------------
The device takes the whole controller-output frame before it changes the
write-enable latch or memory. A refused frame changes neither.

=========================  ===================================================
``reason``                 the frame
=========================  ===================================================
``"partial_opcode"``       ended 1 to 7 bits into the command byte
``"partial_address"``      ended before the last address bit
``"partial_dummy"``        FAST READ ended before the last dummy bit
``"wel_clear"``            PAGE PROGRAM or SECTOR ERASE with the latch clear
``"partial_byte"``         PAGE PROGRAM or a callback frame ended 1 to 7 bits
                           into a payload byte
``"no_payload"``           PAGE PROGRAM carried no payload byte
``"unexpected_payload"``   WRITE ENABLE, WRITE DISABLE or SECTOR ERASE carried
                           a bit after its last command or address bit
``"unknown_opcode"``       command outside the supported set
=========================  ===================================================

WRITE ENABLE and WRITE DISABLE are exactly one command byte. SECTOR ERASE is
one command byte and exactly ``addr_bytes`` address bytes. PAGE PROGRAM is one
command byte, ``addr_bytes`` address bytes and at least one complete payload
byte. A PAGE PROGRAM or SECTOR ERASE with the latch clear is refused as
``wel_clear`` whatever its length: the address is decoded when complete, no
payload is taken, and the frame is not graded for its shape.

A registered callback runs only on a frame with a complete command byte,
``addr_bytes`` complete address bytes and a payload that ends on a byte
boundary. PAGE PROGRAM handled by a callback also keeps the write-enable gate
and needs at least one payload byte.

A read (READ, FAST READ, JEDEC ID, status) is graded for its command, address
and dummy phases only. Once the device drives its response, chip-select may
rise at any bit: ``data_out`` holds the complete bytes sent and the frame is
accepted.

``ok`` alone tells whether the device accepted a frame. ``data_in`` is what it
received, also on a refused frame.

An exception inside the protocol engine is logged and kept; ``stop()`` raises
it, so a test that stops the device fails.
"""

import logging
import os
from typing import Any, Callable, Dict, List, Optional

import cocotb
from cocotb.triggers import FallingEdge, First, RisingEdge

from .ocah_spi_types import (
    LANE_OPCODES,
    PAGE_SIZE,
    SECTOR_SIZE,
    SR1_WEL,
    OcahSpiOpcode,
    SpiMode,
    command_format,
)

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


class _CsDeasserted(OcahSpiFlashError):
    """Chip-select rose during a byte receive; ``bits`` of that byte were sampled."""

    def __init__(self, message: str, bits: int) -> None:
        super().__init__(message)
        self.bits = bits


class _Refused(Exception):
    """A frame the device refuses; the handler records ``reason`` and returns."""

    def __init__(self, reason: str, *, addr: int = 0, data_in: bytes = b"") -> None:
        super().__init__(reason)
        self.reason = reason
        self.addr = addr
        self.data_in = data_in


def _opcode_label(opcode: int) -> str:
    """``0xNN`` for a command byte, ``partial`` for the no-byte sentinel."""
    return "partial" if opcode < 0 else f"0x{opcode:02X}"


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
        if self._mode in (SpiMode.QUAD, SpiMode.OCTAL, SpiMode.QUAD_IO) and (
            dq_out is None or dq_in is None
        ):
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
        self._engine_error: Optional[BaseException] = None
        self._input_bits = 0
        self._input_clocks = 0

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
            that returns ``bytes`` to transmit back, or ``None``. The handler
            runs only after a frame with a complete command byte, complete
            address and byte-complete payload; PAGE PROGRAM also needs the
            write-enable latch and at least one payload byte.
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
        """Stop the flash device BFM.  The transaction history survives.

        Raises ``OcahSpiFlashError`` when the protocol engine raised while it
        ran; the first such exception is the cause.
        """
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            _cancel_task(self._task)
            self._task = None
        self.log.info("%s: stopped (%d transactions served)", self.name, len(self._transactions))
        error, self._engine_error = self._engine_error, None
        if error is not None:
            raise OcahSpiFlashError(
                f"{self.name}: the protocol engine raised while running: {error!r}"
            ) from error

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
            await FallingEdge(self._cs_n)
            if not self._running:
                break
            try:
                await self._handle_transaction()
            except Exception as exc:  # noqa: BLE001
                self.log.error("%s: exception in transaction handler: %s", self.name, exc)
                if self._engine_error is None:
                    self._engine_error = exc

    async def _handle_transaction(self) -> None:
        """Handle a single SPI transaction (CS low to CS high)."""
        self._input_bits = 0
        self._input_clocks = 0
        try:
            opcode = await self._recv_byte_single()
        except _CsDeasserted as exc:
            self.log.warning(
                "%s: frame ended %d bit(s) into the command byte — refused", self.name, exc.bits
            )
            self._log_transaction(-1, 0, b"", b"", ok=False, reason="partial_opcode")
            return
        try:
            await self._dispatch(opcode)
        except _Refused as refused:
            self.log.warning(
                "%s: opcode %s refused: %s (input_bits=%d)",
                self.name,
                _opcode_label(opcode),
                refused.reason,
                self._input_bits,
            )
            self._log_transaction(
                opcode, refused.addr, b"", refused.data_in, ok=False, reason=refused.reason
            )

    async def _dispatch(self, opcode: int) -> None:
        """Run one command after its command byte; raise ``_Refused`` to refuse the frame."""
        addr = 0
        rx_data: bytes = b""
        tx_data: bytes = b""
        ok = True
        reason = ""

        if self._verbose:
            self.log.debug("%s: opcode=0x%02X", self.name, opcode)

        # PAGE PROGRAM always observes the write-enable gate, including callback overrides.
        if opcode == OcahSpiOpcode.PAGE_PROGRAM and not self._wel:
            addr, _, _ = await self._recv_write_frame(graded=False)
            raise _Refused("wel_clear", addr=addr)

        # Check for registered callback override.
        if opcode in self._cmd_callbacks:
            addr, payload, tail_bits = await self._recv_write_frame()
            if tail_bits:
                raise _Refused("partial_byte", addr=addr, data_in=payload)
            if opcode == OcahSpiOpcode.PAGE_PROGRAM and not payload:
                raise _Refused("no_payload", addr=addr)
            result = await self._cmd_callbacks[opcode](opcode, addr, payload)
            if opcode == OcahSpiOpcode.PAGE_PROGRAM:
                self._wel = False
            sent = await self._send_bytes(result) if result else b""
            self._log_transaction(opcode, addr, sent, payload)
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
            tx_data = await self._send_bytes_active(jedec_bytes)

        # --- READ STATUS REGISTER 1 ---
        elif opcode == OcahSpiOpcode.READ_SR1:
            tx_data = await self._send_bytes_active(bytes([self.status_reg1]))

        # --- READ STATUS REGISTER 2 ---
        elif opcode == OcahSpiOpcode.READ_SR2:
            tx_data = await self._send_bytes_active(bytes([self._sr2]))

        # --- WRITE ENABLE / WRITE DISABLE: exactly one command byte ---
        elif opcode in (OcahSpiOpcode.WRITE_ENABLE, OcahSpiOpcode.WRITE_DISABLE):
            extra, tail_bits = await self._recv_remaining()
            if extra or tail_bits:
                raise _Refused("unexpected_payload")
            self._wel = opcode == OcahSpiOpcode.WRITE_ENABLE
            self.log.debug("%s: write-enable latch %s", self.name, "set" if self._wel else "clear")

        # --- READ (slow, 1-1-1) ---
        elif opcode == OcahSpiOpcode.READ:
            addr = await self._recv_read_addr()
            tx_data = await self._do_read(addr)

        # --- FAST READ (1-1-1 + 8-bit dummy) ---
        elif opcode == OcahSpiOpcode.FAST_READ:
            addr = await self._recv_read_addr()
            try:
                await self._recv_byte_single()  # consume 8 dummy bits
            except _CsDeasserted:
                raise _Refused("partial_dummy", addr=addr) from None
            tx_data = await self._do_read(addr)

        # --- PAGE PROGRAM: command, address, at least one payload byte ---
        elif opcode == OcahSpiOpcode.PAGE_PROGRAM:
            addr, rx_data, tail_bits = await self._recv_write_frame()
            if tail_bits:
                raise _Refused("partial_byte", addr=addr, data_in=rx_data)
            if not rx_data:
                raise _Refused("no_payload", addr=addr)
            self._do_page_program(addr, rx_data)
            self._wel = False

        # --- SECTOR ERASE (4 KB): command and exactly addr_bytes address bytes ---
        elif opcode == OcahSpiOpcode.SECTOR_ERASE:
            if not self._wel:
                addr, _, _ = await self._recv_write_frame(graded=False)
                raise _Refused("wel_clear", addr=addr)
            addr, extra, tail_bits = await self._recv_write_frame()
            if extra or tail_bits:
                raise _Refused("unexpected_payload", addr=addr)
            self._do_sector_erase(addr)
            self._wel = False

        # --- Dual and quad commands (four-lane binding only) ---
        elif opcode in LANE_OPCODES and self._mode == SpiMode.QUAD_IO:
            addr, tx_data, rx_data = await self._lane_command(opcode)

        else:
            self.log.warning(
                "%s: unknown opcode 0x%02X — draining to CS deassert", self.name, opcode
            )
            await self._recv_remaining()
            ok, reason = False, "unknown_opcode"

        self._log_transaction(opcode, addr, tx_data, rx_data, ok=ok, reason=reason)

    # ------------------------------------------------------------------
    # Flash operation helpers
    # ------------------------------------------------------------------

    async def _lane_command(self, opcode: int) -> tuple[int, bytes, bytes]:
        """Run a dual or quad command; return (address, bytes sent, payload taken).

        The address phase runs at the format's address width, then the dummy
        clocks, then the data phase at its width. The same refusal rules as
        the single-lane commands apply phase by phase.
        """
        fmt = command_format(opcode)
        assert fmt is not None
        if not fmt.response:
            # QUAD PAGE PROGRAM: the write-enable gate first, then the shape rules.
            if not self._wel:
                await self._recv_remaining()
                raise _Refused("wel_clear")
            addr = await self._recv_read_addr()
            payload, tail_bits = await self._recv_remaining(fmt.data_lanes)
            if tail_bits:
                raise _Refused("partial_byte", addr=addr, data_in=bytes(payload))
            if not payload:
                raise _Refused("no_payload", addr=addr)
            self._do_page_program(addr, bytes(payload))
            self._wel = False
            return addr, b"", bytes(payload)
        try:
            addr = 0
            for _ in range(self._addr_bytes):
                addr = (addr << 8) | await self._recv_byte_lanes(fmt.addr_lanes)
        except _CsDeasserted:
            raise _Refused("partial_address") from None
        for _ in range(fmt.dummy_clocks):
            await First(RisingEdge(self._sclk), RisingEdge(self._cs_n))
            if int(self._cs_n.value) != 0:
                raise _Refused("partial_dummy", addr=addr)
            self._input_clocks += 1
        return addr, await self._do_read(addr, fmt.data_lanes), b""

    async def _do_read(self, addr: int, lanes: int = 1) -> bytes:
        """Stream memory to the controller until CS deasserts; return the complete bytes sent.

        The byte in flight when chip-select rises is not part of the record:
        the controller clocked none or only some of its bits.
        """
        out: bytearray = bytearray()
        while int(self._cs_n.value) == 0:
            if addr >= self._flash_size:
                byte_val = 0xFF
            else:
                byte_val = self._mem[addr]
            if lanes == 1:
                sent = await self._send_byte_single(byte_val)
            else:
                sent = await self._send_byte_lanes(byte_val, lanes)
            if not sent:
                break
            out.append(byte_val)
            addr = (addr + 1) & _ADDR_MASK_24
        return bytes(out)

    def _do_page_program(self, addr: int, data: bytes) -> None:
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
        for bits in range(8):
            await First(RisingEdge(self._sclk), RisingEdge(self._cs_n))
            if int(self._cs_n.value) != 0:
                raise _CsDeasserted(f"{self.name}: CS deasserted during byte receive", bits)
            mosi_sig = self._mosi if self._mode == SpiMode.SINGLE else self._dq_out
            bit = int(mosi_sig.value) & 0x1
            byte_val = (byte_val << 1) | bit
            self._input_bits += 1
            self._input_clocks += 1
        return byte_val

    async def _recv_byte_lanes(self, lanes: int) -> int:
        """Receive one byte on ``lanes`` lanes of ``dq_out``, most significant bits first."""
        if lanes == 1:
            return await self._recv_byte_single()
        byte_val = 0
        mask = (1 << lanes) - 1
        for clocks in range(8 // lanes):
            await First(RisingEdge(self._sclk), RisingEdge(self._cs_n))
            if int(self._cs_n.value) != 0:
                raise _CsDeasserted(
                    f"{self.name}: CS deasserted during byte receive", clocks * lanes
                )
            byte_val = (byte_val << lanes) | (int(self._dq_out.value) & mask)
            self._input_bits += lanes
            self._input_clocks += 1
        return byte_val

    async def _send_byte_single(self, byte_val: int) -> bool:
        """Send one byte MSB-first on MISO, changing on falling SCK edge.

        Races each clock edge against CS deassertion: after the controller
        clocks in the final RX byte it stops the clock and raises CS, so
        waiting on ``FallingEdge(sclk)`` alone would block forever. Returns
        True when the controller sampled all eight bits (the rising edge after
        the last one), False when CS deasserted first.
        """
        for bit_idx in range(7, -1, -1):
            await First(FallingEdge(self._sclk), RisingEdge(self._cs_n))
            if int(self._cs_n.value) != 0:
                return False
            bit = (byte_val >> bit_idx) & 0x1
            if self._mode == SpiMode.SINGLE:
                self._miso.value = bit
            elif self._mode == SpiMode.QUAD_IO:
                self._dq_in.value = bit << 1  # standard mode: lane 1 to the controller
            else:
                self._dq_in.value = bit
        return await self._last_bit_sampled()

    async def _send_byte_lanes(self, byte_val: int, lanes: int) -> bool:
        """Send one byte on ``lanes`` lanes of ``dq_in``, most significant bits first.

        Each falling SCK edge drives the next ``lanes`` bits, the least
        significant of them on lane 0. Returns True when the controller
        sampled the last group.
        """
        mask = (1 << lanes) - 1
        for shift in range(8 - lanes, -1, -lanes):
            await First(FallingEdge(self._sclk), RisingEdge(self._cs_n))
            if int(self._cs_n.value) != 0:
                return False
            self._dq_in.value = (byte_val >> shift) & mask
        return await self._last_bit_sampled()

    async def _last_bit_sampled(self) -> bool:
        """Wait for the sample edge of the bit just driven; False when CS rises first."""
        await First(RisingEdge(self._sclk), RisingEdge(self._cs_n))
        return int(self._cs_n.value) == 0

    async def _send_bytes(self, data: bytes) -> bytes:
        """Send bytes until chip-select rises; return the bytes sent in full."""
        sent = bytearray()
        for byte_val in data:
            if int(self._cs_n.value) != 0:
                break
            if not await self._send_byte_single(byte_val):
                break
            sent.append(byte_val)
        return bytes(sent)

    async def _send_bytes_active(self, data: bytes) -> bytes:
        """Send bytes, then drain remaining clocks until CS deasserts; return the bytes sent in full."""
        sent = await self._send_bytes(data)
        await self._drain_to_cs_high()
        return sent

    async def _recv_addr(self) -> int:
        """Receive addr_bytes bytes and assemble into an integer address."""
        addr = 0
        for _ in range(self._addr_bytes):
            byte_val = await self._recv_byte_single()
            addr = (addr << 8) | byte_val
        return addr

    async def _recv_read_addr(self) -> int:
        """Address of a read; the frame is refused as ``partial_address`` when it ends early."""
        try:
            return await self._recv_addr()
        except _CsDeasserted:
            raise _Refused("partial_address") from None

    async def _recv_write_frame(self, *, graded: bool = True) -> tuple[int, bytes, int]:
        """Take the rest of a write frame up to chip-select rise.

        Returns the address, the complete payload bytes after it, and the bits
        of the byte chip-select ended. A frame shorter than the address is
        refused as ``partial_address`` when ``graded``; otherwise its address
        reads as 0 and its payload as empty.
        """
        rest, tail_bits = await self._recv_remaining()
        if len(rest) < self._addr_bytes:
            if graded:
                raise _Refused("partial_address")
            return 0, b"", 0
        addr = int.from_bytes(rest[: self._addr_bytes], "big")
        return addr, bytes(rest[self._addr_bytes :]), tail_bits

    async def _recv_remaining(self, lanes: int = 1) -> tuple[bytearray, int]:
        """Receive bytes on ``lanes`` lanes until CS deasserts.

        Returns the complete bytes and the count of bits (0 to 7) sampled in
        the byte that chip-select ended.
        """
        buf: bytearray = bytearray()
        while int(self._cs_n.value) == 0:
            try:
                byte_val = await self._recv_byte_lanes(lanes)
                buf.append(byte_val)
            except _CsDeasserted as exc:
                return buf, exc.bits
        return buf, 0

    async def _drain_to_cs_high(self) -> None:
        """Consume clock edges until CS_N returns high."""
        while int(self._cs_n.value) == 0:
            await RisingEdge(self._cs_n)

    # ------------------------------------------------------------------
    # Quad / Octal modes
    # ------------------------------------------------------------------
    # mode="quad" and mode="octal" bind the DQ bus but run the single-bit
    # engine: the command byte, the address bytes, and the data phase all use
    # DQ0 (bit 0 of dq_out / dq_in), one bit per SCK.
    # mode="quad_io" binds four lanes: single-lane phases take lane 0 of
    # dq_out and drive lane 1 of dq_in; the dual and quad commands of
    # LANE_OPCODES run their phases on two or four lanes.

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
            "data_in": bytes(data_in),  # complete payload bytes received from the controller
            "ok": ok,
            "reason": reason,
            "input_bits": self._input_bits,
            "input_clocks": self._input_clocks,
            "tail_bits": self._input_bits % 8,
        }
        self._transactions.append(rec)
        if self._verbose:
            self.log.debug(
                "%s: txn opcode=%s addr=0x%06X out=%d B in=%d B ok=%s%s",
                self.name,
                _opcode_label(opcode),
                addr,
                len(data_out),
                len(data_in),
                ok,
                f" reason={reason}" if reason else "",
            )
