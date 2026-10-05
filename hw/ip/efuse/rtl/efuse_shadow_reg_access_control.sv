// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Enforce per-field read and write locks on APB accesses to the shadow map.
//
// Filter APB requests using efuse_field_map_i and locks_i before they reach the shadow
// regs.
//
// LockVectorBits is 2*(EFUSE_FIELDS-1), with write-lock at 2n and read-lock at 2n+1 per
// real field. The LOCKS meta-field uses sentinel idx all-ones and is excluded from hw-lock
// checks.
//
// Report write_locked_o, read_locked_o, write_setup_only_o, and lc_state_access_o.
// locked_field_access_interrupt_o signals locked-field hits.

module efuse_shadow_reg_access_control #(
  parameter int unsigned EFUSE_ADDR_WIDTH = 12,  // Width of the MAP window byte offset on
                                                 // apb_req_paddr_i.
  parameter int unsigned EFUSE_FIELDS = 1,  // eFuse field-map entry count.
  parameter bit HAS_LC_STATE = 1'b0,    // Set for SEP: field index 0 is the lifecycle-state field,
                                        // exempt from hardware locks and reported on
                                        // lc_state_access_o.

  parameter type efuse_apb_req_t = logic,  // eFuse APB request type.
  parameter type efuse_apb_resp_t = logic,  // eFuse APB response type.

  parameter type efuse_addr_t = logic,  // Fuse bit-address type; here it only widens the APB byte
                                        // offset for the field-range lookups.
  parameter type efuse_data_t = logic,  // Fuse data-word type.

  localparam type efuse_strb_t = logic [3:0],  // APB write-strobe type.

  localparam int unsigned LockVectorBits = 2 * (EFUSE_FIELDS - 1)    // Hardware lock bits: a write and a read lock
                                                                     // per field, excluding the LOCKS meta-field.
) (
  input  logic                                  clk_i,  // System clock; not used, the module is
                                                        // combinational.
  input  logic                                  rst_ni,  // Active-low reset; not used, the module
                                                         // is combinational.

  input  logic                                  secure_tm_i,  // Secure test mode, active-high; adds
                                                              // each field's secure-test-mode lock
                                                              // to the write check.

  input  efuse_pkg::rule_t [EFUSE_FIELDS-1:0]   efuse_field_map_i,  // Per-field byte ranges, lock indices, and
                                                                    // software lock bits.

  input  logic [EFUSE_ADDR_WIDTH-1:0]           apb_req_paddr_i,  // Byte offset within the MAP
                                                                  // window, matched against the
                                                                  // field byte ranges.
  input  logic [2:0]                            apb_req_pprot_i,  // APB protection attributes,
                                                                  // forwarded unchanged.
  input  logic                                  apb_req_psel_i,  // APB select for the MAP window.
  input  logic                                  apb_req_penable_i,  // APB access phase; lock checks apply only while
                                                                    // it and the select are high.
  input  logic                                  apb_req_pwrite_i,  // APB transfer direction, high
                                                                   // for a write.
  input  logic [31:0]                           apb_req_pwdata_i,  // Write data forwarded to the
                                                                   // shadow registers when the
                                                                   // access is allowed.
  input  logic [3:0]                            apb_req_pstrb_i,  // Byte lane enables for the
                                                                  // write.

  output efuse_apb_resp_t                       apb_resp_o,  // APB response; a locked access
                                                             // completes with read data 0xBADCAB1E
                                                             // and no slave error.

  output efuse_apb_req_t                        apb_req_from_ac_o,  // APB request forwarded to the shadow registers;
                                                                    // zero unless the access passes the lock checks.
  input  efuse_apb_resp_t                       apb_resp_from_ac_i,  // APB response from the shadow registers for
                                                                     // accesses that pass the lock checks.

  output logic                                  write_locked_o,  // High during an APB write access
                                                                 // to a field that is write locked
                                                                 // by its hardware lock bit, its
                                                                 // software lock bits, or its
                                                                 // secure-test-mode lock.
  output logic                                  write_setup_only_o,  // High when the addressed field is set-only:
                                                                     // writes may set bits but not clear them; low
                                                                     // when its hardware write lock is set.
  output logic                                  lc_state_access_o,  // High when the address falls in the
                                                                    // lifecycle-state field.
  output logic                                  read_locked_o,  // High when the addressed field is
                                                                // read locked by its hardware or
                                                                // software lock bit.

  input  logic [LockVectorBits-1:0]           locks_i,    // Hardware lock bits from the shadow
                                                          // LOCKS words: write lock at 2n, read
                                                          // lock at 2n+1 for field n.

  output logic                                  locked_field_access_interrupt_o  // High during an APB access that a
                                                                                 // lock blocks.
);

  `include "prim_assert.sv"

  ////////////////////////////////////////////////////////////////////////////
  // Parameter Validation
  ////////////////////////////////////////////////////////////////////////////
  `OCAH_OT_ASSERT_INIT(EfuseAddrWidthCheck_A, EFUSE_ADDR_WIDTH >= 4)
  `OCAH_OT_ASSERT_INIT(EfuseFieldsCheck_A, EFUSE_FIELDS >= 1)

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
  // Signal Declarations
  ////////////////////////////////////////////////////////////////////////////

  // Access control status
  logic                                     is_write_locked;
  logic                                     is_read_locked;
  logic                                     is_lc_state_access;

  // Field lookup results
  logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] field_index;
  logic [3:0]                               sw_lock_bits;

  // Final combined status
  logic                                     final_write_lock_status;
  logic                                     final_read_lock_status;
  logic                                     final_write_setup_only_status;

  ////////////////////////////////////////////////////////////////////////////
  // Combinational Logic
  ////////////////////////////////////////////////////////////////////////////

  // Field index and lock bit lookup
  always_comb begin
    field_index = find_efuse_field_index(efuse_addr_t'(apb_req_paddr_i));
    sw_lock_bits = find_efuse_sw_lock(efuse_addr_t'(apb_req_paddr_i));

    if (HAS_LC_STATE) begin
      // For LC_STATE field (index 0), write/read locks are handled by parent module
      is_write_locked = (field_index == '0) ? 1'b0 : write_locked(field_index);
      is_read_locked = (field_index == '0) ? 1'b0 : read_locked(field_index);
    end else begin
      // Standard lock checking for non-LC_STATE configurations
      is_write_locked = write_locked(field_index);
      is_read_locked = read_locked(field_index);
    end
  end

  // Final status generation - combine hardware and software lock states
  assign final_write_setup_only_status = !is_write_locked & (sw_lock_bits[2:1] == 2'b10);  // not write locked from lock bits and also setup only

  // is_write_locked -> from locks field , lock[2:1] 0->sw writable?, lock[3] -> secure_tm lock.
  assign final_write_lock_status = secure_tm_i ? (is_write_locked | (sw_lock_bits[2:1] == 2'b11) | sw_lock_bits[3]) : (is_write_locked | (sw_lock_bits[2:1] == 2'b11));
  assign final_read_lock_status = is_read_locked | sw_lock_bits[0];

  // LC_STATE access detection
  always_comb begin
    if (HAS_LC_STATE && (field_index == '0)) begin
      is_lc_state_access = 1'b1;
    end else begin
      is_lc_state_access = 1'b0;
    end
  end
  ////////////////////////////////////////////////////////////////////////////
  // APB Access Control Logic
  ////////////////////////////////////////////////////////////////////////////

  always_comb begin
    // response back to smc access
    apb_resp_o.pready = 1'b0;
    apb_resp_o.prdata = efuse_data_t'(0);
    apb_resp_o.pslverr = 1'b0;

    // request to shadow registers
    apb_req_from_ac_o.psel = 1'b0;
    apb_req_from_ac_o.penable = 1'b0;
    apb_req_from_ac_o.paddr = '0;
    apb_req_from_ac_o.pprot = '0;
    apb_req_from_ac_o.pwrite = 1'b0;
    apb_req_from_ac_o.pstrb = efuse_strb_t'(0);
    apb_req_from_ac_o.pwdata = efuse_data_t'(0);
    write_locked_o = 1'b0;
    locked_field_access_interrupt_o = 1'b0;

    if (apb_req_penable_i && apb_req_psel_i) begin
      // trying to write to a write locked field
      if (apb_req_pwrite_i && final_write_lock_status) begin
        apb_resp_o.pslverr = 1'b0;
        apb_resp_o.pready = 1'b1;
        apb_resp_o.prdata = efuse_data_t'(32'hbadcab1e);
        write_locked_o = 1'b1;
        locked_field_access_interrupt_o = 1'b1;
      end  // trying to read from a read locked field
      else if (!apb_req_pwrite_i && final_read_lock_status) begin
        apb_resp_o.pslverr = 1'b0;
        apb_resp_o.pready  = 1'b1;
        apb_resp_o.prdata  = efuse_data_t'(32'hbadcab1e);
        locked_field_access_interrupt_o = 1'b1;
      end  // normal access
      else begin
        apb_resp_o.pslverr = apb_resp_from_ac_i.pslverr;
        apb_resp_o.pready = apb_resp_from_ac_i.pready;
        apb_resp_o.prdata = apb_resp_from_ac_i.prdata;

        apb_req_from_ac_o.psel = apb_req_psel_i;
        apb_req_from_ac_o.penable = apb_req_penable_i;
        apb_req_from_ac_o.paddr = $bits(apb_req_from_ac_o.paddr)'(apb_req_paddr_i);
        apb_req_from_ac_o.pprot = apb_req_pprot_i;
        apb_req_from_ac_o.pwrite = apb_req_pwrite_i;
        apb_req_from_ac_o.pstrb = apb_req_pstrb_i;
        apb_req_from_ac_o.pwdata = apb_req_pwdata_i;
        write_locked_o = 1'b0;
      end
    end
  end

  ////////////////////////////////////////////////////////////////////////////
  // Output Assignments
  ////////////////////////////////////////////////////////////////////////////

  assign write_setup_only_o = final_write_setup_only_status;
  assign read_locked_o = final_read_lock_status;
  assign lc_state_access_o = is_lc_state_access;

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

  ////////////////////////////////////////////////////////////////////////////
  // Runtime Assertions
  ////////////////////////////////////////////////////////////////////////////

  // Generate address width checks for each efuse field

endmodule : efuse_shadow_reg_access_control
