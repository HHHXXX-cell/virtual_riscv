//=============================================================================
// filelist/tb_unit.f — TB **单元级**编译单元清单（无 UVM、无 DUT 包；域分离见 rtl.f 表头）
// 路径一律相对仓库根（vlog 从仓库根调用）
// 分层（本表＝编译单元层）：
//   单元1  tb/unit/rt_t_trace_writer.sv       —— `rt_t`→CSV 写出器 + 停机判据 + watchdog（DUT 无关）
//   单元2  tb/unit/rt_t_trace_writer_smoke.sv —— 上件的单元冒烟驱动（合成 retire 记录；只编译在环）
// 判据（script/flow.py 的 tb-compile）：`-- Compiling` 计数 == 本表 .sv 条目数，且 `Errors: 0`
// 注意：本表**不含** `tb/vr1_uvm/**`（UVM 平台清单见 filelist/tb.f，需 UVM src 的 +incdir）、
//       也**不含** `rtl/**`（DUT 清单见 filelist/rtl.f：域分离，DUT 与平台各自成清单）。
//       新增 TB 单元件时按序追加，且保持 `+incdir+` 行在前。
//=============================================================================
+incdir+rtl/vr1/include

tb/unit/rt_t_trace_writer.sv
tb/unit/rt_t_trace_writer_smoke.sv
