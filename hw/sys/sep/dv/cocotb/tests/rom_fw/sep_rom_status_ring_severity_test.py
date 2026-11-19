# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secondary boot that fails at the manifest with a small valid status ring: severity reserves.

rom.adoc, Status Reporting, Ring-Buffer Semantics:

    [SEP-ROM-STAT-020] Capacity shall be reserved by severity so an error can always be
    recorded: `INFO`-class inserts require 3 free slots and degrade to an `INFO_OVERFLOW`
    marker at exactly 3; `WARN` requires 2, degrading to `WARNING_OVERFLOW`; `ERROR` inserts
    down to the last free slot.

rom.adoc, Status output channels and Status Ring Buffer:

    Status ring | SMC SRAM (offset from scratch[11]) | Every non-`DEBUG` status, consumed by
    the SMC and forwarded to the platform (OCCP).

    When status reporting is enabled, the ROM initializes a produce-only ring buffer in SMC
    SRAM at the offset published in scratch[11] and thereafter mirrors every non-debug status
    code into it.

The SEP ROM docs give no ring layout. The leaf infers it: `head` at offset 0, `tail` at 4,
`num_entries` at 8, the 32-bit entries from offset 12, and `head` a slot index. The SMC ROM
docs (hw/sys/smc/bootrom/prod/doc/status-coordination.adoc, Ring buffers) name the same fields,
and the SMC DV ring struct (hw/sys/smc/dv/fw/include/smc_ring_buffer.h) has this order with
`head` as the write index. The retention rule, its inferences and the overflow-marker codes
are in `sep_rom_status_ring_model`. The leaf publishes a ring of 8 entries with head = tail = 0
at SMC SRAM offset `0x000F0000`, outside the packed SMC image, and nothing drains it. The inherited secondary boot refuses the manifest at
offset `0x5000`, so the ROM offers many INFO statuses before the manifest WARN and the two
ERRORs.

* CHK-RING-SEVERITY-RESERVE: at the end of the run, `entries[0..k)` equal
  `expected_ring(offered, 8)` (k entries), `head` is k and the slots past k still hold the
  leaf's fill words. `offered` is every non-DEBUG `cold_scratch[1]` word recorded after the
  ROM's first scratch[11] read.

