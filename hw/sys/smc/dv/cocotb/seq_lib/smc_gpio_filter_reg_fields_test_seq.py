# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO ACCESS_FILTER requirement value space and individual enable bit set and clear.

Sources hw/ip/gpio/regs/gpio_intf.rdl (ACCESS_FILTER), integrator GPIO pad table.

Instance 60 is the pad the integrator table reserves. Both requirement fields take every
value 0..7 with both enables clear, then each enable bit is set and cleared with an access
that satisfies the filter it arms.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import gpio_intf_u32
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_pad_table import pad_function
from .smc_regblock_field_sweep_utils import RegInstance, reg_instances

_ACCESS_FILTER = (
    "gpio_intf/ACCESS_FILTER",
    "SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_ACCESS_FILTER_NUM",
    "GPIO_INTF_{index}__ACCESS_FILTER_REG_ADDR",
)

_INSTANCE = 60
_INSTANCE_FUNCTION = "Reserved"
_WR_EN = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__WRITE_FILTER_ENABLE_bm")
_RD_EN = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__READ_FILTER_ENABLE_bm")
_AW_BP = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__AWPROT_REQUIREMENT_bp")
_AR_BP = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__ARPROT_REQUIREMENT_bp")
_AW_RESET = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__AWPROT_REQUIREMENT_reset")
_AR_RESET = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__ARPROT_REQUIREMENT_reset")
_RESET_WORD = (_AW_RESET << _AW_BP) | (_AR_RESET << _AR_BP)

STEP_ORDER = ("BRINGUP_DONE", "REQUIREMENT_VALUES", "ENABLE_BIT_LEGS", "RESTORE_READBACK")
CHK_ORDER = (
    ("REQUIREMENT_VALUES", "CHK-GPIO-FILTER-REG-REQ-VALUES"),
    ("ENABLE_BIT_LEGS", "CHK-GPIO-FILTER-REG-ENABLE-BITS"),
)


class smc_gpio_filter_reg_fields_test_seq(SmcCsrSeq):
    """Drive the ACCESS_FILTER requirement fields and enable bits of instance 60."""

    def __init__(self, name: str = "smc_gpio_filter_reg_fields_test_seq") -> None:
        super().__init__(name)
        self.values_driven = 0
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        cocotb.log.info("%s: %s", chk_id, text)

    async def _read(self, label: str, inst: RegInstance, prot: int = 0) -> int:
        got = await self.csr_read(f"GPIO{_INSTANCE}_{label}", inst.addr, prot=prot)
        assert isinstance(got, int), f"{label}: unresolved read data {got!r}"
        return got

    async def _requirements(self, flt: RegInstance) -> str:
        parts = []
        for field, bp, other in (
            ("AWPROT", _AW_BP, _AR_RESET << _AR_BP),
            ("ARPROT", _AR_BP, _AW_RESET << _AW_BP),
        ):
            seen = []
            for value in range(8):
                word = (value << bp) | other
                await self.csr_write(f"GPIO{_INSTANCE}_{field}_REQ{value}", flt.addr, word)
                got = await self._read(f"{field}_REQ{value}_RB", flt)
                assert got == word, (
                    f"GPIO {_INSTANCE} ACCESS_FILTER after writing {field.lower()}_requirement "
                    f"= {value} reads 0x{got:08x}, expected 0x{word:08x}"
                )
                self.values_driven += 1
                seen.append(f"{value}")
            parts.append(f"{field.lower()}_requirement 0..7 ({','.join(seen)})")
        await self.csr_write(f"GPIO{_INSTANCE}_REQ_RESTORE", flt.addr, _RESET_WORD)
        back = await self._read("REQ_RESTORE_RB", flt)
        assert back == _RESET_WORD, f"ACCESS_FILTER restore reads 0x{back:08x}"
        assert self.values_driven == 16, f"{self.values_driven} of 16 values driven"
        return "; ".join(parts)

    async def _enable_legs(self, flt: RegInstance) -> str:
        legs = (
            ("WR_SET", _WR_EN, 0, 0, _RESET_WORD | _WR_EN),
            ("WR_CLR", 0, 1, 0, _RESET_WORD),
            ("RD_SET", _RD_EN, 0, 1, _RESET_WORD | _RD_EN),
            ("RD_CLR", 0, 0, 0, _RESET_WORD),
            ("BOTH_SET", _WR_EN | _RD_EN, 0, 1, _RESET_WORD | _WR_EN | _RD_EN),
            ("BOTH_CLR", 0, 1, 0, _RESET_WORD),
        )
        parts = []
        for tag, bits, awprot, arprot, expect in legs:
            await self.csr_write(
                f"GPIO{_INSTANCE}_{tag}", flt.addr, _RESET_WORD | bits, prot=awprot
            )
            got = await self._read(f"{tag}_RB", flt, prot=arprot)
            assert got == expect, (
                f"GPIO {_INSTANCE} ACCESS_FILTER after {tag} reads 0x{got:08x}, "
                f"expected 0x{expect:08x}"
            )
            parts.append(f"{tag}=0x{got:08x}")
        return ", ".join(parts)

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.steps) == STEP_ORDER, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert tuple(self.chk_steps) == CHK_ORDER, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BRINGUP_DONE < REQUIREMENT_VALUES < ENABLE_BIT_LEGS < "
            "RESTORE_READBACK; checker lines %s; stamps %s",
            ",".join(c for _, c in self.chk_steps),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        function = pad_function(_INSTANCE)
        assert function == _INSTANCE_FUNCTION, (
            f"the integrator pad table gives pad {_INSTANCE} the function {function!r}, not "
            f"{_INSTANCE_FUNCTION!r}"
        )
        flt = reg_instances(*_ACCESS_FILTER)[_INSTANCE]
        idle = await self._read("IDLE", flt)
        assert idle == _RESET_WORD, (
            f"ACCESS_FILTER reads 0x{idle:08x} before any write, expected 0x{_RESET_WORD:08x}"
        )
        self._mark("BRINGUP_DONE")

        reqs = await self._requirements(flt)
        self._mark("REQUIREMENT_VALUES")
        self._chk(
            "REQUIREMENT_VALUES",
            "CHK-GPIO-FILTER-REG-REQ-VALUES",
            f"on GPIO instance {_INSTANCE} with both enables clear {self.values_driven} values "
            f"read back exactly as written, the other requirement and the enables unchanged "
            f"({reqs})",
        )

        legs = await self._enable_legs(flt)
        self._mark("ENABLE_BIT_LEGS")
        self._chk(
            "ENABLE_BIT_LEGS",
            "CHK-GPIO-FILTER-REG-ENABLE-BITS",
            f"on GPIO instance {_INSTANCE} the enable bits read back exactly ({legs})",
        )

        final = await self._read("END", flt)
        assert final == _RESET_WORD, f"ACCESS_FILTER ends at 0x{final:08x}"
        self._mark("RESTORE_READBACK")
        self._nonvac()
