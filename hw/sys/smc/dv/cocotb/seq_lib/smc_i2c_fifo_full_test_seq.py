# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C FIFO FULL/EMPTY proofs on real FIFO occupancy.

FMT and TX are filled by CSR pushes until FULL, then reset and re-checked.
RX and ACQ cannot be filled from CSRs at all -- they only take bus traffic --
so each of them gets a same-run positive control on ``tb_i2c0_*``:

* RX: DUT I2C0 as host reads bytes out of the VIP EEPROM slave, and the leg
  requires ``RXLVL`` to reach the byte count before ``RXRST`` is applied.
* ACQ: DUT I2C0 as target accepts a VIP-master write, and the leg requires
  ``ACQLVL`` to reach the acquired-word count before ``ACQRST`` is applied.

Without those the EMPTY/LVL==0 compares after the reset would be satisfied by
the FIFO's own reset state, i.e. by a reset that did nothing
(``[NEGATIVE-NEEDS-POSITIVE-CONTROL]``).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_FMTRST,
    I2C_FIFO_CTRL_RXRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_HOST_FIFO_STATUS_RXLVL_BM,
    I2C_HOST_FIFO_STATUS_RXLVL_BP,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_ACQFULL,
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_FMTFULL,
    I2C_STATUS_RXEMPTY,
    I2C_STATUS_RXFULL,
    I2C_STATUS_TXEMPTY,
    I2C_STATUS_TXFULL,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
)

try:
    from .smc_i2c_protocol_vip import SmcI2cEepromSlave, SmcI2cMasterVip

    _I2C_VIP_AVAILABLE = True
except Exception:  # noqa: BLE001 - optional at import time
    SmcI2cEepromSlave = None  # type: ignore[assignment]
    SmcI2cMasterVip = None  # type: ignore[assignment]
    _I2C_VIP_AVAILABLE = False

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

# SPEC depths, hw/ip/i2c/doc/interface.adoc:16 and :18 --
#   "CTRL_TX_FIFO_DEPTH |64 |Controller mode TX FIFO depth (entries)"
#   "TGT_TX_FIFO_DEPTH  |64 |Target mode TX FIFO depth (entries)"
# The controller-mode TX FIFO is the FMT FIFO written through FDATA.
_FMT_DEPTH = 64
_TX_DEPTH = 64
_TARGET_ADDR = 0x10
_EEPROM_ADDR = 0x50
#: Bytes the DUT host reads out of the VIP EEPROM to fill the RX FIFO.
_RX_FILL_BYTES = 4
_EEPROM_CONTENT = bytes([0x5A, 0xA5, 0x3C, 0xC3])
#: Bytes the VIP master writes to the DUT target to fill the ACQ FIFO.
_ACQ_FILL_PAYLOAD = bytes([0x11, 0x22, 0x33])
#: START + 3 data + STOP with ACQ_START_STOP_EN set.
_ACQ_FILL_WORDS = len(_ACQ_FILL_PAYLOAD) + 2
_STATUS_POLL_ITERS = 64
_STATUS_POLL_STEP_NS = 100
# Bus-traffic fill bound. The ACQ frame (100 kHz, 3 bytes) needs well under
# 1 ms of sim time and the RX read completes sooner, so 400 x 10 us = 4 ms is
# generous enough that a real transfer is never cut short and tight enough that
# a FIFO that never fills fails quickly.
_BUS_POLL_ITERS = 400
_BUS_POLL_STEP_US = 10


def _rx_lvl(status: int) -> int:
    return (int(status) & I2C_HOST_FIFO_STATUS_RXLVL_BM) >> (I2C_HOST_FIFO_STATUS_RXLVL_BP)


