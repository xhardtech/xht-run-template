// SPDX-License-Identifier: MIT
// (c) 2026 XhardTech
// rv32i_min: an educational MINIMAL single-cycle RV32I CPU running an INLINE
//   program ROM. The program computes sum(1..10)=55 via an ADDI/ADD loop with a
//   backward BNE branch, then halts in a BEQ self-loop.
// Runtime: after a few clocks `result` settles to 55 (x1) and `pc` settles to 24.
//   Supported subset: LUI, ADDI, ADD, BEQ, BNE. x0 is hardwired to 0.

`default_nettype none

module rv32i_min(
    input  wire        clk,
    input  wire        rst,
    output wire [31:0] result,
    output wire [31:0] pc
);
    // ---- program counter ----
    reg [31:0] pc_r;
    assign pc = pc_r;

    // ---- inline instruction ROM (word-addressed) ----
    reg [31:0] rom [0:7];
    initial begin
        rom[0] = 32'h00000093; // addi x1,x0,0    ; sum  = 0
        rom[1] = 32'h00000113; // addi x2,x0,0    ; i    = 0
        rom[2] = 32'h00a00193; // addi x3,x0,10   ; lim  = 10
        rom[3] = 32'h00110113; // addi x2,x2,1    ; i   += 1   (loop)
        rom[4] = 32'h002080b3; // add  x1,x1,x2   ; sum += i
        rom[5] = 32'hfe311ce3; // bne  x2,x3,-8   ; if i!=lim goto loop
        rom[6] = 32'h00000063; // beq  x0,x0,0    ; halt self-loop
        rom[7] = 32'h00000013; // addi x0,x0,0    ; nop (pad)
    end

    // ---- fetch ----
    wire [31:0] instr = rom[pc_r[4:2]]; // 8 words, byte pc -> word index

    // ---- decode ----
    wire [6:0]  opcode = instr[6:0];
    wire [4:0]  rd     = instr[11:7];
    wire [2:0]  funct3 = instr[14:12];
    wire [4:0]  rs1    = instr[19:15];
    wire [4:0]  rs2    = instr[24:20];
    wire [6:0]  funct7 = instr[31:25];

    wire [31:0] imm_i = {{20{instr[31]}}, instr[31:20]};
    wire [31:0] imm_u = {instr[31:12], 12'b0};
    wire [31:0] imm_b = {{19{instr[31]}}, instr[31], instr[7],
                         instr[30:25], instr[11:8], 1'b0};

    // ---- register file (x0 == 0) ----
    reg [31:0] regs [0:31];
    integer k;
    initial for (k = 0; k < 32; k = k + 1) regs[k] = 32'b0;

    wire [31:0] rv1 = (rs1 == 5'd0) ? 32'b0 : regs[rs1];
    wire [31:0] rv2 = (rs2 == 5'd0) ? 32'b0 : regs[rs2];

    // ---- opcodes ----
    localparam OP_LUI    = 7'b0110111;
    localparam OP_OPIMM  = 7'b0010011; // ADDI
    localparam OP_OP     = 7'b0110011; // ADD
    localparam OP_BRANCH = 7'b1100011; // BEQ/BNE

    // ---- ALU / writeback value ----
    reg [31:0] wb_val;
    reg        wb_en;
    always @(*) begin
        wb_val = 32'b0;
        wb_en  = 1'b0;
        case (opcode)
            OP_LUI: begin
                wb_val = imm_u;
                wb_en  = 1'b1;
            end
            OP_OPIMM: begin // funct3==000 ADDI
                wb_val = rv1 + imm_i;
                wb_en  = (funct3 == 3'b000);
            end
            OP_OP: begin // funct3==000, funct7==0 ADD
                wb_val = rv1 + rv2;
                wb_en  = (funct3 == 3'b000) && (funct7 == 7'b0000000);
            end
            default: begin
                wb_val = 32'b0;
                wb_en  = 1'b0;
            end
        endcase
    end

    // ---- branch decision ----
    reg taken;
    always @(*) begin
        taken = 1'b0;
        if (opcode == OP_BRANCH) begin
            case (funct3)
                3'b000: taken = (rv1 == rv2);   // BEQ
                3'b001: taken = (rv1 != rv2);   // BNE
                default: taken = 1'b0;
            endcase
        end
    end

    wire [31:0] pc_next = taken ? (pc_r + imm_b) : (pc_r + 32'd4);

    // ---- sequential update ----
    always @(posedge clk) begin
        if (rst) begin
            pc_r <= 32'b0;
        end else begin
            if (wb_en && (rd != 5'd0))
                regs[rd] <= wb_val;
            pc_r <= pc_next;
        end
    end

    // expose x1 (the running sum) as the result
    assign result = regs[1];

endmodule

`default_nettype wire