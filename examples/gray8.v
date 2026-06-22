// SPDX-License-Identifier: MIT
// (c) 2026 XhardTech
// 8-bit Gray-code counter: keeps a binary counter, outputs bin and its Gray code.
// Runtime: on each clk rising edge (rst low), bin increments and gray = bin ^ (bin>>1).
`default_nettype none
module gray8(
    input  wire       clk,
    input  wire       rst,
    output wire [7:0] gray,
    output reg  [7:0] bin
);
    always @(posedge clk) begin
        if (rst)
            bin <= 8'd0;
        else
            bin <= bin + 8'd1;
    end
    assign gray = bin ^ (bin >> 1);
endmodule
`default_nettype wire
