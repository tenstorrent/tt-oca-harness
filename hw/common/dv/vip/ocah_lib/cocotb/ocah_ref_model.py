# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reference-model base: the per-feature predictor behind the mandatory bench scoreboard.

A bench ``<Dut><Feature>RefModel`` extends it. It subscribes to the VIP
monitor stream the feature is observed on, reads TB observables through the
handles the env plumbs, keeps whatever model state the prediction needs, and
republishes one expected item per transaction it predicts on ``expected_ap``,
in observation order; the scoreboard pairs that stream with the observed one.
Expected values derive from configuration and the observed stimulus, never
from the observation under check. A reference model performs no comparison
and emits no verdict: a mismatch is the scoreboard's finding. ``write()``
never awaits. The SV-UVM twin is ``ocah_ref_model``.
"""

from __future__ import annotations

from pyuvm import uvm_analysis_port, uvm_subscriber

__all__ = ["OcahRefModel"]


class OcahRefModel(uvm_subscriber):
    """Observed stream in through ``analysis_export``, expected items out on ``expected_ap``."""

    def __init__(self, name: str, parent: object) -> None:
        super().__init__(name, parent)
        # Expected items, one per predicted transaction, in observation order.
        self.expected_ap = uvm_analysis_port("expected_ap", self)

    def write(self, item: object) -> None:
        """Stream handler; every concrete reference model overrides it.

        The base accepts and drops, so an unconnected base instance is inert.
        """
