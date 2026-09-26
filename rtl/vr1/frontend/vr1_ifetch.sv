// ==========================================================================
// rtl/vr1/frontend/vr1_ifetch.sv — M03 取指级（`F0/P3` 出队 + `F1/P4` 请求 + `F2/P5` 对齐写 IBUF）
//
// 状态（不得误读，红线 R8）：
//   · 本模块**已实现**：① FTQ 队头出队（`F0`）；② 取指请求/响应握手（单 outstanding，
//     `mem_req_t` IF 形态）；③ 32 B 窗 **16 槽**对齐与**指令边界 walk**（`spec/01` §3.16 规则）；
//     ④ **IBUF 16 槽 × 92 bit** 写入口（`F2/P5` 整窗 1 拍写完）＋ 组合读出口（D 级消费）；
//     ⑤ **逐窗握手/反压**（M1-S2）：D 侧 `ibuf_drain_i` 清窗有效位；窗未取尽时 **F0 不出队、
//        不发请求**（`ibuf_win_vld_q` 即"IBUF 忙"）——防新窗覆盖未消费槽。
//   · 本模块**未实现**（逐条给出口，未完成项一律 TODO，不写"看起来对"的逻辑）：
//     - **跨窗拼接 `xw_carry`**（§3.16 ISS-039 定案 A）与 C 压缩展开（16→32 bit）：
//       **不在 G1-I**（清单 §1.2 第 6 条；镜像全 32 bit、槽 15 起始不可达）⇒ 本版 walk 只认
//       **4 B 对齐**（每指令占 2 槽），起始槽 >14（必跨窗）不产出 —— TODO(G1-F v5)；
//     - 取指异常（`err`/`err_code`/`err_pos` 截断、I page/access fault）：无 PMA/PMP/翻译判决面
//       （清单 §1.2 第 1 条、§2.6「`fetch_raw_t.err/err_code` 恒 0」）⇒ 恒 0 —— TODO(G1-F)；
//     - **冲刷/重定向**（BRU 解析后的重定向、trap/MRET 重定向）——TODO(M1-S3)/TODO(M1-S4)：
//       本版无重定向入口，取指流只走"顺序流经 M01 的 pc 寄存器"（见 vr1_bp.sv）。
//   · 首版**不做 L1I**（清单 §1.2 第 2 条）：响应端由 TB 内存桩直连；请求 VA 由桩按 `VA[39:5]`
//     生成 32 B 窗基址（§3.16 `win_base_pc` 行 BLK-08：**产生点在 L1I 侧**，本模块只消费）。
//
// 依据：
//   · doc/spec/01 §3.13 `mem_req_t`（IF 请求形态）／§3.16 `icache_rsp_t`（响应形态 + walk 规则）
//     ／§3.2 `ftq_entry_t`（上游）／§3.3 `fetch_raw_t`（IBUF 槽形态与 16 槽口径）；
//   · doc/spec/01 §1.1 `P3/F0`、`P4/F1`、`P5/F2` 行；§1.2（IBUF 在 D 之前）；
//   · doc/spec/00 §4.1 `FETCH_BYTES=32`／§4.2 `IBUF_ENTRIES=16`／`RESET_PC`；
//   · doc/decisions/G1-I-最小冻结清单.md §2.6（首版恒 0／不消费成员表）、§2.3（简化 #1 单发射）。
//
// 写授权：`state/freeze.json` 的 rtl_write_authorized=true（R0 2026-09-25 签署 G1-I 的人令）。
// ==========================================================================
`ifndef VR1_IFETCH_SV
`define VR1_IFETCH_SV

module vr1_ifetch
  import vr1_pkg::*;
