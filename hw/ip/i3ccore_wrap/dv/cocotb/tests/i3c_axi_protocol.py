# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C AXI-Lite Protocol

Exercises AXI-Lite register access with response checking:
  - mapped write / read-back round-trip (BRESP/RRESP must be OKAY)
  - mapped HC_CONTROL read with exact reset/default expectation
  - helper sensitivity: a deliberate expect_resp mismatch must fail

Constrained-random: the written pattern is randomized (shared framework, seed
from +seed/SEED/default). QUEUE_THLD_CTRL's threshold fields clamp values to
<= 7, so the random pattern is generated with every byte in 0..7 (and non-zero)
to guarantee an exact read-back — the AXI round-trip is the scoreboard.

Note: uses QUEUE_THLD_CTRL, a confirmed RW register. The DAT region (0x400+)
is NOT used here — it is external 64-bit SRAM, not a plain 32-bit scratch
register, and an un-written entry reads X.
"""

import os
import sys

import cocotb
from cocotbext.axi import AxiResp
from env.i3c_api import (
    I3CBASE_HC_CONTROL_REG_ADDR,
    PIOCONTROL_QUEUE_THLD_CTRL_REG_ADDR,
)
from env.i3c_rand import RandMgr
from env.i3c_test_base import CTRL_BASE, make_env

# Authoritative register map (generated).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../regs/gen/py"))
import oca_i3c_wrap_reg as _csr  # noqa: E402


def _default_by_suffix(suffix):
    """Resolve <parameterisation-prefix>_<suffix> from the generated map.

    The generated reset-value symbols carry a prefix encoding the RDL
    parameterisation, so they cannot be named literally without breaking on
    re-parameterisation. Requiring exactly one match makes a rename or an
    ambiguity an import-time error instead of a silently wrong expectation.
    """
    names = [n for n in dir(_csr) if n.endswith(suffix)]
    if len(names) != 1:
        raise AttributeError(
            f"expected exactly 1 generated symbol ending in {suffix!r}, found "
            f"{len(names)}: {names} — the register map was regenerated"
        )
    return getattr(_csr, names[0])


# HC_CONTROL reset value, taken from the generated map rather than duplicated here:
# a hand-copied literal and the DUT both trace to the same RDL, so a golden that
# diverges from the MIPI HCI register table would still compare equal.
# 0x40 is bit 6 = mode_selector (bus_enable is bit 31, i.e. 0x80000000).
HC_CONTROL_DEFAULT = _default_by_suffix("HC_CONTROL_REG_DEFAULT")


def _rand_thld_pattern(r):
    """A 32-bit value with every byte in 0..7 (valid threshold fields) and != 0,
    so it round-trips through QUEUE_THLD_CTRL without field clamping."""
    while True:
        p = sum(r.randint(0, 7) << (8 * i) for i in range(4))
        if p != 0:
            return p


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_axi_protocol(dut):
    tb, helper, _ctrl, _tgt = await make_env(dut)
    r = RandMgr(name="axi_protocol")  # seed logged; +seed/SEED override

    thld_addr = CTRL_BASE + PIOCONTROL_QUEUE_THLD_CTRL_REG_ADDR
    hc_addr = CTRL_BASE + I3CBASE_HC_CONTROL_REG_ADDR

    pattern = _rand_thld_pattern(r)
    # Mapped write / read-back — helper asserts BRESP/RRESP == OKAY
    await helper.write(thld_addr, pattern, expect_resp=AxiResp.OKAY)
    val = await helper.read(thld_addr, expect_resp=AxiResp.OKAY)
    tb.log.info(
        f"CHK-QUEUE_THLD_CTRL: addr=0x{thld_addr:X} wrote=0x{pattern:08X} "
        f"read=0x{val:08X} resp=OKAY"
    )
    assert val == pattern, f"mapped readback mismatch 0x{val:08X} != 0x{pattern:08X}"

    # Second mapped read with exact expected reset/default value
    hc = await helper.read(hc_addr, expect_resp=AxiResp.OKAY)
    tb.log.info(
        f"CHK-HC_CONTROL: addr=0x{hc_addr:X} read=0x{hc:08X} "
        f"expected=0x{HC_CONTROL_DEFAULT:08X} resp=OKAY"
    )
    assert hc == HC_CONTROL_DEFAULT, f"HC_CONTROL mismatch 0x{hc:08X} != 0x{HC_CONTROL_DEFAULT:08X}"

    # Verify that an expected-response mismatch raises an error. Unmapped accesses
    # alias to instance 0 and cannot provide a DUT-generated negative response.
    raised = False
    try:
        await helper.read(hc_addr, expect_resp=AxiResp.SLVERR)
    except AssertionError as exc:
        raised = True
        tb.log.info(f"CHK-RESP-MISMATCH-GATE: caught expected assert: {exc}")
    assert raised, "helper.read(..., expect_resp=SLVERR) must raise when DUT returns OKAY"

    tb.log.info(f"AXI-Lite protocol test complete (seed=0x{r.seed:08X}, checks=3)")
