# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot one staged SMC firmware image and pair its verdict with a bench observation.

Every firmware leaf in fw.toml runs the same path: the runner stages
`<image>.ecc.hex`, `check_cpu_firmware_boot_contract` clears CPU_CTRL
SCRATCH_0, publishes the seed, programs the reset vectors, drops boot_stall
and polls SCRATCH_0 until the image posts its PASS word. That word is the
firmware grading itself, so on its own it says only that the CPU ran the image
to completion.

This base adds the two places where the bench looks at the DUT without going
through that word. `before_boot` runs with the cores still held: arm passive
monitors, clear registers the image will write, start a handshake watcher.
`after_pass` runs once the PASS word has been read back: read the CSRs and
memory the image left behind, count pad edges, compare wire traffic against
what the image says it transferred. A subclass that adds nothing is the plain
`smc_fw_hello_world_test` pattern.

The scratch words are CPU_CTRL SCRATCH[n]; `scratch_addr` evaluates the
generated `SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(n)` macro so the index map in
fw/include/smc_test.h and the bench agree on where each word lives.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_indexed_addr
from .smc_cpu_vip_utils import check_cpu_firmware_boot_contract
from .smc_csr_seq_utils import SmcCsrSeq


def scratch_addr(index: int) -> int:
    """CPU_CTRL SCRATCH[index] from the generated address map."""
    return smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", index)


class _RisingEdgeCounter:
    """Count 0->1 transitions of one published TB signal until stopped."""

    def __init__(self, signal, clk) -> None:
        self.count = 0
        self._signal = signal
        self._clk = clk
        self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        prev = int(self._signal.value) if self._signal.value.is_resolvable else 0
        while True:
            await RisingEdge(self._clk)
            if not self._signal.value.is_resolvable:
                continue
            cur = int(self._signal.value)
            if prev == 0 and cur == 1:
                self.count += 1
            prev = cur

    def stop(self) -> int:
        self._task.cancel()
        return self.count


class smc_fw_image_boot_seq(SmcCsrSeq):
    """Scratch-image boot to the firmware PASS word, then a bench observation."""

    #: CHK token stem: "I2C-SANITY" logs CHK-FW-I2C-SANITY-BOOT.
    tag = "IMAGE"
    #: Verdict-poll bound in units of 100 clk_smc_i cycles. Each subclass sets
    #: the figure measured for its image (check_cpu_firmware_boot_contract).
    poll_iterations = 2000

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.boot: dict[str, object] = {}
        self._edge_counters: dict[str, _RisingEdgeCounter] = {}

    async def before_boot(self) -> None:
        """Bench setup while the cores are still held. Default: nothing."""

    async def after_pass(self) -> None:
        """Bench observation after the PASS word was read back. Default: nothing."""

    def count_edges_from_now(self, signal_name: str) -> None:
        dut = cocotb.top
        assert hasattr(dut, signal_name), f"{signal_name} is not a published TB signal"
        self._edge_counters[signal_name] = _RisingEdgeCounter(
            getattr(dut, signal_name), dut.clk_smc_i
        )

    def edges_counted(self, signal_name: str) -> int:
        return self._edge_counters.pop(signal_name).stop()

    async def body(self) -> None:
        await self.before_boot()
        # require_image=True: without the staged image there is nothing to
        # boot, and reporting that as a skip would leave a green run that
        # proved nothing.
        self.boot = await check_cpu_firmware_boot_contract(
            self, require_image=True, poll_iterations=self.poll_iterations
        )
        cocotb.log.info(
            "CHK-FW-%s-BOOT: %s",
            self.tag,
            ", ".join(f"{k}={v}" for k, v in sorted(self.boot.items())),
        )
        await self.after_pass()
        for name in list(self._edge_counters):
            self.edges_counted(name)
