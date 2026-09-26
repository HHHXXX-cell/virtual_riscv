// ==========================================================================
// rtl/vr1/ctrl/vr1_rob.sv — M15 ROB 提交级（首版：单条在飞 ＋ `commit_t`/`rt_t` 装配）
//
// 状态（不得误读，红线 R8）：
//   · 本模块**已实现**（M1-S3 第二批）：
//     ① **`rob_entry_t`**（`spec/01` §3.7 全字段）——`S` 拍分配、`WB` 拍置 `finish` 与结果面、
//        `CT` 拍出队；② **`commit_t`**（§3.17 全字段）与 **`rt_t`**（§3.21 全字段）的**装配**
//        （`spec/01` §7 A10：`rt_t` 由 `CT` 授权拍产生，**唯一来源**）；
//     ③ 按序提交判据：`commit_vld_o = 条目有效 ∧ finish`（`finish` 可在同拍由 `WB` 置入）。
//   · **首版结构简化**（计划 §2.3 简化 #1／#4，接口之内）：**ROB 深度实现为"1 条在飞"**
//     ——`DECODE_WIDTH=4`/`COMMIT_WIDTH=4` 的多 lane 接口**保留**，`commit_t` 给出**单 lane**
//     （sink 只读 lane 0 语义）；`ROB_ENTRIES=128` 的容量面（占用计数、`rob_near_full` 反压、
//     4 条/拍提交）随多发射批 —— TODO(M1-S3)。`free_o=1` 即"条目空"。
//   · **两处口径缺登记**（**不新造语义**，逐条给出口）：
//     - `excp_t.tval` 的**级间载体**在冻结面无定义（`spec/01` §3.18 尾注：来源归 `spec/10`，
//       T-10-4 未闭）⇒ 本版用**内部寄存器** `tval_q`（非新 struct、非接口类型）承载：
//       `S` 期 `pre_exc` 条目取 `raw32`（非法指令回填指令位，`spec/10` §4.1 `mtval` 行）、
//       `WB` 期由完成回报给出（非对齐 VA）—— TODO(G1-F)（T-10-4 收口后随 `spec/01` 升版换载体）；
//     - `mem_*` 观测面（§3.21②「提交拍读 SQ/LQ」）与 `csr_old/csr_new`（§3.21③「`csrq` 队头」）
//       的**首版载体**：无 LQ/SQ、无 `csrq`（计划 §2.3 简化 #1/#3）⇒ 由 `E` 拍随完成回报携带、
//       本模块锁存到提交拍（与 §3.21②③ 的"提交拍读"在**时序**上等价：单条在飞、无更老投机）——
//       TODO(M1-S3)（队列落地后改真读口）。
//   · 本模块**未实现**：多 lane 提交/`COMMIT_WIDTH` 展开、`rob_near_full` 反压、checkpoint 槽与
//     回滚面（`needs_ckpt` 照冻面携带、恒 0）、`wfi_vld`、异常**注入**路径（中断，一期无源）——
//     逐条 TODO(M1-S3)/TODO(G1-F)。
//
// 依据（逐条可核）：
//   · doc/spec/01 §3.6 `rob_alloc_t`（分配面）／§3.7 `rob_entry_t`（§3.7 全字段）／
//     §3.17 `commit_t`／§3.21 `rt_t`（含 N9 数据来源①~④）／§7 A10（`rt_t` 唯一来源）；
//   · doc/spec/02 §3.1（`type[6:0]` 位序）／§3.2（`dst_kind`）；doc/spec/10 §4.1（`mtval` 回填）；
//   · doc/decisions/G1-I-最小冻结清单.md §2.1 第 16 行（M15 职责：128 项、不存结果、按序提交；
//     `rt_t` 唯一来源）／§2.6（恒 0 表）；doc/design/M1-实现计划.md §2.3 简化 #1/#4、§4.1。
//
// 写授权：`state/freeze.json` 的 rtl_write_authorized=true（R0 2026-09-25 签署 G1-I 的人令）。
// ==========================================================================
`ifndef VR1_ROB_SV
`define VR1_ROB_SV

module vr1_rob
  import vr1_pkg::*;
