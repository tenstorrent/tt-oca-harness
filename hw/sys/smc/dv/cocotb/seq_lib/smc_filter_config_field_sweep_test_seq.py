# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FILTER_CONFIG field cycle and write-once lock on all 32 filter entries.

`smc_filter_field_sweep_test` reads the reset content of the three registers of
the first four entries and `smc_filter_multi_entry_test` proves the 32 entries
are separately addressable with full-width writes. Neither drives a field to
all-ones through byte lanes, and neither touches the write-once lock, so this
sequence does both on every inbound and outbound entry.

The ones pattern arms the entry (`entry_enabled`) in the same write that sets
`read_allowed` and `write_allowed`, so an entry that did match a transaction
would permit it. The entry can match almost nothing in any case: its address
range stays at the reset `START_ADDR`/`END_ADDR`, which
`hw/ip/axi_filter/doc/index.adoc` widens to the first granule of the address
space, and the ones pattern gives `src_id` a value no source of this bench
carries. The zeros pattern clears `entry_enabled` again before the next entry
is touched.

`locked` is `onwrite = woset`, so only a reset clears it, and a locked entry
steers every later configuration write to the AXI error subordinate, which
terminates it with DECERR. Its leg therefore runs last, after every entry has
completed its field cycle and been restored, and the sequence leaves all 32
entries locked. The refusal is the leg's own checker, and the field cycle that
ran over the same addresses moments earlier is its live control: the entry
accepted those writes and the refused ones leave it reading the locked word.
The entry addresses are registered with the SEP_IN monitor only once the field
cycles are over, so a DECERR during them is still booked.

`START_ADDR` and `END_ADDR` are not written here. Hardware writes a widened
range back into them when the programmed range falls inside one granule, so the
written value is not the value the next read returns.
"""

from __future__ import annotations

import cocotb

from .smc_decode_probe_utils import AXI_RESP_DECERR
from .smc_regblock_field_sweep_utils import RegInstance, SmcRegblockFieldSweepSeq, reg_instances

_FILTER_CONFIG = (
    (
        "smc_inbound_filter_ctrl/FILTER_CONFIG",
        "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR",
        "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_NUM",
        "SMC_INBOUND_FILTER_CTRL_{index}__FILTER_CONFIG_REG_ADDR",
    ),
    (
        "smc_outbound_filter_ctrl/FILTER_CONFIG",
        "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR",
        "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_NUM",
        "SMC_OUTBOUND_FILTER_CTRL_{index}__FILTER_CONFIG_REG_ADDR",
    ),
)

_LOCK_FIELD = "locked"
_ACCESSES_PER_FIELD_CYCLE = 12
_ACCESSES_PER_LOCK_LEG = 6
_PREDICTED_READS_PER_LOCK_LEG = 3


def _lock_mask(inst: RegInstance) -> int:
    for field in inst.reg.fields:
        if field.name == _LOCK_FIELD:
            return field.mask
    raise KeyError(f"{inst.label}: the generated map declares no {_LOCK_FIELD} field")


class smc_filter_config_field_sweep_test_seq(SmcRegblockFieldSweepSeq):
    """Cycle every FILTER_CONFIG field, then set and re-test the write-once lock."""

    def __init__(self, name: str = "smc_filter_config_field_sweep_test_seq") -> None:
        super().__init__(name)
        self.locks_held = 0
        self.denied_resps: list[int] = []

    async def _lock_leg(self, inst: RegInstance) -> None:
        reg = inst.reg
        half = inst.width_bytes // 2
        lock = _lock_mask(inst)
        assert lock & reg.reset_word == 0, (
            f"{inst.label}: the RDL reset already carries {_LOCK_FIELD}, so a write of it "
            f"could not be told from the reset state"
        )
        locked_word = reg.reset_word | lock

        await self.csr_write(f"{inst.label}:lock", inst.addr + half, lock >> (half * 8), half)
        got = await self.csr_read(
            f"{inst.label}:lock_rb", inst.addr, expected=locked_word, length=inst.width_bytes
        )
        assert got & lock == lock, (
            f"{inst.label} @ 0x{inst.addr:08x}: a write of the {_LOCK_FIELD} bit left it at "
            f"0x{got & lock:x}, but the RDL makes it `onwrite = woset`"
        )

        for tag, offset, width, data in (
            ("unlock_try", half, inst.width_bytes - half, 0),
            ("reconfigure_try", 0, half, reg.rw_mask & ((1 << (half * 8)) - 1)),
        ):
            resp = await self.csr_write_expect_error(
                f"{inst.label}:{tag}", inst.addr + offset, data, length=width, resp=AXI_RESP_DECERR
            )
            self.denied_resps.append(resp)
            held = await self.csr_read(
                f"{inst.label}:{tag}_rb",
                inst.addr,
                expected=locked_word,
                length=inst.width_bytes,
            )
            assert held == locked_word, (
                f"{inst.label} @ 0x{inst.addr:08x}: the refused {tag} write left the entry "
                f"at 0x{held:x} instead of the locked 0x{locked_word:x}"
            )
        self.locks_held += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        entries: list[RegInstance] = []
        for spec in _FILTER_CONFIG:
            entries.extend(reg_instances(*spec))
        assert len({inst.addr for inst in entries}) == len(entries), (
            "the generated map gives two filter entries the same FILTER_CONFIG address"
        )
        count = len(entries)

        for inst in entries:
            await self.granule_cycle(inst)
        cocotb.log.info(
            "CHK-FILTER-CONFIG-FIELD-SWEEP: %d filter entries each read their RDL reset, "
            "took the all-ones and all-zeros pattern of every software-writable "
            "FILTER_CONFIG field through half-register writes whose byte lanes over the "
            "other half were deasserted, and were restored to that reset; %d contract "
            "compares",
            count,
            self.value_checks,
        )

        sb_before = self.env.scoreboard.sys_axi_value_checks_seen
        for inst in entries:
            half = inst.width_bytes // 2
            self.env.axi_monitor.expected_decerr_addrs.update({inst.addr, inst.addr + half})
        for inst in entries:
            await self._lock_leg(inst)
        cocotb.log.info(
            "CHK-FILTER-CONFIG-LOCK-WOSET: on each of %d filter entries the write-once "
            "%s field went from clear to set on a write of 1, and the entry then refused "
            "both a write of 0 over that bit and a write of the other half with DECERR "
            "(%d refusals) while still reading the locked word, so the refused writes took "
            "no effect; every write before the lock on the same addresses was accepted",
            self.locks_held,
            _LOCK_FIELD,
            len(self.denied_resps),
        )

        expected = count * (_ACCESSES_PER_FIELD_CYCLE + _ACCESSES_PER_LOCK_LEG)
        self.assert_all_reachable(expected, "FILTER_CONFIG_FIELD_SWEEP")
        assert self.registers_swept == count, (
            f"the sweep completed {self.registers_swept} field cycles for {count} entries"
        )
        assert self.locks_held == count, (
            f"the sweep proved the lock on {self.locks_held} of {count} entries"
        )
        self.assert_value_checks(
            sb_before, count * _PREDICTED_READS_PER_LOCK_LEG, "FILTER_CONFIG_FIELD_SWEEP"
        )
