# ADworkflo Verification Commands

把当前项目的验证命令写在这里。主窗口执行任务时，优先按这里跑。

## 默认命令

```powershell
# 示例，按项目实际技术栈替换
# npm test
# npm run lint
# npm run typecheck
```

## 规则

- 只跑能证明验收标准的最小确定性检查。
- 优先使用项目已有脚本，例如 `package.json`、`pyproject.toml`、`Makefile`、CI 配置里的命令。
- 跳过命令时，必须在 `.adworkflow/verification_result.json` 写清原因。
- 没有真实运行并成功的命令，不能写进 `passed`。
