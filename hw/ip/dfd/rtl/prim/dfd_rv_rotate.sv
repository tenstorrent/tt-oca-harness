// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//Rotate data based on a pointer.

//ROT_LEFT=1, NUM_IN=3, NUM_OUT=4             ROTATE vs  SHIFT
//DIN[2:0] = {A,B,C} PTR=0  -> DOUT[3:0] = {0,A,B,C};  {0,A,B,C};
//DIN[2:0] = {A,B,C} PTR=1  -> DOUT[3:0] = {A,B,C,0};  {A,B,C,0};
//DIN[2:0] = {A,B,C} PTR=2  -> DOUT[3:0] = {B,C,0,A};  {B,C,0,0};
//DIN[2:0] = {A,B,C} PTR=3  -> DOUT[3:0] = {C,0,A,B};  {C,0,0,0};

//ROT_LEFT=0, NUM_IN=3, NUM_OUT=4             ROTATE vs  SHIFT
//DIN[2:0] = {A,B,C} PTR=0  -> DOUT[3:0] = {0,A,B,C};  {0,A,B,C};
//DIN[2:0] = {A,B,C} PTR=1  -> DOUT[3:0] = {C,0,A,B};  {0,0,A,B};
//DIN[2:0] = {A,B,C} PTR=2  -> DOUT[3:0] = {B,C,0,A};  {0,0,0,A};
//DIN[2:0] = {A,B,C} PTR=3  -> DOUT[3:0] = {A,B,C,0};  {0,0,0,0};


module dfd_rv_rotate
	#(parameter int unsigned NUM_IN   = 6,
		parameter int unsigned NUM_OUT  = 8,
		parameter int unsigned ROT_LEFT = 1,
		parameter int unsigned IS_SHIFT = 0,
		parameter int unsigned DATA_SIZE= 10,

		parameter int unsigned NUM_OUT_ENC_WIDTH = (NUM_OUT == 1) ? 1 : $clog2(NUM_OUT)
	)
	(
		input [NUM_IN-1:0] [DATA_SIZE-1:0]         DataIn,
		input [NUM_OUT_ENC_WIDTH-1:0]              PtrOut,

		output logic [NUM_OUT-1:0] [DATA_SIZE-1:0] DataOut
	);

	logic [2*NUM_OUT-1:0] [DATA_SIZE-1:0]       ConCatData;

	generate
		if(ROT_LEFT) begin: LEFT
			assign ConCatData = (IS_SHIFT ? ($bits(ConCatData))'(DataIn) : {2{{(DATA_SIZE*(NUM_OUT-NUM_IN)){1'b0}},DataIn}}) << (PtrOut * DATA_SIZE);
			assign DataOut    =  IS_SHIFT ? ConCatData[NUM_OUT-1:0]      : ConCatData[2*NUM_OUT-1:NUM_OUT];
		end
		else begin: RIGHT
			assign ConCatData = (IS_SHIFT ? ($bits(ConCatData))'(DataIn) : {2{{(DATA_SIZE*(NUM_OUT-NUM_IN)){1'b0}},DataIn}}) >> (PtrOut * DATA_SIZE);
			assign DataOut    = ConCatData[NUM_OUT-1:0];
		end
	endgenerate

endmodule
// Local Variables:
// verilog-library-directories:("." "../common/")
// verilog-library-extensions:(".sv" ".h" ".v")
// verilog-typedef-regexp: "_[tseu]$"
// End:
