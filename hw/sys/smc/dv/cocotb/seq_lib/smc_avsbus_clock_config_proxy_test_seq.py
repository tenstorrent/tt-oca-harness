# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus clock-gate proxy: the AVS_CFG window answers ungated and refuses while gated.

The proof is a two-sided, same-run experiment on one variable
(``CLOCK_GATE_CONTROL.AVS_CG_EN``):

* **Positive control** -- with the gate CLEARED, all three AVS_CFG windows must
  complete OKAY, and the word each returns is recorded
  ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
* **Negative leg** -- with the gate SET, the same three reads must complete
  SLVERR carrying the error-slave word ``0xBADCAB1E``, and a write into
  AVS_CFG_0 must complete SLVERR. The access gate in front of the AVSBus
  controller answers these on the SMC clock, so a no-response is a failure of
  this leg, never a pass: the driver raises on a timeout ([TIMEOUT-MUST-FAIL]).
* **Recovery** -- with the gate CLEARED again, the three windows answer OKAY
  with the words the positive control recorded, so the refused write took no
  effect and the AVSBus controller is reachable again.

Nothing here asserts the sequence's own access counters: reachability is
carried by ``assert_all_reachable`` (scoreboard cross-check) and the value
compares by the scoreboard's own ``sys_axi_value_checks_seen`` tally.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import AVS_CG_EN, CLOCK_GATE_CONTROL, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_SLVERR = 2
# The word the access gate's error slave returns while the AVSBus clock is gated.
GATED_RDATA = SmcCsrSeq.ERR_SLAVE_SIGNATURE

AVS_CFG_WINDOWS = [
    ("AVS_CFG_0", smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR")),
    ("AVS_CFG_1", smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_1_BASE_ADDR")),
    ("AVS_CONFIG", smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CONFIG_BASE_ADDR")),
]

# Directed-stimulus floor. Composition: 7 CLOCK_GATE_CONTROL accesses (save,
# write + readback ungated, write + readback gated, restore write + readback),
# one read per AVS_CFG window in each of the three probe loops (3 x 3 = 9) and
# the refused write into AVS_CFG_0 (1).
EXPECTED_ACCESSES = 17
# Value-checked reads: the three CLOCK_GATE_CONTROL readbacks and the three
# recovery reads compared against the positive control's words.
EXPECTED_VALUE_CHECKS = 6


class smc_avsbus_clock_config_proxy_test_seq(SmcCsrSeq):
    """AVS_CFG answers OKAY with AVS_CG_EN=0 and SLVERR/0xBADCAB1E with AVS_CG_EN=1."""

    def __init__(self, name: str = "smc_avsbus_clock_config_proxy_test_seq") -> None:
        super().__init__(name)
        # Words the positive control read, published for the testcase-level gate.
        self.ungated_words: dict[str, int] = {}
        # Gated reads that completed SLVERR with the error-slave word.
        self.gated_errors = 0
        # Response code of the refused write into AVS_CFG_0.
        self.gated_write_resp: int | None = None
        # Recovery reads that returned the positive control's word.
        self.recovered = 0
        self.value_checks = 0

    async def body(self) -> None:
        original = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)

        # ---- Positive control: gate CLEARED, the AVS_CFG windows answer OKAY ----
        ungated = original & ~AVS_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_AVS_OFF", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_AVS_OFF", CLOCK_GATE_CONTROL, expected=ungated)
        for name, addr in AVS_CFG_WINDOWS:
            # `csr_read` leaves allow_error False, so the scoreboard holds this
            # read to OKAY, and allow_timeout False, so a no-response raises in
            # the driver. Without this positive control the SLVERR below is
            # indistinguishable from a window that refuses every access.
            self.ungated_words[name] = await self.csr_read(f"{name}_UNGATED", addr)
            cocotb.log.info(
                "AVS positive control: %s @ 0x%08x answered OKAY with rdata=0x%08x "
                "with AVS_CG_EN cleared",
                name,
                addr,
                self.ungated_words[name],
            )

        # ---- Negative leg: gate SET, the same accesses complete SLVERR ----
        enabled = original | AVS_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_AVS_EN", CLOCK_GATE_CONTROL, enabled)
        await self.csr_read("CLOCK_GATE_CONTROL_AVS_EN", CLOCK_GATE_CONTROL, expected=enabled)
        for name, addr in AVS_CFG_WINDOWS:
            # Exact code and exact word: the helper asserts both, and the
            # scoreboard enforces the code again through `expected_resp`.
            await self.csr_read_err_signature(f"{name}_GATED", addr, resp=AXI_RESP_SLVERR)
            self.gated_errors += 1
        name0, addr0 = AVS_CFG_WINDOWS[0]
        # The complement of the recorded word, so a write that leaked through
        # the gate into a writable field is caught by the recovery read.
        self.gated_write_resp = await self.csr_write_expect_error(
            f"{name0}_GATED",
            addr0,
            (~self.ungated_words[name0]) & 0xFFFF_FFFF,
            resp=AXI_RESP_SLVERR,
        )

        # ---- Recovery: gate CLEARED again, the windows answer the recorded words ----
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, expected=ungated)
        for name, addr in AVS_CFG_WINDOWS:
            await self.csr_read(f"{name}_RECOVERED", addr, expected=self.ungated_words[name])
            self.recovered += 1

        # ---- Reconciliation against the scoreboard, not against self-counts ----
        self.assert_all_reachable(EXPECTED_ACCESSES, "AVSBUS_CLOCK_CONFIG")
        sb = self.env.scoreboard
        self.value_checks = sb.sys_axi_value_checks_seen
        assert self.value_checks >= EXPECTED_VALUE_CHECKS, (
            f"expected {EXPECTED_VALUE_CHECKS} value-checked SEP_IN AXI reads "
            f"(AVS_CG_EN cleared / set / restored readbacks and the three recovery "
            f"reads), scoreboard saw {self.value_checks}"
        )
        cocotb.log.info(
            "CHK-AVSBUS-CG: AVS_CG_EN=0 -> all %d AVS_CFG window(s) answered OKAY (%s); "
            "AVS_CG_EN=1 -> all %d answered SLVERR with 0x%08X and the write into %s was "
            "refused with resp=%d; AVS_CG_EN=0 again -> all %d answered OKAY with the "
            "recorded word; CLOCK_GATE_CONTROL 0x%x -> 0x%x -> 0x%x readback-checked; "
            "scoreboard value_checks=%d (>= %d)",
            len(AVS_CFG_WINDOWS),
            ",".join(f"{n}=0x{self.ungated_words[n]:08x}" for n, _ in AVS_CFG_WINDOWS),
            self.gated_errors,
            GATED_RDATA,
            name0,
            self.gated_write_resp,
            self.recovered,
            ungated,
            enabled,
            ungated,
            self.value_checks,
            EXPECTED_VALUE_CHECKS,
        )
