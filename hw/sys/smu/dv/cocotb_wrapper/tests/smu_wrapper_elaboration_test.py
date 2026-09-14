# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-CARD:          SMU_ALL_001   ANCHOR: smu_wrapper_elaboration_sep_rtl_test
"""PyUVM entry point for the production SMU wrapper elaboration smoke."""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smu_wrapper_elaboration_seq import SmuWrapperElaborationSeq
from smu_base_test import smu_base_test


def _log_evidence(logger, token: str) -> None:
    """Emit the evidence aliases in the SmuScoreboard log format."""
    logger.info("EVIDENCE: %s", token)
    logger.info("EVIDENCE:%s", token)
    if not token.startswith("CHK-"):
        logger.info("EVIDENCE:CHK-%s", token)
        logger.info("EVIDENCE: CHK-%s", token)


@pyuvm.test()
class smu_wrapper_elaboration_test(smu_base_test):
    """Verify the selected production-wrapper profile and reset propagation."""

    require_distinct_ref_smu = True

    async def run_scenario(self) -> None:
        await SmuWrapperElaborationSeq(self).run()

        expected_sep = int(cocotb.plusargs.get("expected_sep", "0"), 0)
        # no_sep leaf evidence token.
        # SEP=1 card evidence is emitted inside the sequence (CHK-SMU-*).
        if expected_sep == 0:
            # CHK-NONVAC is emitted by the sequence after its ordered fence.
            token = "WRAP_ELAB_OK"
            _log_evidence(self.logger, token)
            self.logger.info(
                "CHK-WRAP-ELAB %s: no-SEP wrapper elaboration and reset legs "
                "completed; the compares behind it are the CHK-* lines in the "
                "sequence log",
                token,
            )
        else:
            _log_evidence(self.logger, "WRAP_ELAB_SEP_OK")
            self.logger.info(
                "SMU_ALL_001 sequence complete (SEP=1 card CHK-* lines in sequence log)"
            )
