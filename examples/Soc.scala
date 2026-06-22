//> using scala "2.13.14"
//> using dep "org.chipsalliance::chisel:6.6.0"
//> using plugin "org.chipsalliance:::chisel-plugin:6.6.0"

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage

// ---------------------------------------------------------------------------
// Tiny RV32I assembler (host-side, in Scala) used to build the ROM image.
// Produces 32-bit little-endian instruction words.
// ---------------------------------------------------------------------------
object Asm {
  // register helpers
  val zero = 0; val ra = 1; val sp = 2; val gp = 3; val tp = 4
  val t0 = 5; val t1 = 6; val t2 = 7
  val s0 = 8; val s1 = 9
  val a0 = 10; val a1 = 11; val a2 = 12; val a3 = 13; val a4 = 14; val a5 = 15

  private def u(x: Long, hi: Int, lo: Int): Long = (x >> lo) & ((1L << (hi - lo + 1)) - 1)

  // R-type
  def rtype(funct7: Int, rs2: Int, rs1: Int, funct3: Int, rd: Int, opcode: Int): Long =
    ((funct7 & 0x7f).toLong << 25) | ((rs2 & 0x1f).toLong << 20) | ((rs1 & 0x1f).toLong << 15) |
      ((funct3 & 0x7).toLong << 12) | ((rd & 0x1f).toLong << 7) | (opcode & 0x7f).toLong

  // I-type
  def itype(imm: Int, rs1: Int, funct3: Int, rd: Int, opcode: Int): Long =
    ((imm & 0xfff).toLong << 20) | ((rs1 & 0x1f).toLong << 15) |
      ((funct3 & 0x7).toLong << 12) | ((rd & 0x1f).toLong << 7) | (opcode & 0x7f).toLong

  // S-type
  def stype(imm: Int, rs2: Int, rs1: Int, funct3: Int, opcode: Int): Long = {
    val i = imm & 0xfff
    (u(i, 11, 5) << 25) | ((rs2 & 0x1f).toLong << 20) | ((rs1 & 0x1f).toLong << 15) |
      ((funct3 & 0x7).toLong << 12) | (u(i, 4, 0) << 7) | (opcode & 0x7f).toLong
  }

  // B-type
  def btype(imm: Int, rs2: Int, rs1: Int, funct3: Int, opcode: Int): Long = {
    val i = imm & 0x1fff
    (u(i, 12, 12) << 31) | (u(i, 10, 5) << 25) | ((rs2 & 0x1f).toLong << 20) |
      ((rs1 & 0x1f).toLong << 15) | ((funct3 & 0x7).toLong << 12) |
      (u(i, 4, 1) << 8) | (u(i, 11, 11) << 7) | (opcode & 0x7f).toLong
  }

  // U-type
  def utype(imm: Int, rd: Int, opcode: Int): Long =
    ((imm.toLong & 0xfffff) << 12) | ((rd & 0x1f).toLong << 7) | (opcode & 0x7f).toLong

  // J-type
  def jtype(imm: Int, rd: Int, opcode: Int): Long = {
    val i = imm & 0x1fffff
    (u(i, 20, 20) << 31) | (u(i, 10, 1) << 21) | (u(i, 11, 11) << 20) |
      (u(i, 19, 12) << 12) | ((rd & 0x1f).toLong << 7) | (opcode & 0x7f).toLong
  }

  // Instruction mnemonics ---------------------------------------------------
  def LUI(rd: Int, imm20: Int)   = utype(imm20, rd, 0x37)
  def AUIPC(rd: Int, imm20: Int) = utype(imm20, rd, 0x17)
  def JAL(rd: Int, off: Int)     = jtype(off, rd, 0x6f)
  def JALR(rd: Int, rs1: Int, imm: Int) = itype(imm, rs1, 0x0, rd, 0x67)

  def BEQ(rs1: Int, rs2: Int, off: Int) = btype(off, rs2, rs1, 0x0, 0x63)
  def BNE(rs1: Int, rs2: Int, off: Int) = btype(off, rs2, rs1, 0x1, 0x63)
  def BLT(rs1: Int, rs2: Int, off: Int) = btype(off, rs2, rs1, 0x4, 0x63)
  def BGE(rs1: Int, rs2: Int, off: Int) = btype(off, rs2, rs1, 0x5, 0x63)

