// ==========================================================================
// rtl/vr1/exu/vr1_exu_int.sv — M09 整数执行单元（`INT`：ALU／SHIFT／MUL／DIV·REM）
//
// 状态（不得误读，红线 R8）：
//   · 本模块**已实现**（M1-S3 第二批）：`disp_x_t`（§3.11）→ `x_complete_t`（§3.20）；
//     指令面＝G1-I 14 条中的整数类 6 条 ＋ W 型 1 条 ＋ **M2 增补 27 条**（`doc/spec/02` §9.1.1／
//     §9.1.2／§9.1.3）：`LUI`、`AUIPC`（源面＝pc）、OP-IMM 9 条（`ADDI/SLTI/SLTIU/XORI/ORI/ANDI/
//     SLLI/SRLI/SRAI`）、OP-32 9 条（`ADDIW/SLLIW/SRLIW/SRAIW/ADDW/SUBW/SLLW/SRLW/SRAW`）、
//     OP 10 条（`ADD/SUB/SLL/SLT/SLTU/XOR/SRL/SRA/OR/AND`）、M 扩展 3 条（`MUL/DIV/REM`）。
//     语义逐条照 §10.1／§10.5／§10.6／§10.7／§17.1；比较类区分有符号（`SLT/SLTI`）与无符号
//     （`SLTU/SLTIU`，后者立即数**先符号扩展再按无符号比较**）；W 型一律低 32 位运算后按 bit31
//     符号扩展（SI-14）；RV64 移位量 64 位用 6 bit、W 型用 5 bit。
//   · **多拍口径**（计划 §2.1 第 10 行「时序可先多拍但可判」）：ALU/SHIFT 1 拍、
//     `MUL`＝`MUL_LAT`(=3) 拍、`DIV`/`REM`＝`DIV_LAT`(=35) 拍（不流水、独占）；占用判据＝
//     `disp_rdy_o=0`，完成判据＝`xc_o.vld=1`（一拍脉冲）。**结果值本身是组合算出的**，
//     多拍由占用计数器体现 —— 本版**不实现**真正的迭代除法器链（时序/面积面归 `spec/05`／
//     综合批次）⇒ 该实现取舍已登记 `TODO(M1-S3)`（真流水化时只换本文件内部、不动端口）。
//   · 本模块**未实现**（逐条给出口）：
//     - `MULH/MULHU/MULHSU/MULW/DIVU/REMU/DIVW/DIVUW/REMW/REMUW`（`spec/02` §9.1.6 其余成员）：
//       不在 G1-I 14 条内（清单 §1.1）⇒ 本版不产生其语义（`default` 分支不产结果）—— TODO(G1-F)；
//     - 其余 ALU/SHIFT 成员（`SLT/XOR/OR/AND/...`，§9.1.1）：同上，不在 14 条内 —— TODO(G1-F)；
//     - `x_complete_t.vld` 之外的上报面（异常/fault）：整数运算**不产生异常**（`spec/02` §17.1
//       尾注：「除零/溢出不得报同步异常」）⇒ 本单元无 `fault` 出口（与 `vr1_bru`/LSU 同构分离）。
//
// 依据（逐条可核）：
//   · doc/spec/01 §3.11 `disp_x_t`（`isop`/`rs1_val`/`rs2_val`/`imm`/`pc`/`rob_id`/`rd_paddr`/
//     `is_w`/`sext`）／§3.20 `x_complete_t`（`vld`/`robid`/`paddr`/`data`）；
//   · doc/spec/02 §10.1（LUI/ADDI/ADDIW/SLLI 逐条语义）／§10.6（MUL/DIV/REM）／
//     §17.1（M 扩展 13 成员语义与除零/溢出表：商全 1、余＝被除数、溢出仅「最小负数÷-1」）；
//   · doc/spec/00 §4.4 `MUL_LAT=3`／`DIV_LAT=35`（本模块占用拍数口径的唯一数值源）；
//   · doc/decisions/G1-I-最小冻结清单.md §1.1（14 条）／§2.6（首版恒 0／不消费成员表）；
//   · doc/design/M1-实现计划.md §2.1 第 10 行（M09 职责）／§2.3 简化 #1（单发射）。
//
// 首版口径登记（**不新造语义**）：
//   · `disp_x_t.imm` 已由 `D` 级按 ISA 语义符号扩展（§3.4 尾注）⇒ 本单元直接消费，
//     **不再二次扩展**；移位类按 `imm[5:0]` 取 shamt（§9.5 `imm_kind=11`）；
//   · `eu_id` 不消费（`spec/01` §3.11 只有位宽与值域，**无单元号→EU 分配表**）——同 `vr1_bru`；
//   · `is_w`/`sext` 消费：W 型结果按 bit31 符号扩展（本版只有 `ADDIW` 一条）。
//
// 写授权：`state/freeze.json` 的 rtl_write_authorized=true（R0 2026-09-25 签署 G1-I 的人令）。
// ==========================================================================
`ifndef VR1_EXU_INT_SV
`define VR1_EXU_INT_SV

module vr1_exu_int
  import vr1_pkg::*;
(
  input  logic                  clk,
  input  logic                  rst_n,

  // ---- 上游：发射选择（`spec/01` §3.11 `disp_x_t`；本版**单发射** ⇒ 只消费 1 条/拍）----
  input  logic                  disp_vld_i,     // 本拍发起一条 INT μop
  input  var vr1_pkg::disp_x_t  disp_i,
  output logic                  disp_rdy_o,     // 0 = 占用中（多拍 EU 不流水）

  // ---- 下游：写回完成回报（`spec/01` §3.20 `x_complete_t`，1 条/拍脉冲）----
  output vr1_pkg::x_complete_t  xc_o
);

  // -------------------------------------------------------------------------
  // 常量（`isop` 成员编码逐行取自 `spec/02` §9.1；本模块**只引用**，不另赋、不重排）
  // -------------------------------------------------------------------------
  localparam logic [9:0] ISOP_ADDI  = 10'h000;   // §9.1.1
  localparam logic [9:0] ISOP_SLTI  = 10'h001;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_SLTIU = 10'h002;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_XORI  = 10'h003;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_ORI   = 10'h004;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_ANDI  = 10'h005;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_SLLI  = 10'h006;   // §9.1.1（imm_kind=11 shamt）
  localparam logic [9:0] ISOP_SRLI  = 10'h007;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_SRAI  = 10'h008;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_AUIPC = 10'h010;   // §9.1.3（M2 增补：源面＝PC）
  localparam logic [9:0] ISOP_ADDIW = 10'h020;   // §9.1.2（W 型）
  localparam logic [9:0] ISOP_SLLIW = 10'h021;   // §9.1.2（M2 增补）
  localparam logic [9:0] ISOP_SRLIW = 10'h022;   // §9.1.2（M2 增补）
  localparam logic [9:0] ISOP_SRAIW = 10'h023;   // §9.1.2（M2 增补）
  localparam logic [9:0] ISOP_ADD   = 10'h030;   // §9.1.1（M2 增补：寄存器型基础 OP）
  localparam logic [9:0] ISOP_SUB   = 10'h031;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_SLL   = 10'h032;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_SLT   = 10'h033;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_SLTU  = 10'h034;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_XOR   = 10'h035;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_SRL   = 10'h036;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_SRA   = 10'h037;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_OR    = 10'h038;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_AND   = 10'h039;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_LUI   = 10'h040;   // §9.1.3
  localparam logic [9:0] ISOP_ADDW  = 10'h050;   // §9.1.2（M2 增补）
  localparam logic [9:0] ISOP_SUBW  = 10'h051;   // §9.1.2（M2 增补）
  localparam logic [9:0] ISOP_SLLW  = 10'h052;   // §9.1.2（M2 增补）
  localparam logic [9:0] ISOP_SRLW  = 10'h053;   // §9.1.2（M2 增补）
  localparam logic [9:0] ISOP_SRAW  = 10'h054;   // §9.1.2（M2 增补）
  localparam logic [9:0] ISOP_MUL   = 10'h200;   // §9.1.6
  localparam logic [9:0] ISOP_DIV   = 10'h280;   // §9.1.6
  localparam logic [9:0] ISOP_REM   = 10'h282;   // §9.1.6

  // -------------------------------------------------------------------------
  // 占用拍数（`spec/00` §4.4：`MUL_LAT=3`／`DIV_LAT=35`；其余 1 拍）
  // -------------------------------------------------------------------------
  function automatic logic [5:0] lat_of(input logic [9:0] isop);
    unique case (isop)
      ISOP_MUL:            lat_of = 6'(MUL_LAT);
      ISOP_DIV, ISOP_REM:  lat_of = 6'(DIV_LAT);
      default:             lat_of = 6'd1;
    endcase
  endfunction

  // -------------------------------------------------------------------------
  // 结果（组合；§10.1／§10.6／§17.1 逐条语义）
  // -------------------------------------------------------------------------
  function automatic logic [63:0] alu_result(input vr1_pkg::disp_x_t d);
    logic [63:0] s1, s2;
    logic [63:0] imm64;
    logic [31:0] w32, w32b;
    logic signed [63:0] ss1, ss2, q, r;
    logic        mdiv_ovf;
    begin
      s1    = d.rs1_val;
      s2    = d.rs2_val;
      imm64 = {{20{d.imm[43]}}, d.imm};           // `imm` 已符号扩展（§3.4）⇒ 展到 64 bit
      unique case (d.isop)
        // ---- U 型：LUI：rd ← imm（`D` 级已给 `sext32(imm[31:12]<<12)`，§10.1）----
        ISOP_LUI:   alu_result = imm64;
        // ---- U 型（M2 增补）：AUIPC：rd ← pc ＋（imm[31:12] 左移 12）----
        //   `src_sel=10 pc`（§9.5 R2）⇒ 源面取 `disp_x_t.pc`（40 bit 规范地址，符号扩展到 64）。
        ISOP_AUIPC: alu_result = {{24{d.pc[39]}}, d.pc} + imm64;
        // ---- I 型 ALU：ADDI/SLTI/SLTIU/XORI/ORI/ANDI（§10.5）----
        ISOP_ADDI:  alu_result = s1 + imm64;
        ISOP_SLTI:  alu_result = ($signed(s1) < $signed(imm64)) ? 64'd1 : 64'd0;   // 有符号比较
        ISOP_SLTIU: alu_result = (s1 < imm64) ? 64'd1 : 64'd0;   // 立即数已符号扩展，按**无符号**比较（ISA）
        ISOP_XORI:  alu_result = s1 ^ imm64;
        ISOP_ORI:   alu_result = s1 | imm64;
        ISOP_ANDI:  alu_result = s1 & imm64;
        // ---- I 型移位（M2 增补）：移位量＝imm[5:0]（shamt 已在 0..63）----
        ISOP_SLLI:  alu_result = s1 << d.imm[5:0];
        ISOP_SRLI:  alu_result = s1 >> d.imm[5:0];
        ISOP_SRAI:  alu_result = $signed(s1) >>> d.imm[5:0];
        // ---- W 型（§9.1.2／SI-14）：低 32 位运算 → 按 bit31 符号扩展 ----
        ISOP_ADDIW: begin
          w32        = s1[31:0] + d.imm[31:0];
          alu_result = {{32{w32[31]}}, w32};
        end
        ISOP_ADDW: begin
          w32        = s1[31:0] + s2[31:0];
          alu_result = {{32{w32[31]}}, w32};
        end
        ISOP_SUBW: begin
          w32        = s1[31:0] - s2[31:0];
          alu_result = {{32{w32[31]}}, w32};
        end
        ISOP_SLLIW: begin
          w32        = s1[31:0] << d.imm[4:0];
          alu_result = {{32{w32[31]}}, w32};
        end
        ISOP_SRLIW: begin
          w32        = s1[31:0] >> d.imm[4:0];
          alu_result = {{32{w32[31]}}, w32};
        end
        ISOP_SRAIW: begin
          w32        = $signed(s1[31:0]) >>> d.imm[4:0];
          alu_result = {{32{w32[31]}}, w32};
        end
        ISOP_SLLW: begin
          w32        = s1[31:0] << s2[4:0];        // W 型移位量＝rs2[4:0]（§9.1.2）
          alu_result = {{32{w32[31]}}, w32};
        end
        ISOP_SRLW: begin
          w32        = s1[31:0] >> s2[4:0];
          alu_result = {{32{w32[31]}}, w32};
        end
        ISOP_SRAW: begin
          w32        = $signed(s1[31:0]) >>> s2[4:0];
          alu_result = {{32{w32[31]}}, w32};
        end
        // ---- OP 型（M2 增补）：寄存器第二面（§10.6）----
        ISOP_ADD:   alu_result = s1 + s2;
        ISOP_SUB:   alu_result = s1 - s2;
        ISOP_SLL:   alu_result = s1 << s2[5:0];     // RV64 寄存器移位用 6 bit（§9.1.1）
        ISOP_SRL:   alu_result = s1 >> s2[5:0];
        ISOP_SRA:   alu_result = $signed(s1) >>> s2[5:0];
        ISOP_XOR:   alu_result = s1 ^ s2;
        ISOP_OR:    alu_result = s1 | s2;
        ISOP_AND:   alu_result = s1 & s2;
        ISOP_SLT:   alu_result = ($signed(s1) < $signed(s2)) ? 64'd1 : 64'd0;
        ISOP_SLTU:  alu_result = (s1 < s2) ? 64'd1 : 64'd0;
        // ---- M：MUL：积的低 64 位（§17.1 #1）----
        ISOP_MUL: begin
          ss1 = $signed(s1);
          ss2 = $signed(s2);
          alu_result = ss1 * ss2;
        end
        // ---- M：DIV/REM（§17.1 #6/#8 ＋ 除零/溢出表 Table 22）----
        ISOP_DIV, ISOP_REM: begin
          ss1      = $signed(s1);
          ss2      = $signed(s2);
          mdiv_ovf = (ss1 == {1'b1, 63'b0}) && (ss2 == -64'sd1);   // 最小负数 ÷ -1
          if (ss2 == 64'sd0) begin
            // 除零：商＝全 1；余数＝被除数（**不报异常**，§17.1 尾注）
            if (d.isop == ISOP_DIV) alu_result = 64'hFFFF_FFFF_FFFF_FFFF;
            else                    alu_result = s1;
          end else if (mdiv_ovf) begin
            // 有符号溢出：商＝被除数；余数＝0
            if (d.isop == ISOP_DIV) alu_result = s1;
            else                    alu_result = 64'd0;
          end else begin
            q = ss1 / ss2;                          // SV `/` 对整数＝向零取整（§17.1 #6）
            r = ss1 % ss2;                          // 余数符号随被除数（§17.1 #8）
            alu_result = (d.isop == ISOP_DIV) ? q : r;
          end
        end
        // 其余 isop 不属本单元（清单 §1.1 只有 14 条；`D` 级不会为它们产生合法语义）——
        //   本版**不产结果**、由上层按"未识别"处置（TODO(G1-F)：完整 87 成员面）
        default:    alu_result = 64'd0;
      endcase
    end
  endfunction

  // -------------------------------------------------------------------------
  // 占用计数器（多拍但可判）：发起拍锁存结果与随流键，`lat-1` 拍后给完成脉冲
  // -------------------------------------------------------------------------
  logic        busy_q;
  logic [5:0]  cnt_q;
  logic [63:0] res_q;
  logic [7:0]  robid_q;
  logic [5:0]  paddr_q;

  assign disp_rdy_o = !busy_q;                      // 占用中不收新请求（不流水，与 §5.2 E1..E5 口径同）

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      busy_q   <= 1'b0;
      cnt_q    <= 6'd0;
      res_q    <= 64'd0;
      robid_q  <= 8'd0;
      paddr_q  <= 6'd0;
    end else if (!busy_q) begin
      if (disp_vld_i) begin
        res_q   <= alu_result(disp_i);
        robid_q <= disp_i.rob_id;
        paddr_q <= disp_i.rd_paddr;
        cnt_q   <= lat_of(disp_i.isop) - 6'd1;
        busy_q  <= 1'b1;
      end
    end else if (cnt_q == 6'd0) begin
      busy_q <= 1'b0;                               // 本拍给完成脉冲；次拍可收新请求
    end else begin
      cnt_q <= cnt_q - 6'd1;
    end
  end

  always_comb begin
    xc_o        = '0;
    xc_o.vld    = busy_q && (cnt_q == 6'd0);
    xc_o.robid  = robid_q;
    xc_o.paddr  = paddr_q;
    xc_o.data   = res_q;
  end

  // -------------------------------------------------------------------------
  // 状态与不变量（本版如实列出；断言化归 SVA 批 `spec/11` §7，本批不含）：
  //   ① 完成脉冲恰一拍（`busy_q && cnt_q==0`）；② 占用期间不收新请求（`disp_rdy_o=0`）⇒
  //      在飞 μop 恒 1 条；③ `DIV/REM` 的占用拍数 == `DIV_LAT`、`MUL` == `MUL_LAT`
  //      （由 `tb/unit/exu_int_smoke_tb.sv` 逐案实测）。
  // -------------------------------------------------------------------------
  // synopsys translate_off
  initial $display("[vr1_exu_int] M09 INT EU: LUI/AUIPC/ADDI(+ALU imm family)/SLLI/SRLI/SRAI/ADDIW(+W family)/ADD(+OP family)/MUL/DIV/REM landed at M1-S3b + M2(+25 ALU); multi-cycle = MUL_LAT/DIV_LAT occupancy counters (TODO(M1-S3): real iterative divider); 87-member complete face TODO(G1-F)");
  // synopsys translate_on

endmodule

`endif // VR1_EXU_INT_SV
