# LoopX 采用者登记机制

这是一个由项目和用户自愿维护、自己声明的公开目录。登记表示公开关系，不代表
testimonial、认证、安全审查、支持承诺或 maintainer 背书。

维护者基于公开证据观察的[生态采用清单](../community/ecosystem-adoption.zh-CN.md)
仍然是独立的证据表面。根目录的 [`ADOPTERS.md`](../../ADOPTERS.md) 用于项目和用户
主动描述自己的使用，也允许登记计划中或实验中的试用。

## 当前目录

目前还没有公开自报条目。这是有意保持的空状态：只有项目或用户愿意被公开点名时，
才添加自己。

## 登记方式

项目或用户可以通过一个小型 PR 添加、更新或删除自己的行。无需提供内部账号、内部
部署、credential、客户信息、raw transcript 或无法由公开证据支撑的效果结论。

复制以下格式，只填写能够公开支持的内容：

```md
| 项目或用户 | 公开链接 | Integration / Workflow / Learning / Derivative | active / experimental / planned / paused | 一句话说明公开使用方式和边界 | YYYY-MM-DD |
```

登记时：

1. 使用公开项目、个人主页、issue、PR、release 或文档链接；
2. 说明实际使用了什么，以及处于计划中还是已经运行；
3. 除非有公开证据，不要把某项结果归因于 LoopX；
4. 运行仓库的 public/private 边界和文档检查；
5. 按 [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 对 commit 做 DCO sign-off。

这是一个有界的 public-doc 变更。拥有 merge 权限的协作者在检查通过后可以自合并；
没有该权限的项目或用户可以提交同样的小型 PR，走正常 maintainer 合并路径。添加条目
不会授予仓库、产品、支持或背书权限。

条目所有者可以随时请求删除。对于失效链接、混淆关系、私有内容或缺乏支持的结论，
maintainer 可以要求更新或移除，并保留公开变更历史。
