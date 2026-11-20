你好，感谢你花时间逐条比对，也感谢你指出这些问题。下面按你第一节的顺序逐条说明来源，
再说五个接口的处理情况。两个项目都是 GPL-3.0，许可上兼容。

先说结论：你列的条目里，**分类表、排除表、封面候选表、DNS、更新镜像表、CDN 兜底 IP 表
确实参考了 LytVPK**；**测速算法和下载器不是**（你判断得对）；**五个线上接口已全部删除**，
没有任何回退到你的服务的兜底路径。

## 一、逐项说明

### 1.1 工坊分类表 —— 参考了

`qml/components/WorkshopPage.qml` 的 `groups` 是六组、47 个 Steam 标签，
分组方式、组内顺序、中文显示名沿用了你的 `WORKSHOP_CATEGORIES`
（[sidebar.js L12-L90](https://github.com/LaoYutang/lytvpk/blob/c8c68819695dfc282c4d059f62e0bf7742befc50/frontend/src/js/features/workshop/sidebar.js#L12-L90)）。

改动只有 2 处显示名：「幸存者」→「干员」、「散弹枪」→「霰弹枪」。
标签本身是 Steam 公开分类，这里一致的是「分成哪六组、按什么顺序排」这套组织方式。
数据用 QML 数组重写，不是移植 JS 代码。已在文件对应位置注明出处。

### 1.2 工坊浏览流程 —— 参考了（产品设计层面）

分类筛选、单件／合集切换、热门／最新／评分排序、ID 直达、卡片详情、稍后看、
合集子项展开 —— 这套页面结构参考了 LytVPK。代码是独立写的（QML + Python，
和你 Wails/Go + 原生 JS 的实现不同）。

### 2.1 人物识别排除表 —— 参考了

`app/vpk_reader.py` 的 `_NON_CHARACTER_DIRS` 与你的 `uiAssetRoots`
（[asset_scope.go L5-L45](https://github.com/LaoYutang/lytvpk/blob/c8c68819695dfc282c4d059f62e0bf7742befc50/internal/parser/asset_scope.go#L5-L45)）对比：

| 项 | LytVPK | 本项目 |
| --- | --- | --- |
| `materials/vgui/` | 有 | 有 |
| `materials/sprites/` | 有 | **无** |
| `resource/` | 有 | 有 |
| `scripts/` | 有 | 有 |
| `particles/` | 有 | 有 |
| `sound/ui/` | 有 | 有 |

匹配方式也不同：你用 `strings.Contains`（任意位置包含），本项目用 `startswith`（前缀）。
后面的角色证据目录和关键词表是本项目自己整理的。

### 2.2 包内封面与类型识别 —— 参考了

`PREVIEW_CANDIDATES` 里那 3 个**目录型**模式
（`materials/vgui/maps/menu/`、`materials/vgui/loadingscreen`、`resource/overviews/`）
及其顺序，与你的 `previewPatterns` 一致
（[parser.go L312-L368](https://github.com/LaoYutang/lytvpk/blob/c8c68819695dfc282c4d059f62e0bf7742befc50/internal/parser/parser.go#L312-L368)）。

差异：你第一级只精确找 `addonimage.jpg`，本项目把 `addonimage.jpg / .png / .jpeg`
按扩展名列成元组；你第二级混了 `.jpg`/`.jpeg`/`.png` 这类扩展名模式，本项目不用，
改成先用 `guess_image_ext_from_name()` 确认是图片、再套目录前缀。

`.bsp` 判地图 → 否则人物 → 否则武器的**优先级阶梯**，参考了你的 `DetermineVPKType`
（[detector.go L15-L46](https://github.com/LaoYutang/lytvpk/blob/c8c68819695dfc282c4d059f62e0bf7742befc50/internal/parser/detector.go#L15-L46)）；
三条武器目录也一样。差异：你扫到 `.bsp` 直接 `break` 定类型，本项目只置标志位、
把目录扫完再判（同一份结果还要给出人物/武器的全部证据）。落点在 `app/modmanager.py`。

`ADDON_KEYS` 键表是本项目按实际 VPK 归纳的，不是移植。

### 2.3 加载顺序编辑器 —— 交互参考，格式独立

「从 MOD 工具栏打开、拖动整行、显示真实标题和文件名、缺失项标红、写回 `addonlist.txt`」
这套交互形态参考了 LytVPK。差异：本项目新增文件要**手动同步**，你那边自动列出并标绿。

文件格式处理（`app/addonlist.py`）独立实现，强调的是三件实测出来的事：
LF 换行、**GBK 编码**（不是 UTF-8）、值 `1`/`0` 表示启用/禁用。这部分是本项目自己踩坑总结的。

### 3.1 工坊 DNS —— 跨语言移植，已注明

`app/workshop_dns.py` 的 `_lookup_ipv4` 确实是按你的 `lookupIPv4`
（[workshop_dns.go L81-L115](https://github.com/LaoYutang/lytvpk/blob/c8c68819695dfc282c4d059f62e0bf7742befc50/internal/network/workshop_dns.go#L81-L115)）
用 Python 重写的。沿用：同一条响应内顺 CNAME 找 A、只回 CNAME 时再查目标名、
`maxWorkshopCNAMEHops = 8` 跳上限、成环检测、中文报错措辞。`WorkshopDialer` 的
「Host 与 SNI 保持域名、socket 只连 IP」思路也来自你。

本项目改动：自带 DNS 报文编解码（UDP，失败回落 TCP）；把「TCP 建连 + TLS 握手」
算一次尝试、失败换下一个 IP（你的 `DialContext` 只管 TCP，握手交给 `http.Transport`，
握手卡住的节点会拖死整个请求）；解析失败回落到系统解析并写 warning。
已在模块 docstring 顶部加「出处与改动」小节，附上游链接。

### 3.2 应用更新检查 —— 参考了

`app/updater.py` 的 `MIRRORS` 这 8 个镜像**及其顺序**取自你的
[update.go L43-L57](https://github.com/LaoYutang/lytvpk/blob/c8c68819695dfc282c4d059f62e0bf7742befc50/internal/app/update.go#L43-L57)；
「从最终重定向 URL 的 `/tag/` 末段取版本号」也是从你这儿学的。

本项目改动：镜像探测改为**并发**（你那边串行，8 个镜像各超时一次最坏 26 秒 ——
这正是本项目以前「检查更新一直转圈」的原因，并发后 2~4 秒）；
「下载 + 替换 exe + 失败回滚」自己重写。已在 docstring 和 `MIRRORS` 上方注明。

### 4.1 CDN 候选节点兜底表 —— 参考了

`BUILTIN_CDN_IPS` 这 6 个 IP 及**排列顺序**取自你的 `defaultSteamCDNIPs`
（[ip_selector.go L29-L37](https://github.com/LaoYutang/lytvpk/blob/c8c68819695dfc282c4d059f62e0bf7742befc50/internal/network/ip_selector.go#L29-L37)）。
已在常量上方注明。

差异：你那份是「远端节点池不可用时兜底」；本项目**已经没有任何远端节点池**，
这份表就是唯一来源。地名表 `IP_REGION_HINTS` 是自己整理的。

### 4.2 测速算法 —— 独立实现（你判断得对）

本项目（`_probe_one`）：TCP 443 建连 → TLS 握手（SNI 用域名）→ HTTP `HEAD` 一个
CDN 路径，量总耗时选最低，不测吞吐。
你的做法：先测 TCP 80 延迟取前五，再用 64 KiB 预热 + 512 KiB Range 实测吞吐，
都失败才回退延迟最低。这部分不主张相同。

### 5.1 工坊解析后端 —— 曾调用，已完全移除

这是你意见里最关键的一条，**确实曾经把你的解析 Worker 作为首选后端**。现在已全部删除：

- `workshop_dl.py`：`PARSE_API` / `WORKSHOP_DETAIL_API` / `WORKSHOP_DETAIL_BACKUP` 三个常量已删，
  只剩官方 `ISteamRemoteStorage/GetPublishedFileDetails` 与 `GetCollectionDetails`；
- `mods.py`：`WORKSHOP_RELAY_DETAIL` 已删；
- `workshop_net.py`：`CDN_POOL_URL` / `WORKSHOP_LIST_BASE` 已删，
  工坊列表改走官方 `IPublishedFileService/QueryFiles`（要用户自己的 key）；
- `servers.py`：`MAP_API` 已删，地图中文名改纯内置表。

全仓库现在搜 `laoyutang` 只剩注释里的历史说明，没有任何可执行调用路径。

### 5.2 下载器 —— 独立实现（你说不认定为照搬，我同意）

本项目是「多文件并发、单个文件流式写盘」，没有 Range 分块、没有续传校验、没有进度落盘。
实际 VPK 文件从 `file_url` 直拉，不经过你的 Worker。

### 6. 服务器收藏与管理 —— 部分参考

「收藏、权重排序、状态与玩家详情、地图中文名、直连、配置导入导出、面板配置」
这份**功能清单**参考了 LytVPK。但：

- 配置格式不同（本项目用 `l42d.servers` 标识 + 合集名 + 多面板的对象结构）；
- A2S 查询协议（`FF FF FF FF 54 …`，含 challenge 处理）按 Valve 公开文档自己实现；
- 服务器分组、按前缀+同 IP 归并、拖拽 JSON 导入这些是本项目自己加的；
- 地图中文名查你的线上服务那一段**已删除**（见 5.1）。

## 二、五个线上接口的处理

| 接口 | 现状 |
| --- | --- |
| `GET l4d2-workshop.laoyutang.cn/list` | **已移除**，改官方 `QueryFiles`（用户自己的 key） |
| `GET l4d2-workshop.laoyutang.cn/detail?id=…` | **已移除**，改官方 `GetPublishedFileDetails` |
| `POST l4d2-workshop-parse.laoyutang.cn/` | **已移除**，改官方批量 `GetPublishedFileDetails` |
| `GET lytvpk-get-ips.laoyutang.cn/` | **已移除**，只用内置 6 个 IP 表 |
| `GET l4d2-maps.laoyutang.cn/{mapCode}` | **已移除**，改纯内置地图名表 |

没有任何「回退到你的服务」的兜底路径。

关于「项目自带中转站」那句 README 措辞：**已更正**。原文确实会让人以为是本项目自己的服务，
实际是你的。现在 README 的「致谢」一节写明早期版本曾请求你的接口、占用你的额度、并已全部移除。

## 三、README 的致谢

原来冗长的「功能来源与致谢」已精简为「致谢」一节，明确：

1. 感谢 LytVPK（作者 LaoYutang）在产品思路与部分技术方案上的参考价值；
2. 列出参考范围（工坊浏览、加载顺序编辑器、更新检查、CDN 优选）；
3. 说明 VPK 解析、A2S 查询、网盘链接提取、B 站登录为独立实现；
4. 说明早期曾调用你的五个接口、现已全部移除。

## 四、想请你确认两点

1. **纯数据表**（分类表、IP 表、镜像表）：本项目按「沿用分组/顺序，数据用本语言重写」
   处理，并在文件里注明了出处。如果你希望这几张表也在文件头加更明确的
   「本表数据来自 LytVPK，GPL-3.0」版权行，我可以照做 —— 你说一声就改。
2. **发布版本**：上述改动（五个接口迁移 + README 来源说明）会一起随 **v1.0.1** 发布，
   发布后会在该 Issue 补一条链接。

再次感谢你的耐心比对。如果还有我漏掉或说错的地方，请直接指出。
