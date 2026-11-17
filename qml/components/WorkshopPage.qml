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
import QtQuick.Controls.Basic
import L4D2

/* 创意工坊 · 浏览
   ==================
   这一页是我自己的一套布局，和 MOD 管理器刻意做得不一样：

     左：分类「河道」——分组标题 + 胶囊状分类，选中的带强调色竖条；
         点一下立刻筛（多标签是「同时具备」关系）
     中：卡片墙——一直往下滚就继续加载，没有翻页；鼠标移上去浮出快捷操作
     右：详情抽屉——浮在卡片墙上的斜切面板（不是常驻侧栏），点空白处关掉

   顶栏是「单件 MOD / 合集」二选一（默认单件），搜索框、排序、ID 直达、稍后看。

   数据都来自 core.mods.browse*：
     browseFilter(query, sort, kind, tags) 重置并从第 1 页拉
     browseMore()                          滚到底追加下一页
     browseItems / browseThumbs            列表 + 封面（一一对应）
*/
Item {
    id: page
    objectName: "workshopPage"
    clip: true

    property var mgr: core ? core.mods : null

    // 卡片墙的数据源（镜像 core.mods.browseItems，见 syncWsModel）
    ListModel { id: wsModel }
    ListModel { id: laterModel }

    // ---------------- 筛选状态（这一份是「界面上想看到的」，不是后端状态）
    property string query: ""
    property string sortKey: "trend"
    property string kind: "mod"          // mod=单件 / collection=合集
    property var activeTags: []          // 多标签 AND
    property bool showLater: false       // 只看「稍后看」

    // ---------------- 详情
    property var picked: ({})
    property bool detailOpen: false
    property string stage: ""
    property bool loadingDetail: false
    property bool downloading: false
    property string translated: ""
    property bool translating: false
    property string translateError: ""
    property bool showTranslated: false
    property var probeItems: []
    property bool includeDeps: false     // 下载时是否连前置一起下（默认否）
    property bool pendingDeps: false     // 下载在等前置清单
    property bool depsProbing: false     // 只是补前置清单（用户勾了开关，还没点下载）
    property bool probeWantDeps: false   // 当前这次解析要不要前置
    property bool probeFull: false       // 已有全部前置的清单
    // 合集成员：先来 60 个，剩下的后端边拉边报（membersDone 为 true 才是全了）
    property var memberItems: []
    property int memberTotal: 0
    property int memberCount: 0          // 已经拿到多少个
    property bool membersDone: true

    // 「合集 → 成员 → 返回」的路径（存上一级快照，见 openDetail / backDetail）
    property var detailStack: []
    // 多封面：当前看第几张（0 = 工坊封面，后面是作者贴在简介里的效果图）
    property int coverIndex: 0
    // 工坊统计（浏览/订阅/收藏/发布/更新）—— 后端异步补，回来了才有
    property var pickedStats: ({})
    // 合集成员里重复出现的 ID（同一个 MOD 被作者放了两次）
    property var memberSeen: ({})
    property var memberDupIds: ({})

    readonly property var sortOptions: [
        { key: "trend",  label: "热门",     glyph: "\uE9D2" },
        { key: "recent", label: "最新",     glyph: "\uE823" },
        { key: "top",    label: "评分最高", glyph: "\uE735" }
    ]

    // 分类表：中文显示名 → Steam 标签（原样传标签最准，别翻译成中文去查）
    readonly property var groups: [
        {
            title: "干员",
            items: [
                { label: "Bill", tag: "Bill" }, { label: "Francis", tag: "Francis" },
                { label: "Louis", tag: "Louis" }, { label: "Zoey", tag: "Zoey" },
                { label: "Coach", tag: "Coach" }, { label: "Ellis", tag: "Ellis" },
                { label: "Nick", tag: "Nick" }, { label: "Rochelle", tag: "Rochelle" }
            ]
        },
        {
            title: "感染者",
            items: [
                { label: "特感", tag: "Special Infected" },
                { label: "Tank", tag: "Tank" }, { label: "Witch", tag: "Witch" },
                { label: "Hunter", tag: "Hunter" }, { label: "Smoker", tag: "Smoker" },
                { label: "Boomer", tag: "Boomer" }, { label: "Charger", tag: "Charger" },
                { label: "Jockey", tag: "Jockey" }, { label: "Spitter", tag: "Spitter" },
                { label: "普通感染者", tag: "Common Infected" }
            ]
        },
        {
            title: "模式 & 战役",
            items: [
                { label: "战役", tag: "Campaigns" }, { label: "合作", tag: "Co-op" },
                { label: "生存", tag: "Survival" }, { label: "对抗", tag: "Versus" },
                { label: "清道夫", tag: "Scavenge" }, { label: "写实", tag: "Realism" },
                { label: "写实对抗", tag: "Realism Versus" },
                { label: "突变", tag: "Mutations" }, { label: "单人", tag: "Single Player" }
            ]
        },
        {
            title: "武器",
            items: [
                { label: "步枪", tag: "Rifle" }, { label: "冲锋枪", tag: "SMG" },
                { label: "霰弹枪", tag: "Shotgun" }, { label: "狙击枪", tag: "Sniper" },
                { label: "手枪", tag: "Pistol" }, { label: "近战", tag: "Melee" },
                { label: "榴弹", tag: "Grenade Launcher" }, { label: "M60", tag: "M60" },
                { label: "投掷物", tag: "Throwable" }
            ]
        },
        {
            title: "物品",
            items: [
                { label: "治疗包", tag: "Medkit" }, { label: "电击器", tag: "Defibrillator" },
                { label: "肾上腺素", tag: "Adrenaline" }, { label: "止痛药", tag: "Pills" }
            ]
        },
        {
            title: "其他资源",
            items: [
                { label: "UI", tag: "UI" }, { label: "音效", tag: "Sounds" },
                { label: "脚本", tag: "Scripts" }, { label: "模型", tag: "Models" },
                { label: "纹理", tag: "Textures" }, { label: "杂项", tag: "Miscellaneous" },
                { label: "其他", tag: "Other" }
            ]
        }
    ]

    // ---------------- 小工具
    function fmtCount(n) {
        var v = Number(n || 0);
        if (v >= 100000000) return (v / 100000000).toFixed(1) + " 亿";
        if (v >= 10000) return (v / 10000).toFixed(1) + " 万";
        return String(v);
    }

    function hasTag(tag) {
        for (var i = 0; i < page.activeTags.length; i++)
            if (String(page.activeTags[i]).toLowerCase() === String(tag).toLowerCase())
                return true;
        return false;
    }

    function tagLabel(tag) {
        var gs = page.groups;
        for (var i = 0; i < gs.length; i++)
            for (var j = 0; j < gs[i].items.length; j++)
                if (gs[i].items[j].tag === tag) return gs[i].items[j].label;
        return tag;
    }

    function applyFilter() {
        if (!page.mgr) return;
        page.showLater = false;
        page.picked = ({});
        page.detailOpen = false;
        page.mgr.browseFilter(page.query, page.sortKey, page.kind, page.activeTags);
        wsGrid.positionViewAtBeginning();
    }

    function toggleTag(tag) {
        var out = [];
        var found = false;
        for (var i = 0; i < page.activeTags.length; i++) {
            if (String(page.activeTags[i]) === String(tag)) found = true;
            else out.push(page.activeTags[i]);
        }
        if (!found) out.push(tag);
        page.activeTags = out;
        page.applyFilter();
    }

    function clearTags() {
        // 在「稍后看」里点「全部分类」也要能回到正常列表。
        // 以前这里 activeTags 是空的就直接 return，showLater 还开着，
        // 看起来就像「点了全部分类没反应」。
        if (page.activeTags.length === 0 && !page.showLater) return;
        page.activeTags = [];
        page.applyFilter();          // applyFilter 里会把 showLater 复原
    }

    function setKind(k) {
        if (page.kind === k) return;
        page.kind = k;
        page.applyFilter();
    }

    function setSort(k) {
        if (page.sortKey === k) return;
        page.sortKey = k;
        page.applyFilter();
    }

    function resetAll() {
        page.query = "";
        page.activeTags = [];
        page.showLater = false;
        page.applyFilter();
    }

    // 滚到接近底部就继续加载（真正的「无限滚动」，没有页码）
    function maybeMore() {
        if (!page.mgr || page.showLater) return;
        if (page.mgr.browseLoading || page.mgr.browseLoadingMore || page.mgr.browseDone) return;
        var remain = wsGrid.contentHeight - (wsGrid.contentY + wsGrid.height);
        if (remain < 700) page.mgr.browseMore();
    }

    // ---------------- 详情
    function openDetail(item) {
        if (!item || !item.id) return;
        // 从「合集」点进成员时，先把合集这一屏存起来，好让用户能退回去
        // （成员详情和合集详情是同一个抽屉，不记一下就没法回头）。
        if (page.detailOpen && page.picked && page.picked.isCollection === true
                && String(page.picked.id || "") !== String(item.id || "")) {
            page.detailStack = page.detailStack.concat([{
                item: page.picked,
                items: page.memberItems,
                total: page.memberTotal,
                count: page.memberCount,
                done: page.membersDone,
                seen: page.memberSeen,
                dup: page.memberDupIds,
                stats: page.pickedStats
            }]);
        }
        page.picked = item;
        page.detailOpen = true;
        page.probeItems = [];
        page.translated = "";
        page.translateError = "";
        page.showTranslated = false;
        page.loadingDetail = true;
        page.stage = "正在读取详情…";
        page.pendingDeps = false;
        page.probeFull = false;
        page.probeWantDeps = false;
        page.memberItems = [];
        page.memberTotal = 0;
        page.memberCount = 0;
        page.membersDone = true;
        page.coverIndex = 0;
        page.pickedStats = ({});
        page.memberSeen = ({});
        page.memberDupIds = ({});
        // 快速通道：先只解析本体，卡片点开就该立刻有内容可看
        page.mgr.probeWorkshopFast(item.id);
        // 统计数字单独补（官方接口才有，慢一点也没关系）
        page.mgr.requestWorkshopStats(item.id);
    }

    // 回到上一级（合集）。不清 detailStack 之前存的快照就直接渲染回去，
    // 不重新联网 —— 成员清单已经在手里了。
    function backDetail() {
        var st = page.detailStack || [];
        if (st.length === 0) return;
        var top = st[st.length - 1];
        page.detailStack = st.slice(0, st.length - 1);
        page.picked = top.item || ({});
        page.probeItems = [];
        page.memberItems = top.items || [];
        page.memberTotal = top.total || 0;
        page.memberCount = top.count || 0;
        page.membersDone = top.done !== false;
        page.memberSeen = top.seen || ({});
        page.memberDupIds = top.dup || ({});
        page.pickedStats = top.stats || ({});
        page.coverIndex = 0;
        page.loadingDetail = false;
        page.stage = "";
        page.translated = "";
        page.showTranslated = false;
    }

    // ---------------- 多封面 ----------------
    // 工坊只给一张封面，但作者常把效果图贴在简介里（[img]…[/img]），
    // 后端的 images 已经把两者合并好了。
    function detailImages() {
        var p = page.picked || ({});
        var list = p.images || [];
        if (list.length === 0 && (p.preview || "").length > 0) list = [p.preview];
        return list;
    }

    function coverSourceAt(idx) {
        var list = page.detailImages();
        if (list.length === 0) return "";
        var i = Math.max(0, Math.min(idx, list.length - 1));
        return page.mgr ? page.mgr.coverUrl(list[i]) : list[i];
    }

    function coverSource() {
        return page.coverSourceAt(page.coverIndex);
    }

    // ---------------- 合集成员里的重复项 ----------------
    function noteMemberIds(list) {
        var seen = page.memberSeen || ({});
        var dup = page.memberDupIds || ({});
        for (var i = 0; i < (list ? list.length : 0); i++) {
            var id = String((list[i] || {}).id || "");
            if (!id) continue;
            var n = (seen[id] || 0) + 1;
            seen[id] = n;
            if (n > 1) dup[id] = true;
        }
        page.memberSeen = seen;
        page.memberDupIds = dup;
    }

    function isDupMember(id) {
        return (page.memberDupIds || ({}))[String(id || "")] === true;
    }

    // 这个 ID 在这个合集里出现了几次（1 = 只出现一次）
    function dupTimes(id) {
        var n = (page.memberSeen || ({}))[String(id || "")];
        return n === undefined ? 1 : n;
    }

    function dupMemberCount() {
        var d = page.memberDupIds || ({});
        var n = 0;
        for (var k in d) if (d[k] === true) n++;
        return n;
    }

    function closeDetail() {
        page.detailOpen = false;
        page.detailStack = [];
    }

    function hasDepInfo() {
        var items = page.probeItems || [];
        for (var i = 0; i < items.length; i++)
            if (items[i].isDep) return true;
        return false;
    }

    function depCount() {
        var n = 0;
        var items = page.probeItems || [];
        for (var i = 0; i < items.length; i++)
            if (items[i].isDep) n++;
        return n;
    }

    function depHint() {
        if (page.depsProbing || page.pendingDeps) return "正在解析前置…";
        if (page.depCount() > 0)
            return "发现 " + page.depCount() + " 个前置，会一起下";
        if (page.loadingDetail) return "读完详情再检查前置";
        if (!page.probeFull) return "勾上会顺带查一遍前置";
        return "这个条目没写前置";
    }

    // 「连前置一起下」这一行该不该出现。
    // 只有**确实查到有前置**（或者已经勾上、正在解析）时才占位置 —— 一行永远
    // 勾不出结果的开关只会让人以为漏了什么。没查到前置的条目想主动查一次，
    // 用下面那颗「检查前置」小按钮（它会走一次带前置的完整解析）。
    function showDepRow() {
        if (!page.picked || page.picked.isCollection === true) return false;
        if (page.includeDeps) return true;                 // 勾着就得留着让他能取消
        if (page.depsProbing || page.pendingDeps) return true;
        return page.depCount() > 0;
    }

    // 真正要丢给下载器的条目：本体 + （可选）还没装的前置
    function buildDownloadItems() {
        var out = [];
        // 合集：只把「合集本身」交给后端，由后端去展开全部成员
        //（浏览阶段为了快只列了前 60 个，成员直链也一律没查）
        if (page.picked && page.picked.isCollection === true) {
            out.push({
                id: page.picked.id, title: page.picked.title || "",
                url: "", filename: "", sizeText: page.picked.sizeText || "",
                isMain: true, isDep: false, isMember: false, isCollection: true,
                available: true, enabled: true, checked: true
            });
            return out;
        }
        var items = page.probeItems || [];
        for (var i = 0; i < items.length; i++) {
            var it = items[i];
            if (it.isDep) {
                if (!page.includeDeps) continue;
                if (it.installed) continue;      // 装过的前置不用再下一遍
            }
            // 没有直链的条目也留着：后端会在下载线程里现场解析（详情页因此才能秒开）
            if (!it.url && !it.isMember && !it.isMain) continue;
            out.push({
                id: it.id, title: it.title, url: it.url || "",
                filename: it.filename || "", sizeText: it.sizeText || "",
                isMain: !it.isDep, isDep: !!it.isDep, isMember: !!it.isMember,
                available: true, enabled: true, checked: true
            });
        }
        if (out.length === 0 && page.picked && (page.picked.id || "").length > 0) {
            var p = page.picked;
            out.push({
                id: p.id, title: p.title, url: p.url || "",
                filename: p.filename || "", sizeText: p.sizeText || "",
                isMain: true, isDep: false, isMember: false,
                available: true, enabled: true, checked: true
            });
        }
        return out;
    }

    // 列表往 GridView 里塞的时候走一个 ListModel 镜像：
    // 直接绑 browseItems 的话，每追加一页整个模型都被换掉，
    // GridView 会连同滚动位置一起重置 —— 表现就是「往下滚一下又跳回最上面」。
    // 用 ListModel 只 append 尾巴，滚动位置就保得住。
    function syncWsModel() {
        var items = (page.mgr && page.mgr.browseItems) ? page.mgr.browseItems : [];
        var thumbs = (page.mgr && page.mgr.browseThumbs) ? page.mgr.browseThumbs : [];
        var reset = wsModel.count > items.length;
        if (!reset && wsModel.count > 0 && items.length > 0)
            reset = (wsModel.get(0).item.id !== items[0].id);
        if (reset) wsModel.clear();
        for (var i = wsModel.count; i < items.length; i++) {
            wsModel.append({
                item: items[i],
                thumb: thumbs[i] || (items[i].preview || "")
            });
        }
        return reset;
    }

    // 「稍后看」也走一层 ListModel 镜像：它以前直接绑 laterItems，
    // 每次收藏/移除整个模型都被换掉，GridView 连着滚动位置一起重置，
    // 一屏 200 条的时候这一下就是几百毫秒的卡顿（看着像卡死）。
    function syncLaterModel() {
        var items = (page.mgr && page.mgr.laterItems) ? page.mgr.laterItems : [];
        var reset = laterModel.count > items.length;
        if (!reset && laterModel.count > 0 && items.length > 0)
            reset = (String(laterModel.get(0).item.id) !== String(items[0].id));
        if (reset) laterModel.clear();
        for (var i = laterModel.count; i < items.length; i++)
            laterModel.append({ item: items[i], thumb: items[i].preview || "" });
        return reset;
    }

    function onProbe(res) {
        page.loadingDetail = false;
        page.stage = "";
        page.probeFull = page.probeWantDeps;
        if (!res || !res.ok) {
            page.pendingDeps = false;
            if (res && res.error && page.detailOpen) page.stage = res.error;
            return;
        }
        page.probeItems = res.items || [];
        var main = null;
        for (var i = 0; i < page.probeItems.length; i++)
            if (!page.probeItems[i].isDep) { main = page.probeItems[i]; break; }
        if (!main) return;
        var isColl = res.isCollection === true;
        var merged = {};
        for (var k in page.picked) merged[k] = page.picked[k];
        merged.desc = main.desc || merged.desc || "";
        merged.url = isColl ? "" : (main.url || "");
        merged.sizeText = main.sizeText || merged.sizeText || "";
        merged.filename = main.filename || "";
        merged.installed = main.installed === true;
        merged.available = main.available !== false;
        merged.note = main.note || "";
        // 合集不要把标题改成「第一个成员的名字」
        merged.title = isColl ? (res.title || merged.title) : (main.title || merged.title);
        merged.isCollection = isColl;
        merged.memberCount = res.memberCount || 0;
        merged.listedCount = res.listedCount || 0;
        merged.truncated = res.truncated === true;
        merged.lite = res.lite === true;
        if (main.preview) merged.preview = main.preview;
        // 封面列表也要带回来：工坊只给一张，作者贴在简介里的效果图由后端的
        // images 一起给（首屏详情回来之前列表里只有这一张）。
        if (main.images && main.images.length > 0) merged.images = main.images;
        page.picked = merged;
        // 合集：先把首屏这批成员摆上，剩下的等后端一批一批送过来
        if (isColl) {
            page.memberItems = res.items || [];
            page.memberTotal = res.memberCount || page.memberItems.length;
            page.memberCount = page.memberItems.length;
            page.membersDone = res.streaming !== true;
            // 从这份开始统计重复成员（同一个 ID 在合集里出现两次）
            page.memberSeen = ({});
            page.memberDupIds = ({});
            page.noteMemberIds(page.memberItems);
        } else {
            page.memberItems = [];
            page.memberTotal = 0;
            page.memberCount = 0;
            page.membersDone = true;
            page.memberSeen = ({});
            page.memberDupIds = ({});
        }
        page.depsProbing = false;
        // 「连前置一起下」补完解析了：接着把下载发出去
        if (page.pendingDeps) {
            page.pendingDeps = false;
            page.doDownload();
        }
    }

    // 合集成员的后继批次：后端一次送 100 个，到了就往后接上（不重建、不跳位）
    function onMembers(res) {
        if (!res || !page.picked || page.picked.isCollection !== true) return;
        if (String(res.id) !== String(page.picked.id)) return;   // 用户已经点开别的条目了
        var add = res.items || [];
        if (add.length > 0) {
            page.memberItems = page.memberItems.concat(add);
            page.noteMemberIds(add);
        }
        page.memberCount = page.memberItems.length;
        if (res.memberCount) page.memberTotal = res.memberCount;
        if (res.done === true) page.membersDone = true;
    }

    // 工坊统计数字回来了：只认当前打开的这一条
    function onStats(res) {
        if (!res || !page.picked) return;
        if (String(res.id) !== String(page.picked.id)) return;
        page.pickedStats = res;
    }

    // 统计做成小胶囊：有值才出现。
    // （浏览/订阅/收藏/发布/更新只有官方接口给，所以是异步补回来的；
    //   没补回来之前这一行整个不占位置。）
    //
    // 分成「数字」和「日期」两组、各占一行：
    // 五个挤在一行时抽屉只有 358px，日期那两枚特别宽，会被挤到换行、
    // 甚至顶到右边的滚动条上（真实反馈「UI 挤压溢出」）。
    // 数字三个一行、日期两个一行，宽度都富余，也不会再出现参差的换行。
    function statChips() {
        var s = page.pickedStats || ({});
        var out = [];
        if (s.viewsText) out.push({ glyph: "\uE7B3", label: "浏览 " + s.viewsText, tone: Theme.cyan });
        if (s.subsText) out.push({ glyph: "\uE8AB", label: "订阅 " + s.subsText, tone: Theme.cyan });
        if (s.favsText) out.push({ glyph: "\uE734", label: "收藏 " + s.favsText, tone: Theme.pink });
        return out;
    }

    function statDateChips() {
        var s = page.pickedStats || ({});
        var out = [];
        if (s.updatedText) out.push({ glyph: "\uE823", label: "更新 " + s.updatedText, tone: Theme.textMute });
        if (s.createdText) out.push({ glyph: "\uE787", label: "发布 " + s.createdText, tone: Theme.textMute });
        return out;
    }

    function statsCount() { return page.statChips().length + page.statDateChips().length; }

    // 成员区的进度文字
    function membersHint() {
        var total = page.memberTotal || page.memberCount;
        var dup = page.dupMemberCount();
        var tail = dup > 0 ? " · 其中 " + dup + " 个重复" : "";
        if (page.membersDone) return "共 " + total + " 个成员，都在这儿了" + tail;
        return "共 " + total + " 个成员 · 已列出 " + page.memberCount + " 个，还在往下拉…" + tail;
    }

    // 勾上「连前置一起下」时立刻去补前置清单，别等用户再点一次
    function wantDeps() {
        if (page.probeFull || page.depsProbing || page.pendingDeps) return;
        if (!page.picked || !page.picked.id) return;
        page.depsProbing = true;
        page.probeWantDeps = true;
        page.stage = "正在解析前置…";
        page.mgr.probeWorkshopAsync(page.picked.id);
    }

    function doTranslate() {
        var d = (page.picked && page.picked.desc) ? page.picked.desc : "";
        if (!d || page.translating) return;
        page.translating = true;
        page.translateError = "";
        page.mgr.translateTextAsync(d);
    }

    function onTranslated(res) {
        page.translating = false;
        if (res && res.ok) {
            page.translated = res.text || "";
            page.showTranslated = true;
        } else {
            page.translateError = (res && res.error) ? res.error : "翻译失败";
        }
    }

    function doDownload() {
        var it = page.picked || ({});
        if (page.downloading) return;
        var isColl = it.isCollection === true;
        // 合集、以及「只快速解析过、还没拿直链」的条目都要能点：
        // 前者后端会展开成员，后者后端会在下载线程里现场解析直链
        if (!it.url && !isColl && (it.id || "").length === 0) return;
        // 要连前置一起下，但手上只有「本体」这份快速解析结果 → 先补前置清单
        if (page.includeDeps && !page.probeFull && !isColl) {
            page.pendingDeps = true;
            page.downloading = true;
            page.probeWantDeps = true;
            page.stage = "正在解析前置…";
            page.mgr.probeWorkshopAsync(it.id);
            return;
        }
        var items = page.buildDownloadItems();
        if (items.length === 0) return;
        page.downloading = true;
        page.mgr.downloadWorkshopAsync(items);
    }

    function onDownloaded(res) {
        page.downloading = false;
        page.pendingDeps = false;
        if (res && res.ok && page.picked && page.picked.id) {
            var m = {};
            for (var k in page.picked) m[k] = page.picked[k];
            m.installed = true;
            page.picked = m;
            // 真的下载（不是「连前置」那次补解析）已经交给下载页了。
            // 这里的按钮立刻恢复可用，别再自己转圈 —— 以前 `downloading`
            // 要等整个下载结束才复位，合集动辄几百个成员，表现就是
            // 「创意工坊一直显示下载中/处理中」。
            if (!res.expanding) {
                page.stage = "";
            }
        }
    }

    Connections {
        target: page.mgr
        function onBrowseChanged() {
            // 只有「换了一整份列表」（切分类/搜索/排序）才回到顶部；
            // 往下追加时 syncWsModel 只补尾巴、不重建，滚动位置保持不动。
            var reset = page.syncWsModel();
            page.syncLaterModel();
            if (reset && page.mgr && page.mgr.browsePage <= 1
                    && !page.mgr.browseLoadingMore)
                wsGrid.positionViewAtBeginning();
        }
        function onBrowseAppended() { page.syncWsModel(); }
        function onWorkshopProbeProgress(s, d, t) {
            page.stage = t > 0 ? (s + "（" + d + "/" + t + "）") : s;
        }
        function onWorkshopProbed(res) { page.onProbe(res); }
        function onWorkshopMembersChanged(res) { page.onMembers(res); }
        function onWorkshopStatsChanged(res) { page.onStats(res); }
        function onWorkshopDownloaded(res) { page.onDownloaded(res); }
        function onTranslationReady(res) { page.onTranslated(res); }
    }

    Component.onCompleted: {
        if (page.mgr && page.mgr.browseItems.length === 0)
            page.mgr.browseFilter("", "trend", "mod", []);
        else
            page.syncWsModel();
        page.syncLaterModel();
    }

    // ======================================================== 左侧分类河道
    Rectangle {
        id: rail
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 168
        radius: Theme.radiusS
        color: Theme.surface
        border.width: 1
        border.color: Theme.border

        Flickable {
            id: railFlick
            objectName: "wsRailFlick"
            anchors.fill: parent
            anchors.margins: 10
            contentWidth: width
            contentHeight: railCol.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            // 分类栏的滚动条：能拖、能看见自己在哪
            // 注意：附加 ScrollBar 由 Qt 自己摆位置，别再 anchor top/bottom，
            // 否则会报 "possible anchor loop"。
            ScrollBar.vertical: ScrollBar {
                id: railBar
                objectName: "wsRailBar"
                policy: ScrollBar.AsNeeded
                width: 6
                anchors.right: parent.right
                anchors.rightMargin: 2
                contentItem: Rectangle {
                    implicitWidth: 6
                    radius: 3
                    color: railBar.pressed ? Theme.accent
                                           : (railBar.hovered ? Theme.scrim(0.3)
                                                              : Theme.scrim(0.18))
                    Behavior on color { ColorAnimation { duration: 120 } }
                }
                background: Item { }
            }

            Column {
                id: railCol
                width: parent.width
                spacing: 3

                // 全部分类：清掉所有标签
                Rectangle {
                    width: parent.width
                    height: 32
                    radius: Theme.radiusXS
                    readonly property bool on: page.activeTags.length === 0 && !page.showLater
                    color: on
                           ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
                           : (allMa.containsMouse ? Theme.scrim(0.06) : "transparent")
                    border.width: on ? 1 : 0
                    border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.42)
                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 8
                        Text {
                            text: "\uE8FD"
                            font.family: Theme.iconFont
                            font.pixelSize: 12
                            color: parent.parent.on ? Theme.accent : Theme.textMute
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "全部分类"
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            font.weight: parent.parent.on ? Font.DemiBold : Font.Normal
                            color: parent.parent.on ? Theme.text : Theme.textDim
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    MouseArea {
                        id: allMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.clearTags()
                    }
                }

                // 只看稍后看
                Rectangle {
                    width: parent.width
                    height: 32
                    radius: Theme.radiusXS
                    readonly property bool on: page.showLater
                    color: on
                           ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
                           : (laterMa.containsMouse ? Theme.scrim(0.06) : "transparent")
                    border.width: on ? 1 : 0
                    border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.42)
                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 8
                        Text {
                            text: "\uE734"
                            font.family: Theme.iconFont
                            font.pixelSize: 12
                            color: parent.parent.on ? Theme.accent : Theme.textMute
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "稍后看"
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            font.weight: parent.parent.on ? Font.DemiBold : Font.Normal
                            color: parent.parent.on ? Theme.text : Theme.textDim
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            visible: page.mgr && page.mgr.laterCount > 0
                            text: page.mgr ? page.mgr.laterCount : 0
                            font.family: Theme.monoFont
                            font.pixelSize: 9
                            color: parent.parent.on ? Theme.accent : Theme.textMute
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    MouseArea {
                        id: laterMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            page.showLater = !page.showLater;
                            if (page.showLater) {
                                page.detailOpen = false;
                                page.syncLaterModel();
                                // 作用在**正要显示**的 laterGrid 上；之前是对着
                                // 已经隐藏的 wsGrid 调，白白让它算一遍布局。
                                laterGrid.positionViewAtBeginning();
                            }
                        }
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                // 分组
                Repeater {
                    model: page.groups
                    delegate: Column {
                        required property var modelData
                        width: railCol.width
                        spacing: 2

                        Item { width: 1; height: 4 }
                        Text {
                            leftPadding: 10
                            text: modelData.title
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            font.letterSpacing: 0.8
                        }
                        Item { width: 1; height: 2 }

                        Repeater {
                            model: modelData.items
                            delegate: Rectangle {
                                required property var modelData
                                width: railCol.width
                                height: 28
                                radius: Theme.radiusXS
                                readonly property bool on: page.hasTag(modelData.tag)
                                color: on
                                       ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.14)
                                       : (chipMa.containsMouse ? Theme.scrim(0.055) : "transparent")

                                // 选中时的强调色竖条（和左导航栏呼应，但更细）
                                Rectangle {
                                    width: 2
                                    height: 14
                                    radius: 1
                                    x: 1
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: parent.on
                                    color: Theme.accent
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 12
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.label
                                    color: parent.on ? Theme.text : Theme.textDim
                                    font.family: Theme.uiFont
                                    font.pixelSize: 12
                                    font.weight: parent.on ? Font.DemiBold : Font.Normal
                                }
                                MouseArea {
                                    id: chipMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: page.toggleTag(modelData.tag)
                                }
                            }
                        }
                    }
                }

                Item { width: 1; height: 10 }
            }
        }
    }

    // ======================================================== 右侧主区
    Column {
        id: main
        anchors.left: rail.right
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        spacing: 10

        // ---------------- 顶栏：单件/合集 + 搜索 + 排序 + 动作
        Item {
            id: topBar
            width: parent.width
            height: 40

            // 单件 / 合集：两段式开关，默认单件
            Rectangle {
                id: kindSwitch
                objectName: "wsKindSwitch"
                width: 148
                height: 34
                radius: 17
                color: Theme.surfaceSoft
                border.width: 1
                border.color: Theme.border
                anchors.verticalCenter: parent.verticalCenter

                Rectangle {
                    id: kindPill
                    width: (parent.width - 6) / 2
                    height: parent.height - 6
                    y: 3
                    x: page.kind === "mod" ? 3 : 3 + width
                    radius: height / 2
                    color: Theme.accent
                    Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                }

                Row {
                    anchors.fill: parent
                    Repeater {
                        model: [{ k: "mod", t: "单件 MOD" }, { k: "collection", t: "合集" }]
                        delegate: Item {
                            required property var modelData
                            objectName: "wsKind_" + modelData.k
                            width: (kindSwitch.width) / 2
                            height: kindSwitch.height
                            Text {
                                anchors.centerIn: parent
                                text: modelData.t
                                color: page.kind === modelData.k
                                       ? "#ffffff" : Theme.textDim
                                font.family: Theme.uiFont
                                font.pixelSize: 11
                                font.weight: page.kind === modelData.k ? Font.DemiBold : Font.Normal
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: page.setKind(modelData.k)
                            }
                        }
                    }
                }
            }

            // 搜索
            Rectangle {
                id: searchBox
                objectName: "wsSearchBox"
                anchors.left: kindSwitch.right
                anchors.leftMargin: 10
                anchors.right: sortRow.left
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                height: 34
                radius: Theme.radiusS
                color: Theme.surfaceSoft
                border.width: 1
                border.color: wsInput.activeFocus ? Theme.accent : Theme.border

                // 文本框自己不会把鼠标变成「工」字，得挂一个 HoverHandler
                HoverHandler { cursorShape: Qt.IBeamCursor }

                // 点框里的空白处（图标、右侧留白）也要能聚焦 —— 输入框本身
                // 只占 Row 的一小段，以前点在旁边什么都不会发生。
                // 它声明在 Row 之前，所以不会抢 TextInput 自己的点击。
                MouseArea {
                    anchors.fill: parent
                    onClicked: wsInput.forceActiveFocus()
                }

                // 程序改 page.query（重置按钮 / 切换筛选）时把文字同步回输入框。
                // 以前用 `text: page.query` 直接绑定，用户一输入绑定就被打断，
                // 之后程序再改 query 输入框就不跟着变了。
                Connections {
                    target: page
                    function onQueryChanged() {
                        if (wsInput.text !== page.query)
                            wsInput.text = page.query;
                    }
                }

                Row {
                    anchors.fill: parent
                    anchors.leftMargin: 11
                    anchors.rightMargin: 8
                    spacing: 7
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "\uE721"
                        font.family: Theme.iconFont
                        font.pixelSize: 12
                        color: wsInput.activeFocus ? Theme.accent : Theme.textMute
                    }
                    TextInput {
                        id: wsInput
                        objectName: "wsSearchInput"
                        width: parent.width - 40
                        height: parent.height
                        verticalAlignment: TextInput.AlignVCenter
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                        selectByMouse: true
                        clip: true
                        onTextChanged: page.query = text
                        onAccepted: page.applyFilter()
                        // Esc 退出焦点（以前按 Esc 焦点会一直留在输入框里，
                        // 接着敲键盘就直接变成搜索词）
                        Keys.onEscapePressed: function (event) {
                            wsInput.focus = false;
                            event.accepted = true;
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: wsInput.text.length === 0
                            text: "搜工坊（英文关键词命中率更高）"
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                    }
                    Item {
                        width: 16; height: 16
                        anchors.verticalCenter: parent.verticalCenter
                        visible: wsInput.text.length > 0
                        Text {
                            anchors.centerIn: parent
                            text: "\uE711"
                            font.family: Theme.iconFont
                            font.pixelSize: 9
                            color: clearMa.containsMouse ? Theme.accent : Theme.textMute
                        }
                        MouseArea {
                            id: clearMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                page.query = "";
                                wsInput.text = "";
                                page.applyFilter();
                            }
                        }
                    }
                }
            }

            // 排序胶囊
            Row {
                id: sortRow
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4

                Repeater {
                    model: page.sortOptions
                    delegate: Rectangle {
                        required property var modelData
                        width: sortTxt.implicitWidth + 26
                        height: 30
                        radius: 15
                        readonly property bool on: page.sortKey === modelData.key
                        color: on
                               ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
                               : (sMa.containsMouse ? Theme.scrim(0.07) : Theme.scrim(0.035))
                        border.width: 1
                        border.color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g,
                                                   Theme.accent.b, 0.5) : Theme.border
                        Row {
                            anchors.centerIn: parent
                            spacing: 5
                            Text {
                                text: modelData.glyph
                                font.family: Theme.iconFont
                                font.pixelSize: 10
                                color: parent.parent.on ? Theme.accent : Theme.textMute
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                id: sortTxt
                                text: modelData.label
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                                color: parent.parent.on ? Theme.accent : Theme.textDim
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        MouseArea {
                            id: sMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.setSort(modelData.key)
                        }
                    }
                }
            }
        }

        // ---------------- 已选标签 / 状态行
        Item {
            id: crumbRow
            width: parent.width
            height: 26

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6

                Repeater {
                    model: page.activeTags
                    delegate: Rectangle {
                        required property var modelData
                        height: 22
                        width: tagTxt.implicitWidth + 34
                        radius: 11
                        color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.14)
                        border.width: 1
                        border.color: Qt.rgba(Theme.accent.r, Theme.accent.g,
                                              Theme.accent.b, 0.4)
                        Row {
                            anchors.centerIn: parent
                            spacing: 4
                            Text {
                                id: tagTxt
                                text: page.tagLabel(modelData)
                                color: Theme.accent
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: "\uE711"
                                font.family: Theme.iconFont
                                font.pixelSize: 7
                                color: tagMa.containsMouse ? Theme.text : Theme.accent
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        MouseArea {
                            id: tagMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.toggleTag(modelData)
                        }
                    }
                }

                Rectangle {
                    visible: page.activeTags.length > 1
                    height: 22
                    width: clearAllTxt.implicitWidth + 20
                    radius: 11
                    color: clearAllMa.containsMouse ? Theme.scrim(0.1) : Theme.scrim(0.05)
                    Text {
                        id: clearAllTxt
                        anchors.centerIn: parent
                        text: "清空分类"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                    MouseArea {
                        id: clearAllMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.clearTags()
                    }
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: page.activeTags.length === 0
                    text: page.kind === "collection"
                          ? "正在浏览合集 · 多个 MOD 打包发布"
                          : "正在浏览单件 MOD"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                }
            }

            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: {
                        if (!page.mgr) return "";
                        if (page.showLater) return "稍后看 " + page.mgr.laterCount + " 个";
                        var loaded = page.mgr.browseItems.length;
                        var total = page.mgr.browseTotal;
                        if (!total) return "";
                        return "已加载 " + page.fmtCount(loaded) + " / "
                               + page.fmtCount(total);
                    }
                    color: Theme.textMute
                    font.family: Theme.monoFont
                    font.pixelSize: 10
                }

                Rectangle {
                    height: 22
                    width: idGoTxt.implicitWidth + 22
                    radius: 11
                    color: idGoMa.containsMouse ? Theme.scrim(0.1) : Theme.scrim(0.05)
                    border.width: 1
                    border.color: Theme.border
                    Text {
                        id: idGoTxt
                        anchors.centerIn: parent
                        text: "ID 直达"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                    MouseArea {
                        id: idGoMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: idDialog.open()
                    }
                }

                Rectangle {
                    height: 22
                    width: resetTxt.implicitWidth + 22
                    radius: 11
                    color: resetMa.containsMouse ? Theme.scrim(0.1) : Theme.scrim(0.05)
                    border.width: 1
                    border.color: Theme.border
                    Text {
                        id: resetTxt
                        anchors.centerIn: parent
                        text: "重置"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                    MouseArea {
                        id: resetMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.resetAll()
                    }
                }
            }
        }

        // ---------------- 卡片墙
        Item {
            id: gridWrap
            width: parent.width
            height: parent.height - topBar.height - crumbRow.height - 20

            // 首屏加载
            Column {
                anchors.centerIn: parent
                spacing: 10
                visible: page.mgr && page.mgr.browseLoading
                         && page.mgr.browseItems.length === 0
                Spinner {
                    width: 26; height: 26
                    anchors.horizontalCenter: parent.horizontalCenter
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "正在拉取创意工坊列表…"
                    color: Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                }
            }

            // 空状态
            Column {
                anchors.centerIn: parent
                spacing: 8
                visible: page.mgr && !page.mgr.browseLoading
                         && page.mgr.browseItems.length === 0 && !page.showLater
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "\uE774"
                    font.family: Theme.iconFont
                    font.pixelSize: 30
                    color: Theme.textMute
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: page.activeTags.length > 0
                          ? "这个分类下没搜到，换个标签或清空试试"
                          : "什么都没搜到，换个关键词试试"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                }
            }

            // 稍后看：单独一屏
            // 顶部一条小标题栏（数量 + 清空），卡片右上角带「移除」
            Rectangle {
                id: laterHead
                objectName: "wsLaterHead"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 34
                visible: page.showLater
                color: "transparent"

                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    Text {
                        text: "稍后看"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        objectName: "wsLaterHint"
                        text: (page.mgr ? page.mgr.laterCount : 0) + " 个（只记 ID，换台机器也还在）"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                Rectangle {
                    id: clearLaterBtn
                    objectName: "wsLaterClear"
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    height: 24
                    width: clearLaterTxt.implicitWidth + 18
                    radius: 12
                    visible: page.mgr && page.mgr.laterCount > 0
                    color: clearLaterMa.containsMouse ? Theme.scrim(0.12) : Theme.scrim(0.05)
                    border.width: 1
                    border.color: Theme.border
                    Text {
                        id: clearLaterTxt
                        anchors.centerIn: parent
                        text: "清空"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                    MouseArea {
                        id: clearLaterMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (page.mgr) page.mgr.clearLater();
                            page.syncLaterModel();
                        }
                    }
                }
            }

            GridView {
                id: laterGrid
                objectName: "wsLaterGrid"
                anchors.fill: parent
                anchors.topMargin: 38
                visible: page.showLater
                cellWidth: wsGrid.cellWidth
                cellHeight: wsGrid.cellHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: laterModel

                ScrollBar.vertical: ScrollBar {
                    id: laterBar
                    objectName: "wsLaterBar"
                    policy: ScrollBar.AsNeeded
                    width: 8
                    anchors.right: parent.right
                    anchors.rightMargin: 2
                    contentItem: Rectangle {
                        implicitWidth: 6
                        radius: 3
                        color: laterBar.pressed ? Theme.accent
                                                : (laterBar.hovered ? Theme.scrim(0.34)
                                                                    : Theme.scrim(0.2))
                        Behavior on color { ColorAnimation { duration: 120 } }
                    }
                    background: Item { }
                }
                delegate: Item {
                    id: cell
                    required property var item
                    required property string thumb
                    width: laterGrid.cellWidth - 10
                    height: laterGrid.cellHeight - 10
                    WsCard {
                        anchors.fill: parent
                        item: cell.item
                        thumb: cell.thumb || cell.item.preview || ""
                        later: true
                        onOpened: page.openDetail(cell.item)
                    }
                    // 移除：直接摘掉这一条，不用先点开详情
                    Rectangle {
                        id: rmBtn
                        objectName: "wsLaterRemove"
                        width: 22
                        height: 22
                        radius: 11
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.top: parent.top
                        anchors.topMargin: 8
                        color: rmMa.containsMouse ? Qt.rgba(0.85, 0.25, 0.28, 0.9)
                                                  : Qt.rgba(0, 0, 0, 0.42)
                        Text {
                            anchors.centerIn: parent
                            text: "\uE711"
                            font.family: Theme.iconFont
                            font.pixelSize: 10
                            color: "#FFFFFF"
                        }
                        MouseArea {
                            id: rmMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (page.mgr) page.mgr.toggleLater(cell.item.id);
                                page.syncLaterModel();
                            }
                        }
                    }
                }
            }

            // 稍后看空着的时候给句话，别让人对着一片空白以为卡住了
            Column {
                anchors.centerIn: laterGrid
                spacing: 8
                visible: page.showLater && page.mgr && page.mgr.laterCount === 0
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "\uE734"
                    font.family: Theme.iconFont
                    font.pixelSize: 30
                    color: Theme.textMute
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "还没有存过东西；卡片右上角的「稍后看」就会存到这里"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                }
            }

            // 主列表
            GridView {
                id: wsGrid
                objectName: "wsGrid"
                anchors.fill: parent
                visible: !page.showLater
                clip: true
                cellWidth: Math.max(196, Math.floor((width - 6) / Math.max(1, Math.floor((width - 6) / 208))))
                cellHeight: Math.round(cellWidth * 0.78)
                model: wsModel
                boundsBehavior: Flickable.StopAtBounds
                cacheBuffer: 1200
                onContentYChanged: page.maybeMore()
                onHeightChanged: page.maybeMore()

                ScrollBar.vertical: ScrollBar {
                    id: wsBar
                    objectName: "wsGridBar"
                    policy: ScrollBar.AsNeeded
                    width: 8
                    anchors.right: parent.right
                    anchors.rightMargin: 2
                    contentItem: Rectangle {
                        implicitWidth: 6
                        radius: 3
                        color: wsBar.pressed ? Theme.accent
                                             : (wsBar.hovered ? Theme.scrim(0.34)
                                                              : Theme.scrim(0.2))
                        Behavior on color { ColorAnimation { duration: 120 } }
                    }
                    background: Item { }
                }

                delegate: Item {
                    id: cell
                    required property var item
                    required property string thumb
                    required property int index
                    width: wsGrid.cellWidth - 10
                    height: wsGrid.cellHeight - 10

                    WsCard {
                        anchors.fill: parent
                        item: cell.item
                        thumb: cell.thumb || (cell.item.preview || "")
                        later: page.mgr ? page.mgr.isLater(cell.item.id) : false
                        onOpened: page.openDetail(cell.item)
                    }
                }

                // 底部：加载更多 / 到底了
                footer: Item {
                    width: wsGrid.width
                    height: 54
                    Row {
                        anchors.centerIn: parent
                        spacing: 8
                        visible: page.mgr && page.mgr.browseLoadingMore
                        Spinner {
                            width: 16; height: 16
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "正在加载更多…"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: page.mgr && !page.mgr.browseLoadingMore
                                 && page.mgr.browseDone
                                 && page.mgr.browseItems.length > 0
                        text: "—— 到底了，共 " + page.fmtCount(page.mgr ? page.mgr.browseTotal : 0) + " 个 ——"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: page.mgr && page.mgr.browseError.length > 0
                        text: "加载失败：" + (page.mgr ? page.mgr.browseError : "")
                        color: Theme.warn
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }
            }
        }
    }

    // ======================================================== 卡片（内部组件）
    component WsCard: Item {
        id: card
        objectName: "wsCard"
        property var item: ({})
        property string thumb: ""
        property bool later: false
        property bool hovered: cardMa.containsMouse
        signal opened()

        // 只有 fileType == 2 才是真合集：Steam 会给一部分普通 MOD 也带上
        // num_children，之前按 children 判，单件列表里会冒出「合集 N」角标
        readonly property bool isCollection: Number(item.fileType || 0) === 2

        Rectangle {
            id: body
            anchors.fill: parent
            radius: Theme.radiusS
            color: card.hovered ? Theme.surfaceHi : Theme.surface
            border.width: 1
            border.color: card.hovered ? Theme.borderHi : Theme.border
            clip: true

            // 封面
            Item {
                id: cover
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: parent.height - 52
                clip: true

                Rectangle {
                    anchors.fill: parent
                    color: Theme.surfaceSoft
                    Text {
                        anchors.centerIn: parent
                        text: "\uE8B9"
                        font.family: Theme.iconFont
                        font.pixelSize: 22
                        color: Theme.textMute
                    }
                }

                Image {
                    anchors.fill: parent
                    source: card.thumb
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    cache: true
                    sourceSize.width: Math.max(1, Math.round(width * 1.2))
                    sourceSize.height: Math.max(1, Math.round(height * 1.2))
                    opacity: status === Image.Ready ? 1 : 0
                    scale: card.hovered ? 1.045 : 1.0
                    Behavior on opacity { NumberAnimation { duration: 180 } }
                    Behavior on scale { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
                }

                // 底部渐隐，保证标题永远看得清
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 46
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "transparent" }
                        GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.55) }
                    }
                }

                // 合集角标：一个小堆叠符号 + 数量
                Rectangle {
                    visible: card.isCollection
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.margins: 7
                    height: 20
                    width: collRow.implicitWidth + 14
                    radius: 10
                    color: Qt.rgba(0, 0, 0, 0.55)
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.18)
                    Row {
                        id: collRow
                        anchors.centerIn: parent
                        spacing: 4
                        Text {
                            text: "\uE8F1"
                            font.family: Theme.iconFont
                            font.pixelSize: 9
                            color: "#ffffff"
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "合集" + (Number(card.item.children || 0) > 0
                                            ? " " + card.item.children : "")
                            font.family: Theme.uiFont
                            font.pixelSize: 9
                            color: "#ffffff"
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }

                // 悬停浮层：只是「提示这块能点」，不给按钮
                // （整张卡片就是热区，浮层里再放按钮反而会被上层 MouseArea 吃掉点击）
                Rectangle {
                    objectName: "wsCardHover"
                    anchors.fill: parent
                    color: Qt.rgba(0, 0, 0, 0.32)
                    opacity: card.hovered ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 140 } }

                    Rectangle {
                        anchors.centerIn: parent
                        width: hintRow.implicitWidth + 26
                        height: 30
                        radius: 15
                        color: Theme.accent
                        opacity: card.hovered ? 1 : 0
                        scale: card.hovered ? 1 : 0.92
                        Behavior on opacity { NumberAnimation { duration: 140 } }
                        Behavior on scale {
                            NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
                        }
                        Row {
                            id: hintRow
                            anchors.centerIn: parent
                            spacing: 6
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: "查看详情"
                                font.family: Theme.uiFont
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                                color: "#ffffff"
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: "\uE76C"
                                font.family: Theme.iconFont
                                font.pixelSize: 9
                                color: "#ffffff"
                            }
                        }
                    }
                }

                // 订阅数角标（右下，压在封面里）
                Rectangle {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 7
                    height: 18
                    width: subsRow.implicitWidth + 12
                    radius: 9
                    color: Qt.rgba(0, 0, 0, 0.5)
                    Row {
                        id: subsRow
                        anchors.centerIn: parent
                        spacing: 3
                        Text {
                            text: "\uE735"
                            font.family: Theme.iconFont
                            font.pixelSize: 8
                            color: Theme.warn
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: page.fmtCount(card.item.subs)
                            font.family: Theme.monoFont
                            font.pixelSize: 9
                            color: "#ffffff"
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }
            }

            // 标题区
            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 9
                anchors.topMargin: 0
                spacing: 3
                Text {
                    width: parent.width
                    text: card.item.title || card.item.id
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    wrapMode: Text.Wrap
                    maximumLineCount: 1
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    text: {
                        var tags = card.item.tags || [];
                        if (tags.length > 0) return tags.slice(0, 2).join(" · ");
                        return card.item.id ? ("ID " + card.item.id) : "";
                    }
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 9
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }
            }
        }

        MouseArea {
            id: cardMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: card.opened()
        }
    }

    // ======================================================== 详情抽屉（浮层）
    Item {
        id: detailLayer
        anchors.fill: parent
        visible: page.detailOpen
        z: 200

        // 遮罩：点空白关掉
        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, 0.36)
            opacity: page.detailOpen ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 160 } }
            MouseArea {
                anchors.fill: parent
                onClicked: page.closeDetail()
            }
        }

        Rectangle {
            id: drawer
            width: 400
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            anchors.rightMargin: page.detailOpen ? 0 : -(width + 24)
            radius: Theme.radius
            color: Theme.panel
            border.width: 1
            border.color: Theme.borderHi
            clip: true
            Behavior on anchors.rightMargin {
                NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
            }

            // ---------------- 滚轮防穿透 ----------------
            // 详情里滚到底之后，滚轮会穿透到后面的卡片墙，把列表也滚走。
            // 铺一层只吃滚轮、不吃点击的 MouseArea 兜底（同详情面板的做法）。
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.NoButton
                z: -1
                onWheel: function (wheel) { wheel.accepted = true }
            }

            // 左侧一道强调色细边：和卡片墙分界，也当装饰
            Rectangle {
                width: 3
                height: parent.height - 40
                radius: 1.5
                color: Theme.accent
                opacity: 0.7
                anchors.left: parent.left
                anchors.leftMargin: 0
                anchors.verticalCenter: parent.verticalCenter
            }

            // 统计胶囊的统一样式（数字行、日期行共用）
            Component {
                id: statChipComp
                Rectangle {
                    required property var modelData
                    height: 20
                    width: Math.min(statTxt.implicitWidth + 24, 168)
                    radius: 10
                    color: Theme.scrim(0.05)
                    border.width: 1
                    border.color: Theme.border
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 7
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.glyph
                        font.family: Theme.iconFont
                        font.pixelSize: 9
                        color: modelData.tone
                    }
                    Text {
                        id: statTxt
                        anchors.left: parent.left
                        anchors.leftMargin: 20
                        anchors.verticalCenter: parent.verticalCenter
                        // 先按文字自然宽度算，超过胶囊上限才省略 ——
                        // 不能直接用 anchors.left/right 撑：那样 implicitWidth
                        // 会变成「已被省略后的宽度」，胶囊越缩越短（踩过）。
                        width: Math.min(implicitWidth, 140)
                        text: modelData.label
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        elide: Text.ElideRight
                    }
                }
            }

            Flickable {
                anchors.fill: parent
                anchors.margins: 16
                anchors.leftMargin: 18
                contentWidth: width
                contentHeight: detCol.height
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                ScrollBar.vertical: ScrollBar {
                    id: detBar
                    objectName: "wsDetailBar"
                    policy: ScrollBar.AsNeeded
                    width: 8
                    anchors.right: parent.right
                    anchors.rightMargin: -6
                    contentItem: Rectangle {
                        implicitWidth: 6
                        radius: 3
                        color: detBar.pressed ? Theme.accent
                                              : (detBar.hovered ? Theme.scrim(0.34)
                                                                : Theme.scrim(0.2))
                        Behavior on color { ColorAnimation { duration: 120 } }
                    }
                    background: Item { }
                }

                Column {
                    id: detCol
                    width: parent.width - 8
                    spacing: 10

                    // 从合集点进成员之后，这里给一条「返回」——
                    // 不然成员详情和合集详情共用一个抽屉，用户就回不去了。
                    Rectangle {
                        objectName: "wsBackRow"
                        width: parent.width
                        height: page.detailStack.length > 0 ? 30 : 0
                        visible: page.detailStack.length > 0
                        radius: Theme.radiusXS
                        color: backMa.containsMouse
                               ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.14)
                               : Theme.scrim(0.04)
                        border.width: 1
                        border.color: Theme.border

                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: "\uE72B"
                            font.family: Theme.iconFont
                            font.pixelSize: 11
                            color: Theme.accent
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 26
                            anchors.right: parent.right
                            anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            elide: Text.ElideRight
                            text: "返回合集：" + ((page.detailStack.length > 0
                                                  && page.detailStack[page.detailStack.length - 1].item)
                                                 ? (page.detailStack[page.detailStack.length - 1].item.title
                                                    || page.detailStack[page.detailStack.length - 1].item.id)
                                                 : "")
                            color: Theme.accent
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                        }
                        MouseArea {
                            id: backMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.backDetail()
                        }
                    }

                    // 顶部：大封面 + 关闭
                    Item {
                        width: parent.width
                        height: 186

                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusXS
                            color: Theme.surfaceSoft
                            clip: true
                            Image {
                                anchors.fill: parent
                                source: page.coverSource()
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                cache: true
                                sourceSize.width: Math.max(1, Math.round(width * 1.4))
                                sourceSize.height: Math.max(1, Math.round(height * 1.4))
                                opacity: status === Image.Ready ? 1 : 0
                                Behavior on opacity { NumberAnimation { duration: 180 } }
                            }

                            // 多封面：左边一张、右边一张（作者在简介里贴的效果图）
                            Repeater {
                                model: page.detailImages().length > 1 ? 1 : 0
                                delegate: Item {
                                    anchors.fill: parent
                                    Rectangle {
                                        anchors.left: parent.left
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.leftMargin: 6
                                        width: 24; height: 24; radius: 12
                                        visible: page.coverIndex > 0
                                        color: Qt.rgba(0, 0, 0, 0.5)
                                        Text {
                                            anchors.centerIn: parent
                                            text: "\uE76B"
                                            font.family: Theme.iconFont
                                            font.pixelSize: 10
                                            color: "#ffffff"
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: page.coverIndex = Math.max(0, page.coverIndex - 1)
                                        }
                                    }
                                    Rectangle {
                                        anchors.right: parent.right
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.rightMargin: 6
                                        width: 24; height: 24; radius: 12
                                        visible: page.coverIndex < page.detailImages().length - 1
                                        color: Qt.rgba(0, 0, 0, 0.5)
                                        Text {
                                            anchors.centerIn: parent
                                            text: "\uE76C"
                                            font.family: Theme.iconFont
                                            font.pixelSize: 10
                                            color: "#ffffff"
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: page.coverIndex = Math.min(page.detailImages().length - 1,
                                                                                  page.coverIndex + 1)
                                        }
                                    }
                                    // 「2 / 3」这样的角标
                                    Rectangle {
                                        anchors.left: parent.left
                                        anchors.bottom: parent.bottom
                                        anchors.margins: 7
                                        height: 18
                                        width: picIdx.implicitWidth + 12
                                        radius: 9
                                        color: Qt.rgba(0, 0, 0, 0.55)
                                        Text {
                                            id: picIdx
                                            anchors.centerIn: parent
                                            text: (page.coverIndex + 1) + " / " + page.detailImages().length
                                            color: "#ffffff"
                                            font.family: Theme.uiFont
                                            font.pixelSize: 9
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 7
                            width: 26
                            height: 26
                            radius: 13
                            color: Qt.rgba(0, 0, 0, 0.5)
                            Text {
                                anchors.centerIn: parent
                                text: "\uE711"
                                font.family: Theme.iconFont
                                font.pixelSize: 10
                                color: "#ffffff"
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: page.closeDetail()
                            }
                        }
                    }

                    // 缩略图条：一眼看到作者一共给了几张图，点哪张看哪张
                    Row {
                        objectName: "wsCoverStrip"
                        width: parent.width
                        height: page.detailImages().length > 1 ? 44 : 0
                        visible: page.detailImages().length > 1
                        spacing: 6

                        Repeater {
                            model: page.detailImages()
                            delegate: Rectangle {
                                required property var modelData
                                required property int index
                                width: 58
                                height: 40
                                radius: 4
                                clip: true
                                color: Theme.surfaceSoft
                                border.width: page.coverIndex === index ? 2 : 1
                                border.color: page.coverIndex === index ? Theme.accent : Theme.border

                                Image {
                                    anchors.fill: parent
                                    anchors.margins: 2
                                    source: page.coverSourceAt(index)
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    cache: true
                                    sourceSize.width: 116
                                    sourceSize.height: 80
                                    opacity: status === Image.Ready ? 1 : 0
                                    Behavior on opacity { NumberAnimation { duration: 150 } }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: page.coverIndex = index
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: page.picked.title || page.picked.id || ""
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                    }

                    // 点进来的是合集里重复出现的那个成员：说清楚它被放了几次，
                    // 不然用户下载时会以为「怎么下了好几遍同一个」。
                    Text {
                        objectName: "wsDupNotice"
                        width: parent.width
                        visible: page.dupTimes(page.picked.id) > 1
                        text: "这个 MOD 在这个合集里出现了 " + page.dupTimes(page.picked.id)
                              + " 次（作者放了多份）"
                        color: Theme.warn
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        wrapMode: Text.Wrap
                    }

                    // 标签 / 体积 / 状态
                    Flow {
                        width: parent.width
                        spacing: 5

                        Repeater {
                            model: page.picked.tags || []
                            delegate: Rectangle {
                                required property var modelData
                                height: 18
                                width: miniTag.implicitWidth + 12
                                radius: 9
                                color: Theme.scrim(0.055)
                                Text {
                                    id: miniTag
                                    anchors.centerIn: parent
                                    text: modelData
                                    color: Theme.textMute
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                }
                            }
                        }
                        Rectangle {
                            visible: (page.picked.sizeText || "").length > 0
                            height: 18
                            width: sizeTxt.implicitWidth + 12
                            radius: 9
                            color: Theme.scrim(0.055)
                            Text {
                                id: sizeTxt
                                anchors.centerIn: parent
                                text: page.picked.sizeText || ""
                                color: Theme.textMute
                                font.family: Theme.monoFont
                                font.pixelSize: 9
                            }
                        }
                        Rectangle {
                            visible: page.picked.installed === true
                            height: 18
                            width: instTxt.implicitWidth + 12
                            radius: 9
                            color: Qt.rgba(Theme.ok.r, Theme.ok.g, Theme.ok.b, 0.16)
                            Text {
                                id: instTxt
                                anchors.centerIn: parent
                                text: "已在本地"
                                color: Theme.ok
                                font.family: Theme.uiFont
                                font.pixelSize: 9
                            }
                        }
                    }

                    // 工坊统计：浏览 / 订阅 / 收藏 一行，更新 / 发布 一行
                    // （浏览订阅这些只有官方接口有，后端异步补回来才显示）
                    Column {
                        objectName: "wsStatsRow"
                        width: parent.width
                        spacing: 6
                        visible: page.statsCount() > 0

                        Flow {
                            width: parent.width
                            spacing: 6
                            visible: page.statChips().length > 0
                            Repeater {
                                model: page.statChips()
                                delegate: statChipComp
                            }
                        }
                        Flow {
                            width: parent.width
                            spacing: 6
                            visible: page.statDateChips().length > 0
                            Repeater {
                                model: page.statDateChips()
                                delegate: statChipComp
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        height: page.loadingDetail ? 20 : 0
                        visible: page.loadingDetail
                        spacing: 8
                        Spinner {
                            width: 13; height: 13
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: page.stage || "正在读取详情…"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            elide: Text.ElideRight
                            width: parent.width - 24
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    // 描述 + 翻译
                    Row {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: "简介"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Item { width: Math.max(0, parent.width - 140); height: 1 }
                        Rectangle {
                            visible: (page.picked.desc || "").length > 0
                            height: 21
                            width: trTxt.implicitWidth + 16
                            radius: 10
                            color: page.showTranslated
                                   ? Qt.rgba(Theme.accent.r, Theme.accent.g,
                                             Theme.accent.b, 0.18)
                                   : (trMa.containsMouse ? Theme.scrim(0.1) : Theme.scrim(0.05))
                            border.width: 1
                            border.color: page.showTranslated ? Theme.accent : Theme.border
                            Text {
                                id: trTxt
                                anchors.centerIn: parent
                                text: page.translating
                                      ? "翻译中…"
                                      : (page.showTranslated ? "看原文" : "译成中文")
                                color: page.showTranslated ? Theme.accent : Theme.textDim
                                font.family: Theme.uiFont
                                font.pixelSize: 9
                            }
                            MouseArea {
                                id: trMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                enabled: !page.translating
                                onClicked: {
                                    if (page.showTranslated) page.showTranslated = false;
                                    else if (page.translated.length > 0) page.showTranslated = true;
                                    else page.doTranslate();
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        visible: page.translateError.length > 0
                        text: "翻译失败：" + page.translateError
                        color: Theme.warn
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        wrapMode: Text.Wrap
                    }

                    // 简介框：固定高度 + 自己一条滚动条。
                    // 以前直接把 TextEdit 的高度写成 min(contentHeight, 210)
                    // 却没有 clip，长简介的文字会溢出自身高度、压到下面的按钮上。
                    Rectangle {
                        id: descWrap
                        objectName: "wsDescBox"
                        width: parent.width
                        height: Math.min(descFlick.contentHeight + 12, 210)
                        radius: Theme.radiusXS
                        color: Theme.scrim(0.03)
                        border.width: 1
                        border.color: Theme.border
                        clip: true

                        Flickable {
                            id: descFlick
                            objectName: "wsDescFlick"
                            anchors.fill: parent
                            anchors.margins: 6
                            anchors.rightMargin: 13
                            contentWidth: width
                            contentHeight: descEdit.contentHeight
                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            flickableDirection: Flickable.VerticalFlick

                            ScrollBar.vertical: ScrollBar {
                                id: descBar
                                objectName: "wsDescBar"
                                policy: descFlick.contentHeight > descFlick.height
                                        ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
                                width: 8
                                contentItem: Rectangle {
                                    implicitWidth: 6
                                    radius: 3
                                    color: parent.pressed ? Theme.accent
                                                          : (parent.hovered ? Theme.scrim(0.34)
                                                                            : Theme.scrim(0.2))
                                }
                                background: Item { }
                            }

                            TextEdit {
                                id: descEdit
                                objectName: "wsDescText"
                                width: descFlick.width
                                text: page.showTranslated && page.translated.length > 0
                                      ? page.translated
                                      : ((page.picked.desc || "").length > 0
                                         ? page.picked.desc : "（这个 MOD 没写简介）")
                                color: page.showTranslated ? Theme.text : Theme.textDim
                                font.family: Theme.uiFont
                                font.pixelSize: 11
                                wrapMode: TextEdit.WrapAnywhere
                                readOnly: true
                                selectByMouse: true
                                persistentSelection: true
                                textFormat: TextEdit.PlainText
                                selectionColor: Qt.rgba(Theme.accent.r, Theme.accent.g,
                                                        Theme.accent.b, 0.45)
                                selectedTextColor: "#ffffff"
                                activeFocusOnPress: false
                            }
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    // 「连前置一起下」——默认不勾。前置在工坊里是另一个 MOD，
                    // 用户不勾就只下本体；勾了才把没装过的前置一起排进下载队列。
                    // 确认没有前置时整行不出现（见 showDepRow）。
                    Rectangle {
                        id: depRow
                        objectName: "wsDepRow"
                        width: parent.width
                        height: page.showDepRow() ? 42 : 0
                        visible: page.showDepRow()
                        radius: Theme.radiusS
                        color: page.includeDeps
                               ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.10)
                               : (depMa.containsMouse ? Theme.scrim(0.08) : Theme.scrim(0.03))
                        border.width: 1
                        border.color: page.includeDeps ? Theme.accent : Theme.border

                        HoverHandler { cursorShape: Qt.PointingHandCursor }

                        MouseArea {
                            id: depMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                page.includeDeps = !page.includeDeps;
                                if (page.includeDeps) page.wantDeps();
                            }
                        }

                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 8

                            Rectangle {
                                width: 16
                                height: 16
                                radius: 4
                                anchors.verticalCenter: parent.verticalCenter
                                color: page.includeDeps ? Theme.accent : "transparent"
                                border.width: 1
                                border.color: page.includeDeps ? Theme.accent : Theme.border
                                Text {
                                    anchors.centerIn: parent
                                    visible: page.includeDeps
                                    text: "\uE73E"
                                    font.family: Theme.iconFont
                                    font.pixelSize: 9
                                    color: Theme.bg
                                }
                            }

                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: "连前置一起下"
                                color: page.includeDeps ? Theme.text : Theme.textDim
                                font.family: Theme.uiFont
                                font.pixelSize: 11
                            }
                        }

                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.min(implicitWidth, parent.width * 0.5)
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideRight
                            text: page.depHint()
                            color: page.includeDeps ? Theme.accent : Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 9
                        }
                    }

                    // 动作区
                    Row {
                        width: parent.width
                        spacing: 8

                        ActionButton {
                            width: parent.width - 104
                            height: 36
                            label: page.downloading ? "下载中…"
                                   : (page.picked.installed === true
                                      ? "重新下载" : "下载到 addons")
                            busy: page.downloading
                            // 只要知道 ID 就能下：直链由后端在下载时现解析
                            enabledBtn: ((page.picked.url || "").length > 0
                                         || page.picked.isCollection === true
                                         || (page.picked.id || "").length > 0)
                                        && !page.downloading && !page.loadingDetail
                            onClicked: page.doDownload()
                        }

                        Rectangle {
                            width: 96
                            height: 36
                            radius: Theme.radiusS
                            readonly property bool on: page.mgr && page.picked.id
                                                       ? page.mgr.isLater(page.picked.id) : false
                            color: on
                                   ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
                                   : (laterBtnMa.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.04))
                            border.width: 1
                            border.color: on ? Theme.accent : Theme.border
                            Row {
                                anchors.centerIn: parent
                                spacing: 5
                                Text {
                                    text: parent.parent.on ? "\uE735" : "\uE734"
                                    font.family: Theme.iconFont
                                    font.pixelSize: 11
                                    color: parent.parent.on ? Theme.accent : Theme.textDim
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: parent.parent.on ? "已存" : "稍后看"
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                    color: parent.parent.on ? Theme.accent : Theme.textDim
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                            MouseArea {
                                id: laterBtnMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (page.mgr && page.picked.id) {
                                        page.mgr.toggleLater(page.picked.id);
                                        page.syncLaterModel();
                                    }
                                }
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 6
                        Rectangle {
                            height: 26
                            width: pageTxt.implicitWidth + 18
                            radius: 13
                            color: pageMa.containsMouse ? Theme.scrim(0.1) : Theme.scrim(0.045)
                            border.width: 1
                            border.color: Theme.border
                            Text {
                                id: pageTxt
                                anchors.centerIn: parent
                                text: "打开工坊页面"
                                color: Theme.textDim
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                            MouseArea {
                                id: pageMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (page.mgr && page.picked.id)
                                        page.mgr.openWorkshopPage(page.picked.id);
                                }
                            }
                        }
                        Rectangle {
                            height: 26
                            width: copyTxt.implicitWidth + 18
                            radius: 13
                            color: copyMa.containsMouse ? Theme.scrim(0.1) : Theme.scrim(0.045)
                            border.width: 1
                            border.color: Theme.border
                            Text {
                                id: copyTxt
                                anchors.centerIn: parent
                                text: "复制 ID"
                                color: Theme.textDim
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                            MouseArea {
                                id: copyMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (page.mgr && page.picked.id)
                                        page.mgr.copyWorkshopLink(page.picked.id);
                                }
                            }
                        }
                        // 没有前置的 MOD 不会自动出现「连前置一起下」那一行，
                        // 想确认一次就点这里（会跑一遍带前置的完整解析）。
                        Rectangle {
                            height: 26
                            width: depChkTxt.implicitWidth + 18
                            radius: 13
                            visible: page.picked.isCollection !== true
                                     && page.depCount() === 0 && !page.includeDeps
                                     && !page.depsProbing && !page.pendingDeps
                                     && !page.loadingDetail
                            color: depChkMa.containsMouse ? Theme.scrim(0.1) : Theme.scrim(0.045)
                            border.width: 1
                            border.color: Theme.border
                            Text {
                                id: depChkTxt
                                anchors.centerIn: parent
                                text: page.probeFull ? "复查前置" : "检查前置"
                                color: Theme.textDim
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                            MouseArea {
                                id: depChkMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: page.wantDeps()
                            }
                        }
                    }

                    // 合集：说清楚「成员都列在下面了、下载会把全部一起拉」，不然会以为列表不全
                    Text {
                        width: parent.width
                        visible: page.picked.isCollection === true && !page.loadingDetail
                        text: page.memberCount > 0
                              ? ("这个合集一共 " + page.memberTotal
                                 + " 个成员，下面都列出来了；点下载会把全部成员一起拉下来")
                              : ("合集，共 " + (page.picked.memberCount
                                              || page.picked.listedCount || 0)
                                 + " 个成员，点下载会一起拉下来")
                        color: Theme.cyan
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        wrapMode: Text.Wrap
                    }

                    // ---------------- 合集成员清单
                    // 首屏先 60 个，剩下的后端一批 100 个往回送，这里只往后接，
                    // 不重建列表 —— 边拉边看，不用干等 875 个全解析完。
                    Column {
                        objectName: "wsMemberBox"
                        width: parent.width
                        spacing: 6
                        visible: page.picked.isCollection === true
                                 && page.memberCount > 0 && !page.loadingDetail

                        Row {
                            width: parent.width
                            spacing: 6
                            Text {
                                id: memberTitle
                                text: "成员"
                                color: Theme.text
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                            }
                            Text {
                                objectName: "wsMemberHint"
                                width: parent.width - memberTitle.implicitWidth - 12
                                text: page.membersHint()
                                color: page.membersDone ? Theme.textMute : Theme.accent
                                font.family: Theme.uiFont
                                font.pixelSize: 9
                                elide: Text.ElideRight
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: Math.min(268, memberList.contentHeight + 10)
                            radius: Theme.radiusXS
                            color: Theme.scrim(0.045)
                            border.width: 1
                            border.color: Theme.border

                            ListView {
                                id: memberList
                                objectName: "wsMemberList"
                                anchors.fill: parent
                                anchors.margins: 5
                                clip: true
                                spacing: 2
                                model: page.memberItems
                                boundsBehavior: Flickable.StopAtBounds

                                delegate: Rectangle {
                                    width: ListView.view.width
                                    height: 34
                                    radius: Theme.radiusXS
                                    color: memMa.containsMouse ? Theme.scrim(0.1) : "transparent"

                                    Row {
                                        anchors.left: parent.left
                                        anchors.leftMargin: 6
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 8

                                        Rectangle {
                                            width: 22
                                            height: 22
                                            radius: 4
                                            color: Theme.scrim(0.12)
                                            anchors.verticalCenter: parent.verticalCenter
                                            Image {
                                                anchors.fill: parent
                                                anchors.margins: 1
                                                source: (page.mgr && modelData.preview)
                                                        ? page.mgr.coverUrl(modelData.preview) : ""
                                                fillMode: Image.PreserveAspectCrop
                                                asynchronous: true
                                                sourceSize.width: 44
                                                sourceSize.height: 44
                                            }
                                        }
                                        Column {
                                            anchors.verticalCenter: parent.verticalCenter
                                            width: memberList.width - 130
                                            spacing: 1
                                            Text {
                                                width: parent.width
                                                text: modelData.title || ("工坊 " + modelData.id)
                                                color: modelData.installed ? Theme.textMute : Theme.text
                                                font.family: Theme.uiFont
                                                font.pixelSize: 10
                                                elide: Text.ElideRight
                                            }
                                            Row {
                                                spacing: 6
                                                Text {
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    text: modelData.sizeText || ""
                                                    color: Theme.textMute
                                                    font.family: Theme.uiFont
                                                    font.pixelSize: 8
                                                }
                                                // 同一个 MOD 在合集里被放了不止一次 —— 下之前先知道，
                                                // 免得多下一份一样的（体积可不小）。
                                                Rectangle {
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    visible: page.isDupMember(modelData.id)
                                                    height: 13
                                                    width: dupTxt.implicitWidth + 10
                                                    radius: 6
                                                    color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.16)
                                                    Text {
                                                        id: dupTxt
                                                        anchors.centerIn: parent
                                                        text: "重复"
                                                        color: Theme.warn
                                                        font.family: Theme.uiFont
                                                        font.pixelSize: 8
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    // 已装的标一下，省得重复下
                                    Text {
                                        anchors.right: parent.right
                                        anchors.rightMargin: 8
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: modelData.installed === true
                                        text: "已装"
                                        color: Theme.ok
                                        font.family: Theme.uiFont
                                        font.pixelSize: 8
                                    }
                                    Text {
                                        anchors.right: parent.right
                                        anchors.rightMargin: 8
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: modelData.installed !== true
                                             && modelData.available === false
                                        text: "下载时解析直链"
                                        color: Theme.textMute
                                        font.family: Theme.uiFont
                                        font.pixelSize: 8
                                    }

                                    MouseArea {
                                        id: memMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: page.openDetail(modelData)
                                    }
                                }

                                ScrollBar.vertical: ScrollBar {
                                    id: memberBar
                                    objectName: "wsMemberBar"
                                    policy: ScrollBar.AsNeeded
                                    width: 6
                                    contentItem: Rectangle {
                                        radius: 3
                                        color: memberBar.pressed ? Theme.accent
                                               : (memberBar.hovered ? Theme.scrim(0.34)
                                                                    : Theme.scrim(0.2))
                                    }
                                    background: Item { }
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        visible: page.picked.available === false && !page.loadingDetail
                                 && page.picked.isCollection !== true
                        text: "这个条目没有可用的下载直链（可能只有正版订阅能下）"
                        color: Theme.warn
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        wrapMode: Text.Wrap
                    }

                    // 「直链在下载时解析」这类说明（详情页因此才能秒开）
                    Text {
                        width: parent.width
                        visible: (page.picked.note || "").length > 0
                                 && !page.loadingDetail
                                 && page.picked.available !== false
                                 && page.picked.isCollection !== true
                        text: page.picked.note || ""
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        wrapMode: Text.Wrap
                    }

                    Text {
                        width: parent.width
                        text: "下载会落到 addons 目录；同名文件不覆盖，自动加序号。"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        wrapMode: Text.Wrap
                    }

                    Item { width: 1; height: 6 }
                }
            }

            // 抽屉自己的滚动条
            Rectangle {
                width: 4
                radius: 2
                color: Theme.scrim(0.18)
                anchors.right: parent.right
                anchors.rightMargin: 3
                anchors.top: parent.top
                anchors.topMargin: 16
                height: Math.max(30, (parent.height - 32) * 0.3)
                visible: false
            }
        }
    }

    // ======================================================== ID 直达弹窗
    Popup {
        id: idDialog
        anchors.centerIn: parent
        width: 420
        height: 152
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        padding: 0

        background: Rectangle {
            radius: Theme.radiusS
            color: Theme.panel
            border.width: 1
            border.color: Theme.borderHi
        }

        Column {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10

            Row {
                width: parent.width
                Text {
                    text: "ID 直达"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
                Item { width: Math.max(0, parent.width - 60); height: 1 }
            }

            Text {
                width: parent.width
                text: "粘贴工坊链接或纯数字 ID，直接看详情并下载（合集也行）。"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
                wrapMode: Text.Wrap
            }

            Rectangle {
                width: parent.width
                height: 34
                radius: Theme.radiusXS
                color: Theme.surfaceSoft
                border.width: 1
                border.color: idInput.activeFocus ? Theme.accent : Theme.border

                HoverHandler { cursorShape: Qt.IBeamCursor }

                TextInput {
                    id: idInput
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    verticalAlignment: TextInput.AlignVCenter
                    color: Theme.text
                    font.family: Theme.monoFont
                    font.pixelSize: 11
                    selectByMouse: true
                    clip: true
                    onAccepted: idGoBtn.clicked()
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: idInput.text.length === 0
                        text: "例如 3829533320"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                }
            }

            Row {
                width: parent.width
                spacing: 8
                ActionButton {
                    id: idGoBtn
                    width: (parent.width - 8) / 2
                    height: 32
                    label: "打开详情"
                    onClicked: {
                        var raw = String(idInput.text || "").trim();
                        if (!raw) return;
                        var m = /([?&]id=)?(\d{5,20})/.exec(raw);
                        var wid = m ? m[2] : raw;
                        var item = { id: wid, title: "工坊 " + wid, preview: "", subs: 0 };
                        idDialog.close();
                        idInput.text = "";
                        page.openDetail(item);
                    }
                }
                ActionButton {
                    width: (parent.width - 8) / 2
                    height: 32
                    accent: false
                    label: "取消"
                    onClicked: idDialog.close()
                }
            }
        }
    }
}
