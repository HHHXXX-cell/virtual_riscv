// ==========================================================================
// tb/unit/rt_t_trace_writer.sv — `rt_t` → trace CSV 写出器 + 停机判据 + watchdog
//                            （G1-I 清单 `GI-13` 的 TB 侧缺口的首件实现）
//
// 依据（逐条可核，本文件不自创任何列/口径）：
//   · doc/spec/01 §3.21 `rt_t` 成员位域表（L710~L736）——本模块端口逐成员同名同宽；
//   · doc/spec/01 §6 顶层端口表 L862：`rt_valid_o`（1 bit）/ `rt_o`（543 bit）——**单条/拍**
//     （本模块即按"1 条/拍"实现；COMMIT_WIDTH=4 的 lane 展开不在冻结端口面上，见"未做"段）；
//   · doc/spec/01 §7「trace 比对口径」L899~L901 + 「异常条目三条规定」#1（B10 lane 粒度）；
//   · iss/README.md §3「trace 字段映射（唯一权威表）」——列序、空串规则、ABI 名口径；
//   · iss/vriss/trace.py `TRACE_CSV_FIELDS` / `ABI_NAMES` / `gpr_field()` / `csr_field()` /
//     `_mode_str()`（本文件的格式化规则**逐条照抄**这两处，不另立规则）；
//   · iss/tools/trace_compare.py `DEFAULT_COLS=['pc','binary','gpr','csr']`（默认不比的列：`instr`/
//     `instr_str`/`operand`=工具自定义文本；`cycle`/`mispred`/`seq`=调试量）；
//   · doc/design/M1-实现计划.md §4.1（映射表）/§4.2（停机与 watchdog，红线 R9）；
//   · iss/tests/test_smoke.py `TOHOST`/`halt_val==1`（riscv-tests 停机语义）；
//   · doc/process/00 **ISS-013**（`csr` 列取**写后新值**=`rt_t.csr_new`）。
//
// 读写边界（如实声明）：
//   · 本文件是 **TB 侧**件（DUT 无关：只吃 `rt_t` 面，不例化 DUT、不含任何 DUT 层次路径）；
//   · **不 import `vr1_pkg`**（刻意的）：端口按 §3.21 逐成员展平，避开 M1 计划 §3.3 冲突①
//     「`tb/vr1_uvm/vr1_pkg.sv` 与 RTL 参数/类型包同名」——本件因此可在任何库里单独编译；
//   · 本批**未跑**仿真（无激励）：写出器的"实际产出 vs 期望件"逐字节闭合留给 M1-S4（见文末"未做"）。
//
// 行尾口径（**实测锚点**，勿凭记忆改）：ModelSim SE-64 2020.4 在 Windows 下
//   `$fopen(path,"w")` 为**文本模式**，`$fwrite` 里的 `\n` 被翻成 CRLF（探针实测
//   `sim/run_tb_compile/probe_out.csv`：`"LF-ROW a,b\r\n"`）；而显式 `\r\n` 会变成 `\r\r\n`
//   （`"CRLF-ROW a,br\r\n"`——`\r` 原样保留、`\n` 再翻一次）。
//   ⇒ 本模块**一律只写 `\n`**，落盘即 CRLF，与 `iss/vriss/trace.py` 的 `csv.DictWriter`
//   默认 lineterminator=`\r\n` 逐字节同款。**禁止**改成显式 `\r\n`。
// ==========================================================================
`ifndef RT_T_TRACE_WRITER_SV
`define RT_T_TRACE_WRITER_SV

