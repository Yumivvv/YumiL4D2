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
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Window
import L4D2
import "components"

Window {
    id: win
    width: 1320
    height: 880
    minimumWidth: 1040
    minimumHeight: 640
    visible: true
    title: "Yumi的L4D2工具箱"
    color: "transparent"
    // 无边框窗口要显式带上「可最小化/可最大化」的 hint，否则 Windows 的任务栏
    // 不知道这个窗口能不能最小化 —— 点了任务栏图标会「没反应」（用户报的）。
    // 只写 FramelessWindowHint 时，系统把它当成一个不可最小化的工具窗。
    flags: Qt.Window
           | Qt.FramelessWindowHint
           | Qt.WindowMinimizeButtonHint
           | Qt.WindowMaximizeButtonHint
           | Qt.WindowSystemMenuHint
           | Qt.WindowCloseButtonHint

    property int section: 0       // 0=视频监控 1=MOD 管理器
    property int page: 0          // 0=全部 1=新视频
    property bool maximized: false
    property var detailVideo: ({})
    property bool detailLoading: false
    property bool detailOpen: false
    property bool playerOpen: false
    property var pendingNew: []
    property bool authorOpen: false
    property bool authorLoading: false
    property var authorInfo: ({})

    // 服务器配置导入：选完文件先存路径 + 预览结果，等用户确认再真导
    property string srvImportPath: ""
    property var srvImportInfo: ({})

    // 剪贴板里检测到服务器地址时，弹一次「要不要一键导入」的确认框。
    // clipInfo 是 core.servers.scanClipboard() 的返回值（含解析出的地址）。
    property bool clipAskOpen: false
    property var clipInfo: ({})

    // ------------------------------------------------ 剪贴板里的服务器地址
    // 有人把服务器地址发给你（微信/QQ/论坛），你复制了一下 —— 现在不用再去
    // 「从文字导入」里粘一遍，回到窗口就主动问一句。
    //
    // ★ 触发条件是「**有新的复制动作**」，不是「剪贴板里有地址」。
    //   程序启动时剪贴板里本来躺着的东西（可能是昨天复制的、甚至是这段代码）
    //   不算数 —— 后端 scanClipboard 第一次调用只记基线，返回 changed=false。
    //   所以开软件不会弹，只有你在别处真的复制了新东西再切回来才弹。
    //
    // 其余三个约束：
    //   · 只在**程序窗口自己获得焦点**时问（onActiveChanged + 低频兜底）
    //   · 同一段文字只问一次（处理完调 noteClipboardHandled 对齐计数）
    //   · 弹着别的东西（播放器/详情/设置/别的弹窗）时不插队，等下次再说
    property bool clipPending: false       // 有「新复制但还没问」的内容等着

    function checkClipboardServers() {
        if (!core || !core.servers)
            return
        if (!core.clipboardServers)
            return
        // ★ 这里**不再**用 win.active 当硬门槛。
        //   之前写的是 `if (!win.active) return`，结果「从托盘唤起 / 窗口名以上是
        //   前台但系统没给焦点 / 远程桌面」这些情况下 active 一直是 false，
        //   用户复制完切回来永远等不到提示（就是这次报的 bug）。
        //   active 只在**触发时机**上起作用（onActiveChanged 会重查一次），
        //   真正该挡的是「有模态框挡着」，那由下面这一段负责。
        if (clipAskOpen || srvImportConfirm.opened
                || win.playerOpen || win.authorOpen || win.detailOpen
                || win.section === 5) {
            // 有东西挡着：先记着，等它关掉再问（见下面几个 on*Changed）
            clipPending = true
            return
        }
        var info = core.servers.scanClipboard()
        if (!info || info.changed !== true)
            return
        clipPending = false
        if ((info.total || 0) <= 0) {
            // 新复制的内容里根本没有服务器地址 —— 安静记成已处理
            core.servers.noteClipboardHandled()
            return
        }
        // ★ 全是重复的就不打扰。
        //   复制一段分享文本、里面那台本来就在收藏里，没有任何可做的事
        //   （`fresh == 0` 时「一键导入」是灰的、点了也只是关框），
        //   弹出来只会打扰人。用户明确要求这种情况**不要提示**。
        //   注意仍然要调 noteClipboardHandled()，否则后端还记着「有新复制没消费」，
        //   下次焦点一变又走一遍这段逻辑。
        if ((info.fresh || 0) <= 0) {
            core.servers.noteClipboardHandled()
            return
        }
        clipInfo = info
        clipAskOpen = true
    }

    // 窗口重新获得焦点时查一次（用户从微信切回来就是这个时机）
    onActiveChanged: {
        if (active && core.clipboardServers)
            clipCheckTimer.restart()
    }

    Timer {
        id: clipCheckTimer
        interval: 450           // 等窗口自己安顿下来，避免和切页/弹窗打架
        repeat: false
        onTriggered: win.checkClipboardServers()
    }

    // 窗口一直在前台、用户在别的程序里复制完又切回来，靠 onActiveChanged；
    // 但「一直停在窗口里、用手机扫码/另一台机器复制」这种收不到焦点变化，
    // 所以再挂一个低频轮询兜底（30 秒一次，只是读一下剪贴板文本）。
    // 注意它同样只认「有新复制动作」，不会因为剪贴板里本来就有地址就一直弹。
    // 这里也不看 win.active —— 见 checkClipboardServers 里的说明。
    Timer {
        id: clipPollTimer
        interval: 30000
        repeat: true
        running: core.clipboardServers
        onTriggered: win.checkClipboardServers()
    }

    // 右上角那组窗口按钮占的宽度（最小化+最大化+关闭 + 间距 + 右边距）。
    // 各页头右侧的内容要按这个留白，否则会和按钮叠在一起
    // （上一版「只看新的」开关就正好被压在按钮底下）。
    readonly property int winButtonsReserve: 150

    // 切页 / 切到 MOD / 打开设置时，详情面板一律收起，避免和别的东西堆在一起
    onSectionChanged: {
        closeDetail();
        // 从设置页（section 5）退出来时，把被它挡住的剪贴板询问补上
        if (section !== 5 && clipPending)
            clipRetry.restart();
    }
    onPageChanged: closeDetail()

    // 有「新复制但刚才被挡住没问」的内容时，挡路的东西一关掉就补问一次。
    // 只挂在这几个最常见的出口上 —— 漏掉也不会丢，30 秒兜底轮询还会再看一眼。
    onPlayerOpenChanged: if (!playerOpen) clipRetry.restart()
    onDetailOpenChanged: if (!detailOpen) clipRetry.restart()
    onAuthorOpenChanged: if (!authorOpen) clipRetry.restart()
    onClipAskOpenChanged: if (!clipAskOpen && clipPending) clipRetry.restart()

    Timer {
        id: clipRetry
        interval: 600
        repeat: false
        onTriggered: {
            // 同样不看 win.active（托盘唤起 / 远程桌面时它可能是 false）
            if (win.clipPending)
                win.checkClipboardServers();
        }
    }

    // ---------------------------------------------------------------- 外框
    Rectangle {
        id: frame
        anchors.fill: parent
        radius: win.maximized ? 0 : 14
        color: Theme.bg
        border.width: 1
        border.color: Theme.scrim(0.08)
        clip: true

        // 背景氛围光（跟着明暗走：夜深深色 / 日间浅色）
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: Theme.bgGradTop }
                GradientStop { position: 0.45; color: Theme.bgGradMid }
                GradientStop { position: 1.0; color: Theme.bgGradBottom }
            }
        }

        // 自定义背景图：铺满窗口，透明度走设置里的滑块。
        // 放在渐变上面、氛围光和内容下面，所以内容面板的底色还压得住文字。
        //
        // ★ sourceSize 必须**固定**，不能绑 width/height ——
        //   拖动窗口边框时 width/height 每一帧都在变，绑上去就等于每一帧都要求
        //   「按新尺寸重新解码这张图」。异步解码需要时间，这期间 Image 是空的，
        //   于是背景图一闪一闪（就是用户报的「调节窗口大小背景图闪烁」）。
        //   现在按屏幕尺寸一次性算好，窗口怎么拖都不重新解码。
        Image {
            id: bgImage
            objectName: "bgImageLayer"
            readonly property int decodeW: Math.max(1280, Math.round(Screen.width))
            readonly property int decodeH: Math.max(720, Math.round(Screen.height))

            anchors.fill: parent
            source: core.bgImageUrl
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: true
            // 解码后一直留着，切走/收起时不用重新解一遍
            retainWhileLoading: true
            smooth: true
            sourceSize.width: decodeW
            sourceSize.height: decodeH
            visible: core.bgOn && core.bgImageUrl.length > 0 && core.bgOpacity > 0
            // 图还没解码好时先隐藏，避免「白闪一下再出图」
            opacity: (status === Image.Ready ? 1 : 0) * (core.bgOpacity / 100)
            Behavior on opacity { NumberAnimation { duration: 180 } }
        }

        // 氛围光：深色主题下是「暗暗发光」，浅色主题下必须调淡，
        // 否则淡粉大圆糊在白底上会显得脏。
        Rectangle {
            width: 620
            height: 620
            radius: 310
            x: -180
            y: 120
            color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b,
                           Theme.dark ? 0.055 : 0.035)
            opacity: Theme.dark ? 0.9 : 0.75
        }
        Rectangle {
            width: 520
            height: 520
            radius: 260
            x: parent.width - 300
            y: -220
            color: Qt.rgba(Theme.pink.r, Theme.pink.g, Theme.pink.b,
                           Theme.dark ? 0.05 : 0.028)
        }

        RowLayout {
            anchors.fill: parent
            spacing: 0
            // ======================================================== 侧边栏
            Item {
                Layout.preferredWidth: 224
                Layout.fillHeight: true

                // 侧边栏底色：深色主题下压暗一层，浅色主题下提亮一层
                // （原来固定 rgba(0,0,0,0.28)，浅色主题里会变成一块灰，很脏）
                Rectangle {
                    anchors.fill: parent
                    color: Theme.dark ? Qt.rgba(0, 0, 0, 0.28)
                                      : Qt.rgba(255, 255, 255, 0.55)
                    border.width: 0
                }
                Rectangle {
                    width: 1
                    height: parent.height
                    anchors.right: parent.right
                    color: Theme.scrim(0.055)
                }

                Column {
                    anchors.fill: parent
                    anchors.topMargin: 26
                    anchors.bottomMargin: 20
                    anchors.leftMargin: 18
                    anchors.rightMargin: 16
                    spacing: 6

                    // ---- 品牌 ----
                    Row {
                        spacing: 11
                        // 应用图标（assets/appLogo.png，和窗口/任务栏/exe 是同一张图），
                        // 圆角裁切跟原来的色块徽标一致
                        Rectangle {
                            width: 40; height: 40; radius: 12
                            color: Theme.scrim(0.06)
                            clip: true
                            Image {
                                objectName: "brandLogo"
                                anchors.fill: parent
                                source: core.logoUrl
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                cache: true
                                smooth: true
                                sourceSize.width: 80
                                sourceSize.height: 80
                            }
                            Text {
                                visible: core.logoUrl.length === 0
                                anchors.centerIn: parent
                                text: "Y"
                                color: "#ffffff"
                                font.family: Theme.uiFont
                                font.pixelSize: 18
                                font.weight: Font.Black
                            }
                        }
                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 1
                            Text {
                                text: "Yumi的L4D2工具箱"
                                color: Theme.text
                                font.family: Theme.uiFont
                                font.pixelSize: 14
                                font.weight: Font.Bold
                            }
                        }
                    }

                    Item { width: 1; height: 18 }

                    Text {
                        text: "视频"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        font.letterSpacing: 1.2
                        leftPadding: 8
                    }

                    Item { width: 1; height: 4 }

                    // ---- 导航项 ----
                    Repeater {
                        model: [
                            { label: "全部视频", icon: "\uE8FD", count: core.totalCount, page: 0 },
                            { label: "新视频", icon: "\uEA8F", count: core.newCount, page: 1 }
                        ]
                        delegate: Item {
                            width: parent.width
                            height: 40
                            property bool current: win.section === 0 && win.page === modelData.page
                            property bool hov: navMa.containsMouse

                            Rectangle {
                                anchors.fill: parent
                                radius: Theme.radiusS
                                color: current ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.14)
                                               : (hov ? Theme.scrim(0.05) : "transparent")
                                border.width: current ? 1 : 0
                                border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.30)

                                Rectangle {
                                    width: 3
                                    height: 18
                                    radius: 2
                                    anchors.left: parent.left
                                    anchors.leftMargin: -1
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: current
                                    color: Theme.accent
                                }
                            }

                            Row {
                                anchors.left: parent.left
                                anchors.leftMargin: 14
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 10
                                Text {
                                    text: modelData.icon
                                    font.family: Theme.iconFont
                                    font.pixelSize: 14
                                    color: current ? Theme.accent : Theme.textDim
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: modelData.label
                                    font.family: Theme.uiFont
                                    font.pixelSize: 13
                                    font.weight: current ? Font.DemiBold : Font.Normal
                                    color: current ? Theme.text : Theme.textDim
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }

                            Rectangle {
                                visible: modelData.count > 0
                                anchors.right: parent.right
                                anchors.rightMargin: 12
                                anchors.verticalCenter: parent.verticalCenter
                                height: 19
                                width: Math.max(19, cntTxt.implicitWidth + 12)
                                radius: 9.5
                                color: modelData.page === 1
                                       ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.9)
                                       : Theme.scrim(0.09)
                                Text {
                                    id: cntTxt
                                    anchors.centerIn: parent
                                    text: modelData.count > 999 ? "999+" : modelData.count
                                    color: modelData.page === 1 ? "#ffffff" : Theme.textDim
                                    font.family: Theme.monoFont
                                    font.pixelSize: 10
                                    font.weight: Font.Bold
                                }
                            }

                            MouseArea {
                                id: navMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    // 从 MOD 页点回来时要切回视频区，否则页面不变
                                    win.section = 0;
                                    win.page = modelData.page;
                                    core.setShowOnlyNew(modelData.page === 1);
                                }
                            }
                        }
                    }

                    Item { width: 1; height: 14 }

                    Text {
                        text: "MOD"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        font.letterSpacing: 1.2
                        leftPadding: 8
                    }

                    Item { width: 1; height: 4 }

                    // ---- MOD 管理器入口 ----
                    Item {
                        id: modNavItem
                        width: parent.width
                        height: 40
                        property bool current: win.section === 1
                        property bool hov: modMa.containsMouse

                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusS
                            color: modNavItem.current ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.14)
                                                      : (modNavItem.hov ? Theme.scrim(0.05) : "transparent")
                            border.width: modNavItem.current ? 1 : 0
                            border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.30)

                            Rectangle {
                                width: 3
                                height: 18
                                radius: 2
                                anchors.left: parent.left
                                anchors.leftMargin: -1
                                anchors.verticalCenter: parent.verticalCenter
                                visible: modNavItem.current
                                color: Theme.accent
                            }
                        }

                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 10
                            Text {
                                text: "\uE7B8"
                                font.family: Theme.iconFont
                                font.pixelSize: 14
                                color: modNavItem.current ? Theme.accent : Theme.textDim
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: "MOD 管理器"
                                font.family: Theme.uiFont
                                font.pixelSize: 13
                                font.weight: modNavItem.current ? Font.DemiBold : Font.Normal
                                color: modNavItem.current ? Theme.text : Theme.textDim
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }

                        Rectangle {
                            visible: core.mods.totalCount > 0
                            anchors.right: parent.right
                            anchors.rightMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            height: 19
                            width: Math.max(19, modCntTxt.implicitWidth + 12)
                            radius: 9.5
                            color: Theme.scrim(0.09)
                            Text {
                                id: modCntTxt
                                anchors.centerIn: parent
                                text: core.mods.totalCount > 999 ? "999+" : core.mods.totalCount
                                color: Theme.textDim
                                font.family: Theme.monoFont
                                font.pixelSize: 10
                                font.weight: Font.Bold
                            }
                        }

                        MouseArea {
                            id: modMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: win.section = 1
                        }
                    }

                    // ---- 创意工坊入口（浏览 / 下载 MOD）
                    Item {
                        id: wsNavItem
                        width: parent.width
                        height: 40
                        property bool current: win.section === 2
                        property bool hov: wsMa.containsMouse

                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusS
                            color: wsNavItem.current
                                   ? Qt.rgba(Theme.accent.r, Theme.accent.g,
                                             Theme.accent.b, 0.14)
                                   : (wsNavItem.hov ? Theme.scrim(0.05) : "transparent")
                            border.width: wsNavItem.current ? 1 : 0
                            border.color: Qt.rgba(Theme.accent.r, Theme.accent.g,
                                                  Theme.accent.b, 0.30)

                            Rectangle {
                                width: 3
                                height: 18
                                radius: 2
                                anchors.left: parent.left
                                anchors.leftMargin: -1
                                anchors.verticalCenter: parent.verticalCenter
                                visible: wsNavItem.current
                                color: Theme.accent
                            }
                        }

                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 10
                            Text {
                                text: "\uE774"
                                font.family: Theme.iconFont
                                font.pixelSize: 14
                                color: wsNavItem.current ? Theme.accent : Theme.textDim
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: "创意工坊"
                                font.family: Theme.uiFont
                                font.pixelSize: 13
                                font.weight: wsNavItem.current ? Font.DemiBold
                                                               : Font.Normal
                                color: wsNavItem.current ? Theme.text : Theme.textDim
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }

                        MouseArea {
                            id: wsMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: win.section = 2
                        }
                    }

                    // ---- 服务器（收藏 + 实时状态）
                    Item {
                        id: srvNavItem
                        width: parent.width
                        height: 40
                        property bool current: win.section === 3
                        property bool hov: srvMa.containsMouse

                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusS
                            color: srvNavItem.current
                                   ? Qt.rgba(Theme.accent.r, Theme.accent.g,
                                             Theme.accent.b, 0.14)
                                   : (srvNavItem.hov ? Theme.scrim(0.05) : "transparent")
                            border.width: srvNavItem.current ? 1 : 0
                            border.color: Qt.rgba(Theme.accent.r, Theme.accent.g,
                                                  Theme.accent.b, 0.30)

                            Rectangle {
                                width: 3
                                height: 18
                                radius: 2
                                anchors.left: parent.left
                                anchors.leftMargin: -1
                                anchors.verticalCenter: parent.verticalCenter
                                visible: srvNavItem.current
                                color: Theme.accent
                            }
                        }

                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 10
                            Text {
                                text: "\uE968"
                                font.family: Theme.iconFont
                                font.pixelSize: 14
                                color: srvNavItem.current ? Theme.accent : Theme.textDim
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: "服务器"
                                font.family: Theme.uiFont
                                font.pixelSize: 13
                                font.weight: srvNavItem.current ? Font.DemiBold
                                                                : Font.Normal
                                color: srvNavItem.current ? Theme.text : Theme.textDim
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }

                        Rectangle {
                            visible: core.servers.serverCount > 0
                            anchors.right: parent.right
                            anchors.rightMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            height: 19
                            width: Math.max(19, srvCntTxt.implicitWidth + 12)
                            radius: 9.5
                            color: core.servers.onlineCount > 0
                                   ? Qt.rgba(0.25, 0.75, 0.43, 0.18)
                                   : Theme.scrim(0.09)
                            Text {
                                id: srvCntTxt
                                anchors.centerIn: parent
                                text: core.servers.onlineCount + "/" + core.servers.serverCount
                                color: core.servers.onlineCount > 0 ? "#3FBF6E" : Theme.textDim
                                font.family: Theme.monoFont
                                font.pixelSize: 9
                                font.weight: Font.Bold
                            }
                        }

                        MouseArea {
                            id: srvMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: win.section = 3
                        }
                    }

                    Item { width: 1; height: 14 }

                    Text {
                        text: "设置"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                        font.letterSpacing: 1.2
                        leftPadding: 8
                    }

                    Item { width: 1; height: 4 }

                    Item {
                        id: settingsNavItem
                        width: parent.width
                        height: 40
                        property bool hov: setMa.containsMouse
                        // 设置现在是普通一页（section 5），高亮看 section
                        property bool current: win.section === 5
                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusS
                            color: (settingsNavItem.current || setMa.containsMouse)
                                   ? Theme.scrim(0.055) : "transparent"
                        }
                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 10
                            Text {
                                text: "\uE713"
                                font.family: Theme.iconFont
                                font.pixelSize: 14
                                color: settingsNavItem.current ? Theme.accent : Theme.textDim
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: "设置"
                                font.family: Theme.uiFont
                                font.pixelSize: 13
                                color: settingsNavItem.current ? Theme.text : Theme.textDim
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        MouseArea {
                            id: setMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            // 设置是普通一页：点一下切过去，再点一下回视频页
                            onClicked: win.section = (win.section === 5 ? 0 : 5)
                        }
                    }

                    Item { width: 1; height: 1; Layout.fillHeight: true }

                    // ---- 下载入口（左下角，设置下面）----
                    // 做成图标 + 文字一条，旁边挂「进行中数量」角标；
                    // 有任务在跑时整条泛强调色，扫一眼就知道后台还在动。
                    Item {
                        id: dlNavItem
                        objectName: "dlNavItem"
                        width: parent.width
                        height: 40
                        property bool current: win.section === 4
                        property bool hov: dlMa.containsMouse
                        readonly property int activeN: core.downloads.activeCount

                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusS
                            color: dlNavItem.current
                                   ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.14)
                                   : (dlNavItem.hov ? Theme.scrim(0.05) : "transparent")
                            border.width: dlNavItem.current ? 1 : 0
                            border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.30)

                            Rectangle {
                                width: 3
                                height: 18
                                radius: 2
                                anchors.left: parent.left
                                anchors.leftMargin: -1
                                anchors.verticalCenter: parent.verticalCenter
                                visible: dlNavItem.current
                                color: Theme.accent
                            }
                        }

                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 10

                            // 有下载在跑时图标轻轻呼吸，表示还在动
                            Text {
                                text: "\uE896"
                                font.family: Theme.iconFont
                                font.pixelSize: 14
                                color: dlNavItem.current || dlNavItem.activeN > 0
                                       ? Theme.accent : Theme.textDim
                                anchors.verticalCenter: parent.verticalCenter
                                SequentialAnimation on opacity {
                                    running: dlNavItem.activeN > 0 && !dlNavItem.current
                                    loops: Animation.Infinite
                                    NumberAnimation { from: 1; to: 0.4; duration: 800; easing.type: Easing.InOutSine }
                                    NumberAnimation { from: 0.4; to: 1; duration: 800; easing.type: Easing.InOutSine }
                                }
                            }
                            Text {
                                text: "下载"
                                font.family: Theme.uiFont
                                font.pixelSize: 13
                                font.weight: dlNavItem.current ? Font.DemiBold : Font.Normal
                                color: dlNavItem.current ? Theme.text : Theme.textDim
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }

                        // 角标：进行中优先显示数量，没有进行中就显示总数
                        Rectangle {
                            visible: dlNavItem.activeN > 0 || core.downloads.totalCount > 0
                            anchors.right: parent.right
                            anchors.rightMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            height: 19
                            width: Math.max(19, dlCntTxt.implicitWidth + 12)
                            radius: 9.5
                            color: dlNavItem.activeN > 0
                                   ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.9)
                                   : Theme.scrim(0.09)
                            Text {
                                id: dlCntTxt
                                anchors.centerIn: parent
                                text: dlNavItem.activeN > 0 ? dlNavItem.activeN
                                                            : core.downloads.totalCount
                                color: dlNavItem.activeN > 0 ? "#ffffff" : Theme.textDim
                                font.family: Theme.monoFont
                                font.pixelSize: 10
                                font.weight: Font.Bold
                            }
                        }

                        MouseArea {
                            id: dlMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: win.section = 4
                        }
                    }

                    // ---- 启动游戏（左下角，播放图标）----
                    // 从 MOD 管理器的工具条搬过来的：启动游戏是全局动作，
                    // 不该只在 MOD 页出现；那边它还把「检查 MOD 文件 / 刷新」挤窄了。
                    // 做成一颗大一点的图标按钮（播放键），旁边写一行小字说明。
                    Item {
                        id: launchNavItem
                        objectName: "launchGameBtn"
                        width: parent.width
                        height: 44
                        property bool hov: launchMa.containsMouse
                        property bool busy: core.mods.busy

                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusS
                            // 播放键用强调色实心，和「下载」那种列表项区分开：
                            // 这是个「按一下就发生事情」的动作，不是导航。
                            color: launchMa.pressed
                                   ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.28)
                                   : (launchMa.containsMouse
                                      ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                                      : Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.10))
                            border.width: 1
                            border.color: Qt.rgba(Theme.accent.r, Theme.accent.g,
                                                  Theme.accent.b, launchNavItem.hov ? 0.55 : 0.30)
                            Behavior on color { ColorAnimation { duration: 100 } }
                        }

                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 10
                            // 播放三角
                            Text {
                                text: "\uE768"
                                font.family: Theme.iconFont
                                font.pixelSize: 15
                                color: Theme.accent
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: "启动游戏"
                                font.family: Theme.uiFont
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                                color: Theme.text
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }

                        MouseArea {
                            id: launchMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: core.mods.launchGame()
                            ToolTip.visible: containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "启动《求生之路2》"
                        }
                    }

                    Item {
                        width: parent.width
                        height: 8
                        // 窗口矮的时候这一格让位：640 高时侧栏本来就紧，
                        // 再加固定 8px 会把底下的监控卡片顶出可视区（实测过）。
                        visible: win.height > 720
                    }

                    // ---- 底部监控卡片 ----
                    // 窗口很矮时整张卡片收起来（见下面的 visible）：它是「参考信息」，
                    // 而下载入口是「要点的东西」，优先级比它高。
                    Rectangle {
                        width: parent.width
                        height: 92
                        visible: win.height > 720
                        radius: Theme.radius
                        color: Theme.scrim(0.035)
                        border.width: 1
                        border.color: Theme.scrim(0.06)

                        Column {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 8

                            Row {
                                spacing: 7
                                Rectangle {
                                    width: 8; height: 8; radius: 4
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: core.monitoring ? Theme.ok : Theme.textMute
                                    SequentialAnimation on opacity {
                                        running: core.monitoring
                                        loops: Animation.Infinite
                                        NumberAnimation { from: 1; to: 0.25; duration: 900; easing.type: Easing.InOutSine }
                                        NumberAnimation { from: 0.25; to: 1; duration: 900; easing.type: Easing.InOutSine }
                                    }
                                }
                                Text {
                                    text: core.monitoring ? "自动刷新中" : "自动刷新已暂停"
                                    color: core.monitoring ? Theme.ok : Theme.textMute
                                    font.family: Theme.uiFont
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }

                            Text {
                                width: parent.width
                                text: core.lastCheckText
                                color: Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                                elide: Text.ElideRight
                            }

                            ToggleSwitch {
                                checked: core.monitoring
                                onToggled: function (v) { v ? core.start_monitor() : core.stop_monitor(); }
                            }
                        }
                    }
                }
            }

            // ======================================================== 主区域
            Item {
                id: mainArea
                Layout.fillWidth: true
                Layout.fillHeight: true
                // 设置页是这一层上的独立一页：它显示时把主区域整体收起来，
                // 免得底下的视频/MOD/工坊页还在接事件（滚动会串）。
                visible: win.section !== 5

                // ---------------- 视频监控页 ----------------
                Column {
                    anchors.fill: parent
                    spacing: 0
                    visible: win.section === 0
                    opacity: win.section === 0 ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 140 } }

                    // ------------------------------------------------ 标题栏
                    Item {
                        id: headerBar
                        width: parent.width
                        height: 68

                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton
                            onPressed: win.startSystemMove()
                            onDoubleClicked: win.toggleMaximized()
                        }

                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 24
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 10

                            Text {
                                text: win.page === 1 ? "新视频" : "全部视频"
                                color: Theme.text
                                font.family: Theme.uiFont
                                font.pixelSize: 19
                                font.weight: Font.Bold
                                anchors.verticalCenter: parent.verticalCenter
                            }

                            Rectangle {
                                height: 22
                                width: kwTxt.implicitWidth + 20
                                radius: 11
                                color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.13)
                                border.width: 1
                                border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.28)
                                anchors.verticalCenter: parent.verticalCenter
                                Text {
                                    id: kwTxt
                                    anchors.centerIn: parent
                                    text: core.keyword
                                    color: Theme.accent
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        win.section = 5;
                                        keywordEdit.forceActiveFocus();
                                    }
                                }
                            }

                            Text {
                                text: core.busy ? "正在扫描…" : core.statusText
                                color: core.busy ? Theme.warn : Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 12
                                anchors.verticalCenter: parent.verticalCenter
                                elide: Text.ElideRight
                                width: Math.min(implicitWidth, 320)
                            }
                        }

                        Row {
                            anchors.right: parent.right
                            // 右上角是全局窗口按钮，这里必须让开，否则「刷新 / 标已读 /
                            // 自动」三个按钮会被压在最小化最大化关闭底下。
                            anchors.rightMargin: 12 + win.winButtonsReserve
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 6

                            IconButton {
                                glyph: "\uE72C"
                                tip: "立即检查新视频 (F5)"
                                active: core.busy
                                boxSize: 34
                                onClicked: core.scan_now()
                            }
                            IconButton {
                                glyph: "\uE73E"
                                tip: "全部标为已读"
                                boxSize: 34
                                enabled: core.newCount > 0
                                opacity: core.newCount > 0 ? 1 : 0.35
                                onClicked: core.markAllSeen()
                            }
                            // 自动刷新的开关：用文字按钮，暂停/播放的图标字体在这个字号下会渲染成方框
                            Item {
                                width: 44
                                height: 34
                                Rectangle {
                                    anchors.centerIn: parent
                                    width: 44
                                    height: 28
                                    radius: 8
                                    color: core.monitoring
                                           ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, monMa.pressed ? 0.26 : 0.16)
                                           : (monMa.pressed ? Theme.scrim(0.11)
                                                            : (monMa.containsMouse ? Theme.scrim(0.07)
                                                                                   : Theme.scrim(0.04)))
                                    border.width: 1
                                    border.color: core.monitoring
                                                  ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.45)
                                                  : Theme.border
                                    Behavior on color { ColorAnimation { duration: 90 } }
                                    Text {
                                        anchors.centerIn: parent
                                        text: core.monitoring ? "暂停" : "自动"
                                        color: core.monitoring ? Theme.text : Theme.textDim
                                        font.family: Theme.uiFont
                                        font.pixelSize: 11
                                    }
                                }
                                MouseArea {
                                    id: monMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: core.toggleMonitor()
                                    ToolTip.visible: containsMouse
                                    ToolTip.text: core.monitoring ? "暂停自动刷新" : "开启自动刷新"
                                    ToolTip.delay: 500
                                }
                            }
                            Item { width: 8; height: 1 }
                            // 窗口按钮由 WindowButtons 统一提供（窗口右上角那一份），
                            // 这里不再各写一套 —— 否则每个页面的按钮位置/样式会各自漂移。
                        }
                    }

                    // ------------------------------------------------ 工具条
                    Item {
                        width: parent.width
                        height: 56

                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 24
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 9

                            SearchBox {
                                width: 300
                                placeholder: "在已获取的视频里搜索标题 / UP主 / 标签…"
                                onEdited: function (v) { core.setFilterText(v); }
                            }

                            Item { width: 6; height: 1 }

                            // 视频筛选按钮（排序 + 日期筛选都在弹出的面板里）
                            Rectangle {
                                id: vidFilterBtn
                                width: 86
                                height: 30
                                radius: Theme.radiusXS
                                color: vidFilterMa.pressed
                                       ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.28)
                                       : (core.sortMode !== "pubdate" || core.dateFilter !== 0
                                          ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.14)
                                          : (vidFilterMa.containsMouse ? Theme.scrim(0.08) : Theme.scrim(0.04)))
                                border.width: 1
                                border.color: (core.sortMode !== "pubdate" || core.dateFilter !== 0)
                                              ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.5)
                                              : Theme.border
                                Behavior on color { ColorAnimation { duration: 90 } }

                                Row {
                                    anchors.centerIn: parent
                                    spacing: 4
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: (core.sortMode !== "pubdate" || core.dateFilter !== 0) ? "筛选 ·" : "筛选"
                                        color: (core.sortMode !== "pubdate" || core.dateFilter !== 0) ? Theme.accent : Theme.textDim
                                        font.family: Theme.uiFont
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: "\uE70D"
                                        font.family: Theme.iconFont
                                        font.pixelSize: 8
                                        color: Theme.textMute
                                    }
                                }
                                MouseArea {
                                    id: vidFilterMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: vidFilterPopup.opened ? vidFilterPopup.close() : vidFilterPopup.open()
                                }
                            }
                        }

                        Row {
                            anchors.right: parent.right
                            anchors.rightMargin: 22 + win.winButtonsReserve
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 10

                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: core.shownCount + " 个结果"
                                color: Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 12
                            }

                            Rectangle {
                                width: 1; height: 16
                                color: Theme.border
                                anchors.verticalCenter: parent.verticalCenter
                            }

                            Text {
                                text: "只看新的"
                                color: Theme.textDim
                                font.family: Theme.uiFont
                                font.pixelSize: 12
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            ToggleSwitch {
                                checked: core.showOnlyNew
                                anchors.verticalCenter: parent.verticalCenter
                                onToggled: function (v) {
                                    win.page = v ? 1 : 0;
                                    core.setShowOnlyNew(v);
                                }
                            }
                        }
                    }

                    // ------------------------------------------------ 列表
                    Item {
                        width: parent.width
                        height: parent.height - 68 - 56

                        ListView {
                            id: listView
                            anchors.fill: parent
                            anchors.leftMargin: 24
                            anchors.rightMargin: 24
                            anchors.bottomMargin: 12
                            clip: true
                            model: core.videoModel
                            spacing: 0
                            boundsBehavior: Flickable.StopAtBounds
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

                            delegate: VideoDelegate {
                                onClickedItem: function (bvid) { win.openDetail(bvid); }
                                onPlayItem: function (bvid) {
                                    win.playerOpen = true;
                                    core.playVideo(bvid);
                                }
                                onCopyItem: function (bvid) { core.copyLink(bvid); }
                                onSeenItem: function (bvid) { core.markSeen(bvid); }
                            }

                            add: Transition {
                                NumberAnimation { properties: "opacity"; from: 0; to: 1; duration: 220 }
                                NumberAnimation { properties: "y"; from: 12; to: 0; duration: 240; easing.type: Easing.OutCubic }
                            }

                            displaced: Transition {
                                NumberAnimation { properties: "y"; duration: 180; easing.type: Easing.OutCubic }
                            }

                            // ---------------- 空状态 ----------------
                            Text {
                                anchors.centerIn: parent
                                visible: listView.count === 0
                                horizontalAlignment: Text.AlignHCenter
                                lineHeight: 1.7
                                text: core.busy
                                      ? "正在获取数据，请稍候…"
                                      : (core.firstRun
                                         ? "还没有数据\n点左上角「刷新」抓取一次「" + core.keyword + "」的最新视频"
                                         : (core.showOnlyNew ? "暂时没有新视频，休息一下 ☕" : "没有匹配的视频"))
                                color: Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 13
                            }
                        }

                        // 列表顶部渐变遮罩，滚动时更柔和。
                        // 颜色必须跟主题背景走 —— 以前写死成深色 rgba(0.04,0.05,0.07)，
                        // 日间模式里会在列表顶上横一道黑杠（截图里红框那条）。
                        Rectangle {
                            anchors.top: parent.top
                            anchors.left: parent.left
                            anchors.right: parent.right
                            height: 14
                            gradient: Gradient {
                                orientation: Gradient.Vertical
                                GradientStop { position: 0; color: Theme.fade(0.92) }
                                GradientStop { position: 1; color: Theme.fade(0.0) }
                            }
                            visible: listView.contentY > 2
                        }

                        // ---------------- 详情滑出面板 ----------------
                        Rectangle {
                            anchors.fill: parent
                            // 压暗底：浅色主题下太重会显得闷，减一半
                            color: Qt.rgba(0, 0, 0, Theme.dark ? 0.35 : 0.16)
                            opacity: win.detailOpen ? 1 : 0
                            visible: opacity > 0.01
                            Behavior on opacity { NumberAnimation { duration: 200 } }
                            MouseArea {
                                anchors.fill: parent
                                // hoverEnabled：吃掉悬停事件，否则鼠标移到详情面板上时
                                // 底下的视频列表行还会显示悬浮样式
                                hoverEnabled: true
                                onClicked: win.closeDetail()
                            }
                        }

                        DetailPanel {
                            id: detail
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 10
                            anchors.topMargin: 2
                            anchors.right: parent.right
                            showPanel: win.detailOpen
                            video: win.detailVideo
                            links: win.detailVideo.links || []
                            loading: win.detailLoading
                            onClosed: win.closeDetail()
                            onOpenUrl: function (url) { core.openUrl(url); }
                            onCopyLink: function (bvid) { core.copyLink(bvid); }
                            onCopyText: function (text) { core.copyText(text); }
                            onCopyCode: function (code, name) { core.copyCode(code, name); }
                            onCopyDesc: function (v) { core.copyDesc(v); }
                            // 分享：标题 + 视频链接 + 网盘链接和提取码，一次复制全
                            onShareVideo: function (v) { core.shareVideo(v); }
                            // 下载视频：排进统一下载队列，进度在下载页里看
                            onDownloadVideo: function (bvid) {
                                if (!bvid)
                                    return;
                                core.downloads.addVideo(bvid);
                                win.detailOpen = false;
                            }
                            // 蓝奏云：解析直链后进下载队列（解析在后台线程做，
                            // 页面立刻返回，不会卡住详情面板）
                            onDownloadPanLink: function (link) {
                                if (!link || !link.url) {
                                    win.toast("这条网盘链接没有地址", "warn");
                                    return;
                                }
                                // ★ 一定要检查返回值并弹提示。
                                //   以前这里只调 `addPanFile(link)` 就完事，
                                //   而那个槽的签名写错了（`@Slot(str)`），
                                //   QML 传对象被强转成字符串、Python 里抛
                                //   AttributeError，被 Qt 吞掉 ——
                                //   用户看到的就是「点了什么也没有」。
                                var res = core.downloads.addPanFile(link);
                                if (res && res.ok) {
                                    win.toast("已加入下载，进度看左下角「下载」", "ok");
                                } else {
                                    win.toast((res && res.error)
                                              || "加入下载失败（原因未知）", "error");
                                }
                                win.detailOpen = false;
                            }
                            onPlayVideo: function (bvid) {
                                win.detailOpen = false;
                                win.playerOpen = true;
                                core.playVideo(bvid);
                            }
                            onOpenAuthor: function (bvid) {
                                win.authorOpen = true;
                                win.authorLoading = true;
                                win.authorInfo = core.findVideo(bvid);
                                core.openAuthor(bvid);
                            }
                        }
                    }
                }

                // ---------------- MOD 管理器页 ----------------
                Item {
                    anchors.fill: parent
                    visible: win.section === 1
                    opacity: win.section === 1 ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 140 } }

                    // 顶部标题栏（保留窗口拖动 + 窗口按钮）
                    Item {
                        id: modHeader
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: 68

                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton
                            onPressed: win.startSystemMove()
                            onDoubleClicked: win.toggleMaximized()
                        }

                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 24
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 10

                            Text {
                                text: "MOD 管理器"
                                color: Theme.text
                                font.family: Theme.uiFont
                                font.pixelSize: 19
                                font.weight: Font.Bold
                                anchors.verticalCenter: parent.verticalCenter
                            }

                            Text {
                                text: core.mods.statusText
                                color: Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 11
                                anchors.verticalCenter: parent.verticalCenter
                                elide: Text.ElideRight
                                width: Math.min(implicitWidth, 400)
                            }
                        }

                        Row {
                            anchors.right: parent.right
                            anchors.rightMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 6

                            // 窗口按钮由 WindowButtons 统一提供（窗口右上角那一份），
                            // 这里不再各写一套 —— 否则每个页面的按钮位置/样式会各自漂移。
                        }
                    }

                    // MOD 面板主体
                    ModPanel {
                        id: modPanel
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: modHeader.bottom
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 24
                        anchors.rightMargin: 24
                        anchors.bottomMargin: 16
                        onStatusMessage: function (t) { }
                    }
                }

                // ---------------- 创意工坊页 ----------------
                Item {
                    anchors.fill: parent
                    visible: win.section === 2
                    opacity: win.section === 2 ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 140 } }

                    // 顶部标题栏（保留窗口拖动 + 窗口按钮）
                    Item {
                        id: wsHeader
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: 68

                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton
                            onPressed: win.startSystemMove()
                            onDoubleClicked: win.toggleMaximized()
                        }

                        Column {
                            anchors.left: parent.left
                            anchors.leftMargin: 24
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 2

                            Row {
                                spacing: 8
                                Text {
                                    text: "创意工坊"
                                    color: Theme.text
                                    font.family: Theme.uiFont
                                    font.pixelSize: 20
                                    font.weight: Font.Bold
                                }
                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    height: 20
                                    width: wsHintTxt.implicitWidth + 16
                                    radius: 10
                                    color: Qt.rgba(Theme.accent.r, Theme.accent.g,
                                                   Theme.accent.b, 0.14)
                                    Text {
                                        id: wsHintTxt
                                        anchors.centerIn: parent
                                        text: "单 MOD / 合集"
                                        color: Theme.accent
                                        font.family: Theme.uiFont
                                        font.pixelSize: 10
                                    }
                                }
                            }
                            Text {
                                text: "粘链接或 ID 直接解析，也能下载合集"
                                color: Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                        }

                        // 窗口按钮
                        Row {
                            anchors.right: parent.right
                            anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 6

                            // 窗口按钮由 WindowButtons 统一提供（窗口右上角那一份），
                            // 这里不再各写一套 —— 否则每个页面的按钮位置/样式会各自漂移。
                        }
                    }

                    WorkshopPage {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: wsHeader.bottom
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 22
                        anchors.rightMargin: 22
                        anchors.bottomMargin: 16
                    }
                }

                // ---------------- 服务器页 ----------------
                Item {
                    anchors.fill: parent
                    visible: win.section === 3
                    opacity: win.section === 3 ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 140 } }

                    Item {
                        id: srvHeader
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: 68

                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton
                            onPressed: win.startSystemMove()
                            onDoubleClicked: win.toggleMaximized()
                        }

                        Column {
                            anchors.left: parent.left
                            anchors.leftMargin: 24
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 2

                            Row {
                                spacing: 8
                                Text {
                                    text: "服务器"
                                    color: Theme.text
                                    font.family: Theme.uiFont
                                    font.pixelSize: 20
                                    font.weight: Font.Bold
                                }
                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    height: 20
                                    width: srvHintTxt.implicitWidth + 16
                                    radius: 10
                                    color: Qt.rgba(Theme.accent.r, Theme.accent.g,
                                                   Theme.accent.b, 0.14)
                                    Text {
                                        id: srvHintTxt
                                        anchors.centerIn: parent
                                        text: "A2S 直查"
                                        color: Theme.accent
                                        font.family: Theme.uiFont
                                        font.pixelSize: 10
                                    }
                                }
                            }
                            Text {
                                text: "收藏常去的服务器，看人数、地图和模式，一键唤起 Steam 直连"
                                color: Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                        }

                        Row {
                            anchors.right: parent.right
                            anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 6

                            // 窗口按钮由 WindowButtons 统一提供（窗口右上角那一份），
                            // 这里不再各写一套 —— 否则每个页面的按钮位置/样式会各自漂移。
                        }
                    }

                    ServersPage {
                        id: serversPageItem
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: srvHeader.bottom
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 22
                        anchors.rightMargin: 22
                        anchors.bottomMargin: 16
                        // 导出 / 导入服务器配置：文件框在下面（和音效、背景图那些放一起），
                        // 这里只把请求转过去。
                        onRequestExport: srvExportDlg.open()
                        onRequestImport: srvImportDlg.open()
                    }
                }

                // ---------------- 下载页 ----------------
                // 入口在左下角那颗下载图标（和设置并排），不占侧栏正文的位置：
                // 它是个「随时想看就看」的页面，不是每天都要切的主功能。
                Item {
                    anchors.fill: parent
                    visible: win.section === 4
                    opacity: win.section === 4 ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 140 } }

                    Item {
                        id: dlHeader
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.topMargin: 28
                        anchors.leftMargin: 22
                        anchors.rightMargin: 22
                        height: 26

                        // 拖动区
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton
                            onPressed: function (mouse) {
                                if (mouse.button === Qt.LeftButton)
                                    win.startSystemMove();
                            }
                        }
                    }

                    DownloadsPage {
                        id: downloadsPageItem
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 22
                        anchors.rightMargin: 22
                        anchors.topMargin: 22
                        anchors.bottomMargin: 16
                    }

                    // 拖动区必须盖在 DownloadsPage **上面**（所以声明在它后面）。
                    // 以前它声明在前、只占 28~54px 那条，而 DownloadsPage 从 22px
                    // 就开始画、又填满整页，把那条拖动区整个盖住了 ——
                    // 表现就是「下载界面拖不动窗口」（用户报的）。
                    // 现在单独铺一条横跨页面顶部、位于页面之上的拖动带：
                    // 只吃左键拖动、不吃点击，所以页头的「清空已结束」照样能点。
                    MouseArea {
                        id: dlDragStrip
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.leftMargin: 22
                        anchors.rightMargin: win.winButtonsReserve
                        anchors.topMargin: 20
                        height: 34
                        acceptedButtons: Qt.LeftButton
                        z: 5
                        cursorShape: Qt.ArrowCursor
                        onPressed: function (mouse) {
                            if (mouse.button === Qt.LeftButton)
                                win.startSystemMove();
                        }
                        onDoubleClicked: win.toggleMaximized()
                    }
                }
            }
        }

        // ------------------------------------------------ 全局窗口按钮
        // 只放**这一份**，锚在窗口右上角，所有页面共用。
        // 以前四个页面页头各写一套（最小化 / 最大化 / 关闭），改一处要改四遍，
        // 而且各页头 rightMargin 略有差异，切页时按钮会轻微错位 ——
        // 看起来就是「每个界面的窗口按钮是独立的」（用户报的）。
        // z 要高过所有页面内容，但低于弹层（弹层是 260+）。
        WindowButtons {
            id: winButtons
            z: 200
            anchors.right: parent.right
            anchors.rightMargin: 14
            anchors.top: parent.top
            anchors.topMargin: 13
            target: win
            maximized: win.maximized
        }

        // ------------------------------------------------ 视频筛选弹层
        Item {
            id: vidFilterPopup
            parent: frame
            property bool opened: false
            function open() { opened = true; }
            function close() { opened = false; }

            visible: opened
            x: 24 + 300 + 6 + 86 + 6
            y: 68 + 56 + 4
            width: 224
            height: vidFilterCol.height + 24
            z: 260

            Rectangle {
                anchors.fill: parent
                radius: Theme.radiusS
                color: Theme.panelHi
                border.width: 1
                border.color: Theme.borderHi
            }

            Column {
                id: vidFilterCol
                x: 14
                y: 12
                width: parent.width - 28
                spacing: 11

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
                        model: [
                            { label: "最新发布", mode: "pubdate" },
                            { label: "最多播放", mode: "views" }
                        ]
                        delegate: Rectangle {
                            required property var modelData
                            width: parent.width
                            height: 26
                            radius: Theme.radiusXS
                            property bool on: core.sortMode === modelData.mode
                            color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, vsMa.pressed ? 0.26 : 0.16)
                                      : (vsMa.pressed ? Theme.scrim(0.11)
                                                      : (vsMa.containsMouse ? Theme.scrim(0.05) : "transparent"))
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.label
                                color: parent.on ? Theme.text : Theme.textDim
                                font.family: Theme.uiFont
                                font.pixelSize: 12
                            }
                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                visible: parent.on
                                text: "✓"
                                color: Theme.accent
                                font.pixelSize: 11
                            }
                            MouseArea {
                                id: vsMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: core.setSortMode(modelData.mode)
                            }
                        }
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                Text {
                    text: "日期"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }

                Column {
                    width: parent.width
                    spacing: 2
                    Repeater {
                        model: [
                            { label: "全部日期", days: 0 },
                            { label: "最近一天", days: 1 },
                            { label: "最近七天", days: 7 },
                            { label: "最近半年", days: 180 }
                        ]
                        delegate: Rectangle {
                            required property var modelData
                            width: parent.width
                            height: 26
                            radius: Theme.radiusXS
                            property bool on: core.dateFilter === modelData.days
                            color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, vdMa.pressed ? 0.26 : 0.16)
                                      : (vdMa.pressed ? Theme.scrim(0.11)
                                                      : (vdMa.containsMouse ? Theme.scrim(0.05) : "transparent"))
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.label
                                color: parent.on ? Theme.text : Theme.textDim
                                font.family: Theme.uiFont
                                font.pixelSize: 12
                            }
                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                visible: parent.on
                                text: "✓"
                                color: Theme.accent
                                font.pixelSize: 11
                            }
                            MouseArea {
                                id: vdMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: core.setDateFilter(modelData.days)
                            }
                        }
                    }
                }
            }
        }

        // 点别处关掉视频筛选面板
        MouseArea {
            id: vidFilterDismiss
            parent: frame
            anchors.fill: parent
            z: 259
            enabled: vidFilterPopup.opened
            visible: enabled
            onClicked: vidFilterPopup.close()
            onWheel: function (wheel) { wheel.accepted = true }
        }

        // ------------------------------------------------ 应用内新视频提示条
        Rectangle {
            id: newBanner
            width: 340
            height: 74
            radius: Theme.radius
            anchors.right: parent.right
            anchors.rightMargin: 20
            y: -100
            color: Theme.surfaceHi
            border.width: 1
            border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.45)
            visible: y > -80
            Behavior on y { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }

            Rectangle {
                width: 4
                height: parent.height - 18
                radius: 2
                anchors.left: parent.left
                anchors.leftMargin: 4
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.accent
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.right: parent.right
                anchors.rightMargin: 34
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3
                Text {
                    text: "发现 " + win.pendingNew.length + " 个新视频"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 13
                    font.weight: Font.Bold
                }
                Text {
                    width: parent.width
                    text: win.pendingNew.length > 0 ? (win.pendingNew[0].title || "") : ""
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.top: parent.top
                anchors.topMargin: 10
                text: "\uE711"
                font.family: Theme.iconFont
                font.pixelSize: 10
                color: closeBanner.containsMouse ? Theme.accent : Theme.textMute
                MouseArea {
                    id: closeBanner
                    anchors.fill: parent
                    anchors.margins: -6
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: newBanner.y = -100
                }
            }

            MouseArea {
                anchors.fill: parent
                anchors.rightMargin: 28
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    win.page = 1;
                    core.setShowOnlyNew(true);
                    newBanner.y = -100;
                }
            }
        }

        // ------------------------------------------------ 设置页（内嵌，不是抽屉）
        //
        // 以前设置是「右侧滑出的 430px 抽屉」，压在内容上面：改设置时看不到背后的页面，
        // 而且它和详情面板、各种弹层抢 z 序，焦点容易乱。用户要的是「设置就是普通一页」，
        // 所以现在铺满主区域、跟其它页一样靠 `win.section` 切换。
        // 侧栏那颗「设置」仍然是入口，只是现在切到 section 5（普通一页）。
        Rectangle {
            id: settingsDrawer
            // 只占**主区域**（侧栏 224 宽），别盖住侧栏 —— 设置是普通一页，
            // 侧栏得一直能点。以前它是抽屉（浮在整窗上），所以锚满整个窗口就行；
            // 改成内嵌页之后必须把侧栏那块让出来。
            //
            // 也不能和主区域里那几个页面同时显示：它们都是 anchors.fill 主区域，
            // 设置页 z 更高会盖住，但下面的视频页如果 visible 还是 true，
            // 滚动/点击事件仍会串进去。所以这一页显示时，主区域自己要收起来
            // （见下面 `mainArea.visible`）。
            anchors.left: parent.left
            anchors.leftMargin: 224
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.rightMargin: 0
            anchors.topMargin: 0
            anchors.bottomMargin: 0
            radius: 0
            z: 40
            color: "transparent"
            border.width: 0
            visible: win.section === 5
            // 进出页时淡入淡出，跟其它页一致（不再是横向滑入）
            opacity: win.section === 5 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 140 } }

            // ---------------- 滚轮防穿透 ----------------
            // 设置里全都是滚动区（长列表 + 各种下拉），鼠标滚到尽头之后
            // 事件会穿透到下面的视频/MOD 列表，把后面的列表也滚走。
            // 铺一层只吃滚轮、不吃点击的 MouseArea 兜底（同详情面板的做法）。
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.NoButton
                z: -1
                onWheel: function (wheel) { wheel.accepted = true }
            }

            Flickable {
                id: settingsFlick
                objectName: "settingsFlick"
                anchors.fill: parent
                // 内嵌页要自己留边（原来是抽屉自带的 20px）。右侧多留一点：
                // 右上角有窗口按钮，内容不要贴到它底下。
                anchors.leftMargin: 26
                anchors.rightMargin: 26
                anchors.topMargin: 24
                anchors.bottomMargin: 20
                clip: true
                contentWidth: width
                contentHeight: settingsCol.height
                boundsBehavior: Flickable.StopAtBounds

            Column {
                id: settingsCol
                objectName: "settingsCol"
                // 宽屏最多 980：以前写死 760，1080p 上右边空一大片，内容还被压得很长
                width: Math.min(980, settingsFlick.width)
                spacing: 22

                // 页标题
                // 这里以前右上角还有一颗「×」关闭按钮 —— 那是设置还是**右侧抽屉**
                // 时代的遗物（抽屉要能收起来）。现在设置是普通一页，退回上一页
                // 走侧栏或者 Esc 就够了，再挂一颗×既多余、又和窗口的关闭按钮撞脸
                // （用户报的「设置里面残留的关闭按钮」）。整颗删掉。
                Item {
                    width: parent.width
                    height: 32
                    Text {
                        text: "设置"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 19
                        font.weight: Font.Bold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 52
                        anchors.verticalCenter: parent.verticalCenter
                        text: "改完立刻生效，不用保存"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }

                // ================= ① 监控与提醒 =================
                Item {
                    width: parent.width
                    height: 34
                    Rectangle {
                        anchors.fill: parent
                        anchors.topMargin: 8
                        radius: 6
                        color: Theme.scrim(0.045)
                    }
                    Rectangle {
                        width: 3
                        height: 15
                        radius: 1.5
                        anchors.left: parent.left
                        anchors.leftMargin: 9
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.accent
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 19
                        anchors.verticalCenter: parent.verticalCenter
                        text: "① 监控与提醒"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }

                // 关键词（支持多个，结果合并到同一个列表并去重）
                Column {
                    width: parent.width
                    spacing: 7
                    Row {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: "搜索关键词"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "（多个关键词结果会合并去重）"
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    // 已有关键词标签
                    Flow {
                        width: parent.width
                        spacing: 6

                        Repeater {
                            model: core.keywords
                            delegate: Rectangle {
                                height: 26
                                width: kwLabel.implicitWidth + 34
                                radius: 13
                                color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.14)
                                border.width: 1
                                border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.35)

                                Text {
                                    id: kwLabel
                                    anchors.left: parent.left
                                    anchors.leftMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData
                                    color: Theme.accent
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                }

                                Text {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "\uE711"
                                    font.family: Theme.iconFont
                                    font.pixelSize: 8
                                    color: kwRemove.containsMouse ? "#ffffff" : Theme.accent
                                }

                                MouseArea {
                                    id: kwRemove
                                    anchors.fill: parent
                                    anchors.leftMargin: parent.width - 24
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: core.removeKeyword(modelData)
                                }
                            }
                        }
                    }

                    // 添加新关键词
                    Rectangle {
                        width: parent.width
                        height: 38
                        radius: Theme.radiusS
                        color: Theme.surfaceSoft
                        border.width: 1
                        border.color: keywordEdit.activeFocus ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.55) : Theme.border
                        TextField {
                            id: keywordEdit
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 78
                            color: Theme.text
                            font.family: Theme.uiFont
                            font.pixelSize: 13
                            background: null
                            padding: 0
                            verticalAlignment: TextInput.AlignVCenter
                            placeholderText: "输入新关键词，回车添加…"
                            placeholderTextColor: Theme.textMute
                            onAccepted: {
                                if (text.trim().length > 0) {
                                    core.addKeyword(text.trim());
                                    text = "";
                                }
                            }
                        }

                        Rectangle {
                            anchors.right: parent.right
                            anchors.rightMargin: 5
                            anchors.verticalCenter: parent.verticalCenter
                            width: 66
                            height: 28
                            radius: Theme.radiusXS
                            scale: addKwMa.pressed ? 0.94 : 1.0
                            Behavior on scale { NumberAnimation { duration: 90 } }
                            color: addKwMa.pressed ? Theme.accentDeep
                                                   : (addKwMa.containsMouse ? Theme.accent
                                                                            : Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.7))
                            Text {
                                anchors.centerIn: parent
                                text: "添加"
                                color: "#ffffff"
                                font.family: Theme.uiFont
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }
                            MouseArea {
                                id: addKwMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (keywordEdit.text.trim().length > 0) {
                                        core.addKeyword(keywordEdit.text.trim());
                                        keywordEdit.text = "";
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        text: "加完点右上角 ↻ 刷新抓一次，搜索到的新视频会并进同一个列表"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }

                // 刷新间隔
                Column {
                    width: parent.width
                    spacing: 7
                    Text {
                        text: "自动刷新间隔"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                    }
                    Row {
                        spacing: 6
                        Repeater {
                            model: [
                                { label: "5分", v: 5 }, { label: "10分", v: 10 },
                                { label: "15分", v: 15 }, { label: "30分", v: 30 },
                                { label: "1小时", v: 60 }, { label: "关", v: 0 }
                            ]
                            delegate: Item {
                                width: 52
                                height: 30
                                property bool current: (modelData.v === 0 ? !core.monitoring : (core.monitoring && core.intervalMin === modelData.v))
                                Rectangle {
                                    anchors.fill: parent
                                    radius: Theme.radiusXS
                                    scale: intMa.pressed ? 0.94 : 1.0
                                    Behavior on scale { NumberAnimation { duration: 90 } }
                                    color: intMa.pressed
                                           ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.32)
                                           : current
                                             ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                                             : (intMa.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.03))
                                    border.width: 1
                                    border.color: current ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.5)
                                                          : (intMa.containsMouse ? Theme.borderHi : Theme.border)
                                    Text {
                                        anchors.centerIn: parent
                                        text: modelData.label
                                        color: (current || intMa.containsMouse) ? Theme.accent : Theme.textDim
                                        font.family: Theme.uiFont
                                        font.pixelSize: 12
                                    }
                                }
                                MouseArea {
                                    id: intMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: core.setIntervalAndRestart(modelData.v)
                                }
                            }
                        }
                    }
                }

                // 抓取页数
                Column {
                    width: parent.width
                    spacing: 7
                    Text {
                        text: "每次抓取页数（每页约 42 个视频）"
                        color: Theme.textDim
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                    }
                    Row {
                        spacing: 6
                        Repeater {
                            model: [1, 2, 3]
                            delegate: Item {
                                width: 52
                                height: 30
                                property bool current: core.maxPages === modelData
                                Rectangle {
                                    anchors.fill: parent
                                    radius: Theme.radiusXS
                                    color: current ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                                                   : (pageMa.containsMouse ? Theme.scrim(0.06) : Theme.scrim(0.03))
                                    border.width: 1
                                    border.color: current ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.5) : Theme.border
                                    Text {
                                        anchors.centerIn: parent
                                        text: modelData + " 页"
                                        color: current ? Theme.accent : Theme.textDim
                                        font.family: Theme.uiFont
                                        font.pixelSize: 12
                                    }
                                }
                                MouseArea {
                                    id: pageMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: core.setMaxPages(modelData)
                                }
                            }
                        }
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                // 通知开关
                Column {
                    width: parent.width
                    spacing: 12
                    Repeater {
                        model: [
                            { label: "新视频系统通知", desc: "右下角弹出 Windows 通知横幅", key: "toast" },
                            { label: "通知提示音", desc: "有新视频时播放提示音（音效可在下面自定义）", key: "sound" },
                            { label: "关闭窗口时最小化到托盘", desc: "关掉窗口后继续在后台检查", key: "tray" },
                            { label: "剪贴板服务器检测", desc: "复制到服务器地址时，回到窗口就问一句要不要加进收藏", key: "clip" }
                        ]
                        delegate: Row {
                            width: parent.width
                            spacing: 10
                            Column {
                                width: parent.width - 54
                                spacing: 2
                                Text {
                                    text: modelData.label
                                    color: Theme.text
                                    font.family: Theme.uiFont
                                    font.pixelSize: 12
                                }
                                Text {
                                    text: modelData.desc
                                    color: Theme.textMute
                                    font.family: Theme.uiFont
                                    font.pixelSize: 10
                                }
                            }
                            // 「试听」只保留下面「提示音效」区里的那一个，
                            // 这里以前又放了一个，等于同一件事有两个入口。
                            ToggleSwitch {
                                anchors.verticalCenter: parent.verticalCenter
                                checked: modelData.key === "toast" ? core.notifyToast
                                       : modelData.key === "sound" ? core.notifySound
                                       : modelData.key === "clip" ? core.clipboardServers
                                       : core.trayOnClose
                                onToggled: function (v) {
                                    if (modelData.key === "toast") core.setNotifyToast(v);
                                    else if (modelData.key === "sound") core.setNotifySound(v);
                                    else if (modelData.key === "clip") core.setClipboardServers(v);
                                    else core.setTrayOnClose(v);
                                }
                            }
                        }
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                // ---- 提示音效（可自定义：导入 / 更换 / 恢复默认）----
                Column {
                    width: parent.width
                    spacing: 9

                    Row {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: "提示音效"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: core.alertSoundName
                            color: core.alertSoundName.length > 0 ? Theme.ok : Theme.warn
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                            elide: Text.ElideMiddle
                            width: Math.min(implicitWidth, parent.width - 140)
                        }
                        Item { width: Math.max(0, parent.width - 60 - 74); height: 1 }
                        Text {
                            text: "试听"
                            color: soundTestMa.containsMouse ? Theme.accent : Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                            font.underline: soundTestMa.containsMouse
                            anchors.verticalCenter: parent.verticalCenter
                            MouseArea {
                                id: soundTestMa
                                anchors.fill: parent
                                anchors.margins: -4
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: core.testSound()
                            }
                        }
                    }

                    // 可选音效：点一下就换
                    Flow {
                        width: parent.width
                        spacing: 6
                        Repeater {
                            model: core.soundList
                            delegate: Rectangle {
                                required property var modelData
                                height: 26
                                width: Math.min(sndTxt.implicitWidth + 22, parent.width - 4)
                                radius: 13
                                property bool on: core.alertSoundName === modelData.name
                                color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                                          : (sndMa.containsMouse ? Theme.scrim(0.07)
                                                                 : Theme.scrim(0.035))
                                border.width: 1
                                border.color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.5)
                                                 : Theme.border
                                Text {
                                    id: sndTxt
                                    anchors.centerIn: parent
                                    text: modelData.name
                                    elide: Text.ElideMiddle
                                    width: Math.min(implicitWidth, parent.width - 16)
                                    horizontalAlignment: Text.AlignHCenter
                                    color: parent.on ? Theme.accent : Theme.textDim
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                }
                                MouseArea {
                                    id: sndMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: core.setAlertSound(modelData.name)
                                }
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 6
                        ActionButton {
                            width: (parent.width - 12) / 2
                            height: 32
                            accent: false
                            label: "导入音效"
                            onClicked: soundDlg.open()
                        }
                        ActionButton {
                            width: (parent.width - 12) / 2
                            height: 32
                            accent: false
                            label: "恢复默认"
                            onClicked: core.resetAlertSound()
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: "打开音效目录"
                            color: sndDirMa.containsMouse ? Theme.accent : Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                            font.underline: sndDirMa.containsMouse
                            anchors.verticalCenter: parent.verticalCenter
                            MouseArea {
                                id: sndDirMa
                                anchors.fill: parent
                                anchors.margins: -3
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: core.openSoundsFolder()
                            }
                        }
                        Text {
                            text: "也可以直接把音效文件丢进去"
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    Text {
                        width: parent.width
                        text: core.soundHint + "，默认用目录里的 bbb.mp3。"
                        wrapMode: Text.Wrap
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                // ================= ② 外观与主题 =================
                Item {
                    width: parent.width
                    height: 34
                    Rectangle {
                        anchors.fill: parent
                        anchors.topMargin: 8
                        radius: 6
                        color: Theme.scrim(0.045)
                    }
                    Rectangle {
                        width: 3
                        height: 15
                        radius: 1.5
                        anchors.left: parent.left
                        anchors.leftMargin: 9
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.accent
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 19
                        anchors.verticalCenter: parent.verticalCenter
                        text: "② 外观与主题"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }

                // ---- 外观模式（夜间 / 日间 / 跟随系统）----
                Column {
                    width: parent.width
                    spacing: 9

                    Row {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: "外观模式"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: core.followsSystem
                                  ? "跟随系统（当前系统是" + core.systemThemeLabel + "）"
                                  : core.appearanceLabel
                            color: core.followsSystem ? Theme.ok : Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                            elide: Text.ElideRight
                            width: Math.max(0, parent.width - 60)
                        }
                    }

                    // 三选一：跟系统 / 夜间 / 日间。用一排等宽按钮，比下拉框少一次点击。
                    Row {
                        width: parent.width
                        spacing: 6
                        Repeater {
                            model: [
                                { key: "system", label: "跟随系统", glyph: "\uE770" },
                                { key: "dark", label: "夜间", glyph: "\uE708" },
                                { key: "light", label: "日间", glyph: "\uE706" }
                            ]
                            delegate: Rectangle {
                                required property var modelData
                                readonly property bool on: core.appearance === modelData.key
                                width: (parent.width - 12) / 3
                                height: 34
                                radius: Theme.radiusXS
                                color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g,
                                                    Theme.accent.b, themeMa.pressed ? 0.30 : 0.18)
                                          : (themeMa.pressed ? Theme.scrim(0.14)
                                                             : (themeMa.containsMouse ? Theme.scrim(0.08)
                                                                                     : Theme.scrim(0.04)))
                                border.width: 1
                                border.color: on ? Theme.accent : Theme.border
                                Behavior on color { ColorAnimation { duration: 110 } }

                                Row {
                                    anchors.centerIn: parent
                                    spacing: 5
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: modelData.glyph
                                        font.family: Theme.iconFont
                                        font.pixelSize: 12
                                        color: parent.parent.on ? Theme.accent : Theme.textDim
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: modelData.label
                                        color: parent.parent.on ? Theme.accent : Theme.textDim
                                        font.family: Theme.uiFont
                                        font.pixelSize: 11
                                        font.weight: parent.parent.on ? Font.DemiBold : Font.Normal
                                    }
                                }

                                MouseArea {
                                    id: themeMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: core.setAppearance(modelData.key)
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: core.followsSystem
                              ? "跟着 Windows 的「应用模式」走，系统换了你这里也自动换。"
                              : "已固定，" + (core.appearance === "dark" ? "界面始终深色。"
                                                                        : "界面始终浅色。")
                        wrapMode: Text.Wrap
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                // ---- 背景图（可自定义：导入 / 透明度 / 移除）----
                Column {
                    width: parent.width
                    spacing: 9

                    Row {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: "背景图"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: !core.bgOn ? "开关已关闭，用默认渐变"
                                  : (core.bgImageName.length > 0 ? core.bgImageName : "未设置，用默认渐变")
                            color: (core.bgOn && core.bgImageName.length > 0) ? Theme.ok : Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                            elide: Text.ElideMiddle
                            // 固定占宽，右边留给开关，不会互相挤
                            width: Math.max(0, parent.width - 60 - 46 - 12)
                        }
                        // 总开关：关了就用回默认渐变，图和透明度都还留着
                        ToggleSwitch {
                            objectName: "bgOnSwitch"
                            anchors.verticalCenter: parent.verticalCenter
                            checked: core.bgOn
                            onToggled: function (v) { core.setBgOn(v); }
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 12

                        // 缩略图：直接叠一张 mini 版背景，改透明度能马上看到效果
                        Rectangle {
                            id: bgPreviewBox
                            objectName: "bgPreviewBox"
                            width: 132
                            height: 82
                            radius: Theme.radiusXS
                            color: Theme.dark ? Qt.rgba(0, 0, 0, 0.35)
                                              : Qt.rgba(0, 0, 0, 0.06)
                            border.width: 1
                            border.color: Theme.border
                            clip: true

                            Rectangle {
                                anchors.fill: parent
                                gradient: Gradient {
                                    orientation: Gradient.Vertical
                                    GradientStop { position: 0.0; color: Theme.bgGradTop }
                                    GradientStop { position: 0.45; color: Theme.bgGradMid }
                                    GradientStop { position: 1.0; color: Theme.bgGradBottom }
                                }
                            }
                            Image {
                                anchors.fill: parent
                                source: core.bgImageUrl
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                cache: true
                                // 预览框尺寸固定，这里绑 width/height 不会抖
                                sourceSize.width: Math.max(1, Math.round(width))
                                sourceSize.height: Math.max(1, Math.round(height))
                                visible: core.bgImageUrl.length > 0
                                opacity: core.bgOpacity / 100
                            }
                            Text {
                                anchors.centerIn: parent
                                visible: core.bgImageUrl.length === 0
                                text: "无背景图"
                                color: Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                        }

                        Column {
                            width: Math.max(0, parent.width - 144)
                            spacing: 8
                            anchors.verticalCenter: parent.verticalCenter

                            Row {
                                width: parent.width
                                Text {
                                    text: "透明度"
                                    color: Theme.textDim
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Item { width: Math.max(0, parent.width - 92); height: 1 }
                                Text {
                                    text: core.bgOpacity + "%"
                                    color: Theme.accent
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }

                            Item {
                                width: parent.width
                                height: 20

                                Rectangle {
                                    id: bgTrack
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width
                                    height: 4
                                    radius: 2
                                    color: Theme.scrim(0.16)

                                    Rectangle {
                                        width: parent.width * (core.bgOpacity / 100)
                                        height: parent.height
                                        radius: 2
                                        color: Theme.accent
                                    }
                                    Rectangle {
                                        x: parent.width * (core.bgOpacity / 100) - width / 2
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: bgDrag.pressed ? 11 : 9
                                        height: width
                                        radius: width / 2
                                        color: "#ffffff"
                                        border.width: 2
                                        border.color: Theme.accent
                                    }
                                    MouseArea {
                                        id: bgDrag
                                        anchors.fill: parent
                                        anchors.topMargin: -10
                                        anchors.bottomMargin: -10
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor

                                        function applyAt(x) {
                                            var r = Math.max(0, Math.min(1, x / bgTrack.width));
                                            core.previewBgOpacity(Math.round(r * 100));
                                        }
                                        onPressed: function (m) { applyAt(m.x); }
                                        onPositionChanged: function (m) {
                                            if (pressed) applyAt(m.x);
                                        }
                                        onReleased: function (m) {
                                            // 松手才落盘，拖的时候只预览
                                            core.setBgOpacity(core.bgOpacity);
                                        }
                                    }
                                }
                            }

                            Text {
                                width: parent.width
                                text: "调太高会看不清上面的文字"
                                wrapMode: Text.Wrap
                                color: Theme.textMute
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 6
                        ActionButton {
                            width: (parent.width - 6) / 2
                            height: 32
                            accent: false
                            label: core.bgImageName.length > 0 ? "更换背景图" : "选择背景图"
                            onClicked: bgDlg.open()
                        }
                        ActionButton {
                            width: (parent.width - 6) / 2
                            height: 32
                            accent: false
                            // 移除 = 真的把 background.* 删掉（不是只关掉）
                            label: "移除背景"
                            enabledBtn: core.bgImageName.length > 0
                            onClicked: core.clearBgImage()
                        }
                    }

                    // 只有一个文件，所以不再有「点图片名切换」的列表；
                    // 换成一行固定文件名的说明，用户一眼知道背景图存在哪。
                    Row {
                        width: parent.width
                        spacing: 6
                        visible: core.bgImageName.length > 0
                        Rectangle {
                            width: 8
                            height: 8
                            radius: 4
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.ok
                        }
                        Text {
                            text: "当前文件：" + core.bgImageName
                            color: Theme.textDim
                            font.family: Theme.monoFont
                            font.pixelSize: 10
                            elide: Text.ElideMiddle
                            width: Math.max(0, parent.width - 20)
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: "打开背景图目录"
                            color: bgDirMa.containsMouse ? Theme.accent : Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 11
                            font.underline: bgDirMa.containsMouse
                            anchors.verticalCenter: parent.verticalCenter
                            MouseArea {
                                id: bgDirMa
                                anchors.fill: parent
                                anchors.margins: -3
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: core.openBgFolder()
                            }
                        }
                        Text {
                            text: "自己丢图进去也行，但文件名必须是 background"
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                            elide: Text.ElideRight
                            width: Math.max(0, parent.width - 100)
                        }
                    }

                    Text {
                        width: parent.width
                        text: core.bgHint + "。只保留一个文件 background.*，"
                              + "换图会覆盖旧的，「移除背景」会真的删掉它。"
                        wrapMode: Text.Wrap
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                // ---- 主题色（色盘取色，全局强调色跟着变）----
                Column {
                    objectName: "accentSection"
                    width: parent.width
                    spacing: 9

                    Row {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: "主题色"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "按钮、高亮、进度条都用这个颜色"
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    // 取色面板：色盘 + 明度条 + RGB 微调。
                    // 以前这里是「一个色块 + R/G/B 三条滑块」，只能靠拖滑块凑颜色，
                    // 想选个具体的粉/青基本靠试 —— 用户要的是能直接点着选。
                    ColorWheel {
                        id: accentPicker
                        objectName: "accentPicker"
                        width: parent.width
                        height: 236
                        current: Theme.accent
                        // 拖动/点击过程中只做实时预览（不写盘）
                        onPicked: function (c) {
                            core.previewAccent(Math.round(c.r * 255),
                                               Math.round(c.g * 255),
                                               Math.round(c.b * 255));
                        }
                        // 松手才落盘：拖动过程中每一步都写 config.json 会很卡
                        onReleased: {
                            function toHex(c) {
                                var h = "0123456789ABCDEF";
                                function b(n) {
                                    var x = Math.max(0, Math.min(255, Math.round(n * 255)));
                                    return h.charAt(Math.floor(x / 16)) + h.charAt(x % 16);
                                }
                                return "#" + b(c.r) + b(c.g) + b(c.b);
                            }
                            accentPicker.commit();
                        }
                    }

                    // 预设色：点一下就套上（想快速换个颜色不用慢慢拖）
                    Text {
                        text: "预设"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                    Flow {
                        width: parent.width
                        spacing: 6
                        Repeater {
                            model: [
                                { name: "默认红", hex: "#FF4D57" },
                                { name: "樱粉", hex: "#FB7299" },
                                { name: "橙", hex: "#FF8A3D" },
                                { name: "琥珀", hex: "#F5B33C" },
                                { name: "草绿", hex: "#3ED598" },
                                { name: "青", hex: "#4DD0E1" },
                                { name: "海蓝", hex: "#4D8CFF" },
                                { name: "紫", hex: "#9B6BFF" }
                            ]
                            delegate: Rectangle {
                                required property var modelData
                                height: 26
                                width: Math.max(34, preTxt.implicitWidth + 30)
                                radius: 13
                                property bool on: core.uiAccent === modelData.hex
                                color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                                          : (preMa.containsMouse ? Theme.scrim(0.07)
                                                                  : Theme.scrim(0.035))
                                border.width: 1
                                border.color: on ? Theme.accent : Theme.border

                                // 左边一个小圆点显示该预设的颜色
                                Rectangle {
                                    id: preDot
                                    width: 12
                                    height: 12
                                    radius: 6
                                    color: modelData.hex
                                    anchors.left: parent.left
                                    anchors.leftMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    border.width: 1
                                    border.color: Theme.scrim(0.18)
                                }
                                Text {
                                    id: preTxt
                                    anchors.left: preDot.right
                                    anchors.leftMargin: 5
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.name
                                    color: parent.on ? Theme.accent : Theme.textDim
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                }
                                MouseArea {
                                    id: preMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        var h = modelData.hex;
                                        var r = parseInt(h.substr(1, 2), 16);
                                        var g = parseInt(h.substr(3, 2), 16);
                                        var b = parseInt(h.substr(5, 2), 16);
                                        core.setAccent(r, g, b);
                                    }
                                }
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 6
                        ActionButton {
                            width: (parent.width - 6) / 2
                            height: 32
                            accent: false
                            label: "恢复默认色"
                            onClicked: core.resetAccent()
                        }
                        Item { width: (parent.width - 6) / 2; height: 1 }
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                // ================= ③ 目录与网络 =================
                Item {
                    width: parent.width
                    height: 34
                    Rectangle {
                        anchors.fill: parent
                        anchors.topMargin: 8
                        radius: 6
                        color: Theme.scrim(0.045)
                    }
                    Rectangle {
                        width: 3
                        height: 15
                        radius: 1.5
                        anchors.left: parent.left
                        anchors.leftMargin: 9
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.accent
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 19
                        anchors.verticalCenter: parent.verticalCenter
                        text: "③ 目录与网络"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }

                // MOD 目录（从 MOD 管理器搬过来的，放在这儿不占主界面位置）
                Column {
                    width: parent.width
                    spacing: 8

                    Row {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: "MOD 目录"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: core.mods.hasDir ? "已找到" : "未设置"
                            color: core.mods.hasDir ? Theme.ok : Theme.warn
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 34
                        radius: Theme.radiusXS
                        color: Theme.scrim(0.035)
                        border.width: 1
                        border.color: Theme.border

                        Text {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: core.mods.addonsDir.length > 0
                                  ? core.mods.addonsDir
                                  : "还没检测到，点右边「检测」或「选择」"
                            elide: Text.ElideMiddle
                            color: core.mods.hasDir ? Theme.textDim : Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }
                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: core.mods.openAddonsFolder()
                            ToolTip.visible: containsMouse && core.mods.hasDir
                            ToolTip.text: "点一下打开这个文件夹"
                            ToolTip.delay: 500
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 6
                        ActionButton {
                            width: (parent.width - 12) / 2
                            height: 32
                            accent: false
                            label: "检测"
                            onClicked: modPanel.autoDetectDir()
                        }
                        ActionButton {
                            width: (parent.width - 12) / 2
                            height: 32
                            accent: false
                            label: "选择目录"
                            onClicked: modPanel.openDirPicker()
                        }
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                // 创意工坊导入的下载线程数
                Column {
                    width: parent.width
                    spacing: 8

                    Row {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: "下载线程"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: core.mods.downloadThreads + " 线程"
                            color: core.mods.downloadThreads > 4 ? Theme.warn : Theme.ok
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    // 1-16：一次下多个 MOD / 前置时用几条线程同时下。
                    // 上限从 8 提到 16：下载站给的是 CDN 直链，16 条并发实测不限速，
                    // 而工坊 MOD 多是「几十个小文件」，并发高收益明显；再高瓶颈就转到
                    // 「逐条解析直链」上去了，反而更容易被下载站限流。
                    Row {
                        width: parent.width
                        spacing: 3
                        Repeater {
                            model: [1, 2, 3, 4, 6, 8, 12, 16]
                            delegate: Rectangle {
                                required property int modelData
                                readonly property bool on: core.mods.downloadThreads === modelData
                                width: (parent.width - 21) / 8
                                height: 30
                                radius: Theme.radiusXS
                                color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g,
                                                    Theme.accent.b, thMa.pressed ? 0.28 : 0.18)
                                          : (thMa.pressed ? Theme.scrim(0.12)
                                                          : (thMa.containsMouse ? Theme.scrim(0.07)
                                                                                : Theme.scrim(0.04)))
                                border.width: 1
                                border.color: on ? Theme.accent : Theme.border
                                Behavior on color { ColorAnimation { duration: 90 } }
                                Text {
                                    anchors.centerIn: parent
                                    text: modelData
                                    color: parent.on ? Theme.accent : Theme.textDim
                                    font.family: Theme.monoFont
                                    font.pixelSize: 11
                                    font.weight: parent.on ? Font.Bold : Font.Normal
                                }
                                MouseArea {
                                    id: thMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: core.mods.setDownloadThreads(modelData)
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: "创意工坊导入时同时下几个文件。开太多容易被 CDN 限速，"
                              + "3 线程一般够用。"
                        wrapMode: Text.Wrap
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                // ---- 网络加速（工坊封面 / 详情 / 下载都走它）
                // 界面上只出现节点地名（东京 / 首尔…），IP 一律不进 UI。
                Column {
                    objectName: "netAccelSection"
                    width: parent.width
                    spacing: 8

                    Row {
                        width: parent.width
                        spacing: 7

                        Text {
                            text: "\uE945"
                            font.family: Theme.iconFont
                            font.pixelSize: 13
                            color: core.mods.cdnEnabled ? Theme.accent : Theme.textMute
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "网络加速"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        // 状态胶囊：一个状态点 + 「模式 · 地名 · 延迟」
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            height: 20
                            width: statusTxt.implicitWidth + 24
                            radius: 10
                            color: core.mods.cdnEnabled
                                   ? Qt.rgba(Theme.accent.r, Theme.accent.g,
                                             Theme.accent.b, 0.13)
                                   : Theme.scrim(0.05)
                            border.width: 1
                            border.color: core.mods.cdnEnabled
                                          ? Qt.rgba(Theme.accent.r, Theme.accent.g,
                                                    Theme.accent.b, 0.42)
                                          : Theme.border
                            Row {
                                anchors.centerIn: parent
                                spacing: 5
                                Rectangle {
                                    width: 6
                                    height: 6
                                    radius: 3
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: !core.mods.cdnEnabled ? Theme.textMute
                                           : (core.mods.cdnTesting ? Theme.warn : Theme.ok)
                                }
                                Text {
                                    id: statusTxt
                                    objectName: "cdnStatusText"
                                    text: core.mods.cdnTesting
                                          ? "正在测速…"
                                          : core.mods.cdnSummary
                                    color: core.mods.cdnEnabled ? Theme.accent : Theme.textMute
                                    font.family: Theme.uiFont
                                    font.pixelSize: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                        }

                        Item { width: Math.max(0, parent.width - 340); height: 1 }
                        ToggleSwitch {
                            objectName: "cdnSwitch"
                            anchors.verticalCenter: parent.verticalCenter
                            checked: core.mods.cdnEnabled
                            onToggled: function (v) { core.mods.setCdnEnabled(v); }
                        }
                    }

                    // 模式：自动优选 / 手动指定（选中块会滑过去）
                    Rectangle {
                        id: cdnModeTrack
                        objectName: "cdnModeSwitch"
                        width: 216
                        height: 28
                        radius: 14
                        visible: core.mods.cdnEnabled
                        color: Theme.scrim(0.05)
                        border.width: 1
                        border.color: Theme.border

                        Rectangle {
                            id: cdnModePill
                            y: 3
                            width: (cdnModeTrack.width - 6) / 2
                            height: cdnModeTrack.height - 6
                            x: core.mods.cdnMode === "manual" ? 3 + width : 3
                            radius: 11
                            color: Qt.rgba(Theme.accent.r, Theme.accent.g,
                                           Theme.accent.b, 0.20)
                            border.width: 1
                            border.color: Qt.rgba(Theme.accent.r, Theme.accent.g,
                                                  Theme.accent.b, 0.55)
                            Behavior on x {
                                NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
                            }
                        }

                        Row {
                            anchors.fill: parent
                            Item {
                                objectName: "cdnMode_auto"
                                width: (cdnModeTrack.width - 6) / 2
                                height: parent.height
                                Row {
                                    anchors.centerIn: parent
                                    spacing: 5
                                    Text {
                                        text: "\uE9D2"
                                        font.family: Theme.iconFont
                                        font.pixelSize: 10
                                        color: core.mods.cdnMode === "auto"
                                               ? Theme.accent : Theme.textMute
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    Text {
                                        text: "自动优选"
                                        font.family: Theme.uiFont
                                        font.pixelSize: 10
                                        color: core.mods.cdnMode === "auto"
                                               ? Theme.accent : Theme.textDim
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: core.mods.setCdnMode("auto")
                                }
                            }
                            Item {
                                objectName: "cdnMode_manual"
                                width: (cdnModeTrack.width - 6) / 2
                                height: parent.height
                                Row {
                                    anchors.centerIn: parent
                                    spacing: 5
                                    Text {
                                        text: "\uE70F"
                                        font.family: Theme.iconFont
                                        font.pixelSize: 10
                                        color: core.mods.cdnMode === "manual"
                                               ? Theme.accent : Theme.textMute
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    Text {
                                        text: "手动指定"
                                        font.family: Theme.uiFont
                                        font.pixelSize: 10
                                        color: core.mods.cdnMode === "manual"
                                               ? Theme.accent : Theme.textDim
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: core.mods.setCdnMode("manual")
                                }
                            }
                        }
                    }

                    // 自动优选：程序自己挑机器，界面上只说地名，不摆 IP
                    Row {
                        width: parent.width
                        spacing: 6
                        visible: core.mods.cdnEnabled && core.mods.cdnMode === "auto"
                        Text {
                            text: "自动优选"
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: core.mods.cdnTesting ? "正在逐个测速…"
                                                       : "点「重新测速」会重新挑最快的机房"
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Spinner {
                            width: 14
                            height: 14
                            visible: core.mods.cdnTesting
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    // 手动指定：自己填 IPv4 / IPv6（自建服务器、指定节点都行）
                    Column {
                        width: parent.width
                        spacing: 5
                        visible: core.mods.cdnEnabled && core.mods.cdnMode === "manual"

                        Rectangle {
                            width: parent.width
                            height: 30
                            radius: Theme.radiusXS
                            color: Theme.scrim(0.05)
                            border.width: 1
                            border.color: cdnIpInput.activeFocus ? Theme.accent : Theme.border

                            HoverHandler { cursorShape: Qt.IBeamCursor }

                            TextInput {
                                id: cdnIpInput
                                objectName: "cdnIpInput"
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                verticalAlignment: TextInput.AlignVCenter
                                color: Theme.text
                                font.family: Theme.monoFont
                                font.pixelSize: 11
                                selectByMouse: true
                                selectionColor: Theme.accent
                                text: core.mods.cdnIp
                                // Enter 或者点走即生效；不合法时 store 那边会 toast 提示
                                onAccepted: core.mods.setCdnIp(text)
                                onEditingFinished: core.mods.setCdnIp(text)

                                Text {
                                    anchors.fill: parent
                                    verticalAlignment: Text.AlignVCenter
                                    visible: cdnIpInput.text.length === 0
                                    text: "填一个 IPv4 / IPv6，例如 23.59.72.59"
                                    color: Theme.textMute
                                    font.family: Theme.uiFont
                                    font.pixelSize: 10
                                }
                            }
                        }

                        Text {
                            width: parent.width
                            text: {
                                if (core.mods.cdnIp.length === 0)
                                    return "还没填地址，加速暂时不起作用";
                                var region = core.mods.cdnRegion;
                                if (region.length > 0)
                                    return "这个地址在 " + region + "，已生效";
                                return "地址已生效（认不出机房位置，不影响使用）";
                            }
                            wrapMode: Text.Wrap
                            color: core.mods.cdnIp.length > 0 ? Theme.ok : Theme.warn
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 6
                        visible: core.mods.cdnEnabled
                        ActionButton {
                            objectName: "cdnTestBtn"
                            width: 104
                            height: 28
                            accent: false
                            label: "重新测速"
                            glyph: "\uE72C"
                            busy: core.mods.cdnTesting
                            onClicked: core.mods.autoSelectCdnNode()
                        }
                        ActionButton {
                            objectName: "cdnOffBtn"
                            width: 104
                            height: 28
                            accent: false
                            label: "关闭加速"
                            glyph: "\uE711"
                            onClicked: core.mods.setCdnMode("off")
                        }
                    }

                    Text {
                        width: parent.width
                        text: core.mods.cdnEnabled
                              ? "国内直连 cdn.steamusercontent.com 常被解析到很远的机房，"
                                + "工坊封面就会白一片。加速只决定「连到哪台机器」，"
                                + "握手的域名和证书照旧校验 —— 安全上和直接访问一样。"
                              : "已关闭：不指定机器，交给下面的 DNS 去解析。"
                      + "用自动优选时只按地名显示，不把地址摆到界面上。"
                        wrapMode: Text.Wrap
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                // ---- 工坊 DNS（和上面的网络加速是两件独立的事：
                //      加速管「连哪个机器」，这里管「谁来把域名解析成地址」）
                Column {
                    objectName: "workshopDnsSection"
                    width: parent.width
                    spacing: 8

                    Row {
                        width: parent.width
                        spacing: 7

                        Text {
                            text: "\uE704"
                            font.family: Theme.iconFont
                            font.pixelSize: 13
                            color: Theme.accent
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "工坊 DNS"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            height: 20
                            width: dnsStatusTxt.implicitWidth + 20
                            radius: 10
                            color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.12)
                            border.width: 1
                            border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.38)
                            Text {
                                id: dnsStatusTxt
                                objectName: "dnsStatusText"
                                anchors.centerIn: parent
                                text: core.mods.dnsSummary
                                color: Theme.accent
                                font.family: Theme.uiFont
                                font.pixelSize: 10
                            }
                        }
                    }

                    // 四个选项竖着排：右边区域窄，横排文案会挤成一团
                    Column {
                        width: parent.width
                        spacing: 2

                        Repeater {
                            model: core.mods.dnsModes

                            delegate: Rectangle {
                                required property var modelData
                                objectName: "dnsMode_" + modelData.value
                                width: parent.width
                                height: 26
                                radius: Theme.radiusXS
                                color: dnsMa.containsMouse ? Theme.scrim(0.07) : "transparent"

                                Row {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 4
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 8

                                    // 单选框：选中的那个中间填一个实心点
                                    Rectangle {
                                        width: 13
                                        height: 13
                                        radius: 6.5
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: "transparent"
                                        border.width: 1
                                        border.color: modelData.active ? Theme.accent : Theme.borderHi
                                        Rectangle {
                                            anchors.centerIn: parent
                                            width: 7
                                            height: 7
                                            radius: 3.5
                                            visible: modelData.active
                                            color: Theme.accent
                                        }
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: modelData.label
                                        color: modelData.active ? Theme.text : Theme.textDim
                                        font.family: Theme.uiFont
                                        font.pixelSize: 11
                                    }
                                }

                                MouseArea {
                                    id: dnsMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: core.mods.setDnsMode(modelData.value)
                                }
                            }
                        }
                    }

                    // 自定义 DNS：只收单个 IPv4 / IPv6
                    Column {
                        width: parent.width
                        spacing: 5
                        visible: core.mods.dnsMode === "custom"

                        Rectangle {
                            width: parent.width
                            height: 30
                            radius: Theme.radiusXS
                            color: Theme.scrim(0.05)
                            border.width: 1
                            border.color: dnsInput.activeFocus ? Theme.accent : Theme.border

                            HoverHandler { cursorShape: Qt.IBeamCursor }

                            TextInput {
                                id: dnsInput
                                objectName: "dnsCustomInput"
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                verticalAlignment: TextInput.AlignVCenter
                                color: Theme.text
                                font.family: Theme.monoFont
                                font.pixelSize: 11
                                selectByMouse: true
                                selectionColor: Theme.accent
                                text: core.mods.dnsCustom
                                onAccepted: core.mods.setDnsCustom(text)
                                onEditingFinished: core.mods.setDnsCustom(text)

                                Text {
                                    anchors.fill: parent
                                    verticalAlignment: Text.AlignVCenter
                                    visible: dnsInput.text.length === 0
                                    text: "例如 119.29.29.29 或 2400:3200::1"
                                    color: Theme.textMute
                                    font.family: Theme.uiFont
                                    font.pixelSize: 10
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: "工坊的列表、详情、下载链接和封面都按这里选的 DNS 解析，"
                              + "改完立刻生效 —— 只影响本程序，不动系统设置。"
                        wrapMode: Text.Wrap
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                // ================= ④ 数据与缓存 =================
                Item {
                    width: parent.width
                    height: 34
                    Rectangle {
                        anchors.fill: parent
                        anchors.topMargin: 8
                        radius: 6
                        color: Theme.scrim(0.045)
                    }
                    Rectangle {
                        width: 3
                        height: 15
                        radius: 1.5
                        anchors.left: parent.left
                        anchors.leftMargin: 9
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.accent
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 19
                        anchors.verticalCenter: parent.verticalCenter
                        text: "④ 数据与缓存"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }

                // 删 MOD 的方式
                Column {
                    width: parent.width
                    spacing: 8

                    Row {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: "删除 MOD 时"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: core.mods.deleteToRecycle ? "回收站" : "直接删除"
                            color: core.mods.deleteToRecycle ? Theme.ok : Theme.warn
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 6
                        Repeater {
                            model: [
                                { key: true, label: "放进回收站" },
                                { key: false, label: "直接删除" }
                            ]
                            delegate: Rectangle {
                                required property var modelData
                                width: (parent.width - 6) / 2
                                height: 32
                                radius: Theme.radiusXS
                                property bool on: core.mods.deleteToRecycle === modelData.key
                                color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b,
                                                    delMa.pressed ? 0.26 : 0.16)
                                          : (delMa.pressed ? Theme.scrim(0.11)
                                                           : (delMa.containsMouse ? Theme.scrim(0.05)
                                                                                  : Theme.scrim(0.035)))
                                border.width: 1
                                border.color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.45)
                                                 : Theme.border
                                Behavior on color { ColorAnimation { duration: 90 } }

                                Text {
                                    anchors.centerIn: parent
                                    text: modelData.label
                                    color: parent.on ? Theme.text : Theme.textDim
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                }
                                MouseArea {
                                    id: delMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: core.mods.setDeleteToRecycle(modelData.key)
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: core.mods.deleteToRecycle
                              ? "删掉的 MOD 会和同名封面图一起进系统回收站，删错了能还原。"
                              : "删掉的 MOD 会被永久删除（连同名封面图），没法撤回。"
                        wrapMode: Text.Wrap
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 10
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }
                Column {
                    width: parent.width
                    spacing: 8

                    Row {
                        width: parent.width
                        spacing: 6
                        Text {
                            text: "缓存"
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "共 " + core.cacheSummary
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 6

                        // 原来这里还有一格「视频缓存 XX —— 点一下清空」。
                        // 那是**摆设**：视频是直接流式播放的（QtMultimedia 自己管缓冲），
                        // 程序从来没有往 `cache/video/` 写过任何文件 ——
                        // 那个目录只在「统计大小」和「清空」时被读到，永远是 0 B。
                        // 留着一个永远是 0 B、点了也没东西可清的按钮只会让人以为功能坏了，
                        // 所以整格删掉，封面缓存占满整行。
                        Rectangle {
                            width: parent.width
                            height: 40
                            radius: Theme.radiusXS
                            color: Theme.scrim(0.035)
                            border.width: 1
                            border.color: Theme.border
                            Column {
                                anchors.centerIn: parent
                                spacing: 1
                                Text {
                                    text: "封面缓存 " + core.modCache.text
                                    color: Theme.textDim
                                    font.family: Theme.uiFont
                                    font.pixelSize: 10
                                }
                                Text {
                                    text: "工坊封面本地副本，点一下清空（清了会自动重下）"
                                    color: Theme.textMute
                                    font.family: Theme.uiFont
                                    font.pixelSize: 9
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: core.clearModCache()
                            }
                        }
                    }

                    ActionButton {
                        label: "一键清理全部缓存"
                        accent: false
                        width: parent.width
                        height: 34
                        onClicked: core.clearAllCaches()
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                Row {
                    width: parent.width
                    spacing: 8
                    ActionButton {
                        label: "清空本地记录"
                        accent: false
                        width: parent.width
                        onClicked: clearConfirm.open()
                    }
                }

                Text {
                    width: parent.width
                    text: "数据保存在 data/config.json 与 data/library.json，删掉即恢复初始状态。"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    wrapMode: Text.Wrap
                    lineHeight: 1.5
                }

                // ================= ⑤ 关于 =================
                Item {
                    width: parent.width
                    height: 34
                    Rectangle {
                        anchors.fill: parent
                        anchors.topMargin: 8
                        radius: 6
                        color: Theme.scrim(0.045)
                    }
                    Rectangle {
                        width: 3
                        height: 15
                        radius: 1.5
                        anchors.left: parent.left
                        anchors.leftMargin: 9
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.accent
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 19
                        anchors.verticalCenter: parent.verticalCenter
                        text: "⑤ 关于"
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }

                // 作者 + 版本 + 主页。文案全部来自 core.about*（见 app/core.py），
                // 这里只负责排版 —— 以后改名/换仓库地址不用在 QML 里再找一遍。
                Rectangle {
                    width: parent.width
                    height: aboutCol.implicitHeight + 32
                    radius: Theme.radiusS
                    color: Theme.scrim(0.035)
                    border.width: 1
                    border.color: Theme.border

                    Column {
                        id: aboutCol
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16
                        spacing: 10

                        Row {
                            spacing: 10
                            Rectangle {
                                width: 36; height: 36; radius: 11
                                color: Theme.scrim(0.05)
                                clip: true
                                Image {
                                    anchors.fill: parent
                                    source: core.logoUrl
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    cache: true
                                    smooth: true
                                    sourceSize.width: 72
                                    sourceSize.height: 72
                                }
                            }
                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 2
                                Text {
                                    text: core.aboutName
                                    color: Theme.text
                                    font.family: Theme.uiFont
                                    font.pixelSize: 13
                                    font.weight: Font.Bold
                                }
                                Text {
                                    text: "作者：" + core.aboutAuthor + "　·　版本 " + core.aboutVersion
                                    color: Theme.textDim
                                    font.family: Theme.uiFont
                                    font.pixelSize: 11
                                }
                            }
                        }

                        // GitHub 主页：整行可点（直接开浏览器），右边再给一颗「复制」
                        Rectangle {
                            width: parent.width
                            height: 36
                            radius: Theme.radiusXS
                            color: ghMa.containsMouse ? Theme.scrim(0.075) : Theme.scrim(0.035)
                            border.width: 1
                            border.color: ghMa.containsMouse ? Theme.borderHi : Theme.border
                            Behavior on color { ColorAnimation { duration: 90 } }

                            Row {
                                anchors.left: parent.left
                                anchors.leftMargin: 12
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Text {
                                    text: "\uE774"   // GitHub 那条链子图标（Segoe Fluent Icons）
                                    color: Theme.textMute
                                    font.family: Theme.iconFont
                                    font.pixelSize: 12
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 1
                                    Text {
                                        text: "GitHub"
                                        color: Theme.text
                                        font.family: Theme.uiFont
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        text: core.aboutHomepageText
                                        color: Theme.textMute
                                        font.family: Theme.monoFont
                                        font.pixelSize: 10
                                    }
                                }
                            }

                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: 12
                                anchors.verticalCenter: parent.verticalCenter
                                text: "打开"
                                color: Theme.accent
                                font.family: Theme.uiFont
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }

                            MouseArea {
                                id: ghMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: core.openHomepage()
                            }
                        }

                        Row {
                            width: parent.width
                            spacing: 8
                            ActionButton {
                                label: "复制链接"
                                accent: false
                                width: (parent.width - 8) / 2
                                height: 32
                                onClicked: core.copyHomepage()
                            }
                            ActionButton {
                                label: "打开数据目录"
                                accent: false
                                width: (parent.width - 8) / 2
                                height: 32
                                onClicked: core.openDataDir()
                            }
                        }

                        Text {
                            width: parent.width
                            text: "本程序按 GPL-3.0 发布，源码在 GitHub 上可以随便看、随便改；"
                                  + "遇到问题欢迎去仓库提 issue。"
                            color: Theme.textMute
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            wrapMode: Text.Wrap
                            lineHeight: 1.4
                        }
                    }
                }

                Item { width: 1; height: 1 }
            }
            }

            // 滚动条放在 Flickable **外面**，贴着抽屉右边缘。
            // 之前是挂 Flickable 的 ScrollBar.vertical —— 那种会自动贴在 Flickable
            // 的右边缘、盖在内容上面（开关、按钮被压住）。挪出来之后两者各占一块，
            // 互不遮挡；Flickable 的 anchors.margins 也就不用再为它留 30px 了。
            ScrollBar {
                id: settingsBar
                objectName: "settingsBar"
                orientation: Qt.Vertical
                anchors.right: parent.right
                anchors.rightMargin: 6
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.topMargin: 20
                anchors.bottomMargin: 20
                width: 8
                padding: 1
                // ScrollBar 的 size / position 都是 0..1：
                //   size     = 可视高度 / 内容高度（滑块长度占比）
                //   position = 已经滚过的比例
                // ScrollBar 自己会把 position 夹在 [0, 1 - size] 里（滑块底端最多贴到
                // 轨道底端），所以「拖到底」最多只能把 position 拖到 1 - size。
                // 以前直接按 position 换算内容偏移：
                //     contentY = position * 可滚距离
                // 于是拖到底也只到 (1 - size) * 可滚距离 —— 永远差一屏，
                // 看起来就是「拖不到最下面，只有滚轮能滑到底」。
                // 现在把 position 归一化到「可拖行程」1 - size 上，拖到底就是真到底。
                readonly property real scrollableY: Math.max(0, settingsFlick.contentHeight - settingsFlick.height)
                readonly property real dragRange: Math.max(0.0001, 1 - size)
                size: settingsFlick.contentHeight > 0
                      ? Math.min(1, settingsFlick.height / settingsFlick.contentHeight)
                      : 1
                // 拖动 → 内容偏移：position 属于 [0, dragRange]，按比例铺满可滚距离
                function contentFromPos(p) {
                    return dragRange > 0 ? (p / dragRange) * scrollableY : 0;
                }
                visible: settingsFlick.contentHeight > settingsFlick.height
                active: settingsFlick.moving || pressed
                // 拖动时 position 是控件自己在改（会打断普通绑定），
                // 所以这里用 Binding：没在拖的时候由它负责跟随内容位置。
                Binding {
                    target: settingsBar
                    property: "position"
                    when: !settingsBar.pressed
                    restoreMode: Binding.RestoreNone
                    value: settingsBar.scrollableY > 0
                           ? Math.max(0, Math.min(
                                 settingsBar.dragRange,
                                 settingsFlick.contentY / settingsBar.scrollableY
                                 * settingsBar.dragRange))
                           : 0
                }
                // 拖动滚动条 → 带着 Flickable 走
                onPositionChanged: {
                    if (pressed) {
                        settingsFlick.contentY = Math.max(
                            0, Math.min(scrollableY, contentFromPos(position)));
                    }
                }
                contentItem: Rectangle {
                    implicitWidth: 6
                    radius: 3
                    color: settingsBar.pressed
                           ? Theme.scrim(0.40)
                           : (settingsBar.hovered || settingsBar.active
                              ? Theme.scrim(0.28)
                              : Theme.scrim(0.16))
                }
                background: Item { }
            }
        }

        // ------------------------------------------------ 确认弹窗
        Popup {
            id: clearConfirm
            anchors.centerIn: Overlay.overlay
            width: 340
            height: 150
            modal: true
            focus: true
            padding: 0
            background: Rectangle {
                radius: Theme.radius
                color: Theme.surface
                border.width: 1
                border.color: Theme.borderHi
            }
            contentItem: Column {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                Text {
                    text: "确定清空所有本地记录？"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 14
                    font.weight: Font.Bold
                }
                Text {
                    width: parent.width
                    text: "下次扫描会把当前搜到的视频当作基线，不会误报成新视频。"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                    lineHeight: 1.5
                }
                Row {
                    spacing: 10
                    ActionButton {
                        label: "取消"
                        accent: false
                        width: 90
                        onClicked: clearConfirm.close()
                    }
                    ActionButton {
                        label: "确定清空"
                        width: 110
                        onClicked: {
                            core.clearAll();
                            clearConfirm.close();
                        }
                    }
                }
            }
        }

        // ------------------------------------------------ 剪贴板里发现的服务器
        // 从别处复制了一段带 ip:port 的文字 → 回到窗口时问一句要不要加进收藏。
        // 只加不删，重复地址跳过（和「导入配置文件」同一套规矩）。
        Popup {
            id: clipAskDlg
            objectName: "srvClipAskDlg"
            visible: win.clipAskOpen
            // ★ 关框（Esc / 点外面 / 三个按钮任意一个）都要把这段记成「已处理」。
            //   以前这里只有 `clipAskOpen = false`，于是「点✕关掉、没点按钮」时
            //   后端计数还记得「有新复制没消费」，下次焦点一变又弹一遍 ——
            //   同一段内容反复提示，就是用户报的「重复剪贴板提示导入」。
            //   放在 onClosed 里是因为三个按钮都会先关框，一处兜住最稳。
            onClosed: {
                win.clipAskOpen = false;
                if (core && core.servers)
                    core.servers.noteClipboardHandled();
            }
            anchors.centerIn: Overlay.overlay
            modal: true
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
            padding: 20
            contentWidth: 400
            contentHeight: clipCol.implicitHeight

            background: Rectangle {
                radius: 14
                color: Theme.panel
                border.width: 1
                border.color: Theme.borderHi
            }

            contentItem: Column {
                id: clipCol
                width: 400
                spacing: 10

                Text {
                    text: "剪贴板里有服务器地址"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }

                Text {
                    width: parent.width
                    // 只有「确实有新的可导入」时才会弹这个框（重复的在 checkClipboardServers
                    // 里就被挡掉了），所以文案只留这一种。
                    text: "找到 " + (win.clipInfo.total || 0) + " 台服务器，其中 "
                          + (win.clipInfo.fresh || 0) + " 台不在收藏里。要一键加进收藏吗？"
                    color: Theme.ok
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }

                Text {
                    width: parent.width
                    visible: ((win.clipInfo.freshAddrs || []).length > 0)
                    text: "新找到的：" + (win.clipInfo.freshAddrs || []).join("  ")
                    color: Theme.ok
                    font.family: Theme.monoFont
                    font.pixelSize: 10
                    wrapMode: Text.WrapAnywhere
                }

                Text {
                    width: parent.width
                    visible: ((win.clipInfo.addrs || []).length > 0)
                    text: "这段文字里的地址：" + (win.clipInfo.addrs || []).join("  ")
                    color: Theme.textMute
                    font.family: Theme.monoFont
                    font.pixelSize: 10
                    lineHeight: 1.45
                    wrapMode: Text.WrapAnywhere
                }

                Text {
                    width: parent.width
                    visible: (win.clipInfo.fresh || 0) > 0
                    text: "同一个地址只加一次，已有的会被跳过；导入后会自动查一次状态。"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    wrapMode: Text.WordWrap
                }

                Row {
                    width: parent.width
                    spacing: 8
                    ActionButton {
                        width: 96
                        height: 30
                        accent: false
                        label: "以后别问"
                        onClicked: {
                            win.clipAskOpen = false;
                            core.servers.noteClipboardHandled();
                            core.setClipboardServers(false);
                            win.toast("已关闭剪贴板检测，想开回来去设置里", "info");
                        }
                    }
                    Item { width: Math.max(0, parent.width - 96 - 172); height: 1 }
                    ActionButton {
                        width: 76
                        height: 30
                        accent: false
                        label: "不用"
                        onClicked: {
                            win.clipAskOpen = false;
                            // 记成「这段已经处理过」：不复制新东西就不会再问
                            core.servers.noteClipboardHandled();
                        }
                    }
                    ActionButton {
                        objectName: "srvClipImportBtn"
                        width: 84
                        height: 30
                        // 框只会在「有新的可导入」时弹出，所以这里固定是「一键导入」。
                        label: "一键导入"
                        onClicked: {
                            var info = win.clipInfo || {};
                            var text = info.text || "";
                            win.clipAskOpen = false;
                            core.servers.noteClipboardHandled();
                            if (text.length === 0) {
                                win.toast("这段文字已经变了，重新复制一次吧", "warn");
                                return;
                            }
                            core.servers.importFromText(text);
                        }
                    }
                }
            }
        }

        // ------------------------------------------------ 选择提示音效文件
        FileDialog {
            id: soundDlg
            title: "选择提示音效（MP3 / WAV / FLAC / OGG / AAC / APE）"
            fileMode: FileDialog.OpenFile
            nameFilters: [
                "音效文件 (*.mp3 *.wav *.flac *.ogg *.aac *.ape)",
                "所有文件 (*)"
            ]
            onAccepted: {
                var s = String(selectedFile);
                if (s.indexOf("file:///") === 0)
                    s = s.substring(8);
                else if (s.indexOf("file://") === 0)
                    s = s.substring(7);
                try { s = decodeURIComponent(s); } catch (e) { }
                core.importAlertSound(s);
            }
        }

        // ------------------------------------------------ 服务器配置导出
        FileDialog {
            id: srvExportDlg
            objectName: "srvExportDlg"
            title: "导出服务器配置（不含面板密码）"
            fileMode: FileDialog.SaveFile
            defaultSuffix: "json"
            nameFilters: ["服务器配置 (*.json)", "所有文件 (*)"]
            onAccepted: {
                var s = String(selectedFile);
                if (s.indexOf("file:///") === 0) s = s.substring(8);
                else if (s.indexOf("file://") === 0) s = s.substring(7);
                try { s = decodeURIComponent(s); } catch (e) { }
                core.servers.exportConfig(s);
            }
        }

        // ------------------------------------------------ 服务器配置导入
        FileDialog {
            id: srvImportDlg
            objectName: "srvImportDlg"
            title: "导入服务器配置（.json）"
            fileMode: FileDialog.OpenFile
            nameFilters: ["服务器配置 (*.json)", "所有文件 (*)"]
            onAccepted: {
                var s = String(selectedFile);
                if (s.indexOf("file:///") === 0) s = s.substring(8);
                else if (s.indexOf("file://") === 0) s = s.substring(7);
                try { s = decodeURIComponent(s); } catch (e) { }
                // 先预览：说清楚有几台是新的、几台已存在，再让用户确认
                var info = core.servers.previewImport(s);
                if (!info || info.ok !== true) {
                    win.toast((info && info.error) || "这个文件读不了", "error");
                    return;
                }
                if (info.total === 0) {
                    win.toast("这个文件里没有服务器", "warn");
                    return;
                }
                if (info.fresh === 0) {
                    win.toast("这 " + info.duplicate + " 台都已经在列表里了", "info");
                    return;
                }
                srvImportPath = s;
                srvImportInfo = info;
                srvImportConfirm.open();
            }
        }

        // 导入前确认（复用 Popup，不额外占一个模态层）
        Popup {
            id: srvImportConfirm
            objectName: "srvImportConfirm"
            anchors.centerIn: Overlay.overlay
            modal: true
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
            padding: 20
            contentWidth: 380
            contentHeight: importCol2.implicitHeight

            background: Rectangle {
                radius: 14
                color: Theme.panel
                border.width: 1
                border.color: Theme.borderHi
            }

            contentItem: Column {
                id: importCol2
                width: 380
                spacing: 10

                Text {
                    text: "导入服务器配置"
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width
                    text: "将导入 " + (srvImportInfo.fresh || 0) + " 台服务器"
                          + ((srvImportInfo.duplicate || 0) > 0
                             ? "（另有 " + srvImportInfo.duplicate
                               + " 台已在列表里，会跳过）" : "")
                    color: Theme.ok
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: (srvImportInfo.names || []).length > 0
                    text: (srvImportInfo.names || []).join("\n")
                    color: Theme.textMute
                    font.family: Theme.monoFont
                    font.pixelSize: 10
                    lineHeight: 1.4
                    wrapMode: Text.WrapAnywhere
                }
                Text {
                    width: parent.width
                    text: "已有的服务器不会被改动；导入进来的不带面板密码。"
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    wrapMode: Text.WordWrap
                }
                Row {
                    width: parent.width
                    spacing: 8
                    Item { width: Math.max(0, parent.width - 168); height: 1 }
                    ActionButton {
                        width: 76
                        height: 30
                        accent: false
                        label: "取消"
                        onClicked: srvImportConfirm.close()
                    }
                    ActionButton {
                        width: 84
                        height: 30
                        label: "导入"
                        onClicked: {
                            srvImportConfirm.close();
                            core.servers.importConfig(srvImportPath);
                        }
                    }
                }
            }
        }

        // ------------------------------------------------ 选择背景图文件
        FileDialog {
            id: bgDlg
            fileMode: FileDialog.OpenFile
            nameFilters: [
                "图片文件 (*.jpg *.jpeg *.png *.webp *.bmp *.gif)",
                "所有文件 (*)"
            ]
            onAccepted: {
                var s = String(selectedFile);
                if (s.indexOf("file:///") === 0)
                    s = s.substring(8);
                else if (s.indexOf("file://") === 0)
                    s = s.substring(7);
                try { s = decodeURIComponent(s); } catch (e) { }
                core.importBgImage(s);
            }
        }

        // ------------------------------------------------ 内置播放器浮层
        PlayerOverlay {
            id: playerOverlay
            anchors.fill: parent
            open: win.playerOpen
            player: core.player
            z: 270
            onClosed: {
                win.playerOpen = false;
                core.stopVideo();
            }
            onRequestOpenExternal: function (bvid) {
                core.openVideoUrl(bvid);
            }
        }

        // ------------------------------------------------ UP 主小卡片
        AuthorCard {
            id: authorCard
            anchors.fill: parent
            open: win.authorOpen
            author: win.authorInfo
            loading: win.authorLoading
            onClosed: win.authorOpen = false
            onOpenSpace: function (mid) { core.openSpace(mid); }
            onOpenUpload: function (mid) { core.openUploadPage(mid); }
            onOpenVideoDetail: function (bvid) {
                // 点作者名片里的视频 -> 关掉名片，打开该视频的详情面板
                win.authorOpen = false;
                win.openDetail(bvid);
            }
        }

        // ------------------------------------------------ 窗口边缘拖拽调整大小
        MouseArea {
            width: 6
            height: parent.height - 20
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.topMargin: 10
            cursorShape: Qt.SizeHorCursor
            onPressed: win.startSystemResize(Qt.LeftEdge)
        }
        MouseArea {
            width: 6
            height: parent.height - 20
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.topMargin: 10
            cursorShape: Qt.SizeHorCursor
            onPressed: win.startSystemResize(Qt.RightEdge)
        }
        MouseArea {
            height: 6
            width: parent.width - 20
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.leftMargin: 10
            cursorShape: Qt.SizeVerCursor
            onPressed: win.startSystemResize(Qt.BottomEdge)
        }
        // 最后一个孩子：动作提示浮层（必须在最上层，且不吃鼠标）
        ToastLayer {
            id: toastHost
            anchors.fill: parent
        }
    }

    // ---------------------------------------------------------------- 逻辑
    function toast(text, level) {
        toastHost.show(text, level);
    }
    function grabPreview(path) {
        return frame.grabToImage(function (result) {
            result.saveToFile(path);
        });
    }

    // 截图脚本专用：连 Popup 一起抓。
    // frame.grabToImage 抓不到 Popup —— Popup 挂在 window 的 overlay 上，
    // 是 frame 的兄弟节点，不在 frame 的树里。contentItem 才是整窗根。
    function grabWindowShot(path) {
        return contentItem.grabToImage(function (result) {
            result.saveToFile(path);
        });
    }

    // 给截图脚本 / Esc 用：打开、关闭 MOD 页的筛选面板
    function openModFilter() {
        modPanel.openFilterPopup();
    }

    // 给截图脚本用：打开排序面板
    function openModSort() {
        modPanel.openSortPopup();
    }

    // 给截图脚本用：打开视频筛选面板
    function openVidFilter() {
        vidFilterPopup.open();
    }

    function closeVidFilter() {
        if (!vidFilterPopup.opened) return false;
        vidFilterPopup.close();
        return true;
    }

    // 给截图脚本用：切到「选择」模式
    property alias modsSelMode: modPanel.selectMode

    // 筛选面板开着就先收它，返回 true 表示已经处理了
    function closeFilterPopup() {
        return modPanel.closeFilterPopup();
    }

    function toggleMaximized() {
        if (win.maximized) {
            win.showNormal();
            win.maximized = false;
        } else {
            win.showMaximized();
            win.maximized = true;
        }
    }

    function closeDetail() {
        if (win.detailOpen) {
            win.detailOpen = false;
            // 告诉后端「详情关掉了」，后台刷新回来就不必再推界面更新
            core.clearDetail();
        }
    }

    function openDetail(bvid) {
        if (win.section === 5) win.section = 0;
        win.detailVideo = core.findVideo(bvid);
        win.detailOpen = true;
        win.detailLoading = true;
        core.openDetail(bvid);
    }

    function updateBanner() {
        newBanner.y = 78;
        bannerTimer.restart();
    }

    Connections {
        target: core
        function onDetailReady(v) {
            win.detailVideo = v;
            win.detailLoading = false;
        }
        function onDetailFailed(msg) {
            win.detailLoading = false;
        }
        function onAuthorReady(info) {
            win.authorInfo = info;
            win.authorLoading = false;
        }
        function onAuthorFailed(msg) {
            win.authorLoading = false;
        }
        function onNewItemsFound(items) {
            win.pendingNew = items;
            win.updateBanner();
        }
        // 动作型提示：复制 / 导入 / 删除 / 转换… 统一走这个会淡出的浮层
        function onToastRequested(text, level) {
            toastHost.show(text, level);
        }
    }

    // MOD 管理器自己的提示（导入完成、删除、被占用…）
    Connections {
        target: core.mods
        function onToastRequested(text, level) {
            toastHost.show(text, level);
        }
    }

    // 主题色 / 明暗模式：配置里存的值同步进 Theme 单例，全局跟着变。
    // Theme 是 singleton，改一处所有引用它的组件（按钮/进度条/高亮/配色）都实时刷新。
    function syncTheme() {
        Theme.accentBase = core.uiAccent;
        Theme.dark = core.isDark;
    }

    Component.onCompleted: syncTheme()
    Connections {
        target: core
        function onStatusChanged() {
            syncTheme();
        }
    }

    Timer {
        id: bannerTimer
        interval: 9000
        onTriggered: newBanner.y = -100
    }

    Shortcut {
        sequences: ["F5"]
        onActivated: core.scan_now()
    }
    Shortcut {
        sequences: ["Escape"]
        onActivated: {
            if (win.closeVidFilter()) {
                // 视频筛选面板收掉了，这层 Esc 就到此为止
            } else if (win.closeFilterPopup()) {
                // MOD 筛选面板收掉了
            } else if (win.authorOpen) {
                win.authorOpen = false;
            } else if (win.playerOpen) {
                win.playerOpen = false;
                core.stopVideo();
            } else if (win.detailOpen) win.closeDetail();
            else if (win.section === 5) if (win.section === 5) win.section = 0;
            // 下载页是独立一页，Esc 退回视频页（和别的覆盖层不同，它占满整块）
            else if (win.section === 4) win.section = 0;
        }
    }
    Shortcut {
        sequences: ["Space"]
        enabled: win.playerOpen
        onActivated: core.player.togglePlay()
    }
    Shortcut {
        sequences: ["Left"]
        enabled: win.playerOpen
        onActivated: core.player.seekRelative(-10000)
    }
    Shortcut {
        sequences: ["Right"]
        enabled: win.playerOpen
        onActivated: core.player.seekRelative(10000)
    }
    Shortcut {
        sequences: ["Up"]
        enabled: win.playerOpen
        onActivated: core.player.changeVolume(10)
    }
    Shortcut {
        sequences: ["Down"]
        enabled: win.playerOpen
        onActivated: core.player.changeVolume(-10)
    }
    Shortcut {
        sequences: ["Ctrl+F"]
        onActivated: {
            // 在服务器页就聚焦那页自己的搜索框（那里能搜名字/地址/地图/模式），
            // 别的页还是老行为：回视频页、清掉「只看新的」。
            if (win.section === 3) {
                if (serversPageItem)
                    serversPageItem.focusSearch()
                return;
            }
            // 下载页没有搜索框，Ctrl+F 不该把用户踢回视频页
            if (win.section === 4)
                return;
            win.page = 0;
            core.setShowOnlyNew(false);
        }
    }

    // Ctrl+J：直接切到下载页（和浏览器「下载」的键位一致，肌肉记忆）
    Shortcut {
        sequences: ["Ctrl+J"]
        onActivated: {
            win.section = win.section === 4 ? 0 : 4;
            if (win.section === 5) win.section = 0;
        }
    }
}
