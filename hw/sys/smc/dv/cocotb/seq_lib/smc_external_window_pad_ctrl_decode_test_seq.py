# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mandatory external-window control apertures route to the adopter AXI-Lite port.

``memmap.adoc`` (AXI-Lite External Window - Mandatory Region) lists the clock
observation GPIO interface/control pairs for the PLL and PVT clocks, the
power-on/pad-bias control block, the reference-clock GPIO control block and
65 per-pad control blocks at a fixed stride. Their addresses come from the
generated bootrom register header (``smc_top_regs.h``), the same map the boot
ROM is built against.

The adopter implementation of these blocks is out of this repository, so
nothing behind the window is specified here and nothing behind it is credited.
What the SMC side owns, and what is proven here, is the decode into the window:
every access must drive ``smc_external_req_o`` (sampled as
``tb_axil_external_active`` on every ``clk_smc_i`` edge while the access is in
flight) and complete with an error response rather than wedging or being
answered by some other block. The data returned with that error is required to
be the error-slave word ``0xBADCAB1E`` that every error slave in the design
returns, so a live responder answering in the terminator's place fails on the
data as well as on the response code. The per-pad stride is taken from the
header and checked against the spec's 0x20 before the first and last instance
are probed.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import external_gpio_ctrl_addr, external_gpio_ctrl_indices, smc_bootrom_addr
from .smc_decode_probe_utils import SmcDecodeProbeSeq

# memmap.adoc: "Per-Pad GPIO Control | BASE + ... + (N x 0x20) | 65 instances".
SPEC_PER_PAD_STRIDE = 0x20
SPEC_PER_PAD_INSTANCES = 65
# The word the reference integration's window terminator returns with its
# DECERR, shared by every error slave in the design; another word means a
# live responder answered where only the terminator should.
TERMINATOR_RDATA = SmcDecodeProbeSeq.ERR_SLAVE_SIGNATURE

_CONTROL_BLOCKS = (
    ("pll-obs-intf-decode", "GPIO_PLL_CLK_OBS_INTF_DATA_CTRL"),
    ("pll-obs-ctrl-decode", "GPIO_PLL_CLK_OBS_CTRL_CONTROL"),
    ("pvt-obs-intf-decode", "GPIO_PVT_CLK_OBS_INTF_DATA_CTRL"),
    ("pvt-obs-ctrl-decode", "GPIO_PVT_CLK_OBS_CTRL_CONTROL"),
    ("gpio-poc-pbias-decode", "GPIO_POC_PBIAS_CTRL_CONTROL"),
    ("gpio-refclk-ctrl-decode", "GPIO_REFCLK_CTRL_CONTROL"),
)

EXPECTED_ACCESSES = len(_CONTROL_BLOCKS) + 4


def _ext(symbol: str) -> int:
    return smc_bootrom_addr(f"SMC_TOP_SMC_EXTERNAL_MANDATORY_{symbol}_BASE_ADDR")


class smc_external_window_pad_ctrl_decode_test_seq(SmcDecodeProbeSeq):
    """Route every mandatory control block and the per-pad first/last instance."""

    def __init__(self, name: str = "smc_external_window_pad_ctrl_decode_test_seq") -> None:
        super().__init__(name)
        self.hits: dict[str, int] = {}
        self.write_resp: int | None = None

    async def _probe(self, cell: str, label: str, addr: int) -> None:
        rdata, hits = await self.read_external_routed(label, addr, decerr=True)
        assert rdata == TERMINATOR_RDATA, (
            f"{label} @ 0x{addr:08x}: the error response carried data 0x{rdata:08x} instead of "
            f"the terminator's 0x{TERMINATOR_RDATA:08x}, so another responder answered in its "
            f"place"
        )
        self.hits[label] = hits
        self.close_cell(
            cell,
            f"0x{addr:08x} was presented on smc_external_req_o as a read request for {hits} "
            f"clk_smc_i cycle(s) and was answered DECERR/0x{TERMINATOR_RDATA:08X} by the "
            f"adopter-window terminator",
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

        # The write channel of the same terminator: a write into the first
        # per-pad block must reach the port as a write request for that address
        # and be refused, like the reads.
        pad0 = external_gpio_ctrl_addr(0)
        self.write_resp, wr_hits = await self.write_external_routed(
            "GPIO_CTRL_0_CONTROL_WR", pad0, 0xFFFF_FFFF
        )
        self.hits["GPIO_CTRL_0_CONTROL_WR"] = wr_hits

        self.assert_all_reachable(EXPECTED_ACCESSES, "EXTERNAL_WINDOW_PAD_CTRL_DECODE")
        self.report_cells("CHK-EXTWIN-PAD-CTRL")
        cocotb.log.info(
            "CHK-EXTERNAL-WINDOW-PAD-CTRL-DECODE: %d control-block and %d per-pad addresses each "
            "reached the adopter external AXI-Lite port as a request carrying that address "
            "(request cycles %s) and completed DECERR "
            "with the error-slave word 0x%08X, the terminator's answer for an address nothing "
            "behind the window decodes; per-pad stride 0x%x, %d instances; a write to per-pad "
            "block 0 reached the port as a write request for that address and was refused with "
            "resp=%s",
            len(_CONTROL_BLOCKS),
            3,
            sorted(self.hits.values()),
            TERMINATOR_RDATA,
            stride,
            len(idxs),
            self.write_resp,
        )
