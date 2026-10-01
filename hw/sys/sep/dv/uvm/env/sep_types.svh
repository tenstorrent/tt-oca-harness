// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP bench constants, DUT geometry, and pure helper functions shared by the
// environment (scoreboard predictor, cfgs) and the sequence library (CSR
// operations, scenario helpers). Register addresses, reset values, and field
// masks come from the generated register header
// hw/sys/sep/regs/gen/svh/sep_reg.svh (the SystemVerilog export of
// hw/sys/sep/regs/sep.rdl); the few bench-only constants cite their source.
// No class lives here: everything is a package-scope type, constant, or
// `function automatic`. The cocotb twin is env/sep_reg_meta.py plus the
// SepAxiItem access contract.
//
// The TB modules compiled ahead of this package (tb/sep_outbound_mbx.sv,
// cov/sv/sep_fcov.sv) include sep_reg.svh first, which defines its include
// guard and puts the symbols in $unit. A package cannot reference $unit, so
// the guard is cleared here and the package declares its own copy.

`undef SEP_TOP_REG_SVH
`include "sep_reg.svh"

// ---------------------------------------------------------------------------
// CPU-LSU AXI4 splice: sep_cpu.lsu_axi_req behind the tb_top s_axi_* pins
// (sep_32_64_3_12 geometry: addr32/data64/id3/user12).
// ---------------------------------------------------------------------------
localparam int unsigned SepLsuAddrWidth = 32;
localparam int unsigned SepLsuDataWidth = 64;
localparam int unsigned SepLsuIdWidth = 3;
localparam int unsigned SepLsuBeatBytes = SepLsuDataWidth / 8;

// Every SEP CSR under test is a 32-bit register reached with a narrow
// single-beat transfer on the 64-bit bus (AxSIZE = 2); the data rides the
// addressed byte lanes, the same access shape the cocotb SepAxiDriver
// issues for a 4-byte item.
localparam int unsigned SepCsrBytes = 4;
localparam int unsigned SepCsrSize = 2;

// Scoreboard feature names (sep_scoreboard predictors; test cfg policy).
localparam string SepFeatureCpuCtrlCsr = "cpu_ctrl_csr";

// One predicted register: word address, reset value, and the
// implemented-field mask. Reserved fields are outside the mask, so a
// readback compares as `written & mask` (cocotb sep_reg_meta.mask32 parity).
typedef struct {
  string     name;
  bit [63:0] addr;
  bit [31:0] reset_value;
  bit [31:0] mask;
} sep_csr_desc_t;

// Implemented-field masks of the multi-field registers, folded from the
// generated per-field masks.
localparam bit [31:0] SepPkaCtrlMask = 32'(
    SEP_CPU_CTRL_PKA_CTRL_PKA_DPA_DISABLE_MASK | SEP_CPU_CTRL_PKA_CTRL_PKA_NOISE_SRC_MASK |
    SEP_CPU_CTRL_PKA_CTRL_PKA_NOISE_SRC_VALID_MASK
);

