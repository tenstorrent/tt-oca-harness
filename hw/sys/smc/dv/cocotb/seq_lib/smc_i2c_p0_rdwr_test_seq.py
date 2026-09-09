# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 host to I2C1 target. Requires +smc_i2c_shared_bus."""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_HOSTIDLE,
    I2C_STATUS_RXEMPTY,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
    acq_abyte,
    acq_signal,
    pack_acq,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_TARGET_ADDR = 0x10
# Distinct bytes so an order swap fails the ACQ compare.
_REG_ADDR = 0x5A
_DATA_LO = 0xA5
_DATA_HI = 0x3C
# Read-leg payload. Distinct from every write byte above so a stale FIFO entry
# or a mirrored write byte cannot satisfy the read compare.
_READ_BYTE = 0xC3


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


def _target_id(address0: int, mask0: int = 0x7F) -> int:
    return (address0 & 0x7F) | ((mask0 & 0x7F) << 7)


class smc_i2c_p0_rdwr_test_seq(SmcCsrSeq):
    """I2C0 controller write → I2C1 target ACQ capture, then I2C0 read back."""

    def __init__(self, name: str = "smc_i2c_p0_rdwr_test_seq") -> None:
        super().__init__(name)
        self.accesses: int = 0
        self.acq_words: list[int] = []
        self.transfer_ok: bool = False
        self.read_ok: bool = False

    def _idx_addr(self, symbol: str, idx: int) -> int:
        return smc_indexed_addr(symbol, idx)

    async def _program_timing(self, idx: int) -> None:
        await self.csr_write(
            f"I2C{idx}_TIMING0",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR", idx),
            _pack_timing0(0x1A, 0x32),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING1",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR", idx),
            _pack_timing1(2, 2),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING2",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR", idx),
            _pack_timing2(5, 4),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING3",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR", idx),
            _pack_timing3(2, 5),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING4",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR", idx),
            _pack_timing4(4, 5),
        )

    async def _wait_hostidle(self, label: str) -> None:
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", 0)
        status = 0
        left_idle = False
        for _ in range(200):
            status = await self.csr_read(f"{label}_BUSY", status_addr)
            if not (status & I2C_STATUS_HOSTIDLE):
                left_idle = True
                break
            await Timer(1, units="us")
        if not left_idle:
            raise AssertionError(f"{label}: I2C0 host never left hostidle (STATUS=0x{status:08x})")
        for _ in range(400):
            status = await self.csr_read(f"{label}_STATUS", status_addr)
            if status & I2C_STATUS_HOSTIDLE:
                return
            await Timer(10, units="us")
        raise AssertionError(f"{label}: I2C0 host stuck busy (STATUS=0x{status:08x})")

    async def _wait_rx_byte(self, label: str, idx: int) -> int:
        """Bounded poll of host RX; expiry fails."""
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        rdata_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_RDATA_BASE_ADDR", idx)
        status = 0
        for _ in range(400):
            status = await self.csr_read(f"{label}_RX", status_addr)
            if not (status & I2C_STATUS_RXEMPTY):
                return int(await self.csr_read(f"{label}_RD", rdata_addr)) & 0xFF
            await Timer(5, units="us")
        raise AssertionError(f"{label}: I2C{idx} RX timeout STATUS=0x{status:08x}")

    async def _drain_acq_until_stop(self, idx: int) -> list[int]:
        """Drain ACQ until a STOP SIGNAL entry appears."""
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        acq_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR", idx)
        got: list[int] = []
        saw_stop = False
        for _ in range(4000):
            status = await self.csr_read(f"I2C{idx}_STATUS_ACQ", status_addr)
            if status & I2C_STATUS_ACQEMPTY:
                if saw_stop:
                    return got
                await Timer(10, units="us")
                continue
            word = await self.csr_read(f"I2C{idx}_ACQDATA", acq_addr)
            got.append(int(word) & 0xFFFF)
            if acq_signal(word) == I2C_ACQ_SIGNAL_STOP:
                saw_stop = True
        if not saw_stop:
            raise AssertionError(
                f"I2C{idx} ACQ: no STOP SIGNAL before drain timeout; words={[hex(w) for w in got]}"
            )
        return got

    async def body(self) -> None:
        if "smc_i2c_shared_bus" not in cocotb.plusargs:
            raise AssertionError(
                "smc_i2c_p0_rdwr_test requires +smc_i2c_shared_bus "
                "(tb_top must short I2C0/I2C1 OD pads)"
            )

        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        ungated = cg & ~I2C_CG_EN
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, ungated)

        wrap1 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 1)
        await self.csr_write("I2C1_WRAP_TARGET", wrap1, I2C_WRAP_CTRL_TARGET)
        await self._program_timing(1)
        await self.csr_write(
            "I2C1_TARGET_ID",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", 1),
            _target_id(_TARGET_ADDR),
        )
        await self.csr_write(
            "I2C1_FIFO_RST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 1),
            I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self.csr_write(
            "I2C1_CTRL_TARGET",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 1),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

        wrap0 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0)
        await self.csr_write("I2C0_WRAP_HOST", wrap0, I2C_WRAP_CTRL_HOST)
        await self._program_timing(0)
        await self.csr_write(
            "I2C0_OVRD_OFF",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", 0),
            0,
        )
        await self.csr_write(
            "I2C0_FIFO_RST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0),
            I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self.csr_write(
            "I2C0_CEVENTS_CLR",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR", 0),
            0xF,
        )
        await self.csr_write(
            "I2C0_ENABLEHOST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0),
            I2C_CTRL_ENABLEHOST,
        )

        fdata = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", 0)
        addr_w = (_TARGET_ADDR << 1) | 0
        await self.csr_write("I2C0_FDATA_START", fdata, I2C_FDATA_START | addr_w)
        await self.csr_write("I2C0_FDATA_REG", fdata, _REG_ADDR)
        await self.csr_write("I2C0_FDATA_LO", fdata, _DATA_LO)
        await self.csr_write("I2C0_FDATA_HI_STOP", fdata, I2C_FDATA_STOP | _DATA_HI)

        await self._wait_hostidle("I2C0_P0_WRITE")
        self.acq_words = await self._drain_acq_until_stop(1)

        expect = [
            pack_acq(addr_w, I2C_ACQ_SIGNAL_START),
            pack_acq(_REG_ADDR, I2C_ACQ_SIGNAL_NONE),
            pack_acq(_DATA_LO, I2C_ACQ_SIGNAL_NONE),
            pack_acq(_DATA_HI, I2C_ACQ_SIGNAL_NONE),
            pack_acq(0, I2C_ACQ_SIGNAL_STOP),
        ]
        # STOP ABYTE is implementation-defined; gate SIGNAL==STOP and prior frames.
        if len(self.acq_words) < 5:
            raise AssertionError(
                f"I2C1 ACQ too short: got {len(self.acq_words)} "
                f"words={[hex(w) for w in self.acq_words]}"
            )
        for i, exp in enumerate(expect[:-1]):
            got = self.acq_words[i]
            if acq_abyte(got) != acq_abyte(exp) or acq_signal(got) != acq_signal(exp):
                raise AssertionError(
                    f"I2C1 ACQ[{i}] mismatch: got=0x{got:x} "
                    f"(abyte=0x{acq_abyte(got):02x} sig={acq_signal(got)}) "
                    f"expected=0x{exp:x} "
                    f"(abyte=0x{acq_abyte(exp):02x} sig={acq_signal(exp)})"
                )
        stop_word = self.acq_words[4]
        if acq_signal(stop_word) != I2C_ACQ_SIGNAL_STOP:
            raise AssertionError(
                f"I2C1 ACQ[4] missing STOP SIGNAL: got=0x{stop_word:x} sig={acq_signal(stop_word)}"
            )

        cocotb.log.info(
            "CHK-I2C-P0-RDWR-WRITE: I2C0→I2C1 ACQ frames match "
            "START+addr + [%02x,%02x,%02x] + STOP words=%s",
            _REG_ADDR,
            _DATA_LO,
            _DATA_HI,
            [hex(w) for w in self.acq_words[:5]],
        )
        self.transfer_ok = True

        # ---- Read leg: I2C0 host reads a byte back out of the I2C1 target ----
        #
        # The write proof above is only half of what this testcase claims: the
        # read direction needs its own frame and its own compare, or a DUT with
        # a wholly broken read path passes. Preload the target's TX FIFO before
        # the read frame is queued so the target does not have to clock-stretch,
        # which is the same ordering smc_i2c_p0_conti_test_seq uses.
        txdata1 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR", 1)
        fifo0 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0)
        fifo1 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 1)
        addr_r = (_TARGET_ADDR << 1) | 1

        # Clear the host RX/FMT and the target ACQ/TX so nothing from the write
        # leg can be mistaken for the read result.
        await self.csr_write("I2C0_FIFO_RST_RD", fifo0, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write("I2C1_FIFO_RST_RD", fifo1, I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST)
        await self.csr_write("I2C1_TXDATA", txdata1, _READ_BYTE)
        await self.csr_write("I2C0_FDATA_START_RD", fdata, I2C_FDATA_START | addr_r)
        await self.csr_write("I2C0_FDATA_READB_STOP", fdata, I2C_FDATA_READB | I2C_FDATA_STOP | 1)
        await self._wait_hostidle("I2C0_P0_READ")

        got_byte = await self._wait_rx_byte("I2C0_P0_READ", 0)
        if got_byte != _READ_BYTE:
            raise AssertionError(
                f"I2C0 read leg: RDATA got 0x{got_byte:02x}, expected the byte "
                f"preloaded into the I2C1 target TX FIFO 0x{_READ_BYTE:02x}"
            )
        cocotb.log.info(
            "CHK-I2C-P0-RDWR-READ: I2C0 host read 0x%02X back from the I2C1 "
            "target over the shared pads (addr_r=0x%02X)",
            got_byte,
            addr_r,
        )
        self.read_ok = True
