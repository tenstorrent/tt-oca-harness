# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DATA_CTRL_ENABLE and ACCESS_FILTER cycles on every GPIO_INTF instance.

`smc_gpio_intf_full_sweep_test` reads DATA_CTRL on all GPIO_INTF_NUM instances;
this sequence drives the other two registers of the same block, in both
directions and through byte lanes, on every instance.

DATA_CTRL_ENABLE takes the generic half-register cycle: its three fields are
per-field overrides that route core2pad and the two direction bits from
DATA_CTRL onto the pad. DATA_CTRL keeps its reset word throughout, so the
override window drives the pad with the reset data and direction, and it lasts
from the write of one half to the restore a few accesses later.

ACCESS_FILTER gates the block's own register interface on AxPROT, so the order
of its cycle is what keeps the sequence able to reach the register again:

* `arprot_requirement` is driven first, while both filter enables are still 0
  and nothing is gated;
* the enables are then set in one lower-half write that also drops
  `awprot_requirement` to 0, so writes with AxPROT=0 -- every write this
  sequence issues -- stay admissible while the read half is armed at
  AxPROT=7. The armed state carries its own allow and deny legs;
* `arprot_requirement` is cleared next, which re-admits AxPROT=0 reads, and
  only then does `awprot_requirement` take the all-ones value, in the same
  write that clears both enables;
* the RDL reset word is restored in a full-width write.

