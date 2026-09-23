#==============================================================================
# run_cmd/vr1_flow.do — VR1 平台编译/仿真流程模板（ModelSim SE-64 2020.4）
# 片号：D-7（平台骨架·ModelSim-only 片，R4 验证面）
# 判据口径（ADR-5）：**退出码不作判据**；判据＝产物证据行——
#   ① vlog 日志中 `-- Compiling` 行数（= 编译单元装载数）
#   ② 段末 `** Error` / `** Warning` 行数（以实跑输出末行为权威源）
#   仿真侧另按红线 R8：UVM 报告 / 断言 / 覆盖率命中，三选一为显式证据。
# 用法（两种等价；均从仓库根执行，filelist 路径相对仓库根）：
#   a) ModelSim 会话内： do run_cmd/vr1_flow.do
#   b) 命令行：          vsim -64 -c -do "source run_cmd/vr1_flow.do" -l sim/run_r4_d7/flow.log
# 沙箱：库/日志/INI 一律落 sim/run_<runner_id>/（红线 R10；本文件用 run_r4_d7）
# 状态：D-7 片只实跑 vlib/vmap/vlog 三段（证据见 doc/verify/05 R-050）；
#       vopt/vsim 两段待 DUT 接入后实跑，**未跑前不得视为已验证**。
#==============================================================================

set RUNDIR sim/run_r4_d7
file mkdir $RUNDIR
if {![file exists $RUNDIR/modelsim.ini]} { set _fh [open $RUNDIR/modelsim.ini w]; close $_fh }
set env(MODELSIM) [file normalize $RUNDIR/modelsim.ini]

# ---- 建库与映射（UVM 1.2 预编译库在安装目录）----
vlib $RUNDIR/work
vmap work $RUNDIR/work
vmap mtiUvm D:/modeltech64_2020.4/uvm-1.2

# ---- 编译（覆盖率开关编译期必带；不含 rtl/，RTL 尚未存在）----
vlog -64 -sv -cover bcesf -ntb_opts uvm-1.2 -f filelist/tb.f -l $RUNDIR/vlog_compile.log

# ---- 优化 + 批仿真（vsim 行＝source 式；Tcl 正斜杠；quit -f 在被 source 的 tcl 内）----
vopt -64 -cover=bcesf work.vr1_top_tb -o work_opt
vsim -64 -c -coverage +UVM_TESTNAME=vr1_smoke_test -do "source run_cmd/vr1_smoke.tcl" -l $RUNDIR/vsim_smoke.log work_opt
