// SPDX-License-Identifier: MIT
// (c) 2026 XhardTech
//
// uart_echo: a byte-level UART console for a browser RTL-simulation terminal.
//
// Expected behavior:
//   After synchronous reset is released, the module streams a fixed BANNER
//   one byte per clock cycle (uart_tx_valid high, uart_tx = char), exactly
//   once. Once the banner is fully sent, on every cycle where uart_rx_valid
//   is high it echoes the received byte back out (uart_tx <= uart_rx,
//   uart_tx_valid high for that single cycle). uart_tx_valid is only ever a
//   single-cycle pulse.

`default_nettype none

module uart_echo(
    input  wire       clk,
    input  wire       rst,            // active-high synchronous reset
    input  wire       uart_rx_valid,  // host asserts for 1 cycle when uart_rx holds a byte
    input  wire [7:0] uart_rx,        // the received byte
    output reg        uart_tx_valid,  // assert for exactly 1 cycle when uart_tx holds a byte
    output reg  [7:0] uart_tx         // the byte to print
);

    localparam integer BANNER_LEN = 106; // 105 chars + 1 terminator
    reg [7:0] banner [0:BANNER_LEN-1];

    initial begin
        banner[  0]=8'h3D; banner[  1]=8'h3D; banner[  2]=8'h3D; banner[  3]=8'h20;
        banner[  4]=8'h58; banner[  5]=8'h68; banner[  6]=8'h61; banner[  7]=8'h72;
        banner[  8]=8'h64; banner[  9]=8'h54; banner[ 10]=8'h65; banner[ 11]=8'h63;
        banner[ 12]=8'h68; banner[ 13]=8'h20; banner[ 14]=8'h52; banner[ 15]=8'h54;
        banner[ 16]=8'h4C; banner[ 17]=8'h20; banner[ 18]=8'h74; banner[ 19]=8'h65;
        banner[ 20]=8'h72; banner[ 21]=8'h6D; banner[ 22]=8'h69; banner[ 23]=8'h6E;
        banner[ 24]=8'h61; banner[ 25]=8'h6C; banner[ 26]=8'h20; banner[ 27]=8'h20;
        banner[ 28]=8'h28; banner[ 29]=8'h56; banner[ 30]=8'h65; banner[ 31]=8'h72;
        banner[ 32]=8'h69; banner[ 33]=8'h6C; banner[ 34]=8'h61; banner[ 35]=8'h74;
        banner[ 36]=8'h6F; banner[ 37]=8'h72; banner[ 38]=8'h20; banner[ 39]=8'h2D;
        banner[ 40]=8'h3E; banner[ 41]=8'h20; banner[ 42]=8'h57; banner[ 43]=8'h41;
        banner[ 44]=8'h53; banner[ 45]=8'h4D; banner[ 46]=8'h2C; banner[ 47]=8'h20;
        banner[ 48]=8'h69; banner[ 49]=8'h6E; banner[ 50]=8'h20; banner[ 51]=8'h79;
        banner[ 52]=8'h6F; banner[ 53]=8'h75; banner[ 54]=8'h72; banner[ 55]=8'h20;
        banner[ 56]=8'h62; banner[ 57]=8'h72; banner[ 58]=8'h6F; banner[ 59]=8'h77;
        banner[ 60]=8'h73; banner[ 61]=8'h65; banner[ 62]=8'h72; banner[ 63]=8'h29;
        banner[ 64]=8'h20; banner[ 65]=8'h3D; banner[ 66]=8'h3D; banner[ 67]=8'h3D;
        banner[ 68]=8'h0D; banner[ 69]=8'h0A; banner[ 70]=8'h54; banner[ 71]=8'h79;
        banner[ 72]=8'h70; banner[ 73]=8'h65; banner[ 74]=8'h20; banner[ 75]=8'h62;
        banner[ 76]=8'h65; banner[ 77]=8'h6C; banner[ 78]=8'h6F; banner[ 79]=8'h77;
        banner[ 80]=8'h20; banner[ 81]=8'h61; banner[ 82]=8'h6E; banner[ 83]=8'h64;
        banner[ 84]=8'h20; banner[ 85]=8'h69; banner[ 86]=8'h74; banner[ 87]=8'h20;
        banner[ 88]=8'h65; banner[ 89]=8'h63; banner[ 90]=8'h68; banner[ 91]=8'h6F;
        banner[ 92]=8'h65; banner[ 93]=8'h73; banner[ 94]=8'h20; banner[ 95]=8'h62;
        banner[ 96]=8'h61; banner[ 97]=8'h63; banner[ 98]=8'h6B; banner[ 99]=8'h2E;
        banner[100]=8'h0D; banner[101]=8'h0A; banner[102]=8'h3E; banner[103]=8'h20;
        banner[104]=8'h00; banner[105]=8'h00;
    end

    localparam S_BANNER = 1'b0, S_ECHO = 1'b1;
    reg                        state;
    reg [$clog2(BANNER_LEN):0] idx;

    always @(posedge clk) begin
        if (rst) begin
            state <= S_BANNER; idx <= 0; uart_tx_valid <= 1'b0; uart_tx <= 8'h00;
        end else begin
            uart_tx_valid <= 1'b0;
            case (state)
                S_BANNER: begin
                    if (banner[idx] == 8'h00) state <= S_ECHO;
                    else begin uart_tx <= banner[idx]; uart_tx_valid <= 1'b1; idx <= idx + 1'b1; end
                end
                S_ECHO: if (uart_rx_valid) begin uart_tx <= uart_rx; uart_tx_valid <= 1'b1; end
                default: state <= S_ECHO;
            endcase
        end
    end
endmodule
`default_nettype wire
