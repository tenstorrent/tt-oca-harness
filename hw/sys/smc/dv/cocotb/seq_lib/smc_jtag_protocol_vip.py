# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS CPU JTAG protocol VIP wrapper.

Thin DUT-local facade over ``ocah_jtag_vip`` for the SMC CPU TAP brought out
as ``tb_cpu_jtag_*``:

* ``OcahJtagMasterDriver`` / ``OcahJtagDevice`` provide bus bind + register map.
* Active-high ``tb_cpu_jtag_reset`` is driven only by this wrapper — it is
  NOT exposed as bus ``trst`` because ``cocotbext-jtag`` assumes
  IEEE active-low TRST polarity.
* Runtime IR/DR scans use ``OcahJtagMasterDriver`` bit-bang only (no ``JTAGDriver``).
  cocotbext-jtag's GatedClock + RX FSM desyncs after long DMI idle sequences
  (RX stuck in CAPTURE_IR), which makes DMI captures look like status=0/data=0.
"""

from __future__ import annotations

import logging
from typing import Optional

import cocotb
from cocotb.triggers import Timer
from ocah_jtag_vip import OcahJtagDevice, OcahJtagMasterDriver, OcahJtagMasterDriverError

# IEEE 1149.1 / RISC-V Debug Spec opcodes (5-bit IR).
_IDCODE_OPCODE = 0x01
_DTMCS_OPCODE = 0x10
_DMI_OPCODE = 0x11
_BYPASS_OPCODE = 0x1F
_DMI_DR_WIDTH = 41

# `tb_top.sv` JEP106 + part-number + version composition.
EXPECTED_CPU_TAP_IDCODE = 0x10CA0555

SmcJtagTapError = OcahJtagMasterDriverError


class SmcCpuTapDevice(OcahJtagDevice):
    """Device descriptor for the SMC CPU TAP (EL2 RISC-V DTM-like layout)."""

    def __init__(self, idcode: int = EXPECTED_CPU_TAP_IDCODE) -> None:
        super().__init__(
            name="smc_cpu_tap",
            idcode=idcode,
            ir_width=5,
            idle_delay=6,
            add_bypass=True,
        )
        self.add_reg("IDCODE", 32, _IDCODE_OPCODE)
        self.add_reg("DTMCS", 32, _DTMCS_OPCODE)
        self.add_reg("DMI", _DMI_DR_WIDTH, _DMI_OPCODE, write=True)


class SmcJtagTap:
    """SMC OSS CPU JTAG TAP wrapper around ``ocah_jtag_vip`` bit-bang."""

    def __init__(
        self,
        *,
        prefix: str = "tb_cpu_jtag",
        reset_signal_name: Optional[str] = "tb_cpu_jtag_reset",
        tck_period_ns: int = 10,
        ir_width: int = 5,
        expected_idcode: int = EXPECTED_CPU_TAP_IDCODE,
        name: str = "smc_cpu_jtag",
    ) -> None:
        self.name = name
        self.log = logging.getLogger(name)
        self.ir_width = ir_width
        self._tck_period_ns = tck_period_ns
        self._prefix = prefix
        self._reset_signal_name = reset_signal_name
        self._expected_idcode = expected_idcode
        self._tap: Optional[OcahJtagMasterDriver] = None
        self._device: Optional[SmcCpuTapDevice] = None
        self._dmi_selected: bool = False

    def _drive_reset(self, asserted: bool) -> None:
        """Drive SMC active-high CPU JTAG reset (1=assert)."""
        if self._reset_signal_name is None:
            return
        getattr(cocotb.top, self._reset_signal_name).value = 1 if asserted else 0

    def init_signals(self) -> None:
        """Drive TAP inputs to a safe idle state and bind OcahJtagMasterDriver."""
        dut = cocotb.top
        getattr(dut, f"{self._prefix}_tck").value = 0
        getattr(dut, f"{self._prefix}_tms").value = 1
        getattr(dut, f"{self._prefix}_tdi").value = 0
        self._drive_reset(False)

        self._tap = OcahJtagMasterDriver.from_prefix(
            dut,
            self._prefix,
            name=self.name,
            tck_period_ns=self._tck_period_ns,
            ir_width=self.ir_width,
            tap_type="cpu",
            trst_signal=None,
        )
        self._device = SmcCpuTapDevice(idcode=self._expected_idcode)
        self._tap.add_device(self._device)
        self._tap.init_signals()
        self._dmi_selected = False
        cocotb.log.info(
            "%s: bound OcahJtagMasterDriver bit-bang (prefix=%s, ir_width=%d, tck=%d ns, "
            "idcode=0x%08X, reset=%s active-high external)",
            self.name,
            self._prefix,
            self.ir_width,
            self._tck_period_ns,
            self._expected_idcode,
            self._reset_signal_name,
        )

    def _ensure(self) -> OcahJtagMasterDriver:
        if self._tap is None:
            self.init_signals()
        assert self._tap is not None
        return self._tap

    async def _idle_tck(self, cycles: int) -> None:
        """Hold TMS=0 (Run-Test/Idle) for ``cycles`` TCK edges."""
        tap = self._ensure()
        for _ in range(max(int(cycles), 0)):
            await tap.step_tms(0)

    async def reset_tap(self, *, assert_trst: bool = True) -> None:
        """Force the TAP into TEST_LOGIC_RESET; TRST pulse + TMS navigation.

        Rocket's DMI TL xbar / DM outer use *synchronous* reset on TCK. A
        wall-time TRST pulse with TCK held low never clears those regs
        (``out_woready`` stays X and dmcontrol writes are dropped). Hold
        ``tb_cpu_jtag_reset`` while stepping TCK.
        """
        tap = self._ensure()
        if assert_trst and self._reset_signal_name is not None:
            self._drive_reset(True)
            for _ in range(16):
                await tap.step_tms(1)
            self._drive_reset(False)
            for _ in range(4):
                await tap.step_tms(1)
        else:
            await Timer(self._tck_period_ns * 2, unit="ns")
        await tap.reset_tap(10)
        self._dmi_selected = False

    async def read_idcode(self, *, check: bool = True) -> int:
        tap = self._ensure()
        captured = int(await tap.read_idcode())
        self._dmi_selected = False
        cocotb.log.info(
            "%s: IDCODE=0x%08X (expected 0x%08X)",
            self.name,
            captured,
            self._expected_idcode,
        )
        if captured in (0, 0xFFFFFFFF):
            raise SmcJtagTapError(f"{self.name}: implausible IDCODE 0x{captured:08X}")
        if captured & 0x1 != 0x1:
            raise SmcJtagTapError(
                f"{self.name}: IDCODE bit[0] must be 1 (IEEE 1149.1), got 0x{captured:08X}"
            )
        if check and captured != self._expected_idcode:
            raise SmcJtagTapError(
                f"{self.name}: IDCODE 0x{captured:08X} != expected 0x{self._expected_idcode:08X}"
            )
        return captured

    async def shift_ir(self, addr_or_name) -> None:
        tap = self._ensure()
        if isinstance(addr_or_name, str):
            if self._device is None:
                raise SmcJtagTapError(f"{self.name}: device not initialized")
            opcode = self._device.reg(addr_or_name).opcode
        else:
            opcode = int(addr_or_name)
        await tap.shift_ir(opcode, width=self.ir_width, back_to_rti=True)
        self._dmi_selected = opcode == _DMI_OPCODE

    async def shift_dr(self, value: Optional[int] = None, *, width: int = 32) -> int:
        tap = self._ensure()
        return int(await tap.shift_dr(0 if value is None else int(value), width, back_to_rti=True))

    async def bypass(self) -> None:
        await self.shift_ir(_BYPASS_OPCODE)

    async def read_dtmcs(self) -> int:
        """Shift DTMCS instruction (IR=0x10), read 32-bit DR."""
        tap = self._ensure()
        captured = int(await tap.read("DTMCS"))
        self._dmi_selected = False
        version = captured & 0xF
        abits = (captured >> 4) & 0x3F
        idle = (captured >> 12) & 0x7
        cocotb.log.info(
            "%s: DTMCS=0x%08X (version=0x%X, abits=%d, idle=%d)",
            self.name,
            captured,
            version,
            abits,
            idle,
        )
        return captured

    @staticmethod
    def _pack_dmi(addr: int, data: int, op: int, *, abits: int = 7) -> int:
        """Pack RISC-V DTM DMI scan value: {addr[abits], data[32], op[2]}."""
        return ((addr & ((1 << abits) - 1)) << 34) | ((data & 0xFFFFFFFF) << 2) | (op & 0x3)

    @staticmethod
    def _unpack_dmi(raw: int) -> tuple[int, int, int]:
        """Return (addr_ignored_or_zero, data, status_op) from a DMI capture."""
        status = raw & 0x3
        data = (raw >> 2) & 0xFFFFFFFF
        return 0, data, status

    async def _select_dmi(self) -> None:
        if self._dmi_selected:
            return
        tap = self._ensure()
        await tap.shift_ir(_DMI_OPCODE, width=self.ir_width, back_to_rti=True)
        self._dmi_selected = True

    async def _dmi_scan(self, value: int) -> int:
        """One 41-bit DMI DR scan; return TDO capture. Leaves TAP in RTI."""
        tap = self._ensure()
        await self._select_dmi()
        captured = int(await tap.shift_dr(int(value), _DMI_DR_WIDTH, back_to_rti=True))
        # Honor DTMCS.idle recommendation between DMI updates.
        idle = 6 if self._device is None else max(int(self._device.idle_delay), 5)
        await self._idle_tck(idle)
        return captured

    async def _dtmcs_dmireset(self, dtmcs: int) -> None:
        tap = self._ensure()
        await tap.write("DTMCS", int(dtmcs) | (1 << 16))
        self._dmi_selected = False
        await self._idle_tck(16)

    async def dmi_access(
        self, addr: int, data: int = 0, *, op: int = 1, abits: int = 7, idle: int = 5
    ) -> tuple[int, int]:
        """Perform one DMI transaction; return (data, status)."""
        req = self._pack_dmi(addr, data, op, abits=abits)
        await self._dmi_scan(req)  # launch; prior TDO ignored
        # Extra RTI so DTM/DM can complete before Capture-DR (avoid stickyBusy).
        await self._idle_tck(max(int(idle), 5) * 8)
        captured = await self._dmi_scan(0)  # NOP capture
        _, resp_data, status = self._unpack_dmi(captured)
        if status == 3:
            dtmcs = await self.read_dtmcs()
            await self._dtmcs_dmireset(dtmcs)
            await self._idle_tck(max(int(idle), 5) * 8)
            await self._dmi_scan(req)
            await self._idle_tck(max(int(idle), 5) * 8)
            captured = await self._dmi_scan(0)
            _, resp_data, status = self._unpack_dmi(captured)
        cocotb.log.info(
            "%s: DMI addr=0x%02X op=%d req=0x%X -> data=0x%08X status=%d raw=0x%X",
            self.name,
            addr,
            op,
            req,
            resp_data,
            status,
            captured,
        )
        return resp_data, status

    async def dmi_read(self, addr: int, *, abits: int = 7, idle: int = 5) -> int:
        """DMI read; raise on failed/busy status. Returns 32-bit data."""
        data, status = await self.dmi_access(addr, 0, op=1, abits=abits, idle=idle)
        for _ in range(4):
            if status != 3:
                break
            await self._idle_tck(max(int(idle), 5) * 8)
            data, status = await self.dmi_access(addr, 0, op=1, abits=abits, idle=idle)
        if status != 0:
            raise SmcJtagTapError(
                f"{self.name}: DMI read 0x{addr:02X} status={status} data=0x{data:08X}"
            )
        return data

    async def dmi_write(self, addr: int, data: int, *, abits: int = 7, idle: int = 5) -> None:
        """DMI write; raise on failed status (busy retried). Empty capture OK."""
        _, status = await self.dmi_access(addr, data, op=2, abits=abits, idle=idle)
        for _ in range(4):
            if status != 3:
                break
            await self._idle_tck(max(int(idle), 5) * 8)
            _, status = await self.dmi_access(addr, data, op=2, abits=abits, idle=idle)
        if status not in (0, 3):
            raise SmcJtagTapError(
                f"{self.name}: DMI write 0x{addr:02X}=0x{data:08X} status={status}"
            )
        if status == 3:
            raise SmcJtagTapError(f"{self.name}: DMI write 0x{addr:02X}=0x{data:08X} still busy")

    async def read_dmstatus(self) -> int:
        """Activate DM (dmactive + ack CDC) then read dmstatus (DMI 0x11)."""
        dtmcs = await self.read_dtmcs()
        abits = (dtmcs >> 4) & 0x3F
        idle = max((dtmcs >> 12) & 0x7, 5)
        if abits == 0:
            abits = 7
        if ((dtmcs >> 8) & 0x7) != 0:
            await self._dtmcs_dmireset(dtmcs)
        await self.dmi_write(0x10, 0x0000_0001, abits=abits, idle=idle)
        # Keep TCK running for dmactiveAck CDC + debug_clock ungating.
        await self._idle_tck(max(idle, 5) * 200)
        try:
            cocotb.log.info(
                "%s: after dmactive write: tb_cpu_debug_dmactive=%d ack=%d",
                self.name,
                int(cocotb.top.tb_cpu_debug_dmactive.value),
                int(cocotb.top.tb_cpu_debug_dmactive_ack.value),
            )
        except Exception:  # noqa: BLE001 - tb_cpu_debug_dmactive* probes are optional
            pass
        # Both polls below raise on expiry: a debug module that never leaves
        # reset, or is absent, must fail the smoke test rather than be logged
        # as a pass ([TIMEOUT-MUST-FAIL]).
        _DM_POLLS = 16
        dmcontrol = 0
        for _ in range(_DM_POLLS):
            dmcontrol = await self.dmi_read(0x10, abits=abits, idle=idle)
            if dmcontrol & 0x1:
                break
            await self._idle_tck(idle * 20)
        else:
            raise AssertionError(
                f"{self.name}: DMCONTROL.dmactive never set after {_DM_POLLS} "
                f"DMI reads of 0x10 (last readback 0x{dmcontrol:08X}). The "
                f"debug module is not active, so every later DMI result in "
                f"this scenario is meaningless."
            )
        cocotb.log.info("%s: dmcontrol readback=0x%08X", self.name, dmcontrol)
        dmstatus = 0
        for _ in range(_DM_POLLS):
            dmstatus = await self.dmi_read(0x11, abits=abits, idle=idle)
            if (dmstatus & 0xF) != 0:
                break
            await self._idle_tck(idle * 20)
        else:
            raise AssertionError(
                f"{self.name}: DMSTATUS.version stayed 0 after {_DM_POLLS} DMI "
                f"reads of 0x11 (last readback 0x{dmstatus:08X}). Version 0 is "
                f"'no debug module present' in the RISC-V debug spec, so this "
                f"is not a slow bring-up -- there is nothing answering."
            )
        version = dmstatus & 0xF
        cocotb.log.info(
            "%s: dmstatus=0x%08X (version=%d authenticated=%d abits=%d idle=%d)",
            self.name,
            dmstatus,
            version,
            (dmstatus >> 7) & 0x1,
            abits,
            idle,
        )
        return dmstatus