  def LB (rd: Int, rs1: Int, imm: Int) = itype(imm, rs1, 0x0, rd, 0x03)
  def LBU(rd: Int, rs1: Int, imm: Int) = itype(imm, rs1, 0x4, rd, 0x03)
  def LW (rd: Int, rs1: Int, imm: Int) = itype(imm, rs1, 0x2, rd, 0x03)
  def SB (rs2: Int, rs1: Int, imm: Int) = stype(imm, rs2, rs1, 0x0, 0x23)
  def SW (rs2: Int, rs1: Int, imm: Int) = stype(imm, rs2, rs1, 0x2, 0x23)

  def ADDI(rd: Int, rs1: Int, imm: Int) = itype(imm, rs1, 0x0, rd, 0x13)
  def ANDI(rd: Int, rs1: Int, imm: Int) = itype(imm, rs1, 0x7, rd, 0x13)
  def ORI (rd: Int, rs1: Int, imm: Int) = itype(imm, rs1, 0x6, rd, 0x13)
  def XORI(rd: Int, rs1: Int, imm: Int) = itype(imm, rs1, 0x4, rd, 0x13)
  def SLLI(rd: Int, rs1: Int, sh: Int)  = itype(sh & 0x1f, rs1, 0x1, rd, 0x13)
  def SRLI(rd: Int, rs1: Int, sh: Int)  = itype(sh & 0x1f, rs1, 0x5, rd, 0x13)

  def ADD(rd: Int, rs1: Int, rs2: Int) = rtype(0x00, rs2, rs1, 0x0, rd, 0x33)
  def SUB(rd: Int, rs1: Int, rs2: Int) = rtype(0x20, rs2, rs1, 0x0, rd, 0x33)
  def AND(rd: Int, rs1: Int, rs2: Int) = rtype(0x00, rs2, rs1, 0x7, rd, 0x33)
  def OR (rd: Int, rs1: Int, rs2: Int) = rtype(0x00, rs2, rs1, 0x6, rd, 0x33)
  def XOR(rd: Int, rs1: Int, rs2: Int) = rtype(0x00, rs2, rs1, 0x4, rd, 0x33)
}

// ---------------------------------------------------------------------------
// Program builder: produces (romWords, dmemBytes).
// Memory map:
//   ROM   (instruction fetch) : starts at PC=0
//   DMEM  (data RAM)          : base 0x2000_0000, holds banner string
//   UART  : base 0x1000_0000
//      SW  to 0x1000_0000 -> transmit byte
//      LW  from 0x1000_0004 -> status, bit0 = rx byte available
//      LW  from 0x1000_0000 -> rx byte (and clears available)
// ---------------------------------------------------------------------------
object Program {
  import Asm._

  val BANNER = "XhardTech RV32 SoC (Chisel) booting...\r\nhart0: online. type to echo.\r\n> "

  val DMEM_BASE  = 0x20000000
  val UART_BASE  = 0x10000000

