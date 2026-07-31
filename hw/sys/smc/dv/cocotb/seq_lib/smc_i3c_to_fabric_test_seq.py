# SPDX-License-Identifier: Apache-2.0
"""I3C-window → fabric decode smoke (stub-aware).

Toggles the I3C CSR clock-gate control, restores it, then proves the I3C
wrapper CSR window is decoded by reading HCI_VERSION.

HONESTY (2026-07-29): product RTL instantiates ``i3ccore_stub`` → expected
completion is **SLVERR + 0xBADCAB1E**, not OpenTitan I3C protocol. This test
defends fabric decode / stub err-slv signature — **not** CCC/IBI / real core.
See ``hw/sys/smc/doc/dv_hack_cleanup_checklist.md`` Phase 2.1.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_base_test_seq import smc_base_test_seq

try:
    from .smc_i3c_vip_utils import (
        get_or_bind_i3c_controller,
        get_or_bind_i3c_slave,
        i3c_directed_sdr_write_proof,
    )
    _I3C_PROTOCOL_VIP_AVAILABLE = True
    _I3C_PROTOCOL_VIP_IMPORT_ERROR = None
except Exception as _exc:  # noqa: BLE001 - optional at import time
    get_or_bind_i3c_controller = None  # type: ignore[assignment]
    get_or_bind_i3c_slave = None  # type: ignore[assignment]
    i3c_directed_sdr_write_proof = None  # type: ignore[assignment]
    _I3C_PROTOCOL_VIP_AVAILABLE = False
    _I3C_PROTOCOL_VIP_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    OCA_I3C_WRAP_0_REG_MAP_BASE_ADDR,
    SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_ADDR,
)

CLOCK_GATE_CONTROL = SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_ADDR
I3C_CG_EN = 1 << 9

# OCA_I3C_WRAP_0 CSR base. RTL instantiates i3ccore_stub → SLVERR + 0xBADCAB1E.
I3C0_HCI_VERSION = OCA_I3C_WRAP_0_REG_MAP_BASE_ADDR
AXI_RESP_SLVERR = 2
I3C_STUB_SIGNATURE = 0xBADCAB1E


class smc_i3c_to_fabric_test_seq(smc_base_test_seq):
    """Exercise I3C clock gate and the OSS bounded stub-SLVERR path."""

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
        allow_error: bool = False,
        expect_error: bool = False,
        expected_resp: int | None = None,
    ) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        item.allow_error = allow_error or expect_error
        item.expect_error = expect_error
        item.expected_resp = expected_resp
        await self.start_item(item)
        await self.finish_item(item)
        self.reads += 1
        self.last_resp_code = item.resp_code
        if expected_resp is not None:
            assert item.resp_code == expected_resp, (
                f"{name} @ 0x{addr:08x}: resp={item.resp_code}, "
                f"expected {expected_resp}"
            )
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
        # Bind shared cocotbext-i3c target + controller via SMC OSS split-port
        # polarity/wired-AND adapter. Non-fatal on any wiring problem so the
        # existing CSR/HCI_VERSION checks continue to gate the test.
        if _I3C_PROTOCOL_VIP_AVAILABLE:
            get_or_bind_i3c_slave()
            get_or_bind_i3c_controller()

        self.clock_gate_value = await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        enabled = self.clock_gate_value | I3C_CG_EN
        await self._write("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, enabled)
        await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, expected=enabled)

        await self._write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL,
                          self.clock_gate_value)
        await self._read("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL,
                         expected=self.clock_gate_value)
        # i3ccore_stub terminates with SLVERR/0xBADCAB1E. Prove the periph xbar
        # routes the I3C window (no hang). Green scope = stub signature only.
        rdata = await self._read(
            "I3C0_HCI_VERSION",
            I3C0_HCI_VERSION,
            allow_error=True,
            expect_error=True,
            expected_resp=AXI_RESP_SLVERR,
        )
        assert self.reads == 4, "expected clock-gate checks plus one I3C CSR read"
        assert (rdata & 0xFFFF_FFFF) == I3C_STUB_SIGNATURE, (
            f"I3C stub signature mismatch: got 0x{rdata & 0xFFFF_FFFF:08X}, "
            f"expected 0x{I3C_STUB_SIGNATURE:08X}"
        )

        if _I3C_PROTOCOL_VIP_AVAILABLE:
            # Extra (non-gating) protocol traffic. Only claim "proof complete"
            # when the loopback actually drove the bus -- the helper returns
            # False (and logs a warning) if the VIP is unavailable or the drive
            # errored, in which case we must NOT log a success message.
            drove = await i3c_directed_sdr_write_proof()
            if drove:
                cocotb.log.info(
                    "I3C loopback proof complete: real START + RSVD + ADDR + "
                    "SDR-payload sequence driven onto tb_i3c0_* pins by the "
                    "shared cocotbext-i3c controller (target `TARGET:::Performing "
                    "write` log confirms the bus carried the traffic)"
                )
            else:
                cocotb.log.warning(
                    "I3C loopback proof did NOT drive the bus (VIP unavailable "
                    "or drive error); test still gated on the CSR/HCI_VERSION "
                    "checks above"
                )
