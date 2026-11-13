// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC filter functional coverage: the AXI-Lite protection filter guarding a
// GPIO wrap, the JTAG2AXI manager's path through the alias remap and the
// inbound fabric filter, the filter-rule covergroups smc_infilt_rule_cg and
// smc_outfilt_rule_cg of SMC_FCOV.adoc, and the alias-remap covergroup
// smc_alias_remap_cg.
//
// The protection filter compares the request's prot against a programmed
// requirement, so the two points are "equal" and "one bit apart" -- the
// second is the nearest miss, which a coarse mismatch point would hide.
//
// The filter-rule groups need the programmed entries, which no bench net
// carries: a shadow of both filter tables is kept from the SEP_IN writes that
// complete OKAY at the entry registers, and the match rule of the axi_filter
// chapter (Match, Then Permit) is applied to each probe. The inbound deciding
// entry is the lowest set bit of the hit vector the DUT exposes and is
// cross-checked against the shadow; the outbound deciding entry comes from the
// shadow alone. A probe on which the DUT and the shadow disagree, on the entry
// or on the verdict, samples no cell.
//
// The alias-remap group keeps a shadow of the eight remap regions the same
// way and grades each JTAG probe against it: the region and the position of
// the address against the region bounds come from the shadow, the DUT's remap
// index and the SYS_OUT address and AxCACHE are cross-checked against it, and
// a probe on which they disagree samples no cell.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal or a member of the u_output_axi_if instance.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_filt_fcov (
  input wire clk_smc_i,
  input wire rst_cold_ni,

  // GPIO wrap 0 AXI-Lite protection filter.
  input wire gpio_awvalid_i,
  input wire gpio_arvalid_i,
  input wire [2:0] gpio_awprot_i,
  input wire [2:0] gpio_arprot_i,
  input wire [2:0] gpio_awprot_req_i,
  input wire [2:0] gpio_arprot_req_i,
  input wire gpio_wr_filter_en_i,
  input wire gpio_rd_filter_en_i,

  // JTAG2AXI manager activity, its alias-remap hit debug and the inbound
  // fabric filter decision.
  input wire jtag_awvalid_i,
  input wire jtag_arvalid_i,
  input wire [2:0] remap_jtag_aw_hit_i,
  input wire [2:0] remap_jtag_ar_hit_i,
  input wire [15:0] inb_write_hit_i,
  input wire [15:0] inb_read_hit_i,
  input wire inb_isolate_write_i,
  input wire inb_isolate_read_i,

  // SEP_IN write channels, for the filter entries as written.
  input wire sep_awvalid_i,
  input wire sep_awready_i,
  input wire [55:0] sep_awaddr_i,
  input wire sep_wvalid_i,
  input wire sep_wready_i,
  input wire sep_wlast_i,
  input wire [63:0] sep_wdata_i,
  input wire [7:0] sep_wstrb_i,
  input wire sep_bvalid_i,
  input wire sep_bready_i,
  input wire [1:0] sep_bresp_i,

  // SYS_IN address phases and completions, the inbound probes.
  input wire sys_awvalid_i,
  input wire sys_awready_i,
  input wire [55:0] sys_awaddr_i,
  input wire [7:0] sys_awlen_i,
  input wire [2:0] sys_awprot_i,
  input wire [11:0] sys_awuser_i,
  input wire sys_arvalid_i,
  input wire sys_arready_i,
  input wire [55:0] sys_araddr_i,
  input wire [7:0] sys_arlen_i,
  input wire [2:0] sys_arprot_i,
  input wire [11:0] sys_aruser_i,
  input wire sys_bvalid_i,
  input wire sys_bready_i,
  input wire [1:0] sys_bresp_i,
  input wire sys_rvalid_i,
  input wire sys_rready_i,
  input wire sys_rlast_i,
  input wire [1:0] sys_rresp_i,

  // JTAG address phases and completions, the outbound probes.
  input wire jtag_awready_i,
  input wire [55:0] jtag_awaddr_i,
  input wire [7:0] jtag_awlen_i,
  input wire [2:0] jtag_awprot_i,
  input wire [11:0] jtag_awuser_i,
  input wire jtag_arready_i,
  input wire [55:0] jtag_araddr_i,
  input wire [7:0] jtag_arlen_i,
  input wire [2:0] jtag_arprot_i,
  input wire [11:0] jtag_aruser_i,
  input wire [3:0] jtag_awcache_i,
  input wire [3:0] jtag_arcache_i,
  input wire jtag_bvalid_i,
  input wire jtag_bready_i,
  input wire [1:0] jtag_bresp_i,
  input wire jtag_rvalid_i,
  input wire jtag_rready_i,
  input wire jtag_rlast_i,
  input wire [1:0] jtag_rresp_i,

  // SEP_IN read channels, for the region registers as read back.
  input wire sep_arvalid_i,
  input wire sep_arready_i,
  input wire [55:0] sep_araddr_i,
  input wire sep_rvalid_i,
  input wire sep_rready_i,
  input wire sep_rlast_i,
  input wire [1:0] sep_rresp_i,

  // SYS_OUT address handshakes with their address, length, prot and cache.
  input wire out_awvalid_i,
  input wire out_awready_i,
  input wire [55:0] out_awaddr_i,
  input wire [7:0] out_awlen_i,
  input wire [2:0] out_awprot_i,
  input wire [3:0] out_awcache_i,
  input wire out_arvalid_i,
  input wire out_arready_i,
  input wire [55:0] out_araddr_i,
  input wire [7:0] out_arlen_i,
  input wire [2:0] out_arprot_i,
  input wire [3:0] out_arcache_i,

  // Graded-window gate (tb_fcov_gate), driven by the owning leaf.
  input wire fcov_gate_i
);

  import smc_top_addrmap_pkg::SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_TOTAL_SIZE;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_TOTAL_SIZE;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE;
  import filter_ctrl_addrmap_pkg::FILTER_CTRL_FILTER_CONFIG_BASE_ADDR;
  import filter_ctrl_addrmap_pkg::FILTER_CTRL_START_ADDR_BASE_ADDR;
  import filter_ctrl_addrmap_pkg::FILTER_CTRL_END_ADDR_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_WRAP_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_TOTAL_SIZE;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_STRIDE;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR;
  // The FILTER_CONFIG field positions and the reset words of filter_ctrl.rdl.
  `include "filter_ctrl_reg.svh"
  // The REGION_ATTRS field positions and the reset words of alias_remap.rdl.
  `include "alias_remap_reg.svh"

  wire in_reset = (rst_cold_ni !== 1'b1);

  // ------------------------------------------------------------------
  // Protection filter. Both points require the corresponding filter enable,
  // because with the enable clear the comparison is bypassed and the prot
  // value carries no meaning.
  // ------------------------------------------------------------------
  wire [2:0] awprot_diff = gpio_awprot_i ^ gpio_awprot_req_i;
  wire [2:0] arprot_diff = gpio_arprot_i ^ gpio_arprot_req_i;

  logic [1:0] awprot_diff_ones, arprot_diff_ones;
  always_comb begin
    awprot_diff_ones = '0;
    arprot_diff_ones = '0;
    for (int unsigned b = 0; b < 3; b++) begin
      if (awprot_diff[b] === 1'b1) awprot_diff_ones = awprot_diff_ones + 2'd1;
      if (arprot_diff[b] === 1'b1) arprot_diff_ones = arprot_diff_ones + 2'd1;
    end
  end

  wire aw_filtered = (gpio_awvalid_i === 1'b1) && (gpio_wr_filter_en_i === 1'b1)
      && (^gpio_awprot_i !== 1'bx) && (^gpio_awprot_req_i !== 1'bx);
  wire ar_filtered = (gpio_arvalid_i === 1'b1) && (gpio_rd_filter_en_i === 1'b1)
      && (^gpio_arprot_i !== 1'bx) && (^gpio_arprot_req_i !== 1'bx);

  wire awprot_exact_match_e = aw_filtered && (awprot_diff_ones == 2'd0);
  wire awprot_one_bit_off_e = aw_filtered && (awprot_diff_ones == 2'd1);
  wire arprot_exact_match_e = ar_filtered && (arprot_diff_ones == 2'd0);
  wire arprot_one_bit_off_e = ar_filtered && (arprot_diff_ones == 2'd1);
  `OCAH_FCOV_COVER(c_awprot_exact_match, awprot_exact_match_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_awprot_one_bit_off, awprot_one_bit_off_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_arprot_exact_match, arprot_exact_match_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_arprot_one_bit_off, arprot_one_bit_off_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // JTAG2AXI through the alias remap and the inbound filter. The remap hit
  // debug is per-manager, so it attributes the remap to the JTAG path; the
  // filter decision is shared, so its point is qualified by the JTAG
  // manager being the one presenting a request.
  // ------------------------------------------------------------------
  wire jtag_active = (jtag_awvalid_i === 1'b1) || (jtag_arvalid_i === 1'b1);
  wire jtag_remap_hit = (remap_jtag_aw_hit_i !== 3'd0) || (remap_jtag_ar_hit_i !== 3'd0);
  wire jtag2axi_remapped_e = jtag_active && jtag_remap_hit
      && (^remap_jtag_aw_hit_i !== 1'bx) && (^remap_jtag_ar_hit_i !== 1'bx);

  wire filter_decided = (inb_write_hit_i !== 16'd0) || (inb_read_hit_i !== 16'd0)
      || (inb_isolate_write_i === 1'b1) || (inb_isolate_read_i === 1'b1);
  wire jtag2axi_filtered_e = jtag_active && filter_decided;
  `OCAH_FCOV_COVER(c_jtag2axi_remapped, jtag2axi_remapped_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_jtag2axi_filtered, jtag2axi_filtered_e, clk_smc_i, in_reset)

  // The filter blocking and admitting, kept as their own points so a run in
  // which nothing was ever blocked is visible rather than implied.
  wire inbound_blocked_e = (inb_isolate_write_i === 1'b1) || (inb_isolate_read_i === 1'b1);
  wire inbound_admitted_e = !inbound_blocked_e
      && ((inb_write_hit_i !== 16'd0) || (inb_read_hit_i !== 16'd0));
  `OCAH_FCOV_COVER(c_inbound_filter_blocked, inbound_blocked_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_inbound_filter_admitted, inbound_admitted_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Covergroup: the prot value against the programmed requirement, which the
  // flat list can only bucket by hamming distance.
  // ------------------------------------------------------------------
  covergroup cg_prot_filter with function sample (
      logic [2:0] prot, logic [2:0] requirement, logic enabled
  );
    option.per_instance = 1;
    cp_prot: coverpoint prot;
    cp_req: coverpoint requirement;
    cp_en: coverpoint enabled;
    x_prot_req: cross cp_prot, cp_req;
  endgroup

  cg_prot_filter u_cg_awprot = new();
  cg_prot_filter u_cg_arprot = new();

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) begin
      if (gpio_awvalid_i) u_cg_awprot.sample(gpio_awprot_i, gpio_awprot_req_i, gpio_wr_filter_en_i);
      if (gpio_arvalid_i) u_cg_arprot.sample(gpio_arprot_i, gpio_arprot_req_i, gpio_rd_filter_en_i);
    end
  end

  // ------------------------------------------------------------------
  // Shadow filter tables (SMC_FCOV.adoc, smc_infilt_rule_cg and
  // smc_outfilt_rule_cg): the 16 inbound and 16 outbound entries as the last
  // SEP_IN write that completed OKAY at each entry register left them, from
  // the single 64-bit beat with every strobe set. One SEP_IN write is
  // outstanding at a time. A write with a strobe clear changes no shadow
  // entry. The shadow follows the cold reset only.
  // ------------------------------------------------------------------
  localparam int unsigned NumEntries = 16;
  localparam logic [55:0] InbBase = 56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_BASE_ADDR);
  localparam logic [55:0] InbSpan =
      56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_TOTAL_SIZE);
  localparam logic [55:0] OutbBase = 56'(SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_BASE_ADDR);
  localparam logic [55:0] OutbSpan =
      56'(SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_TOTAL_SIZE);
  localparam logic [55:0] InbStride = 56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE);
  localparam logic [55:0] OutbStride =
      56'(SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE);
  // Register offsets inside an entry.
  localparam logic [55:0] OffConfig = 56'(FILTER_CTRL_FILTER_CONFIG_BASE_ADDR);
  localparam logic [55:0] OffStart = 56'(FILTER_CTRL_START_ADDR_BASE_ADDR);
  localparam logic [55:0] OffEnd = 56'(FILTER_CTRL_END_ADDR_BASE_ADDR);
  typedef struct packed {
    logic en;
    logic ns;
    logic burst;
    logic rd;
    logic wr;
    logic [3:0] src;
    logic [55:0] start;
    logic [55:0] stop;
  } entry_t;
  typedef entry_t [NumEntries-1:0] table_t;

  // The shadowed fields of the FILTER_CONFIG reset word.
  localparam logic [63:0] ConfigReset = 64'(FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT);
  localparam entry_t EntryReset = '{
      en: ConfigReset[FILTER_CTRL_FILTER_CONFIG_ENTRY_ENABLED_SHIFT],
      ns: ConfigReset[FILTER_CTRL_FILTER_CONFIG_ALLOW_NS_SHIFT],
      burst: ConfigReset[FILTER_CTRL_FILTER_CONFIG_ALLOW_BURST_SHIFT],
      rd: ConfigReset[FILTER_CTRL_FILTER_CONFIG_READ_ALLOWED_SHIFT],
      wr: ConfigReset[FILTER_CTRL_FILTER_CONFIG_WRITE_ALLOWED_SHIFT],
      src: ConfigReset[FILTER_CTRL_FILTER_CONFIG_SRC_ID_SHIFT+:4],
      start: 56'(FILTER_CTRL_START_ADDR_REG_DEFAULT),
      stop: 56'(FILTER_CTRL_END_ADDR_REG_DEFAULT)
  };

  function automatic entry_t entry_from_config(input entry_t e, input logic [63:0] word);
    entry_from_config = e;
    entry_from_config.rd = word[FILTER_CTRL_FILTER_CONFIG_READ_ALLOWED_SHIFT];
    entry_from_config.wr = word[FILTER_CTRL_FILTER_CONFIG_WRITE_ALLOWED_SHIFT];
    entry_from_config.en = word[FILTER_CTRL_FILTER_CONFIG_ENTRY_ENABLED_SHIFT];
    entry_from_config.ns = word[FILTER_CTRL_FILTER_CONFIG_ALLOW_NS_SHIFT];
    entry_from_config.src = word[FILTER_CTRL_FILTER_CONFIG_SRC_ID_SHIFT+:4];
    entry_from_config.burst = word[FILTER_CTRL_FILTER_CONFIG_ALLOW_BURST_SHIFT];
  endfunction

  wire sep_aw_acc = (sep_awvalid_i === 1'b1) && (sep_awready_i === 1'b1);
  wire sep_w_last_acc = (sep_wvalid_i === 1'b1) && (sep_wready_i === 1'b1)
      && (sep_wlast_i === 1'b1);
  wire sep_b_okay = (sep_bvalid_i === 1'b1) && (sep_bready_i === 1'b1)
      && (sep_bresp_i === 2'b00);

  logic [55:0] sep_waddr_q;
  logic [63:0] sep_wdata_q;
  logic sep_wfull_q;
  table_t inb_q, outb_q;

  wire [55:0] inb_off = sep_waddr_q - InbBase;
  wire [55:0] outb_off = sep_waddr_q - OutbBase;
  wire inb_reg_w = sep_b_okay && sep_wfull_q && (inb_off < InbSpan);
  wire outb_reg_w = sep_b_okay && sep_wfull_q && (outb_off < OutbSpan);
  wire [3:0] inb_idx = 4'(inb_off / InbStride);
  wire [3:0] outb_idx = 4'(outb_off / OutbStride);
  wire [55:0] inb_reg_off = inb_off % InbStride;
  wire [55:0] outb_reg_off = outb_off % OutbStride;

  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      sep_waddr_q <= '0;
      sep_wdata_q <= '0;
      sep_wfull_q <= 1'b0;
      for (int unsigned i = 0; i < NumEntries; i++) begin
        inb_q[i] <= EntryReset;
        outb_q[i] <= EntryReset;
      end
    end else begin
      if (sep_aw_acc) sep_waddr_q <= sep_awaddr_i;
      if (sep_w_last_acc) begin
        sep_wdata_q <= sep_wdata_i;
        sep_wfull_q <= (sep_wstrb_i === 8'hFF);
      end
      if (inb_reg_w) begin
        case (inb_reg_off)
          OffConfig: inb_q[inb_idx] <= entry_from_config(inb_q[inb_idx], sep_wdata_q);
          OffStart: inb_q[inb_idx].start <= sep_wdata_q[55:0];
          OffEnd: inb_q[inb_idx].stop <= sep_wdata_q[55:0];
          default: ;
        endcase
      end
      if (outb_reg_w) begin
        case (outb_reg_off)
          OffConfig: outb_q[outb_idx] <= entry_from_config(outb_q[outb_idx], sep_wdata_q);
          OffStart: outb_q[outb_idx].start <= sep_wdata_q[55:0];
          OffEnd: outb_q[outb_idx].stop <= sep_wdata_q[55:0];
          default: ;
        endcase
      end
    end
  end

  // ------------------------------------------------------------------
  // The match rule (axi_filter index.adoc, Match, Then Permit): an entry
  // matches when it is enabled, the address lies in its range widened to the
  // granule (4 KiB with allow_burst set, 8 bytes with it clear), AxPROT[1]
  // equals allow_ns, the source ID equals src_id or src_id is 0, and
  // allow_burst is set or AxLEN is 0. The lowest matching entry decides by
  // its permission bit for the channel; no match answers the instance's
  // default. A term is graded on a probe when it alone keeps a lower entry,
  // whose permission bit answers the other way, from deciding the probe.
  // ------------------------------------------------------------------
  typedef struct packed {
    logic match;
    logic [3:0] idx;
    logic bit_set;
    logic verdict;
    logic higher_deny;
    logic term_range;
    logic term_ns;
    logic term_src;
    logic term_burst;
  } decode_t;

  localparam logic [1:0] TermRange = 2'd0;
  localparam logic [1:0] TermNs = 2'd1;
  localparam logic [1:0] TermSrc = 2'd2;
  localparam logic [1:0] TermBurst = 2'd3;

  function automatic decode_t decode(input table_t tbl, input logic [55:0] addr, input logic ns,
                                     input logic [3:0] src, input logic [7:0] len,
                                     input logic write, input logic block_default);
    logic [55:0] lo, hi;
    logic f_range, f_ns, f_src, f_burst, f_en, e_bit;
    logic [NumEntries-1:0] hit, one_range, one_ns, one_src, one_burst, bits;
    decode = '0;
    for (int unsigned i = 0; i < NumEntries; i++) begin
      lo = tbl[i].burst ? {tbl[i].start[55:12], 12'h000} : {tbl[i].start[55:3], 3'h0};
      hi = tbl[i].burst ? {tbl[i].stop[55:12], 12'hFFF} : {tbl[i].stop[55:3], 3'h7};
      f_en = !tbl[i].en;
      f_range = !((addr >= lo) && (addr <= hi));
      f_ns = (ns != tbl[i].ns);
      f_src = (tbl[i].src != 4'd0) && (src != tbl[i].src);
      f_burst = !tbl[i].burst && (len != 8'd0);
      e_bit = write ? tbl[i].wr : tbl[i].rd;
      hit[i] = !(f_en || f_range || f_ns || f_src || f_burst);
      bits[i] = e_bit;
      one_range[i] = f_range && !(f_en || f_ns || f_src || f_burst);
      one_ns[i] = f_ns && !(f_en || f_range || f_src || f_burst);
      one_src[i] = f_src && !(f_en || f_range || f_ns || f_burst);
      one_burst[i] = f_burst && !(f_en || f_range || f_ns || f_src);
    end
    for (int unsigned i = 0; i < NumEntries; i++) begin
      if (hit[i] && !decode.match) begin
        decode.match = 1'b1;
        decode.idx = 4'(i);
        decode.bit_set = bits[i];
      end
    end
    decode.verdict = decode.match ? decode.bit_set : !block_default;
    for (int unsigned i = 0; i < NumEntries; i++) begin
      if (decode.match && decode.bit_set && (4'(i) > decode.idx) && hit[i] && !bits[i]) begin
        decode.higher_deny = 1'b1;
      end
      if ((!decode.match || (4'(i) < decode.idx)) && (bits[i] != decode.verdict)) begin
        decode.term_range |= one_range[i];
        decode.term_ns |= one_ns[i];
        decode.term_src |= one_src[i];
        decode.term_burst |= one_burst[i];
      end
    end
  endfunction

  function automatic logic [4:0] lowest_set(input logic [15:0] v);
    lowest_set = 5'd16;
    for (int i = 15; i >= 0; i--) begin
      if (v[i]) lowest_set = 5'(i);
    end
  endfunction

  // AxLEN buckets of the inbound probe row: 0, 1, 3, 7, 15; another value
  // maps to code 7, which no bin lists.
  function automatic logic [2:0] len_code(input logic [7:0] len);
    case (len)
      8'd0: return 3'd0;
      8'd1: return 3'd1;
      8'd3: return 3'd2;
      8'd7: return 3'd3;
      8'd15: return 3'd4;
      default: return 3'd7;
    endcase
  endfunction

  // Owner-specific qualifiers beside the gate: the inbound group samples
  // while an inbound entry at an index of 2 to 15 has been written since the
  // gate rose and one is enabled in the shadow, and the probe's AxUSER above
  // [3:0] is 0 (a repeat with a source ID above AxUSER[3:0] presents its
  // probe's cell again; the owner grades it against the probe); the outbound
  // group samples while an outbound entry has been written since the gate
  // rose. A write is a SEP_IN write that completed OKAY at an entry register
  // of that table; each written flag clears on every rise of the gate. The
  // one gate net opens every live group; an owner that programs its entries
  // before raising the gate, or programs none, counts nothing here.
  wire gate_on = (fcov_gate_i === 1'b1);
  logic gate_q;
  wire gate_rise = gate_on && !gate_q;
  wire inb_rule_w = inb_reg_w && (inb_idx >= 4'd2);
  logic inb_written_q, outb_written_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      gate_q <= 1'b0;
      inb_written_q <= 1'b0;
      outb_written_q <= 1'b0;
    end else begin
      gate_q <= gate_on;
      if (gate_rise) begin
        inb_written_q <= 1'b0;
        outb_written_q <= 1'b0;
      end else begin
        if (inb_rule_w) inb_written_q <= 1'b1;
        if (outb_reg_w) outb_written_q <= 1'b1;
      end
    end
  end
  logic inb_enabled;
  always_comb begin
    inb_enabled = 1'b0;
    for (int unsigned i = 2; i < NumEntries; i++) begin
      if (inb_q[i].en) inb_enabled = 1'b1;
    end
  end
  wire inb_live = inb_written_q && inb_enabled;
  wire outb_live = outb_written_q;

  // ------------------------------------------------------------------
  // Inbound probes on SYS_IN. One probe is outstanding per channel. At the
  // AW or AR handshake the shadow decode of the probe is kept; one edge
  // later the hit vector is read, when the request has crossed the port's
  // axi_cut and the filter presents its entry hits. The sample is the B or
  // R-last handshake that completes the probe, so the verdict is known. The
  // deciding entry is the lowest set bit of the hit vector; a probe counts
  // only when it equals the shadow's lowest match and the response equals
  // the shadow's verdict.
  // ------------------------------------------------------------------
  typedef struct packed {
    logic pending;
    decode_t dec;
    logic ns;
    logic user_hi_zero;
    logic [7:0] len;
    logic [15:0] hit;
  } probe_t;

  wire sys_aw_acc = (sys_awvalid_i === 1'b1) && (sys_awready_i === 1'b1);
  wire sys_ar_acc = (sys_arvalid_i === 1'b1) && (sys_arready_i === 1'b1);
  wire sys_b_acc = (sys_bvalid_i === 1'b1) && (sys_bready_i === 1'b1);
  wire sys_r_last_acc = (sys_rvalid_i === 1'b1) && (sys_rready_i === 1'b1)
      && (sys_rlast_i === 1'b1);

  probe_t inb_wr_q, inb_rd_q;
  logic inb_wr_hit_e, inb_rd_hit_e;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      inb_wr_q <= '0;
      inb_rd_q <= '0;
      inb_wr_hit_e <= 1'b0;
      inb_rd_hit_e <= 1'b0;
    end else begin
      inb_wr_hit_e <= sys_aw_acc;
      inb_rd_hit_e <= sys_ar_acc;
      if (sys_aw_acc) begin
        inb_wr_q.pending <= 1'b1;
        inb_wr_q.dec <= decode(inb_q, sys_awaddr_i, sys_awprot_i[1], sys_awuser_i[3:0],
                               sys_awlen_i, 1'b1, 1'b1);
        inb_wr_q.ns <= sys_awprot_i[1];
        inb_wr_q.user_hi_zero <= (sys_awuser_i[11:4] == 8'd0);
        inb_wr_q.len <= sys_awlen_i;
      end else if (sys_b_acc) begin
        inb_wr_q.pending <= 1'b0;
      end
      if (inb_wr_hit_e) inb_wr_q.hit <= inb_write_hit_i;
      if (sys_ar_acc) begin
        inb_rd_q.pending <= 1'b1;
        inb_rd_q.dec <= decode(inb_q, sys_araddr_i, sys_arprot_i[1], sys_aruser_i[3:0],
                               sys_arlen_i, 1'b0, 1'b1);
        inb_rd_q.ns <= sys_arprot_i[1];
        inb_rd_q.user_hi_zero <= (sys_aruser_i[11:4] == 8'd0);
        inb_rd_q.len <= sys_arlen_i;
      end else if (sys_r_last_acc) begin
        inb_rd_q.pending <= 1'b0;
      end
      if (inb_rd_hit_e) inb_rd_q.hit <= inb_read_hit_i;
    end
  end

  wire inb_wr_done = sys_b_acc && inb_wr_q.pending;
  wire inb_rd_done = sys_r_last_acc && inb_rd_q.pending;
  wire inb_sample_e = gate_on && inb_live && (inb_wr_done || inb_rd_done);
  // A read and a write completing in the same cycle sample the write only,
  // and the deciding entry's terms are read from the live shadow at the
  // completing handshake; neither case arises under the owners' one
  // outstanding probe and one outstanding SEP_IN write.
  probe_t inb_p;
  assign inb_p = inb_wr_done ? inb_wr_q : inb_rd_q;
  wire [1:0] inb_resp = inb_wr_done ? sys_bresp_i : sys_rresp_i;
  wire inb_permit = (inb_resp === 2'b00);
  wire inb_deny = (inb_resp === 2'b11);
  wire [4:0] inb_hit_low = lowest_set(inb_p.hit);
  wire inb_entry_ok = inb_p.dec.match ? (inb_hit_low == {1'b0, inb_p.dec.idx})
                                      : (inb_hit_low == 5'd16);
  wire inb_verdict_ok = inb_p.dec.verdict ? inb_permit : inb_deny;
  wire inb_graded = inb_sample_e && inb_p.user_hi_zero && inb_entry_ok && inb_verdict_ok;
  wire inb_entry_src_wild = (inb_q[inb_p.dec.idx].src == 4'd0);
  wire inb_entry_ns = inb_q[inb_p.dec.idx].ns;
  wire inb_entry_burst = inb_q[inb_p.dec.idx].burst;
  wire [1:0] inb_kind = !inb_graded ? 2'd0 : inb_p.dec.match ? 2'd1 : 2'd2;
  wire inb_term_range_e = inb_graded && inb_p.dec.term_range;
  wire inb_term_ns_e = inb_graded && inb_p.dec.term_ns;
  wire inb_term_src_e = inb_graded && inb_p.dec.term_src;
  wire inb_term_burst_e = inb_graded && inb_p.dec.term_burst;
  // The twins of cp_deny_term in the user family.
  `OCAH_FCOV_COVER(c_infilt_deny_range, inb_term_range_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_infilt_deny_ns, inb_term_ns_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_infilt_deny_src_id, inb_term_src_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_infilt_deny_burst, inb_term_burst_e, clk_smc_i, in_reset)

  // The 16 {allow_ns, src_id class, allow_burst, verdict} bins of one
  // deciding entry; every bin leads with the decided kind, which only a
  // graded probe carries.
  `define SMC_INFILT_ENTRY_BINS(name, idx) \
      bins name``_ns0_wild_b0_deny = {{2'd1, idx, 1'b0, 1'b0, 1'b0, 1'b0}}; \
      bins name``_ns0_wild_b0_permit = {{2'd1, idx, 1'b0, 1'b0, 1'b0, 1'b1}}; \
      bins name``_ns0_wild_b1_deny = {{2'd1, idx, 1'b0, 1'b0, 1'b1, 1'b0}}; \
      bins name``_ns0_wild_b1_permit = {{2'd1, idx, 1'b0, 1'b0, 1'b1, 1'b1}}; \
      bins name``_ns0_equal_b0_deny = {{2'd1, idx, 1'b0, 1'b1, 1'b0, 1'b0}}; \
      bins name``_ns0_equal_b0_permit = {{2'd1, idx, 1'b0, 1'b1, 1'b0, 1'b1}}; \
      bins name``_ns0_equal_b1_deny = {{2'd1, idx, 1'b0, 1'b1, 1'b1, 1'b0}}; \
      bins name``_ns0_equal_b1_permit = {{2'd1, idx, 1'b0, 1'b1, 1'b1, 1'b1}}; \
      bins name``_ns1_wild_b0_deny = {{2'd1, idx, 1'b1, 1'b0, 1'b0, 1'b0}}; \
      bins name``_ns1_wild_b0_permit = {{2'd1, idx, 1'b1, 1'b0, 1'b0, 1'b1}}; \
      bins name``_ns1_wild_b1_deny = {{2'd1, idx, 1'b1, 1'b0, 1'b1, 1'b0}}; \
      bins name``_ns1_wild_b1_permit = {{2'd1, idx, 1'b1, 1'b0, 1'b1, 1'b1}}; \
      bins name``_ns1_equal_b0_deny = {{2'd1, idx, 1'b1, 1'b1, 1'b0, 1'b0}}; \
      bins name``_ns1_equal_b0_permit = {{2'd1, idx, 1'b1, 1'b1, 1'b0, 1'b1}}; \
      bins name``_ns1_equal_b1_deny = {{2'd1, idx, 1'b1, 1'b1, 1'b1, 1'b0}}; \
      bins name``_ns1_equal_b1_permit = {{2'd1, idx, 1'b1, 1'b1, 1'b1, 1'b1}};

  // The 10 {AxLEN, AxPROT[1]} bins of one channel of an admitted probe.
  `define SMC_INFILT_PROBE_BINS(name, ch) \
      bins name``_len0_ns0 = {{1'b1, ch, 3'd0, 1'b0}}; \
      bins name``_len0_ns1 = {{1'b1, ch, 3'd0, 1'b1}}; \
      bins name``_len1_ns0 = {{1'b1, ch, 3'd1, 1'b0}}; \
      bins name``_len1_ns1 = {{1'b1, ch, 3'd1, 1'b1}}; \
      bins name``_len3_ns0 = {{1'b1, ch, 3'd2, 1'b0}}; \
      bins name``_len3_ns1 = {{1'b1, ch, 3'd2, 1'b1}}; \
      bins name``_len7_ns0 = {{1'b1, ch, 3'd3, 1'b0}}; \
      bins name``_len7_ns1 = {{1'b1, ch, 3'd3, 1'b1}}; \
      bins name``_len15_ns0 = {{1'b1, ch, 3'd4, 1'b0}}; \
      bins name``_len15_ns1 = {{1'b1, ch, 3'd4, 1'b1}};

  // Each sample fills the coverpoints of its event and passes the others a
  // value no bin lists. Every cell of a row has a bin; no bin and no
  // ignore_bins share a value.
  covergroup smc_infilt_rule_cg with function sample (
      logic [1:0] kind,
      logic [3:0] entry,
      logic ns,
      logic src_equal,
      logic burst,
      logic verdict,
      logic admitted,
      logic write,
      logic [2:0] len,
      logic probe_ns,
      logic term_graded,
      logic [1:0] term
  );
    option.per_instance = 1;
    // {decided kind, entry, allow_ns, src_id class, allow_burst, verdict}:
    // 224 cells over entries 2 to 15, plus the no-match block. Entries 0
    // and 1 stay at their reset words under the owner's filter, so no bin
    // lists them.
    cp_rule: coverpoint {
      kind, entry, ns, src_equal, burst, verdict
    } {
      `SMC_INFILT_ENTRY_BINS(e2, 4'd2)
      `SMC_INFILT_ENTRY_BINS(e3, 4'd3)
      `SMC_INFILT_ENTRY_BINS(e4, 4'd4)
      `SMC_INFILT_ENTRY_BINS(e5, 4'd5)
      `SMC_INFILT_ENTRY_BINS(e6, 4'd6)
      `SMC_INFILT_ENTRY_BINS(e7, 4'd7)
      `SMC_INFILT_ENTRY_BINS(e8, 4'd8)
      `SMC_INFILT_ENTRY_BINS(e9, 4'd9)
      `SMC_INFILT_ENTRY_BINS(e10, 4'd10)
      `SMC_INFILT_ENTRY_BINS(e11, 4'd11)
      `SMC_INFILT_ENTRY_BINS(e12, 4'd12)
      `SMC_INFILT_ENTRY_BINS(e13, 4'd13)
      `SMC_INFILT_ENTRY_BINS(e14, 4'd14)
      `SMC_INFILT_ENTRY_BINS(e15, 4'd15)
      bins block = {{2'd2, 4'd0, 1'b0, 1'b0, 1'b0, 1'b0}};
    }
    // {admitted, channel, AxLEN bucket, AxPROT[1]}: 20 cells.
    cp_probe: coverpoint {
      admitted, write, len, probe_ns
    } {
      `SMC_INFILT_PROBE_BINS(rd, 1'b0)
      `SMC_INFILT_PROBE_BINS(wr, 1'b1)
    }
    // {graded, term}: the term that alone keeps a lower entry, whose
    // permission bit answers the other way, from deciding the probe; 4
    // single-event bins.
    cp_deny_term: coverpoint {
      term_graded, term
    } {
      bins range = {{1'b1, TermRange}};
      bins allow_ns = {{1'b1, TermNs}};
      bins src_id = {{1'b1, TermSrc}};
      bins allow_burst = {{1'b1, TermBurst}};
    }
  endgroup
  `undef SMC_INFILT_ENTRY_BINS
  `undef SMC_INFILT_PROBE_BINS

  smc_infilt_rule_cg u_cg_infilt_rule = new();

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset && inb_sample_e) begin
      u_cg_infilt_rule.sample(
          inb_kind, inb_p.dec.match ? inb_p.dec.idx : 4'd0, inb_p.dec.match && inb_entry_ns,
          inb_p.dec.match && !inb_entry_src_wild, inb_p.dec.match && inb_entry_burst,
          inb_p.dec.verdict, inb_graded && inb_permit, inb_wr_done, len_code(inb_p.len), inb_p.ns,
          1'b0, TermRange);
      if (inb_term_range_e) begin
        u_cg_infilt_rule.sample(2'd0, 4'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 3'd7, 1'b0, 1'b1,
                                TermRange);
      end
      if (inb_term_ns_e) begin
        u_cg_infilt_rule.sample(2'd0, 4'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 3'd7, 1'b0, 1'b1,
                                TermNs);
      end
      if (inb_term_src_e) begin
        u_cg_infilt_rule.sample(2'd0, 4'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 3'd7, 1'b0, 1'b1,
                                TermSrc);
      end
      if (inb_term_burst_e) begin
        u_cg_infilt_rule.sample(2'd0, 4'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 3'd7, 1'b0, 1'b1,
                                TermBurst);
      end
    end
  end

  // ------------------------------------------------------------------
  // Outbound probes on JTAG. One probe is outstanding per channel. The
  // shadow decode of the request at the JTAG AW or AR handshake gives the
  // lowest matching entry and the permission bit of the probe's direction;
  // the sample is the B or R-last handshake at the JTAG port, and the probe
  // counts only when the response is the function of the cell: DECERR for a
  // matching lowest entry with the bit clear, OKAY otherwise. The SYS_OUT
  // address handshake of an admitted probe carries the probe shape. The
  // src_id term is applied to the JTAG request's AxUSER[3:0] as a bench
  // reading: the output path assigns the outbound source ID (fabric.adoc,
  // Output Remapping), and the owner programs every src_id 0.
  // ------------------------------------------------------------------
  typedef struct packed {
    logic pending;
    decode_t dec;
  } out_probe_t;

  wire jtag_aw_acc = (jtag_awvalid_i === 1'b1) && (jtag_awready_i === 1'b1);
  wire jtag_ar_acc = (jtag_arvalid_i === 1'b1) && (jtag_arready_i === 1'b1);
  wire jtag_b_acc = (jtag_bvalid_i === 1'b1) && (jtag_bready_i === 1'b1);
  wire jtag_r_last_acc = (jtag_rvalid_i === 1'b1) && (jtag_rready_i === 1'b1)
      && (jtag_rlast_i === 1'b1);

  out_probe_t outb_wr_q, outb_rd_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      outb_wr_q <= '0;
      outb_rd_q <= '0;
    end else begin
      if (jtag_aw_acc) begin
        outb_wr_q.pending <= 1'b1;
        outb_wr_q.dec <= decode(outb_q, jtag_awaddr_i, jtag_awprot_i[1], jtag_awuser_i[3:0],
                                jtag_awlen_i, 1'b1, 1'b0);
      end else if (jtag_b_acc) begin
        outb_wr_q.pending <= 1'b0;
      end
      if (jtag_ar_acc) begin
        outb_rd_q.pending <= 1'b1;
        outb_rd_q.dec <= decode(outb_q, jtag_araddr_i, jtag_arprot_i[1], jtag_aruser_i[3:0],
                                jtag_arlen_i, 1'b0, 1'b0);
      end else if (jtag_r_last_acc) begin
        outb_rd_q.pending <= 1'b0;
      end
    end
  end

  wire outb_wr_done = jtag_b_acc && outb_wr_q.pending;
  wire outb_rd_done = jtag_r_last_acc && outb_rd_q.pending;
  wire outb_sample_e = gate_on && outb_live && (outb_wr_done || outb_rd_done);
  // As for the inbound probes: a read and a write completing in the same
  // cycle sample the write only, and the entry's terms come from the live
  // shadow at the completing handshake.
  out_probe_t outb_p;
  assign outb_p = outb_wr_done ? outb_wr_q : outb_rd_q;
  wire [1:0] outb_resp = outb_wr_done ? jtag_bresp_i : jtag_rresp_i;
  wire outb_verdict_ok = outb_p.dec.verdict ? (outb_resp === 2'b00) : (outb_resp === 2'b11);
  wire outb_graded = outb_sample_e && outb_verdict_ok;
  wire outb_rule_e = outb_graded && outb_p.dec.match;
  wire outb_entry_ns = outb_q[outb_p.dec.idx].ns;
  wire outb_entry_burst = outb_q[outb_p.dec.idx].burst;
  // Priority classes: the lowest matching entry denies; it allows while a
  // higher-numbered matching entry denies; no entry matches. A lowest allow
  // with no higher deny is a cp_rule cell alone.
  wire [1:0] outb_prio = !outb_graded ? 2'd0
                       : !outb_p.dec.match ? 2'd3
                       : !outb_p.dec.bit_set ? 2'd1
                       : outb_p.dec.higher_deny ? 2'd2 : 2'd0;

  wire out_aw_acc = (out_awvalid_i === 1'b1) && (out_awready_i === 1'b1);
  wire out_ar_acc = (out_arvalid_i === 1'b1) && (out_arready_i === 1'b1);
  wire out_probe_wr_e = gate_on && outb_live && out_aw_acc && outb_wr_q.pending;
  wire out_probe_rd_e = gate_on && outb_live && out_ar_acc && outb_rd_q.pending;
  wire out_probe_e = out_probe_wr_e || out_probe_rd_e;
  wire out_probe_len_nz = out_probe_wr_e ? (out_awlen_i != 8'd0) : (out_arlen_i != 8'd0);
  wire out_probe_ns = out_probe_wr_e ? out_awprot_i[1] : out_arprot_i[1];

  // The 16 {allow_ns, allow_burst, direction, permission bit} bins of one
  // entry; every bin leads with the graded flag.
  `define SMC_OUTFILT_ENTRY_BINS(name, idx) \
      bins name``_ns0_b0_rd_clear = {{1'b1, idx, 1'b0, 1'b0, 1'b0, 1'b0}}; \
      bins name``_ns0_b0_rd_set = {{1'b1, idx, 1'b0, 1'b0, 1'b0, 1'b1}}; \
      bins name``_ns0_b0_wr_clear = {{1'b1, idx, 1'b0, 1'b0, 1'b1, 1'b0}}; \
      bins name``_ns0_b0_wr_set = {{1'b1, idx, 1'b0, 1'b0, 1'b1, 1'b1}}; \
      bins name``_ns0_b1_rd_clear = {{1'b1, idx, 1'b0, 1'b1, 1'b0, 1'b0}}; \
      bins name``_ns0_b1_rd_set = {{1'b1, idx, 1'b0, 1'b1, 1'b0, 1'b1}}; \
      bins name``_ns0_b1_wr_clear = {{1'b1, idx, 1'b0, 1'b1, 1'b1, 1'b0}}; \
      bins name``_ns0_b1_wr_set = {{1'b1, idx, 1'b0, 1'b1, 1'b1, 1'b1}}; \
      bins name``_ns1_b0_rd_clear = {{1'b1, idx, 1'b1, 1'b0, 1'b0, 1'b0}}; \
      bins name``_ns1_b0_rd_set = {{1'b1, idx, 1'b1, 1'b0, 1'b0, 1'b1}}; \
      bins name``_ns1_b0_wr_clear = {{1'b1, idx, 1'b1, 1'b0, 1'b1, 1'b0}}; \
      bins name``_ns1_b0_wr_set = {{1'b1, idx, 1'b1, 1'b0, 1'b1, 1'b1}}; \
      bins name``_ns1_b1_rd_clear = {{1'b1, idx, 1'b1, 1'b1, 1'b0, 1'b0}}; \
      bins name``_ns1_b1_rd_set = {{1'b1, idx, 1'b1, 1'b1, 1'b0, 1'b1}}; \
      bins name``_ns1_b1_wr_clear = {{1'b1, idx, 1'b1, 1'b1, 1'b1, 1'b0}}; \
      bins name``_ns1_b1_wr_set = {{1'b1, idx, 1'b1, 1'b1, 1'b1, 1'b1}};

  covergroup smc_outfilt_rule_cg with function sample (
      logic rule_graded,
      logic [3:0] entry,
      logic ns,
      logic burst,
      logic write,
      logic bit_set,
      logic [1:0] prio,
      logic probe,
      logic len_nz,
      logic probe_ns
  );
    option.per_instance = 1;
    // {graded, entry, allow_ns, allow_burst, direction, permission bit}: 256
    // cells.
    cp_rule: coverpoint {
      rule_graded, entry, ns, burst, write, bit_set
    } {
      `SMC_OUTFILT_ENTRY_BINS(e0, 4'd0)
      `SMC_OUTFILT_ENTRY_BINS(e1, 4'd1)
      `SMC_OUTFILT_ENTRY_BINS(e2, 4'd2)
      `SMC_OUTFILT_ENTRY_BINS(e3, 4'd3)
      `SMC_OUTFILT_ENTRY_BINS(e4, 4'd4)
      `SMC_OUTFILT_ENTRY_BINS(e5, 4'd5)
      `SMC_OUTFILT_ENTRY_BINS(e6, 4'd6)
      `SMC_OUTFILT_ENTRY_BINS(e7, 4'd7)
      `SMC_OUTFILT_ENTRY_BINS(e8, 4'd8)
      `SMC_OUTFILT_ENTRY_BINS(e9, 4'd9)
      `SMC_OUTFILT_ENTRY_BINS(e10, 4'd10)
      `SMC_OUTFILT_ENTRY_BINS(e11, 4'd11)
      `SMC_OUTFILT_ENTRY_BINS(e12, 4'd12)
      `SMC_OUTFILT_ENTRY_BINS(e13, 4'd13)
      `SMC_OUTFILT_ENTRY_BINS(e14, 4'd14)
      `SMC_OUTFILT_ENTRY_BINS(e15, 4'd15)
    }
    // Priority: 3 bins.
    cp_priority: coverpoint prio {
      bins lowest_deny = {2'd1}; bins lowest_allow_higher_deny = {2'd2}; bins no_match = {2'd3};
    }
    // {probe, AxLEN non-zero, AxPROT[1]} at the SYS_OUT handshake of an
    // admitted probe: 4 cells.
    cp_probe: coverpoint {
      probe, len_nz, probe_ns
    } {
      bins len0_ns0 = {3'b1_0_0};
      bins len0_ns1 = {3'b1_0_1};
      bins lenz_ns0 = {3'b1_1_0};
      bins lenz_ns1 = {3'b1_1_1};
    }
  endgroup
  `undef SMC_OUTFILT_ENTRY_BINS

  smc_outfilt_rule_cg u_cg_outfilt_rule = new();

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) begin
      if (outb_sample_e) begin
        u_cg_outfilt_rule.sample(outb_rule_e, outb_rule_e ? outb_p.dec.idx : 4'd0,
                                 outb_rule_e && outb_entry_ns, outb_rule_e && outb_entry_burst,
                                 outb_wr_done, outb_rule_e && outb_p.dec.bit_set, outb_prio, 1'b0,
                                 1'b0, 1'b0);
      end
      if (out_probe_e) begin
        u_cg_outfilt_rule.sample(1'b0, 4'd0, 1'b0, 1'b0, 1'b0, 1'b0, 2'd0, 1'b1, out_probe_len_nz,
                                 out_probe_ns);
      end
    end
  end

  // ------------------------------------------------------------------
  // smc_alias_remap_cg (SMC_FCOV.adoc): the JTAG probes of the alias remap
  // against a shadow of the eight regions, kept from the SEP_IN writes that
  // complete OKAY at REGION_START, REGION_END and REGION_ATTRS with every
  // strobe set (the register is the whole beat; one SEP_IN write is
  // outstanding at a time). A region contains the addresses from its start
  // up to, not including, its end while valid is set; the lowest-numbered
  // region that contains the address applies, adds its offset to bits
  // [55:12] modulo 2^44 and replaces AxCACHE by cacheable; a miss passes the
  // pair unchanged (fabric.adoc, Alias Remapping; alias_remap.rdl). The
  // position of a probe is read against the region it hits (first byte of
  // the start page, last byte of the last page, interior) or, on a miss,
  // against the valid region whose edge it sits on (last byte of the page
  // before the start page, first byte of the end page).
  // ------------------------------------------------------------------
  localparam int unsigned NumRegions = 8;
  localparam logic [55:0] AliasBase = 56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_BASE_ADDR);
  localparam logic [55:0] AliasSpan = 56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_TOTAL_SIZE);
  localparam logic [55:0] AliasStride = 56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_STRIDE);
  // Register offsets inside a region, from the register addresses of region 0.
  localparam logic [55:0] OffRegionStart =
      56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR(
      0
  )) - AliasBase;
  localparam logic [55:0] OffRegionEnd =
      56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR(
      0
  )) - AliasBase;
  localparam logic [55:0] OffRegionAttrs =
      56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR(
      0
  )) - AliasBase;
  typedef struct packed {
    logic valid;
    logic [3:0] cache;
    logic [43:0] offset;
    logic [55:0] start;
    logic [55:0] stop;
  } region_t;
  typedef region_t [NumRegions-1:0] regions_t;

  // start_addr, end_addr and offset are the [55:12] fields of their words.
  function automatic logic [55:0] page_bound(input logic [63:0] word);
    return {word[55:12], 12'h000};
  endfunction

  localparam logic [63:0] StartReset = 64'(REMAP_REGION_REGION_START_REG_DEFAULT);
  localparam logic [63:0] EndReset = 64'(REMAP_REGION_REGION_END_REG_DEFAULT);
  localparam logic [63:0] AttrsReset = 64'(REMAP_REGION_REGION_ATTRS_REG_DEFAULT);
  localparam region_t RegionReset = '{
      valid: AttrsReset[REMAP_REGION_REGION_ATTRS_VALID_SHIFT],
      cache: AttrsReset[REMAP_REGION_REGION_ATTRS_CACHEABLE_SHIFT+:4],
      offset: AttrsReset[REMAP_REGION_REGION_ATTRS_OFFSET_SHIFT+:44],
      start: {StartReset[55:12], 12'h000},
      stop: {EndReset[55:12], 12'h000}
  };

  function automatic region_t region_from_attrs(input region_t r, input logic [63:0] word);
    region_from_attrs = r;
    region_from_attrs.valid = word[REMAP_REGION_REGION_ATTRS_VALID_SHIFT];
    region_from_attrs.cache = word[REMAP_REGION_REGION_ATTRS_CACHEABLE_SHIFT+:4];
    region_from_attrs.offset = word[REMAP_REGION_REGION_ATTRS_OFFSET_SHIFT+:44];
  endfunction

  wire [55:0] alias_off = sep_waddr_q - AliasBase;
  wire alias_reg_w = sep_b_okay && sep_wfull_q && (alias_off < AliasSpan);
  wire [2:0] alias_idx = 3'(alias_off / AliasStride);
  wire [55:0] alias_reg_off = alias_off % AliasStride;
  regions_t regions_q;

  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      for (int unsigned i = 0; i < NumRegions; i++) regions_q[i] <= RegionReset;
    end else if (alias_reg_w) begin
      case (alias_reg_off)
        OffRegionStart: regions_q[alias_idx].start <= page_bound(sep_wdata_q);
        OffRegionEnd: regions_q[alias_idx].stop <= page_bound(sep_wdata_q);
        OffRegionAttrs: regions_q[alias_idx] <= region_from_attrs(regions_q[alias_idx], sep_wdata_q);
        default: ;
      endcase
    end
  end

  // A region register read back over SEP_IN (one read outstanding at a time).
  wire sep_ar_acc = (sep_arvalid_i === 1'b1) && (sep_arready_i === 1'b1);
  wire sep_r_last_okay = (sep_rvalid_i === 1'b1) && (sep_rready_i === 1'b1)
      && (sep_rlast_i === 1'b1) && (sep_rresp_i === 2'b00);
  logic [55:0] sep_raddr_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) sep_raddr_q <= '0;
    else if (sep_ar_acc) sep_raddr_q <= sep_araddr_i;
  end
  wire alias_reg_r = sep_r_last_okay && ((sep_raddr_q - AliasBase) < AliasSpan);

  // Owner-specific qualifier beside the gate: the group samples while a
  // region register has been accessed over SEP_IN since the gate rose, a
  // write that completed OKAY at a region register or a read of one (the
  // owner reads the reset words of every region before its transparent probe
  // and writes the regions before every other probe); the flag clears on
  // every rise of the gate. No other owner accesses a region register under
  // its gate, so their JTAG traffic counts nothing here.
  logic alias_written_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) alias_written_q <= 1'b0;
    else if (gate_rise) alias_written_q <= 1'b0;
    else if (alias_reg_w || alias_reg_r) alias_written_q <= 1'b1;
  end
  wire alias_live = alias_written_q;

  localparam logic [2:0] PosInterior = 3'd0;
  localparam logic [2:0] PosFirst = 3'd1;
  localparam logic [2:0] PosLast = 3'd2;
  localparam logic [2:0] PosBelowStart = 3'd3;
  localparam logic [2:0] PosEndPage = 3'd4;
  localparam logic [2:0] PosNone = 3'd7;
  localparam logic [1:0] PassNone = 2'd0;
  localparam logic [1:0] PassReset = 2'd1;
  localparam logic [1:0] PassValidClear = 2'd2;

  typedef struct packed {
    logic hit;
    logic [2:0] region;
    logic cache_nz;
    logic [2:0] pos;
    logic [55:0] taddr;
    logic [3:0] tcache;
    logic [1:0] pass_kind;
  } alias_dec_t;

  function automatic alias_dec_t alias_decode(input regions_t tbl, input logic [55:0] addr,
                                              input logic [3:0] cache);
    logic all_reset, in_clear, contained;
    alias_decode = '0;
    alias_decode.pos = PosNone;
    alias_decode.taddr = addr;
    alias_decode.tcache = cache;
    all_reset = 1'b1;
    in_clear = 1'b0;
    for (int unsigned i = 0; i < NumRegions; i++) begin
      contained = (addr >= tbl[i].start) && (addr < tbl[i].stop);
      if (tbl[i] != RegionReset) all_reset = 1'b0;
      if (tbl[i].valid && contained && !alias_decode.hit) begin
        alias_decode.hit = 1'b1;
        alias_decode.region = 3'(i);
        alias_decode.cache_nz = (tbl[i].cache != 4'd0);
        alias_decode.taddr = {44'(addr[55:12] + tbl[i].offset), addr[11:0]};
        alias_decode.tcache = tbl[i].cache;
        alias_decode.pos = (addr == tbl[i].start) ? PosFirst
                         : (addr == tbl[i].stop - 56'd1) ? PosLast : PosInterior;
      end
      if (!tbl[i].valid && contained) in_clear = 1'b1;
    end
    if (!alias_decode.hit) begin
      for (int unsigned i = 0; i < NumRegions; i++) begin
        if (tbl[i].valid && (alias_decode.pos == PosNone)) begin
          if (addr == tbl[i].start - 56'd1) begin
            alias_decode.pos = PosBelowStart;
            alias_decode.region = 3'(i);
            alias_decode.cache_nz = (tbl[i].cache != 4'd0);
          end else if (addr == tbl[i].stop) begin
            alias_decode.pos = PosEndPage;
            alias_decode.region = 3'(i);
            alias_decode.cache_nz = (tbl[i].cache != 4'd0);
          end
        end
      end
      alias_decode.pass_kind = all_reset ? PassReset : (in_clear ? PassValidClear : PassNone);
    end
  endfunction

  // One probe outstanding per channel. At the JTAG AW or AR handshake the
  // shadow decode of the probe is kept; one edge later the DUT's remap index
  // is read, when the request has crossed the port's axi_cut and the remap
  // presents its lowest-hit region (on a miss the index reads as the highest
  // region, so it is compared on a hit only); the first SYS_OUT address
  // handshake of that channel while the probe is outstanding carries the
  // translated pair. The sample is the B or R-last handshake at the JTAG
  // port, and the probe counts only when it completes OKAY, the index equals
  // the shadow's region on a hit, and the SYS_OUT address and AxCACHE equal
  // the pair the shadow derives.
  typedef struct packed {
    logic pending;
    logic idx_pending;
    logic cap;
    logic [55:0] addr;
    alias_dec_t dec;
    logic [2:0] idx;
    logic [55:0] oaddr;
    logic [3:0] ocache;
  } alias_probe_t;

  alias_probe_t al_wr_q, al_rd_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      al_wr_q <= '0;
      al_rd_q <= '0;
    end else begin
      if (jtag_aw_acc) begin
        al_wr_q.pending <= 1'b1;
        al_wr_q.idx_pending <= 1'b1;
        al_wr_q.cap <= 1'b0;
        al_wr_q.addr <= jtag_awaddr_i;
        al_wr_q.dec <= alias_decode(regions_q, jtag_awaddr_i, jtag_awcache_i);
      end else begin
        if (jtag_b_acc) al_wr_q.pending <= 1'b0;
        if (al_wr_q.idx_pending) begin
          al_wr_q.idx <= remap_jtag_aw_hit_i;
          al_wr_q.idx_pending <= 1'b0;
        end
        if (out_aw_acc && al_wr_q.pending && !al_wr_q.cap) begin
          al_wr_q.cap <= 1'b1;
          al_wr_q.oaddr <= out_awaddr_i;
          al_wr_q.ocache <= out_awcache_i;
        end
      end
      if (jtag_ar_acc) begin
        al_rd_q.pending <= 1'b1;
        al_rd_q.idx_pending <= 1'b1;
        al_rd_q.cap <= 1'b0;
        al_rd_q.addr <= jtag_araddr_i;
        al_rd_q.dec <= alias_decode(regions_q, jtag_araddr_i, jtag_arcache_i);
      end else begin
        if (jtag_r_last_acc) al_rd_q.pending <= 1'b0;
        if (al_rd_q.idx_pending) begin
          al_rd_q.idx <= remap_jtag_ar_hit_i;
          al_rd_q.idx_pending <= 1'b0;
        end
        if (out_ar_acc && al_rd_q.pending && !al_rd_q.cap) begin
          al_rd_q.cap <= 1'b1;
          al_rd_q.oaddr <= out_araddr_i;
          al_rd_q.ocache <= out_arcache_i;
        end
      end
    end
  end

  wire al_wr_done = jtag_b_acc && al_wr_q.pending;
  wire al_rd_done = jtag_r_last_acc && al_rd_q.pending;
  wire alias_sample_e = gate_on && alias_live && (al_wr_done || al_rd_done);
  // A read and a write completing in the same cycle sample the write only;
  // the owner keeps one probe outstanding.
  alias_probe_t al_p;
  assign al_p = al_wr_done ? al_wr_q : al_rd_q;
  wire [1:0] al_resp = al_wr_done ? jtag_bresp_i : jtag_rresp_i;
  wire al_pair_ok = al_p.cap && (al_p.oaddr == al_p.dec.taddr) && (al_p.ocache == al_p.dec.tcache);
  wire al_idx_ok = !al_p.dec.hit || (al_p.idx == al_p.dec.region);
  wire al_graded = alias_sample_e && (al_resp === 2'b00) && al_pair_ok && al_idx_ok;
  wire al_region_e = al_graded && (al_p.dec.pos != PosNone);
  wire al_low_nz = (al_p.addr[11:0] != 12'd0);

  // The 10 {cacheable class, position} bins of one region; every bin leads
  // with the graded flag.
  `define SMC_ALIAS_REGION_BINS(name, idx) \
      bins name``_c0_interior = {{1'b1, idx, 1'b0, PosInterior}}; \
      bins name``_c0_first = {{1'b1, idx, 1'b0, PosFirst}}; \
      bins name``_c0_last = {{1'b1, idx, 1'b0, PosLast}}; \
      bins name``_c0_below_start = {{1'b1, idx, 1'b0, PosBelowStart}}; \
      bins name``_c0_end_page = {{1'b1, idx, 1'b0, PosEndPage}}; \
      bins name``_cnz_interior = {{1'b1, idx, 1'b1, PosInterior}}; \
      bins name``_cnz_first = {{1'b1, idx, 1'b1, PosFirst}}; \
      bins name``_cnz_last = {{1'b1, idx, 1'b1, PosLast}}; \
      bins name``_cnz_below_start = {{1'b1, idx, 1'b1, PosBelowStart}}; \
      bins name``_cnz_end_page = {{1'b1, idx, 1'b1, PosEndPage}};

  covergroup smc_alias_remap_cg with function sample (
      logic graded,
      logic [2:0] region,
      logic cache_nz,
      logic [2:0] pos,
      logic low_graded,
      logic low_nz,
      logic [1:0] pass_kind
  );
    option.per_instance = 1;
    // {graded, region, cacheable class, position}: 80 cells.
    cp_region_hit: coverpoint {
      graded, region, cache_nz, pos
    } {
      `SMC_ALIAS_REGION_BINS(r0, 3'd0)
      `SMC_ALIAS_REGION_BINS(r1, 3'd1)
      `SMC_ALIAS_REGION_BINS(r2, 3'd2)
      `SMC_ALIAS_REGION_BINS(r3, 3'd3)
      `SMC_ALIAS_REGION_BINS(r4, 3'd4)
      `SMC_ALIAS_REGION_BINS(r5, 3'd5)
      `SMC_ALIAS_REGION_BINS(r6, 3'd6)
      `SMC_ALIAS_REGION_BINS(r7, 3'd7)
    }
    // {graded, AxADDR[11:0] non-zero}: 2 cells, the low bits kept on a hit.
    cp_low_bits: coverpoint {
      low_graded, low_nz
    } {
      bins zero = {2'b10}; bins nonzero = {2'b11};
    }
    // Every region at its reset word; a region with valid clear over the
    // address: 2 cells, the pair passing unchanged.
    cp_pass: coverpoint pass_kind {
      bins reset = {PassReset}; bins valid_clear = {PassValidClear};
    }
  endgroup
  `undef SMC_ALIAS_REGION_BINS

  smc_alias_remap_cg u_cg_alias_remap = new();

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset && alias_sample_e) begin
      u_cg_alias_remap.sample(al_region_e, al_region_e ? al_p.dec.region : 3'd0,
                              al_region_e && al_p.dec.cache_nz,
                              al_region_e ? al_p.dec.pos : PosNone, al_graded,
                              al_graded && al_low_nz, al_graded ? al_p.dec.pass_kind : PassNone);
    end
  end

endmodule : smc_filt_fcov