  // Build the instruction stream. We track instruction index so we can
  // compute relative branch/jump offsets in bytes.
  def build(): (Seq[Long], Seq[Byte]) = {
    val insns = scala.collection.mutable.ArrayBuffer[Long]()
    def emit(w: Long): Int = { val idx = insns.length; insns += (w & 0xffffffffL); idx }
    def pcOf(idx: Int): Int = idx * 4

    // Registers used:
    //   s0 = DMEM base (banner pointer base)
    //   s1 = UART base
    //   a0 = current char pointer
    //   a1 = loaded byte
    //   a2 = scratch / status

    // ---- setup: s0 = DMEM_BASE, s1 = UART_BASE ----
    // Load 32-bit constants via LUI + ADDI (account for sign-extension of ADDI imm).
    def li(rd: Int, value: Int): Unit = {
      val lo = value & 0xfff
      val hi = if ((lo & 0x800) != 0) (value >>> 12) + 1 else (value >>> 12)
      emit(LUI(rd, hi & 0xfffff))
      emit(ADDI(rd, rd, sign12(lo)))
    }
    def sign12(x: Int): Int = if ((x & 0x800) != 0) x | 0xfffff000 else x

    li(s0, DMEM_BASE)
    li(s1, UART_BASE)

    // a0 = s0 (banner pointer)
    emit(ADDI(a0, s0, 0))

    // ---- print loop ----
    // loop_print:
    val loopPrint = insns.length
    emit(LBU(a1, a0, 0))                 // a1 = mem[a0]
    // if a1 == 0 goto done_print  (forward branch, patch later)
    val bEqIdx = emit(0)                  // placeholder BEQ a1, zero, doneOff
    emit(SW(a1, s1, 0))                  // uart_tx = a1
    emit(ADDI(a0, a0, 1))                // a0++
    // goto loop_print
    val jBackIdx = emit(0)                // placeholder JAL zero, loopPrint
    // done_print:
    val donePrint = insns.length

    // patch BEQ (from bEqIdx to donePrint)
    insns(bEqIdx) = BEQ(a1, zero, pcOf(donePrint) - pcOf(bEqIdx))
    // patch JAL back to loopPrint
    insns(jBackIdx) = JAL(zero, pcOf(loopPrint) - pcOf(jBackIdx))

    // ---- echo loop ----
    // loop_echo:
    val loopEcho = insns.length
    emit(LW(a2, s1, 4))                  // a2 = uart status
    emit(ANDI(a2, a2, 1))                // a2 = a2 & 1
    val bEcho = emit(0)                   // BEQ a2, zero, loop_echo (back)
    emit(LW(a1, s1, 0))                  // a1 = rx byte (clears avail)
    emit(SW(a1, s1, 0))                  // echo: uart_tx = a1
    val jEcho = emit(0)                   // JAL zero, loop_echo (back)

    // patch echo back-branch (BEQ a2,zero -> loopEcho)
    insns(bEcho) = BEQ(a2, zero, pcOf(loopEcho) - pcOf(bEcho))
    insns(jEcho) = JAL(zero, pcOf(loopEcho) - pcOf(jEcho))

    // ---- DMEM image: banner + null terminator ----
    val dbytes = (BANNER.map(_.toByte) :+ 0.toByte).toSeq

    (insns.toSeq, dbytes)
  }
}

// ---------------------------------------------------------------------------
// The SoC: single-cycle RV32I core + ROM + DMEM + MMIO UART.
// ---------------------------------------------------------------------------
class Soc extends Module {
  // ---- TOP-LEVEL bare IOs (firtool emits these names unprefixed) ----
  val uart_tx_valid = IO(Output(Bool()))
  val uart_tx       = IO(Output(UInt(8.W)))
  val uart_rx_valid = IO(Input(Bool()))
  val uart_rx       = IO(Input(UInt(8.W)))

  // ---- build program image ----
  val (romWords, dmemBytes) = Program.build()
  val ROM_DEPTH  = math.max(romWords.length, 1)
  val DMEM_BYTES = math.max(dmemBytes.length, 4)
  // round DMEM up to multiple of 4 words
  val DMEM_WORDS = (DMEM_BYTES + 3) / 4

  // ---- instruction ROM ----
  val rom = VecInit(romWords.map(_.U(32.W)))

  // ---- data memory as word array (byte addressable via masks) ----
  // pack dmem bytes into words (little-endian)
  val dmemWordInit = (0 until DMEM_WORDS).map { wi =>
    var v = 0L
    for (b <- 0 until 4) {
      val bi = wi * 4 + b
      val byte = if (bi < dmemBytes.length) (dmemBytes(bi).toLong & 0xff) else 0L
      v |= byte << (8 * b)
    }
    v & 0xffffffffL
  }
  val dmem = RegInit(VecInit(dmemWordInit.map(_.U(32.W))))

  // ---- UART RX holding register + flag ----
  val rxData  = RegInit(0.U(8.W))
  val rxAvail = RegInit(false.B)
  when(uart_rx_valid) {
    rxData  := uart_rx
    rxAvail := true.B
  }

  // ---- CPU state ----
  val pc   = RegInit(0.U(32.W))
  val regs = Reg(Vec(32, UInt(32.W)))
  // x0 hardwired to 0: we never write index 0, and read returns 0 explicitly.

  // ---- fetch ----
  val pcWord = pc(31, 2)
  val instr  = Mux(pcWord < ROM_DEPTH.U, rom(pcWord), 0.U(32.W))

