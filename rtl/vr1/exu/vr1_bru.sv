// ==========================================================================
// rtl/vr1/exu/vr1_bru.sv — M10 分支解析单元（`BRU`：`E` 级组合解析 → `br_resolve_t` 冲刷请求）
//
// 状态（不得误读，红线 R8）：
//   · 本模块**已实现**（M1-S3 第一批，`doc/design/M1-实现计划.md` §5 S3 行 / §2.1 第 11 行）：
//     ① **`BEQ`/`JAL` 解析**（G1-I 14 条中的两条控制转移；`spec/02` §9.1.3）：方向
//        `taken_real` 与目标 `target_real = pc + 偏移`（偏移按 ISA 语义符号扩展、40 bit 域内回绕）；
//     ①' **`BNE` 解析**（M2 增补，2026-09-26 心跳第 5 轮）：`spec/02` §9.1.3 `BNE`=0x081 ／
//        §10.2 行「同上（与 BEQ 同体例：无目的、源 rs1/rs2、无同步异常）」——方向判据＝
//        `rs1_val != rs2_val`（64 bit 逐位不等），目标式与 `BEQ` 同式。入面依据＝
//        `sim/image/rv64ui/GAP.json` 的机械反算（52 条子集测试**全部**含 `bne`）；
//     ①'' **条件分支 6 条全入面 ＋ JALR**（M3-(d) 增补，2026-09-26 心跳第 10 轮）：`BLT`/`BGE`
//        按**有符号**比较、`BLTU`/`BGEU` 按**无符号**比较（`spec/02` §9.1.3 逐成员含义行
//        「有符号/无符号小于／大于等于分支」＋ §10.2 六行「同上」）；`JALR` 目标＝
//        `(rs1_val + sext(imm)) & ~1`（§10.2 JALR 行逐字；`IALIGN=16` 下 bit1≠0 **不产生**
//        instruction-address-misaligned，故本单元只清 bit0、不产 fault）；`is_jalr_ret` 按
//        §16.4-(2) T-7 定案谓词构造（不再是"构造不可达"的恒 0）。入面依据同 GAP 机械反算；
//     ② **`mispred` 形成**（`spec/01` §3.12 逐字）：`= (taken_real != pred_taken) ||
//        (taken_real && (target_real != pred_target))`——首版预测器恒"预测不跳转"（`vr1_bp`），
//        故 taken 必误预测；
//     ③ **1 条/拍**输出（§3.12 口径）：同拍多分支 lane 时按 **lane 号小 = 更老**取最老一条
//        （首版单发射，`doc/design/M1-实现计划.md` §2.3 简化 #1）。
//   · 本模块**未实现**（逐条给出口，未完成项一律 TODO，不写"看起来对"的逻辑）：
//     - **`wb_t` 写回**（M10 在 `spec/00` §6 的另一个输出：JAL 的 link＝`pc+4`）：随写回通路
//       （WB 级）落地 —— TODO(M1-S3)；
//     - **`is_jalr_ret`**（M3-(d) 起**已实现**）：谓词＝`JALR ∧ (rs1_arch∈{x1,x5}) ∧ (rd_arch≠rs1_arch)`
//       （`spec/01` §3.12／`spec/02` §16.4-(2) T-7）。**下游消费（RAS 更新/预测）归 `spec/03`**，
//       M1 后端不消费该位（`vr1_core` 未接）—— TODO(G1-F v7)（RAS/预测器面）；
//     - **`bad_va`**：无 PMA/PMP/翻译判决面（清单 §1.2 第 1 条、§2.6）⇒ 恒 0；
//     - **冲刷消费与重定向接线**（谁读 `br_resolve_o`、如何清 FTQ／重定向 BP）：归冲刷控制与前端
//       入口 —— TODO(M1-S3)；本模块只产 `br_resolve_t`；
//     - **`eu_id` 不消费**：`spec/01` §3.11 只有 `eu_id` 的位宽与值域（0..8），**无 单元号→EU 的
//       分配表**（冻结面无定义）⇒ 本版按 `isop` 选分支 lane、`eu_id` 不消费，不自造映射
//       —— TODO(G1-F)。
//
// 依据（逐条可核）：
//   · doc/spec/01 §3.11 `disp_x_t`（`isop`/`rs1_val`/`rs2_val`/`imm`/`pc`/`rob_id`/
//     `pred_taken`/`pred_target`/`bp_upd_id`/`ckpt_id`/`ftq_id`/`rs1_arch`/`rd_arch`）；
//     §3.12 `br_resolve_t`（逐成员语义，含 `mispred` 与 `taken_real`/`target_real` 定义）；
//     §1.1 `E` 行（解析级）、§5.1「分支误预测 | `BRU`(`E`)」、§5.2 `BP1..BP3` 行（重定向到
//     `target_real`）；
//   · doc/spec/02 §9.1.3（`BEQ`=0x080／`JAL`=0x0A0；`JAL` 无条件跳转、`BEQ` 相等即跳）、
//     §10.2（控制转移 8 条：首版只做 `BEQ`/`JAL` 两条在执行面）；
//   · doc/spec/10 §? —— 不涉（无异常面）；doc/decisions/G1-I-最小冻结清单.md §1.1（14 条）／
//     §1.2 第 1/6 条（无 MMU/C）／§2.6（首版恒 0／不消费成员表）；
//   · doc/design/M1-实现计划.md §2.1 第 11 行（M10 首版职责：`BEQ`/`JAL` 解析 ＋ `br_resolve_t`
//     冲刷请求；首版静态预测 ⇒ taken 必误预测，正好覆盖冲刷面）、§2.3 简化 #1（单发射）、
//     §2.3 简化 #2（顺序/静态预测）。
//
// 首版口径登记（**不新造语义，逐条给依据**）：
//   · `taken_real=0` 时 `target_real` 的取值：`spec/01` §3.12 只写"实际目标（间接分支用
//     `rs1_val+imm` 再判规范地址）"，**未定义条件分支不跳时的取值** ⇒ 本版取"该指令的静态目标
//     ＝`pc+偏移`"（与 `taken_real=1` 同式，避免引入第二语义），其消费方（冲刷/重定向）只在
//     `mispred && taken_real` 时读该域；该口径缺归 G1-F —— TODO(G1-F)；
//   · `rs1_val`/`rs2_val` 按 §3.11 由 `W`（发射选择）拍自 PRF 读出（后读）⇒ 本版直接消费、不回读；
//   · 比较口径：`BEQ` 的判据是"两操作数相等"，按 64 bit **逐位相等**判（与符号性无关）。
//
// 写授权：`state/freeze.json` 的 rtl_write_authorized=true（R0 2026-09-25 签署 G1-I 的人令）。
// ==========================================================================
`ifndef VR1_BRU_SV
`define VR1_BRU_SV

