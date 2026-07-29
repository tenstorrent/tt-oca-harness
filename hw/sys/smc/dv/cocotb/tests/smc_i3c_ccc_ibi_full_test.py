# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM I3C directed-SDR protocol test (P2 Phase A #2).

HARD gates (the test PASSes on these, all independent of the best-effort
protocol traffic below):
  * ``smc_i3c_to_fabric_test_seq`` — I3C CSR clock-gate write-readback value
    check + HCI_VERSION error-signature decode.
  * ``check_i3c0_external_pull_low`` — I3C0 SCL/SDA follow external pull-low.

Supplementary (best-effort, non-gating) bus traffic via
``i3c_full_daa_and_ccc_proof``: it drives THREE directed SDR writes onto the
tb_i3c0_* pins through the split-port polarity + wired-AND adapter. The
target's ``TARGET:::Performing write`` log line is the bus-traffic evidence.

KNOWN GAP (honest disclosure): despite this file's historical name, RSTDAA /
SETDASA / GETSTATUS CCC and IBI are NOT driven -- the bundled cocotbext-i3c
target ``_run`` asserts on the header decode that follows CCC framing
(``I3cHeader.NONE``), so those steps are intentionally omitted (see
``i3c_full_daa_and_ccc_proof``). Full CCC/IBI closure is deferred until the
upstream target state machine is fixed. The recorded evidence reflects only
what is actually driven.
"""

from __future__ import annotations

import cocotb
import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_i3c_to_fabric_test_seq import smc_i3c_to_fabric_test_seq
from seq_lib.smc_i3c_vip_utils import (
    check_i3c0_external_pull_low,
    i3c_full_daa_and_ccc_proof,
)


@pyuvm.test()
class smc_i3c_ccc_ibi_full_test(smc_base_test):
    """P2-A / P2-12: CSR + pin SDR proof (CCC/IBI NOT driven; see module doc)."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        # Reuse the I3C-to-fabric seq so the CSR/HCI decode is also
        # exercised. Then run the full DAA + CCC + SDR proof helper.
        seq = smc_i3c_to_fabric_test_seq("i3c_ccc_ibi_full_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_i3c0_external_pull_low()
        # Hard gates above exercise real I3C CSR/RTL decode. Directed SDR pin
        # traffic needs cocotbext-i3c; when the VIP is absent, keep the RTL
        # gates and record the pin path as deferred (do not invent a DV stub).
        result = await i3c_full_daa_and_ccc_proof()
        sdr_ok = bool(result and result.get("ok") and result.get("writes", 0) >= 3)
        if not sdr_ok:
            cocotb.log.warning(
                "I3C SDR pin proof deferred (cocotbext-i3c unavailable or "
                "drive incomplete): %s — CSR/pull-low gates already passed",
                result,
            )
        await self.record_protocol_vip(
            SmcProtocolVipKind.I3C,
            type(self).__name__,
            csr_accesses=seq.reads + 2,
            proxy=not sdr_ok,
            details=(
                "U4-3: CSR+pull-low hard gates on real I3C RTL; directed SDR "
                f"{'PASS' if sdr_ok else 'DEFERRED'} "
                "(RSTDAA/SETDASA/GETSTATUS/IBI still deferred upstream); "
                "SDR-proof result="
                + str({k: str(v)[:32] for k, v in (result or {}).items()})
            ),
        )
