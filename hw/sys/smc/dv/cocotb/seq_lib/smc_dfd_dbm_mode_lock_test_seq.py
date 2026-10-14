# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walk the debug-bus mux modes, then latch the CLA lock and prove it holds.

Every address, field position, field width, reset value and software-access
type comes from the generated register map through
:mod:`seq_lib.smc_rdl_regmap` and :mod:`seq_lib.smc_cla_regmap`. Every value
programmed into a field comes from that field's own RDL description, stated
here rather than quoted. The vendored RTL is not a source for any value this
sequence programs or compares against.

Two surfaces the other DFD leaves leave alone:

* **The debug-bus mux modes.** ``DEBUG_BUS_MUX.Dbmmode`` is two bits and its
  RDL description names four modes: the mux off, normal debug, an identifier
  output mode and a toggle mode. The other DFD leaves program only normal
  debug. This one walks all four across every value of the identifier field,
  because a mux takes a mode only while the programmed identifier is its own.

* **The CLA lock.** ``CDbgClaCtrlStatus.ClaLock`` is described as locking the
  CLA so the enable latches and stays latched. No later write undoes it, so
  the MMR write sweep excludes the register and this leaf sets it as its last
  act: the lock is set, read back, and then a further write that would clear
  it in the written word has to leave it set. Each leaf is its own simulation
  and the run ends immediately afterwards, so nothing downstream inherits a
  locked CLA.
"""

from __future__ import annotations

import cocotb

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import dfd_register, pack_fields, reg_field

# dfx_ctrl_status.rdl Dbmmode: the value its description names as the mux
# identifier output mode.
_DBM_MODE_IDENTIFIER = 2


class smc_dfd_dbm_mode_lock_test_seq(SmcCsrSeq):
    """Program every debug-bus mux mode, then latch the CLA lock and hold it."""

    def __init__(self, name: str = "smc_dfd_dbm_mode_lock_test_seq") -> None:
        super().__init__(name)
        self.modes_programmed: list[int] = []
        self.mux_writes = 0
        self.lock_held = False
        self.value_checks = 0

    # -- register helpers -------------------------------------------------

    @staticmethod
    def _short(reg) -> str:
        return reg.path.rsplit("/", 1)[1]

    async def _read(self, reg, label: str) -> int:
        return await self.csr_read(f"{self._short(reg)}:{label}", reg.addr, length=reg.width_bytes)

    async def _write(self, reg, word: int, label: str) -> None:
        await self.csr_write(f"{self._short(reg)}:{label}", reg.addr, word, length=reg.width_bytes)

    # -- phases -----------------------------------------------------------

    async def _sweep_modes(self) -> None:
        """Every mode the 2-bit field offers, on every mux of the array."""
        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write(clk, pack_fields(clk, {"force_clk_en": 1}), "force")

        reg = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        mode = reg_field(reg, "Dbmmode")
        dbmid = reg_field(reg, "Dbmid")
        for value in range(1 << mode.width):
            for identity in range(1 << dbmid.width):
                await self._write(
                    reg,
                    pack_fields(reg, {"Dbmmode": value, "Dbmid": identity}),
                    f"mode{value}_id{identity}",
                )
                self.mux_writes += 1
            last = await self._read(reg, f"mode{value}_rb")
            got_mode = (last & mode.mask) >> mode.offset
            got_id = (last & dbmid.mask) >> dbmid.offset
            assert got_mode == value and got_id == (1 << dbmid.width) - 1, (
                f"{reg.path} @ 0x{reg.addr:08x}: after programming mode {value} into every "
                f"one of the {1 << dbmid.width} identifiers it reads mode {got_mode} and "
                f"identifier {got_id}"
            )
            self.modes_programmed.append(value)
            self.value_checks += 1

        assert self.modes_programmed == list(range(1 << mode.width)), (
            f"the mode walk programmed {self.modes_programmed}, not every value of the "
            f"{mode.width}-bit Dbmmode field"
        )
        # The walk ends in the toggle mode. Every mux is then taken out of it into
        # the identifier output mode, so the mode leaves toggle with the mux
        # clocked, rather than into the off mode that stops its clock.
        leave = _DBM_MODE_IDENTIFIER
        for identity in range(1 << dbmid.width):
            await self._write(
                reg,
                pack_fields(reg, {"Dbmmode": leave, "Dbmid": identity}),
                f"leave_id{identity}",
            )
            self.mux_writes += 1
        last = await self._read(reg, "leave_rb")
        got_mode = (last & mode.mask) >> mode.offset
        assert got_mode == leave, (
            f"{reg.path} @ 0x{reg.addr:08x}: after taking every identifier from the toggle "
            f"mode to mode {leave} it reads mode {got_mode}"
        )
        self.modes_programmed.append(leave)
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DBM-MODE-SWEEP: every one of the %d modes the %d-bit Dbmmode field offers "
            "was programmed into every one of the %d mux identifiers and read back, and the "
            "array was then taken from the toggle mode into the identifier output mode, %d "
            "writes in all; a mux takes a mode only while the programmed identifier is its "
            "own, so this is the whole array in every mode rather than one mux in one mode",
            1 << mode.width,
            mode.width,
            1 << dbmid.width,
            self.mux_writes,
        )

    async def _latch_lock(self) -> None:
        """Set the CLA lock, then require a write that would clear it to fail to."""
        reg = cla_register("CDbgClaCtrlStatus")
        lock = cla_field(reg, "ClaLock")
        chain = cla_field(reg, "ClaChainLoopDelay")
        held_chain = (reg.reset_word & chain.mask) >> chain.offset

        before = await self._read(reg, "before_lock")
        assert before & lock.mask == 0, (
            f"CDbgClaCtrlStatus @ 0x{reg.addr:08x} reads 0x{before:x} with ClaLock already "
            f"set before this sequence set it, so the latch below would prove nothing"
        )
        self.value_checks += 1

        await self._write(
            reg, pack_fields(reg, {"ClaLock": 1, "ClaChainLoopDelay": held_chain}), "lock"
        )
        locked = await self._read(reg, "locked")
        assert locked & lock.mask, (
            f"CDbgClaCtrlStatus @ 0x{reg.addr:08x} reads 0x{locked:x} after ClaLock was "
            f"written 1; the RDL makes the bit software-writable, so it has to take"
        )
        self.value_checks += 1

        # The register contract says the lock latches. A write whose data has the
        # bit clear must not clear it, and it is the only way to reach the decode
        # of this register with the lock already set.
        await self._write(reg, pack_fields(reg, {"ClaChainLoopDelay": held_chain}), "clear_attempt")
        after = await self._read(reg, "after_clear_attempt")
        assert after & lock.mask, (
            f"CDbgClaCtrlStatus @ 0x{reg.addr:08x} reads 0x{after:x} after a write whose "
            f"data had ClaLock clear; the RDL says the lock latches, so the bit must survive"
        )
        self.lock_held = True
        self.value_checks += 1
        cocotb.log.info(
            "CHK-CLA-LOCK-LATCHED: CDbgClaCtrlStatus.ClaLock read 0, took a software write "
            "of 1, and then survived a further write to the same register whose data had "
            "the bit clear, which is the latching the register description states. It is "
            "the last act of this run, so no later stimulus inherits a locked CLA"
        )

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        await self._sweep_modes()
        # Restore the mux array and the DFD clock control before the lock, which
        # no later write can clear.
        for reg in (
            dfd_register("dfx_ctrl/DEBUG_BUS_MUX"),
            dfd_register("dfx_ctrl/DEBUG_CTRL"),
        ):
            await self._write(reg, reg.reset_word, "restore")

        await self._latch_lock()
