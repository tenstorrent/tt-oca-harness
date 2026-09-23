# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART log-engine effective-length boundaries and log-write under TX backpressure.

Firmware test: `fw/tests/uart_log_engine_boundary_backpressure` is loaded into
scratch by the firmware loader. On wrap 0 with UART0 in MCR.LOOP it runs: A, an
8-byte request inside a 16-byte slot (one fetch beat); B, a 64-byte request
into a 64-byte slot written against uart_tx_ready low (the transmitter reports
ready only while its TX FIFO holds no data), whose 64 bytes the firmware reads
back in order while the transfer runs; D, a
24-byte request clamped to its 16-byte slot; E, a 15-byte slot rounded down to
one 8-byte beat. A, D and E read back exactly the requested or clamped byte
count from RBR and require no extra byte. Those compares are the firmware's.

Bench observation: while the image runs, `tb_uart0_log_write_stalled` -- a
fetched byte waiting at the wrap-0 log engine's read-data FIFO while the UART
transmit-ready input is low, the cycles on which its write FSM is held off --
is sampled on every clk_smc_i edge and must be 1 on at least one cycle and not
on all of them: the write FSM honours the UART's ready input. The count covers
the whole image; `tb_uart0_tx_ready` alone would not do, since it is also low
on cycles where the engine has nothing to write. After the PASS word the SPM
source
holds E's 0xE0..0xEF in its first 16 bytes and B's 0x50..0x7F behind them (B
was the only scenario to write past byte 16), and the engine reads back
programmed as E left it -- REGION_SIZE 0xF0 at the buffer, LOG_WRITE_ADDR at
UART0's THR -- with CTRL.EN and MCR.LOOP cleared by the cleanup.

Tokens: CHK-FW-LOG-ENGINE-BOUNDARY-BOOT, CHK-FW-LOG-ENGINE-CSR-STATE,
CHK-FW-LOG-ENGINE-SPM-PATTERN, CHK-FW-LOG-ENGINE-TX-BACKPRESSURE.

Requires the staged image and a held boot:
  +smc_scratch_ram_hex=uart_log_engine_boundary_backpressure.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
Must NOT use +skip_fuse_sense -- see dv_policy 1.6.
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smc_fw_log_engine_test_seq import (
    LOG_BUFFER_BASE,
    LogEngineFinalState,
    smc_fw_log_engine_test_seq,
    uart_reg,
)
from smc_base_test import smc_base_test

# Scenario E: 240 / 16 = 15 bytes per slot.
SCENARIO_E_REGION_SIZE = 0xF0
# Bytes 0..15 are scenario E's 0xE0.., bytes 16..63 are what remains of
# scenario B's 0x40 + i fill (A, D and E rewrite only the first 8 or 16).
SPM_PATTERN = bytes(0xE0 + i for i in range(16)) + bytes(0x40 + i for i in range(16, 64))
# Wrap-0 log engine write stall, published by tb_top: a fetched byte waiting in
# the engine's read-data FIFO while the UART transmit-ready input is low. The
# transmitter reports ready only while its TX FIFO holds no data, so every
# scenario's bytes wait on the serialiser; B's 64-byte transfer is the longest.
STALL_SIGNAL = "tb_uart0_log_write_stalled"
TX_READY_SIGNAL = "tb_uart0_tx_ready"
SCENARIO_B_BYTES = 64


class _boundary_backpressure_seq(smc_fw_log_engine_test_seq):
    """The log-engine observation plus a count of transmit-ready-low cycles."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stalled_cycles: int | None = None
        self.sampled_cycles: int | None = None
        self.tx_ready_low_cycles: int | None = None

    async def before_boot(self) -> None:
        await super().before_boot()
        # The stall net is active-high, so its "low" count is the cycles with
        # no stall; the stalled count is the remainder.
        self.count_low_cycles_from_now(STALL_SIGNAL)
        self.count_low_cycles_from_now(TX_READY_SIGNAL)

    async def after_pass(self) -> None:
        await super().after_pass()
        not_stalled, total = self.low_cycles_counted(STALL_SIGNAL)
        self.tx_ready_low_cycles, _ = self.low_cycles_counted(TX_READY_SIGNAL)
        self.stalled_cycles, self.sampled_cycles = total - not_stalled, total
        assert 0 < self.stalled_cycles < total, (
            f"{STALL_SIGNAL} was 1 on {self.stalled_cycles} of {total} clk_smc_i cycles while "
            f"the image ran; the engine writes {SCENARIO_B_BYTES} bytes in scenario B through a "
            f"transmitter that is ready only with an empty TX FIFO, so a fetched byte must have "
            f"waited on at least one cycle"
        )
        cocotb.log.info(
            "CHK-FW-LOG-ENGINE-TX-BACKPRESSURE: %s sampled 1 on %d of %d clk_smc_i cycles "
            "while the image ran (a fetched byte held at the engine's read-data FIFO while "
            "%s was low; %s was low on %d cycles in all, the rest with nothing to write), so "
            "the log-write FSM honours the UART's ready input; the firmware read all %d of "
            "scenario B's bytes back in order under it",
            STALL_SIGNAL,
            self.stalled_cycles,
            total,
            TX_READY_SIGNAL,
            TX_READY_SIGNAL,
            self.tx_ready_low_cycles,
            SCENARIO_B_BYTES,
        )


@pyuvm.test()
class smc_fw_uart_log_engine_boundary_backpressure_test(smc_base_test):
    """Firmware runs the boundary scenarios; the bench reads the source and engine state."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-LOG-ENGINE-BOUNDARY-BOOT",
        "CHK-FW-LOG-ENGINE-CSR-STATE",
        "CHK-FW-LOG-ENGINE-SPM-PATTERN",
        "CHK-FW-LOG-ENGINE-TX-BACKPRESSURE",
    )
    min_evidence = 4

    async def run_scenario(self) -> None:
        seq = _boundary_backpressure_seq(
            "fw_uart_log_engine_boundary_backpressure_seq",
            tag="LOG-ENGINE-BOUNDARY",
            # PASS landed 334 us after release in the reference run (~670 polls at a
            # 5 ns clk_smc_i); 7000 is ~10x that.
            poll_iterations=7_000,
            spm_pattern=SPM_PATTERN,
            engines=(
                LogEngineFinalState(0, LOG_BUFFER_BASE, SCENARIO_E_REGION_SIZE, uart_reg(0, "RBR")),
            ),
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.csr_state_ok and seq.spm_pattern_ok, (
            f"bench observation incomplete: csr={seq.csr_state_ok} spm={seq.spm_pattern_ok}"
        )
        assert seq.stalled_cycles, "the log-write stall count was never taken"
