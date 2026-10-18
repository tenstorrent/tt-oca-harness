# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Debug-module DMI layer over the SEP core JTAG TAP.

The VeeR EL2 core TAP is a RISC-V debug transport module (RISC-V Debug
Specification 0.13, Debug Transport Module): IR width 5, ``dtmcs`` at IR 0x10,
``dmi`` at IR 0x11. A ``dmi`` scan is ``abits + 34`` bits: address in the top
``abits`` bits, 32-bit data, then a 2-bit op (1 read, 2 write; the captured op
is the status of the previous access: 0 success, 2 failed, 3 busy). IR 0x18 is
the reset-vector TDR of ``hw/sys/sep/doc/cpu.adoc`` (Reset Vector), 32 bits,
PC[31:1] with bit 0 shifted as 0.

The pins are the ``tb_top`` top-port drive ``jtag_{tck,tms,tdi,trst_n}_i``
with ``jtag_tdo_o``; a leaf sets ``jtag_bench_own_i`` to 1 before it uses this
layer (``SepJtagDmi.take_pins``). The TAP driver is the shared
``OcahJtagMasterDriver``.

The driver reads an X or Z on TDO as 0. This layer puts a sampler on the
driver's TDO handle that records each X or Z value the driver reads in
Shift-DR, and a ``dtmcs`` or ``dmi`` scan with an X or Z in a captured bit
raises ``DmiError``. An undriven TDO therefore cannot decode as a DMI success
with data 0.

Usage::

    dmi = SepJtagDmi.from_dut(dut)
    dmi.take_pins()
    await dmi.tap.reset_tap()
    dtmcs = await dmi.read_dtmcs()
    await dmi.dmi_write(DM_DMCONTROL, 1)
    val = await dmi.sba_read(0x1000_0000, size=2)
