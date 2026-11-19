// Yumi的L4D2工具箱
// Copyright (C) 2026 ZengDeRong
// 
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, version 3.
// 
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
// 
// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import L4D2

// 服务器页：左边一列「值班台」卡片，右边一块检查员面板（详情 + 玩家）。
// 整套是照着这个程序自己的语言画的：深色底 + 左侧强调色细边 + 信号格 +
// 等宽字体写地址，不跟创意工坊页共用抽屉那一套。
Item {
    id: page
    objectName: "serversPage"

    property var mgr: (typeof core !== "undefined" && core) ? core.servers : null
    property var selected: null            // 当前选中的那一台（servers 里的 dict 副本）
    property string playersFor: ""         // 玩家列表对应哪台
    property var players: []
    property string playersError: ""
    property bool playersLoading: false
    property string sortMode: mgr ? mgr.sortMode : "players"
    property string addrInput: ""

    // ---- 搜索
    // 只搜「我自己起的名字 + 服务器自报名 + 地址 + 模式 + 地图 + 地区标签」，
    // 不碰权重/延迟这些数字 —— 那些已经有排序了，再混进搜索只会更难找。
    property string query: ""
    // ---- 合集（同一「系列」/ 同 IP 的服自动归到一起）
    // ★ 用户明确要的交互：**不是折叠展开**，而是单独空出一块地方「选合集」。
    //   折叠展开的问题是：收起时看不到组里有哪些服、展开又把列表撑得很长，
    //   而且和「分类筛选条」挤在一起容易混。
    //   现在左侧一个独立的合集选择器（竖排），点哪个就只看哪一组，
    //   主列表永远是干净的一列服务器。
    property string groupKey: "all"     // 当前选中的合集，all = 全部

    // ---- 诊断接口（给测试脚本验「悬浮按钮和数据区不重叠」）
    // 卡片自己会在 Component.onCompleted 后把几何写进这里，
    // 比 Python 遍历 item 树可靠（无头环境下 childItems() 常常拿不到）。
    property var cardGeometry: ({})

    readonly property var groupList: (page.mgr && page.mgr.groups)
                                      ? page.mgr.groups : []

    // 当前合集收录的地址集合（all 时为空 = 不过滤）
    readonly property var groupAddrs: {
        var gs = page.groupList
        for (var i = 0; i < gs.length; ++i) {
            if (gs[i].key === page.groupKey)
                return gs[i].addrs || []
        }
        return []
    }

    // 点合集：切到那一组；再点一次「全部」就回全量
    function selectGroup(key) {
        page.groupKey = key
        // ★ 换合集必须把分类重置回「全部」。
        //   用户报的「某个合集没有战役，切到另一个合集就什么都不显示」：
        //   分类停在「战役」上，而新合集里一台战役服都没有 → 列表被双重过滤成空，
        //   看起来像「这个合集坏了」。合集是主筛选条件，换组就该从头看。
        page.category = "all"
        // 告诉后端当前合集：分类条的数字必须跟着合集走，
        // 否则会出现「分类上写 5、点进去一个都没有」。
        if (page.mgr)
            page.mgr.setGroupFilter(key)
        // 换合集等于换了一份列表，回到顶部是合理的
        srvList._anchorAddr = ""
        srvList.positionViewAtBeginning()
    }


    // ---- 多选删除
    // 进入「选择」模式后每张卡片左边出现勾选框，底部浮出一条操作栏。
    // 只是勾选不影响单击查看详情 —— 那个在非选择模式下照旧。
    property bool selectMode: false
    property var checked: ({})        // addr -> true

    function enterSelect() {
        page.selectMode = true
        page.checked = ({})
    }

    function exitSelect() {
        page.selectMode = false
        page.checked = ({})
    }

    function toggleChecked(addr) {
        var next = ({})
        var cur = page.checked || {}
        for (var k in cur) {
            if (cur[k])
                next[k] = true
        }
        if (next[addr]) delete next[addr];
        else next[addr] = true;
        page.checked = next;
    }

    function checkedCount() {
        var n = 0
        var cur = page.checked || {}
        for (var k in cur)
            if (cur[k]) n++
        return n
    }

    // 全选 / 全不选（只作用于**当前可见**的那些，符合直觉：
    // 筛了分类之后「全选」不该把看不见的也选上）
    function setAllChecked(on) {
        var next = ({})
        if (on) {
            var rows = page.visibleServers
            for (var i = 0; i < rows.length; ++i)
                next[rows[i].addr] = true
        }
        page.checked = next
    }

    function removeChecked() {
        if (!page.mgr)
            return
        var picked = []
        var cur = page.checked || {}
        for (var k in cur)
            if (cur[k]) picked.push(k)
        if (picked.length === 0)
            return
        var res = page.mgr.removeMany(picked)
        if (res && res.ok) {
            page.exitSelect()
            if (page.selected && picked.indexOf(page.selected.addr) >= 0)
                page.selected = null
        }
    }
    property var allServers: mgr ? mgr.servers : []
    // 经过「合集 + 分类 + 搜索」过滤后的列表（不再折叠，永远一列平铺）
    readonly property var filteredServers: page.filterServers(
        page.filterByGroup(
            page.filterByCategory(page.allServers, page.category)),
        page.query)

    readonly property var visibleServers: page.filteredServers
    readonly property int matchCount: page.visibleServers.length

    // 按合集过滤：groupKey 为 all 时不过滤
    function filterByGroup(rows) {
        if (!page.groupKey || page.groupKey === "all")
            return rows || []
        var addrs = page.groupAddrs
        if (!addrs || addrs.length === 0)
            return rows || []
        var out = []
        for (var i = 0; i < (rows || []).length; ++i) {
            if (addrs.indexOf(rows[i].addr) >= 0)
                out.push(rows[i])
        }
        return out
    }


    // 分类列表：只列有服务器的那些（后端 categories 已经算好）
    //
    // ★ `category` 这个属性**必须显式声明并给默认值 "all"**。
    //   之前被前面的改动误删了，于是 `page.category` 是 undefined：
    //     · 分类条里 `page.category === modelData.key` 永远为 false
    //       → 没有任何一个分类显示为「选中」，看着像「分类选不了」
    //     · `filterByCategory(rows, undefined)` 走进「不过滤」分支，
    //       点了分类也不会有反应
    //   QML 里给未声明的属性赋值**不会报错**（会当成动态属性），
    //   所以这个坑很隐蔽 —— 界面画得出来，就是点了没反应。
    property string category: "all"

    readonly property var categoryList: (page.mgr && page.mgr.categories)
                                          ? page.mgr.categories : []

    function filterByCategory(rows, key) {
        if (!key || key === "all")
            return rows || []
        var out = []
        for (var i = 0; i < (rows || []).length; ++i) {
            if ((rows[i].category || "other") === key)
                out.push(rows[i])
        }
        return out
    }

    function filterServers(rows, text) {
        var q = (text || "").trim().toLowerCase()
        if (q.length === 0)
            return rows || []
        // 空格分词：多个词是「都要命中」，和常见搜索习惯一致
        var words = q.split(/\s+/).filter(function (w) { return w.length > 0 })
        var out = []
        for (var i = 0; i < (rows || []).length; ++i) {
            var row = rows[i]
            var hay = [
                row.name || "", row.liveName || "", row.addr || "",
                row.modeLabel || "", row.map || "", row.mapName || "",
                row.mapTitle || "", row.chapter || "", row.tag || ""
            ].join(" ").toLowerCase()
            var hit = true
            for (var w = 0; w < words.length; ++w) {
                if (hay.indexOf(words[w]) < 0) {
                    hit = false
                    break
                }
            }
            if (hit)
                out.push(row)
        }
        return out
    }

    function clearQuery() {
        page.query = ""
        searchField.text = ""
        searchField.forceActiveFocus()
    }

    // ---------------------------------------------------- 配置导出 / 导入
    // 文件选择框在 Main.qml（那里已经有一堆 FileDialog）；
    // 这里只发信号，选完由 Main 回调 `onExportChosen(path)`。
    signal requestExport()
    signal requestImport()
    // 拖拽导入：把 .json 文件拖进服务器页，直接走批量导入
    signal requestDropImport(var paths)

    function askExport() {
        if (!page.mgr || page.mgr.serverCount === 0) {
            page.hintText = "列表里还没有服务器，没什么可导出的"
            page.hintAt = Date.now()
            return
        }
        page.requestExport()
    }

    function askImport() {
        page.requestImport()
    }

    // 多选状态下导出：只导出勾中的那些（后端 exportConfig 支持 addrs 参数）
    function askExportChecked() {
        if (!page.mgr)
            return
        var picked = []
        var cur = page.checked || {}
        for (var k in cur)
            if (cur[k]) picked.push(k)
        if (picked.length === 0) {
            page.hintText = "先勾选要导出的服务器"
            page.hintAt = Date.now()
            return
        }
        page.exportAddrs = picked
        page.requestExport()
    }

    // 当前要导出的地址集合（空 = 全部）
    property var exportAddrs: []

    // 拖进来的一堆文件 → 交给 Main 去调 importConfigs
    function handleDropped(urls) {
        var paths = []
        for (var i = 0; i < (urls || []).length; ++i) {
            var u = String(urls[i] || "")
            if (u.length === 0)
                continue
            // file:///C:/x/y.json → C:/x/y.json
            u = u.replace(/^file:\/\/\//, "").replace(/^file:\/\//, "")
            try { u = decodeURIComponent(u) } catch (e) { }
            paths.push(u)
        }
        if (paths.length === 0)
            return
        page.requestDropImport(paths)
    }

    // ---------------------------------------------------- 分享 / 从文字导入
    // 分享：后端把一台服务器写成一段人话并塞进剪贴板，这里只负责弹窗给用户看
    // 一眼（万一手滑复制错了，能立刻发现）。
    // 从文字导入：把剪贴板 / 聊天记录里的一段话粘进来，抠出 ip:port 再加。
    property bool shareOpen: false
    property string shareText: ""
    property string shareAddr: ""
    property bool pasteOpen: false
    property string pasteText: ""
    property var pasteInfo: ({})

    function askShare(row) {
        if (!row || !page.mgr) {
            page.hintText = "先选一台服务器再分享"
            page.hintAt = Date.now()
            return
        }
        var res = page.mgr.shareServer(row.addr)
        page.shareText = (res && res.text) || ""
        page.shareAddr = row.addr
        page.shareOpen = page.shareText.length > 0
        if (!res || res.ok !== true) {
            page.hintText = (res && res.error) || "分享失败"
            page.hintAt = Date.now()
        }
    }

    function openPaste() {
        page.pasteText = ""
        page.pasteInfo = ({})
        page.pasteOpen = true
        pasteInput.forceActiveFocus()
    }

    // 粘进来的文字一变就实时预览「这里面有几台、几台是新的」
    function refreshPaste() {
        if (!page.mgr) {
            page.pasteInfo = ({})
            return
        }
        page.pasteInfo = page.mgr.parseShareText(page.pasteText)
    }

    function readClipboardIntoPaste() {
        var info = page.mgr ? page.mgr.scanClipboard() : null
        if (!info || !info.text) {
            page.pasteText = ""
            page.pasteInfo = ({})
            return
        }
        page.pasteText = info.text
        page.refreshPaste()
        pasteInput.forceActiveFocus()
    }

    function submitPaste() {
        if (!page.mgr)
            return
        var res = page.mgr.importFromText(page.pasteText)
        if (res && res.ok === true) {
            page.pasteOpen = false
            page.hintText = ""
        } else {
            page.hintText = (res && res.error) || "没导入成功"
            page.hintAt = Date.now()
        }
    }

    // Ctrl+F 用：把光标直接放进搜索框（并全选已有内容，方便直接覆盖重搜）
    function focusSearch() {
        searchField.forceActiveFocus()
        searchField.selectAll()
    }

    // 程序侧改了 query（清空 / 恢复 / 别处设置的）时，把文字同步进输入框。
    // 输入框的 text 不再绑定 query（见 searchField 上的注释），所以这里要手工对待：
    // 只在内容真的不一样时才写，否则会把用户正在输入的光标位置顶掉。
    Connections {
        target: page
        function onQueryChanged() {
            if (searchField.text !== page.query)
                searchField.text = page.query
        }
    }

    readonly property color accent: Theme.accent
    readonly property color okColor: "#3FBF6E"
    readonly property color warnColor: Theme.warn
    readonly property color offColor: "#E5534B"

    // ------------------------------------------------------------ 小工具
    function modeColor(mode) {
        switch (mode) {
        case "coop": return Theme.cyan
        case "versus": return Theme.pink
        case "realism": return "#B98BFF"
        case "realismversus": return "#8D6BFF"
        case "survival": return "#F0A93B"
        case "scavenge": return "#4FC3D9"
        case "mutation": return "#E2754A"
        default: return Theme.textDim
        }
    }

    function stateColor(state) {
        if (state === "online") return okColor
        if (state === "querying") return warnColor
        if (state === "off") return offColor
        return Theme.scrim(0.35)
    }

    function pingBars(ms) {
        if (!ms || ms <= 0) return 0
        if (ms < 80) return 4
        if (ms < 150) return 3
        if (ms < 260) return 2
        return 1
    }

    function pingColor(ms) {
        var b = pingBars(ms)
        if (b >= 3) return okColor
        if (b === 2) return warnColor
        return offColor
    }

    function titleOf(row) {
        if (!row) return ""
        if ((row.name || "").length > 0)
            return row.name
        return (row.liveName || "").length > 0 ? row.liveName : row.addr
    }

    function mapText(row) {
        if (!row) return ""
        if ((row.mapTitle || "").length > 0)
            return row.mapTitle + ((row.chapter || "").length > 0 ? " · " + row.chapter : "")
        return row.map || "地图未知"
    }

    function selectServer(row) {
        page.selected = row
        page.loadPlayers(row)
    }

    function loadPlayers(row) {
        if (!page.mgr || !row)
            return
        if (page.playersFor === row.addr && (page.players || []).length > 0
                && row.state === "online")
            return
        page.playersFor = row.addr
        page.players = []
        page.playersError = ""
        page.playersLoading = true
        page.mgr.requestPlayers(row.addr)
    }

    function addFromInput() {
        var text = (page.addrInput || "").trim()
        if (!page.mgr || text.length === 0)
            return
        var res = page.mgr.addServer(text)
        if (res && res.ok) {
            page.addrInput = ""
            page.selected = null
        } else if (res && res.error) {
            page.hintText = res.error
            page.hintAt = Date.now()
        }
    }

    property string hintText: ""
    property double hintAt: 0
    property string noteDraft: ""
    // 提示条停留多久（毫秒）。只给「出错 / 被拦住」这类需要看一眼的用。
    readonly property int hintHoldMs: 5000

    // 哪些状态文字值得占用页头那一行？
    // 原则：**只显示需要人注意的**。成功类动作（已添加/已保存/已移出）不占位置，
    // 有 toast 兜着就够了；「查完了 N/M 个在线」这种结果看页头读数即可。
    function isTransientHint(text) {
        var t = String(text || "")
        if (t.length === 0)
            return false
        // 这些是「出问题了 / 被拦住」，必须让人看到
        var important = ["失败", "连不上", "解析不了", "看不懂", "不合法",
                         "没找到", "没装", "重复", "不在列表", "空", "错误"]
        for (var i = 0; i < important.length; ++i) {
            if (t.indexOf(important[i]) >= 0)
                return true
        }
        return false
    }

    // ---- 添加 / 编辑对话框
    property bool formOpen: false
    property bool formEditing: false
    property string formOldAddr: ""
    property string formName: ""
    property string formAddr: ""
    property string formWeight: "0"
    property bool formAdvanced: false
    property bool formClearPw: false
    property string formError: ""

    // ---- IP 直连对话框
    property bool directOpen: false
    property string directInput: ""
    property string directPreview: ""
    property string directError: ""

    ListModel { id: formPanelModel }

    // 无参版本：工具条「添加服务器」按钮和截图脚本都调它
    function openAdd() {
        page.openAddDialog(null)
    }

    // ------------------------------------------------------ 添加服务器的三种模式
    // 「单条 / 批量 / 扫描」都在同一个「添加服务器」弹窗里切，不再有独立弹窗：
    //   · 加一台      → 单条
    //   · 一整段文字  → 批量
    //   · 扫某个 IP   → 扫描（端口遍历）
    // 用户反馈「端口遍历单独一个界面」和「批量单独一个弹窗」都太散，
    // 而且独立弹窗一多，剪贴板提示还会到处抢焦点。
    property bool formBulk: false
    property string bulkText: ""
    property var bulkPreview: ({})
    property string bulkError: ""

    // 端口遍历（现在跑在添加服务器弹窗里，不再有自己的 scanOpen）
    property bool formScan: false
    property string scanHost: ""
    property int scanFrom: 27015
    property int scanTo: 27025
    property bool scanRunning: false
    property int scanDone: 0
    property int scanTotal: 0
    property string scanNow: ""
    property var scanResults: []
    property var scanChecked: ({})   // addr -> true，选中的

    // 用来判断「添加服务器」弹窗现在是哪个模式：0=单条 1=批量 2=扫描
    readonly property int formMode: page.formScan ? 2 : (page.formBulk ? 1 : 0)

    function switchToScan() {
        page.formBulk = false
        page.formScan = true
        page.bulkError = ""
        page.scanResults = []
        page.scanChecked = ({})
        page.scanRunning = false
        page.scanDone = 0
        page.scanTotal = 0
        page.scanNow = ""
        scanHostInput.forceActiveFocus()
    }

    // 兼容旧入口：以前工具条上有一颗「批量添加」按钮，现在合进「添加服务器」了。
    // 保留这个函数是因为截图脚本 / 测试还在调它。
    function openBulk() {
        page.openAddDialog(null)
        page.switchToBulk()
        bulkInput.forceActiveFocus()
    }

    function refreshBulk() {
        if (!page.mgr) {
            page.bulkPreview = ({})
            return
        }
        page.bulkPreview = page.mgr.parseShareText(page.bulkText)
    }

    function readClipboardIntoBulk() {
        var info = page.mgr ? page.mgr.scanClipboard() : null
        if (!info || !info.text) {
            page.bulkText = ""
            page.bulkPreview = ({})
            return
        }
        page.bulkText = info.text
        page.refreshBulk()
        bulkInput.forceActiveFocus()
    }

    function submitBulk() {
        if (!page.mgr)
            return
        var info = page.bulkPreview || {}
        var addrs = info.freshAddrs || []
        if (addrs.length === 0) {
            page.bulkError = (info.total || 0) > 0
                             ? "这些服务器都已经在收藏里了" : "没找到服务器地址"
            return
        }
        var res = page.mgr.addMany(addrs)
        if (res && res.added > 0) {
            // 批量是「一次性动作」，加完直接关掉整个添加弹窗
            page.bulkError = ""
            page.formOpen = false
        } else {
            page.bulkError = (res && res.error) || "添加失败"
        }
    }

    // ---- 端口遍历（现在是添加服务器弹窗的第三种模式）
    // 保留 openScan 这个名字：工具条按钮和截图脚本都在调它。
    function openScan() {
        page.openAddDialog(null)
        page.switchToScan()
    }

    // 粘进来的主机如果带端口（1.1.1.1:25000），自动拆成 IP + 25000~25099。
    // 这是用户明确要的行为：从聊天记录复制一条地址粘进来就能直接扫。
    //
    // ★ 拆完要**真的把起止端口两个文本框改掉**，不能只改 page.scanFrom/scanTo。
    //   那两个 TextInput 的 text 是单向初值（不是绑定），只改属性界面不会变
    //   —— 用户看到的就是「IP 输进去后面两个框没动」。
    function normalizeScanHost() {
        var raw = String(page.scanHost || "").trim()
        if (raw.length === 0)
            return false
        var host = raw
        var low = host.toLowerCase()
        var prefixes = ["steam://connect/", "steam://", "connect "]
        for (var i = 0; i < prefixes.length; ++i) {
            if (low.indexOf(prefixes[i]) === 0) {
                host = host.substring(prefixes[i].length).trim()
                break
            }
        }
        host = host.replace(/\\/g, "/").split("/")[0].trim()
        var parts = host.split(":")
        if (parts.length !== 2)
            return false
        var port = parseInt(parts[1].trim(), 10)
        if (isNaN(port) || port < 1 || port > 65535)
            return false
        page.scanHost = parts[0].trim()
        page.scanFrom = port
        page.scanTo = Math.min(65535, port + 99)
        // 关键：把两个端口框的文字一起换掉
        scanFromInput.text = String(page.scanFrom)
        scanToInput.text = String(page.scanTo)
        return true
    }

    function startScan() {
        if (!page.mgr || page.scanRunning)
            return
        page.normalizeScanHost()
        page.scanResults = []
        page.scanChecked = ({})
        page.scanDone = 0
        page.scanNow = ""
        var res = page.mgr.scanPortRange(page.scanHost, page.scanFrom, page.scanTo)
        if (!res || res.ok !== true) {
            page.bulkError = (res && res.error) || "启动失败"
            return
        }
        // 后端可能把「IP:端口」拆开了，把结果显示回到输入框
        if (res.host && res.host !== page.scanHost)
            page.scanHost = res.host
        if (res.start && res.start !== page.scanFrom) {
            page.scanFrom = res.start
            scanFromInput.text = String(page.scanFrom)
        }
        if (res.end && res.end !== page.scanTo) {
            page.scanTo = res.end
            scanToInput.text = String(page.scanTo)
        }
        page.scanTotal = res.total
        page.scanRunning = true
    }

    function stopScan() {
        if (page.mgr && page.scanRunning)
            page.mgr.cancelScan()
        page.scanRunning = false
    }

    function onScanProgress(done, total, addr) {
        page.scanDone = done
        page.scanTotal = total
        page.scanNow = addr || ""
    }

    function onScanFinished(list) {
        page.scanRunning = false
        page.scanResults = list || []
        // 默认全选：扫出来的一般都想要
        var sel = ({})
        for (var i = 0; i < (list || []).length; ++i)
            sel[list[i].addr] = true
        page.scanChecked = sel
    }

    function scanSelectedCount() {
        var n = 0
        for (var k in page.scanChecked)
            if (page.scanChecked[k]) n++
        return n
    }

    function toggleScanAll(on) {
        var sel = ({})
        for (var i = 0; i < page.scanResults.length; ++i)
            sel[page.scanResults[i].addr] = on
        page.scanChecked = sel
    }

    function saveScanPicked() {
        if (!page.mgr)
            return
        var picked = []
        for (var i = 0; i < page.scanResults.length; ++i) {
            var r = page.scanResults[i]
            if (page.scanChecked[r.addr])
                picked.push({ addr: r.addr, name: r.name || "" })
        }
        if (picked.length === 0) {
            page.bulkError = "一台都没选"
            return
        }
        var res = page.mgr.addMany(picked)
        if (res && res.added > 0) {
            // 保存完直接关掉整个「添加服务器」弹窗
            page.formOpen = false
        } else {
            page.bulkError = (res && res.error) || "保存失败"
        }
    }


    // 无参版本：编辑当前选中的那台（面板里的「编辑」按钮也走这个法子）
    function openEdit() {
        if (page.selected)
            page.openAddDialog(page.selected)
    }

    // ---- 合集重命名（自动识别不准时的兜底）
    property string renameKey: ""
    property string renameLabel: ""
    property string renameHint: ""
    property bool renameOpen: false

    function openRenameGroup(g) {
        if (!g || !page.mgr)
            return
        page.renameKey = String(g.key || "")
        page.renameLabel = String(g.label || "")
        page.renameHint = (g.count || 0) + " 台服务器"
        page.renameOpen = true
    }

    function applyRename() {
        if (!page.mgr)
            return
        var res = page.mgr.renameGroup(page.renameKey, page.renameLabel)
        if (res && res.ok) {
            page.renameOpen = false
            // 改名后合集 key 变了（手动名是 m: 开头），回到「全部」最不容易迷路
            page.selectGroup("all")
        }
    }

    function openAddDialog(row) {
        if (!page.mgr)
            return
        page.formBulk = false
        page.formScan = false
        page.formEditing = row !== null && row !== undefined
        page.formOldAddr = page.formEditing ? row.addr : ""
        page.formName = page.formEditing ? (row.name || "") : ""
        page.formAddr = page.formEditing ? row.addr : ""
        page.formWeight = page.formEditing ? String(row.weight || 0) : "0"
        page.formAdvanced = false
        page.formClearPw = false
        page.formError = ""
        page.bulkText = ""
        page.bulkPreview = ({})
        page.bulkError = ""
        formPanelModel.clear()
        if (page.formEditing) {
            var d = page.mgr.serverDetail(row.addr)
            if (d && d.ok) {
                page.formName = d.name || ""
                page.formAddr = d.addr || row.addr
                page.formWeight = String(d.weight || 0)
                var list = d.panels || []
                for (var i = 0; i < list.length; ++i) {
                    formPanelModel.append({ url: list[i].url, password: "",
                                            hasPassword: list[i].hasPassword === true })
                }
            }
        } else {
            // 新加的先摆一行空的：展开高级就能直接填，
            // 不用先找「+ 再加一个面板」。
            formPanelModel.append({ url: "", password: "", hasPassword: false })
        }
        page.formOpen = true
    }

    // 在「添加服务器」里切到批量模式（编辑时不显示这个开关）
    function switchToBulk() {
        // ★ 必须把 formScan 也清掉：formMode 是按「formScan > formBulk > 单条」
        //   算的（readonly property int formMode: formScan ? 2 : (formBulk ? 1 : 0)）。
        //   从「扫描」切到「批量」时只设 formBulk=true、不取消 formScan 的话，
        //   formMode 仍然是 2，界面还停在扫描面板 —— 就是用户报的
        //   「从扫描点单条/批量没反应」。两个开关必须互斥。
        page.formScan = false
        page.formBulk = true
        page.bulkText = ""
        page.bulkPreview = ({})
        page.bulkError = ""
        // 切走时把扫描收尾，别留着后台线程
        if (page.scanRunning || (page.mgr && page.mgr.scanRunning))
            page.stopScan()
        page.scanRunning = false
    }

    function switchToSingle() {
        page.formScan = false
        page.formBulk = false
        page.bulkError = ""
        if (page.scanRunning || (page.mgr && page.mgr.scanRunning))
            page.stopScan()
        page.scanRunning = false
    }

    function addPanelRow() {
        formPanelModel.append({ url: "", password: "", hasPassword: false })
        page.formAdvanced = true
    }

    function removePanelRow(index) {
        if (index >= 0 && index < formPanelModel.count)
            formPanelModel.remove(index)
    }

    function submitForm() {
        if (!page.mgr)
            return
        var panels = []
        for (var i = 0; i < formPanelModel.count; ++i) {
            var r = formPanelModel.get(i)
            panels.push({ url: r.url, password: r.password })
        }
        var res = page.mgr.saveServer({
            addr: page.formAddr,
            oldAddr: page.formOldAddr,
            name: page.formName,
            weight: parseInt(page.formWeight) || 0,
            panels: panels,
            clearPassword: page.formClearPw
        })
        if (res && res.ok) {
            page.formOpen = false
            page.hintText = page.mgr.statusText
            page.hintAt = Date.now()
        } else {
            page.formError = (res && res.error) || "保存失败了"
        }
    }

    function removeFromForm() {
        if (!page.mgr || !page.formEditing)
            return
        page.mgr.removeServer(page.formOldAddr)
        if (page.selected && page.selected.addr === page.formOldAddr)
            page.selected = null
        page.formOpen = false
    }

    function openDirectDialog() {
        if (!page.mgr)
            return
        page.directInput = ""
        page.directPreview = ""
        page.directError = ""
        page.directOpen = true
    }

    function updateDirectPreview() {
        if (!page.mgr || !page.directOpen)
            return
        var text = (page.directInput || "").trim()
        if (text.length === 0) {
            page.directPreview = ""
            page.directError = ""
            return
        }
        var res = page.mgr.parseAddress(text)
        if (res && res.ok) {
            // 域名会在这里先解析成 IP —— Steam 只认 IP，界面要如实显示会连到哪个 IP
            page.directPreview = res.steamTarget || res.addr
            page.directError = ""
        } else {
            page.directPreview = ""
            page.directError = (res && res.error) || "地址不对"
        }
    }

    function submitDirect() {
        var res = page.mgr.directConnect(page.directInput)
        // 成功就关框（浮层会报「正在连接 / 已复制命令」）；
        // 失败留在框里，把原因写在输入框下面，别让玩家猜。
        if (res && res.ok)
            page.directOpen = false
        else
            page.directError = (res && res.error) || "地址不对"
    }

    // 连一台收藏里的服务器。游戏已经在跑的时候后端会把
    // `connect ip:port` 塞进剪贴板，界面用浮层把这句话说出来。
    function connectTo(row) {
        if (!page.mgr || !row)
            return
        var res = page.mgr.connectResult(row.addr)
        if (res && !res.ok)
            page.hintText = res.error || "连不上"
        page.hintAt = Date.now()
    }

    function saveDirectToForm() {
        if (!page.mgr || (page.directPreview || "").length === 0)
            return
        page.directOpen = false
        page.openAddDialog(null)
        page.formAddr = page.directPreview
    }

    onSelectedChanged: {
        page.noteDraft = page.selected ? (page.selected.name || "") : ""
        if (page.selected)
            page.loadPlayers(page.selected)
    }

    // 进入服务器页时**自动刷新一次状态**（用户要的：省得每次手动点）。
    //
    // 两道闸，避免「一直刷」：
    //  1. `_enteredOnce` —— 本次运行只自动刷第一次进页面，来回切页不会反复查；
    //  2. `_lastAutoRefresh` —— 30 秒内重复进出也不重查（防抖），
    //     但用户点「刷新状态」按钮永远立刻生效（那条路不经过这里）。
    //
    // 另外：没有任何收藏时不查（`refreshAll` 会自己说「先加一个服务器地址吧」，
    // 那句提示对一个空列表来说很吵，这里直接跳过）。
    property bool _enteredOnce: false
    property double _lastAutoRefresh: 0
    readonly property int autoRefreshCooldownMs: 30000

    function autoRefreshOnEnter() {
        if (!page.mgr || page.mgr.serverCount === 0)
            return
        if (page.mgr.busy)
            return
        var now = Date.now()
        if (page._enteredOnce && (now - page._lastAutoRefresh) < page.autoRefreshCooldownMs)
            return
        page._enteredOnce = true
        page._lastAutoRefresh = now
        page.mgr.refreshAll()
    }

    onVisibleChanged: {
        if (visible)
            page.autoRefreshOnEnter()
    }

    // 搜索把当前选中的那台筛掉了 —— 右边详情还开着它就成了「看不见的悬空选中」，
    // 玩家会以为列表卡住了。这里顺手取消选中。
    //
    // 注意这里**直接调 filterServers 重算一遍**，不要读 page.visibleServers：
    // 在 onQueryChanged 里读一个依赖 query 的绑定，拿到的是重算之前的旧值
    // （踩过：设 query 之后选中项明明被筛掉了，判定却还留在列表里）。
    onQueryChanged: {
        if (!page.selected)
            return
        var rows = page.filterServers(page.allServers, page.query)
        for (var i = 0; i < rows.length; ++i) {
            if (rows[i].addr === page.selected.addr)
                return
        }
        page.selected = null
    }

    // 首次进来就把列表接上（不然 allServers 要等到第一次 serversChanged 才有值）
    Component.onCompleted: {
        if (page.mgr) {
            page.allServers = page.mgr.servers
            // 分类条的数字必须跟着合集走（后端 categories 会读这个 key）
            page.mgr.setGroupFilter(page.groupKey)
        }
    }

    Connections {
        target: page.mgr
        function onPlayersLoaded(res) {
            if (!res || res.addr !== page.playersFor)
                return
            page.playersLoading = false
            page.players = res.players || []
            page.playersError = res.ok ? "" : (res.error || "拿不到玩家列表")
        }
        function onServersChanged() {
            // 列表数据源：搜索过滤是纯 JS 的，得自己把最新数据接过来
            if (page.mgr)
                page.allServers = page.mgr.servers
            // 选中的那一行跟着刷新（人数 / 地图会变）
            if (!page.selected)
                return
            var rows = page.allServers
            for (var i = 0; i < rows.length; ++i) {
                if (rows[i].addr === page.selected.addr) {
                    page.selected = rows[i]
                    return
                }
            }
            page.selected = null
        }
        function onStatusChanged() {
            // 以前这里把 mgr.statusText 无条件灌进 hintText，于是「查完了：1/1 个在线」
            // 这种长期状态会一直挂在页头下面（用户嫌多余）。
            // 现在只把**真正的异常/需要人看一眼的结果**显示出来：
            // 「已添加 / 已移出 / 已保存」这类成功动作不占文字位，下面有 toast 兜着。
            var t = String(page.mgr.statusText || "")
            if (t.length === 0)
                return
            if (page.isTransientHint(t)) {
                page.hintText = t
                page.hintAt = Date.now()
            }
        }
        // 端口遍历的进度与结果
        function onScanProgress(done, total, addr) {
            page.onScanProgress(done, total, addr);
        }
        function onScanFinished(list) {
            page.onScanFinished(list);
        }
    }

    // ------------------------------------------------------------ 拖拽导入
    // 把 .json 配置文件直接拖进服务器页就能导入（可以一次拖多个）。
    // 「添加服务器」弹窗、从文字导入、端口遍历都已经有各自入口，
    // 这里专门省掉「点导入 → 在文件选择框里翻目录」那几步。
    property bool dropActive: false
    DropArea {
        id: dropZone
        objectName: "srvDropZone"
        anchors.fill: parent
        // 拖拽时要能看到下面的列表，所以只在拖动期间激活
        onEntered: function (drag) {
            if (!drag.hasUrls)
                return;
            page.dropActive = true;
            drag.accepted = true;
        }
        onExited: page.dropActive = false
        onDropped: function (drop) {
            page.dropActive = false;
            if (drop.hasUrls)
                page.handleDropped(drop.urls);
            drop.accepted = true;
        }
    }

    // 拖拽时的整页高亮 + 说明
    Rectangle {
        objectName: "srvDropOverlay"
        anchors.fill: parent
        visible: page.dropActive
        z: 500
        color: Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.10)
        border.width: 2
        border.color: page.accent
        radius: Theme.radiusS
        // 完全不吃鼠标：拖拽事件归 DropArea
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.NoButton
        }
        Column {
            anchors.centerIn: parent
            spacing: 8
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "\uE8B5"                  // Import
                font.family: Theme.iconFont
                font.pixelSize: 34
                color: page.accent
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "松开即可导入服务器配置"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "支持一次拖入多个 .json（合集名也会一起还原）"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
            }
        }
    }

    // ------------------------------------------------------------ 页头
    Item {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 58

        Row {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: 10

            // 三块读数
            Repeater {
                model: [
                    { label: "收藏", value: page.mgr ? page.mgr.serverCount : 0, color: Theme.text },
                    { label: "在线", value: page.mgr ? page.mgr.onlineCount : 0, color: page.okColor },
                    { label: "在线人数", value: page.mgr ? page.mgr.totalPlayers : 0, color: Theme.cyan }
                ]
                delegate: Rectangle {
                    width: 92
                    height: 46
                    radius: Theme.radiusS
                    color: Theme.scrim(0.05)
                    border.width: 1
                    border.color: Theme.border

                    Column {
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 1
                        Text {
                            text: modelData.value
                            color: modelData.color
                            font.family: Theme.monoFont
                            font.pixelSize: 19
                            font.weight: Font.Bold
                        }
                        Text {
                            text: modelData.label
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 9
                        }
                    }
                }
            }
        }

        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            // 添加服务器（里面可以切「批量」）
            ActionButton {
                objectName: "srvAddBtn"
                label: "添加服务器"
                glyph: "\uE710"
                onClicked: page.openAddDialog(null)
            }

            ActionButton {
                objectName: "srvDirectBtn"
                label: "IP 直连"
                glyph: "\uE768"
                accent: true
                onClicked: page.openDirectDialog()
            }

            ActionButton {
                objectName: "srvRefreshBtn"
                label: page.mgr && page.mgr.busy ? "查询中" : "刷新状态"
                glyph: "\uE72C"
                busy: page.mgr ? page.mgr.busy : false
                onClicked: if (page.mgr) page.mgr.refreshAll()
            }

            // 分隔线：把「常用动作」和「工具类图标」分开，
            // 一排图标连在一起看图不清楚（用户反馈「UI 看起来怪怪的」）
            Rectangle {
                width: 1
                height: 20
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.border
            }

            // 导出 / 导入配置：攒了一堆服务器要分享给别人时用。
            // 两颗都做成图标按钮 —— 工具条已经有三颗文字按钮，
            // 再加两颗文字会挤；这两件事也不常做。
            IconButton {
                objectName: "srvExportBtn"
                glyph: "\uEDE1"          // Save / 导出
                // 多选模式下 = 只导出勾中的那些
                tip: page.selectMode
                     ? "导出勾选的服务器配置（含合集名）"
                     : "导出服务器配置（含合集名，不含密码）"
                boxSize: 30
                enabledBtn: page.mgr ? page.mgr.serverCount > 0 : false
                onClicked: {
                    if (page.selectMode)
                        page.askExportChecked();
                    else
                        page.askExport();
                }
            }

            IconButton {
                objectName: "srvImportBtn"
                glyph: "\uE8B5"          // Import / 导入
                tip: "导入服务器配置"
                boxSize: 30
                onClicked: page.askImport()
            }

            // 从文字导入：聊天记录 / 论坛里的一段话，直接把 ip:port 抠出来。
            // 和上面「导入配置文件」是两件事 —— 那个要 .json 文件，这个只要文本。
            IconButton {
                objectName: "srvPasteBtn"
                glyph: "\uE77F"          // Paste / 粘贴
                tip: "从文字导入（粘贴一段带 IP 的文字）"
                boxSize: 30
                onClicked: page.openPaste()
            }

            // 多选：进「选择」模式后可以一次删掉好几台。
            // （端口遍历原来也在这里有一颗按钮，现在并进「添加服务器」了 ——
            //   弹窗里切到「扫描」就能用，不再单独占一个入口。）
            IconButton {
                objectName: "srvSelectBtn"
                glyph: page.selectMode ? "\uE711" : "\uE73A"   // 叉 / 多选
                tip: page.selectMode ? "退出多选" : "多选服务器"
                boxSize: 30
                active: page.selectMode
                enabledBtn: page.mgr ? page.mgr.serverCount > 0 : false
                onClicked: {
                    if (page.selectMode)
                        page.exitSelect();
                    else
                        page.enterSelect();
                }
            }
        }
    }

    // 状态提示条：**已经删掉**（用户要求）。
    //
    // 以前这里常年挂着「查完了：1/1 个在线」这种文字，紧贴在页头下面。
    // 但同样的信息页头那三个读数（收藏 / 在线 / 在线人数）已经写得很清楚了，
    // 刷新状态这件事也不需要文字回执 —— 卡片上的状态色和数字本身就在变。
    // 留着它只是每个页面顶部多一行灰字，看着多余。
    //
    // 现在只保留「用户真的需要看到」的临时提示（出错、地址不合法、添加成功），
    // 由 `hintText` 驱动、几秒后自动消失（见下面的 hintTimer）。
    Text {
        id: hintLine
        objectName: "srvHintLine"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.topMargin: -6
        height: visible ? 14 : 0
        // 只显示「这一下发生的动作结果」，不再显示 mgr.statusText 那种长期状态
        visible: page.hintText.length > 0
                        && (Date.now() - page.hintAt) < page.hintHoldMs
        text: visible ? page.hintText : ""
        color: Theme.warn
        font.family: Theme.uiFont
        font.pixelSize: 10
        elide: Text.ElideRight
    }

    // 提示条到点自动收掉（以前它一直挂着，就是因为没人清）
    Timer {
        id: hintTimer
        interval: page.hintHoldMs
        repeat: false
        onTriggered: page.hintText = ""
    }
    onHintAtChanged: {
        if (page.hintText.length > 0)
            hintTimer.restart()
    }

    // ------------------------------------------------------------ 添加/编辑
    Popup {
        id: formDlg
        objectName: "srvFormDlg"
        visible: page.formOpen
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        anchors.centerIn: Overlay.overlay

        Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.55) }

        // 关掉对话框时，如果正在扫描就一起停掉。
        // 以前「端口遍历」是独立弹窗，它自己在 onClosed 里 cancelScan()；
        // 现在并进来了，收尾逻辑得挂到这儿，否则关掉对话框后台还在扫。
        onClosed: {
            page.formOpen = false;
            if (page.scanRunning || (page.mgr && page.mgr.scanRunning))
                page.stopScan();
            page.scanRunning = false;
        }

        padding: 20
        contentWidth: 560
        contentHeight: formCol.implicitHeight

        background: Rectangle {
            radius: 14
            color: Theme.panel
            border.width: 1
            border.color: Theme.borderHi
        }

        contentItem: Column {
            id: formCol
            width: 560
            spacing: 11

            // 标题行：标题占左边，切换器贴右边。
            // ★ 这里以前是 `Row { Text; Text; Item{width: 父宽-250}; 切换器 }` ——
            //   三块固定宽度加起来（标题 + 副标题 + 占位 + 切换器）远超对话框的 560，
            //   于是「单条 / 批量」切换器被挤到框外（用户报的「悬浮出界面外了」）。
            //   这和之前「读剪贴板按钮飞出去」是同一个坑：
            //   **Row 里用 `parent.width - N` 当占位，只要前面的文字比 N 长就会溢出**。
            //   改用锚点后与文字长度无关。
            Item {
                width: parent.width
                height: 30

                Row {
                    anchors.left: parent.left
                    anchors.right: formSeg.right
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: page.formEditing ? "编辑服务器"
                              : (page.formBulk ? "批量添加服务器" : "添加服务器")
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        // 副标题在窄的时候会被省略，别硬撑
                        width: Math.max(0, parent.width - implicitWidth > 0
                                           ? implicitWidth : parent.width)
                        text: page.formEditing ? "IP 填错了就在这儿改"
                              : (page.formBulk ? "一段文字里有多少加多少"
                                               : "常去的服存下来，一进来就能看人数")
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        elide: Text.ElideRight
                    }
                }

                // 「单条 / 批量」切换：只在新加时出现（编辑一台说「批量」没意义）
                Rectangle {
                    id: formSeg
                    visible: !page.formEditing
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: segRow.implicitWidth + 8
                    height: 26
                    radius: 13
                    color: Theme.scrim(0.05)
                    border.width: 1
                    border.color: Theme.border

                    Row {
                        id: segRow
                        anchors.centerIn: parent
                        spacing: 0
                        Repeater {
                            // 三种模式：单条 / 批量 / 扫描（端口遍历以前是独立弹窗）
                            model: [
                                { key: 0, label: "单条" },
                                { key: 1, label: "批量" },
                                { key: 2, label: "扫描" }
                            ]
                            delegate: Rectangle {
                                required property var modelData
                                width: segTxt.implicitWidth + 20
                                height: 22
                                radius: 11
                                property bool on: page.formMode === modelData.key
                                color: on
                                       ? Qt.rgba(page.accent.r, page.accent.g,
                                                 page.accent.b, 0.18)
                                       : "transparent"
                                Text {
                                    id: segTxt
                                    anchors.centerIn: parent
                                    text: modelData.label
                                    color: parent.on ? page.accent : Theme.textDim
                                    font.family: Theme.uiFont
                                    font.pixelSize: 10
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    hoverEnabled: true
                                    onClicked: {
                                        if (modelData.key === 2)
                                            page.switchToScan();
                                        else if (modelData.key === 1)
                                            page.switchToBulk();
                                        else
                                            page.switchToSingle();
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 名称（批量模式下整段单条表单都收起来）
            Column {
                visible: page.formMode === 0
                width: parent.width
                spacing: 4
                Text {
                    text: "服务器名称"
                    color: Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                }
                Rectangle {
                    width: parent.width
                    height: 32
                    radius: 8
                    color: Theme.scrim(0.06)
                    border.width: 1
                    border.color: nameInput.activeFocus ? page.accent : Theme.border
                    HoverHandler { cursorShape: Qt.IBeamCursor }
                    TextInput {
                        id: nameInput
                        objectName: "srvFormName"
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        verticalAlignment: TextInput.AlignVCenter
                        text: page.formName
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                        selectByMouse: true
                        onTextChanged: page.formName = text
                        onAccepted: addrInput.forceActiveFocus()
                        Text {
                            anchors.fill: parent
                            verticalAlignment: Text.AlignVCenter
                            visible: nameInput.text.length === 0
                            text: "随便起，比如「宿舍常玩的那个」"
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                    }
                }
            }

            // 地址 + 权重
            Row {
                visible: page.formMode === 0
                width: parent.width
                spacing: 10

                Column {
                    width: parent.width - 132
                    spacing: 4
                    Text {
                        text: "服务器地址"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                    Rectangle {
                        width: parent.width
                        height: 32
                        radius: 8
                        color: Theme.scrim(0.06)
                        border.width: 1
                        border.color: addrInput.activeFocus ? page.accent : Theme.border
                        HoverHandler { cursorShape: Qt.IBeamCursor }
                        TextInput {
                            id: addrInput
                            objectName: "srvFormAddr"
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            verticalAlignment: TextInput.AlignVCenter
                            text: page.formAddr
                            color: Theme.text
                            font.family: Theme.monoFont
                            font.pixelSize: 12
                            selectByMouse: true
                            onTextChanged: page.formAddr = text
                            onAccepted: page.submitForm()
                            Text {
                                anchors.fill: parent
                                verticalAlignment: Text.AlignVCenter
                                visible: addrInput.text.length === 0
                                text: "1.2.3.4 或 1.2.3.4:27015"
                                color: Theme.textMute
                                font.family: Theme.monoFont
                                font.pixelSize: 11
                            }
                        }
                    }
                }

                Column {
                    width: 122
                    spacing: 4
                    Text {
                        text: "排序权重"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                    Rectangle {
                        width: parent.width
                        height: 32
                        radius: 8
                        color: Theme.scrim(0.06)
                        border.width: 1
                        border.color: weightInput.activeFocus ? page.accent : Theme.border
                        HoverHandler { cursorShape: Qt.IBeamCursor }
                        TextInput {
                            id: weightInput
                            objectName: "srvFormWeight"
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            verticalAlignment: TextInput.AlignVCenter
                            text: page.formWeight
                            color: Theme.text
                            font.family: Theme.monoFont
                            font.pixelSize: 12
                            selectByMouse: true
                            validator: IntValidator { bottom: -9999; top: 9999 }
                            onTextChanged: page.formWeight = text
                            onAccepted: page.submitForm()
                        }
                    }
                }
            }

            Text {
                width: parent.width
                visible: page.formError.length > 0
                text: page.formError
                color: page.warnColor
                font.family: Theme.uiFont
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }

            // 高级：面板
            Item {
                visible: page.formMode === 0
                width: parent.width
                height: visible ? 26 : 0

                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: advMa.containsMouse ? Theme.scrim(0.06) : "transparent"
                }
                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 6
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: page.formAdvanced ? "\uE70D" : "\uE76C"
                        font.family: Theme.iconFont
                        font.pixelSize: 10
                        color: Theme.textMute
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "高级：面板地址与密码"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: formPanelModel.count > 0
                        text: "（" + formPanelModel.count + " 个面板）"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }
                MouseArea {
                    id: advMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: page.formAdvanced = !page.formAdvanced
                }
            }

            Column {
                width: parent.width
                spacing: 8
                visible: page.formAdvanced

                Repeater {
                    model: formPanelModel

                    // 每个面板一张小卡片：地址一行、密码一行，字段高度 34、字号 12.5。
                    // 上一版这两行挤在同一个 Row 里，密码框宽度是
                    // `parent.width - pUrl.width - 118` 算出来的 —— 两个宽度一抵消基本归零，
                    // 于是「面板密码」只剩一条窄缝、字只有 10px，根本没法填（用户报的就是这个）。
                    delegate: Rectangle {
                        id: panelCard
                        required property int index
                        required property string url
                        required property string password
                        required property bool hasPassword
                        property bool pwShown: false

                        width: formCol.width
                        height: panelInner.implicitHeight + 16
                        radius: 10
                        color: Theme.scrim(0.045)
                        border.width: 1
                        border.color: (pUrl.activeFocus || pPw.activeFocus)
                                      ? Qt.rgba(page.accent.r, page.accent.g,
                                                page.accent.b, 0.5)
                                      : (panelHover.hovered ? Theme.borderHi : Theme.border)

                        HoverHandler { id: panelHover }

                        Column {
                            id: panelInner
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            anchors.topMargin: 8
                            spacing: 6

                            // ---- 面板地址
                            Row {
                                width: parent.width
                                spacing: 8

                                Text {
                                    width: 54
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "面板地址"
                                    color: Theme.textDim
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                }

                                Rectangle {
                                    width: parent.width - 54 - 8 - 26 - 8
                                    height: 34
                                    radius: 8
                                    color: Theme.scrim(0.06)
                                    border.width: 1
                                    border.color: pUrl.activeFocus ? page.accent : Theme.border
                                    HoverHandler { cursorShape: Qt.IBeamCursor }

                                    TextInput {
                                        id: pUrl
                                        objectName: "srvFormPanelUrl" + index
                                        anchors.fill: parent
                                        anchors.leftMargin: 10
                                        anchors.rightMargin: 10
                                        verticalAlignment: TextInput.AlignVCenter
                                        text: url
                                        color: Theme.text
                                        font.family: Theme.monoFont
                                        font.pixelSize: 13
                                        selectByMouse: true
                                        onTextChanged: formPanelModel.setProperty(index, "url", text)
                                        Text {
                                            anchors.fill: parent
                                            verticalAlignment: Text.AlignVCenter
                                            visible: pUrl.text.length === 0
                                            text: "面板地址，如 1.2.3.4:8080"
                                            color: Theme.textMute
                                            font.family: Theme.monoFont
                                            font.pixelSize: 12
                                        }
                                    }
                                }

                                IconButton {
                                    glyph: "\uE711"
                                    tip: "去掉这个面板"
                                    boxSize: 26
                                    danger: true
                                    anchors.verticalCenter: parent.verticalCenter
                                    onClicked: page.removePanelRow(index)
                                }
                            }

                            // ---- 面板密码
                            Row {
                                width: parent.width
                                spacing: 8

                                Text {
                                    width: 54
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "面板密码"
                                    color: Theme.textDim
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                }

                                Rectangle {
                                    width: parent.width - 54 - 8 - 52 - 8
                                    height: 34
                                    radius: 8
                                    color: Theme.scrim(0.06)
                                    border.width: 1
                                    border.color: pPw.activeFocus ? page.accent : Theme.border
                                    HoverHandler { cursorShape: Qt.IBeamCursor }

                                    TextInput {
                                        id: pPw
                                        objectName: "srvFormPanelPw" + index
                                        anchors.fill: parent
                                        anchors.leftMargin: 10
                                        anchors.rightMargin: 10
                                        verticalAlignment: TextInput.AlignVCenter
                                        text: password
                                        echoMode: panelCard.pwShown ? TextInput.Normal
                                                                    : TextInput.Password
                                        color: Theme.text
                                        font.family: Theme.monoFont
                                        font.pixelSize: 13
                                        selectByMouse: true
                                        onTextChanged: formPanelModel.setProperty(index, "password", text)
                                        Text {
                                            anchors.fill: parent
                                            verticalAlignment: Text.AlignVCenter
                                            visible: pPw.text.length === 0
                                            text: hasPassword ? "已保存，留空不改"
                                                              : "面板密码（留空就是不填）"
                                            color: Theme.textMute
                                            font.family: Theme.uiFont
                                            font.pixelSize: 12
                                        }
                                    }
                                }

                                // 看不见自己打了什么最容易填错，给个「显示」开关
                                Rectangle {
                                    width: 52
                                    height: 34
                                    radius: 8
                                    color: shownMa.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.05)
                                    border.width: 1
                                    border.color: panelCard.pwShown ? page.accent : Theme.border

                                    Text {
                                        anchors.centerIn: parent
                                        text: panelCard.pwShown ? "隐藏" : "显示"
                                        color: panelCard.pwShown ? page.accent : Theme.textDim
                                        font.family: Theme.uiFont
                                        font.pixelSize: 11
                                    }
                                    MouseArea {
                                        id: shownMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: panelCard.pwShown = !panelCard.pwShown
                                    }
                                }
                            }
                        }
                    }
                }

                Row {
                    width: parent.width
                    spacing: 8

                    Rectangle {
                        width: 132
                        height: 30
                        radius: 15
                        color: addPanelMa.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.05)
                        border.width: 1
                        border.color: Theme.border
                        Text {
                            anchors.centerIn: parent
                            text: "＋ 再加一个面板"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                        MouseArea {
                            id: addPanelMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.addPanelRow()
                        }
                    }

                    Rectangle {
                        width: 148
                        height: 30
                        radius: 15
                        color: clearPwMa.containsMouse ? Theme.scrim(0.09) : "transparent"
                        border.width: 1
                        border.color: page.formClearPw ? Theme.warn : Theme.border
                        Row {
                            anchors.centerIn: parent
                            spacing: 5
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                width: 12
                                text: page.formClearPw ? "\uE73E" : ""
                                font.family: Theme.iconFont
                                font.pixelSize: 11
                                color: Theme.warn
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: "清除已保存密码"
                                color: page.formClearPw ? Theme.warn : Theme.textDim
                                font.family: Theme.uiFont
                                font.pixelSize: 11
                            }
                        }
                        MouseArea {
                            id: clearPwMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.formClearPw = !page.formClearPw
                        }
                    }
                }

                Text {
                    width: parent.width
                    text: "密码用 Windows 账户的密钥加密后再存进本地配置；换台电脑就解不开，等于没存过。"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    lineHeight: 1.3
                    wrapMode: Text.WordWrap
                }
            }

            // ---------------- 批量模式的面板 ----------------
            // 「批量添加」不再是一个独立的弹窗，而是这个对话框里的一种模式。
            // 好处：入口只剩「添加服务器」一个，用户不会问「批量和添加有啥区别」。
            Column {
                visible: page.formBulk
                width: parent.width
                spacing: 9

                Item {
                    width: parent.width
                    height: 28
                    Text {
                        anchors.left: parent.left
                        anchors.right: bulkClipBtn.left
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        text: "一行一个、或者整段粘进来都行"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        elide: Text.ElideRight
                    }
                    ActionButton {
                        id: bulkClipBtn
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: 96
                        height: 26
                        accent: false
                        label: "读剪贴板"
                        onClicked: page.readClipboardIntoBulk()
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 170
                    radius: Theme.radiusXS
                    color: Theme.scrim(0.05)
                    border.width: 1
                    border.color: bulkInput.activeFocus ? page.accent : Theme.border

                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: 8
                        TextArea {
                            id: bulkInput
                            objectName: "srvBulkInput"
                            placeholderText: "1.2.3.4:27015\n5.6.7.8:27016\nconnect 9.9.9.9:27015"
                            color: Theme.text
                            placeholderTextColor: Theme.textMute
                            font.family: Theme.monoFont
                            font.pixelSize: 11
                            wrapMode: TextArea.WrapAnywhere
                            selectByMouse: true
                            background: Item { }
                            onTextChanged: {
                                if (page.bulkText !== text) {
                                    page.bulkText = text
                                    page.refreshBulk()
                                }
                            }
                        }
                    }
                }

                Text {
                    width: parent.width
                    visible: page.bulkText.length > 0
                    text: {
                        var info = page.bulkPreview || {}
                        if ((info.total || 0) === 0)
                            return "没找到服务器地址"
                        var s = "找到 " + info.total + " 个地址，其中 "
                                + (info.fresh || 0) + " 个可以添加"
                        if ((info.duplicate || 0) > 0)
                            s += "（" + info.duplicate + " 个已在收藏里）"
                        return s
                    }
                    color: ((page.bulkPreview || {}).fresh || 0) > 0 ? Theme.ok : Theme.warn
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }

                Text {
                    width: parent.width
                    visible: page.bulkError.length > 0
                    text: page.bulkError
                    color: page.warnColor
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    wrapMode: Text.WordWrap
                }
            }

            // ---------------- 扫描模式的面板 ----------------
            // 端口遍历以前是独立弹窗，用户反馈和「添加服务器」分成两处太散。
            // 现在它是这个对话框的第三种模式（单条 / 批量 / 扫描）。
            Column {
                visible: page.formScan
                width: parent.width
                spacing: 10

            Text {
                width: parent.width
                text: "扫描指定主机的端口范围，只列出真的有回应的服务器。"
                      + "一次最多 1000 个端口，扫完可以一键把选中的存进收藏。"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            // 主机 + 端口范围
            Row {
                width: parent.width
                spacing: 8

                Column {
                    width: parent.width - 200
                    spacing: 4
                    Text {
                        text: "主机（IP 或域名）"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                    Rectangle {
                        width: parent.width
                        height: 30
                        radius: Theme.radiusXS
                        color: Theme.scrim(0.05)
                        border.width: 1
                        border.color: scanHostInput.activeFocus ? page.accent : Theme.border
                        HoverHandler { cursorShape: Qt.IBeamCursor }
                        TextInput {
                            id: scanHostInput
                            objectName: "srvScanHost"
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            verticalAlignment: TextInput.AlignVCenter
                            text: page.scanHost
                            color: Theme.text
                            font.family: Theme.monoFont
                            font.pixelSize: 11
                            selectByMouse: true
                            clip: true
                            enabled: !page.scanRunning
                            onTextChanged: {
                                page.scanHost = text;
                                // ★ 输入/粘贴后**立刻**试着拆「IP:端口」。
                                //   以前只挂在 onEditingFinished 上 —— 那个信号要
                                //   失去焦点才发，粘贴完光标还在框里就不会触发，
                                //   用户看到的就是「IP 输进去了，后面两个端口框没变」。
                                //   这里加 250ms 防抖：一边手打 `1.1.1.1:250` 时
                                //   不会每敲一个数字就拆一次（那会把正在输的半截吃掉）。
                                scanSplitTimer.restart();
                            }
                            // 失去焦点时再确认一次（兜住极少数没走防抖的情况）
                            onEditingFinished: page.normalizeScanHost()
                            Keys.onReturnPressed: {
                                page.normalizeScanHost();
                                page.startScan();
                            }

                            // 拆分防抖：输入停下 250ms 才动作
                            Timer {
                                id: scanSplitTimer
                                interval: 250
                                repeat: false
                                onTriggered: {
                                    // 只有「看起来是完整地址」时才拆，避免打断手输
                                    if (/\d+$/.test(scanHostInput.text)
                                            && scanHostInput.text.indexOf(":") > 0)
                                        page.normalizeScanHost();
                                }
                            }
                            Text {
                                anchors.fill: parent
                                verticalAlignment: Text.AlignVCenter
                                visible: scanHostInput.text.length === 0
                                text: "IP 或 IP:端口（会自动拆出端口扫 100 个）"
                                color: Theme.textMute
                                font.family: Theme.monoFont
                                font.pixelSize: 10
                            }
                        }
                    }
                }

                Column {
                    width: 88
                    spacing: 4
                    Text {
                        text: "起始端口"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                    Rectangle {
                        width: parent.width
                        height: 30
                        radius: Theme.radiusXS
                        color: Theme.scrim(0.05)
                        border.width: 1
                        border.color: Theme.border
                        HoverHandler { cursorShape: Qt.IBeamCursor }
                        TextInput {
                            id: scanFromInput
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            verticalAlignment: TextInput.AlignVCenter
                            text: String(page.scanFrom)
                            color: Theme.text
                            font.family: Theme.monoFont
                            font.pixelSize: 11
                            selectByMouse: true
                            enabled: !page.scanRunning
                            validator: IntValidator { bottom: 1; top: 65535 }
                            onTextChanged: {
                                var v = parseInt(text);
                                if (!isNaN(v)) page.scanFrom = v;
                            }
                        }
                    }
                }

                Column {
                    width: 88
                    spacing: 4
                    Text {
                        text: "结束端口"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                    Rectangle {
                        width: parent.width
                        height: 30
                        radius: Theme.radiusXS
                        color: Theme.scrim(0.05)
                        border.width: 1
                        border.color: Theme.border
                        HoverHandler { cursorShape: Qt.IBeamCursor }
                        TextInput {
                            id: scanToInput
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            verticalAlignment: TextInput.AlignVCenter
                            text: String(page.scanTo)
                            color: Theme.text
                            font.family: Theme.monoFont
                            font.pixelSize: 11
                            selectByMouse: true
                            enabled: !page.scanRunning
                            validator: IntValidator { bottom: 1; top: 65535 }
                            onTextChanged: {
                                var v = parseInt(text);
                                if (!isNaN(v)) page.scanTo = v;
                            }
                        }
                    }
                }
            }

            // 进度
            Column {
                width: parent.width
                visible: page.scanRunning || page.scanDone > 0
                spacing: 5
                Rectangle {
                    width: parent.width
                    height: 6
                    radius: 3
                    color: Theme.scrim(0.1)
                    Rectangle {
                        width: page.scanTotal > 0
                               ? parent.width * (page.scanDone / page.scanTotal) : 0
                        height: parent.height
                        radius: 3
                        color: Theme.accent
                        Behavior on width { NumberAnimation { duration: 120 } }
                    }
                }
                Text {
                    width: parent.width
                    text: page.scanRunning
                          ? "扫描中 " + page.scanDone + " / " + page.scanTotal
                            + (page.scanNow ? "   " + page.scanNow : "")
                          : "扫完 " + page.scanTotal + " 个端口，有回应 "
                            + page.scanResults.length + " 个"
                    color: Theme.textMute
                    font.family: Theme.monoFont
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
            }

            // 结果列表
            Rectangle {
                width: parent.width
                height: Math.min(200, Math.max(0, page.scanResults.length * 30 + 8))
                visible: page.scanResults.length > 0
                radius: Theme.radiusXS
                color: Theme.scrim(0.035)
                border.width: 1
                border.color: Theme.border

                ListView {
                    anchors.fill: parent
                    anchors.margins: 4
                    clip: true
                    model: page.scanResults
                    spacing: 2
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                        width: 6
                        contentItem: Rectangle {
                            radius: 3
                            color: Theme.scrim(0.24)
                        }
                        background: Item { }
                    }
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width - 8
                        height: 28
                        radius: 6
                        color: checkedMa.containsMouse ? Theme.scrim(0.07) : "transparent"

                        CheckBox {
                            id: scanCheck
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            checked: page.scanChecked[modelData.addr] === true
                            onToggled: {
                                var sel = page.scanChecked;
                                sel[modelData.addr] = checked;
                                page.scanChecked = sel;
                            }
                        }
                        Text {
                            anchors.left: scanCheck.right
                            anchors.leftMargin: 2
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - scanCheck.width - 150
                            text: modelData.addr + (modelData.name ? "  " + modelData.name : "")
                            color: Theme.text
                            font.family: Theme.monoFont
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }
                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.players + "/" + modelData.maxPlayers
                                  + (modelData.ms ? "  " + modelData.ms + "ms" : "")
                            color: Theme.textMute
                            font.family: Theme.monoFont
                            font.pixelSize: 9
                        }
                        MouseArea {
                            id: checkedMa
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: scanCheck.toggle()
                        }
                    }
                }
            }

            Text {
                width: parent.width
                visible: page.bulkError.length > 0
                text: page.bulkError
                color: page.warnColor
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            Row {
                width: parent.width
                spacing: 8

                ActionButton {
                    visible: !page.scanRunning && page.scanResults.length > 0
                    width: 84
                    height: 30
                    accent: false
                    label: "全选"
                    onClicked: page.toggleScanAll(true)
                }
                ActionButton {
                    visible: !page.scanRunning && page.scanResults.length > 0
                    width: 84
                    height: 30
                    accent: false
                    label: "全不选"
                    onClicked: page.toggleScanAll(false)
                }

                Item { width: Math.max(0, parent.width - 176
                                          - (page.scanResults.length > 0 ? 176 : 0)); height: 1 }

                ActionButton {
                    width: 84
                    height: 30
                    accent: false
                    // 以前这颗是「关闭」（关掉独立的扫描弹窗）。
                    // 扫描现在是添加对话框的一部分，所以它是「取消」= 关整个对话框。
                    label: page.scanRunning ? "停止" : "取消"
                    onClicked: {
                        if (page.scanRunning)
                            page.stopScan();
                        else
                            page.formOpen = false;
                    }
                }
                ActionButton {
                    objectName: "srvScanStartBtn"
                    width: 84
                    height: 30
                    visible: !page.scanRunning
                    label: page.scanResults.length > 0 ? "保存选中" : "开始扫描"
                    enabledBtn: page.scanResults.length > 0
                                ? page.scanSelectedCount() > 0
                                : page.scanHost.length > 0
                    onClicked: {
                        if (page.scanResults.length > 0)
                            page.saveScanPicked();
                        else
                            page.startScan();
                    }
                }
            }
            }

            // 底部按钮（扫描模式下整行收起来 —— 那一行按钮在扫描面板内部，
            // 不收的话会出现两排「取消」，用户不知道点哪个）
            Row {
                width: parent.width
                spacing: 8
                visible: !page.formScan

                Rectangle {
                    width: 76
                    height: 30
                    radius: 15
                    visible: page.formEditing
                    color: delMa.containsMouse ? Qt.rgba(0.95, 0.35, 0.35, 0.16) : "transparent"
                    border.width: 1
                    border.color: Qt.rgba(0.95, 0.4, 0.4, 0.4)
                    Text {
                        anchors.centerIn: parent
                        text: "删除"
                        color: "#ef6b6b"
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                    MouseArea {
                        id: delMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.removeFromForm()
                    }
                }

                Item {
                    width: Math.max(0, parent.width - 76 - 76 - 84 - 24)
                    height: 1
                }

                Rectangle {
                    width: 76
                    height: 30
                    radius: 15
                    color: cancelMa.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.05)
                    border.width: 1
                    border.color: Theme.border
                    Text {
                        anchors.centerIn: parent
                        text: "取消"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                    MouseArea {
                        id: cancelMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.formOpen = false
                    }
                }

                Rectangle {
                    width: 84
                    height: 30
                    radius: 15
                    color: saveMa.containsMouse
                           ? Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.9)
                           : page.accent
                    opacity: page.formBulk
                             && ((page.bulkPreview || {}).fresh || 0) <= 0 ? 0.45 : 1.0
                    Text {
                        anchors.centerIn: parent
                        // 批量模式下这颗按钮变成「全部添加」
                        text: page.formBulk ? "全部添加"
                              : (page.formEditing ? "保存修改" : "添加")
                        color: Theme.bg
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                    MouseArea {
                        id: saveMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (page.formBulk)
                                page.submitBulk();
                            else
                                page.submitForm();
                        }
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------ IP 直连
    Popup {
        id: directDlg
        objectName: "srvDirectDlg"
        visible: page.directOpen
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        anchors.centerIn: Overlay.overlay

        Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.55) }

        onClosed: page.directOpen = false

        padding: 20
        contentWidth: 420
        contentHeight: directCol.implicitHeight

        background: Rectangle {
            radius: 14
            color: Theme.panel
            border.width: 1
            border.color: Theme.borderHi
        }

        contentItem: Column {
            id: directCol
            width: 420
            spacing: 10

            Text {
                text: "IP 直连"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                text: "填 IP 就行，端口不写按 27015；会唤起 Steam 连过去，不存进列表。"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            Rectangle {
                width: parent.width
                height: 34
                radius: 8
                color: Theme.scrim(0.06)
                border.width: 1
                border.color: dirInput.activeFocus ? page.accent : Theme.border
                HoverHandler { cursorShape: Qt.IBeamCursor }
                TextInput {
                    id: dirInput
                    objectName: "srvDirectInput"
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    verticalAlignment: TextInput.AlignVCenter
                    text: page.directInput
                    color: Theme.text
                    font.family: Theme.monoFont
                    font.pixelSize: 12
                    selectByMouse: true
                    onTextChanged: {
                        page.directInput = text
                        page.updateDirectPreview()
                    }
                    onAccepted: page.submitDirect()
                    Text {
                        anchors.fill: parent
                        verticalAlignment: Text.AlignVCenter
                        visible: dirInput.text.length === 0
                        text: "例如 42.193.137.24 或 42.193.137.24:27015"
                        color: Theme.textMute
                        font.family: Theme.monoFont
                        font.pixelSize: 11
                    }
                }
            }

            Text {
                width: parent.width
                visible: page.directError.length > 0 || page.directPreview.length > 0
                text: page.directError.length > 0
                      ? page.directError
                      : "会连到 " + page.directPreview
                color: page.directError.length > 0 ? page.warnColor : page.okColor
                font.family: Theme.monoFont
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            Row {
                width: parent.width
                spacing: 8

                Rectangle {
                    width: 96
                    height: 30
                    radius: 15
                    visible: page.directPreview.length > 0
                    color: saveDirectMa.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.05)
                    border.width: 1
                    border.color: Theme.border
                    Text {
                        anchors.centerIn: parent
                        text: "存进列表"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                    MouseArea {
                        id: saveDirectMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.saveDirectToForm()
                    }
                }

                Item {
                    width: Math.max(0, parent.width - 96 - 76 - 84 - 24)
                    height: 1
                }

                Rectangle {
                    width: 76
                    height: 30
                    radius: 15
                    color: dirCancelMa.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.05)
                    border.width: 1
                    border.color: Theme.border
                    Text {
                        anchors.centerIn: parent
                        text: "取消"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                    MouseArea {
                        id: dirCancelMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.directOpen = false
                    }
                }

                Rectangle {
                    width: 84
                    height: 30
                    radius: 15
                    color: page.directPreview.length > 0 ? page.accent : Theme.scrim(0.12)
                    Text {
                        anchors.centerIn: parent
                        text: "连接"
                        color: page.directPreview.length > 0 ? Theme.bg : Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: page.directPreview.length > 0
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.submitDirect()
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------ 主体
    Row {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: hintLine.bottom
        anchors.topMargin: 8
        anchors.bottom: parent.bottom
        spacing: 14

        // ---- 左：服务器列表
        Item {
            id: listWrap
            width: parent.width - panel.width - 14
            height: parent.height

            // ==================================================================
            // 合集选择器（独立一列，固定在列表左边）
            // ==================================================================
            // ★ 用户要的：**不是折叠展开**，而是单独空出一块地方「选合集」。
            //   所以这里是左侧一条竖排列表：全部服务器 / 散服 / 各系列合集，
            //   点哪个右边就只显示哪一组。没有合集的服务器照常出现在「散服」里，
            //   不会因为分组而"看不见"。
            //   没有合集可选项时（groupList 只有「全部」），整列收起来不占地方。
            Rectangle {
                id: groupRail
                objectName: "srvGroupRail"
                visible: page.groupList.length > 1
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: visible ? 132 : 0
                radius: Theme.radiusS
                color: Theme.surface
                border.width: 1
                border.color: Theme.border

                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 8
                    spacing: 4

                    Text {
                        text: "合集"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        font.letterSpacing: 1.1
                        leftPadding: 4
                        bottomPadding: 2
                    }

                    Repeater {
                        model: page.groupList
                        delegate: Rectangle {
                            required property var modelData
                            width: parent.width
                            height: 34
                            radius: Theme.radiusXS
                            property bool on: page.groupKey === modelData.key
                            color: on
                                   ? Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.16)
                                   : (grpMa.containsMouse ? Theme.scrim(0.07) : "transparent")
                            border.width: on ? 1 : 0
                            border.color: Qt.rgba(page.accent.r, page.accent.g,
                                                  page.accent.b, 0.34)

                            Column {
                                anchors.left: parent.left
                                anchors.leftMargin: 8
                                anchors.right: parent.right
                                anchors.rightMargin: 6
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 1

                                Text {
                                    width: parent.width
                                    text: modelData.label
                                    color: parent.parent.on ? page.accent : Theme.text
                                    font.family: modelData.kind === "ip"
                                                 ? Theme.monoFont : Theme.uiFont
                                    font.pixelSize: 11
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    // 整组都在同一台机器上（同 IP 不同端口）时额外标一下，
                                    // 让「模式不同但同一个服主」这件事一眼看得出来。
                                    text: modelData.count + " 台"
                                          + (modelData.host ? " · 同 IP" : "")
                                    width: parent.width
                                    elide: Text.ElideRight
                                    color: Theme.textMute
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                }
                            }
                            MouseArea {
                                id: grpMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: page.selectGroup(modelData.key)
                            }
                            // 右键 / 悬浮出「改名」：自动识别不准时用户能自己命名
                            MouseArea {
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.bottom: parent.bottom
                                width: 20
                                visible: modelData.kind !== "all" && modelData.kind !== "none"
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                ToolTip.visible: containsMouse
                                ToolTip.text: "重命名这个合集"
                                ToolTip.delay: 400
                                onClicked: page.openRenameGroup(modelData)
                                Text {
                                    anchors.centerIn: parent
                                    text: "\uE70F"          // Edit
                                    font.family: Theme.iconFont
                                    font.pixelSize: 10
                                    color: parent.containsMouse ? page.accent : Theme.textMute
                                }
                            }
                        }
                    }
                }

                // 竖排内容多了能滚
                Flickable {
                    anchors.fill: parent
                    anchors.margins: 0
                    contentHeight: 0
                    visible: false
                }
            }

            // 右边剩下的区域（分类条 / 排序 / 搜索 / 列表）
            Item {
                id: mainCol
                anchors.left: groupRail.visible ? groupRail.right : parent.left
                anchors.leftMargin: groupRail.visible ? 14 : 0
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom

            // ---- 分类筛选条
            // 服务器按「名字里的提示词」自动归类（写实/对抗/战役/模组服…），
            // 这条胶囊栏只列出**当前确实有服务器**的类目，没有的空类目不显示。
            // 放在排序栏上面一行；没有分类可选时整条收掉，不占位。
            Row {
                id: catBar
                objectName: "srvCatBar"
                anchors.left: parent.left
                anchors.top: parent.top
                height: visible ? 22 : 0
                spacing: 6
                visible: page.categoryList.length > 1

                Repeater {
                    model: page.categoryList
                    delegate: Rectangle {
                        required property var modelData
                        width: catTxt.implicitWidth + 18
                        height: 22
                        radius: 11
                        property bool on: page.category === modelData.key
                        color: on
                               ? Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.16)
                               : (catMa.containsMouse ? Theme.scrim(0.07) : "transparent")
                        border.width: on ? 1 : 0
                        border.color: Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.34)

                        Text {
                            id: catTxt
                            anchors.centerIn: parent
                            text: modelData.label + " " + modelData.count
                            color: parent.on ? page.accent : Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }
                        MouseArea {
                            id: catMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                page.category = modelData.key;
                                // 换分类时回到顶部是合理的（等于换了一份列表）
                                srvList._anchorAddr = "";
                                srvList.positionViewAtBeginning();
                            }
                        }
                    }
                }
            }

            // 排序切换（很窄的一排胶囊）
            Row {
                id: sortBar
                anchors.left: parent.left
                anchors.top: catBar.visible ? catBar.bottom : parent.top
                anchors.topMargin: catBar.visible ? 6 : 0
                height: 24
                spacing: 6

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "排序"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    rightPadding: 2
                }

                Repeater {
                    model: [
                        { key: "weight", label: "权重" },
                        { key: "players", label: "人数" },
                        { key: "ping", label: "延迟" },
                        { key: "name", label: "名字" }
                    ]
                    delegate: Rectangle {
                        width: sortTxt.implicitWidth + 18
                        height: 24
                        radius: 12
                        color: page.sortMode === modelData.key
                               ? Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.16)
                               : (sortMa.containsMouse ? Theme.scrim(0.07) : "transparent")
                        border.width: page.sortMode === modelData.key ? 1 : 0
                        border.color: Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.34)

                        Text {
                            id: sortTxt
                            anchors.centerIn: parent
                            text: modelData.label
                            color: page.sortMode === modelData.key ? page.accent : Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                        MouseArea {
                            id: sortMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: if (page.mgr) page.mgr.setSortMode(modelData.key)
                        }
                    }
                }
            }

            // 搜索框：贴在排序栏右边，宽度吃掉剩下的空间（最少 150，别挤成一条缝）。
            // 和排序同一行，是因为这排本来就矮（24px），再单开一行会把列表挤掉一截。
            Rectangle {
                id: searchBox
                objectName: "srvSearchBox"
                anchors.left: sortBar.right
                anchors.leftMargin: 14
                anchors.right: parent.right
                anchors.verticalCenter: sortBar.verticalCenter
                height: 24
                width: Math.max(150, parent.width - sortBar.width - 14)
                radius: 12
                color: Theme.scrim(0.05)
                border.width: 1
                border.color: searchField.activeFocus
                              ? Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.55)
                              : Theme.border
                Behavior on border.color { ColorAnimation { duration: Theme.anim } }

                HoverHandler { cursorShape: Qt.IBeamCursor }

                // 点图标/留白也能聚焦（TextInput 只占中间一段）
                MouseArea {
                    anchors.fill: parent
                    onClicked: searchField.forceActiveFocus()
                }

                Row {
                    anchors.fill: parent
                    anchors.leftMargin: 9
                    anchors.rightMargin: 7
                    spacing: 6

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "\uE721"
                        font.family: Theme.iconFont
                        font.pixelSize: 11
                        color: searchField.activeFocus ? page.accent : Theme.textMute
                        Behavior on color { ColorAnimation { duration: Theme.anim } }
                    }

                    Text {
                        // 搜到几台，直接写在框里；没搜的时候不占地方
                        id: matchCounter
                        anchors.verticalCenter: parent.verticalCenter
                        visible: (page.query || "").trim().length > 0
                        text: page.matchCount + "/" + page.allServers.length
                        color: page.matchCount === 0 ? page.warnColor : Theme.textMute
                        font.family: Theme.monoFont
                        font.pixelSize: 10
                    }

                    TextInput {
                        id: searchField
                        objectName: "srvSearchInput"
                        // 宽度按兄弟项实测宽度算，别写死数字：
                        // 窗口缩到最小时这条框只有 170 出头，写死的余量会把输入区挤成负数。
                        width: Math.max(0, parent.width - 11 - 6 - matchCounter.width - 6
                                        - (searchClear.visible ? searchClear.width + 6 : 0))
                        height: parent.height
                        verticalAlignment: TextInput.AlignVCenter
                        // ★ 这里**不能**写 `text: page.query`。
                        //   那是个双向绑定：用户敲一个字母 → text 变 → onTextChanged
                        //   把 page.query 也改了 → 绑定又把 text 写回旧值，
                        //   表现就是「输入框里打字母，字不跟着走 / 被打回去」。
                        //   改为文本由输入框自己管，程序侧要改（清空 / 恢复）时
                        //   通过下面的 Connections 单向同步进去。
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                        selectByMouse: true
                        selectionColor: Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.45)
                        onTextChanged: page.query = text
                        Keys.onEscapePressed: page.clearQuery()

                        Text {
                            anchors.fill: parent
                            verticalAlignment: Text.AlignVCenter
                            visible: searchField.text.length === 0
                            // 窄的时候只留「搜服务器」，宽的才把可搜字段全写出来
                            text: searchBox.width < 260 ? "搜服务器…"
                                                        : "搜名字 / 地址 / 地图 / 模式"
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }

                    Item {
                        id: searchClear
                        width: 14
                        height: 14
                        anchors.verticalCenter: parent.verticalCenter
                        visible: searchField.text.length > 0
                        Text {
                            anchors.centerIn: parent
                            text: "\uE711"
                            font.family: Theme.iconFont
                            font.pixelSize: 8
                            color: searchClearMa.containsMouse ? page.accent : Theme.textMute
                        }
                        MouseArea {
                            id: searchClearMa
                            anchors.fill: parent
                            anchors.margins: -3
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.clearQuery()
                        }
                    }
                }
            }

            // 列表本体
            ListView {
                id: srvList
                objectName: "srvList"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: sortBar.bottom
                anchors.topMargin: 8
                anchors.bottom: parent.bottom
                clip: true
                spacing: 8
                boundsBehavior: Flickable.StopAtBounds
                model: page.visibleServers

                // ★ 加/删服务器后列表会跳回开头（用户报的）。
                //   根因：`model` 绑的是 `page.visibleServers`，那是个**每次
                //   serversChanged 都会重新算出来的新 JS 数组**。ListView 拿到
                //   一个「全新的 model」时会把内容整体替换、把 contentY 归零 ——
                //   表现就是「刚加完一台，列表啪地跳回最上面」。
                //
                //   这里的修法：**只在列表内容真的变了（增/删）时**把滚动位置
                //   按「原来那台服务器的地址」恢复回去，而不是仅凭 index 恢复
                //   （插入一行会让后面所有 index 错位）。
                //   只是刷新人数/延迟（行数没变）时完全不动，用户滚动位置不受影响。
                property string _anchorAddr: ""
                property int _lastCount: -1

                onContentYChanged: {
                    // 记录「当前视口顶部那一行」的地址，用来在列表变化后回到这里
                    if (count > 0 && contentY >= 0) {
                        var idx = indexAt(1, contentY + 4);
                        if (idx >= 0 && idx < count) {
                            var row = page.visibleServers[idx];
                            if (row)
                                srvList._anchorAddr = row.addr || "";
                        }
                    }
                }

                Connections {
                    target: page
                    function onVisibleServersChanged() {
                        var newCount = srvList.count;
                        var oldCount = srvList._lastCount;
                        srvList._lastCount = newCount;
                        // 行数没变 = 只是状态刷新，别动滚动位置
                        if (oldCount === newCount || srvList._anchorAddr.length === 0)
                            return;
                        // 行数变了（加/删）：把原来那台重新滚回视口
                        var rows = page.visibleServers;
                        var want = srvList._anchorAddr;
                        for (var i = 0; i < rows.length; ++i) {
                            if ((rows[i].addr || "") === want) {
                                srvList.positionViewAtIndex(i, ListView.Beginning);
                                return;
                            }
                        }
                        // 那台被删了 → 退一步：保持同一个 index 位置（别跳回顶部）
                        if (oldCount > 0 && srvList.contentY > 0)
                            srvList.positionViewAtIndex(
                                Math.min(newCount - 1, Math.floor(srvList.contentY / 92)),
                                ListView.Beginning);
                    }
                }

                ScrollBar.vertical: ScrollBar {
                    id: srvBar
                    objectName: "srvBar"
                    policy: ScrollBar.AsNeeded
                    width: 8
                    contentItem: Rectangle {
                        radius: 4
                        color: srvBar.pressed ? page.accent
                                              : (srvBar.hovered ? Theme.scrim(0.34) : Theme.scrim(0.2))
                    }
                    background: Item { }
                }

                delegate: Rectangle {
                    id: srvCard
                    objectName: "srvCard"
                    required property var modelData
                    required property int index
                    readonly property bool picked: page.selected && page.selected.addr === modelData.addr
                    // 「鼠标在这张卡上」——由卡片自己的 HoverHandler 提供，
                    // 不用 cardMa.containsMouse：那个会被子按钮抢走（见下面按钮行的说明）
                    readonly property bool hovered: cardHH.hovered
                    // 底部「操作带」的高度：悬浮按钮就停在这条带里，
                    // 内容（左侧信息列 / 右侧数据区）在它上方结束。
                    readonly property int actionBarH: 26

                    // 把几何情况回报给 page.cardGeometry（只报第一张卡）
                    Component.onCompleted: {
                        if (index === 0) {
                            Qt.callLater(function () {
                                page.cardGeometry = ({
                                    "cardH": Math.round(srvCard.height),
                                    "cardW": Math.round(srvCard.width),
                                    "btnRect": ({
                                        "x": Math.round(btnRow.x),
                                        "y": Math.round(btnRow.y),
                                        "w": Math.round(btnRow.width),
                                        "h": Math.round(btnRow.height)
                                    }),
                                    "infoRect": ({
                                        "x": Math.round(bigInfo.x),
                                        "y": Math.round(bigInfo.y),
                                        "w": Math.round(bigInfo.width),
                                        "h": Math.round(bigInfo.height)
                                    })
                                })
                            })
                        }
                    }

                    width: srvList.width
                    // 高度 108：左侧四行（18+18+13+14 + 间距9 + 上下边距16 = 88），
                    // 右侧三块（人数 24 + 地图 14 + 信号行 12 + 间距 4 = 54）。
                    // 高度 118 = 内容区 92 + 底部操作带 26。
                    // ★ 底部必须留出 26px 给悬浮的快捷按钮（连接/分享/编辑/移出）。
                    //   以前按钮直接压在卡片右下角，正好和「人数/地图/信号行」
                    //   那一块重叠，鼠标一悬浮就互相盖住。
                    height: 118
                    radius: Theme.radiusS
                    color: picked ? Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.08)
                                  : (srvCard.hovered ? Theme.scrim(0.06) : Theme.scrim(0.035))
                    border.width: 1
                    border.color: picked ? Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.42)
                                         : Theme.border

                    // 左侧状态细边（组头行不显示）
                    Rectangle {
                        width: 3
                        height: parent.height - 16
                        radius: 2
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        color: page.stateColor(modelData.state)
                    }
                    // ================= 右侧数据区：人数 + 地图 =================
                    // 固定宽度 120，垂直居中，右边距 12。
                    // 左侧文字列的右边界就是这一块的左边，二者永不重叠。
                    Column {
                        id: bigInfo
                        width: 120
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        // 顶部对齐、底部止于「底部操作带」之上 ——
                        // 不再 verticalCenter（那样会压到悬浮按钮）。
                        anchors.top: parent.top
                        anchors.topMargin: 8
                        anchors.bottom: srvCardTopActionBar.top
                        anchors.bottomMargin: -2
                        // 三块之间留点缝：人数 / 地图 / 信号行
                        spacing: 3

                        // 人数：大号数字（满员橙 / 有人绿 / 空服灰）
                        Row {
                            id: playersRow
                            x: parent.width - width
                            spacing: 3

                            Text {
                                id: playersNum
                                text: modelData.state === "online"
                                      ? String(modelData.players)
                                      : (modelData.state === "querying" ? "…" : "–")
                                color: {
                                    if (modelData.state !== "online")
                                        return Theme.textMute;
                                    var mx = Number(modelData.maxPlayers || 0);
                                    var pl = Number(modelData.players || 0);
                                    if (mx > 0 && pl >= mx) return page.warnColor;
                                    if (pl <= 0) return Theme.textMute;
                                    return Theme.ok;
                                }
                                font.family: Theme.monoFont
                                font.pixelSize: 20
                                font.weight: Font.Bold
                            }
                            Text {
                                id: playersMax
                                anchors.bottom: playersNum.bottom
                                anchors.bottomMargin: 3
                                text: modelData.state === "online"
                                      && Number(modelData.maxPlayers || 0) > 0
                                      ? "/" + modelData.maxPlayers : ""
                                color: Theme.textMute
                                font.family: Theme.monoFont
                                font.pixelSize: 11
                            }
                        }

                        // 地图：单独一行，右对齐
                        Text {
                            width: parent.width
                            horizontalAlignment: Text.AlignRight
                            text: page.mapText(modelData) || "地图未知"
                            color: (modelData.mapTitle || "").length > 0
                                   ? Theme.textDim : Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }

                        // 信号格 + 延迟 + 检查时间（贴着卡片右端，在人数/地图下面）
                        // 放在这里而不是左侧第 4 行：左侧那列的右边界是
                        // bigInfo.left（卡片中间），放那儿永远靠不到右边。
                        Row {
                            id: signalPart
                            x: parent.width - width
                            spacing: 4

                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 2
                                Repeater {
                                    model: 4
                                    delegate: Rectangle {
                                        width: 3
                                        height: 4 + index * 2.5
                                        anchors.bottom: parent.bottom
                                        radius: 1
                                        color: index < page.pingBars(modelData.ms)
                                               ? page.pingColor(modelData.ms)
                                               : Theme.scrim(0.14)
                                    }
                                }
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.state === "online"
                                      ? (modelData.ms + " ms") : "—"
                                color: modelData.state === "online"
                                       ? page.pingColor(modelData.ms) : Theme.textMute
                                font.family: Theme.monoFont
                                font.pixelSize: 9
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: (modelData.checkedText || "")
                                color: Theme.textMute
                                font.family: Theme.monoFont
                                font.pixelSize: 8
                            }
                        }
                    }

                    // ================= 左侧信息列 =================
                    // 四行固定高度，从上往下排，右侧到 bigInfo 为止。
                    Column {
                        id: leftCol
                        anchors.left: parent.left
                        // 选择模式下给勾选框让位
                        anchors.leftMargin: page.selectMode ? 36 : 14
                        anchors.right: bigInfo.left
                        anchors.rightMargin: 10
                        anchors.top: parent.top
                        anchors.topMargin: 8
                        // 底部止于操作带之上，避免第 4 行（地址）被按钮压住
                        anchors.bottom: srvCardTopActionBar.top
                        anchors.bottomMargin: 4
                        spacing: 3
                        Behavior on anchors.leftMargin { NumberAnimation { duration: 120 } }

                        // ---- 第 1 行：模式 / 标签 / 密码 / 权重 / 状态
                        Row {
                            width: parent.width
                            height: 18
                            spacing: 5

                            // 模式胶囊
                            Rectangle {
                                height: 17
                                width: modeTxt.implicitWidth + 14
                                anchors.verticalCenter: parent.verticalCenter
                                radius: 8.5
                                color: Qt.rgba(page.modeColor(modelData.mode).r,
                                               page.modeColor(modelData.mode).g,
                                               page.modeColor(modelData.mode).b, 0.16)
                                border.width: 1
                                border.color: Qt.rgba(page.modeColor(modelData.mode).r,
                                                      page.modeColor(modelData.mode).g,
                                                      page.modeColor(modelData.mode).b, 0.35)
                                Text {
                                    id: modeTxt
                                    anchors.centerIn: parent
                                    text: modelData.modeLabel
                                    color: page.modeColor(modelData.mode)
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                    font.weight: Font.DemiBold
                                }
                            }
                            // 地区标签
                            Rectangle {
                                visible: (modelData.tag || "").length > 0
                                height: 17
                                width: tagTxt.implicitWidth + 12
                                anchors.verticalCenter: parent.verticalCenter
                                radius: 8.5
                                color: Theme.scrim(0.07)
                                Text {
                                    id: tagTxt
                                    anchors.centerIn: parent
                                    text: modelData.tag
                                    color: Theme.textDim
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                }
                            }
                            // 有密码
                            Rectangle {
                                visible: modelData.passworded
                                height: 17
                                width: 34
                                anchors.verticalCenter: parent.verticalCenter
                                radius: 8.5
                                color: Qt.rgba(page.warnColor.r, page.warnColor.g,
                                               page.warnColor.b, 0.14)
                                Text {
                                    anchors.centerIn: parent
                                    text: "密码"
                                    color: page.warnColor
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                }
                            }
                            // 权重
                            Rectangle {
                                visible: Number(modelData.weight || 0) !== 0
                                height: 15
                                width: weightTxt.implicitWidth + 12
                                anchors.verticalCenter: parent.verticalCenter
                                radius: 7.5
                                color: Theme.scrim(0.08)
                                Text {
                                    id: weightTxt
                                    anchors.centerIn: parent
                                    text: "权重 " + modelData.weight
                                    color: Theme.textDim
                                    font.family: Theme.monoFont
                                    font.pixelSize: 9
                                }
                            }
                            // 非在线状态文字
                            Text {
                                visible: modelData.state !== "online"
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.state === "querying" ? "查询中…"
                                      : (modelData.state === "off" ? "离线" : "未查询")
                                color: Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                        }

                        // ---- 第 2 行：服务器名
                        Text {
                            width: parent.width
                            height: 18
                            verticalAlignment: Text.AlignVCenter
                            text: page.titleOf(modelData)
                            color: Theme.text
                            font.family: Theme.uiFont
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }

                        // ---- 第 3 行：自报名（和备注不同时才显示）
                        Text {
                            width: parent.width
                            height: visible ? 13 : 0
                            visible: (modelData.liveName || "").length > 0
                                     && modelData.liveName !== page.titleOf(modelData)
                            verticalAlignment: Text.AlignVCenter
                            text: modelData.liveName
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }

                        // ---- 第 4 行：只放地址
                        // 信号格 / 延迟 / 检查时间已经挪到**右侧数据区**的下面一行
                        // （见 bigInfo 里的信号行）。
                        //
                        // ★ 以前它们在这一行的右端，但这一行的父容器（leftCol）
                        //   右边界是 bigInfo.left —— 也就是卡片**中间**，
                        //   所以视觉上「延迟和时间停在中间」，并没有贴到卡片右侧。
                        //   挪进 bigInfo 后就是真正贴着卡片右端了。
                        Text {
                            width: parent.width
                            height: 14
                            verticalAlignment: Text.AlignVCenter
                            text: modelData.addr
                            color: Theme.textMute
                            font.family: Theme.monoFont
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }

                    }


                    // 底部操作带的「上边界」占位：内容区锚到它的上边即可，
                    // 比手工算 y 更稳（改高度不用同步改两处）。
                    Item {
                        id: srvCardTopActionBar
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: srvCard.actionBarH
                        // 悬浮时给操作带一层淡底，视觉上是一整条而不是几个孤立图标
                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusS
                            color: srvCard.hovered || srvCard.picked
                                   ? Theme.scrim(0.05) : "transparent"
                            Behavior on color { ColorAnimation { duration: 100 } }
                        }
                    }

                    // 卡片右侧的快捷按钮（连接 / 分享 / 编辑 / 移出）
                    //
                    // ★ 这里以前是 `visible: cardMa.containsMouse || srvCard.picked`，
                    //   于是鼠标一移到这几颗按钮上就开始**无限闪烁**：
                    //     cardMa 是铺满整卡的 MouseArea，按钮自己的 MouseArea
                    //     一旦吃掉 hover，cardMa.containsMouse 立刻变 false
                    //     → 按钮行隐藏 → 鼠标又落回卡片 → 变 true → 又显示 …
                    //   每帧来回切，看着就是狂闪（用户报的）。
                    //
                    //   修法：按钮行的显隐只由**自己的 HoverHandler**决定。
                    //   HoverHandler 只看「指针是否在这个 Item 的几何范围内」，
                    //   子项里别的 MouseArea 抢 hover 不会让它变 false，
                    //   所以不会和按钮自己的 hover 打架。
                    //   同时把它的范围盖住整张卡片（见下面 srvCardHover），
                    //   这样「移到按钮上」时 hover 一直成立。
                    //
                    // z 要比 cardMa 高：cardMa 是 anchors.fill 的兄弟项、声明在后面，
                    // 不加 z 的话点这些按钮会被它吃掉（「删不掉服务器」就是这么来的）
                    Row {
                        id: btnRow
                        anchors.right: parent.right
                        anchors.rightMargin: 10
                        // 垂直居中在「底部操作带」里
                        anchors.verticalCenter: srvCardTopActionBar.verticalCenter
                        spacing: 4
                        z: 2
                        visible: srvCard.hovered || srvCard.picked

                        IconButton {
                            objectName: "srvCardConnect"
                            glyph: "\uE768"
                            tip: "连接"
                            boxSize: 22
                            onClicked: page.connectTo(srvCard.modelData)
                        }
                        IconButton {
                            objectName: "srvCardShare"
                            glyph: "\uE72D"      // Share
                            tip: "分享给好友（复制地址文本）"
                            boxSize: 22
                            onClicked: page.askShare(srvCard.modelData)
                        }
                        IconButton {
                            objectName: "srvCardEdit"
                            glyph: "\uE70F"
                            tip: "编辑"
                            boxSize: 22
                            onClicked: page.openAddDialog(srvCard.modelData)
                        }
                        IconButton {
                            objectName: "srvCardRemove"
                            glyph: "\uE711"
                            tip: "移出列表"
                            boxSize: 22
                            danger: true
                            onClicked: {
                                page.mgr.removeServer(srvCard.modelData.addr)
                                if (page.selected && page.selected.addr === srvCard.modelData.addr)
                                    page.selected = null
                            }
                        }
                    }

                    MouseArea {
                        id: cardMa
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.LeftButton
                        cursorShape: Qt.PointingHandCursor
                        // 选择模式下单击 = 勾选/取消，不切详情（免得连点两下跳来跳去）
                        onClicked: {
                            if (page.selectMode)
                                page.toggleChecked(srvCard.modelData.addr);
                            else
                                page.selectServer(srvCard.modelData);
                        }
                        onDoubleClicked: {
                            if (!page.selectMode)
                                page.connectTo(srvCard.modelData);
                        }
                    }
                    // 选择模式下的勾选框。
                    // 放在**卡片最左边、压住那条状态细条**的位置：那里本来是空的，
                    // 不会盖到「模式胶囊 / 名字 / 地址」这三行文字
                    // （一开始我放在 leftMargin:10，正好压在模式胶囊上）。
                    Rectangle {
                        objectName: "srvCardCheck"
                        visible: page.selectMode
                        anchors.left: parent.left
                        anchors.leftMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        width: 20
                        height: 20
                        radius: 6
                        z: 3
                        property bool on: (page.checked || {})[srvCard.modelData.addr] === true
                        color: on ? page.accent : Theme.scrim(0.12)
                        border.width: on ? 0 : 1
                        border.color: Theme.borderHi

                        Text {
                            anchors.centerIn: parent
                            visible: parent.on
                            text: "\uE73E"       // CheckMark
                            font.family: Theme.iconFont
                            font.pixelSize: 11
                            color: Theme.bg
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.toggleChecked(srvCard.modelData.addr)
                        }
                    }

                    // 整张卡片的 hover 判定。挂在卡片上（不是 cardMa 上），
                    // 所以按钮行显隐和卡片底色都不再受「谁的 MouseArea 抢到 hover」影响。
                    // blocking: false —— 不抢指针事件，卡片本身的点击照旧走 cardMa。
                    HoverHandler {
                        id: cardHH
                        blocking: false
                    }
                }
            }

            // 空状态
            Column {
                anchors.centerIn: parent
                width: Math.min(420, parent.width - 40)
                spacing: 10
                visible: !page.mgr || page.mgr.serverCount === 0

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "\uE968"
                    font.family: Theme.iconFont
                    font.pixelSize: 40
                    color: Theme.scrim(0.24)
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "还没有服务器，点右上角「添加服务器」存一个"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: "收藏之后这里会显示服务器名、模式、地图和人数；点一下就能看谁在里面。\n只想进一次的话，右边那颗「IP 直连」填个 IP 就行。"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    lineHeight: 1.4
                }
            }

            // ---------------- 多选操作栏 ----------------
            // 选择模式下浮在列表底部：已选数量 + 全选 + 删除 + 取消。
            // 用不透明的底色盖住列表底部，避免和卡片文字叠在一起。
            Rectangle {
                id: selBar
                objectName: "srvSelBar"
                visible: page.selectMode
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: visible ? 46 : 0
                radius: Theme.radiusS
                color: Theme.panel
                border.width: 1
                border.color: Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.42)
                z: 10

                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 10

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "已选 " + page.checkedCount() + " 台"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: page.checkedCount() >= page.visibleServers.length
                              && page.visibleServers.length > 0 ? "全不选" : "全选"
                        color: selectAllMa.containsMouse ? page.accent : Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                        MouseArea {
                            id: selectAllMa
                            anchors.fill: parent
                            anchors.margins: -5
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.setAllChecked(
                                !(page.checkedCount() >= page.visibleServers.length
                                  && page.visibleServers.length > 0))
                        }
                    }
                }

                Row {
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8

                    // 导出选中：和「删除选中」一样只在多选栏里出现，
                    // 放在「取消」左边（用户截图里指的位置）
                    ActionButton {
                        objectName: "srvSelExportBtn"
                        width: 108
                        height: 30
                        accent: false
                        label: "导出配置"
                        enabledBtn: page.checkedCount() > 0
                        onClicked: page.askExportChecked()
                    }
                    ActionButton {
                        width: 76
                        height: 30
                        accent: false
                        label: "取消"
                        onClicked: page.exitSelect()
                    }
                    ActionButton {
                        objectName: "srvSelDeleteBtn"
                        width: 96
                        height: 30
                        label: "删除选中"
                        enabledBtn: page.checkedCount() > 0
                        onClicked: selConfirm.open()
                    }
                }
            }

            // 删除确认（多选删除是不可撤销的，问一句）
            Popup {
                id: selConfirm
                objectName: "srvSelConfirm"
                anchors.centerIn: Overlay.overlay
                modal: true
                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                padding: 20
                contentWidth: 340
                contentHeight: selConfirmCol.implicitHeight

                background: Rectangle {
                    radius: 14
                    color: Theme.panel
                    border.width: 1
                    border.color: Theme.borderHi
                }

                contentItem: Column {
                    id: selConfirmCol
                    width: 340
                    spacing: 10

                    Text {
                        text: "移出 " + page.checkedCount() + " 台服务器？"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }
                    Text {
                        width: parent.width
                        text: "只是从收藏列表里移出，不会影响游戏里的任何东西。"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        wrapMode: Text.WordWrap
                    }
                    Row {
                        width: parent.width
                        spacing: 8
                        Item { width: Math.max(0, parent.width - 172); height: 1 }
                        ActionButton {
                            width: 76
                            height: 30
                            accent: false
                            label: "取消"
                            onClicked: selConfirm.close()
                        }
                        ActionButton {
                            objectName: "srvSelDeleteConfirm"
                            width: 88
                            height: 30
                            label: "移出列表"
                            onClicked: {
                                selConfirm.close();
                                page.removeChecked();
                            }
                        }
                    }
                }
            }

            // 搜索空结果：有收藏、但一条都没命中（和上面那个「还没有服务器」是两回事）
            Column {
                objectName: "srvNoMatch"
                anchors.centerIn: parent
                width: Math.min(420, parent.width - 40)
                spacing: 10
                visible: page.mgr !== null && page.mgr.serverCount > 0
                         && (page.query || "").trim().length > 0
                         && page.matchCount === 0

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "\uE721"
                    font.family: Theme.iconFont
                    font.pixelSize: 34
                    color: Theme.scrim(0.22)
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "没有匹配「" + page.query.trim() + "」的服务器"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: "搜索会看名字、地址、地图和模式；空格分隔的多个词要同时命中。"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    lineHeight: 1.4
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 96
                    height: 28
                    radius: 14
                    color: noMatchClearMa.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.05)
                    border.width: 1
                    border.color: Theme.border
                    Text {
                        anchors.centerIn: parent
                        text: "清空搜索"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                    MouseArea {
                        id: noMatchClearMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.clearQuery()
                    }
                }
            }
            }
        }

        // ---- 右：检查员面板
        Rectangle {
            id: panel
            objectName: "srvPanel"
            width: 366
            height: parent.height
            radius: Theme.radius
            color: Theme.scrim(0.05)
            border.width: 1
            border.color: Theme.border
            clip: true

            // 没选中时的说明
            Column {
                anchors.centerIn: parent
                width: parent.width - 48
                spacing: 8
                visible: !page.selected

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "\uE9D9"
                    font.family: Theme.iconFont
                    font.pixelSize: 32
                    color: Theme.scrim(0.22)
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: page.mgr && page.mgr.serverCount > 0 ? "点左边任意一台看详情"
                                                                 : "还没有收藏服务器"
                    color: Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: "详情里能看到模式、地图、延迟，还有在线玩家和分数；\n「连接」会直接唤起 Steam。"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    lineHeight: 1.5
                }
            }

            Column {
                id: detailCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 16
                anchors.topMargin: 16
                height: parent.height - 32
                spacing: 10
                visible: page.selected !== null && page.selected !== undefined

                // 名字 + 备注编辑
                Text {
                    width: parent.width
                    text: page.selected ? page.titleOf(page.selected) : ""
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 16
                    font.weight: Font.Bold
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    visible: page.selected && (page.selected.name || "").length > 0
                    text: page.selected ? page.selected.name : ""
                    color: Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }

                // 地址 + 复制
                Rectangle {
                    width: parent.width
                    height: 28
                    radius: Theme.radiusXS
                    color: Theme.scrim(0.07)

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 10
                        anchors.right: copyTxt.left
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        text: page.selected ? page.selected.addr : ""
                        color: Theme.text
                        font.family: Theme.monoFont
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                    Text {
                        id: copyTxt
                        anchors.right: parent.right
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: "复制"
                        color: copyMa.containsMouse ? page.accent : Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        MouseArea {
                            id: copyMa
                            anchors.fill: parent
                            anchors.margins: -4
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: if (page.mgr && page.selected) page.mgr.copyAddress(page.selected.addr)
                        }
                    }
                }

                // 备注：点一下就能改，回车保存
                Row {
                    width: parent.width
                    height: 26
                    spacing: 8

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "备注"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                    Rectangle {
                        width: parent.width - 44
                        height: 26
                        radius: Theme.radiusXS
                        color: Theme.scrim(0.06)
                        border.width: 1
                        border.color: noteText.activeFocus ? page.accent : "transparent"

                        HoverHandler { cursorShape: Qt.IBeamCursor }

                        TextInput {
                            id: noteText
                            objectName: "srvNoteInput"
                            anchors.left: parent.left
                            anchors.leftMargin: 8
                            anchors.right: parent.right
                            anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            text: page.noteDraft
                            color: Theme.text
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                            selectByMouse: true
                            clip: true
                            selectionColor: Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.35)
                            onTextChanged: page.noteDraft = text
                            onEditingFinished: {
                                if (page.mgr && page.selected)
                                    page.mgr.renameServer(page.selected.addr, page.noteDraft)
                            }
                            Keys.onEscapePressed: function (event) {
                                page.noteDraft = page.selected ? (page.selected.name || "") : ""
                                noteText.focus = false
                                event.accepted = true
                            }
                            Text {
                                anchors.fill: parent
                                verticalAlignment: Text.AlignVCenter
                                visible: noteText.text.length === 0
                                text: "给它起个容易认的名字"
                                color: Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                        }
                    }
                }

                // 元数据网格（两列，键值对）
                Grid {
                    width: parent.width
                    columns: 2
                    columnSpacing: 10
                    rowSpacing: 6

                    Repeater {
                        // 「字体看着怪」的根因：这一格原来**全部**用 Theme.monoFont
                        // （Consolas）。Consolas 没有中文字形，中文要靠系统回退字体补，
                        // 于是「黑色狂欢节 1高速公路」这种中英混排的字重/基线全不一致，
                        // 看着又细又飘（用户报的）。
                        // 现在按内容类型分：
                        //   · 含中文的（模式 / 地图 / 版本）→ UI 字体，中英同一套字形
                        //   · 纯数字的（人数 / BOT / 延迟）→ 保留等宽，数字对齐更好看
                        // 每一项都带 `mono` 标记，省得在 delegate 里再判断内容。
                        model: page.selected ? [
                            { k: "模式", v: page.selected.modeLabel, mono: false },
                            { k: "地图", v: page.mapText(page.selected), mono: false },
                            { k: "人数", v: page.selected.state === "online"
                                           ? page.selected.players + " / " + page.selected.maxPlayers
                                           : "—", mono: true },
                            { k: "BOT", v: String(page.selected.bots || 0), mono: true },
                            { k: "延迟", v: page.selected.state === "online"
                                           ? page.selected.ms + " ms" : "—", mono: true },
                            { k: "版本", v: page.selected.version || "—", mono: false }
                        ] : []

                        delegate: Column {
                            required property var modelData
                            width: (panel.width - 32 - 10) / 2 - 4
                            spacing: 2
                            // 键名：小而暗，统一 UI 字体（中文标签不该走等宽）
                            Text {
                                text: modelData.k
                                color: Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                            // 值：按 mono 标记选字体，字号统一 12（原来 11 偏小）
                            Text {
                                width: parent.width
                                text: modelData.v
                                color: Theme.text
                                font.family: modelData.mono ? Theme.monoFont
                                                            : Theme.uiFont
                                font.pixelSize: 12
                                // 中英混排的字段用 DemiBold：回退字体的中文笔画偏细，
                                // 不加粗会和英文/数字视觉重量差一截
                                font.weight: modelData.mono ? Font.Normal
                                                            : Font.DemiBold
                                elide: Text.ElideRight
                            }
                        }
                    }
                }

                // 动作区：一颗主按钮 + 一排图标按钮。
                //
                // 以前这里是四颗文字按钮（连接 / 编辑 / 复制命令 / 刷新），
                // 详情面板只有 366 宽，再加上「分享」当场就挤出去了 ——
                // 最后一个按钮被面板裁掉一半（截图里能看见）。
                // 现在文字只留给最常用的「连接服务器」，其余都收成图标按钮
                // （都有 tooltip），窄面板也放得下。
                Row {
                    width: parent.width
                    spacing: 6

                    ActionButton {
                        objectName: "srvConnectBtn"
                        label: "连接服务器"
                        glyph: "\uE768"
                        accent: true
                        height: 34
                        width: Math.min(136, parent.width - 4 * 34)
                        enabledBtn: page.selected !== null && page.selected !== undefined
                        onClicked: page.connectTo(page.selected)
                    }

                    IconButton {
                        objectName: "srvEditBtn"
                        glyph: "\uE70F"
                        tip: "编辑这台"
                        boxSize: 30
                        enabledBtn: page.selected !== null && page.selected !== undefined
                        onClicked: if (page.selected) page.openAddDialog(page.selected)
                    }
                    IconButton {
                        objectName: "srvCmdBtn"
                        glyph: "\uE8C8"
                        tip: "复制 connect 命令"
                        boxSize: 30
                        enabledBtn: page.selected !== null && page.selected !== undefined
                        onClicked: if (page.mgr && page.selected) page.mgr.copyConnectCommand(page.selected.addr)
                    }
                    IconButton {
                        objectName: "srvShareBtn"
                        glyph: "\uE72D"
                        tip: "分享给好友（复制地址文本）"
                        boxSize: 30
                        enabledBtn: page.selected !== null && page.selected !== undefined
                        onClicked: page.askShare(page.selected)
                    }
                    IconButton {
                        glyph: "\uE72C"
                        tip: "刷新这台"
                        boxSize: 30
                        onClicked: if (page.mgr && page.selected) page.mgr.refreshOne(page.selected.addr)
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: Theme.border
                }

                // 玩家列表
                Row {
                    width: parent.width
                    Text {
                        text: "在线玩家"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                    Text {
                        leftPadding: 6
                        text: page.playersLoading ? "（读取中…）" : "（" + page.players.length + " 人）"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }

                Text {
                    width: parent.width
                    visible: (page.playersError || "").length > 0 && !page.playersLoading
                    text: page.playersError
                    color: page.warnColor
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    wrapMode: Text.WordWrap
                }

                ListView {
                    id: playerList
                    objectName: "srvPlayerList"
                    width: parent.width
                    // Column 里按「剩下的高度」算：y 由布局定好，height 跟着它收缩，
                    // 这样窗口变矮时玩家列表不会顶出面板底部（踩过）。
                    height: Math.max(80, detailCol.height - y)
                    clip: true
                    spacing: 2
                    boundsBehavior: Flickable.StopAtBounds
                    model: page.players

                    ScrollBar.vertical: ScrollBar {
                        id: playerBar
                        policy: ScrollBar.AsNeeded
                        width: 6
                        contentItem: Rectangle {
                            radius: 3
                            color: playerBar.pressed ? page.accent
                                                     : (playerBar.hovered ? Theme.scrim(0.34)
                                                                          : Theme.scrim(0.2))
                        }
                        background: Item { }
                    }

                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        width: playerList.width - 8
                        height: 28
                        radius: 6
                        color: index % 2 === 0 ? Theme.scrim(0.04) : "transparent"

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            // 右边那两块（时长 + 分数）加起来占 118px，名字这边让出来
                            width: parent.width - 130
                            text: modelData.name
                            color: Theme.text
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }

                        // ★ 在线时长 + 分数原来是**一行挤在一起、9px、textMute**：
                        //   时长本来就是一串「01:23:45」，小字号 + 暗色 + 等宽字体挤在
                        //   半透明条纹底上，几乎看不清（用户报的）。
                        //   现在拆成两个**独立的小胶囊**：时长用稍亮的 textDim、字号提到 10，
                        //   分数单独一个淡底块，两者不再糊成一团。
                        Row {
                            anchors.right: parent.right
                            anchors.rightMargin: 6
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 6

                            // 在线时长：给个淡底 + 提亮，一眼能读出来
                            Rectangle {
                                height: 18
                                width: timeText.width + 12
                                radius: 4
                                color: Theme.scrim(0.07)
                                anchors.verticalCenter: parent.verticalCenter
                                Text {
                                    id: timeText
                                    objectName: "srvPlayerTime"
                                    anchors.centerIn: parent
                                    text: modelData.timeText || "--:--"
                                    // 比 body 暗一档但比原来亮：原来 textMute 太糊
                                    color: Theme.textDim
                                    font.family: Theme.monoFont
                                    font.pixelSize: 10
                                    font.weight: Font.DemiBold
                                }
                            }

                            // 分数：和时长分开，别再用「   」硬拼
                            Rectangle {
                                height: 18
                                width: scoreText.width + 10
                                radius: 4
                                color: Theme.scrim(0.04)
                                anchors.verticalCenter: parent.verticalCenter
                                Text {
                                    id: scoreText
                                    objectName: "srvPlayerScore"
                                    anchors.centerIn: parent
                                    text: (modelData.score === undefined
                                           || modelData.score === null)
                                          ? "-" : (modelData.score + " 分")
                                    color: Theme.textMute
                                    font.family: Theme.monoFont
                                    font.pixelSize: 9
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------ 合集重命名
    // 自动识别不准（比如名字没规律、前缀切不出来）时，让用户自己给合集起名。
    // 名字存在 config 的 server_group_names 里，整组共用；清空 = 恢复自动识别。
    Popup {
        id: renameDlg
        objectName: "srvRenameDlg"
        visible: page.renameOpen
        onClosed: page.renameOpen = false
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        anchors.centerIn: Overlay.overlay
        padding: 20
        contentWidth: 380
        contentHeight: renameCol.implicitHeight

        Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.55) }

        background: Rectangle {
            radius: 14
            color: Theme.panel
            border.width: 1
            border.color: Theme.borderHi
        }

        contentItem: Column {
            id: renameCol
            width: 380
            spacing: 10

            Text {
                text: "重命名合集"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                text: "自动识别不准时，可以自己给这个合集起个名字（" + page.renameHint + "）。"
                      + "留空并确定 = 恢复自动识别。"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.WordWrap
                lineHeight: 1.4
            }

            Rectangle {
                width: parent.width
                height: 36
                radius: Theme.radiusXS
                color: Theme.scrim(0.05)
                border.width: 1
                border.color: renameInput.activeFocus ? Theme.accent : Theme.border

                TextInput {
                    id: renameInput
                    objectName: "srvRenameInput"
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    verticalAlignment: TextInput.AlignVCenter
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    selectByMouse: true
                    maximumLength: 24
                    text: page.renameLabel
                    onTextChanged: page.renameLabel = text
                    onAccepted: page.applyRename()
                    Keys.onEscapePressed: page.renameOpen = false

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: renameInput.text.length === 0
                        text: "给合集起个名字…"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                    }
                }
            }

            Row {
                width: parent.width
                spacing: 8
                Item { width: 1; height: 1 }
                ActionButton {
                    width: 88
                    height: 32
                    accent: false
                    label: "取消"
                    onClicked: page.renameOpen = false
                }
                ActionButton {
                    objectName: "srvRenameOkBtn"
                    width: 100
                    height: 32
                    label: "确定"
                    onClicked: page.applyRename()
                }
            }
        }

        onOpened: {
            renameInput.forceActiveFocus()
            renameInput.selectAll()
        }
    }

    // ------------------------------------------------------------ 分享弹窗
    // 后端复制到剪贴板之后弹这个：把要发出去的那段字原样摆出来，
    // 手滑复制错了能一眼看见，也能再点一次「再复制一遍」。
    Popup {
        id: shareDlg
        objectName: "srvShareDlg"
        visible: page.shareOpen
        onClosed: page.shareOpen = false
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        anchors.centerIn: Overlay.overlay
        padding: 20
        contentWidth: 420
        contentHeight: shareCol.implicitHeight

        Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.55) }

        background: Rectangle {
            radius: 14
            color: Theme.panel
            border.width: 1
            border.color: Theme.borderHi
        }

        contentItem: Column {
            id: shareCol
            width: 420
            spacing: 10

            Text {
                text: "分享给好友"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                text: "下面这段已经复制好了，直接粘到微信 / QQ 发出去就行。"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            Rectangle {
                width: parent.width
                height: shareBody.implicitHeight + 20
                radius: Theme.radiusXS
                color: Theme.scrim(0.05)
                border.width: 1
                border.color: Theme.border

                Text {
                    id: shareBody
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    text: page.shareText
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    lineHeight: 1.45
                    wrapMode: Text.WrapAnywhere
                }
            }

            Row {
                width: parent.width
                spacing: 8
                Item { width: Math.max(0, parent.width - 176); height: 1 }
                ActionButton {
                    width: 84
                    height: 30
                    accent: false
                    label: "关闭"
                    onClicked: shareDlg.close()
                }
                ActionButton {
                    width: 84
                    height: 30
                    label: "再复制一遍"
                    onClicked: {
                        if (page.mgr) page.mgr.shareServer(page.shareAddr);
                    }
                }
            }
        }
    }

    // -------------------------------------------------- 从文字导入弹窗
    // 程序侧改了 pasteText（点「读剪贴板」、清空）时把文字同步进输入框。
    // TextArea 的 text 不绑定 pasteText —— 绑了会在用户打字时来回顶光标，
    // 所以和搜索框一样：只在内容真的不一样时写一次。
    Connections {
        target: page
        function onPasteTextChanged() {
            if (pasteInput.text !== page.pasteText)
                pasteInput.text = page.pasteText
        }
    }

    Popup {
        id: pasteDlg
        objectName: "srvPasteDlg"
        visible: page.pasteOpen
        onClosed: page.pasteOpen = false
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        anchors.centerIn: Overlay.overlay
        padding: 20
        contentWidth: 460
        contentHeight: pasteCol.implicitHeight

        Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.55) }

        background: Rectangle {
            radius: 14
            color: Theme.panel
            border.width: 1
            border.color: Theme.borderHi
        }

        contentItem: Column {
            id: pasteCol
            width: 460
            spacing: 10

            // 标题行：标题占左边剩余宽度（过长自动省略），按钮固定贴右边。
            // ★ 以前这里是 `Row { Text; Item{width: 父宽-200}; Button{width:96} }`，
            //   三项加起来 = 标题宽 + (460-200) + 96 + 间距 > 460，
            //   于是「读剪贴板」被挤到对话框外面（用户报的）。
            //   占位 Item 这种写法只在「固定宽度的按钮 + 空按钮」时才算得准，
            //   标题文字一长就崩。改成锚点后与文字长度无关。
            Item {
                width: parent.width
                height: 30

                Text {
                    anchors.left: parent.left
                    anchors.right: pasteReadBtn.left
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: "从文字导入服务器"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                ActionButton {
                    id: pasteReadBtn
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: 96
                    height: 28
                    accent: false
                    label: "读剪贴板"
                    onClicked: page.readClipboardIntoPaste()
                }
            }

            Text {
                width: parent.width
                text: "把带服务器地址的一段话贴进来（ip:port、connect 命令、steam://connect/ 都认），"
                      + "会自动找出里面的服务器。"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            Rectangle {
                width: parent.width
                height: 96
                radius: Theme.radiusXS
                color: Theme.scrim(0.05)
                border.width: 1
                border.color: pasteInput.activeFocus ? page.accent : Theme.border

                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 8
                    TextArea {
                        id: pasteInput
                        objectName: "srvPasteInput"
                        placeholderText: "例如：来这个服 1.2.3.4:27015，或者直接敲 connect 1.2.3.4:27015"
                        color: Theme.text
                        placeholderTextColor: Theme.textMute
                        font.family: Theme.monoFont
                        font.pixelSize: 11
                        wrapMode: TextArea.WrapAnywhere
                        selectByMouse: true
                        background: Item { }
                        onTextChanged: {
                            if (page.pasteText !== text) {
                                page.pasteText = text
                                page.refreshPaste()
                            }
                        }
                    }
                }
            }

            // 实时预览：找到几台、几台是新的
            Text {
                width: parent.width
                visible: page.pasteText.length > 0
                text: {
                    var info = page.pasteInfo || {}
                    if ((info.total || 0) === 0)
                        return "没在这段文字里找到服务器地址"
                    var s = "找到 " + info.total + " 台服务器"
                    if ((info.duplicate || 0) > 0)
                        s += "（其中 " + info.duplicate + " 台已经在收藏里，会跳过）"
                    return s
                }
                color: ((page.pasteInfo || {}).total || 0) > 0 ? Theme.ok : Theme.warn
                font.family: Theme.uiFont
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }

            Text {
                width: parent.width
                visible: ((page.pasteInfo || {}).addrs || []).length > 0
                text: ((page.pasteInfo || {}).addrs || []).join("   ")
                color: Theme.textMute
                font.family: Theme.monoFont
                font.pixelSize: 10
                wrapMode: Text.WrapAnywhere
                lineHeight: 1.4
            }

            Row {
                width: parent.width
                spacing: 8
                Item { width: Math.max(0, parent.width - 176); height: 1 }
                ActionButton {
                    width: 84
                    height: 30
                    accent: false
                    label: "取消"
                    onClicked: pasteDlg.close()
                }
                ActionButton {
                    objectName: "srvPasteImportBtn"
                    width: 84
                    height: 30
                    label: "导入"
                    enabledBtn: ((page.pasteInfo || {}).total || 0) > 0
                    onClicked: page.submitPaste()
                }
            }
        }
    }

}
