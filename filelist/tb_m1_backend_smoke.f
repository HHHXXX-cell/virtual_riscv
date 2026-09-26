//=============================================================================
// filelist/tb_m1_backend_smoke.f — M1-S3b 后端三件定向冒烟的 **TB 侧**编译单元清单
//   （**必须与 filelist/rtl.f 同批编译**，且必须排在 rtl.f 的单元之后）
// 路径一律相对仓库根（vlog 从仓库根调用）
// 分层（本表＝本冒烟的 TB 侧单元；**DUT 侧单元一律取自 filelist/rtl.f，不在本表重复列举**）：
//   单元1  tb/unit/exu_int_smoke_tb.sv  —— M09 整数执行单元（值 ＋ MUL_LAT/DIV_LAT 占用）
//   单元2  tb/unit/csr_trap_smoke_tb.sv —— M17 CSR（六件/写使能/trap 进场/MRET）＋ M18 重定向
//   单元3  tb/unit/lsu_smoke_tb.sv      —— M11 访存（AGU/符号扩展/非对齐码 4·6 且不发请求）
// 判据（本片＝**阶段证据**；后端三件的集成面由 `rtl-vs-iss`（`filelist/tb_m1_e2e.f`）承担）：
//   同批 vlog 的 `-- Compiling` 计数 == filelist/rtl.f 条目数 + 本表条目数，且 vlog/vopt×3/vsim×3
//   逐段 `Errors: 0` ＋ 三件各自 `cases=… n_fail=0` 与 `PASS` 行。
// 为什么不入 filelist/rtl.f：`rtl.f` 表头明写「本表**不含 tb/**」（域分离），且 `rtl-compile` 的
//   不变式是「计数 == rtl.f 条目数」——把 TB 件塞进去会同时破坏不变式与域分离。
// 为什么不入 filelist/tb_unit.f（DUT 无关的 TB 单元件清单）：三件均例化 RTL 模块（引用 `vr1_pkg`），
//   **单独编译不成单元**，只能与 rtl.f 同批编。
// 注意：沙箱独占见 AGENTS.md §5 规则 10；新增单元件时按序追加，且保持 `+incdir+` 行在前。
//=============================================================================
+incdir+rtl/vr1/include

tb/unit/exu_int_smoke_tb.sv
tb/unit/csr_trap_smoke_tb.sv
tb/unit/lsu_smoke_tb.sv
