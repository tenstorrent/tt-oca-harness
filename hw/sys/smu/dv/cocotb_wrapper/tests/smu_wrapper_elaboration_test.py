# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-CARD:          SMU_ALL_001   ANCHOR: smu_wrapper_elaboration_test
"""PyUVM entry point for the production SMU wrapper elaboration smoke."""

from __future__ import annotations

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

    #: Stamped here once the sequence's card steps and its CHK-NONVAC fence
    #: have all held; the compares behind it are the CHK-* lines in the
    #: sequence log.
    required_evidence = ("WRAP_ELAB_OK",)

    async def run_scenario(self) -> None:
        await SmuWrapperElaborationSeq(self).run()
        _log_evidence(self.logger, "WRAP_ELAB_OK")
        self.logger.info("CHK-WRAP-ELAB WRAP_ELAB_OK: wrapper elaboration and reset legs completed")
