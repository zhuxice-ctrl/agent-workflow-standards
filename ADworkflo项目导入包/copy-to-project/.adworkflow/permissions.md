# ADworkflo Permissions

这个文件定义当前项目里 Agent 可以做什么、什么需要先问你。

## 默认允许

- 读取 `task_spec` 和 `context_manifest` 需要的项目文件。
- 修改当前任务明确需要的文件。
- 运行本地构建、lint、typecheck、单元测试、冒烟测试。
- 更新 `.adworkflow/` 下的工作流 artifacts。

## 需要先确认

- 安装、升级、删除依赖。
- 修改公开 API、数据库 schema、权限、鉴权、计费、部署、密钥处理。
- 删除文件、移动大目录、对无关文件做大范围格式化。
- 调用外部生产服务，或修改远程状态。

## 默认禁止

- 回滚用户未要求回滚的改动。
- 把长聊天记录当作交接材料。
- 未经要求编辑项目根目录之外的文件。
- 没有写 `verification_result.json` 就声称任务完成。
