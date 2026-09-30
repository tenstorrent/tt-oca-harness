# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reserved addresses in the SEP memory map must be refused.

Ports the negative-decode behaviour of the OCAH ``sep_cpu_lsu_negative_matrix``,
``sep_cpu_ifu_invalid_target`` and ``sep_fabric_xbar_error_closure`` tests.

no_cpu / +skip_fuse_sense. RANDCFG: reserved gaps just above each live block
every seed, plus seed-selected addresses drawn from every reserved row.

The expectation comes from ``env/sep_axi_decode_map.py``. A reserved
row allocates nothing, so an access there must not answer OKAY. DECERR
versus SLVERR is unnamed, so the flavour is counted and logged.

CHK-MAP-REFUSE-DATA: a refused read returns none of the live words sampled on
the same bus (the live-bus control, SW_RESET_N, boot-ROM word 0). A refused
access never reaches a unit, so a refused read that hands back live data has
reached one. The sampled set is named in ``seq_lib/sep_axi_map_refuse_seq.py``.

CHK-OKAY is the live-bus control: a known-mapped CSR on the same bus returns
OKAY and its generated reset value. Without it a wedged or dead bus would
refuse every probe and read as a clean pass.

Scope: this walks the gaps BETWEEN block windows.
``sep_fabric_deadspace_decode_test`` walks the dead tail INSIDE a window, and
owns the write-alias check that a refused write left no live register changed.
Neither subsumes the other.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_axi_map_refuse_seq import (
    ANCHOR_KEPT,
    MAPPED_CSR_ADDR,
    PROBE_FLOOR,
    SHORT_ROW_LIMIT,
    SepAxiMapRefuse,
    SepAxiMapRefuseCfg,
)


@pyuvm.test()
class sep_axi_map_refuse_test(sep_base_test):
    """Every reserved address in the map is refused by the fabric."""

    async def run_scenario(self) -> None:
        cfg = SepAxiMapRefuseCfg(self.random_seed())
        self.logger.info("map-refuse config: %s", cfg.summary())

        await self.bring_up_no_cpu()
        refuse = SepAxiMapRefuse(self)

        # Live-bus control first: every refusal after this is a decode result
        # rather than a bus that answers nothing.
        miss = await refuse.mapped_csr()
        assert miss is None, f"CHK-OKAY FAIL: {miss}"
        assert not self.env.scoreboard.errors, (
            "CHK-OKAY FAIL: scoreboard recorded an error on the mapped control"
        )
        self.logger.info(
            "CHK-OKAY PASS: mapped CSR 0x%08x returned OKAY with its generated reset value",
            MAPPED_CSR_ADDR,
        )
        miss = await refuse.sample_live()
        assert miss is None, f"CHK-MAP-REFUSE-DATA FAIL: {miss}"
        assert refuse.live, (
            "CHK-MAP-REFUSE-DATA FAIL: every sampled live word read zero, so the "
            "refused-read data compare cannot fail"
        )

        # Every probe is a reserved address this test asserts. Unnamed-refuse
        # spans are excluded when the set is built.
        fails: list[str] = []
        for item in cfg.probes:
            tag = "anchor" if item.anchor else "rand"
            miss = await refuse.probe(item)
            if miss is None:
                self.logger.info(
                    "CHK-MAP-REFUSE PASS: %s 0x%08x refused (%s, %s)",
                    item.op,
                    item.addr,
                    item.unit,
                    tag,
                )
            else:
                fails.append(miss)
                self.logger.error("CHK-MAP-REFUSE FAIL [%s]: %s", tag, miss)

        if fails:
            raise AssertionError(
                f"CHK-MAP-REFUSE FAIL: {len(fails)} address(es) that no "
                f"decode rule covers were not refused "
                f"({refuse.refused} of {len(cfg.probes)} refused)"
            )

        # A refused read whose data equals a sampled live word already failed
        # CHK-MAP-REFUSE above with the word named. This line is the positive
        # evidence, and it needs at least one refused read to compare.
        assert refuse.reads_compared > 0, (
            "CHK-MAP-REFUSE-DATA FAIL: no refused read was compared against the live words"
        )
        self.logger.info(
            "CHK-MAP-REFUSE-DATA PASS: %d refused read(s) returned none of the %d live "
            "word(s) sampled (%s)",
            refuse.reads_compared,
            len(refuse.live),
            ", ".join(f"{label}=0x{val:08x}" for val, label in refuse.live.values()),
        )

        # Positive evidence: both channels were exercised. A write reaches the
        # B path and a read the R path, and a decoder can refuse one while
        # completing the other.
        n_wr = sum(1 for p in cfg.probes if p.op == "w")
        n_rd = sum(1 for p in cfg.probes if p.op == "r")
        assert n_wr > 0 and n_rd > 0, (
            f"CHK-MAP-REFUSE FAIL: probe set is {n_rd} read(s) and {n_wr} "
            f"write(s); both channels must be exercised, or a decoder that "
            f"refuses one and completes the other passes"
        )
        self.logger.info(
            "CHK-MAP-REFUSE PASS: %d address(es) no decode rule covers were "
            "refused (%d DECERR, %d SLVERR)",
            len(cfg.probes),
            refuse.decerr,
            refuse.slverr,
        )
        # Raw-pin cross-check: the monitor counts DECERR beats it saw on the
        # bus, which is evidence independent of what the master reported. Every
        # credit armed for a DECERR was consumed by a real beat.
        seen = self.env.axi_monitor.expected_decerr_seen
        # Both sides being zero would satisfy the compare below while proving
        # nothing: this checker exists to show the walk actually refused
        # something, so a run that observed no DECERR at all fails here.
        assert refuse.decerr > 0, (
            "CHK-NONVAC FAIL: the walk reported no DECERR response at all, so "
            "the refusal contract has no evidence in this run"
        )
        assert seen == refuse.decerr, (
            f"CHK-NONVAC FAIL: the master reported {refuse.decerr} DECERR "
            f"response(s) but the monitor saw {seen} on the bus"
        )
        self.logger.info(
            "CHK-NONVAC PASS: %d DECERR beat(s) observed on the bus match the "
            "%d the master reported",
            seen,
            refuse.decerr,
        )
        # Floors at the run seed, not only in the module selftest: the selftest
        # pins seeds 1-3, so without these a map or crossbar change that shrank
        # the walk at the seed a regression actually used would still report a
        # clean pass.
        n_anchor = sum(1 for p in cfg.probes if p.anchor)
        assert len(cfg.probes) >= PROBE_FLOOR, (
            f"CHK-RANDCFG FAIL: seed {cfg.seed} walked {len(cfg.probes)} "
            f"probes, below the floor of {PROBE_FLOOR}; a reserved row "
            f"stopped yielding addresses"
        )
        assert n_anchor == ANCHOR_KEPT, (
            f"CHK-RANDCFG FAIL: seed {cfg.seed} kept {n_anchor} anchors, "
            f"expected {ANCHOR_KEPT}; a directed gap left the map"
        )
        assert len(cfg.short_regions) <= SHORT_ROW_LIMIT, (
            f"CHK-RANDCFG FAIL: seed {cfg.seed} left "
            f"{len(cfg.short_regions)} row(s) short of quota, above the "
            f"{SHORT_ROW_LIMIT} unnamed-refuse rows"
        )
        self.logger.info(
            "CHK-RANDCFG PASS: walked %d probes (floor %d) with all %d "
            "anchors and %d short row(s) from seed %d",
            len(cfg.probes),
            PROBE_FLOOR,
            n_anchor,
            len(cfg.short_regions),
            cfg.seed,
        )
