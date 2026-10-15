# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U4-2: SMBus Host Notify with DUT I2C0 as target @ 0x08.

VIP master drives SMBus 2.0 Host Notify onto ``tb_i2c0_*``; DUT OpenTitan
target captures the frame in ACQDATA (not VIP EEPROM listener).

Scope: Host Notify only, VIP master -> DUT target; the SMBALERT# path is
covered by smc_smbus_alert_ara_test_seq.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_FMTRST,
    I2C_FIFO_CTRL_RXRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_WRAP_CTRL_TARGET,
    acq_abyte,
    acq_signal,
    pack_acq,
)

try:
    from .smc_i2c_protocol_vip import SmcI2cMasterVip

    _I2C_VIP_AVAILABLE = True
except Exception:  # noqa: BLE001
    SmcI2cMasterVip = None  # type: ignore[assignment]
    _I2C_VIP_AVAILABLE = False

_HOST_ADDR = 0x08
_TARGET_ADDR = 0x50
_NOTIFY_DATA16 = 0xBEEF

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

I2C0_WRAP_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0)
I2C0_OVRD = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", 0)
I2C0_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0)
I2C0_STATUS = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", 0)
I2C0_FIFO_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0)
I2C0_TARGET_ID = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", 0)
I2C0_ACQDATA = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR", 0)
I2C0_TIMING0 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR", 0)
I2C0_TIMING1 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR", 0)
I2C0_TIMING2 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR", 0)
I2C0_TIMING3 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR", 0)
I2C0_TIMING4 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR", 0)

# I2C_EN only (target path; not CONTROLLER) — generated-header symbol.
I2C_WRAP_ENABLE = I2C_WRAP_CTRL_TARGET
I2C_OVRD_OFF = 0x0
# RXRST|FMTRST|ACQRST|TXRST — clear host + target FIFOs before target mode.
I2C_FIFO_CTRL_ALL_RST = (
    I2C_FIFO_CTRL_RXRST | I2C_FIFO_CTRL_FMTRST | I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST
)


def _host_notify_payload(target_addr7: int, data16: int) -> bytes:
    """SMBus 2.0 Host Notify data payload.

    SMBus 2.0 §5.5.10 Host Notify protocol: after the SMBus Host address the
    notifying device sends its own 7-bit address left-shifted with the R/W bit
    cleared, then the 16-bit status low byte, then the high byte.  Single
    source of the golden for both the sequence gate and the scoreboard record.
    """
    return bytes(
        [
            (target_addr7 & 0x7F) << 1,
            data16 & 0xFF,
            (data16 >> 8) & 0xFF,
        ]
    )


