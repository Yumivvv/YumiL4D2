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

// 右侧滑出的视频详情面板
Item {
    id: panel
    objectName: "dpPanel"
    property var video: ({})
    property var links: []          // 简介里提取出的网盘链接
    property bool showPanel: false
    property bool loading: false
    signal closed()
    signal openUrl(string url)
    signal copyLink(string bvid)
    signal copyDesc(var video)
    signal markSeen(string bvid)
    signal playVideo(string bvid)
    signal copyText(string text)
    signal copyCode(string code, string name)
    signal openAuthor(string bvid)
    signal shareVideo(var video)
    signal downloadVideo(string bvid)
    // 三连：点赞 / 投币 / 收藏（具体点哪几项由设置决定）
    signal triple(string bvid)
    // 没登录时点三连 → 让主窗口引导去设置里登录
    signal needLogin()
    // 蓝奏云：交给下面下载（Main.qml 转给 core.downloads.addPanFile）
    signal downloadPanLink(var link)

    // 当前点了但还没决定「本地下载 / 浏览器」的那条链接
    property var pendingLink: ({})

    // 只对蓝奏云弹选择：其它网盘没有稳定直链，硬解析只会失败
    function isLanzou(url) {
        var u = (url || "").toLowerCase();
        return u.indexOf("lanzou") >= 0;
    }

    width: 480
    x: showPanel ? parent.width - width - 4 : parent.width + 30
    Behavior on x { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
    opacity: showPanel ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 180 } }
    visible: opacity > 0.01

    // ---------------- 下半部分的高度预算 ----------------
    // 统计区下面挤着三块：网盘链接、置顶评论、简介。
    // 以前前两块各自最多吃 150 / 132，谁都不让谁，内容一多简介那一块
    // 就被压成 0 高 —— 用户看到的正是「网盘链接太多，简介看不到了」。
    // 现在先给简介留够 descMin，剩下的空间再按 55% / 45% 分给前两块 ——
    // 两块加起来也只吃「余量」那点，不会动到简介的那一份。
    readonly property real belowStats: Math.max(0, actionsRow.y - (statsBox.y + statsBox.height) - 20)
    readonly property real descMin: 132
    // 简介标题那行 + 上下边距的固定开销（量出来约 46~54px，留 56 稳一点）
    readonly property real descChrome: 56
    readonly property real shareRoom: Math.max(0, belowStats - descChrome - descMin)

    // ★ 两个预算要**动态分配**，不能各占死一半。
    //   以前是 linkBudget = shareRoom*0.55、commentBudget = shareRoom*0.45，
    //   于是「视频没有网盘、但有置顶评论」时：网盘那一块高度 0，
    //   而它那 55% 的空间**白白闲置**，评论只能拿 45%，
    //   窗口小一点 45% 就接近 0，整块置顶评论被压没 ——
    //   用户看到的就是「有网盘才显示置顶评论，没网盘就不显示」。
    readonly property bool hasLinks: (panel.video.links || []).length > 0
    readonly property bool hasComment: ((panel.video.topComment || {}).text || "").length > 0
    readonly property real linkNeed: hasLinks ? linksCol.height + 16 : 0
    readonly property real commentNeed: hasComment ? tcCol.height + 16 : 0

    // 先把「需求」加起来，不超余量就各取所需（谁也不截断）
    readonly property real needTotal: linkNeed + commentNeed
    readonly property bool everythingFits: needTotal <= shareRoom

    // ★ 置顶评论的**保底高度**：窗口矮的时候 shareRoom 可能被简介吃光，
    //   评论分到 0 就整块消失。给个下限，宁可压缩简介也不让评论没了
    //   （评论通常就一两行字，占不了多少）。
    readonly property real commentFloor: 52

    readonly property real linkBudget: {
        if (!hasLinks) return 0;
        if (everythingFits) return linkNeed;
        // 只有网盘没有评论 → 独吞
        if (!hasComment) return shareRoom;
        return Math.max(0, shareRoom * 0.55);
    }
    readonly property real commentBudget: {
        if (!hasComment) return 0;
        if (everythingFits) return commentNeed;
        // 只有评论没有网盘 → 独吞（这正是用户报的那个场景）
        if (!hasLinks) return Math.max(commentFloor, shareRoom);
        // 两样都有：按 45% 分，但**不低于保底**
        return Math.max(Math.min(commentFloor, commentNeed), shareRoom * 0.45);
    }

    // ---------------- 滚轮防穿透 ----------------
    // Qt Quick 里没被接受的滚轮事件会「穿透」到同位置下层的 item，
    // 于是在内层 Flickable 滚到底之后，滚动会传到后面的视频列表上。
    // 这里铺一层只吃滚轮、不吃点击的 MouseArea 兜底。
    // z: -1 保证它垫在所有内容下面：内层 Flickable 先拿到滚轮，
    // 只有它滚不动时才会落到这里被吃掉。
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        z: -1
        onWheel: function (wheel) { wheel.accepted = true }
    }

    // ---------------- 背景 ----------------
    Rectangle {
        anchors.fill: parent
        radius: Theme.radius
        color: Theme.panel
        border.width: 1
        border.color: Theme.borderHi

        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: Theme.radius
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: Theme.scrim(0.035) }
                GradientStop { position: 0.35; color: "transparent" }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.22) }
            }
        }
    }

    // ---------------- 头部 ----------------
    Item {
        id: headerRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.topMargin: 16
        height: 32

        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: "视频详情"
            color: Theme.text
            font.family: Theme.uiFont
            font.pixelSize: 16
            font.weight: Font.DemiBold
        }

        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            Rectangle {
                width: 6
                height: 6
                radius: 3
                anchors.verticalCenter: parent.verticalCenter
                color: panel.loading ? Theme.warn : Theme.ok
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: panel.loading ? "加载中" : "已同步"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 10
            }
            IconButton {
                glyph: "\uE711"
                tip: "关闭 (Esc)"
                boxSize: 30
                onClicked: panel.closed()
            }
        }
    }

    // ---------------- 封面 ----------------
    Rectangle {
        id: hero
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: headerRow.bottom
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.topMargin: 10
        height: 186
        radius: Theme.radiusS
        color: Theme.surfaceSoft
        clip: true

        Image {
            id: heroImg
            anchors.fill: parent
            source: panel.video.coverUrl || ""
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: true
            opacity: status === Image.Ready ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 260 } }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 70
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 1.0; color: Qt.rgba(0.02, 0.03, 0.05, 0.9) }
            }
        }

        Rectangle {
            visible: (panel.video.duration || "").length > 0
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            height: 20
            width: heroDur.implicitWidth + 14
            radius: 5
            color: Qt.rgba(0, 0, 0, 0.62)
            Text {
                id: heroDur
                anchors.centerIn: parent
                text: panel.video.duration || ""
                font.family: Theme.monoFont
                font.pixelSize: 11
                color: "#E8EBF2"
            }
        }

        // 播放按钮：走内置播放器
        Rectangle {
            anchors.centerIn: parent
            width: 56
            height: 56
            radius: 28
            color: heroMa.pressed ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.92)
                                  : Qt.rgba(0, 0, 0, 0.46)
            border.width: 1.5
            border.color: heroMa.containsMouse ? Theme.accent : Theme.scrim(0.42)
            scale: heroMa.pressed ? 0.92 : (heroMa.containsMouse ? 1.08 : 1.0)
            Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
            Behavior on color { ColorAnimation { duration: 120 } }

            Text {
                anchors.centerIn: parent
                text: "\uE768"
                font.family: Theme.iconFont
                font.pixelSize: 23
                color: "#ffffff"
            }
            MouseArea {
                id: heroMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: panel.playVideo(panel.video.bvid || "")
            }
        }

        Item {
            anchors.fill: parent
            visible: panel.loading
            Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.55) }
            Spinner {
                anchors.centerIn: parent
                width: 32
                height: 32
            }
        }
    }

    // ---------------- 标题 / 作者 ----------------
    Column {
        id: titleBlock
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: hero.bottom
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.topMargin: 10
        spacing: 6

        // 标题可拖选：用 TextEdit(readOnly) 而不是 Text，Text 是画出来的字，
        // 鼠标拖不动。TextEdit 高度靠 contentHeight 自适应，行数和原来一致。
        TextEdit {
            id: titleEdit
            width: parent.width
            text: panel.video.title || ""
            color: Theme.text
            font.family: Theme.uiFont
            font.pixelSize: 15
            font.weight: Font.DemiBold
            wrapMode: TextEdit.Wrap
            readOnly: true
            selectByMouse: true
            persistentSelection: true
            textFormat: TextEdit.PlainText
            selectionColor: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.45)
            selectedTextColor: "#ffffff"
            // 高度跟着内容走，最多两行的高度（跟原来的视觉一致）
            height: Math.min(contentHeight, Math.ceil(font.pixelSize * 1.3 * 2 + 4))
            clip: true
            // 别抢走聚焦，否则 Esc 之类会被它吃掉
            activeFocusOnPress: false
            cursorVisible: false
        }

        Item {
            width: parent.width
            height: 17

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8

                Text {
                    text: "\uE77B"
                    font.family: Theme.iconFont
                    font.pixelSize: 12
                    color: authorMa.containsMouse ? Theme.accent : Theme.textMute
                    anchors.verticalCenter: parent.verticalCenter
                    Behavior on color { ColorAnimation { duration: 110 } }
                }

                // 点作者昵称打开作者名片
                Text {
                    id: authorName
                    text: panel.video.author || ""
                    color: authorMa.containsMouse ? Theme.accent : Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    font.underline: authorMa.containsMouse
                    anchors.verticalCenter: parent.verticalCenter
                    Behavior on color { ColorAnimation { duration: 110 } }

                    MouseArea {
                        id: authorMa
                        anchors.fill: parent
                        anchors.margins: -3
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: panel.openAuthor(panel.video.bvid || "")
                    }
                }

                Text {
                    text: "·"
                    color: Theme.textMute
                    font.pixelSize: 12
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: panel.video.pubText || ""
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }

    // ---------------- 数据 ----------------
    Rectangle {
        id: statsBox
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: titleBlock.bottom
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.topMargin: 8
        height: 50
        radius: Theme.radiusS
        color: Theme.scrim(0.035)
        border.width: 1
        border.color: Theme.border

        Row {
            anchors.fill: parent
            anchors.margins: 6
            Repeater {
                model: [
                    { k: "播放", v: panel.video.viewsText || "0", c: Theme.cyan },
                    { k: "点赞", v: panel.video.likeText || "0", c: Theme.pink },
                    { k: "弹幕", v: panel.video.danmakuText || "0", c: Theme.warn },
                    { k: "收藏", v: panel.video.favText || "0", c: Theme.ok }
                ]
                Column {
                    width: (statsBox.width - 12) / 4
                    spacing: 1
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: modelData.v
                        color: modelData.c
                        font.family: Theme.monoFont
                        font.pixelSize: 13
                        font.weight: Font.Bold
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: modelData.k
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }
            }
        }
    }

    // ---------------- 网盘链接区（有才显示） ----------------
    Rectangle {
        id: linksBox
        objectName: "dpLinksBox"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: statsBox.bottom
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.topMargin: 8
        height: panel.links.length > 0 ? Math.max(0, panel.linkBudget) : 0
        visible: panel.links.length > 0
        radius: Theme.radiusS
        color: Qt.rgba(Theme.ok.r, Theme.ok.g, Theme.ok.b, 0.055)
        border.width: 1
        border.color: Qt.rgba(Theme.ok.r, Theme.ok.g, Theme.ok.b, 0.22)
        clip: true

        Flickable {
            anchors.fill: parent
            anchors.margins: 8
            clip: true
            contentWidth: width
            contentHeight: linksCol.height
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                width: 10
                padding: 2
                contentItem: Rectangle {
                    implicitWidth: 6
                    radius: 3
                    color: parent.pressed ? Theme.scrim(0.42)
                                         : (parent.hovered ? Theme.scrim(0.32)
                                                           : Theme.scrim(0.20))
                }
            }

            Column {
                id: linksCol
                width: parent.width - 6
                spacing: 5

                Row {
                    width: parent.width
                    spacing: 6
                    Text {
                        text: "\uE71B"
                        font.family: Theme.iconFont
                        font.pixelSize: 11
                        color: Theme.ok
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "简介里的网盘链接"
                        color: Theme.ok
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                Repeater {
                    model: panel.links
                    delegate: Rectangle {
                        id: linkRow
                        width: linksCol.width
                        // 有文件说明时两行，否则一行
                        height: (modelData.label || "").length > 0 ? 46 : 30
                        radius: 6
                        color: lkMa.pressed ? Theme.scrim(0.16)
                                            : (lkMa.containsMouse ? Theme.scrim(0.10)
                                                                  : Theme.scrim(0.05))
                        Behavior on color { ColorAnimation { duration: 100 } }

                        Column {
                            anchors.left: parent.left
                            anchors.leftMargin: 8
                            anchors.right: parent.right
                            anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 3

                            // 第一行：网盘名 + 链接 + 提取码
                            Row {
                                width: parent.width
                                spacing: 7

                                // 网盘图标：主题色圆角块 + 网盘名首字，
                                // 一眼看出是夸克/百度/蓝奏/爱发电还是别的
                                Rectangle {
                                    width: 22
                                    height: 22
                                    radius: 5
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: modelData.color || Theme.ok
                                    Text {
                                        anchors.centerIn: parent
                                        text: (modelData.name || "盘").substring(0, 1)
                                        color: "#ffffff"
                                        font.family: Theme.uiFont
                                        font.pixelSize: 11
                                        font.weight: Font.Bold
                                    }
                                }
                                Text {
                                    text: modelData.name
                                    color: Theme.text
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                    font.weight: Font.DemiBold
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    width: Math.max(40, parent.width - 210)
                                    text: modelData.url
                                    color: Theme.textMute
                                    font.family: Theme.monoFont
                                    font.pixelSize: 10
                                    elide: Text.ElideMiddle
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Rectangle {
                                    visible: (modelData.code || "").length > 0
                                    height: 16
                                    width: codeTxt.implicitWidth + 10
                                    radius: 3
                                    color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.16)
                                    anchors.verticalCenter: parent.verticalCenter
                                    Text {
                                        id: codeTxt
                                        anchors.centerIn: parent
                                        text: "码 " + modelData.code
                                        color: Theme.warn
                                        font.family: Theme.monoFont
                                        font.pixelSize: 9
                                    }
                                }
                            }

                            // 第二行：这个网盘里装的是什么
                            Row {
                                width: parent.width
                                spacing: 5
                                visible: (modelData.label || "").length > 0

                                Text {
                                    text: "\uE8A5"
                                    font.family: Theme.iconFont
                                    font.pixelSize: 9
                                    color: Theme.ok
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    width: parent.width - 16
                                    text: modelData.label || ""
                                    color: Theme.textDim
                                    font.family: Theme.uiFont
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                        }

                        MouseArea {
                            id: lkMa
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            cursorShape: Qt.PointingHandCursor

                            // 提示：右键弹出菜单，可复制链接或提取码
                            ToolTip.visible: lkMa.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "右键：复制链接" + ((modelData.code || "").length > 0
                                                              ? " / 提取码 " + modelData.code : "")

                            onClicked: function (mouse) {
                                if (mouse.button === Qt.RightButton) {
                                    // 有码弹含「复制提取码」的菜单，无码弹精简菜单，
                                    // 彻底避免无码时菜单里多一个空项
                                    if ((modelData.code || "").length > 0)
                                        linkMenuWithCode.popup();
                                    else
                                        linkMenuNoCode.popup();
                                } else if (panel.isLanzou(modelData.url)) {
                                    // 蓝奏云：直接给直链，能本地下，所以先问一句
                                    // 「本地下载 / 浏览器打开」，而不是闷头开浏览器。
                                    panel.pendingLink = modelData;
                                    lanzouChoice.popup();
                                } else {
                                    panel.openUrl(modelData.url);
                                }
                            }
                        }

                        // 蓝奏云专用：点一下先问「本地下载还是浏览器」
                        Menu {
                            id: lanzouChoice
                            objectName: "lanzouChoiceMenu"
                            MenuItem {
                                objectName: "lanzouLocalDl"
                                text: "本地下载（解析直链）"
                                onTriggered: panel.downloadPanLink(panel.pendingLink)
                            }
                            MenuItem {
                                text: "在浏览器打开"
                                onTriggered: panel.openUrl((panel.pendingLink || {}).url || "")
                            }
                        }

                        Menu {
                            id: linkMenuWithCode
                            MenuItem {
                                text: "复制链接"
                                onTriggered: panel.copyText(modelData.url)
                            }
                            MenuItem {
                                text: "复制提取码 " + modelData.code
                                onTriggered: panel.copyCode(modelData.code, modelData.name || "")
                            }
                            MenuItem {
                                text: "在浏览器打开"
                                onTriggered: panel.openUrl(modelData.url)
                            }
                        }
                        Menu {
                            id: linkMenuNoCode
                            MenuItem {
                                text: "复制链接"
                                onTriggered: panel.copyText(modelData.url)
                            }
                            MenuItem {
                                text: "在浏览器打开"
                                onTriggered: panel.openUrl(modelData.url)
                            }
                        }
                    }
                }
            }
        }
    }

    // ---------------- 置顶评论（有才显示） ----------------
    Rectangle {
        id: topCommentBox
        objectName: "dpCommentBox"
        readonly property var tc: panel.video.topComment || ({})
        readonly property bool has: (tc.text || "").length > 0
        readonly property var extraLinks: panel.video.commentLinks || []

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: linksBox.bottom
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.topMargin: has ? 8 : 0
        height: has ? Math.max(0, panel.commentBudget) : 0
        visible: has
        radius: Theme.radiusS
        color: Qt.rgba(Theme.cyan.r, Theme.cyan.g, Theme.cyan.b, 0.055)
        border.width: 1
        border.color: Qt.rgba(Theme.cyan.r, Theme.cyan.g, Theme.cyan.b, 0.22)
        clip: true

        Flickable {
            anchors.fill: parent
            anchors.margins: 8
            clip: true
            contentWidth: width
            contentHeight: tcCol.height
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                width: 10
                padding: 2
                contentItem: Rectangle {
                    implicitWidth: 6
                    radius: 3
                    color: parent.pressed ? Theme.scrim(0.42)
                                         : (parent.hovered ? Theme.scrim(0.32)
                                                           : Theme.scrim(0.20))
                }
            }

            Column {
                id: tcCol
                width: parent.width - 6
                spacing: 4

                // 头部：置顶标记 + 用户 + 点赞
                Row {
                    width: parent.width
                    spacing: 6

                    Text {
                        text: "\uE718"
                        font.family: Theme.iconFont
                        font.pixelSize: 10
                        color: Theme.cyan
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "置顶评论"
                        color: Theme.cyan
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: topCommentBox.tc.user || ""
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        elide: Text.ElideRight
                        width: Math.min(implicitWidth, parent.width - 90)
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Item { width: 1; height: 1 }
                    Text {
                        text: "赞 " + (topCommentBox.tc.like || 0)
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                // 正文（可拖选）
                TextEdit {
                    width: parent.width
                    text: topCommentBox.tc.text || ""
                    color: Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    wrapMode: TextEdit.WrapAnywhere
                    readOnly: true
                    selectByMouse: true
                    persistentSelection: true
                    textFormat: TextEdit.PlainText
                    selectionColor: Qt.rgba(Theme.cyan.r, Theme.cyan.g, Theme.cyan.b, 0.45)
                    selectedTextColor: "#ffffff"
                    activeFocusOnPress: false
                    cursorVisible: false
                }

                // 置顶评论里发的网盘（有才显示，复用下面同一套打开/复制逻辑）
                Repeater {
                    model: topCommentBox.extraLinks
                    delegate: Rectangle {
                        id: tcLinkRow
                        required property var modelData
                        width: tcCol.width
                        height: 26
                        radius: 5
                        color: tcLinkMa.pressed ? Theme.scrim(0.16)
                                                : (tcLinkMa.containsMouse ? Theme.scrim(0.10)
                                                                          : Theme.scrim(0.05))

                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 7
                            anchors.right: parent.right
                            anchors.rightMargin: 7
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 6

                            // 评论里的网盘也用同样图标风格：主题色块 + 首字
                            Rectangle {
                                width: 20
                                height: 20
                                radius: 4
                                anchors.verticalCenter: parent.verticalCenter
                                color: modelData.color || Theme.ok
                                Text {
                                    anchors.centerIn: parent
                                    text: (modelData.name || "盘").substring(0, 1)
                                    color: "#ffffff"
                                    font.family: Theme.uiFont
                                    font.pixelSize: 10
                                    font.weight: Font.Bold
                                }
                            }
                            Text {
                                text: modelData.name || "网盘"
                                color: Theme.text
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                width: Math.max(30, parent.width - 150)
                                text: modelData.url || ""
                                color: Theme.textMute
                                font.family: Theme.monoFont
                                font.pixelSize: 9
                                elide: Text.ElideMiddle
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Rectangle {
                                visible: (modelData.code || "").length > 0
                                height: 15
                                width: tcCode.implicitWidth + 9
                                radius: 3
                                color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.16)
                                anchors.verticalCenter: parent.verticalCenter
                                Text {
                                    id: tcCode
                                    anchors.centerIn: parent
                                    text: "码 " + (modelData.code || "")
                                    color: Theme.warn
                                    font.family: Theme.monoFont
                                    font.pixelSize: 9
                                }
                            }
                        }

                        MouseArea {
                            id: tcLinkMa
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            cursorShape: Qt.PointingHandCursor
                            onClicked: function (mouse) {
                                if (mouse.button === Qt.RightButton) {
                                    if ((modelData.code || "").length > 0)
                                        tcLinkMenuWithCode.popup();
                                    else
                                        tcLinkMenuNoCode.popup();
                                } else {
                                    panel.openUrl(modelData.url);
                                }
                            }
                        }

                        Menu {
                            id: tcLinkMenuWithCode
                            MenuItem {
                                text: "复制链接"
                                onTriggered: panel.copyText(modelData.url)
                            }
                            MenuItem {
                                text: "复制提取码 " + modelData.code
                                onTriggered: panel.copyCode(modelData.code, modelData.name || "")
                            }
                            MenuItem {
                                text: "在浏览器打开"
                                onTriggered: panel.openUrl(modelData.url)
                            }
                        }
                        Menu {
                            id: tcLinkMenuNoCode
                            MenuItem {
                                text: "复制链接"
                                onTriggered: panel.copyText(modelData.url)
                            }
                            MenuItem {
                                text: "在浏览器打开"
                                onTriggered: panel.openUrl(modelData.url)
                            }
                        }
                    }
                }
            }
        }
    }

    // ---------------- 简介标题 ----------------
    Item {
        id: descHead
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: topCommentBox.bottom
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.topMargin: 10
        height: 18

        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: "简介"
            color: Theme.textDim
            font.family: Theme.uiFont
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 34
            anchors.verticalCenter: parent.verticalCenter
            text: "可直接拖选文字复制"
            color: Theme.textMute
            font.family: Theme.uiFont
            font.pixelSize: 10
        }

        Rectangle {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: 40
            height: 18
            radius: 4
            color: copyDescMa.pressed ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.3)
                                      : (copyDescMa.containsMouse ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                                                                  : Theme.scrim(0.06))
            Text {
                anchors.centerIn: parent
                text: "全选复制"
                color: copyDescMa.containsMouse ? Theme.accent : Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 9
            }
            MouseArea {
                id: copyDescMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: panel.copyDesc(panel.video)
            }
        }
    }

    // ---------------- 简介正文：可滚动 + 可选中 ----------------
    Flickable {
        id: descFlick
        objectName: "dpDescFlick"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: descHead.bottom
        anchors.bottom: actionsRow.top
        anchors.leftMargin: 18
        anchors.rightMargin: 12
        anchors.topMargin: 6
        anchors.bottomMargin: 10
        clip: true
        contentWidth: width
        contentHeight: descText.paintedHeight
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            width: 12
            padding: 2
            contentItem: Rectangle {
                implicitWidth: 8
                radius: 4
                color: parent.pressed ? Theme.scrim(0.42)
                                     : (parent.hovered ? Theme.scrim(0.32)
                                                       : Theme.scrim(0.20))
                Behavior on color { ColorAnimation { duration: 110 } }
            }
        }

        // selectByMouse 让鼠标能直接拖选文字
        TextEdit {
            id: descText
            width: descFlick.width - 8
            text: panel.video.desc || "（暂无简介）"
            color: Theme.textDim
            font.family: Theme.uiFont
            font.pixelSize: 12
            wrapMode: TextEdit.WrapAnywhere
            readOnly: true
            selectByMouse: true
            persistentSelection: true
            selectionColor: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.45)
            selectedTextColor: "#ffffff"
            textFormat: TextEdit.PlainText
        }
    }

    // ---------------- 操作 ----------------
    //
    // ★ 宽度必须先扣掉 spacing 再分。以前五颗按钮的比例加起来正好是 1.0，
    //   再算上 4 个 8px 的 spacing 就超出容器 32px —— 最后那颗「三连」
    //   被挤到面板外面看不见（用户报的「三连按钮 UI 有问题」）。
    //   现在用 (width - spacing*4) 作基数分配。
    //
    // 顺序：播放 / 分享 / 三连 / 复制链接 / 浏览器。
    // 「三连」紧跟「分享」后面（用户要求）：它和分享一样是「对创作者好」的动作，
    // 放在分享右边一眼就能看到；复制链接、浏览器这类搬运动作排在更右边。
    //
    // 五颗按钮等宽（各 0.2，加起来正好 1.0）：以前比例是
    // 0.20/0.17/0.22/0.21/0.20，宽窄不一，「分享」被压得比别的窄一截，
    // 看起来像没对齐。现在统一，「复制链接」那四个字也放得下
    // （每颗约 82px，内部给文字留 58px，12px 字号四个汉字约 48px）。
    //
    // ★ 三连在**未登录时也必须可点**：点下去要提示登录并弹二维码。
    //   以前这里写了 enabledBtn: core.biliLoggedIn，而 ActionButton 的
    //   MouseArea 是 `enabled: enabledBtn` —— 未登录时点击事件根本不会到达
    //   onClicked，那条 needLogin 分支等于永远走不到（用户点了没反应）。
    //   所以「能不能点」只跟有没有 bvid 有关，「是不是强调色」才跟登录态有关。
    Row {
        id: actionsRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.bottomMargin: 14
        height: 38
        spacing: 8

        // 可用宽度：总宽减去 4 个间隔
        readonly property real avail: Math.max(0, width - spacing * 4)

        ActionButton {
            objectName: "playButton"
            label: "播放"
            glyph: ""
            width: actionsRow.avail * 0.2
            height: 38
            onClicked: panel.playVideo(panel.video.bvid || "")
        }
        // 这里原来还有一颗「下载」按钮（排进下载队列）。用户反馈：
        // 五个按钮挤在一行，把「内置播放 / 分享 / 复制链接 / 浏览器」都压窄了。
        // 视频下载本来也不是这个面板的核心动作（真要下可以去下载页/浏览器），
        // 所以整颗去掉。
        ActionButton {
            objectName: "shareButton"
            label: "分享"
            glyph: ""
            width: actionsRow.avail * 0.2
            height: 38
            onClicked: panel.shareVideo(panel.video || ({}))
        }
        // 「三连」：给 UP 主点赞 / 投币 / 收藏（按设置里的开关）。
        // 已登录时用强调色；未登录时保持普通样式但**照样可点**，
        // 点下去由主窗口提示登录并直接弹二维码（见 needLogin）。
        ActionButton {
            objectName: "tripleButton"
            label: "三连"
            glyph: ""
            accent: core.biliLoggedIn
            enabledBtn: (panel.video.bvid || "").length > 0
            width: actionsRow.avail * 0.2
            height: 38
            onClicked: {
                if (!core.biliLoggedIn) {
                    panel.needLogin();
                    return;
                }
                panel.triple(panel.video.bvid || "");
            }
        }
        ActionButton {
            objectName: "copyLinkButton"
            label: "复制链接"
            glyph: ""
            accent: false
            width: actionsRow.avail * 0.2
            height: 38
            onClicked: panel.copyLink(panel.video.bvid || "")
        }
        ActionButton {
            objectName: "browserButton"
            label: "浏览器"
            glyph: ""
            accent: false
            width: actionsRow.avail * 0.2
            height: 38
            onClicked: panel.openUrl("https://www.bilibili.com/video/" + (panel.video.bvid || ""))
        }
    }
}