`DATA_CTRL.pad2core` and `DATA_CTRL.lsio_enable` are hardware-driven and are
not written here; `DATA_CTRL` itself is the subject of
`smc_gpio_intf_full_sweep_test`.
"""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import gpio_intf_u32
from .smc_regblock_field_sweep_utils import RegInstance, SmcRegblockFieldSweepSeq, reg_instances

_DATA_CTRL_ENABLE = (
    "gpio_intf/DATA_CTRL_ENABLE",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_ENABLE_REG_ADDR",
)
_ACCESS_FILTER = (
    "gpio_intf/ACCESS_FILTER",
    "SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_ACCESS_FILTER_NUM",
    "GPIO_INTF_{index}__ACCESS_FILTER_REG_ADDR",
)

_WRITE_FILTER_ENABLE = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__WRITE_FILTER_ENABLE_bm")
_READ_FILTER_ENABLE = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__READ_FILTER_ENABLE_bm")
_AWPROT_REQUIREMENT = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__AWPROT_REQUIREMENT_bm")
_ARPROT_REQUIREMENT = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__ARPROT_REQUIREMENT_bm")
_ARPROT_SHIFT = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__ARPROT_REQUIREMENT_bp")

_PROT_ALL_ONES = _ARPROT_REQUIREMENT >> _ARPROT_SHIFT
_PROT_ZERO = 0

# DECERR is the response hw/ip/gpio/doc/programming.adoc ("Filter
# Configuration") specifies for a transaction whose protection bits do not
# match an armed filter.
_AXI_RESP_DECERR = 3

_ACCESSES_PER_DATA_CTRL_ENABLE = 12
_ACCESSES_PER_ACCESS_FILTER = 12
# Contract compares per instance: the six reads of the DATA_CTRL_ENABLE cycle
# and the six admitted reads of the ACCESS_FILTER cycle. Every one of them
# carries a fully predicted word, so the scoreboard books one exact compare
# each, independently of this sequence's own counters.
_PREDICTED_READS_PER_INSTANCE = 12


class smc_gpio_intf_regblock_sweep_test_seq(SmcRegblockFieldSweepSeq):
    """Drive DATA_CTRL_ENABLE and ACCESS_FILTER on every GPIO_INTF instance."""

    def __init__(self, name: str = "smc_gpio_intf_regblock_sweep_test_seq") -> None:
        super().__init__(name)
        self.denials = 0

    async def _read_denied(self, inst: RegInstance) -> int:
        """An AxPROT=0 read of an armed read filter DECERRs with the error word."""
        item = SmcSysAxiItem(f"rd_{inst.label}:denied")
        item.op = SmcSysAxiOp.READ
        item.addr = inst.addr
        item.length = inst.width_bytes
        item.allow_error = True
        item.expect_error = True
        item.prot = _PROT_ZERO
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == _AXI_RESP_DECERR, (
            f"{inst.label} @ 0x{inst.addr:08x}: an AxPROT={_PROT_ZERO} read of a register "
            f"whose read filter requires AxPROT={_PROT_ALL_ONES} must be refused with "
            f"DECERR, got resp={item.resp_code} (rdata=0x{item.rdata:x})"
        )
        got = item.rdata & self.word_mask(inst)
        assert got == (self.ERR_SLAVE_SIGNATURE & self.word_mask(inst)), (
            f"{inst.label} @ 0x{inst.addr:08x}: a refused read must return the error-slave "
            f"word 0x{self.ERR_SLAVE_SIGNATURE:08x}, got 0x{got:08x}"
        )
        self.denials += 1
        return item.rdata

    async def _access_filter_cycle(self, inst: RegInstance) -> None:
        reg = inst.reg
        half = inst.width_bytes // 2
        model = reg.reset_word
        await self.read_check(inst, "reset", model)

        await self.csr_write(
            f"{inst.label}:arprot_ones", inst.addr + half, _ARPROT_REQUIREMENT >> (half * 8), 2
        )
        model |= _ARPROT_REQUIREMENT
        await self.read_check(inst, "arprot_ones", model)

        armed = _WRITE_FILTER_ENABLE | _READ_FILTER_ENABLE
        await self.csr_write(f"{inst.label}:armed", inst.addr, armed, 2)
        model = (model & ~0xFFFF) | armed
        await self.read_check(inst, "armed", model, prot=_PROT_ALL_ONES)
        await self._read_denied(inst)

        await self.csr_write(f"{inst.label}:arprot_zeros", inst.addr + half, 0, 2)
        model &= ~_ARPROT_REQUIREMENT
        await self.read_check(inst, "arprot_zeros", model)

        await self.csr_write(f"{inst.label}:awprot_ones", inst.addr, _AWPROT_REQUIREMENT, 2)
        model = (model & ~0xFFFF) | _AWPROT_REQUIREMENT
        await self.read_check(inst, "awprot_ones", model)

        await self.csr_write(f"{inst.label}:restore", inst.addr, reg.reset_word, inst.width_bytes)
        await self.read_check(inst, "restore", reg.reset_word)
        self.registers_swept += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        enables = reg_instances(*_DATA_CTRL_ENABLE)
        filters = reg_instances(*_ACCESS_FILTER)
        assert len(enables) == len(filters), (
            f"the generated map declares {len(enables)} DATA_CTRL_ENABLE instances and "
            f"{len(filters)} ACCESS_FILTER instances of the same block"
        )
        instances = len(enables)

        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.update(inst.addr for inst in filters)

        sb_before = self.env.scoreboard.sys_axi_value_checks_seen

        for inst in enables:
            await self.granule_cycle(inst)
        cocotb.log.info(
            "CHK-GPIO-INTF-DATA-CTRL-ENABLE-SWEEP: %d GPIO_INTF DATA_CTRL_ENABLE instances "
            "each read their RDL reset, took the all-ones and all-zeros pattern of their "
            "three override fields through half-register writes whose byte lanes over the "
            "other half were deasserted, and were restored to that reset; %d contract "
            "compares so far",
            instances,
            self.value_checks,
        )

        for inst in filters:
            await self._access_filter_cycle(inst)
        cocotb.log.info(
            "CHK-GPIO-INTF-ACCESS-FILTER-SWEEP: %d GPIO_INTF ACCESS_FILTER instances each "
            "drove both filter enables and both AxPROT requirement fields to all-ones and "
            "all-zeros through half-register writes and were restored to their RDL reset "
            "0x%08x; %d contract compares in total",
            instances,
            filters[0].reg.reset_word,
            self.value_checks,
        )

        assert self.denials == instances, (
            f"the armed leg of {instances} ACCESS_FILTER instances produced {self.denials} refusals"
        )
        cocotb.log.info(
            "CHK-GPIO-INTF-ACCESS-FILTER-DENY: on each of %d GPIO_INTF instances the armed "
            "read filter admitted the AxPROT=%d read that carried the programmed word and "
            "refused the AxPROT=%d read of the same address with DECERR and 0x%08x, so the "
            "refusal is the AxPROT gate and not a window that stopped answering",
            instances,
            _PROT_ALL_ONES,
            _PROT_ZERO,
            self.ERR_SLAVE_SIGNATURE,
        )

        expected = instances * (_ACCESSES_PER_DATA_CTRL_ENABLE + _ACCESSES_PER_ACCESS_FILTER)
        self.assert_all_reachable(expected, "GPIO_INTF_REGBLOCK_SWEEP")
        assert self.registers_swept == 2 * instances, (
            f"the sweep completed {self.registers_swept} register cycles for "
            f"{2 * instances} register instances"
        )
        self.assert_value_checks(
            sb_before,
            instances * _PREDICTED_READS_PER_INSTANCE,
            "GPIO_INTF_REGBLOCK_SWEEP",
        )
