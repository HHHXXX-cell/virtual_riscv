//=============================================================================
// filelist/tb_m1_e2e.f — M1 端到端冒烟的 **TB 侧**编译单元清单
//   （**必须与 filelist/rtl.f 同批编译**，且必须排在 rtl.f 的单元之后）
// 路径一律相对仓库根（vlog 从仓库根调用）
// 分层（本表＝本冒烟的 TB 侧单元；**DUT 侧单元一律取自 filelist/rtl.f，不在本表重复列举**）：
//   单元1  tb/unit/rt_t_trace_writer.sv —— `rt_t`→CSV 写出器 + 停机判据 + watchdog（DUT 无关件）
//   单元2  tb/unit/m1_e2e_cov.sv        —— 首批功能覆盖模型（covergroup）＋ SVA 断言（**纯监视器**；
//                                          **2026-09-26 心跳第 8 轮新增**；VP 号／`spec/11` 规则号
//                                          逐条写在件头，消费方＝`run_cmd/cover_rv1.py` 的 `-cvg` 面）
//   单元3  tb/unit/m1_e2e_tb.sv         —— 例化 `vr1_core` ＋ 内存桩 ＋ 写出器 ＋ 覆盖模型；跑真镜像
// 判据（本片＝**阶段证据** + `rtl-vs-iss` 的产出侧）：
//   同批 vlog 的 `-- Compiling` 计数 == filelist/rtl.f 条目数 + 本表条目数，且 vlog/vopt/vsim
//   逐段 `Errors: 0` ＋ 逐条退休证据行 ＋ 写出器 `HALT_PASS`/`CLOSE` 行。
//   **注（`m1_e2e_cov.sv` 为何必须在**本表**里）**：它引 `vr1_pkg::rt_t`／`RESET_PC`
//   ⇒ 必须与 `rtl.f` 的 `vr1_pkg` 同批编译（`filelist/tb_unit.f` 无 DUT 包，收不了它）；
//   上面的计数不变式随本表条目数自动对齐（追加一行即同步）。
//   **为什么不 bind**（如实登记）：实测（心跳第 8 轮探针）任何形式的 `bind` 都会让 vlog 多出
//   一行 `-- Compiling package <名>_sv_unit` ⇒ `m2-rv64ui`／`rtl-vs-iss`／`regress_rv1.compile_design`
//   的「计数 == 清单条目数」不变式会 fail-closed 报错；判据本体不许动 ⇒ 改用 TB 例化＋层次化采样口。
// 为什么不入 filelist/rtl.f：`rtl.f` 表头明写「本表**不含 tb/**」（域分离），且 `rtl-compile` 的
//   不变式是「计数 == rtl.f 条目数」——把 TB 件塞进去会同时破坏不变式与域分离。
// 为什么不入 filelist/tb_unit.f（DUT 无关的 TB 单元件清单）：本件例化 `vr1_core`，
//   **单独编译不成单元**，只能与 rtl.f 同批编。
// 注意：沙箱独占见 AGENTS.md §5 规则 10；新增单元件时按序追加，且保持 `+incdir+` 行在前。
//=============================================================================
+incdir+rtl/vr1/include

tb/unit/rt_t_trace_writer.sv
tb/unit/m1_e2e_cov.sv
tb/unit/m1_e2e_tb.sv
