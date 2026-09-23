#==============================================================================
# run_cmd/vr1_smoke.tcl — VR1 冒烟运行脚本（vsim -do source 目标）
# 片号：D-7 平台骨架（ModelSim-only）
# 口径：必须由 vsim 以 `-do "source run_cmd/vr1_smoke.tcl"` 载入（Tcl 正斜杠）；
#       **尾部必带 quit -f**，否则 -c 模式不退出会挂住。
# 判据（ADR-5）：退出码不作判据；判据＝UVM 报告行 / 断言 / 覆盖率命中（红线 R8）。
# 状态：D-7 片未实跑（无 DUT）；DUT 接入后随 run_cmd/vr1_flow.do 使用。
#==============================================================================

# D-7 占位：用例由命令行 +UVM_TESTNAME=vr1_smoke_test 选择（见 vr1_flow.do）
run -all
quit -f
