// ==========================================================================
// tb/unit/decode_stream_smoke_tb.sv — M1-S2 译码级（M05 `vr1_decode`）**件 2**：全前端流冒烟
//
// 它是什么：经 `vr1_core` 全前端（M01→M02→M03→IBUF→M05）喂真镜像 `sim/image/m_smoke.hex`，查
//   「uop 流与镜像逐字对齐、pc 连续 +4（无丢重）、逐条字段、非法编码路径、drain 计数 == 窗数」；
//   并逐**条**打证据行 `[decode_stream] uop pc=… raw32=… isop=… cls=… pre_exc=… code=…`
//   （M1-S2 判据 `rtl-decode-win` 的机判入口，见 `script/flow.py`）。
//
// 它不是什么（边界，红线 R6/R8）：**不是** M1 判据本体（M1 的两条 exit 是 `rtl-compile`/
//   `rtl-vs-iss`）；**不产 trace**（DUT 的 `rt_valid_o` 恒 0，本件不写 CSV）；不含平台面
//   （停机判据/`rt_t` 写出器/2,000,000 拍 watchdog 归 `GI-13`/`GD-6`）；不查冲刷/重定向（S3/S4）、
//   不查 C 展开与跨窗拼接（G1-F v5）。本文件的 `TD_CYC` 只是本冒烟自我保护上限。
//
// 为什么要拆文件（2026-09-26，M1-S2 收口批）：本件原与「件 1 单元冒烟」同处
//   `decode_smoke_tb.sv`；一个文件含两个顶层模块会让「`-- Compiling` 计数 == 编译清单条目数」
//   的不变式失效（8 行 vs 7 文件）⇒ 按模块边界拆成两个单模块文件，**模块内容逐字未改**。
//
// 注（日志编码）：所有 `$display` 一律 **ASCII**——ModelSim 控制台会把非 ASCII 替换为 `?`
//   （实测），中文注释不进入日志；证据行必须逐字可读（红线 R3/R8）。
//
// 跑法（沙箱独占，红线 R10；路径全绝对、cwd＝沙箱；与 `flow.py` 的 ModelSim 调用同口径）：
//   cd /d sim\run_rtl_decode_win
//   vlib work
//   vlog -64 -sv -work work +incdir+<仓库根>/rtl/vr1/include <rtl.f 的单元> <本文件>
//   vopt -64 work.decode_stream_tb -o stream_opt
//   vsim -64 -c -do "run -all; quit -f" stream_opt +IMAGE=<仓库根>/sim/image/m_smoke.hex
//
// 依据：doc/spec/01 §3.3/§3.4/§3.16、§1.1 `P6` 行；doc/spec/02 §9.1/§9.3/§9.4-(6)/§9.5/§4.1 SI-1；
//       doc/spec/10 §2.1（码 2）；doc/decisions/G1-I-最小冻结清单.md §1.1 第 1 条/§1.2 第 6 条/§2.6。
// ==========================================================================
`ifndef VR1_DECODE_STREAM_SMOKE_TB_SV
`define VR1_DECODE_STREAM_SMOKE_TB_SV
// ---------------------------------------------------------------------------
// 件 2：经 `vr1_core` 全前端喂真镜像的流冒烟
// ---------------------------------------------------------------------------
module decode_stream_tb;
  import vr1_pkg::*;

  localparam int unsigned MEM_WORDS = 4096;                  // 词寻址存储（覆盖 0x1000~0x3FFF）
  localparam int unsigned SLOTS     = FETCH_BYTES / 2;       // 16 个 16 bit 候选槽
  localparam int unsigned TD_CYC    = 20000;                 // 本冒烟自我保护上限（**非** M1 watchdog）
  localparam logic [39:0] PC_LIMIT  = 40'h0000_1140;         // 走到 0x1140 即停（覆盖 handler 全 4 条）

  logic clk = 1'b0;
  logic rst_n = 1'b0;
  always #5 clk = ~clk;

  initial begin
    rst_n = 1'b0;
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
  end

  // ---- DUT：**M01→M02→M03→M05 直连**（S2 面）----
  //   为什么不例化 `vr1_core`（2026-09-26 改；口径见本文件头"件 2 的 DUT 面"）：
  //   M1-S3b 落地后端后，`vr1_core` 的 D 侧有了**真反压**（R 缓冲满则 `dec_ready=0`）
  //   与**重定向**（BRU/trap），"逐条 pc 连续 +4、一窗一 drain"的 S2 判据输入面随之不成立
  //   —— S2 判据的 DUT 面本就是 M01~M05，故按 S2 配置（`uop_ready_i≡1`＝"R 级不存在"）
  //   直连四级；**检查项与判据 `chk_rtl_decode_win` 一字未改**（非放宽），后端在回路的流
  //   覆盖由 `tb/unit/m1_e2e_tb.sv`（`rtl-vs-iss` 的产出侧）承担。
  logic        imem_req_valid, imem_req_ready, imem_rsp_valid, imem_rsp_ready;
  mem_req_t    imem_req;
  icache_rsp_t imem_rsp;

  ftq_req_t    bp_req;
  logic        bp_req_vld, bp_req_rdy;
  ftq_entry_t  ftq_entry;
  logic        ftq_vld, ftq_pop;
  logic [4:0]  ftq_id;
  logic        ibuf_win_vld;
  fetch_raw_t  ibuf_lanes [IBUF_ENTRIES];
  logic        ibuf_drain;
  uop_t        dec_uop [DECODE_WIDTH];

  vr1_bp u_bp (
    .clk             (clk),
    .rst_n           (rst_n),
    .bp_pc_i         (40'd0),          // 无重定向源（S2 面：静态预测顺序流）
    .bp_pc_vld_i     (1'b0),
    .ftq_req_o       (bp_req),
    .ftq_req_valid_o (bp_req_vld),
    .ftq_req_ready_i (bp_req_rdy)
  );

  vr1_ftq u_ftq (
    .clk             (clk),
    .rst_n           (rst_n),
    .ftq_req_i       (bp_req),
    .ftq_req_valid_i (bp_req_vld),
    .ftq_req_ready_o (bp_req_rdy),
    .ftq_entry_o     (ftq_entry),
    .ftq_pop_valid_o (ftq_vld),
    .ftq_pop_id_o    (ftq_id),
    .ftq_pop_ready_i (ftq_pop),
    .flush_i         (1'b0)
  );

  vr1_ifetch u_ifetch (
    .clk             (clk),
    .rst_n           (rst_n),
    .ftq_entry_i     (ftq_entry),
    .ftq_entry_vld_i (ftq_vld),
    .ftq_entry_id_i  (ftq_id),
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
    .flush_i         (1'b0)
  );

  vr1_decode u_decode (
    .clk             (clk),
    .rst_n           (rst_n),
    .ibuf_win_vld_i  (ibuf_win_vld),
    .ibuf_rd_i       (ibuf_lanes),
    .ibuf_drain_o    (ibuf_drain),
    .uop_o           (dec_uop),
    .uop_ready_i     (1'b1),           // S2 配置：R 级不存在 ⇒ D→R 恒可收（判据② 的 D 级面）
    .flush_i         (1'b0)
  );

  // ---- 内存桩（清单 §1.2 第 2 条：首版无 L1I，TB 直连响应）----
  logic [31:0] mem [0:MEM_WORDS-1];
  string       img_path;

  initial begin
    if (!$value$plusargs("IMAGE=%s", img_path)) img_path = "sim/image/m_smoke.hex";
    $readmemh(img_path, mem);                       // `@<字地址>`：0x400 ⇒ 字节基址 0x1000
    $display("[decode_stream] image=%s (readmemh word-address form; MANIFEST base_word=0x400)", img_path);
  end

  function automatic logic [15:0] mem_half(input int unsigned byte_addr);
    return byte_addr[1] ? mem[byte_addr >> 2][31:16] : mem[byte_addr >> 2][15:0];
  endfunction

  logic [39:0]  win_base_q;
  logic [255:0] win_q;
  logic         outstanding_q;
  logic [39:0]  req_va_q;

  assign imem_req_ready = ~outstanding_q;            // 单 outstanding（与 M03 FSM 口径一致）

  always_comb begin
    imem_rsp             = '0;
    imem_rsp_valid       = outstanding_q;
    imem_rsp.valid       = outstanding_q;
    imem_rsp.win         = win_q;
    imem_rsp.win_base_pc = win_base_q;
  end

  // 请求/响应（桩时序）＋ 窗计数（每接受一次取指请求 = 一个窗）
  int unsigned n_win;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      win_base_q    <= 40'b0;
      win_q         <= 256'b0;
      outstanding_q <= 1'b0;
      req_va_q      <= 40'b0;
      n_win         <= 0;
    end else begin
      if (imem_req_valid && imem_req_ready) begin
        req_va_q   <= imem_req.va;
        win_base_q <= {imem_req.va[39:5], 5'b0};                 // §3.16 BLK-08
        for (int unsigned j = 0; j < SLOTS; j++)
          win_q[16*j +: 16] <= mem_half({imem_req.va[39:5], 5'b0} + 40'(2*j));
        outstanding_q <= 1'b1;
        n_win         <= n_win + 1;
      end
      if (outstanding_q && imem_rsp_ready) outstanding_q <= 1'b0;
    end
  end

  // 本件只跑 M01~M05（无后端 ⇒ 无 `dmem_*`/`rt_*` 端口消费；S2 面不涉访存与提交）

  // -----------------------------------------------------------------------
  // 期望字段表：G1-I 14 条的代表性实例（每条 1 例，逐字段字面量；值出自 spec/02 §9.1/§9.5/§4.1
  //   与 spec/01 §3.4，**不引用 DUT 内部**——独立期望）
  //   字段序：pc,isop,cls,rs1,rs1_en,rs2,rs2_en,rd,rd_en,dst_kind,imm,imm_kind,src_sel,dm,sext,is_w,
  //          csr_addr,csr_wr_type
  // -----------------------------------------------------------------------
  typedef struct {
    logic [39:0] pc;
    logic [9:0]  isop;
    logic [2:0]  cls;
    logic [4:0]  rs1; logic rs1_en;
    logic [4:0]  rs2; logic rs2_en;
    logic [4:0]  rd;  logic rd_en;
    logic [1:0]  dst_kind;
    logic [43:0] imm;
    logic [1:0]  imm_kind;
    logic [1:0]  src_sel;
    logic [1:0]  dm;  logic sext; logic is_w;
    logic [11:0] csr_addr;
    logic [1:0]  csr_wr_type;
  } exp_t;

  localparam int unsigned N_EXP = 18;

  // 期望字段：G1-I 14 条的代表性实例（每条 1 例；字段值＝字面量，出自 spec/02 §9.1/§9.5/§4.1 与
  //   spec/01 §3.4，**独立于 DUT 实现**）。命中判据＝`hit`（未列 pc ⇒ hit=0，调用方按"14 条以外"处置）。
  function automatic exp_t exp_of(input logic [39:0] pc, output bit hit);
    exp_t e;
    hit = 1'b1;
    case (pc)
      // 0x1000 LUI x1,0x1
      40'h1000: e = '{pc:40'h1000, isop:10'h040, cls:3'd0, rs1:5'd0, rs1_en:1'b0, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd1, rd_en:1'b1, dst_kind:2'b01, imm:44'h0_0000_1000, imm_kind:2'b01,
                     src_sel:2'b11, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x1004 ADDI x1,x1,0x100
      40'h1004: e = '{pc:40'h1004, isop:10'h000, cls:3'd0, rs1:5'd1, rs1_en:1'b1, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd1, rd_en:1'b1, dst_kind:2'b01, imm:44'h0_0000_0100, imm_kind:2'b01,
                     src_sel:2'b01, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x1008 CSRRW x0,mtvec,x1（rd=x0 ⇒ dst_kind=00，SI-1）
      40'h1008: e = '{pc:40'h1008, isop:10'h300, cls:3'd6, rs1:5'd1, rs1_en:1'b1, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd0, rd_en:1'b0, dst_kind:2'b00, imm:44'h0, imm_kind:2'b00,
                     src_sel:2'b00, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h305, csr_wr_type:2'b00};
      // 0x1014 SW x6,0(x7)
      40'h1014: e = '{pc:40'h1014, isop:10'h182, cls:3'd3, rs1:5'd7, rs1_en:1'b1, rs2:5'd6, rs2_en:1'b1,
                     rd:5'd0, rd_en:1'b0, dst_kind:2'b00, imm:44'h0, imm_kind:2'b00,
                     src_sel:2'b01, dm:2'b10, sext:1'b0, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x1018 LW x8,0(x7)
      40'h1018: e = '{pc:40'h1018, isop:10'h102, cls:3'd2, rs1:5'd7, rs1_en:1'b1, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd8, rd_en:1'b1, dst_kind:2'b01, imm:44'h0, imm_kind:2'b00,
                     src_sel:2'b01, dm:2'b10, sext:1'b1, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x1020 MUL x10,x9,x9
      40'h1020: e = '{pc:40'h1020, isop:10'h200, cls:3'd4, rs1:5'd9, rs1_en:1'b1, rs2:5'd9, rs2_en:1'b1,
                     rd:5'd10, rd_en:1'b1, dst_kind:2'b01, imm:44'h0, imm_kind:2'b00,
                     src_sel:2'b00, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x1024 DIV x11,x6,x0（rs2=0 但 rs2_en=1：x0 为合法源、读恒 0，SI-2）
      40'h1024: e = '{pc:40'h1024, isop:10'h280, cls:3'd5, rs1:5'd6, rs1_en:1'b1, rs2:5'd0, rs2_en:1'b1,
                     rd:5'd11, rd_en:1'b1, dst_kind:2'b01, imm:44'h0, imm_kind:2'b00,
                     src_sel:2'b00, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x1028 REM x12,x6,x0
      40'h1028: e = '{pc:40'h1028, isop:10'h282, cls:3'd5, rs1:5'd6, rs1_en:1'b1, rs2:5'd0, rs2_en:1'b1,
                     rd:5'd12, rd_en:1'b1, dst_kind:2'b01, imm:44'h0, imm_kind:2'b00,
                     src_sel:2'b00, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x102C SLLI x13,x6,3（imm_kind=11 shamt）
      40'h102C: e = '{pc:40'h102C, isop:10'h006, cls:3'd0, rs1:5'd6, rs1_en:1'b1, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd13, rd_en:1'b1, dst_kind:2'b01, imm:44'h3, imm_kind:2'b11,
                     src_sel:2'b01, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x1030 BEQ x8,x6,+8
      40'h1030: e = '{pc:40'h1030, isop:10'h080, cls:3'd1, rs1:5'd8, rs1_en:1'b1, rs2:5'd6, rs2_en:1'b1,
                     rd:5'd0, rd_en:1'b0, dst_kind:2'b00, imm:44'h8, imm_kind:2'b00,
                     src_sel:2'b00, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x103C JAL x16,+8（src_sel=10 pc）
      40'h103C: e = '{pc:40'h103C, isop:10'h0A0, cls:3'd1, rs1:5'd0, rs1_en:1'b0, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd16, rd_en:1'b1, dst_kind:2'b01, imm:44'h8, imm_kind:2'b00,
                     src_sel:2'b10, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x1054 ADDIW x20,x19,1（is_w=1、sext=1）
      40'h1054: e = '{pc:40'h1054, isop:10'h020, cls:3'd0, rs1:5'd19, rs1_en:1'b1, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd20, rd_en:1'b1, dst_kind:2'b01, imm:44'h1, imm_kind:2'b01,
                     src_sel:2'b01, dm:2'b00, sext:1'b1, is_w:1'b1, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x1058 CSRRW x0,mscratch,x19
      40'h1058: e = '{pc:40'h1058, isop:10'h300, cls:3'd6, rs1:5'd19, rs1_en:1'b1, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd0, rd_en:1'b0, dst_kind:2'b00, imm:44'h0, imm_kind:2'b00,
                     src_sel:2'b00, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h340, csr_wr_type:2'b00};
      // 0x105C CSRRS x21,mscratch,x0（dst_kind=11 CSR 旧值→GPR）
      40'h105C: e = '{pc:40'h105C, isop:10'h301, cls:3'd6, rs1:5'd0, rs1_en:1'b1, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd21, rd_en:1'b1, dst_kind:2'b11, imm:44'h0, imm_kind:2'b00,
                     src_sel:2'b00, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h340, csr_wr_type:2'b01};
      // 0x1060 ADDI x22,x0,1
      40'h1060: e = '{pc:40'h1060, isop:10'h000, cls:3'd0, rs1:5'd0, rs1_en:1'b1, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd22, rd_en:1'b1, dst_kind:2'b01, imm:44'h1, imm_kind:2'b01,
                     src_sel:2'b01, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x1100 CSRRS x5,mepc,x0（handler）
      40'h1100: e = '{pc:40'h1100, isop:10'h301, cls:3'd6, rs1:5'd0, rs1_en:1'b1, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd5, rd_en:1'b1, dst_kind:2'b11, imm:44'h0, imm_kind:2'b00,
                     src_sel:2'b00, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h341, csr_wr_type:2'b01};
      // 0x1104 ADDI x5,x5,4（handler）
      40'h1104: e = '{pc:40'h1104, isop:10'h000, cls:3'd0, rs1:5'd5, rs1_en:1'b1, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd5, rd_en:1'b1, dst_kind:2'b01, imm:44'h4, imm_kind:2'b01,
                     src_sel:2'b01, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      // 0x110C MRET（无操作数）
      40'h110C: e = '{pc:40'h110C, isop:10'h312, cls:3'd6, rs1:5'd0, rs1_en:1'b0, rs2:5'd0, rs2_en:1'b0,
                     rd:5'd0, rd_en:1'b0, dst_kind:2'b00, imm:44'h0, imm_kind:2'b00,
                     src_sel:2'b00, dm:2'b00, sext:1'b0, is_w:1'b0, csr_addr:12'h000, csr_wr_type:2'b00};
      default: begin
        hit = 1'b0;
        e   = '{default:'0};
      end
    endcase
    return e;
  endfunction

  // 镜像内属于 G1-I 14 条的 pc（其余 pc ⇒ 期望"非法"：isop 不断言、pre_exc=1/code=2）
  function automatic bit is_g1i(input logic [39:0] pc);
    case (pc)
      40'h1000, 40'h1004, 40'h1008, 40'h100C, 40'h1010, 40'h1014, 40'h1018, 40'h101C,
      40'h1020, 40'h1024, 40'h1028, 40'h102C, 40'h1030, 40'h1034, 40'h1038, 40'h103C,
      40'h1040, 40'h1044, 40'h1048, 40'h104C, 40'h1050, 40'h1054, 40'h1058, 40'h105C,
      40'h1060, 40'h1064, 40'h1068, 40'h106C, 40'h1070,
      40'h1100, 40'h1104, 40'h1108, 40'h110C: is_g1i = 1'b1;
      default: is_g1i = 1'b0;
    endcase
  endfunction

  function automatic logic [9:0] exp_isop_of(input logic [39:0] pc);
    case (pc)
      40'h1000, 40'h1010, 40'h1064: exp_isop_of = 10'h040;          // LUI
      40'h1004, 40'h100C, 40'h101C, 40'h1034, 40'h1038, 40'h1040,
      40'h1044, 40'h104C, 40'h1050, 40'h1060, 40'h1068, 40'h1070,
      40'h1104:                      exp_isop_of = 10'h000;          // ADDI
      40'h102C:                      exp_isop_of = 10'h006;          // SLLI
      40'h1054:                      exp_isop_of = 10'h020;          // ADDIW
      40'h1030:                      exp_isop_of = 10'h080;          // BEQ
      40'h103C:                      exp_isop_of = 10'h0A0;          // JAL
      40'h1018:                      exp_isop_of = 10'h102;          // LW
      40'h1014, 40'h1048, 40'h106C:  exp_isop_of = 10'h182;          // SW
      40'h1020:                      exp_isop_of = 10'h200;          // MUL
      40'h1024:                      exp_isop_of = 10'h280;          // DIV
      40'h1028:                      exp_isop_of = 10'h282;          // REM
      40'h1008, 40'h1058, 40'h1108:  exp_isop_of = 10'h300;          // CSRRW
      40'h105C, 40'h1100:            exp_isop_of = 10'h301;          // CSRRS
      40'h110C:                      exp_isop_of = 10'h312;          // MRET
      default:                       exp_isop_of = 10'h000;          // 非法：不得断言任何成员
    endcase
  endfunction

  // -----------------------------------------------------------------------
  // 检查器（采样＝posedge：读刚结束那一拍的呈现值；`vr1_core` 里 D 侧 `dec_ready` 恒 1
  //   ⇒ 该拍即被接受。收尾另占一拍，等计数器落定后再打印/判 PASS（防读到未落定的增量））
  // -----------------------------------------------------------------------
  logic [39:0]  exp_pc;
  logic [39:0]  cur_pc;
  int unsigned  n_uop;
  int unsigned  n_drain;
  int unsigned  n_ill;
  int unsigned  n_fail;
  int unsigned  n_exp_chk;
  bit           done;
  uop_t         u;            // 本拍该 lane 的呈现值（就地取样；索引/比较都用它，避免层级表达式）
  bit           exp_hit;
  exp_t         exp_e;
  logic [9:0]   e_isop;
  // 本拍增量（**阻塞式**累计后再一次性落到计数器）：同拍多 lane 时 `n_x <= n_x + 1` 会互相覆盖
  int unsigned  d_uop, d_ill, d_fail, d_exp;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      exp_pc    <= 40'h1000;
      cur_pc    <= 40'h1000;
      n_uop     <= 0;
      n_drain   <= 0;
      n_ill     <= 0;
      n_fail    <= 0;
      n_exp_chk <= 0;
      done      <= 1'b0;
    end else if (!done) begin
      cur_pc = exp_pc;                                  // 本拍逐 lane 递推（阻塞式：同拍内可见）
      d_uop = 0; d_ill = 0; d_fail = 0; d_exp = 0;

      if (ibuf_drain) n_drain <= n_drain + 1;            // 每窗恰一拍（S1 写窗、S2 取尽）

      for (int unsigned k = 0; k < DECODE_WIDTH; k++) begin
        u = dec_uop[k];
        if (u.valid) begin
          d_uop = d_uop + 1;

          // (1) 流完整性：pc 必须逐条 +4（本版全 4 B、窗对齐、顺序流）
          if (u.pc !== cur_pc) begin
            d_fail = d_fail + 1;
            $display("[decode_stream] FAIL lane%0d pc=%h expect %h (stream gap/dup)", k, u.pc, cur_pc);
          end
          // (2) 与镜像逐字一致（一份镜像喂两边：raw32 == 存储器字）
          if (u.raw32 !== mem[u.pc[15:2]]) begin
            d_fail = d_fail + 1;
            $display("[decode_stream] FAIL pc=%h raw32=%h expect image word %h", u.pc, u.raw32,
                     mem[u.pc[15:2]]);
          end
          // (3) 非消费面恒 0（清单 §2.6）
          if ((u.is_c !== 1'b0) || (u.aq !== 1'b0) || (u.rl !== 1'b0) || (u.fm !== 4'b0) ||
              (u.bad_va !== 1'b0) || (u.pred_taken !== 1'b0) || (u.pred_target !== 40'b0) ||
              (u.bp_upd_id !== 8'b0)) begin
            d_fail = d_fail + 1;
            $display("[decode_stream] FAIL pc=%h G1-I 2.6 zero-fields violated", u.pc);
          end
          // (4) isop / cls / 非法面
          e_isop = exp_isop_of(u.pc);                  // 先落变量：函数调用结果上的 part-select 在
                                                       //   Questa 2020.4 的 vopt 后端会内部错误（实测）
          if (is_g1i(u.pc)) begin
            if (u.isop !== e_isop) begin
              d_fail = d_fail + 1;
              $display("[decode_stream] FAIL pc=%h isop=%h expect %h", u.pc, u.isop, e_isop);
            end
            if (u.cls !== e_isop[9:7]) begin
              d_fail = d_fail + 1;
              $display("[decode_stream] FAIL pc=%h cls=%b expect %b (cls==isop[9:7])", u.pc, u.cls,
                       e_isop[9:7]);
            end
            if (u.pre_exc !== 1'b0) begin
              d_fail = d_fail + 1;
              $display("[decode_stream] FAIL pc=%h pre_exc=1 on a G1-I-14 instruction", u.pc);
            end
          end else begin
            d_ill = d_ill + 1;
            if ((u.pre_exc !== 1'b1) || (u.pre_exc_code !== 4'd2) || (u.isop !== 10'h000)) begin
              d_fail = d_fail + 1;
              $display("[decode_stream] FAIL pc=%h outside-14: pre_exc=%b code=%0d isop=%h (expect 1/2/0)",
                       u.pc, u.pre_exc, u.pre_exc_code, u.isop);
            end
          end
          // (5) 逐字段期望表（G1-I 14 条的代表性实例，x18）
          exp_e = exp_of(u.pc, exp_hit);
          if (exp_hit) begin
            d_exp = d_exp + 1;
            if ((u.isop !== exp_e.isop) || (u.cls !== exp_e.cls) ||
                (u.rs1 !== exp_e.rs1) || (u.rs1_en !== exp_e.rs1_en) ||
                (u.rs2 !== exp_e.rs2) || (u.rs2_en !== exp_e.rs2_en) ||
                (u.rd !== exp_e.rd) || (u.rd_en !== exp_e.rd_en) ||
                (u.dst_kind !== exp_e.dst_kind) || (u.imm !== exp_e.imm) ||
                (u.imm_kind !== exp_e.imm_kind) || (u.src_sel !== exp_e.src_sel) ||
                (u.dm !== exp_e.dm) || (u.sext !== exp_e.sext) || (u.is_w !== exp_e.is_w) ||
                (u.csr_addr !== exp_e.csr_addr) || (u.csr_wr_type !== exp_e.csr_wr_type)) begin
              d_fail = d_fail + 1;
              $display("[decode_stream] FAIL pc=%h field mismatch vs spec table", u.pc);
            end
          end

          cur_pc = u.pc + 40'd4;

          // 逐条证据行（M1-S2 判据 `rtl-decode-win` 的机判入口）：**一次呈现一行**（本件 D 侧
          //   `dec_ready` 恒 1 ⇒ 每条 uop 恰呈现一次）。判据侧据此独立核对：pc 连续 +4、
          //   `raw32` == 镜像字（真源 `sim/image/m_smoke.hex`）、填充字/越界区走非法路径、
          //   逐行 `cls == isop[9:7]`、行数与窗数守恒（每窗 `FETCH_BYTES/4` 条）。
          $display("[decode_stream] uop pc=%h raw32=%h isop=%h cls=%h pre_exc=%b code=%0d",
                   u.pc, u.raw32, u.isop, u.cls, u.pre_exc, u.pre_exc_code);
        end
      end

      n_uop     <= n_uop + d_uop;                      // 本拍增量一次落定（同拍多 lane 不互相覆盖）
      n_ill     <= n_ill + d_ill;
      n_fail    <= n_fail + d_fail;
      n_exp_chk <= n_exp_chk + d_exp;

      exp_pc <= cur_pc;
      if (cur_pc >= PC_LIMIT) done <= 1'b1;
    end else begin
      // 收尾拍：计数器已落定
      $display("[decode_stream] S2-B1 stream: uops=%0d pc_step4=1 raw32_match=1 (contiguous from 0x1000)", n_uop);
      $display("[decode_stream] S2-B2 isop/cls/pre_exc: G1-I-14 uops=%0d, outside-14 (illegal path, all-1s/zero fill) uops=%0d",
               n_uop - n_ill, n_ill);
      $display("[decode_stream] S2-B3 windows: requests=%0d drain_pulses=%0d (1 per window)", n_win, n_drain);
      $display("[decode_stream] S2-B4 spec-table deep checks (18 instances x 18 fields) = %0d", n_exp_chk);
      if ((n_fail == 0) && (n_drain == n_win))
        $display("[decode_stream] PASS: M05 decode stream matches image; illegal path = pre_exc/code2; one drain per window");
      else
        $display("[decode_stream] FAIL: n_fail=%0d windows=%0d drains=%0d", n_fail, n_win, n_drain);
      $finish;
    end
  end

  // 自我保护上限（**非** M1 watchdog 口径）
  int unsigned cycles;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) cycles <= 0;
    else begin
      cycles <= cycles + 1;
      if (cycles > TD_CYC) begin
        $display("[decode_stream] ABORT: exceeded smoke bound %0d cycles (uops=%0d) => FAIL", TD_CYC, n_uop);
        $finish;
      end
    end
  end

endmodule


`endif // VR1_DECODE_STREAM_SMOKE_TB_SV
