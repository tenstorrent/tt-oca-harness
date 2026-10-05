# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM (PicoRV32) ROM firmware for the SEP DV ESRC -> DRBG -> CSRNG -> EDN -> KM
# entropy alive smoke. The Key Manager's drbg_sampler only asserts TREADY on the
# EDN->KM stream when its own CPU pulls entropy, so this firmware makes the KM
# genuinely CONSUME one genbits word (a real tvalid && tready handshake).
#
# The DRBG-sampler DATA read blocks until a stream word is available; the
# sampler's read-timeout (CFG.TIMEOUT, reset 256 cycles) would otherwise abort
# the read long before the forced-noise entropy datapath produces a seed
# (~78k cycles), so the timeout is disabled first by writing CFG = 0.
#
# Addresses come from the generated key_manager_addr.h (key_manager.rdl):
#   DRBG sampler DATA  read consumes one EDN stream word
#   DRBG sampler CFG   TIMEOUT[31:16], PREFETCH[0]  (reset 0x0100_0000)
#   KM SRAM base       word0 used as a consumed-word liveness marker
#
# Build (output committed as ../km_rom_entropy.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_entropy.parhex

#include "key_manager_addr.h"

    .equ DRBG_SAMPLER,  KEY_MANAGER_DRBG_SAMPLER_BASE_ADDR
    .equ SAMPLER_DATA,  KEY_MANAGER_DRBG_SAMPLER_DATA_BASE_ADDR - KEY_MANAGER_DRBG_SAMPLER_BASE_ADDR
    .equ SAMPLER_CFG,   KEY_MANAGER_DRBG_SAMPLER_CFG_BASE_ADDR - KEY_MANAGER_DRBG_SAMPLER_BASE_ADDR
    .equ SRAM_BASE,     KEY_MANAGER_SRAM_BASE_ADDR

    .section .text
    .globl _start
_start:
    li    x1, DRBG_SAMPLER       # DRBG sampler base
    sw    x0, SAMPLER_CFG(x1)    # CFG = 0 -> disable read timeout (and prefetch)
    lw    x2, SAMPLER_DATA(x1)   # DATA read: blocks until entropy, KM consumes a word
    li    x3, SRAM_BASE          # KM SRAM base
    sw    x2, 0(x3)              # store consumed word to SRAM word0 (liveness marker)
1:  j     1b                     # spin
