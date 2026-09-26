// ==========================================================================
// rtl/vr1/ctrl/vr1_csr.sv — M17 CSR 单元（六件 ＋ trap 进场 6 动作 ＋ `MRET` 返回动作）
//
// 状态（不得误读，红线 R8）：
//   · 本模块**已实现**（M1-S3 第二批，G1-I 一期口径）：
//     ① **六个 CSR**（`mtvec`/`mepc`/`mscratch`/`mcause`/`mtval`/`mstatus`）读口（组合、零副作用）
//        ＋ 提交拍写口（`spec/01` §3.19 `csr_wr_t`：`RW`/`RS`/`RC` 三型 ＋ 「源为 0 不写」收口）；
//     ② **trap 进场 6 动作**（`spec/10` §2：`mepc ← 触发 pc`、`mcause ← 码`、`mtval ← 触发信息`、
//        `MPIE ← MIE`、`MIE ← 0`、`MPP ← 前级`）——本版单特权级（`priv` 恒 M，清单 §2.6）；
//     ③ **`MRET` 返回动作**（`spec/10` §2：`MIE ← MPIE`、`MPIE ← 1`、`MPP ← 最低可用模式(U)`、
//        `MPP≠M ⇒ 清 MPRV`；返回 `pc = mepc` 由 `vr1_trap` 按 `ret_ctrl_t.epc` 重定向）；
//     ④ `csr_new_o`/`csr_wr_en_o`（`rt_t.csr_new`/`csr_wr_en` 的唯一来源：**写后新值**，
//        `doc/process/00` ISS-013）。
//   · 本模块**未实现**（逐条给出口，不写"看起来对"的逻辑）：
//     - **CSR 全表**（`spec/10` §4.1 的 S 侧 ＋ `misa` 之外的 M 侧 ＋ PMP/计数器）：不在
//       G1-I 六件内（清单 §1.1）⇒ 未列地址**读 0、写忽略**（与 ISS 现行字典默认行为一致，
//       以便 M1 逐指令比对；`spec/10` §4.2 的 illegal 口径随全表落地）—— TODO(G1-F)；
//     - **S 态委托**（`medeleg`/`mideleg`/`stvec`/`sepc`…）：一期无 S 态（`spec/10` §3
//       ISS 也不实现委托）⇒ 不实现 —— TODO(G1-F)；
//     - **WARL 掩码的两处**：`mtvec.MODE ≥ 2 保旧值`、`mepc[0]/[1] 恒 0`（`spec/10` §4.1／
//       `spec/01` §3.18 Q30）**未施加** —— 与 ISS 现行实现（`machine.py:csr_write` 直存）
//       同口径以保证 M1 逐指令比对；两处属「spec 与 ISS 分歧」，已按 `AGENTS.md` 尾注
//       登记为**过渡态临时裁定**，待 spec/10 与 ISS 对齐后收口 —— TODO(G1-F)；
//     - **读副作用/`rd=x0` 的「不读」**：`spec/10` §4.3 T-10-6 只影响副作用面，本六件**零副作用**
//       ⇒ 本版恒读（`CSRRW rd=x0` 的 rd 面由 D 级 SI-1 收口，§4.1）；
//     - **CSR 写队列 `csrq`（8 项）与 §3.19 五条硬规则**：首版单发射单提交（计划 §2.3 简化 #1）
//       ⇒ 提交拍直写、无队列（冲刷作废/命中失败/抑制写三规则**构造上不可达**）—— TODO(M1-S3)。
//
// 依据（逐条可核）：
//   · doc/spec/01 §3.19 `csr_wr_t`（`vld`/`addr`/`op`/`wdata_sel`/`wdata`）／§3.18 `ret_ctrl_t`；
//     §3.21 `rt_t.csr_addr/csr_old/csr_new/csr_wr_en`；§7 A16（CSR 写观察点）;
//   · doc/spec/10 §2（trap 进场/返回动作逐条）／§4.1（六件复位值与位段：`mtvec`=0、`mepc`=0、
//     `mscratch` 全 64 R/W、`mcause` WLRL、`mtval` 可写、`mstatus` WARL 最小集）／§4.3 T-10-6；
//   · doc/spec/02 §9.1.7（CSRRW/CSRRS）／§4.3 类③（CSR 逐条读写规则）；
//   · doc/decisions/G1-I-最小冻结清单.md §1.1（六件 CSR）／§2.6（单特权级、恒 0 表）。
//
// 写授权：`state/freeze.json` 的 rtl_write_authorized=true（R0 2026-09-25 签署 G1-I 的人令）。
// ==========================================================================
`ifndef VR1_CSR_SV
`define VR1_CSR_SV

module vr1_csr
  import vr1_pkg::*;
