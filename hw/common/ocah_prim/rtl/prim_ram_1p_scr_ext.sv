// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Scramble a single-port SRAM front-end over prim_ram_1p_adv_ext tiles.
//
// Refuse to grant req_i while key_valid_i is low. intg_error_i suppresses any real memory
// transaction on an upstream integrity fault.
//
// Delay writes one cycle so reads and writes share the PRINCE keystream unit. Hold a
// pending write across a following read and detect address collisions; a colliding read
// returns the masked bytes of the pending write data.
// Read data returns one cycle after the grant. The inner RAM runs without ECC, so rerror_o
// can only report parity errors.
//
// Keep cipher rounds low for latency. PRINCE's original 5 half-rounds are 2*5+1 effective
// rounds; NUM_PRINCE_ROUNDS_HALF of 3 is about 7 effective rounds and must be in [1..5].
//
// NUM_DIFF_ROUNDS of 0 disables diffusion because non-linear data diffusion can interact
// adversely with end-to-end ECC. Enable it only with full knowledge of that interaction,
// for example with byte parity.

module prim_ram_1p_scr_ext
  import prim_ram_1p_pkg::*;

  `include "ocah_assert.svh"
  import prim_ram_1p_adv_ext_pkg::*;
#(
  parameter  int DEPTH                  = 16*1024,  // Logical depth; must be a power of 2 if
                                                    // NUM_ADDR_SCR_ROUNDS > 0.
  parameter  int INST_DEPTH             = DEPTH,  // Per-tile depth for RAM tiling.
  parameter  int WIDTH                  = 32,  // Data width; must be byte-aligned when byte parity
                                               // is enabled.
  parameter  int DATA_BITS_PER_MASK     = 8,  // Must be 8 when byte parity is enabled.
  parameter  bit ENABLE_PARITY          = 0,  // Enables byte parity.

  parameter  int NUM_PRINCE_ROUNDS_HALF = 3,  // PRINCE half-rounds in [1..5]; kept low for latency.
                                              // Original PRINCE uses 5 half-rounds (2*5+1
                                              // effective); 3 is about 7 effective rounds.
  parameter  int NUM_DIFF_ROUNDS        = 0,  // Extra diffusion rounds; 0 disables diffusion.
                                              // Default 0 because non-linear data diffusion
                                              // can interact adversely with end-to-end ECC;
                                              // enable only with full knowledge of that
                                              // interaction (for example with byte parity).
  parameter  int DIFF_WIDTH             = DATA_BITS_PER_MASK,  // Diffusion block width; at least 4,
                                                               // and 8 with parity. Use 8 for
                                                               // intra-byte diffusion.
  parameter  int NUM_ADDR_SCR_ROUNDS    = 2,  // Address scrambling rounds; 0 disables address
                                              // scrambling.
  parameter  bit REPLICATE_KEY_STREAM   = 1'b0,  // 1 replicates the same 64-bit keystream across a
                                                 // wider data port; 0 replicates the cipher with a
                                                 // wider nonce for a unique keystream across the
                                                 // full width.

  parameter type ram_req_t              = prim_ram_1p_adv_ext_req_t,  // External RAM request
                                                                      // struct; may override the
                                                                      // package default.
  parameter type ram_rsp_t              = prim_ram_1p_adv_ext_rsp_t,  // External RAM response
                                                                      // struct; may override the
                                                                      // package default.

  localparam int AddrWidth              = prim_util_pkg::vbits(DEPTH),  // Logical address width; derived.
  localparam int NumParScr              = (REPLICATE_KEY_STREAM) ? 1 : (WIDTH + 63) / 64,  // Parallel PRINCE instances so the keystream covers WIDTH;
                                                                                           // PRINCE block size is 64 bits.
  localparam int NumParKeystr           = (REPLICATE_KEY_STREAM) ? (WIDTH + 63) / 64 : 1,  // Parallel keystream replicas when REPLICATE_KEY_STREAM is set.
  localparam int DataKeyWidth           = 128,  // Scrambling key width from PRINCE; all parallel
                                                // ciphers share the key with different IVs.
  localparam int NonceWidth             = 64 * NumParScr,  // Nonce width; each 64-bit scrambling
                                                           // primitive needs a 64-bit IV.
  localparam int NumRamInst             = prim_util_pkg::ceil_div(DEPTH, INST_DEPTH)  // Number of tiled RAM instances.
) (
  input                                    clk_i,  // Memory clock.
  input                                    rst_ni,  // Async reset, active-low.

  input                                    key_valid_i,  // Scrambling key is live; requests are not
                                                         // granted while low.
  input        [DataKeyWidth-1:0]          key_i,  // Scrambling key.
  input        [NonceWidth-1:0]            nonce_i,  // Scrambling nonce; the top AddrWidth bits key
                                                     // address scrambling and the low bits form the
                                                     // keystream IVs.

  input                                    req_i,  // Unscrambled access request.
  output logic                             gnt_o,  // Request grant; req_i gated combinationally by
                                                   // key_valid_i.
  input                                    write_i,  // Write when high, read when low.
  input        [AddrWidth-1:0]             addr_i,  // Logical address before scramble.
  input        [WIDTH-1:0]                 wdata_i,  // Plaintext write data.
  input        [WIDTH-1:0]                 wmask_i,  // Write mask; must be byte-aligned for parity.
  input                                    intg_error_i,  // Suppresses any real memory transaction
                                                          // on an integrity fault and kills the
                                                          // matching read response.
  output logic [WIDTH-1:0]                 rdata_o,  // Descrambled read data; 0 while rvalid_o is
                                                     // low.
  output logic                             rvalid_o,  // Read response (rdata_o) is valid.
  output logic [1:0]                       rerror_o,  // Bit1 flags a parity error; bit0,
                                                      // correctable, is always 0.
  output logic [AddrWidth-1:0]             raddr_o,  // Unscrambled address of the last granted
                                                     // read, for error reporting.

  output logic                             wr_collision_o,  // Read hits a pending write address;
                                                            // valid with rvalid_o.
  output logic                             write_pending_o,  // High while a write is granted or a
                                                             // delayed write is being committed to
                                                             // memory.

  output logic                             alert_o,  // Invalid MuBi4 encoding on an internal
                                                     // control signal, including those of the inner
                                                     // RAM.

  output ram_req_t         [NumRamInst-1:0] ram_req_o,  // Per-tile external RAM requests from the
                                                        // inner prim_ram_1p_adv_ext.
  input  ram_rsp_t         [NumRamInst-1:0] ram_rsp_i  // Per-tile external RAM responses.
);

  import prim_mubi_pkg::mubi4_t;
  import prim_mubi_pkg::mubi4_and_hi;
  import prim_mubi_pkg::mubi4_bool_to_mubi;
  import prim_mubi_pkg::mubi4_or_hi;
  import prim_mubi_pkg::mubi4_test_invalid;
  import prim_mubi_pkg::mubi4_test_true_loose;
  import prim_mubi_pkg::MuBi4True;
  import prim_mubi_pkg::MuBi4False;
  import prim_mubi_pkg::MuBi4Width;

  //////////////////////
  // Parameter Checks //
  //////////////////////

  // The depth needs to be a power of 2 in case address scrambling is turned on
  `OCAH_ASSERT_STATIC(DepthPow2Check_A, NUM_ADDR_SCR_ROUNDS <= '0 || 2**$clog2(DEPTH) == DEPTH)
  `OCAH_ASSERT_STATIC(DiffWidthMinimum_A, DIFF_WIDTH >= 4)
  `OCAH_ASSERT_STATIC(DiffWidthWithParity_A, ENABLE_PARITY && (DIFF_WIDTH == 8) || !ENABLE_PARITY)

  /////////////////////////////////////////
  // Pending Write and Address Registers //
  /////////////////////////////////////////

  // Writes are delayed by one cycle, such the same keystream generation primitive (prim_prince) can
  // be reused among reads and writes. Note however that with this arrangement, we have to introduce
  // a mechanism to hold a pending write transaction in cases where that transaction is immediately
  // followed by a read. The pending write transaction is written to memory as soon as there is no
  // new read transaction incoming. The latter can be a special case if the incoming read goes to
  // the same address as the pending write. To that end, we detect the address collision and return
  // the data from the write holding register.

  // Read / write strobes
  mubi4_t read_en, read_en_buf;
  logic   read_en_b;
  mubi4_t write_en_d, write_en_buf_d, write_en_q;
  logic   write_en_b;
  logic [MuBi4Width-1:0] read_en_b_buf, write_en_buf_b_d;
  assign gnt_o = req_i & key_valid_i;

  assign read_en = mubi4_bool_to_mubi(gnt_o & ~write_i);
  assign write_en_d = mubi4_bool_to_mubi(gnt_o & write_i);

  prim_buf #(
    .Width(MuBi4Width)
  ) u_read_en_buf (
    .in_i (read_en),
    .out_o(read_en_b_buf)
  );

  assign read_en_buf = mubi4_t'(read_en_b_buf);

  prim_buf #(
    .Width(MuBi4Width)
  ) u_write_en_d_buf (
    .in_i (write_en_d),
    .out_o(write_en_buf_b_d)
  );

  assign write_en_buf_d = mubi4_t'(write_en_buf_b_d);

  mubi4_t write_pending_q;
  mubi4_t addr_collision_d, addr_collision_q;
  logic [AddrWidth-1:0] addr_scr;
  logic [AddrWidth-1:0] waddr_scr_q;
  mubi4_t addr_match;
  logic [MuBi4Width-1:0] addr_match_buf;

  assign addr_match = (addr_scr == waddr_scr_q) ? MuBi4True : MuBi4False;
  prim_buf #(
    .Width(MuBi4Width)
  ) u_addr_match_buf (
    .in_i (addr_match),
    .out_o(addr_match_buf)
  );

  assign addr_collision_d = mubi4_and_hi(mubi4_and_hi(mubi4_or_hi(write_en_q,
      write_pending_q), read_en_buf), mubi4_t'(addr_match_buf));

  // Macro requests and write strobe
  // The macro operation is silenced if an integrity error is seen
  logic intg_error_buf, intg_error_w_q;
  prim_buf u_intg_error (
    .in_i(intg_error_i),
    .out_o(intg_error_buf)
  );
  logic macro_req;
  assign macro_req   = ~intg_error_w_q & ~intg_error_buf &
      mubi4_test_true_loose(mubi4_or_hi(mubi4_or_hi(read_en_buf, write_en_q), write_pending_q));
  // We are allowed to write a pending write transaction to the memory if there is no incoming read.
  logic macro_write;
  assign macro_write = mubi4_test_true_loose(mubi4_or_hi(write_en_q, write_pending_q)) &
    ~mubi4_test_true_loose(read_en_buf) & ~intg_error_w_q;
  // New read write collision
  logic rw_collision;
  assign rw_collision = mubi4_test_true_loose(mubi4_and_hi(write_en_q, read_en_buf));

  // Write currently processed inside this module. Although we are sending an immediate d_valid
  // back to the host, the write could take longer due to the scrambling.
  assign write_pending_o = macro_write | mubi4_test_true_loose(write_en_buf_d);

  // When a read is followed after a write with the same address, we return the data from the
  // holding register.
  assign wr_collision_o = mubi4_test_true_loose(addr_collision_q);

  ////////////////////////
  // Address Scrambling //
  ////////////////////////

  // We only select the pending write address in case there is no incoming read transaction.
  logic [AddrWidth-1:0] addr_mux;
  assign addr_mux = (mubi4_test_true_loose(read_en_buf)) ? addr_scr : waddr_scr_q;

  // This creates a bijective address mapping using a substitution / permutation network.
  if (NUM_ADDR_SCR_ROUNDS > 0) begin : gen_addr_scr
    logic [AddrWidth-1:0] addr_scr_nonce;
    assign addr_scr_nonce = nonce_i[NonceWidth - AddrWidth +: AddrWidth];

    prim_subst_perm #(
      .DataWidth ( AddrWidth           ),
      .NumRounds ( NUM_ADDR_SCR_ROUNDS ),
      .Decrypt   ( 0                   )
    ) u_prim_subst_perm (
      .data_i ( addr_i         ),
      // Since the counter mode concatenates {nonce_i[NonceWidth-1-AddrWidth:0], addr} to form
      // the IV, the upper AddrWidth bits of the nonce are not used and can be used for address
      // scrambling. In cases where N parallel PRINCE blocks are used due to a data
      // width > 64bit, N*AddrWidth nonce bits are left dangling.
      .key_i  ( addr_scr_nonce ),
      .data_o ( addr_scr       )
    );
  end else begin : gen_no_addr_scr
    assign addr_scr = addr_i;
  end

  // We latch the non-scrambled address for error reporting.
  logic [AddrWidth-1:0] raddr_q;
  assign raddr_o = raddr_q;

  //////////////////////////////////////////////
  // Keystream Generation for Data Scrambling //
  //////////////////////////////////////////////

  // This encrypts the IV consisting of the nonce and address using the key provided in order to
  // generate the keystream for the data. Note that we instantiate a register halfway within this
  // primitive to balance the delay between request and response side.
  localparam int DataNonceWidth = 64 - AddrWidth;
  logic [NumParScr*64-1:0] keystream;
  logic [NumParScr-1:0][DataNonceWidth-1:0] data_scr_nonce;
  for (genvar k = 0; k < NumParScr; k++) begin : gen_par_scr
    assign data_scr_nonce[k] = nonce_i[k * DataNonceWidth +: DataNonceWidth];

    prim_prince #(
      .DataWidth      (64),
      .KeyWidth       (128),
      .NumRoundsHalf  (NUM_PRINCE_ROUNDS_HALF),
      .UseOldKeySched (1'b0),
      .HalfwayDataReg (1'b1), // instantiate a register halfway in the primitive
      .HalfwayKeyReg  (1'b0)  // no need to instantiate a key register as the key remains static
    ) u_prim_prince (
      .clk_i,
      .rst_ni,
      .valid_i ( gnt_o ),
      // The IV is composed of a nonce and the row address
      //.data_i  ( {nonce_i[k * (64 - AddrWidth) +: (64 - AddrWidth)], addr} ),
      .data_i  ( {data_scr_nonce[k], addr_i} ),
      // All parallel scramblers use the same key
      .key_i,
      // Since we operate in counter mode, this can always be set to encryption mode
      .dec_i   ( 1'b0 ),
      // Output keystream to be XOR'ed
      .data_o  ( keystream[k * 64 +: 64] ),
      .valid_o ( )
    );

    // Unread unused bits from keystream
    if (k == NumParKeystr-1 && (WIDTH % 64) > 0) begin : gen_unread_last
      localparam int UnusedWidth = 64 - (WIDTH % 64);
      logic [UnusedWidth-1:0] unused_keystream;
      assign unused_keystream = keystream[(k+1) * 64 - 1 -: UnusedWidth];
    end
  end

  // Replicate keystream if needed
  logic [WIDTH-1:0] keystream_repl;
  assign keystream_repl = WIDTH'({NumParKeystr{keystream}});

  /////////////////////
  // Data Scrambling //
  /////////////////////

  // Data scrambling is a two step process. First, we XOR the write data with the keystream obtained
  // by operating a reduced-round PRINCE cipher in CTR-mode. Then, we diffuse data within each byte
  // in order to get a limited "avalanche" behavior in case parts of the bytes are flipped as a
  // result of a malicious attempt to tamper with the data in memory. We perform the diffusion only
  // within bytes in order to maintain the ability to write individual bytes. Note that the
  // keystream XOR is performed first for the write path such that it can be performed last for the
  // read path. This allows us to hide a part of the combinational delay of the PRINCE primitive
  // behind the propagation delay of the SRAM macro and the per-byte diffusion step.

  logic [WIDTH-1:0] rdata_scr, rdata;
  logic [WIDTH-1:0] wdata_scr_d, wdata_scr_q, wdata_q;
  for (genvar k = 0; k < (WIDTH + DIFF_WIDTH - 1) / DIFF_WIDTH; k++) begin : gen_diffuse_data
    // If the WIDTH is not divisible by DIFF_WIDTH, we need to adjust the width of the last slice.
    localparam int LocalWidth = (WIDTH - k * DIFF_WIDTH >= DIFF_WIDTH) ? DIFF_WIDTH :
                                                                         (WIDTH - k * DIFF_WIDTH);

    // Write path. Note that since this does not fan out into the interconnect, the write path is
    // not as critical as the read path below in terms of timing.
    // Apply the keystream first
    logic [LocalWidth-1:0] wdata_xor;
    assign wdata_xor = wdata_q[k*DIFF_WIDTH +: LocalWidth] ^
                       keystream_repl[k*DIFF_WIDTH +: LocalWidth];

    // Byte aligned diffusion using a substitution / permutation network
    prim_subst_perm #(
      .DataWidth ( LocalWidth       ),
      .NumRounds ( NUM_DIFF_ROUNDS ),
      .Decrypt   ( 0                )
    ) u_prim_subst_perm_enc (
      .data_i ( wdata_xor ),
      .key_i  ( '0        ),
      .data_o ( wdata_scr_d[k*DIFF_WIDTH +: LocalWidth] )
    );

    // Read path. This is timing critical. The keystream XOR operation is performed last in order to
    // hide the combinational delay of the PRINCE primitive behind the propagation delay of the
    // SRAM and the byte diffusion.
    // Reverse diffusion first
    logic [LocalWidth-1:0] rdata_xor;
    prim_subst_perm #(
      .DataWidth ( LocalWidth       ),
      .NumRounds ( NUM_DIFF_ROUNDS ),
      .Decrypt   ( 1                )
    ) u_prim_subst_perm_dec (
      .data_i ( rdata_scr[k*DIFF_WIDTH +: LocalWidth] ),
      .key_i  ( '0        ),
      .data_o ( rdata_xor )
    );

    // Apply Keystream, replicate it if needed
    assign rdata[k*DIFF_WIDTH +: LocalWidth] = rdata_xor ^
                                               keystream_repl[k*DIFF_WIDTH +: LocalWidth];
  end

  ////////////////////////////////////////////////
  // Scrambled data register and forwarding mux //
  ////////////////////////////////////////////////

  // This is the scrambled data holding register for pending writes. This is needed in order to make
  // back to back patterns of the form WR -> RD -> WR work:
  //
  // cycle:          0   |  1   | 2   | 3   |
  // incoming op:    WR0 |  RD  | WR1 | -   |
  // prince:         -   |  WR0 | RD  | WR1 |
  // memory op:      -   |  RD  | WR0 | WR1 |
  //
  // The read transaction in cycle 1 interrupts the first write transaction which has already used
  // the PRINCE primitive for scrambling. If this sequence is followed by another write back-to-back
  // in cycle 2, we cannot use the PRINCE primitive a second time for the first write, and hence
  // need an additional holding register that can buffer the scrambled data of the first write in
  // cycle 1.

  // Clear this if we can write the memory in this cycle. Set only if the current write cannot
  // proceed due to an incoming read operation.
  mubi4_t write_scr_pending_d;
  assign write_scr_pending_d = (macro_write)  ? MuBi4False :
                               (rw_collision) ? MuBi4True :
                                                write_pending_q;

  // Select the correct scrambled word to be written, based on whether the word in the scrambled
  // data holding register is valid or not. Note that the write_scr_q register could in theory be
  // combined with the wdata_q register. We don't do that here for timing reasons, since that would
  // require another read data mux to inject the scrambled data into the read descrambling path.
  logic [WIDTH-1:0] wdata_scr;
  assign wdata_scr = (mubi4_test_true_loose(write_pending_q)) ? wdata_scr_q : wdata_scr_d;

  mubi4_t rvalid_q;
  logic intg_error_r_q;
  logic [WIDTH-1:0] wmask_q;
  always_comb begin : p_forward_mux
    rdata_o = '0;
    rvalid_o = 1'b0;
    // Kill the read response in case an integrity error was seen.
    if (!intg_error_r_q && mubi4_test_true_loose(rvalid_q)) begin
      rvalid_o = 1'b1;
      // In case of a collision, we forward the valid bytes of the write data from the unscrambled
      // holding register.
      if (mubi4_test_true_loose(addr_collision_q)) begin
        for (int k = 0; k < WIDTH; k++) begin
          if (wmask_q[k]) begin
            rdata_o[k] = wdata_q[k];
          end else begin
            rdata_o[k] = rdata[k];
          end
        end
      // regular reads. note that we just return zero in case
      // an integrity error was signalled.
      end else begin
        rdata_o = rdata;
      end
    end
  end

  ///////////////
  // Registers //
  ///////////////
  logic ram_alert;

  assign alert_o = mubi4_test_invalid(write_en_q) | mubi4_test_invalid(addr_collision_q) |
                   mubi4_test_invalid(write_pending_q) | mubi4_test_invalid(rvalid_q) |
                   ram_alert;

  prim_flop #(
    .Width(MuBi4Width),
    .ResetValue(MuBi4Width'(MuBi4False))
  ) u_write_en_flop (
    .clk_i,
    .rst_ni,
    .d_i(MuBi4Width'(write_en_buf_d)),
    .q_o({write_en_q})
  );

  prim_flop #(
    .Width(MuBi4Width),
    .ResetValue(MuBi4Width'(MuBi4False))
  ) u_addr_collision_flop (
    .clk_i,
    .rst_ni,
    .d_i(MuBi4Width'(addr_collision_d)),
    .q_o({addr_collision_q})
  );

  prim_flop #(
    .Width(MuBi4Width),
    .ResetValue(MuBi4Width'(MuBi4False))
  ) u_write_pending_flop (
    .clk_i,
    .rst_ni,
    .d_i(MuBi4Width'(write_scr_pending_d)),
    .q_o({write_pending_q})
  );

  prim_flop #(
    .Width(MuBi4Width),
    .ResetValue(MuBi4Width'(MuBi4False))
  ) u_rvalid_flop (
    .clk_i,
    .rst_ni,
    .d_i(MuBi4Width'(read_en_buf)),
    .q_o({rvalid_q})
  );

  assign read_en_b = mubi4_test_true_loose(read_en_buf);
  assign write_en_b = mubi4_test_true_loose(write_en_buf_d);

  always_ff @(posedge clk_i or negedge rst_ni) begin : p_wdata_buf
    if (!rst_ni) begin
      intg_error_r_q      <= 1'b0;
      intg_error_w_q      <= 1'b0;
      raddr_q             <= '0;
      waddr_scr_q         <= '0;
      wmask_q             <= '0;
      wdata_q             <= '0;
      wdata_scr_q         <= '0;
    end else begin
      intg_error_r_q      <= intg_error_buf;

      if (read_en_b) begin
        raddr_q <= addr_i;
      end
      if (write_en_b) begin
        waddr_scr_q    <= addr_scr;
        wmask_q        <= wmask_i;
        wdata_q        <= wdata_i;
        intg_error_w_q <= intg_error_buf;
      end
      if (rw_collision) begin
        wdata_scr_q <= wdata_scr_d;
      end
    end
  end

  //////////////////
  // Memory Macro //
  //////////////////

  prim_ram_1p_adv_ext #(
    .DEPTH(DEPTH),
    .INST_DEPTH(INST_DEPTH),
    .WIDTH(WIDTH),
    .DATA_BITS_PER_MASK(DATA_BITS_PER_MASK),
    .ENABLE_ECC(1'b0),
    .ENABLE_PARITY(ENABLE_PARITY),
    .ENABLE_INPUT_PIPELINE(1'b0),
    .ENABLE_OUTPUT_PIPELINE(1'b0),
    .ram_req_t(ram_req_t),
    .ram_rsp_t(ram_rsp_t)
  ) u_prim_ram_1p_adv_ext (
    .clk_i,
    .rst_ni,
    .req_i    ( macro_req   ),
    .write_i  ( macro_write ),
    .addr_i   ( addr_mux    ),
    .wdata_i  ( wdata_scr   ),
    .wmask_i  ( wmask_q     ),
    .rdata_o  ( rdata_scr   ),
    .rvalid_o ( ),
    .rerror_o,
    .alert_o  ( ram_alert   ),
    .ram_req_o,
    .ram_rsp_i
  );

  `include "prim_util_get_scramble_params.svh"

endmodule : prim_ram_1p_scr_ext
