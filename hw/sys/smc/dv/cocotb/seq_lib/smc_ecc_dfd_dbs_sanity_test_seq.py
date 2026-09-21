# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RAS-bank / NDM-reset / DFX-debug diagnostic representative precheck.

No ECC and no DBS register is addressed here: neither surface is exposed at the
SMC CSR boundary (the authoritative map ``hw/sys/smc/regs/gen/c/smc_addr.h``
carries no ECC and no ``DBS_``/``_DBS`` symbol). This sequence reads the RAS
bank type/instance ID pair, the NDM-reset registers, and the DFX debug
control/bus-mux registers.

Every expectation is taken from the RDL / PeakRDL-generated headers under
``hw/sys/smc/regs/``; nothing is read from the RTL under test.
``NDMRESET_CLUSTER_COUNT`` is checked against the RDL bounds and its ``sw = r``
contract. The programmer's guide states that this harness reads 4; this
sequence reports the observed count and does not compare it to that value.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_diagnostic_vip_utils import prove_axil_any_master_activity

_MISC_WRAP_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "misc_wrap.h"

# NDMRESET_CLUSTER_COUNT. The programmer's guide states that this harness
# reads 4. This sequence does not compare against that value: the checks are
# the RDL bounds and the ``sw = r`` access contract, and the observed count is
# carried in the evidence token.
#
# Field framing from the generated header of the ``ndm_reset`` block:
# ``ndmreset_cluster_count[7:0]`` is the only field of the register, so the
# bits above it are reserved and must read 0. The RDL says software masks
# NDMRESET_REQUEST with this value, and that field holds up to 32 clusters, so
# a count above that width could not mask it. The ceiling is the request
# field's generated width.
_CLUSTER_COUNT_MASK = _field_mask(
    _MISC_WRAP_H, "NDM_RESET__NDMRESET_CLUSTER_COUNT__NDMRESET_CLUSTER_COUNT_bm"
)
_CLUSTER_COUNT_WIDTH = _field_mask(
    _MISC_WRAP_H, "NDM_RESET__NDMRESET_CLUSTER_COUNT__NDMRESET_CLUSTER_COUNT_bw"
)
NDMRESET_CLUSTER_COUNT_MAX = _field_mask(
    _MISC_WRAP_H, "NDM_RESET__NDMRESET_REQUEST__NDMRESET_REQUEST_bw"
)
assert NDMRESET_CLUSTER_COUNT_MAX <= _CLUSTER_COUNT_MASK, (
    f"the {NDMRESET_CLUSTER_COUNT_MAX}-bit ndmreset_request field does not fit the "
    f"{_CLUSTER_COUNT_WIDTH}-bit ndmreset_cluster_count field declared in {_MISC_WRAP_H}"
)

NDMRESET_CLUSTER_COUNT_ADDR = smc_addr(
    "SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR"
)


def ndmreset_cluster_count_wr_pattern(observed: int) -> int:
    """Software-write pattern for the sw=r leg: every field bit of the observed
    count inverted, so a register that (wrongly) accepted the write cannot
    coincidentally read back the value it held before."""
    return (observed ^ _CLUSTER_COUNT_MASK) & _CLUSTER_COUNT_MASK


# ``DFX_DEBUG_BUS_MUX`` is a 64-bit register -- ``dfx_ctrl_status.rdl:116-118``
# declares ``reg DEBUG_BUS_MUX { regwidth = 0x40; }`` with fields running to
# ``Muxselseg7[63:58]``. It is read 8 bytes wide so the whole declared reset is
# compared; a 4-byte read leaves ``Muxselseg2[33:28]``..``Muxselseg7`` unsampled.
# Every field in that register resets to 0x0 in the RDL.
_DEBUG_BUS_MUX_BYTES = 8

# Value-compared diagnostic reads, identical on Verilator and VCS. Every
# expectation here traces to a cited RDL declaration:
#   * NDMRESET_PROCESS (ndm_reset.rdl): RDL reset 0x0 -> spec-anchored.
#   * DFX DEBUG_CTRL / DEBUG_BUS_MUX: PeakRDL symbols at 0xC000_B808/B810,
#     RDL reset 0x0.
#     DEBUG_CTRL is regwidth 32; DEBUG_BUS_MUX is regwidth 64 (see above).
# NDMRESET_CLUSTER_COUNT is not in this table: no document fixes its value, so
# body() gives it two legs with their own tokens (RDL bounds, then the sw=r
# access contract).
DIAGNOSTIC_READS = [
    (
        "NDMRESET_PROCESS",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_PROCESS_BASE_ADDR"),
        0x0,
        4,
    ),
    ("DFX_DEBUG_CTRL", smc_addr("SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR"), 0x0, 4),
    (
        "DFX_DEBUG_BUS_MUX",
        smc_addr("SMC_TOP_DFX_CTRL_DEBUG_BUS_MUX_BASE_ADDR"),
        0x0,
        _DEBUG_BUS_MUX_BYTES,
    ),
]


class smc_ecc_dfd_dbs_sanity_test_seq(SmcCsrSeq):
    """Use safe RAS/debug CSRs as the diagnostic representative."""

    def __init__(self, name: str = "smc_ecc_dfd_dbs_sanity_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        # Positive control for the downstream AXI-Lite activity OR that
        # check_diagnostic_observability() re-checks at 0 after this body: drive
        # it to 1 first so the later idle assertion is a live measurement and
        # not a stuck-at-0 pass.
        await prove_axil_any_master_activity(self)

        # csr_read only returns after SmcScoreboard._check_sys_axi has asserted
        # OKAY *and* rdata == the table expected for this item (the SYS-AXI
        # driver writes the analysis port before item_done), so each CHK token
        # below is emitted only after that exact expectation passed. Nothing is
        # printed on the setup path.
        for name, addr, expected, length in DIAGNOSTIC_READS:
            rdata = await self.csr_read(name, addr, expected, length=length)
            cocotb.log.info(
                "CHK-DIAG-CSR-%s: SEP_IN AXI read @ 0x%08x returned OKAY "
                "rdata=0x%0*x == expected 0x%0*x (full %d-bit register, RDL "
                "reset)",
                name,
                addr,
                length * 2,
                rdata,
                length * 2,
                expected,
                length * 8,
            )

        # --- NDMRESET_CLUSTER_COUNT: RDL bounds, then RDL access contract ------
        # Leg 1: the programmer's guide states this harness reads 4. This
        # sequence reports that value and checks the RDL bounds: a nonzero
        # count, at most the width of the request register it masks, inside
        # the generated field with the reserved bits at 0.
        count = await self.csr_read("NDMRESET_CLUSTER_COUNT", NDMRESET_CLUSTER_COUNT_ADDR)
        assert (count & ~_CLUSTER_COUNT_MASK) == 0, (
            f"NDMRESET_CLUSTER_COUNT reads 0x{count:08x}: bits above the "
            f"{_CLUSTER_COUNT_WIDTH}-bit ndmreset_cluster_count field are reserved and must be 0"
        )
        assert 0 < count <= NDMRESET_CLUSTER_COUNT_MAX, (
            f"NDMRESET_CLUSTER_COUNT reads {count}: ndm_reset.rdl has it mask the "
            f"{NDMRESET_CLUSTER_COUNT_MAX}-bit ndmreset_request register, so the count "
            f"must be 1..{NDMRESET_CLUSTER_COUNT_MAX}"
        )
        cocotb.log.info(
            "CHK-DIAG-NDMRESET-CLUSTER-COUNT-BOUNDS: NDMRESET_CLUSTER_COUNT "
            "@ 0x%08x reads 0x%08x -- a nonzero count within the %d-bit RDL "
            "field and at most the %d request bits it masks, reserved bits 0. "
            "SCOPE: bounds check only. The programmer's guide states this "
            "harness reads 4; the count is reported, not compared",
            NDMRESET_CLUSTER_COUNT_ADDR,
            count,
            _CLUSTER_COUNT_WIDTH,
            NDMRESET_CLUSTER_COUNT_MAX,
        )

        # Leg 2: RDL register contract. ndm_reset.rdl declares the field
        # sw=r / hw=w, so a software write must be dropped and the count read
        # above must still be presented afterwards. The write pattern is the
        # bit-inverse of that count, so a field that became software-writable
        # reads back the inverted pattern and fails the compare.
        wr_pattern = ndmreset_cluster_count_wr_pattern(count)
        await self.csr_write(
            "NDMRESET_CLUSTER_COUNT_SW_WRITE", NDMRESET_CLUSTER_COUNT_ADDR, wr_pattern
        )
        held = await self.csr_read(
            "NDMRESET_CLUSTER_COUNT_AFTER_SW_WRITE", NDMRESET_CLUSTER_COUNT_ADDR, count
        )
        cocotb.log.info(
            "CHK-DIAG-NDMRESET-CLUSTER-COUNT-RO: sw write 0x%08x to "
            "NDMRESET_CLUSTER_COUNT @ 0x%08x was dropped (field is sw=r/hw=w in "
            "ndm_reset.rdl); readback 0x%08x == the count read before the write",
            wr_pattern,
            NDMRESET_CLUSTER_COUNT_ADDR,
            held,
        )

        assert self.accesses == len(DIAGNOSTIC_READS) + 4, (
            f"diagnostic CSR precheck issued {self.accesses} accesses, expected "
            f"{len(DIAGNOSTIC_READS) + 4} (1 activity positive control + "
            f"{len(DIAGNOSTIC_READS)} value-compared diagnostic reads + the "
            f"NDMRESET_CLUSTER_COUNT bounded read + its sw=r write/readback)"
        )
        cocotb.log.info(
            "CHK-DIAG-CSR-COUNT: %d/%d RDL-traceable diagnostic CSR reads "
            "value-checked, plus 1 activity positive-control access and the "
            "NDMRESET_CLUSTER_COUNT bounded read + sw=r write/readback pair "
            "(%d SEP_IN AXI accesses total)",
            len(DIAGNOSTIC_READS),
            len(DIAGNOSTIC_READS),
            self.accesses,
        )
