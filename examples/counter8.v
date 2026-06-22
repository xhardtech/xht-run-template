// SPDX-License-Identifier: MIT
// (c) 2026 XhardTech
// 8-bit up-counter with count-enable.
// Behavior: on rst count<=0; else if en, count<=count+1 each clk.
//   After rst then en=1 for K cycles, count == K (mod 256).
`default_nettype none
module counter8(
    input  wire       clk,
    input  wire       rst,
    input  wire       en,
    output reg  [7:0] count
);
    always @(posedge clk) begin
        if (rst)
            count <= 8'd0;
        else if (en)
            count <= count + 8'd1;
    end
endmodule
`default_nettype wire
