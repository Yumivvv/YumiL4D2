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
    property var allServers: mgr ? mgr.servers : []
    readonly property var visibleServers: page.filterServers(page.allServers, page.query)
    readonly property int matchCount: page.visibleServers.length

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

    // 无参版本：编辑当前选中的那台（面板里的「编辑」按钮也走这个法子）
    function openEdit() {
        if (page.selected)
            page.openAddDialog(page.selected)
    }

    function openAddDialog(row) {
        if (!page.mgr)
            return
        page.formEditing = row !== null && row !== undefined
        page.formOldAddr = page.formEditing ? row.addr : ""
        page.formName = page.formEditing ? (row.name || "") : ""
        page.formAddr = page.formEditing ? row.addr : ""
        page.formWeight = page.formEditing ? String(row.weight || 0) : "0"
        page.formAdvanced = false
        page.formClearPw = false
        page.formError = ""
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
        if (page.mgr)
            page.allServers = page.mgr.servers
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

            // 添加服务器 / IP 直连
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

            // 导出 / 导入配置：攒了一堆服务器要分享给别人时用。
            // 两颗都做成图标按钮 —— 工具条已经有三颗文字按钮，
            // 再加两颗文字会挤；这两件事也不常做。
            IconButton {
                objectName: "srvExportBtn"
                glyph: "\uEDE1"          // Save / 导出
                tip: "导出服务器配置（分享给别人用，不含密码）"
                boxSize: 30
                enabledBtn: page.mgr ? page.mgr.serverCount > 0 : false
                onClicked: page.askExport()
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

        onClosed: page.formOpen = false

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

            Row {
                width: parent.width
                spacing: 8
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: page.formEditing ? "编辑服务器" : "添加服务器"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: page.formEditing ? "IP 填错了就在这儿改" : "常去的服存下来，一进来就能看人数"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                }
            }

            // 名称
            Column {
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
                width: parent.width
                height: 26

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

            // 底部按钮
            Row {
                width: parent.width
                spacing: 8

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
                    Text {
                        anchors.centerIn: parent
                        text: page.formEditing ? "保存修改" : "添加"
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
                        onClicked: page.submitForm()
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

            // 排序切换（很窄的一排胶囊）
            Row {
                id: sortBar
                anchors.left: parent.left
                anchors.top: parent.top
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

                    width: srvList.width
                    height: 84
                    radius: Theme.radiusS
                    color: picked ? Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.08)
                                  : (srvCard.hovered ? Theme.scrim(0.06) : Theme.scrim(0.035))
                    border.width: 1
                    border.color: picked ? Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.42)
                                         : Theme.border

                    // 左侧状态细边
                    Rectangle {
                        width: 3
                        height: parent.height - 16
                        radius: 2
                        anchors.left: parent.left
                        anchors.leftMargin: 0
                        anchors.verticalCenter: parent.verticalCenter
                        color: page.stateColor(modelData.state)
                    }

                    Column {
                        anchors.left: parent.left
                        anchors.leftMargin: 14
                        anchors.right: signals.left
                        anchors.rightMargin: 10
                        anchors.top: parent.top
                        anchors.topMargin: 10
                        spacing: 4

                        Row {
                            spacing: 6
                            // 模式胶囊
                            Rectangle {
                                height: 17
                                width: modeTxt.implicitWidth + 14
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
                            // 地区标签（名字里的【CN】）
                            Rectangle {
                                visible: (modelData.tag || "").length > 0
                                height: 17
                                width: tagTxt.implicitWidth + 12
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
                            Rectangle {
                                visible: modelData.passworded
                                height: 17
                                width: 34
                                radius: 8.5
                                color: Qt.rgba(page.warnColor.r, page.warnColor.g, page.warnColor.b, 0.14)
                                Text {
                                    anchors.centerIn: parent
                                    text: "密码"
                                    color: page.warnColor
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                }
                            }
                            // 权重非 0 才显示。让人一眼看到这台排在前面
                            // 不是因为人多，是权重高。
                            Rectangle {
                                visible: Number(modelData.weight || 0) !== 0
                                anchors.verticalCenter: parent.verticalCenter
                                height: 15
                                width: weightTxt.implicitWidth + 12
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
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.state === "online"
                                      ? modelData.players + " / " + modelData.maxPlayers
                                      : (modelData.state === "querying" ? "查询中…"
                                          : (modelData.state === "off" ? "离线" : "未查询"))
                                color: modelData.state === "online" ? Theme.text : Theme.textMute
                                font.family: Theme.monoFont
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }
                        }

                        Text {
                            width: parent.width
                            text: page.titleOf(modelData)
                            color: Theme.text
                            font.family: Theme.uiFont
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }

                        Text {
                            width: parent.width
                            visible: (modelData.liveName || "").length > 0
                                     && modelData.liveName !== page.titleOf(modelData)
                            text: modelData.liveName
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }

                        Text {
                            width: parent.width
                            text: page.mapText(modelData) + "   ·   " + modelData.addr
                            color: Theme.textMute
                            font.family: Theme.monoFont
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }
                    }

                    // 右侧：信号格 + 延迟
                    Column {
                        id: signals
                        width: 56
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        anchors.top: parent.top
                        anchors.topMargin: 12
                        spacing: 3

                        Row {
                            anchors.right: parent.right
                            spacing: 2
                            Repeater {
                                model: 4
                                delegate: Rectangle {
                                    width: 4
                                    height: 5 + index * 3
                                    anchors.bottom: parent.bottom
                                    radius: 1
                                    color: index < page.pingBars(modelData.ms)
                                           ? page.pingColor(modelData.ms)
                                           : Theme.scrim(0.14)
                                }
                            }
                        }
                        Text {
                            anchors.right: parent.right
                            text: modelData.state === "online"
                                  ? (modelData.ms + " ms") : "—"
                            color: modelData.state === "online" ? page.pingColor(modelData.ms) : Theme.textMute
                            font.family: Theme.monoFont
                            font.pixelSize: 10
                        }
                        Text {
                            anchors.right: parent.right
                            text: (modelData.checkedText || "")
                            color: Theme.textMute
                            font.family: Theme.monoFont
                            font.pixelSize: 8
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
                        anchors.right: parent.right
                        anchors.rightMargin: 10
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 8
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
                        onClicked: page.selectServer(srvCard.modelData)
                        onDoubleClicked: page.connectTo(srvCard.modelData)
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
                        height: 26
                        radius: 6
                        color: index % 2 === 0 ? Theme.scrim(0.04) : "transparent"

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 130
                            text: modelData.name
                            color: Theme.text
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.timeText + "   " + modelData.score + " 分"
                            color: Theme.textMute
                            font.family: Theme.monoFont
                            font.pixelSize: 9
                        }
                    }
                }
            }
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
