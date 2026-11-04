// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Decode the per-field read and write locks that apply to a shadow-map byte address.
//
// Look addr_i up in efuse_field_map_i and combine the field's software lock bits with its
// hardware lock bits from locks_i. The module is combinational and independent of the bus
// protocol; the caller decides which accesses the locks block.
//
// LockVectorBits is 2*(EFUSE_FIELDS-1), with write-lock at 2n and read-lock at 2n+1 per
// real field. The LOCKS meta-field uses sentinel idx all-ones and is excluded from hw-lock
// checks, as is any unmapped address.

module efuse_shadow_reg_access_control #(
  parameter int unsigned EFUSE_ADDR_WIDTH = 12,  // Width of the MAP window byte offset on addr_i.
  parameter int unsigned EFUSE_FIELDS = 1,  // eFuse field-map entry count.
  parameter bit HAS_LC_STATE = 1'b0,    // Set for SEP: field index 0 is the lifecycle-state field,
                                        // exempt from hardware locks and reported on
                                        // lc_state_access_o.

  parameter type efuse_addr_t = logic,  // Fuse bit-address type; here it only widens addr_i for
                                        // the field-range lookups.

  localparam int unsigned LockVectorBits = 2 * (EFUSE_FIELDS - 1)    // Hardware lock bits: a write and a read lock
                                                                     // per field, excluding the LOCKS meta-field.
) (
  input  logic                                  secure_tm_i,  // Secure test mode, active-high; adds
                                                              // each field's secure-test-mode lock
                                                              // to the write lock.

  input  efuse_pkg::rule_t [EFUSE_FIELDS-1:0]   efuse_field_map_i,  // Per-field byte ranges, lock indices, and
                                                                    // software lock bits.
  input  logic [LockVectorBits-1:0]             locks_i,  // Hardware lock bits from the shadow
                                                          // LOCKS words: write lock at 2n, read
                                                          // lock at 2n+1 for field n.

  input  logic [EFUSE_ADDR_WIDTH-1:0]           addr_i,  // Byte offset within the MAP window,
                                                         // matched against the field byte ranges.

  output logic                                  write_locked_o,  // High when the addressed field is write
                                                                 // locked by its hardware lock bit, its
                                                                 // software lock bits, or its
                                                                 // secure-test-mode lock.
  output logic                                  read_locked_o,  // High when the addressed field is
                                                                // read locked by its hardware or
                                                                // software lock bit.
  output logic                                  write_setup_only_o,  // High when the addressed field is set-only:
                                                                     // writes may set bits but not clear them; low
                                                                     // when its hardware write lock is set.
  output logic                                  lc_state_access_o  // High when the address falls in the
                                                                   // lifecycle-state field.
);

  `include "prim_assert.sv"
  `include "ocah_assert.svh"

  ////////////////////////////////////////////////////////////////////////////
  // Parameter Validation
  ////////////////////////////////////////////////////////////////////////////
  `OCAH_ASSERT_STATIC(EfuseAddrWidthCheck_A, EFUSE_ADDR_WIDTH >= 4)
  `OCAH_ASSERT_STATIC(EfuseFieldsCheck_A, EFUSE_FIELDS >= 1)

  // Bounds every mapped field idx for the locks_i[index*2] / [index*2+1] lookups.
  // The code this guards also skips idx '1, so this does too.
  function automatic logic field_map_idx_in_range();
    logic in_range;
    in_range = 1'b1;
    for (int unsigned i = 0; i < EFUSE_FIELDS; i++) begin
      if ((efuse_field_map_i[i].idx != '1) &&
          (int'(efuse_field_map_i[i].idx) >= int'(EFUSE_FIELDS) - 1)) begin
        in_range = 1'b0;
      end
    end
    return in_range;
  endfunction

  `OCAH_OT_ASSERT_INIT(EfuseFieldMapIdxInRange_A, field_map_idx_in_range())

  ////////////////////////////////////////////////////////////////////////////
  // Lock Decode
  ////////////////////////////////////////////////////////////////////////////

  logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] field_index;
  logic [3:0]                                  sw_lock_bits;
  logic                                        hw_write_locked;
  logic                                        hw_read_locked;

  assign field_index  = find_efuse_field_index(efuse_addr_t'(addr_i));
  assign sw_lock_bits = find_efuse_sw_lock(efuse_addr_t'(addr_i));

  // The lifecycle-state field's locks are applied by efuse_shadow_regs.
  assign lc_state_access_o = HAS_LC_STATE && (field_index == '0);
  assign hw_write_locked   = !lc_state_access_o && write_locked(field_index);
  assign hw_read_locked    = !lc_state_access_o && read_locked(field_index);

  // sw_lock_bits: [0] read lock, [2:1] 2'b11 write lock / 2'b10 set-only, [3] secure-test lock.
  assign write_locked_o     = hw_write_locked || (sw_lock_bits[2:1] == 2'b11) ||
                              (secure_tm_i && sw_lock_bits[3]);
  assign read_locked_o      = hw_read_locked || sw_lock_bits[0];
  assign write_setup_only_o = !hw_write_locked && (sw_lock_bits[2:1] == 2'b10);

  ////////////////////////////////////////////////////////////////////////////
  // Helper Functions
  ////////////////////////////////////////////////////////////////////////////

  // Find the efuse field index for a given address.
  // Returns '1 (all-ones) for the LOCKS meta-field or any unmapped address;
  // both cases are excluded from hardware lock checks.
  function automatic logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] find_efuse_field_index(
      efuse_addr_t address);
    for (int i = 0; i < EFUSE_FIELDS; i = i + 1) begin
      if (address >= efuse_addr_t'(efuse_field_map_i[i].start_addr) &&
                address <= efuse_addr_t'(efuse_field_map_i[i].end_addr)) begin
        return efuse_field_map_i[i].idx;
      end
    end
    return '1;
  endfunction

  // Find the software lock bits for a given address
  function automatic logic [3:0] find_efuse_sw_lock(efuse_addr_t address);
    for (int i = 0; i < EFUSE_FIELDS; i = i + 1) begin
      if (address >= efuse_addr_t'(efuse_field_map_i[i].start_addr) &&
                address <= efuse_addr_t'(efuse_field_map_i[i].end_addr)) begin
        return efuse_field_map_i[i].lock;
      end
    end
    return '0;
  endfunction

  // Check if a field is write locked by hardware locks.
  // idx '1 (all-ones) is the sentinel for the LOCKS meta-field and unmapped
  // addresses; both are excluded from hardware lock checks.
  function automatic logic write_locked(logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] index);
    if (index != '1) begin
      return locks_i[index*2];
    end else begin
      return 1'b0;
    end
  endfunction

  // Check if a field is read locked by hardware locks.
  function automatic logic read_locked(logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] index);
    if (index != '1) begin
      return locks_i[index*2+1];
    end else begin
      return 1'b0;
    end
  endfunction

endmodule : efuse_shadow_reg_access_control
