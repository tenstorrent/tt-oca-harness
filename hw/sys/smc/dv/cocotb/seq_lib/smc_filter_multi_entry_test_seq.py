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

After the CONFIG sweep the same SEP_IN manager drives the AXI-Lite front ends
of every filter entry block, every alias, M-mode and Xvisor remap region block
and the peripheral-crossbar targets that answer on this bench:

* a co-resident register sweep of START_ADDR / END_ADDR and every remap
  register, patterns encoding (family, instance, register) in RW field bits
  only, valid and locked never set;
* per block an outstanding group of eight writes and eight reads, then a
  reads-only group of depth 2;
* per block a write and a read of one register presented together, the AW/AR
  skew rotating over AW first, AR first and the same cycle;
* per block sixteen reads under a 32-cycle RREADY hold, then sixteen
  write-backs under a 32-cycle BREADY hold, deep enough that the responses back
  up behind the crossbar in front of the block;
* per peripheral target a read, a write-back of the value read and a second
  read, then a depth-16 outstanding group, two depth-16 groups spread over all
  targets, an overlapped pair and the same two 16-deep held groups;
* a restore of every touched register to its RDL reset in writes-only groups of
  depth 3 and 1, read back.

Every expected value is the RDL reset, a value this sequence wrote, or the
value the same register returned in the single-access leg of a write-back.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp
from ocah_axi_vip import AxiTimingProfile

from .smc_addr_map import _REPO, reg_field_encode, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import rdl_contract

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

