// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Efuse Shadow Register Access Control
//
//-----------------------------------------------------------------------------

module efuse_shadow_reg_access_control
#(
    parameter int unsigned EFUSE_ADDR_WIDTH = 12,
    parameter int unsigned EFUSE_FIELDS = 1,
    parameter bit HAS_LC_STATE = 1'b0,

    parameter type efuse_map_t = logic,

    parameter type efuse_apb_req_t = logic,
    parameter type efuse_apb_resp_t = logic,

    parameter type efuse_addr_t = logic,
    parameter type efuse_data_t = logic,

    localparam type efuse_strb_t = logic [3:0]
) (
    input  logic                                  clk_i,
    input  logic                                  rst_ni,

    input  logic                                  secure_tm_i,

    // Efuse Field Map Configuration
    input  efuse_pkg::rule_t [EFUSE_FIELDS-1:0]   efuse_field_map_i,

    // APB Register Interface
    input  logic [EFUSE_ADDR_WIDTH-1:0]           apb_req_paddr_i,
    input  logic [2:0]                            apb_req_pprot_i,
    input  logic                                  apb_req_psel_i,
    input  logic                                  apb_req_penable_i,
    input  logic                                  apb_req_pwrite_i,
    input  logic [31:0]                           apb_req_pwdata_i,
    input  logic [3:0]                            apb_req_pstrb_i,

    output efuse_apb_resp_t                       apb_resp_o,

    // APB Interface to/from Access Control
    output efuse_apb_req_t                        apb_req_from_ac_o,
    input  efuse_apb_resp_t                       apb_resp_from_ac_i,

    // Access Control Status Outputs
    output logic                                  write_locked_o,
    output logic                                  write_setup_only_o,
    output logic                                  lc_state_access_o,
    output logic                                  read_locked_o,

    // Shadow Register Map Input
    input  efuse_map_t                            shadow_regs_i,

    // Locked Field Access Interrupt
    output logic                                  locked_field_access_interrupt_o
);

    `include "prim_assert.sv"

    ////////////////////////////////////////////////////////////////////////////
    // Parameter Validation
    ////////////////////////////////////////////////////////////////////////////
    `ASSERT_INIT(EfuseAddrWidthCheck_A, EFUSE_ADDR_WIDTH >= 4)
    `ASSERT_INIT(EfuseFieldsCheck_A, EFUSE_FIELDS >= 1)

    ////////////////////////////////////////////////////////////////////////////
    // Signal Declarations
    ////////////////////////////////////////////////////////////////////////////

    // Access control status
    logic                                     is_write_locked;
    logic                                     is_read_locked;
    logic                                     is_lc_state_access;

    // Field lookup results
    logic [4:0]                               field_index;
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
            is_write_locked = (field_index == 5'd0) ? 1'b0 : write_locked(field_index, shadow_regs_i);
            is_read_locked = (field_index == 5'd0) ? 1'b0 : read_locked(field_index, shadow_regs_i);
        end else begin
            // Standard lock checking for non-LC_STATE configurations
            is_write_locked = write_locked(field_index, shadow_regs_i);
            is_read_locked = read_locked(field_index, shadow_regs_i);
        end
    end

    // Final status generation - combine hardware and software lock states
    assign final_write_setup_only_status = !is_write_locked & (sw_lock_bits[2:1] == 2'b10);  // not write locked from lock bits and also setup only

    // is_write_locked -> from locks field , lock[2:1] 0->sw writable?, lock[3] -> secure_tm lock.
    assign final_write_lock_status = secure_tm_i ? (is_write_locked | (sw_lock_bits[2:1] == 2'b11) | sw_lock_bits[3]) : (is_write_locked | (sw_lock_bits[2:1] == 2'b11));
    assign final_read_lock_status = is_read_locked | sw_lock_bits[0];

    // LC_STATE access detection
    always_comb begin
        if (HAS_LC_STATE && (field_index == 5'd0)) begin
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
    apb_req_from_ac_o.paddr = efuse_addr_t'(0);
    apb_req_from_ac_o.pprot = 2'b0;
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
      end
      // trying to read from a read locked field
      else if (!apb_req_pwrite_i && final_read_lock_status) begin
        apb_resp_o.pslverr = 1'b0;
        apb_resp_o.pready  = 1'b1;
        apb_resp_o.prdata  = efuse_data_t'(32'hbadcab1e);
        locked_field_access_interrupt_o = 1'b1;
      end
      // normal access
      else begin
        apb_resp_o.pslverr = apb_resp_from_ac_i.pslverr;
        apb_resp_o.pready = apb_resp_from_ac_i.pready;
        apb_resp_o.prdata = apb_resp_from_ac_i.prdata;

        apb_req_from_ac_o.psel = apb_req_psel_i;
        apb_req_from_ac_o.penable = apb_req_penable_i;
        apb_req_from_ac_o.paddr = efuse_addr_t'(apb_req_paddr_i);
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

    // Find the efuse field index for a given address
    function automatic logic [4:0] find_efuse_field_index(efuse_addr_t address);
        for (int i = 0; i < EFUSE_FIELDS; i = i + 1) begin
            if (address >= efuse_addr_t'(efuse_field_map_i[i].start_addr) &&
                address <= efuse_addr_t'(efuse_field_map_i[i].end_addr)) begin
                return efuse_field_map_i[i].idx;
            end
        end
        return EFUSE_FIELDS;
    endfunction

    // Find the software lock bits for a given address
    function automatic logic [3:0] find_efuse_sw_lock(efuse_addr_t address);
        for (int i = 0; i < EFUSE_FIELDS; i = i + 1) begin
            if (address >= efuse_addr_t'(efuse_field_map_i[i].start_addr) &&
                address <= efuse_addr_t'(efuse_field_map_i[i].end_addr)) begin
                return efuse_field_map_i[i].lock;
            end
        end

        return '0; // Return unlocked if not found
    endfunction

    // Check if a field is write locked by hardware locks
    function automatic logic write_locked(logic [4:0] index, efuse_map_t shadow_regs);
        if (index < 5'h1f) begin
            return shadow_regs.f.locks[index*2];
        end else begin
            return 1'b0;
        end
    endfunction

    // Check if a field is read locked by hardware locks
    function automatic logic read_locked(logic [4:0] index, efuse_map_t shadow_regs);
        if (index < 5'h1f) begin
            return shadow_regs.f.locks[index*2+1];
        end else begin
            return 1'b0;
        end
    endfunction

    ////////////////////////////////////////////////////////////////////////////
    // Runtime Assertions
    ////////////////////////////////////////////////////////////////////////////

    // Generate address width checks for each efuse field
    // for (genvar i = 0; i < EFUSE_FIELDS; i = i + 1) begin : gen_field_assertions
    //     `ASSERT_INIT(EfuseFieldStartAddrCheck_A,
    //                  efuse_field_map_i[i].start_addr[31:EFUSE_ADDR_WIDTH] == 'd0)
    //     `ASSERT_INIT(EfuseFieldEndAddrCheck_A,
    //                  efuse_field_map_i[i].end_addr[31:EFUSE_ADDR_WIDTH] == 'd0)
    // end
    // for (genvar i = 0; i < EFUSE_FIELDS; i = i + 1) begin : gen_field_assertions
    //     `ASSERT_INIT(EfuseFieldStartAddrCheck_A,
    //                  efuse_field_map_i[i].start_addr[31:EFUSE_ADDR_WIDTH] == 'd0)
    //     `ASSERT_INIT(EfuseFieldEndAddrCheck_A,
    //                  efuse_field_map_i[i].end_addr[31:EFUSE_ADDR_WIDTH] == 'd0)
    // end

endmodule : efuse_shadow_reg_access_control
