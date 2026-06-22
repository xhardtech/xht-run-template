// SPDX-License-Identifier: MIT
// (c) 2026 XhardTech
// XTEA block cipher core: encrypts a FIXED 64-bit plaintext under a FIXED 128-bit
// key, one Feistel iteration per clock for the standard 32 rounds.
// Runtime: after rst is released, v0/v1 stream through the rounds; `done` asserts
// once 32 iterations complete and then v0/v1 hold the final ciphertext forever.
`default_nettype none

module xtea64 (
    input  wire        clk,
    input  wire        rst,
    output wire [31:0] v0,
    output wire [31:0] v1,
    output wire        done
);
    // Fixed plaintext block {v0,v1} and 128-bit key as four 32-bit words.
    localparam [31:0] PT0   = 32'h01234567;
    localparam [31:0] PT1   = 32'h89ABCDEF;
    localparam [31:0] K0    = 32'h00000000;
    localparam [31:0] K1    = 32'h00000001;
    localparam [31:0] K2    = 32'h00000002;
    localparam [31:0] K3    = 32'h00000003;
    localparam [31:0] DELTA = 32'h9E3779B9;

    reg [31:0] r_v0;
    reg [31:0] r_v1;
    reg [31:0] r_sum;   // running sum, starts at 0
    reg [5:0]  r_cnt;   // 0..32
    reg        r_done;

    // key word selected by (sum >> 11) & 3
    function [31:0] keysel;
        input [1:0] idx;
        begin
            case (idx)
                2'd0: keysel = K0;
                2'd1: keysel = K1;
                2'd2: keysel = K2;
                default: keysel = K3;
            endcase
        end
    endfunction

    // First half of one XTEA round, using current v0 and sum:
    //   v0 += (((v1<<4) ^ (v1>>5)) + v1) ^ (sum + key[sum & 3]);
    // Second half, using the *new* v0 and updated sum:
    //   sum += delta;
    //   v1 += (((v0<<4) ^ (v0>>5)) + v0) ^ (sum + key[(sum>>11) & 3]);
    wire [31:0] mix0   = (((r_v1 << 4) ^ (r_v1 >> 5)) + r_v1)
                         ^ (r_sum + keysel(r_sum[1:0]));
    wire [31:0] new_v0 = r_v0 + mix0;

    wire [31:0] sum2   = r_sum + DELTA;
    wire [31:0] mix1   = (((new_v0 << 4) ^ (new_v0 >> 5)) + new_v0)
                         ^ (sum2 + keysel(sum2[12:11]));
    wire [31:0] new_v1 = r_v1 + mix1;

    always @(posedge clk) begin
        if (rst) begin
            r_v0   <= PT0;
            r_v1   <= PT1;
            r_sum  <= 32'h00000000;
            r_cnt  <= 6'd0;
            r_done <= 1'b0;
        end else if (r_cnt < 6'd32) begin
            r_v0   <= new_v0;
            r_v1   <= new_v1;
            r_sum  <= sum2;
            r_cnt  <= r_cnt + 6'd1;
            r_done <= (r_cnt == 6'd31);
        end
        // when r_cnt == 32, hold values (ciphertext latched).
    end

    assign v0   = r_v0;
    assign v1   = r_v1;
    assign done = r_done;
endmodule

`default_nettype wire
