# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OpenTitan SPI controller command sequence on the SEP, under the OSS wrapper.

Boots hw/sys/sep/dv/fw/tests/sep_smu_spi, which drives a minimal command /
address / receive sequence on the SEP's OpenTitan `spi_controller` and reads the
received word back out of RXDATA. The image is written for exactly this
configuration: it needs no external flash model, and it programs no pad path,
because the OT SPI host reaches the pads only on the SMC LSIO primary plane and
no select steers it. The received word is the bench's undriven MISO level (0),
not device content.

The SEP's third-party SPI host wrapper and the SPI flash device models are
excluded from the build (smu_sim_cfg.toml `exclude_files`), so nothing routed
through them can run here; `spi_controller` itself is compiled, and this image
exercises it.

The image parks in one of nine per-stage fail loops, so a failure names the point
in the transfer that stalled rather than just reporting "SPI did not pass".
"""

from __future__ import annotations

from seq_lib.sep_terminal_loop_seq import SepTerminalLoopSeq


class SmuSepSpiSeq(SepTerminalLoopSeq):
    NAME = "sep_spi"
    PASS_SYM = "smu_sep_spi_pass_loop"
    # Labels mirror the firmware's SPI_ERR_* codes, in transfer order.
    FAIL_SYMS = {
        "wait_ready_cmd": "smu_sep_spi_fail_wait_ready_cmd_loop",
        "wait_idle_cmd": "smu_sep_spi_fail_wait_idle_cmd_loop",
        "wait_ready_addr": "smu_sep_spi_fail_wait_ready_addr_loop",
        "wait_ready_rx": "smu_sep_spi_fail_wait_ready_rx_loop",
        "wait_idle_rx": "smu_sep_spi_fail_wait_idle_rx_loop",
        "error_status": "smu_sep_spi_fail_error_status_loop",
        "rx_depth": "smu_sep_spi_fail_rx_depth_loop",
        "rx_data": "smu_sep_spi_fail_rx_data_loop",
        "rx_drain": "smu_sep_spi_fail_rx_drain_loop",
        # Catch-all for an rc outside the enumerated codes. The compiler can
        # prove it unreachable and drop it; the base sequence then reports it as
        # a path this image does not cover, rather than assuming it passed.
        "unclassified": "smu_sep_spi_fail_loop",
    }
    SYM_DEFAULT = "sep_smu_spi.tcm.sym"
    EVIDENCE = ("SEP_REAL_FW_SPI_OK", "SEP_SPI_CONTROLLER_TXRX_OK")
