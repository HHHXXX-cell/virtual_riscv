// ==========================================================================
// rtl/vr1/core/vr1_core.sv — VR1 核顶层（**端口面冻结**；前端 M01~M03 ＋ 译码 M05 ＋ **后端最小通路**）
//
// 状态（不得误读，红线 R8）：
//   · 已落（M1-S0/S1/S2/S3a/S3b，见 `doc/design/M1-实现计划.md` §5）：
//     ① G1-I 冻结的**端口面**（逐条对齐 `doc/decisions/G1-I-最小冻结清单.md` §1/§2.1/§2.6）**一字未改**；
//     ② **取指通路**：M01 `vr1_bp`（顺序/静态预测）→ M02 `vr1_ftq`（16 项；**本批新增冲刷口**）
//        → M03 `vr1_ifetch`（32 B 窗 16 槽 ＋ IBUF；**本批新增冲刷口**）→ 取指请求/响应握手；
//     ③ **译码级** M05 `vr1_decode`（14 条定长译码 ＋ `pre_exc`；**本批新增冲刷口**；
//        M2 增补 `ADD`／`BNE`／ALU 家族化／`AUIPC`（合 27 条）—— 2026-09-26 心跳第 5 轮；
//        M3-(d) 增补 16 条：分支余 4（BLT/BGE/BLTU/BGEU）＋ JALR ＋ 载入余 6 ＋ 存储余 3
//        ＋ FENCE/FENCE.I（合 **57 条**合法面）—— 2026-09-26 心跳第 10 轮，
//        见该文件头"首版子集口径"）；
//     ④ **后端最小通路（M1-S3b）**：`D`→R 缓冲（M06 恒等映射）→`S` 分配 ROB（M15）
//        →`W` 发射读源（后读）→`E` 执行（M09 `vr1_exu_int`／M10 `vr1_bru`／M11 `vr1_lsu`
//        ／M17 `vr1_csr`）→`WB` 完成→`CT` 提交（M15 `commit_t`/`rt_t` ＋ M16 提交拍副作用
//        ＋ M18 `vr1_trap` 的现场组装/`mtvec` 重定向）；`rt_t` 已接到冻结端口 `rt_valid_o`/`rt_o`。
//     复位后取 `RESET_PC`（=0x1000）由 M01 的 pc 寄存器承担（清单 §1.2 第 10 条）。
//   · **首版结构简化**（计划 §2.3：单发射单提交；**接口之内、不动冻结面**）：
//     - M06 重命名 ＝ **恒等映射**（`paddr := arch`，无 RAT/PRF/free-list）：单发射 in-order ⇒
//       `rd_paddr`/`rd_old_paddr` 语义退化但**字段照冻面携带**；R 级**不读源值**（后读在 `W` 拍，
//       `spec/01` §1.1 A9）——TODO(M1-S3)（真 RAT/PRF/free-list）；
//     - M07 分发／M08 IQ **不单列模块**：单发射单条在飞 ⇒ 分配（`rob_alloc_t`）在 `S` 拍内联完成、
//       就绪判据退化为"条目空"、无唤醒 CAM（源值在 `W` 拍直接读 GPR）——TODO(M1-S3)；
//     - **重定向在 `CT` 拍生成**（单条在飞 ⇒ 更年轻指令最多只到 R 缓冲/IBUF/FTQ）：`flush_all` ＝
//       BRU 误预测（`mispred`）或 trap/`MRET`（`vr1_trap`）；逐级动作与 `spec/01` §5.2 等价
//       （`BP1..BP3` 重定向、`F0..F2` 清 FTQ/在途请求、`D` 清指针、`R` 清缓冲）——TODO(M1-S3)
//       （`E` 拍解析即冲刷的时序优化）。
//   · **未实现**（逐条给出口；未完成项一律 `TODO(M1-S<n>)`／`TODO(G1-F v<n>)`，不写"看起来对"的逻辑）：
//     - 多发射/多提交（`COMMIT_WIDTH=4` 的 lane 展开）、128 项 ROB 容量与 `rob_near_full` 反压、
//     - IQ×3（`IQ_INT/MEM/BR`）与唤醒 CAM、旁路网络（`spec/07`）、转发/`LQ`/`SQ`、
//     - checkpoint/回滚（`needs_ckpt` 恒 0，逐条路径）、预测器更新路径（`bp_upd_id` 恒 0）、
//     - cache/MMU/中断（清单 §1.2 不含集；`GI-2` 负判据：本文件无 mmu/mshr/irq 端口与类型名）、
//     - `rt_ready` 反压（trace 写出器为零延迟监视器；见下"不消费面"）。
//   · **两处口径缺登记**（**不新造语义**）：`excp_t.tval` 与 `rt_t.mem_*`/`csr_old` 的**级间载体**
//     在冻结面无定义（`spec/01` §3.18 尾注 T-10-4／§3.21②③ 的"提交拍读 SQ/LQ/`csrq`"）⇒ 首版由
//     `E` 拍随完成回报携带到提交拍（内部寄存器），**不据其做任何判决** —— TODO(G1-F)。
//
// 依据（端口面逐条可核）：
//   · doc/decisions/G1-I-最小冻结清单.md §1（含/不含范围）、§2.1（23 个接口 struct）、§2.6（恒 0 表）；
//   · doc/spec/01 §1.1（级号职责）／§3.x（各 struct）／§4（反压）／§5.1~§5.3（冲刷与恢复点）／
//     §6（顶层端口表）／§7 A10（`rt_t` 由 `CT` 授权拍产生）；
//   · doc/spec/00 §4（参数唯一源）／§6（M01~M20 模块归属）；
//   · doc/spec/10 §2/§4.1（trap 与 CSR）；doc/design/M1-实现计划.md §2.1／§2.3／§5。
//
// 写授权：`state/freeze.json` 的 rtl_write_authorized=true（依 R0 2026-09-25 签署 G1-I 的人令；
//   记录落 doc/spec/14 §7）。基线宣布后本文件转「先批后改」（红线 R5）。
// ==========================================================================
`ifndef VR1_CORE_SV
`define VR1_CORE_SV