(
  input  logic                    clk,
  input  logic                    rst_n,

  // ---- 上游：FTQ 队头（spec/01 §3.2 `ftq_entry_t`，≤1/拍）----
  input  var vr1_pkg::ftq_entry_t ftq_entry_i,
  input  logic                    ftq_entry_vld_i,     // = M02 的 `ftq_pop_valid`
  input  logic [4:0]              ftq_entry_id_i,      // 队头序号（`ftqid_t`；§3.2 N14：「读指针自带」）
  output logic                    ftq_pop_o,           // 队头出队（本拍被 F0 取走）

  // ---- 下游：取指存储侧请求（spec/01 §3.13 `mem_req_t`，`kind=10 IF`）----
  output logic                    imem_req_valid_o,
  output vr1_pkg::mem_req_t       imem_req_o,
  input  logic                    imem_req_ready_i,

  // ---- 上游：取指存储侧响应（spec/01 §3.16 `icache_rsp_t`）----
  input  logic                    imem_rsp_valid_i,
  input  var vr1_pkg::icache_rsp_t imem_rsp_i,
  output logic                    imem_rsp_ready_o,

  // ---- 下游：IBUF（spec/01 §3.3；16 槽 × 92 bit = 1,472 bit，D 级消费）----
  output logic                    ibuf_win_vld_o,      // IBUF 内为"某 32 B 窗"（写后置 1；`ibuf_drain_i` 清 0）
  output vr1_pkg::fetch_raw_t     ibuf_rd_o [IBUF_ENTRIES],

  // ---- 下游：逐窗握手（M1-S2；来自 M05 `vr1_decode`）----
  input  logic                    ibuf_drain_i,        // 本拍＝本窗起始槽已被 D 全部取走 ⇒ 清窗有效位

  // ---- 冲刷口（M1-S3：`spec/01` §5.2 F0~F2 行「清 …在途 L1I/PTW 请求」）----
  // 置 1 一拍 ⇒ 在途请求作废（FSM 回 `F_IDLE`）、IBUF 窗有效位清零（未消费槽一并丢弃）；
  // 下一窗自重定向后的新路径重新请求（`ibuf_q` 内容由下次整窗写覆盖，无需清零）。
  input  logic                    flush_i
);

  // 注：`import vr1_pkg::*;` 写在 module 头部（而非此处）——端口表的 `[IBUF_ENTRIES]` 维度
  //     需要包内参数在**端口作用域**可见（见该行；SV-2009 允许 module 头部包导入）。

  // -------------------------------------------------------------------------
  // 常量（取自参数件/冻结面；不另赋值）
  // -------------------------------------------------------------------------
  localparam logic [1:0] REQ_KIND_IF = 2'b10;          // §3.13 `kind`：00 LD／01 STD／10 IF／11 PTW
  localparam logic [1:0] SIZE_W      = 2'b10;          // §3.13 `size` = `dm`：00 B／01 H／10 W／11 D
  localparam logic [1:0] PRV_M       = 2'b11;          // 清单 §2.6：首版 `priv` 恒 3（仅 M 态）
  localparam int unsigned SLOTS      = FETCH_BYTES / 2;   // 16 个 16 bit 候选槽（§3.3）

  // -------------------------------------------------------------------------
  // IBUF（16 槽 × `fetch_raw_t`(92 bit) = 1,472 bit，spec/01 §3.3）
  //   声明位置在握手段之前：`req_vld` 的"IBUF 忙"门控引用 `ibuf_win_vld_q`（M1-S2）。
  // -------------------------------------------------------------------------
  fetch_raw_t ibuf_q [IBUF_ENTRIES];
  logic       ibuf_win_vld_q;

  assign ibuf_win_vld_o = ibuf_win_vld_q;

  always_comb begin
    for (int unsigned i = 0; i < IBUF_ENTRIES; i++) ibuf_rd_o[i] = ibuf_q[i];   // 组合读口（D 级消费）
  end

  // -------------------------------------------------------------------------
  // 请求/响应握手（**单 outstanding**，与首版"单发射"口径一致：计划 §2.3 简化 #1）
  //   M1-S2 增补：F0 出队/发请求再加一道 **IBUF 空闲** 门控（见下 `req_vld` 注）。
  // -------------------------------------------------------------------------
  typedef enum logic [0:0] {
    F_IDLE,      // 等 FTQ 队头（并发出请求，等 ready；IBUF 忙时本态停留）
    F_WAIT       // 等响应（等 valid）
  } ifstate_e;

  ifstate_e    state_q;

  // F0 随流携带的块属性（F2 写 IBUF 时用：槽 `pc` 由窗基址算、`ftq_id`/`bp_upd_id` 随块）
  logic        blk_vld_q;
  logic [39:0] blk_pc_q;
  logic [4:0]  blk_nib_q;
  logic [4:0]  blk_id_q;                                // `ftqid_t`
  logic [7:0]  blk_bp_upd_id_q;

  logic        req_vld;                                 // 本拍可发请求（队头有效）
  logic        issue;                                   // 请求被接受（＝队头出队拍）
  logic        rsp_acc;                                 // 响应被接受（＝写 IBUF 拍）

  // `ibuf_win_vld_q`（下文声明）即"IBUF 忙"：M1-S2 的逐窗反压——上一窗未被 D 取尽时不发新请求，
  //   故写 IBUF 拍与 D 侧 `ibuf_drain_i` 结构性互斥（请求只在窗有效位为 0 时发出，而窗有效位
  //   只由写置 1、只由 drain 清 0）⇒ 无需再给 `imem_rsp_ready_o` 加门控。
  assign req_vld   = (state_q == F_IDLE) && ftq_entry_vld_i && !ibuf_win_vld_q;
  assign issue     = req_vld && imem_req_ready_i;
  assign rsp_acc   = (state_q == F_WAIT) && imem_rsp_valid_i;

  assign imem_req_valid_o = req_vld;
  assign imem_rsp_ready_o = (state_q == F_WAIT);
  assign ftq_pop_o        = issue;                      // P3/F0：队头恰在请求被接受拍出队

  // -------------------------------------------------------------------------
  // 请求载荷（spec/01 §3.13 逐成员；不消费成员保持合法 0 值——清单 §2.6）
  //   载荷源＝FTQ 队头：出队拍之前队头恒定（写/读指针只在出队拍变），故无需另锁存。
  // -------------------------------------------------------------------------
  always_comb begin
    imem_req_o                = '0;
    imem_req_o.valid          = req_vld;
    imem_req_o.kind           = REQ_KIND_IF;
    imem_req_o.va             = ftq_entry_i.pc;          // 翻译前地址＝块起始 VA
    imem_req_o.pa             = {4'b0, ftq_entry_i.pc};  // 无 MMU ⇒ `pa := va` 恒等旁路（清单 §1.2 第 1 条）
    imem_req_o.size           = SIZE_W;                  // **M1-S2 口径（原 TODO(M1-S2) 收口）**：§3.13
                                                         //   `size` 列只写 `dm`（数据宽度），**IF 请求
                                                         //   的取值在冻结面无定义**（`spec/09` §3 也只给
                                                         //   `ifetch_offset`）⇒ 本版取 `W`＝4 B（本版
                                                         //   窗口内最小可译单元，无 C），且**无消费端**：
                                                         //   响应端是 TB 内存桩，按整窗回 `win[255:0]`、
                                                         //   不看本域。口径冻结（`spec/01` §3.13 或
                                                         //   `spec/09` §3 补一行）归 G1-F —— TODO(G1-F)；
                                                         //   升版前不得据此域做任何判决（不构成判据证据）
    imem_req_o.priv           = PRV_M;                   // 清单 §2.6：恒 3
    imem_req_o.is_fetch       = 1'b1;                    // §3.13：取指访问不参与 store-forward 比较
    imem_req_o.ifetch_offset  = ftq_entry_i.pc[5:0];     // §3.13 L1I 行内窗口偏移（§1.1 P4 按 `VA[5]` 选窗）
    // 其余成员首版恒 0（清单 §2.6／无 LSU）：
    //   rob_id/rd_paddr/lq_id/sq_id（无 LSU 载荷）、amo_op（无 AMO）、sign_ext（取指不用）、
    //   req_id（无 MSHR outstanding）、
    //   **seq（原 TODO(M1-S2) 收口：IF 请求不是 μop ⇒ 本域无产生者）**——全局 μop 序号的**首个
    //   载体是 `rob_alloc_t.seq`（`spec/01` §3.6，S→ROB）**；`uop_t`（§3.4）/`rmap_uop_t`（§3.5）/
    //   `disp_x_t`（§3.11）**均无 `seq` 成员** ⇒ 序号产生点在 **S 级（分发，M1-S3）**，不在 D 级，
    //   更不在 IF 请求上。IF/C 侧 `mem_req_t.seq` 与 `icache_rsp_t.seq`（§3.16）的取值口径在冻结面
    //   无定义（同 `size` 的体例）⇒ 归 G1-F —— TODO(G1-F)；本版恒 0、**不代表任何序号语义**
  end

  // -------------------------------------------------------------------------
  // 槽内容取用（spec/01 §3.16 walk 规则：槽地址 = `win_base_pc` + 2×槽号）
  // -------------------------------------------------------------------------
  // 窗内槽 j 的 16 bit；越窗（槽 16）返回 0（S1 不产出该情形，见下 walk 守卫）
  function automatic logic [15:0] win_slot(input logic [255:0] w, input int unsigned j);
    win_slot = (j < SLOTS) ? w[16*j +: 16] : 16'b0;
  endfunction

  // 该槽是否为块内某指令的**起始槽**（S1：只有 4 B 情形 ⇒ 固定步长 2 槽）
  //   ① `s >= first`：块首槽 = 块起始 `pc[4:1]`（§3.16 定案；窗基址 `[4:0]=0` ⇒ 该式即窗内槽号）；
  //   ② `s <= SLOTS-2`：起始槽须留得出后继槽 —— **跨窗拼接（`xw_carry`）不在 G1-I**（清单 §1.2 第 6 条）
  //      ⇒ 会跨窗的起始槽本版**不产出**（宁可不产出，不产假指令；TODO(G1-F v5)）；
  //   ③ 步长 2 槽、条数 < `nib`（§3.1 块内条数）。
  function automatic logic slot_is_start(input int unsigned s, input int unsigned first,
                                         input int unsigned nib);
    slot_is_start = 1'b0;
    if ((s >= first) && (s <= (SLOTS - 2)))
      if ((((s - first) % 2) == 0) && (((s - first) / 2) < nib))
        slot_is_start = 1'b1;
  endfunction

  // walk 输入（取 F0 锁存的块属性；窗基址/窗内容取本拍响应）
  logic [4:0]   walk_first;
  logic [4:0]   walk_nib;
  logic [39:0]  rsp_win_base;
  logic [255:0] rsp_win;

  assign walk_first   = blk_pc_q[4:1];
  assign walk_nib     = blk_nib_q;
  assign rsp_win_base = imem_rsp_i.win_base_pc;
  assign rsp_win      = imem_rsp_i.win;

  // -------------------------------------------------------------------------
  // 顺序：F0 出队（锁块属性）/ F2 写 IBUF 整窗
  // -------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state_q          <= F_IDLE;
      blk_vld_q        <= 1'b0;
      blk_pc_q         <= 40'b0;
      blk_nib_q        <= 5'd0;
      blk_id_q         <= 5'd0;
      blk_bp_upd_id_q  <= 8'd0;
      ibuf_win_vld_q   <= 1'b0;
    end else if (flush_i) begin
      // 冲刷（M1-S3 落地）：在途请求作废 + 窗有效位清零；本拍**不发新请求**（防旧路径再入队）
      state_q        <= F_IDLE;
      blk_vld_q      <= 1'b0;
      ibuf_win_vld_q <= 1'b0;
    end else begin
      case (state_q)
        F_IDLE: begin
          if (issue) begin
            blk_vld_q       <= ftq_entry_i.valid;
            blk_pc_q        <= ftq_entry_i.pc;
            blk_nib_q       <= ftq_entry_i.nib;
            blk_id_q        <= ftq_entry_id_i;
            blk_bp_upd_id_q <= ftq_entry_i.bp_upd_id;
            state_q         <= F_WAIT;
          end
        end

        F_WAIT: begin
          if (imem_rsp_valid_i) begin
            // P5/F2：写 IBUF（整窗 16 槽，1 拍写完；槽 = 起始槽的 lane 带指令）
            for (int unsigned s = 0; s < IBUF_ENTRIES; s++) begin
              ibuf_q[s]           <= '0;                                    // 未消费面恒 0（§2.6）
              ibuf_q[s].valid     <= blk_vld_q && slot_is_start(s, walk_first, walk_nib);
              ibuf_q[s].pc        <= rsp_win_base + 40'(2*s);               // 槽地址 = 基址 + 2×槽号
              ibuf_q[s].raw32     <= { win_slot(rsp_win, s + 1), win_slot(rsp_win, s) };
              ibuf_q[s].is_c      <= 1'b0;                                  // 无 C（清单 §1.2 第 6 条）
              ibuf_q[s].bp_upd_id <= blk_bp_upd_id_q;
              ibuf_q[s].ftq_id    <= blk_id_q;
              ibuf_q[s].err       <= 1'b0;                                  // TODO(G1-F)：无取指异常判决面
              ibuf_q[s].err_code  <= 4'b0;
            end
            ibuf_win_vld_q <= 1'b1;
            state_q        <= F_IDLE;
          end
        end

        default: state_q <= F_IDLE;
      endcase

      // M1-S2：逐窗握手（D 侧 `vr1_decode` 的 `ibuf_drain_o`）——本窗起始槽已被 D 全部取走
      //   ⇒ 清窗有效位、放行下一窗（下一拍的 F_IDLE 即可出队/发请求）。IBUF 内容**不清**：
      //   槽阵列由下一次写整窗覆盖（未消费面在该写里恒 0，§2.6），读口另有 `ibuf_win_vld` 门控。
      if (ibuf_drain_i) ibuf_win_vld_q <= 1'b0;
    end
  end

  // -------------------------------------------------------------------------
  // 本模块**未实现**面（如实列出；逐条给出口）：
  //   · `xw_carry`（尾半字保持寄存器 + 跨窗拼接）与 C 展开 walk：TODO(G1-F v5)；
  //   · `err_pos` 截断与按槽展开 `err`/`err_code`（§3.16 N12/B-03）：TODO(G1-F)（无异常判决面）；
  //   · **冲刷/重定向入口已落（M1-S3：`flush_i`）**——BRU 误预测与 trap/MRET 重定向共用同一脉冲；
  //     重定向目标 pc 由 M01 的 `bp_pc_i` 承担（本模块只作废、不产目标）；
  //   · `win_base_pc` 与块起始 `pc` 同窗的**协议校验**（§3.16：响应基址 = 请求 `VA[39:5]`）：
  //     归 SVA 断言批（`spec/11` §7 A 类），本批不含；
  //   · 多 outstanding / 请求队列 / 多窗在飞（首版单发射、单请求、单窗）：随 `spec/13` 性能面。
  // -------------------------------------------------------------------------

endmodule

`endif // VR1_IFETCH_SV
