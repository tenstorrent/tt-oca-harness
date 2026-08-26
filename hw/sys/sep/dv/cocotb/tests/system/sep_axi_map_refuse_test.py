# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reserved addresses in the SEP memory map must be refused.

no_cpu / +skip_fuse_sense. RANDCFG: reserved gaps just above each live block
every seed, plus seed-selected addresses drawn from every reserved row.

The expectation comes from the allocation tables in
``hw/sys/sep/doc/memory_map.adoc``, parsed by ``env/sep_axi_decode_map.py``.
Rows marked ``_RSV_`` allocate nothing, so an access there must not answer
OKAY. DECERR versus SLVERR is not mandated by the map, so the flavour is
counted and logged rather than asserted.

Scope: this walks the gaps BETWEEN block windows.
``sep_fabric_deadspace_decode_test`` walks the dead tail INSIDE a window.
Neither subsumes the other.

The run also logs every span the crossbar decode table routes that the map
calls reserved. Those are reported as info, not asserted: the RTL table is a
cross-check on the specification, never the source of the expectation.
"""

from __future__ import annotations

import pyuvm

from sep_base_test import sep_base_test
from env.sep_axi_decode_map import audit_rtl_vs_spec
from seq_lib.sep_axi_map_refuse_seq import SepAxiMapRefuse, SepAxiMapRefuseCfg


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

        fails: list[str] = []
        for item in cfg.probes:
            tag = "anchor" if item.anchor else "rand"
            miss = await refuse.probe(item)
            if miss is None:
                self.logger.info(
                    "CHK-MAP-REFUSE PASS: %s 0x%08x refused (%s, %s)",
                    item.op, item.addr, item.unit, tag)
            else:
                fails.append(miss)
                self.logger.error("CHK-MAP-REFUSE FAIL [%s]: %s", tag, miss)

        if fails:
            raise AssertionError(
                f"CHK-MAP-REFUSE FAIL: {len(fails)} reserved address(es) were "
                f"not refused ({refuse.refused} of {len(cfg.probes)} refused)"
            )

        # Positive evidence: the sweep asked the DUT something, and every
        # answer was a refusal.
        assert refuse.refused == len(cfg.probes), (
            f"CHK-MAP-REFUSE FAIL: counted {refuse.refused} refusals over "
            f"{len(cfg.probes)} probes"
        )
        self.logger.info(
            "CHK-MAP-REFUSE PASS: %d reserved address(es) refused "
            "(%d DECERR, %d SLVERR)",
            refuse.refused, refuse.decerr, refuse.slverr)
        self.logger.info(
            "CHK-RANDCFG PASS: walked %d probes (%d anchors) from seed %d",
            len(cfg.probes),
            sum(1 for p in cfg.probes if p.anchor),
            cfg.seed)