Not covered: "so an error can always be recorded" against a consumer that advances `tail`, and
a ring that wraps; in simulation the WARN insert and WARN drop branches are not reached (the
model's self-test covers them).
"""

from __future__ import annotations

import pyuvm
from env.sep_chk_log import SepChkLog
from env.sep_fabric_tap import SepFabricTap
from env.sep_rom_observer import SepRomObserver
from rom_fw.sep_firmware_secondary_chiplet_bootcode_primary_manifest_invalid_test import (
    sep_firmware_secondary_chiplet_bootcode_primary_manifest_invalid_test as _Base,
)
from rom_fw.sep_rom_status_ring_model import (
    INFO_OVERFLOW,
    TYPE_DEBUG,
    TYPE_ERROR,
    TYPE_WARN,
    WARNING_OVERFLOW,
    entry_matches,
    expected_ring,
    kind,
    ring_trace,
)
from rom_fw.sep_secondary_chiplet_base import SMC_SRAM_BASE
from sep_reg_meta import sym

_SCRATCH11 = 0x4000_0000 + 0x39080 + 8 * 11
_RING_OFFSET = 0x000F_0000
_RING = SMC_SRAM_BASE + _RING_OFFSET
_NUM_ENTRIES = 8
_HEADER_BYTES = 12
_ENTRIES = _RING + _HEADER_BYTES
_ENTRIES_END = _ENTRIES + 4 * _NUM_ENTRIES
_FILL = 0x5E5E_0000
_INVALID_ID_CODE = (1 << 16) | 0x0079
_ID_CODE_MASK = 0x00FF_FFFF
_COLD_1 = sym("SEP_SCRATCH_COLD_SCRATCH_1__REG_ADDR")


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


@pyuvm.test()
class sep_rom_status_ring_severity_test(_Base):
    required_evidence = ("CHK-RING-SEVERITY-RESERVE",)

    def prepare_smc_mem(self) -> None:
        super().prepare_smc_mem()
        mem = self.cfg.smc_mem
        assert mem is not None, (
            "the rom_boot target did not bind its SMC responder; run this leaf on the rom_boot "
            "target, which sets cfg.smc_mem"
        )
        mem.write32(_SCRATCH11, _RING_OFFSET)
        for i, word in enumerate((0, 0, _NUM_ENTRIES)):
            mem.write32(_RING + 4 * i, word)
        for i in range(_NUM_ENTRIES):
            mem.write32(_ENTRIES + 4 * i, _FILL | i)

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        # The observer and the taps start before reset release so the first status store is recorded.
        self.obs = SepRomObserver(self, keep=lambda _insn: False, tracker=False).start()
        self.smc = SepFabricTap("PR-SMC").start()
        self.lsu = SepFabricTap("PR-LSU-XBAR").start()
        smc_mark, lsu_mark = self.smc.mark(), self.lsu.mark()
        base_err = None
        try:
            await super().run_scenario()
        except AssertionError as err:
            base_err = err
        await self.obs.stop()
        await self.smc.stop()
        await self.lsu.stop()
        mem = self.cfg.smc_mem
        self.header = tuple(mem.read32(_RING + 4 * i) for i in range(3))
        self.entries = [mem.read32(_ENTRIES + 4 * i) for i in range(_NUM_ENTRIES)]
        self._grade(
            self.smc.since(smc_mark, "ar"),
            self.smc.since(smc_mark, "aw"),
            self.lsu.since(lsu_mark, "aw"),
            base_err,
        )
        self.chk.finish()

    def _grade(self, smc_ar: list, smc_aw: list, lsu_aw: list, base_err) -> None:
        chk, obs = self.chk, self.obs

        chk.ctrl(
            "SCENARIO",
            base_err is None and obs.verdict_pass() is False,
            base_error=str(base_err or "none"),
            verdict=_hex(obs.verdict[-1][1] if obs.verdict else None),
        )

        # Every status store must leave its own record, or the offered sequence lost a repeat.
        unknown = sum(1 for b in lsu_aw if b.addr is None)
        stores = [b for b in lsu_aw if b.addr is not None and b.addr & ~3 == _COLD_1]
        records = obs.status[1:]
        chk.ctrl(
            "STATUS-NO-COLLAPSE",
            bool(stores)
            and not unknown
            and len(stores) == len(records)
            and obs.status[0][0] < stores[0].t_ps,
            status_stores=len(stores),
            status_records=len(records),
            initial=_hex(obs.status[0][1] if obs.status else None),
            aw_unknown=unknown,
        )

        s11 = [b.t_ps for b in smc_ar if b.addr is not None and b.addr & ~7 == _SCRATCH11]
        t11 = s11[0] if s11 else None
        after = [(t, w) for t, w in obs.status if t11 is not None and t > t11]
        offered = [w for _, w in after if kind(w) != TYPE_DEBUG]
        invalid = [w for w in offered if w & _ID_CODE_MASK == _INVALID_ID_CODE]
        entry_aw = [b for b in smc_aw if b.addr is not None and _ENTRIES <= b.addr < _ENTRIES_END]
        head_aw = [b for b in smc_aw if b.addr is not None and b.addr & ~3 == _RING]
        chk.ctrl(
            "RING-ACCEPTED",
            t11 is not None and bool(entry_aw) and bool(head_aw) and not invalid,
            scratch11_read_ps=t11 or -1,
            scratch11_reads=len(s11),
            entry_writes=len(entry_aw),
            head_writes=len(head_aw),
            invalid_reports=len(invalid),
        )

        head, tail, num = self.header
        chk.ctrl(
            "RING-UNDRAINED",
            tail == 0 and num == _NUM_ENTRIES,
            tail=_hex(tail),
            num_entries=_hex(num),
        )

        # The INFO-class reserve is reached after num_entries - 3 INFO-class offers.
        severe = [i for i, w in enumerate(offered) if kind(w) in (TYPE_WARN, TYPE_ERROR)]
        first_severe = severe[0] if severe else len(offered)
        warns = [w for w in offered if kind(w) == TYPE_WARN]
        errors = [w for w in offered if kind(w) == TYPE_ERROR]
        chk.ctrl(
            "RING-FILLED",
            len(offered) > _NUM_ENTRIES
            and first_severe >= _NUM_ENTRIES - 3
            and bool(warns)
            and bool(errors),
            offered=len(offered),
            info_class_before_first_warn_or_error=first_severe,
            warns=[_hex(w) for w in warns],
            errors=[_hex(w) for w in errors],
        )

        try:
            trace = ring_trace(offered, _NUM_ENTRIES)
            exp = expected_ring(offered, _NUM_ENTRIES)
            model_err = ""
        except ValueError as err:
            trace, exp, model_err = [], [], str(err)
        k = len(exp)
        got = self.entries
        chk.ok(
            "RING-SEVERITY-RESERVE",
            not model_err
            and k < _NUM_ENTRIES
            and all(entry_matches(got[i], exp[i]) for i in range(k))
            and all(got[i] == _FILL | i for i in range(k, _NUM_ENTRIES))
            and head == k,
            head=_hex(head),
            tail=_hex(tail),
            expected_head=k,
            got=[_hex(w) for w in got],
            expected=[_hex(w) for w in exp],
            model_error=model_err or "none",
        )
        chk.obs(
            "RING-TRACE",
            actions=[f"{_hex(w)}:{a}" for w, a, _ in trace if a != "drop"]
            + [f"drops={sum(1 for _, a, _ in trace if a == 'drop')}"],
            first_offered_ps=after[0][0] if after else -1,
        )
        chk.obs(
            "MARKER-TYPES",
            types=[
                f"0x{got[i] >> 24:02x}"
                for i in range(k)
                if exp[i] & 0xFFFF in (INFO_OVERFLOW, WARNING_OVERFLOW)
            ],
        )
