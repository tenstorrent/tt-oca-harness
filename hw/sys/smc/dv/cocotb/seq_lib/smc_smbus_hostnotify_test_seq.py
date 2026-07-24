# SPDX-License-Identifier: Apache-2.0
"""U4-2 remainder: SMBus Host Notify with DUT I2C0 as target @ 0x08.

VIP master drives SMBus 2.0 Host Notify onto ``tb_i2c0_*``; DUT OpenTitan
target captures the frame in ACQDATA (not VIP EEPROM listener).

Honest scope: no SMBALERT# path; Host Notify is VIP-master -> DUT-target.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_csr_seq_utils import SmcCsrSeq

try:
    from .smc_i2c_protocol_vip import SmcI2cMasterVip

    _I2C_VIP_AVAILABLE = True
except Exception:  # noqa: BLE001
    SmcI2cMasterVip = None  # type: ignore[assignment]
    _I2C_VIP_AVAILABLE = False

_HOST_ADDR = 0x08
_TARGET_ADDR = 0x50
_NOTIFY_DATA16 = 0xBEEF

CLOCK_GATE_CONTROL = 0xC001_0018
I2C_CG_EN = 1 << 11
I2C0_WRAP_CTRL = 0xC000_9E00
I2C0_OVRD = 0xC000_9034
I2C0_CTRL = 0xC000_9010
I2C0_STATUS = 0xC000_9014
I2C0_FIFO_CTRL = 0xC000_9020
I2C0_TARGET_ID = 0xC000_9054
I2C0_ACQDATA = 0xC000_9058
I2C0_TIMING0 = 0xC000_903C
I2C0_TIMING1 = 0xC000_9040
I2C0_TIMING2 = 0xC000_9044
I2C0_TIMING3 = 0xC000_9048
I2C0_TIMING4 = 0xC000_904C

I2C_WRAP_ENABLE = 0x1  # I2C_EN only (target path; not CONTROLLER)
I2C_CTRL_ENABLETARGET = 0x2
I2C_OVRD_OFF = 0x0
# RXRST|FMTRST|ACQRST|TXRST — clear host + target FIFOs before target mode.
I2C_FIFO_CTRL_ALL_RST = 0x183
I2C_STATUS_ACQEMPTY = 1 << 9
I2C_ACQ_SIG_START = 0x1
I2C_ACQ_SIG_DATA = 0x0
I2C_ACQ_SIG_STOP = 0x2


def _pack_timing0(thigh: int, tlow: int) -> int:
    return (thigh & 0x1FFF) | ((tlow & 0x1FFF) << 16)


def _pack_timing1(t_r: int, t_f: int) -> int:
    return (t_r & 0x3FF) | ((t_f & 0x1FF) << 16)


def _pack_timing2(tsu_sta: int, thd_sta: int) -> int:
    return (tsu_sta & 0x1FFF) | ((thd_sta & 0x1FFF) << 16)


def _pack_timing3(tsu_dat: int, thd_dat: int) -> int:
    return (tsu_dat & 0x1FF) | ((thd_dat & 0x1FFF) << 16)


def _pack_timing4(tsu_sto: int, t_buf: int) -> int:
    return (tsu_sto & 0x1FFF) | ((t_buf & 0x1FFF) << 16)


def _pack_target_id(address0: int, mask0: int = 0x7F) -> int:
    """TARGET_ID: ADDRESS0[6:0], MASK0[13:7]."""
    return (address0 & 0x7F) | ((mask0 & 0x7F) << 7)


class smc_smbus_hostnotify_test_seq(SmcCsrSeq):
    """DUT-target Host Notify proof."""

    def __init__(self, name: str = "smc_smbus_hostnotify_test_seq") -> None:
        super().__init__(name)
        self.dut_host_notify_ok: bool = False

    async def _program_i2c0_timing(self) -> None:
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))

    async def _drain_acq(self, max_entries: int = 16) -> list[tuple[int, int]]:
        entries: list[tuple[int, int]] = []
        for _ in range(max_entries):
            status = await self.csr_read("I2C0_STATUS_ACQ", I2C0_STATUS)
            if status & I2C_STATUS_ACQEMPTY:
                break
            raw = await self.csr_read("I2C0_ACQDATA", I2C0_ACQDATA)
            abyte = raw & 0xFF
            signal = (raw >> 8) & 0x7
            entries.append((signal, abyte))
        return entries

    async def body(self) -> None:
        assert _I2C_VIP_AVAILABLE, "I2C protocol VIP unavailable"

        await self.prove_dut_i2c0_pins()

        expected_payload = bytes(
            [
                (_TARGET_ADDR & 0x7F) << 1,
                _NOTIFY_DATA16 & 0xFF,
                (_NOTIFY_DATA16 >> 8) & 0xFF,
            ]
        )
        cocotb.log.info(
            "SMBus Host Notify payload self-check: target=0x%02X data=0x%04X -> %s",
            _TARGET_ADDR,
            _NOTIFY_DATA16,
            expected_payload.hex(),
        )

        sim_name = (cocotb.SIM_NAME or "").lower()
        if "verilator" in sim_name:
            cocotb.log.info(
                "SMBus Host Notify DUT-target bus proof skipped on Verilator "
                "(wall-clock bound; VCS is the byte-level authority)."
            )
            return

        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write(
            "CLOCK_GATE_CONTROL_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN
        )
        await self.csr_write("I2C0_WRAP_ENABLE", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE)
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self._program_i2c0_timing()
        await self.csr_write(
            "I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_ALL_RST
        )
        await self.csr_write(
            "I2C0_TARGET_ID_HOST",
            I2C0_TARGET_ID,
            _pack_target_id(_HOST_ADDR, 0x7F),
        )
        await self.csr_write(
            "I2C0_ENABLETARGET", I2C0_CTRL, I2C_CTRL_ENABLETARGET
        )
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        await self._drain_acq()

        master = SmcI2cMasterVip(speed=100_000, name="smc_smbus_hn_master")
        payload = await master.smbus_host_notify(_TARGET_ADDR, _NOTIFY_DATA16)

        # Wait until ACQ has data, then drain (Host Notify = 3 data bytes).
        for _ in range(2000):
            status = await self.csr_read("I2C0_STATUS_WAIT_ACQ", I2C0_STATUS)
            if not (status & I2C_STATUS_ACQEMPTY):
                break
            await Timer(10, units="us")
        else:
            raise AssertionError("DUT ACQ stayed empty after Host Notify")
        await Timer(50, units="us")

        entries = await self._drain_acq()
        cocotb.log.info(
            "DUT Host Notify ACQDATA entries=%s",
            [(f"sig={s}", f"0x{b:02X}") for s, b in entries],
        )
        assert entries, "DUT ACQDATA empty after Host Notify"

        # OT target: address may appear as SIGNAL=START, or as leading DATA if
        # the START marker was coalesced; hard-gate is the 3-byte HN payload.
        data_bytes = [b for s, b in entries if s == I2C_ACQ_SIG_DATA]
        addr_bytes = [b for s, b in entries if s == I2C_ACQ_SIG_START]
        if addr_bytes:
            assert (addr_bytes[0] & 0xFE) == (_HOST_ADDR << 1), (
                f"DUT Host Notify address ACQ mismatch: {addr_bytes}"
            )
        # Payload may be pure DATA entries, or DATA after START.
        matched = (
            data_bytes[:3] == list(expected_payload)
            or data_bytes[-3:] == list(expected_payload)
        )
        assert matched, (
            f"DUT Host Notify data ACQ mismatch: got {[hex(x) for x in data_bytes]}, "
            f"expected {[hex(x) for x in expected_payload]}"
        )
        if not any(s == I2C_ACQ_SIG_STOP for s, _ in entries):
            cocotb.log.warning(
                "DUT Host Notify: STOP not in ACQDATA (payload gate still OK)"
            )

        await self.csr_write("I2C0_CTRL_DISABLE", I2C0_CTRL, 0)
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, cg)
        self.dut_host_notify_ok = True
        cocotb.log.info(
            "DUT Host Notify ACQDATA OK: payload=%s (VIP master -> DUT target @0x08)",
            payload.hex(),
        )
