// ==========================================================================
// rtl/vr1/ctrl/vr1_trap.sv — M18 trap 单元（现场组装 ＋ `mtvec` 重定向 ＋ 冲刷脉冲）
//
// 状态（不得误读，红线 R8）：
//   · 本模块**已实现**（M1-S3 第二批）：
//     ① **`excp_t` 现场组装**（`spec/01` §3.18「产生点署名」：组装者 = `vr1_trap`，**只在提交拍
//        一次**）：来源 ① ROB 头条目（`cause ← exc_code`、`is_intr`、`epc ← 头 pc`、`instr ← raw32`、
//        `from ← 条目 priv`）② `vr1_csr` 同拍组合输出（`mprv_at_trigger`/`mpp_at_trigger` 现场取样）
//        ③ 本模块按向量表规则组合（`to`/`vec_off`）；
//     ② **入口地址**（`spec/10` §2「入口＝`mtvec`（Direct or Vectored）」）：`MODE=1`（Vectored）
//        **且**中断 ⇒ `BASE + 4×cause`，否则 `BASE`（Direct）；
//     ③ **重定向 + `flush_all`**：trap 类 B（本条带异常）与串行化类 B（`MRET`）的冲刷/重取
//        （`spec/01` §5.3③ D3-① 三路）；脉冲口径＝提交拍一拍。
//   · 首版口径登记（**不新造语义**，逐条给依据/出口）：
//     - `excp_t.tval`/`spep` 的**级间载体**在冻结面无定义（`spec/01` §3.18 尾注：「`tval`/`spep`
//       的取值来源本文未定义、归 `spec/10`」，T-10-4 未闭）⇒ 本版由 `E` 拍随完成回报携带到
//       提交拍（内部寄存器，非新 struct），**不据该域做任何判决** —— TODO(G1-F)（T-10-4 收口）；
//     - `deleg`/`spep` 恒 0、`to` 恒 M：一期单特权级、无 S 态委托（`spec/10` §3／清单 §2.6）——
//       TODO(G1-F)（S 态委托）；
//     - `sbe`/`cle`/`svae`/`va_bad`/`is_c` 恒 0：无 PMA/PMP/翻译面、无 C 展开（清单 §1.2 第 1/6 条）；
//     - `kill`/`wfi` 面（§3.17 `wfi_vld`）不在 G1-I 14 条内 ⇒ 恒 0。
//
// 依据（逐条可核）：
//   · doc/spec/01 §3.18（`excp_t` 177 bit 成员位域与产生点署名）／§5.1（触发源与优先级）／
//     §5.3（重定向与重取三路）；§3.21 `rt_t.exc_v/exc_cause/is_intr`；
//   · doc/spec/10 §2（进场 6 动作／返回动作／重执行）／§2.1（码表）／§4.1 `mtvec`（Direct＋Vectored）；
//   · doc/spec/00 §4.7 `MTVEC_MODES`＝Direct + Vectored；
//   · doc/decisions/G1-I-最小冻结清单.md §2.1 第 19 行（`vr1_trap`；`flush_all_t`/`redirect_t`
//     首版为**内部信号**——零定义型，不冻、不自造）／§2.6（恒 0 表）。
//
// 写授权：`state/freeze.json` 的 rtl_write_authorized=true（R0 2026-09-25 签署 G1-I 的人令）。
// ==========================================================================
`ifndef VR1_TRAP_SV
`define VR1_TRAP_SV

module vr1_trap
  import vr1_pkg::*;
