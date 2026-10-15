# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_ctp_status_reset_test - CTP STATUS read-back and CONFIG.RESET recovery.

Spec: cross_trigger_port.rdl (CONFIG.MODE/INVERT/RESET, STATUS),
cross_trigger_port/doc/architecture.adoc, cross_trigger_matrix.rdl (CT_SRC),
cross_trigger_network.rdl (CTN window).
STATUS.BUSY and the four level fields in both modes and both polarities, and the sender recovery
of CONFIG.RESET with the receive side running, on a point-to-point port routed from a wire-OR port.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xtrig_ctp_status_reset_test_seq import smu_xtrig_ctp_status_reset_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xtrig_ctp_status_reset_test(smu_base_test):
    """CTP STATUS levels and CONFIG.RESET handshake recovery at the SMU pads."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_xtrig_ctp_status_reset_test_seq(self).run()
