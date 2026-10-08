// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC bench constants, DUT geometry, and pure helper functions shared by the
// environment (scoreboard predictor, cfgs) and the sequence library (CSR
// operations, scenario helpers). Register addresses come from the generated
// smc_top_addrmap_pkg (hw/sys/smc/regs/gen/sv/smc_addrmap_pkg.sv) and reset
// values from the generated register header smc_reg.svh included below (the
// SystemVerilog export of hw/sys/smc/regs/smc.rdl, same split the cocotb
// twin uses: address from smc_addr.h, expected value from the block header);
// the few bench-only constants cite their source. No class lives here:
// everything is a package-scope type, constant, or `function automatic`. The
// cocotb twin is seq_lib/smc_addr_map.py plus seq_lib/smc_csr_field_catalog.py
// and the SmcSysAxiItem access contract.

`include "smc_reg.svh"

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

// SPM memory is reached with a FULL-WIDTH single-beat transfer instead: one
// 64-bit word, every byte lane strobed (AxSIZE = 3). A CSR-shaped 32-bit
// access would leave half of each word untouched and could not tell two
// aliased addresses apart.
localparam int unsigned SmcMemBytes = SmcSepInBeatBytes;
localparam int unsigned SmcMemSize = 3;

typedef enum {
  WDT_CTRL,
  WDT_COUNT,
  WDT_KEY,
  WDT_CMP,
  WDT_SCALED_COUNT,
  WDT_FEED
} smc_wdt_reg_e;
// KEY and FEED magic values from the wdt.rdl KEY and FEED descriptions.
localparam bit [31:0] SmcWdtMagicKey = 32'h0051_F15E;
localparam bit [31:0] SmcWdtFeedMagic = 32'h0D09_F00D;
localparam int unsigned SmcWdtCores = 4;
localparam bit [63:0] SmcWdtBytes = smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_SIZE;

function automatic bit [63:0] smc_wdt_addr(int unsigned core, smc_wdt_reg_e reg_kind);
  case (core)
    0: case (reg_kind)
      WDT_CTRL: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR;
      WDT_COUNT: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_COUNT_BASE_ADDR;
      WDT_KEY: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_KEY_BASE_ADDR;
      WDT_CMP: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR;
      WDT_SCALED_COUNT: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_SCALED_COUNT_BASE_ADDR;
      WDT_FEED: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_FEED_BASE_ADDR;
      default: return '1;
    endcase
    1: case (reg_kind)
      WDT_CTRL: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE1_WDT_CTRL_BASE_ADDR;
      WDT_COUNT: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE1_WDT_COUNT_BASE_ADDR;
      WDT_KEY: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE1_WDT_KEY_BASE_ADDR;
      WDT_CMP: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE1_WDT_CMP_BASE_ADDR;
      WDT_SCALED_COUNT: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE1_WDT_SCALED_COUNT_BASE_ADDR;
      WDT_FEED: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE1_WDT_FEED_BASE_ADDR;
      default: return '1;
    endcase
    2: case (reg_kind)
      WDT_CTRL: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE2_WDT_CTRL_BASE_ADDR;
      WDT_COUNT: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE2_WDT_COUNT_BASE_ADDR;
      WDT_KEY: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE2_WDT_KEY_BASE_ADDR;
      WDT_CMP: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE2_WDT_CMP_BASE_ADDR;
      WDT_SCALED_COUNT: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE2_WDT_SCALED_COUNT_BASE_ADDR;
      WDT_FEED: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE2_WDT_FEED_BASE_ADDR;
      default: return '1;
    endcase
    3: case (reg_kind)
      WDT_CTRL: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE3_WDT_CTRL_BASE_ADDR;
      WDT_COUNT: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE3_WDT_COUNT_BASE_ADDR;
      WDT_KEY: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE3_WDT_KEY_BASE_ADDR;
      WDT_CMP: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE3_WDT_CMP_BASE_ADDR;
      WDT_SCALED_COUNT: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE3_WDT_SCALED_COUNT_BASE_ADDR;
      WDT_FEED: return smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE3_WDT_FEED_BASE_ADDR;
      default: return '1;
    endcase
    default: return '1;
  endcase
  return '1;
endfunction

// Scoreboard feature names (smc_scoreboard predictors; test cfg policy).
localparam string SmcFeatureScratchCsr = "scratch_csr";
localparam string SmcFeatureDefaultReg = "default_reg";
localparam string SmcFeatureLockCsr = "lock_csr";
localparam string SmcFeatureMutexSema = "mutex_sema";
localparam string SmcFeatureSpmMem = "spm_mem";
localparam string SmcFeatureRegblockWide = "regblock_wide";
localparam string SmcFeatureWdtCsr = "wdt_csr";

localparam bit [63:0] SmcZeroerDestAddr =
    64'(smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR);
localparam bit [63:0] SmcZeroerSizeAddr =
    64'(smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_SIZE_BASE_ADDR);
localparam bit [63:0] SmcZeroerCtrlStatusAddr =
    64'(smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR);
localparam bit [63:0] SmcHangSysCtrlAddr =
    64'(smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_CTRL_BASE_ADDR);
localparam bit [63:0] SmcHangSysThresholdAddr =
    64'(smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR);
localparam bit [63:0] SmcHangSepCtrlAddr =
    64'(smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR);
localparam bit [63:0] SmcHangSepThresholdAddr =
    64'(smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD_BASE_ADDR);
localparam bit [63:0] SmcHangDataAccelCtrlAddr =
    64'(smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR);
localparam bit [63:0] SmcHangDataAccelThresholdAddr = 64'(
    smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD_BASE_ADDR
);
localparam bit [63:0] SmcAliasRegionStartAddr =
    64'(smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR(
    0
));
localparam bit [63:0] SmcAliasRegionEndAddr =
    64'(smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR(
    0
));
localparam bit [63:0] SmcAliasRegionAttrsAddr =
    64'(smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR(
    0
));

typedef struct {
  string     name;
  bit [63:0] addr;
  bit [63:0] reset_value;
  bit [63:0] rw_mask;
  bit [7:0]  rw_lane_mask;
} smc_regblock_wide_entry_t;

function automatic bit [7:0] smc_rw_lane_mask(bit [63:0] rw_mask);
  bit [7:0] lane_mask;
  for (int unsigned lane = 0; lane < SmcMemBytes; lane++) begin
    lane_mask[lane] = |rw_mask[8*lane+:8];
  end
  return lane_mask;
endfunction

function automatic bit [63:0] smc_regblock_merge_write(bit [63:0] original, bit [63:0] data,
                                                       bit [7:0] strb, bit [63:0] rw_mask);
  bit [63:0] biten;
  for (int unsigned lane = 0; lane < SmcMemBytes; lane++) begin
    biten[8*lane+:8] = {8{strb[lane]}};
  end
  return (original & ~(biten & rw_mask)) | (data & biten & rw_mask);
endfunction

function automatic void smc_regblock_wide_catalog(ref smc_regblock_wide_entry_t entries[$]);
  bit [63:0] rw_mask;
  entries.delete();
  rw_mask = 64'(ZEROER_CTRL_DEST_ADDR_DEST_ADDR_MASK);
  entries.push_back('{"ZEROER_CTRL.DEST_ADDR", SmcZeroerDestAddr,
                    64'(ZEROER_CTRL_DEST_ADDR_REG_DEFAULT), rw_mask, smc_rw_lane_mask(rw_mask)});
  rw_mask = 64'(ZEROER_CTRL_SIZE_SIZE_MASK);
  entries.push_back('{"ZEROER_CTRL.SIZE", SmcZeroerSizeAddr, 64'(ZEROER_CTRL_SIZE_REG_DEFAULT),
                    rw_mask, smc_rw_lane_mask(rw_mask)});
  rw_mask = 64'(SMC_BASE_CONFIG_HANG_DET_TIMEOUT_THRESHOLD_VALUE_MASK);
  entries.push_back('{"SMC_BASE_CONFIG.HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD", SmcHangSysThresholdAddr,
                    64'(SMC_BASE_CONFIG_HANG_DET_TIMEOUT_THRESHOLD_REG_DEFAULT), rw_mask,
                    smc_rw_lane_mask(rw_mask)});
  entries.push_back('{"SMC_BASE_CONFIG.HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD", SmcHangSepThresholdAddr,
                    64'(SMC_BASE_CONFIG_HANG_DET_TIMEOUT_THRESHOLD_REG_DEFAULT), rw_mask,
                    smc_rw_lane_mask(rw_mask)});
  entries.push_back('{"SMC_BASE_CONFIG.HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD",
                    SmcHangDataAccelThresholdAddr,
                    64'(SMC_BASE_CONFIG_HANG_DET_TIMEOUT_THRESHOLD_REG_DEFAULT), rw_mask,
                    smc_rw_lane_mask(rw_mask)});
  rw_mask = 64'(REMAP_REGION_REGION_START_START_ADDR_MASK);
  entries.push_back('{"SMC_ALIAS_REMAP_0.REGION_START", SmcAliasRegionStartAddr,
                    64'(REMAP_REGION_REGION_START_REG_DEFAULT), rw_mask, smc_rw_lane_mask(rw_mask)
                    });
  rw_mask = 64'(REMAP_REGION_REGION_END_END_ADDR_MASK);
  entries.push_back('{"SMC_ALIAS_REMAP_0.REGION_END", SmcAliasRegionEndAddr,
                    64'(REMAP_REGION_REGION_END_REG_DEFAULT), rw_mask, smc_rw_lane_mask(rw_mask)});
endfunction

function automatic bit smc_regblock_wide_lookup(
    bit [63:0] addr, output smc_regblock_wide_entry_t entry, output int unsigned index);
  smc_regblock_wide_entry_t entries[$];
  smc_regblock_wide_catalog(entries);
  foreach (entries[i]) begin
    if (addr == entries[i].addr) begin
      entry = entries[i];
      index = i;
      return 1'b1;
    end
  end
  return 1'b0;
endfunction

// Catalogued single-beat reads and writes reach response grading regardless
// of response. The model updates its shadow only for an OKAY write.
function automatic bit smc_is_regblock_wide_access(
    ocah_axi_item t, output smc_regblock_wide_entry_t entry, output int unsigned index);
  if (!smc_regblock_wide_lookup(t.address, entry, index)) return 1'b0;
  return t.data_words.size() == 1 && t.beat_count() == 1;
endfunction

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

// ---------------------------------------------------------------------------
// CSR reset epoch: the value every CSR reference model re-baselines its
// shadow on. Both the cold reset and a de-glitched cool reset are terms of
// the primary reset (clk_rst.adoc "Primary and Warm Reset": rst_primary_n =
// stable_cold_rst_n AND stable_cool_rst_n AND rst_cool_from_flr_n), and
// "Primary reset covers the main SMC functional fabric, peripheral control
// and configuration paths" -- every CSR block reached over SEP_IN, both
// scratch windows included (misc_wrap.rdl; the warm reset equation
// takes rst_primary_n as a term). A model that watched only the cold counter
// would keep predicting pre-cool-reset values.
//
// SPM memory is not on this epoch: it is an SRAM, and nothing in this bench
// establishes that a reset clears its contents.
// ---------------------------------------------------------------------------
function automatic bit [63:0] smc_csr_reset_epoch(bit [31:0] cold_count, bit [31:0] cool_count);
  return {cold_count, cool_count};
endfunction

// ---------------------------------------------------------------------------
// default_reg catalogue: the registers whose post-reset content the
// default_reg feature predicts, and how each one is allowed to be judged.
// Both halves of every compare are symbol-sourced -- the address from
// smc_top_addrmap_pkg, the expected value from a generated *_REG_DEFAULT of
// smc_reg.svh -- so a regenerated RDL moves address and expectation
// together. The three access kinds mirror the cocotb
// seq_lib/smc_csr_field_catalog.py SmcCsrAccessKind:
//
//   SMC_REG_KIND_RW_RESTORE  RDL `sw=rw` (hw=r or hw=na): software owns the
//                            storage, so it holds its reset value until software
//                            writes it. Compared, and a write updates the shadow.
//   SMC_REG_KIND_RO_STATIC   RDL `sw=r; hw=w` where the hardware side is an
//                            integration constant or a TB tie-off, so the read is
//                            deterministic in this bench. Compared; a write can
//                            never change it, so the shadow ignores writes.
//   SMC_REG_KIND_RO_STATUS   RDL `sw=r; hw=w` from live state or from a value the
//                            harness drives to something other than the RDL
//                            default. DECODE-ONLY: `has_default` is 0, no expected
//                            item is published, and only the OKAY response and the
//                            access count are evidence.
//
// A register whose read has a side effect must NOT appear here (CPU_CTRL
// MUTEX acquires on read, so its second read legitimately differs from its
// default -- it belongs to the mutex_sema feature instead).
// ---------------------------------------------------------------------------

typedef enum int unsigned {
  SMC_REG_KIND_RW_RESTORE,
  SMC_REG_KIND_RO_STATIC,
  SMC_REG_KIND_RO_STATUS
} smc_reg_kind_e;

typedef struct {
  string         name;
  bit [63:0]     addr;
  smc_reg_kind_e kind;
  bit            has_default;    // 0 => decode-only, no value contract
  bit [31:0]     default_value;
  string         why;            // cited reason for the kind / decode-only
} smc_default_reg_entry_t;

function automatic void smc_default_reg_catalog(ref smc_default_reg_entry_t entries[$]);
  entries.delete();

  // --- scratch.rdl: `sw=rw; hw=na`, pure software storage, 8 instances. ---
  entries.push_back('{"SCRATCH_COLD_0", smc_scratch_cold_addr(0), SMC_REG_KIND_RW_RESTORE, 1'b1,
                    32'(SCRATCH_SCRATCH_REG_DEFAULT), "scratch.rdl sw=rw hw=na"});
  entries.push_back('{"SCRATCH_COLD_7", smc_scratch_cold_addr(7), SMC_REG_KIND_RW_RESTORE, 1'b1,
                    32'(SCRATCH_SCRATCH_REG_DEFAULT), "scratch.rdl sw=rw hw=na (window top)"});
  entries.push_back('{"SCRATCH_COLD_WARM_0", smc_scratch_cold_warm_addr(0), SMC_REG_KIND_RW_RESTORE,
                    1'b1, 32'(SCRATCH_SCRATCH_REG_DEFAULT),
                    "scratch.rdl sw=rw hw=na, warm reset domain"});
  entries.push_back('{"SCRATCH_COLD_WARM_7", smc_scratch_cold_warm_addr(7), SMC_REG_KIND_RW_RESTORE,
                    1'b1, 32'(SCRATCH_SCRATCH_REG_DEFAULT),
                    "scratch.rdl sw=rw hw=na, warm domain window top"});

  // --- chip_config.rdl ---
  // VERSION_LO/HI and CHIP_ID are `sw=r; hw=w`, driven by smc_misc_wrap from
  // its integration parameters; this bench leaves those parameters at their
  // defaults, which are the constants the generated map declares, so the
  // compare is exact. VERSION_LO's default is non-zero, so a read path stuck
  // at 0 cannot pass this catalogue.
  entries.push_back(
      '{"CHIP_CONFIG_VERSION_LO",
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR),
      SMC_REG_KIND_RO_STATIC, 1'b1, 32'(CHIP_CONFIG_VERSION_LO_REG_DEFAULT),
      "chip_config.rdl sw=r hw=w from integration constant (non-zero default)"});
  entries.push_back(
      '{"CHIP_CONFIG_VERSION_HI",
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_HI_BASE_ADDR),
      SMC_REG_KIND_RO_STATIC, 1'b1, 32'(CHIP_CONFIG_VERSION_HI_REG_DEFAULT),
      "chip_config.rdl sw=r hw=w from integration constant"});
  entries.push_back('{"CHIP_CONFIG_CHIP_ID",
                    64'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_BASE_ADDR),
                    SMC_REG_KIND_RO_STATIC, 1'b1, 32'(CHIP_CONFIG_CHIP_ID_REG_DEFAULT),
                    "chip_config.rdl sw=r hw=w from the CHIP_ID module parameter"});
  // LC_STATE is `sw=r; hw=w` and the UVM harness drives tb_lc_state with the
  // complementary TEST_DEV encoding rather than the RDL default, so its read
  // is an integration value with no default contract: decode-only.
  entries.push_back('{"CHIP_CONFIG_LC_STATE",
                    64'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_LC_STATE_BASE_ADDR),
                    SMC_REG_KIND_RO_STATUS, 1'b0, 32'h0,
                    "chip_config.rdl sw=r hw=w; harness drives tb_lc_state, not the RDL default"});

  // --- ndm_reset.rdl ---
  // NDMRESET_REQUEST is `sw=r; hw=w` and the UVM harness ties
  // tb_ndmreset_request to '0 (tb_top.sv quiescent tie-offs), so unlike the
  // cocotb twin it is deterministic here and is compared against zero.
  entries.push_back(
      '{"NDM_RESET_NDMRESET_REQUEST",
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_REQUEST_BASE_ADDR),
      SMC_REG_KIND_RO_STATIC, 1'b1, 32'(NDM_RESET_NDMRESET_REQUEST_REG_DEFAULT),
      "ndm_reset.rdl sw=r hw=w; harness ties tb_ndmreset_request to '0"});
  entries.push_back(
      '{"NDM_RESET_NDMRESET_PROCESS",
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_PROCESS_BASE_ADDR),
      SMC_REG_KIND_RW_RESTORE, 1'b1, 32'(NDM_RESET_NDMRESET_PROCESS_REG_DEFAULT),
      "ndm_reset.rdl sw=rw hw=r"});
  // CLUSTER_COUNT is `sw=r; hw=w` from a design-side count this bench does not
  // establish: decode-only.
  entries.push_back('{"NDM_RESET_NDMRESET_CLUSTER_COUNT",
                    64'(
                    // verilog_format: off
                    smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR
                    // verilog_format: on
                    ),
                    SMC_REG_KIND_RO_STATUS, 1'b0, 32'h0,
                    "ndm_reset.rdl sw=r hw=w from a design-side count"});

  // --- reset_unit.rdl ---
  // SS_WARM_RESET_N is a plain PeakRDL-internal `sw=rw; hw=r` register
  // that no lock description in reset_unit.rdl names, so a write lands
  // unfiltered and the shadow rule above describes it. Its default is all
  // ones.
  entries.push_back('{"RESET_UNIT_SS_WARM_RESET_N",
                    64'(smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR),
                    SMC_REG_KIND_RW_RESTORE, 1'b1, 32'(RESET_UNIT_SS_WARM_RESET_N_REG_DEFAULT),
                    "reset_unit.rdl:44-49 sw=rw hw=r, default 0xFFFFFFFF (non-zero)"});
  // SS_CONFIG, SS_CONFIG_LOCK and SS_COLD_RESET_N are lock_csr registers: the
  // locks are `onwrite=woset` (a written 0 is inert) and a locked bit of a
  // guarded register "cannot be written to again" (reset_unit.rdl), which the
  // plain shadow rule of this catalogue cannot predict.
endfunction

// Catalogue entry addressing `word_addr`, if any. Used by the reference model
// to decide whether a transaction it observed carries a default contract.
function automatic bit smc_default_reg_lookup(bit [63:0] word_addr,
                                              output smc_default_reg_entry_t entry);
  smc_default_reg_entry_t entries[$];
  smc_default_reg_catalog(entries);
  foreach (entries[i]) begin
    if (smc_csr_word_addr(entries[i].addr) == word_addr) begin
      entry = entries[i];
      return 1'b1;
    end
  end
  return 1'b0;
endfunction

// A catalogued CSR access the default_reg feature may judge: an OKAY
// single-beat transfer at a catalogued address (the narrow 32-bit CSR shape).
function automatic bit smc_is_default_reg_access(ocah_axi_item t,
                                                 output smc_default_reg_entry_t entry);
  if (!smc_default_reg_lookup(smc_csr_word_addr(t.address), entry)) return 1'b0;
  return t.is_ok() && t.data_words.size() == 1 && t.beat_count() == 1;
endfunction

// ---------------------------------------------------------------------------
// lock_csr: the reset unit's two write-once lock registers and the register
// each one guards. Both locks are declared `sw=rw; hw=r; onwrite=woset;` with
// reset 0 and one bit per subsystem, and each lock's RDL description names
// its guarded register and the per-bit rule: SS_CONFIG_LOCK "lock[s] down SS
// config. If bit 0 is written, then bit 0 of other SS config cannot be
// written to again" (reset_unit.rdl SS_CONFIG_LOCK description);
// SS_COLD_RESET_LOCK the same for SS cold reset (its own description). So a
// write to the guarded register lands only on the bits that are strobed and
// unlocked, and a locked bit keeps its value on read-back: that is the
// property the lock_csr feature predicts. Both guarded registers reset to 0,
// the value the generated *_REG_DEFAULT declares.
// ---------------------------------------------------------------------------

typedef struct {
  string     name;
  bit [63:0] target_addr;
  bit [63:0] lock_addr;
  string     rdl_cite;
} smc_lock_pair_t;

function automatic void smc_lock_pairs(ref smc_lock_pair_t pairs[$]);
  pairs.delete();
  pairs.push_back('{"COLD_RESET",
                  64'(smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR),
                  64'(smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR),
                  "reset_unit.rdl:89-96 (SS_COLD_RESET_LOCK guards SS cold reset)"});
  pairs.push_back('{"CONFIG", 64'(smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR),
                  64'(smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_LOCK_BASE_ADDR),
                  "reset_unit.rdl:20-27 (SS_CONFIG_LOCK guards SS config)"});
endfunction

// Locate `word_addr` in the lock-pair table; `is_lock` tells the two roles
// apart.
function automatic bit smc_lock_lookup(bit [63:0] word_addr, output int unsigned pair_idx,
                                       output bit is_lock);
  smc_lock_pair_t pairs[$];
  smc_lock_pairs(pairs);
  foreach (pairs[i]) begin
    if (smc_csr_word_addr(pairs[i].target_addr) == word_addr) begin
      pair_idx = i;
      is_lock  = 1'b0;
      return 1'b1;
    end
    if (smc_csr_word_addr(pairs[i].lock_addr) == word_addr) begin
      pair_idx = i;
      is_lock  = 1'b1;
      return 1'b1;
    end
  end
  return 1'b0;
endfunction

// A lock-pair CSR access the lock_csr feature may judge.
function automatic bit smc_is_lock_csr_access(ocah_axi_item t, output int unsigned pair_idx,
                                              output bit is_lock);
  if (!smc_lock_lookup(smc_csr_word_addr(t.address), pair_idx, is_lock)) return 1'b0;
  return t.is_ok() && t.data_words.size() == 1 && t.beat_count() == 1;
endfunction

// Bits 1..bit_index of a 32-bit word: the bits this bench has put under a
// lock by the given scenario pass; bit 0 is the never-locked control.
function automatic bit [31:0] smc_lock_accum_mask(int unsigned bit_index);
  return 32'((32'h1 << (bit_index + 1)) - 32'h2);
endfunction

// ---------------------------------------------------------------------------
// mutex_sema: the CPU_CTRL hardware mutexes and semaphores, whose READ and
// WRITE both have side effects, so no plain shadow rule describes them.
// Semantics from the cpu_ctrl.rdl MUTEX and SEMA field descriptions (SPEC,
// not RTL):
//
//   reg MUTEX  `field ... mutex[0:0] = 0x1` -- "HW mutex. Reads will attempt
//              to acquire mutex, 1 on success. If the mutex is already
//              acquired, the read will return 0. To release the mutex, write
//              any value to the register." MUTEX[4]: four independent locks.
//   reg SEMA   `field ... sema[15:0] = 0x0` -- "16-bit semaphore value to
//              inc/dec. Writing to this register will inc/dec the semaphore
//              value. The written value is treated as a signed number using
//              2s compliment." SEMA[4].
//
// Both registers are declared regwidth/accesswidth 64, but each live field
// sits inside the low 32 bits, so the bench's 4-byte CSR access covers the
// whole field under test; bits above the field carry no RDL field and are
// masked out of every compare rather than being given an invented expectation.
// ---------------------------------------------------------------------------

localparam int unsigned SmcMutexCount = int'(smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_MUTEX_NUM);
localparam int unsigned SmcSemaCount = int'(smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_SEMA_NUM);

// Field masks and the mutex's two legal read values, symbol-sourced.
localparam bit [31:0] SmcMutexMask = 32'(CPU_CTRL_MUTEX_MUTEX_MASK);
localparam bit [31:0] SmcSemaMask = 32'(CPU_CTRL_SEMA_SEMA_MASK);
// SmcMutexFree is the field's reset value. SmcMutexTaken is the value
// cpu_ctrl.rdl gives in prose for a read of an already-acquired mutex ("the
// read will return 0"); no generated symbol carries it.
localparam bit [31:0] SmcMutexFree = 32'(CPU_CTRL_MUTEX_REG_DEFAULT) & SmcMutexMask;
localparam bit [31:0] SmcMutexTaken = 32'h0;  // cpu_ctrl.rdl MUTEX, quoted above

function automatic bit [63:0] smc_mutex_addr(int unsigned idx);
  return 64'(smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_MUTEX_BASE_ADDR(idx));
endfunction

function automatic bit [63:0] smc_sema_addr(int unsigned idx);
  return 64'(smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_SEMA_BASE_ADDR(idx));
endfunction

// Locate `word_addr` among the mutexes and semaphores; `is_sema` tells the
// two register kinds apart and `idx` is the instance.
function automatic bit smc_mutex_sema_lookup(bit [63:0] word_addr, output int unsigned idx,
                                             output bit is_sema);
  for (int unsigned i = 0; i < SmcMutexCount; i++) begin
    if (smc_csr_word_addr(smc_mutex_addr(i)) == word_addr) begin
      idx     = i;
      is_sema = 1'b0;
      return 1'b1;
    end
  end
  for (int unsigned i = 0; i < SmcSemaCount; i++) begin
    if (smc_csr_word_addr(smc_sema_addr(i)) == word_addr) begin
      idx     = i;
      is_sema = 1'b1;
      return 1'b1;
    end
  end
  return 1'b0;
endfunction

function automatic bit smc_is_mutex_sema_access(ocah_axi_item t, output int unsigned idx,
                                                output bit is_sema);
  if (!smc_mutex_sema_lookup(smc_csr_word_addr(t.address), idx, is_sema)) return 1'b0;
  return t.is_ok() && t.data_words.size() == 1 && t.beat_count() == 1;
endfunction

// ---------------------------------------------------------------------------
// spm_mem: the SPM scratchpad window reached over SEP_IN as 64-bit words.
// ---------------------------------------------------------------------------
localparam bit [63:0] SmcSpmBase = smc_top_addrmap_pkg::SMC_TOP_SPM_MEMORY_BASE_ADDR;
localparam bit [63:0] SmcSpmSize = smc_top_addrmap_pkg::SMC_TOP_SPM_MEMORY_SIZE;

// 64-bit word address (8-byte aligned) of a bus address.
function automatic bit [63:0] smc_mem_word_addr(bit [63:0] addr);
  return addr & ~64'(SmcMemBytes - 1);
endfunction

function automatic bit smc_is_spm_addr(bit [63:0] addr);
  return (addr >= SmcSpmBase) && (addr < SmcSpmBase + SmcSpmSize);
endfunction

// An SPM access the spm_mem feature predicts and compares: an OKAY
// single-beat transfer inside the window.
function automatic bit smc_is_spm_mem_access(ocah_axi_item t);
  if (!smc_is_spm_addr(t.address)) return 1'b0;
  return t.is_ok() && t.data_words.size() == 1 && t.beat_count() == 1;
endfunction

// A single-beat write or aligned 32-bit read of a defined watchdog register.
// No response filter: every such access reaches the comparison, and only an
// OKAY write updates the reference model.
function automatic bit smc_is_wdt_csr_access(ocah_axi_item t, output int unsigned core,
                                             output int unsigned offset);
  bit [63:0] base;
  if (t.expected_beats != 1 || t.beat_count() != 1 || t.data_words.size() != 1) return 1'b0;
  if (t.direction == OCAH_AXI_DIR_READ && (t.size != SmcCsrSize || t.address[1:0] != 0))
    return 1'b0;
  for (int unsigned i = 0; i < SmcWdtCores; i++) begin
    base = smc_wdt_addr(i, WDT_CTRL);
    if (t.address >= base && t.address < base + SmcWdtBytes) begin
      core = i;
      offset = int'(smc_csr_word_addr(t.address) - base);
      case (offset)
        'h0, 'h8, 'hc, 'h10, 'h18, 'h1c, 'h20: return 1'b1;
        default: return 1'b0;
      endcase
    end
  end
  return 1'b0;
endfunction

function automatic bit [31:0] smc_wdt_csr_mask(int unsigned offset);
  case (offset)
    'h0: return ~32'(WDT_CTRL_WDOGIP0_MASK);
    'h1c, 'h20: return 32'hFFFF_FFFF;
    default: return 32'h0;
  endcase
endfunction
