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
import QtQuick.Dialogs
import L4D2

/* MOD 管理器
   左边一列是「状态 / 分类」，中间是卡片网格，右边是选中 MOD 的详情。
   网格用的是合并模型 core.mods.allModel（本地 + 创意工坊混在一起），
   想只看云 mod 就点侧边栏的「创意工坊」。
*/
Item {
    id: page
    objectName: "modPanelRoot"

    // ★ 必须裁剪：详情面板关闭时是推到右边界**之外**的，
    //   而 Item 默认不裁子项 —— 外面 Main.qml 给这个面板留了 24px 右边距，
    //   面板只推出去 8px，剩下 16px 就从那条缝里露出来了（截图里右边那条窄条）。
    //   加了 clip 之后，超出自身范围的部分一律不画。
    clip: true

    property var mgr: core.mods
    signal statusMessage(string text)

    // 根属性求值时 mgr 已经赋好值了；委托里读这些，就不会在首次求值时
    // 撞上「mgr 还是 null」而刷一屏 TypeError。
    readonly property var qStatus: mgr ? mgr.statusCounts : ({})
    readonly property var qCats: mgr ? mgr.categoryCounts : []
    readonly property int qStatusFilter: mgr ? mgr.statusFilter : 0
    readonly property string qCategory: mgr ? mgr.categoryFilter : ""
    readonly property var qSelected: mgr ? mgr.selectedItem : ({})
    readonly property real qMinMB: mgr ? mgr.minMB : 0
    readonly property real qMaxMB: mgr ? mgr.maxMB : 0
    readonly property int qHidden: mgr ? mgr.hiddenCount : 0
    readonly property int qChecked: mgr ? mgr.checkedCount : 0
    readonly property int qSortMode: mgr ? mgr.sortMode : 0
    readonly property bool qBusy: mgr ? mgr.busy : false
    readonly property bool qScanned: mgr ? mgr.scanned : false
    readonly property string qStatusText: mgr ? mgr.statusText : ""
    // ★ 详情面板**常驻**：始终显示在右侧，网格列数固定（不再因开详情而 5列↔3列
    //   来回变），卡片从不会因详情开关而重排 —— 这就是「不再跳行」的根本解法。
    //   没有选中时详情区显示「点一张卡片查看详情」的占位提示。
    readonly property bool detailOpen: true

    // 「选择」模式：打开之后卡片左下角才出现勾选框，平时不干扰浏览
    property bool selectMode: false

    // ---- MOD 简介翻译（和创意工坊详情共用 `translationReady` 那条后端）
    property string descTranslated: ""      // 译文；空 = 还没翻过
    property bool descTranslating: false
    property bool descShowTranslated: true  // 翻完默认显示译文

    // 这些状态是「跟着选中的那个 MOD 走」的：换一个 MOD 就得清空，
    // 否则会把上一个的译文安到这一个头上。
    property string descFor: ""             // 译文对应哪个 path

    function resetDescTranslation() {
        page.descTranslated = ""
        page.descTranslating = false
        page.descShowTranslated = true
        page.descFor = ""
    }

    function translateDesc() {
        var d = (page.qSelected.desc || "").trim()
        if (d.length === 0 || !page.mgr)
            return
        page.descTranslating = true
        page.descFor = page.qSelected.path || ""
        page.mgr.translateTextAsync(d)
    }

    readonly property int gap: 12
    readonly property int cardMin: 118       // 卡片最小宽度：154 → 118，让网格多放列、一屏看更多
    readonly property int sideW: 160       // 侧边栏：178 → 160，给列表多让 18px
    readonly property int detailW: 280     // 详情面板：336 → 280，给列表多让 56px

    readonly property var sortOptions: [
        { mode: 0, label: "默认排序" },
        { mode: 1, label: "优先看启用" },
        { mode: 2, label: "优先看禁用" },
        { mode: 3, label: "优先看收藏" },
        { mode: 4, label: "字母排序" },
        { mode: 5, label: "最近导入" }
    ]

    function sortLabel() {
        for (var i = 0; i < sortOptions.length; i++)
            if (sortOptions[i].mode === qSortMode)
                return qSortMode === 0 ? "排序" : sortOptions[i].label;
        return "排序";
    }

    property var pendingImport: []
    // 导入预演结果（压缩包会展开）：{ count, names, archives }
    property var pendingImportInfo: ({ count: 0, names: [], archives: [] })
    property string pendingDelete: ""
    property var pendingConvert: []
    property bool convertGameRunning: false
    // 导入确认框里也要提示「游戏正在运行」
    property bool importGameRunning: false

    // ---------------- 创意工坊导入 ----------------
    property string wsInput: ""            // 用户粘的链接/ID
    property bool wsProbing: false         // 正在解析（异步，界面不卡）
    property bool wsBusy: false            // 正在下载
    property string wsStage: ""            // 解析进度文字
    property var wsResult: ({})            // probe 的返回
    property var wsItems: []               // 可勾选的条目（本体/合集成员 + 前置）

    function openWorkshopImport() {
        wsInput = "";
        wsResult = ({});
        wsItems = [];
        wsProbing = false;
        wsBusy = false;
        wsStage = "";
        wsImportDlg.open();
    }

    // 异步解析：立刻返回，结果走 Connections 里的 onWorkshopProbed
    function runProbe() {
        if (!String(page.wsInput).trim() || page.wsProbing)
            return;
        page.wsProbing = true;
        page.wsStage = "正在解析…";
        page.wsItems = [];
        page.wsResult = ({});
        page.mgr.probeWorkshopAsync(page.wsInput);
    }

    function onProbeDone(res) {
        page.wsProbing = false;
        page.wsStage = "";
        page.wsResult = res || ({});
        var list = (res && res.items) ? res.items.slice() : [];
        page.wsItems = list;
        if (res && res.ok) {
            // 有已安装的条目 → 提示是否重新下载
            if (res.anyInstalled)
                wsRedownloadConfirm.open();
        }
    }

    function wsCheckedCount() {
        var n = 0;
        for (var i = 0; i < page.wsItems.length; i++)
            if (page.wsItems[i].checked) n++;
        return n;
    }

    // 全选 / 全不选（只作用于能下载的）
    function wsCheckAll(val) {
        var list = [];
        for (var i = 0; i < page.wsItems.length; i++) {
            var it = {};
            for (var k in page.wsItems[i]) it[k] = page.wsItems[i][k];
            it.checked = val && it.available === true;
            list.push(it);
        }
        page.wsItems = list;
    }

    function wsToggle(idx, val) {
        // QVariantList 里的元素是只读快照，改完要整体赋回去才会刷新界面
        var list = page.wsItems.slice();
        if (idx < 0 || idx >= list.length) return;
        var it = {};
        for (var k in list[idx]) it[k] = list[idx][k];
        it.checked = val;
        list[idx] = it;
        page.wsItems = list;
    }

    function runDownload() {
        if (page.wsBusy) return;
        var picked = [];
        for (var i = 0; i < page.wsItems.length; i++)
            if (page.wsItems[i].checked) picked.push(page.wsItems[i]);
        if (picked.length === 0) {
            // `page.mgr.toast` 不存在（ModManager.toast 没加 @Slot，QML 看不见），
            // 以前写成 `page.mgr.toast ? ... : null` 于是这句提示从来没弹过。
            // 走 Core 的 showToast。
            if (typeof core !== "undefined" && core)
                core.showToast("先勾选要下载的条目", "warn");
            return;
        }
        page.wsBusy = true;
        page.mgr.downloadWorkshopAsync(picked);
    }

    function onDownloadDone(res) {
        page.wsBusy = false;
        if (res && res.ok)
            wsImportDlg.close();
    }

    // ---------------- 日期选择（弹日历，不手输）
    property string datePickTarget: "from"   // "from" / "to"
    property int calYear: 0
    property int calMonth: 0                 // 1-12

    function pad2(n) {
        return (n < 10 ? "0" : "") + n;
    }

    function todayParts() {
        var d = new Date();
        return { y: d.getFullYear(), m: d.getMonth() + 1, d: d.getDate() };
    }

    function openDatePicker(target) {
        page.datePickTarget = target;
        // 已经有值就从那个月开始显示，否则从今天
        var existing = target === "from" ? page.mgr.importFrom : page.mgr.importTo;
        var y, m;
        if (existing && existing.length >= 7) {
            var parts = existing.split("-");
            y = parseInt(parts[0], 10);
            m = parseInt(parts[1], 10);
        }
        if (!y || !m || isNaN(y) || isNaN(m)) {
            var t = page.todayParts();
            y = t.y;
            m = t.m;
        }
        page.calYear = y;
        page.calMonth = m;
        datePickerDlg.open();
    }

    function calPrevMonth() {
        var y = page.calYear, m = page.calMonth - 1;
        if (m < 1) { m = 12; y -= 1; }
        page.calYear = y;
        page.calMonth = m;
    }

    function calNextMonth() {
        var y = page.calYear, m = page.calMonth + 1;
        if (m > 12) { m = 1; y += 1; }
        page.calYear = y;
        page.calMonth = m;
    }

    // 这个月有多少天
    function daysInMonth(y, m) {
        return new Date(y, m, 0).getDate();
    }

    // 这个月 1 号是星期几（0=周日）
    function firstWeekday(y, m) {
        return new Date(y, m - 1, 1).getDay();
    }

    // 生成日历格子（前面补空位，中间 1..N）
    function calCells() {
        var y = page.calYear, m = page.calMonth;
        if (!y || !m) return [];
        var lead = page.firstWeekday(y, m);
        var n = page.daysInMonth(y, m);
        var out = [];
        for (var i = 0; i < lead; i++)
            out.push({ day: 0, key: "e" + i });
        for (var d = 1; d <= n; d++)
            out.push({ day: d, key: "d" + d });
        return out;
    }

    function pickDate(day) {
        if (!day || day < 1) return;
        var s = page.calYear + "-" + page.pad2(page.calMonth) + "-" + page.pad2(day);
        var from = page.mgr.importFrom;
        var to = page.mgr.importTo;
        if (page.datePickTarget === "from") from = s;
        else to = s;
        page.mgr.setImportRange(from, to);
        datePickerDlg.close();
    }

    function isPickedDay(day) {
        if (!day) return false;
        // ★ page.mgr 在这里可能是 null：ModPanel 一建出来日历的 delegate
        //   就会调这个函数，而 mgr 的注入（core.mods）晚一步。
        //   以前直接读 page.mgr.importFrom，就会刷一屏
        //   `TypeError: Cannot read property 'importFrom' of null`。
        //   测试环境（没注入 core）更是一启动就满屏红字。
        if (!page.mgr) return false;
        var s = page.calYear + "-" + page.pad2(page.calMonth) + "-" + page.pad2(day);
        return s === page.mgr.importFrom || s === page.mgr.importTo;
    }

    function isToday(day) {
        if (!day) return false;
        var t = page.todayParts();
        return t.y === page.calYear && t.m === page.calMonth && t.d === day;
    }

    // ---------------- 加载顺序（addonlist.txt）
    property var addonItems: []          // [{name, title, exists, isLocal, ...}]
    property int addonDragFrom: -1       // 正在拖的行下标
    property int addonDragTo: -1         // 拖到哪个位置
    property int addonMissing: 0
    property string addonFilePath: ""
    // ★ 待保存的顺序。改动只在这里攒着，点「保存」才写 addonlist.txt。
    property var addonPending: []
    property bool addonDirty: false
    // 跳转到指定序号的输入框
    property string addonJumpText: ""
    property int addonJumpIndex: -1
    // 「文件不存在」标签的固定占位宽度：有就显示、没有也占位，保证右侧控件对齐
    readonly property int aoTagWidth: 64

    function openAddonOrder() {
        page.refreshAddonOrder();
        addonOrderDlg.open();
    }

    // 从后端读最新状态（打开对话框 / 撤销时用）
    function refreshAddonOrder() {
        var v = page.mgr.addonOrder || ({});
        page.addonItems = v.items ? v.items.slice() : [];
        page.addonPending = (v.items ? v.items : []).map(function (x) { return x; });
        page.addonMissing = v.missing || 0;
        page.addonFilePath = v.path || "";
        page.addonDragFrom = -1;
        page.addonDragTo = -1;
        page.addonDirty = false;
    }

    function addonEnabledCount() {
        var n = 0;
        for (var i = 0; i < page.addonItems.length; i++)
            if (page.addonItems[i].enabled) n++;
        return n;
    }

    // 只重算「显示用的列表」，不动 addonItems 里每个条目的原始字段
    function applyAddonPending() {
        var base = {};
        for (var i = 0; i < page.addonItems.length; i++) {
            var it = page.addonItems[i];
            base[it.name] = it;
        }
        var out = [];
        for (var j = 0; j < page.addonPending.length; j++) {
            var nm = page.addonPending[j].name;
            out.push(base[nm] || page.addonPending[j]);
        }
        page.addonItems = out;
    }

    // 内部：把 from 移到 to（只改内存，不写盘）
    function reorderPending(from, to) {
        if (from === to || from < 0 || to < 0) return;
        var list = page.addonPending.slice();
        if (from >= list.length || to >= list.length) return;
        var item = list.splice(from, 1)[0];
        list.splice(to, 0, item);
        page.addonPending = list;
        page.addonDirty = true;
        page.applyAddonPending();
    }

    // 上移 / 下移 / 拖拽 / 跳转都走这里（都是「改内存顺序」）
    function moveAddonRow(from, to) {
        page.reorderPending(from, to);
        page.addonDragFrom = -1;
        page.addonDragTo = -1;
    }

    // 点 # 弹出输入框，输入序号后把这一项移到那里
    function openJumpTo(index) {
        page.addonJumpIndex = index;
        page.addonJumpText = String(index + 1);
        addonJumpDlg.open();
    }

    function doJumpTo() {
        var n = page.addonItems.length;
        var want = parseInt(page.addonJumpText, 10);
        if (isNaN(want)) { addonJumpDlg.close(); return; }
        want = Math.max(1, Math.min(n, want));
        var from = page.addonJumpIndex;
        if (from >= 0 && from !== want - 1)
            page.reorderPending(from, want - 1);
        addonJumpDlg.close();
    }

    // 保存：把当前内存里的顺序写进 addonlist.txt
    function saveAddonOrder() {
        var res = page.mgr.saveAddonOrder(page.addonPending);
        if (res && res.ok) {
            page.addonDirty = false;
            page.refreshAddonOrder();
        }
    }

    // 撤销：丢掉未保存的改动，重新从文件读
    function reloadAddonOrder() {
        page.refreshAddonOrder();
    }

    // 关闭：有未保存改动时提醒一下（但允许直接关，改动丢掉）
    function closeAddonOrder() {
        if (page.addonDirty) {
            addonDiscardDlg.open();
        } else {
            addonOrderDlg.close();
        }
    }

    // 对话框真的关掉之后把状态清干净。
    // 以前按 Esc（Popup.CloseOnEscape）或点外面会绕过 closeAddonOrder，
    // 未保存的改动和「有未保存的修改 / 缺失 N」这些状态就留在内存里，
    // 下次打开还显示上次的进度，看着像没退出去。
    function resetAddonOrderState() {
        page.addonPending = [];
        page.addonDirty = false;
        page.addonDragFrom = -1;
        page.addonDragTo = -1;
        page.addonJumpText = "";
        page.addonJumpIndex = -1;
        page.refreshAddonOrder();
    }

    // 详情面板的键值行：按实际有值的项动态生成。
    // 工坊字段对本地 MOD 没意义，值可能是 "-" 或空，那就干脆不显示这一行。
    function detailRows() {
        var s = page.qSelected || ({});
        var rows = [];
        function add(k, v, u) {
            var val = (v === undefined || v === null) ? "" : String(v).trim();
            if (!val || val === "-" || val === "0" || val === "未知时间") return;
            rows.push({ k: k, v: val, u: u || "" });
        }
        add("体积", s.sizeText);
        add("替换内容", s.content);
        add("导入日期", s.importText);
        add("工坊更新", s.updatedText);
        add("工坊发布", s.createdText);
        add("作者", s.authorLabel, s.authorUrl);
        add("版本", s.vpkVersion);
        add("文件数", s.vpkFileCount > 0 ? String(s.vpkFileCount) : "");
        // 角色/武器：VPK 内部路径推断出来的，用顿号连起来
        if (s.vpkCharacters && s.vpkCharacters.length > 0)
            add("角色", s.vpkCharacters.join("、"));
        if (s.vpkWeapons && s.vpkWeapons.length > 0)
            add("武器", s.vpkWeapons.join("、"));
        add("订阅", s.subsText);
        add("浏览", s.viewsText);
        return rows;
    }

    // 旧的「每动一下立刻写盘」版本已移除：现在统一走 reorderPending()
    // 改内存，点「保存」才落盘。

    // ★ 跳行逻辑已整体移除。详情面板常驻后，网格列数固定、卡片从不重排，
    //   点卡片只会更新右侧详情内容，列表滚动位置保持不变 —— 不再需要任何
    //   revealPath / revealMod / 滚动校正。

    function fileNameOf(p) {
        var s = String(p || "");
        var i = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\"));
        return i >= 0 ? s.substring(i + 1) : s;
    }

    // FileDialog / 拖拽给的都是 file:/// URL，转成本地路径再交给 Python
    function toPath(u) {
        var s = String(u || "");
        if (s.indexOf("file:///") === 0)
            s = s.substring(8);
        else if (s.indexOf("file://") === 0)
            s = s.substring(7);
        try { return decodeURIComponent(s); } catch (e) { return s; }
    }

    // 导入前先让用户确认一遍（文件选了但没导进去最容易懵）
    function askImport(paths) {
        if (!paths || paths.length === 0)
            return;
        var list = [];
        for (var i = 0; i < paths.length; ++i)
            list.push(page.toPath(paths[i]));
        page.pendingImport = list;
        // 压缩包要先展开才知道里面到底有几个文件（预演，不落盘）
        var info = page.mgr ? page.mgr.planImport(list)
                            : { count: list.length, names: [], archives: [] };
        if (!info || !info.count)
            info = { count: list.length, names: [], archives: [] };
        page.pendingImportInfo = info;
        page.importGameRunning = page.mgr ? page.mgr.gameRunning() : false;
        importConfirm.open();
    }

    // 确认框里真正会导入多少个文件
    function pendingImportCount() {
        var info = page.pendingImportInfo;
        if (info && info.count > 0)
            return info.count;
        return page.pendingImport.length;
    }

    // 文件名最多列 5 个，剩下的用「等 N 个」带过
    function previewImportNames() {
        var info = page.pendingImportInfo;
        var names = (info && info.names) ? info.names : [];
        if (names.length === 0) {
            var out = [];
            for (var i = 0; i < page.pendingImport.length; ++i)
                out.push(page.fileNameOf(page.pendingImport[i]));
            names = out;
        }
        return names.slice(0, 5);
    }

    function doImport() {
        var list = page.pendingImport;
        importConfirm.close();
        if (list && list.length > 0 && page.mgr)
            page.mgr.importFiles(list);
        page.pendingImport = [];
        page.pendingImportInfo = ({ count: 0, names: [], archives: [] });
    }

    function askDelete(path) {
        page.pendingDelete = path || "";
        deleteConfirm.open();
    }

    // 勾选里有多少是「创意工坊」的 MOD（转换到本地只对它有意义）
    function checkedWorkshopCount() {
        return page.checkedWorkshopPaths().length;
    }

    function checkedWorkshopPaths() {
        var out = [];
        if (!page.mgr)
            return out;
        var items = page.mgr.checkedItems();
        for (var i = 0; i < items.length; ++i) {
            if (items[i] && items[i].inWorkshopDir === true)
                out.push(items[i].path);
        }
        return out;
    }

    // 转换到本地前先确认：说清数量 + 游戏在跑的话额外提醒
    function askConvert(paths) {
        var list = paths || [];
        if (list.length === 0)
            return;
        page.pendingConvert = list;
        page.convertGameRunning = page.mgr ? page.mgr.gameRunning() : false;
        convertConfirm.open();
    }

    function doConvert() {
        var list = page.pendingConvert;
        convertConfirm.close();
        if (list && list.length > 0 && page.mgr)
            page.mgr.convertToLocal(list);
        page.pendingConvert = [];
    }

    function doDelete() {
        var p = page.pendingDelete;
        deleteConfirm.close();
        if (p && page.mgr)
            page.mgr.deleteOne(p);
        page.pendingDelete = "";
    }

    // 排序已经并进筛选面板了，这两个函数保留名字给旧调用方（截图脚本 / Main.qml）用
    function openSortPopup() { filterPopup.open(); }
    function openFilterPopup() { filterPopup.open(); }
    function closeFilterPopup() {
        if (!filterPopup.opened) return false;
        filterPopup.close();
        return true;
    }

    // 设置面板里的「检测 / 手动选择」都走这里
    function openDirPicker() { dirDlg.open(); }
    function autoDetectDir() {
        if (!page.mgr)
            return;
        page.mgr.auto_detect();
    }

    Component.onCompleted: {
        if (page.mgr && !page.mgr.scanned && page.mgr.hasDir)
            page.mgr.scan();
    }

    // ==================================================================== 侧边栏
    Rectangle {
        id: sidebar
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: page.sideW
        radius: Theme.radiusS
        color: Theme.surface
        border.width: 1
        border.color: Theme.border

        Column {
            id: sideCol
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.topMargin: 10
            anchors.bottom: sideFoot.top
            anchors.bottomMargin: 8
            anchors.leftMargin: 6
            anchors.rightMargin: 6
            spacing: 2
            clip: true

            Text {
                text: "状态"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
                leftPadding: 8
                topPadding: 4
                bottomPadding: 4
            }

            Repeater {
                model: [
                    { key: 0, label: "全部模组", count: page.qStatus.all || 0 },
                    { key: 1, label: "已启用", count: page.qStatus.enabled || 0 },
                    { key: 2, label: "未启用", count: page.qStatus.disabled || 0 },
                    { key: 3, label: "创意工坊", count: page.qStatus.workshop || 0 },
                    { key: 6, label: "本地", count: page.qStatus.local || 0 },
                    { key: 4, label: "我的收藏", count: page.qStatus.favorite || 0 },
                    { key: 5, label: "可更新", count: page.qStatus.updatable || 0 }
                ]
                delegate: Rectangle {
                    required property var modelData
                    width: sideCol.width
                    height: 28
                    radius: Theme.radiusXS
                    property bool on: page.qStatusFilter === modelData.key
                    color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, sma.pressed ? 0.26 : 0.16)
                              : (sma.pressed ? Theme.scrim(0.11)
                                             : (sma.containsMouse ? Theme.scrim(0.05) : "transparent"))
                    Behavior on color { ColorAnimation { duration: 90 } }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.leftMargin: 2
                        anchors.verticalCenter: parent.verticalCenter
                        width: 3
                        height: 14
                        radius: 2
                        visible: parent.on
                        color: Theme.accent
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 13
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.label
                        color: parent.on ? Theme.text : (sma.containsMouse ? Theme.text : Theme.textDim)
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.count > 0 ? modelData.count : ""
                        color: parent.on ? Theme.accent : Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                    MouseArea {
                        id: sma
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.mgr.setStatusFilter(modelData.key)
                    }
                }
            }

            Item { width: 1; height: 10 }

            Text {
                text: "分类"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
                leftPadding: 8
                topPadding: 4
                bottomPadding: 4
            }

            Rectangle {
                width: sideCol.width
                height: 28
                radius: Theme.radiusXS
                color: page.qCategory === ""
                       ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, acma.pressed ? 0.26 : 0.16)
                       : (acma.pressed ? Theme.scrim(0.11)
                                       : (acma.containsMouse ? Theme.scrim(0.05) : "transparent"))
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 13
                    anchors.verticalCenter: parent.verticalCenter
                    text: "全部分类"
                    color: page.qCategory === "" ? Theme.text : (acma.containsMouse ? Theme.text : Theme.textDim)
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                }
                MouseArea {
                    id: acma
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: page.mgr.setCategory("")
                }
            }

            Repeater {
                model: page.qCats
                delegate: Rectangle {
                    required property var modelData
                    width: sideCol.width
                    height: 28
                    radius: Theme.radiusXS
                    property bool on: page.qCategory === modelData.key
                    color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, cma.pressed ? 0.26 : 0.16)
                              : (cma.pressed ? Theme.scrim(0.11)
                                             : (cma.containsMouse ? Theme.scrim(0.05) : "transparent"))
                    Behavior on color { ColorAnimation { duration: 90 } }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 13
                        anchors.right: catCount.left
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.label
                        elide: Text.ElideRight
                        color: parent.on ? Theme.text : (cma.containsMouse ? Theme.text : Theme.textDim)
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                    }
                    Text {
                        id: catCount
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.count
                        color: parent.on ? Theme.accent : Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                    MouseArea {
                        id: cma
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.mgr.setCategory(modelData.key)
                    }
                }
            }
        }

        // 侧边栏底部：目录入口
        Column {
            id: sideFoot
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 6
            spacing: 2

            Rectangle {
                width: parent.width
                height: 1
                color: Theme.border
            }
            Item { width: 1; height: 4 }

            Rectangle {
                width: parent.width
                height: 28
                radius: Theme.radiusXS
                color: fma.containsMouse ? Theme.scrim(0.05) : "transparent"
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: "创意工坊MOD"
                    color: fma.containsMouse ? Theme.accent : Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                }
                MouseArea {
                    id: fma
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    // 打开的是创意工坊文件夹（addons/workshop）
                    onClicked: page.mgr.openWorkshopFolder()
                }
            }

            Rectangle {
                width: parent.width
                height: 28
                radius: Theme.radiusXS
                color: lma.containsMouse ? Theme.scrim(0.05) : "transparent"
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: "本地MOD"
                    color: lma.containsMouse ? Theme.accent : Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                }
                MouseArea {
                    id: lma
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    // 打开的是本地 MOD 文件夹（addons 根目录）
                    onClicked: page.mgr.openAddonsFolder()
                }
            }
            Item { width: 1; height: 2 }
        }
    }

    // ==================================================================== 右侧详情（常驻）
    Rectangle {
        id: detail
        objectName: "modDetailPanel"
        // 和网格并列（网格右边让开了 detailW），详情面板**始终显示**
        z: 30
        // 从状态行下面开始，这样工具条和「共 N 个」那行始终看得见、按得到。
        anchors.top: parent.top
        anchors.topMargin: toolBar.height + 6 + 18 + 8
        anchors.bottom: parent.bottom

        // 宽度固定，位置固定贴在右边缘，不做任何滑入/滑出动画 ——
        // 详情常驻，网格列数恒定，这是「不再跳行」的根本。
        width: page.detailW
        anchors.right: parent.right
        clip: true
        radius: Theme.radiusS
        color: Theme.panel
        border.width: 1
        border.color: Theme.borderHi

        // 挡住滚轮，别让它在详情里滚动时把后面的网格也带跑
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.NoButton
            z: -1
            onWheel: function (wheel) { wheel.accepted = true }
        }

        // 记住上一次显示的 MOD：换了另一个 MOD 才把详情滚回顶部。
        // 不清的话上一个 MOD 滚到哪，新 MOD 一进来就停在中间，
        // 看起来就像「点了卡片但详情没变化」。
        property string lastPath: ""
        Connections {
            target: page.mgr
            function onDetailChanged() {
                var p = page.qSelected.path || "";
                if (p !== detail.lastPath) {
                    detail.lastPath = p;
                    detFlick.contentY = 0;
                    // 换了一个 MOD：把上一个的译文清掉，别张冠李戴
                    page.resetDescTranslation();
                }
            }
            // MOD 简介翻译回来了（和创意工坊详情共用这条信号）
            function onTranslationReady(res) {
                page.descTranslating = false;
                if (res && res.ok) {
                    page.descTranslated = res.text || "";
                    page.descShowTranslated = true;
                } else {
                    page.descTranslated = "";
                    // ★ 不能调 `page.mgr.toast(...)`：`ModManager.toast` 没加
                    //   `@Slot`，QML 那边根本看不见它，调用会抛
                    //   `TypeError: Property 'toast' ... is not a function`。
                    //   统一走 Core 的 `showToast`（那是正经的 @Slot）。
                    var msg = (res && res.error) || "翻译失败";
                    if (typeof core !== "undefined" && core)
                        core.showToast(msg, "error");
                }
            }
            // 创意工坊导入：异步解析的进度与结果
            function onWorkshopProbeProgress(stage, done, total) {
                page.wsStage = total > 0 ? (stage + "（" + done + "/" + total + "）")
                                          : stage;
            }
            function onWorkshopProbed(res) {
                page.onProbeDone(res);
            }
            function onWorkshopDownloaded(res) {
                page.onDownloadDone(res);
            }
            // 加载顺序变化（拖动/同步/改启用位后后端会发这个）
            function onAddonOrderChanged() {
                page.refreshAddonOrder();
            }
        }

        // 详情内容用 Flickable 包起来：窗口矮的时候按钮不会掉到看不见的地方
        Flickable {
            id: detFlick
            objectName: "modDetailFlick"
            anchors.fill: parent
            anchors.margins: 14
            contentWidth: width
            contentHeight: detCol.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                width: 12
                padding: 2
                policy: detCol.height > detFlick.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
                contentItem: Rectangle {
                    implicitWidth: 8
                    radius: 4
                    color: parent.pressed ? Theme.scrim(0.42)
                                          : (parent.hovered ? Theme.scrim(0.30) : Theme.scrim(0.20))
                }
            }

        Column {
            id: detCol
            // 右边留出滚动条的位置，否则按钮会压到滚动条下面（宽度和 contentWidth 分开管）
            width: Math.max(0, detFlick.width - 18)
            spacing: 10

            // 标题行（详情常驻，不再有关闭按钮）
            Item {
                width: parent.width
                height: 22
                Text {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: "MOD 详情"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
            }

            // 封面
            Rectangle {
                width: parent.width
                height: Math.round(width * 9 / 16)
                radius: Theme.radiusXS
                color: Theme.panelDeep
                border.width: 1
                border.color: Theme.border

                Image {
                    anchors.fill: parent
                    anchors.margins: 1
                    source: page.qSelected.hasImage ? page.qSelected.imageUrl : ""
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    visible: page.qSelected.hasImage === true
                    sourceSize.width: 600
                }
                Text {
                    anchors.centerIn: parent
                    visible: !page.qSelected.hasImage
                    text: "没有封面"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                }
            }

            // 标题
            Text {
                width: parent.width
                text: page.qSelected.title || ""
                wrapMode: Text.Wrap
                maximumLineCount: 3
                elide: Text.ElideRight
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 14
                font.weight: Font.DemiBold
                lineHeight: 1.25
            }

            // 徽标行
            Flow {
                width: parent.width
                spacing: 6

                Rectangle {
                    height: 20
                    width: badTxt.width + 16
                    radius: 5
                    color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
                    Text {
                        id: badTxt
                        anchors.centerIn: parent
                        text: page.qSelected.categoryLabel || "其他"
                        color: Theme.accent
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                }
                Rectangle {
                    height: 20
                    width: enTxt.width + 16
                    radius: 5
                    color: page.qSelected.enabled
                           ? Qt.rgba(Theme.ok.r, Theme.ok.g, Theme.ok.b, 0.16)
                           : Theme.scrim(0.07)
                    Text {
                        id: enTxt
                        anchors.centerIn: parent
                        text: page.qSelected.enabled ? "已启用" : "已禁用"
                        color: page.qSelected.enabled ? Theme.ok : Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                }
                Rectangle {
                    height: 20
                    width: idTxt.width + 16
                    radius: 5
                    visible: (page.qSelected.workshopId || "").length > 0
                    color: Qt.rgba(Theme.cyan.r, Theme.cyan.g, Theme.cyan.b, 0.14)
                    Text {
                        id: idTxt
                        anchors.centerIn: parent
                        text: "工坊 " + (page.qSelected.workshopId || "")
                        color: Theme.cyan
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                }
                // 「可更新」黄色图块，紧跟在工坊 ID 右边（以前是一大段
                // 「工坊更新时间和本地文件对得上…」的文字块，既占地方又没信息量）
                Rectangle {
                    height: 20
                    width: updBadgeTxt.width + 16
                    radius: 5
                    visible: page.qSelected.hasUpdate === true
                    color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.18)
                    border.width: 1
                    border.color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.55)
                    Text {
                        id: updBadgeTxt
                        anchors.centerIn: parent
                        text: "可更新"
                        color: Theme.warn
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.mgr.openWorkshopPage(page.qSelected.workshopId)
                    }
                }
            }

            // 基本信息
            Column {
                width: parent.width
                spacing: 5

                Repeater {
                    // ★ 用函数动态生成：工坊字段（订阅/浏览/工坊日期）对本地 MOD 没意义，
                    //   以前一律显示 "-" 白占好几行。现在按有没有值决定显不显示，
                    //   并且把 VPK 内部读到的版本号 / 文件数 / 角色 / 武器也列出来。
                    model: page.detailRows()
                    delegate: Item {
                        required property var modelData
                        width: detCol.width
                        height: 17
                        Text {
                            anchors.left: parent.left
                            width: 60
                            text: modelData.k
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 62
                            anchors.right: parent.right
                            text: modelData.v
                            elide: Text.ElideRight
                            color: modelData.u !== "" && infoMa.containsMouse
                                   ? Theme.accent : Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                            font.underline: modelData.u !== "" && infoMa.containsMouse
                        }
                        MouseArea {
                            id: infoMa
                            anchors.fill: parent
                            hoverEnabled: modelData.u !== ""
                            enabled: modelData.u !== ""
                            cursorShape: Qt.PointingHandCursor
                            onClicked: if (modelData.u !== "") Qt.openUrlExternally(modelData.u)
                        }
                    }
                }
            }

            // 工坊 tags
            Flow {
                width: parent.width
                spacing: 5
                visible: (page.qSelected.tags || []).length > 0
                Repeater {
                    model: page.qSelected.tags || []
                    delegate: Rectangle {
                        required property string modelData
                        height: 19
                        width: tagTxt.width + 14
                        radius: 5
                        color: Theme.scrim(0.06)
                        border.width: 1
                        border.color: Theme.border
                        Text {
                            id: tagTxt
                            anchors.centerIn: parent
                            text: modelData
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }
                    }
                }
            }

            // 操作按钮 + 简介：都用 Column 自然流式布局，高度自动累加。
            // 之前用 Item 把高度写死成 actions.height + descBlock.height + 60，
            // 一旦窗口较矮，detFlick 的 contentHeight 算不准，底部按钮就滚不到。
            //
            // ★ 顺序必须是「按钮在前、简介在后」：
            //   简介的 descFlick 高度跟 descEdit.contentHeight 绑定，选中 MOD 后简介
            //   一加载，整块立刻长高 ~160px，把下面的按钮推下去；窗口矮（1280x860）时
            //   按钮正好被推到窗口下边缘外面，只剩十几像素露在边框/缩放手柄那条上，
            //   于是第一下点空、第二下才点中 —— 这就是「第一次点按钮不生效」。
            //   按钮放前面，位置由封面+标题决定，不随简介高度变化，永远完整可见。
            Column {
                width: parent.width
                spacing: 10

                Column {
                    id: actions
                    width: parent.width
                    spacing: 8

                    ActionButton {
                        width: parent.width
                        accent: !page.qSelected.enabled
                        label: page.qSelected.enabled ? "禁用MOD" : "启用MOD"
                        onClicked: page.mgr.toggleEnabled(page.qSelected.path)
                    }

                    // 更新状态不再单占一块：
                    //   * 有新版 → 顶部工坊 ID 右边那个黄色「可更新」图块（点了去工坊）
                    //   * 没新版 → 什么都不显示（以前这里会挂一大段「已经是最新的」的说明，
                    //     纯占地方，还把下面真正要用的按钮往下挤）

                    ActionButton {
                        width: parent.width
                        accent: false
                        label: page.qSelected.favorited ? "★ 取消收藏" : "☆ 收藏"
                        onClicked: page.mgr.toggleFavorite(page.qSelected.path)
                    }
                    Row {
                        width: parent.width
                        spacing: 8
                        ActionButton {
                            width: (parent.width - 8) / 2
                            accent: false
                            label: "打开目录"
                            onClicked: page.mgr.openModFolder(page.qSelected.path)
                        }
                        ActionButton {
                            width: (parent.width - 8) / 2
                            accent: false
                            label: "工坊页"
                            enabledBtn: (page.qSelected.workshopId || "").length > 0
                            onClicked: page.mgr.openWorkshopPage(page.qSelected.workshopId)
                        }
                    }
                    // 唯一的「检查」入口（原「检查这个 MOD」+「重新检查这个 MOD」合并）
                    ActionButton {
                        width: parent.width
                        accent: false
                        label: "检查MOD"
                        enabledBtn: (page.qSelected.workshopId || "").length > 0
                        onClicked: page.mgr.identifyOne(page.qSelected.path)
                    }
                    // 创意工坊的 MOD 才能「转换到本地」：复制一份到 addons 根目录，
                    // 这样即使退订了工坊也还留着
                    ActionButton {
                        width: parent.width
                        accent: true
                        visible: page.qSelected.inWorkshopDir === true
                        label: "转换到本地MOD"
                        onClicked: page.askConvert([page.qSelected.path])
                    }
                    ActionButton {
                        width: parent.width
                        accent: false
                        label: "删除"
                        onClicked: page.askDelete(page.qSelected.path)
                    }
                }

                Column {
                    id: descBlock
                    width: parent.width
                    spacing: 5

                    // 「简介」标题 + 翻译按钮（和创意工坊详情里那套是同一个后端）
                    Row {
                        width: parent.width
                        spacing: 6

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "简介"
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }

                        // 小字状态：正在翻译 / 已翻译
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: page.descTranslating
                            text: "正在翻译…"
                            color: Theme.warn
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }

                        Item { width: Math.max(0, parent.width - 40 - 160); height: 1 }

                        // 已翻译时给一个「看原文 / 看译文」的切换
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: page.descTranslated.length > 0
                            text: page.descShowTranslated ? "看原文" : "看译文"
                            color: descToggleMa.containsMouse ? Theme.accent : Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            MouseArea {
                                id: descToggleMa
                                anchors.fill: parent
                                anchors.margins: -4
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: page.descShowTranslated = !page.descShowTranslated
                            }
                        }

                        // 译成中文：只在「有简介且还没翻过」时出现。
                        // 本地自制 MOD 没有简介，就不占这个位置。
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: (page.qSelected.desc || "").length > 0
                                     && page.descTranslated.length === 0
                                     && !page.descTranslating
                            text: "译成中文"
                            color: descTransMa.containsMouse ? Theme.accent : Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            MouseArea {
                                id: descTransMa
                                anchors.fill: parent
                                anchors.margins: -4
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: page.translateDesc()
                            }
                        }
                    }

                    Flickable {
                        id: descFlick
                        width: parent.width
                        height: Math.max(60, Math.min(170, descEdit.contentHeight + 4))
                        clip: true
                        contentHeight: descEdit.contentHeight
                        boundsBehavior: Flickable.StopAtBounds

                        TextEdit {
                            id: descEdit
                            width: descFlick.width
                            readOnly: true
                            selectByMouse: true
                            persistentSelection: true
                            wrapMode: TextEdit.Wrap
                            // 有译文且切到译文时显示译文，否则显示原文
                            text: (page.descShowTranslated
                                   && page.descTranslated.length > 0)
                                  ? page.descTranslated
                                  : (page.qSelected.desc && page.qSelected.desc.length > 0
                                     ? page.qSelected.desc
                                     : "这个 MOD 没有简介。\n（本地自制的 MOD 没上传创意工坊，就没有简介）")
                            color: Theme.textDim
                            selectionColor: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.45)
                            selectedTextColor: "#ffffff"
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                        ScrollBar.vertical: ScrollBar {
                            width: 10
                            policy: descEdit.contentHeight > descFlick.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
                            contentItem: Rectangle {
                                implicitWidth: 7
                                radius: 3.5
                                color: parent.pressed ? Theme.scrim(0.42)
                                                      : (parent.hovered ? Theme.scrim(0.30) : Theme.scrim(0.18))
                            }
                        }
                    }
                }

            }
        }
        }

        // 详情常驻时的「未选中」占位：用不透明背景盖住整个详情内容区，
        // 未选中时下面的空封面/按钮既不显示、也点不到（不会误触到空 path 的按钮）。
        Rectangle {
            anchors.fill: detFlick
            z: 2
            visible: (page.qSelected.path || "").length === 0
            color: Theme.panel
            // 挡住点击，避免点到被盖在下面的按钮
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.AllButtons
                onWheel: function (wheel) { wheel.accepted = true }
            }
            Column {
                anchors.centerIn: parent
                spacing: 10
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "\uE7B3"
                    font.family: Theme.iconFont
                    font.pixelSize: 34
                    color: Theme.textMute
                    opacity: 0.6
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "点左侧任意一张卡片\n查看 MOD 详情"
                    horizontalAlignment: Text.AlignHCenter
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    lineHeight: 1.5
                }
            }
        }
    }

    // ==================================================================== 中间：工具条 + 网格
    Item {
        id: center
        anchors.left: sidebar.right
        anchors.leftMargin: 12
        // 卡片墙始终占满：详情面板是浮层，不再把列宽挤变形
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.bottom: parent.bottom

        // ---- 工具条
        Item {
            id: toolBar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 36

            SearchBox {
                id: searchBox
                anchors.left: parent.left
                width: Math.min(240, Math.max(140, center.width - toolRow.width - 16))
                height: 32
                anchors.verticalCenter: parent.verticalCenter
                placeholder: "搜索 MOD 名称 / 分类…"
                onEdited: function (value) { page.mgr.setFilter(value); }
                onCleared: page.mgr.setFilter("")
            }

            Row {
                id: toolRow
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                height: 32

                ActionButton {
                    id: filterBtn
                    height: 32
                    accent: false
                    // 排序也算筛选的一部分了，所以任何一项生效都点亮
                    label: (page.qMinMB > 0 || page.qMaxMB > 0 || page.qSortMode > 0) ? "筛选 ·" : "筛选"
                    onClicked: filterPopup.opened ? filterPopup.close() : filterPopup.open();
                }
                ActionButton {
                    id: selectBtn
                    height: 32
                    accent: page.selectMode
                    label: page.selectMode ? "选择中" : "选择"
                    onClicked: {
                        page.selectMode = !page.selectMode;
                        if (page.selectMode)
                            page.mgr.clearSelected();   // 选择模式下不看详情，省得两件事打架
                        else
                            page.mgr.clearSelection();
                    }
                }
                ActionButton {
                    height: 32
                    accent: false
                    label: "导入"
                    onClicked: fileDlg.open()
                }
                // 创意工坊导入：粘 ID / 链接（也支持合集），下到 addons
                ActionButton {
                    objectName: "wsDownloadButton"
                    height: 32
                    accent: false
                    label: "创意工坊导入"
                    onClicked: page.openWorkshopImport()
                }
                // 加载顺序：改 addonlist.txt 里的真实加载优先级
                ActionButton {
                    objectName: "addonOrderButton"
                    height: 32
                    accent: false
                    label: "加载顺序"
                    onClicked: page.openAddonOrder()
                }
                ActionButton {
                    height: 32
                    accent: false
                    label: "检查 MOD 文件"
                    busy: page.qBusy
                    onClicked: page.mgr.identifyWorkshop()
                }
                ActionButton {
                    height: 32
                    accent: false
                    label: "刷新"
                    busy: page.qBusy
                    onClicked: page.mgr.scan()
                }
                // 「启动游戏」已经从 MOD 面板移走 —— 见侧栏左下角那颗播放图标。
                // 理由：启动游戏是**全局动作**，不该只在 MOD 页出现；
                // 而且它原来占着工具条一个位置，把「检查 MOD 文件 / 刷新」挤窄了。
            }
        }

        // ---- 状态行
        // 只留左边那串统计（共 N 个 · 合计 X GB）。
        // 右边原来还挂着一份 qStatusText（「检查完成：xxx」之类），和标题栏里那句
        // 完全重复，白占一行、还容易分散注意力，已经去掉。
        Item {
            id: statLine
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: toolBar.bottom
            anchors.topMargin: 6
            height: 18

            Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: {
                    if (!page.qScanned)
                        return "还没扫描";
                    var parts = ["共 " + page.mgr.totalCount + " 个"];
                    if (page.qHidden > 0)
                        parts.push("被筛选挡住 " + page.qHidden + " 个");
                    if (page.qChecked > 0)
                        parts.push("已选中 " + page.qChecked + " 个");
                    parts.push("合计 " + page.mgr.totalSizeText);
                    return parts.join("　·　");
                }
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
            }
        }

        // ---- 卡片网格
        GridView {
            id: grid
            anchors.left: parent.left
            // 详情面板**常驻**：网格右边界固定让出 detailW+12，列数恒定，
            // 卡片从不会因详情开关而重排（跳行问题的根源被彻底移除）。
            anchors.right: parent.right
            anchors.rightMargin: page.detailW + 12
            anchors.top: statLine.bottom
            anchors.topMargin: 8
            anchors.bottom: batchBar.top
            anchors.bottomMargin: batchBar.height > 1 ? 10 : 0
            clip: true

            model: page.mgr ? page.mgr.allModel : null
            boundsBehavior: Flickable.StopAtBounds

            readonly property int cols: Math.max(2, Math.floor((width + page.gap) / (page.cardMin + page.gap)))
            cellWidth: Math.floor(width / cols)
            cellHeight: Math.floor(cellWidth * 0.60) + 82

            ScrollBar.vertical: ScrollBar {
                width: 12
                padding: 2
                policy: ScrollBar.AsNeeded
                contentItem: Rectangle {
                    implicitWidth: 8
                    radius: 4
                    color: parent.pressed ? Theme.scrim(0.42)
                                          : (parent.hovered ? Theme.scrim(0.32) : Theme.scrim(0.20))
                }
            }

            delegate: Item {
                id: card
                width: grid.cellWidth - page.gap
                height: grid.cellHeight - page.gap

                // 用 required property 直接接角色，不要靠 model.selected。
                // Qt 6 的 model 代理在某些情况下不会把动态角色暴露成属性，
                // 读 model.selected 会静默得到 undefined —— 选中框就永远画不出来。
                required property int index
                required property bool selected
                required property string path
                required property string title
                required property string stem
                required property string sizeText
                required property string categoryLabel
                required property string content
                // 不叫 enabled：Item 本身有 enabled，重名会让 QML 报
                // 「overrides a member of the base object」，而且容易误伤可见性。
                required property bool enabledState
                required property bool hasImage
                required property string imageUrl
                required property bool favorited
                required property bool hasUpdate
                required property bool checked
                required property bool inWorkshopDir

                // 选中指示：一整圈描边，**画在所有内容之上**。
                // 之前把边框放在 cardBg 上，而 cardBg 没有 z、封面/标题都是后画的兄弟，
                // 覆盖区把边框盖掉了 —— 实测 delegate 里 selected=true，
                // 但截图上连一个红像素都找不到。现在单独抽出来并给 z: 6。
                // enabled: false —— 纯视觉层，不参与任何鼠标交互/命中，
                // 否则会挡住下面 hover MouseArea 的点击（选择模式勾选失效）。
                Rectangle {
                    visible: card.selected
                    z: 6
                    enabled: false
                    anchors.fill: parent
                    anchors.margins: -2
                    radius: Theme.radiusS + 2
                    color: "transparent"
                    border.width: 3
                    border.color: Theme.accent
                }

                Rectangle {
                    visible: card.selected
                    z: 5
                    enabled: false
                    anchors.fill: parent
                    anchors.margins: -6
                    radius: Theme.radiusS + 6
                    color: "transparent"
                    border.width: 2
                    border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.45)
                }

                Rectangle {
                    id: cardBg
                    anchors.fill: parent
                    radius: Theme.radiusS
                    // 底色也跟着变，选中时整卡泛红（这一层在内容下面，只负责底色）
                    color: card.selected
                           ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.22)
                           : (hover.containsMouse ? Theme.surfaceHi : Theme.surfaceHi)
                    Behavior on color { ColorAnimation { duration: 120 } }
                }

                // 「已选中」文字角标去掉了 —— 用户要的是「点开详情后能找回自己点的那个」，
                // 那件事靠红色边框 + 自动滚到它所在位置就够了，不需要多一个标签挡住封面。

                // 封面
                Item {
                    id: coverBox
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 6
                    height: parent.height - 74

                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radiusXS
                        color: Theme.panelDeep
                    }
                    Image {
                        anchors.fill: parent
                        anchors.margins: 1
                        source: card.hasImage ? card.imageUrl : ""
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        visible: card.hasImage === true
                        sourceSize.width: 360
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: !card.hasImage
                        text: (card.title || "?").substring(0, 1)
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 26
                        opacity: 0.55
                    }

                    // 左上角：启用状态
                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.margins: 6
                        height: 19
                        width: stTxt.width + 16
                        radius: 5
                        color: card.enabledState ? Qt.rgba(0.05, 0.16, 0.12, 0.86) : Qt.rgba(0.10, 0.11, 0.14, 0.86)
                        border.width: 1
                        border.color: card.enabledState ? Qt.rgba(Theme.ok.r, Theme.ok.g, Theme.ok.b, 0.55)
                                                    : Theme.scrim(0.16)
                        Row {
                            anchors.centerIn: parent
                            spacing: 4
                            Rectangle {
                                width: 5
                                height: 5
                                radius: 2.5
                                anchors.verticalCenter: parent.verticalCenter
                                color: card.enabledState ? Theme.ok : Theme.textMute
                            }
                            Text {
                                id: stTxt
                                anchors.verticalCenter: parent.verticalCenter
                                text: card.enabledState ? "已启用" : "未启用"
                                color: card.enabledState ? Theme.ok : Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                        }
                    }

                    // 右上角：收藏星标
                    // z 要比整卡的那个 MouseArea 高，否则点击会被它吃掉
                    //
                    // ★ 以前只有一个裸的 "☆" 字符，颜色是 scrim(0.55)，
                    //   压在浅色封面上几乎看不见（用户反馈「星标不明显」）。
                    //   现在给它一个深色圆底 + 描边，未收藏也一眼能看到；
                    //   收藏后变成实心金色星 + 金色描边，状态对比很强。
                    Item {
                        id: star
                        z: 2
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 6
                        width: 26
                        height: 26

                        Rectangle {
                            anchors.fill: parent
                            radius: width / 2
                            // 已收藏：金色小圆底；未收藏：半透明黑底（压在封面上都看得清）
                            color: card.favorited
                                   ? Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.92)
                                   : (starMa.containsMouse
                                      ? Qt.rgba(0, 0, 0, 0.72)
                                      : Qt.rgba(0, 0, 0, 0.52))
                            border.width: 1
                            border.color: card.favorited
                                          ? Qt.rgba(1, 1, 1, 0.55)
                                          : Qt.rgba(1, 1, 1, 0.35)
                            Behavior on color { ColorAnimation { duration: 110 } }
                            scale: starMa.pressed ? 0.88
                                                  : (starMa.containsMouse ? 1.10 : 1.0)
                            Behavior on scale {
                                NumberAnimation { duration: 110; easing.type: Easing.OutCubic }
                            }
                        }

                        Text {
                            anchors.centerIn: parent
                            text: card.favorited ? "★" : "☆"
                            // 已收藏时星是深色（压在金底上），未收藏时是亮白
                            color: card.favorited ? "#4A3200" : "#FFFFFF"
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }

                        MouseArea {
                            id: starMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.mgr.toggleFavorite(card.path)
                        }
                    }
                }

                // 标题
                Text {
                    id: cardTitle
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: coverBox.bottom
                    anchors.leftMargin: 7
                    anchors.rightMargin: 7
                    anchors.topMargin: 4
                    height: 32
                    text: card.title || card.stem || ""
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    color: card.enabledState ? Theme.text : Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    lineHeight: 1.15
                }

                // 分类 · 体积 · 替换内容
                Text {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: cardTitle.bottom
                    anchors.leftMargin: 7
                    anchors.rightMargin: 7
                    text: {
                        var parts = [card.categoryLabel || "其他", card.sizeText || ""];
                        if (card.content)
                            parts.push(card.content);
                        return parts.join(" · ");
                    }
                    elide: Text.ElideRight
                    maximumLineCount: 1
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                }

                // 可更新提示
                Rectangle {
                    anchors.right: parent.right
                    anchors.rightMargin: 7
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 6
                    height: 17
                    width: updTxt.width + 12
                    radius: 4
                    visible: card.hasUpdate === true
                    color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.16)
                    border.width: 1
                    border.color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.45)
                    Text {
                        id: updTxt
                        anchors.centerIn: parent
                        text: "可更新"
                        color: Theme.warn
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }

                // 勾选框：只在「选择」模式出现，放在封面右下角，不再占标题/底行的位置
                // z: 2 —— 必须压过整卡那个 MouseArea，否则根本点不动
                Item {
                    id: checkBox
                    z: 2
                    anchors.right: coverBox.right
                    anchors.bottom: coverBox.bottom
                    anchors.rightMargin: 6
                    anchors.bottomMargin: 6
                    width: 20
                    height: 20
                    visible: page.selectMode
                    opacity: card.checked ? 1 : 0.8
                    Rectangle {
                        anchors.centerIn: parent
                        width: 18
                        height: 18
                        radius: 5
                        color: card.checked ? Theme.accent : Qt.rgba(0, 0, 0, 0.62)
                        border.width: 1.5
                        border.color: card.checked ? Theme.accent : Theme.scrim(0.7)
                        Text {
                            anchors.centerIn: parent
                            visible: card.checked === true
                            text: "✓"
                            color: "#ffffff"
                            font.pixelSize: 11
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.mgr.toggleCheck(index, !card.checked)
                    }
                }

                MouseArea {
                    id: hover
                    // z: 8 —— 压过所有装饰层（描边 z:5/6、勾选框 z:2），
                    // 保证整卡点击一定落得到这里，选择模式勾选不失效。
                    z: 8
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton
                    cursorShape: Qt.PointingHandCursor
                    // 选择模式下：点整张卡 = 勾选/取消勾选（不打开详情）。
                    // 平时：选中并显示详情。
                    onClicked: {
                        if (page.selectMode) {
                            page.mgr.toggleCheck(index, !card.checked);
                            return;
                        }
                        page.mgr.selectMod(card.path);
                    }
                }
            }

            // 空状态
            Text {
                anchors.centerIn: parent
                visible: grid.count === 0
                horizontalAlignment: Text.AlignHCenter
                text: page.qScanned ? "这里没有符合条件的 MOD\n换个分类或者清掉筛选试试"
                                    : "还没有 MOD 目录\n在「设置 → MOD 目录」里检测一下"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 12
                lineHeight: 1.6
            }
        }

        // ---- 批量操作条
        Rectangle {
            id: batchBar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.rightMargin: page.detailW + 12
            anchors.bottom: parent.bottom
            height: (page.selectMode || page.qChecked > 0) ? 46 : 0
            visible: height > 1
            radius: Theme.radiusS
            color: Theme.panelHi
            border.width: 1
            border.color: Theme.borderHi
            clip: true
            Behavior on height { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                text: page.qChecked > 0 ? "已选中 " + page.qChecked + " 个"
                                        : "点卡片左下角的方框来选中 MOD"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 12
            }
            Row {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                ActionButton {
                    height: 30
                    accent: false
                    label: "启用"
                    enabledBtn: page.qChecked > 0
                    onClicked: page.mgr.setEnabledChecked(true)
                }
                ActionButton {
                    height: 30
                    accent: false
                    label: "禁用"
                    enabledBtn: page.qChecked > 0
                    onClicked: page.mgr.setEnabledChecked(false)
                }
                // 只有选中的里面有创意工坊 MOD 才显示，点了只转换那部分
                ActionButton {
                    height: 30
                    accent: true
                    visible: page.checkedWorkshopCount() > 0
                    label: "转换到本地MOD" + (page.checkedWorkshopCount() > 0
                                             ? " (" + page.checkedWorkshopCount() + ")" : "")
                    onClicked: page.askConvert(page.checkedWorkshopPaths())
                }
                ActionButton {
                    height: 30
                    accent: false
                    label: "全选"
                    onClicked: page.mgr.checkAllLocal(!page.mgr.allChecked)
                }
                ActionButton {
                    height: 30
                    accent: false
                    label: "清空"
                    onClicked: page.mgr.clearSelection()
                }
                ActionButton {
                    height: 30
                    label: "删除"
                    enabledBtn: page.qChecked > 0
                    onClicked: batchDeleteConfirm.open()
                }
            }
        }
    }

    // ==================================================================== 详情面板的左侧投影
    // 详情现在和网格各占一块（不重叠），这层投影只是让边界柔和一点。
    // 跟随 detail 的右边界算位置：面板现在用 anchors.right + rightMargin 定位，
    // detail.x 本身就是锚定的派生值，跟着它走不会和主面板错位。
    Rectangle {
        id: detailShadow
        z: 29
        x: detail.x - width
        y: detail.y
        height: detail.height
        width: 10
        visible: width > 1
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "transparent" }
            // 深色主题靠一层黑影把详情和列表分开；浅色主题下 0.45 的黑会糊成
            // 一条很脏的灰边（截图里红框那条），必须调淡很多。
            GradientStop {
                position: 1.0
                color: Qt.rgba(0, 0, 0, Theme.dark ? 0.45 : 0.10)
            }
        }
    }

    // ==================================================================== 体积筛选面板（内联，不用 Popup 是为了能截进预览图）
    // 排序也并进来了（以前是工具条上单独一个按钮，和筛选挨在一起显得重复）
    Item {
        id: filterPopup
        parent: page
        property bool opened: false
        function open() {
            minField.text = (page.mgr && page.mgr.minMB > 0) ? String(page.mgr.minMB) : "";
            maxField.text = (page.mgr && page.mgr.maxMB > 0) ? String(page.mgr.maxMB) : "";
            opened = true;
        }
        function close() { opened = false; }

        visible: opened
        x: Math.max(12, page.width - width - 4)
        y: toolBar.y + toolBar.height + 8
        width: 262
        height: filterCol.height + 28
        z: 300

        Rectangle {
            anchors.fill: parent
            radius: Theme.radiusS
            color: Theme.panelHi
            border.width: 1
            border.color: Theme.borderHi
        }

        Column {
            id: filterCol
            x: 14
            y: 14
            width: parent.width - 28
            spacing: 11

            // ---- 排序（并进筛选面板，不再单独占工具条一个按钮）
            Text {
                text: "排序"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }

            Column {
                width: parent.width
                spacing: 2

                Repeater {
                    model: page.sortOptions
                    delegate: Rectangle {
                        required property var modelData
                        width: parent.width
                        height: 26
                        radius: Theme.radiusXS
                        property bool on: page.qSortMode === modelData.mode
                        color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, soMa.pressed ? 0.26 : 0.16)
                                  : (soMa.pressed ? Theme.scrim(0.11)
                                                  : (soMa.containsMouse ? Theme.scrim(0.05) : "transparent"))
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.label
                            color: parent.on ? Theme.text : Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                        }
                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            visible: parent.on
                            text: "✓"
                            color: Theme.accent
                            font.pixelSize: 11
                        }
                        MouseArea {
                            id: soMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.mgr.setSortMode(modelData.mode)
                        }
                    }
                }
            }

            Text {
                width: parent.width
                text: "未启用的总是沉底"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
                opacity: 0.85
            }

            Rectangle {
                width: parent.width
                height: 1
                color: Theme.border
            }

            Text {
                text: "按体积筛选"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }

            Row {
                spacing: 8
                TextInput {
                    id: minField
                    width: 74
                    height: 30
                    verticalAlignment: TextInput.AlignVCenter
                    leftPadding: 8
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    validator: DoubleValidator { bottom: 0; decimals: 1 }
                    Rectangle {
                        anchors.fill: parent
                        z: -1
                        radius: Theme.radiusXS
                        color: Theme.surfaceSoft
                        border.width: 1
                        border.color: minField.activeFocus ? Theme.accent : Theme.border
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        visible: minField.text.length === 0
                        text: "最小"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                    }
                }
                Text {
                    text: "—"
                    color: Theme.textMute
                    anchors.verticalCenter: parent.verticalCenter
                    font.pixelSize: 12
                }
                TextInput {
                    id: maxField
                    width: 74
                    height: 30
                    verticalAlignment: TextInput.AlignVCenter
                    leftPadding: 8
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    validator: DoubleValidator { bottom: 0; decimals: 1 }
                    Rectangle {
                        anchors.fill: parent
                        z: -1
                        radius: Theme.radiusXS
                        color: Theme.surfaceSoft
                        border.width: 1
                        border.color: maxField.activeFocus ? Theme.accent : Theme.border
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        visible: maxField.text.length === 0
                        text: "最大"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                    }
                }
                Text {
                    text: "MB"
                    color: Theme.textMute
                    anchors.verticalCenter: parent.verticalCenter
                    font.pixelSize: 11
                }
            }

            Row {
                spacing: 6
                Repeater {
                    model: [
                        { label: "小于 1M", lo: 0, hi: 1 },
                        { label: "1-50M", lo: 1, hi: 50 },
                        { label: "大于 100M", lo: 100, hi: 0 }
                    ]
                    delegate: Rectangle {
                        required property var modelData
                        height: 24
                        width: quickTxt.width + 18
                        radius: Theme.radiusXS
                        color: qma.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.05)
                        border.width: 1
                        border.color: (page.qMinMB === modelData.lo && page.qMaxMB === modelData.hi)
                                      ? Theme.accent : Theme.border
                        Text {
                            id: quickTxt
                            anchors.centerIn: parent
                            text: modelData.label
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                        MouseArea {
                            id: qma
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                minField.text = modelData.lo > 0 ? String(modelData.lo) : "";
                                maxField.text = modelData.hi > 0 ? String(modelData.hi) : "";
                                page.mgr.setSizeRange(modelData.lo, modelData.hi);
                            }
                        }
                    }
                }
            }

            Text {
                visible: page.qHidden > 0
                text: "当前有 " + page.qHidden + " 个 MOD 被筛选挡住"
                color: Theme.warn
                font.family: Theme.uiFont
                font.pixelSize: 11
            }

            // ---- 按导入日期筛选 ----
            Rectangle {
                width: parent.width
                height: 1
                color: Theme.border
            }

            Text {
                text: "按导入日期筛选"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }

            // 快捷档：近一天 / 近七天 / 近一个月 / 近半年
            Flow {
                width: parent.width
                spacing: 6
                Repeater {
                    model: [
                        { days: 0, label: "不限" },
                        { days: 1, label: "近一天" },
                        { days: 7, label: "近七天" },
                        { days: 30, label: "近一个月" },
                        { days: 180, label: "近半年" }
                    ]
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool on: page.mgr.importDays === modelData.days
                                                     && !page.mgr.importFrom
                                                     && !page.mgr.importTo
                        height: 24
                        width: dayTxt.implicitWidth + 18
                        radius: Theme.radiusXS
                        color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                                  : (dayMa.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.05))
                        border.width: 1
                        border.color: on ? Theme.accent : Theme.border
                        Text {
                            id: dayTxt
                            anchors.centerIn: parent
                            text: modelData.label
                            color: parent.on ? Theme.accent : Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                        MouseArea {
                            id: dayMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                page.mgr.setImportDays(modelData.days);
                            }
                        }
                    }
                }
            }

            // 自定义区间：点一下弹日历选日期（不用手输）
            // ★ 以前是 TextInput + inputMask，用户得自己敲 2026-01-31，
            //   格式错一位就白填。现在改成只读按钮，点开日历点日子。
            Row {
                spacing: 6
                height: 30

                // 开始日期
                Rectangle {
                    id: fromBtn
                    width: 104
                    height: 30
                    radius: Theme.radiusXS
                    color: fromMa.containsMouse ? Theme.scrim(0.09) : Theme.surfaceSoft
                    border.width: 1
                    border.color: page.mgr.importFrom.length > 0
                                  ? Theme.accent : Theme.border

                    Row {
                        anchors.centerIn: parent
                        spacing: 5
                        Text {
                            text: "\uE787"
                            font.family: Theme.iconFont
                            font.pixelSize: 10
                            color: page.mgr.importFrom.length > 0
                                   ? Theme.accent : Theme.textMute
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            id: fromLabel
                            text: page.mgr.importFrom.length > 0
                                  ? page.mgr.importFrom : "开始日期"
                            color: page.mgr.importFrom.length > 0
                                   ? Theme.text : Theme.textMute
                            font.family: page.mgr.importFrom.length > 0
                                         ? Theme.monoFont : Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    MouseArea {
                        id: fromMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.openDatePicker("from")
                    }
                }

                Text {
                    text: "～"
                    color: Theme.textMute
                    anchors.verticalCenter: parent.verticalCenter
                    font.pixelSize: 12
                }

                // 结束日期
                Rectangle {
                    id: toBtn
                    width: 104
                    height: 30
                    radius: Theme.radiusXS
                    color: toMa.containsMouse ? Theme.scrim(0.09) : Theme.surfaceSoft
                    border.width: 1
                    border.color: page.mgr.importTo.length > 0
                                  ? Theme.accent : Theme.border

                    Row {
                        anchors.centerIn: parent
                        spacing: 5
                        Text {
                            text: "\uE787"
                            font.family: Theme.iconFont
                            font.pixelSize: 10
                            color: page.mgr.importTo.length > 0
                                   ? Theme.accent : Theme.textMute
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            id: toLabel
                            text: page.mgr.importTo.length > 0
                                  ? page.mgr.importTo : "结束日期"
                            color: page.mgr.importTo.length > 0
                                   ? Theme.text : Theme.textMute
                            font.family: page.mgr.importTo.length > 0
                                         ? Theme.monoFont : Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    MouseArea {
                        id: toMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.openDatePicker("to")
                    }
                }

                // 清掉区间
                Rectangle {
                    visible: page.mgr.importFrom.length > 0
                             || page.mgr.importTo.length > 0
                    width: 22
                    height: 30
                    radius: Theme.radiusXS
                    color: clearRangeMa.containsMouse ? Theme.scrim(0.09) : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: "\uE711"
                        font.family: Theme.iconFont
                        font.pixelSize: 9
                        color: clearRangeMa.containsMouse ? Theme.accent : Theme.textMute
                    }
                    MouseArea {
                        id: clearRangeMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.mgr.clearImportFilter()
                    }
                }
            }

            Text {
                width: parent.width
                visible: page.mgr.hasImportFilter
                text: "当前：" + page.mgr.importFilterLabel + " · 已挡掉 "
                      + page.qHidden + " 个"
                color: Theme.warn
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.Wrap
            }

            Text {
                width: parent.width
                text: "点日期按钮弹日历选，留空表示那一端不限"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.Wrap
                opacity: 0.85
            }

            Row {
                spacing: 8
                ActionButton {
                    height: 30
                    label: "应用"
                    onClicked: {
                        page.mgr.setSizeRange(
                            parseFloat(minField.text) || 0,
                            parseFloat(maxField.text) || 0);
                        // ★ 不要在这里调 setImportRange("","")！
                        //   日期是点日历那一刻就落盘的，这里再传空串会把它清掉
                        //   （「选完日期又没了」就是这么来的）。只关面板即可。
                        filterPopup.close();
                    }
                }
                ActionButton {
                    height: 30
                    accent: false
                    label: "重置"
                    onClicked: {
                        minField.text = "";
                        maxField.text = "";
                        searchBox.text = "";
                        page.mgr.resetFilters();
                    }
                }
            }
        }
    }

    // 点别处关掉筛选面板
    MouseArea {
        id: filterDismiss
        parent: page
        anchors.fill: parent
        z: 299
        enabled: filterPopup.opened
        visible: enabled
        onClicked: filterPopup.close()
        onWheel: function (wheel) { wheel.accepted = true }
    }

    // ==================================================================== 创意工坊导入
    Popup {
        id: wsImportDlg
        objectName: "wsImportDlg"
        anchors.centerIn: Overlay.overlay
        width: 560
        padding: 20
        modal: true
        closePolicy: Popup.CloseOnEscape
        background: Rectangle {
            radius: Theme.radius
            color: Theme.surfaceHi
            border.width: 1
            border.color: Theme.borderHi
        }

        // 注意：这里不用 `contentItem:`，直接写 Column ——
        // 和本文件里其它 Popup 保持一致。显式写 contentItem 时
        // Popup 不会帮它求出 implicitHeight，弹窗会是个高度 0 的空壳。
        Column {
            width: parent.width
            spacing: 12

            // ---- 标题
            Row {
                width: parent.width
                spacing: 8
                Text {
                    text: "创意工坊导入"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    anchors.verticalCenter: parent.verticalCenter
                }
                Item { width: Math.max(0, parent.width - 120); height: 1 }
                Text {
                    text: "✕"
                    color: wsCloseMa.containsMouse ? Theme.accent : Theme.textMute
                    font.pixelSize: 13
                    anchors.verticalCenter: parent.verticalCenter
                    MouseArea {
                        id: wsCloseMa
                        anchors.fill: parent
                        anchors.margins: -8
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: wsImportDlg.close()
                    }
                }
            }

            // ---- 输入
            Text {
                width: parent.width
                text: "粘工坊链接，或者直接填 ID。例如：\n"
                      + "https://steamcommunity.com/sharedfiles/filedetails/?id=3829533320\n"
                      + "或者 3829533320"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.Wrap
                lineHeight: 1.4
            }

            Row {
                width: parent.width
                spacing: 8
                TextInput {
                    id: wsInputField
                    objectName: "wsInputField"
                    width: parent.width - 96
                    height: 36
                    verticalAlignment: TextInput.AlignVCenter
                    leftPadding: 10
                    color: Theme.text
                    font.family: Theme.monoFont
                    font.pixelSize: 12
                    text: page.wsInput
                    selectByMouse: true
                    onTextChanged: page.wsInput = text
                    onAccepted: page.runProbe()
                    Rectangle {
                        anchors.fill: parent
                        z: -1
                        radius: Theme.radiusXS
                        color: Theme.surfaceSoft
                        border.width: 1
                        border.color: wsInputField.activeFocus ? Theme.accent : Theme.border
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        visible: wsInputField.text.length === 0
                        text: "粘贴链接或工坊 ID"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                }
                ActionButton {
                    width: 88
                    height: 36
                    label: page.wsProbing ? "解析中" : "解析"
                    busy: page.wsProbing
                    onClicked: page.runProbe()
                }
            }

            // ---- 加载中（异步解析，界面不卡）
            Row {
                width: parent.width
                height: page.wsProbing ? 34 : 0
                visible: page.wsProbing
                spacing: 10
                Spinner {
                    width: 18
                    height: 18
                    anchors.verticalCenter: parent.verticalCenter
                    // Spinner 自带无限旋转动画，visible 为 true 就转
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 30
                    text: page.wsStage || "正在解析…"
                    color: Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }

            // ---- 错误
            Text {
                width: parent.width
                visible: (page.wsResult && page.wsResult.ok === false
                          && (page.wsResult.error || "").length > 0)
                text: (page.wsResult && page.wsResult.error) || ""
                color: Theme.warn
                font.family: Theme.uiFont
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }

            // ---- 结果
            Rectangle {
                width: parent.width
                height: 1
                color: Theme.border
                visible: page.wsResult && page.wsResult.ok === true
            }

            // 本体 / 合集信息
            Column {
                width: parent.width
                spacing: 5
                visible: page.wsResult && page.wsResult.ok === true
                Row {
                    width: parent.width
                    spacing: 6
                    // 合集标一下，避免用户以为是单个 MOD
                    Rectangle {
                        visible: page.wsResult && page.wsResult.isCollection === true
                        height: 18
                        width: wsCollTxt.implicitWidth + 12
                        radius: 4
                        color: Qt.rgba(Theme.cyan.r, Theme.cyan.g, Theme.cyan.b, 0.16)
                        anchors.verticalCenter: parent.verticalCenter
                        Text {
                            id: wsCollTxt
                            anchors.centerIn: parent
                            text: "合集"
                            color: Theme.cyan
                            font.family: Theme.uiFont
                            font.pixelSize: 9
                        }
                    }
                    Text {
                        width: parent.width - (page.wsResult && page.wsResult.isCollection === true
                                               ? 50 : 0)
                        text: (page.wsResult && page.wsResult.title)
                              ? page.wsResult.title : "（无标题）"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                Text {
                    width: parent.width
                    text: {
                        var r = page.wsResult;
                        if (!r || !r.ok) return "";
                        if (r.isCollection) {
                            return "共 " + (r.memberCount || 0) + " 个 MOD · 合计 "
                                   + (r.sizeText || "未知");
                        }
                        var s = "体积 " + (r.sizeText || "未知");
                        if (r.filename) s += " · 文件名 " + r.filename;
                        return s;
                    }
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
                // 依赖检查状态：查到了 / 没依赖 / 没查成，三种要说清楚
                Text {
                    width: parent.width
                    visible: page.wsResult && page.wsResult.ok === true
                    text: {
                        var r = page.wsResult || {};
                        if (r.isCollection) {
                            return "合集里的 MOD 默认全部勾选";
                        }
                        if (r.depsChecked) {
                            return (r.depCount > 0)
                                ? "检测到 " + r.depCount + " 个前置物品（可选，默认不勾）"
                                : "这个 MOD 没有前置物品要求";
                        }
                        return "⚠ 工坊页面连不上，没能检查前置物品（不影响下载本体）"
                              + (r.depsReason ? "：" + r.depsReason : "");
                    }
                    color: (page.wsResult && page.wsResult.depsChecked)
                           ? (page.wsResult.depCount > 0 ? Theme.warn : Theme.ok)
                           : Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    wrapMode: Text.Wrap
                }
            }

            // 条目清单（本体/合集成员 + 前置）
            Flickable {
                width: parent.width
                height: Math.min(200, wsList.height)
                visible: page.wsItems.length > 0
                contentWidth: width
                contentHeight: wsList.height
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 10 }

                Column {
                    id: wsList
                    width: parent.width - 6
                    spacing: 4

                    Repeater {
                        model: page.wsItems
                        delegate: Rectangle {
                            id: wsRow
                            required property var modelData
                            required property int index
                            width: wsList.width
                            height: 44
                            radius: Theme.radiusXS
                            color: page.wsBusy ? Theme.scrim(0.03)
                                               : (wsRowMa.containsMouse ? Theme.scrim(0.07)
                                                                        : Theme.scrim(0.03))
                            border.width: 1
                            border.color: modelData.checked ? Theme.accent : Theme.border

                            // 勾选框
                            Rectangle {
                                id: wsBox
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                width: 16
                                height: 16
                                radius: 4
                                color: modelData.checked ? Theme.accent : "transparent"
                                border.width: 1.5
                                border.color: modelData.checked ? Theme.accent
                                                                : (modelData.available ? Theme.borderHi
                                                                                       : Theme.textMute)
                                Text {
                                    anchors.centerIn: parent
                                    visible: modelData.checked === true
                                    text: "✓"
                                    color: "#ffffff"
                                    font.pixelSize: 10
                                }
                            }

                            Column {
                                anchors.left: wsBox.right
                                anchors.leftMargin: 10
                                anchors.right: wsTag.left
                                anchors.rightMargin: 8
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 2
                                Text {
                                    width: parent.width
                                    text: (modelData.title || modelData.id || "")
                                    color: modelData.available ? Theme.text : Theme.textMute
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                }
                                Text {
                                    width: parent.width
                                    text: {
                                        var s = (modelData.sizeText || "未知");
                                        if (modelData.isMain) s = "本体 · " + s;
                                        else s = "前置 · " + s;
                                        if (!modelData.available && modelData.note)
                                            s += " · " + modelData.note;
                                        return s;
                                    }
                                    color: modelData.available ? Theme.textMute : Theme.warn
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                    elide: Text.ElideRight
                                }
                            }

                            // 右侧标签：已装 / 前置
                            Rectangle {
                                id: wsTag
                                anchors.right: parent.right
                                anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                height: 18
                                width: wsTagTxt.implicitWidth + 12
                                radius: 4
                                visible: modelData.installed === true || modelData.isDep === true
                                color: modelData.installed
                                       ? Qt.rgba(Theme.ok.r, Theme.ok.g, Theme.ok.b, 0.16)
                                       : Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.16)
                                Text {
                                    id: wsTagTxt
                                    anchors.centerIn: parent
                                    text: modelData.installed ? "已安装" : "前置"
                                    color: modelData.installed ? Theme.ok : Theme.warn
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                }
                            }

                            MouseArea {
                                id: wsRowMa
                                anchors.fill: parent
                                hoverEnabled: true
                                enabled: !page.wsBusy && modelData.available === true
                                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                onClicked: page.wsToggle(wsRow.index, !modelData.checked)
                            }
                        }
                    }
                }
            }

            // ---- 全选 / 全不选（合集十几个条目时很有用）
            Row {
                width: parent.width
                spacing: 8
                visible: page.wsItems.length > 1
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "批量："
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                }
                Rectangle {
                    height: 22
                    width: selAllTxt.implicitWidth + 16
                    radius: Theme.radiusXS
                    color: selAllMa.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.05)
                    Text {
                        id: selAllTxt
                        anchors.centerIn: parent
                        text: "全选"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                    MouseArea {
                        id: selAllMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.wsCheckAll(true)
                    }
                }
                Rectangle {
                    height: 22
                    width: selNoneTxt.implicitWidth + 16
                    radius: Theme.radiusXS
                    color: selNoneMa.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.05)
                    Text {
                        id: selNoneTxt
                        anchors.centerIn: parent
                        text: "全不选"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                    MouseArea {
                        id: selNoneMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.wsCheckAll(false)
                    }
                }
            }

            // ---- 底部按钮
            Row {
                width: parent.width
                spacing: 8
                visible: page.wsItems.length > 0
                Text {
                    width: Math.max(0, parent.width - 220)
                    anchors.verticalCenter: parent.verticalCenter
                    text: "已选 " + page.wsCheckedCount() + " / " + page.wsItems.length
                          + "（线程 " + page.mgr.downloadThreads + "，设置里可调）"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
                ActionButton {
                    width: 100
                    height: 34
                    label: page.wsBusy ? "下载中" : "下载"
                    busy: page.wsBusy
                    enabledBtn: page.wsCheckedCount() > 0 && !page.wsBusy
                    onClicked: page.runDownload()
                }
                ActionButton {
                    width: 96
                    height: 34
                    accent: false
                    label: "取消"
                    onClicked: wsImportDlg.close()
                }
            }
        }
    }

    // ==================================================================== 已安装 → 是否重下
    Popup {
        id: wsRedownloadConfirm
        objectName: "wsRedownloadConfirm"
        anchors.centerIn: Overlay.overlay
        width: 440
        padding: 18
        modal: true
        closePolicy: Popup.CloseOnEscape
        background: Rectangle {
            radius: Theme.radius
            color: Theme.surfaceHi
            border.width: 1
            border.color: Theme.borderHi
        }

        Column {
            width: parent.width
            spacing: 12

            Text {
                width: parent.width
                text: "这些 MOD 已经装过了"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }

            Text {
                width: parent.width
                text: {
                    var r = page.wsResult || {};
                    var n = 0;
                    for (var i = 0; i < page.wsItems.length; i++)
                        if (page.wsItems[i].installed) n++;
                    return "检测到 " + n + " 个条目已经在这个目录里（列表里标了「已安装」，"
                           + "默认没有勾选）。\n\n"
                           + "要重新下载它们吗？重新下载会新增一份文件（不会覆盖原来的），"
                           + "游戏里可能会出现两个同名 MOD。";
                }
                color: Theme.textDim
                font.family: Theme.uiFont
                font.pixelSize: 11
                wrapMode: Text.Wrap
                lineHeight: 1.45
            }

            // 游戏在跑时，重下最容易踩坑：文件被占用 → 新旧都写不进去
            Rectangle {
                width: parent.width
                height: gameWarnRow.height + 16
                radius: Theme.radiusXS
                visible: page.wsResult && page.wsResult.gameRunning === true
                color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.12)
                border.width: 1
                border.color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.35)
                Row {
                    id: gameWarnRow
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 7
                    Text {
                        text: "⚠"
                        color: Theme.warn
                        font.pixelSize: 12
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        width: parent.width - 24
                        text: "游戏正在运行，可能导致重新下载失败（文件被占用）。"
                              + "建议先完全关闭 Left 4 Dead 2。"
                        color: Theme.warn
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }

            Row {
                width: parent.width
                spacing: 8
                Item { width: Math.max(0, parent.width - 208); height: 1 }
                ActionButton {
                    width: 104
                    height: 32
                    accent: false
                    label: "不用，跳过"
                    onClicked: wsRedownloadConfirm.close()
                }
                ActionButton {
                    width: 96
                    height: 32
                    label: "重新下载"
                    onClicked: {
                        // 把已安装的也勾上
                        var list = [];
                        for (var i = 0; i < page.wsItems.length; i++) {
                            var it = {};
                            for (var k in page.wsItems[i]) it[k] = page.wsItems[i][k];
                            if (it.installed) it.checked = it.available === true;
                            list.push(it);
                        }
                        page.wsItems = list;
                        wsRedownloadConfirm.close();
                    }
                }
            }
        }
    }

    // ==================================================================== 跳到序号
    Popup {
        id: addonJumpDlg
        objectName: "addonJumpDlg"
        anchors.centerIn: Overlay.overlay
        width: 300
        padding: 18
        modal: true
        closePolicy: Popup.CloseOnEscape
        background: Rectangle {
            radius: Theme.radius
            color: Theme.surfaceHi
            border.width: 1
            border.color: Theme.borderHi
        }

        Column {
            width: parent.width
            spacing: 12

            Text {
                width: parent.width
                text: "跳到第几号？"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                text: "这一个（当前第 " + (page.addonJumpIndex + 1) + " 位）会被移动到"
                      + "你填的序号位置，其余依次顺延。共 "
                      + page.addonItems.length + " 个。"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.Wrap
                lineHeight: 1.4
            }

            TextInput {
                id: jumpField
                width: parent.width
                height: 34
                verticalAlignment: TextInput.AlignVCenter
                horizontalAlignment: TextInput.AlignHCenter
                color: Theme.text
                font.family: Theme.monoFont
                font.pixelSize: 13
                text: page.addonJumpText
                selectByMouse: true
                validator: IntValidator { bottom: 1; top: Math.max(1, page.addonItems.length) }
                onTextChanged: page.addonJumpText = text
                onAccepted: page.doJumpTo()
                Rectangle {
                    anchors.fill: parent
                    z: -1
                    radius: Theme.radiusXS
                    color: Theme.surfaceSoft
                    border.width: 1
                    border.color: jumpField.activeFocus ? Theme.accent : Theme.border
                }
            }

            Row {
                width: parent.width
                spacing: 8
                Item { width: Math.max(0, parent.width - 176); height: 1 }
                ActionButton {
                    width: 84
                    height: 32
                    accent: false
                    label: "取消"
                    onClicked: addonJumpDlg.close()
                }
                ActionButton {
                    width: 84
                    height: 32
                    label: "跳过去"
                    onClicked: page.doJumpTo()
                }
            }
        }
    }

    // ==================================================================== 丢弃未保存改动
    Popup {
        id: addonDiscardDlg
        objectName: "addonDiscardDlg"
        anchors.centerIn: Overlay.overlay
        width: 360
        padding: 18
        modal: true
        closePolicy: Popup.CloseOnEscape
        background: Rectangle {
            radius: Theme.radius
            color: Theme.surfaceHi
            border.width: 1
            border.color: Theme.borderHi
        }

        Column {
            width: parent.width
            spacing: 12

            Text {
                width: parent.width
                text: "还有没保存的改动"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                text: "直接关闭会丢掉这次的顺序调整（addonlist.txt 不会被改）。"
                color: Theme.textDim
                font.family: Theme.uiFont
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }
            Row {
                width: parent.width
                spacing: 8
                Item { width: Math.max(0, parent.width - 268); height: 1 }
                ActionButton {
                    width: 120
                    height: 32
                    accent: false
                    label: "继续编辑"
                    onClicked: addonDiscardDlg.close()
                }
                ActionButton {
                    width: 132
                    height: 32
                    label: "丢弃并关闭"
                    onClicked: {
                        addonDiscardDlg.close();
                        page.addonDirty = false;
                        addonOrderDlg.close();
                    }
                }
            }
        }
    }

    // ==================================================================== 日期选择器
    Popup {
        id: datePickerDlg
        objectName: "datePickerDlg"
        anchors.centerIn: Overlay.overlay
        width: 300
        padding: 16
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            radius: Theme.radius
            color: Theme.surfaceHi
            border.width: 1
            border.color: Theme.borderHi
        }

        Column {
            width: parent.width
            spacing: 10

            // ---- 月份切换
            Item {
                width: parent.width
                height: 30

                Text {
                    anchors.centerIn: parent
                    text: page.calYear + " 年 " + page.calMonth + " 月"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
                // 上一月
                Rectangle {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: 26
                    height: 26
                    radius: Theme.radiusXS
                    color: prevMa.containsMouse ? Theme.scrim(0.10) : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: "\u25C0"
                        color: prevMa.containsMouse ? Theme.accent : Theme.textDim
                        font.pixelSize: 9
                    }
                    MouseArea {
                        id: prevMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.calPrevMonth()
                    }
                }
                // 下一月
                Rectangle {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: 26
                    height: 26
                    radius: Theme.radiusXS
                    color: nextMa.containsMouse ? Theme.scrim(0.10) : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: "\u25B6"
                        color: nextMa.containsMouse ? Theme.accent : Theme.textDim
                        font.pixelSize: 9
                    }
                    MouseArea {
                        id: nextMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.calNextMonth()
                    }
                }
            }

            // ---- 星期表头
            Row {
                width: parent.width
                spacing: 0
                Repeater {
                    model: ["日", "一", "二", "三", "四", "五", "六"]
                    delegate: Text {
                        required property var modelData
                        width: parent.width / 7
                        horizontalAlignment: Text.AlignHCenter
                        text: modelData
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                    }
                }
            }

            // ---- 日期格子（7 列网格）
            Grid {
                width: parent.width
                columns: 7
                spacing: 0
                Repeater {
                    model: page.calCells()
                    delegate: Item {
                        required property var modelData
                        width: parent.width / 7
                        height: 30

                        Rectangle {
                            anchors.centerIn: parent
                            width: 26
                            height: 26
                            radius: 13
                            // 选中的日子填强调色，今天只描边
                            color: page.isPickedDay(modelData.day)
                                   ? Theme.accent : "transparent"
                            border.width: (!page.isPickedDay(modelData.day)
                                           && page.isToday(modelData.day)) ? 1 : 0
                            border.color: Theme.accent
                            visible: modelData.day > 0

                            Text {
                                anchors.centerIn: parent
                                visible: modelData.day > 0
                                text: modelData.day > 0 ? String(modelData.day) : ""
                                color: page.isPickedDay(modelData.day)
                                       ? "#ffffff" : Theme.text
                                font.family: Theme.uiFont
                                font.pixelSize: 11
                                font.weight: page.isToday(modelData.day)
                                             ? Font.Bold : Font.Normal
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: modelData.day > 0
                            enabled: modelData.day > 0
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.pickDate(modelData.day)
                        }
                    }
                }
            }

            // ---- 底部：今天 / 取消
            Row {
                width: parent.width
                spacing: 8
                ActionButton {
                    width: 88
                    height: 30
                    accent: false
                    label: "今天"
                    onClicked: {
                        var t = page.todayParts();
                        page.calYear = t.y;
                        page.calMonth = t.m;
                        page.pickDate(t.d);
                    }
                }
                Item { width: Math.max(0, parent.width - 88 - 88 - 8); height: 1 }
                ActionButton {
                    width: 88
                    height: 30
                    accent: false
                    label: "取消"
                    onClicked: datePickerDlg.close()
                }
            }
        }
    }

    // ==================================================================== 加载顺序
    Popup {
        id: addonOrderDlg
        objectName: "addonOrderDlg"
        anchors.centerIn: Overlay.overlay
        width: 720
        padding: 0
        modal: true
        closePolicy: Popup.CloseOnEscape
        // 不管是 Esc、点外面还是点 ✕，关掉之后都要把状态清干净
        onClosed: page.resetAddonOrderState()
        background: Rectangle {
            radius: Theme.radius
            color: Theme.surfaceHi
            border.width: 1
            border.color: Theme.borderHi
        }

        Column {
            width: parent.width
            spacing: 0

            // ---------------- 标题栏
            Item {
                width: parent.width
                height: 52

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    text: "加载顺序"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 96
                    anchors.right: closeBtn.left
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: {
                        var n = page.addonItems.length;
                        var s = "共 " + n + " 个";
                        if (page.addonMissing > 0) s += " · 缺失 " + page.addonMissing;
                        if (page.addonDirty) s += " · 有未保存的修改";
                        return s;
                    }
                    color: page.addonDirty
                           ? Theme.warn
                           : (page.addonMissing > 0 ? Theme.warn : Theme.textMute)
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }

                IconButton {
                    id: closeBtn
                    objectName: "addonOrderClose"
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    glyph: "\uE711"
                    tip: "关闭 (Esc)"
                    boxSize: 30
                    onClicked: page.closeAddonOrder()
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.border }

            // ---------------- 说明
            Text {
                width: parent.width - 36
                x: 18
                topPadding: 10
                text: "按住任意一行上下拖动，或用右侧 ↑ ↓ 微调，或点 # 直接跳到指定序号。"
                      + "**越靠下加载优先级越高**。改完点右下角「保存」才生效。"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.Wrap
                lineHeight: 1.4
            }

            // ---------------- 列表
            Rectangle {
                width: parent.width - 36
                x: 18
                height: Math.min(430, Math.max(120, aoList.height + 8))
                radius: Theme.radiusXS
                color: Theme.surfaceSoft
                border.width: 1
                border.color: Theme.border
                clip: true

                Flickable {
                    id: aoFlick
                    anchors.fill: parent
                    anchors.margins: 4
                    contentWidth: width
                    contentHeight: aoList.height
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    flickableDirection: Flickable.VerticalFlick

                    ScrollBar.vertical: ScrollBar {
                        policy: aoFlick.contentHeight > aoFlick.height
                                ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                        width: 11
                        padding: 2
                        contentItem: Rectangle {
                            implicitWidth: 7
                            radius: 4
                            // 以前这里写死黑色，深色模式下等于看不见；
                            // 换成跟其他滚动条一致的 Theme 令牌。
                            color: parent.pressed ? Theme.accent
                                                 : (parent.hovered ? Theme.scrim(0.34)
                                                                   : Theme.scrim(0.2))
                        }
                    }

                    Column {
                        id: aoList
                        width: aoFlick.width - 14
                        spacing: 2

                        Repeater {
                            model: page.addonItems
                            delegate: Rectangle {
                                id: aoRow
                                required property var modelData
                                required property int index
                                width: aoList.width
                                height: 42
                                radius: 6
                                color: page.addonDragTo === index
                                       ? Qt.rgba(Theme.accent.r, Theme.accent.g,
                                                 Theme.accent.b, 0.22)
                                       : (aoMa.containsMouse || aoMa.dragging
                                          ? Theme.scrim(0.07) : "transparent")
                                border.width: page.addonDragTo === index ? 1 : 0
                                border.color: Theme.accent
                                opacity: page.addonDragFrom === index ? 0.5 : 1.0

                                Row {
                                    anchors.fill: parent
                                    anchors.leftMargin: 8
                                    anchors.rightMargin: 8
                                    spacing: 8

                                    // ---- 拖拽点（视觉提示，整行都能拖）
                                    Text {
                                        text: "\u2237"
                                        color: aoMa.dragging ? Theme.accent : Theme.textMute
                                        font.pixelSize: 13
                                        anchors.verticalCenter: parent.verticalCenter
                                    }

                                    // ---- 序号
                                    Text {
                                        width: 22
                                        horizontalAlignment: Text.AlignRight
                                        text: String(index + 1)
                                        color: Theme.textMute
                                        font.family: Theme.monoFont
                                        font.pixelSize: 11
                                        anchors.verticalCenter: parent.verticalCenter
                                    }

                                    // ---- 标题 + 文件名
                                    Column {
                                        // 宽度预算：总宽 - 拖点14 - 序号22 - 来源标签52
                                        //           - 按钮(26*3=78) - 间距(5*8=40) - 边距16
                                        width: Math.max(100, parent.width - 14 - 22 - 52
                                                        - 78 - 40 - 16)
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 1

                                        Text {
                                            width: parent.width
                                            text: modelData.title || modelData.name
                                            color: modelData.exists
                                                   ? (modelData.unknownName
                                                      ? Theme.textMute : Theme.text)
                                                   : Theme.warn
                                            font.family: Theme.uiFont
                                            font.pixelSize: 12
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            width: parent.width
                                            visible: modelData.title !== modelData.name
                                                     && (modelData.name || "").length > 0
                                            text: modelData.name
                                            color: Theme.textMute
                                            font.family: Theme.monoFont
                                            font.pixelSize: 9
                                            elide: Text.ElideMiddle
                                        }
                                    }

                                    // ---- 来源标签：缺失 / 禁用 / 本地 / 云
                                    // 「禁用」= addonlist 里写着 enabled=0，或者磁盘上
                                    // 的文件本身就叫 xxx.vpk.disabled —— 以前这两种都
                                    // 显示成「本地」，看着像还开着。
                                    Rectangle {
                                        width: 52
                                        height: 20
                                        radius: 4
                                        anchors.verticalCenter: parent.verticalCenter
                                        readonly property bool bad: modelData.exists !== true
                                        readonly property bool off: !bad
                                                                    && (modelData.enabled !== true
                                                                        || modelData.fileDisabled === true)
                                        color: bad ? Qt.rgba(Theme.warn.r, Theme.warn.g,
                                                             Theme.warn.b, 0.18)
                                                   : (off ? Theme.scrim(0.10)
                                                          : (modelData.isLocal
                                                             ? Qt.rgba(Theme.ok.r, Theme.ok.g,
                                                                       Theme.ok.b, 0.16)
                                                             : Qt.rgba(Theme.cyan.r, Theme.cyan.g,
                                                                       Theme.cyan.b, 0.16)))
                                        Text {
                                            anchors.centerIn: parent
                                            text: parent.bad ? "缺失"
                                                             : (parent.off ? "禁用"
                                                                           : (modelData.isLocal
                                                                              ? "本地" : "云"))
                                            color: parent.bad ? Theme.warn
                                                               : (parent.off ? Theme.textMute
                                                                             : (modelData.isLocal
                                                                                ? Theme.ok : Theme.cyan))
                                            font.family: Theme.uiFont
                                            font.pixelSize: 9
                                            font.weight: Font.DemiBold
                                        }
                                    }

                                    // ---- 上移
                                    Item {
                                        width: 26
                                        height: 26
                                        anchors.verticalCenter: parent.verticalCenter
                                        opacity: index > 0 ? 1.0 : 0.28
                                        Rectangle {
                                            anchors.fill: parent
                                            radius: 4
                                            color: upMa.containsMouse && index > 0
                                                   ? Theme.scrim(0.10) : "transparent"
                                        }
                                        Text {
                                            anchors.centerIn: parent
                                            text: "\uE74A"
                                            font.family: Theme.iconFont
                                            font.pixelSize: 11
                                            color: upMa.containsMouse && index > 0
                                                   ? Theme.accent : Theme.textDim
                                        }
                                        MouseArea {
                                            id: upMa
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            enabled: index > 0
                                            cursorShape: index > 0 ? Qt.PointingHandCursor
                                                                   : Qt.ArrowCursor
                                            onClicked: page.moveAddonRow(index, index - 1)
                                        }
                                    }

                                    // ---- 下移
                                    Item {
                                        width: 26
                                        height: 26
                                        anchors.verticalCenter: parent.verticalCenter
                                        opacity: index < page.addonItems.length - 1
                                                 ? 1.0 : 0.28
                                        Rectangle {
                                            anchors.fill: parent
                                            radius: 4
                                            color: downMa.containsMouse
                                                   && index < page.addonItems.length - 1
                                                   ? Theme.scrim(0.10) : "transparent"
                                        }
                                        Text {
                                            anchors.centerIn: parent
                                            text: "\uE74B"
                                            font.family: Theme.iconFont
                                            font.pixelSize: 11
                                            color: downMa.containsMouse
                                                   && index < page.addonItems.length - 1
                                                   ? Theme.accent : Theme.textDim
                                        }
                                        MouseArea {
                                            id: downMa
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            enabled: index < page.addonItems.length - 1
                                            cursorShape: index < page.addonItems.length - 1
                                                         ? Qt.PointingHandCursor
                                                         : Qt.ArrowCursor
                                            onClicked: page.moveAddonRow(index, index + 1)
                                        }
                                    }

                                    // ---- # 跳到指定序号
                                    Item {
                                        width: 26
                                        height: 26
                                        anchors.verticalCenter: parent.verticalCenter
                                        Rectangle {
                                            anchors.fill: parent
                                            radius: 4
                                            color: jumpMa.containsMouse
                                                   ? Theme.scrim(0.10) : "transparent"
                                        }
                                        Text {
                                            anchors.centerIn: parent
                                            text: "#"
                                            font.family: Theme.monoFont
                                            font.pixelSize: 13
                                            font.weight: Font.Bold
                                            color: jumpMa.containsMouse
                                                   ? Theme.accent : Theme.textDim
                                        }
                                        MouseArea {
                                            id: jumpMa
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: page.openJumpTo(index)
                                        }
                                    }
                                }

                                // ---- 整行拖拽（preventStealing 抢回手势）
                                MouseArea {
                                    id: aoMa
                                    anchors.fill: parent
                                    // 让右边那几个按钮先吃到点击
                                    anchors.rightMargin: 96
                                    hoverEnabled: true
                                    cursorShape: dragging ? Qt.ClosedHandCursor
                                                          : Qt.OpenHandCursor
                                    property bool dragging: false
                                    property int fromIndex: -1
                                    property int targetIndex: -1
                                    preventStealing: true

                                    // ★ 行高 + 间距 才是实际步长，
                                    //   漏了 spacing 会让下半部分越拖越偏
                                    readonly property int rowStep: aoRow.height + aoList.spacing

                                    function rowAtY(absY) {
                                        var idx = Math.floor(absY / rowStep);
                                        return Math.max(0, Math.min(
                                            page.addonItems.length - 1, idx));
                                    }

                                    onPressed: function (m) {
                                        fromIndex = aoRow.index;
                                        targetIndex = aoRow.index;
                                        page.addonDragFrom = aoRow.index;
                                        page.addonDragTo = aoRow.index;
                                    }
                                    onPositionChanged: function (m) {
                                        if (!pressed) return;
                                        if (!dragging) {
                                            if (Math.abs(m.y - height / 2) < 6
                                                && Math.abs(m.x - width / 2) < 6)
                                                return;
                                            dragging = true;
                                        }
                                        var inFlick = mapToItem(aoFlick, m.x, m.y).y;
                                        if (inFlick < 28) {
                                            aoFlick.contentY = Math.max(
                                                0, aoFlick.contentY - 10);
                                        } else if (inFlick > aoFlick.height - 28) {
                                            aoFlick.contentY = Math.min(
                                                Math.max(0, aoFlick.contentHeight
                                                            - aoFlick.height),
                                                aoFlick.contentY + 10);
                                        }
                                        targetIndex = rowAtY(
                                            mapToItem(aoList, m.x, m.y).y);
                                        page.addonDragTo = targetIndex;
                                    }
                                    onReleased: function (m) {
                                        var from = fromIndex;
                                        var to = targetIndex;
                                        dragging = false;
                                        fromIndex = -1;
                                        targetIndex = -1;
                                        page.addonDragFrom = -1;
                                        page.addonDragTo = -1;
                                        if (from >= 0 && to >= 0 && from !== to)
                                            page.moveAddonRow(from, to);
                                    }
                                    onCanceled: {
                                        dragging = false;
                                        fromIndex = -1;
                                        targetIndex = -1;
                                        page.addonDragFrom = -1;
                                        page.addonDragTo = -1;
                                    }
                                }
                            }
                        }

                        Text {
                            width: aoList.width
                            topPadding: 26
                            visible: page.addonItems.length === 0
                            horizontalAlignment: Text.AlignHCenter
                            text: "addonlist.txt 里还没有条目"
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                    }
                }
            }

            // ---------------- 文件路径
            Text {
                width: parent.width - 36
                x: 18
                topPadding: 6
                visible: page.addonFilePath.length > 0
                text: page.addonFilePath
                color: Theme.textMute
                font.family: Theme.monoFont
                font.pixelSize: 9
                elide: Text.ElideMiddle
            }

            // ---------------- 底部按钮：撤销 / 保存 / 关闭
            // ★ 宽度必须算准：三个按钮 84+88+84=256，加 3 个间距 24，
            //   合计 280。以前给文字留 parent.width-260，比按钮总宽还大 ——
            //   文字把按钮顶出弹窗边界（用户看到「按钮跑到界面外」）。
            //   现在留 288（280 + 8 缓冲），并且按钮靠右锚定，不靠 Row 顺序挤。
            Item {
                width: parent.width - 36
                x: 18
                height: 44

                Text {
                    anchors.left: parent.left
                    anchors.right: btnRow.left
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    text: page.addonDirty
                          ? "有未保存的修改 —— 点「保存」写入 addonlist.txt"
                          : "顺序已与 addonlist.txt 一致"
                    color: page.addonDirty ? Theme.warn : Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }

                Row {
                    id: btnRow
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8

                    ActionButton {
                        width: 84
                        height: 32
                        accent: false
                        label: "撤销"
                        enabledBtn: page.addonDirty
                        onClicked: page.reloadAddonOrder()
                    }
                    ActionButton {
                        objectName: "addonOrderSave"
                        width: 88
                        height: 32
                        label: "保存"
                        enabledBtn: page.addonDirty
                        onClicked: page.saveAddonOrder()
                    }
                    ActionButton {
                        width: 84
                        height: 32
                        accent: false
                        label: "关闭"
                        onClicked: page.closeAddonOrder()
                    }
                }
            }
        }
    }

    // ==================================================================== 导入确认
    Popup {
        id: importConfirm
        anchors.centerIn: Overlay.overlay
        width: 420
        padding: 18
        modal: true
        closePolicy: Popup.CloseOnEscape
        background: Rectangle {
            radius: Theme.radius
            color: Theme.surfaceHi
            border.width: 1
            border.color: Theme.borderHi
        }

        Column {
            width: parent.width
            spacing: 12

            Text {
                text: "要导入这 " + page.pendingImportCount() + " 个文件吗？"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                visible: (page.pendingImportInfo && page.pendingImportInfo.archives
                          && page.pendingImportInfo.archives.length > 0)
                text: "压缩包：" + (page.pendingImportInfo && page.pendingImportInfo.archives
                                  ? page.pendingImportInfo.archives.join("、") : "")
                wrapMode: Text.Wrap
                elide: Text.ElideRight
                maximumLineCount: 2
                color: Theme.cyan
                font.family: Theme.uiFont
                font.pixelSize: 11
            }
            Text {
                width: parent.width
                text: "目标目录：" + (page.mgr ? page.mgr.addonsDir : "")
                wrapMode: Text.Wrap
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
            }
            Rectangle {
                width: parent.width
                height: Math.min(150, Math.max(40, importList.contentHeight + 12))
                radius: Theme.radiusXS
                color: Theme.surfaceSoft
                border.width: 1
                border.color: Theme.border

                ListView {
                    id: importList
                    anchors.fill: parent
                    anchors.margins: 6
                    clip: true
                    model: page.previewImportNames()
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { width: 10 }
                    delegate: Text {
                        required property string modelData
                        width: importList.width
                        height: 18
                        text: "· " + modelData
                        elide: Text.ElideMiddle
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                }
            }
            Text {
                width: parent.width
                visible: page.pendingImportCount() > 5
                text: "…… 等 " + page.pendingImportCount() + " 个文件"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
            }
            Text {
                width: parent.width
                text: "提示：和 .vpk 同名的 .jpg / .png 封面图会自动一起复制过去。\n"
                      + "zip 压缩包会先解开，只挑出里面的 .vpk 和封面图导入。"
                wrapMode: Text.Wrap
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
            }
            // 游戏在跑的时候文件会被占用，导入可能失败 —— 提前说清楚
            Rectangle {
                width: parent.width
                height: gameWarnTxt.height + 18
                visible: page.importGameRunning
                radius: Theme.radiusXS
                color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.12)
                border.width: 1
                border.color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.45)

                Text {
                    id: gameWarnTxt
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: 9
                    text: "游戏正在进行中，被占用的 MOD 文件可能导致导入失败。建议先完全退出 Left 4 Dead 2 再导入。"
                    wrapMode: Text.Wrap
                    color: Theme.warn
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    lineHeight: 1.3
                }
            }
            Row {
                anchors.right: parent.right
                spacing: 8
                ActionButton {
                    height: 32
                    accent: false
                    label: "取消"
                    onClicked: {
                        importConfirm.close();
                        page.pendingImport = [];
                    }
                }
                ActionButton {
                    height: 32
                    label: "确认导入"
                    onClicked: page.doImport()
                }
            }
        }
    }

    // ==================================================================== 删除确认
    Popup {
        id: deleteConfirm
        anchors.centerIn: Overlay.overlay
        width: 380
        padding: 18
        modal: true
        closePolicy: Popup.CloseOnEscape
        background: Rectangle {
            radius: Theme.radius
            color: Theme.surfaceHi
            border.width: 1
            border.color: Theme.borderHi
        }

        Column {
            width: parent.width
            spacing: 12

            Text {
                text: "删除这个 MOD？"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                text: page.fileNameOf(page.pendingDelete)
                wrapMode: Text.Wrap
                color: Theme.warn
                font.family: Theme.uiFont
                font.pixelSize: 12
            }
            Text {
                width: parent.width
                text: page.mgr && page.mgr.deleteToRecycle
                      ? "MOD 文件和它的同名封面图都会放进回收站，删错了可以还原。"
                      : "MOD 文件和它的同名封面图会被永久删除，没法撤回。"
                wrapMode: Text.Wrap
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
            }
            Row {
                anchors.right: parent.right
                spacing: 8
                ActionButton {
                    height: 32
                    accent: false
                    label: "取消"
                    onClicked: deleteConfirm.close()
                }
                ActionButton {
                    height: 32
                    label: "确认删除"
                    onClicked: page.doDelete()
                }
            }
        }
    }

    Popup {
        id: batchDeleteConfirm
        anchors.centerIn: Overlay.overlay
        width: 380
        padding: 18
        modal: true
        closePolicy: Popup.CloseOnEscape
        background: Rectangle {
            radius: Theme.radius
            color: Theme.surfaceHi
            border.width: 1
            border.color: Theme.borderHi
        }
        Column {
            width: parent.width
            spacing: 12
            Text {
                text: "删除选中的 " + page.qChecked + " 个 MOD？"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                text: page.mgr && page.mgr.deleteToRecycle
                      ? "MOD 文件和它的同名封面图都会放进回收站，删错了可以还原。"
                      : "MOD 文件和它的同名封面图会被永久删除，没法撤回。"
                wrapMode: Text.Wrap
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
            }
            Row {
                anchors.right: parent.right
                spacing: 8
                ActionButton {
                    height: 32
                    accent: false
                    label: "取消"
                    onClicked: batchDeleteConfirm.close()
                }
                ActionButton {
                    height: 32
                    label: "确认删除"
                    onClicked: {
                        batchDeleteConfirm.close();
                        page.mgr.deleteCheckedOfTab();
                    }
                }
            }
        }
    }

    // ==================================================================== 转换到本地确认
    Popup {
        id: convertConfirm
        anchors.centerIn: Overlay.overlay
        width: 430
        padding: 18
        modal: true
        closePolicy: Popup.CloseOnEscape
        background: Rectangle {
            radius: Theme.radius
            color: Theme.surfaceHi
            border.width: 1
            border.color: Theme.borderHi
        }

        Column {
            width: parent.width
            spacing: 12

            Text {
                width: parent.width
                text: "要转换 " + page.pendingConvert.length + " 个创意工坊 MOD 到本地吗？"
                wrapMode: Text.Wrap
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                text: "会把它们复制到本地 addons 目录，文件名和封面图一起带上。"
                      + "工坊那一份保持不动（退订后本地这份还在）。"
                wrapMode: Text.Wrap
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
                lineHeight: 1.35
            }
            // 游戏正在运行：文件会被占用，务必先提醒
            Rectangle {
                width: parent.width
                height: gameRunTxt.height + 20
                visible: page.convertGameRunning
                radius: Theme.radiusXS
                color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.12)
                border.width: 1
                border.color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.5)

                Text {
                    id: gameRunTxt
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: 10
                    text: "⚠ 游戏正在进行中，有 MOD 文件被占用，可能导致无法导入成功。\n"
                          + "建议先完全关闭 Left 4 Dead 2 再转换。"
                    wrapMode: Text.Wrap
                    color: Theme.warn
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    lineHeight: 1.35
                }
            }
            Text {
                width: parent.width
                text: "被占用的 MOD 会被跳过（不会把它的封面图弄丢），关掉游戏后可以再转换一次。"
                wrapMode: Text.Wrap
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
                lineHeight: 1.35
            }
            Row {
                anchors.right: parent.right
                spacing: 8
                ActionButton {
                    height: 32
                    accent: false
                    label: "取消"
                    onClicked: {
                        convertConfirm.close();
                        page.pendingConvert = [];
                    }
                }
                ActionButton {
                    height: 32
                    label: "确认转换"
                    onClicked: page.doConvert()
                }
            }
        }
    }

    // ==================================================================== 文件对话框 / 拖拽
    FileDialog {
        id: fileDlg
        title: "选择要导入的 MOD"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["L4D2 模组 (*.vpk *.zip)", "所有文件 (*)"]
        onAccepted: page.askImport(selectedFiles)
    }

    FolderDialog {
        id: dirDlg
        title: "选择 Left 4 Dead 2 的 addons 目录"
        onAccepted: {
            var p = page.toPath(selectedFolder);
            if (!page.mgr.trySetAddonsDir(p))
                page.mgr.statusText;    // 目录不对时 trySetAddonsDir 已经写了好提示
        }
    }

    DropArea {
        anchors.fill: parent
        onDropped: function (drop) {
            var list = [];
            if (drop.hasUrls) {
                for (var i = 0; i < drop.urls.length; ++i)
                    list.push(page.toPath(drop.urls[i].toString()));
            }
            page.askImport(list);
        }
    }
}
