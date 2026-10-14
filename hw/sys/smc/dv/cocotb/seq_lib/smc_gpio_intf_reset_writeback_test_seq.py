# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reset-word write-back of ACCESS_FILTER, DATA_CTRL_ENABLE and DATA_CTRL on 65 instances.

Spec sources: hw/ip/gpio/regs/gpio_intf.rdl, hw/sys/smc/regs/gen/c/smc_addr.h.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_regblock_field_sweep_utils import SmcRegblockFieldSweepSeq, reg_instances

_ACCESS_FILTER = (
    "gpio_intf/ACCESS_FILTER",
    "SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_ACCESS_FILTER_NUM",
    "GPIO_INTF_{index}__ACCESS_FILTER_REG_ADDR",
)
_DATA_CTRL_ENABLE = (
    "gpio_intf/DATA_CTRL_ENABLE",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_ENABLE_REG_ADDR",
)
_DATA_CTRL = (
    "gpio_intf/DATA_CTRL",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_REG_ADDR",
)

_INSTANCES = 65
_ACCESS_FILTER_RESET_WORD = 0x00010100
_ZERO_WORD = 0x0
_TERMS = ("BRINGUP_DONE", "INITIAL_READS", "RESET_WORD_WRITES", "WRITEBACK_READS")


class smc_gpio_intf_reset_writeback_test_seq(SmcRegblockFieldSweepSeq):
    """Write the reset words back on every GPIO_INTF instance and read them."""

    def __init__(self, name: str = "smc_gpio_intf_reset_writeback_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.terms: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []

    def _term(self, term: str) -> None:
        self.terms.append((term, int(get_sim_time("ps"))))

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        self._term("BRINGUP_DONE")

        filters = reg_instances(*_ACCESS_FILTER)
        enables = reg_instances(*_DATA_CTRL_ENABLE)
        ctrls = reg_instances(*_DATA_CTRL)
        assert len(filters) == len(enables) == len(ctrls) == _INSTANCES, (
            f"generated map declares {len(filters)} ACCESS_FILTER, {len(enables)} "
            f"DATA_CTRL_ENABLE and {len(ctrls)} DATA_CTRL instances, the spec says {_INSTANCES}"
        )
        ctrl_rw = ctrls[0].reg.rw_mask
        assert filters[0].reg.reset_word == _ACCESS_FILTER_RESET_WORD, (
            f"ACCESS_FILTER RDL reset 0x{filters[0].reg.reset_word:08x}, the spec says "
            f"0x{_ACCESS_FILTER_RESET_WORD:08x}"
        )

        initial = []
        for flt, ena, ctl in zip(filters, enables, ctrls):
            initial.append(
                (
                    await self.csr_read(f"{flt.label}:initial", flt.addr),
                    await self.csr_read(f"{ena.label}:initial", ena.addr),
                    await self.csr_read(f"{ctl.label}:initial", ctl.addr),
                )
            )
        self._term("INITIAL_READS")
        self._mark("S1")

        sb_before = self.env.scoreboard.sys_axi_value_checks_seen
        first_write_done = False
        for flt, ena, ctl in zip(filters, enables, ctrls):
            await self.csr_write(f"{flt.label}:reset_word", flt.addr, _ACCESS_FILTER_RESET_WORD)
            await self.csr_write(f"{ena.label}:reset_word", ena.addr, _ZERO_WORD)
            await self.csr_write(f"{ctl.label}:reset_word", ctl.addr, _ZERO_WORD)
            if not first_write_done:
                self._term("RESET_WORD_WRITES")
                first_write_done = True
            got_f = await self.read_check(flt, "writeback", _ACCESS_FILTER_RESET_WORD)
            got_e = await self.read_check(ena, "writeback", _ZERO_WORD)
            got_c = await self.read_check(ctl, "writeback", _ZERO_WORD)
            assert got_f == _ACCESS_FILTER_RESET_WORD, (
                f"{flt.label}: ACCESS_FILTER read 0x{got_f:08x}, "
                f"want 0x{_ACCESS_FILTER_RESET_WORD:08x}"
            )
            assert got_e == _ZERO_WORD, (
                f"{ena.label}: DATA_CTRL_ENABLE read 0x{got_e:08x}, want 0x0"
            )
            assert got_c & ctrl_rw == 0, (
                f"{ctl.label}: DATA_CTRL writable bits 0x{ctrl_rw:08x} read 0x{got_c & ctrl_rw:08x}"
            )
        self._term("WRITEBACK_READS")
        self._mark("S2")
        self.assert_value_checks(sb_before, len(filters) * 2, "GPIO_INTF_RESET_WRITEBACK")

        self.chk_steps.append(("S2", "CHK-GPIO-RESET-WRITEBACK"))
        cocotb.log.info(
            "CHK-GPIO-RESET-WRITEBACK: %d instances; ACCESS_FILTER read 0x%08x, "
            "DATA_CTRL_ENABLE read 0x%x, DATA_CTRL software-writable bits (mask 0x%08x) read 0x0 "
            "after the reset words were written back; %d expected-value compares",
            len(filters),
            _ACCESS_FILTER_RESET_WORD,
            _ZERO_WORD,
            ctrl_rw,
            self.value_checks,
        )
        self.assert_all_reachable(_INSTANCES * 9, "GPIO_INTF_RESET_WRITEBACK")
        self._nonvac()

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.steps) == ("S1", "S2"), f"step order {self.steps}"
        assert tuple(t for t, _ in self.terms) == _TERMS, f"fence terms {self.terms}"
        term_ps = [ps for _, ps in self.terms]
        assert all(b > a for a, b in zip(term_ps, term_ps[1:])), f"stamps not increasing {term_ps}"
        step_ps = [ps for _, ps in self.steps]
        assert step_ps[1] > step_ps[0], f"step stamps {self.steps}"
        assert tuple(c for _, c in self.chk_steps) == ("CHK-GPIO-RESET-WRITEBACK",)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(_TERMS),
            ",".join(c for _, c in self.chk_steps),
            ",".join(f"{n}={ps}" for n, ps in self.terms + self.steps),
        )
