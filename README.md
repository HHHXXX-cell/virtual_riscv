# virtual_riscv — VR1 超标量乱序 RV64GC 处理器

**AI 会话入口**：先读 [AGENTS.md](AGENTS.md)（项目级上下文与红线），再按其中的知识库路由条款查
`D:\IC验证知识库\AI索引.md`。工作流程遵守
`D:\IC验证知识库\AI验证工作流\AI验证工作流.md` 的九步流水线。

## 项目一句话

从零设计一个代号为 **VR1** 的 RV64GC 乱序处理器核：SystemVerilog 可综合 RTL + 自研 Python
golden ISS + UVM 1.2 验证平台，按"**规格先行 → 接口冻结 → 一次性实现**"的路线推进。

## 当前阶段（2026-09-22 暂停点）

**P0 环境骨架完成 + P1 规格书 / P2 ISS 并行推进中**（见 [doc/04-验证进度.md](doc/04-验证进度.md)）：
`doc/spec/` 已成 2/14 篇；`iss/` golden ISS 骨架已跑通冒烟测试。`rtl/` 为空——接口冻结（Review G1）
之前不允许出现实现代码，这是设计如此不是丢失。

**换到另一台电脑继续**：必读 [doc/交接说明.md](doc/交接说明.md)（搬什么、改哪几处路径、
一条命令校验仓库完好、AI 接续提示词）。

## 目录

| 目录 | 内容 | 可写性 |
|---|---|---|
| `AGENTS.md` | AI 项目级上下文：目录约定/工具链命令/签核标准/18 条工作规则 | 每阶段更新 |
| `doc/` | 九步产出物 `00~10` + `spec/`（规格书 14 篇）+ `环境搭建.md` + `交接说明.md` | AI 可写 |
| `doc/spec/` | ★ 当前主线交付：VR1 微架构规格书 | AI 可写 |
| `doc/项目开发流程.md` | **项目级流程定义**：阶段/门禁（TR↔Review↔基线）、验证策略五问、场景 12 维与验证点 34 法的 VR1 映射、七大收敛指标、四方归因链 | 人批准后方可变更 |
| `doc/00-问题记录.md` | 问题台账（红线 R4），发现即登记 | AI 必写 |
| `rtl/vr1/` | 设计代码 | **基线后只读**（红线 R1，口径见 AGENTS.md §5.1） |
| `tb/vr1_uvm/` | UVM 1.2 验证平台与用例 | AI 工作区 |
| `iss/` | Python golden ISS + trace 归一化 + 比对脚本（用法见 [iss/README.md](iss/README.md)） | AI 工作区 |
| `sw/` | 链接脚本 / crt0 / bare-metal 测试 / riscv-tests 接入 | AI 工作区 |
| `filelist/` | 编译清单 `.f` | AI 工作区 |
| `run_cmd/` | Makefile、vsim do/tcl、回归 runner、riscv-dv target | AI 工作区 |
| `script/` | 构建与解析脚本；临时件放 `script/tmp/` 用完即删 | AI 工作区 |
| `sim/` | 仿真工作目录；`sim/covdb/` 为**签核证据受保护区** | 产物区 |
| `debug/` | 问题定位/取证文档（按《问题分析方法论》§4A 七段骨架） | AI 工作区 |

## 工具链双轨

- **Windows**：`D:\modeltech64_2020.4`（ModelSim SE-64 2020.4，自带预编译 UVM 1.2 win64 +
  `vcover`）→ UVM 平台、功能/代码覆盖率、签核。
- **WSL2 Ubuntu**：riscv64-unknown-elf-gcc + Spike + Verilator → 编译测试程序、ISS-vs-ISS 互检、
  长跑回归与性能。**尚未安装**，命令清单见 [doc/环境搭建.md](doc/环境搭建.md)。

分工纪律：**性能指标不在 ModelSim 上测**（SE 跑 10^7 拍量级不现实），CoreMark/Dhrystone/IPC 一律
走 Verilator + `doc/spec/13` 的 Python 周期近似模型交叉核对。

## 参照实现与规范（本地已有，不重新下载）

| 资料 | 路径 |
|---|---|
| RISC-V 卷 I/卷 II 规范 PDF + 全文提取件 | `D:\IC验证知识库\_tools\riscv-spec.pdf`、`_tools\extracted\riscv_spec\riscv_spec_full.txt` |
| riscv-dv 指令生成器 | `D:\IC验证知识库\_tools\riscv-dv-master` |
| 参考核源码 | `_tools\picorv32-main`、`_tools\ibex-master`、`_tools\cv32e40p-master` |
| AXI 组件 | `_tools\axi-master` |
| 超标量/乱序设计空间 | `D:\IC验证知识库\Verilog与CPU设计知识库\CPU卷\04-高性能超标量CPU精读.md` |
