# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""32-bit CPU stores into one half of a 64-bit register word; the other half holds.

`fw/tests/narrow_store_lane` stores all ones to the half of a 64-bit register
word that its writable fields do not occupy. The core replicates a word store
across both halves of its data bus, so the fields' byte lanes carry ones with
their strobes clear. The bench's SEP_IN master zero-fills unstrobed lanes and
cannot make that case.

The image checks each target itself, before and after its store, and posts
PASS only if all of them held. The bench adds a view that does not go through
that word: with the cores still held it reads every target over SEP_IN and
requires the RDL reset word, and after PASS it reads them again. The field
halves must still hold their reset word, except `RESET_TIMEOUT`, which the boot
contract programs before release and the image puts back after its store. A
MUTEX read must still take the mutex. `region_attrs` is the one target whose stored half has a field, so after
PASS it must read `offset[31:12]` all ones with `cacheable`, `valid` and
`offset[55:32]` still 0. The bench then restores it.

Expected words come from the generated IP-XACT map (`smc_rdl_regmap`), not from
literals. `RESET_TIMEOUT` is compared through its software-writable mask
because its upper half is live hardware status.
"""

from __future__ import annotations

import cocotb

from .smc_cpu_vip_utils import CPU_RESET_TIMEOUT_FORCE
from .smc_fw_image_boot_seq import smc_fw_image_boot_seq
from .smc_rdl_regmap import RdlReg, rdl_array, rdl_contract, rdl_register

# Registers whose writable fields sit in the half the image does not store to.
_HELD = (
    "smc_base_config/CLOCK_GATE_CONTROL",
    "smc_base_config/HANG_DET_SYS_AXI_CTRL",
    "smc_base_config/HANG_DET_SEP_AXI_CTRL",
    "smc_base_config/HANG_DET_DATA_ACCEL_CTRL",
    "dfx_ctrl/DEBUG_CTRL",
    "smc_cpu_ctrl/RESET_TIMEOUT",
)
# The boot contract programs RESET_TIMEOUT before release; the image stores
# against the reset value and puts the boot value back.
_AFTER_BOOT = {"smc_cpu_ctrl/RESET_TIMEOUT": CPU_RESET_TIMEOUT_FORCE}
_MUTEX = "smc_cpu_ctrl/MUTEX"
_ATTRS = "smc_alias_remap/REGION/region_attrs"

_WORD = 8
_LOWER = 0xFFFF_FFFF


class smc_fw_narrow_store_lane_test_seq(smc_fw_image_boot_seq):
    """Boot the narrow-store image, bracketing it with SEP_IN reads of every target."""

    tag = "NARROW-STORE"
    poll_iterations = 2000

    def __init__(self, name: str = "smc_fw_narrow_store_lane_test_seq") -> None:
        super().__init__(name)
        self.held = [rdl_register(path) for path in _HELD]
        self.mutexes = rdl_array(_MUTEX)
        self.attrs = rdl_contract(_ATTRS)
        self.checked = 0
        self.held_ok = False

    async def _held_word(self, reg: RdlReg, when: str, expected: int) -> None:
        mask = reg.rw_mask
        assert mask, f"{reg.path} has no software-writable field"
        got = await self.csr_read(f"{reg.path}:{when}", reg.addr, length=_WORD)
        assert got & mask == expected & mask, (
            f"{reg.path} @ 0x{reg.addr:08x} reads 0x{got:016x} {when}; its writable fields "
            f"(mask 0x{mask:x}) must hold 0x{expected & mask:x}"
        )
        self.checked += 1

    async def _mutex_free(self, reg: RdlReg, when: str) -> None:
        got = await self.csr_read(f"{reg.path}:take_{when}", reg.addr, length=_WORD)
        assert got & 1, (
            f"{reg.path} read 0x{got:x} {when}; a read takes a free mutex and returns 1, "
            f"so something left it held"
        )
        await self.csr_write(f"{reg.path}:release_{when}", reg.addr, 0, length=_WORD)
        self.checked += 1

    async def _all_targets(self, when: str, after_boot: bool) -> None:
        for reg in self.held:
            expected = _AFTER_BOOT.get(reg.path, reg.reset_word) if after_boot else reg.reset_word
            await self._held_word(reg, when, expected)
        for reg in self.mutexes:
            await self._mutex_free(reg, when)

    async def before_boot(self) -> None:
        await self._all_targets("before release", after_boot=False)
        await self.csr_read(
            f"{_ATTRS}:before release",
            self.attrs.addr,
            expected=self.attrs.reset_word,
            length=_WORD,
        )

    async def after_pass(self) -> None:
        self.checked = 0
        await self._all_targets("after PASS", after_boot=True)
        expected = (self.attrs.reset_word & ~_LOWER) | (_LOWER & self.attrs.declared_mask)
        got = await self.csr_read(
            f"{_ATTRS}:after PASS", self.attrs.addr, expected=expected, length=_WORD
        )
        assert got == expected, (
            f"{_ATTRS} reads 0x{got:016x} after PASS, expected 0x{expected:016x}: the "
            f"image's lower-half store of all ones takes offset[31:12] and must leave "
            f"cacheable, valid and offset[55:32] at their reset value"
        )
        await self.csr_write(
            f"{_ATTRS}:restore", self.attrs.addr, self.attrs.reset_word, length=_WORD
        )
        await self.csr_read(
            f"{_ATTRS}:restore", self.attrs.addr, expected=self.attrs.reset_word, length=_WORD
        )
        self.held_ok = True
        cocotb.log.info(
            "CHK-FW-NARROW-STORE-HELD: %d registers read over SEP_IN after PASS: the "
            "writable fields of %s held their RDL reset word (RESET_TIMEOUT the boot "
            "contract's value), each of the %d mutexes was "
            "still free, and %s read 0x%016x (the stored half taken, the other held)",
            self.checked + 1,
            ", ".join(reg.path for reg in self.held),
            len(self.mutexes),
            _ATTRS,
            got,
        )
