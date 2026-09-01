# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Three host/target phases on I2C0/1/2; one pair enabled per phase. Requires +smc_i2c_shared_bus."""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_HOSTIDLE,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
    acq_abyte,
    acq_signal,
    pack_acq,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_PHASES: list[tuple[int, int, int, list[int]]] = [
    (0, 1, 0x30, [0xAA, 0xBB, 0xCC, 0xDD]),
    (1, 2, 0x31, [0x11, 0x22, 0x33, 0x44]),
    (2, 0, 0x32, [0x55, 0x66, 0x77, 0x88]),
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


class smc_i2c_p0_multictrl_test_seq(SmcCsrSeq):
    """Three-phase shared-bus write + ACQ verify across I2C0/1/2."""

    def __init__(self, name: str = "smc_i2c_p0_multictrl_test_seq") -> None:
        super().__init__(name)
        self.phases_ok: list[bool] = [False, False, False]
        self.acq_words_by_phase: list[list[int]] = [[], [], []]

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

    async def _disconnect_all(self) -> None:
        for idx in (0, 1, 2):
            wrap = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)
            await self.csr_write(f"I2C{idx}_WRAP_OFF", wrap, 0)
            await self.csr_write(
                f"I2C{idx}_CTRL_OFF",
                self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", idx),
                0,
            )

    async def _wait_hostidle(self, host: int, label: str) -> None:
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", host)
        status = 0
        left_idle = False
        for _ in range(200):
            status = await self.csr_read(f"{label}_BUSY", status_addr)
            if not (status & I2C_STATUS_HOSTIDLE):
                left_idle = True
                break
            await Timer(1, units="us")
        if not left_idle:
            raise AssertionError(f"{label}: I2C{host} never left hostidle (STATUS=0x{status:08x})")
        for _ in range(400):
            status = await self.csr_read(f"{label}_STATUS", status_addr)
            if status & I2C_STATUS_HOSTIDLE:
                return
            await Timer(10, units="us")
        raise AssertionError(f"{label}: I2C{host} stuck busy (STATUS=0x{status:08x})")

    async def _drain_acq_until_stop(self, tgt: int) -> list[int]:
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", tgt)
        acq_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR", tgt)
        got: list[int] = []
        saw_stop = False
        for _ in range(4000):
            status = await self.csr_read(f"I2C{tgt}_STATUS_ACQ", status_addr)
            if status & I2C_STATUS_ACQEMPTY:
                if saw_stop:
                    return got
                await Timer(10, units="us")
                continue
            word = await self.csr_read(f"I2C{tgt}_ACQDATA", acq_addr)
            got.append(int(word) & 0xFFFF)
            if acq_signal(word) == I2C_ACQ_SIGNAL_STOP:
                saw_stop = True
        if not saw_stop:
            raise AssertionError(
                f"I2C{tgt} ACQ: no STOP before drain timeout; words={[hex(w) for w in got]}"
            )
        return got

    async def _run_phase(
        self, phase: int, host: int, tgt: int, addr: int, payload: list[int]
    ) -> None:
        label = f"P{phase}_I2C{host}->I2C{tgt}"
        await self._disconnect_all()

        wrap_t = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", tgt)
        await self.csr_write(f"{label}_TGT_WRAP", wrap_t, I2C_WRAP_CTRL_TARGET)
        await self._program_timing(tgt)
        await self.csr_write(
            f"{label}_TARGET_ID",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", tgt),
            _target_id(addr),
        )
        await self.csr_write(
            f"{label}_TGT_FIFO",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", tgt),
            I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self.csr_write(
            f"{label}_TGT_CTRL",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", tgt),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

        wrap_h = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", host)
        await self.csr_write(f"{label}_HOST_WRAP", wrap_h, I2C_WRAP_CTRL_HOST)
        await self._program_timing(host)
        await self.csr_write(
            f"{label}_OVRD",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", host),
            0,
        )
        await self.csr_write(
            f"{label}_HOST_FIFO",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", host),
            I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self.csr_write(
            f"{label}_CEVENTS",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR", host),
            I2C_CONTROLLER_EVENTS_ALL,
        )
        await self.csr_write(
            f"{label}_HOST_CTRL",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", host),
            I2C_CTRL_ENABLEHOST,
        )

        fdata = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", host)
        addr_w = (addr << 1) | 0
        await self.csr_write(f"{label}_FDATA_START", fdata, I2C_FDATA_START | addr_w)
        for i, byte in enumerate(payload[:-1]):
            await self.csr_write(f"{label}_FDATA_{i}", fdata, byte)
        await self.csr_write(f"{label}_FDATA_STOP", fdata, I2C_FDATA_STOP | payload[-1])

        await self._wait_hostidle(host, label)
        words = await self._drain_acq_until_stop(tgt)
        self.acq_words_by_phase[phase] = words

        expect = [pack_acq(addr_w, I2C_ACQ_SIGNAL_START)]
        expect.extend(pack_acq(b, I2C_ACQ_SIGNAL_NONE) for b in payload)
        expect.append(pack_acq(0, I2C_ACQ_SIGNAL_STOP))
        if len(words) < len(expect):
            raise AssertionError(
                f"{label}: ACQ too short got={len(words)} words={[hex(w) for w in words]}"
            )
        for i, exp in enumerate(expect[:-1]):
            got = words[i]
            if acq_abyte(got) != acq_abyte(exp) or acq_signal(got) != acq_signal(exp):
                raise AssertionError(f"{label}: ACQ[{i}] mismatch got=0x{got:x} exp=0x{exp:x}")
        if acq_signal(words[len(expect) - 1]) != I2C_ACQ_SIGNAL_STOP:
            raise AssertionError(f"{label}: missing STOP SIGNAL at ACQ[{len(expect) - 1}]")

        cocotb.log.info(
            "CHK-I2C-P0-MULTICTRL-P%d: I2C%d→I2C%d @0x%02x payload=%s ACQ=%s",
            phase,
            host,
            tgt,
            addr,
            [f"{b:02x}" for b in payload],
            [hex(w) for w in words[: len(expect)]],
        )
        self.phases_ok[phase] = True

    async def body(self) -> None:
        if "smc_i2c_shared_bus" not in cocotb.plusargs:
            raise AssertionError(
                "smc_i2c_p0_multictrl_test requires +smc_i2c_shared_bus "
                "(tb_top must short I2C0/I2C1/I2C2 OD pads)"
            )

        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)

        for phase, (host, tgt, addr, payload) in enumerate(_PHASES):
            await self._run_phase(phase, host, tgt, addr, payload)

        await self._disconnect_all()
        if not all(self.phases_ok):
            raise AssertionError(f"multictrl phases incomplete: {self.phases_ok}")
        cocotb.log.info(
            "CHK-I2C-P0-MULTICTRL: all 3 phases PASS phases_ok=%s",
            self.phases_ok,
        )