// The sep_cpu_ctrl registers the cpu_ctrl_csr feature predicts: software RW
// registers with no hardware side effect and no external-memory dependency,
// so a write lands on exactly the implemented field bits and reads back
// through the same path. SEP_LOCAL_BASE_ADDR carries a non-zero reset
// value, so a successful reset read proves the block decoded rather than
// returning zeros from an unmapped address.
function automatic void sep_cpu_ctrl_csr_regs(ref sep_csr_desc_t regs[$]);
  regs.delete();
  regs.push_back('{"SEP_LOCAL_BASE_ADDR", 64'(SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_REG_ADDR),
                 32'(SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_REG_DEFAULT),
                 32'(SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_ADDR_MASK)});
  regs.push_back('{"SEP_SW_DEBUG", 64'(SEP_CPU_CTRL_SEP_SW_DEBUG_REG_ADDR),
                 32'(SEP_CPU_CTRL_SEP_SW_DEBUG_REG_DEFAULT),
                 32'(SEP_CPU_CTRL_SEP_SW_DEBUG_SEP_SW_DEBUG_MASK)});
  regs.push_back('{"SEP_NMI_VEC", 64'(SEP_CPU_CTRL_SEP_NMI_VEC_REG_ADDR),
                 32'(SEP_CPU_CTRL_SEP_NMI_VEC_REG_DEFAULT),
                 32'(SEP_CPU_CTRL_SEP_NMI_VEC_NMI_VEC_MASK)});
  regs.push_back('{"PKA_CTRL", 64'(SEP_CPU_CTRL_PKA_CTRL_REG_ADDR),
                 32'(SEP_CPU_CTRL_PKA_CTRL_REG_DEFAULT), SepPkaCtrlMask});
  regs.push_back('{"SEP_REGION_SIZE", 64'(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_ADDR),
                 32'(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_DEFAULT),
                 32'(SEP_CPU_CTRL_SEP_REGION_SIZE_SIZE_MASK)});
endfunction

// ---------------------------------------------------------------------------
// 32-bit CSR on the 64-bit beat: lane placement helpers (raw-bus-word item
// semantics of the shared AXI VIP).
// ---------------------------------------------------------------------------

// CSR word address (4-byte aligned) of a bus address.
function automatic bit [63:0] sep_csr_word_addr(bit [63:0] addr);
  return addr & ~64'(SepCsrBytes - 1);
endfunction

// First byte lane of the CSR inside the beat (0 or 4 on the 64-bit bus).
function automatic int unsigned sep_csr_lane(bit [63:0] addr);
  return int'(sep_csr_word_addr(addr) % SepLsuBeatBytes);
endfunction

// Write strobes of one CSR access.
function automatic bit [7:0] sep_csr_strb(bit [63:0] addr);
  return 8'(8'h0F << sep_csr_lane(addr));
endfunction

// CSR value positioned on its lanes of the bus word.
function automatic bit [63:0] sep_csr_to_bus(bit [63:0] addr, bit [31:0] data);
  return 64'(data) << (8 * sep_csr_lane(addr));
endfunction

// CSR value extracted from the bus word.
function automatic bit [31:0] sep_csr_from_bus(bit [63:0] addr, bit [63:0] word);
  return 32'(word >> (8 * sep_csr_lane(addr)));
endfunction

// ---------------------------------------------------------------------------
// Predicted-register lookups.
// ---------------------------------------------------------------------------

// Descriptor of the predicted register at a bus address; 0 when the word
// address is outside the predicted set.
function automatic bit sep_cpu_ctrl_csr_lookup(bit [63:0] addr, output sep_csr_desc_t desc);
  sep_csr_desc_t regs[$];
  sep_cpu_ctrl_csr_regs(regs);
  foreach (regs[i]) begin
    if (regs[i].addr == sep_csr_word_addr(addr)) begin
      desc = regs[i];
      return 1'b1;
    end
  end
  return 1'b0;
endfunction

// Descriptor of a predicted register by name; 0 when the name is unknown.
function automatic bit sep_cpu_ctrl_csr_by_name(string name, output sep_csr_desc_t desc);
  sep_csr_desc_t regs[$];
  sep_cpu_ctrl_csr_regs(regs);
  foreach (regs[i]) begin
    if (regs[i].name == name) begin
      desc = regs[i];
      return 1'b1;
    end
  end
  return 1'b0;
endfunction

// A CSR access the cpu_ctrl_csr feature predicts and compares: an OKAY
// single-beat transfer on a predicted register (the narrow 32-bit CSR access
// shape); anything else on the block is outside the contract.
function automatic bit sep_is_cpu_ctrl_csr_access(ocah_axi_item t, output sep_csr_desc_t desc);
  if (!sep_cpu_ctrl_csr_lookup(t.address, desc)) return 1'b0;
  return t.is_ok() && t.data_words.size() == 1 && t.beat_count() == 1;
endfunction
