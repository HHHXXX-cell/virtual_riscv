//=============================================================================
// vr1_if.sv — VR1 DUT ↔ TB 接口骨架（D-7 平台骨架片·占位）
// 依据：doc/spec/01 §3「级间接口（struct 位域）」——接口族对应关系：
//   §3.13 `mem_req_t`（LSU/IF → L1D/L1I）／§3.14 MMU 翻译接口（req/rsp）／
//   §3.15 缺失处理接口（miss/fill/wake）／§3.16 cache 响应接口／
//   §3.17 `commit_t`（ROB → CSR/freelist/SQ）／§3.18 异常包与返回控制／
//   §3.19 `csr_wr_t`（CSR 写端口 81 bit）／§3.21 `rt_t`（退休 trace，P17 输出，
//   验证平台唯一真值接口）；中断/异常注入口径见 §5.1（epc=头 pc／注入）。
// 状态：**仅声明、不驱动**——RTL 未存在、接口未冻结（Review G1 前）。
//   信号名与位宽均为域级占位（[回填]）；位宽/字段/握手语义一律
//   以 spec/01 §3.x 对应 struct 的位域表为唯一权威源，**本文件不自造任何位宽**。
// 本片不写 modport / clocking block / 驱动逻辑；例化见 vr1_top_tb.sv。
//=============================================================================
`ifndef VR1_IF_SV
`define VR1_IF_SV

interface vr1_if (
  input logic clk,
  input logic rst_n
);

  // ---- 族 0：时钟/复位 ----
  // 无 §3 条目；复位语义/多域口径待 spec/01 §5.2 冻结后回填。
  // clk/rst_n 由顶层 tb 驱动；本接口不产生任何驱动。

  // ---- 族 1：取指存储侧 请求/响应（§3.13 IF→L1I 形态 / §3.16 响应）----
  logic        imem_req_valid;   // [回填] 位宽/字段: spec/01 §3.13（addr/mmu_transl_*/vld/err 等）
  logic        imem_req_ready;   // [回填] spec/01 §3.13 或 §3.16 响应侧
  logic        imem_rsp_valid;   // [回填] spec/01 §3.16（cache 响应接口）
  logic        imem_rsp_ready;   // [回填]

  // ---- 族 2：访存侧 请求/响应（§3.13 LSU→L1D / §3.16 响应）----
  logic        dmem_req_valid;   // [回填] spec/01 §3.13
  logic        dmem_req_ready;   // [回填]
  logic        dmem_rsp_valid;   // [回填] spec/01 §3.16
  logic        dmem_rsp_ready;   // [回填]

  // ---- 族 3：MMU 翻译 请求/响应（§3.14）----
  logic        mmu_req_valid;    // [回填] spec/01 §3.14
  logic        mmu_rsp_valid;    // [回填] spec/01 §3.14

  // ---- 族 4：缺失/回填/唤醒（§3.15）----
  logic        mshr_miss_valid;  // [回填] spec/01 §3.15
  logic        mshr_wake_valid;  // [回填] spec/01 §3.15（`mshr_wake_t`）

  // ---- 族 5：提交/退休观察点（§3.17 `commit_t` / §3.21 `rt_t`）----
  logic        commit_valid;     // [回填] spec/01 §3.17
  logic        rt_valid;         // [回填] spec/01 §3.21（位宽按 §3.21 表）
  logic        rt_ready;         // [回填] spec/01 §3.21

  // ---- 族 6：异常/返回控制观察点（§3.18 `excp_t` 177 bit / `ret_ctrl_t` 49 bit）----
  // [回填] 位宽按 §3.18；本族仅由监视器采样，不作驱动。

  // ---- 族 7：CSR 写端口观察点（§3.19 `csr_wr_t` 81 bit）----
  logic        csr_wr_valid;     // [回填] spec/01 §3.19

  // ---- 族 8：中断/异常注入（§5.1 注入口径）----
  logic        irq_ext_pending;  // [回填] spec/01 §5.1（注入时点/屏蔽口径待冻结）

  // 说明：以上为域级占位信号名（非 spec 已定义名）；完整字段/位宽在接口
  // 冻结（Review G1）后按 §3.x 逐条回填；本片无任何驱动/采样行为。

endinterface

`endif
