# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C1 StretchTimeout while the I2C0 target holds SCL. Requires +smc_i2c_shared_bus.

Three legs on the shared bus, in this order, so the timeout is a measurement of
the target's stretch and not of a dead bus:

* Allow leg (positive control): the I2C0 target's TX FIFO is preloaded, the
  I2C1 host reads one byte, and the byte comes back through I2C1 RDATA while
  I2C0's ACQ FIFO shows the START word for the read address. The same bus,
  the same two controllers and the same read frame complete.
* Timeout leg: the I2C0 TX FIFO is emptied and the same read is issued. The
  target stretches SCL with nothing to send (I2C0 raises its own
  ``INTR_STATE.TX_STRETCH``), and the host's ``INTR_STATE.STRETCH_TIMEOUT``
  fires after the programmed count.
* Release leg: a byte written to I2C0 TXDATA ends the stretch, the host leaves
  its busy state and the byte arrives through RDATA, so the stall was the
  target's stretch and not a wedged host.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_START,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_CTRL_MULTI_CONTROLLER_MONITOR_EN,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_HOST_FIFO_CONFIG_FMT_THRESH,
    I2C_HOST_FIFO_CONFIG_RX_THRESH,
    I2C_HOST_FIFO_STATUS_FMTLVL,
    I2C_HOST_TIMEOUT_CTRL_VAL,
    I2C_INTR_ENABLE_STRETCH_TIMEOUT,
    I2C_INTR_STATE_STRETCH_TIMEOUT,
    I2C_INTR_STATE_TX_STRETCH,
    I2C_NACK_HANDLER_TIMEOUT_EN,
    I2C_NACK_HANDLER_TIMEOUT_VAL,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_HOSTIDLE,
    I2C_STATUS_RXEMPTY,
    I2C_TARGET_TIMEOUT_CTRL_EN,
    I2C_TARGET_TIMEOUT_CTRL_VAL,
    I2C_TIMEOUT_CTRL_EN,
    I2C_TIMEOUT_CTRL_VAL,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
    acq_abyte,
    acq_signal,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_TARGET_ADDR = 0x10
_STRETCH_TIMEOUT_CYCLES = 2000
# Bytes the target returns on the allow leg and after the stretch is released;
# distinct from each other and from the address byte so a stale FIFO entry
# cannot satisfy either compare.
_ALLOW_BYTE = 0xC3
_RELEASE_BYTE = 0x3C
_HOSTIDLE_POLLS = 400
_RX_POLLS = 400
_ACQ_POLLS = 400


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