(
  input  logic        clk,
  input  logic        rst_n,

  // ---- 读口（`E` 级投机读；组合、零副作用，`spec/10` §4.3）----
  input  logic [11:0] csr_addr_i,
  output logic [63:0] csr_rdata_o,

  // ---- 写口（提交拍；`spec/01` §3.19 `csr_wr_t`）----
  input  var vr1_pkg::csr_wr_t csr_wr_i,
  output logic [63:0] csr_new_o,       // 写后新值（`rt_t.csr_new`；ISS-013 口径）
  output logic        csr_wr_en_o,     // 实际写使能（`RS`/`RC` 源为 0 ⇒ 0）

  // ---- trap 进场（提交拍；`excp_vld=1` 的条目提交，`spec/10` §2）----
  input  logic        excp_commit_i,
  input  logic [39:0] excp_epc_i,      // 触发指令 pc（ROB 头条目 `pc`，§3.18 `epc`）
  input  logic [3:0]  excp_cause_i,    // `spec/10` §2.1 码
  input  logic        excp_is_intr_i,  // 中断位（与码拆开承载，§2.1 口径）
  input  logic [39:0] excp_tval_i,     // 触发信息（本版：非对齐 VA／非法指令字）
  input  logic [1:0]  excp_from_i,     // 触发时特权级（本版恒 M）

  // ---- `MRET` 返回（提交拍）----
  input  logic        ret_commit_i,
  output vr1_pkg::ret_ctrl_t ret_o,    // §3.18（生产点＝本模块提交拍组合输出）

  // ---- 现场输出（供 `vr1_trap` 组装 `excp_t`／算 `mtvec` 目标；不新增存储）----
  output logic [63:0] mtvec_o,
  output logic [63:0] mepc_o,
  output logic [63:0] mcause_o,
  output logic [63:0] mtval_o,
  output logic [63:0] mscratch_o,
  output logic [63:0] mstatus_o
);

  // -------------------------------------------------------------------------
  // 常量（地址取 `spec/10` §4.1 表；位段取 `spec/10` §4.1 ＋ `spec/01` §3.18）
  // -------------------------------------------------------------------------
  localparam logic [11:0] CSR_MSTATUS  = 12'h300;
  localparam logic [11:0] CSR_MISA     = 12'h301;
  localparam logic [11:0] CSR_MTVEC    = 12'h305;
  localparam logic [11:0] CSR_MSCRATCH = 12'h340;
  localparam logic [11:0] CSR_MEPC     = 12'h341;
  localparam logic [11:0] CSR_MCAUSE   = 12'h342;
  localparam logic [11:0] CSR_MTVAL    = 12'h343;

  // `mstatus` 位（`spec/10` §4.1：`MIE/MPIE/MPP/MPRV/SIE/SPIE/SPP/SUM/MXR/TVM/TW/TSR`＝R/W 最小集）
  localparam int unsigned MIE_B   = 3;
  localparam int unsigned MPIE_B  = 7;
  localparam int unsigned MPP_LO  = 11;
  localparam int unsigned MPRV_B  = 17;
  localparam logic [63:0] MSTATUS_WMASK = 64'h0000_0000_007E_19AA;
  // ↑ = SIE(1)｜MIE(3)｜SPIE(5)｜MPIE(7)｜SPP(8)｜MPP(12:11)｜MPRV(17)｜SUM(18)｜MXR(19)｜
  //   TVM(20)｜TW(21)｜TSR(22)（`spec/10` §4.1 最小集逐位相加；`FS/XS/SD` 恒 0、写忽略）

  localparam logic [1:0] PRV_M = 2'b11;
  localparam logic [1:0] PRV_U = 2'b00;               // 一期「最低可用模式」＝U（`spec/10` §4.1）

  // `csr_wr_t.op`（`spec/01` §3.19：00 RW／01 RS／10 RC／11 读使能-only）
  localparam logic [1:0] OP_RW = 2'b00, OP_RS = 2'b01, OP_RC = 2'b10;

  // -------------------------------------------------------------------------
  // 状态（六件 ＋ `misa` 只读常量）
  // -------------------------------------------------------------------------
  logic [63:0] mstatus_q, mtvec_q, mscratch_q, mepc_q, mcause_q, mtval_q;

  assign mtvec_o    = mtvec_q;
  assign mepc_o     = mepc_q;
  assign mcause_o   = mcause_q;
  assign mtval_o    = mtval_q;
  assign mscratch_o = mscratch_q;
  assign mstatus_o  = mstatus_q;

  // -------------------------------------------------------------------------
  // 读口（组合、零副作用）：六件 ＋ `misa`（只读常量，`spec/10` §4.1）；其余地址读 0
  //   注：写通路的"旧值"**也必须**按 `csr_wr_i.addr` 取（提交拍读口上的 `csr_addr_i` 可以是
  //   下一条 μop 的地址）⇒ 读逻辑收在一个函数里，读写两处共用同一真源（防两套 mux 漂移）
  // -------------------------------------------------------------------------
  // 注（2026-09-26 实测）：本条**用普通 `case` 而非 `unique case`** —— `unique` 版本在
  //   ModelSim vopt 下出现"读口不随寄存器更新"的观测异常（同拍 `csr_rd()` 直调正确、端口
  //   恒 0；见 `sim/run_m1_backend_smoke/run.log` 的 `[dbg]` 行）。语义等价（分支互斥且带
  //   `default`），换回 `unique` 需先证伪该观测异常。
  function automatic logic [63:0] csr_rd(input logic [11:0] a);
    case (a)
      CSR_MSTATUS:  csr_rd = mstatus_q;
      CSR_MISA:     csr_rd = MISA_VALUE;             // 只读常量（`spec/00` §4.7；写忽略）
      CSR_MTVEC:    csr_rd = mtvec_q;
      CSR_MSCRATCH: csr_rd = mscratch_q;
      CSR_MEPC:     csr_rd = mepc_q;
      CSR_MCAUSE:   csr_rd = mcause_q;
      CSR_MTVAL:    csr_rd = mtval_q;
      default:      csr_rd = 64'd0;                  // 未实现地址：TODO(G1-F)（全表＋illegal 口径）
    endcase
  endfunction

  // 读口用 `always_comb`（而非连续 `assign`）承载函数调用：让"函数体读到的寄存器"明确进入
  //   灵敏度面（连续 `assign` + 函数调用在 vopt 下的灵敏度推导曾出现上述观测异常）
  always_comb csr_rdata_o = csr_rd(csr_addr_i);

  // -------------------------------------------------------------------------
  // 写判决（组合）：`writes` 口径＝`spec/01` §3.19「`RW` 恒写；`RS`/`RC` 源非 0 才写」
  //   （`spec/02` §4.1 AN-07：CSRRS/CSRRC 且 rs1=x0 ⇒ 不写 CSR）
  // -------------------------------------------------------------------------
  logic        wr_writes;
  logic [63:0] wr_old;
  logic [63:0] wr_new;

  always_comb begin
    wr_old = csr_rd(csr_wr_i.addr);                    // 按**写口地址**取旧值（写前值）
    unique case (csr_wr_i.op)
      OP_RW:   wr_writes = 1'b1;
      OP_RS:   wr_writes = (csr_wr_i.wdata != 64'd0);
      OP_RC:   wr_writes = (csr_wr_i.wdata != 64'd0);
      default: wr_writes = 1'b0;                       // 11 读使能-only（本版 D 级不产生）
    endcase
    unique case (csr_wr_i.op)
      OP_RW:   wr_new = csr_wr_i.wdata;
      OP_RS:   wr_new = wr_old | csr_wr_i.wdata;
      OP_RC:   wr_new = wr_old & ~csr_wr_i.wdata;
      default: wr_new = wr_old;
    endcase
  end

  assign csr_wr_en_o = csr_wr_i.vld && wr_writes;
  assign csr_new_o   = wr_new;

  // 地址→写入值（`mstatus` 走 WARL 掩码；其余直存）
  function automatic logic [63:0] wr_apply(input logic [11:0] a, input logic [63:0] v);
    wr_apply = (a == CSR_MSTATUS) ? (v & MSTATUS_WMASK) : v;
  endfunction

  // -------------------------------------------------------------------------
  // `MRET` 返回包（`spec/01` §3.18 `ret_ctrl_t`；生产点＝本模块提交拍组合输出）
  // -------------------------------------------------------------------------
  logic [1:0] mpp_eff;
  always_comb begin
    mpp_eff = mstatus_q[MPP_LO+1 -: 2];
    if (mpp_eff == 2'b10) mpp_eff = PRV_M;             // 保留值 ⇒ 回退为 M（ISS `_xret` 同口径）
    ret_o        = '0;
    ret_o.vld    = ret_commit_i;
    ret_o.epc    = mepc_q[39:0];
    ret_o.pp     = mstatus_q[MPP_LO+1 -: 2];
    ret_o.pie    = mstatus_q[MPIE_B];
    ret_o.ie     = mstatus_q[MIE_B];
    ret_o.mprv_clr = (mpp_eff != PRV_M);
    ret_o.mode   = mpp_eff;                            // 返回目标模式（归底规则在提交拍判定）
    ret_o.is_sret = 1'b0;                              // 一期无 S 态（SRET 不在 G1-I 14 条内）
  end

  // -------------------------------------------------------------------------
  // `MRET`/trap 的 `mstatus` 下一值（组合；`spec/10` §2 逐动作）
  // -------------------------------------------------------------------------
  logic [63:0] mstatus_trap;
  logic [63:0] mstatus_ret;
  logic [63:0] mstatus_next;

  always_comb begin
    // trap 进场：MPIE ← MIE；MIE ← 0；MPP ← 前级（其余位不变）
    mstatus_trap = (mstatus_q & ~(64'd1 << MPIE_B) & ~(64'd1 << MIE_B) & ~(64'd3 << MPP_LO))
                   | (((mstatus_q >> MIE_B) & 64'd1) << MPIE_B)
                   | ({62'd0, excp_from_i} << MPP_LO);
    // MRET：MIE ← MPIE；MPIE ← 1；MPP ← 最低可用模式(U)；`MPP≠M` ⇒ 清 MPRV
    mstatus_ret  = (mstatus_q & ~(64'd1 << MIE_B) & ~(64'd1 << MPIE_B) & ~(64'd3 << MPP_LO))
                   | (((mstatus_q >> MPIE_B) & 64'd1) << MIE_B)
                   | (64'd1 << MPIE_B)
                   | ({62'd0, PRV_U} << MPP_LO);
    if (mpp_eff != PRV_M) mstatus_ret = mstatus_ret & ~(64'd1 << MPRV_B);
    // 提交拍唯一写者三选一（优先级写死：trap > MRET > CSR 写；单提交 ⇒ 构造上互斥）
    if (excp_commit_i)     mstatus_next = mstatus_trap;
    else if (ret_commit_i) mstatus_next = mstatus_ret;
    else if (csr_wr_i.vld && wr_writes && (csr_wr_i.addr == CSR_MSTATUS))
                           mstatus_next = wr_apply(CSR_MSTATUS, wr_new);
    else                   mstatus_next = mstatus_q;
  end

  // -------------------------------------------------------------------------
  // 顺序：写口 / trap 进场 / `MRET` 返回（三者互斥；优先级写死 excp > ret > csr_wr）
  // -------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      mstatus_q  <= 64'd0;                             // 六件复位值＝0（`spec/10` §4.1）
      mtvec_q    <= 64'd0;
      mscratch_q <= 64'd0;
      mepc_q     <= 64'd0;
      mcause_q   <= 64'd0;
      mtval_q    <= 64'd0;
    end else if (excp_commit_i) begin
      // ---- trap 进场 6 动作（`spec/10` §2；单特权级 ⇒ 「`priv` ← M」为恒等，无状态）----
      mepc_q    <= {24'd0, excp_epc_i};
      mcause_q  <= (excp_is_intr_i ? 64'h8000_0000_0000_0000 : 64'd0) | {60'd0, excp_cause_i};
      mtval_q   <= {24'd0, excp_tval_i};
      mstatus_q <= mstatus_next;
    end else if (ret_commit_i) begin
      // ---- `MRET` 返回动作（`spec/10` §2；锚 ISS-064：仅 `MPP≠M` 时清 MPRV）----
      mstatus_q <= mstatus_next;
    end else if (csr_wr_i.vld && wr_writes) begin
      unique case (csr_wr_i.addr)
        CSR_MSTATUS:  mstatus_q  <= mstatus_next;
        CSR_MISA:     ;                                   // 只读常量（写忽略，`spec/10` §4.1）
        CSR_MTVEC:    mtvec_q    <= wr_apply(csr_wr_i.addr, wr_new);
        CSR_MSCRATCH: mscratch_q <= wr_apply(csr_wr_i.addr, wr_new);
        CSR_MEPC:     mepc_q     <= wr_apply(csr_wr_i.addr, wr_new);
        CSR_MCAUSE:   mcause_q   <= wr_apply(csr_wr_i.addr, wr_new);
        CSR_MTVAL:    mtval_q    <= wr_apply(csr_wr_i.addr, wr_new);
        default:      ;                                   // 未实现地址：写忽略 —— TODO(G1-F)
      endcase
    end
  end

  // -------------------------------------------------------------------------
  // 状态与不变量（本版如实列出；断言化归 SVA 批 `spec/11` §7，本批不含）：
  //   ① 读口零副作用（组合 mux）⇒ `spec/10` §4.3 T-10-6 的「CSRRW rd=x0 不读」在本实现
  //      无可观测差异（读不改变任何状态）；② 写口、trap 进场、MRET 返回**同拍互斥**（单提交）；
  //   ③ `MPP` 只经 trap/`MRET`/软件写三条路径变化，且 `MPP=2'b10` 永不驻留（`MRET` 归底）。
  // -------------------------------------------------------------------------
  // synopsys translate_off
  initial $display("[vr1_csr] M17 CSR: 6 regs (mtvec/mepc/mscratch/mcause/mtval/mstatus) + misa RO + trap-entry 6 actions + MRET landed at M1-S3b; WARL masks (mtvec.MODE/mepc[0]) follow ISS (transitional ruling); csrq queue TODO(M1-S3); full table TODO(G1-F)");
  // synopsys translate_on

endmodule

`endif // VR1_CSR_SV
