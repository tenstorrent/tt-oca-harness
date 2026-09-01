# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""P1 coverage-gap: SMC_EFUSE_MAP direct read (TC_SMC_P1CG_04).

Existing tests only touch ``CHIP_CONFIG_*`` (mirrored eFuse fields). This test
reads the structured SMC_EFUSE_MAP window (PeakRDL map) over real SEP_IN AXI.

**Proof class: transport.** Every expectation below is the word the bench-wide
``+smc_efuse_hex`` preload (``smc_sim_cfg.toml:132-134``) deposited into the
eFuse bank model at time 0, so what is proven is that the map window decodes and
returns the sensed word -- not that fuse *programming* works. The bank itself is
a declared simulation stand-in: "The eFuse bank model (`efuse_bank_model.sv`) is
a reference, simulation-only stand-in for the real foundry OTP macro ... a 3KB
(768 x 32-bit word) store" (``hw/ip/efuse/doc/architecture.adoc:163-170``).

**Where each expected value comes from.** No expectation is a hand-transcribed
literal and none is locked to an observed read:

* readable words -- ``efuse_preload_word_at(addr)`` parses
  ``hw/sys/smc/dv/assets/smc_efuse_default.hex`` at run time and indexes it by
  ``(addr - SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR)/4``, the same word ordering
  ``efuse_bank_model.sv:140-160`` uses. Regenerating the asset moves the
  expectation with it instead of leaving a stale literal asserting a false
  identity.
* read-locked words -- ``efuse_map_read_locked()`` reads the ``*_READ_LOCK`` bit
  out of the *preloaded* ``LOCKS`` word using the generated bit position from
  ``regs/gen/c/blocks/smc_efuse_map.h``; SPEC then fixes the data a blocked read
  returns: "When a request is blocked, the error slave returns an error response
  with data value `0xbadcab1e`" (``architecture.adoc:297-299``), and
  ``lock[0] = 1`` is "read-locked" (``architecture.adoc:198``).

Every row carries an expectation. A "map read" with ``expected=None`` compares
nothing while still counting toward the stimulus floor, and would let a region
returning the ``0xBADCAB1E`` blocked signature pass unnoticed
([NO-ALWAYS-PASS-CHECKER]). ``BIRA`` carries its asset-derived expectation.
``RESERVED_0`` is not read at all; ``CHIPLET_ID`` is read in its place, because
its
blocked outcome *is* derivable from the sources above: the RESERVED region's
observed block comes from the hardware field-map lock (``rule_t.lock[0]``,
``architecture.adoc:179-201``), which is fused into the array rather than
published in any artifact this testbench can read, so an expectation for it
could only have been copied off the DUT. All four reads now carry an exact,
independently sourced expectation.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import (
    EFUSE_BLOCKED_READ_DATA,
    efuse_map_read_locked,
    efuse_preload_word_at,
)

_LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
_BIRA = smc_addr("SMC_TOP_SMC_EFUSE_MAP_BIRA_BASE_ADDR")
_CHIPLET_ID = smc_addr("SMC_TOP_SMC_EFUSE_MAP_CHIPLET_ID_BASE_ADDR")


def _map_expect(addr: int, lock_field: str | None) -> int:
    """Exact expectation for a 32-bit SMC_EFUSE_MAP read.

    Read-locked by the preloaded LOCKS word -> the SPEC blocked-read data;
    otherwise the preload word backing that address.

    The LOCKS half is sound in the blocking direction only: SPEC says the guard
    enforces "whichever is more restrictive" of the software LOCKS CSR and the
    fused hardware field map (``architecture.adoc:203-226``), so a set LOCKS bit
    always blocks, while a clear one still leaves the fused lock free to block.
    A region that is clear here and nevertheless answers with the blocked
    signature therefore FAILS this compare -- correctly, because the retained
    evidence would otherwise record a fuse value that was never read.
    """
    if lock_field is not None and efuse_map_read_locked(lock_field):
        return EFUSE_BLOCKED_READ_DATA
    return efuse_preload_word_at(addr)


