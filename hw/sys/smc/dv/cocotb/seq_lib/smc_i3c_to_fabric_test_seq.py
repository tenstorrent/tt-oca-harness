# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I3C-window → fabric decode smoke (real OCA I3C core).

Toggles the I3C CSR clock-gate control, restores it, then proves the I3C
wrapper CSR window is decoded by reading HCI_VERSION (OKAY + 0x120).

Optional cocotbext-i3c VIP bind remains non-gating when the package is absent.
"""

from __future__ import annotations

import cocotb

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import I3C_CG_EN, smc_addr
from .smc_base_test_seq import smc_base_test_seq

try:
    from .smc_i3c_vip_utils import (
        get_or_bind_i3c_controller,
        get_or_bind_i3c_slave,
        i3c_directed_sdr_write_proof,
    )

    _I3C_PROTOCOL_VIP_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001 - optional at import time
    get_or_bind_i3c_controller = None  # type: ignore[assignment]
    get_or_bind_i3c_slave = None  # type: ignore[assignment]
    i3c_directed_sdr_write_proof = None  # type: ignore[assignment]
    _I3C_PROTOCOL_VIP_AVAILABLE = False

CLOCK_GATE_CONTROL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)
I3C0_HCI_VERSION = smc_addr("SMC_TOP_OCA_I3C_WRAP_0_BASE_ADDR")
# OpenTitan / OCA I3C HCI_VERSION reset observed on this DUT.
I3C_HCI_VERSION_RESET = 0x120


class smc_i3c_to_fabric_test_seq(smc_base_test_seq):
    """Exercise I3C clock gate and real HCI_VERSION decode."""

    def __init__(self, name: str = "smc_i3c_to_fabric_test_seq") -> None:
        super().__init__(name)
        self.clock_gate_value: int = 0
        self.reads = 0
        self.last_resp_code: int | None = None

    async def _read(
        self,
        name: str,
        addr: int,
        expected: int | None = None,
    ) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.reads += 1
        self.last_resp_code = item.resp_code
        return item.rdata

    async def _write(self, name: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)

    async def body(self) -> None:
        if _I3C_PROTOCOL_VIP_AVAILABLE:
            get_or_bind_i3c_slave()
            get_or_bind_i3c_controller()

        self.clock_gate_value = await self._read(
            "CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL
        )
        enabled = self.clock_gate_value | I3C_CG_EN
        await self._write("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, enabled)
        await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, expected=enabled)

        await self._write(
            "CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, self.clock_gate_value
        )
        await self._read(
            "CLOCK_GATE_CONTROL_RESTORE",
            CLOCK_GATE_CONTROL,
            expected=self.clock_gate_value,
        )

        # Real OCA I3C core: window must complete OKAY with HCI_VERSION reset.
        rdata = await self._read("I3C0_HCI_VERSION", I3C0_HCI_VERSION)
        assert self.reads == 4, "expected clock-gate checks plus one I3C CSR read"
        assert self.last_resp_code == 0, (
            f"I3C0_HCI_VERSION @ 0x{I3C0_HCI_VERSION:08x}: expected OKAY, "
            f"got resp={self.last_resp_code}"
        )
        assert (rdata & 0xFFFF_FFFF) == I3C_HCI_VERSION_RESET, (
            f"I3C HCI_VERSION mismatch: got 0x{rdata & 0xFFFF_FFFF:08X}, "
            f"expected 0x{I3C_HCI_VERSION_RESET:08X}"
        )

        if _I3C_PROTOCOL_VIP_AVAILABLE:
            drove = await i3c_directed_sdr_write_proof()
            if drove:
                cocotb.log.info(
                    "I3C loopback proof complete: real START + RSVD + ADDR + "
                    "SDR-payload sequence driven onto tb_i3c0_* pins"
                )
            else:
                cocotb.log.warning(
                    "I3C loopback proof did NOT drive the bus (VIP unavailable "
                    "or drive error); test still gated on CLOCK_GATE + HCI_VERSION"
                )
        else:
            cocotb.log.info(
                "cocotbext-i3c not installed; CSR/HCI_VERSION gate only"
            )
