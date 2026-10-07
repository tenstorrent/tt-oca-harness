# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Downstream STAP TAP devices: one reactive ``ocah_jtag_vip`` slave per STAP host port.

Each DTP STAP host port (I/O, SMC, SEP, extra0) can splice a behavioral IEEE
1149.1 TAP behind it instead of the default wire loopback: ``tb_top`` routes
the shared slave device's TDO into the STAP host TDI while the port's
``dtp_scan_if.stap_<x>_ds_en`` is set. The device map is
distinct per port (IDCODE and ``DS_TDR`` width), so a swapped or misaligned
splice is caught by the chain readback. The SV-UVM ``dtp_env`` builds the
same four devices from the same values.

Tests opt in per port through ``DtpEnvCfg.stap_ds_attach``; every other
scenario keeps the loopback. Sequences reach a device only through its
``OcahJtagSlaveSequence`` (``cfg.stap_ds_seq``) and describe it to the scan
reference model from ``cfg.stap_ds_device``.
"""

from __future__ import annotations

from ocah_jtag_vip import (
    OcahJtagChecker,
    OcahJtagSlaveAgent,
    OcahJtagSlaveConfig,
    OcahJtagSlaveSequence,
)
from pyuvm import ConfigDB, uvm_component

from .dtp_stap_3dcr_model import STAP_ORDER
from .dtp_tb_if import JTAG_SIGNAL_MAP

__all__ = [
    "DtpStapDsAgent",
    "STAP_DS_DEVICES",
    "STAP_DS_IDCODE_OPCODE",
    "STAP_DS_IR_WIDTH",
    "STAP_DS_TDR_NAME",
    "STAP_DS_TDR_OPCODE",
    "stap_ds_config",
]

STAP_DS_IR_WIDTH = 5
STAP_DS_IDCODE_OPCODE = 0x01
STAP_DS_TDR_OPCODE = 0x02
STAP_DS_TDR_NAME = "DS_TDR"

# STAP name -> (IDCODE with the IEEE 1149.1 marker bit set, DS_TDR width).
# Parity contract with uvm/env/dtp_types.svh (dtp_stap_ds_idcode / dtp_stap_ds_tdr_width).
STAP_DS_DEVICES: dict[str, tuple[int, int]] = {
    "io": (0x1D51_0101, 12),
    "smc": (0x1D51_0203, 16),
    "sep": (0x1D51_0305, 20),
    "extra0": (0x1D51_0407, 8),
}


def stap_ds_config(stap: str) -> OcahJtagSlaveConfig:
    """Slave configuration for one downstream STAP TAP."""
    idcode, tdr_width = STAP_DS_DEVICES[stap]
    return OcahJtagSlaveConfig(
        name=f"dtp_stap_{stap}_ds",
        idcode=idcode,
        ir_width=STAP_DS_IR_WIDTH,
        registers={
            "IDCODE": (32, STAP_DS_IDCODE_OPCODE),
            STAP_DS_TDR_NAME: (tdr_width, STAP_DS_TDR_OPCODE, True),
        },
        signal_map=JTAG_SIGNAL_MAP,
        # The STAP host port has no downstream tdo_oen input.
        drive_tdo_oen=False,
    )


class DtpStapDsAgent(uvm_component):
    """Builds the four downstream devices; responds only on attached ports."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        self.agents: dict[str, OcahJtagSlaveAgent] = {}
        for stap in STAP_ORDER:
            # No passive monitor: the composed-chain scans span the whole
            # network, so per-device scan reconstruction carries no checkable
            # width; the evidence is the device's own state and Update-DR
            # history through the slave sequence.
            agent = OcahJtagSlaveAgent(
                self.tb_if.stap_ds[stap],
                config=stap_ds_config(stap),
                en_monitor=False,
                attach_checker=False,
            )
            self.agents[stap] = agent
            self.cfg.stap_ds_device[stap] = agent.device
            # Scenario passes rebind .checker to their per-pass family checker.
            self.cfg.stap_ds_seq[stap] = OcahJtagSlaveSequence(
                agent.responder,
                checker=OcahJtagChecker(
                    name=f"dtp_stap_{stap}_ds.seq_checker", raise_on_error=False
                ),
            )

    async def run_phase(self) -> None:
        await self.cfg.reset_done.wait()
        for stap in STAP_ORDER:
            if stap not in self.cfg.stap_ds_attach:
                continue
            await self.agents[stap].start()
            idcode, tdr_width = STAP_DS_DEVICES[stap]
            self.logger.info(
                "downstream TAP attached behind STAP %s: idcode=0x%08x ir_width=%d %s width=%d",
                stap,
                idcode,
                STAP_DS_IR_WIDTH,
                STAP_DS_TDR_NAME,
                tdr_width,
            )
