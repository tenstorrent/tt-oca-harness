// SPDX-License-Identifier: Apache-2.0
//
// SEP real-entropy bring-up (ESRC -> DRBG -> CSRNG -> EDN) firmware driver.
// Header-only. Programs the OpenTitan-style entropy stack over the EL2 LSU bus so
// the Key Manager (and crypto engines) receive real EDN genbits -- the
// firmware-replicable equivalent of the OCAH UVM bring-up
// (sep_drbg_uvm_base_test_seq.sv configure_drbg_chain_from_cfg / enable_edn_mode),
// NOT a force. Order matters (mirrors the OCAH guard "configure EDN commands
// ONLY, do NOT enable EDN yet"):
//   1. sep_entropy_configure()       -- PHASE-A: mux, ESRC config (gens OFF),
//                                        CSRNG enable, stage EDN commands.
//   2. sep_entropy_start_generators()-- enable the ring-osc generators.
//   3. (allow time for the first seed to accumulate)
//   4. sep_entropy_enable_edn()      -- PHASE-B: enable EDN last.
// Under Verilator the ESRC ring oscillators do not self-oscillate, so the tb-side
// +esrc_noise_force supplies the raw noise; the DRBG/CSRNG/EDN math below is real.
// CSRNG/EDN sit behind a 64-bit lane adapter; an aligned 32-bit store at the
// register byte address lands on the correct lane. MuBi4: TRUE=0x6, FALSE=0x9.
// csrng cmd word = {8'h0, glen[11:0], flag0=0x9(use-entropy), clen=0, acmd}.

#ifndef SEP_ENTROPY_H
#define SEP_ENTROPY_H

#include <stdint.h>

// sep_cpu_ctrl
#define SEP_CLOCK_GATE_CTRL 0x10A30008u
#define SEP_CLOCK_GATE_ENTROPY 0x001F0421u // reset 0x001F0021 | entropy_fifo_cg (bit 10)
#define SEP_EXT_TRNG_SRC_SEL 0x10A30190u   // 0 = internal DRBG (reset 0x3 = ext_trng)
// entropy_source (flat 32-bit map @ 0x1091_6000)
#define SEP_ESRC_CTRL 0x10916004u
#define SEP_ESRC_FIFO_CTRL 0x10916020u
#define SEP_ESRC_HEALTH_TEST_CTRL 0x10916030u
#define SEP_ESRC_RING_OSC_ENABLE 0x10916090u
#define SEP_ESRC_DECORRELATOR_CTRL 0x109160A0u
// CSRNG @ 0x1091_5000, EDN @ 0x1091_5800 (lane adapter)
#define SEP_CSRNG_CTRL 0x10915014u
#define SEP_EDN_CTRL 0x10915814u
#define SEP_EDN_BOOT_INS_CMD 0x10915818u
#define SEP_EDN_RESEED_CMD 0x1091582Cu
#define SEP_EDN_GENERATE_CMD 0x10915830u
#define SEP_EDN_MAX_REQS 0x10915834u

#define SEP_RING_OSC_SAMPLECLK_ONLY 0x00FFF000u // SAMPLE_CLK_ENABLE on, generators off
#define SEP_RING_OSC_ALL_ON 0x00FFFFFFu         // generators + sample-clk on
#define SEP_CSRNG_CTRL_ENABLE 0x00009666u // {FIPS_FORCE=F, READ_INT_STATE=T, SW_APP=T, ENABLE=T}
#define SEP_EDN_CTRL_AUTO 0x00009666u     // {CMD_FIFO_RST=F, AUTO_REQ=T, BOOT_REQ=T, EDN_ENABLE=T}
#define SEP_CMD_INSTANTIATE 0x00000901u
#define SEP_CMD_RESEED 0x00000902u
#define SEP_CMD_GENERATE_GLEN32 0x00020903u // glen=32

static inline void sep_entropy_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

// PHASE-A: select internal DRBG, configure ESRC with generators OFF, enable
// CSRNG, and stage EDN's Instantiate/Reseed/Generate commands. EDN stays disabled.
static inline void sep_entropy_configure(void) {
    sep_entropy_wr(SEP_CLOCK_GATE_CTRL, SEP_CLOCK_GATE_ENTROPY);
    sep_entropy_wr(SEP_EXT_TRNG_SRC_SEL, 0x0);
    sep_entropy_wr(SEP_ESRC_RING_OSC_ENABLE, SEP_RING_OSC_SAMPLECLK_ONLY);
    sep_entropy_wr(SEP_ESRC_DECORRELATOR_CTRL, 0x003F0000u); // sample_div=63
    sep_entropy_wr(SEP_ESRC_FIFO_CTRL, 0x1);
    sep_entropy_wr(SEP_ESRC_HEALTH_TEST_CTRL, 0x00003207u); // rep_limit=50, rep/apt/markov en
    sep_entropy_wr(SEP_ESRC_CTRL, 0x10000001u);             // RESET=1, SHA256 whitening on
    sep_entropy_wr(SEP_ESRC_CTRL, 0x10000000u);             // RESET=0
    sep_entropy_wr(SEP_CSRNG_CTRL, SEP_CSRNG_CTRL_ENABLE);
    sep_entropy_wr(SEP_EDN_BOOT_INS_CMD, SEP_CMD_INSTANTIATE);
    sep_entropy_wr(SEP_EDN_RESEED_CMD, SEP_CMD_RESEED);
    sep_entropy_wr(SEP_EDN_GENERATE_CMD, SEP_CMD_GENERATE_GLEN32); // glen=32
    sep_entropy_wr(SEP_EDN_MAX_REQS, 8);                           // reseed interval=8
}

// Enable the ring-osc generators (the tb +esrc_noise_force already drives noise).
static inline void sep_entropy_start_generators(void) {
    sep_entropy_wr(SEP_ESRC_RING_OSC_ENABLE, SEP_RING_OSC_ALL_ON);
}

// PHASE-B: enable EDN last (auto+boot). Call after a seed has accumulated; EDN
// then auto-issues Instantiate+Generate and streams genbits to the KM.
static inline void sep_entropy_enable_edn(void) {
    sep_entropy_wr(SEP_EDN_CTRL, SEP_EDN_CTRL_AUTO);
}

#endif // SEP_ENTROPY_H
