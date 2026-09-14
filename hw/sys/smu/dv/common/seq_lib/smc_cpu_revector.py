# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Restart the SMC cores at a chosen entry, over JTAG2AXI.

An image placed in SMC scratch RAM by the +smc_scratch_ram_hex backdoor needs
something to point the cores at it. The Rocket frontend latches RESET_VECTOR
only on tile reset, so the sequence is: force the reset to apply even if the
cluster never drains, program the vector on all four cores, hold them, pulse
them, and let go.

Entering such an image by jumping to it from ROM instead does not work: the core
arrives carrying whatever state the ROM left, mtvec among it, and the first trap
goes to address 0. A tile reset is what the SMC firmware's own header means by
the SEP-driven or cocotb-backdoor boot.

hw/sys/smc/dv does the same thing through its CSR agent
(seq_lib/smc_cpu_vip_utils.py). This environment has no such agent, so the
writes go over the DTP's JTAG2AXI, which reaches SMC addresses directly and is a
product path rather than a testbench override.

SINGLE_OP is pipelined: a shift launches one transaction and captures the
PREVIOUS one's status. Checking the status of the same shift that launched a
write therefore reports the op before it, and issuing writes back to back leaves
no time for the AXI transaction to retire, so later ones come back BUSY and are
dropped. Every access here launches, waits, then shifts again to capture -- the
pattern smu_dtp_sep_smc_chain_seq.py uses. The DTP AW counter says whether the
bridge launched anything at all, which separates a closed debug gate from a
transaction the SMC refused.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from seq_lib.wrapper_jtag import (
    J2A_OP_WRITE,
    J2A_SIZE_8B,
    J2A_ST_BUSY,
    J2A_ST_OKAY,
    J2A_STATUS_NAME,
    single_op_payload,
    single_op_rdata,
    single_op_status,
)

# smc_reg.py: SMC_CPU_CTRL_*__REG_ADDR.
RESET_VECTOR_0 = 0xC003_9000
RESET_VECTOR_STRIDE = 8
RESET_CTRL = 0xC003_9020
RESET_TIMEOUT = 0xC003_9030

#: timeout_value[15:0]=32, timeout_mode[16]=1 so the reset force-applies.
RESET_TIMEOUT_FORCE = 0x0001_0020
#: Hold cores in reset, uncore released (bit 8).
RESET_CTRL_HOLD_CORES = 0x0000_0100
#: CPU_CTRL_RESET_CTRL_REG_DEFAULT (cores+uncore released) | pulse-start [7:4].
RESET_CTRL_PULSE_ALL = 0x0000_01FF

NUM_CORES = 4

#: Cycles between launching a SINGLE_OP and capturing its result. The bridge
#: crosses into the SMC clock domain and back, so this is generous rather than
#: tuned; smu_dtp_sep_smc_chain_seq.py uses the same figure.
SETTLE_CYCLES = 4000
#: BUSY is the bridge saying "ask again", so it is polled rather than waited out
#: with a longer fixed delay: one settle window does not always cover a
#: transaction that crossed into a busy SMC.
BUSY_RETRIES = 20

#: Bound on waiting for the SMC to leave reset, in clk_smu cycles.
SMC_RESET_TIMEOUT_CYCLES = 200_000
#: ROM-fetch count is sampled every SMC_BOOT_SETTLE_CYCLES; two equal non-zero
#: samples mean the boot has stopped fetching and reached its parking loop.
SMC_BOOT_SETTLE_CYCLES = 2_000
SMC_BOOT_SETTLE_POLLS = 200


async def _single_op(jtag, payload: int, *, settle: int = SETTLE_CYCLES):
    """Launch one SINGLE_OP and capture its result with a second shift.

    The capture is a separate shift because CAPTURE-DR presents the PREVIOUS
    transaction's result: reading the status out of the shift that launched the
    op reports the op before it.
    """
    await jtag.write("SMC_AXI_SINGLE_OP", payload)
    for _ in range(BUSY_RETRIES):
        await ClockCycles(cocotb.top.clk_smu_i, settle)
        captured = int(await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0))
        status = single_op_status(captured)
        if status != J2A_ST_BUSY:
            return status, single_op_rdata(captured)
    return J2A_ST_BUSY, 0


def _aw_count() -> int:
    return int(cocotb.top.dtp_smc_dbg_aw_count_o.value)


