// ==========================================================================
// rtl/vr1/frontend/vr1_bp.sv — M01 预测器子系统
//                        （**G1-I 首版：顺序/静态预测 —— 预测不跳转**）
//
// 状态（不得误读，红线 R8）：**本文件不是"预测器"**，只是取指块的**顺序发生器**。
//   · 首版无 BTB/TAGE/SC-lite/ITTAGE-lite/RAS：不判分支、不预测目标（`spec/03` 表结构面不做）；
//   · 预测器**更新路径**（`bp_upd_t`、提交反馈、校正队列出队）**不在 G1-I**
//     （清单 §1.2 第 7 条 + §5 v7）⇒ 本模块**无更新口**，`bp_upd_id` 恒 0；
//   · 因此 `br_vld=0`/`taken=0`（"预测不跳转"）⇒ `BEQ`/`JAL` 必误预测，由 BRU 解析 + 冲刷恢复兜底；
//     重定向源（BRU 冲刷 / trap / MRET）属 **M1-S3/S4**：本模块已留 `bp_pc_i` 口，
//     接线与 tie-off 见 `vr1_core.sv` 的 `TODO(M1-S3)`／`TODO(M1-S4)`（本批调用方恒 0）。
//
// 依据（逐条可核）：
//   · doc/spec/01 §3.1 `ftq_req_t` 成员位域与合法值域（本模块**唯一**产出接口）；
//   · doc/spec/01 §1.1 `P0/P1/P2` 行（BP1 取 `bp_pc`、BP2 表查、BP3 打包入 FTQ）；
//   · doc/spec/01 §3.16 `win_base_pc` 与 walk 规则（块首槽 = 块起始 `pc[4:1]`）；§1.1 `P4` 行（按 `VA[5]` 选 32 B 窗）；
//   · doc/spec/00 §4.1 `FETCH_BYTES=32`／`RESET_PC=0x1000`；§6 M01 行（上游 `bp_pc_i`、下游 `ftq_req_t`）；
//   · doc/decisions/G1-I-最小冻结清单.md §2.6（首版恒 0／不消费成员表）、§2.3（三条结构简化）。
//
// 首版结构简化（`doc/design/M1-实现计划.md` §2.3 简化 #2，接口之内、不动冻结面）：
//   · 块 = 一个 32 B 取指窗内的**全部 4 B 指令**（`nib` = 窗内余量/2，见下）；
//     "块尾是首个可预测分支"的截断规则（§3.1 Q39）需要分支信息 ⇒ 归预测器表结构版（G1-F v7）。
//
// 写授权：`state/freeze.json` 的 rtl_write_authorized=true（R0 2026-09-25 签署 G1-I 的人令）。
// ==========================================================================
`ifndef VR1_BP_SV
`define VR1_BP_SV

