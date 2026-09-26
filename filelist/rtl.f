//=============================================================================
// filelist/rtl.f — VR1 DUT 编译单元清单（G1-I 冻签后：rtl/ 进实现期）
// 路径一律相对仓库根（vlog 从仓库根调用：vlog -64 -sv -f filelist/rtl.f）
// 分层（本表＝编译单元层；**顺序即编译顺序**，包必须先于消费它的模块）：
//   单元1  rtl/vr1/include/vr1_pkg.sv  —— 参数件 + 类型件 的包裹包（`include 生成件，禁手改）
//   单元2  rtl/vr1/frontend/vr1_bp.sv    —— M01 预测器（M1-S1：顺序/静态预测，预测不跳转）
//   单元3  rtl/vr1/frontend/vr1_ftq.sv   —— M02 FTQ（M1-S1：16 项队列，ftq_req_t → ftq_entry_t）
//   单元4  rtl/vr1/frontend/vr1_ifetch.sv—— M03 取指（M1-S1 窗对齐/IBUF ＋ M1-S2 逐窗 drain 握手）
//   单元5  rtl/vr1/ctrl/vr1_decode.sv    —— M05 译码（M1-S2：IBUF 消费 ＋ G1-I 14 条 ＋ pre_exc）
//   单元6  rtl/vr1/exu/vr1_bru.sv        —— M10 分支解析（M1-S3：BEQ/JAL 解析 ＋ br_resolve_t）
//   单元7  rtl/vr1/exu/vr1_exu_int.sv    —— M09 整数执行单元（M1-S3b：ALU/SHIFT/MUL/DIV·REM）
//   单元8  rtl/vr1/ctrl/vr1_csr.sv       —— M17 CSR 单元（M1-S3b：六件 ＋ trap 进场 ＋ MRET）
//   单元9  rtl/vr1/ctrl/vr1_trap.sv      —— M18 trap 单元（M1-S3b：excp_t 组装 ＋ mtvec 重定向）
//   单元10 rtl/vr1/lsu/vr1_lsu.sv        —— M11 访存单元（M1-S3b：LW/SW ＋ 非对齐 fault）
//   单元11 rtl/vr1/ctrl/vr1_rob.sv       —— M15 ROB 提交级（M1-S3b：单条在飞 ＋ commit_t/rt_t）
//   单元12 rtl/vr1/core/vr1_core.sv    —— DUT 顶层（G1-I 冻结端口面；前端＋译码＋后端最小通路）
// 判据（script/flow.py 的 rtl-compile）：`-- Compiling` 计数 == 本表 .sv 行数，且逐段 `Errors: 0`
// 注意：本表**不含 tb/**（TB 编译清单见 filelist/tb.f）；沙箱独占见 AGENTS.md §5 规则 10。
//       新增模块时按 M01~M20（doc/spec/00 §6）逐块追加，且保持包在前。
//=============================================================================
+incdir+rtl/vr1/include

rtl/vr1/include/vr1_pkg.sv
rtl/vr1/frontend/vr1_bp.sv
rtl/vr1/frontend/vr1_ftq.sv
rtl/vr1/frontend/vr1_ifetch.sv
rtl/vr1/ctrl/vr1_decode.sv
rtl/vr1/exu/vr1_bru.sv
rtl/vr1/exu/vr1_exu_int.sv
rtl/vr1/ctrl/vr1_csr.sv
rtl/vr1/ctrl/vr1_trap.sv
rtl/vr1/lsu/vr1_lsu.sv
rtl/vr1/ctrl/vr1_rob.sv
rtl/vr1/core/vr1_core.sv