class smc_i2c_p0_timeout_test_seq(SmcCsrSeq):
    """Stretch-timeout IRQ when target TX is empty during host READ."""

    def __init__(self, name: str = "smc_i2c_p0_timeout_test_seq") -> None:
        super().__init__(name)
        self.stretch_ok: bool = False
        self.allow_ok: bool = False
        self.release_ok: bool = False

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

    async def _wait_host_busy_then_idle(self, label: str, idx: int) -> None:
        """The host must leave HOSTIDLE for the frame and come back to it; expiry fails."""
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        status = 0
        for _ in range(_HOSTIDLE_POLLS):
            status = await self.csr_read(f"{label}_BUSY", status_addr)
            if not (status & I2C_STATUS_HOSTIDLE):
                break
            await Timer(1, unit="us")
        else:
            raise AssertionError(
                f"{label}: I2C{idx} host never left hostidle (STATUS=0x{status:08x})"
            )
        for _ in range(_HOSTIDLE_POLLS):
            status = await self.csr_read(f"{label}_STATUS", status_addr)
            if status & I2C_STATUS_HOSTIDLE:
                return
            await Timer(10, unit="us")
        raise AssertionError(f"{label}: I2C{idx} host stuck busy (STATUS=0x{status:08x})")

    async def _wait_rx_byte(self, label: str, idx: int) -> int:
        """Bounded poll of the host RX FIFO; expiry fails."""
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        rdata_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_RDATA_BASE_ADDR", idx)
        status = 0
        for _ in range(_RX_POLLS):
            status = await self.csr_read(f"{label}_RX", status_addr)
            if not (status & I2C_STATUS_RXEMPTY):
                return int(await self.csr_read(f"{label}_RD", rdata_addr)) & 0xFF
            await Timer(5, unit="us")
        raise AssertionError(f"{label}: I2C{idx} RX timeout STATUS=0x{status:08x}")

    async def _acq_start_word(self, label: str, idx: int) -> int:
        """Drain the target ACQ FIFO and return the first START word; none within the bound fails."""
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        acq_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR", idx)
        words: list[int] = []
        for _ in range(_ACQ_POLLS):
            status = await self.csr_read(f"{label}_STATUS_ACQ", status_addr)
            if status & I2C_STATUS_ACQEMPTY:
                await Timer(5, unit="us")
                continue
            word = int(await self.csr_read(f"{label}_ACQDATA", acq_addr)) & 0xFFFF
            words.append(word)
            if acq_signal(word) == I2C_ACQ_SIGNAL_START:
                return word
        raise AssertionError(
            f"{label}: I2C{idx} ACQ holds no START word; drained {[hex(w) for w in words]}"
        )

    async def _issue_read(self, label: str) -> None:
        fdata = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", 1)
        addr_r = (_TARGET_ADDR << 1) | 1
        await self.csr_write(f"{label}_FDATA_START", fdata, I2C_FDATA_START | addr_r)
        await self.csr_write(
            f"{label}_FDATA_READB_STOP",
            fdata,
            I2C_FDATA_READB | I2C_FDATA_STOP | 1,
        )

    async def body(self) -> None:
        if "smc_i2c_shared_bus" not in cocotb.plusargs:
            raise AssertionError("smc_i2c_p0_timeout_test requires +smc_i2c_shared_bus")

        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        # The I2C0 pads must track the open-drain bus before either controller
        # can see the other; the wait raises if the sense path never follows.
        await self.wait_i2c0_lsio_ready("I2C0_LSIO")

        # I2C0 target, TX empty
        wrap0 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0)
        await self.csr_write("I2C0_WRAP_TGT", wrap0, I2C_WRAP_CTRL_TARGET)
        await self._program_timing(0)
        await self.csr_write(
            "I2C0_TARGET_ID",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", 0),
            _target_id(_TARGET_ADDR),
        )
        await self.csr_write(
            "I2C0_FIFO_RST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0),
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST,
        )
        await self.csr_write(
            "I2C0_CTRL_TGT",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

        # I2C1 host with stretch timeout enabled
        wrap1 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 1)
        await self.csr_write("I2C1_WRAP_HOST", wrap1, I2C_WRAP_CTRL_HOST)
        await self._program_timing(1)
        await self.csr_write(
            "I2C1_OVRD",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", 1),
            0,
        )
        await self.csr_write(
            "I2C1_FIFO_RST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 1),
            I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        # TIMEOUT_CTRL: VAL | EN; MODE=0 is StretchTimeout (MODE=1 is BusTimeout).
        await self.csr_write(
            "I2C1_TIMEOUT_CTRL",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMEOUT_CTRL_BASE_ADDR", 1),
            (_STRETCH_TIMEOUT_CYCLES & I2C_TIMEOUT_CTRL_VAL) | I2C_TIMEOUT_CTRL_EN,
        )
        await self.csr_write(
            "I2C1_INTR_ENABLE",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", 1),
            I2C_INTR_ENABLE_STRETCH_TIMEOUT,
        )
        await self.csr_write(
            "I2C1_INTR_CLR",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 1),
            0xFFFFFFFF,
        )
        await self.csr_write(
            "I2C1_CTRL_HOST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 1),
            I2C_CTRL_ENABLEHOST,
        )

        addr_r = (_TARGET_ADDR << 1) | 1
        txdata0 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR", 0)
        fifo0 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0)
        fifo1 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 1)
        intr0 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0)
        intr_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 1)

        # ---- Allow leg: the target answers the same read frame ----
        await self.csr_write(
            "I2C0_FIFO_RST_ALLOW", fifo0, I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST
        )
        await self.csr_write("I2C0_TXDATA_ALLOW", txdata0, _ALLOW_BYTE)
        await self._issue_read("I2C1_ALLOW")
        await self._wait_host_busy_then_idle("I2C1_ALLOW", 1)
        got = await self._wait_rx_byte("I2C1_ALLOW", 1)
        assert got == _ALLOW_BYTE, (
            f"allow leg: I2C1 RDATA got 0x{got:02x}, expected the byte preloaded into the I2C0 "
            f"target TX FIFO 0x{_ALLOW_BYTE:02x}"
        )
        start_word = await self._acq_start_word("I2C0_ALLOW", 0)
        assert acq_abyte(start_word) == addr_r, (
            f"allow leg: I2C0 ACQ START word carries address byte 0x{acq_abyte(start_word):02x}, "
            f"expected the read address 0x{addr_r:02x}"
        )
        self.allow_ok = True
        cocotb.log.info(
            "CHK-I2C-P0-TIMEOUT-TARGET-LIVE: I2C1 host read 0x%02x back from the I2C0 target "
            "over the shared pads (addr_r=0x%02x) and I2C0 ACQ holds the START word 0x%04x for "
            "that address, so the target is on the bus the timeout leg times out against",
            got,
            addr_r,
            start_word,
        )

        # ---- Timeout leg: the same read with the target TX FIFO empty ----
        await self.csr_write(
            "I2C0_FIFO_RST_EMPTY", fifo0, I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST
        )
        await self.csr_write("I2C0_INTR_CLR", intr0, 0xFFFFFFFF)
        await self.csr_write("I2C1_FIFO_RST_EMPTY", fifo1, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write("I2C1_INTR_CLR_EMPTY", intr_addr, 0xFFFFFFFF)
        await self._issue_read("I2C1_EMPTY")

        intr = 0
        for _ in range(800):
            intr = await self.csr_read("I2C1_INTR_POLL", intr_addr)
            if intr & I2C_INTR_STATE_STRETCH_TIMEOUT:
                break
            await Timer(5, unit="us")
        else:
            raise AssertionError(f"STRETCH_TIMEOUT not seen INTR_STATE=0x{intr:08x}")
        # The target's own view of the same event: it is stretching because the
        # host asked for a byte it does not have.
        tgt_intr = await self.csr_read("I2C0_INTR_STRETCHING", intr0)
        assert tgt_intr & I2C_INTR_STATE_TX_STRETCH, (
            f"I2C1 timed out but the I2C0 target does not report TX_STRETCH "
            f"(INTR_STATE=0x{tgt_intr:08x}): the stall was not the target holding SCL"
        )
        start_word = await self._acq_start_word("I2C0_EMPTY", 0)
        assert acq_abyte(start_word) == addr_r, (
            f"timeout leg: I2C0 ACQ START word carries 0x{acq_abyte(start_word):02x}, expected "
            f"the read address 0x{addr_r:02x}"
        )
        self.stretch_ok = True
        cocotb.log.info(
            "CHK-I2C-P0-TIMEOUT: I2C1 STRETCH_TIMEOUT INTR_STATE=0x%x after %d cycles while the "
            "I2C0 target reports TX_STRETCH (INTR_STATE=0x%x) and holds the START word 0x%04x for "
            "addr_r=0x%02x in its ACQ FIFO: the host timed out on the target's stretch",
            intr,
            _STRETCH_TIMEOUT_CYCLES,
            tgt_intr,
            start_word,
            addr_r,
        )

        # ---- Release leg: feeding the target ends the stretch and completes the read ----
        await self.csr_write("I2C0_TXDATA_RELEASE", txdata0, _RELEASE_BYTE)
        await self._wait_host_busy_then_idle("I2C1_RELEASE", 1)
        got = await self._wait_rx_byte("I2C1_RELEASE", 1)
        assert got == _RELEASE_BYTE, (
            f"release leg: I2C1 RDATA got 0x{got:02x}, expected the byte written to I2C0 TXDATA "
            f"0x{_RELEASE_BYTE:02x} after the timeout"
        )
        self.release_ok = True
        cocotb.log.info(
            "CHK-I2C-P0-TIMEOUT-RELEASE: writing 0x%02x to I2C0 TXDATA ended the stretch; the "
            "I2C1 host left its busy state and read that byte back, so the timed-out read was "
            "held by the target, not by a wedged host",
            got,
        )

        # Clean release
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
        await self._timeout_fifo_csr_sweep()

    async def _timeout_fifo_csr_sweep(self) -> None:
        """Masked write/readback over the timeout + FIFO-config CSRs.

        Run last, with both controllers already disabled by the clean-release
        writes above, so programming timeout values perturbs nothing.

        Every register here is `sw = rw; hw = r` with no side-effect property in
        hw/ip/i2c/regs/i2c.rdl, and each write is masked to the generated field
        masks so reserved bits are never driven.

        EXCLUDED -- `INTR_TEST`. It is declared `singlepulse` in
        i2c.rdl, so a written 1 does NOT stick and a write/readback expectation
        is not derivable for it, and its 20 fields force real interrupt sources
        into the shared regression.
        """
        idx = 1
        # (symbol, writable mask, bits that MUST be exercised as 1).
        #
        # `must_set` drives contract boundaries that the common pattern misses:
        # HOST_TIMEOUT_CTRL bit 20 proves the selected 31-bit value reaches the
        # RTL connectivity assertions without being truncated, and each EN bit
        # takes a 0 -> 1 -> 0 transition.
        sweep = (
            ("HOST_TIMEOUT_CTRL", I2C_HOST_TIMEOUT_CTRL_VAL, 1 << 20),
            (
                "TARGET_TIMEOUT_CTRL",
                I2C_TARGET_TIMEOUT_CTRL_VAL | I2C_TARGET_TIMEOUT_CTRL_EN,
                I2C_TARGET_TIMEOUT_CTRL_EN,
            ),
            (
                "HOST_NACK_HANDLER_TIMEOUT",
                I2C_NACK_HANDLER_TIMEOUT_VAL | I2C_NACK_HANDLER_TIMEOUT_EN,
                I2C_NACK_HANDLER_TIMEOUT_EN,
            ),
            (
                "HOST_FIFO_CONFIG",
                I2C_HOST_FIFO_CONFIG_RX_THRESH | I2C_HOST_FIFO_CONFIG_FMT_THRESH,
                0,
            ),
        )
        for name, mask, must_set in sweep:
            addr = self._idx_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{name}_BASE_ADDR", idx)
            probe = (
                (1 << 20) | 8 if name == "HOST_TIMEOUT_CTRL" else (0x5A5A_A5A5 & mask) | must_set
            )
            assert probe & must_set == must_set, (
                f"{name}: the probe 0x{probe:08x} does not set the bits this "
                f"row exists to exercise (0x{must_set:08x})"
            )
            if name == "HOST_TIMEOUT_CTRL":
                assert probe > 0x000F_FFFF, (
                    f"{name}: probe 0x{probe:08x} does not exercise a timeout "
                    "above the former 20-bit implementation limit"
                )
            await self.csr_read(f"I2C{idx}_{name}_RESET", addr, expected=0)
            await self.csr_write(f"I2C{idx}_{name}_WR", addr, probe)
            await self.csr_read(f"I2C{idx}_{name}_RB", addr, expected=probe)
            if name == "HOST_TIMEOUT_CTRL":
                ctrl_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", idx)
                await self.csr_write(
                    f"I2C{idx}_MONITOR_ENABLE_HIGH_TIMEOUT",
                    ctrl_addr,
                    I2C_CTRL_MULTI_CONTROLLER_MONITOR_EN,
                )
                await self.csr_read(
                    f"I2C{idx}_MONITOR_ENABLE_HIGH_TIMEOUT_RB",
                    ctrl_addr,
                    expected=I2C_CTRL_MULTI_CONTROLLER_MONITOR_EN,
                )
                # HOST_TIMEOUT_CTRL.VAL is 31 bits wide: with bit 20 set the
                # monitor timeout outlasts the host enable, so the queued command
                # stays blocked in the format FIFO. A counter that truncated the
                # value to 20 bits would load only eight cycles, expire before
                # the command is enabled, and consume it.
                fifo_ctrl_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", idx)
                await self.csr_write(
                    f"I2C{idx}_MONITOR_FMT_RESET",
                    fifo_ctrl_addr,
                    I2C_FIFO_CTRL_RXRST_FMTRST,
                )
                fdata_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", idx)
                await self.csr_write(
                    f"I2C{idx}_MONITOR_FMT_QUEUE",
                    fdata_addr,
                    I2C_FDATA_START | (_TARGET_ADDR << 1),
                )
                await self.csr_write(
                    f"I2C{idx}_MONITOR_HOST_ENABLE",
                    ctrl_addr,
                    I2C_CTRL_MULTI_CONTROLLER_MONITOR_EN | I2C_CTRL_ENABLEHOST,
                )
                await Timer(1, unit="us")
                fifo_status_addr = self._idx_addr(
                    "SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR", idx
                )
                fifo_status = await self.csr_read(f"I2C{idx}_MONITOR_FMT_BLOCKED", fifo_status_addr)
                fmt_level = fifo_status & I2C_HOST_FIFO_STATUS_FMTLVL
                assert fmt_level == 1, (
                    "31-bit monitor timeout did not keep the queued command blocked: "
                    f"HOST_FIFO_STATUS=0x{fifo_status:08x}"
                )
                await self.csr_write(f"I2C{idx}_MONITOR_DISABLE", ctrl_addr, 0)
                await self.csr_write(
                    f"I2C{idx}_MONITOR_FMT_CLEANUP",
                    fifo_ctrl_addr,
                    I2C_FIFO_CTRL_RXRST_FMTRST,
                )
            await self.csr_write(f"I2C{idx}_{name}_RESTORE", addr, 0)
            await self.csr_read(f"I2C{idx}_{name}_RESTORE_RB", addr, expected=0)

        # TARGET_NACK_COUNT is `rclr` (i2c.rdl): the first read returns the
        # value and CLEARS it, so the second read must return 0.
        nack = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_NACK_COUNT_BASE_ADDR", idx)
        nack_probe = 0x5A
        await self.csr_write(f"I2C{idx}_TARGET_NACK_COUNT_WR", nack, nack_probe)
        await self.csr_read(f"I2C{idx}_TARGET_NACK_COUNT_RD1", nack, expected=nack_probe)
        await self.csr_read(f"I2C{idx}_TARGET_NACK_COUNT_RD2", nack, expected=0)
        cocotb.log.info(
            "CHK-I2C-TIMEOUT-CSR-SWEEP: %d timeout/FIFO CSRs took a masked "
            "write/readback/restore on controller %d (HOST_TIMEOUT_CTRL used a "
            ">20-bit value and both TIMEOUT EN bits were driven 0->1->0), and "
            "TARGET_NACK_COUNT "
            "read 0x%x then 0x0 on the second read, which is its rclr semantic "
            "and not just storage (INTR_TEST excluded -- singlepulse, see "
            "docstring)",
            len(sweep),
            idx,
            nack_probe,
        )
