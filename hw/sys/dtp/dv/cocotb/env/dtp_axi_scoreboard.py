# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP AXI scoreboard lifecycle owner.

Thin DUT-local wrapper that builds the shared ``ocah_axi_vip`` reference models
and scoreboard for the three JTAG2AXI targets, publishes them through the env
cfg for sequences, and finalizes once in ``check_phase``. The shared classes own
all comparison and evidence mechanics; this component owns only lifecycle,
stream routing, and DTP policy.

Opt-in: tests set ``use_axi_scoreboard = True`` (see ``dtp_base_test``); the
component stays inert otherwise.
"""

from __future__ import annotations

from ocah_axi_vip import OcahAxiRefModel, OcahAxiScoreboard
from pyuvm import ConfigDB, uvm_component

from .dtp_types import get_jtag2axi_target

JTAG2AXI_TARGETS = ("smc_axi", "smc_otp", "sep_otp")


class DtpAxiScoreboard(uvm_component):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.scoreboard: OcahAxiScoreboard | None = None
        if not getattr(self.cfg, "axi_scoreboard_enabled", False):
            return

        models = {
            target: OcahAxiRefModel(
                name=f"dtp_{target}_model",
                beat_bytes=get_jtag2axi_target(target).beat_bytes,
            )
            for target in JTAG2AXI_TARGETS
        }
        self.scoreboard = OcahAxiScoreboard(
            name="dtp-axi-scoreboard",
            raise_on_error=False,
            required_ids=self.cfg.axi_checker_required_ids,
            min_transactions_per_stream=self.cfg.axi_checker_stream_minimums,
            logger=self.logger,
        )
        for target, model in models.items():
            self.scoreboard.set_stream_model(target, model)

        self.cfg.axi_scoreboard = self.scoreboard
        self.cfg.axi_models = models
        self.logger.info(
            "DTP AXI scoreboard enabled (required_ids=%s stream_minimums=%s)",
            sorted(self.cfg.axi_checker_required_ids),
            self.cfg.axi_checker_stream_minimums,
        )

    def check_phase(self) -> None:
        if self.scoreboard is None:
            return
        # Halt observation BEFORE finalizing so no callback can land after
        # the summary; the scoreboard also hard-rejects post-finalize items.
        for monitor in getattr(self.cfg, "axi_monitors", {}).values():
            monitor.halt()
        for target, watcher in getattr(self.cfg, "axi_watchers", {}).items():
            watcher.halt()
            watcher.report(
                self.scoreboard.evidence,
                context=f"target={target}",
            )
        self.scoreboard.finalize()
