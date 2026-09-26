// ==========================================================================
// tb/unit/rt_t_trace_writer_smoke.sv — `rt_t_trace_writer` 的**单元级冒烟驱动**（DUT 无关）
//
// 它做什么：不接 DUT、不接内存桩，直接按拍喂 5 条**合成 retire 记录**给写出器，最后一条是
//   `tohost` 写（val=1）⇒ 期望走出 `HALT_PASS`。用来在 RTL 侧 trace 产出就位**之前**，把
//   「写出器的落盘格式 + 停机判据 + 文件打开/关闭」三件事单独跑通并留证。
//
// 为什么是"合成记录"而不是 golden 的 30 条：M1 的 golden 数据走 `sim/golden/tb_format_expect.csv`
//   （由 `iss/tools/gen_tb_trace_format.py` 用**同一套规则**渲染，判据 `trace-format-contract` ③ 判
//   golden vs 期望件 0 mismatch）。本冒烟只覆盖"写出器实际产出"这一端，5 条记录逐条对着
//   `spec/01` §3.21 的映射表取证：普通写回 / CSR 写（写后新值）/ 异常条目 / 64 位负值 / rd=x0 空串。
//
// 运行配方（**本批实测跑过**；本批**未**注册为 flow 判据，理由见 `script/flow.py:chk_trace_format_contract`
// 的 docstring：常跑守卫不得依赖 vsim license（ISS-104），正式判据落在 M1-S4 的仿真步骤）：
//   cd <仓库根> && mkdir sim\run_rt_t_writer_smoke
//   vlib  sim\run_rt_t_writer_smoke\work
//   vlog -64 -sv -work sim\run_rt_t_writer_smoke\work +incdir+rtl/vr1/include ^
//        tb/unit/rt_t_trace_writer.sv tb/unit/rt_t_trace_writer_smoke.sv
//   vsim -64 -c -do "run -all; quit -f" +RT_T_CSV=sim\run_rt_t_writer_smoke\rtl_side.csv ^
//        -work sim\run_rt_t_writer_smoke\work work.rt_t_trace_writer_smoke
//
// 实测结果（2026-09-26，ModelSim SE-64 2020.4；证据行逐字）：
//   [rt_t_trace_writer] HALT_PASS tohost=0x0040000010 val=0x1 rows=5 cyc=9
//   [rt_t_trace_writer] CLOSE csv=...\rtl_side.csv rows=5 exc=1 intr=0 mispred=0 br=0 load=0 store=0 cyc=8 halted=1
//   落盘 CSV（逐字节与"同规则 Python 渲染"相等，行尾 CRLF）：
//     pc,instr,gpr,csr,binary,mode,instr_str,operand
//     00001000,,ra:0x0000000000001000,,000010b7,PRV_M,,
//     00001008,,,0x305:0x0000000000001100,30509073,PRV_M,,
//     00001048,,,,0113a0a3,PRV_M,,
//     00001020,,a0:0xffffffffffffffff,,02948533,PRV_M,,
//     0000106c,,,,016ba023,PRV_M,,
//   （第 1 行 lui／第 3 行 csrrw→`csr` 新值／第 4 行异常条目／第 5 行 64 位负值／第 6 行 rd=x0 空串；
//     批注：探针初版曾报 `HALT_PASS rows=5` 而 `CLOSE rows=4` —— nonblocking 未落地导致汇报少 1，
//     已由写出器的「登记值 + 当拍在途」汇报口径修正，本冒烟即该修正的回归件。）
//
// 失败通路反证（2026-09-26 实测；改法即配方，证据落 `sim/run_rt_t_writer_smoke/fail_paths.log`）：
//   · watchdog：把本件第 5 条 drive 的 `i_memv/i_memwr/i_wdata` 改成 `1'b0,1'b0,1'b0` 且
//     `MAX_CYCLES` 改 8 ⇒ 证据行 `WATCHDOG_TIMEOUT cyc=8 >= MAX_CYCLES=8 rows=5 (rows done; R9/AB6)`
//     ＋ `** Fatal: ... watchdog timeout: no tohost write within 8 cycles`（Errors: 1）；
//   · HALT_FAIL：把第 5 条的 `i_wdata` 从 `64'h1` 改成 `64'h3`（riscv-tests 的 (testnum<<1)|1）
//     ⇒ 证据行 `HALT_FAIL tohost=0x0040000010 val=0x3 testnum=1 rows=5` ＋ `** Fatal: ... != 1`（Errors: 1）。
//   两条 `$fatal` 路径都**先 `$fflush` 再终止**：CSV 里已写行不丢（CLOSE 行同拍印证 rows=5）。
//
// 边界：本件是 **TB 单元件**（进 `filelist/tb_unit.f`，只做编译在环；不接 DUT、不进 `filelist/tb.f` 的
//   UVM 平台）；`MAX_CYCLES=100` 刻意调小，用来**顺带覆盖 watchdog 通路**（把 `RT_T_WRITE`/`tohost`
//   那条 drive 注释掉，即可看到 `WATCHDOG_TIMEOUT ... rows=4` + `$fatal` 的证据行）。
// ==========================================================================
`ifndef RT_T_TRACE_WRITER_SMOKE_SV
`define RT_T_TRACE_WRITER_SMOKE_SV