  // ---- decode ----
  val opcode = instr(6, 0)
  val rd     = instr(11, 7)
  val funct3 = instr(14, 12)
  val rs1    = instr(19, 15)
  val rs2    = instr(24, 20)
  val funct7 = instr(31, 25)

  def rv(idx: UInt): UInt = Mux(idx === 0.U, 0.U(32.W), regs(idx))
  val rv1 = rv(rs1)
  val rv2 = rv(rs2)

  // immediates
  val immI = Cat(Fill(20, instr(31)), instr(31, 20))
  val immS = Cat(Fill(20, instr(31)), instr(31, 25), instr(11, 7))
  val immB = Cat(Fill(19, instr(31)), instr(31), instr(7), instr(30, 25), instr(11, 8), 0.U(1.W))
  val immU = Cat(instr(31, 12), 0.U(12.W))
  val immJ = Cat(Fill(11, instr(31)), instr(31), instr(19, 12), instr(20), instr(30, 21), 0.U(1.W))

  // opcodes
  val OP_LUI    = "b0110111".U
  val OP_AUIPC  = "b0010111".U
  val OP_JAL    = "b1101111".U
  val OP_JALR   = "b1100111".U
  val OP_BRANCH = "b1100011".U
  val OP_LOAD   = "b0000011".U
  val OP_STORE  = "b0100011".U
  val OP_IMM    = "b0010011".U
  val OP_REG    = "b0110011".U

  // ---- ALU ----
  def alu(f3: UInt, f7bit: Bool, a: UInt, b: UInt): UInt = {
    val res = Wire(UInt(32.W))
    res := 0.U
    switch(f3) {
      is("b000".U) { res := Mux(f7bit, a - b, a + b) } // ADD/SUB
      is("b111".U) { res := a & b }
      is("b110".U) { res := a | b }
      is("b100".U) { res := a ^ b }
      is("b001".U) { res := (a << b(4, 0))(31, 0) }       // SLL
      is("b101".U) { res := a >> b(4, 0) }                 // SRL (logical)
      is("b010".U) { res := (a.asSInt < b.asSInt).asUInt } // SLT
      is("b011".U) { res := (a < b).asUInt }               // SLTU
    }
    res
  }

  // register-register vs register-immediate
  val aluB_imm = immI
  val regAlu   = alu(funct3, funct7(5), rv1, rv2)
  val immAlu   = alu(funct3, Mux(funct3 === "b101".U, funct7(5), false.B), rv1, aluB_imm)

  // ---- memory address for load/store ----
  val loadAddr  = (rv1.asSInt + immI.asSInt).asUInt
  val storeAddr = (rv1.asSInt + immS.asSInt).asUInt

  val DMEM_BASE = Program.DMEM_BASE.U(32.W)
  val UART_BASE = Program.UART_BASE.U(32.W)

  // dmem word index helpers
  def dmemIndex(addr: UInt): UInt = (addr - DMEM_BASE)(31, 2)
  def byteOff(addr: UInt): UInt   = addr(1, 0)

  val isUart   = (storeAddr(31, 12) === UART_BASE(31, 12))
  val isUartLd = (loadAddr(31, 12)  === UART_BASE(31, 12))

  // ---- LOAD result ----
  val ldWord    = dmem(dmemIndex(loadAddr))
  val ldByteSel = byteOff(loadAddr)
  val ldByte    = MuxLookup(ldByteSel, ldWord(7, 0))(Seq(
    0.U -> ldWord(7, 0),
    1.U -> ldWord(15, 8),
    2.U -> ldWord(23, 16),
    3.U -> ldWord(31, 24)
  ))
  val ldByteSExt = Cat(Fill(24, ldByte(7)), ldByte)
  val ldByteZExt = Cat(Fill(24, 0.U), ldByte)

  // UART mmio loads
  val uartStatus = Cat(0.U(31.W), rxAvail)         // bit0 = rx avail
  val uartRxRd   = Cat(0.U(24.W), rxData)
  // offset 0 -> rx data, offset 4 -> status
  val uartLoadVal = Mux(loadAddr(2), uartStatus, uartRxRd)