module vr1_core (
  // ---- 时钟/复位（spec/01 §6；spec/00 §4.7：CLK_DOMAINS=1，异步复位、同步释放）----
  // 注：复位"同步释放"由片上复位同步器实现，属后续批次；本批只吃 rst_n。
  input  logic                  clk,
  input  logic                  rst_n,

  // ---- 族 1：取指存储侧（spec/01 §3.13 请求 / §3.16 `icache_rsp_t` 响应）----
  // 首版无 L1I：由 TB 内存桩充当响应端（清单 §1.2 第 2 条）。请求/响应握手在 M03 `vr1_ifetch`。
  output logic                  imem_req_valid,
  output vr1_pkg::mem_req_t     imem_req,
  input  logic                  imem_req_ready,
  input  logic                  imem_rsp_valid,
  input  var vr1_pkg::icache_rsp_t  imem_rsp,
  output logic                  imem_rsp_ready,

  // ---- 族 2：访存侧（spec/01 §3.13 请求 / §3.16 `dcache_rsp_t` 响应）----
  // 首版无 L1D、无转发（清单 §1.2 第 2 条、§2.6 `dcache_rsp_t` 行）。
  output logic                  dmem_req_valid,
  output vr1_pkg::mem_req_t     dmem_req,
  input  logic                  dmem_req_ready,
  input  logic                  dmem_rsp_valid,
  input  var vr1_pkg::dcache_rsp_t  dmem_rsp,
  output logic                  dmem_rsp_ready,

  // ---- 族 5：提交/退休观察点（spec/01 §3.17 `commit_t` / §3.21 `rt_t`）----
  // `rt_o` 是 TB 侧 trace 写出器的唯一真值载荷（§3.21）；M1-S3b 起由 M15 `vr1_rob` 在 `CT` 拍产出。
  output logic                  commit_valid,
  output logic                  rt_valid_o,
  output vr1_pkg::rt_t          rt_o,
  input  logic                  rt_ready,

  // ---- 族 7：CSR 写端口观察点（spec/01 §3.19 `csr_wr_t`）----
  output logic                  csr_wr_valid
);

  import vr1_pkg::*;

  // -------------------------------------------------------------------------
  // 常量（`isop` 成员编码逐行取自 `spec/02` §9.1；本文件**只引用**，不另赋、不重排）
  // -------------------------------------------------------------------------
  localparam logic [9:0] ISOP_ADDI  = 10'h000;
  localparam logic [9:0] ISOP_SLTI  = 10'h001;
  localparam logic [9:0] ISOP_SLTIU = 10'h002;
  localparam logic [9:0] ISOP_XORI  = 10'h003;
  localparam logic [9:0] ISOP_ORI   = 10'h004;
  localparam logic [9:0] ISOP_ANDI  = 10'h005;
  localparam logic [9:0] ISOP_SLLI  = 10'h006;
  localparam logic [9:0] ISOP_SRLI  = 10'h007;
  localparam logic [9:0] ISOP_SRAI  = 10'h008;
  localparam logic [9:0] ISOP_AUIPC = 10'h010;   // M2 增补（§9.1.3）
  localparam logic [9:0] ISOP_ADDIW = 10'h020;
  localparam logic [9:0] ISOP_SLLIW = 10'h021;
  localparam logic [9:0] ISOP_SRLIW = 10'h022;
  localparam logic [9:0] ISOP_SRAIW = 10'h023;
  localparam logic [9:0] ISOP_ADD   = 10'h030;   // M2 增补（§9.1.1）
  localparam logic [9:0] ISOP_SUB   = 10'h031;
  localparam logic [9:0] ISOP_SLL   = 10'h032;
  localparam logic [9:0] ISOP_SLT   = 10'h033;
  localparam logic [9:0] ISOP_SLTU  = 10'h034;
  localparam logic [9:0] ISOP_XOR   = 10'h035;
  localparam logic [9:0] ISOP_SRL   = 10'h036;
  localparam logic [9:0] ISOP_SRA   = 10'h037;
  localparam logic [9:0] ISOP_OR    = 10'h038;
  localparam logic [9:0] ISOP_AND   = 10'h039;
  localparam logic [9:0] ISOP_LUI   = 10'h040;
  localparam logic [9:0] ISOP_ADDW  = 10'h050;
  localparam logic [9:0] ISOP_SUBW  = 10'h051;
  localparam logic [9:0] ISOP_SLLW  = 10'h052;
  localparam logic [9:0] ISOP_SRLW  = 10'h053;
  localparam logic [9:0] ISOP_SRAW  = 10'h054;
  localparam logic [9:0] ISOP_BEQ   = 10'h080;
  localparam logic [9:0] ISOP_BNE   = 10'h081;   // M2 增补（§9.1.3）
  localparam logic [9:0] ISOP_BLT   = 10'h082;   // M3-(d) 增补（§9.1.3）
  localparam logic [9:0] ISOP_BGE   = 10'h083;   // M3-(d) 增补
  localparam logic [9:0] ISOP_BLTU  = 10'h084;   // M3-(d) 增补
  localparam logic [9:0] ISOP_BGEU  = 10'h085;   // M3-(d) 增补
  localparam logic [9:0] ISOP_JALR  = 10'h090;   // M3-(d) 增补（§9.1.3）
  localparam logic [9:0] ISOP_JAL   = 10'h0A0;
  localparam logic [9:0] ISOP_LB    = 10'h100;   // M3-(d) 增补（§9.1.4）
  localparam logic [9:0] ISOP_LH    = 10'h101;   // M3-(d) 增补
  localparam logic [9:0] ISOP_LW    = 10'h102;
  localparam logic [9:0] ISOP_LD    = 10'h103;   // M3-(d) 增补
  localparam logic [9:0] ISOP_LBU   = 10'h104;   // M3-(d) 增补
  localparam logic [9:0] ISOP_LHU   = 10'h105;   // M3-(d) 增补
  localparam logic [9:0] ISOP_LWU   = 10'h106;   // M3-(d) 增补
  localparam logic [9:0] ISOP_SB    = 10'h180;   // M3-(d) 增补
  localparam logic [9:0] ISOP_SH    = 10'h181;   // M3-(d) 增补
  localparam logic [9:0] ISOP_SW    = 10'h182;
  localparam logic [9:0] ISOP_SD    = 10'h183;   // M3-(d) 增补
  localparam logic [9:0] ISOP_MUL   = 10'h200;
  localparam logic [9:0] ISOP_DIV   = 10'h280;
  localparam logic [9:0] ISOP_REM   = 10'h282;
  localparam logic [9:0] ISOP_CSRRW = 10'h300;
  localparam logic [9:0] ISOP_CSRRS = 10'h301;
  localparam logic [9:0] ISOP_MRET  = 10'h312;
  localparam logic [9:0] ISOP_FENCE = 10'h380;   // M3-(d) 增补（§9.1.8）
  localparam logic [9:0] ISOP_FENCEI= 10'h381;   // M3-(d) 增补（§9.1.8；Zifencei）

  localparam logic [1:0] PRV_M    = 2'b11;      // 单特权级（清单 §2.6）
  localparam logic [1:0] DST_NONE = 2'b00;

  // =========================================================================
  // 内部信号声明（**全部前置**：ModelSim `vlog` 要求先声明后使用；端口连接里出现的
  //   未声明标识符会被当作**1 bit 隐式网**——宽信号会静默截断，故一律显式声明）
  // =========================================================================
  // ---- 前端级间与冲刷 ----
  ftq_req_t    bp_ftq_req;
  logic        bp_ftq_req_vld;
  logic        bp_ftq_req_rdy;
  ftq_entry_t  ftq_head;
  logic        ftq_head_vld;
  logic [4:0]  ftq_head_id;
  logic        ftq_pop;
  logic        ibuf_win_vld;
  fetch_raw_t  ibuf_lanes [IBUF_ENTRIES];
  logic        ibuf_drain;
  logic        flush_all;                       // 冲刷脉冲（BRU 误预测 / trap / MRET）
  logic        redirect_vld;                    // 重定向有效（= flush_all）
  logic [39:0] redirect_pc;                     // 重定向目标 pc

  // ---- 译码 ----
  uop_t        dec_uop [DECODE_WIDTH];
  logic        dec_ready;

  // ---- R 缓冲（M06 恒等映射）----
  rmap_uop_t   rbuf [DECODE_WIDTH];
  logic [2:0]  rbuf_cnt;
  logic [2:0]  grp_n;
  logic        accept_grp;
  logic        disp_fire;
  rmap_uop_t   head;

  // ---- S/ROB/提交 ----
  rob_alloc_t  alloc;
  logic        rob_free;
  logic        rob_commit_vld;
  commit_t     rob_commit;
  rt_t         rob_rt;
  logic [63:0] rob_data;
  logic [3:0]  rob_head_exc_code;
  logic        rob_head_is_intr;
  logic [39:0] rob_head_pc;
  logic [31:0] rob_head_raw32;
  logic [1:0]  rob_head_priv;
  logic [39:0] rob_head_tval;

  // ---- 单元选择（组合，以 `head.isop` 为准）----
  logic        is_int_q, is_br_q, is_mem_q, is_csr_q, is_mret_q, is_fence_q, is_none_q;
  logic        unit_rdy;

  // ---- WB 完成回报面（EXU / LSU / 简单单元 三选一）----
  logic        wb_vld;
  logic [63:0] wb_rd_data;
  logic        wb_exc_v;
  logic [3:0]  wb_exc_code;
  logic [39:0] wb_tval;
  logic        wb_mem_v, wb_mem_wr;
  logic [39:0] wb_mem_addr;
  logic [63:0] wb_mem_wdata, wb_mem_rdata;
  logic [1:0]  wb_mem_size;
  logic        wb_csr_v;
  logic [63:0] wb_csr_src, wb_csr_old;
  logic        wb_is_br, wb_mispred;

  // ---- W 拍发射 ----
  disp_x_t     disp;
  logic [63:0] rs1_val, rs2_val;

  // ---- M09 EXU ----
  x_complete_t xc;
  logic        exu_launch, exu_rdy;

  // ---- M10 BRU（提交拍消费的重定向面）----
  disp_x_t     bru_disp [ISSUE_WIDTH];
  br_resolve_t br_res;
  logic        bru_launch;
  logic        br_pend_v, br_pend_taken, br_pend_mispred;
  logic [39:0] br_pend_target, br_pend_pc;
  logic        br_redirect_v;
  logic [39:0] br_redirect_pc;

  // ---- M11 LSU ----
  ls_complete_t lsc;
  logic         lsu_launch, lsu_rdy;
  logic [39:0]  lsu_tval;
  logic [63:0]  lsu_ld_data;
  logic         lsu_mem_v, lsu_mem_wr;
  logic [39:0]  lsu_mem_addr;
  logic [63:0]  lsu_mem_wdata, lsu_mem_rdata;
  logic [1:0]   lsu_mem_size;

  // ---- M17 CSR / M18 trap ----
  csr_wr_t     csr_wr;
  logic [63:0] csr_rdata, csr_new;
  logic        csr_wr_en;
  ret_ctrl_t   csr_ret;
  excp_t       excp_pkt;
  logic [63:0] csr_mtvec, csr_mepc, csr_mcause, csr_mtval, csr_mscratch, csr_mstatus;
  logic        excp_commit, ret_commit;
  logic        trap_redirect_v;
  logic [39:0] trap_redirect_pc;

  // ---- 内部状态 ----
  logic [63:0] gpr [32];
  logic [63:0] cycle_q;
  logic [11:0] seq_q;
  logic        pend_q;
  logic [63:0] pend_data_q;
  logic        pend_csr_v_q;
  logic [63:0] pend_csr_src_q, pend_csr_old_q;
  logic        pend_is_br_q, pend_mispred_q;
  logic        pend_exc_v_q;
  logic [3:0]  pend_exc_code_q;
  logic [39:0] pend_tval_q;
  logic        mret_q;

  // -------------------------------------------------------------------------
  // M01 预测器（顺序/静态预测；重定向入口 M1-S3b 起由 `flush_all`/`redirect_pc` 驱动）
  // -------------------------------------------------------------------------
  vr1_bp u_bp (
    .clk             (clk),
    .rst_n           (rst_n),
    .bp_pc_i         (redirect_pc),
    .bp_pc_vld_i     (redirect_vld),
    .ftq_req_o       (bp_ftq_req),
    .ftq_req_valid_o (bp_ftq_req_vld),
    .ftq_req_ready_i (bp_ftq_req_rdy)
  );

  // -------------------------------------------------------------------------
  // M02 FTQ（16 项；本批新增 `flush_i`）
  // -------------------------------------------------------------------------
  vr1_ftq u_ftq (
    .clk             (clk),
    .rst_n           (rst_n),
    .ftq_req_i       (bp_ftq_req),
    .ftq_req_valid_i (bp_ftq_req_vld),
    .ftq_req_ready_o (bp_ftq_req_rdy),
    .ftq_entry_o     (ftq_head),
    .ftq_pop_valid_o (ftq_head_vld),
    .ftq_pop_id_o    (ftq_head_id),
    .ftq_pop_ready_i (ftq_pop),
    .flush_i         (flush_all)
  );

  // -------------------------------------------------------------------------
  // M03 取指（32 B 窗对齐 → 16 槽 → IBUF；本批新增 `flush_i`）
  // -------------------------------------------------------------------------
  vr1_ifetch u_ifetch (
    .clk             (clk),
    .rst_n           (rst_n),
    .ftq_entry_i     (ftq_head),
    .ftq_entry_vld_i (ftq_head_vld),
    .ftq_entry_id_i  (ftq_head_id),
    .ftq_pop_o       (ftq_pop),
    .imem_req_valid_o(imem_req_valid),
    .imem_req_o      (imem_req),
    .imem_req_ready_i(imem_req_ready),
    .imem_rsp_valid_i(imem_rsp_valid),
    .imem_rsp_i      (imem_rsp),
    .imem_rsp_ready_o(imem_rsp_ready),
    .ibuf_win_vld_o  (ibuf_win_vld),
    .ibuf_rd_o       (ibuf_lanes),
    .ibuf_drain_i    (ibuf_drain),
    .flush_i         (flush_all)
  );

  // -------------------------------------------------------------------------
  // M05 译码级：IBUF 读口消费（≤`DECODE_WIDTH` 个起始槽/拍）→ `uop_t[]`
  //   `uop_ready_i` = R 缓冲可收（M1-S3b：由"恒 1 丢包"改为**真反压**）
  // -------------------------------------------------------------------------
  vr1_decode u_decode (
    .clk             (clk),
    .rst_n           (rst_n),
    .ibuf_win_vld_i  (ibuf_win_vld),
    .ibuf_rd_i       (ibuf_lanes),
    .ibuf_drain_o    (ibuf_drain),
    .uop_o           (dec_uop),
    .uop_ready_i     (dec_ready),
    .flush_i         (flush_all)
  );

  // =========================================================================
  // 后端最小通路（M1-S3b）：R 缓冲（M06 恒等映射）→ S 分配 → W 发射 → E → WB → CT
  // =========================================================================

  // -------------------------------------------------------------------------
  // M06 重命名（首版**恒等映射**）：`uop_t` → `rmap_uop_t`（§3.5 全字段照携带）
  //   物理号 := 架构号（无 RAT/PRF/free-list；见文件头简化声明）
  // -------------------------------------------------------------------------
  function automatic rmap_uop_t map_uop(input uop_t u);
    rmap_uop_t m;
    m               = '0;
    m.valid         = u.valid;
    m.pc            = u.pc;
    m.raw32         = u.raw32;
    m.is_c          = u.is_c;
    m.isop          = u.isop;
    m.cls           = u.cls;
    m.rs1_en        = u.rs1_en;
    m.rs2_en        = u.rs2_en;
    m.rd_en         = u.rd_en;
    m.rd            = u.rd;
    m.dst_kind      = u.dst_kind;
    m.imm           = u.imm;
    m.imm_kind      = u.imm_kind;
    m.src_sel       = u.src_sel;
    m.dm            = u.dm;
    m.sext          = u.sext;
    m.is_w          = u.is_w;
    m.aq            = u.aq;
    m.rl            = u.rl;
    m.fm            = u.fm;
    m.csr_addr      = u.csr_addr;
    m.csr_wr_type   = u.csr_wr_type;
    m.pred_taken    = u.pred_taken;
    m.pred_target   = u.pred_target;
    m.bp_upd_id     = u.bp_upd_id;
    m.ftq_id        = u.ftq_id;
    m.pre_exc       = u.pre_exc;
    m.pre_exc_code  = u.pre_exc_code;
    m.bad_va        = u.bad_va;
    // 恒等映射面（§3.5 新增成员）
    m.psrc1         = {1'b0, u.rs1};
    m.psrc2         = {1'b0, u.rs2};
    m.rs1_arch      = u.rs1;
    m.rd_paddr      = {1'b0, u.rd};
    m.rd_old_paddr  = {1'b0, u.rd};
    m.rd_is_new     = 1'b0;                      // 无 free-list 分配（简化）
    m.ckpt_id       = 2'b00;
    m.is_br         = is_br_member(u.isop);
    m.needs_ckpt    = 1'b0;                      // 无 checkpoint（计划 §2.3 简化 #4）
    m.rs1_val       = 64'd0;                     // R 级不读源值（后读在 `W` 拍，§1.1 A9）
    return m;
  endfunction

  always_comb begin
    grp_n = 3'd0;
    for (int unsigned k = 0; k < DECODE_WIDTH; k++)
      if (dec_uop[k].valid) grp_n = grp_n + 3'd1;
  end

  // `dec_ready` = R 缓冲空（可整组收）+ 非冲刷拍（冲刷拍不收，防旧路径入流）
  assign dec_ready  = (rbuf_cnt == 3'd0) && !flush_all;
  assign accept_grp = dec_ready && (grp_n != 3'd0);

  // -------------------------------------------------------------------------
  // M15 ROB（单条在飞）与 S 拍分配
  // -------------------------------------------------------------------------
  assign unit_rdy = is_int_q ? exu_rdy : (is_mem_q ? lsu_rdy : 1'b1);
  assign head      = rbuf[0];
  assign disp_fire = (rbuf_cnt != 3'd0) && rob_free && !flush_all && unit_rdy;

  // 本批**单发射**（计划 §2.3 简化 #1）：unit 选定以 `head.isop` 为准。
  //   **显式逐成员列举**（不用 `cls` 代列举）：非法编码的 `isop` 恒 `'0`（＝`ISOP_ADDI`），其 `cls`
  //   亦为 000 ⇒ 用 `cls` 会把非法条目派给 EXU、破坏"非法⇒异常条目"的收口（`is_none_q` 路径）。
  //   注：`ISOP_ADDI==0` 与该别名共存的既有行为不变（非法条目的结果面已由 `D` 级撤空、
  //   `alloc.pre_exc` 已在 ROB 侧定性）—— TODO(G1-F)：`uop_t` 增 `is_ill`/独立非法成员后可收口。
  //   成员面（M3-(d) 起）：§9.1.1 19 ＋ §9.1.2 9 ＋ §9.1.3 10 ＋ §9.1.4 11 ＋ §9.1.6 3 ＋ §9.1.7 2
  //   ＋ §9.1.8 3 ＝ 57（与 `vr1_decode` 的合法面逐条一致；余 30 成员随 G1-F）。
  function automatic logic is_int_member(input logic [9:0] isop);
    unique case (isop)
      ISOP_ADDI, ISOP_SLTI, ISOP_SLTIU, ISOP_XORI, ISOP_ORI, ISOP_ANDI,
      ISOP_SLLI, ISOP_SRLI, ISOP_SRAI, ISOP_AUIPC,
      ISOP_ADDIW, ISOP_SLLIW, ISOP_SRLIW, ISOP_SRAIW,
      ISOP_ADD, ISOP_SUB, ISOP_SLL, ISOP_SLT, ISOP_SLTU, ISOP_XOR, ISOP_SRL, ISOP_SRA, ISOP_OR, ISOP_AND,
      ISOP_LUI, ISOP_ADDW, ISOP_SUBW, ISOP_SLLW, ISOP_SRLW, ISOP_SRAW,
      ISOP_MUL, ISOP_DIV, ISOP_REM:  is_int_member = 1'b1;
      default:                       is_int_member = 1'b0;
    endcase
  endfunction

  function automatic logic is_br_member(input logic [9:0] isop);
    is_br_member = (isop == ISOP_BEQ)  || (isop == ISOP_BNE)  || (isop == ISOP_BLT)
                || (isop == ISOP_BGE)  || (isop == ISOP_BLTU) || (isop == ISOP_BGEU)
                || (isop == ISOP_JAL)  || (isop == ISOP_JALR);   // M3-(d)：分支 6 条 ＋ JAL/JALR
  endfunction

  // 访存成员（§9.1.4 全 11 条；M3-(d) 起载入 7 ＋ 存储 4 全入面）
  function automatic logic is_mem_member(input logic [9:0] isop);
    is_mem_member = (isop == ISOP_LB)  || (isop == ISOP_LH)  || (isop == ISOP_LW)
                 || (isop == ISOP_LD)  || (isop == ISOP_LBU) || (isop == ISOP_LHU)
                 || (isop == ISOP_LWU) || (isop == ISOP_SB)  || (isop == ISOP_SH)
                 || (isop == ISOP_SW)  || (isop == ISOP_SD);
  endfunction

  // 序类成员（§9.1.8 FENCE/FENCE.I；类型位 `type.bit4`）
  //   最小语义（本版）：识别 + **无副作用完成**——无 L1I、无 store buffer、取指桩为组合读
  //   ⇒ 排空/无效化动作集合为空（`spec/00` §2 一期 ISA 串含 `zifencei` ⇒ 按"最小语义"入面）。
  function automatic logic is_fence_member(input logic [9:0] isop);
    is_fence_member = (isop == ISOP_FENCE) || (isop == ISOP_FENCEI);
  endfunction

  always_comb begin
    is_int_q   = is_int_member(head.isop);
    is_br_q    = is_br_member(head.isop);
    is_mem_q   = is_mem_member(head.isop);
    is_csr_q   = (head.isop == ISOP_CSRRW) || (head.isop == ISOP_CSRRS);
    is_mret_q  = (head.isop == ISOP_MRET);
    is_fence_q = is_fence_member(head.isop);
    // 无对应单元 ⇒ 非法编码（`D` 级对 57 条以外一律 `pre_exc=1`/code 2 且 `isop=0`，见 `vr1_decode`）
    is_none_q  = !(is_int_q || is_br_q || is_mem_q || is_csr_q || is_mret_q || is_fence_q);
  end

  // `type_f[6:0]`（`spec/02` §3.1 位序；本设计由 `isop` 唯一导出，不设第二张表）
  function automatic logic [6:0] type_of(input logic is_br, input logic is_mem,
                                         input logic is_csr, input logic is_fence);
    type_of    = 7'd0;
    type_of[0] = 1'b0;                           // is_c（无 C 展开）
    type_of[1] = is_br;
    type_of[2] = 1'b0;                           // is_comp（无 C 展开第二半）
    type_of[3] = 1'b0;                           // is_wfi（不在本批入面集内）
    type_of[4] = is_fence;                       // §3.1 bit4：FENCE/FENCE.I（M3-(d) 起可置位）
    type_of[5] = is_mem;
    type_of[6] = is_csr;
  endfunction

  // 分配载荷（`spec/01` §3.6）
  always_comb begin
    alloc            = '0;
    alloc.valid      = 1'b1;
    alloc.slot       = 8'd0;                     // 单条在飞 ⇒ 槽号恒 0 有效（128 项槽号 TODO(M1-S3)）
    alloc.pc         = head.pc;
    alloc.raw32      = head.raw32;
    alloc.type_f     = type_of(is_br_q, is_mem_q, is_csr_q, is_fence_q);
    alloc.dst_kind   = head.dst_kind;
    alloc.rd_arch    = head.rd;
    alloc.rd_paddr   = head.rd_paddr;
    alloc.rd_old_paddr = head.rd_old_paddr;
    alloc.ckpt_id    = head.ckpt_id;
    alloc.priv       = PRV_M;                    // 单特权级（清单 §2.6）
    alloc.pre_exc    = {head.pre_exc, head.pre_exc_code};   // §3.6：{v, code[3:0]}
    alloc.seq        = seq_q;                    // 全局 μop 序号：**产生点＝S 级**（§3.6）
    alloc.grp_last   = 1'b1;                     // 单发射 ⇒ 每组 1 条 ⇒ 组尾恒真（简化）
    alloc.needs_ckpt = head.needs_ckpt;
    alloc.ftq_id     = head.ftq_id;
  end

  vr1_rob u_rob (
    .clk               (clk),
    .rst_n             (rst_n),
    .alloc_vld_i       (disp_fire),
    .alloc_i           (alloc),
    .alloc_csr_addr_i  (head.csr_addr),
    .alloc_csr_op_i    (head.csr_wr_type),
    .free_o            (rob_free),
    .wb_vld_i          (wb_vld),
    .wb_rd_data_i      (wb_rd_data),
    .wb_exc_v_i        (wb_exc_v),
    .wb_exc_code_i     (wb_exc_code),
    .wb_tval_i         (wb_tval),
    .wb_mem_v_i        (wb_mem_v),
    .wb_mem_addr_i     (wb_mem_addr),
    .wb_mem_wdata_i    (wb_mem_wdata),
    .wb_mem_rdata_i    (wb_mem_rdata),
    .wb_mem_size_i     (wb_mem_size),
    .wb_mem_wr_i       (wb_mem_wr),
    .wb_csr_v_i        (wb_csr_v),
    .wb_csr_src_i      (wb_csr_src),
    .wb_csr_old_i      (wb_csr_old),
    .wb_is_br_i        (wb_is_br),
    .wb_mispred_i      (wb_mispred),
    .commit_vld_o      (rob_commit_vld),
    .commit_o          (rob_commit),
    .excp_i            (excp_pkt),
    .ret_i             (csr_ret),
    .rt_o              (rob_rt),
    .commit_ack_i      (1'b1),                   // 首版无 RT 反压（见文件头"不消费面"）
    .cycle_i           (cycle_q),
    .csr_new_i         (csr_new),
    .csr_wr_en_i       (csr_wr_en),
    .head_exc_code_o   (rob_head_exc_code),
    .head_is_intr_o    (rob_head_is_intr),
    .head_pc_o         (rob_head_pc),
    .head_raw32_o      (rob_head_raw32),
    .head_priv_o       (rob_head_priv),
    .head_tval_o       (rob_head_tval),
    .head_data_o       (rob_data)
  );

  // -------------------------------------------------------------------------
  // `W` 拍发射载荷（`spec/01` §3.11 `disp_x_t`；后读源值，§1.1 A9）
  // -------------------------------------------------------------------------
  // 源寄存器取号：`rmap_uop_t`（§3.5）**无** `rs1`/`rs2` 成员 —— 架构号由 `rs1_arch` 与
  //   恒等映射面 `psrc2[4:0]`（＝架构号）给出（真 RAT 版按 `psrc1/psrc2` 读 PRF，TODO(M1-S3)）
  always_comb begin
    rs1_val = head.rs1_en ? gpr[head.rs1_arch] : 64'd0;
    rs2_val = head.rs2_en ? gpr[head.psrc2[4:0]] : 64'd0;
  end

  always_comb begin
    disp              = '0;
    disp.valid        = 1'b1;
    disp.eu_id        = 4'd0;                    // 无「单元号→EU」分配表 ⇒ 不消费（TODO(G1-F)）
    disp.isop         = head.isop;
    disp.rs1_val      = rs1_val;
    disp.rs2_val      = rs2_val;
    disp.imm          = head.imm;
    disp.pc           = head.pc;
    disp.rob_id       = 8'd0;                    // 单条在飞 ⇒ rob_id 恒 0（TODO(M1-S3)：128 项 id）
    disp.rd_paddr     = head.rd_paddr;
    disp.dm           = head.dm;
    disp.sext         = head.sext;
    disp.is_w         = head.is_w;
    disp.aq           = head.aq;
    disp.rl           = head.rl;
    disp.csr_addr     = head.csr_addr;
    disp.csr_wr_type  = head.csr_wr_type;
    disp.pred_taken   = head.pred_taken;
    disp.pred_target  = head.pred_target;
    disp.bp_upd_id    = head.bp_upd_id;
    disp.ckpt_id      = head.ckpt_id;
    disp.ftq_id       = head.ftq_id;
    disp.rs1_arch     = head.rs1_arch;               // §3.5 有 `rs1_arch`（无 `rs1`）
    disp.rd_arch      = head.rd;                     // §3.5 `rd`＝架构号（`rd_paddr` 为物理号）
  end

  // -------------------------------------------------------------------------
  // M09 整数执行单元（ALU/SHIFT/MUL/DIV·REM；多拍占用见其文件头）
  // -------------------------------------------------------------------------
  assign exu_launch = disp_fire && is_int_q;

  vr1_exu_int u_exu (
    .clk        (clk),
    .rst_n      (rst_n),
    .disp_vld_i (exu_launch),
    .disp_i     (disp),
    .disp_rdy_o (exu_rdy),
    .xc_o       (xc)
  );

  // -------------------------------------------------------------------------
  // M10 分支解析（组合；本批**首次例化**）：`disp_x_t[ISSUE_WIDTH]` → `br_resolve_t`
  //   单发射 ⇒ 只用 lane 0；结果在发射拍采样、提交拍消费（重定向，见下）
  // -------------------------------------------------------------------------
  assign bru_launch = disp_fire && is_br_q;

  always_comb begin
    for (int unsigned k = 0; k < ISSUE_WIDTH; k++) bru_disp[k] = '0;
    bru_disp[0]        = disp;
    bru_disp[0].valid  = bru_launch;
  end

  vr1_bru u_bru (
    .clk          (clk),
    .rst_n        (rst_n),
    .disp_i       (bru_disp),
    .br_resolve_o (br_res)
  );

  // -------------------------------------------------------------------------
  // M11 访存单元（LW/SW ＋ 非对齐 fault；请求/响应握手）
  // -------------------------------------------------------------------------
  assign lsu_launch = disp_fire && is_mem_q;

  vr1_lsu u_lsu (
    .clk              (clk),
    .rst_n            (rst_n),
    .req_vld_i        (lsu_launch),
    .disp_i           (disp),
    .req_rdy_o        (lsu_rdy),
    .ls_o             (lsc),
    .tval_o           (lsu_tval),
    .ld_data_o        (lsu_ld_data),
    .mem_v_o          (lsu_mem_v),
    .mem_addr_o       (lsu_mem_addr),
    .mem_wdata_o      (lsu_mem_wdata),
    .mem_rdata_o      (lsu_mem_rdata),
    .mem_size_o       (lsu_mem_size),
    .mem_wr_o         (lsu_mem_wr),
    .dmem_req_valid_o (dmem_req_valid),
    .dmem_req_o       (dmem_req),
    .dmem_req_ready_i (dmem_req_ready),
    .dmem_rsp_valid_i (dmem_rsp_valid),
    .dmem_rsp_i       (dmem_rsp),
    .dmem_rsp_ready_o (dmem_rsp_ready)
  );

  // -------------------------------------------------------------------------
  // M17 CSR 单元（六件 ＋ trap 进场 ＋ MRET）与 M18 trap 单元（现场组装 ＋ 重定向）
  // -------------------------------------------------------------------------
  // 读口：地址恒取"将发射/在飞"的 μop（组合、零副作用；`W`/`E` 拍同拍采样，§1.1 A9）
  vr1_csr u_csr (
    .clk            (clk),
    .rst_n          (rst_n),
    .csr_addr_i     (head.csr_addr),
    .csr_rdata_o    (csr_rdata),
    .csr_wr_i       (csr_wr),
    .csr_new_o      (csr_new),
    .csr_wr_en_o    (csr_wr_en),
    .excp_commit_i  (excp_commit),
    .excp_epc_i     (rob_head_pc),
    .excp_cause_i   (rob_head_exc_code),
    .excp_is_intr_i (rob_head_is_intr),
    .excp_tval_i    (rob_head_tval),
    .excp_from_i    (rob_head_priv),
    .ret_commit_i   (ret_commit),
    .ret_o          (csr_ret),
    .mtvec_o        (csr_mtvec),
    .mepc_o         (csr_mepc),
    .mcause_o       (csr_mcause),
    .mtval_o        (csr_mtval),
    .mscratch_o     (csr_mscratch),
    .mstatus_o      (csr_mstatus)
  );

  vr1_trap u_trap (
    .clk            (clk),
    .rst_n          (rst_n),
    .exc_vld_i      (rob_commit.exc_vld),       // 提交拍定性：**本条以异常提交**（§3.17 `exc_vld`）
    .exc_code_i     (rob_head_exc_code),
    .exc_is_intr_i  (rob_head_is_intr),
    .exc_pc_i       (rob_head_pc),
    .exc_instr_i    (rob_head_raw32),
    .exc_priv_i     (rob_head_priv),
    .exc_tval_i     (rob_head_tval),
    .mtvec_i        (csr_mtvec),
    .mstatus_i      (csr_mstatus),
    .ret_i          (csr_ret),
    .excp_o         (excp_pkt),
    .redirect_vld_o (trap_redirect_v),
    .redirect_pc_o  (trap_redirect_pc),
    .flush_all_o    ()
  );

  // -------------------------------------------------------------------------
  // 提交拍（`CT`）：架构态写（GPR）＋ CSR 写触发 ＋ 重定向/冲刷生成
  // -------------------------------------------------------------------------
  // CSR 写端口（§3.19）：仅当提交包声明 `csr_vld`（`type[6]` ∧ 非异常条目，§3.17＋§3.19 规则 5）
  //   `commit_t.csr_wr` 是 **81 bit 打包位域**（`spec/01` §3.17 表：`csr_wr` 81）⇒ 先按
  //   `csr_wr_t`（同 81 bit）**位流还原**再逐成员取用（禁裸切片，防打包序假设写死）
  csr_wr_t cwr;
  assign cwr   = rob_commit.csr_wr;
  assign csr_wr = cwr;

  assign excp_commit = rob_commit.exc_vld;
  // MRET 提交（串行化类 B，§5.3②）：**必须用发射拍锁存的 `mret_q`**——组合版 `is_mret_q`
  //   跟着"当前 `rbuf[0]`"走，提交拍那一条已经出队、`rbuf[0]` 可能是**下一条**（实测：
  //   `CSRRW x0,mepc` 提交拍正好把 MRET 排到 `rbuf[0]` ⇒ 误触发 MRET 返回、用**旧** `mepc`
  //   重定向回去，形成 trap-回跳死循环）
  assign ret_commit  = rob_commit_vld && mret_q;

  // GPR 写口（架构态）：`rd_wb_en` 已在 M15 按 `dst_kind≠00` ∧ 非异常条目收口
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int unsigned i = 0; i < 32; i++) gpr[i] <= 64'd0;
    end else if (rob_commit_vld && rob_commit.rd_en && (rob_commit.rd_paddr[4:0] != 5'd0)) begin
      gpr[rob_commit.rd_paddr[4:0]] <= rob_data;
    end
  end

  // 重定向/冲刷（提交拍一拍脉冲；`spec/01` §5.2 逐级动作的一次性施加）
  assign br_redirect_v  = rob_commit_vld && br_pend_v && br_pend_mispred && !excp_commit;
  assign br_redirect_pc = br_pend_taken ? br_pend_target : (br_pend_pc + 40'd4);

  assign redirect_vld = trap_redirect_v || br_redirect_v;
  assign redirect_pc  = trap_redirect_v ? trap_redirect_pc : br_redirect_pc;
  assign flush_all    = redirect_vld;

  // -------------------------------------------------------------------------
  // 提交/退休观察点（`spec/01` §6 端口；§3.21 `rt_t` 由 M15 在 `CT` 授权拍产出）
  // -------------------------------------------------------------------------
  assign commit_valid = rob_commit_vld;
  assign rt_valid_o   = rob_commit_vld;
  assign rt_o         = rob_rt;
  assign csr_wr_valid = csr_wr.vld;

  // -------------------------------------------------------------------------
  // 内部状态：GPR（架构寄存器堆，单发射 in-order ⇒ 与 PRF 等价）、拍计数、μop 序号、
  //   简单单元（BRU/CSR/pre_exc）的在途结果、分支解析采样、R 缓冲与提交侧锁存
  // -------------------------------------------------------------------------
  // 简单单元在途（次拍完成：BRU 组合解析、CSR 读、非法编码）；`mret_q`＝提交拍消费的 MRET 标记
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cycle_q         <= 64'd0;
      seq_q           <= 12'd0;
      for (int unsigned k = 0; k < DECODE_WIDTH; k++) rbuf[k] <= '0;
      rbuf_cnt        <= 3'd0;
      pend_q          <= 1'b0;
      pend_data_q     <= 64'd0;
      pend_csr_v_q    <= 1'b0;
      pend_csr_src_q  <= 64'd0;
      pend_csr_old_q  <= 64'd0;
      pend_is_br_q    <= 1'b0;
      pend_mispred_q  <= 1'b0;
      pend_exc_v_q    <= 1'b0;
      pend_exc_code_q <= 4'd0;
      pend_tval_q     <= 40'd0;
      mret_q          <= 1'b0;
      br_pend_v       <= 1'b0;
      br_pend_taken   <= 1'b0;
      br_pend_mispred <= 1'b0;
      br_pend_target  <= 40'd0;
      br_pend_pc      <= 40'd0;
    end else begin
      cycle_q <= cycle_q + 64'd1;

      // ---- R 缓冲：冲刷清零 / 出队下移 / 整组收入 ----
      if (flush_all) begin
        rbuf_cnt <= 3'd0;
      end else if (disp_fire) begin
        for (int unsigned k = 0; k < DECODE_WIDTH; k++)
          rbuf[k] <= (k == DECODE_WIDTH-1) ? '0 : rbuf[k+1];
        rbuf_cnt <= rbuf_cnt - 3'd1;
      end else if (accept_grp) begin
        for (int unsigned k = 0; k < DECODE_WIDTH; k++) rbuf[k] <= map_uop(dec_uop[k]);
        rbuf_cnt <= grp_n;
      end

      // ---- S 拍分配：全局 μop 序号自增（§3.6 `seq` 产生点）----
      if (disp_fire) seq_q <= seq_q + 12'd1;

      // ---- S/W 拍锁存：提交拍（次拍起）消费的随流信息 ----
      if (disp_fire) begin
        mret_q <= is_mret_q;
        if (is_br_q) begin
          br_pend_v       <= 1'b1;
          br_pend_taken   <= br_res.taken_real;
          br_pend_mispred <= br_res.mispred;
          br_pend_target  <= br_res.target_real;
          br_pend_pc      <= head.pc;
        end
        if (is_br_q || is_csr_q || is_mret_q || is_fence_q || is_none_q) begin
          // 简单单元：次拍完成（BRU 组合解析 / CSR 组合读 / FENCE 无副作用完成 / 非法编码无需结果）
          pend_q          <= 1'b1;
          pend_data_q     <= is_csr_q ? csr_rdata          // CSR 旧值 → `rd_data`（§4.3 类③）
                           : is_br_q  ? (head.pc + 40'd4)  // `JAL`/`JALR` 链接＝`pc+4`（M10 `wb_t` TODO 的替代）
                           : 64'd0;                        // FENCE/FENCE.I：无目的、无数据
          pend_csr_v_q    <= is_csr_q;
          pend_csr_src_q  <= is_csr_q ? rs1_val : 64'd0;   // `csr_wr_t.wdata`（§3.19 规则 2）
          pend_csr_old_q  <= is_csr_q ? csr_rdata : 64'd0; // §3.21③（`csrq` 队头的首版等价物）
          pend_is_br_q    <= is_br_q;
          pend_mispred_q  <= is_br_q ? br_res.mispred : 1'b0;
          // `is_none_q` ⇒ 非法编码：`D` 级对 57 条以外一律 `pre_exc=1`/code 2（见 `vr1_decode`）
          //   文件头"首版子集口径"）⇒ 一律按异常条目提交（无副作用、不产假语义）
          pend_exc_v_q    <= is_none_q;
          pend_exc_code_q <= head.pre_exc_code;
          pend_tval_q     <= is_none_q ? {8'b0, head.raw32} : 40'd0;  // 非法指令回填指令位（§4.1）
        end
      end
      if (pend_q && wb_vld) pend_q <= 1'b0;      // 完成拍释放
      if (flush_all) begin
        pend_q    <= 1'b0;
        br_pend_v <= 1'b0;
      end
    end
  end

  // -------------------------------------------------------------------------
  // WB 拍：完成回报选择（EXU / LSU / 简单单元）——三条互斥（在飞 μop 恒 1 条）
  // -------------------------------------------------------------------------
  always_comb begin
    wb_rd_data    = 64'd0;
    wb_exc_v      = 1'b0;
    wb_exc_code   = 4'd0;
    wb_tval       = 40'd0;
    wb_mem_v      = 1'b0;
    wb_mem_addr   = 40'd0;
    wb_mem_wdata  = 64'd0;
    wb_mem_rdata  = 64'd0;
    wb_mem_size   = 2'd0;
    wb_mem_wr     = 1'b0;
    wb_csr_v      = 1'b0;
    wb_csr_src    = 64'd0;
    wb_csr_old    = 64'd0;
    wb_is_br      = 1'b0;
    wb_mispred    = 1'b0;
    wb_vld        = xc.vld || lsc.vld || pend_q;

    if (xc.vld) begin
      wb_rd_data = xc.data;                       // §3.20 `x_complete_t`
    end else if (lsc.vld) begin
      wb_rd_data   = lsu_ld_data;                 // load 数据（store 时无意义）
      wb_mem_v     = lsu_mem_v;                   // §3.21② 观测面（无 fault 才有访存事件）
      wb_mem_addr  = lsu_mem_addr;
      wb_mem_wdata = lsu_mem_wdata;
      wb_mem_rdata = lsu_mem_rdata;
      wb_mem_size  = lsu_mem_size;
      wb_mem_wr    = lsu_mem_wr;
      wb_exc_v     = (lsc.fault != 2'b00);        // 非对齐（`MISALIGNED_EN=0`，码 4/6）
      wb_exc_code  = lsc.code;
      wb_tval      = lsu_tval;
    end else if (pend_q) begin
      wb_rd_data   = pend_data_q;
      wb_csr_v     = pend_csr_v_q;
      wb_csr_src   = pend_csr_src_q;
      wb_csr_old   = pend_csr_old_q;
      wb_is_br     = pend_is_br_q;
      wb_mispred   = pend_mispred_q;
      wb_exc_v     = pend_exc_v_q;
      wb_exc_code  = pend_exc_code_q;
      wb_tval      = pend_tval_q;
    end
  end

  // -------------------------------------------------------------------------
  // 本批**不消费**的面（如实列出，防"看起来全接了"的误读）：
  //   · `rt_ready`（§6 端口）：TB 侧 `rt_t_trace_writer` 是**零延迟纯监视器**（落盘即时、不倒逼
  //     DUT）⇒ 首版 `commit_ack` 恒 1、不接反压；真实反压语义随 M15/RT 级 —— TODO(M1-S4)；
  //   · `csr_mcause`/`csr_mtval`/`csr_mscratch`（M17 输出）：供 `spec/10` 的 CSR 观察面/后续断言，
  //     本批无消费端（`rt_t` 无 `mcause`/`mtval` 列）⇒ 显式列出，不接假负载；
  //   · `br_res.rob_id`/`ckpt_id`/`ftq_id` 等随流字段：单条在飞 ⇒ 提交拍不需要（`ftq_id` 由 ROB
  //     条目自带，§3.17）。
  // 证据行**一律 ASCII**：ModelSim 控制台把非 ASCII 替换为 `?`（实测），中文注释不进口志。
  // -------------------------------------------------------------------------
  // synopsys translate_off
  initial $display("[vr1_core] M1-S3b + M2 + M3-(d): backend landed (M06 identity rename -> M15 single-in-flight ROB/commit/rt_t -> M16 commit side effects -> M09 EXU / M10 BRU(6 br + JAL/JALR) / M11 LSU(7 ld + 4 st) / M17 CSR / M18 TRAP / FENCE-FENCEI as no-op); multi-issue, IQ, PRF/RAT, LQ/SQ, cache/MMU, interrupts NOT implemented (TODOs in header)");
  // synopsys translate_on

endmodule

`endif // VR1_CORE_SV
