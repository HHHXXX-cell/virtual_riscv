// ==========================================================================
// rtl/vr1/lsu/vr1_lsu.sv — M11 访存单元（载入 7 条 ＋ 存储 4 条 ＋ 按宽非对齐 fault）
//
// 状态（不得误读，红线 R8）：
//   · 本模块**已实现**：
//     ① **AGU**：`addr = rs1_val + sext(imm)`（`spec/02` §10.3/§10.4 逐条语义，40 bit 域内回绕）；
//     ② **按宽非对齐判决**（`MISALIGNED_EN=0`，`spec/00` §2／§4.7、`spec/10` §2.1 码 4/6）：
//        对齐要求逐宽 —— 字节恒对齐、半字 `addr[0]=0`、字 `addr[1:0]=0`、双字 `addr[2:0]=0`
//        （`spec/02` §10.3/§10.4 各条「非对齐（`MISALIGNED_EN=0`，`spec/00` 行 245）→
//        misaligned fault」）。**不对齐 ⇒ 不发任何存储请求**，直接以 `ls_complete_t.fault/code`
//        报 fault（`load`→码 4、`store`→码 6），并在 `tval_o` 给出触发 VA；
//     ③ **请求/响应握手**：`mem_req_t`（`kind=00 LD`/`01 STD`，§3.13）＋ `dcache_rsp_t`（§3.16）；
//     ④ **载入的宽度/扩展**（M3-(d) 增补，2026-09-26 心跳第 10 轮）：
//        `dm`（00 B／01 H／10 W／11 D，§9.5）选定取回字节数；`sext`（§9.5：LB/LH/LW=1、
//        LBU/LHU/LWU=0、LD 不适用）选定符号/零扩展；**字节通路（littl-endian 内提取）在本单元完成**：
//        存储侧回读的是 `va[2:0]` 所在 8 B 对齐双字的 64 bit 内容（`dcache_rsp_t.data`，
//        TB 桩口径见 `tb/unit/m1_e2e_tb.sv`），本单元按 `addr_q[2:0]` 右移后再按宽度截取；
//     ⑤ **存储的宽度/字节使能**（同上批）：`dm` 逐条照 §9.5（SB 00／SH 01／SW 10／SD 11）；
//        `mem_req_o.size` ＝ `dm`（§3.13 `size` 口径）；数据面 `st_data_q` ＝ `rs2_val` **未移位**
//        （与 ISS `rec.mem_wdata` 同口径；字节使能由提交拍写出端按 `size`＋`addr[2:0]` 施加，
//        `rt_t.mem_size`/`mem_addr`/`mem_wdata` 三域已逐拍给出 —— §3.21②）；
//     ⑥ 提交拍观测面（`spec/01` §3.21②）：`mem_v/mem_addr/mem_wdata/mem_rdata/mem_size/mem_wr`
//        （`mem_size` ＝ `dm`，不再是恒 W）。
//   · 首版结构简化（计划 §2.3 简化 #3，接口之内）：
//     - **无 LQ/SQ**（`LQ_ENTRIES`/`SQ_ENTRIES` 面不做）：单发射单条在飞 ⇒ 在飞访存 μop 恒 1 条，
//       队列面与 `mem_req_t.lq_id/sq_id` 的产生点随之留空（恒 0）—— TODO(M1-S3)；
//     - **store 完成判据 ＝ 请求被接受**（`dmem_req_ready`）：一期禁投机 store 写 cache（清单
//       `GS-5`），且本设计在飞 μop 即"最老未提交"（提交序＝执行序）⇒ E 拍发起与"提交后写"等价；
//       `dcache_rsp_t` 于 store 的**写响应契约**在冻结面无定义（§3.16 只给数据回填语义）
//       ⇒ 本版不等写响应 —— TODO(G1-F)（`spec/09` 收口）；
//     - **`MISALIGNED_EN=1` 的拆包**（跨 4 B 边界多次访问）：一期禁（`spec/00` §2）—— 不实现；
//     - **转发/旁路**（`spec/07`）：无 L1D（清单 §1.2 第 2 条，响应端＝TB 内存桩）⇒ 不实现。
//   · 本模块**未实现**（逐条给出口）：AMO/LR/SC（§9.1.5）、`FENCE` 序面（§9.1.8）、
//     TLB/PMP/PMA 判决（`bad_va`/访问 fault 码 5/7）——均不在本批入面（清单 §1.1／§1.2 第 1 条）
//     —— TODO(G1-F)。
//
// 依据（逐条可核）：
//   · doc/spec/01 §3.11 `disp_x_t`（`rs1_val`/`rs2_val`/`imm`/`dm`/`sext`/`rd_paddr`/`rob_id`）／
//     §3.13 `mem_req_t`／§3.16 `dcache_rsp_t`／§3.20 `ls_complete_t`／§3.21②（`mem_*` 来源）；
//   · doc/spec/02 §9.1.4（载入 7／存储 4 成员编码）／§9.5（「`dm`」/「`sext`」两行派生规则）／
//     §10.3（载入 7 条：结果＝字节/半字/字/双字，含符号/零扩展逐条）／§10.4（存储 4 条：
//     `addr = rs1 + sext(imm)`）；
//   · doc/spec/10 §2.1 码 4/6（非对齐一律 fault；`MISALIGNED_EN=0`）；
//   · doc/decisions/G1-I-最小冻结清单.md §1.2 第 1/2 条（无 MMU/cache）／`GS-5`（禁投机 store 写）／
//     §2.6（恒 0 表）；doc/design/M1-实现计划.md §2.1 第 12 行／§2.3 简化 #3。
//
// 写授权：`state/freeze.json` 的 rtl_write_authorized=true（R0 2026-09-25 签署 G1-I 的人令）。
// ==========================================================================
`ifndef VR1_LSU_SV
`define VR1_LSU_SV

