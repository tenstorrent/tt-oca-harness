# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Filter multi-entry sweep.

RTL exposes 16 inbound + 16 outbound filter entries; this sweep covers every
one of the 32 slots.

Each of the 32 slots is proven *individually discriminable*, not merely
"a window that answers 0x3000": every slot gets a signature value unique to
(direction, index), and the sweep is PHASED so that the 32 signatures are
CO-RESIDENT when they are read back.

Phasing is the whole point. A per-slot write/readback/restore cycle proves
nothing about aliasing: only one slot is ever non-default at a time, so an RTL
that mapped all 32 windows onto one physical register would return the value
just written through the very same address and pass. Here phase 2 programs all
32 slots without restoring any of them, and phase 3 reads all 32 back while
all 32 are still resident -- so a read of slot i can only return sig_i if slot
i has storage of its own. Under total aliasing the register holds sig_31 when
phase 3 starts and the very first readback fails; under any partial aliasing
of two windows the later-written one overwrites the earlier and that slot's
readback fails.

Phase 1 checks the RDL reset content of every window before anything is
written, and phases 4/5 restore and re-confirm the RDL default, so the run
also carries reset-value evidence for every slot.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_addr_map import _REPO, reg_field_encode
from .smc_csr_seq_utils import SmcCsrSeq

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    SMC_INBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_1__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_2__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_3__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_4__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_5__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_6__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_7__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_8__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_9__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_10__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_11__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_12__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_13__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_14__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_15__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_1__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_2__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_3__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_4__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_5__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_6__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_7__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_8__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_9__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_10__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_11__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_12__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_13__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_14__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_15__FILTER_CONFIG_REG_ADDR,
)

# PeakRDL-traceable FILTER_CONFIG addresses (filter_ctrl.rdl) and RDL reset
# (FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT). Per slot the sweep checks
# the full 64-bit RDL reset content, then a (direction,index)-unique signature
# read back at that offset WHILE THE OTHER 31 SIGNATURES ARE STILL RESIDENT --
# so slot i's evidence cannot be produced by slot j -- then the restored reset
# content.
_INBOUND_FILTER_CONFIG = (
    SMC_INBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_1__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_2__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_3__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_4__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_5__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_6__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_7__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_8__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_9__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_10__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_11__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_12__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_13__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_14__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_15__FILTER_CONFIG_REG_ADDR,
)
_OUTBOUND_FILTER_CONFIG = (
    SMC_OUTBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_1__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_2__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_3__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_4__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_5__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_6__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_7__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_8__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_9__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_10__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_11__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_12__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_13__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_14__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_15__FILTER_CONFIG_REG_ADDR,
)


_FILTER_CTRL_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"

#: Accesses issued per slot, spread over the five phases: reset read,
#: signature write, co-resident signature readback, restore write, restore
#: readback.
_ACCESSES_PER_SLOT = 5
#: Reads carrying an ``expected=`` (the scoreboard books one value check each).
_VALUE_CHECKS_PER_SLOT = 3


def _slot_signature(index: int, outbound: bool) -> int:
    """FILTER_CONFIG value unique to (direction, slot index).

    Field positions come from the generated PeakRDL layout
    (``FILTER_CTRL_FILTER_CONFIG_reg_t``), never from hand-written shifts.
    Only ``sw=rw`` fields whose ``filter_ctrl.rdl`` reset is 0 are driven --
    ``read_allowed``/``write_allowed`` encode the direction and
    ``src_id``/``group_id`` encode the index in two independent nibbles that
    move in opposite directions, so no two of the 32 slots share a value.
    ``entry_enabled``, ``allow_ns``, ``allow_burst`` and the write-once
    ``locked`` are left at their reset value: the sweep must not arm or lock a
    filter. ``data_bus_width`` is ``sw=r``, which is why the expected readback
    is the RDL default OR-ed with the signature.
    """
    return reg_field_encode(
        _FILTER_CTRL_H,
        "FILTER_CTRL",
        "FILTER_CONFIG",
        read_allowed=0 if outbound else 1,
        write_allowed=1 if outbound else 0,
        src_id=index & 0xF,
        group_id=(15 - index) & 0xF,
    )


