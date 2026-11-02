// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Check program and read targets against field locks, lifecycle-state rules, and RMA token checks.
//
// HAS_LC_STATE distinguishes SEP (lifecycle field present) from SMC.
// LC_STATE_BIT_POSITION and TOKEN_MATCH_CODE locate and encode token checks; the SIP and
// chiplet token bit addresses are LC_STATE_BIT_POSITION+1 and +2.
//
// The program and read interfaces sample the lock and secure-TM status when firmware starts a
// command and refuse a blocked start without issuing it; a command already issued completes.
//
// Targets at or above ADOPTER_BIT_BASE are looked up in the adopter field map, at byte offsets
// from that base, against adopter_locks_i; targets below it use the harness field map and
// locks_i. The full bit address selects the table, so no adopter target aliases a harness field.
//
// - efuse_err_o sets on a lock-refused start and sticks until error_clear_i.
// - Lock and secure-TM status are exported.

module efuse_guard #(
  parameter int unsigned EFUSE_FIELDS     = 1,  // eFuse field-map entry count.
  parameter int unsigned EFUSE_ADDR_WIDTH = 12,  // eFuse byte-address width.
  parameter int unsigned LOCK_VECTOR_BITS = 2 * (EFUSE_FIELDS - 1),  // Harness lock bits on locks_i.
  parameter int unsigned ADOPTER_FIELDS = 0,  // Adopter field-map entry count; 0 disables the
                                              // adopter lookup.
  parameter int unsigned ADOPTER_BIT_BASE = 0,  // Fuse bit address of the first adopter fuse.
  parameter int unsigned ADOPTER_LOCK_VECTOR_BITS = 64,  // Adopter lock bits on adopter_locks_i.

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
  localparam int unsigned NumAdopterRules = ADOPTER_FIELDS > 0 ? ADOPTER_FIELDS : 1,  // Adopter field-map
                                                                                      // port width.
  localparam efuse_addr_t SipTokenBitAddr = efuse_addr_t'(LC_STATE_BIT_POSITION + 1),  // Bit address of the RMA SiP token bit.
  localparam efuse_addr_t ChipletTokenBitAddr = efuse_addr_t'(LC_STATE_BIT_POSITION + 2)  // Bit address of the RMA chiplet token bit.
) (
  input logic clk_i,                    // System clock.
  input logic rst_ni,                   // Active-low synchronous reset; clears efuse_err_o.
  input logic secure_tm_i,              // Secure test mode, active-high; blocks every start
                                        // without raising the error.

  input efuse_pkg::rule_t [EFUSE_FIELDS-1:0] efuse_field_map_i,  // Per-field byte ranges and lock
                                                                 // indices used to find the lock
                                                                 // bits for a harness target.
  input efuse_pkg::rule_t [NumAdopterRules-1:0] adopter_field_map_i,  // Per-region byte ranges, from
                                                                      // ADOPTER_BIT_BASE, and lock
                                                                      // indices for an adopter target;
                                                                      // unused when ADOPTER_FIELDS is 0.

  input logic [5:0] rma_sip_token_match_i,  // RMA SiP token-match status code from token
                                            // processing.
  input logic [5:0] rma_chiplet_token_match_i,  // RMA chiplet token-match status code from token
                                                // processing.

  output logic efuse_err_o,             // Sticky error set when a program or read start is refused
                                        // by a lock or, for a program, by a missing RMA token match;
                                        // not set by secure test mode.
  input  logic error_clear_i,           // Clears the sticky error; a same-cycle new error takes
                                        // priority.

  input logic [LOCK_VECTOR_BITS-1:0] locks_i,  // Harness lock bits: write lock at 2n, read lock
                                               // at 2n+1 for lock index n.
  input logic [ADOPTER_LOCK_VECTOR_BITS-1:0] adopter_locks_i,  // Adopter lock bits, in the same
                                                               // layout as locks_i.
  input efuse_addr_t program_target_addr_i,  // Fuse bit address a program start would target.
  input efuse_addr_t read_target_addr_i,  // Fuse bit address a read start would target.
  input logic program_blocked_i,        // One-cycle pulse: a lock refused a program start.
  input logic read_blocked_i,           // One-cycle pulse: a lock refused a read start.

  output logic is_read_locked_o,        // High when the read target address falls in a read-locked
                                        // field.
  output logic is_program_locked_o,     // High when the program target address is write locked or
                                        // is an RMA token bit without a token match.
  output logic secure_tm_blocked_o      // High while secure test mode blocks fuse command starts.
);

  logic is_program_locked;
  logic is_read_locked;
  logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] pro_read_intf_rd_index, pro_read_intf_wr_index;
  logic rd_is_adopter, wr_is_adopter;
  logic pro_read_intf_lock_lc_state_write;
  logic pro_read_intf_rm_lc_state_write_lock;
  logic pro_read_intf_rm_lc_state_read_lock;

  // If read or write is from programming interface or read interface
  always_comb begin
    rd_is_adopter = (ADOPTER_FIELDS > 0) && (read_target_addr_i >= efuse_addr_t'(ADOPTER_BIT_BASE));
    wr_is_adopter = (ADOPTER_FIELDS > 0) && (program_target_addr_i >= efuse_addr_t'(ADOPTER_BIT_BASE));

    // Shift since the address is a bit address and the field maps are byte addresses.
    pro_read_intf_rd_index = rd_is_adopter ? find_adopter_field_index(read_target_addr_i) :
        find_efuse_field_index(efuse_byte_addr_t'(read_target_addr_i >> 3));
    pro_read_intf_wr_index = wr_is_adopter ? find_adopter_field_index(program_target_addr_i) :
        find_efuse_field_index(efuse_byte_addr_t'(program_target_addr_i >> 3));

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
    pro_read_intf_rm_lc_state_write_lock =
        (HAS_LC_STATE && !wr_is_adopter && (pro_read_intf_wr_index == '0)) ? 1'b0 :
        entry_locked(wr_is_adopter, pro_read_intf_wr_index, 1'b0);
    pro_read_intf_rm_lc_state_read_lock =
        (HAS_LC_STATE && !rd_is_adopter && (pro_read_intf_rd_index == '0)) ? 1'b0 :
        entry_locked(rd_is_adopter, pro_read_intf_rd_index, 1'b1);

    is_program_locked = pro_read_intf_rm_lc_state_write_lock || pro_read_intf_lock_lc_state_write;
    is_read_locked = pro_read_intf_rm_lc_state_read_lock;
  end

  logic err;

  assign is_program_locked_o = is_program_locked;
  assign is_read_locked_o = is_read_locked;
  assign secure_tm_blocked_o = secure_tm_i;

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

  // Returns '1 (all-ones) for the lock meta-field or any unmapped address;
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

  // Returns '1 for an unused entry or any address outside the adopter regions.
  function automatic logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] find_adopter_field_index(
      efuse_addr_t address);
    efuse_addr_t offset;
    offset = efuse_addr_t'((address - efuse_addr_t'(ADOPTER_BIT_BASE)) >> 3);
    for (int i = 0; i < NumAdopterRules; i = i + 1) begin
      if (offset >= efuse_addr_t'(adopter_field_map_i[i].start_addr) &&
          offset <= efuse_addr_t'(adopter_field_map_i[i].end_addr)) begin
        return adopter_field_map_i[i].idx;
      end
    end
    return '1;
  endfunction

  // idx '1 (all-ones) is the sentinel for the lock meta-field and unmapped
  // addresses; hardware lock bits are never applied to either.
  function automatic logic entry_locked(logic adopter,
                                        logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] index,
                                        logic read);
    if (index == '1) return 1'b0;
    return adopter ? adopter_locks_i[index*2+int'(read)] : locks_i[index*2+int'(read)];
  endfunction

endmodule
