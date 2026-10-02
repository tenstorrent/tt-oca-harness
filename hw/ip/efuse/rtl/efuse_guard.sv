// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Filter fuse commands against field locks, lifecycle-state rules, and RMA token checks.
//
// HAS_LC_STATE distinguishes SEP (lifecycle field present) from SMC.
// LC_STATE_BIT_POSITION and TOKEN_MATCH_CODE locate and encode token checks; the SIP and
// chiplet token bit addresses are LC_STATE_BIT_POSITION+1 and +2.
//
// Block program or read when shadow locks or failed RMA token matches apply; secure_tm_i
// can force a secure-TM block.
//
// The outputs report the filtering result:
//
// - Filtered command req/resp pass allowed traffic.
// - efuse_err_o sticks until error_clear_i.
// - Lock and secure-TM status are exported.

module efuse_guard #(
  parameter int unsigned EFUSE_FIELDS     = 1,  // eFuse field-map entry count.
  parameter int unsigned EFUSE_ADDR_WIDTH = 12,  // eFuse byte-address width.
  parameter type         efuse_map_t      = logic,  // Shadow eFuse map type.
  parameter type         fuse_command_req_t      = logic,  // Fuse-command request type.
  parameter type         fuse_command_resp_t      = logic,  // Fuse-command response type.

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
  input logic secure_tm_i,              // Secure test mode, active-high; blocks all fuse traffic
                                        // without raising the error.

  input efuse_pkg::rule_t [EFUSE_FIELDS-1:0] efuse_field_map_i,  // Per-field byte ranges and lock
                                                                 // indices used to find the lock
                                                                 // bits for a target address.

  input logic [5:0] rma_sip_token_match_i,  // RMA SiP token-match status code from token
                                            // processing.
  input logic [5:0] rma_chiplet_token_match_i,  // RMA chiplet token-match status code from token
                                                // processing.

  output logic efuse_err_o,             // Sticky error set when a program or read is blocked by a
                                        // lock or, for a program, by a missing RMA token match; not
                                        // set by secure test mode.
  input  logic error_clear_i,           // Clears the sticky error; a same-cycle new error takes
                                        // priority.

  input fuse_command_req_t fuse_command_req_i,  // Fuse command selected by the controller, before
                                                // filtering.
  output fuse_command_req_t fuse_command_req_filtered_o,  // Fuse command to the SHIM; zero when
                                                          // blocked.

  input fuse_command_resp_t fuse_command_resp_i,  // Fuse command response from the SHIM.
  output fuse_command_resp_t fuse_command_resp_filtered_o,  // Fuse command response to the
                                                            // controller; zero when blocked.

  input efuse_map_t shadow_regs_i,      // Shadow eFuse map supplying the per-field read and write
                                        // lock bits.
  input logic is_programing_i,          // High while the program interface has a command
                                        // outstanding.
  input efuse_addr_t program_target_addr_i,  // Fuse bit address of the outstanding program command.
  input logic is_reading_i,             // High while the read interface has a command outstanding.
  input efuse_addr_t read_target_addr_i,  // Fuse bit address of the outstanding read command.

  output logic is_read_locked_o,        // High when the read target address falls in a read-locked
                                        // field.
  output logic is_program_locked_o,     // High when the program target address is write locked or
                                        // is an RMA token bit without a token match.
  output logic secure_tm_blocked_o      // High while secure test mode blocks fuse traffic.
);

  logic is_program_locked;
  logic is_read_locked;
  logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] pro_read_intf_rd_index, pro_read_intf_wr_index;
  logic pro_read_intf_lock_lc_state_write;
  logic pro_read_intf_rm_lc_state_write_lock;
  logic pro_read_intf_rm_lc_state_read_lock;

  // If read or write is from programming interface or read interface
  always_comb begin
    pro_read_intf_rd_index = find_efuse_field_index(efuse_byte_addr_t'(read_target_addr_i >> 3));     // need to shift since address is a bit address and the shadow registers are byte address
    pro_read_intf_wr_index = find_efuse_field_index(efuse_byte_addr_t'(program_target_addr_i >> 3));  // need to shift since address is a bit address and the shadow registers are byte address

    pro_read_intf_rm_lc_state_write_lock = 1'b0; // In SEP, LC_STATE has write/read lock but even if their lock is set, it should not block the pro_read_interface
    pro_read_intf_rm_lc_state_read_lock = 1'b0;
    pro_read_intf_lock_lc_state_write = 1'b0;
    // LC State write lock
    if (HAS_LC_STATE) begin
      if ((program_target_addr_i == SipTokenBitAddr) && (rma_sip_token_match_i != TOKEN_MATCH_CODE)) begin
        pro_read_intf_lock_lc_state_write = 1'b1;
      end
      else if ((program_target_addr_i == ChipletTokenBitAddr) && (rma_chiplet_token_match_i != TOKEN_MATCH_CODE)) begin
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

  logic error_capture, err;
  logic secure_tm_blocked;

  assign is_program_locked_o = is_program_locked;
  assign is_read_locked_o = is_read_locked;
  assign secure_tm_blocked_o = secure_tm_blocked;

  localparam fuse_command_req_t EmptyReq = '0;
  localparam fuse_command_resp_t FuseCommandRespDefault = '0;

  always_comb begin
    fuse_command_req_filtered_o = fuse_command_req_i;
    error_capture  = 1'b0;
    secure_tm_blocked = 1'b0;
    fuse_command_resp_filtered_o   = fuse_command_resp_i;
    if (secure_tm_i) begin
      fuse_command_req_filtered_o = EmptyReq;
      error_capture  = 1'b0;  // secure_tm is on, but it is not an error_capture, error_capture is for read/write blocked
      secure_tm_blocked = 1'b1;
      fuse_command_resp_filtered_o   = FuseCommandRespDefault; // all output of the efuse is connected to 0;
    end else if (is_programing_i && is_program_locked) begin
      error_capture  = 1'b1;
      fuse_command_req_filtered_o = EmptyReq;
      fuse_command_resp_filtered_o   = FuseCommandRespDefault;
    end else if (is_reading_i && is_read_locked) begin
      error_capture  = 1'b1;
      fuse_command_req_filtered_o = EmptyReq;
      fuse_command_resp_filtered_o   = FuseCommandRespDefault;
    end
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      err <= 1'b0;
    end else begin
      if (error_capture) begin
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
