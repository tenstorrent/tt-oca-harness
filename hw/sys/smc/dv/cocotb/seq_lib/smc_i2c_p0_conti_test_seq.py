# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Three I2C1→I2C0 write/read pairs. Requires +smc_i2c_shared_bus."""

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
_PAIRS = [
    ([0x10, 0x11], 0x90),
    ([0x20, 0x21], 0xA0),
    ([0x30, 0x31], 0xB0),
]


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


class smc_i2c_p0_conti_test_seq(SmcCsrSeq):
    """Alternating host write / read pairs with ACQ + RX compares."""

    def __init__(self, name: str = "smc_i2c_p0_conti_test_seq") -> None:
        super().__init__(name)
        self.pairs_ok: int = 0

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
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", 1)
        status = 0
        left_idle = False
        for _ in range(200):
            status = await self.csr_read(f"{label}_BUSY", status_addr)
            if not (status & I2C_STATUS_HOSTIDLE):
                left_idle = True
                break
            await Timer(1, units="us")
        if not left_idle:
            raise AssertionError(f"{label}: host never left idle STATUS=0x{status:08x}")
        for _ in range(400):
            status = await self.csr_read(f"{label}_IDLE", status_addr)
            if status & I2C_STATUS_HOSTIDLE:
                return
            await Timer(10, units="us")
        raise AssertionError(f"{label}: host idle timeout STATUS=0x{status:08x}")

    async def _drain_acq_until_stop(self) -> list[int]:
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", 0)
        acq_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR", 0)
        words: list[int] = []
        for _ in range(32):
            st = await self.csr_read("ACQ_STATUS", status_addr)
            if st & I2C_STATUS_ACQEMPTY:
                await Timer(5, units="us")
                st = await self.csr_read("ACQ_STATUS2", status_addr)
                if st & I2C_STATUS_ACQEMPTY:
                    break
            word = int(await self.csr_read("ACQDATA", acq_addr))
            words.append(word)
            if acq_signal(word) == I2C_ACQ_SIGNAL_STOP:
                break
        return words

    async def _wait_rx_byte(self, label: str) -> int:
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", 1)
        rdata_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_RDATA_BASE_ADDR", 1)
        status = 0
        for _ in range(400):
            status = await self.csr_read(f"{label}_RX", status_addr)
            if not (status & I2C_STATUS_RXEMPTY):
                return int(await self.csr_read(f"{label}_RD", rdata_addr)) & 0xFF
            await Timer(5, units="us")
        raise AssertionError(f"{label}: RX timeout STATUS=0x{status:08x}")

    async def body(self) -> None:
        if "smc_i2c_shared_bus" not in cocotb.plusargs:
            raise AssertionError("smc_i2c_p0_conti_test requires +smc_i2c_shared_bus")

        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)

        wrap0 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0)
        await self.csr_write("I2C0_WRAP_TGT", wrap0, I2C_WRAP_CTRL_TARGET)
        await self._program_timing(0)
        await self.csr_write(
            "I2C0_TARGET_ID",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", 0),
            _target_id(_TARGET_ADDR),
        )
        await self.csr_write(
            "I2C0_CTRL_TGT",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

        wrap1 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 1)
        await self.csr_write("I2C1_WRAP_HOST", wrap1, I2C_WRAP_CTRL_HOST)
        await self._program_timing(1)
        await self.csr_write(
            "I2C1_OVRD",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", 1),
            0,
        )
        await self.csr_write(
            "I2C1_CTRL_HOST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 1),
            I2C_CTRL_ENABLEHOST,
        )

        fdata = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", 1)
        txdata = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR", 0)
        fifo0 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0)
        fifo1 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 1)
        addr_w = (_TARGET_ADDR << 1) | 0
        addr_r = (_TARGET_ADDR << 1) | 1

        for i, (wbytes, rbyte) in enumerate(_PAIRS):
            label = f"P{i}"
            await self.csr_write(
                f"{label}_FIFO0",
                fifo0,
                I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST,
            )
            await self.csr_write(f"{label}_FIFO1", fifo1, I2C_FIFO_CTRL_RXRST_FMTRST)

            # Write leg
            await self.csr_write(f"{label}_W_START", fdata, I2C_FDATA_START | addr_w)
            await self.csr_write(f"{label}_W_B0", fdata, wbytes[0])
            await self.csr_write(f"{label}_W_STOP", fdata, I2C_FDATA_STOP | wbytes[1])
            await self._wait_hostidle(f"{label}_W")
            words = await self._drain_acq_until_stop()
            expect = [pack_acq(addr_w, I2C_ACQ_SIGNAL_START)]
            expect.extend(pack_acq(b, I2C_ACQ_SIGNAL_NONE) for b in wbytes)
            expect.append(pack_acq(0, I2C_ACQ_SIGNAL_STOP))
            if len(words) < len(expect):
                raise AssertionError(f"{label} write ACQ too short got={[hex(w) for w in words]}")
            for i, exp in enumerate(expect[:-1]):
                got = words[i]
                if acq_abyte(got) != acq_abyte(exp) or acq_signal(got) != acq_signal(exp):
                    raise AssertionError(
                        f"{label} write ACQ[{i}] mismatch got=0x{got:x} exp=0x{exp:x}"
                    )
            if acq_signal(words[len(expect) - 1]) != I2C_ACQ_SIGNAL_STOP:
                raise AssertionError(
                    f"{label} write ACQ missing STOP got={[hex(w) for w in words]}"
                )

            # Read leg — preload TX before FMT so no long stretch
            await self.csr_write(f"{label}_TX", txdata, rbyte)
            await self.csr_write(f"{label}_R_START", fdata, I2C_FDATA_START | addr_r)
            await self.csr_write(
                f"{label}_R_READB",
                fdata,
                I2C_FDATA_READB | I2C_FDATA_STOP | 1,
            )
            await self._wait_hostidle(f"{label}_R")
            got = await self._wait_rx_byte(f"{label}_R")
            if got != rbyte:
                raise AssertionError(f"{label} RX got 0x{got:02x} expect 0x{rbyte:02x}")
            self.pairs_ok += 1
            cocotb.log.info("CHK-I2C-P0-CONTI-%s: write ACQ ok RX=0x%02x", label, got)

        cocotb.log.info("CHK-I2C-P0-CONTI: %d alternating pairs PASS", self.pairs_ok)
        await self.csr_write(
            "I2C0_CTRL_OFF",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0),
            0,
        )
        await self.csr_write(
            "I2C1_CTRL_OFF",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 1),
            0,
        )