module vr1_bru
  import vr1_pkg::*;
(
  input  logic                  clk,        // 本版纯组合解析（无内部状态）；clk/rst_n 为后续 SVA/流水留位
  input  logic                  rst_n,

  // ---- 上游：IQ → 执行单元分发（`spec/01` §3.11 `disp_x_t`，`ISSUE_WIDTH`(=6) 条/拍）----
  input  var vr1_pkg::disp_x_t  disp_i [ISSUE_WIDTH],

  // ---- 下游：分支解析结果 → 冲刷控制（`spec/01` §3.12 `br_resolve_t`，1 条/拍）----
  output vr1_pkg::br_resolve_t  br_resolve_o
);

  // 注：`import vr1_pkg::*;` 写在 module 头部——端口表的 `[ISSUE_WIDTH]` 维度与 `disp_x_t`/
  //     `br_resolve_t` 需要包内符号在**端口作用域**可见（同 `vr1_ifetch`/`vr1_decode`）。

  // -------------------------------------------------------------------------
  // 常量（`isop` 成员编码逐行取自 `spec/02` §9.1.3；本模块**只引用**，不另赋、不重排）
  // -------------------------------------------------------------------------
  localparam logic [9:0] ISOP_BEQ  = 10'h080;      // §9.1.3 条件分支
  localparam logic [9:0] ISOP_BNE  = 10'h081;      // §9.1.3 条件分支（M2 增补）
  localparam logic [9:0] ISOP_BLT  = 10'h082;      // §9.1.3 条件分支（M3-(d) 增补）
  localparam logic [9:0] ISOP_BGE  = 10'h083;      // §9.1.3 条件分支（M3-(d) 增补）
  localparam logic [9:0] ISOP_BLTU = 10'h084;      // §9.1.3 条件分支（M3-(d) 增补）
  localparam logic [9:0] ISOP_BGEU = 10'h085;      // §9.1.3 条件分支（M3-(d) 增补）
  localparam logic [9:0] ISOP_JALR = 10'h090;      // §9.1.3 间接跳转（M3-(d) 增补）
  localparam logic [9:0] ISOP_JAL  = 10'h0A0;      // §9.1.3 无条件跳转

  // -------------------------------------------------------------------------
  // lane 选择：**最老的**分支 lane（lane 号小 = 程序序更老；§3.11 的 6 lane 同组）
  //   首版单发射（计划 §2.3 简化 #1）⇒ 每拍至多解析 1 条；多分支 lane 的其余条在后续拍解析
  //   （发射序由 IQ 保证）。`eu_id` 不消费（无分配表 ⇒ 不自造映射，见文件头 TODO(G1-F)）。
  //   M3-(d)：条件分支 6 条 ＋ JAL ＋ JALR 全入面（§9.1.3 的 10 成员中除 `LUI`/`AUIPC` 的 8 条）。
  // -------------------------------------------------------------------------
  function automatic logic lane_is_br(input vr1_pkg::disp_x_t d);
    unique case (d.isop)
      ISOP_BEQ, ISOP_BNE, ISOP_BLT, ISOP_BGE, ISOP_BLTU, ISOP_BGEU,
      ISOP_JAL, ISOP_JALR: lane_is_br = d.valid;
      default:             lane_is_br = 1'b0;
    endcase
  endfunction

  logic        found;
  int unsigned sel;

  always_comb begin
    found = 1'b0;
    sel   = 0;
    for (int unsigned k = 0; k < ISSUE_WIDTH; k++) begin
      if (!found && lane_is_br(disp_i[k])) begin
        found = 1'b1;
        sel   = k;
      end
    end
  end

  // -------------------------------------------------------------------------
  // 解析（组合）：方向 / 目标 / 误预测（`spec/01` §3.12 逐字）
  // -------------------------------------------------------------------------
  vr1_pkg::disp_x_t     u;
  logic signed [63:0]   off64;                 // `imm` 已按 ISA 语义符号扩展（§3.4）⇒ 再展到 64 bit
  logic [39:0]          tgt;                   // 目标：条件分支/JAL＝pc＋偏移；JALR＝(rs1＋偏移)&~1
  logic                 tk;                    // 实际方向 `taken_real`
  logic                 mp;                    // `mispred`
  logic                 jalr_ret;              // `is_jalr_ret`（T-7 谓词）

  always_comb begin
    u     = disp_i[sel];
    off64 = {{20{u.imm[43]}}, u.imm};          // imm：44 bit 有符号 ⇒ 符号扩展到 64 bit
    // ---- 目标式（`spec/02` §10.2 逐行；40 bit 域内回绕）----
    //   · 条件分支 6 条 / JAL：`pc + 偏移`（B/J 型偏移，§9.1.3）；
    //   · JALR：**目标＝（rs1＋I 型偏移）最低位清零**（§10.2 JALR 行逐字）——先按 40 bit 域
    //     回绕求和，再清 bit0；`rs1_val` 由 `W` 拍后读（§3.11），本拍直接消费。
    tgt   = (u.isop == ISOP_JALR) ? ((u.rs1_val[39:0] + off64[39:0]) & ~40'd1)
                                  : (u.pc + off64[39:0]);
    // ---- 方向（`spec/02` §9.1.3／§10.2；rs1_val/rs2_val 由 W 拍后读）----
    //   JAL/JALR 无条件跳；BEQ/BNE 逐位等/不等；BLT/BGE 按**有符号**；BLTU/BGEU 按**无符号**。
    //   比较一律在 64 bit 上进行（符号性由比较算子决定，不先窄化）。
    unique case (u.isop)
      ISOP_JAL, ISOP_JALR: tk = 1'b1;
      ISOP_BEQ:            tk = (u.rs1_val == u.rs2_val);
      ISOP_BNE:            tk = (u.rs1_val != u.rs2_val);
      ISOP_BLT:            tk = ($signed(u.rs1_val) <  $signed(u.rs2_val));
      ISOP_BGE:            tk = ($signed(u.rs1_val) >= $signed(u.rs2_val));
      ISOP_BLTU:           tk = (u.rs1_val <  u.rs2_val);
      ISOP_BGEU:           tk = (u.rs1_val >= u.rs2_val);
      default:             tk = 1'b0;          // 非分支 lane（`found=0` 时本包整包为 0，见下）
    endcase
    // 误预测：方向不符，或 taken 但目标不符（§3.12 定义式，逐字）
    //   首版预测器恒"预测不跳转"（`vr1_bp`）⇒ 一切 taken 分支必 `mispred=1`（含 JAL/JALR）。
    mp    = (tk != u.pred_taken) || (tk && (tgt != u.pred_target));
    // ---- `is_jalr_ret`（`spec/02` §16.4-(2) T-7 定案谓词，M3-(d) 起可构造）----
    //   `= (isop=JALR) ∧ (rs1_arch ∈ {x1,x5}) ∧ (rd_arch ≠ rs1_arch)`；其余情形恒 0。
    //   注：本位只承载**弹栈面**（RAS 预测用）；push 面由 rd 字段直接判（`spec/03`，不越篇）。
    jalr_ret = (u.isop == ISOP_JALR)
               && ((u.rs1_arch == 5'd1) || (u.rs1_arch == 5'd5))
               && (u.rd_arch != u.rs1_arch);
  end

  always_comb begin
    br_resolve_o = '0;
    // 无分支 lane ⇒ 本条**整包为 0**（`valid=0`；不携带任何未选 lane 的载荷——防"读无效包"误读，
    //   与清单 §2.6「不消费面保持合法 0 值」同口径）
    if (found) begin
      br_resolve_o.valid       = 1'b1;
      br_resolve_o.rob_id      = u.rob_id;      // 以下随流字段逐项直通所选 lane（§3.12）
      br_resolve_o.pc          = u.pc;
      br_resolve_o.taken_real  = tk;
      br_resolve_o.target_real = tgt;           // taken_real=0 时亦取"静态目标"（首版口径登记，见文件头）
      br_resolve_o.mispred     = mp;
      br_resolve_o.bad_va      = 1'b0;          // 无翻译/PMA 判决面（清单 §1.2 第 1 条／§2.6）
      br_resolve_o.is_jalr_ret = jalr_ret;      // §16.4-(2) T-7 定案谓词（M3-(d) 起可构造）
      br_resolve_o.pred_taken  = u.pred_taken;  // 反馈给 `spec/03` 的 IUM 更新模仿器（首版无表结构）
      br_resolve_o.pred_target = u.pred_target;
      br_resolve_o.bp_upd_id   = u.bp_upd_id;
      br_resolve_o.ckpt_id     = u.ckpt_id;
      br_resolve_o.ftq_id      = u.ftq_id;      // 冲刷键：清 `ftq_id` 之后的 FTQ 项（§5.2 `F0..F2` 行）
    end
  end

  // -------------------------------------------------------------------------
  // 状态与不变量（本版如实列出，防误读；断言化归 SVA 批 `spec/11` §7，本批不含）：
  //   ① **1 条/拍**：`br_resolve_o.valid=1` 时其载荷必来自某一个分支 lane（`isop∈{BEQ,JAL}`）；
  //   ② 未选中分支 lane **不产冲刷**（本版不排空：`valid=0` 即"本拍无解析结果"）；
  //   ③ 目标式 `target_real = pc + sext(imm)` 与 ISA 语义同式（`spec/02` §9.1.3/§10.2）；
  //   ④ 本模块**无历史状态**（不设 `busy`/`pending`）——`DIV` 类的"不可中途取消"（§5.2 `E1..E5` 行）
  //      不涉本模块（BRU 解析为单拍组合）。
  // -------------------------------------------------------------------------
  // synopsys translate_off
  initial $display("[vr1_bru] M10 BRU: 6 conditional branches + JAL + JALR resolve + br_resolve_t (mispred per spec/01 3.12, is_jalr_ret per T-7) landed at M1-S3 + M2(+BNE) + M3-(d); wb_t writeback and flush wiring NOT implemented (TODO(M1-S3))");
  // synopsys translate_on

endmodule

`endif // VR1_BRU_SV
