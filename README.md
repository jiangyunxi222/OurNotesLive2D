# OurNotesLive2D

整理后的 Live2DViewerEX 资源：44 个角色，230 套衣装。

完整复制角色目录并导入 `00_integrated` 主入口。

## 新版菜单

主菜单提供「动作」「表情」「换装」「声音与控制」「关闭菜单」。换装及各级列表均可直接返回主菜单。

- 点击身体上的语音区域只播放语音，不展开主菜单或播放控制菜单；再次点击可以切换语音。
- 从菜单中主动选择语音时，仍显示字幕、重播、停止和返回按钮。
- 表情保持至下一次选择，使用「清除表情」恢复。
- 新动作或「停止并回到待机」可解除动作保持，操作菜单无需等待动画结束。
- 「声音与控制 → 恢复默认 / 解除保持」清除动作、表情及参数锁定；「关闭菜单」仅关闭操作框。

更新后请完整重载 `00_integrated` 主入口，确保旧实例中的控制器已卸载；仅切换衣装不会更新父模型。

## 角色索引

| 团体 | 角色 | 衣装数 | 整合入口 |
|---|---|---:|---|
| Ave Mujica | 三角初华 | 11 | [导入入口](<Ave Mujica/三角初华/00_integrated.model3.json>) |
| Ave Mujica | 丰川祥子 | 9 | [导入入口](<Ave Mujica/丰川祥子/00_integrated.model3.json>) |
| Ave Mujica | 八幡海铃 | 9 | [导入入口](<Ave Mujica/八幡海铃/00_integrated.model3.json>) |
| Ave Mujica | 祐天寺若麦 | 7 | [导入入口](<Ave Mujica/祐天寺若麦/00_integrated.model3.json>) |
| Ave Mujica | 若叶睦 | 15 | [导入入口](<Ave Mujica/若叶睦/00_integrated.model3.json>) |
| MyGO!!!!! | 千早爱音 | 10 | [导入入口](<MyGO!!!!!/千早爱音/00_integrated.model3.json>) |
| MyGO!!!!! | 椎名立希 | 9 | [导入入口](<MyGO!!!!!/椎名立希/00_integrated.model3.json>) |
| MyGO!!!!! | 要乐奈 | 6 | [导入入口](<MyGO!!!!!/要乐奈/00_integrated.model3.json>) |
| MyGO!!!!! | 长崎素世 | 7 | [导入入口](<MyGO!!!!!/长崎素世/00_integrated.model3.json>) |
| MyGO!!!!! | 高松灯 | 7 | [导入入口](<MyGO!!!!!/高松灯/00_integrated.model3.json>) |
| millsage | 伊泽枣 | 7 | [导入入口](<millsage/伊泽枣/00_integrated.model3.json>) |
| millsage | 和泉朋花 | 8 | [导入入口](<millsage/和泉朋花/00_integrated.model3.json>) |
| millsage | 汐见萤 | 4 | [导入入口](<millsage/汐见萤/00_integrated.model3.json>) |
| millsage | 泽海奏多 | 6 | [导入入口](<millsage/泽海奏多/00_integrated.model3.json>) |
| millsage | 滨崎茉幌 | 9 | [导入入口](<millsage/滨崎茉幌/00_integrated.model3.json>) |
| millsage | 琴平凪 | 8 | [导入入口](<millsage/琴平凪/00_integrated.model3.json>) |
| millsage | 琴平树 | 3 | [导入入口](<millsage/琴平树/00_integrated.model3.json>) |
| 一家Dumb Rock! | 佣人（sub_shizukus_maid） | 1 | [导入入口](<一家Dumb Rock!/佣人（sub_shizukus_maid）/00_integrated.model3.json>) |
| 一家Dumb Rock! | 四宫宁月 | 7 | [导入入口](<一家Dumb Rock!/四宫宁月/00_integrated.model3.json>) |
| 一家Dumb Rock! | 奶奶（sub_raikas_grandmother） | 1 | [导入入口](<一家Dumb Rock!/奶奶（sub_raikas_grandmother）/00_integrated.model3.json>) |
| 一家Dumb Rock! | 妈妈（sub_mikus_mother） | 1 | [导入入口](<一家Dumb Rock!/妈妈（sub_mikus_mother）/00_integrated.model3.json>) |
| 一家Dumb Rock! | 宁月的母亲 | 1 | [导入入口](<一家Dumb Rock!/宁月的母亲/00_integrated.model3.json>) |
| 一家Dumb Rock! | 宁月的父亲 | 1 | [导入入口](<一家Dumb Rock!/宁月的父亲/00_integrated.model3.json>) |
| 一家Dumb Rock! | 梅里千樱梨 | 6 | [导入入口](<一家Dumb Rock!/梅里千樱梨/00_integrated.model3.json>) |
| 一家Dumb Rock! | 爸爸（sub_mikus_father） | 1 | [导入入口](<一家Dumb Rock!/爸爸（sub_mikus_father）/00_integrated.model3.json>) |
| 一家Dumb Rock! | 矢仓蓬咲 | 5 | [导入入口](<一家Dumb Rock!/矢仓蓬咲/00_integrated.model3.json>) |
| 一家Dumb Rock! | 须贺蕾叶 | 7 | [导入入口](<一家Dumb Rock!/须贺蕾叶/00_integrated.model3.json>) |
| 一家Dumb Rock! | 马桥心玖 | 9 | [导入入口](<一家Dumb Rock!/马桥心玖/00_integrated.model3.json>) |
| 其他角色 | 蕾叶父亲的秘书 | 1 | [导入入口](<其他角色/蕾叶父亲的秘书/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | A子 | 1 | [导入入口](<夢限大みゅーたいぷ/A子/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | Raki | 1 | [导入入口](<夢限大みゅーたいぷ/Raki/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 丸君 | 1 | [导入入口](<夢限大みゅーたいぷ/丸君/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 仲町阿拉蕾 | 11 | [导入入口](<夢限大みゅーたいぷ/仲町阿拉蕾/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 千石由乃 | 6 | [导入入口](<夢限大みゅーたいぷ/千石由乃/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 宫永野乃花 | 8 | [导入入口](<夢限大みゅーたいぷ/宫永野乃花/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 小春 | 2 | [导入入口](<夢限大みゅーたいぷ/小春/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 峰月律 | 9 | [导入入口](<夢限大みゅーたいぷ/峰月律/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 歌美 | 1 | [导入入口](<夢限大みゅーたいぷ/歌美/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 波塔 | 1 | [导入入口](<夢限大みゅーたいぷ/波塔/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 波波 | 1 | [导入入口](<夢限大みゅーたいぷ/波波/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 经纪人（sub_yumemita_manager） | 2 | [导入入口](<夢限大みゅーたいぷ/经纪人（sub_yumemita_manager）/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 蓓儿 | 1 | [导入入口](<夢限大みゅーたいぷ/蓓儿/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 薇欧拉 | 2 | [导入入口](<夢限大みゅーたいぷ/薇欧拉/00_integrated.model3.json>) |
| 夢限大みゅーたいぷ | 藤都子 | 7 | [导入入口](<夢限大みゅーたいぷ/藤都子/00_integrated.model3.json>) |

模型 ID 独立，换装由固定父模型管理。仅提交处理后的模型配置、运行资源、清单和必要说明，不包含原始 LPK、备份及处理工具。

配置与资源引用已校验；样本做过官方接口冒烟检查，完整鼠标点击实测尚未完成。素材权利归原权利人。

## 统一点击规则

| 实际点击位置 | 效果 |
|---|---|
| 头顶、刘海上部 | 切换表情 |
| 脸部下半部 | 随机语音，按开关显示字幕 |
| 上身中央 | 播放普通动作 |
| 画面右侧手臂 | 角色左臂动作 |
| 画面左侧手臂 | 角色右臂动作 |
| 腰部、衣服中段 | 直接随机换装 |
| 腿部、衣服下段 | 打开主菜单 |

每套衣装均包含七个独立矩形点击区，按该衣装默认站姿的头部和身体比例定位，跟随模型整体移动和缩放。点击层保持透明，衣服网格合并或隐藏不会取消入口。动作造成的局部身体变形不会改变矩形分区。

仅头像形态也保留相同布局，上身、腰部、腿部入口位于头像下方的透明区域，左右手入口位于对应两侧。

表情、语音和身体动作不会展开菜单。缺少方向动作时播放普通动作，缺少素材时保持待机。点击分区之间的空白可打开主菜单。

请完整重载 `00_integrated` 主入口，保留 `assets/hitareas` 中的点击层文件。

语音菜单可切换字幕显示，默认开启，并在同一角色换装后保留。

语音字幕默认开启，同一角色换装后保留设置。尚未收录语音的角色，点击语音区显示「当前角色未提供语音素材」，此提示不受字幕开关影响。

原有带语音角色按各角色原有数量重建，无法追溯或属于他人的旧条目以来源明确的本角色语音替换。祖母与经纪人另归回 12 条，合计 701 条。各角色 assets/voices/voice-sources.json 记录实际说话者、台词、音频来源及校验值。