async def _write64(jtag, addr: int, value: int, what: str) -> None:
    before = _aw_count()
    status, _ = await _single_op(
        jtag,
        single_op_payload(J2A_OP_WRITE, addr, size=J2A_SIZE_8B, data=value, wstrb=0xFF),
    )
    assert _aw_count() > before, (
        f"{what}: the DTP bridge launched no write for 0x{addr:08x} "
        f"(AW count stayed at {before}); SMC JTAG2AXI is gated off in this "
        "lifecycle state, so the cores cannot be re-vectored over it"
    )
    assert status == J2A_ST_OKAY, (
        f"{what}: JTAG2AXI write of 0x{value:016x} to 0x{addr:08x} returned "
        f"{J2A_STATUS_NAME.get(status, status)}; the cores cannot be re-vectored "
        "without it"
    )


async def _wait_smc_out_of_reset(log, timeout_cycles: int = SMC_RESET_TIMEOUT_CYCLES) -> None:
    """Block until the SMC has left reset and its ROM boot has settled.

    Re-vectoring before this point does nothing at all: RESET_VECTOR resets to
    its own default, so vectors programmed while the SMC is still in reset are
    thrown away, and a hold/pulse of a block already held in reset is a no-op.
    The whole sequence then completes with every write reporting OKAY while
    changing nothing -- the failure mode this wait exists to prevent.
    """
    for _ in range(timeout_cycles):
        await ClockCycles(cocotb.top.clk_smu_i, 1)
        if int(cocotb.top.obs_smc_rst_n_o.value) == 1:
            break
    else:
        raise AssertionError(
            f"SMC still in reset after {timeout_cycles} cycles; there is nothing to re-vector"
        )
    # Let the ROM boot reach its parking loop, so the pulse below restarts a
    # settled cluster rather than racing the boot it is meant to replace.
    rom_reads = -1
    for _ in range(SMC_BOOT_SETTLE_POLLS):
        before = rom_reads
        rom_reads = int(cocotb.top.smc_rom_read_count_o.value)
        if rom_reads > 0 and rom_reads == before:
            log.info(
                "SMC re-vector: SMC out of reset, ROM boot settled at %d ROM fetches",
                rom_reads,
            )
            break
        await ClockCycles(cocotb.top.clk_smu_i, SMC_BOOT_SETTLE_CYCLES)
    else:
        log.info(
            "SMC re-vector: SMC out of reset, ROM fetch count did not settle "
            "after %d polls of %d cycles (last sample %d)",
            SMC_BOOT_SETTLE_POLLS,
            SMC_BOOT_SETTLE_CYCLES,
            rom_reads,
        )


async def revector_smc_cores(test, jtag, entry: int, *, settle_cycles: int = 64) -> None:
    """Reset all four SMC cores so they start executing at `entry`."""
    log = test.logger
    log.info("SMC re-vector: entry=0x%08x", entry)

    await _wait_smc_out_of_reset(log)

    await _write64(jtag, RESET_TIMEOUT, RESET_TIMEOUT_FORCE, "reset timeout force")

    for core in range(NUM_CORES):
        await _write64(
            jtag,
            RESET_VECTOR_0 + core * RESET_VECTOR_STRIDE,
            entry,
            f"reset vector core{core}",
        )

    # A RESET_VECTOR_0 readback over this port hangs every run: the SMC ROM image
    # parks its cores in `wfi`, and with the cluster quiesced a read never returns
    # -- the AR launches and the bridge stays BUSY for good, while posted writes
    # still get their B. The vector's effect is observable instead: after the
    # pulse the cores fetch from `entry`, which the caller sees as scratch reads
    # climbing and the image reaching its protocol.
    await _write64(jtag, RESET_CTRL, RESET_CTRL_HOLD_CORES, "hold cores")
    # Past timeout_value on the SMC's own clock, so the force-apply can take the
    # level hold; the SMU clock this sequence otherwise runs on is not it.
    await ClockCycles(cocotb.top.obs_smc_clk_o, settle_cycles)

    await _write64(jtag, RESET_CTRL, RESET_CTRL_PULSE_ALL, "pulse cores")
    await ClockCycles(cocotb.top.obs_smc_clk_o, settle_cycles)

    log.info("SMC re-vector: cores pulsed, now running from 0x%08x", entry)
