# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sweep the full 12-bit AxUSER field across the SEP fabric apertures.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"; "AXI fabric"): `aw.user`, `ar.user` and `w.user` on
`xbar_slv_req[*]` / `xbar_mst_req[*]` of
`hw/sys/sep/rtl/sep_local_axi_xbar.sv` and
`hw/sys/sep/rtl/crossbars/sep_system_peripherals_xbar.sv`, on
`sep_crypto_axi_reqs[*]` of `hw/sys/sep/rtl/sep_crypto_axi_interconnect.sv`,
and on `sep_system_peripheral_56_remapped_from_demux_axi_reqs[*]` of
`hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_peripherals.sv`. It also
moves `b.user` / `r.user` on the matching response structs, which are driven
back from the request user field by the crossbars.

AxUSER is 12 bits on every SEP port (`hw/sys/sep/rtl/sep_pkg.sv:24` and the
sibling `*_USER_WIDTH` parameters). Only `user[3:0]` moves today: it is the
inbound filter's `src_id`, which the inbound-filter tests drive on the
external master. `user[11:4]` is at zero toggle on every port of every module
above, and on the CPU-LSU path even `user[3:0]` never leaves zero
(`xbar_slv_req[1].aw.user[11:0]` untoggled).

The VPLAN parks `AxUSER[11:4]` as not frontdoor reachable. That entry is
stale: `SepAxiItem.user` exists (`cocotb/env/sep_axi_agent.py`), the driver
passes it to the VIP in `_drive`, and `dv/tb/tb_top.sv` wires
`lsu_req_drive.aw.user = s_axi_awuser` on the CPU-LSU splice. Driving it is
stimulus plumbing, not a force.

Stimulus: repeat one read and write set over the SEP SRAM, the outbound and
inbound filter banks, the local-master alias-remap bank, the AP and STEE
output-remap banks, SEP_CPU_CTRL and the TRNG aperture, with `user` swept over
all-ones, the two alternating halves, zero, and four seed-derived values from
`env/sep_seeded_rng.py`, so every one of the 12 bits moves in both directions.

Nothing in the SEP fabric decodes on AxUSER except the inbound filter's
`src_id` match, and the CPU-LSU master does not cross an inbound filter, so a
swept access is answered exactly as the default one is. The writes are chosen
so the sweep changes no state a later step depends on: CLOCK_GATE_CTRL takes
the implemented mask every fabric driver in this tree writes, the SRAM word is
scratch, and no filter or remap region is enabled anywhere in this leaf.

Response handling: the open tree has no external TRNG.
`hw/top/sep_ip_integration.sv` terminates `ext_trng_axil_req_i` with an
AXI-Lite error slave, so that leg answers with an error by design. Those
accesses take `allow_error` / `allow_unverified_write_resp`, exactly as
`sep_cov_crypto_ic_trng_aperture_test` does; `SepCovStim.access` arms the AXI
monitor for the tolerated beat.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_cov_stimulus_seq import CLOCK_GATE_CTRL, CLOCK_GATE_UNGATE, SepCovStim
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_BASE,
    AP_BASE,
    INFILT_BASE,
    OUTFILT_BASE,
    STEE_BASE,
)

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
TRNG_BASE = sym("TRNG_APERTURE_MEM_BASE_ADDR")

# Scratch word on the SRAM port, clear of the burst apertures the other
# coverage leaves use at the bottom of the block.
SRAM_WORD = SRAM_BASE + 0x0800

# AxUSER is 12 bits on every SEP port.
USER_WIDTH = 12
USER_MASK = (1 << USER_WIDTH) - 1

# All-ones and the two alternating halves move every bit of the field in both
# directions; the trailing zero returns the bus to the value the rest of the
# suite drives.
USER_PATTERNS = (USER_MASK, 0x555, 0xAAA, 0x000)

# Extra seed-derived values, so a regression over several seeds does not drive
# the same four vectors every time.
USER_RANDOM_COUNT = 4

READ_ADDRS = (
    OUTFILT_BASE,
    INFILT_BASE,
    ALIAS_BASE,
    AP_BASE,
    STEE_BASE,
    CLOCK_GATE_CTRL,
    SRAM_WORD,
)

WRITE_ADDRS = (
    (CLOCK_GATE_CTRL, CLOCK_GATE_UNGATE),
    (SRAM_WORD, 0xA5A5_5A5A),
)

WDATA_TRNG = 0xC0FF_EE00


@pyuvm.test()
class sep_cov_xbar_axuser_sweep_test(sep_base_test):
    """AxUSER over the full 12-bit field on the fabric apertures. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        seed = self.random_seed()
        rng = SepSeededRng(seed)
        users = list(USER_PATTERNS) + [
            rng.getrandbits(USER_WIDTH) for _ in range(USER_RANDOM_COUNT)
        ]
        self.logger.info("AxUSER sweep: seed=%d values=%s", seed, [f"0x{u:03x}" for u in users])

        for user in users:
            for addr in READ_ADDRS:
                await stim.access(
                    op=SepAxiOp.READ,
                    addr=addr,
                    user=user,
                    name=f"cov_user{user:03x}_rd",
                )
            for addr, data in WRITE_ADDRS:
                await stim.access(
                    op=SepAxiOp.WRITE,
                    addr=addr,
                    wdata=data,
                    user=user,
                    name=f"cov_user{user:03x}_wr",
                )
            # The crypto interconnect is only crossed by an access into a
            # crypto aperture, so the sweep needs one leg of it per value.
            await stim.access(
                op=SepAxiOp.WRITE,
                addr=TRNG_BASE,
                wdata=WDATA_TRNG,
                user=user,
                allow_unverified_write_resp=True,
                name=f"cov_user{user:03x}_trng_wr",
            )
            await stim.access(
                op=SepAxiOp.READ,
                addr=TRNG_BASE,
                user=user,
                allow_error=True,
                name=f"cov_user{user:03x}_trng_rd",
            )
            self.logger.info("AxUSER=0x%03x driven over the fabric apertures", user)
