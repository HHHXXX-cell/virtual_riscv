// ==========================================================================
// rtl/vr1/frontend/vr1_ftq.sv — M02 取指队列（FTQ，16 项）
//
// 状态（不得误读，红线 R8）：
//   · 本模块**已实现**：16 项环形队列（`FTQ_ENTRIES=16`）＋ 写口反压 ＋ 队头读出口
//     ＋ 队头序号（`ftqid_t` 口径）；写/读为**同拍可同时进行**的标准 valid/ready 语义。
//   · 首版**不做**（推迟面，逐条给出出口）：
//     - `icache_ready=0 ⇒ 队头停留`（§3.2）：首版无 cache 层次（清单 §1.2 第 2 条、§2.6
//       "`icache_ready`/`ptw_req` 恒 1／恒 0"）⇒ 恒 1、无停留分支；
//     - **冲刷/恢复**（§5.2「清 `ftq_id` 之后的 FTQ 项」）：无 BRU/trap 冲刷源 ⇒ TODO(M1-S3)；
//     - 预测器**更新路径**的 `ftq_id` 出队键（§3.17 `commit_t.ftq_id` 反馈）：TODO(G1-F v7)。
//
// 依据：
//   · doc/spec/01 §3.1 `ftq_req_t`（写口载荷）／§3.2 `ftq_entry_t`（读出口载荷 = 全字段 +2）；
//   · doc/spec/01 §3.2 尾注（N14）：「读出口的序号由 FTQ 读指针自带」⇒ 本模块另出 `ftq_pop_id_o`
//     （`spec/01` §2 的 `ftqid_t` = `logic [4:0]`：4 bit index + 1 wrap）；
//   · doc/spec/01 §1.1 `P2`/`P3` 行（BP3 写 FTQ；F0 队头出队）；`FTQ_ENTRIES=16`（`spec/00` §4.2）；
//   · doc/decisions/G1-I-最小冻结清单.md §2.1（两型在冻结面内）／§2.6（恒值表）。
//
// 写授权：`state/freeze.json` 的 rtl_write_authorized=true（R0 2026-09-25 签署 G1-I 的人令）。
// ==========================================================================
`ifndef VR1_FTQ_SV
`define VR1_FTQ_SV

module vr1_ftq (
  input  logic                    clk,
  input  logic                    rst_n,

  // ---- 写口：BP3 → FTQ（spec/01 §3.1 `ftq_req_t`，1/拍）----
  input  var vr1_pkg::ftq_req_t   ftq_req_i,
  input  logic                    ftq_req_valid_i,
  output logic                    ftq_req_ready_o,     // 0 = 满（反压 M01）

  // ---- 读口：FTQ → IF（spec/01 §3.2 `ftq_entry_t`，≤1/拍）----
  output vr1_pkg::ftq_entry_t     ftq_entry_o,
  output logic                    ftq_pop_valid_o,     // 队头有效（spec/00 §6 M02 行名 `ftq_pop_valid`）
  output logic [4:0]              ftq_pop_id_o,        // 队头序号（`ftqid_t` 口径，见文件头 N14 注）
  input  logic                    ftq_pop_ready_i,     // 队头被取走（IF 接受该块）

  // ---- 冲刷口（M1-S3：`spec/01` §5.2 F0~F2 行「清 `mispred` 所属 `ftq_id` 之后的 FTQ 项」）----
  // 置 1 一拍 ⇒ 在册项**全部作废**（写指针回到读指针、计数归零），冲刷拍不接受写入。
  input  logic                    flush_i
);

  import vr1_pkg::*;

  // -------------------------------------------------------------------------
  // 存储与指针（4 bit index + 1 wrap = 5 bit，`ftqid_t` 口径；禁止裸 < / > 比较）
  // -------------------------------------------------------------------------
  localparam int unsigned IDX_W = $clog2(FTQ_ENTRIES);          // 4
  localparam int unsigned PTR_W = IDX_W + 1;                    // 5（含 wrap）

  ftq_req_t         entry_q [FTQ_ENTRIES];
  logic [PTR_W-1:0] wr_ptr_q;
  logic [PTR_W-1:0] rd_ptr_q;
  logic [4:0]       cnt_q;                                      // 0..16（5 bit 装得下 16）

  logic             wr_en;
  logic             pop_en;

  assign ftq_req_ready_o = (cnt_q != 5'(FTQ_ENTRIES));          // 满 ⇒ 反压
  assign ftq_pop_valid_o = (cnt_q != 5'd0);
  assign ftq_pop_id_o    = rd_ptr_q;                            // 队头序号由读指针自带（N14）
  assign wr_en           = ftq_req_valid_i && ftq_req_ready_o;
  assign pop_en          = ftq_pop_valid_o && ftq_pop_ready_i;

  // -------------------------------------------------------------------------
  // 读出口形态：`ftq_entry_t` = `ftq_req_t` 全字段 + `icache_ready`/`ptw_req`
  //   （首版恒 1/恒 0 —— 清单 §2.6；逐成员赋值，不依赖结构体打包顺序假设）
  // -------------------------------------------------------------------------
  function automatic ftq_entry_t to_entry(input ftq_req_t r);
    to_entry              = '0;
    to_entry.valid        = r.valid;
    to_entry.pc           = r.pc;
    to_entry.nib          = r.nib;
    to_entry.br_vld       = r.br_vld;
    to_entry.br_type      = r.br_type;
    to_entry.taken        = r.taken;
    to_entry.target       = r.target;
    to_entry.ras_op       = r.ras_op;
    to_entry.ras_top      = r.ras_top;
    to_entry.pred_conf    = r.pred_conf;
    to_entry.bp_upd_id    = r.bp_upd_id;
    to_entry.bad_va       = r.bad_va;
    to_entry.icache_ready = 1'b1;      // 清单 §2.6：无 cache 缺失 ⇒ 恒 1（队头不停留）
    to_entry.ptw_req      = 1'b0;      // 清单 §2.6：无 MMU/PTW
    return to_entry;
  endfunction

  assign ftq_entry_o = to_entry(entry_q[rd_ptr_q[IDX_W-1:0]]);

  // -------------------------------------------------------------------------
  // 顺序（写/读同拍互不干扰；write-first 无需旁路：同拍写入的项不可能是本拍队头）
  // -------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr_q <= '0;
      rd_ptr_q <= '0;
      cnt_q    <= '0;
    end else if (flush_i) begin
      // 冲刷（M1-S3 落地）：在册项全部作废。本设计**只从队头消费**且冲刷源恒在提交拍
      //   （更老项必已出队）⇒ 「清 `ftq_id` 之后」与「清全部在册项」等价（§5.2 F0~F2 行）；
      //   冲刷拍**不接受写入**：BP 的重定向在本拍生效（`bp_pc_i`），下一拍起写入的才是新路径块。
      wr_ptr_q <= rd_ptr_q;
      cnt_q    <= '0;
    end else begin
      if (wr_en) begin
        entry_q[wr_ptr_q[IDX_W-1:0]] <= ftq_req_i;
        wr_ptr_q <= wr_ptr_q + PTR_W'(1);
      end
      if (pop_en) begin
        rd_ptr_q <= rd_ptr_q + PTR_W'(1);
      end
      unique case ({wr_en, pop_en})
        2'b10:   cnt_q <= cnt_q + 5'd1;
        2'b01:   cnt_q <= cnt_q - 5'd1;
        default: cnt_q <= cnt_q;
      endcase
    end
  end

endmodule

`endif // VR1_FTQ_SV