module vr1_lsu
  import vr1_pkg::*;
(
  input  logic        clk,
  input  logic        rst_n,

  // ---- 上游：发射（`W` 拍；§3.11 `disp_x_t`，本版单发射 ⇒ 1 条/拍）----
  input  logic        req_vld_i,
  input  var vr1_pkg::disp_x_t disp_i,
  output logic        req_rdy_o,       // 0 = 占用中（在飞访存恒 1 条）

  // ---- 下游：完成回报（§3.20 `ls_complete_t`，vld 一拍脉冲）----
  output vr1_pkg::ls_complete_t ls_o,
  output logic [39:0] tval_o,          // 触发 VA（fault 拍有效；载体口径见文件头）
  output logic [63:0] ld_data_o,       // load 结果（= 写回 `rd_data`；store 时无意义）

  // ---- 提交拍观测面（§3.21②：`rt_t.mem_*`）----
  output logic        mem_v_o,
  output logic [39:0] mem_addr_o,
  output logic [63:0] mem_wdata_o,
  output logic [63:0] mem_rdata_o,
  output logic [1:0]  mem_size_o,
  output logic        mem_wr_o,

  // ---- 存储侧：请求（§3.13 `mem_req_t`，`kind=00 LD`/`01 STD`）----
  output logic         dmem_req_valid_o,
  output vr1_pkg::mem_req_t dmem_req_o,
  input  logic         dmem_req_ready_i,
  // ---- 存储侧：响应（§3.16 `dcache_rsp_t`）----
  input  logic          dmem_rsp_valid_i,
  input  var vr1_pkg::dcache_rsp_t dmem_rsp_i,
  output logic          dmem_rsp_ready_o
);

  // -------------------------------------------------------------------------
  // 常量（`isop` 逐行取自 `spec/02` §9.1.4；码取 `spec/10` §2.1；宽度取 §9.5 `dm` 行）
  // -------------------------------------------------------------------------
  localparam logic [9:0] ISOP_LB  = 10'h100;
  localparam logic [9:0] ISOP_LH  = 10'h101;
  localparam logic [9:0] ISOP_LW  = 10'h102;
  localparam logic [9:0] ISOP_LD  = 10'h103;
  localparam logic [9:0] ISOP_LBU = 10'h104;
  localparam logic [9:0] ISOP_LHU = 10'h105;
  localparam logic [9:0] ISOP_LWU = 10'h106;
  localparam logic [9:0] ISOP_SB  = 10'h180;
  localparam logic [9:0] ISOP_SH  = 10'h181;
  localparam logic [9:0] ISOP_SW  = 10'h182;
  localparam logic [9:0] ISOP_SD  = 10'h183;
  localparam logic [1:0] KIND_LD  = 2'b00;      // §3.13 `kind`：00 LD
  localparam logic [1:0] KIND_STD = 2'b01;      // §3.13 `kind`：01 STD
  localparam logic [1:0] SZ_B     = 2'b00;      // §9.5 `dm`：00 B
  localparam logic [1:0] SZ_H     = 2'b01;      // §9.5 `dm`：01 H
  localparam logic [1:0] SZ_W     = 2'b10;      // §9.5 `dm`：10 W
  localparam logic [1:0] SZ_D     = 2'b11;      // §9.5 `dm`：11 D
  localparam logic [1:0] PRV_M    = 2'b11;      // 清单 §2.6：单特权级
  localparam logic [3:0] EXC_LOAD_MISALIGNED  = 4'd4;   // §2.1 码 4
  localparam logic [3:0] EXC_STORE_MISALIGNED = 4'd6;   // §2.1 码 6

  // -------------------------------------------------------------------------
  // 成员判别（`isop` 单值函数；本模块只引用 §9.1.4 的 11 个成员）
  // -------------------------------------------------------------------------
  function automatic logic is_store_op(input logic [9:0] isop);
    is_store_op = (isop == ISOP_SB) || (isop == ISOP_SH)
               || (isop == ISOP_SW) || (isop == ISOP_SD);
  endfunction

  // -------------------------------------------------------------------------
  // 按宽对齐判据（`MISALIGNED_EN=0`；`spec/02` §10.3/§10.4 各条 ＋ `spec/00` §2 口径统一）
  //   `a` = 有效地址（40 bit）；`sz` = `dm`（§9.5 宽度编码）
  // -------------------------------------------------------------------------
  function automatic logic misaligned_of(input logic [39:0] a, input logic [1:0] sz);
    unique case (sz)
      SZ_B:    misaligned_of = 1'b0;            // 字节：恒对齐（任意地址合法）
      SZ_H:    misaligned_of = a[0];            // 半字：2 B 对齐
      SZ_W:    misaligned_of = a[1] | a[0];     // 字：4 B 对齐
      default: misaligned_of = a[2] | a[1] | a[0];  // 双字：8 B 对齐
    endcase
  endfunction

  // -------------------------------------------------------------------------
  // 载入结果的宽度截取与扩展（`spec/02` §10.3 逐条「结果＝字节符号扩展」/「零扩展」/「双字」）
  //   `w`  ：存储侧回读的 64 bit（`va[2:0]` 所在 8 B 对齐双字，见 TB 桩口径）
  //   `off`：`addr[2:0]`（littl-endian ⇒ 低地址即低字节）
  // -------------------------------------------------------------------------
  function automatic logic [63:0] load_extract(input logic [63:0] w,
                                               input logic [2:0]  off,
                                               input logic [1:0]  sz,
                                               input logic        sgn);
    logic [63:0] sh;
    begin
      sh = w >> {off, 3'b000};
      unique case (sz)
        SZ_B:    load_extract = sgn ? {{56{sh[7]}},  sh[7:0]}   : {56'b0, sh[7:0]};
        SZ_H:    load_extract = sgn ? {{48{sh[15]}}, sh[15:0]}  : {48'b0, sh[15:0]};
        SZ_W:    load_extract = sgn ? {{32{sh[31]}}, sh[31:0]}  : {32'b0, sh[31:0]};
        default: load_extract = sh;                 // D：整宽，无扩展面（§9.5 `sext` 不适用）
      endcase
    end
  endfunction

  // -------------------------------------------------------------------------
  // 顺序（IDLE → REQ → [RSP] → DONE）：单条在飞、不流水
  // -------------------------------------------------------------------------
  typedef enum logic [1:0] {
    L_IDLE,     // 等发射（可收新请求）
    L_REQ,      // 已发请求，等 `dmem_req_ready`（load 与 store 都等）
    L_RSP,      // load：等 `dmem_rsp_valid`
    L_DONE      // 完成拍（给 `ls_o.vld` 一拍脉冲）
  } lsu_state_e;

  lsu_state_e  state_q;

  logic        is_store_q, fault_q;
  logic [1:0]  size_q, req_kind_q;
  logic        sext_q;
  logic [39:0] addr_q;
  logic [63:0] st_data_q;        // store 数据（`rs2_val`，**未移位**；见文件头 ⑤）
  logic [63:0] ld_data_q;        // load 结果（已扩展）
  logic [7:0]  robid_q;
  logic [5:0]  paddr_q;
  logic        mem_v_q;          // 提交拍观测面有效（访存且无 fault，§3.21②）

  logic [63:0] imm64;
  logic [39:0] agu_addr;

  assign imm64    = {{20{disp_i.imm[43]}}, disp_i.imm};      // `imm` 已按 ISA 语义符号扩展（§3.4）
  assign agu_addr = disp_i.rs1_val[39:0] + imm64[39:0];      // 40 bit 域内回绕（§10.3/§10.4）

  assign req_rdy_o = (state_q == L_IDLE);

  // -------------------------------------------------------------------------
  // 请求载荷（§3.13 逐成员；不消费成员保持合法 0 值——清单 §2.6）
  // -------------------------------------------------------------------------
  always_comb begin
    dmem_req_o            = '0;
    dmem_req_o.valid      = (state_q == L_REQ);
    dmem_req_o.kind       = req_kind_q;
    dmem_req_o.va         = addr_q;
    dmem_req_o.pa         = {4'b0, addr_q};                   // 无 MMU ⇒ `pa := va`（清单 §1.2 第 1 条）
    dmem_req_o.size       = size_q;                           // §3.13：`size` = `dm`（§9.5 宽度）
    dmem_req_o.amo_op     = 4'b0;                             // 无 AMO（清单 §1.2）
    dmem_req_o.sign_ext   = sext_q;                           // load：§9.5 `sext`；store：恒 0（不适用）
    dmem_req_o.rob_id     = robid_q;
    dmem_req_o.rd_paddr   = paddr_q;
    // `lq_id`/`sq_id`：首版无 LQ/SQ（计划 §2.3 简化 #3）⇒ 恒 0 —— TODO(M1-S3)
    dmem_req_o.priv       = PRV_M;
    dmem_req_o.is_fetch   = 1'b0;
    // `ifetch_offset`/`req_id`/`seq`：数据侧不消费（无 MSHR；`seq` 产生点在 S 级，§3.6）⇒ 恒 0
  end

  assign dmem_req_valid_o = (state_q == L_REQ);
  assign dmem_rsp_ready_o = (state_q == L_RSP);

  // -------------------------------------------------------------------------
  // 完成回报（§3.20）与观测面（§3.21②）
  // -------------------------------------------------------------------------
  always_comb begin
    ls_o       = '0;
    ls_o.vld   = (state_q == L_DONE);
    ls_o.robid = robid_q;
    // `fault`[1:0] 的编码面在冻结面无定义（§3.20 只给位宽）⇒ 本版按方向给 01=load/10=store、
    //   00=无 fault，**仅供本单元自用**；消费方（提交侧）只读 `code`（§2.1 码表）—— TODO(G1-F)
    ls_o.fault = fault_q ? (is_store_q ? 2'b10 : 2'b01) : 2'b00;
    ls_o.code  = fault_q ? (is_store_q ? EXC_STORE_MISALIGNED : EXC_LOAD_MISALIGNED) : 4'd0;
    ls_o.lqid  = 6'd0;                                        // 无 LQ（TODO(M1-S3)）
  end
  assign tval_o      = addr_q;
  assign ld_data_o   = ld_data_q;

  assign mem_v_o     = mem_v_q;
  assign mem_addr_o  = addr_q;
  assign mem_wdata_o = st_data_q;
  assign mem_rdata_o = ld_data_q;                             // §3.21①：与 `rd_data` 同值（load 结果）
  assign mem_size_o  = size_q;                                // §3.21②：`dm`（M3-(d) 起非常量 W）
  assign mem_wr_o    = is_store_q;

  // -------------------------------------------------------------------------
  // 顺序
  // -------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state_q     <= L_IDLE;
      is_store_q  <= 1'b0;
      fault_q     <= 1'b0;
      size_q      <= SZ_W;
      req_kind_q  <= KIND_LD;
      sext_q      <= 1'b1;
      addr_q      <= 40'd0;
      st_data_q   <= 64'd0;
      ld_data_q   <= 64'd0;
      robid_q     <= 8'd0;
      paddr_q     <= 6'd0;
      mem_v_q     <= 1'b0;
    end else begin
      unique case (state_q)
        L_IDLE: begin
          mem_v_q <= 1'b0;                                     // 新请求拍清观测面
          if (req_vld_i) begin
            addr_q     <= agu_addr;
            st_data_q  <= disp_i.rs2_val;                      // store 数据（`rs2`，未移位）
            robid_q    <= disp_i.rob_id;
            paddr_q    <= disp_i.rd_paddr;
            size_q     <= disp_i.dm;                           // §9.5 `dm`：B/H/W/D
            sext_q     <= disp_i.sext;                         // §9.5 `sext`（load）；store 恒 0
            is_store_q <= is_store_op(disp_i.isop);
            req_kind_q <= is_store_op(disp_i.isop) ? KIND_STD : KIND_LD;
            // 按宽非对齐判决（`MISALIGNED_EN=0`）：不发请求，直接进完成拍报 fault（码 4/6）
            fault_q    <= misaligned_of(agu_addr, disp_i.dm);
            state_q    <= misaligned_of(agu_addr, disp_i.dm) ? L_DONE : L_REQ;
          end
        end

        L_REQ: begin
          if (dmem_req_ready_i) begin
            if (is_store_q) begin
              mem_v_q <= 1'b1;                                 // store 完成＝请求被接受（见文件头）
              state_q <= L_DONE;
            end else begin
              state_q <= L_RSP;
            end
          end
        end

        L_RSP: begin
          if (dmem_rsp_valid_i) begin
            // 回读的是 `va[2:0]` 所在 8 B 对齐双字的 64 bit；按 `addr[2:0]` 移位后按 `dm` 截取，
            //   再按 `sext` 扩展（`spec/02` §10.3 逐条：LB/LH/LW 符号扩展、LBU/LHU/LWU 零扩展、
            //   LD 整宽）—— 字节通路全部在本单元内完成，不依赖存储侧做 lane 选择。
            ld_data_q <= load_extract(dmem_rsp_i.data, addr_q[2:0], size_q, sext_q);
            mem_v_q   <= 1'b1;
            state_q   <= L_DONE;
          end
        end

        L_DONE: begin
          state_q <= L_IDLE;                                   // 完成脉冲恰一拍
        end

        default: state_q <= L_IDLE;
      endcase
    end
  end

  // -------------------------------------------------------------------------
  // 状态与不变量（本版如实列出；断言化归 SVA 批 `spec/11` §7，本批不含）：
  //   ① 在飞访存恒 ≤1（`state_q≠L_IDLE` ⇒ 不收新请求，`req_rdy_o=0`）；
  //   ② 非对齐请求**不产生 `dmem_req_valid_o`**（码 4/6 的构造性保证；判据按 `size_q` 逐宽）；
  //   ③ store 的数据面永不发第二次（单发射、无重放）—— TODO(M1-S3)（重放/冲刷面）；
  //   ④ `mem_size_o` == 本条访存的 `dm`（B/H/W/D），与 `dmem_req_o.size` 同源同理。
  // -------------------------------------------------------------------------
  // synopsys translate_off
  initial $display("[vr1_lsu] M11 LSU: 7 loads + 4 stores (dm/sext per spec/02 9.5) + per-width misaligned fault (cause 4/6, MISALIGNED_EN=0) + mem_req/dcache_rsp handshake; no LQ/SQ, no forwarding, AMO/fence/TLB TODO(G1-F)");
  // synopsys translate_on

endmodule

`endif // VR1_LSU_SV