def _acq_lvl(status: int) -> int:
    return (int(status) & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> (I2C_TARGET_FIFO_STATUS_ACQLVL_BP)


def _target_id(address0: int, mask0: int = 0x7F) -> int:
    return (address0 & 0x7F) | ((mask0 & 0x7F) << 7)


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


class smc_i2c_fifo_full_test_seq(SmcCsrSeq):
    """FMT/TX full+empty and RX/ACQ empty STATUS proofs."""

    def __init__(self, name: str = "smc_i2c_fifo_full_test_seq") -> None:
        super().__init__(name)
        self.fmt_ok: bool = False
        self.rx_ok: bool = False
        self.tx_ok: bool = False
        self.acq_ok: bool = False
        #: Push count at which FMTFULL / TXFULL first asserted (SPEC depth).
        self.fmt_full_at: int = -1
        self.tx_full_at: int = -1
        #: Peak occupancy observed before the RX / ACQ reset (positive control).
        self.rx_lvl_filled: int = -1
        self.acq_lvl_filled: int = -1
        self._eeprom = None

    def _addr(self, symbol: str, idx: int) -> int:
        return smc_indexed_addr(symbol, idx)

    async def _program_timing(self, idx: int) -> None:
        await self.csr_write(
            f"I2C{idx}_TIMING0",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR", idx),
            _pack_timing0(0x1A, 0x32),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING1",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR", idx),
            _pack_timing1(2, 2),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING2",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR", idx),
            _pack_timing2(5, 4),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING3",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR", idx),
            _pack_timing3(2, 5),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING4",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR", idx),
            _pack_timing4(4, 5),
        )

    async def _await_lvl_at_least(self, label: str, lvl_a: int, lvl_fn, want: int) -> int:
        """Bounded wait for a FIFO level to reach ``want``; expiry raises."""
        lvl = -1
        for i in range(_BUS_POLL_ITERS):
            lvl = lvl_fn(await self.csr_read(f"{label}_{i}", lvl_a))
            if lvl >= want:
                return lvl
            await Timer(_BUS_POLL_STEP_US, units="us")
        raise AssertionError(
            f"{label}: FIFO level reached only {lvl}, expected >= {want} -- "
            f"the positive control never filled the FIFO, so a following "
            f"EMPTY compare would prove nothing"
        )

    async def _await_status(
        self,
        label: str,
        status_a: int,
        *,
        want_set: int = 0,
        want_clear: int = 0,
    ) -> int:
        """Poll STATUS until want_set bits are 1 and want_clear bits are 0."""
        st = 0
        for i in range(_STATUS_POLL_ITERS):
            st = await self.csr_read(f"{label}_{i}", status_a)
            if (st & want_set) == want_set and (st & want_clear) == 0:
                return st
            await Timer(_STATUS_POLL_STEP_NS, units="ns")
        raise AssertionError(
            f"{label} timeout STATUS=0x{st:08x} want_set=0x{want_set:x} want_clear=0x{want_clear:x}"
        )

    async def _await_lvl_zero(self, label: str, lvl_a: int, lvl_fn) -> None:
        lvl = -1
        for i in range(_STATUS_POLL_ITERS):
            lvl = lvl_fn(await self.csr_read(f"{label}_{i}", lvl_a))
            if lvl == 0:
                return
            await Timer(_STATUS_POLL_STEP_NS, units="ns")
        raise AssertionError(f"{label} level stuck at {lvl}")

    async def _test_fmt(self) -> None:
        idx = 0
        status_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        fifo_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", idx)
        fdata_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", idx)

        await self.csr_write("FMT_RST", fifo_a, I2C_FIFO_CTRL_FMTRST)
        await self._await_status(
            "FMT_EMPTY0",
            status_a,
            want_set=I2C_STATUS_FMTEMPTY,
            want_clear=I2C_STATUS_FMTFULL,
        )

        for i in range(_FMT_DEPTH + 10):
            st = await self.csr_read(f"FMT_FILL_ST_{i}", status_a)
            if st & I2C_STATUS_FMTFULL:
                self.fmt_full_at = i
                break
            await self.csr_write(f"FMT_FDATA_{i}", fdata_a, 0xAA + (i & 0xFF))
        else:
            raise AssertionError("FMTFULL never set while filling FDATA")

        # SPEC depth compare: hw/ip/i2c/doc/interface.adoc:16 gives
        # CTRL_TX_FIFO_DEPTH = 64 for the controller-mode (FMT) FIFO, so FULL
        # must assert on the 64th entry -- not merely "eventually".
        assert self.fmt_full_at == _FMT_DEPTH, (
            f"FMTFULL asserted after {self.fmt_full_at} FDATA pushes, SPEC "
            f"CTRL_TX_FIFO_DEPTH is {_FMT_DEPTH} "
            f"(hw/ip/i2c/doc/interface.adoc:16)"
        )

        await self._await_status("FMT_FULL", status_a, want_set=I2C_STATUS_FMTFULL)

        await self.csr_write("FMT_RST2", fifo_a, I2C_FIFO_CTRL_FMTRST)
        await self._await_status(
            "FMT_EMPTY1",
            status_a,
            want_set=I2C_STATUS_FMTEMPTY,
            want_clear=I2C_STATUS_FMTFULL,
        )
        cocotb.log.info(
            "CHK-I2C-FIFO-FULL-FMT: FMTFULL at push %d (SPEC "
            "CTRL_TX_FIFO_DEPTH=%d) then FMTEMPTY after FMTRST",
            self.fmt_full_at,
            _FMT_DEPTH,
        )
        self.fmt_ok = True

    async def _test_rx_empty(self) -> None:
        """RXRST clears a FIFO that this leg first proved to be non-empty.

        Positive control: DUT I2C0 in controller mode reads
        ``_RX_FILL_BYTES`` bytes out of the VIP EEPROM slave on ``tb_i2c0_*``,
        and the leg requires RXLVL to reach that count (bounded, expiry
        raises) BEFORE RXRST is written.  Without it, RXEMPTY/RXLVL==0 after
        the reset is just the FIFO's reset state and a no-op RXRST passes.
        """
        idx = 0
        status_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        fifo_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", idx)
        fdata_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", idx)
        ovrd_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", idx)
        cevents_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR", idx)
        ctrl_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", idx)
        host_fifo = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR", idx)

        assert _I2C_VIP_AVAILABLE and SmcI2cEepromSlave is not None, (
            "I2C protocol VIP unavailable: the RX leg needs a bus responder to fill the RX FIFO"
        )
        self._eeprom = SmcI2cEepromSlave(addr=_EEPROM_ADDR, name="smc_i2c0_fifo_full_eeprom")
        self._eeprom.write_mem(0, _EEPROM_CONTENT)

        await self.wait_i2c0_lsio_ready("I2C0_FIFO_FULL_RX")
        await self.csr_write("RX_OVRD_OFF", ovrd_a, 0)
        await self._program_timing(idx)
        await self.csr_write("RX_CEVENTS_CLR", cevents_a, I2C_CONTROLLER_EVENTS_ALL)
        await self.csr_write("RX_PRE_RST", fifo_a, I2C_FIFO_CTRL_RXRST)
        await self.csr_write("RX_ENABLEHOST", ctrl_a, I2C_CTRL_ENABLEHOST)

        # START + address|R, then read _RX_FILL_BYTES bytes and NACK/STOP.
        addr_r = (_EEPROM_ADDR << 1) | 1
        await self.csr_write("RX_FDATA_START", fdata_a, I2C_FDATA_START | addr_r)
        await self.csr_write(
            "RX_FDATA_READ",
            fdata_a,
            I2C_FDATA_READB | I2C_FDATA_STOP | (_RX_FILL_BYTES & 0xFF),
        )

        self.rx_lvl_filled = await self._await_lvl_at_least(
            "RX_LVL_FILL", host_fifo, _rx_lvl, _RX_FILL_BYTES
        )
        # The FIFO is demonstrably non-empty right now: RXEMPTY must be clear.
        st_full = await self.csr_read("RX_ST_NONEMPTY", status_a)
        assert not (st_full & I2C_STATUS_RXEMPTY), (
            f"RXLVL={self.rx_lvl_filled} but RXEMPTY still set "
            f"(STATUS=0x{st_full:08x}): the STATUS path does not track "
            f"occupancy, so the post-reset EMPTY compare would prove nothing"
        )
        assert self._eeprom.starts > 0, (
            "RX positive control: the VIP EEPROM responder framed no START on "
            f"tb_i2c0_* (starts={self._eeprom.starts} "
            f"bytes={self._eeprom.bytes}); the RX bytes did not come from a "
            "real bus transfer"
        )

        await self.csr_write("RX_RST", fifo_a, I2C_FIFO_CTRL_RXRST)
        await self._await_status(
            "RX_ST",
            status_a,
            want_set=I2C_STATUS_RXEMPTY,
            want_clear=I2C_STATUS_RXFULL,
        )
        await self._await_lvl_zero("RX_LVL", host_fifo, _rx_lvl)
        await self.csr_write("RX_HOST_DISABLE", ctrl_a, 0)
        cocotb.log.info(
            "CHK-I2C-FIFO-FULL-RX: RXLVL reached %d (>=%d, VIP EEPROM "
            "starts=%d bytes=%d) with RXEMPTY clear, then RXEMPTY set and "
            "RXLVL==0 after RXRST",
            self.rx_lvl_filled,
            _RX_FILL_BYTES,
            self._eeprom.starts,
            self._eeprom.bytes,
        )
        self.rx_ok = True

    async def _test_tx(self) -> None:
        idx = 1
        status_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        fifo_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", idx)
        tx_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR", idx)

        await self.csr_write("TX_RST", fifo_a, I2C_FIFO_CTRL_TXRST)
        await self._await_status(
            "TX_EMPTY0",
            status_a,
            want_set=I2C_STATUS_TXEMPTY,
            want_clear=I2C_STATUS_TXFULL,
        )

        for i in range(_TX_DEPTH + 10):
            st = await self.csr_read(f"TX_FILL_ST_{i}", status_a)
            if st & I2C_STATUS_TXFULL:
                self.tx_full_at = i
                break
            await self.csr_write(f"TX_DATA_{i}", tx_a, 0xBB + (i & 0xFF))
        else:
            raise AssertionError("TXFULL never set while filling TXDATA")

        # SPEC depth compare: hw/ip/i2c/doc/interface.adoc:18 gives
        # TGT_TX_FIFO_DEPTH = 64 for the target-mode TX FIFO.
        assert self.tx_full_at == _TX_DEPTH, (
            f"TXFULL asserted after {self.tx_full_at} TXDATA pushes, SPEC "
            f"TGT_TX_FIFO_DEPTH is {_TX_DEPTH} "
            f"(hw/ip/i2c/doc/interface.adoc:18)"
        )

        await self._await_status("TX_FULL", status_a, want_set=I2C_STATUS_TXFULL)

        await self.csr_write("TX_RST2", fifo_a, I2C_FIFO_CTRL_TXRST)
        await self._await_status(
            "TX_EMPTY1",
            status_a,
            want_set=I2C_STATUS_TXEMPTY,
            want_clear=I2C_STATUS_TXFULL,
        )
        cocotb.log.info(
            "CHK-I2C-FIFO-FULL-TX: TXFULL at push %d (SPEC "
            "TGT_TX_FIFO_DEPTH=%d) then TXEMPTY after TXRST",
            self.tx_full_at,
            _TX_DEPTH,
        )
        self.tx_ok = True

    async def _test_acq_empty(self) -> None:
        """ACQRST clears a FIFO that this leg first proved to be non-empty.

        Positive control: the VIP master writes ``_ACQ_FILL_PAYLOAD`` to the
        DUT I2C0 target on ``tb_i2c0_*``; with ACQ_START_STOP_EN set the frame
        lands as START + data + STOP, and the leg requires ACQLVL to reach
        that word count (bounded, expiry raises) BEFORE ACQRST is written.
        """
        idx = 0
        status_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        fifo_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", idx)
        wrap_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)
        ctrl_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", idx)
        tgtid_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", idx)
        tgt_fifo = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR", idx)

        assert _I2C_VIP_AVAILABLE and SmcI2cMasterVip is not None, (
            "I2C protocol VIP unavailable: the ACQ leg needs a bus master to fill the ACQ FIFO"
        )

        # Re-role I2C0 from controller to target for the acquire path.
        await self.csr_write("ACQ_CTRL_OFF", ctrl_a, 0)
        await self.csr_write("ACQ_WRAP_TGT", wrap_a, I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready("I2C0_FIFO_FULL_ACQ")
        await self.csr_write("ACQ_PRE_RST", fifo_a, I2C_FIFO_CTRL_ACQRST)
        await self.csr_write("ACQ_TARGET_ID", tgtid_a, _target_id(_TARGET_ADDR))
        await self.csr_write(
            "ACQ_CTRL_TGT",
            ctrl_a,
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

        master = SmcI2cMasterVip(speed=100_000, name="smc_i2c0_fifo_full_master")
        await master.write(_TARGET_ADDR, _ACQ_FILL_PAYLOAD)

        self.acq_lvl_filled = await self._await_lvl_at_least(
            "ACQ_LVL_FILL", tgt_fifo, _acq_lvl, _ACQ_FILL_WORDS
        )
        st_full = await self.csr_read("ACQ_ST_NONEMPTY", status_a)
        assert not (st_full & I2C_STATUS_ACQEMPTY), (
            f"ACQLVL={self.acq_lvl_filled} but ACQEMPTY still set "
            f"(STATUS=0x{st_full:08x}): the STATUS path does not track "
            f"occupancy, so the post-reset EMPTY compare would prove nothing"
        )

        await self.csr_write("ACQ_RST", fifo_a, I2C_FIFO_CTRL_ACQRST)
        await self._await_status(
            "ACQ_ST",
            status_a,
            want_set=I2C_STATUS_ACQEMPTY,
            want_clear=I2C_STATUS_ACQFULL,
        )
        await self._await_lvl_zero("ACQ_LVL", tgt_fifo, _acq_lvl)
        cocotb.log.info(
            "CHK-I2C-FIFO-FULL-ACQ: ACQLVL reached %d (>=%d: START + %d data "
            "+ STOP) with ACQEMPTY clear, then ACQEMPTY set and ACQLVL==0 "
            "after ACQRST",
            self.acq_lvl_filled,
            _ACQ_FILL_WORDS,
            len(_ACQ_FILL_PAYLOAD),
        )
        self.acq_ok = True

    async def body(self) -> None:
        cg = await self.csr_read("I2C_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("I2C_UNGATE", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)

        wrap0 = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0)
        wrap1 = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 1)
        await self.csr_write("I2C0_WRAP_HOST", wrap0, I2C_WRAP_CTRL_HOST)
        await self.csr_write("I2C1_WRAP_TGT", wrap1, I2C_WRAP_CTRL_TARGET)

        # Leave ENABLEHOST=0 so FMT fills do not drain onto the bus.
        await self.csr_write(
            "I2C0_CTRL",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0),
            0,
        )
        await self.csr_write(
            "I2C1_TARGET_ID",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", 1),
            _target_id(_TARGET_ADDR),
        )
        await self.csr_write(
            "I2C1_CTRL",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 1),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

        await self._test_fmt()
        await self._test_rx_empty()
        await self._test_tx()
        await self._test_acq_empty()
        assert self.fmt_ok and self.rx_ok and self.tx_ok and self.acq_ok, (
            f"I2C FIFO legs incomplete: fmt={self.fmt_ok} rx={self.rx_ok} "
            f"tx={self.tx_ok} acq={self.acq_ok}"
        )
        cocotb.log.info(
            "CHK-I2C-FIFO-FULL-BASIC: fmt=%s(full@%d) rx=%s(lvl=%d) tx=%s(full@%d) acq=%s(lvl=%d)",
            self.fmt_ok,
            self.fmt_full_at,
            self.rx_ok,
            self.rx_lvl_filled,
            self.tx_ok,
            self.tx_full_at,
            self.acq_ok,
            self.acq_lvl_filled,
        )