class smc_filter_multi_entry_test_seq(SmcCsrSeq):
    def __init__(self, name: str = "smc_filter_multi_entry_test_seq") -> None:
        super().__init__(name)
        #: Scoreboard-measured exact-value compares booked by this sweep.
        self.value_checks_measured = 0

    @staticmethod
    def _slot_table() -> list[tuple[str, int, int, int]]:
        """(label, index, addr, signature) for all 32 slots, host-side.

        The signature is derived in Python from the generated RDL default and
        the generated field layout before any access is issued; nothing on this
        path reads the DUT, so the readback expectation is never a self-compare.
        """
        default = FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT
        table: list[tuple[str, int, int, int]] = []
        for i, addr in enumerate(_INBOUND_FILTER_CONFIG):
            table.append(("INBOUND_FILTER", i, addr, default | _slot_signature(i, outbound=False)))
        for i, addr in enumerate(_OUTBOUND_FILTER_CONFIG):
            table.append(("OUTBOUND_FILTER", i, addr, default | _slot_signature(i, outbound=True)))
        return table

    async def body(self) -> None:
        sb = self.env.scoreboard
        value_checks_before = sb.sys_axi_value_checks_seen
        default = FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT

        table = self._slot_table()
        slots = len(table)
        # Pre-condition of the whole co-residency argument: if two slots were
        # given the same signature, "slot i's readback can only be produced by
        # slot i" would already be false host-side, before the DUT is involved.
        assert len({sig for _, _, _, sig in table}) == slots, (
            "filter_multi_entry: the 32 slot signatures are not pairwise "
            "distinct, so a co-resident readback would not discriminate slots"
        )
        assert len({addr for _, _, addr, _ in table}) == slots, (
            "filter_multi_entry: the 32 FILTER_CONFIG addresses are not pairwise distinct"
        )

        # PHASE 1 -- RDL reset content of every window, before anything is
        # written anywhere.
        for label, index, addr, _sig in table:
            await self.csr_read(f"{label}_{index}_CONFIG", addr, expected=default, length=8)

        # PHASE 2 -- program ALL 32 slots and restore NONE of them, so that at
        # the end of this phase the 32 distinct signatures are simultaneously
        # resident in the DUT.
        for label, index, addr, sig in table:
            await self.csr_write(f"{label}_{index}_CONFIG_SIG", addr, sig, length=8)

        # PHASE 3 -- the slot-identity proof. Every readback happens while the
        # other 31 slots still hold their own distinct signatures, so a window
        # aliased onto another slot returns that slot's signature and the
        # scoreboard's exact 64-bit compare fails. Under total aliasing the
        # shared register holds the LAST signature written in phase 2, so the
        # very first readback here fails.
        for label, index, addr, sig in table:
            await self.csr_read(f"{label}_{index}_CONFIG_SIG", addr, expected=sig, length=8)

        # PHASE 4/5 -- restore the RDL reset content everywhere, readback
        # confirmed, so the sweep leaves no filter CSR perturbed.
        for label, index, addr, _sig in table:
            await self.csr_write(f"{label}_{index}_CONFIG_RESTORE", addr, default, length=8)
        for label, index, addr, _sig in table:
            await self.csr_read(f"{label}_{index}_CONFIG_RESTORE", addr, expected=default, length=8)

        expected_accesses = slots * _ACCESSES_PER_SLOT
        expected_value_checks = slots * _VALUE_CHECKS_PER_SLOT

        # Loop integrity + the scoreboard cross-check that the traffic really
        # reached an independent observer.
        self.assert_all_reachable(expected_accesses, "filter_multi_entry")

        # Minimum-activity gate on the aggregate that carries the whole proof:
        # the scoreboard books a value check only AFTER an exact rdata compare
        # passed, so a mis-bound analysis path (or a leg that lost its
        # `expected=`) fails here instead of passing on zero compares.
        self.value_checks_measured = sb.sys_axi_value_checks_seen - value_checks_before
        assert self.value_checks_measured >= expected_value_checks, (
            f"filter_multi_entry: scoreboard booked only "
            f"{self.value_checks_measured} SEP_IN AXI exact-value compares, "
            f"expected at least {expected_value_checks} "
            f"({slots} slots x {_VALUE_CHECKS_PER_SLOT}: RDL reset, per-slot "
            f"signature readback, restore readback)"
        )
        cocotb.log.info(
            "CHK-FILTER-MULTI-ENTRY-SLOT-IDENTITY: %d filter slots each "
            "proved by a (direction,index)-unique FILTER_CONFIG signature "
            "read back at its own offset WHILE ALL %d SIGNATURES ARE "
            "CO-RESIDENT (phase 2 programs every slot and restores none; "
            "phase 3 reads every slot back), so a decode that aliased two or "
            "more windows onto one physical register returns a neighbour's "
            "signature and fails the scoreboard's exact 64-bit compare; "
            "scoreboard booked %d >= %d exact-value compares (independent "
            "observer, not the sequence's own access counter)",
            slots,
            slots,
            self.value_checks_measured,
            expected_value_checks,
        )
