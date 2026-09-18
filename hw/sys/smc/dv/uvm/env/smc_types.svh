// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC bench constants, DUT geometry, and pure helper functions shared by the
// environment (scoreboard predictor, cfgs) and the sequence library (CSR
// operations, scenario helpers). Register addresses come from the generated
// smc_top_addrmap_pkg (hw/sys/smc/regs/gen/sv/smc_addrmap_pkg.sv); the few
// bench-only constants cite their source. No class lives here: everything is
// a package-scope type, constant, or `function automatic`. The cocotb twin
// is seq_lib/smc_addr_map.py plus the SmcSysAxiItem access contract.

// ---------------------------------------------------------------------------
// SEP_IN AXI4 ingress: smc_wrapper.sep_axi_in_req_i behind the tb_top
// s_axi_* pins (smc_pkg::smc_sep_in_56_64_6_12_axi_req_t geometry).
// ---------------------------------------------------------------------------
localparam int unsigned SmcSepInAddrWidth = 56;
localparam int unsigned SmcSepInDataWidth = 64;
localparam int unsigned SmcSepInIdWidth = 6;
// SYS_OUT AXI4 egress geometry (smc_pkg smc_sys_out_56_64_8_12_axi_*).
localparam int unsigned SmcSysOutAddrWidth = 56;
localparam int unsigned SmcSysOutDataWidth = 64;
localparam int unsigned SmcSysOutIdWidth = 8;
localparam int unsigned SmcSepInBeatBytes = SmcSepInDataWidth / 8;

// Every SMC CSR is a 32-bit register reached with a narrow single-beat
// transfer on the 64-bit bus (AxSIZE = 2); the data rides the addressed
// byte lanes, the same access shape the cocotb SmcSysAxiDriver issues.
localparam int unsigned SmcCsrBytes = 4;
localparam int unsigned SmcCsrSize = 2;

// Scoreboard feature names (smc_scoreboard predictors; test cfg policy).
localparam string SmcFeatureScratchCsr = "scratch_csr";

// SMC_MISC_WRAP scratch windows: SCRATCH_COLD lives in the cold reset
// domain, SCRATCH_COLD_WARM in the warm domain that fuse sense releases.
localparam bit [63:0] SmcScratchColdBase =
    smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR;
localparam bit [63:0] SmcScratchColdSize =
    smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SIZE;
localparam bit [63:0] SmcScratchColdWarmBase =
    smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR;
localparam bit [63:0] SmcScratchColdWarmSize =
    smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SIZE;

// SCRATCH_COLD[idx] / SCRATCH_COLD_WARM[idx] absolute addresses.
function automatic bit [63:0] smc_scratch_cold_addr(int unsigned idx);
  return 64'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR(idx));
endfunction

function automatic bit [63:0] smc_scratch_cold_warm_addr(int unsigned idx);
  return 64'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR(idx));
endfunction

// 1 when `addr` falls inside a scratch window; `warm` names the domain.
function automatic bit smc_is_scratch_csr(bit [63:0] addr, output bit warm);
  warm = 1'b0;
  if (addr >= SmcScratchColdBase && addr < SmcScratchColdBase + SmcScratchColdSize) return 1'b1;
  if (addr >= SmcScratchColdWarmBase && addr < SmcScratchColdWarmBase + SmcScratchColdWarmSize) begin
    warm = 1'b1;
    return 1'b1;
  end
  return 1'b0;
endfunction

// A scratch CSR access the scratch_csr feature predicts and compares: an
// OKAY single-beat transfer inside a scratch window (the narrow 32-bit CSR
// access shape); anything else on the window is outside the contract.
function automatic bit smc_is_scratch_csr_access(ocah_axi_item t, output bit warm);
  if (!smc_is_scratch_csr(t.address, warm)) return 1'b0;
  return t.is_ok() && t.data_words.size() == 1 && t.beat_count() == 1;
endfunction

// ---------------------------------------------------------------------------
// 32-bit CSR on the 64-bit beat: lane placement helpers (raw-bus-word item
// semantics of the shared AXI VIP).
// ---------------------------------------------------------------------------

// CSR word address (4-byte aligned) of a bus address.
function automatic bit [63:0] smc_csr_word_addr(bit [63:0] addr);
  return addr & ~64'(SmcCsrBytes - 1);
endfunction

// First byte lane of the CSR inside the beat (0 or 4 on the 64-bit bus).
function automatic int unsigned smc_csr_lane(bit [63:0] addr);
  return int'(smc_csr_word_addr(addr) % SmcSepInBeatBytes);
endfunction

// Write strobes of one CSR access.
function automatic bit [7:0] smc_csr_strb(bit [63:0] addr);
  return 8'(8'h0F << smc_csr_lane(addr));
endfunction

// CSR value positioned on its lanes of the bus word.
function automatic bit [63:0] smc_csr_to_bus(bit [63:0] addr, bit [31:0] data);
  return 64'(data) << (8 * smc_csr_lane(addr));
endfunction

// CSR value extracted from the bus word.
function automatic bit [31:0] smc_csr_from_bus(bit [63:0] addr, bit [63:0] word);
  return 32'(word >> (8 * smc_csr_lane(addr)));
endfunction