# Every SMC_EFUSE_MAP region that has BOTH a generated base address and a
# generated `*_READ_LOCK` bit in blocks/smc_efuse_map.h, so `_map_expect` can
# derive an exact expectation for it from the preload asset plus the generated
# map. Excluded on purpose:
#   * `RESERVED_0..64` -- see the module docstring: its blocked outcome is not
#     independently derivable, so a compare on it would not be evidence.
#   * `SPI_CONFIG` / `SPI_CTRL_FIELD_ENABLE` -- a LOCKS read-lock bit exists for
#     each, but no `SMC_TOP_SMC_EFUSE_MAP_SPI_*_BASE_ADDR` does, so there is no
#     register to read on this map.
_MAP_REGIONS = (
    (
        "CLUSTER",
        "SMC_TOP_SMC_EFUSE_MAP_CLUSTER_BASE_ADDR",
        "SMC_EFUSE_MAP__LOCKS__CLUSTER_READ_LOCK_bm",
    ),
    (
        "FABRIC",
        "SMC_TOP_SMC_EFUSE_MAP_FABRIC_BASE_ADDR",
        "SMC_EFUSE_MAP__LOCKS__FABRIC_READ_LOCK_bm",
    ),
    (
        "SOP_TOPOLOGY",
        "SMC_TOP_SMC_EFUSE_MAP_SOP_TOPOLOGY_BASE_ADDR",
        "SMC_EFUSE_MAP__LOCKS__SOP_TOPOLOGY_READ_LOCK_bm",
    ),
    (
        "I2C_CLOCK_GATING",
        "SMC_TOP_SMC_EFUSE_MAP_I2C_CLOCK_GATING_BASE_ADDR",
        "SMC_EFUSE_MAP__LOCKS__I2C_CLOCK_GATING_READ_LOCK_bm",
    ),
    (
        "I3C_DISABLE",
        "SMC_TOP_SMC_EFUSE_MAP_I3C_DISABLE_BASE_ADDR",
        "SMC_EFUSE_MAP__LOCKS__I3C_DISABLE_READ_LOCK_bm",
    ),
    (
        "PLL_AND_SENSOR",
        "SMC_TOP_SMC_EFUSE_MAP_PLL_AND_SENSOR_BASE_ADDR",
        "SMC_EFUSE_MAP__LOCKS__PLL_AND_SENSOR_READ_LOCK_bm",
    ),
    (
        "PACKAGE_ID",
        "SMC_TOP_SMC_EFUSE_MAP_PACKAGE_ID_BASE_ADDR",
        "SMC_EFUSE_MAP__LOCKS__PACKAGE_ID_READ_LOCK_bm",
    ),
)
# `I2C_I3C_ID` is a 9-entry array. The authoritative map carries it as a PeakRDL
# indexed macro -- `SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR(idx) =
# 0xC00078AC + idx * 0x8` (smc_addr.h:773) -- so the base AND the stride come
# from the generated map via `smc_indexed_addr`, not from arithmetic invented
# here ([ADDRESS-FROM-AUTHORITATIVE-MAP]). Note the stride is 8, not 4. All nine
# entries share one read-lock bit but are backed by distinct preload words, so
# they also widen the distinctness gate below.
_I2C_I3C_ID_COUNT = 9

EFUSE_MAP_READS = [
    # LOCKS itself is not read-locked by any LOCKS bit; it is words 0/1 of the
    # preload asset.
    ("EFUSE_MAP_LOCKS_LO", _LOCKS, _map_expect(_LOCKS, None)),
    ("EFUSE_MAP_LOCKS_HI", _LOCKS + 4, _map_expect(_LOCKS + 4, None)),
    (
        "EFUSE_MAP_BIRA",
        _BIRA,
        _map_expect(_BIRA, "SMC_EFUSE_MAP__LOCKS__BIRA_DIS_READ_LOCK_bm"),
    ),
    (
        "EFUSE_MAP_CHIPLET_ID",
        _CHIPLET_ID,
        _map_expect(_CHIPLET_ID, "SMC_EFUSE_MAP__LOCKS__CHIPLET_ID_READ_LOCK_bm"),
    ),
]
for _rname, _asym, _lsym in _MAP_REGIONS:
    _a = smc_addr(_asym)
    EFUSE_MAP_READS.append((f"EFUSE_MAP_{_rname}", _a, _map_expect(_a, _lsym)))
for _i in range(_I2C_I3C_ID_COUNT):
    _a = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR", _i)
    EFUSE_MAP_READS.append(
        (
            f"EFUSE_MAP_I2C_I3C_ID_{_i}",
            _a,
            _map_expect(_a, "SMC_EFUSE_MAP__LOCKS__I2C_I3C_ID_READ_LOCK_bm"),
        )
    )


class smc_efuse_map_read_test_seq(SmcCsrSeq):
    def __init__(self, name: str = "smc_efuse_map_read_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()

    async def body(self) -> None:
        # Before fuse-sense completes the map window is error-slaved
        # (SLVERR/0xBADCAB1E). Wait for sense so VCS/Verilator hit the real path.
        await self.wait_fuse_sense_done()

        for name, addr, expected in EFUSE_MAP_READS:
            await self.csr_read(name, addr, expected=expected)

        # Scoreboard cross-check, not a self-count: `accesses` is bumped by
        # `csr_read` regardless of what the DUT returned, so on its own it
        # cannot see a mis-bound analysis path ([NO-ZERO-ACTIVITY-PASS]).
        self.assert_all_reachable(len(EFUSE_MAP_READS), "EFUSE_MAP_READ")

        # Non-vacuity of the sweep: the four expectations must not all be the
        # same word, or a window stuck at one value would satisfy every row.
        distinct = {exp for _n, _a, exp in EFUSE_MAP_READS}
        assert len(distinct) >= 3, (
            "EFUSE_MAP_READ: the preload asset makes "
            f"{len(distinct)} distinct expectation(s) across "
            f"{len(EFUSE_MAP_READS)} rows -- the sweep can no longer "
            "discriminate a stuck map window from a working one"
        )
        cocotb.log.info(
            "CHK-EFUSE-MAP-READ: %s (expectations derived from "
            "assets/smc_efuse_default.hex + SMC_EFUSE_MAP LOCKS read-lock bits, "
            "%d distinct values)",
            "; ".join(f"{name}@0x{addr:08x}==0x{exp:08x}" for name, addr, exp in EFUSE_MAP_READS),
            len(distinct),
        )
        self.chk_seen.add("CHK-EFUSE-MAP-READ")