module rt_t_trace_writer_smoke;

  logic clk = 1'b0, rst_n = 1'b1;

  // 展平后的 `rt_t` 激励面（与 tb/unit/rt_t_trace_writer.sv 的端口逐一对应）
  logic        rt_valid   = 1'b0;
  logic [0:0]  rt_t_valid = 1'b0;
  logic [39:0] pc         = 40'h0;
  logic [31:0] instr      = 32'h0;
  logic [0:0]  is_c       = 1'b0;
  logic [4:0]  rd_idx     = 5'h0;
  logic [0:0]  rd_wb_en   = 1'b0;
  logic [63:0] rd_data    = 64'h0;
  logic [1:0]  priv       = 2'b11;                 // 首版仅 M 态（清单 §2.6）
  logic [11:0] csr_addr   = 12'h0;
  logic [63:0] csr_old    = 64'h0;
  logic [63:0] csr_new    = 64'h0;
  logic [0:0]  csr_wr_en  = 1'b0;
  logic [0:0]  exc_v      = 1'b0;
  logic [3:0]  exc_cause  = 4'h0;
  logic [0:0]  is_intr    = 1'b0;
  logic [0:0]  mispred    = 1'b0;
  logic [0:0]  is_br      = 1'b0;
  logic [0:0]  mem_v      = 1'b0;
  logic [39:0] mem_addr   = 40'h0;
  logic [63:0] mem_wdata  = 64'h0;
  logic [63:0] mem_rdata  = 64'h0;
  logic [1:0]  mem_size   = 2'b10;                 // 2'b10 = W（spec/02 §9.5 `dm`）
  logic [0:0]  mem_wr     = 1'b0;
  logic [11:0] seq        = 12'h0;
  logic [63:0] cycle      = 64'h0;

  rt_t_trace_writer #(.MAX_CYCLES(100)) u_writer (
    .clk(clk), .rst_n(rst_n), .rt_valid(rt_valid), .rt_t_valid(rt_t_valid),
    .pc(pc), .instr(instr), .is_c(is_c), .rd_idx(rd_idx), .rd_wb_en(rd_wb_en), .rd_data(rd_data),
    .priv(priv), .csr_addr(csr_addr), .csr_old(csr_old), .csr_new(csr_new), .csr_wr_en(csr_wr_en),
    .exc_v(exc_v), .exc_cause(exc_cause), .is_intr(is_intr), .mispred(mispred), .is_br(is_br),
    .mem_v(mem_v), .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_rdata(mem_rdata),
    .mem_size(mem_size), .mem_wr(mem_wr), .seq(seq), .cycle(cycle));

  always #1 clk = ~clk;

  // 一拍一条：negedge 摆激励 → posedge 被写出器采样 → negedge 撤激励（`valid` 单拍脉冲）
  task automatic drive(input logic [39:0] i_pc, input logic [31:0] i_instr,
                       input logic [4:0] i_rd, input logic i_wb, input logic [63:0] i_rdata,
                       input logic i_csrwe, input logic [11:0] i_csra, input logic [63:0] i_csrn,
                       input logic i_exc, input logic i_memv, input logic i_memwr,
                       input logic [63:0] i_wdata);
    begin
      @(negedge clk);
      rt_valid = 1'b1; rt_t_valid = 1'b1;
      pc = i_pc; instr = i_instr; rd_idx = i_rd; rd_wb_en = i_wb; rd_data = i_rdata;
      csr_wr_en = i_csrwe; csr_addr = i_csra; csr_new = i_csrn; csr_old = 64'h0;
      exc_v = i_exc; exc_cause = i_exc ? 4'd6 : 4'd0;          // 6 = store address misaligned
      mem_v = i_memv; mem_wr = i_memwr;
      mem_addr = i_memv ? 40'h00_4000_0010 : 40'h0;            // 唯一的访存记录即 tohost 写
      mem_wdata = i_wdata; mem_rdata = i_memv ? i_wdata : 64'h0;
      seq = seq + 1'b1; cycle = cycle + 1'b1;
      @(posedge clk);
      @(negedge clk);
      rt_valid = 1'b0; rt_t_valid = 1'b0; rd_wb_en = 1'b0; csr_wr_en = 1'b0;
      mem_v = 1'b0; mem_wr = 1'b0;
    end
  endtask

  string smoke_csv_path;

  initial begin
    // 冒烟必须显式给 CSV 路径（避免默认值落到仓库根）；写出器自己的 initial 读同一个 plusarg。
    if (!$value$plusargs("RT_T_CSV=%s", smoke_csv_path))
      $fatal(1, "[rt_t_trace_writer_smoke] missing +RT_T_CSV=<path> plusarg");
    rst_n = 1'b0;
    @(posedge clk); @(posedge clk);
    rst_n = 1'b1;
    // 1) 0x1000 lui ra,0x1                        → gpr=ra:0x…1000
    drive(40'h00_0000_1000, 32'h000010b7, 5'd1, 1'b1, 64'h0000_0000_0000_1000,
          1'b0, 12'h0, 64'h0, 1'b0, 1'b0, 1'b0, 64'h0);
    // 2) 0x1008 csrrw x0,mtvec,ra                 → csr=0x305:0x…1100（写后新值，ISS-013），gpr 空串
    drive(40'h00_0000_1008, 32'h30509073, 5'd0, 1'b0, 64'h0,
          1'b1, 12'h305, 64'h0000_0000_0000_1100, 1'b0, 1'b0, 1'b0, 64'h0);
    // 3) 0x1048 sw x17,1(x7) 非对齐 → 异常条目（exc_v=1）→ 两列皆空串
    drive(40'h00_0000_1048, 32'h0113a0a3, 5'd0, 1'b0, 64'h0,
          1'b0, 12'h0, 64'h0, 1'b1, 1'b0, 1'b0, 64'h0);
    // 4) 0x1020 mul a0,-1,-1                      → gpr=a0:0xffffffffffffffff（64 位负值）
    drive(40'h00_0000_1020, 32'h02948533, 5'd10, 1'b1, 64'hffff_ffff_ffff_ffff,
          1'b0, 12'h0, 64'h0, 1'b0, 1'b0, 1'b0, 64'h0);
    // 5) 0x106c sw x22,0(x23) → tohost=1          → HALT_PASS（riscv-tests 语义）
    drive(40'h00_0000_106c, 32'h016ba023, 5'd0, 1'b0, 64'h0,
          1'b0, 12'h0, 64'h0, 1'b0, 1'b1, 1'b1, 64'h1);
    repeat (2) @(posedge clk);
    $fatal(1, "[rt_t_trace_writer_smoke] no halt seen (tohost write was expected)");
  end

endmodule

`endif // RT_T_TRACE_WRITER_SMOKE_SV