module vr1_bp (
  input  logic                    clk,
  input  logic                    rst_n,

  // ---- 上游：取指起点 pc（spec/00 §6 M01 行的 `bp_pc_i`；重定向源在 M1-S3 接入）----
  // 语义：本拍为一**重定向**（BRU 冲刷 / trap / MRET 后的新起点）；`bp_pc_vld_i=0` 时
  //       预测器走顺序流（32 B 窗推进）。首版调用方恒 0（无重定向源，见 vr1_core 的 TODO）。
  input  logic [39:0]             bp_pc_i,
  input  logic                    bp_pc_vld_i,

  // ---- 下游：预测块请求（spec/01 §3.1 `ftq_req_t`，写 1/拍；M02 `vr1_ftq` 消费）----
  output vr1_pkg::ftq_req_t       ftq_req_o,
  output logic                    ftq_req_valid_o,
  input  logic                    ftq_req_ready_i
);

  import vr1_pkg::*;

  // -------------------------------------------------------------------------
  // 常量（全部取自参数件/冻结面，不另赋值）
  // -------------------------------------------------------------------------
  localparam logic [39:0] RESET_PC_VA = RESET_PC[39:0];   // spec/00 §4.1：复位向量 0x1000（＝镜像 base）
  // 一窗 16 个 16 bit 候选槽（spec/01 §3.3「槽数两套」：FETCH_BYTES/2）
  localparam int unsigned SLOTS_PER_WIN = FETCH_BYTES / 2;
  // 首版每指令占 2 槽（4 B 对齐、无 C；清单 §1.2 第 6 条）⇒ 一窗至多 FETCH_BYTES/4 条
  // 说明：**不是自造参数**——是 `FETCH_BYTES` 与"4 B 对齐"两个已冻事实的算术推论，仅本模块局部使用。
  localparam int unsigned MAX_INSTR_PER_WIN = FETCH_BYTES / 4;

  // -------------------------------------------------------------------------
  // 顺序流 pc：复位 = `RESET_PC`；重定向优先；否则按 32 B 窗推进
  //   （块覆盖到本窗末 ⇒ 下一块起点 = 本窗基址 + FETCH_BYTES；`pc + 4×nib` 在 4 B 对齐下等价）
  // -------------------------------------------------------------------------
  logic [39:0] next_pc_q;

  // 块首槽 = 块起始 `pc[4:1]`（spec/01 §3.16 walk 规则；窗基址 `[4:0]=0` ⇒ 该式即窗内槽号）
  logic [4:0]  blk_first_slot;
  assign blk_first_slot = next_pc_q[4:1];

  // 块内指令数 `nib`（§3.1 值域 1..16）：窗内余量槽数 / 2
  //   S1 全 4 B 对齐 ⇒ `blk_first_slot` 为偶 ⇒ `nib ∈ 1..8`（slot=14 ⇒ 1 条，slot=0 ⇒ 8 条）。
  //   2 字节对齐块首（`nib` 可能算得 0）随 C 展开与跨窗拼接版一并处理：TODO(G1-F v5)。
  logic [4:0]  blk_nib;
  always_comb begin
    int unsigned rem_slots;
    rem_slots = SLOTS_PER_WIN - blk_first_slot;           // 1..16（blk_first_slot ≤ 15）
    blk_nib   = rem_slots >> 1;
  end

  // -------------------------------------------------------------------------
  // 首版「有块可预测」= 顺序流恒真（无 WFI/停机判据在预测器侧；停机在提交/访存侧）
  //   重定向拍（M1-S3 起）同样"有块可预测" ⇒ 有效条件 = 重定向 | 顺序流
  // -------------------------------------------------------------------------
  logic blk_avail;
  assign blk_avail = 1'b1;

  assign ftq_req_valid_o = blk_avail | bp_pc_vld_i;

  // -------------------------------------------------------------------------
  // 预测块请求载荷（spec/01 §3.1 逐成员；不消费成员保持合法 0 值——清单 §2.6）
  // -------------------------------------------------------------------------
  always_comb begin
    ftq_req_o           = '0;
    ftq_req_o.valid     = ftq_req_valid_o;
    ftq_req_o.pc        = next_pc_q;                      // 块起始 VA（2 B 对齐；S1 恒 4 B 对齐）
    ftq_req_o.nib       = blk_nib;                        // 块内指令条数（1..8）
    ftq_req_o.br_vld    = 1'b0;                           // §3.1：块尾是分支——S1 无分支信息 ⇒ 恒 0
    ftq_req_o.br_type   = 2'b00;                          // 00 条件（br_vld=0 时无效）
    ftq_req_o.taken     = 1'b0;                           // **预测不跳转**（首版静态预测）
    ftq_req_o.target    = 40'b0;                          // taken=0 ⇒ 目标无效
    ftq_req_o.ras_op    = 2'b00;                          // 00 无（无 RAS；G1-F v7）
    ftq_req_o.ras_top   = 40'b0;
    ftq_req_o.pred_conf = 2'b00;                          // 置信度 0（无 SC-lite 幅度）
    ftq_req_o.bp_upd_id = 8'h00;                          // TODO(G1-F v7)：更新路径与表结构不在 G1-I
    ftq_req_o.bad_va    = 1'b0;                           // 无翻译/PMA 判决面（清单 §1.2 第 1 条）
  end

  // -------------------------------------------------------------------------
  // pc 寄存器：复位取 RESET_PC / 重定向优先 / 顺序推进（接受拍）
  // -------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      next_pc_q <= RESET_PC_VA;                           // 清单 §1.2 第 10 条：复位后取 RESET_PC
    end else if (bp_pc_vld_i) begin
      next_pc_q <= bp_pc_i;                               // 重定向（M1-S3 接入源；S1 不可达）
    end else if (ftq_req_valid_o && ftq_req_ready_i) begin
      next_pc_q <= {next_pc_q[39:5], 5'b0} + 40'(FETCH_BYTES);   // 下一 32 B 窗（顺序流）
    end
  end

  // -------------------------------------------------------------------------
  // 本模块**未实现**面（如实列出，防"看起来像预测器"的误读）：
  //   · L1BTB/L2BTB/TAGE/SC-lite/ITTAGE-lite 查表与仲裁（`spec/03`）——无表、无分支判定；
  //   · RAS（`ras_op`/`ras_top`）与 call/return 对；
  //   · 更新路径（`bp_upd_t`、提交反馈、校正队列出队）——清单 §1.2 第 7 条；
  //   · checkpoint 分配与 `needs_ckpt`（在 R 级，M1-S3）；
  //   · 取指异常（`bad_va` 恒 0）——无 PMA/PMP/翻译面（清单 §1.2 第 1 条）。
  // -------------------------------------------------------------------------

endmodule

`endif // VR1_BP_SV
