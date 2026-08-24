// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Find's first N Set, In parallel can pulls out data, gets N one-hot vectors, and also performs encode of those N set bits.
module dfd_rv_ffsN#(parameter DIR_L2H    = 1,              //Direction of Priority
                parameter WIDTH      = 8,              //Number of inputs.
                parameter SIZE       = ($clog2(WIDTH) > 1 ? $clog2(WIDTH) : 1), //Log2 Number of inputs
                parameter DATA_WIDTH = 4,              //Width of data  
                parameter NUM_SEL    = 3)              //Number of muxed outputs   (
   
   (input  [WIDTH-1:0]                         req_in,
    input [WIDTH-1:0] [DATA_WIDTH-1:0]         data_in,
    
    output logic [NUM_SEL-1:0]                 req_sum,
    output logic [NUM_SEL-1:0][DATA_WIDTH-1:0] data_out,
    output logic [NUM_SEL-1:0][WIDTH-1:0]      req_out,
    output logic [NUM_SEL-1:0][SIZE-1:0]       enc_req_out);
   
   localparam INIT_IDX  =  DIR_L2H ? 0 : NUM_SEL-1;
   //localparam PAD_WIDTH = 1 << $clog2(WIDTH);
   localparam PAD_WIDTH = 1 << SIZE;
   
   //This needs to be a complete binary tree, therefore add padding internally.
   logic [PAD_WIDTH-1:0][DATA_WIDTH-1:0] pad_data_in;
   logic [PAD_WIDTH-1:0]                 pad_req_in;

   generate
      if(WIDTH != PAD_WIDTH) begin
         assign pad_data_in = {{(PAD_WIDTH-WIDTH)*DATA_WIDTH{1'bx}},data_in};
         assign pad_req_in  = {{(PAD_WIDTH-WIDTH){1'b0}},req_in};
      end else begin
         assign pad_data_in = {data_in};
         assign pad_req_in  = {req_in};
      end               
   endgenerate

   logic [1:0][PAD_WIDTH-1:0][NUM_SEL-1:0][DATA_WIDTH-1:0] data_mux;
   logic [1:0][PAD_WIDTH-1:0][NUM_SEL-1:0][PAD_WIDTH-1:0]  req_mux;
   logic [1:0][PAD_WIDTH-1:0][NUM_SEL-1:0][SIZE-1:0]  enc_req_mux;
   logic [1:0][PAD_WIDTH-1:0][NUM_SEL-1:0]  sum;
   
   assign data_out   [NUM_SEL-1:0] = data_mux [0][0][NUM_SEL-1:0];
   //assign req_out    [NUM_SEL-1:0] = req_mux    [0][0][NUM_SEL-1:0][WIDTH-1:0];
   assign enc_req_out[NUM_SEL-1:0] = enc_req_mux[0][0][NUM_SEL-1:0];
   assign req_sum    [NUM_SEL-1:0] = sum [0][0];  
   always_comb for(int i=0;i<NUM_SEL;i++) req_out[i] = req_mux [0][0][i][WIDTH-1:0];
     
   //Initialize leaf's of tree to data_in
   // spyglass disable_block W415a
   always_comb begin
        automatic int MAX_BKT_LOWER_LVL, MAX_BKT_CURR_LVL, NODE, LVL;
        automatic int unsigned LVL_CURR, LVL_PREV, LVL_START;

        data_mux    = '0;
        req_mux     = '0;
        sum         = '0;
        enc_req_mux = '0;

        LVL_START = (SIZE % 2 == 0)? 0 : 1; 
        for(int i=0;i<PAD_WIDTH;i++) begin
            data_mux   [(1)'(LVL_START)][i][0]                = pad_data_in[i];
            req_mux    [(1)'(LVL_START)][i][0][PAD_WIDTH-1:0] = PAD_WIDTH'(pad_req_in [i]);
            sum        [(1)'(LVL_START)][i][0]                = pad_req_in [i];
        end
        
        for(LVL=SIZE-1; LVL>=0; LVL--) begin
            MAX_BKT_LOWER_LVL            = ((1 << SIZE-LVL-1) >  NUM_SEL) ? NUM_SEL : (1 << (SIZE-LVL-1)); //spyglass disable W316 
            MAX_BKT_CURR_LVL             = ((MAX_BKT_LOWER_LVL * 2) >  NUM_SEL) ? NUM_SEL : (MAX_BKT_LOWER_LVL * 2); //spyglass disable W316 
            LVL_CURR = 32'(LVL % 2); 
            LVL_PREV = 32'((LVL + 1 ) % 2); 

            for(NODE=0; NODE < (1 << LVL); NODE++) begin
                  automatic int unsigned R, L;

                  automatic logic [NUM_SEL-1:0][DATA_WIDTH-1:0] data_mux_nodeR    , data_mux_nodeL   ;
                  automatic logic [NUM_SEL-1:0][PAD_WIDTH-1:0]  req_mux_nodeR     , req_mux_nodeL    ;
                  automatic logic [NUM_SEL-1:0][SIZE-1:0]       enc_req_mux_nodeR , enc_req_mux_nodeL;
                  automatic logic [NUM_SEL-1:0]                 sum_nodeR         , sum_nodeL        ;

                  automatic logic [NUM_SEL-1:0][PAD_WIDTH-1:0]  req_mux_nodeR_upd    , req_mux_nodeL_upd    ;
                  automatic logic [NUM_SEL-1:0][SIZE-1:0]       enc_req_mux_nodeR_upd, enc_req_mux_nodeL_upd;

                  automatic logic [NUM_SEL-1:0][DATA_WIDTH-1:0] data_mux_tmp      ;
                  automatic logic [NUM_SEL-1:0][PAD_WIDTH-1:0]  req_mux_tmp       ;
                  automatic logic [NUM_SEL-1:0][SIZE-1:0]       enc_req_mux_tmp   ;
                  automatic logic [NUM_SEL-1:0]                 sum_tmp           ;

                  R = 2 * NODE + int'(DIR_L2H);
                  L = 2 * NODE + int'(!DIR_L2H);

                  data_mux_nodeR    = data_mux   [(1)'(LVL_PREV)][($clog2(PAD_WIDTH))'(R)];
                  req_mux_nodeR     = req_mux    [(1)'(LVL_PREV)][($clog2(PAD_WIDTH))'(R)];
                  enc_req_mux_nodeR = enc_req_mux[(1)'(LVL_PREV)][($clog2(PAD_WIDTH))'(R)];
                  sum_nodeR         = sum        [(1)'(LVL_PREV)][($clog2(PAD_WIDTH))'(R)];

                  data_mux_nodeL    = data_mux   [(1)'(LVL_PREV)][($clog2(PAD_WIDTH))'(L)];
                  req_mux_nodeL     = req_mux    [(1)'(LVL_PREV)][($clog2(PAD_WIDTH))'(L)];
                  enc_req_mux_nodeL = enc_req_mux[(1)'(LVL_PREV)][($clog2(PAD_WIDTH))'(L)];
                  sum_nodeL         = sum        [(1)'(LVL_PREV)][($clog2(PAD_WIDTH))'(L)];

                  for(int i=0; i < NUM_SEL; i++) begin:REQ_UPD
                     req_mux_nodeR_upd    [i] = req_mux_nodeR     [i] << (DIR_L2H << (SIZE-LVL-1));
                     enc_req_mux_nodeR_upd[i] = enc_req_mux_nodeR [i] | SIZE'(DIR_L2H << (SIZE-1-LVL));
                     req_mux_nodeL_upd    [i] = req_mux_nodeL     [i] << ((DIR_L2H ? 0 : 1) << (SIZE-LVL-1));
                     enc_req_mux_nodeL_upd[i] = enc_req_mux_nodeL [i] | SIZE'(!DIR_L2H) << (SIZE-1-LVL);
                  end

                  req_mux_tmp        = '0;  
                  data_mux_tmp       = 'x;
                  enc_req_mux_tmp    = '0;
                  sum_tmp            = '0;

                  // Set nodeR as the base
                  for(int bktr=0; bktr < NUM_SEL; bktr++) begin:BKT_DEF
                     if (bktr < MAX_BKT_LOWER_LVL) begin
                        req_mux_tmp    [bktr] =  req_mux_nodeR_upd    [bktr];
                        data_mux_tmp   [bktr] =  data_mux_nodeR       [bktr];
                        enc_req_mux_tmp[bktr] =  enc_req_mux_nodeR_upd[bktr];
                        sum_tmp        [bktr] =  sum_nodeR            [bktr];
                     end
                  end

                  for(int bktl=0; bktl < NUM_SEL; bktl++) begin:BKT_RGT
                     if (bktl < MAX_BKT_LOWER_LVL) begin
                        if(sum_nodeL[bktl]) begin
                           // Copy nodeL, [bktl-1:0] does not need to be updated here because sum_nodeL is always filled from the LSB side.
                           req_mux_tmp[bktl]     = req_mux_nodeL_upd    [bktl];
                           data_mux_tmp[bktl]    = data_mux_nodeL       [bktl];
                           enc_req_mux_tmp[bktl] = enc_req_mux_nodeL_upd[bktl];
                           sum_tmp[bktl]         = sum_nodeL            [bktl];

                           // Copy shifted nodeR
                           for(int bktsft=bktl+1; bktsft < NUM_SEL; bktsft++) begin
                              if (bktsft < MAX_BKT_CURR_LVL) begin
                                 req_mux_tmp[bktsft]     = req_mux_nodeR_upd    [bktsft-bktl-1];
                                 data_mux_tmp[bktsft]    = data_mux_nodeR       [bktsft-bktl-1];
                                 enc_req_mux_tmp[bktsft] = enc_req_mux_nodeR_upd[bktsft-bktl-1];
                                 sum_tmp[bktsft]         = sum_nodeR            [bktsft-bktl-1];
                              end
                           end
                        end
                     end
                  end

                  req_mux    [(1)'(LVL_CURR)][NODE] = req_mux_tmp    ;            
                  data_mux   [(1)'(LVL_CURR)][NODE] = data_mux_tmp   ;           
                  enc_req_mux[(1)'(LVL_CURR)][NODE] = enc_req_mux_tmp;           
                  sum        [(1)'(LVL_CURR)][NODE] = sum_tmp        ;

                  //$display("%h",data_mux);
                  //$display("LVL %d, NODE %d, MAX_BKT_AT_LVL %d, data_mux %h",LVL,2*NODE+!DIR_L2H,MAX_BKT_AT_LVL,req_mux[LVL][NODE][bkt]);
            end //for NODE
        end //for LVL
      end //always_comb

   // spyglass enable_block W415a
endmodule
// Local Variables:
// verilog-library-directories:(".")
// verilog-library-extensions:(".sv" ".h" ".v")
// verilog-typedef-regexp: "_[tseu]$"
// End:

