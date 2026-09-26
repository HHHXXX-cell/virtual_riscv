// ==========================================================================
// rtl/vr1/ctrl/vr1_decode.sv — M05 译码级（`D`/`P6`）：IBUF 读口 → `uop_t[DECODE_WIDTH]`
//
// 状态（不得误读，红线 R8）：
//   · 本模块**已实现**（M1-S2，`doc/design/M1-实现计划.md` §5 S2 行）：
//     ① **IBUF 消费**：从 M03 的组合读口（`spec/01` §3.3，16 槽）按**槽号升序**取
//        ≤`DECODE_WIDTH` 个**起始槽**（`fetch_raw_t.valid`＝该槽为指令起始，由 P5 walk 产出）
//        构成本拍 uop 组；② **逐窗握手**（`ibuf_drain_o`）：本窗起始槽全部取走 ⇒ 置 1 一拍，
//        M03 据此清 `ibuf_win_vld` 并放行下一窗（S1 的"写后恒 1"口径到此闭合）；
//     ③ **G1-I 14 条定长译码**（清单 §1.1 第 1 条）＋非法编码 `pre_exc`/`pre_exc_code`；
//     ④ D→R 交接握手（`uop_ready_i`，R 级反压入口）。
//     ⑤ **M2 增补（2026-09-26 心跳第 5 轮）**：`ADD`（OP f7=0000000/f3=000）与 `BNE`（BRANCH
//        f3=001）入面，随后按 `sim/image/rv64ui/GAP.json` 的机械反算续补 **OP-IMM 7 条**
//        （SLTI/SLTIU/XORI/ORI/ANDI/SRLI/SRAI）、**OP 8 条**（SUB/SLL/SLT/SLTU/XOR/SRL/SRA/OR/AND）、
//        **OP-32 8 条**（SLLIW/SRLIW/SRAIW/ADDW/SUBW/SLLW/SRLW/SRAW）、**AUIPC** —— 依据 `spec/02`
//        §9.1.1／§9.1.2／§9.1.3 成员编码 ＋ §10.1／§10.5／§10.6／§10.7 逐条语义 ＋ §9.5 派生域
//        （`src_sel`：寄存器型 00 PRF、立即数型 01 imm、AUIPC 10 pc；移位类 `imm_kind`=11 shamt、
//        W 型 `is_w`/`sext`=1）。**语义与派生域逐条照表，不新造**。
//        增补后本模块的合法面＝**G1-I 14 条 ＋ M2 增补 27 条 ＋ M3-(d) 增补 16 条 = 57 条**（见下
//        "首版子集口径"）；其余编码一律 `pre_exc`（非法），完整 87 成员表随 G1-F 落地 —— TODO(G1-F)。
//     ⑥ **M3-(d) 增补（2026-09-26 心跳第 10 轮，「补缺指令」批）**：按 `sim/image/rv64ui/GAP.json`
//        的 `pending_subset` 机械反算，补 **条件分支余 4 条**（BLT/BGE/BLTU/BGEU，§9.1.3
//        0x082..0x085；条件由成员唯一承载、方向解析在 M10）、**JALR**（§9.1.3 0x090；目标式
//        `(rs1+imm)&~1` 在 M10）、**载入余 6 条**（LB/LH/LD/LBU/LHU/LWU，§9.1.4 0x100..0x106；
//        `dm`/`sext` 逐条照 §9.5）、**存储余 3 条**（SB/SH/SD，§9.1.4 0x180..0x183）、
//        **MISC-MEM 2 条**（FENCE 0x380 / FENCE.I 0x381，§9.1.8；依据 `spec/00` §2 一期 ISA 串
//        `rv64imac_zicsr_zifencei` 含 `zifencei` ⇒ 按最小语义入面：识别 + 无副作用完成，
//        排空/无效化动作集合在本版为空——无 L1I、无 store buffer、取指桩为组合读）。
//   · 本模块**未实现**（逐条给出口，未完成项一律 TODO，不写"看起来对"的逻辑）：
//     - **C 展开（16→32 bit）**：`C_EXPAND_STAGES=1` 的展开级（M04 `vr1_cexpand`）不在 G1-I
//       （清单 §1.2 第 6 条、`GS-3` 自决：首版 D 级直读 `fetch_raw_t`、展开级恒等旁路）
//       ⇒ 本版**一律按 32 bit 译码**、`is_c` 恒 0；低 2 位 ≠`11` 的字按非法处理 —— TODO(G1-F v5)；
//     - **取指异常**（`fetch_raw_t.err`/`err_code` → `pre_exc`）：无 PMA/PMP/翻译判决面
//       （清单 §1.2 第 1 条；§2.6「`fetch_raw_t.err/err_code` 恒 0」）⇒ 本版不消费 —— TODO(G1-F)；
//     - **R 级**（M06 `vr1_rename`）：不存在（M1-S3）⇒ `uop_o` 的消费方为 `vr1_core` 内部线，
//       未接任何下游（`uop_ready_i` 恒 1）—— TODO(M1-S3)；
//     - **14 条之外的指令面**：见下「首版子集口径」。
//
// 依据（逐条可核）：
//   · doc/spec/01 §3.4 `uop_t`（成员位域与合法值域）／§3.3 `fetch_raw_t`（IBUF→D 形态，
//     N8 定案：「IBUF→D 每拍组合读出全部 16 槽，D 级按 §3.16 的 walk 结果选取 ≤DECODE_WIDTH 个
//     **起始槽**构建 uop」）／§3.16（walk 规则：槽地址 = 窗基址 + 2×槽号）；
//   · doc/spec/01 §1.1 `P6`/`D` 行（译码级动作＝C 展开 + 定长译码 + 立即数生成 + 预检非法）；
//     §1.3 每拍吞吐「译码 4 条」（`DECODE_WIDTH`）；
//   · doc/spec/02 §9.1（`isop` 成员编码唯一权威表）／§9.3（位段规则 `isop = cls<<7 | g<<4 | m`）／
//     §9.4-(6)（`cls` 即 `isop[9:7]` 恒等投影）／§9.5（`cls`/`src_sel`/`dm`/`sext` 四域派生视图）／
//     §2.1（格式 → `imm_kind` 归属）／§4.1 的 SI-1（任何 `rd=x0` ⇒ `dst_kind=00`）；
//   · doc/spec/10 §2.1 码 2 `Illegal instruction`（产生点＝「译码预检 `pre_exc_code`」）；
//   · doc/decisions/G1-I-最小冻结清单.md §1.1 第 1 条（14 条指令）／§1.2 第 6 条（无 C）／
//     §2.3（码 2 的判决点首版仅"译码期预检"）／§2.6（首版恒 0／不消费成员表）／`GS-3`（直读 `fetch_raw_t`）；
//   · doc/design/M1-实现计划.md §2.3 简化 #1（单发射：多 lane 接口保留，本步不引入多发射）。
//
// 首版子集口径（**显式登记，不得误读为"全 ISA 合法判据"**）：
//   · 本版对 **G1-I 14 条 ＋ M2 增补 27 条 ＋ M3-(d) 增补 16 条（合 57 条）** 给出合法语义；**其余一切编码**
//     （含 G1-F 后才入面的合法 RV64 指令、`spec/02` §9.1 其余 30 个成员、以及 §9.3「保留段」
//     的组合）一律置 `pre_exc=1` + `pre_exc_code=4'd2`（非法指令）——依据：`spec/10` §2.1 码 2 行
//     的产生点（「译码预检 `pre_exc_code`」）＋`spec/02` §9.3 依据句（保留编码 **UNSPECIFIED**；
//     本项目取「RES 编码点一律非法化」为平台选择）；**当前 rv64ui 子集逐条镜像的助记符缺口由
//     `sim/image/rv64ui/GAP.json` 机械反算**（见 `sim/run_m2_rv64ui/run.log`）⇒ 该收口不影响
//     M2 判据。**余下未入面者**（`spec/02` §9.1 计 30 成员）：§9.1.1/§9.1.2 已满 28 条（无余），
//     §9.1.5 A 扩展 11 条、§9.1.6 M 扩展余 10 条、§9.1.7 CSR 余 4 条（CSRRC/CSRRWI/CSRRSI/
//     CSRRCI）、§9.1.8 余 5 条（ECALL/EBREAK/SRET/WFI/SFENCE.VMA）——完整合法性表（87 成员）
//     随 G1-F 增量落地 —— TODO(G1-F)；
//   · `spec/02` §9.3「reserved 组合不得由译码产生」在此落实为：本模块**从不**对未识别编码
//     断言任何 `isop`（非法分支里 `isop` 保持 0 且 `pre_exc=1`）。
//
// 写授权：`state/freeze.json` 的 rtl_write_authorized=true（R0 2026-09-25 签署 G1-I 的人令）。
// ==========================================================================
`ifndef VR1_DECODE_SV
`define VR1_DECODE_SV

module vr1_decode
  import vr1_pkg::*;
(
  input  logic                     clk,
  input  logic                     rst_n,

  // ---- 上游：IBUF 读口（spec/01 §3.3；M03 `vr1_ifetch` 组合读出，16 槽 × 92 bit）----
  input  logic                     ibuf_win_vld_i,   // IBUF 内为"某 32 B 窗"（M03 写后置 1）
  input  var vr1_pkg::fetch_raw_t  ibuf_rd_i [IBUF_ENTRIES],

  // ---- 上游：逐窗握手（本拍＝本窗起始槽已被 D 全部取走并交出）----
  // 置 1 一拍 ⇒ M03 清 `ibuf_win_vld`、放行下一窗写入（S1 端口注「逐窗握手归 M1-S2」的落地）。
  output logic                     ibuf_drain_o,

  // ---- 下游：译码结果（spec/01 §3.4 `uop_t`，≤`DECODE_WIDTH` 条/拍；无效 lane `valid=0`）----
  output vr1_pkg::uop_t            uop_o [DECODE_WIDTH],

  // ---- 下游：R 级反压入口（`uop_o` 在本拍被接受）----
  input  logic                     uop_ready_i,

  // ---- 冲刷口（M1-S3：`spec/01` §5.2 `D` 行「清流水线寄存器、`pre_exc` 丢弃」）----
  // 置 1 一拍 ⇒ 本拍**不接受**（`take=0`、不置 drain）、读指针归零；IBUF 窗由 M03 的
  // `flush_i` 同拍清（`ibuf_win_vld_i=0` ⇒ 无 lane，不会重present 旧路径槽）。
  input  logic                     flush_i
);

  // 注：`import vr1_pkg::*;` 写在 module 头部——端口表的 `[IBUF_ENTRIES]`/`[DECODE_WIDTH]`
  //     维度与 `fetch_raw_t`/`uop_t` 需要包内符号在**端口作用域**可见（同 `vr1_ifetch`）。

  // -------------------------------------------------------------------------
  // 常量（RISC-V 基指令编码位域；取自规范，非本项目自造参数）
  // -------------------------------------------------------------------------
  localparam logic [6:0] OPC_LUI    = 7'b0110111;
  localparam logic [6:0] OPC_AUIPC  = 7'b0010111;      // AUIPC（M2 增补）
  localparam logic [6:0] OPC_OPIMM  = 7'b0010011;      // OP-IMM
  localparam logic [6:0] OPC_OPIMM32= 7'b0011011;      // OP-IMM-32（ADDIW/SLLIW/SRLIW/SRAIW）
  localparam logic [6:0] OPC_OP32   = 7'b0111011;      // OP-32 （ADDW/SUBW/SLLW/SRLW/SRAW）
  localparam logic [6:0] OPC_OP     = 7'b0110011;      // OP    （ADD/MUL/DIV/REM）
  localparam logic [6:0] OPC_JAL    = 7'b1101111;
  localparam logic [6:0] OPC_JALR   = 7'b1100111;      // JALR（M3-(d) 增补）
  localparam logic [6:0] OPC_BRANCH = 7'b1100011;      // 6 条条件分支（M2 增补 BNE；M3-(d) 补齐 BLT/BGE/BLTU/BGEU）
  localparam logic [6:0] OPC_LOAD   = 7'b0000011;      // LB/LH/LW/LD/LBU/LHU/LWU（M3-(d) 补齐 7 条）
  localparam logic [6:0] OPC_STORE  = 7'b0100011;      // SB/SH/SW/SD（M3-(d) 补齐 4 条）
  localparam logic [6:0] OPC_MISC   = 7'b0001111;      // MISC-MEM：FENCE/FENCE.I（M3-(d) 增补）
  localparam logic [6:0] OPC_SYSTEM = 7'b1110011;      // CSRRW/CSRRS/MRET
  localparam logic [6:0] F7_BASE    = 7'b0000000;      // OP 的基础（非 M 扩展）funct7（ADD/ADDW/SLL/SRL/SLT/…）
  localparam logic [6:0] F7_SUB     = 7'b0100000;      // OP/OP-32 的 SUB/SRA/SUBW/SRAW funct7
  localparam logic [6:0] F7_MULDIV  = 7'b0000001;      // OP 的 M 扩展 funct7
  localparam logic [6:0] F7_MRET    = 7'b0011000;      // SYSTEM 的 MRET funct7
  localparam logic [5:0] F6_ZERO    = 6'b000000;       // 移位类 funct6：SLLI/SRLI
  localparam logic [5:0] F6_SRA     = 6'b010000;       // 移位类 funct6：SRAI
  localparam logic [2:0] F3_ADD     = 3'b000;          // OP：ADD（f7=0000000）
  localparam logic [2:0] F3_BEQ     = 3'b000;          // BRANCH：BEQ
  localparam logic [2:0] F3_BNE     = 3'b001;          // BRANCH：BNE（M2 增补）
  localparam logic [2:0] F3_BLT     = 3'b100;          // BRANCH：BLT（M3-(d) 增补）
  localparam logic [2:0] F3_BGE     = 3'b101;          // BRANCH：BGE（M3-(d) 增补）
  localparam logic [2:0] F3_BLTU    = 3'b110;          // BRANCH：BLTU（M3-(d) 增补）
  localparam logic [2:0] F3_BGEU    = 3'b111;          // BRANCH：BGEU（M3-(d) 增补）
  localparam logic [2:0] F3_SLLI    = 3'b001;
  localparam logic [2:0] F3_DIV     = 3'b100;
  localparam logic [2:0] F3_REM     = 3'b110;
  localparam logic [2:0] F3_LW      = 3'b010;
  localparam logic [2:0] F3_SW      = 3'b010;
  localparam logic [2:0] F3_SLTI    = 3'b010;          // OP-IMM：SLTI（M2 增补）
  localparam logic [2:0] F3_SLTIU   = 3'b011;          // OP-IMM：SLTIU（M2 增补）
  localparam logic [2:0] F3_XORI    = 3'b100;          // OP-IMM：XORI（M2 增补）
  localparam logic [2:0] F3_SRLI    = 3'b101;          // OP-IMM：SRLI/SRAI（M2 增补）
  localparam logic [2:0] F3_ORI     = 3'b110;          // OP-IMM：ORI（M2 增补）
  localparam logic [2:0] F3_ANDI    = 3'b111;          // OP-IMM：ANDI（M2 增补）
  localparam logic [2:0] F3_FENCE   = 3'b000;          // MISC-MEM：FENCE
  localparam logic [2:0] F3_FENCEI  = 3'b001;          // MISC-MEM：FENCE.I（Zifencei）
  localparam logic [4:0] RS2_MRET   = 5'b00010;

  // `isop` 成员编码（spec/02 §9.1 逐行；本模块**只引用**，不另赋、不重排）
  localparam logic [9:0] ISOP_ADDI  = 10'h000;   // §9.1.1
  localparam logic [9:0] ISOP_SLTI  = 10'h001;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_SLTIU = 10'h002;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_XORI  = 10'h003;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_ORI   = 10'h004;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_ANDI  = 10'h005;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_SLLI  = 10'h006;   // §9.1.1
  localparam logic [9:0] ISOP_SRLI  = 10'h007;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_SRAI  = 10'h008;   // §9.1.1（M2 增补）
  localparam logic [9:0] ISOP_AUIPC = 10'h010;   // §9.1.3（M2 增补）
  localparam logic [9:0] ISOP_ADDIW = 10'h020;   // §9.1.2
  localparam logic [9:0] ISOP_SLLIW = 10'h021;   // §9.1.2（M2 增补）
  localparam logic [9:0] ISOP_SRLIW = 10'h022;   // §9.1.2（M2 增补）
  localparam logic [9:0] ISOP_SRAIW = 10'h023;   // §9.1.2（M2 增补）
  localparam logic [9:0] ISOP_ADD   = 10'h030;   // §9.1.1（M2 增补）
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
  localparam logic [9:0] ISOP_BEQ   = 10'h080;   // §9.1.3
  localparam logic [9:0] ISOP_BNE   = 10'h081;   // §9.1.3（M2 增补）
  localparam logic [9:0] ISOP_BLT   = 10'h082;   // §9.1.3（M3-(d) 增补）
  localparam logic [9:0] ISOP_BGE   = 10'h083;   // §9.1.3（M3-(d) 增补）
  localparam logic [9:0] ISOP_BLTU  = 10'h084;   // §9.1.3（M3-(d) 增补）
  localparam logic [9:0] ISOP_BGEU  = 10'h085;   // §9.1.3（M3-(d) 增补）
  localparam logic [9:0] ISOP_JALR  = 10'h090;   // §9.1.3（M3-(d) 增补）
  localparam logic [9:0] ISOP_JAL   = 10'h0A0;   // §9.1.3
  localparam logic [9:0] ISOP_LB    = 10'h100;   // §9.1.4（M3-(d) 增补）
  localparam logic [9:0] ISOP_LH    = 10'h101;   // §9.1.4（M3-(d) 增补）
  localparam logic [9:0] ISOP_LW    = 10'h102;   // §9.1.4
  localparam logic [9:0] ISOP_LD    = 10'h103;   // §9.1.4（M3-(d) 增补）
  localparam logic [9:0] ISOP_LBU   = 10'h104;   // §9.1.4（M3-(d) 增补）
  localparam logic [9:0] ISOP_LHU   = 10'h105;   // §9.1.4（M3-(d) 增补）
  localparam logic [9:0] ISOP_LWU   = 10'h106;   // §9.1.4（M3-(d) 增补；RV64 专有）
  localparam logic [9:0] ISOP_SB    = 10'h180;   // §9.1.4（M3-(d) 增补）
  localparam logic [9:0] ISOP_SH    = 10'h181;   // §9.1.4（M3-(d) 增补）
  localparam logic [9:0] ISOP_SW    = 10'h182;   // §9.1.4
  localparam logic [9:0] ISOP_SD    = 10'h183;   // §9.1.4（M3-(d) 增补）
  localparam logic [9:0] ISOP_MUL   = 10'h200;   // §9.1.6
  localparam logic [9:0] ISOP_DIV   = 10'h280;   // §9.1.6
  localparam logic [9:0] ISOP_REM   = 10'h282;   // §9.1.6
  localparam logic [9:0] ISOP_CSRRW = 10'h300;   // §9.1.7
  localparam logic [9:0] ISOP_CSRRS = 10'h301;   // §9.1.7
  localparam logic [9:0] ISOP_MRET  = 10'h312;   // §9.1.8
  localparam logic [9:0] ISOP_FENCE = 10'h380;   // §9.1.8（M3-(d) 增补）
  localparam logic [9:0] ISOP_FENCEI= 10'h381;   // §9.1.8（M3-(d) 增补；Zifencei）

  // 派生域取值（spec/01 §3.4 值域；spec/02 §9.5 给逐成员派生规则）
  localparam logic [1:0] DST_NONE  = 2'b00, DST_GPR = 2'b01, DST_CSR = 2'b11;   // 10=FPR 一期禁止产生
  localparam logic [1:0] IMM_OFF   = 2'b00, IMM_ALU = 2'b01;
  localparam logic [1:0] IMM_SHAMT = 2'b11;                                      // 10（CSR uimm）本版不产生
  localparam logic [1:0] SRC_PRF   = 2'b00, SRC_IMM = 2'b01, SRC_PC = 2'b10, SRC_ZERO = 2'b11;
  // 访存宽度 `dm`（§9.5：仅访存 11 成员取具值）＋ `sext`（§9.5：载入 LB/LH/LW=1、LBU/LHU/LWU=0）
  localparam logic [1:0] DM_B      = 2'b00, DM_H = 2'b01, DM_W = 2'b10, DM_D = 2'b11;
  localparam logic [1:0] CSR_WR_RW = 2'b00, CSR_WR_RS = 2'b01;                   // 11/10 本版不产生（见下注）
  localparam logic [3:0] EXC_ILLEGAL = 4'd2;                                     // spec/10 §2.1 码 2

  // -------------------------------------------------------------------------
  // 立即数生成（spec/01 §3.4 `imm`：「已按 ISA 语义符号扩展」，44 bit 容器）
  // -------------------------------------------------------------------------
  function automatic logic [43:0] sext12_44(input logic [11:0] v);      // I 型（ADDI/ADDIW/LW/SW）
    sext12_44 = {{32{v[11]}}, v};
  endfunction

  function automatic logic [43:0] sext13_44(input logic [12:0] v);      // B 型（BEQ）
    sext13_44 = {{31{v[12]}}, v};
  endfunction

  function automatic logic [43:0] sext21_44(input logic [20:0] v);      // J 型（JAL）
    sext21_44 = {{23{v[20]}}, v};
  endfunction

  function automatic logic [43:0] uimm20_44(input logic [19:0] v);      // U 型（LUI）：imm[31:12] 左移 12（RV64 符号扩展）
    uimm20_44 = {{12{v[19]}}, v, 12'b0};
  endfunction

  // -------------------------------------------------------------------------
  // 单条指令译码（组合函数；输入＝指令字 ＋ 槽随行信息，输出＝`uop_t`）
  //   识别面＝G1-I 14 条（清单 §1.1 第 1 条）；未识别 ⇒ `pre_exc=1`/`pre_exc_code=2`（见文件头口径）
  // -------------------------------------------------------------------------
  function automatic uop_t decode_word(input logic [31:0] w,
                                       input logic [39:0] pc,
                                       input logic [4:0]  ftq_id,
                                       input logic [7:0]  bp_upd_id);
    uop_t       u;
    logic [6:0] opcode;
    logic [2:0] f3;
    logic [6:0] f7;
    logic [4:0] rs1, rs2, rd;
    logic       rd_writes;      // 该成员是否写 GPR 目的（再由 SI-1 按 rd≠x0 收口）
    logic       dst_is_csr;     // 目的面是"CSR 旧值→GPR"（dst_kind=11）

    u           = '0;
    opcode      = w[6:0];
    f3          = w[14:12];
    f7          = w[31:25];
    rs1         = w[19:15];
    rs2         = w[24:20];
    rd          = w[11:7];
    rd_writes   = 1'b0;
    dst_is_csr  = 1'b0;

    // 槽随行信息（spec/01 §3.3 → §3.4 逐项直连）
    u.valid     = 1'b1;
    u.pc        = pc;
    u.raw32     = w;                 // trace 用原始字（§3.4）
    u.is_c      = 1'b0;              // 无 C（清单 §1.2 第 6 条）——恒等旁路
    u.ftq_id    = ftq_id;
    u.bp_upd_id = bp_upd_id;
    // 不消费面（清单 §2.6）：`aq`/`rl`/`fm`/`bad_va` 恒 0；
    // `pred_taken`/`pred_target`：首版预测器恒"预测不跳转"（`vr1_bp` 的 `taken=0`）⇒ 取值即
    //   预测器实际输出（恒 0）——**不是 tie-off 假设**；随 FTQ 随流携带（`fetch_raw_t` 无该成员，
    //   需接口升版）归 G1-F v7 —— TODO(G1-F v7)。

    unique case (opcode)
      // ---- U 型：LUI（§9.1.3 0x040；§10.1：rd←imm[31:12] 左移 12、RV64 符号扩展、无源）----
      OPC_LUI: begin
        u.isop       = ISOP_LUI;
        u.src_sel    = SRC_ZERO;               // §9.5 R3：无寄存器/PC 源、结果＝立即数零基
        u.imm_kind   = IMM_ALU;                // §2.1：U 型 = 01
        u.imm        = uimm20_44(w[31:12]);
        rd_writes    = 1'b1;
      end

      // ---- U 型（M2 增补）：AUIPC（§9.1.3 0x010；§10.1：rd←pc＋（imm[31:12] 左移 12））----
      //   源面＝PC（§9.5 R2，优先于 R4 的 imm 面）；目标/结果为 pc＋已符号扩展的 U 型立即数。
      OPC_AUIPC: begin
        u.isop       = ISOP_AUIPC;
        u.src_sel    = SRC_PC;
        u.imm_kind   = IMM_ALU;
        u.imm        = uimm20_44(w[31:12]);
        rd_writes    = 1'b1;
      end

      // ---- I 型 ALU：ADDI/SLTI/SLTIU/XORI/ORI/ANDI/SLLI/SRLI/SRAI（§9.1.1；M2 增补 7 条）----
      OPC_OPIMM: begin
        unique case (f3)
          3'b000: begin                        // ADDI（0x000）
            u.isop = ISOP_ADDI;
            u.imm  = sext12_44(w[31:20]); u.imm_kind = IMM_ALU;
          end
          F3_SLTI: begin                       // SLTI（0x001；有符号立即数比较）
            u.isop = ISOP_SLTI;
            u.imm  = sext12_44(w[31:20]); u.imm_kind = IMM_ALU;
          end
          F3_SLTIU: begin                      // SLTIU（0x002；立即数按符号扩展后**无符号**比较）
            u.isop = ISOP_SLTIU;
            u.imm  = sext12_44(w[31:20]); u.imm_kind = IMM_ALU;
          end
          F3_XORI: begin                       // XORI（0x003）
            u.isop = ISOP_XORI;
            u.imm  = sext12_44(w[31:20]); u.imm_kind = IMM_ALU;
          end
          F3_ORI: begin                        // ORI（0x004）
            u.isop = ISOP_ORI;
            u.imm  = sext12_44(w[31:20]); u.imm_kind = IMM_ALU;
          end
          F3_ANDI: begin                       // ANDI（0x005）
            u.isop = ISOP_ANDI;
            u.imm  = sext12_44(w[31:20]); u.imm_kind = IMM_ALU;
          end
          F3_SLLI: begin                       // SLLI（0x006）：RV64 funct6 必须为 0（非 0 为保留编码）
            if (w[31:26] == F6_ZERO) begin
              u.isop = ISOP_SLLI;
              u.imm  = {38'b0, w[25:20]};        // shamt[5:0]（§9.1.1；无符号 ⇒ 零扩展）
              u.imm_kind = IMM_SHAMT;
            end else begin
              u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
            end
          end
          F3_SRLI: begin                       // SRLI（0x007）/ SRAI（0x008）：funct6 00_0000／01_0000 分列
            if (w[31:26] == F6_ZERO) begin
              u.isop = ISOP_SRLI;
              u.imm  = {38'b0, w[25:20]}; u.imm_kind = IMM_SHAMT;
            end else if (w[31:26] == F6_SRA) begin
              u.isop = ISOP_SRAI;
              u.imm  = {38'b0, w[25:20]}; u.imm_kind = IMM_SHAMT;
            end else begin
              u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
            end
          end
          default: begin
            u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
          end
        endcase
        // I 型 ALU 公共源/目的面（合法分支统一补齐；非法分支不留半成品载荷）
        if (!u.pre_exc) begin
          u.rs1_en  = 1'b1; u.rs1 = rs1;
          u.src_sel = SRC_IMM;                 // §9.5 R4：含立即数操作数面
          rd_writes = 1'b1;
        end
      end

      // ---- OP-IMM-32（opcode 0011011）：ADDIW/SLLIW/SRLIW/SRAIW（§9.1.2；M2 增补 3 条）----
      //   注：**本族不是 R 型** —— f3=000（ADDIW）时 w[31:25] 是**立即数高位**（imm[11:5]），
      //   不得当 funct7 判 ⇒ 该分支只按 f3 识别（与 G1-I 版一致）；只有 f3=001/101 的移位成员
      //   才带 funct7 语义（0000000／0100000）。
      OPC_OPIMM32: begin
        unique case (f3)
          3'b000: begin                        // ADDIW（0x020）
            u.isop = ISOP_ADDIW;
            u.imm  = sext12_44(w[31:20]); u.imm_kind = IMM_ALU;
          end
          3'b001: begin                        // SLLIW（0x021）：funct7 必须 0（bit25=1 为保留编码）
            if (f7 == F7_BASE) begin
              u.isop = ISOP_SLLIW;
              u.imm  = {38'b0, w[24:20]};      // shamt 5 bit（§9.1.2；无符号 ⇒ 零扩展）
              u.imm_kind = IMM_SHAMT;
            end else begin
              u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
            end
          end
          3'b101: begin                        // SRLIW（0x022）/ SRAIW（0x023）：funct7 分列
            if (f7 == F7_BASE) begin
              u.isop = ISOP_SRLIW;
              u.imm  = {38'b0, w[24:20]}; u.imm_kind = IMM_SHAMT;
            end else if (f7 == F7_SUB) begin
              u.isop = ISOP_SRAIW;
              u.imm  = {38'b0, w[24:20]}; u.imm_kind = IMM_SHAMT;
            end else begin
              u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
            end
          end
          default: begin
            u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
          end
        endcase
        if (!u.pre_exc) begin
          u.rs1_en  = 1'b1; u.rs1 = rs1;
          u.src_sel = SRC_IMM;                 // §9.5 R4（OP-32 立即数 4 条）
          u.is_w    = 1'b1;
          u.sext    = 1'b1;                    // §9.5：W 型 9 成员 = 1（结果按 bit31 扩展）
          rd_writes = 1'b1;
        end
      end

      // ---- OP-32（opcode 0111011）：ADDW/SUBW/SLLW/SRLW/SRAW（§9.1.2；M2 增补 5 条）----
      //   本族是 **R 型**（第二面＝rs2 寄存器）⇒ funct7 判合法（0000000 基础组／0100000 SUB·SRA 组）。
      OPC_OP32: begin
        unique case (f3)
          3'b000: begin                        // ADDW（0x050）/ SUBW（0x051）
            if      (f7 == F7_BASE) u.isop = ISOP_ADDW;
            else if (f7 == F7_SUB)  u.isop = ISOP_SUBW;
            else begin u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL; end
          end
          3'b001: begin                        // SLLW（0x052）
            if (f7 == F7_BASE) u.isop = ISOP_SLLW;
            else begin u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL; end
          end
          3'b101: begin                        // SRLW（0x053）/ SRAW（0x054）
            if      (f7 == F7_BASE) u.isop = ISOP_SRLW;
            else if (f7 == F7_SUB)  u.isop = ISOP_SRAW;
            else begin u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL; end
          end
          default: begin
            u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
          end
        endcase
        if (!u.pre_exc) begin
          u.rs1_en  = 1'b1; u.rs1 = rs1;
          u.rs2_en  = 1'b1; u.rs2 = rs2;
          u.src_sel = SRC_PRF;                 // §9.5 R5（OP-32 寄存器 5 条）
          u.is_w    = 1'b1;
          u.sext    = 1'b1;
          rd_writes = 1'b1;
        end
      end

      // ---- OP：基础面 ADD（§9.1.1 0x030）＋ M 扩展 MUL/DIV/REM（§9.1.6）----
      OPC_OP: begin
        if (f7 == F7_MULDIV) begin
          u.rs1_en  = 1'b1; u.rs1 = rs1;
          u.rs2_en  = 1'b1; u.rs2 = rs2;
          u.src_sel = SRC_PRF;                 // §9.5 R5：第二面为 PRF 寄存器
          rd_writes = 1'b1;
          unique case (f3)
            3'b000: u.isop = ISOP_MUL;
            F3_DIV: u.isop = ISOP_DIV;
            F3_REM: u.isop = ISOP_REM;
            default: begin
              u.isop    = '0;                  // 未识别：不得断言任何成员（§9.3 reserved 规则）
              u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
            end
          endcase
          if (u.pre_exc) begin                 // 非法分支：撤掉已写成的源面（不留半成品载荷）
            u.rs1_en = 1'b0; u.rs2_en = 1'b0; u.src_sel = '0; rd_writes = 1'b0;
          end
        end else if ((f7 == F7_BASE) || (f7 == F7_SUB)) begin
          // ---- M2 增补：基础 OP 面（§9.1.1；f7=0000000 → ADD/SLL/SLT/SLTU/XOR/SRL/OR/AND，
          //      f7=0100000 → SUB/SRA）。第二面一律为 PRF 寄存器（§9.5 R5）、无立即数面 ----
          unique case (f7)
            F7_BASE: begin
              unique case (f3)
                3'b000: u.isop = ISOP_ADD;
                3'b001: u.isop = ISOP_SLL;
                3'b010: u.isop = ISOP_SLT;
                3'b011: u.isop = ISOP_SLTU;
                3'b100: u.isop = ISOP_XOR;
                3'b101: u.isop = ISOP_SRL;
                3'b110: u.isop = ISOP_OR;
                3'b111: u.isop = ISOP_AND;
              endcase
            end
            default: begin                       // F7_SUB（f7 已由外层守卫限定为 0000000/0100000）
              if (f3 == 3'b000) begin
                u.isop = ISOP_SUB;
              end else if (f3 == 3'b101) begin
                u.isop = ISOP_SRA;
              end else begin
                u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
              end
            end
          endcase
          if (!u.pre_exc) begin
            u.rs1_en  = 1'b1; u.rs1 = rs1;
            u.rs2_en  = 1'b1; u.rs2 = rs2;
            u.src_sel = SRC_PRF;                 // §9.5 R5：第二面为 PRF 寄存器
            rd_writes = 1'b1;
          end
        end else begin
          u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
        end
      end

      // ---- 条件分支 6 条：BEQ/BNE（§9.1.3 0x080/0x081）＋ BLT/BGE/BLTU/BGEU（M3-(d) 增补，
      //      0x082..0x085；均无目的、源 rs1/rs2、B 型偏移 00）----
      //   条件判决**不在 D 级**：本模块只给 `isop` 成员（条件由成员唯一承载，§9.4-(2) 分列裁定），
      //   方向解析在 M10 `vr1_bru`（§10.2「同上（与 BEQ 同体例）」逐行）。
      //   `f3=010/011`（保留编码）⇒ 非法（`spec/02` §9.3 保留段规则②）。
      OPC_BRANCH: begin
        unique case (f3)
          F3_BEQ:  u.isop = ISOP_BEQ;
          F3_BNE:  u.isop = ISOP_BNE;
          F3_BLT:  u.isop = ISOP_BLT;
          F3_BGE:  u.isop = ISOP_BGE;
          F3_BLTU: u.isop = ISOP_BLTU;
          F3_BGEU: u.isop = ISOP_BGEU;
          default: begin
            u.isop = '0;                                                 // 未识别：不得断言任何成员
            u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
          end
        endcase
        if (!u.pre_exc) begin
          u.rs1_en   = 1'b1; u.rs1 = rs1;
          u.rs2_en   = 1'b1; u.rs2 = rs2;
          u.src_sel  = SRC_PRF;                                          // §9.5 R5（分支 6 条）
          u.imm_kind = IMM_OFF;                                          // §2.1：B 型 = 00
          u.imm      = sext13_44({w[31], w[7], w[30:25], w[11:8], 1'b0});
          rd_writes  = 1'b0;                                             // 无链接
        end
      end

      // ---- 间接跳转：JALR（§9.1.3 0x090；M3-(d) 增补）----
      //   `spec/02` §10.2 行：`rd=01`（link=pc＋4）、源 rs1、**目标＝（rs1＋I 型偏移）最低位清零**；
      //   §9.5 R4：`src_sel=01 imm`（偏移参与数据通路）／§2.1：I 型偏移 `imm_kind=00`。
      //   目标式计算（含 `&~1`）归 M10 `vr1_bru`（§3.12 `br_resolve_t.target_real`）——本模块只给
      //   成员与立即数位域（I 型：imm[11:0] 符号扩展）。
      //   `f3≠000`：规范只定义 f3=000 的 JALR（其余为保留编码）⇒ 非法。
      OPC_JALR: begin
        if (f3 == 3'b000) begin
          u.isop     = ISOP_JALR;
          u.rs1_en   = 1'b1; u.rs1 = rs1;
          u.src_sel  = SRC_IMM;                                          // §9.5 R4（JALR 1：偏移）
          u.imm_kind = IMM_OFF;
          u.imm      = sext12_44(w[31:20]);
          rd_writes  = 1'b1;                                             // link＝pc＋4（rd=x0 时由 SI-1 收口）
        end else begin
          u.isop = '0;
          u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
        end
      end

      // ---- 无条件跳转：JAL（§9.1.3 0x0A0；源＝pc，rd 可 x0）----
      OPC_JAL: begin
        u.isop     = ISOP_JAL;
        u.src_sel  = SRC_PC;                                           // §9.5 R2：目标＝pc＋偏移
        u.imm_kind = IMM_OFF;                                          // §2.1：J 型 = 00
        u.imm      = sext21_44({w[31], w[19:12], w[20], w[30:21], 1'b0});
        rd_writes  = 1'b1;                                             // link＝pc＋4（rd=x0 时由 SI-1 收口 ⇒ dst_kind=00）
      end

      // ---- 载入 7 条：LB/LH/LW/LD/LBU/LHU/LWU（§9.1.4 0x100..0x106；M3-(d) 补齐余 6 条）----
      //   逐成员派生（§9.5「`dm`」/「`sext`」两行，逐条照表）：
      //     LB/LBU=00、LH/LHU=01、LW/LWU=10、LD=11；sext：LB/LH/LW=1、LBU/LHU/LWU=0、
      //     LD **不适用**（整宽无扩展 ⇒ 本版取 0，LSU 侧只对 <64 bit 的宽度消费该域）。
      //   `f3=111` ⇒ 非法（§9.1.4 只有 7 个载入成员；保留编码规则同 §9.3）。
      OPC_LOAD: begin
        u.rs1_en   = 1'b1; u.rs1 = rs1;
        u.src_sel  = SRC_IMM;                                          // §9.5 R4（载入 7 条＝偏移）
        u.imm_kind = IMM_OFF;
        u.imm      = sext12_44(w[31:20]);
        u.sext     = 1'b0;
        unique case (f3)
          3'b000: begin u.isop = ISOP_LB;  u.dm = DM_B; u.sext = 1'b1; end
          3'b001: begin u.isop = ISOP_LH;  u.dm = DM_H; u.sext = 1'b1; end
          3'b010: begin u.isop = ISOP_LW;  u.dm = DM_W; u.sext = 1'b1; end
          3'b011: begin u.isop = ISOP_LD;  u.dm = DM_D; end             // LD：sext 不适用（§9.5）
          3'b100: begin u.isop = ISOP_LBU; u.dm = DM_B; end
          3'b101: begin u.isop = ISOP_LHU; u.dm = DM_H; end
          3'b110: begin u.isop = ISOP_LWU; u.dm = DM_W; end
          default: begin
            u.isop = '0;
            u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;            // f3=111：保留编码
          end
        endcase
        if (!u.pre_exc) rd_writes = 1'b1;
        else begin u.rs1_en = 1'b0; u.rs1 = 5'd0; u.src_sel = '0; end   // 非法分支：撤掉源面
      end

      // ---- 存储 4 条：SB/SH/SW/SD（§9.1.4 0x180..0x183；M3-(d) 补齐余 3 条；无目的）----
      //   `dm`＝SB 00／SH 01／SW 10／SD 11（§9.5）；store 无扩展面 ⇒ `sext` 恒 0（§9.5「其余不适用」）。
      //   `f3≥100` ⇒ 非法（§9.1.4 只有 4 个存储成员）。
      OPC_STORE: begin
        u.rs1_en   = 1'b1; u.rs1 = rs1;
        u.rs2_en   = 1'b1; u.rs2 = rs2;
        u.src_sel  = SRC_IMM;                                          // §9.5 R4（存储 4 条＝偏移）
        u.imm_kind = IMM_OFF;
        u.imm      = sext12_44({w[31:25], w[11:7]});
        u.sext     = 1'b0;                                             // store 无扩展面（不适用）
        unique case (f3)
          3'b000: begin u.isop = ISOP_SB; u.dm = DM_B; end
          3'b001: begin u.isop = ISOP_SH; u.dm = DM_H; end
          3'b010: begin u.isop = ISOP_SW; u.dm = DM_W; end
          3'b011: begin u.isop = ISOP_SD; u.dm = DM_D; end
          default: begin
            u.isop = '0;
            u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
          end
        endcase
        if (u.pre_exc) begin u.rs1_en = 1'b0; u.rs2_en = 1'b0;
                             u.rs1 = 5'd0; u.rs2 = 5'd0; u.src_sel = '0; end
        rd_writes = 1'b0;
      end

      // ---- MISC-MEM：FENCE（§9.1.8 0x380）／FENCE.I（§9.1.8 0x381；Zifencei，M3-(d) 增补）----
      //   依据：`spec/00` §2 一期 ISA 串 ＝ `rv64imac_zicsr_zifencei` ⇒ `zifencei` **在一期范围内**
      //   （含 Zifencei 行的"一期附带"注），故按"最小语义"入面。
      //   最小语义（`spec/02` §10.8 两行「同上」＋ §9.5 R1「无操作数消费 ⇒ `src_sel` 不适用」）：
      //     · 两者均为"序"类（`type.bit4`），**无寄存器目的/源、无立即数语义**（fm/pred/succ 为编码
      //       常量字段，承载域＝§9.2-(7)，本版不消费）；
      //     · 本版无 L1I、无 store buffer、取指桩为组合读（无脏行）⇒ FENCE/FENCE.I 的**排空与
      //       无效化动作集合为空**（`spec/11` 的序面断言归后续批）——即"识别 + 无副作用完成"。
      //   `f3∉{000,001}` ⇒ 非法（ISS 侧同口径：`machine.py` 只允许 FENCE(0)/FENCE.I(1)）。
      OPC_MISC: begin
        if      (f3 == F3_FENCE)  u.isop = ISOP_FENCE;
        else if (f3 == F3_FENCEI) u.isop = ISOP_FENCEI;
        else begin
          u.isop = '0;
          u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
        end
        // 无操作数面：`src_sel`/`imm_kind`/`rs*_en`/`rd_en` 一律保持初值 0（§9.5 R1「不适用」）
      end

      // ---- SYSTEM：MRET（§9.1.8）＋ CSR（§9.1.7：CSRRW/CSRRS）----
      OPC_SYSTEM: begin
        if (f3 == 3'b000) begin
          if ((f7 == F7_MRET) && (rs2 == RS2_MRET) && (rs1 == 5'd0) && (rd == 5'd0)) begin
            u.isop = ISOP_MRET;                                        // 无操作数（§9.5 R1 ⇒ `src_sel`/`imm_kind` 不适用、恒 0）
          end else begin
            u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;            // ECALL/EBREAK/SRET/... 不在 14 条内
          end
        end else if ((f3 == 3'b001) || (f3 == 3'b010)) begin
          // 寄存器型 CSR：写数据源＝rs1（`wdata_sel` 归 spec/10 的 T-3；本版不产生）
          u.isop        = (f3 == 3'b001) ? ISOP_CSRRW : ISOP_CSRRS;
          u.rs1_en      = 1'b1;
          u.rs1         = rs1;
          u.src_sel     = SRC_PRF;                                     // §9.5 R5（CSR 寄存器 3 条）
          u.csr_addr    = w[31:20];                                    // §3.4 `csr_addr` 12 bit
          u.csr_wr_type = (f3 == 3'b001) ? CSR_WR_RW : CSR_WR_RS;      // §9.4-(4) 成员→写类型映射
          rd_writes     = 1'b1;
          dst_is_csr    = 1'b1;                                        // §9.1.7：dst_kind=11（CSR 旧值→GPR）
          // 注：`csr_wr_type=2'b11`（读使能-only）与 `2'b10`（RC）本版**不产生**——
          //   · CSRRC 不在 14 条内；· 「CSRRS/CSRRC 且 rs1=x0 ⇒ 不写 CSR」（`spec/02` §4.1 AN-07）
          //   的判决点在 **CSR 单元**（M1-S4，`csrq` 队列）、不在 D 级；`spec/02` §3.5 的
          //   「`csr_wr_type` 与 `op` 的编码空间关系」＝ T-2/T-3 **未闭** ⇒ 本模块不抢先自造映射。
        end else begin
          u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;              // CSRRWI/CSRRSI/CSRRCI 不在 14 条内
        end
      end

      // ---- 未识别 opcode（含全 0／全 1 字、保留空间）：一律非法（文件头"首版子集口径"）----
      default: begin
        u.pre_exc = 1'b1; u.pre_exc_code = EXC_ILLEGAL;
      end
    endcase

    // 目的面统一收口（`spec/02` §4.1 **SI-1**：任何 `rd=x0` 的 μop ⇒ `dst_kind=00`、
    //   不分配 PRF 目的、不消耗 free-list ⇒ 本模块在此处而非逐成员处置）
    if (rd_writes && (rd != 5'd0)) begin
      u.rd       = rd;
      u.rd_en    = 1'b1;
      u.dst_kind = dst_is_csr ? DST_CSR : DST_GPR;
    end else begin
      u.rd       = 5'd0;
      u.rd_en    = 1'b0;
      u.dst_kind = DST_NONE;
    end

    // 非法条目：撤掉结果面（异常条目不得携带可执行的语义载荷；`spec/02` §19 提交抑制口径的 D 侧前置）
    if (u.pre_exc) begin
      u.rd       = 5'd0;
      u.rd_en    = 1'b0;
      u.dst_kind = DST_NONE;
    end

    // `cls` ＝ `isop[9:7]` **恒等投影**（`spec/02` §9.4-(6)／§9.5 逐成员值）——由 `isop` 一次导出，
    //   不设第二张表（防双编码，§9.4-(6) 判据）
    u.cls = u.isop[9:7];

    return u;
  endfunction

  // -------------------------------------------------------------------------
  // 本窗消费指针（IBUF 槽号 0..IBUF_ENTRIES；本版＝单窗在飞，见下"状态与不变量"）
  // -------------------------------------------------------------------------
  logic [4:0]       rd_ptr_q;                  // 本窗内下一个候选起始槽号（5 bit 装得下 0..16）
  logic [4:0]       slot_of [DECODE_WIDTH];    // 本拍各 lane 选中的槽号
  int unsigned      n_sel;                     // 本拍有效 lane 数（0..DECODE_WIDTH）
  logic [4:0]       last_sel;                  // 本拍最后一 lane 的槽号（n_sel>0 时有效）
  logic             take;                      // 本拍结果被下游接受（D→R 握手）
  logic             remain;                    // 本窗内仍有未取走的起始槽

  // 槽可选判据：本窗有效 ∧ 该槽为指令起始（P5 walk 产出）∧ 槽号 ≥ 读指针
  logic [IBUF_ENTRIES-1:0] lane_avail;
  always_comb begin
    for (int unsigned i = 0; i < IBUF_ENTRIES; i++)
      lane_avail[i] = ibuf_win_vld_i && ibuf_rd_i[i].valid && (i >= rd_ptr_q);
  end

  // 选择与打包：按槽号**升序**取前 `DECODE_WIDTH` 个起始槽 → lane 0..n_sel-1（程序序）
  always_comb begin
    int unsigned n;
    n     = 0;
    n_sel = 0;
    for (int unsigned k = 0; k < DECODE_WIDTH; k++) begin
      uop_o[k]   = '0;                         // 未选中 lane 恒 0（`valid=0`）
      slot_of[k] = 5'd0;
    end
    for (int unsigned i = 0; i < IBUF_ENTRIES; i++) begin
      if (lane_avail[i] && (n < DECODE_WIDTH)) begin
        uop_o[n]   = decode_word(ibuf_rd_i[i].raw32, ibuf_rd_i[i].pc,
                                 ibuf_rd_i[i].ftq_id, ibuf_rd_i[i].bp_upd_id);
        slot_of[n] = i[4:0];
        n          = n + 1;
        n_sel      = n;
      end
    end
  end

  always_comb begin
    last_sel = slot_of[0];
    if (n_sel > 0) last_sel = slot_of[n_sel-1];
  end

  // 剩余判据：本窗内仍有"未取走的起始槽"⇒ 不能置 drain
  logic [IBUF_ENTRIES-1:0] sel_mask;
  always_comb begin
    sel_mask = '0;
    for (int unsigned k = 0; k < DECODE_WIDTH; k++)
      if (k < n_sel) sel_mask[slot_of[k]] = 1'b1;
    remain = |(lane_avail & ~sel_mask);
  end

  assign take         = (n_sel != 0) && uop_ready_i && !flush_i;   // 冲刷拍不接受（M1-S3）
  assign ibuf_drain_o = take && !remain;       // 本窗末拍：本拍取走了本窗最后一批起始槽

  // -------------------------------------------------------------------------
  // 读指针：接受拍推进到"最后选中槽 + 1"；本窗取尽（drain）⇒ 归零（下一窗自槽 0 起扫）；
  //   **冲刷拍归零**（M1-S3）：窗被作废后必须自槽 0 重扫，否则新窗的低槽被跳过
  // -------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rd_ptr_q <= 5'd0;
    end else if (flush_i) begin
      rd_ptr_q <= 5'd0;
    end else if (take) begin
      rd_ptr_q <= ibuf_drain_o ? 5'd0 : (last_sel + 5'd1);
    end
  end

  // -------------------------------------------------------------------------
  // 状态与不变量（本版如实列出，防误读；断言化归 SVA 批 `spec/11` §7 A 类，本批不含）：
  //   ① **单窗在飞**：IBUF 内至多一个窗（M03 写口反压：`ibuf_win_vld` 未清则 F0 不出队、
  //      不发请求）⇒ D 侧无需窗身份标签（`ftq_id` 随各槽携带，用于随流追溯）；
  //   ② **窗 ⇒ 至少一个起始槽**：P5 walk 的守卫（起始槽 ≤ `SLOTS-2` 且步长 2 且条数 < `nib`）
  //      在"块起始 4 B 对齐、`nib`＝窗内余量/2"（首版：`vr1_bp` 恒产 32 B 对齐块、`nib=8`）下
  //      保证 ≥1 槽带 `valid` ⇒ **不存在"窗内零起始槽"导致 D 无物可取**的构型；
  //      该不变式的机器检查归 SVA 批（`spec/11`），本模块不自设断言（规则 14）。
  //   ③ `uop_ready_i=0`（R 级反压）时：不推进指针、不置 drain ⇒ 同一组 lane 在下一拍重新呈现，
  //      **不丢不重**（M1-S2 无 R 级消费 ⇒ `vr1_core` 恒接 1，见其接线注）。
  // -------------------------------------------------------------------------
  // synopsys translate_off
  initial $display("[vr1_decode] M05 D-stage: 57-member legal face (G1-I 14 + M2 ALU/AUIPC 27 + M3-(d) 16: BLT/BGE/BLTU/BGEU/JALR + LOAD/STORE full family + FENCE/FENCE.I) decode + IBUF consume/drain landed at M1-S2; consumer (R/rename) NOT implemented (TODO(M1-S3))");
  // synopsys translate_on

endmodule

`endif // VR1_DECODE_SV