module rt_t_trace_writer #(
    // watchdog 拍数上限（红线 R9「功能比对类」= 2,000,000 拍）；超限 `$fatal` + 证据行（批中止判据 AB6）
    parameter int unsigned    MAX_CYCLES = 2_000_000,
    // riscv-tests `tohost`（iss/tests/test_smoke.py `TOHOST`；G1-I 清单 §1.1 第 8 条）
    parameter logic [39:0]    TOHOST_ADDR = 40'h00_4000_0010,
    // CSV 落盘路径默认值：相对**仿真 cwd**（M1 计划 §1.2 的比对命令从仓库根运行）；
    // 沙箱/别处运行请用 `+RT_T_CSV=<path>` 覆盖（见 `initial` 段的 $value$plusargs）
    parameter string          CSV_PATH_DEFAULT = "sim/run_m1_rtl/rtl_side.csv"
) (
    input  logic        clk,
    input  logic        rst_n,                  // 低有效异步复位（spec/00 §4.7：CLK_DOMAINS=1）

    // ---- 握手（spec/01 §6 L862 `rt_valid_o`）----
    // 语义：`rt_valid` = CT 授权拍（§7 A10「trace 只能由 CT 产生」）；与下方载荷位 `rt_t_valid`
    // 是**两个不同的东西**：前者是端口级握手，后者是 §3.21 的成员 `valid`。本模块取**与**（最严：
    // 一个授权拍 + 一个有效条目才写一行；宁少写一行也不写一行假 trace——红线 R6/R8）。
    input  logic        rt_valid,

    // ---- rt_t 载荷（spec/01 §3.21，逐成员同名/同宽；与 rtl/vr1/include/vr1_types.svh 的
    //      `rt_t` 声明逐行对应，位宽改动须同步该生成件（改 spec/01 §3 后重跑 flow.py types））----
    input  logic [0:0]  rt_t_valid,             // §3.21 valid
    input  logic [39:0] pc,                     // §3.21 pc
    input  logic [31:0] instr,                  // §3.21 instr（原始指令字 → CSV 列 `binary`）
    input  logic [0:0]  is_c,                   // §3.21 is_c（首版 RV64GC 无 C 展开 ⇒ 恒 0）
    input  logic [4:0]  rd_idx,                 // §3.21 rd_idx
    input  logic [0:0]  rd_wb_en,               // §3.21 rd_wb_en（`gpr` 空串规则的一半）
    input  logic [63:0] rd_data,                // §3.21 rd_data
    input  logic [1:0]  priv,                   // §3.21 priv → CSV 列 `mode`
    input  logic [11:0] csr_addr,               // §3.21 csr_addr
    input  logic [63:0] csr_old,                // §3.21 csr_old（**不进 CSV**：ISS-013 定「取写后新值」）
    input  logic [63:0] csr_new,                // §3.21 csr_new → CSV 列 `csr`（写后新值）
    input  logic [0:0]  csr_wr_en,              // §3.21 csr_wr_en（`csr` 空串规则）
    input  logic [0:0]  exc_v,                  // §3.21 exc_v（本批仅计数/证据行，不改列语义）
    input  logic [3:0]  exc_cause,              // §3.21 exc_cause（同上）
    input  logic [0:0]  is_intr,                // §3.21 is_intr（同上）
    input  logic [0:0]  mispred,                // §3.21 mispred（**不参与比对**，仅计数）
    input  logic [0:0]  is_br,                  // §3.21 is_br（仅计数）
    input  logic [0:0]  mem_v,                  // §3.21 mem_v（停机判据的一半）
    input  logic [39:0] mem_addr,               // §3.21 mem_addr（停机判据：== TOHOST_ADDR）
    input  logic [63:0] mem_wdata,              // §3.21 mem_wdata（停机判据的**值**，见"停机判据"段）
    input  logic [63:0] mem_rdata,              // §3.21 mem_rdata（= load 结果，与 rd_data 同值；CSV 无此列）
    input  logic [1:0]  mem_size,               // §3.21 mem_size（不参与停机判据，见下）
    input  logic [0:0]  mem_wr,                 // §3.21 mem_wr（store 标志）
    input  logic [11:0] seq,                    // §3.21 seq（**不参与比对**，仅调试排序用）
    input  logic [63:0] cycle                   // §3.21 cycle（**不参与比对**，仅性能统计）
);

  // -------------------------------------------------------------------------
  // ① 格式化规则常量 —— **逐字照 iss/vriss/trace.py，禁自创、禁改序**
  // -------------------------------------------------------------------------
  // 表头逐字 == `iss/vriss/trace.py` 的 `TRACE_CSV_FIELDS`（8 列，顺序即列序）：
  //   TRACE_CSV_FIELDS = ["pc","instr","gpr","csr","binary","mode","instr_str","operand"]
  // 判据 `trace-format-contract` ② 会把本字面量与 trace.py 的真源逐字比对（机判，禁人眼兜底）。
  localparam string TRACE_CSV_HEADER = "pc,instr,gpr,csr,binary,mode,instr_str,operand";

  // ABI 名表逐项 == `iss/vriss/trace.py` 的 `ABI_NAMES`（同序同拼写；判据 ② 逐项机判。
  // 为什么必须一字不差：trace_compare.py 的 `normalize_row()` 只做**小写化**不做名映射 ⇒
  // `gpr` 列的名不同即 mismatch，与数值无关）。
  localparam string ABI_NAMES[32] = '{
      "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
      "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
      "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
      "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6"};

  // -------------------------------------------------------------------------
  // ② 逐列格式化函数（规则出处逐条注明）
  // -------------------------------------------------------------------------
  // `mode` 列：trace.py `_mode_str()`——0→PRV_U／1→PRV_S／3→PRV_M／其余→`PRV_?<n>`
  function automatic string mode_str(input logic [1:0] prv);
    case (prv)
      2'd0:    return "PRV_U";
      2'd1:    return "PRV_S";
      2'd3:    return "PRV_M";
      default: return $sformatf("PRV_?%0d", prv);
    endcase
  endfunction

  // `gpr` 列：trace.py `gpr_field()`——`rd_idx==0` 或 `rd_wb_en==0` ⇒ **空串**，否则 `<abi名>:0x%016x`。
  // （`CSRRW x0,mtvec,x1`／`CSRRW x0,mscratch,x19` 的 rd=x0 行因此为空串——映射表 L45 的实测依据。）
  function automatic string gpr_field(input logic [4:0]  rd_i,
                                      input logic [0:0]  wb_i,
                                      input logic [63:0] dat_i);
    if (!wb_i || rd_i == 5'd0) return "";
    return $sformatf("%s:0x%016x", ABI_NAMES[rd_i], dat_i);
  endfunction

  // `csr` 列：trace.py `csr_field()`——`csr_wr_en==0` ⇒ 空串，否则 `0x<addr 3位>:0x%016x`，
  // **取写后新值 `csr_new`**（doc/process/00 ISS-013：只给旧值无法直接判 CSR 行为）。
  function automatic string csr_field(input logic [0:0]  wr_i,
                                      input logic [11:0] adr_i,
                                      input logic [63:0] new_i);
    if (!wr_i) return "";
    return $sformatf("0x%03x:0x%016x", adr_i, new_i);
  endfunction

  // -------------------------------------------------------------------------
  // ③ 状态
  // -------------------------------------------------------------------------
  string   csv_path;                             // 仅在 initial 段驱动
  integer  fd;                                   // 0 = 未打开（fail-loud，见 initial 段）；仅 initial/final 段驱动
  longint unsigned n_retired, n_exc, n_intr, n_mispred, n_br, n_load, n_store;  // 仅 always_ff（含复位分支）
  longint unsigned cyc_q;                        // **TB 本地**拍计数（见 watchdog 段：刻意不用 rt_t.cycle）
  bit      halted;                               // tohost 写已命中（无论 PASS/FAIL）；仅 always_ff 驱动

  // 当拍在途事件（组合，供"登记值 + 在途"汇报口径用）——见 ⑥ 段说明：`$finish`/`$fatal` 与
  // 退休登记发生在**同一拍**，nonblocking 赋值尚未落地 ⇒ 汇报必须补上在途项，否则证据行比
  // 实际落盘行数少 1（首次探针实测踩到：HALT_PASS rows=5 而 CLOSE rows=4）。
  logic retire_fire, halt_fire;
  assign retire_fire = rt_valid && rt_t_valid;
  assign halt_fire   = mem_v && mem_wr && (mem_addr == TOHOST_ADDR);

  // -------------------------------------------------------------------------
  // ④ 打开文件 + 写表头（time 0，确定性：空跑也留一件**有表头**的 CSV，便于比对器报"0 条"而非"缺文件"）
  // -------------------------------------------------------------------------
  initial begin
    if (!$value$plusargs("RT_T_CSV=%s", csv_path)) csv_path = CSV_PATH_DEFAULT;
    fd = $fopen(csv_path, "w");
    // 证据/错误行一律 **ASCII**（中文一律只进注释）：vlog 按本机码页读源，字符串里的多字节字符
    // 会以本机码页落进 log，flow.py 的判据要按字面 grep 这些行（见 tb-compile / 后续步骤）。
    if (fd == 0)
      $fatal(1, "[rt_t_trace_writer] $fopen FAILED (dir missing?): %s -- override with +RT_T_CSV=<path>",
             csv_path);
    $fwrite(fd, "%s\n", TRACE_CSV_HEADER);       // `\n` 即可：文本模式落盘为 CRLF（见文件头行尾口径）
    // 计数器的初值一律走 always_ff 的复位分支（`always_ff` 驱动的变量不得被第二个进程驱动，vlog-7061）
    $display("[rt_t_trace_writer] OPEN csv=%s MAX_CYCLES=%0d TOHOST=0x%010x",
             csv_path, MAX_CYCLES, TOHOST_ADDR);
  end

  // -------------------------------------------------------------------------
  // ⑤ 每拍：写一行 / 停机判据 / watchdog
  //    —— 一条退休 = 一行；`instr`/`instr_str`/`operand` 三列**留空**（理由见下）
  // -------------------------------------------------------------------------
  // 为什么三列留空：`rt_t`（§3.21，25 个成员）**没有任何反汇编文本成员**，而这三列在
  // `trace.py:to_trace_row()` 里全部来自 `instr_str`/`operand`（`instr` 列 = 助记符 = `instr_str`）。
  // 三者均**默认不参与比对**（`trace_compare.py` 的 `DEFAULT_COLS`，iss/README.md §3 表 L48）⇒
  // 留空既如实（TB 无文本来源）又不影响判据；若将来要填，须由 TB 侧反汇编器产出并显式开启 `--with-asm`
  // （那是**放宽/口径变更**，须登记，不许顺手开）。**本处留空不是"没写完"，是映射表的规定动作。**
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cyc_q      <= '0;
      n_retired  <= '0;
      n_exc      <= '0;
      n_intr     <= '0;
      n_mispred  <= '0;
      n_br       <= '0;
      n_load     <= '0;
      n_store    <= '0;
      halted     <= 1'b0;
    end else if (!halted) begin
      cyc_q <= cyc_q + 1'b1;

      // ---- 退休行（§4.1 映射表逐列：pc｜(空)｜gpr｜csr｜binary｜mode｜(空)｜(空)）----
      if (retire_fire) begin
        $fwrite(fd, "%08x,,%s,%s,%08x,%s,,\n",
                pc, gpr_field(rd_idx, rd_wb_en, rd_data),
                csr_field(csr_wr_en, csr_addr, csr_new), instr, mode_str(priv));
        n_retired  <= n_retired + 1'b1;
        n_exc      <= n_exc + exc_v;
        n_intr     <= n_intr + is_intr;
        n_mispred  <= n_mispred + mispred;
        n_br       <= n_br + is_br;
        n_load     <= n_load + ((mem_v && !mem_wr) ? 1'b1 : 1'b0);
        n_store    <= n_store + ((mem_v && mem_wr) ? 1'b1 : 1'b0);
      end

      // ---- 停机判据（riscv-tests：向 `tohost` 写 1 = PASS）----
      // 判据面：`mem_v && mem_wr && (mem_addr == TOHOST_ADDR)`——**store 且地址命中**即停机事件；
      // `mem_size` **不参与**判据（riscv-tests 惯例是 4 B `sw`，但写成 `sd/sb` 也是同一语义的停机；
      // 收紧到 size==W 只会在写法变化时假不命中，不得当判据）。命中后值语义照 `__main__.py:cmd_run()`：
      //   `val==1` ⇒ PASS（退出码 0 口径）；否则 = `(testnum<<1)|1` 的 FAIL 编码 ⇒ 报 FAIL 行并 `$fatal`。
      // 值取 `mem_wdata` **整 64 位**：`SW` 的数据是否符号扩展至 64 位，spec 未定（TODO 见文末）
      //   ——但本判据只对 `==1` 判等，两口径（零扩/符号扩）在 `==1` 上等价，不影响 PASS 判定。
      if (halt_fire) begin
        halted <= 1'b1;
        $fflush(fd);                              // `$finish`/`$fatal` 前先落盘（不能只靠 final 段）
        if (mem_wdata == 64'd1) begin
          $display("[rt_t_trace_writer] HALT_PASS tohost=0x%010x val=0x%0x rows=%0d cyc=%0d",
                   mem_addr, mem_wdata, n_retired + retire_fire, cyc_q + 1'b1);
          $finish;
        end else begin
          $display("[rt_t_trace_writer] HALT_FAIL tohost=0x%010x val=0x%0x testnum=%0d rows=%0d",
                   mem_addr, mem_wdata, (mem_wdata >> 1), n_retired + retire_fire);
          $fatal(1, "[rt_t_trace_writer] tohost value != 1 => program self-reported FAIL (riscv-tests)");
        end
      end

      // ---- watchdog（红线 R9：2,000,000 拍；对应批中止判据 AB6 的单用例形态）----
      // 用**本地**拍计数而非 `rt_t.cycle`：后者是"仅性能统计/不参与比对"的成员，DUT 未产出时恒 0，
      // 拿它做超时判据等于把 watchdog 关掉（且会让 TB 依赖一个不参与比对的量）。
      if (cyc_q >= MAX_CYCLES) begin
        halted <= 1'b1;
        $fflush(fd);                              // 超时也要留证：先把已写行落盘再 $fatal
        $display("[rt_t_trace_writer] WATCHDOG_TIMEOUT cyc=%0d >= MAX_CYCLES=%0d rows=%0d (rows done; R9/AB6)",
                 cyc_q, MAX_CYCLES, n_retired + retire_fire);
        $fatal(1, "[rt_t_trace_writer] watchdog timeout: no tohost write within %0d cycles", MAX_CYCLES);
      end
    end
  end

  // -------------------------------------------------------------------------
  // ⑥ 收尾：关闭文件 + 一行汇总证据（红线 R8：判定必须有显式证据行）
  //   汇报口径＝「登记值 + 当拍在途」（`retire_fire`/`halt_fire`）：`$finish` 与退休登记同拍时
  //   nonblocking 尚未落地，直接报 `n_retired` 会比实际落盘行数少 1（探针实测踩过）。
  //   `$fatal`（HALT_FAIL/watchdog）路径未必走到本段 ⇒ 那两条路径各自先 `$fflush` 留证。
  // -------------------------------------------------------------------------
  final begin
    if (fd != 0) $fclose(fd);
    $display("[rt_t_trace_writer] CLOSE csv=%s rows=%0d exc=%0d intr=%0d mispred=%0d br=%0d load=%0d store=%0d cyc=%0d halted=%0b",
             csv_path, n_retired + retire_fire, n_exc, n_intr, n_mispred, n_br, n_load, n_store,
             cyc_q, halted | halt_fire);
  end

  // -------------------------------------------------------------------------
  // 未消费成员（如实列出，防"看起来全接了"的误读；均为**不参与比对**或本批无判据的成员）：
  //   · `csr_old`——ISS-013 已定 `csr` 列取写后新值；旧值是 §7 三条规定 #1「异常指令自身的
  //     错误写由内存镜像点 + `csr_old` 覆盖」的**备用**证据面，本批无对应判据（归 M1-S4 的
  //     异常专项）；
  //   · `mem_rdata`——与 `rd_data` 同值（§3.21①），CSV 无该列；
  //   · `is_c`——首版无 C 展开（`spec/02` §5）⇒ 恒 0；
  //   · `mem_size`/`csr_addr`（当 `csr_wr_en=0` 时）/`seq`/`cycle`——见上；`mispred`/`seq`/`cycle`
  //     仅进计数与调试，**绝不混进 8 列**（混了会把"两边都有但值不同"误判成 mismatch，
  //     trace.py 头部注释同款理由）。
  //
  // 未做（显式标注，不假装完成）：
  //   1. TODO(M1-S4)：**多 lane** 写出。冻结端口面（§6 L862）只有单条 `rt_valid_o`/`rt_o` ⇒
  //      本批按 1 条/拍实现。若 M1-S5 需要 `COMMIT_WIDTH=4` 的逐 lane 展开，须先在冻结面里
  //      给出 4 lane 端口（属**接口变更**，走升版 + RR，不许在 TB 侧自造 lane 展开）；
  //   2. TODO(M1-S4)：写出器的**仿真级自证**（合成 retire 向量 → 实际 CSV vs 期望件逐字节）未在本批
  //      做——本批的自证走"两端同规"路线：`sim/golden/tb_format_expect.csv`（按本模块同一套规则渲染）
  //      vs `sim/golden/iss_smoke.csv` 由 `trace-format-contract` 判据 ③ 判 0 mismatch，本模块的
  //      表头/ABI 名表由判据 ② 与 `iss/vriss/trace.py` 逐字机判。**逐字节闭合**（本模块实际产出 vs
  //      `tb_format_expect.csv`）在 M1-S4 拿到 RTL 侧 30 条后一次性做（两件同规 ⇒ 应逐字节相等）；
  //   3. TODO(M1-S4)：`rt_ready` 反压协议——本模块是**零延迟纯监视器**（落盘即时、不倒逼 DUT），
  //      故不接 `rt_ready`；该端口归顶层 TB 驱动（`vr1_core.rt_ready`，§6），真实反压语义随
  //      M15/RT 级落地；
  //   4. TODO(M1-S4)：`SW` 的 `mem_wdata` 是否符号扩展至 64 位（停机判据的值口径）——spec/01 §3.21
  //      未写；本模块按**整 64 位判 1**（两口径在 `==1` 上等价），待 spec 落文后同步注释；
  //   5. TODO(M1-S4)：异常条目的 `gpr`/`csr` 清零口径。本模块**刻意不做** `exc_v` 特判：空串只由
  //      `rd_wb_en`/`csr_wr_en` 决定（= trace.py 唯一规则）。§7 三条规定 #1「仅异常条目自身
  //      `gpr`/`csr`/`mem` 清零且两侧同规则」在 ISS 侧是"该条目的写使能本为 0"的自然结果，
  //      TB 侧再特判一次等于**额外放宽**（会掩盖"异常条目仍置 rd_wb_en=1"这类 DUT 缺陷）；
  //      若首轮比对在此处报 mismatch，按 §7 归因到 RTL 侧写使能，而不是改本模块。
  // -------------------------------------------------------------------------

endmodule

`endif // RT_T_TRACE_WRITER_SV