import smc_reg  # noqa: E402
from smc_reg import (  # noqa: E402
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_END_ADDR_REG_FIELDS,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_FIELDS,
    OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    OUTPUT_REMAP_REGION_REGION_ATTRS_REG_FIELDS,
    REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    REMAP_REGION_REGION_ATTRS_REG_FIELDS,
    REMAP_REGION_REGION_END_REG_DEFAULT,
    REMAP_REGION_REGION_END_REG_FIELDS,
    REMAP_REGION_REGION_START_REG_DEFAULT,
    REMAP_REGION_REGION_START_REG_FIELDS,
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


#: Fields a pattern never sets: `valid` arms a remap region and `locked` is
#: write-once-set, so writing either would change what the fabric does.
_GUARDED_FIELDS = frozenset({"valid", "locked"})


def _rw_mask(fields: tuple) -> int:
    """Mask of the software-writable field bits of a generated register layout."""
    mask = 0
    for name, lsb, msb, sw, *_rest in fields:
        if sw == "rw" and name not in _GUARDED_FIELDS:
            mask |= ((1 << (msb - lsb + 1)) - 1) << lsb
    return mask


def _reg_addr(prefix: str, index: int, reg: str) -> int:
    return getattr(smc_reg, f"SMC_{prefix}_{index}__{reg}_REG_ADDR")


class _Reg:
    """One 64-bit register of a block: address, reset and RW mask."""

    def __init__(self, label: str, addr: int, reset: int, mask: int) -> None:
        self.label = label
        self.addr = addr
        self.reset = reset
        self.mask = mask


class _Block:
    """One register block of a family, with its writable registers."""

    def __init__(self, family: _Family, index: int) -> None:
        self.family = family
        self.index = index
        self.label = f"{family.token}{index}"
        self.writable: list[_Reg] = []
        self.config: _Reg | None = None


class _Family:
    """A family of identical register blocks reached through one demux."""

    def __init__(self, token: str, chk: str, code: int) -> None:
        self.token = token
        self.chk = chk
        self.code = code
        self.blocks: list[_Block] = []


#: Family codes put in pattern bits [55:52]; each family gets its own.
_FAMILY_CODES = {"IB": 1, "OB": 2, "AL": 3, "MM": 4, "XV": 5}
#: Pattern phase codes, bits [44:41]: one per step that writes; the outstanding
#: group's eight writes take _PH_GROUP + 0..7.
_PH_SWEEP, _PH_OVERLAP, _PH_GROUP = 1, 4, 6


def _families() -> list[_Family]:
    start_mask = _rw_mask(FILTER_CTRL_START_ADDR_REG_FIELDS)
    end_mask = _rw_mask(FILTER_CTRL_END_ADDR_REG_FIELDS)
    fams: list[_Family] = []
    for token, prefix, chk in (
        ("IB", "INBOUND_FILTER_CTRL", "CHK-HS-FILTER-IB"),
        ("OB", "OUTBOUND_FILTER_CTRL", "CHK-HS-FILTER-OB"),
    ):
        fam = _Family(token, chk, _FAMILY_CODES[token])
        for i in range(16):
            blk = _Block(fam, i)
            blk.config = _Reg(
                f"{blk.label}_CONFIG",
                _reg_addr(prefix, i, "FILTER_CONFIG"),
                FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
                0,
            )
            blk.writable = [
                _Reg(
                    f"{blk.label}_START",
                    _reg_addr(prefix, i, "START_ADDR"),
                    FILTER_CTRL_START_ADDR_REG_DEFAULT,
                    start_mask,
                ),
                _Reg(
                    f"{blk.label}_END",
                    _reg_addr(prefix, i, "END_ADDR"),
                    FILTER_CTRL_END_ADDR_REG_DEFAULT,
                    end_mask,
                ),
            ]
            fam.blocks.append(blk)
        fams.append(fam)
    alias = _Family("AL", "CHK-HS-ALIAS-REGS", _FAMILY_CODES["AL"])
    for i in range(8):
        blk = _Block(alias, i)
        for reg, reset, fields in (
            (
                "REGION_START",
                REMAP_REGION_REGION_START_REG_DEFAULT,
                REMAP_REGION_REGION_START_REG_FIELDS,
            ),
            ("REGION_END", REMAP_REGION_REGION_END_REG_DEFAULT, REMAP_REGION_REGION_END_REG_FIELDS),
            (
                "REGION_ATTRS",
                REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                REMAP_REGION_REGION_ATTRS_REG_FIELDS,
            ),
        ):
            blk.writable.append(
                _Reg(
                    f"{blk.label}_{reg}",
                    _reg_addr("ALIAS_REMAP", i, f"REGION_{reg}"),
                    reset,
                    _rw_mask(fields),
                )
            )
        alias.blocks.append(blk)
    fams.append(alias)
    ormp_mask = _rw_mask(OUTPUT_REMAP_REGION_REGION_ATTRS_REG_FIELDS)
    for token, prefix, chk in (
        ("MM", "MMODE_REMAP", "CHK-HS-ORMP-MMODE"),
        ("XV", "XVISOR_REMAP", "CHK-HS-ORMP-XVISOR"),
    ):
        fam = _Family(token, chk, _FAMILY_CODES[token])
        for i in range(8):
            blk = _Block(fam, i)
            blk.writable = [
                _Reg(
                    f"{blk.label}_ATTRS",
                    _reg_addr(prefix, i, "REGION_REGION_ATTRS"),
                    OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                    ormp_mask,
                )
            ]
            fam.blocks.append(blk)
        fams.append(fam)
    return fams


def _pattern(blk: _Block, reg_index: int, phase: int, reg: _Reg) -> int:
    """Value unique to (family, instance, register, phase), inside the RW mask.

    The family, instance, register and phase sit in bits [55:41], which every
    RW mask here keeps whole, so two patterns never collide after masking; bits
    [59:56] reach only the alias cacheable field. The
    register index alone makes a filter's START_ADDR and END_ADDR patterns
    differ above bit 12, so the two always lie in different granules of either
    size and the same-granule write-back never applies.
    """
    raw = (
        (blk.family.code << 52)
        | (blk.index << 47)
        | ((reg_index + 1) << 45)
        | (phase << 41)
        | (((blk.index * 0x9E37 + reg_index * 0x7F4B + phase * 0x3C6F) & 0xF_FFFF_FFFF) << 4)
        | (((blk.index + phase) & 0xF) << 56)
    )
    return raw & reg.mask


# AW/AR skews of an overlapped pair, rotated over the blocks of each family.
_SKEW = 4
_SKEWS: tuple[tuple[str, AxiTimingProfile | None, bool], ...] = (
    ("aw_first", AxiTimingProfile(ar_delay=_SKEW), True),
    ("ar_first", AxiTimingProfile(aw_delay=_SKEW), False),
    ("same_cycle", None, True),
)
# Held groups: sixteen reads behind a held RREADY, then sixteen write-backs
# behind a held BREADY.
_HOLD_DEPTH = 16
_READY_HOLD = 32
_R_HOLD = AxiTimingProfile(r_ready_delay=_READY_HOLD)
_B_HOLD = AxiTimingProfile(b_ready_delay=_READY_HOLD)
# Outstanding group: eight writes interleaved with eight reads.
_GROUP_WRITES = 8
# Depth of each peripheral-crossbar outstanding group, and the number of groups
# spread over all targets.
_PX_DEPTH = 16
_PX_SPREAD_GROUPS = 2

# Peripheral-crossbar targets probed on this bench: the units fabric.adoc names
# in the peripheral island and the memory map's system and peripheral control
# group, one documented register each, every write carrying back the value the
# register just returned. The DTP CSR window is left out: its response channel
# is tied idle at this bench, so an access there never completes (SF-039). The
# list and register choice are a DV reading pending SF-012.
_PXBAR_PROBES: tuple[tuple[str, str, bool], ...] = (
    ("reset_unit", "smc_reset_unit/SS_CONFIG", False),
    ("misc_scratch", "smc_misc_wrap/scratch_cold/SCRATCH[0]", False),
    ("gpio_intf", "gpio_intf/ACCESS_FILTER", False),
    ("avsbus", "smc_avsbus_controller/AVS_CFG_0", True),
    ("i2c", "smc_i2c_wrap/i2c/HOST_FIFO_CONFIG", True),
    ("uart", "smc_uart_wrap/uart_log_engine_wrap/uart/SCR", True),
    ("efuse_map", "smc_efuse_map/OCCP_TRANSPORT_TIMEOUT", False),
    ("efuse_interface_ctrl", "efuse_interface_ctrl/EFUSE_READ_REQ_TIMEOUT", False),
    ("telemetry", "smc_telemetry_receiver_wrap/telemetry_receiver/INTR_ENABLE", False),
    ("system_timer", "smc_system_timer_octs/TIMER_PRESET_LO", False),
    ("dfx_ctrl", "dfx_ctrl/DEBUG_BUS_MUX", False),
    ("i3c", "oca_i3c_wrap/i3c_csr/I3CBase/DEV_CTX_BASE_LO", True),
)
#: The AXI-Lite extension window's straps word, `sw = r` in straps.rdl.
_PXBAR_STRAPS_SYMBOL = "SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_LO_BASE_ADDR"

_TERMS = (
    "SETUP",
    "CONFIG_SWEEP",
    "REG_SWEEP",
    "OUTSTANDING",
    "OVERLAP",
    "HELD",
    "PXBAR_SINGLE",
    "PXBAR_OUT",
    "PXBAR_OVERLAP",
    "PXBAR_HELD",
    "RESTORE",
)
_OKAY = 0


def _item(
    label: str,
    op: SmcSysAxiOp,
    addr: int,
    width: int,
    *,
    wdata: int = 0,
    expected: int | None = None,
    axi_id: int | None = None,
) -> SmcSysAxiItem:
    item = SmcSysAxiItem(f"{op.value}_{label}")
    item.op = op
    item.addr = addr
    item.length = width
    item.wdata = wdata
    item.expected = expected
    item.axi_id = axi_id
    return item


class _FamilyTally:
    """What one family's checker reports."""

    def __init__(self) -> None:
        self.sweep_ok = 0
        self.sweep_total = 0
        self.groups = 0
        self.group_accesses = 0
        self.overlap = 0
        self.overlap_pre = 0
        self.overlap_post = 0
        self.overlap_skews: set[str] = set()
        self.held = 0
        self.restore = 0
        self.max_group_ns = 0


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

    async def _config_sweep(self) -> None:
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

    # -- handshake legs ----------------------------------------------------

    def _stamp(self, term: str, before: int) -> None:
        self._stamps.append((term, self.accesses - before, get_sim_time("ns")))

    async def _single(self, item: SmcSysAxiItem) -> SmcSysAxiItem:
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._note_wait(f"single {item.op.value} 0x{item.addr:08x}", [item], 0)
        return item

    async def _group(self, name: str, items: list[SmcSysAxiItem], timing=None) -> int:
        """Run one group and return its latency in ns, every member answered once."""
        sb = self.env.scoreboard
        seen = sb.sys_axi_checks_seen
        t0 = get_sim_time("ns")
        group = SmcSysAxiGroupItem(name, items, timing=timing)
        await self.start_item(group)
        await self.finish_item(group)
        latency = int(get_sim_time("ns") - t0)
        self.accesses += len(items)
        self._groups += 1
        delta = sb.sys_axi_checks_seen - seen
        assert delta == len(items), (
            f"{name}: the scoreboard checked {delta} access(es) of a group of {len(items)}, "
            f"so a response was lost or duplicated"
        )
        self._note_wait(name, items, latency)
        return latency

    def _note_wait(self, name: str, items: list[SmcSysAxiItem], latency: int) -> None:
        for item in items:
            assert not item.timed_out, f"{name}: {item} expired"
            assert item.resp_code is not None, f"{name}: {item} completed with no response"
        self._waits += 1
        self._max_latency = max(self._max_latency, latency)
        self._last_wait = f"{name}:" + ",".join(f"{i.op.value[0]}{i.resp_code}" for i in items)

    def _okay(self, name: str, items: list[SmcSysAxiItem]) -> None:
        for item in items:
            assert item.resp_code == _OKAY, f"{name}: {item} answered resp={item.resp_code}"

    async def _read_model(self, reg: _Reg) -> None:
        item = await self._single(
            _item(reg.label, SmcSysAxiOp.READ, reg.addr, 8, expected=self._model[reg.addr])
        )
        self._okay(reg.label, [item])

    async def _reg_sweep(self, fams: list[_Family]) -> None:
        writes: list[tuple[_Block, _Reg, int]] = []
        for fam in fams:
            for blk in fam.blocks:
                for k, reg in enumerate(blk.writable):
                    writes.append((blk, reg, _pattern(blk, k, _PH_SWEEP, reg)))
        assert len({w[2] for w in writes}) == len(writes), "sweep patterns are not distinct"
        assert len({w[1].addr for w in writes}) == len(writes), "sweep addresses are not distinct"
        for _blk, reg, value in writes:
            item = await self._single(_item(reg.label, SmcSysAxiOp.WRITE, reg.addr, 8, wdata=value))
            self._okay(reg.label, [item])
            self._model[reg.addr] = value
        for blk, reg, _value in writes:
            await self._read_model(reg)
            tally = self._tally[blk.family.token]
            tally.sweep_ok += 1
            tally.sweep_total += 1

    def _reads_not_written(self, blk: _Block) -> tuple[_Reg, _Reg]:
        """Two registers a block's outstanding group reads but does not write."""
        blocks = blk.family.blocks
        prev = blocks[(blk.index - 1) % len(blocks)]
        if blk.config is not None:
            return blk.config, prev.writable[0]
        if len(blk.writable) > 2:
            return blk.writable[2], prev.writable[0]
        return prev.writable[0], blocks[(blk.index - 2) % len(blocks)].writable[0]

    async def _outstanding(self, fams: list[_Family]) -> None:
        for fam in fams:
            tally = self._tally[fam.token]
            for blk in fam.blocks:
                if len(blk.writable) >= 2:
                    targets = [(0, blk.writable[0], 1), (1, blk.writable[1], 2)]
                else:
                    targets = [(0, blk.writable[0], 1)]
                # Each register's writes share one AXI ID, so AXI orders them
                # and the last one written is the value that sticks.
                x, y = self._reads_not_written(blk)
                reads = (x, y)
                items: list[SmcSysAxiItem] = []
                last: dict[int, int] = {}
                for j in range(_GROUP_WRITES):
                    k, reg, wid = targets[j % len(targets)]
                    value = _pattern(blk, k, _PH_GROUP + j, reg)
                    last[reg.addr] = value
                    items.append(
                        _item(
                            f"{reg.label}_g{j}",
                            SmcSysAxiOp.WRITE,
                            reg.addr,
                            8,
                            wdata=value,
                            axi_id=wid,
                        )
                    )
                    rd = reads[j % 2]
                    items.append(
                        _item(
                            f"{rd.label}_g{j}",
                            SmcSysAxiOp.READ,
                            rd.addr,
                            8,
                            expected=self._model[rd.addr],
                        )
                    )
                assert len({i.wdata for i in items if i.op is SmcSysAxiOp.WRITE}) == _GROUP_WRITES
                latency = await self._group(f"{blk.label}_8w8r", items)
                self._okay(blk.label, items)
                self._model.update(last)
                a, b = targets[0][1], targets[-1][1]
                rb = [
                    _item(
                        f"{a.label}_rb", SmcSysAxiOp.READ, a.addr, 8, expected=self._model[a.addr]
                    ),
                    _item(
                        f"{b.label}_rb", SmcSysAxiOp.READ, b.addr, 8, expected=self._model[b.addr]
                    ),
                ]
                latency = max(latency, await self._group(f"{blk.label}_rb2", rb))
                self._okay(blk.label, rb)
                tally.groups += 1
                tally.group_accesses += len(items)
                tally.max_group_ns = max(tally.max_group_ns, latency)

    async def _overlap(self, fams: list[_Family]) -> None:
        for fam in fams:
            tally = self._tally[fam.token]
            for blk in fam.blocks:
                k = blk.index % len(blk.writable)
                reg = blk.writable[k]
                pre = self._model[reg.addr]
                post = _pattern(blk, k, _PH_OVERLAP, reg)
                skew, timing, write_first = _SKEWS[blk.index % len(_SKEWS)]
                wr = _item(f"{reg.label}_ov", SmcSysAxiOp.WRITE, reg.addr, 8, wdata=post)
                rd = _item(f"{reg.label}_ov", SmcSysAxiOp.READ, reg.addr, 8)
                items = [wr, rd] if write_first else [rd, wr]
                latency = await self._group(f"{blk.label}_overlap_{skew}", items, timing)
                self._okay(blk.label, items)
                assert rd.rdata in (pre, post), (
                    f"{blk.label} overlapped read ({skew}) returned 0x{rd.rdata:x}, neither the "
                    f"pre-write 0x{pre:x} nor the post-write 0x{post:x}"
                )
                if rd.rdata == pre:
                    tally.overlap_pre += 1
                else:
                    tally.overlap_post += 1
                self._model[reg.addr] = post
                await self._read_model(reg)
                tally.overlap += 1
                tally.overlap_skews.add(skew)
                tally.max_group_ns = max(tally.max_group_ns, latency)

    async def _held(self, fams: list[_Family]) -> None:
        for fam in fams:
            tally = self._tally[fam.token]
            for blk in fam.blocks:
                regs = list(blk.writable) + ([blk.config] if blk.config is not None else [])
                reads = [
                    _item(
                        f"{r.label}_hr{j}",
                        SmcSysAxiOp.READ,
                        r.addr,
                        8,
                        expected=self._model[r.addr],
                    )
                    for j, r in ((j, regs[j % len(regs)]) for j in range(_HOLD_DEPTH))
                ]
                latency = await self._group(f"{blk.label}_held_r32", reads, _R_HOLD)
                self._okay(blk.label, reads)
                writes = [
                    _item(
                        f"{r.label}_hw{j}", SmcSysAxiOp.WRITE, r.addr, 8, wdata=self._model[r.addr]
                    )
                    for j, r in (
                        (j, blk.writable[j % len(blk.writable)]) for j in range(_HOLD_DEPTH)
                    )
                ]
                latency = max(latency, await self._group(f"{blk.label}_held_b32", writes, _B_HOLD))
                self._okay(blk.label, writes)
                tally.held += 1
                tally.max_group_ns = max(tally.max_group_ns, latency)

    async def _restore(self, fams: list[_Family]) -> None:
        regs = [reg for fam in fams for blk in fam.blocks for reg in blk.writable]
        owner = {reg.addr: fam.token for fam in fams for blk in fam.blocks for reg in blk.writable}
        depths: list[int] = []
        index = 0
        while index < len(regs):
            depth = 3 if len(regs) - index >= 3 else 1
            chunk = regs[index : index + depth]
            items = [
                _item(f"{r.label}_rst", SmcSysAxiOp.WRITE, r.addr, 8, wdata=r.reset) for r in chunk
            ]
            await self._group(f"restore_{index}_d{depth}", items)
            self._okay("restore", items)
            for r in chunk:
                self._model[r.addr] = r.reset
            depths.append(depth)
            index += depth
        assert {1, 3} <= set(depths), f"restore groups had depths {sorted(set(depths))}"
        for reg in regs:
            await self._read_model(reg)
            self._tally[owner[reg.addr]].restore += 1
        self._restore_depths = depths

    # -- peripheral crossbar -------------------------------------------------

    def _pxbar_targets(self) -> list[tuple[str, int, int, bool]]:
        targets: list[tuple[str, int, int, bool]] = []
        for name, path, pclk in _PXBAR_PROBES:
            reg = rdl_contract(path)
            for field in reg.fields:
                assert not field.read_action and not field.modified_write, (
                    f"{name}: probe {path} field {field.name} has a read or write side effect"
                )
                assert field.access != "write-only", f"{name}: probe {path} field {field.name}"
            assert reg.width_bytes in (4, 8), f"{name}: probe {path} is {reg.width_bytes} bytes"
            targets.append((name, reg.addr, reg.width_bytes, pclk))
        targets.append(("ext_straps", smc_addr(_PXBAR_STRAPS_SYMBOL), 4, False))
        assert len({t[1] for t in targets}) == len(targets), "two probes share an address"
        return targets

    async def _pxbar_single(self, targets) -> None:
        for name, addr, width, _pclk in targets:
            first = await self._single(_item(f"px_{name}_rd1", SmcSysAxiOp.READ, addr, width))
            wb = await self._single(
                _item(f"px_{name}_wb", SmcSysAxiOp.WRITE, addr, width, wdata=first.rdata)
            )
            again = await self._single(
                _item(f"px_{name}_rd2", SmcSysAxiOp.READ, addr, width, expected=first.rdata)
            )
            assert again.rdata == first.rdata, (
                f"{name}: read 0x{again.rdata:x} after a write-back of 0x{first.rdata:x}"
            )
            self._px_first[addr] = first.rdata
            self._px_resp[name] = (first.resp_code, wb.resp_code, again.resp_code)
            cocotb.log.info(
                "PXBAR %s @0x%08x width=%d value=0x%x rresp=%s bresp=%s rresp2=%s "
                "(observed; LINKED-ISSUE SF-012)",
                name,
                addr,
                width,
                first.rdata,
                first.resp_code,
                wb.resp_code,
                again.resp_code,
            )

    def _px_rd(self, tag: str, target) -> SmcSysAxiItem:
        name, addr, width, _pclk = target
        return _item(
            f"px_{name}_{tag}", SmcSysAxiOp.READ, addr, width, expected=self._px_first[addr]
        )

    def _px_wr(self, tag: str, target) -> SmcSysAxiItem:
        name, addr, width, _pclk = target
        return _item(f"px_{name}_{tag}", SmcSysAxiOp.WRITE, addr, width, wdata=self._px_first[addr])

    async def _pxbar_outstanding(self, targets) -> None:
        n = len(targets)
        for target in targets:
            items = [
                self._px_rd(f"o_{j}", target) if j % 2 == 0 else self._px_wr(f"o_{j}", target)
                for j in range(_PX_DEPTH)
            ]
            await self._group(f"px_{target[0]}_out16", items)
            self._px_groups += 1
        spread: set[str] = set()
        for g in range(_PX_SPREAD_GROUPS):
            items = []
            for j in range(_PX_DEPTH):
                target = targets[(g * _PX_DEPTH // 2 + j // 2) % n]
                spread.add(target[0])
                tag = f"s{g}_{j}"
                items.append(self._px_rd(tag, target) if j % 2 == 0 else self._px_wr(tag, target))
            await self._group(f"px_spread16_{g}", items)
            self._px_groups += 1
        assert len(spread) == n, f"spread groups reached {len(spread)} of {n} targets"
        pclk = {t[0] for t in targets if t[3]}
        assert pclk & spread and spread - pclk, "spread groups did not mix clock domains"

    async def _pxbar_overlap(self, targets) -> None:
        for k, target in enumerate(targets):
            skew, timing, write_first = _SKEWS[k % len(_SKEWS)]
            wr, rd = self._px_wr(f"ov_{skew}", target), self._px_rd(f"ov_{skew}", target)
            await self._group(
                f"px_{target[0]}_overlap_{skew}", [wr, rd] if write_first else [rd, wr], timing
            )
            self._px_overlap += 1

    async def _pxbar_held(self, targets) -> None:
        for target in targets:
            reads = [self._px_rd(f"hr{j}", target) for j in range(_HOLD_DEPTH)]
            await self._group(f"px_{target[0]}_held_r32", reads, _R_HOLD)
            writes = [self._px_wr(f"hw{j}", target) for j in range(_HOLD_DEPTH)]
            await self._group(f"px_{target[0]}_held_b32", writes, _B_HOLD)
            self._px_held += 1

    async def _pxbar_final(self, targets) -> None:
        for target in targets:
            item = await self._single(self._px_rd("final", target))
            assert item.rdata == self._px_first[target[1]], f"{target[0]} moved"

    # -- body ----------------------------------------------------------------

    async def body(self) -> None:
        self._stamps: list[tuple[str, int, int]] = []
        self._model: dict[int, int] = {}
        self._groups = 0
        self._waits = 0
        self._max_latency = 0
        self._last_wait = ""
        self._px_first: dict[int, int] = {}
        self._px_resp: dict[str, tuple] = {}
        self._px_groups = 0
        self._px_overlap = 0
        self._px_held = 0
        self._restore_depths: list[int] = []
        bound_ns = self.cfg.axi_timeout_ns

        before = self.accesses
        await self.wait_fuse_sense_done()
        self._waits += 1
        self._stamp("SETUP", before)

        before = self.accesses
        await self._config_sweep()
        self._stamp("CONFIG_SWEEP", before)
        self._waits += self.accesses - before

        fams = _families()
        self._tally = {fam.token: _FamilyTally() for fam in fams}
        for fam in fams:
            for blk in fam.blocks:
                for reg in blk.writable:
                    self._model[reg.addr] = reg.reset
                if blk.config is not None:
                    self._model[blk.config.addr] = blk.config.reset

        for term, leg in (
            ("REG_SWEEP", self._reg_sweep),
            ("OUTSTANDING", self._outstanding),
            ("OVERLAP", self._overlap),
            ("HELD", self._held),
        ):
            before = self.accesses
            await leg(fams)
            self._stamp(term, before)

        targets = self._pxbar_targets()
        for term, leg in (
            ("PXBAR_SINGLE", self._pxbar_single),
            ("PXBAR_OUT", self._pxbar_outstanding),
            ("PXBAR_OVERLAP", self._pxbar_overlap),
            ("PXBAR_HELD", self._pxbar_held),
        ):
            before = self.accesses
            await leg(targets)
            if term == "PXBAR_HELD":
                await self._pxbar_final(targets)
            self._stamp(term, before)

        before = self.accesses
        await self._restore(fams)
        self._stamp("RESTORE", before)

        sb = self.env.scoreboard
        assert sb.sys_axi_checks_seen + sb.sys_axi_reset_aborted_seen >= self.accesses, (
            f"the scoreboard checked {sb.sys_axi_checks_seen} SEP_IN item(s) of "
            f"{self.accesses} issued"
        )

        for fam in fams:
            t = self._tally[fam.token]
            blocks = len(fam.blocks)
            regs = sum(len(b.writable) for b in fam.blocks)
            assert t.sweep_ok == t.sweep_total == regs, f"{fam.token}: sweep {t.sweep_ok}/{regs}"
            assert t.groups == blocks, f"{fam.token}: {t.groups} groups"
            assert t.overlap == blocks and t.overlap_skews == {s for s, _t, _w in _SKEWS}, (
                f"{fam.token}: overlap {t.overlap} skews {sorted(t.overlap_skews)}"
            )
            assert t.held == blocks, f"{fam.token}: held {t.held}"
            assert t.restore == regs, f"{fam.token}: restore {t.restore}/{regs}"
            cocotb.log.info(
                "%s: blocks=%d sweep %d/%d rb==wr; 8W+8R groups %d accesses %d once-each; "
                "overlap %d pre=%d post=%d skews=%s; held 16R(r32)+16W(b32) x %d once-each; "
                "restore ok "
                "%d regs at RDL reset; max group latency %d ns vs TB bound %d ns per access "
                "(observed; LINKED-ISSUE SF-038)",
                fam.chk,
                blocks,
                t.sweep_ok,
                t.sweep_total,
                t.groups,
                t.group_accesses,
                t.overlap,
                t.overlap_pre,
                t.overlap_post,
                ",".join(sorted(t.overlap_skews)),
                t.held,
                t.restore,
                t.max_group_ns,
                bound_ns,
            )

        assert self._px_groups == len(targets) + _PX_SPREAD_GROUPS, f"{self._px_groups} groups"
        assert self._px_held == len(targets), f"pxbar held {self._px_held}"
        cocotb.log.info(
            "CHK-HS-PXBAR: responding targets=%d (DTP CSR excluded, SF-039) single once-each "
            "rb==first; depth-16 groups %d once-each; overlap %d; held 16R(r32)+16W(b32) x %d "
            "once-each; resp per target %s (LINKED-ISSUE SF-012)",
            len(targets),
            self._px_groups,
            self._px_overlap,
            self._px_held,
            ";".join(f"{n}=r{r[0]}/b{r[1]}/r{r[2]}" for n, r in self._px_resp.items()),
        )

        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits (fuse sense 200000 clk_smc_i; every single "
            "access and every group member %d ns, expiry raises AssertionError in the SEP_IN "
            "driver); %d groups, max group latency %d ns; last state %s; 0 expired",
            self._waits,
            bound_ns,
            self._groups,
            self._max_latency,
            self._last_wait,
        )

        terms = tuple(term for term, _n, _t in self._stamps)
        assert terms == _TERMS, f"fence terms {terms}"
        times = [t for _term, _n, t in self._stamps]
        assert all(b >= a for a, b in zip(times, times[1:])), f"fence times {times}"
        assert all(n > 0 for term, n, _t in self._stamps if term != "SETUP"), (
            f"a fence term issued no access: {self._stamps}"
        )
        cocotb.log.info(
            "CHK-NONVAC: %s; %s; %d SEP_IN accesses",
            "<".join(terms),
            " ".join(f"{term}(n={n},t={t}ns)" for term, n, t in self._stamps),
            self.accesses,
        )
