# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
################################################################################
# io_delay_budgets.tcl - I/O delay budgets, as a fraction of the clock period
#
# One table for every block, so a port that appears at several levels (a child
# block's own top and its parent's passthrough) carries the same budget at each.
# Sourced by each block's I/O delay files.
################################################################################

global io_budget
# Generic synchronous I/O: half the period outside the block.
set io_budget(default) 0.5
# Memory requests go straight to the macro; responses reserve the access time.
set io_budget(mem_req) 0.1
set io_budget(sram_rsp) 0.6
set io_budget(rom_rsp) 0.7
# Asynchronous inputs resynchronized inside the block.
set io_budget(async) 0.1
# External JTAG hop, applied from the launching TCK edge: the host drives TMS,
# TDI and TRST on the falling edge and samples TDO on the rising edge.
set io_budget(jtag) 0.2