(
  input  logic        clk,            // 本版纯组合（无内部状态）；clk/rst_n 为后续 SVA/流水留位
  input  logic        rst_n,

  // ---- 提交拍：ROB 头条目（`spec/01` §3.7）----
  input  logic        exc_vld_i,      // 条目 `exc_v`（异常/中断标记）
  input  logic [3:0]  exc_code_i,     // 条目 `exc_code`（§2.1 码）
  input  logic        exc_is_intr_i,  // 条目 `is_intr`（一期恒 0：无中断源，清单 §1.2）
  input  logic [39:0] exc_pc_i,       // 条目 `pc`（→ `epc`）
  input  logic [31:0] exc_instr_i,    // 条目 `raw32`（→ `instr`）
  input  logic [1:0]  exc_priv_i,     // 条目 `priv`（→ `from`）

  // ---- 提交拍：触发信息（`tval`；载体见文件头 TODO(G1-F)）----
  input  logic [39:0] exc_tval_i,

  // ---- CSR 现场（`vr1_csr` 同拍组合输出）----
  input  logic [63:0] mtvec_i,
  input  logic [63:0] mstatus_i,

  // ---- 返回控制（MRET；`vr1_csr` 提交拍组合输出，§3.18）----
  input  var vr1_pkg::ret_ctrl_t ret_i,

  // ---- 输出：现场包 ＋ 重定向 ＋ 冲刷 ----
  output vr1_pkg::excp_t excp_o,
  output logic        redirect_vld_o, // 本拍重定向（trap 或 MRET 返回）
  output logic [39:0] redirect_pc_o,  // 重定向目标 pc
  output logic        flush_all_o     // 冲刷脉冲（同 `redirect_vld_o`；内部信号口径，清单 §2.1 #19）
);

  localparam logic [1:0] PRV_M = 2'b11;
  localparam logic [1:0] MTVEC_VECTORED = 2'b01;      // `spec/10` §4.1：MODE∈{0 Direct,1 Vectored}

  // -------------------------------------------------------------------------
  // 入口地址（`spec/10` §2：Direct ＝ BASE；Vectored ＋ 中断 ＝ BASE + 4×cause）
  //   `spec/10` §4.1：`BASE` 对齐 4 B ⇒ 取 `mtvec[63:2]`（低 2 位为 MODE）
  // -------------------------------------------------------------------------
  logic [63:0] mvec_base;
  logic [63:0] trap_pc;
  logic [5:0]  vec_off;

  // `BASE` = `mtvec[63:2] << 2`（低 2 位是 `MODE`，必须**左移补回**，不是高位补零）
  assign mvec_base = {mtvec_i[63:2], 2'b00};
  assign vec_off   = {2'b00, exc_code_i, 2'b00};      // 4 × cause（cause ≤ 15 ⇒ 6 bit 装得下）

  always_comb begin
    if ((mtvec_i[1:0] == MTVEC_VECTORED) && exc_is_intr_i)
      trap_pc = mvec_base + {58'd0, vec_off};
    else
      trap_pc = mvec_base;
  end

  // -------------------------------------------------------------------------
  // 重定向（trap 优先于 MRET；单提交 ⇒ 构造上互斥）与冲刷脉冲
  // -------------------------------------------------------------------------
  assign redirect_vld_o = exc_vld_i || ret_i.vld;
  assign redirect_pc_o  = exc_vld_i ? trap_pc[39:0] : ret_i.epc;
  assign flush_all_o    = redirect_vld_o;

  // -------------------------------------------------------------------------
  // `excp_t` 现场组装（§3.18 成员逐项；来源逐条见文件头）
  // -------------------------------------------------------------------------
  always_comb begin
    excp_o                  = '0;
    excp_o.vld              = exc_vld_i;
    excp_o.cause            = exc_code_i;
    excp_o.is_intr          = exc_is_intr_i;
    excp_o.epc              = exc_pc_i;
    excp_o.tval             = exc_tval_i;              // 载体口径见文件头 TODO(G1-F)
    excp_o.from             = exc_priv_i;
    excp_o.to               = PRV_M;                   // 一期单特权级（不委托）
    excp_o.deleg            = 1'b0;                    // 无 S 态委托（清单 §1.2）
    excp_o.vec_off          = vec_off;                 // vectored 模式偏移（§3.18）
    excp_o.instr            = exc_instr_i;
    excp_o.is_c             = 1'b0;                    // 无 C（清单 §1.2 第 6 条）
    excp_o.sbe              = 1'b0;                    // mstatus.SBE 一期恒 0（§3.18 尾注）
    excp_o.cle              = 1'b0;
    excp_o.svae             = 1'b0;                    // 硬件置 A/D（`spec/00` §4.6）
    excp_o.va_bad           = 1'b0;                    // 无翻译/PMP 判决面
    excp_o.mprv_at_trigger  = mstatus_i[17];           // MPRV 现场取样（§3.18 尾注）
    excp_o.mpp_at_trigger   = mstatus_i[12:11];        // MPP 现场取样
    excp_o.spep             = 40'd0;                   // 无 S 态（TODO(G1-F)）
  end

  // -------------------------------------------------------------------------
  // 状态与不变量（本版如实列出；断言化归 SVA 批 `spec/11` §7，本批不含）：
  //   ① 重定向脉冲恰一拍（组合自提交拍）；② `MODE≥2` 时按 Direct 处置（`mtvec` 的 WARL 掩码
  //      未施加——与 ISS 同口径，见 `vr1_csr` 文件头）；③ `vec_off` == 4×cause（vectored 中断）。
  // -------------------------------------------------------------------------
  // synopsys translate_off
  initial $display("[vr1_trap] M18 TRAP: excp_t assembly + mtvec redirect (Direct/Vectored) + flush pulse landed at M1-S3b; deleg/S-mode and tval carrier TODO(G1-F)");
  // synopsys translate_on

endmodule

`endif // VR1_TRAP_SV
