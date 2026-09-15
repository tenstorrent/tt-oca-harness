# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mandatory external-window control apertures route to the adopter AXI-Lite port.

``memmap.adoc`` (AXI-Lite External Window - Mandatory Region) lists the clock
observation GPIO interface/control pairs for the PLL and PVT clocks, the
power-on/pad-bias control block, the reference-clock GPIO control block and
65 per-pad control blocks at a fixed stride. Their addresses come from the
generated bootrom register header (``smc_top_regs.h``), the same map the boot
ROM is built against.

The adopter implementation of these blocks is out of this repository: the
reference ``smc_ip_integration`` terminates every one of them with an
AXI-Lite error slave that answers DECERR with zero data
(``smc_gpio_ctrl_full_sweep_test`` measures the same). What the SMC side owns,
and what is proven here, is the decode into the window: every access must
drive ``smc_external_req_o`` (sampled as ``tb_axil_external_active`` on every
``clk_smc_i`` edge while the access is in flight) and complete with the
terminator's DECERR and zero data rather than wedging or being answered by
some other block. The per-pad stride is taken from the header and checked
against the spec's 0x20 before the first and last instance are probed.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import external_gpio_ctrl_addr, external_gpio_ctrl_indices, smc_bootrom_addr
from .smc_decode_probe_utils import SmcDecodeProbeSeq

# memmap.adoc: "Per-Pad GPIO Control | BASE + ... + (N x 0x20) | 65 instances".
SPEC_PER_PAD_STRIDE = 0x20
SPEC_PER_PAD_INSTANCES = 65
# smc_ip_integration's error slaves answer with zero data.
TERMINATOR_RDATA = 0

_CONTROL_BLOCKS = (
    ("pll-obs-intf-decode", "GPIO_PLL_CLK_OBS_INTF_DATA_CTRL"),
    ("pll-obs-ctrl-decode", "GPIO_PLL_CLK_OBS_CTRL_CONTROL"),
    ("pvt-obs-intf-decode", "GPIO_PVT_CLK_OBS_INTF_DATA_CTRL"),
    ("pvt-obs-ctrl-decode", "GPIO_PVT_CLK_OBS_CTRL_CONTROL"),
    ("gpio-poc-pbias-decode", "GPIO_POC_PBIAS_CTRL_CONTROL"),
    ("gpio-refclk-ctrl-decode", "GPIO_REFCLK_CTRL_CONTROL"),
)

EXPECTED_ACCESSES = len(_CONTROL_BLOCKS) + 3


def _ext(symbol: str) -> int:
    return smc_bootrom_addr(f"SMC_TOP_SMC_EXTERNAL_MANDATORY_{symbol}_BASE_ADDR")


class smc_external_window_pad_ctrl_decode_test_seq(SmcDecodeProbeSeq):
    """Route every mandatory control block and the per-pad first/last instance."""

    def __init__(self, name: str = "smc_external_window_pad_ctrl_decode_test_seq") -> None:
        super().__init__(name)
        self.hits: dict[str, int] = {}

    async def _probe(self, cell: str, label: str, addr: int) -> None:
        rdata, hits = await self.read_external_routed(label, addr, decerr=True)
        assert rdata == TERMINATOR_RDATA, (
            f"{label} @ 0x{addr:08x}: DECERR carried data 0x{rdata:08x}, not the adopter-window "
            f"terminator's zero data, so another responder answered"
        )
        self.hits[label] = hits
        self.close_cell(
            cell,
            f"0x{addr:08x} drove smc_external_req_o for {hits} clk_smc_i cycle(s) and was answered "
            f"DECERR/0 by the adopter-window terminator",
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        idxs = external_gpio_ctrl_indices()
        # The SEP_IN monitor flags any DECERR it was not told to expect. Every
        # address this leaf touches is answered by the adopter window's
        # terminator, so all of them are intended error-slave probes.
        self.env.axi_monitor.expected_decerr_addrs.update(
            {_ext(symbol) for _cell, symbol in _CONTROL_BLOCKS}
            | {external_gpio_ctrl_addr(i) for i in (idxs[0], idxs[1], idxs[-1])}
        )
        for cell, symbol in _CONTROL_BLOCKS:
            await self._probe(cell, symbol, _ext(symbol))

        assert len(idxs) == SPEC_PER_PAD_INSTANCES and idxs == tuple(
            range(SPEC_PER_PAD_INSTANCES)
        ), (
            f"generated map declares per-pad control instances {idxs[:3]}..{idxs[-1]} "
            f"({len(idxs)}), spec declares {SPEC_PER_PAD_INSTANCES}"
        )
        stride = external_gpio_ctrl_addr(1) - external_gpio_ctrl_addr(0)
        assert stride == SPEC_PER_PAD_STRIDE, (
            f"generated per-pad control stride 0x{stride:x} differs from the spec's "
            f"0x{SPEC_PER_PAD_STRIDE:x}"
        )
        last = idxs[-1]
        assert external_gpio_ctrl_addr(last) == external_gpio_ctrl_addr(0) + last * stride
        # One cell per probed address: the first and last per-pad instances are
        # the same two measurements as the first and last per-pad block, so a
        # second name on either would inflate the printed cell count.
        await self._probe("per-pad-instance-0", "GPIO_CTRL_0_CONTROL", external_gpio_ctrl_addr(0))
        await self._probe("per-pad-stride-0x20", "GPIO_CTRL_1_CONTROL", external_gpio_ctrl_addr(1))
        await self._probe(
            f"per-pad-instance-{last}", f"GPIO_CTRL_{last}_CONTROL", external_gpio_ctrl_addr(last)
        )

        self.assert_all_reachable(EXPECTED_ACCESSES, "EXTERNAL_WINDOW_PAD_CTRL_DECODE")
        self.report_cells("CHK-EXTWIN-PAD-CTRL")
        cocotb.log.info(
            "CHK-EXTERNAL-WINDOW-PAD-CTRL-DECODE: %d control-block and %d per-pad addresses each "
            "drove the adopter external AXI-Lite port (active cycles %s) and completed DECERR/0 "
            "from the reference integration's terminator; per-pad stride 0x%x, %d instances",
            len(_CONTROL_BLOCKS),
            3,
            sorted(self.hits.values()),
            stride,
            len(idxs),
        )
