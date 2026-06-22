`default_nettype none
// 8-bit Fibonacci LFSR — a clean 3rd test design for the Actions WASM build pipeline.
module lfsr8 (input wire clk, input wire rst, output wire [7:0] lfsr);
    reg [7:0] r;
    always @(posedge clk)
        if (rst) r <= 8'h01;
        else     r <= {r[6:0], r[7]^r[5]^r[4]^r[3]};
    assign lfsr = r;
endmodule
`default_nettype wire
