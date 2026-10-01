# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP TB interface accessor: the one place cocotb touches the HDL top.

``tb_top.sv`` instantiates one control-domain ``dtp_tb_if``, one
``dtp_scan_if``, one ``dtp_xtrig_if``, the primary-TAP and four
downstream-TAP ``ocah_jtag_if`` instances, and one active plus one passive
``ocah_axi_if`` per DTP bus. ``DtpTbIf`` holds those hierarchical handles,
resolves DTP observables by their flat names across the three domain
interfaces, drives and samples the lifecycle debug disables by field name,
and binds the shared AXI VIP at each bus's real geometry through
``OcahAxiConfig``. The SV-UVM twin is the set of ``virtual`` interface
handles ``dtp_env`` publishes; the member names are identical.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ocah_axi_vip import OcahAxiBus, OcahAxiConfig, OcahAxiProtocol

from .dtp_dbg_disable import DBG_DISABLE_FIELDS, full_dbg_disable, validate_dbg_disable
from .dtp_dv_cfg import DTP_NUM_CLK_STOP_REQ, DV_CFG_PARITY
from .dtp_scan_ref_model import STAP_ORDER

__all__ = ["DtpTbIf"]

# ocah_jtag_if member names for the VIP's logical JTAG signal names; the
# other five members carry the logical names themselves.
JTAG_SIGNAL_MAP: dict[str, str] = {"trst": "trst_n"}

_DBG_DISABLE_PREFIX = "dbg_disable_"

# Flat observable names that map onto a member of a different name (or of the
# primary-TAP interface).
_ALIASES: dict[str, tuple[str, str]] = {
    "clk_i": ("ctrl", "clk"),
    "rst_n_i": ("ctrl", "sys_rst_n"),
    "pwr_on_rst_ni": ("ctrl", "por_rst_n"),
    "jtag_ptap_state": ("ctrl", "tap_state"),
    "jtag_ptap_inst_decoded": ("ctrl", "inst_decoded"),
    "jtag_tck": ("jtag", "tck"),
    "jtag_tms": ("jtag", "tms"),
    "jtag_tdi": ("jtag", "tdi"),
    "jtag_tdo": ("jtag", "tdo"),
    "jtag_tdo_oen": ("jtag", "tdo_oen"),
    "jtag_trst": ("jtag", "trst_n"),
}


class DtpTbIf:
    """Hierarchical handles of the DTP TB interfaces plus name and geometry resolution."""

    JTAG_SIGNAL_MAP = JTAG_SIGNAL_MAP
    SMC_AXI_GEOMETRY = OcahAxiConfig(
        protocol=OcahAxiProtocol.AXI4, addr_width=56, data_width=64, id_width=2, user_width=12
    )
    OTP_AXIL_GEOMETRY = OcahAxiConfig(
        protocol=OcahAxiProtocol.AXI4_LITE, addr_width=32, data_width=32
    )
    XTRIG_AXIL_GEOMETRY = OcahAxiConfig(
        protocol=OcahAxiProtocol.AXI4_LITE, addr_width=32, data_width=32
    )

    def __init__(self, top: Any) -> None:
        self.top = top
        self.ctrl = top.u_tb_if
        self.scan = top.u_scan_if
        self.xtrig = top.u_xtrig_if
        self.jtag = top.u_jtag_if
        self.stap_ds = {stap: getattr(top, f"u_stap_{stap}_ds_if") for stap in STAP_ORDER}
        self._axi_active = {
            "smc_axi": top.u_smc_axi_slave_if,
            "smc_otp": top.u_smc_otp_slave_if,
            "sep_otp": top.u_sep_otp_slave_if,
            "xtrig": top.u_xtrig_master_if,
        }
        self._axi_passive = {
            "smc_axi": top.u_m_axi_if,
            "smc_otp": top.u_smc_otp_axil_if,
            "sep_otp": top.u_sep_otp_axil_if,
            "xtrig": top.u_xtrig_axil_if,
        }
        self._axi_geometry = {
            "smc_axi": self.SMC_AXI_GEOMETRY,
            "smc_otp": self.OTP_AXIL_GEOMETRY,
            "sep_otp": self.OTP_AXIL_GEOMETRY,
            "xtrig": self.XTRIG_AXIL_GEOMETRY,
        }

    # --- clock and resets -----------------------------------------------------
    @property
    def clk(self) -> Any:
        return self.ctrl.clk

    @property
    def sys_rst_n(self) -> Any:
        return self.ctrl.sys_rst_n

    @property
    def por_rst_n(self) -> Any:
        return self.ctrl.por_rst_n

    # --- observables and stimulus by flat name -------------------------------
    def handle(self, name: str) -> Any:
        """Signal handle of a DTP observable or stimulus by its flat name."""
        alias = _ALIASES.get(name)
        if alias is not None:
            return getattr(getattr(self, alias[0]), alias[1])
        for scope in (self.ctrl, self.scan, self.xtrig):
            if hasattr(scope, name):
                return getattr(scope, name)
        raise AttributeError(f"{name} is not a member of the DTP TB interfaces")

    def has(self, name: str) -> bool:
        """True when ``name`` resolves to a member of the DTP TB interfaces."""
        try:
            self.handle(name)
        except AttributeError:
            return False
        return True

    def sample(self, name: str) -> int:
        """Integer value of a member by its flat name."""
        return int(self.handle(name).value)

    # --- lifecycle debug disables ---------------------------------------------
    def dbg_disable(self) -> dict[str, int]:
        """Current dbg_disable fields (1 = path disabled)."""
        return {name: self.dbg_field(name) for name in DBG_DISABLE_FIELDS}

    def dbg_field(self, name: str) -> int:
        """Driven value of one dbg_disable field by name."""
        return int(self._dbg_handle(name).value)

    def set_dbg_disable(self, values: Mapping[str, int]) -> None:
        """Drive the named dbg_disable fields; the other fields keep their state."""
        for name, value in validate_dbg_disable(values).items():
            self._dbg_handle(name).value = value

    def set_dbg_disable_vector(self, values: Mapping[str, int] | None) -> None:
        """Drive all eleven dbg_disable fields; unnamed fields are enabled (0)."""
        self.set_dbg_disable(full_dbg_disable(values))

    def _dbg_handle(self, name: str) -> Any:
        if name not in DBG_DISABLE_FIELDS:
            raise ValueError(f"unknown dbg_disable field {name!r}")
        return getattr(self.ctrl, _DBG_DISABLE_PREFIX + name)

    # --- bench configuration -----------------------------------------------------
    def check_dv_cfg(self) -> None:
        """Compare the configuration ``tb_top`` elaborated with this realization's copy."""
        mismatches: dict[str, tuple[int, int]] = {}
        for name, expected in DV_CFG_PARITY.items():
            observed = self.sample(name)
            if observed != expected:
                mismatches[name] = (observed, expected)
        width = len(self.ctrl.xtrig_clk_stop_req)
        if width != DTP_NUM_CLK_STOP_REQ:
            mismatches["xtrig_clk_stop_req width"] = (width, DTP_NUM_CLK_STOP_REQ)
        if mismatches:
            raise RuntimeError(
                f"dtp_dv_cfg.py disagrees with dtp_dv_cfg_pkg.sv (observed, expected): {mismatches}"
            )

    # --- JTAG2AXI bridge state --------------------------------------------------
    def bridge_fsm_idle(self, target: str) -> int:
        """1 while the bridge's AXI state machine is idle."""
        return self.sample(f"{target}_fsm_idle")

    def bridge_fsm_on_path(self, target: str, *, read: bool) -> int:
        """1 while the bridge's AXI state machine is on the read or the write path."""
        return self.sample(f"{target}_fsm_{'read' if read else 'write'}_path")

    def bridge_op_pending(self, target: str) -> int:
        """1 while the bridge holds a launched SINGLE_OP."""
        return self.sample(f"{target}_op_pending")

    def cdc_clear_seen(self, target: str) -> int:
        """1 once the bridge's CDC has run its TCK-side isolate-and-clear since the last clear."""
        return self.sample(f"{target}_cdc_clear_seen")

    def set_cdc_clear_seen_clear(self, value: int) -> None:
        """Hold ``cdc_clear_seen_clear``: 1 clears every bridge's sticky clear-seen flag."""
        self.handle("cdc_clear_seen_clear").value = value

    def set_error_rdata(self, prefix: str, value: int) -> None:
        """Drive the errored-beat read word of the bridge port whose activity prefix is ``prefix``."""
        self.handle(f"{prefix}_err_rdata").value = value

    # --- shared AXI VIP binding -----------------------------------------------
    def axi_bus(self, target: str, *, passive: bool = False) -> OcahAxiBus:
        """Shared-VIP bus handle over one DTP AXI interface at the bus's real geometry.

        ``target`` is ``smc_axi``, ``smc_otp``, ``sep_otp``, or ``xtrig``; the
        active instance carries the responder or initiator connection, the
        passive one feeds the monitors.
        """
        scopes = self._axi_passive if passive else self._axi_active
        if target not in scopes:
            raise ValueError(f"unknown DTP AXI target {target!r}")
        return self._axi_geometry[target].bus(scopes[target])
