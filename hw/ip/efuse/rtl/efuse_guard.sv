// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Check program and read target addresses against field locks, lifecycle-state rules, and RMA
// token checks before a fuse command is issued.
//
// HAS_LC_STATE distinguishes SEP (lifecycle field present) from SMC.
// LC_STATE_BIT_POSITION and TOKEN_MATCH_CODE locate and encode token checks; the SIP and
// chiplet token bit addresses are LC_STATE_BIT_POSITION+1 and +2.
//
// - is_program_locked_o and is_read_locked_o are sampled by the interfaces at start time;
//   a blocked command never reaches the SHIM.
// - efuse_err_o sets when an interface reports a lock-refused start and sticks until
//   error_clear_i.

module efuse_guard #(
  parameter int unsigned EFUSE_FIELDS     = 1,  // eFuse field-map entry count.
  parameter int unsigned EFUSE_ADDR_WIDTH = 12,  // eFuse byte-address width.
  parameter type         efuse_map_t      = logic,  // Shadow eFuse map type.

  parameter bit HAS_LC_STATE = 1'b0,    // Set for SEP: exempts field index 0 from locks and gates
                                        // the RMA token bits on token matches; clear for SMC.
  parameter int unsigned LC_STATE_BIT_POSITION = 0,  // Bit address of the lifecycle-state field.

  parameter logic [5:0] TOKEN_MATCH_CODE = 6'b010101,  // Token-match status code that permits
                                                       // programming the corresponding RMA token
                                                       // bit.

  parameter type efuse_addr_t = logic,  // Fuse bit-address type.
  parameter type efuse_data_t = logic [31:0],  // Fuse data-word type; declared but not used in this
                                               // module.

  localparam type efuse_byte_addr_t = logic [EFUSE_ADDR_WIDTH-1:0],  // Fuse byte-address type.
  localparam efuse_addr_t SipTokenBitAddr = efuse_addr_t'(LC_STATE_BIT_POSITION + 1),  // Bit address of the RMA SiP token bit.
  localparam efuse_addr_t ChipletTokenBitAddr = efuse_addr_t'(LC_STATE_BIT_POSITION + 2)  // Bit address of the RMA chiplet token bit.
) (
  input logic clk_i,                    // System clock.
  input logic rst_ni,                   // Active-low synchronous reset; clears efuse_err_o.

  input efuse_pkg::rule_t [EFUSE_FIELDS-1:0] efuse_field_map_i,  // Per-field byte ranges and lock
                                                                 // indices used to find the lock
                                                                 // bits for a target address.

  input logic [5:0] rma_sip_token_match_i,  // RMA SiP token-match status code from token
                                            // processing.
  input logic [5:0] rma_chiplet_token_match_i,  // RMA chiplet token-match status code from token
                                                // processing.

  output logic efuse_err_o,             // Sticky error set when a program or read start is refused
                                        // by a lock or, for a program, by a missing RMA token match;
                                        // not set by secure test mode.
  input  logic error_clear_i,           // Clears the sticky error; a same-cycle new error takes
                                        // priority.

  input efuse_map_t shadow_regs_i,      // Shadow eFuse map supplying the per-field read and write
                                        // lock bits.
  input efuse_addr_t program_addr_i,    // Fuse bit address a program start would target.
  input efuse_addr_t read_addr_i,       // Fuse bit address a read start would target.
  input logic program_blocked_i,        // One-cycle pulse: a program start was refused by a lock.
  input logic read_blocked_i,           // One-cycle pulse: a read start was refused by a lock.

  output logic is_read_locked_o,        // High when read_addr_i falls in a read-locked field.
  output logic is_program_locked_o      // High when program_addr_i is write locked or is an RMA
                                        // token bit without a token match.
);

  logic is_program_locked;
  logic is_read_locked;
  logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] pro_read_intf_rd_index, pro_read_intf_wr_index;
  logic pro_read_intf_lock_lc_state_write;
  logic pro_read_intf_rm_lc_state_write_lock;
  logic pro_read_intf_rm_lc_state_read_lock;

  // If read or write is from programming interface or read interface
  always_comb begin
    pro_read_intf_rd_index = find_efuse_field_index(efuse_byte_addr_t'(read_addr_i >> 3));     // need to shift since address is a bit address and the shadow registers are byte address
    pro_read_intf_wr_index = find_efuse_field_index(efuse_byte_addr_t'(program_addr_i >> 3));  // need to shift since address is a bit address and the shadow registers are byte address

    pro_read_intf_rm_lc_state_write_lock = 1'b0; // In SEP, LC_STATE has write/read lock but even if their lock is set, it should not block the pro_read_interface
    pro_read_intf_rm_lc_state_read_lock = 1'b0;
    pro_read_intf_lock_lc_state_write = 1'b0;
    // LC State write lock
    if (HAS_LC_STATE) begin
      if ((program_addr_i == SipTokenBitAddr) && (rma_sip_token_match_i != TOKEN_MATCH_CODE)) begin
        pro_read_intf_lock_lc_state_write = 1'b1;
      end
      else if ((program_addr_i == ChipletTokenBitAddr) && (rma_chiplet_token_match_i != TOKEN_MATCH_CODE)) begin
        pro_read_intf_lock_lc_state_write = 1'b1;
      end
    end
    if (HAS_LC_STATE) begin
      // SEP
      pro_read_intf_rm_lc_state_write_lock = (pro_read_intf_wr_index == '0)? 1'b0 : entry_write_locked(pro_read_intf_wr_index, shadow_regs_i);
      pro_read_intf_rm_lc_state_read_lock = (pro_read_intf_rd_index == '0)? 1'b0 : entry_read_locked(pro_read_intf_rd_index, shadow_regs_i);
    end else begin
      // SMC
      pro_read_intf_rm_lc_state_write_lock = entry_write_locked(pro_read_intf_wr_index, shadow_regs_i);
      pro_read_intf_rm_lc_state_read_lock = entry_read_locked(pro_read_intf_rd_index, shadow_regs_i);
    end

    is_program_locked = pro_read_intf_rm_lc_state_write_lock || pro_read_intf_lock_lc_state_write;
    is_read_locked = pro_read_intf_rm_lc_state_read_lock;
  end

  logic err;

  assign is_program_locked_o = is_program_locked;
  assign is_read_locked_o = is_read_locked;

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      err <= 1'b0;
    end else begin
      if (program_blocked_i || read_blocked_i) begin
        err <= 1'b1;
      end else if (error_clear_i) begin
        err <= 1'b0;
      end
    end
  end

  assign efuse_err_o = err;

  // Returns '1 (all-ones) for the LOCKS meta-field or any unmapped address;
  // both cases are excluded from hardware lock checks.
  function automatic logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] find_efuse_field_index(
      efuse_byte_addr_t address);
    for (int i = 0; i < EFUSE_FIELDS; i = i + 1) begin
      if (address >= efuse_byte_addr_t'(efuse_field_map_i[i].start_addr) && address <= efuse_byte_addr_t'(efuse_field_map_i[i].end_addr)) begin
        return efuse_field_map_i[i].idx;
      end
    end
    return '1;
  endfunction

  // idx '1 (all-ones) is the sentinel for the LOCKS meta-field and unmapped
  // addresses; hardware lock bits are never applied to either.
  function automatic logic entry_write_locked(logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] index,
                                              efuse_map_t shadow_regs);
    if (index != '1) begin
      return shadow_regs.locks.locks[index*2];
    end else return 1'b0;
  endfunction

  function automatic logic entry_read_locked(logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] index,
                                             efuse_map_t shadow_regs);
    if (index != '1) begin
      return shadow_regs.locks.locks[index*2+1];
    end else return 1'b0;
  endfunction

endmodule
