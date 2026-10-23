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
terminates it with DECERR. Its leg therefore runs after every entry has
completed its field cycle and been restored. The refusal is the leg's own
checker, and the field cycle that ran over the same addresses moments earlier
is its live control: the entry accepted those writes and the refused ones leave
it reading the locked word. The entry addresses are registered with the SEP_IN
monitor only once the field cycles are over, so a DECERR during them is still
booked.

With all 32 entries locked, the bench reset agent applies one cold reset. The
first reads after it hold every entry to the documented field resets of
`filter_ctrl.adoc` (`data_bus_width` 0x3, every other FILTER_CONFIG field 0,
`START_ADDR[55:0]` 0x0, `END_ADDR[55:0]` 0x7) with `locked` clear, and an
`allow_ns` write to each entry then answers OKAY and reads back, so the lock
did not survive the reset. Whether the reserved bits read 0 is open (SF-006):
they are logged and never compared.

`START_ADDR` and `END_ADDR` are not written here. Hardware writes a widened
range back into them when the programmed range falls inside one granule, so the
written value is not the value the next read returns.
"""

from __future__ import annotations

from collections import Counter

import cocotb
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_indexed_addr
from .smc_decode_probe_utils import AXI_RESP_DECERR
from .smc_regblock_field_sweep_utils import RegInstance, SmcRegblockFieldSweepSeq, reg_instances
from .smc_reset_seq_base import SmcResetSeqBase

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
_ACCESSES_PER_COLD_RESET_LEG = 7

# Documented resets, hw/ip/axi_filter/regs/gen/adoc/filter_ctrl.adoc: data_bus_width R 0x3 and
# every other FILTER_CONFIG field 0x0; start_addr[55:0] 0x0; end_addr[55:0] 0x7; locked is bit 63.
_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_CFG_FIELD_RESETS = {
    "locked": 0x0,
    "allow_burst": 0x0,
    "group_id": 0x0,
    "src_id": 0x0,
    "data_bus_width": 0x3,
    "allow_ns": 0x0,
    "entry_enabled": 0x0,
    "write_allowed": 0x0,
    "read_allowed": 0x0,
}
_CFG_MASKS = {
    name: _field_mask(_FILTER_H, f"FILTER_CTRL__FILTER_CONFIG__{name.upper()}_bm")
    for name in _CFG_FIELD_RESETS
}
_CFG_DECLARED = sum(_CFG_MASKS.values())
_LOCKED_BIT = 1 << 63
_ADDR_FIELD = (1 << 56) - 1
_START_RESET = 0x0
_END_RESET = 0x7
_ALLOW_NS_WRITE = _CFG_MASKS["allow_ns"]
_LOWER_HALF_BYTES = 4
_OKAY = 0
FUSE_SENSE_BOUND_SMC_CYCLES = 200_000
_FUSE_PROBES = ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n")
FENCE_ORDER = ("FIELD-SWEEP", "LOCK-ALL", "COLD-RESET", "RESET-WORDS", "WRITABLE")


def _lock_mask(inst: RegInstance) -> int:
    for field in inst.reg.fields:
        if field.name == _LOCK_FIELD:
            return field.mask
    raise KeyError(f"{inst.label}: the generated map declares no {_LOCK_FIELD} field")


def _field(word: int, mask: int) -> int:
    return (word & mask) >> ((mask & -mask).bit_length() - 1)


def _cfg_fields(word: int) -> dict[str, int]:
    return {name: _field(word, mask) for name, mask in _CFG_MASKS.items()}


def _probe_levels() -> str:
    return " ".join(f"{name}={getattr(cocotb.top, name).value}" for name in _FUSE_PROBES)


class smc_filter_config_field_sweep_test_seq(SmcResetSeqBase, SmcRegblockFieldSweepSeq):
    """Cycle every FILTER_CONFIG field, set the write-once lock, then clear it by cold reset."""

    def __init__(self, name: str = "smc_filter_config_field_sweep_test_seq") -> None:
        super().__init__(name)
        self.locks_held = 0
        self.denied_resps: list[int] = []
        self.dispatch_reset = None
        self.locked_before_reset: dict[int, int] = {}
        self.fence: list[tuple[str, int, int]] = []
        self.reset_words_read = 0
        self.writable_entries = 0

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        await self.dispatch_reset(item)

    def _stamp(self, term: str, count: int) -> None:
        self.fence.append((term, int(get_sim_time("ps")), count))

    async def _access(self, label: str, addr: int, op: SmcSysAxiOp, length: int, data: int = 0):
        item = SmcSysAxiItem(f"{'rd' if op == SmcSysAxiOp.READ else 'wr'}_{label}")
        item.op, item.addr, item.length = op, addr, length
        if op == SmcSysAxiOp.WRITE:
            item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == _OKAY, (
            f"{label} @ 0x{addr:08x}: resp={item.resp_code}, the register answers OKAY"
        )
        return int(item.rdata)

    async def _read64(self, label: str, addr: int) -> int:
        return await self._access(label, addr, SmcSysAxiOp.READ, 8)

    def _check_cfg(self, label: str, addr: int, word: int, want: dict[str, int]) -> None:
        got = _cfg_fields(word)
        bad = {name: got[name] for name in want if got[name] != want[name]}
        assert not bad, (
            f"{label} @ 0x{addr:08x}: FILTER_CONFIG 0x{word:016x} has fields {bad}, "
            f"filter_ctrl.adoc gives {want}"
        )

    async def _fuse_sense_after_reset(self) -> None:
        at_release = _probe_levels()
        try:
            await self.wait_fuse_sense_done(FUSE_SENSE_BOUND_SMC_CYCLES)
        except AssertionError as exc:
            raise AssertionError(
                f"post-cold-reset fuse sense: {exc}; bound={FUSE_SENSE_BOUND_SMC_CYCLES} "
                f"smc cycles; last {_probe_levels()}"
            ) from exc
        for name in _FUSE_PROBES:
            sig = getattr(cocotb.top, name).value
            assert sig.is_resolvable and int(sig) == 1, f"{name} reads {sig} after the wait"
        self._timeout_paths.append(
            f"post_reset_fuse_sense: bound={FUSE_SENSE_BOUND_SMC_CYCLES} smc_cycles, expiry raises "
            f"AssertionError with the last probe levels; at release {at_release}; "
            f"done {_probe_levels()}"
        )

    async def _cold_reset(self) -> None:
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            "cold_assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released("cold_release")
        await self._fuse_sense_after_reset()

    async def _reset_words(
        self, entries: list[RegInstance], siblings: dict[int, tuple[int, int]]
    ) -> tuple[list[int], Counter, Counter, Counter]:
        unlocked: list[int] = []
        cfg_rsvd: Counter = Counter()
        start_rsvd: Counter = Counter()
        end_rsvd: Counter = Counter()
        for inst in entries:
            start_addr, end_addr = siblings[inst.addr]
            cfg = await self._read64(f"{inst.label}:post_reset_cfg", inst.addr)
            start = await self._read64(f"{inst.label}:post_reset_start", start_addr)
            end = await self._read64(f"{inst.label}:post_reset_end", end_addr)
            assert cfg & _LOCKED_BIT == 0, (
                f"{inst.label} @ 0x{inst.addr:08x}: still locked after the cold reset "
                f"(FILTER_CONFIG 0x{cfg:016x})"
            )
            unlocked.append(inst.addr)
            self._check_cfg(inst.label, inst.addr, cfg, _CFG_FIELD_RESETS)
            assert start & _ADDR_FIELD == _START_RESET, (
                f"{inst.label} START_ADDR @ 0x{start_addr:08x}: [55:0] reads "
                f"0x{start & _ADDR_FIELD:x}, filter_ctrl.adoc gives 0x{_START_RESET:x}"
            )
            assert end & _ADDR_FIELD == _END_RESET, (
                f"{inst.label} END_ADDR @ 0x{end_addr:08x}: [55:0] reads "
                f"0x{end & _ADDR_FIELD:x}, filter_ctrl.adoc gives 0x{_END_RESET:x}"
            )
            cfg_rsvd[cfg & ~_CFG_DECLARED] += 1
            start_rsvd[start & ~_ADDR_FIELD] += 1
            end_rsvd[end & ~_ADDR_FIELD] += 1
            self.reset_words_read += 1
        return unlocked, cfg_rsvd, start_rsvd, end_rsvd

    async def _writable(self, entries: list[RegInstance]) -> None:
        set_ns = dict(_CFG_FIELD_RESETS, allow_ns=1)
        for inst in entries:
            await self._access(
                f"{inst.label}:allow_ns",
                inst.addr,
                SmcSysAxiOp.WRITE,
                _LOWER_HALF_BYTES,
                _ALLOW_NS_WRITE,
            )
            got = await self._read64(f"{inst.label}:allow_ns_rb", inst.addr)
            self._check_cfg(inst.label, inst.addr, got, set_ns)
            await self._access(
                f"{inst.label}:restore", inst.addr, SmcSysAxiOp.WRITE, _LOWER_HALF_BYTES, 0
            )
            got = await self._read64(f"{inst.label}:restore_rb", inst.addr)
            self._check_cfg(inst.label, inst.addr, got, _CFG_FIELD_RESETS)
            self.writable_entries += 1

    def _nonvac_fence(self, count: int) -> None:
        order = [term for term, _, _ in self.fence]
        assert order == list(FENCE_ORDER), f"fence order {order}, want {list(FENCE_ORDER)}"
        stamps = [t for _, t, _ in self.fence]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"fence stamps {stamps}"
        want = {"COLD-RESET": 1}
        for term, _, n in self.fence:
            assert n == want.get(term, count), f"fence term {term} count {n}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; %s",
            " < ".join(order),
            ", ".join(f"{term} n={n} t={t}ps" for term, t, n in self.fence),
        )

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
        self.locked_before_reset[inst.addr] = held
        self.locks_held += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        entries: list[RegInstance] = []
        siblings: dict[int, tuple[int, int]] = {}
        for spec in _FILTER_CONFIG:
            insts = reg_instances(*spec)
            entries.extend(insts)
            for inst in insts:
                siblings[inst.addr] = tuple(
                    smc_indexed_addr(spec[1].replace("_FILTER_CONFIG_", f"_{reg}_"), inst.index)
                    for reg in ("START_ADDR", "END_ADDR")
                )
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
        self._stamp("FIELD-SWEEP", self.registers_swept)

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
        self._stamp("LOCK-ALL", self.locks_held)

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

        assert _CFG_MASKS["locked"] == _LOCKED_BIT, (
            f"the generated map places locked at 0x{_CFG_MASKS['locked']:x}, "
            f"filter_ctrl.adoc at bit 63"
        )
        pre_locked = [w for w in self.locked_before_reset.values() if w & _LOCKED_BIT]
        assert len(self.locked_before_reset) == count and len(pre_locked) == count, (
            f"{len(pre_locked)} of {count} entries read locked=1 before the cold reset"
        )
        await self._cold_reset()
        monitor = self.env.axi_monitor
        decerr_addrs = {
            a for inst in entries for a in (inst.addr, inst.addr + inst.width_bytes // 2)
        }
        assert decerr_addrs <= monitor.expected_decerr_addrs, (
            "the lock leg's DECERR addresses are not all registered with the monitor"
        )
        monitor.expected_decerr_addrs.difference_update(decerr_addrs)
        self._stamp("COLD-RESET", 1)

        unlocked, cfg_rsvd, start_rsvd, end_rsvd = await self._reset_words(entries, siblings)
        self._stamp("RESET-WORDS", self.reset_words_read)
        for leg, text in (
            ("set", f"locked=1 written on {self.locks_held} entries"),
            ("observed", f"locked read 1 on {len(pre_locked)} entries before the cold reset"),
            ("cleared", "cold reset asserted (COLD_RST_LO) and released (COLD_RST_HI)"),
            ("checked_cleared", f"locked read 0 on {len(unlocked)} entries on the first read"),
        ):
            cocotb.log.info("LIFECYCLE CHK-FILTER-COLD-RESET-UNLOCK %s: %s", leg, text)
        assert len(unlocked) == count, f"{len(unlocked)} of {count} entries read unlocked"
        cocotb.log.info(
            "CHK-FILTER-COLD-RESET-UNLOCK: pre-reset locked=1 on %d/%d, post-reset locked=0 "
            "(FILTER_CONFIG bit 63) on %d/%d on the first read after the cold reset",
            len(pre_locked),
            count,
            len(unlocked),
            count,
        )

        def _rsvd(tally: Counter) -> str:
            return ",".join(f"0x{v:x} on {n}" for v, n in sorted(tally.items()))

        cocotb.log.info(
            "CHK-FILTER-COLD-RESET-WORDS: %d/%d entries cfg fields reset (dbw=3, locked, "
            "allow_burst, group_id, src_id, allow_ns, entry_enabled, write_allowed, "
            "read_allowed = 0), start[55:0]=0x%x, end[55:0]=0x%x, all 64-bit reads OKAY; "
            "reserved bits logged (SF-006, not compared): cfg %s start %s end %s",
            self.reset_words_read,
            count,
            _START_RESET,
            _END_RESET,
            _rsvd(cfg_rsvd),
            _rsvd(start_rsvd),
            _rsvd(end_rsvd),
        )

        await self._writable(entries)
        self._stamp("WRITABLE", self.writable_entries)
        cocotb.log.info(
            "CHK-FILTER-COLD-RESET-WRITABLE: %d/%d allow_ns writes OKAY, %d/%d readbacks "
            "allow_ns=1 with every other field at its reset, %d/%d restores at reset",
            self.writable_entries,
            count,
            self.writable_entries,
            count,
            self.writable_entries,
            count,
        )

        total = count * (
            _ACCESSES_PER_FIELD_CYCLE + _ACCESSES_PER_LOCK_LEG + _ACCESSES_PER_COLD_RESET_LEG
        )
        self.assert_all_reachable(total, "FILTER_CONFIG_COLD_RESET")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, 0 expired: %s",
            len(self._timeout_paths),
            "; ".join(self._timeout_paths),
        )
        self._nonvac_fence(count)
