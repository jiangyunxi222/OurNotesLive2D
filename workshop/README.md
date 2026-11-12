# OurNotes 创意工坊资产

对应分支为 `workshop/live2dviewerex`，共 44 个角色，发布状态为草稿。

## 文件位置

- 角色目录保存模型、贴图、动作、物理数据、语音和资源清单。
- `catalog.json` 索引全部角色资料卡。
- `characters/<角色编号>/entry.json` 关联角色资源、封面、发布信息和验证状态。
- `characters/<角色编号>/metadata.json` 可通过 EX Studio 标题旁的导入按钮载入。
- `characters/<角色编号>/cover.png` 是使用该角色第一套衣装渲染的 768 × 768 封面。

在仓库根目录运行 `python workshop/validate.py` 检查资料与资源引用。

## 更新

资源随仓库版本管理。主分支更新后合并到本分支，同步资料卡中的数量、名称和封面，并运行检查。已发布条目的 `workshopId` 用于后续更新。

EX Studio 生成的 WPK 和打包中间文件保存在 `workshop/build/`。该目录使用 Git 忽略规则。

## 待办

当前菜单依赖独立面板后台。创意工坊订阅版的原生菜单适配和 WPK 导入验证记录为 `pending`，待适配验证通过后发布。其他角色标签的核对状态记录在对应资料卡中。
