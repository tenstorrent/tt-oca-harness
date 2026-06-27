// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

// Fast Find First Set - parallel logic
// This can really help if the lsb/msb bits (depending on if you are searching L2H/H2L)
// are available early, as they fanout to every other bit output
// If you need something that is more balanced, use the regular dfd_rv_ffs although that can get slower compared to this optimization

module dfd_rv_ffs_fast #(parameter DIR_L2H    = 1,              //Direction of Priority L2H=1 finds lsb's, L2H=0 finds msb
		parameter WIDTH      = 8,              //Number of inputs.
		parameter SIZE       = $clog2(WIDTH),  //Log2 Number of inputs
		parameter DATA_WIDTH = 4)              //Width of data
	(input [WIDTH-1:0]                  req_in,
		input [WIDTH-1:0][DATA_WIDTH-1:0]  data_in,

		output logic [DATA_WIDTH-1:0]      data_out,
		output logic [WIDTH-1:0]           req_out,
		output logic [WIDTH-1:0]           req_out_therm,
		output logic [SIZE-1:0]            enc_req_out
	);


	logic [WIDTH-1:0][SIZE-1:0] enc_req;
	logic preORTerm;

	// spyglass disable_block W415a
	if (DIR_L2H) begin
		always_comb begin
			req_out[0] = req_in[0];
			req_out_therm[0] = req_in[0];
			enc_req[0] = '0;
			preORTerm = 1'b0;
			for(int i=1;i<WIDTH;i++) begin
				preORTerm = preORTerm | req_in[i-1];
				req_out[i] = req_in[i] & ~preORTerm;
				req_out_therm[i] = req_in[i] | preORTerm;
				enc_req[i] = SIZE'(i);
			end
		end
	end
	else begin
		always_comb begin
			req_out[WIDTH-1] = req_in[WIDTH-1];
			req_out_therm[WIDTH-1] = req_in[WIDTH-1];
			enc_req[WIDTH-1] = SIZE'(WIDTH-1);
			preORTerm = 1'b0;
			for(int i=WIDTH-2;i>=0;i--) begin
				preORTerm = preORTerm | req_in[i+1];
				req_out[i] = req_in[i] & ~preORTerm;
				req_out_therm[i] = req_in[i] | preORTerm;
				enc_req[i] = SIZE'(i);
			end
		end
	end

	always_comb begin
		data_out[DATA_WIDTH-1:0] = '0;
		enc_req_out[SIZE-1:0] = '0;
		for(int i=0;i<WIDTH;i++) begin
			data_out[DATA_WIDTH-1:0] = req_out[i] ? data_in[i][DATA_WIDTH-1:0] : data_out[DATA_WIDTH-1:0];
			enc_req_out[SIZE-1:0] = req_out[i] ? enc_req[i][SIZE-1:0] : enc_req_out[SIZE-1:0];
		end
	end
	// spyglass enable_block W415a
endmodule
// Local Variables:
// verilog-library-directories:(".")
// verilog-library-extensions:(".sv" ".h" ".v")
// verilog-typedef-regexp: "_[tseu]$"
// End:
