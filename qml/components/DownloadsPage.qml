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

// 下载页：所有下载（MOD / B站视频 / 以后别的东西）都在这一个列表里。
//
// 设计取舍：
//   - **不做「解析」标签页**。参考项目那边「解析 + 任务列表」两块是因为它要
//     从链接里解析工坊 ID；这边的解析入口已经长在创意工坊页和 MOD 面板里了，
//     再搬一个过来只会让两处逻辑分叉。这里只做一件事：把队列看清楚、能操作。
//   - **进行中永远排在最上面**（后端 `_sorted()` 保证），已结束的按时间倒序。
//   - 进度条只在 running 时动；done 显示绿色满格，failed/canceled 变灰，
//     一眼能分清「下完了」和「没下成」。
Item {
    id: page
    objectName: "downloadsPage"

    property var mgr: (typeof core !== "undefined" && core) ? core.downloads : null
    property var tasks: mgr ? mgr.tasks : []
    property string filter: "all"        // all / active / done / failed
    property var filtered: page.applyFilter(page.tasks, page.filter)

    readonly property color okColor: "#3FBF6E"
    readonly property color errColor: "#E5534B"
    readonly property color accentColor: Theme.accent

    Connections {
        target: page.mgr
        function onDownloadsChanged() {
            page.tasks = page.mgr.tasks
        }
    }

    function applyFilter(rows, mode) {
        if (!rows)
            return []
        if (mode === "active")
            return rows.filter(function (t) { return t.active })
        if (mode === "done")
            return rows.filter(function (t) { return t.status === "done" })
        if (mode === "failed")
            return rows.filter(function (t) {
                return t.status === "failed" || t.status === "canceled"
            })
        return rows
    }

    function statusText(t) {
        switch (t.status) {
        case "queued": return "排队中"
        case "running": return "下载中"
        case "done": return "已完成"
        case "failed": return "失败"
        case "canceled": return "已取消"
        default: return t.status
        }
    }

    function statusColor(t) {
        switch (t.status) {
        case "running": return page.accentColor
        case "queued": return Theme.textDim
        case "done": return page.okColor
        case "failed": return page.errColor
        case "canceled": return Theme.textMute
        default: return Theme.textMute
        }
    }

    function kindText(kind) {
        if (kind === "mod") return "MOD"
        if (kind === "video") return "视频"
        return "文件"
    }

    function kindGlyph(kind) {
        if (kind === "mod") return "\uE8B7"
        if (kind === "video") return "\uE714"
        return "\uE896"
    }

    function progressText(t) {
        if (t.total > 0)
            return t.doneText + " / " + t.totalText
        if (t.done > 0)
            return t.doneText
        return "—"
    }

    function counts(mode) {
        if (!page.tasks)
            return 0
        return page.applyFilter(page.tasks, mode).length
    }

    // ---------------------------------------------------- 压缩包 → 导入 MOD
    // 点「导入 MOD」先查包里有什么：有 .vpk 才弹确认，没有就直接说清楚。
    // 这样不会让用户对着一个几百 MB 的无关压缩包白等解压。
    property string importTaskId: ""
    property var importInfo: ({})
    property bool importOpen: false

    function askImportArchive(tid) {
        if (!page.mgr)
            return
        var info = page.mgr.inspectTaskArchive(tid)
        if (!info || info.ok !== true) {
            page.importError = (info && info.error) || "这个压缩包打不开"
            page.importOpen = true
            page.importTaskId = tid
            page.importInfo = info || ({})
            return
        }
        if (!info.isArchive) {
            page.importError = "这个文件不是压缩包"
            page.importOpen = true
            page.importTaskId = tid
            page.importInfo = info
            return
        }
        page.importTaskId = tid
        page.importInfo = info
        page.importError = ""
        page.importOpen = true
    }

    function confirmImportArchive() {
        if (!page.mgr || page.importTaskId.length === 0)
            return
        var res = page.mgr.importTaskArchive(page.importTaskId)
        page.importOpen = false
        page.importResult = (res && res.ok)
                             ? ("已导入 " + (res.copied || []).length + " 个 MOD")
                             : ((res && res.error) || "导入失败")
        page.importResultAt = Date.now()
    }

    property string importError: ""
    property string importResult: ""
    property double importResultAt: 0

    // ------------------------------------------------------------ 页头
    Item {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 58

        Column {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Text {
                text: "下载"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 19
                font.weight: Font.Bold
            }
            Text {
                text: page.mgr ? page.mgr.summaryText : ""
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
            }
        }

        Row {
            anchors.right: parent.right
            // ★ 让开右上角的全局窗口按钮（最小化 / 最大化 / 关闭）。
            //   以前这里是 anchors.right: parent.right 顶到底，那个按钮正好压在
            //   最小化/最大化/关闭底下，点不着也看不清（用户报的「重叠」）。
            anchors.rightMargin: (typeof win !== "undefined" && win)
                                 ? win.winButtonsReserve : 150
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            ActionButton {
                objectName: "dlClearBtn"
                label: "清空已结束"
                glyph: "\uE74D"
                accent: false
                enabledBtn: page.counts("done") + page.counts("failed") > 0
                // ★ 这一下现在会**连文件一起删**（以前只摘记录，文件留在磁盘上，
                //   用户报的「无法真实删除，还会遗留」）。提示要说清楚；
                //   下进 addons 的 MOD 仍然只摘记录，也照实写出来。
                //
                //   注意 ActionButton 没有 tip 属性（那是 IconButton 的），
                //   所以这里挂 ToolTip，别写 `tip:` —— 那样会被静默忽略。
                //
                //   ★ 也不能写成 `ToolTip.visible: clrHover.containsMouse`
                //     再在下面声明 `HoverHandler { id: clrHover }`：
                //     同一对象里**先引用后声明**，属性绑定求值时 clrHover
                //     还没实例化，Qt 会报 "Unable to assign [undefined] to bool"。
                //     用 HoverHandler 自己的 `hovered` 属性就没有这个问题。
                ToolTip.text: "清掉已完成/失败的记录，并删除下载的文件"
                              + "（进回收站；下进 addons 的 MOD 文件保留）"
                ToolTip.delay: 500
                ToolTip.visible: clrHover.hovered
                HoverHandler {
                    id: clrHover
                    // HoverHandler 默认只在 pressed 时才算 hovered，
                    // 要显式打开「悬停即真」，否则提示永远不弹。
                    blocking: false
                }
                onClicked: if (page.mgr) page.mgr.clearFinished()
            }
        }
    }

    // ------------------------------------------------------------ 筛选条
    Row {
        id: filterBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.topMargin: 2
        height: 26
        spacing: 6

        Repeater {
            model: [
                { key: "all", label: "全部" },
                { key: "active", label: "进行中" },
                { key: "done", label: "已完成" },
                { key: "failed", label: "失败/取消" }
            ]
            delegate: Rectangle {
                width: chipTxt.implicitWidth + 22
                height: 26
                radius: 13
                color: page.filter === modelData.key
                       ? Qt.rgba(page.accentColor.r, page.accentColor.g, page.accentColor.b, 0.16)
                       : (chipMa.containsMouse ? Theme.scrim(0.07) : "transparent")
                border.width: page.filter === modelData.key ? 1 : 0
                border.color: Qt.rgba(page.accentColor.r, page.accentColor.g,
                                      page.accentColor.b, 0.34)

                Text {
                    id: chipTxt
                    anchors.centerIn: parent
                    text: modelData.label + " " + page.counts(modelData.key)
                    color: page.filter === modelData.key ? page.accentColor : Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                }
                MouseArea {
                    id: chipMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: page.filter = modelData.key
                }
            }
        }
    }

    // ------------------------------------------------------------ 列表
    ListView {
        id: dlList
        objectName: "dlList"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: filterBar.bottom
        anchors.topMargin: 10
        anchors.bottom: parent.bottom
        clip: true
        spacing: 8
        boundsBehavior: Flickable.StopAtBounds
        model: page.filtered

        ScrollBar.vertical: ScrollBar {
            id: dlBar
            objectName: "dlBar"
            policy: ScrollBar.AsNeeded
            width: 8
            contentItem: Rectangle {
                radius: 4
                color: dlBar.pressed ? page.accentColor
                                     : (dlBar.hovered ? Theme.scrim(0.34) : Theme.scrim(0.2))
            }
            background: Item { }
        }

        delegate: Rectangle {
            id: card
            objectName: "dlCard"
            required property var modelData
            required property int index

            width: dlList.width
            height: 86
            radius: Theme.radiusS
            color: cardMa.containsMouse ? Theme.scrim(0.06) : Theme.scrim(0.035)
            border.width: 1
            border.color: modelData.status === "running"
                          ? Qt.rgba(page.accentColor.r, page.accentColor.g,
                                    page.accentColor.b, 0.4)
                          : Theme.border

            // 左侧状态细边
            Rectangle {
                width: 3
                height: parent.height - 20
                radius: 2
                anchors.left: parent.left
                anchors.leftMargin: 0
                anchors.verticalCenter: parent.verticalCenter
                color: page.statusColor(modelData)
            }

            MouseArea {
                id: cardMa
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.right: actions.left
                anchors.rightMargin: 10
                anchors.top: parent.top
                anchors.topMargin: 10
                spacing: 5

                // 第一行：类型徽章 + 状态 + 大小
                Row {
                    spacing: 7

                    Rectangle {
                        height: 17
                        width: kindRow.implicitWidth + 16
                        radius: 8.5
                        color: Theme.scrim(0.07)
                        Row {
                            id: kindRow
                            anchors.centerIn: parent
                            spacing: 4
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: page.kindGlyph(modelData.kind)
                                font.family: Theme.iconFont
                                font.pixelSize: 9
                                color: Theme.textMute
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: page.kindText(modelData.kind)
                                font.family: Theme.uiFont
                                font.pixelSize: 9
                                color: Theme.textMute
                            }
                        }
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: page.statusText(modelData)
                        color: page.statusColor(modelData)
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: (modelData.speedText || "").length > 0
                        text: modelData.speedText
                        color: Theme.textMute
                        font.family: Theme.monoFont
                        font.pixelSize: 10
                    }
                }

                // 第二行：标题
                Text {
                    width: parent.width
                    text: modelData.title
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }

                // 第三行：进度条 + 字节数
                Row {
                    width: parent.width
                    spacing: 8

                    Rectangle {
                        width: parent.width - bytesTxt.implicitWidth - 8
                        height: 5
                        radius: 2.5
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.scrim(0.12)

                        Rectangle {
                            width: parent.width * (modelData.percent / 100.0)
                            height: parent.height
                            radius: 2.5
                            color: modelData.status === "running" ? page.accentColor
                                 : (modelData.status === "done" ? page.okColor
                                    : Theme.scrim(0.3))
                            Behavior on width { NumberAnimation { duration: 180 } }
                        }
                    }
                    Text {
                        id: bytesTxt
                        anchors.verticalCenter: parent.verticalCenter
                        text: page.progressText(modelData)
                        color: Theme.textMute
                        font.family: Theme.monoFont
                        font.pixelSize: 10
                    }
                }

                // 失败原因 / 取消原因
                Text {
                    width: parent.width
                    visible: (modelData.error || "").length > 0
                    text: modelData.error
                    color: modelData.status === "failed" ? page.errColor : Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
            }

            // 右侧操作
            Row {
                id: actions
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4

                IconButton {
                    objectName: "dlCancelBtn"
                    glyph: "\uE711"
                    tip: "取消"
                    boxSize: 24
                    danger: true
                    visible: modelData.active
                    onClicked: if (page.mgr) page.mgr.cancelTask(modelData.id)
                }
                IconButton {
                    objectName: "dlRetryBtn"
                    glyph: "\uE72C"
                    tip: "重试"
                    boxSize: 24
                    visible: !modelData.active
                    onClicked: if (page.mgr) page.mgr.retryTask(modelData.id)
                }
                IconButton {
                    objectName: "dlFolderBtn"
                    glyph: "\uE8B7"
                    tip: "打开所在文件夹"
                    boxSize: 24
                    visible: !modelData.active
                    onClicked: if (page.mgr) page.mgr.openTaskFolder(modelData.id)
                }
                // 压缩包 → 一键导入 MOD
                // 只在「下完了、而且是压缩包」时出现。点了先查包里有没有 .vpk，
                // 有才问一句再导（避免白解压一个几百 MB 的无关包）。
                IconButton {
                    objectName: "dlImportBtn"
                    glyph: "\uE8B5"
                    tip: "把这个压缩包里的 MOD 导入 addons"
                    boxSize: 24
                    visible: modelData.isArchive === true
                    onClicked: if (page.mgr) page.askImportArchive(modelData.id)
                }
                IconButton {
                    objectName: "dlRemoveBtn"
                    glyph: "\uE74D"
                    // ★ 现在这一下**真的会删文件**（以前只摘记录，磁盘上还在，
                    //   用户报的「无法真实删除，还会遗留」就是它）。
                    //   提示必须说实话，不能还写「从列表移除」。
                    //   下进 addons 的 MOD 仍然只摘记录（见 downloads.py 里的
                    //   `_should_delete_file`），这里也照实说明。
                    tip: modelData.kind === "mod"
                         ? "从列表移除（MOD 文件会保留）"
                         : "移除并删除下载的文件（进回收站，可还原）"
                    boxSize: 24
                    visible: !modelData.active
                    onClicked: if (page.mgr) page.mgr.removeTask(modelData.id)
                }
            }
        }
    }

    // ------------------------------------------------------------ 空状态
    Column {
        objectName: "dlEmpty"
        anchors.centerIn: parent
        width: Math.min(440, parent.width - 60)
        spacing: 10
        visible: page.filtered.length === 0

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "\uE896"
            font.family: Theme.iconFont
            font.pixelSize: 38
            color: Theme.scrim(0.22)
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: page.tasks.length === 0 ? "还没有下载"
                                           : "这一档里没有任务"
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
            text: page.tasks.length === 0
                  ? "在创意工坊 / MOD 面板里点「下载」，或者视频详情里点「下载」，\n任务都会排到这里，能看进度、能取消、能重试。"
                  : "换个筛选看看，或者点「清空已结束」把记录收掉。"
            color: Theme.textMute
            font.family: Theme.uiFont
            font.pixelSize: 11
            lineHeight: 1.45
        }
    }

    // ------------------------------------------------------------ 导入确认
    Popup {
        id: importDlg
        objectName: "dlImportDlg"
        visible: page.importOpen
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        anchors.centerIn: Overlay.overlay

        Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.55) }

        onClosed: page.importOpen = false

        padding: 20
        contentWidth: 420
        contentHeight: importCol.implicitHeight

        background: Rectangle {
            radius: 14
            color: Theme.panel
            border.width: 1
            border.color: Theme.borderHi
        }

        contentItem: Column {
            id: importCol
            width: 420
            spacing: 10

            Text {
                width: parent.width
                text: (page.importInfo && page.importInfo.mods > 0)
                      ? "导入压缩包里的 MOD" : "这个压缩包用不上"
                color: Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }

            // 有 MOD：说明会导入几个、带几张封面，列出前几个名字
            Column {
                width: parent.width
                spacing: 6
                visible: page.importInfo && page.importInfo.mods > 0
                         && page.importError.length === 0

                Text {
                    width: parent.width
                    text: "里面有 " + page.importInfo.mods + " 个 MOD"
                          + (page.importInfo.images > 0
                             ? "，" + page.importInfo.images + " 张封面会一起导入"
                             : "（没找到封面图）")
                    color: Theme.ok
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: (page.importInfo.names || []).length > 0
                    text: (page.importInfo.names || []).join("\n")
                    color: Theme.textMute
                    font.family: Theme.monoFont
                    font.pixelSize: 10
                    lineHeight: 1.4
                    wrapMode: Text.WrapAnywhere
                }
                Text {
                    width: parent.width
                    text: "导入到 addons 目录；同名文件不会覆盖，会自动加序号。"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    wrapMode: Text.WordWrap
                }
            }

            // 没有 MOD / 出错
            Text {
                width: parent.width
                visible: page.importError.length > 0
                         || !(page.importInfo && page.importInfo.mods > 0)
                text: page.importError.length > 0
                      ? page.importError
                      : ("里面没有 .vpk 文件"
                         + ((page.importInfo && page.importInfo.images > 0)
                            ? "（只有图片）" : "") + "，没什么可导入的")
                color: page.importError.length > 0 ? page.warnColor : Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }

            Row {
                width: parent.width
                spacing: 8

                Item { width: Math.max(0, parent.width - 168); height: 1 }

                Rectangle {
                    width: 76
                    height: 30
                    radius: 15
                    color: impCancelMa.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.05)
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
                        id: impCancelMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.importOpen = false
                    }
                }

                Rectangle {
                    width: 84
                    height: 30
                    radius: 15
                    readonly property bool canImport: page.importInfo
                              && page.importInfo.mods > 0
                              && page.importError.length === 0
                    color: canImport ? page.accentColor : Theme.scrim(0.12)
                    Text {
                        anchors.centerIn: parent
                        text: "导入"
                        color: parent.canImport ? Theme.bg : Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: parent.canImport
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.confirmImportArchive()
                    }
                }
            }
        }
    }

    // 导入结果小条（几秒后自己消失）
    Rectangle {
        objectName: "dlImportResult"
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 12
        width: Math.min(460, resTxt.implicitWidth + 32)
        height: 32
        radius: 16
        visible: page.importResult.length > 0
                 && (Date.now() - page.importResultAt) < 4000
        color: Theme.panelHi
        border.width: 1
        border.color: page.importResult.indexOf("已导入") === 0
                      ? page.okColor : page.errColor

        Text {
            id: resTxt
            anchors.centerIn: parent
            text: page.importResult
            color: page.importResult.indexOf("已导入") === 0
                   ? page.okColor : page.errColor
            font.family: Theme.uiFont
            font.pixelSize: 11
        }
    }
}