"""

from __future__ import annotations

import logging
from typing import Any

from ocah_jtag_vip import OcahJtagMasterDriver, OcahJtagState

IR_WIDTH = 5
IR_IDCODE = 0x01
IR_DTMCS = 0x10
IR_DMI = 0x11
IR_RSTVEC = 0x18
IR_BYPASS = 0x1F
DTMCS_BITS = 32
RSTVEC_BITS = 32

DMI_OP_NOP = 0
DMI_OP_READ = 1
DMI_OP_WRITE = 2
DMI_STATUS_OK = 0
DMI_STATUS_FAILED = 2
DMI_STATUS_BUSY = 3

# Debug module registers (RISC-V Debug Specification 0.13, Debug Module).
DM_DATA0 = 0x04
DM_DMCONTROL = 0x10
DM_DMSTATUS = 0x11
DM_HARTINFO = 0x12
DM_ABSTRACTCS = 0x16
DM_COMMAND = 0x17
DM_SBCS = 0x38
DM_SBADDRESS0 = 0x39
DM_SBADDRESS1 = 0x3A
DM_SBDATA0 = 0x3C
DM_SBDATA1 = 0x3D

# sbcs fields.
SBCS_SBBUSYERROR = 1 << 22
SBCS_SBBUSY = 1 << 21
SBCS_SBREADONADDR = 1 << 20
SBCS_SBACCESS_LSB = 17
SBCS_SBAUTOINCREMENT = 1 << 16
SBCS_SBREADONDATA = 1 << 15
SBCS_SBERROR_LSB = 12
SBCS_SBERROR_MASK = 0x7 << SBCS_SBERROR_LSB

# dmcontrol fields.
DMCONTROL_DMACTIVE = 1 << 0
DMCONTROL_NDMRESET = 1 << 1
DMCONTROL_HALTREQ = 1 << 31
DMCONTROL_RESUMEREQ = 1 << 30

PIN_MAP = {
    "tck": "jtag_tck_i",
    "tms": "jtag_tms_i",
    "tdi": "jtag_tdi_i",
    "tdo": "jtag_tdo_o",
    "trst": "jtag_trst_n_i",
}

_SBACCESS = {1: 0, 2: 1, 4: 2, 8: 3}


class DmiError(AssertionError):
    """A DMI access failed or stayed busy past its bound."""


class _TdoSampler:
    """Stands in for the TDO handle on the driver bus.

    The driver reads ``value`` once per TCK cycle, before it advances its
    tracked TAP state, so the tracked state at the read is the state of the
    sampled bit. A read in Shift-DR whose bits are not all 0 or 1 is recorded
    in ``unknown``. Every other attribute is the handle's own.
    """

    def __init__(self, handle: Any, tap: OcahJtagMasterDriver) -> None:
        self._handle = handle
        self._tap = tap
        self.unknown: list[str] = []

    @property
    def value(self) -> Any:
        val = self._handle.value
        if self._tap.get_current_state() is OcahJtagState.SHIFT_DR:
            bits = str(val)
            if not bits or any(c not in "01" for c in bits):
                self.unknown.append(bits)
        return val

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)


def dtmcs_fields(value: int) -> dict[str, int]:
    """Decode ``dtmcs``: version, abits, dmistat, idle."""
    return {
        "version": value & 0xF,
        "abits": (value >> 4) & 0x3F,
        "dmistat": (value >> 10) & 0x3,
        "idle": (value >> 12) & 0x7,
    }


class SepJtagDmi:
    """DMI reads and writes, system-bus access and the reset-vector TDR."""

    def __init__(
        self,
        tap: OcahJtagMasterDriver,
        *,
        dut: Any = None,
        abits: int = 7,
        busy_bound: int = 64,
        log: logging.Logger | None = None,
    ) -> None:
        self.tap = tap
        self.dut = dut
        self.abits = abits
        self.busy_bound = busy_bound
        self.log = log or logging.getLogger("cocotb.sep_jtag_dmi")
        tdo = getattr(tap.bus, "tdo", None)
        if tdo is None:
            raise DmiError("the TAP driver has no TDO handle")
        if not isinstance(tdo, _TdoSampler):
            tdo = _TdoSampler(tdo, tap)
            tap.bus.tdo = tdo
        self._tdo = tdo

    @classmethod
    def from_dut(cls, dut, *, tck_period_ns: int = 40, **kwargs: Any) -> "SepJtagDmi":
        tap = OcahJtagMasterDriver(
            dut,
            name="sep_core_tap",
            tck_period_ns=tck_period_ns,
            ir_width=IR_WIDTH,
            tap_type="dtm",
            signal_map=dict(PIN_MAP),
        )
        return cls(tap, dut=dut, **kwargs)

    def take_pins(self) -> None:
        """Drive the TAP idle values, then hand the core TAP pins to this driver."""
        if self.dut is None:
            raise DmiError("take_pins needs the dut handle")
        self.tap.init_signals()
        self.dut.jtag_bench_own_i.value = 1

    def release_pins(self) -> None:
        """Give the core TAP pins back to the tb_top registers."""
        if self.dut is not None:
            self.dut.jtag_bench_own_i.value = 0

    @property
    def dmi_bits(self) -> int:
        return self.abits + 34

    async def _shift_dr_known(self, value: int, width: int, what: str) -> int:
        """``shift_dr`` back to Run-Test/Idle; raise when a captured bit is X or Z."""
        self._tdo.unknown.clear()
        cap = await self.tap.shift_dr(value, width, back_to_rti=True)
        if self._tdo.unknown:
            raise DmiError(
                f"{what}: TDO held X or Z on {len(self._tdo.unknown)} of {width} "
                f"captured bits (values {','.join(self._tdo.unknown)})"
            )
        return int(cap)

    async def read_dtmcs(self) -> int:
        await self.tap.shift_ir(IR_DTMCS, IR_WIDTH, back_to_rti=False)
        return await self._shift_dr_known(0, DTMCS_BITS, "dtmcs scan")

    async def dmi_reset(self) -> None:
        """Write ``dtmcs.dmireset`` (bit 16) to clear a sticky DMI error."""
        await self.tap.shift_ir(IR_DTMCS, IR_WIDTH, back_to_rti=False)
        await self.tap.shift_dr(1 << 16, DTMCS_BITS, back_to_rti=True)

    def _pack(self, addr: int, data: int, op: int) -> int:
        return ((addr & ((1 << self.abits) - 1)) << 34) | ((data & 0xFFFF_FFFF) << 2) | (op & 3)

    @staticmethod
    def _unpack(value: int) -> tuple[int, int]:
        """(data, status) of a captured ``dmi`` scan."""
        return (value >> 2) & 0xFFFF_FFFF, value & 3

    async def _dmi_scan(self, addr: int, data: int, op: int) -> tuple[int, int]:
        await self.tap.shift_ir(IR_DMI, IR_WIDTH, back_to_rti=False)
        cap = await self._shift_dr_known(
            self._pack(addr, data, op), self.dmi_bits, f"dmi scan addr=0x{addr:02x} op={op}"
        )
        return self._unpack(cap)

    async def _dmi_access(self, addr: int, data: int, op: int) -> int:
        """Issue one access, then read its status with a NOP scan.

        A busy status (3) clears with ``dtmcs.dmireset`` and the access is
        issued again, as the debug specification states; the number of tries
        is bounded by ``busy_bound``.
        """
        for _ in range(self.busy_bound):
            await self._dmi_scan(addr, data, op)
            rdata, status = await self._dmi_scan(0, 0, DMI_OP_NOP)
            if status == DMI_STATUS_OK:
                return rdata
            if status == DMI_STATUS_FAILED:
                raise DmiError(f"DMI access to 0x{addr:02x} failed (status 2)")
            await self.dmi_reset()
        raise DmiError(f"DMI access to 0x{addr:02x} busy after {self.busy_bound} tries")

    async def dmi_read(self, addr: int) -> int:
        data = await self._dmi_access(addr, 0, DMI_OP_READ)
        self.log.debug("DMI read  0x%02x -> 0x%08x", addr, data)
        return data

    async def dmi_write(self, addr: int, data: int) -> None:
        await self._dmi_access(addr, data, DMI_OP_WRITE)
        self.log.debug("DMI write 0x%02x <- 0x%08x", addr, data)

    async def wait_sbbusy_clear(self) -> int:
        """Poll ``sbcs`` until ``sbbusy`` is 0 (bounded); return ``sbcs``."""
        for _ in range(self.busy_bound):
            sbcs = await self.dmi_read(DM_SBCS)
            if not sbcs & SBCS_SBBUSY:
                return sbcs
        raise DmiError(f"sbcs.sbbusy still 1 after {self.busy_bound} reads")

    async def sba_setup(self, size: int, *, read_on_addr: bool, read_on_data: bool = False) -> None:
        """Program ``sbcs``: access size, read triggers, sticky errors cleared (W1C)."""
        if size not in _SBACCESS:
            raise ValueError(f"system-bus access size {size} is not 1, 2, 4 or 8")
        sbcs = (_SBACCESS[size] << SBCS_SBACCESS_LSB) | SBCS_SBBUSYERROR | SBCS_SBERROR_MASK
        if read_on_addr:
            sbcs |= SBCS_SBREADONADDR
        if read_on_data:
            sbcs |= SBCS_SBREADONDATA
        await self.dmi_write(DM_SBCS, sbcs)

    async def sba_read(self, addr: int, *, size: int = 4) -> tuple[int, int]:
        """System-bus read; returns (data, sberror). 8-byte reads return both data words."""
        await self.sba_setup(size, read_on_addr=True)
        await self.dmi_write(DM_SBADDRESS0, addr)
        sbcs = await self.wait_sbbusy_clear()
        lo = await self.dmi_read(DM_SBDATA0)
        hi = await self.dmi_read(DM_SBDATA1) if size == 8 else 0
        return (hi << 32) | lo, (sbcs >> SBCS_SBERROR_LSB) & 0x7

    async def sba_write(self, addr: int, data: int, *, size: int = 4) -> int:
        """System-bus write; returns sberror. The write starts on the ``sbdata0`` write."""
        await self.sba_setup(size, read_on_addr=False)
        await self.dmi_write(DM_SBADDRESS0, addr)
        if size == 8:
            await self.dmi_write(DM_SBDATA1, (data >> 32) & 0xFFFF_FFFF)
        await self.dmi_write(DM_SBDATA0, data & 0xFFFF_FFFF)
        sbcs = await self.wait_sbbusy_clear()
        return (sbcs >> SBCS_SBERROR_LSB) & 0x7

    async def shift_rstvec(self, vector: int) -> int:
        """Shift ``vector`` into the reset-vector TDR; returns the captured bits."""
        if vector & 1:
            raise ValueError("the reset vector must be halfword aligned")
        await self.tap.shift_ir(IR_RSTVEC, IR_WIDTH, back_to_rti=False)
        return int(await self.tap.shift_dr(vector & 0xFFFF_FFFE, RSTVEC_BITS, back_to_rti=True))

    async def tlr(self) -> None:
        """Enter Test-Logic-Reset with five TMS-high clocks, TRST released."""
        for _ in range(5):
            await self.tap.step_tms(1)

    async def trst_pulse(self, tck_cycles: int = 1) -> None:
        """Assert ``jtag_trst_n`` for ``tck_cycles`` TCK clocks, then release it."""
        await self.tap.assert_trst(tck_cycles=tck_cycles)
        await self.tap.release_trst()