(
  input  logic         clk,
  input  logic         rst_n,

  // ---- `S` 拍：分配（§3.6 `rob_alloc_t`）----
  input  logic         alloc_vld_i,
  input  var vr1_pkg::rob_alloc_t alloc_i,
  // `uop_t` 面在 `rob_alloc_t` 里没有的成员，随分配面直通（`spec/01` §3.6 缺口，见文件头）
  input  logic [11:0]  alloc_csr_addr_i,     // `uop_t.csr_addr`（§3.4 → §3.19 `csr_wr.addr`）
  input  logic [1:0]   alloc_csr_op_i,       // `uop_t.csr_wr_type`（§3.19 `op` 同编码）
  output logic         free_o,               // 可分配（首版：条目空）

  // ---- `WB` 拍：完成回报（§3.20 合并面 ＋ 内部载体）----
  input  logic         wb_vld_i,
  input  logic [63:0]  wb_rd_data_i,         // 结果（ALU/load 数据；CSR 类＝`csr_old`）
  input  logic         wb_exc_v_i,           // `E` 拍 fault（LSU；无 MMU/cache ⇒ 只有非对齐码 4/6）
  input  logic [3:0]   wb_exc_code_i,
  input  logic [39:0]  wb_tval_i,            // 触发 VA（载体口径见文件头）
  input  logic         wb_mem_v_i,
  input  logic [39:0]  wb_mem_addr_i,
  input  logic [63:0]  wb_mem_wdata_i,
  input  logic [63:0]  wb_mem_rdata_i,
  input  logic [1:0]   wb_mem_size_i,
  input  logic         wb_mem_wr_i,
  input  logic         wb_csr_v_i,           // 该 μop 是 CSR 类（`type[6]`）
  input  logic [63:0]  wb_csr_src_i,         // CSR 写数据（`csr_wr_t.wdata` ＝ rs1_val 面）
  input  logic [63:0]  wb_csr_old_i,         // `csrq` 队头 `old_val`（§3.21③；本版由 `E` 拍携带）
  input  logic         wb_is_br_i,
  input  logic         wb_mispred_i,

  // ---- `CT` 拍：提交（§3.17）----
  output logic         commit_vld_o,
  output vr1_pkg::commit_t commit_o,
  input  var vr1_pkg::excp_t excp_i,         // 由 `vr1_trap` 提交拍组装（§3.18 署名）
  input  var vr1_pkg::ret_ctrl_t ret_i,      // 由 `vr1_csr` 提交拍组合输出（§3.18）
  output vr1_pkg::rt_t rt_o,                 // §3.21（`CT` 授权拍）
  input  logic         commit_ack_i,         // 提交被接受（本拍清条目）
  input  logic [63:0]  cycle_i,              // `rt_t.cycle`（仅性能统计/调试，不参与比对）
  input  logic [63:0]  csr_new_i,            // `vr1_csr` 写后新值（`rt_t.csr_new`）
  input  logic         csr_wr_en_i,          // `vr1_csr` 实际写使能（`rt_t.csr_wr_en`）

  // ---- 提交拍现场（供 `vr1_trap` 组装 `excp_t`／`vr1_csr` 执行进场动作；§3.18 来源①）----
  output logic [3:0]   head_exc_code_o,
  output logic         head_is_intr_o,
  output logic [39:0]  head_pc_o,
  output logic [31:0]  head_raw32_o,
  output logic [1:0]   head_priv_o,
  output logic [39:0]  head_tval_o,
  output logic [63:0]  head_data_o           // 有效结果（`rt_t.rd_data` 同源；GPR 写口用）
);

  // -------------------------------------------------------------------------
  // 条目与内部载体（首版 1 条在飞 ⇒ 单组寄存器）
  // -------------------------------------------------------------------------
  rob_entry_t  entry_q;
  logic [63:0] data_q;          // 结果（§3.21①：提交拍读 PRF 的等价物——本版由 `WB` 携带）
  logic [39:0] tval_q;          // 见文件头口径缺登记
  logic [11:0] csr_addr_q;
  logic [1:0]  csr_op_q;
  logic [63:0] csr_src_q;
  logic [63:0] csr_old_q;
  logic        mem_v_q, mem_wr_q;
  logic [39:0] mem_addr_q;
  logic [63:0] mem_wdata_q, mem_rdata_q;
  logic [1:0]  mem_size_q;
  logic        is_br_q, mispred_q;
  logic        type_is_csr_q;   // `type[6]`（`is_csr`）直存（entry 的 `type_f[6]` 同源）

  assign free_o = !entry_q.v;

  // 完成条件：`finish` 已在条目上，或**本拍**由 `WB` 置入（同拍完成同拍提交，省一拍）
  logic        eff;                              // 本拍完成入端口有效（`WB` 与提交同拍）
  logic        finish_eff;
  logic [63:0] data_eff;
  assign eff        = wb_vld_i;
  assign finish_eff = entry_q.finish | wb_vld_i;
  assign data_eff   = wb_vld_i ? wb_rd_data_i : data_q;

  assign commit_vld_o = entry_q.v && finish_eff;

  // -------------------------------------------------------------------------
  // 提交拍：异常/返回面（`exc_v`/`exc_code` 同拍可见；`WB` 抑制写口径见下）
  // -------------------------------------------------------------------------
  logic        exc_v_eff;
  logic [3:0]  exc_code_eff;
  logic [39:0] tval_eff;
  assign exc_v_eff    = entry_q.exc_v | (wb_vld_i & wb_exc_v_i);
  assign exc_code_eff = entry_q.exc_v ? entry_q.exc_code : wb_exc_code_i;
  assign tval_eff     = (wb_vld_i && wb_exc_v_i && !entry_q.exc_v) ? wb_tval_i : tval_q;

  // 提交拍现场输出（`vr1_trap`/GPR 写口消费；同拍完成 ⇒ 取入端口值，防"读到上一拍值"）
  assign head_exc_code_o = exc_code_eff;
  assign head_is_intr_o  = entry_q.is_intr;
  assign head_pc_o       = entry_q.pc;
  assign head_raw32_o    = entry_q.raw32;
  assign head_priv_o     = entry_q.priv;
  assign head_tval_o     = tval_eff;
  assign head_data_o     = data_eff;

  // 结果面写使能：`dst_kind≠00` ∧ 非异常条目（`spec/02` §19：异常条目抑制写；与 ISS `_rd` 未调用同效）
  logic rd_wb_en;
  assign rd_wb_en = commit_vld_o && (entry_q.dst_kind != 2'b00) && !exc_v_eff;

  // -------------------------------------------------------------------------
  // `commit_t`（§3.17 逐成员；单 lane）
  // -------------------------------------------------------------------------
  csr_wr_t cwr;                                  // `commit_o.csr_wr`（81 bit 打包域）的组装载体
  always_comb begin
    commit_o               = '0;
    cwr                    = '0;
    commit_o.valid         = commit_vld_o;
    commit_o.rd_en         = rd_wb_en;
    commit_o.rd_paddr      = entry_q.rd_paddr;
    commit_o.rd_old_paddr  = entry_q.rd_old_paddr;
    commit_o.lq_dealloc    = 1'b0;                       // 无 LQ/SQ（计划 §2.3 简化 #3）—— TODO(M1-S3)
    commit_o.lq_id         = 6'd0;
    commit_o.sq_dealloc    = 1'b0;
    commit_o.sq_id         = 5'd0;
    // `csr_vld`：本条为 CSR 写 ∧ 非异常条目（§3.17 ＋ §3.19 规则 5「异常提交的 CSR 写抑制」）
    //   注：`commit_t.csr_wr` 是 **81 bit 打包位域**（§3.17 表）⇒ 先组 `csr_wr_t`（同 81 bit）
    //   再整包赋给该域（SV 打包结构↔打包向量同宽可直接赋值；禁在核内裸切片）
    commit_o.csr_vld   = commit_vld_o && type_is_csr_q && !exc_v_eff;
    cwr                = '0;
    cwr.vld            = commit_o.csr_vld;
    cwr.addr           = csr_addr_q;
    cwr.op             = csr_op_q;
    // `wdata_sel`：编码归 `spec/10`（`spec/02` §3.5 T-3 **未闭**）⇒ 本版恒 0、**不据其做判决**
    //   （`wdata` 已按「寄存器型取 `rs1_val`」装订，§3.19 规则 2）—— TODO(G1-F)
    cwr.wdata_sel      = 2'b00;
    // `wdata` 同取**当拍有效值**：`WB`（＝本拍完成）携带的 `rs1_val` 尚未落进 `csr_src_q`
    //   （非阻塞赋值到本拍末才生效）⇒ 只读寄存器会把 0 写进 CSR（实测：mtvec 被写成 0，
    //   trap 重定向到 pc=0）。与 `rt_o` 的 `eff` 同源。
    cwr.wdata          = eff ? wb_csr_src_i : csr_src_q;
    commit_o.csr_wr    = cwr;
    // `exc_vld` 必须与提交同拍：仅靠 `exc_v_eff` 会让"已标异常但尚未 `finish`"的条目
    //   （`exc_v=1` ∧ `finish=0`）持续拉高 `excp_commit` ⇒ `flush_all` 恒 1、机器冻结
    //   （实测：trap 后停摆）。`spec/01` §5.1：异常**在提交边界**才生效。
    commit_o.exc_vld       = commit_vld_o && exc_v_eff;
    commit_o.exc_pkt       = excp_i;                     // `vr1_trap` 组装（§3.18）
    commit_o.ret_vld       = ret_i.vld;
    commit_o.ret_pkt       = ret_i;
    commit_o.wfi_vld       = 1'b0;                       // 无 WFI（不在 G1-I 14 条内）—— TODO(G1-F)
    commit_o.seq           = entry_q.seq;
    commit_o.ftq_id        = entry_q.ftq_id;
  end

  // -------------------------------------------------------------------------
  // `rt_t`（§3.21 逐成员；`spec/01` §7 A10：CT 授权拍唯一来源）
  // -------------------------------------------------------------------------
  always_comb begin
    rt_o             = '0;
    rt_o.valid       = commit_vld_o;
    rt_o.pc          = entry_q.pc;
    rt_o.instr       = entry_q.raw32;
    rt_o.is_c        = 1'b0;                             // 无 C 展开（清单 §1.2 第 6 条）
    rt_o.rd_idx      = entry_q.rd_arch;
    rt_o.rd_wb_en    = rd_wb_en;
    rt_o.rd_data     = data_eff;
    rt_o.priv        = entry_q.priv;
    rt_o.csr_addr    = csr_addr_q;
    // 注：`WB` 面成员一律取**当拍有效值**（`eff ? 入端口 : 寄存器`）——`finish` 与提交同拍
    //   （见 `commit_vld_o` 定义）⇒ 只读寄存器会拿到"上一拍的值"（实测：store 的 `mem_*`
    //   会错位到下一行 trace）。本块与上面的 `*_eff` 同源。
    rt_o.csr_old     = eff ? wb_csr_old_i : csr_old_q;
    rt_o.csr_new     = csr_new_i;                        // 写后新值（ISS-013 口径，§3.21）
    rt_o.csr_wr_en   = commit_o.csr_vld && csr_wr_en_i;   // 实际写使能（RS 源为 0 ⇒ 0，§3.19）
    rt_o.exc_v       = exc_v_eff;
    rt_o.exc_cause   = exc_code_eff;
    rt_o.is_intr     = entry_q.is_intr;
    rt_o.mispred     = eff ? wb_mispred_i : mispred_q;    // 仅调试用，不参与比对（§3.21）
    rt_o.is_br       = eff ? wb_is_br_i : is_br_q;
    rt_o.mem_v       = eff ? wb_mem_v_i : mem_v_q;
    rt_o.mem_addr    = eff ? wb_mem_addr_i : mem_addr_q;
    rt_o.mem_wdata   = eff ? wb_mem_wdata_i : mem_wdata_q;
    rt_o.mem_rdata   = eff ? wb_mem_rdata_i : mem_rdata_q;  // §3.21①：与 `rd_data` 同值
    rt_o.mem_size    = eff ? wb_mem_size_i : mem_size_q;
    rt_o.mem_wr      = eff ? wb_mem_wr_i : mem_wr_q;
    rt_o.seq         = entry_q.seq;                      // 不参与比对（调试排序）
    rt_o.cycle       = cycle_i[63:0];                    // 不参与比对（性能统计）
  end

  // -------------------------------------------------------------------------
  // 顺序：分配（S）／完成（WB）／出队（CT）
  // -------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      entry_q       <= '0;
      data_q        <= 64'd0;
      tval_q        <= 40'd0;
      csr_addr_q    <= 12'd0;
      csr_op_q      <= 2'd0;
      csr_src_q     <= 64'd0;
      csr_old_q     <= 64'd0;
      mem_v_q       <= 1'b0;
      mem_wr_q      <= 1'b0;
      mem_addr_q    <= 40'd0;
      mem_wdata_q   <= 64'd0;
      mem_rdata_q   <= 64'd0;
      mem_size_q    <= 2'd0;
      is_br_q       <= 1'b0;
      mispred_q     <= 1'b0;
      type_is_csr_q <= 1'b0;
    end else begin
      // ---- 分配（`S` 拍；`free_o=1` 时才可能发生）----
      if (alloc_vld_i && free_o) begin
        entry_q.v             <= 1'b1;
        entry_q.pc            <= alloc_i.pc;
        entry_q.raw32         <= alloc_i.raw32;
        entry_q.priv          <= alloc_i.priv;
        entry_q.type_f        <= alloc_i.type_f;
        entry_q.finish        <= 1'b0;                   // 完成由 `WB` 置（同拍亦可提交）
        // `S` 期预检异常（`pre_exc`＝{v, code}，§3.6）：非法指令在 `S`/`D` 期即标 `exc_v`
        //   （§5.1 触发源：译码期非法指令在 `S` 级检测）
        entry_q.exc_v         <= alloc_i.pre_exc[4];
        entry_q.exc_code      <= alloc_i.pre_exc[3:0];
        entry_q.is_intr       <= 1'b0;                   // 一期无中断源（清单 §1.2）
        entry_q.dst_kind      <= alloc_i.dst_kind;
        entry_q.rd_arch       <= alloc_i.rd_arch;
        entry_q.rd_paddr      <= alloc_i.rd_paddr;
        entry_q.rd_old_paddr  <= alloc_i.rd_old_paddr;
        entry_q.ckpt_id       <= alloc_i.ckpt_id;
        entry_q.lq_v          <= 1'b0;                   // 无 LQ/SQ（计划 §2.3 简化 #3）
        entry_q.lq_id         <= 6'd0;
        entry_q.sq_v          <= 1'b0;
        entry_q.sq_id         <= 5'd0;
        entry_q.mem_done      <= 1'b0;
        entry_q.fdirty        <= 1'b0;                   // 一期无 FP（`spec/00` §7 第 3 条）
        entry_q.needs_ckpt    <= alloc_i.needs_ckpt;
        entry_q.ftq_id        <= alloc_i.ftq_id;
        entry_q.seq           <= alloc_i.seq;
        // 预检异常条目的 `tval`：非法指令回填**指令位**（`spec/10` §4.1 `mtval` 行）
        tval_q                <= {8'b0, alloc_i.raw32};
        type_is_csr_q         <= alloc_i.type_f[6];
        csr_addr_q            <= alloc_csr_addr_i;
        csr_op_q              <= alloc_csr_op_i;
        // 注：CSR 写数据（`csr_wr_t.wdata` ＝ `rs1_val`）在**发射（`W`）拍**才读出
        //     （后读，`spec/01` §1.1 A9）⇒ 由 `WB` 拍经 `wb_csr_src_i` 携带并在下面写口锁存；
        //     分配拍与 `WB` 拍在本设计**互斥**（单条在飞）⇒ 本分支不写 `csr_src_q`。
        mem_v_q               <= 1'b0;
        mem_wr_q              <= 1'b0;
        mem_size_q            <= 2'd0;
        is_br_q               <= alloc_i.type_f[1];
        mispred_q             <= 1'b0;
      end

      // ---- 完成（`WB` 拍）----
      if (wb_vld_i) begin
        entry_q.finish <= 1'b1;
        data_q         <= wb_rd_data_i;
        if (wb_exc_v_i && !entry_q.exc_v) begin
          // 异常优先级写死：`S`/`D` 期预检（更早检测）**不被** `E` 期 fault 覆盖
          //   （`spec/01` §5.1「同拍多异常按 `spec/02` 固定优先序，不允许或起来当一个」的实现面）
          entry_q.exc_v    <= 1'b1;
          entry_q.exc_code <= wb_exc_code_i;
          tval_q           <= wb_tval_i;
        end
        mem_v_q     <= wb_mem_v_i;
        mem_wr_q    <= wb_mem_wr_i;
        mem_addr_q  <= wb_mem_addr_i;
        mem_wdata_q <= wb_mem_wdata_i;
        mem_rdata_q <= wb_mem_rdata_i;
        mem_size_q  <= wb_mem_size_i;
        csr_src_q   <= wb_csr_src_i;
        csr_old_q   <= wb_csr_old_i;
        type_is_csr_q <= wb_csr_v_i;
        is_br_q     <= wb_is_br_i;
        mispred_q   <= wb_mispred_i;
      end

      // ---- 出队（`CT` 拍；提交被接受）----
      if (commit_vld_o && commit_ack_i) begin
        entry_q.v      <= 1'b0;
        entry_q.finish <= 1'b0;
        mem_v_q        <= 1'b0;
        mispred_q      <= 1'b0;
        is_br_q        <= 1'b0;
      end
    end
  end

  // -------------------------------------------------------------------------
  // 状态与不变量（本版如实列出；断言化归 SVA 批 `spec/11` §7，本批不含）：
  //   ① 在飞条目恒 ≤1（`free_o=0` ⇒ 不再分配）；② 提交序＝分配序（单条在飞 ⇒ 恒等）；
  //   ③ `exc_v` 一旦置位不再清（除出队）；④ `rd_wb_en=0` 当 `exc_v=1`（§19 抑制写）。
  // -------------------------------------------------------------------------
  // synopsys translate_off
  initial $display("[vr1_rob] M15 ROB: single-in-flight commit stage + commit_t + rt_t (spec/01 3.17/3.21) landed at M1-S3b; multi-lane/128-entry/rob_near_full TODO(M1-S3); tval/mem_* carriers TODO(G1-F)");
  // synopsys translate_on

endmodule

`endif // VR1_ROB_SV
