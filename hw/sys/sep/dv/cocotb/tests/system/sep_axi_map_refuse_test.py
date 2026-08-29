# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reserved addresses in the SEP memory map must be refused.

Ports the negative-decode behaviour of the OCAH ``sep_cpu_lsu_negative_matrix``,
``sep_cpu_ifu_invalid_target`` and ``sep_fabric_xbar_error_closure`` tests.

no_cpu / +skip_fuse_sense. RANDCFG: reserved gaps just above each live block
every seed, plus seed-selected addresses drawn from every reserved row.

The expectation comes from the allocation tables in
``hw/sys/sep/doc/memory_map.adoc``, parsed by ``env/sep_axi_decode_map.py``.
Rows marked ``_RSV_`` allocate nothing, so an access there must not answer
OKAY. DECERR versus SLVERR is not mandated by the map, so the flavour is
counted and logged rather than asserted.

CHK-OKAY is the live-bus control: a known-mapped CSR on the same bus returns
OKAY and its generated reset value. Without it a wedged or dead bus would
refuse every probe and read as a clean pass.

Scope: this walks the gaps BETWEEN block windows.
``sep_fabric_deadspace_decode_test`` walks the dead tail INSIDE a window, and
owns the write-alias check that a refused write left no live register changed.
Neither subsumes the other.

The run also logs every span the crossbar decode table routes that the map
calls reserved. Those are reported as info, not asserted: the RTL table is a
cross-check on the specification, never the source of the expectation.
"""

from __future__ import annotations

import pyuvm

from sep_base_test import sep_base_test
from env.sep_axi_decode_map import audit_rtl_vs_spec
from seq_lib.sep_axi_map_refuse_seq import (
    MAPPED_CSR_ADDR,
    SepAxiMapRefuse,
    SepAxiMapRefuseCfg,
)


@pyuvm.test()
class sep_axi_map_refuse_test(sep_base_test):
    """Every reserved address in the map is refused by the fabric."""

    async def run_scenario(self) -> None:
        cfg = SepAxiMapRefuseCfg(self.random_seed())
        self.logger.info("map-refuse config: %s", cfg.summary())

        # Cross-check, logged not asserted. A span here is an address the
        # crossbar routes that the map does not describe.
        for line in audit_rtl_vs_spec():
            self.logger.info("MAP-AUDIT: %s", line)

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
            "CHK-OKAY PASS: mapped CSR 0x%08x returned OKAY with its "
            "generated reset value", MAPPED_CSR_ADDR)

        fails: list[str] = []          # unrouted: a hard contract
        findings: list[str] = []       # routed-reserved: an open question
        for item in cfg.probes:
            tag = "anchor" if item.anchor else "rand"
            miss = await refuse.probe(item)
            if miss is None:
                self.logger.info(
                    "CHK-MAP-REFUSE PASS: %s 0x%08x refused (%s, %s, %s)",
                    item.op, item.addr, item.unit, item.klass, tag)
            elif item.klass == "unrouted":
                fails.append(miss)
                self.logger.error("CHK-MAP-REFUSE FAIL [%s]: %s", tag, miss)
            else:
                findings.append(miss)
                self.logger.info("MAP-OPEN [%s]: %s", tag, miss)

        # Findings first, so they are in the log whichever way the run ends.
        if findings:
            self.logger.info(
                "MAP-OPEN: %d routed-but-reserved address(es) completed. The "
                "crossbar routes these spans and memory_map.adoc calls them "
                "reserved. Whether the fabric must refuse them is a "
                "specification question and is NOT asserted here; resolving "
                "it from the RTL would let the decoder define its own "
                "contract.", len(findings))

        if fails:
            raise AssertionError(
                f"CHK-MAP-REFUSE FAIL: {len(fails)} address(es) that no "
                f"decode rule covers were not refused "
                f"({refuse.refused} of {len(cfg.probes)} refused)"
            )

        # Positive evidence: the unrouted contract was actually exercised, on
        # both channels. A write reaches the B path and a read the R path, and
        # a decoder can refuse one while completing the other.
        n_unrouted = sum(1 for p in cfg.probes if not p.routed)
        assert n_unrouted > 0, (
            "CHK-MAP-REFUSE FAIL: no unrouted address in the probe set; the "
            "hard contract was not exercised at all"
        )
        n_wr = sum(1 for p in cfg.probes if p.op == "w" and not p.routed)
        n_rd = sum(1 for p in cfg.probes if p.op == "r" and not p.routed)
        assert n_wr > 0 and n_rd > 0, (
            f"CHK-MAP-REFUSE FAIL: probe set is {n_rd} read(s) and {n_wr} "
            f"write(s); both channels must be exercised, or a decoder that "
            f"refuses one and completes the other passes"
        )
        self.logger.info(
            "CHK-MAP-REFUSE PASS: %d unrouted address(es) refused "
            "(%d DECERR, %d SLVERR); %d routed-but-reserved address(es) "
            "reported as MAP-OPEN, not asserted",
            n_unrouted, refuse.decerr, refuse.slverr, len(findings))
        # Raw-pin cross-check: the monitor counts DECERR beats it saw on the
        # bus, which is evidence independent of what the master reported. Every
        # credit armed for a DECERR was consumed by a real beat.
        seen = self.env.axi_monitor.expected_decerr_seen
        assert seen == refuse.decerr, (
            f"CHK-NONVAC FAIL: the master reported {refuse.decerr} DECERR "
            f"response(s) but the monitor saw {seen} on the bus"
        )
        self.logger.info(
            "CHK-NONVAC PASS: %d DECERR beat(s) observed on the bus match the "
            "%d the master reported", seen, refuse.decerr)
        self.logger.info(
            "CHK-RANDCFG PASS: walked %d probes (%d anchors) from seed %d",
            len(cfg.probes),
            sum(1 for p in cfg.probes if p.anchor),
            cfg.seed)
