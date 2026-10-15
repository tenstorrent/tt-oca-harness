# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP AXI scoreboard lifecycle owner.

Thin DUT-local wrapper that builds the shared ``ocah_axi_vip`` reference models
and scoreboard for the three JTAG2AXI targets, publishes them through the env
cfg for sequences, and finalizes once in ``check_phase``. The shared classes own
all comparison and evidence mechanics; this component owns only lifecycle,
stream routing, and DTP policy. A test that names per-bridge IDs also gets one
checker per bridge for the sequence's judgements of that bridge, and each of
the three must record every such ID.

Opt-in: tests set ``use_axi_scoreboard = True`` (see ``dtp_base_test``); the
component stays inert otherwise.
"""

from __future__ import annotations

from ocah_axi_vip import OcahAxiRefModel, OcahAxiScoreboard
from ocah_checker import OcahChecker
from pyuvm import ConfigDB, uvm_component

from .dtp_types import JTAG2AXI_TARGETS

__all__ = ["DtpAxiScoreboard"]


class DtpAxiScoreboard(uvm_component):
    """Builds, publishes and finalizes the shared AXI scoreboard and its per-bridge checkers."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.scoreboard: OcahAxiScoreboard | None = None
        self.target_evidence: dict[str, OcahChecker] = {}
        if not getattr(self.cfg, "axi_scoreboard_enabled", False):
            return

        models = {
            target: OcahAxiRefModel(name=f"dtp_{target}_model", beat_bytes=cfg.beat_bytes)
            for target, cfg in JTAG2AXI_TARGETS.items()
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
        target_ids = self.cfg.axi_checker_target_required_ids
        if target_ids:
            self.target_evidence = {
                target: OcahChecker(
                    name=f"dtp-axi-{target}",
                    required_ids=target_ids,
                    fail_fast=False,
                    logger=self.logger,
                )
                for target in JTAG2AXI_TARGETS
            }

        self.cfg.axi_scoreboard = self.scoreboard
        self.cfg.axi_models = models
        self.cfg.axi_target_evidence = self.target_evidence
        self.logger.info(
            "DTP AXI scoreboard enabled (required_ids=%s target_required_ids=%s "
            "stream_minimums=%s)",
            sorted(self.cfg.axi_checker_required_ids),
            sorted(target_ids),
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
        # Every checker finalizes, so one failing checker cannot hide another.
        problems = []
        for checker in (*self.target_evidence.values(), self.scoreboard):
            try:
                checker.finalize()
            except AssertionError as exc:
                problems.append(str(exc))
        if problems:
            raise AssertionError("; ".join(problems))
