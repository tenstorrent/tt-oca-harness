# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_EFUSE_MAP direct read.

``CHIP_CONFIG_*`` mirrors eFuse fields; this test reads the structured
SMC_EFUSE_MAP window (PeakRDL map) itself over real SEP_IN AXI.

**Proof class: transport.** Every expectation below is the word the bench-wide
``+smc_efuse_hex`` preload (``smc_sim_cfg.toml``) deposited into the
eFuse bank model at time 0, so what is proven is that the map window decodes and
returns the sensed word -- not that fuse *programming* works. The bank itself is
a declared simulation stand-in for the OTP macro (see
``hw/ip/efuse/doc/architecture.adoc``).

**Where each expected value comes from.** No expectation is a hand-transcribed
literal and none is locked to an observed read:

* readable words -- ``efuse_preload_word_at(addr)`` parses
  ``hw/sys/smc/dv/assets/smc_efuse_default.hex`` at run time and indexes it by
  ``(addr - SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR)/4``, the same word ordering
  ``efuse_bank_model.sv`` uses. Regenerating the asset moves the
  expectation with it instead of leaving a stale literal asserting a false
  identity.
* read-locked words -- ``efuse_map_read_locked()`` reads the ``*_READ_LOCK`` bit
  out of the *preloaded* ``LOCKS`` word using the generated bit position from
  ``regs/gen/c/blocks/smc_efuse_map.h``; SPEC then fixes the data a blocked read
  returns: "When a request is blocked, the error slave returns an error response
  with data value `0xbadcab1e`" (``architecture.adoc``, Lifecycle State
  (LC_STATE) Effects), and ``lock[0] = 1`` is "read-locked"
  (``architecture.adoc``, Access Permissions and Security).

Every row carries an exact, independently sourced expectation: a "map read"
with ``expected=None`` compares nothing while counting toward the stimulus
floor, and would let a region returning the ``0xBADCAB1E`` blocked signature
pass unnoticed ([NO-ALWAYS-PASS-CHECKER]). ``RESERVED_0`` is not read: its
block comes from the hardware field-map lock (``rule_t.lock[0]``,
``architecture.adoc``, Access Permissions and Security), which is fused into
the array rather than published in any artifact this testbench can read, so no
expectation for it can be derived independently of the DUT.
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


def _map_expect(addr: int, lock_field: str | None) -> int:
    """Exact expectation for a 32-bit SMC_EFUSE_MAP read.

    Read-locked by the preloaded LOCKS word -> the SPEC blocked-read data;
    otherwise the preload word backing that address.

    The LOCKS half is sound in the blocking direction only: SPEC says the guard
    enforces "whichever is more restrictive" of the software LOCKS CSR and the
    fused hardware field map (``architecture.adoc``, Hardware vs. Software
    Locks), so a set LOCKS bit always blocks, while a clear one still leaves the
    fused lock free to block.
    A region that is clear here and nevertheless answers with the blocked
    signature fails this compare.
    """
    if lock_field is not None and efuse_map_read_locked(lock_field):
        return EFUSE_BLOCKED_READ_DATA
    return efuse_preload_word_at(addr)


# Every SMC_EFUSE_MAP region that has BOTH a generated base address and a
# generated `*_READ_LOCK` bit in blocks/smc_efuse_map.h, so `_map_expect` can
# derive an exact expectation for it from the preload asset plus the generated
# map ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
_MAP_REGIONS = (
    (
        "JTAG_PUBLIC_IDENTITY",
        "SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR",
        "SMC_EFUSE_MAP__LOCKS__JTAG_PUBLIC_IDENTITY_READ_LOCK_bm",
    ),
    (
        "SMC_CONFIG",
        "SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR",
        "SMC_EFUSE_MAP__LOCKS__SMC_CONFIG_READ_LOCK_bm",
    ),
    (
        "OCCP_TRANSPORT_TIMEOUT",
        "SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR",
        "SMC_EFUSE_MAP__LOCKS__OCCP_TRANSPORT_TIMEOUT_READ_LOCK_bm",
    ),
)
# `I2C_I3C_ID` is a 9-entry array. The authoritative map carries it as a PeakRDL
# indexed macro so the base AND the stride come from the generated map via
# `smc_indexed_addr`, not from arithmetic invented here. All nine entries share
# one read-lock bit but are backed by distinct preload words, widening the
# distinctness gate below.
_I2C_I3C_ID_COUNT = 9
# Probe the first two SPARE regions as a representative sample; all 28 share
# independent read-lock bits.
_SPARE_PROBE_COUNT = 2

EFUSE_MAP_READS = [
    # LOCKS itself is not read-locked by any LOCKS bit; it is words 0/1 of the
    # preload asset.
    ("EFUSE_MAP_LOCKS_LO", _LOCKS, _map_expect(_LOCKS, None)),
    ("EFUSE_MAP_LOCKS_HI", _LOCKS + 4, _map_expect(_LOCKS + 4, None)),
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
for _i in range(_SPARE_PROBE_COUNT):
    _a = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", _i)
    _lsym = f"SMC_EFUSE_MAP__LOCKS__SPARE{_i}_READ_LOCK_bm"
    EFUSE_MAP_READS.append((f"EFUSE_MAP_SPARE_{_i}", _a, _map_expect(_a, _lsym)))


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

        # Non-vacuity of the sweep: the expectations must not all be the same
        # word, or a window stuck at one value would satisfy every row.
        distinct = {exp for _n, _a, exp in EFUSE_MAP_READS}
        assert len(distinct) >= 3, (
            "EFUSE_MAP_READ: the preload asset makes "
            f"{len(distinct)} distinct expectation(s) across "
            f"{len(EFUSE_MAP_READS)} rows -- the sweep can no longer "
            "discriminate a stuck map window from a working one"
        )
        # Split the rows by what each one proves. A blocked row's expectation is
        # the SPEC error-slave signature, so it predicts a refusal and says
        # nothing about fuse content; an unlocked row compares the preload word
        # and is the content proof. Naming both in the token keeps a reader from
        # counting the first kind as the second.
        blocked = [r for r in EFUSE_MAP_READS if r[2] == EFUSE_BLOCKED_READ_DATA]
        content = [r for r in EFUSE_MAP_READS if r[2] != EFUSE_BLOCKED_READ_DATA]
        assert content, (
            "every SMC_EFUSE_MAP row expects the blocked signature, so no read "
            "in this sweep proves fuse content"
        )
        cocotb.log.info(
            "CHK-EFUSE-MAP-READ: %d content rows compared against "
            "assets/smc_efuse_default.hex (%s); %d blocked rows compared against "
            "the SPEC error-slave signature 0x%08x, which predicts a refusal and "
            "is not a content proof (%s); %d distinct values overall",
            len(content),
            "; ".join(f"{n}@0x{a:08x}==0x{e:08x}" for n, a, e in content),
            len(blocked),
            EFUSE_BLOCKED_READ_DATA,
            "; ".join(f"{n}@0x{a:08x}" for n, a, _e in blocked) or "none",
            len(distinct),
        )
        self.chk_seen.add("CHK-EFUSE-MAP-READ")
