# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO register-driven output (core2pad) driveback verification.

Programs GPIO wrap 0 as a register-driven TX output and checks the DUT pad
outputs actually follow the CSR programming.

The tb_top ``tb_gpio_core2pad_*`` observables are OR-reductions over the whole
``core2pad_o`` pad bus (which also carries idle-high LSIO pads such as UART TX),
so they cannot isolate a single GPIO wrap. Instead this sequence reads the full
``tb_core2pad_o`` / ``tb_core2pad_en_o`` buses (TB mirrors of real
``smc.core2pad_*``) and isolates wrap 0 by *delta*: only wrap 0 is programmed,
so exactly one output-enable bit must change, and that bit's value must track
the register. This is self-locating (no hard-coded pad index) and does not
depend on the OR aggregates.

DATA_CTRL field encoding (hw/ip/gpio/regs/gpio_intf.rdl):
  * bit0      core2pad          register-driven value to the pad
  * bit[5:4]  enable_rx_tx      2'b01 = TX enabled (drive pad)
  * bit16     interface_enable  select register values to drive the pad
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

GPIO0_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)

_CORE2PAD = 1 << 0
_TX_ENABLE = 1 << 4  # enable_rx_tx = 2'b01
_IF_ENABLE = 1 << 16  # interface_enable

OUT_DRIVE_HIGH = _IF_ENABLE | _TX_ENABLE | _CORE2PAD
OUT_DRIVE_LOW = _IF_ENABLE | _TX_ENABLE
OUT_DISABLE = 0


class smc_gpio_output_driveback_test_seq(SmcCsrSeq):
    """Drive wrap 0 as output via CSR and observe the pad it controls."""

    def __init__(self, name: str = "smc_gpio_output_driveback_test_seq") -> None:
        super().__init__(name)

    @staticmethod
    def _resolve_int(sig) -> int:
        """Read a wide pad-bus vector, resolving X/Z bits to 0 (bit positions
        preserved). VCS leaves undriven upper pad bits at X (X-init pessimism)
        while Verilator zero-inits them; this test isolates GPIO wrap 0 by a
        single-bit delta, so the undriven X bits are irrelevant and safely read
        as 0. A driven bit that is itself X still reads 0, which makes the
        delta/value assertions below fail with a clear message."""
        v = sig.value
        try:
            return int(v)
        except Exception:  # noqa: BLE001 - X/Z present (VCS undriven pads)
            s = getattr(v, "binstr", None) or str(v)
            bits = "".join(c if c in "01" else "0" for c in s if c not in " _")
            return int(bits, 2) if bits else 0

    def _en_vec(self, dut) -> int:
        return self._resolve_int(dut.tb_core2pad_en_o)

    def _val_vec(self, dut) -> int:
        return self._resolve_int(dut.tb_core2pad_o)

    async def body(self) -> None:
        dut = cocotb.top

        # Baseline pad-output vectors before any GPIO programming. Undriven upper
        # pad bits may be X on VCS, so we do NOT require the whole vector to be
        # resolvable; the single-bit wrap-0 delta below is the real gate (and a
        # driven bit stuck at X would resolve to 0 and trip those asserts).
        await ClockCycles(dut.clk_smc_i, 4)
        width = len(dut.tb_core2pad_en_o.value)
        mask = (1 << width) - 1
        base_en = self._en_vec(dut)

        # 1) Enable TX + drive value high. Exactly one output-enable bit (the
        #    pad owned by GPIO wrap 0) must newly assert, and its value = 1.
        await self.csr_write("GPIO0_TX_HIGH", GPIO0_DATA_CTRL, OUT_DRIVE_HIGH)
        await ClockCycles(dut.clk_smc_i, 8)
        newly_en = self._en_vec(dut) & (~base_en & mask)
        assert newly_en != 0, (
            "programming GPIO wrap0 as TX asserted no new pad output-enable "
            f"(base core2pad_en_o=0x{base_en:x})"
        )
        assert (newly_en & (newly_en - 1)) == 0, (
            f"GPIO wrap0 output touched more than one pad (delta=0x{newly_en:x})"
        )
        pad_bit = newly_en
        pad_idx = newly_en.bit_length() - 1
        assert (self._val_vec(dut) & pad_bit) != 0, (
            f"GPIO wrap0 pad[{pad_idx}] value did not follow register (high)"
        )

        # 2) Keep TX enabled, drive value low -> value clears, enable stays.
        await self.csr_write("GPIO0_TX_LOW", GPIO0_DATA_CTRL, OUT_DRIVE_LOW)
        await ClockCycles(dut.clk_smc_i, 8)
        assert (self._en_vec(dut) & pad_bit) != 0, (
            f"GPIO wrap0 pad[{pad_idx}] output-enable dropped while TX still enabled"
        )
        assert (self._val_vec(dut) & pad_bit) == 0, (
            f"GPIO wrap0 pad[{pad_idx}] value did not follow register (low)"
        )

        # 3) Disable the register interface -> pad output released.
        await self.csr_write("GPIO0_DISABLE", GPIO0_DATA_CTRL, OUT_DISABLE)
        await ClockCycles(dut.clk_smc_i, 8)
        assert (self._en_vec(dut) & pad_bit) == 0, (
            f"GPIO wrap0 pad[{pad_idx}] output-enable did not release after disable"
        )

        # `self.accesses` is incremented by every csr_* call in
        # smc_csr_seq_utils.py, so `self.accesses == <literal>` restates the
        # loop above and cannot fail on anything the DUT did
        # ([NO-ZERO-ACTIVITY-PASS]). `assert_all_reachable` cross-checks the
        # same count against the scoreboard, which a mis-bound analysis path
        # or a dead port fails.
        self.assert_all_reachable(3, "GPIO_OUTPUT_DRIVEBACK")
        cocotb.log.info(
            "GPIO wrap0 output driveback verified on pad[%d] (core2pad + core2pad_en)",
            pad_idx,
        )