#: Golden Host Notify data payload for this scenario (see above).
EXPECTED_PAYLOAD = _host_notify_payload(_TARGET_ADDR, _NOTIFY_DATA16)


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
        #: Golden, derived once from ``_TARGET_ADDR`` / ``_NOTIFY_DATA16``.
        self.expected_bytes: bytes = EXPECTED_PAYLOAD
        #: Data bytes actually drained out of the DUT ACQ FIFO.
        self.observed_bytes: bytes = b""
        #: Full ACQ word list (SIGNAL+ABYTE) actually drained from the DUT.
        self.observed_acq_words: list[int] = []

    async def _program_i2c0_timing(self) -> None:
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))

    async def _drain_acq(self, max_entries: int = 16) -> list[int]:
        """Non-blocking flush: drain whatever ACQ holds right now."""
        words: list[int] = []
        for _ in range(max_entries):
            status = await self.csr_read("I2C0_STATUS_ACQ", I2C0_STATUS)
            if status & I2C_STATUS_ACQEMPTY:
                break
            raw = await self.csr_read("I2C0_ACQDATA", I2C0_ACQDATA)
            words.append(int(raw) & 0xFFFF)
        return words

    async def _drain_acq_until_stop(self, max_polls: int = 4000) -> list[int]:
        """Bounded drain that requires the frame to terminate in a STOP word.

        Mirrors ``smc_i2c_p0_multictrl_test_seq._drain_acq_until_stop``: expiry
        without a STOP raises, so a frame the DUT never terminated fails the
        testcase instead of warning.
        """
        words: list[int] = []
        saw_stop = False
        for _ in range(max_polls):
            status = await self.csr_read("I2C0_STATUS_WAIT_ACQ", I2C0_STATUS)
            if status & I2C_STATUS_ACQEMPTY:
                if saw_stop:
                    return words
                await Timer(10, unit="us")
                continue
            raw = await self.csr_read("I2C0_ACQDATA", I2C0_ACQDATA)
            words.append(int(raw) & 0xFFFF)
            if acq_signal(raw) == I2C_ACQ_SIGNAL_STOP:
                saw_stop = True
        raise AssertionError(
            "DUT Host Notify: ACQ frame never terminated in a STOP word "
            f"(saw_stop={saw_stop} words={[hex(w) for w in words]})"
        )

    async def body(self) -> None:
        assert _I2C_VIP_AVAILABLE, "I2C protocol VIP unavailable"

        await self.prove_dut_i2c0_pins()

        expected_payload = self.expected_bytes
        cocotb.log.info(
            "SMBus Host Notify payload self-check: target=0x%02X data=0x%04X -> %s",
            _TARGET_ADDR,
            _NOTIFY_DATA16,
            expected_payload.hex(),
        )

        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_ENABLE", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE)
        await self.wait_i2c0_lsio_ready("I2C0_HOSTNOTIFY_WRAP")
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self._program_i2c0_timing()
        await self.csr_write("I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_ALL_RST)
        await self.csr_write(
            "I2C0_TARGET_ID_HOST",
            I2C0_TARGET_ID,
            _pack_target_id(_HOST_ADDR, 0x7F),
        )
        # ACQ_START_STOP_EN makes the OT target push explicit START/STOP words
        # into ACQDATA, so the frame's address and termination are observable
        # (the same programming smc_i2c_p0_multictrl_test_seq uses).
        await self.csr_write(
            "I2C0_ENABLETARGET",
            I2C0_CTRL,
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        await self._drain_acq()

        master = SmcI2cMasterVip(speed=100_000, name="smc_smbus_hn_master")
        payload = await master.smbus_host_notify(_TARGET_ADDR, _NOTIFY_DATA16)

        # Bounded drain that requires a terminating STOP word; expiry raises.
        words = await self._drain_acq_until_stop()
        self.observed_acq_words = list(words)
        cocotb.log.info(
            "DUT Host Notify ACQDATA words=%s",
            [f"(sig={acq_signal(w)},0x{acq_abyte(w):02X})" for w in words],
        )

        # Exact expected frame: START(host addr, W) + 3 HN data bytes + STOP.
        expect = [pack_acq((_HOST_ADDR << 1) | 0, I2C_ACQ_SIGNAL_START)]
        expect.extend(pack_acq(b, I2C_ACQ_SIGNAL_NONE) for b in expected_payload)
        expect.append(pack_acq(0, I2C_ACQ_SIGNAL_STOP))
        assert len(words) == len(expect), (
            f"DUT Host Notify ACQ length mismatch: got={len(words)} "
            f"exp={len(expect)} words={[hex(w) for w in words]}"
        )

        # Target-address leg — unconditional: a START word must be present and
        # must carry this DUT target's own address with the R/W bit masked.
        start_words = [w for w in words if acq_signal(w) == I2C_ACQ_SIGNAL_START]
        assert start_words, (
            "DUT Host Notify: no START word in ACQDATA, so the target address "
            f"the DUT decoded is unobservable; words={[hex(w) for w in words]}"
        )
        assert (acq_abyte(start_words[0]) & 0xFE) == (_HOST_ADDR << 1), (
            "DUT Host Notify address ACQ mismatch: got "
            f"0x{acq_abyte(start_words[0]):02X} exp 0x{_HOST_ADDR << 1:02X}"
        )

        # Position-by-position compare of the whole frame (payload included).
        for i, exp_word in enumerate(expect[:-1]):
            got = words[i]
            if acq_abyte(got) != acq_abyte(exp_word) or acq_signal(got) != acq_signal(exp_word):
                raise AssertionError(
                    f"DUT Host Notify ACQ[{i}] mismatch got=0x{got:04x} "
                    f"exp=0x{exp_word:04x} "
                    f"words={[hex(w) for w in words]}"
                )
        assert acq_signal(words[-1]) == I2C_ACQ_SIGNAL_STOP, (
            f"DUT Host Notify: frame does not end in STOP; last word "
            f"0x{words[-1]:04x} words={[hex(w) for w in words]}"
        )

        data_bytes = [acq_abyte(w) for w in words if acq_signal(w) == I2C_ACQ_SIGNAL_NONE]
        self.observed_bytes = bytes(data_bytes)

        await self.csr_write("I2C0_CTRL_DISABLE", I2C0_CTRL, 0)
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, cg)
        self.dut_host_notify_ok = True
        cocotb.log.info(
            "CHK-SMBUS-HOSTNOTIFY-FRAME: VIP master -> DUT I2C0 target "
            "@0x%02X; ACQ frame START/0x%02X + payload=%s + STOP "
            "(exp payload=%s, VIP drove=%s)",
            _HOST_ADDR,
            acq_abyte(start_words[0]),
            self.observed_bytes.hex(),
            expected_payload.hex(),
            payload.hex(),
        )
