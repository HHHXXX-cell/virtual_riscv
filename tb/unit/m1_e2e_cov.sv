// ==========================================================================
// tb/unit/m1_e2e_cov.sv — VR1 **首批功能覆盖模型（covergroup）与 SVA 断言**（TB 侧，纯监视器）
//
// 它是什么（红线 R6/R8：本件**只观测**，不产"通过"结论、不驱动 DUT）：
//   · **功能覆盖模型**（`covergroup`，显式 `sample()`）：把 `doc/verify/02-验证点清单.md`（VP 清单）
//     里**已明确**的检查面落成可机读的 bin —— 消费方＝`run_cmd/cover_rv1.py` 的 `-cvg` 面
//     （`doc/verify/07-<batch>.txt`§A）。**验证点只取自 VP 清单，不自造**（每条 bin 的注释给 VP 号）。
//   · **SVA 断言**（并发断言，逐条 `disable iff`）：落 `doc/spec/11-SVA与lint规则.md` **已明确的规则**
//     （§3 的 L-03 显式时序窗口／L-06 复位语义／L-07 禁止项）与 VP 清单里**已写成不变式**的面。
//     每条断言的注释给「`spec/11` 规则号（或 A 系列编号状态）＋ VP 号」。
//
// 落点与**为什么不 bind**（如实登记，依据可复核）：
//   · 任务口径首选"TB 侧 ＋ `bind` 挂 DUT"；本条**未用 `bind`**，因为实测（2026-09-26 心跳第 8 轮，
//     一次性探针已随沙箱清理）**任何形式的 `bind` 都会让 vlog 多出一行
//     `-- Compiling package <名>_sv_unit`**（含只放一行 `bind` 的文件）⇒ `-- Compiling` 计数 ==
//     清单条目数 的**两条在跑判据**（`script/flow.py` 的 `m2-rv64ui`／`rtl-vs-iss`）与覆盖率/回归
//     runner 的同一不变式（`run_cmd/regress_rv1.py:compile_design`）会 fail-closed 报错。
//     **复现法**（≤2 分钟）：把任一含 `bind` 的文件加进编译集，`vlog -64 -sv -cover bcesf …` 的输出
//     即多一行上述 `-- Compiling package`。**判据本体一字未动**（硬约束）⇒ 改用**等价观测面**：
//     本模块由 `tb/unit/m1_e2e_tb.sv` 例化，采样口＝DUT 端口 ＋ 该 TB 既有的层次化探针写法
//     （`m1_e2e_tb.sv` 的 `+DBG` 段同款）；**不改冻结端口面、不改 RTL 内部逻辑**，
//     本文件在 `filelist/tb_m1_e2e.f` 里按序追加（清单条目数与计数不变式同步）。
//   · `spec/11` §2 的要求（**非 DUT 端口名必须显式标注"TB 从采样口构造"**）：本模块端口中标注
//     `[内部采样口]` 者即此类（DUT 内部信号，TB 以层次化路径接入，见例化点的实参注释）。
//
// 覆盖模型清单（第一批；每条给 VP 出处与落点依据）
//   CG1 `cg_retire`   —— VP-01（F-01 RV64I 逐条语义）／VP-22（F-22 提交：提交序与 trace 字段）／
//                        VP-05（F-05 Zicsr：CSR 读回）／VP-08＋VP-X02（异常条目）
//   CG2 `cg_fetch`    —— VP-16（F-16 取指/IBUF：协议交互序列）／VP-32（F-32：`RESET_PC` 首条取指）
//   CG3 `cg_lsu_fsm`  —— VP-27（F-27 LQ/SQ/转发）／VP-24（F-24 反压与死锁）／VP-09（F-09 非对齐）
//
// 断言清单（第一批；每条给 `spec/11` 规则号 ＋ VP 号；`spec/11` §1 的 A1~A19 面向 free-list/RAT/
//   `csrq`/checkpoint 等**尚未实现**的机制（该篇 §1 归属面逐行可核）⇒ 本批**一条都落不了**，
//   按"不新造语义、不改判据强度"（`spec/11` 篇首②）**不假落**；留 `TODO(M2-c-2)` 待机制在环后按
//   `spec/11` §1 逐条落（A20 为候选，见该篇 T-11-1）：
//     A1（本文件）复位可见态：`spec/11` L-06 ＋ VP-32；A2 首个取指请求 VA：VP-32 ＋ `spec/00` §4.1；
//     A3 `rd=x0` 不写回：`spec/02` §4.1 SI-1 ＋ VP-18；A4 异常码非 0：VP-X02 ＋ `spec/10` §2.1；
//     A5 内存类发射需 LSU 空闲：VP-24／VP-27（`vr1_lsu.sv` 文件头不变量①）；
//     A6 非对齐不发访存请求：VP-09（同上不变量②，负向核对）。
//
// 口径与纪律（**不得违反**）：
//   · 红线 R7：本件**不设 waiver/exclude**；未命中的 bin 一律**原样保留**（它们是**真实覆盖缺口**，
//     例如单特权级下的 U 态 bin、尚未有定向激励的异常 bin —— 详见各 bin 注释）；
//     "覆盖率阈值"归 M3/签核（`AGENTS.md` §4），本批只要求**机制在环**。
//   · `spec/11` L-02：不用 1800-2023 新特性（无 `default disable iff`，逐条显式 `disable iff`）。
//   · `spec/11` L-03：时序窗口显式（本批断言无 `##` 延迟序列）。
//   · 写边界：本件只读 DUT（纯输入端口），**无输出、无 `force`**。
//
// 依据：`doc/verify/02-验证点清单.md`（VP-01/05/08/09/16/18/22/24/27/32、VP-X02）；
//       `doc/spec/11-SVA与lint规则.md`（§1 编号面、§2 绑定口径、§3 L-02/L-03/L-06/L-07、§5 T-11-x）；
//       `doc/spec/00` §4.1（`RESET_PC`）；`doc/spec/01` §3.13/§3.16/§3.21；`doc/spec/10` §2.1。
//
// TODO（如实登记；做不通的不硬做、不堆无意义 cover —— 红线 R7）
//   · TODO(M2-c-2-a)：`spec/11` §1 的 A1~A19 全部**待机制在环**（free-list/RAT/PRF/`csrq`/
//     checkpoint/多发射冲刷面 —— 均为 `doc/spec/01` §5／`G1-I` 清单 §3 的延后类）；
//   · TODO(M2-c-2-b)：CG1 的 `cp_exc`／CG3 的三个未命中迁移／`cp_priv` 的 U 态 bin ⇒ 需要
//     **定向激励**（VP-09／VP-X02／VP-07 的定向用例、复位在途指令的复位注入），属 M3 用例批；
//     **不是**覆盖模型能补的（覆盖模型只观测已产生的激励）；
//   · TODO(M2-c-2-c)：CG3 的状态编码取自 `rtl/vr1/lsu/vr1_lsu.sv` 的 `lsu_state_e` 声明序
//     （`L_IDLE/L_REQ/L_RSP/L_DONE` = 0/1/2/3）；若该 enum 重排，本件须同步（**同源耦合已声明**）。
// ==========================================================================
`ifndef M1_E2E_COV_SV
`define M1_E2E_COV_SV

module m1_e2e_cov #(
  // 与 `sw/env/link.ld`／TB `TOHOST_ADDR` 同源（`spec/01` §3.16 停机观测面）
  parameter logic [39:0] TOHOST_ADDR = 40'h00_4000_0010
) (
  input logic clk,
  input logic rst_n,

  // ---- 提交/退休观察点（**DUT 冻结端口**：`rt_valid_o` / `rt_o`；`spec/01` §3.17/§3.21）----
  // 注：struct 型输入端口一律带 `var`（与 `vr1_core.sv` 的端口写法同款）——不加会触发
  //     vlog/vopt 的 `13314 Defaulting port kind to 'var'` 警告（实测；警告非错误，但保持零噪声）
  input logic                rt_valid,        // = vr1_core.rt_valid_o
  input var vr1_pkg::rt_t    rt,              // = vr1_core.rt_o
  input logic                commit_valid,    // = vr1_core.commit_valid

  // ---- 取指侧（**DUT 冻结端口**：`spec/01` §3.13/§3.16）----
  input logic                imem_req_valid,
  input var vr1_pkg::mem_req_t imem_req,
  input logic                imem_req_ready,
  input logic                imem_rsp_valid,
  input logic                imem_rsp_ready,

  // ---- 访存侧（**DUT 冻结端口**）----
  input logic                dmem_req_valid,
  input var vr1_pkg::mem_req_t dmem_req,
  input logic                dmem_rsp_valid,
  input logic                dmem_rsp_ready,

  // ---- [内部采样口] DUT 内部信号（TB 从层次化路径构造；`spec/11` §2 声明口径）----
  input logic [1:0]          lsu_state,       // = u_dut.u_lsu.state_q（编码见 TODO(M2-c-2-c)）
  input logic                lsu_fault,       // = u_dut.u_lsu.fault_q（非对齐 fault 判决位）
  input logic                disp_fire,       // = u_dut.disp_fire（S 拍发射）
  input logic                disp_is_mem      // = u_dut.is_mem_q（发射条目的访存类）
);

  import vr1_pkg::*;

  // -------------------------------------------------------------------------
  // 常量（**只引用、不另赋值**：`spec/00` §4 是数值唯一权威源）
  // -------------------------------------------------------------------------
  // `RESET_PC` 取自 `vr1_pkg`（＝`spec/00` §4.1 的生成件），本件不写死 0x1000（`spec/11` L-05）
  localparam logic [39:0] RESET_PC_40 = RESET_PC[39:0];

  // LSU 状态编码：**与 `rtl/vr1/lsu/vr1_lsu.sv` 的 `lsu_state_e` 声明序逐字对应**（见 TODO(M2-c-2-c)）
  localparam logic [1:0] L_IDLE = 2'd0, L_REQ = 2'd1, L_RSP = 2'd2, L_DONE = 2'd3;

  // 采样辅助变量（**先声明后使用**：covergroup 的 coverpoint 表达式在 `new` 时解析）
  logic first_req_va_ok;         // CG2 的 `cp_first_pc` 采样变量（首请求 VA 判定）
  logic seen_req_q;              // 是否已接受过取指请求（复位期不计，防"复位窗吃掉首请求"）

  // =========================================================================
  // CG1 `cg_retire` —— 退休（提交）面功能覆盖（VP-01 / VP-05 / VP-08 / VP-22 / VP-X02）
  //   采样条件：**提交拍**（`rt_valid`；`rt_o.valid` 与该信号同源，见 `vr1_core.sv` 的
  //   `assign rt_valid_o = rob_commit_vld;`）⇒ 每一 bin 的命中数＝该类退休指令的**条数**
  //   （可直接与 VP-22 的"trace 字段逐条比对"条数对照，不产任何判据）。
  // =========================================================================
  covergroup cg_retire;
    option.per_instance = 1;

    // VP-01（F-01 RV64I 63 条）：退休指令的 **opcode 类**（按 `spec/02` §9.1 的编码面分组，
    //   与 `rtl/vr1/ctrl/vr1_decode.sv` 的 `OPC_*` 逐条对应；`unimp`（7'b1111111）在
    //   `RVTEST_CODE_END` 里、恒在 tohost 停机之后 ⇒ 不该退休，故落 `op_other` 负向 bin）
    cp_op: coverpoint rt.instr[6:0] {
      bins op_lui     = {7'b0110111};   // LUI
      bins op_auipc   = {7'b0010111};   // AUIPC
      bins op_jal     = {7'b1101111};   // JAL
      bins op_branch  = {7'b1100011};   // BEQ/BNE（BLT/BGE 族不在 RTL 子集内）
      bins op_load    = {7'b0000011};   // LW
      bins op_store   = {7'b0100011};   // SW
      bins op_opimm   = {7'b0010011};   // ADDI 族
      bins op_op      = {7'b0110011};   // ADD 族 + M（MUL/DIV/REM）
      bins op_opimm32 = {7'b0011011};   // ADDIW 族
      bins op_op32    = {7'b0111011};   // ADDW 族
      bins op_system  = {7'b1110011};   // CSRRW/CSRRS/MRET
      bins op_other   = default;        // **负向 bin**：不得退休的编码（含 unimp）
    }

    // VP-01：`funct3` 全 8 值（8 bins；与 opcode 面正交，覆盖三操作数类的低位分组）
    cp_f3: coverpoint rt.instr[14:12];

    // VP-22（提交）：`rd` 写回面（`rd_wb_en=0` ⇒ 无架构写；异常条目按 `spec/02` §19 抑制写）
    cp_wb: coverpoint rt.rd_wb_en {
      bins no_wb   = {1'b0};
      bins has_wb  = {1'b1};
    }

    // VP-27（访存面）/ VP-01：提交拍携带的访存观测面（`spec/01` §3.21②）
    cp_mem: coverpoint {rt.mem_v, rt.mem_wr} {
      bins no_mem   = {2'b00};
      bins load     = {2'b10};   // mem_v ∧ !mem_wr
      bins store    = {2'b11};   // mem_v ∧ mem_wr
    }

    // VP-05（F-05 Zicsr；`spec/10` §4.1 的 7 条 CSR）：退休条目携带的 CSR 地址面
    //   注：只对 CSR 类指令有意义，其余指令的该字段无语义（`csr_wr_en=0`），故另设 `default` bin
    cp_csr: coverpoint rt.csr_addr {
      bins csr_mstatus  = {12'h300};
      bins csr_misa     = {12'h301};
      bins csr_mtvec    = {12'h305};
      bins csr_mscratch = {12'h340};
      bins csr_mepc     = {12'h341};
      bins csr_mcause   = {12'h342};
      bins csr_mtval    = {12'h343};
      bins csr_other    = default;
    }

    // VP-08 / VP-X02（异常专项）：**异常提交面**（`spec/01` §3.21 的 `exc_v`/`exc_cause`）
    //   注：`exc_v=1` 的 bin 在本批 36 条全过用例下为 **0 命中**——这是**真实的覆盖缺口**
    //   （异常触发点属 VP-X02 的定向用例，见 TODO(M2-c-2-b)），**不 waiver、不移除**（红线 R7）
    cp_exc: coverpoint rt.exc_v {
      bins no_exc = {1'b0};
      bins exc    = {1'b1};
    }

    // VP-07 前置 / VP-32：退休特权级（一期单特权级 M ⇒ `priv_u` 为**登记在册的缺口**）
    cp_priv: coverpoint rt.priv {
      bins priv_u = {2'b00};
      bins priv_m = {2'b11};
    }
  endgroup

  // =========================================================================
  // CG2 `cg_fetch` —— 取指协议交互面（VP-16 / VP-32；`spec/01` §3.13/§3.16）
  //   采样条件：每个时钟沿（协议面是**逐拍**的，见 VP-16「协议交互序列」）
  // =========================================================================
  covergroup cg_fetch;
    option.per_instance = 1;

    // VP-16：取指请求握手（`imem_req_valid` × `imem_req_ready`）——`10` 为"请求未被接受"
    cp_req_hs: coverpoint {imem_req_valid, imem_req_ready} {
      bins idle      = {2'b00};
      bins req_wait  = {2'b10};
      bins req_bite  = {2'b11};
    }

    // VP-16：取指响应握手（"保持到被接受"语义的观测面；`imem_rsp_ready` 由 DUT 给出）
    cp_rsp_hs: coverpoint {imem_rsp_valid, imem_rsp_ready} {
      bins idle      = {2'b00};
      bins rsp_wait  = {2'b10};
      bins rsp_bite  = {2'b11};
    }

    // VP-32（F-32 时钟复位）：**复位释放后首个被接受的取指请求**地址面
    //   判据来源：`RESET_PC`＝首条取指地址（`spec/00` §4.1；G1-I 清单 §1.2 第 10 条）
    cp_first_pc: coverpoint first_req_va_ok {
      bins first_is_reset_pc = {1'b1};
      bins later_or_other    = {1'b0};
    }
  endgroup

  // =========================================================================
  // CG3 `cg_lsu_fsm` —— LSU 状态×事件面（VP-09 / VP-24 / VP-27）
  //   采样条件：每个时钟沿；状态编码单源＝`vr1_lsu.sv` 的 `lsu_state_e`（见 TODO(M2-c-2-c)）
  //   **为什么立这条**：`doc/verify/07-m2cov_r1.txt` 的代码覆盖薄弱面之一是
  //   `vr1_lsu` 的 FSM Transitions 5/8；本模型把**同一批迁移**以功能面复述，使"迁移未命中"
  //   在 `-cvg` 面同样可见（两口径互为交叉印证，**不改任何阈值**）
  // =========================================================================
  covergroup cg_lsu_fsm;
    option.per_instance = 1;

    cp_state: coverpoint lsu_state {
      bins s_idle = {L_IDLE};
      bins s_req  = {L_REQ};
      bins s_rsp  = {L_RSP};
      bins s_done = {L_DONE};
    }

    // 与 `vr1_lsu.sv` 的 8 条迁移一一对应（未命中者＝真实缺口，见 TODO(M2-c-2-b)）
    cp_trans: coverpoint lsu_state {
      bins t_idle_req  = (L_IDLE => L_REQ);    // 就绪请求：进请求拍
      bins t_idle_done = (L_IDLE => L_DONE);   // 非对齐：不发请求直接报 fault（VP-09，本批 0 命中）
      bins t_req_rsp   = (L_REQ  => L_RSP);    // load：请求被接受，等响应
      bins t_req_done  = (L_REQ  => L_DONE);   // store：请求被接受即完成
      bins t_req_idle  = (L_REQ  => L_IDLE);   // 复位落在请求拍（本批 0 命中：复位只在 t=0）
      bins t_rsp_done  = (L_RSP  => L_DONE);   // load 响应到达
      bins t_rsp_idle  = (L_RSP  => L_IDLE);   // 复位落在响应拍（同上）
      bins t_done_idle = (L_DONE => L_IDLE);   // 完成脉冲恰一拍
    }
  endgroup

  // -------------------------------------------------------------------------
  // 采样（`spec/11` L-03：采样点显式；不复用隐式 `@(posedge clk)` 事件，便于逐条读条件）
  // -------------------------------------------------------------------------
  cg_retire  cg_retire_i  = new;
  cg_fetch   cg_fetch_i   = new;
  cg_lsu_fsm cg_lsu_fsm_i = new;

  // 首个被接受的取指请求：VA == `RESET_PC` ⇒ 1；此后（或尚未出现首个请求）⇒ 0
  assign first_req_va_ok = (!seen_req_q && imem_req_valid && imem_req_ready)
                           ? (imem_req.va == RESET_PC_40) : 1'b0;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) seen_req_q <= 1'b0;
    else if (imem_req_valid && imem_req_ready) seen_req_q <= 1'b1;
  end

  always @(posedge clk) begin
    if (rst_n) begin
      if (rt_valid) cg_retire_i.sample();       // 提交拍（VP-22）
      cg_fetch_i.sample();                      // 逐拍（VP-16 协议面）
      cg_lsu_fsm_i.sample();                    // 逐拍（VP-09/VP-24/VP-27）
    end
  end

  // -------------------------------------------------------------------------
  // SVA 断言（第一批；逐条给「`spec/11` 规则号／A 系列状态 ＋ VP 号」）
  // -------------------------------------------------------------------------
  // A1（VP-32／`spec/11` §3 L-06「复位语义」）：**复位期间**提交/访存可见态必须为 0
  //   —— 复位"异步复位、同步释放"在本版由 TB 的 `rst_n` 承担（`spec/00` §4.7）；
  //   `rt_valid_o`/`commit_valid` 由 `vr1_rob` 的 `entry_q.v`（复位值 0）导出，
  //   `dmem_req_valid` 由 `vr1_lsu` 的 `state_q`（复位值 `L_IDLE`）导出。
  a1_reset_visible_zero: assert property (
      @(posedge clk) (!rst_n) |-> (!rt_valid && !commit_valid && !dmem_req_valid))
    else $error("[m1_e2e_cov] A1 违例：复位期间提交/访存可见态非 0（spec/11 L-06 / VP-32）");

  // A2（VP-32；`spec/00` §4.1 `RESET_PC`）：**复位释放后首个被接受的取指请求** VA == `RESET_PC`
  //   注：`seen_req_q` 只在复位释放后置位（复位期的请求不吞掉"首个"）
  a2_first_fetch_reset_pc: assert property (
      @(posedge clk) disable iff (!rst_n)
      (!seen_req_q && imem_req_valid && imem_req_ready) |-> (imem_req.va == RESET_PC_40))
    else $error("[m1_e2e_cov] A2 违例：复位后首个取指请求 VA ≠ RESET_PC（VP-32）");

  // A3（VP-18「x0 不分配」；依据 `spec/02` §4.1 **SI-1**：任何 `rd=x0` 的 μop ⇒ `dst_kind=00`）：
  //   退休条目的写回使能 ⇒ `rd_idx ≠ 0`
  a3_x0_no_wb: assert property (
      @(posedge clk) disable iff (!rst_n)
      (rt_valid && rt.rd_wb_en) |-> (rt.rd_idx != 5'd0))
    else $error("[m1_e2e_cov] A3 违例：rd=x0 却带写回使能（spec/02 §4.1 SI-1 / VP-18）");

  // A4（VP-X02 的"不得产生"负向核对；`spec/10` §2.1）：异常条目的 `mcause` **不得为 0**
  //   （码 0 因 `IALIGN=16` 不可产生 —— `doc/verify/02` VP-08/VP-X02 行同款口径）
  a4_exc_cause_nonzero: assert property (
      @(posedge clk) disable iff (!rst_n)
      (rt_valid && rt.exc_v) |-> (rt.exc_cause != 4'd0))
    else $error("[m1_e2e_cov] A4 违例：异常条目 cause=0（VP-X02 / spec/10 §2.1）");

  // A5（VP-24 反压／VP-27；依据 `vr1_lsu.sv` 文件头不变量①「在飞访存恒 ≤1」）：
  //   **访存类**发射（`disp_fire ∧ is_mem`）时 LSU 必须处于 IDLE
  a5_disp_mem_needs_idle_lsu: assert property (
      @(posedge clk) disable iff (!rst_n)
      (disp_fire && disp_is_mem) |-> (lsu_state == L_IDLE))
    else $error("[m1_e2e_cov] A5 违例：LSU 非空闲却发射访存类 μop（VP-24／vr1_lsu 不变量①）");

  // A6（VP-09；`vr1_lsu.sv` 文件头不变量②「非对齐请求**不产生** `dmem_req_valid_o`」）：
  //   非对齐 fault 判决置位 ⇒ 不得进入请求拍（即不得发访存请求）——**负向核对**
  //   注：本批 36 条全过用例**无一条**触发非对齐（`MISALIGNED_EN=0`，见 `doc/process/00` ISS-010）
  //   ⇒ 本断言在此批为**未被激励**状态；属 TODO(M2-c-2-b) 的定向用例面
  a6_misalign_no_dmem_req: assert property (
      @(posedge clk) disable iff (!rst_n)
      (lsu_fault) |-> ((lsu_state != L_REQ) && !dmem_req_valid))
    else $error("[m1_e2e_cov] A6 违例：非对齐 fault 却发出访存请求（VP-09／vr1_lsu 不变量②）");

endmodule

`endif // M1_E2E_COV_SV
