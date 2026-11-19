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

// UP 主小卡片：头像 / 昵称 / 签名 / 近期视频
Item {
    id: root
    property var author: ({})
    property bool open: false
    property bool loading: false

    signal closed()
    signal openSpace(string mid)
    signal openUpload(string mid)
    signal openVideoDetail(string bvid)   // 点视频卡片：打开的是视频详情，不是直接播放
    // 点「关注」：登录了就直接关注/取关；没登录由主窗口弹扫码登录
    signal followRequested(string mid)

    // 当前有没有关注这位 UP 主（主窗口查询后回填）
    property bool following: false

    visible: open
    z: 320

    // 滚轮防穿透：没被接受的滚轮事件会落到下层的视频列表上
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        z: -1
        onWheel: function (wheel) { wheel.accepted = true }
    }

    // 半透明遮罩，点空白关闭
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.55)
        MouseArea {
            anchors.fill: parent
            onClicked: root.closed()
        }
    }

    Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 520)
        height: Math.min(parent.height - 60, contentCol.height + 40)
        radius: Theme.radius
        color: Theme.surface
        border.width: 1
        border.color: Theme.borderHi
        clip: true

        // 吃掉点击，避免误关
        MouseArea { anchors.fill: parent }

        // 顶部渐变装饰
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 88
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.20) }
                GradientStop { position: 1; color: Qt.rgba(Theme.pink.r, Theme.pink.g, Theme.pink.b, 0.10) }
            }
        }

        Column {
            id: contentCol
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 20
            spacing: 14

            // ---------------- 头部 ----------------
            Item {
                width: parent.width
                height: 64

                Rectangle {
                    id: avatar
                    width: 64
                    height: 64
                    radius: 32
                    color: Theme.surfaceSoft
                    border.width: 2
                    border.color: Theme.scrim(0.18)
                    clip: true

                    Image {
                        anchors.fill: parent
                        source: root.author.faceLocal || root.author.face || ""
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        cache: true
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: !root.author.face && !root.author.faceLocal
                        text: "\uE77B"
                        font.family: Theme.iconFont
                        font.pixelSize: 24
                        color: Theme.textMute
                    }
                }

                Column {
                    anchors.left: avatar.right
                    anchors.leftMargin: 14
                    anchors.right: closeBtn.left
                    anchors.rightMargin: 10
                    anchors.verticalCenter: avatar.verticalCenter
                    spacing: 5

                    Text {
                        width: parent.width
                        text: root.author.name || (root.loading ? "加载中…" : "未知 UP 主")
                        color: Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 17
                        font.weight: Font.Bold
                        elide: Text.ElideRight
                    }

                    Text {
                        width: parent.width
                        text: root.author.sign || "这个人很懒，什么都没写"
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                        elide: Text.ElideRight
                        maximumLineCount: 1
                    }

                    Row {
                        spacing: 10
                        Text {
                            text: "粉丝 " + (root.author.fans || 0)
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }
                        Text {
                            visible: (root.author.level || 0) > 0
                            text: "LV" + (root.author.level || 0)
                            color: Theme.warn
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                        }
                        Text {
                            text: "UID " + (root.author.mid || "-")
                            color: Theme.textMute
                            font.family: Theme.monoFont
                            font.pixelSize: 10
                        }
                    }
                }

                IconButton {
                    id: closeBtn
                    anchors.right: parent.right
                    anchors.top: parent.top
                    glyph: "\uE711"
                    tip: "关闭 (Esc)"
                    boxSize: 30
                    onClicked: root.closed()
                }
            }

            // ---------------- 跳转按钮 ----------------
            Row {
                width: parent.width
                spacing: 8

                // 关注：登录了才写得进（没登录点它会弹扫码登录，见主窗口）
                // 已关注时按钮变普通样式、文字改成「已关注」，再点就是取关
                ActionButton {
                    objectName: "authorFollowBtn"
                    label: root.following ? "已关注" : "关注"
                    accent: !root.following
                    width: parent.width * 0.32
                    height: 34
                    enabledBtn: (root.author.mid || 0) > 0
                    onClicked: root.followRequested(String(root.author.mid || ""))
                }
                ActionButton {
                    label: "前往主页"
                    accent: false
                    width: parent.width * 0.32
                    height: 34
                    enabledBtn: (root.author.mid || 0) > 0
                    onClicked: root.openSpace(String(root.author.mid || ""))
                }
                ActionButton {
                    label: "全部投稿"
                    accent: false
                    width: parent.width * 0.32
                    height: 34
                    enabledBtn: (root.author.mid || 0) > 0
                    onClicked: root.openUpload(String(root.author.mid || ""))
                }
            }

            // ---------------- 近期视频 ----------------
            Row {
                width: parent.width
                spacing: 6
                Text {
                    text: "近期视频"
                    color: Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: root.loading ? "加载中…"
                                       : ((root.author.videos || []).length + " 个")
                    color: Theme.textMute
                    font.family: Theme.uiFont
                    font.pixelSize: 10
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            // 2 行 x 3 列
            Grid {
                width: parent.width
                columns: 3
                spacing: 8

                Repeater {
                    model: root.author.videos || []

                    delegate: Rectangle {
                        width: (contentCol.width - 16) / 3
                        height: width * 0.62 + 34
                        radius: Theme.radiusXS
                        color: itemMa.containsMouse ? Theme.scrim(0.08) : Theme.scrim(0.035)
                        border.width: 1
                        border.color: itemMa.containsMouse ? Theme.borderHi : "transparent"
                        clip: true

                        Rectangle {
                            id: thumbBox
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: parent.width * 0.62
                            color: Theme.surfaceSoft
                            clip: true

                            Image {
                                anchors.fill: parent
                                source: modelData.cover || ""
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                cache: true
                                opacity: status === Image.Ready ? 1 : 0
                                Behavior on opacity { NumberAnimation { duration: 200 } }
                            }

                            Rectangle {
                                visible: (modelData.duration || "").length > 0
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.margins: 4
                                height: 15
                                width: durTxt.implicitWidth + 8
                                radius: 3
                                color: Qt.rgba(0, 0, 0, 0.7)
                                Text {
                                    id: durTxt
                                    anchors.centerIn: parent
                                    text: modelData.duration || ""
                                    color: "#E8EBF2"
                                    font.family: Theme.monoFont
                                    font.pixelSize: 9
                                }
                            }
                        }

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 6
                            anchors.right: parent.right
                            anchors.rightMargin: 6
                            anchors.top: thumbBox.bottom
                            anchors.topMargin: 5
                            text: modelData.title || ""
                            color: Theme.text
                            font.family: Theme.uiFont
                            font.pixelSize: 10
                            elide: Text.ElideRight
                            maximumLineCount: 2
                            wrapMode: Text.Wrap
                            lineHeight: 1.2
                            height: 26
                        }

                        MouseArea {
                            id: itemMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.openVideoDetail(modelData.bvid || "")
                        }
                    }
                }
            }

            // 空状态
            Text {
                width: parent.width
                visible: !root.loading && (root.author.videos || []).length === 0
                text: "暂时没取到这个 UP 主的近期视频\n点上面的「全部投稿」可以直接去 B 站看"
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
                horizontalAlignment: Text.AlignHCenter
                lineHeight: 1.6
            }
        }
    }
}
