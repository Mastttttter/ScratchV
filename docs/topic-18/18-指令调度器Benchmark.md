# 课题 18：Benchmark 与 CI 报告

将固定功能用例、实际编译输出和合成规模测试分别展示。所有数字均由本次运行产生。

## 固定功能用例：编译器集成与真实执行

在仓库根目录运行（本地虚拟环境可使用 `.venv/bin/python`）：

```bash
python -m benchmarks.run_inst_scheduler_case
```

默认读取 `benchmarks/cases/inst_scheduler_feature.asm`，输出：

- `benchmark_reports/inst_scheduler_report.json`
- `benchmark_reports/inst_scheduler_report.md`

先将同一份汇编分别交给 `CompilerDriver._run_asm_passes` 的 `schedule=False` 和 `schedule=True, schedule_strict=True` 配置，确认启用后的输出与 `schedule_assembly` 一致，再编码前后汇编并分别用真实 TinyFive 执行。其它汇编优化开关均使用关闭的默认值。

用例依次执行 load、依赖 load 的 add、独立 addi、store。调度后将 addi 放到 load 与 add 之间。初始状态固定为 `a0=1024`、`t2=7`、其它寄存器为零；数据区为 16 个字，首字为 9，其余为零。

| 指标 | 调度前 | 调度后 |
| --- | ---: | ---: |
| 源汇编指令数 | 4 | 4 |
| 局部模型周期（估算） | 5 | 4 |
| 局部模型停顿（估算） | 1 | 0 |
| 编码机器指令数 | 4 | 4 |
| 代码大小（字节） | 16 | 16 |
| TinyFive 实际执行指令数 | 4 | 4 |

执行比较覆盖全部 32 个整数寄存器和数据区的 16 个字。默认用例的预期结果为 `t0=9`、`t1=16`、`t3=1`、`memory[1028]=16`，测试同时检查这些值。运行器要求用例确实发生有收益的换序，且前后执行结果一致；TinyFive 缺失、执行失败或结果不一致都会生成 FAIL 报告并返回非零退出码，不允许静态分析替代执行。

这个执行入口只接受有界的直线整数代码，固定 `a0`，访存限定在上述数据区内的对齐 `lw/sw`。分支、调用、浮点或任意地址的程序不能使用“执行指令数等于编码指令数”的终止方法，因此会被明确拒绝。

## 实际编译输出：同一份汇编的静态 A/B

```bash
python -m benchmarks.run_inst_scheduler_case \
  benchmark_reports/cnn_scratchv.s --static-only \
  --json benchmark_reports/inst_scheduler_cnn.json \
  --markdown benchmark_reports/inst_scheduler_cnn.md
```

该命令同样通过编译器的调度开关处理相同输入，记录 SHA-256、源指令数、调度模型、建模覆盖率、移动指令数、区域状态、诊断以及优化器耗时。所有无收益、遇到边界或超过大小上限的区域都保留在报告中。

`--static-only` 的 JSON 类型为 `assembly-ab`，执行状态为 `not_run`，`output_equal` 为 `null`。它不声称 CNN 已经端到端执行，也不报告未经编码或执行测量的机器码大小和动态指令数。零收益是有效测量结果，不导致失败；没有指令被建模时，Markdown 中的周期和停顿显示 `N/A`。

`status=passed` 表示报告运行和相应校验通过；`comparison_status` 单独区分 `changed`（已换序）、`no_improvement`（无收益）和 `not_modeled`（未建模）。当前 standalone CNN 列表包含数字分支偏移，例如 `bne t4, zero, -48`，会触发调度器的整份输入保留规则。本地报告因此为 `not_modeled`，不能解释为 CNN 加速或已完成 CNN 执行验证。源指令数不计入 `_op_/layer1/Conv:` 这类显示标签，JSON 的 `scheduling` 保留调度器原始诊断与计数。

## 合成规模测试

```bash
python -m benchmarks.bench_inst_scheduler --repeats 3 \
  --json benchmark_reports/inst_scheduler_synthetic.json \
  --markdown benchmark_reports/inst_scheduler_synthetic.md
```

使用固定种子 42，覆盖 10、50、100、200、500、1000、5000 条指令。默认区域上限为 1024，因此 5000 条的整块用例跳过并显示 `N/A`；可用 `--max-region-size` 调整上限。

JSON 继续使用数组格式并保留原有统计字段，新增 `benchmark_type=synthetic`、输入哈希、种子、重复次数、区域上限、区域数量与 `execution_verified=false`。原有周期字段仍为模型对已覆盖区域的求和；必须结合 `modeled` 和 `skipped` 解读，不能将未建模的零计数当作完整程序耗时。

## 统计口径与 CI

- 模型周期只表示局部调度区域的静态估算，假设区域入口操作数就绪，不包含缓存、分支预测和程序路径执行次数。
- 优化器耗时是主机执行调度 pass 的时间，以重复运行的均值和标准差报告，不是目标程序运行时间。
- TinyFive 提供固定用例的执行结果与动态指令数，不能证明硬件周期下降。调度只改变顺序，示例中的指令数和代码大小保持不变。
- CI 的固定用例和合成测试分别生成报告；CNN 步骤生成 `cnn_scratchv.s` 后，再运行静态 A/B。该输入沿用现有 CNN 编译步骤的 `--const-merge` 输出，比较两侧使用完全相同的汇编，只切换调度。
- 三组 JSON/Markdown 都由现有 `benchmark-reports` artifact 收集，Markdown 同时写入 GitHub Actions Job Summary。报告文件属于生成产物，保留在已被忽略的 `benchmark_reports/` 中。