  val loadResult = Wire(UInt(32.W))
  when(isUartLd) {
    loadResult := uartLoadVal
  } .otherwise {
    // funct3: 000=LB, 100=LBU, 010=LW
    loadResult := MuxLookup(funct3, ldWord)(Seq(
      "b000".U -> ldByteSExt,
      "b100".U -> ldByteZExt,
      "b010".U -> ldWord
    ))
  }

  // ---- writeback value ----
  val wbVal = Wire(UInt(32.W))
  wbVal := 0.U
  val doWrite = Wire(Bool())
  doWrite := false.B

  // ---- next PC ----
  val pcPlus4 = pc + 4.U
  val nextPc  = Wire(UInt(32.W))
  nextPc := pcPlus4

  // branch comparison
  val brTaken = Wire(Bool())
  brTaken := false.B
  switch(funct3) {
    is("b000".U) { brTaken := rv1 === rv2 }                 // BEQ
    is("b001".U) { brTaken := rv1 =/= rv2 }                 // BNE
    is("b100".U) { brTaken := rv1.asSInt < rv2.asSInt }     // BLT
    is("b101".U) { brTaken := rv1.asSInt >= rv2.asSInt }    // BGE
    is("b110".U) { brTaken := rv1 < rv2 }                   // BLTU
    is("b111".U) { brTaken := rv1 >= rv2 }                  // BGEU
  }

  // ---- UART TX default ----
  uart_tx_valid := false.B
  uart_tx       := 0.U

  // RX clear-on-read (offset 0 load from UART)
  val clearRx = Wire(Bool())
  clearRx := false.B

  switch(opcode) {
    is(OP_LUI) {
      wbVal := immU; doWrite := true.B
    }
    is(OP_AUIPC) {
      wbVal := (pc.asSInt + immU.asSInt).asUInt; doWrite := true.B
    }
    is(OP_JAL) {
      wbVal := pcPlus4; doWrite := true.B
      nextPc := (pc.asSInt + immJ.asSInt).asUInt
    }
    is(OP_JALR) {
      wbVal := pcPlus4; doWrite := true.B
      nextPc := ((rv1.asSInt + immI.asSInt).asUInt) & ~1.U(32.W)
    }
    is(OP_BRANCH) {
      when(brTaken) { nextPc := (pc.asSInt + immB.asSInt).asUInt }
    }
    is(OP_IMM) {
      wbVal := immAlu; doWrite := true.B
    }
    is(OP_REG) {
      wbVal := regAlu; doWrite := true.B
    }
    is(OP_LOAD) {
      wbVal := loadResult; doWrite := true.B
      when(isUartLd && !loadAddr(2)) { clearRx := true.B } // reading rx data clears avail
    }
    is(OP_STORE) {
      when(isUart) {
        // store to UART tx
        uart_tx_valid := true.B
        uart_tx       := rv2(7, 0)
      }
    }
  }

  // ---- register writeback ----
  when(doWrite && (rd =/= 0.U)) {
    regs(rd) := wbVal
  }

  // ---- DMEM store (SW/SB) for non-UART addresses ----
  when(opcode === OP_STORE && !isUart) {
    val wi  = dmemIndex(storeAddr)
    val off = byteOff(storeAddr)
    when(funct3 === "b010".U) {
      // SW
      dmem(wi) := rv2
    } .otherwise {
      // SB: update one byte
      val old = dmem(wi)
      val nb  = rv2(7, 0)
      val merged = MuxLookup(off, old)(Seq(
        0.U -> Cat(old(31, 8), nb),
        1.U -> Cat(old(31, 16), nb, old(7, 0)),
        2.U -> Cat(old(31, 24), nb, old(15, 0)),
        3.U -> Cat(nb, old(23, 0))
      ))
      dmem(wi) := merged
    }
  }

  // ---- RX flag update: set on receive, clear on read ----
  when(clearRx) {
    rxAvail := false.B
  }
  // (if both receive and clear in same cycle, receive wins via ordering below)
  when(uart_rx_valid) {
    rxData  := uart_rx
    rxAvail := true.B
  }

  // ---- commit PC ----
  pc := nextPc
}

object Main extends App {
  println("=BEGIN_SV=")
  println(ChiselStage.emitSystemVerilog(
    new Soc,
    firtoolOpts = Array("-disable-all-randomization", "-strip-debug-info")
  ))
}
