# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

"""
I3C Error: Parity Injection  (Test Plan #36)

Scaffold for parity/CRC/frame error injection and error-status reporting.
Compile-only: actual bit-flip injection needs an RTL force hook (see GAP
TP-009); this runs a clean transfer then inspects the error-status path.
"""
import cocotb
from cocotb.triggers import ClockCycles
from i3c_test_base import make_env, bring_up_and_assign

RESPONSE_PORT = 0x08C
PIO_INTR_STATUS = 0x0A0


@cocotb.test(timeout_time=2000, timeout_unit='us')
async def test_error_parity_inject(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)

    # Baseline clean transfer -> err_status should be 0
    data = [0xDE, 0xAD, 0xBE, 0xEF]
    ok, resp, rx = await ctrl.private_write(data, tgt, dat_idx=0)
    err = (resp >> 27) & 0x3
    tb.log.info(f"baseline write resp=0x{resp:08X} err_status={err}")
    assert ok and err == 0, "baseline transfer should be error-free"

    # TODO(sim-verify): force a parity/CRC bit flip on SDA during the data phase
    # and assert err_status in {1,2,3}; requires an internal force point.
    await ClockCycles(dut.clk, 50)
    status = await helper.read(PIO_INTR_STATUS)
    tb.log.info(f"PIO_INTR_STATUS = 0x{status:08X}")

    tb.log.info("Parity-injection scaffold complete")
