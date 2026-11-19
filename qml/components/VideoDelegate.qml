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
import L4D2

// 列表行
Item {
    id: del
    width: ListView.view ? ListView.view.width : 600
    height: 124

    required property int index
    required property string bvid
    required property string title
    required property string author
    required property string pubRel
    required property string duration
    required property string playText
    required property string danmakuText
    required property string coverUrl
    required property bool isNew
    required property string descSnippet
    required property string pubText

    // 鼠标是否落在右侧图标区。图标自带 hoverEnabled 的 MouseArea，
    // 鼠标移上去时 rowHover 会失去 hover，若不单独记录就会导致图标闪烁消失。
    property bool hoveringAction: playMa.containsMouse || linkMa.containsMouse || seenMa.containsMouse

    // 整行 hover：行体或右侧图标区任一处都算
    property bool hovered: rowHover.containsMouse || hoveringAction
    signal clickedItem(string bvid)
    signal playItem(string bvid)
    signal copyItem(string bvid)
    signal seenItem(string bvid)

    Rectangle {
        id: rowBg
        anchors.fill: parent
        anchors.margins: 1
        anchors.topMargin: 3
        anchors.bottomMargin: 3
        radius: Theme.radius
        color: del.hovered ? Theme.scrim(0.048)
                           : (del.isNew ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.055)
                                        : "transparent")
        border.width: 1
        border.color: del.hovered ? Theme.borderHi
                                  : (del.isNew ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.22)
                                               : "transparent")
        Behavior on color { ColorAnimation { duration: 120 } }
        Behavior on border.color { ColorAnimation { duration: 120 } }

        Rectangle {
            width: 3
            height: parent.height - 24
            anchors.left: parent.left
            anchors.leftMargin: 2
            anchors.verticalCenter: parent.verticalCenter
            radius: 2
            visible: del.isNew
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0; color: Theme.accent }
                GradientStop { position: 1; color: Theme.pink }
            }
        }
    }

    // 铺满整行的 hover 探测（最底层，不会挡住上面按钮的点击）
    MouseArea {
        id: rowHover
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton
        cursorShape: Qt.PointingHandCursor
        onClicked: del.clickedItem(del.bvid)
    }

    Row {
        anchors.fill: parent
        anchors.leftMargin: 12
        // 右侧给操作按钮留出空间
        anchors.rightMargin: 52
        anchors.topMargin: 10
        anchors.bottomMargin: 10
        spacing: 14

        // ---------------- 封面 ----------------
        Item {
            width: 184
            height: 104
            anchors.verticalCenter: parent.verticalCenter

            Rectangle {
                id: coverBox
                anchors.fill: parent
                radius: Theme.radiusS
                color: Theme.surfaceSoft
                clip: true

                Image {
                    id: coverImg
                    anchors.fill: parent
                    source: del.coverUrl
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    cache: true
                    smooth: true
                    opacity: status === Image.Ready ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 260 } }
                    scale: del.hovered ? 1.05 : 1.0
                    Behavior on scale { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
                }

                Text {
                    anchors.centerIn: parent
                    visible: coverImg.status !== Image.Ready
                    text: "\uE714"
                    font.family: Theme.iconFont
                    font.pixelSize: 22
                    color: Theme.textMute
                    opacity: 0.45
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 30
                    gradient: Gradient {
                        orientation: Gradient.Vertical
                        GradientStop { position: 0; color: "transparent" }
                        GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.72) }
                    }
                }

                Rectangle {
                    visible: del.duration.length > 0
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 5
                    height: 17
                    width: durTxt.implicitWidth + 10
                    radius: 4
                    color: Qt.rgba(0, 0, 0, 0.66)
                    Text {
                        id: durTxt
                        anchors.centerIn: parent
                        text: del.duration
                        font.family: Theme.monoFont
                        font.pixelSize: 10
                        color: "#E8EBF2"
                    }
                }

                Rectangle {
                    visible: del.isNew
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.margins: 5
                    height: 18
                    width: newTxt.implicitWidth + 12
                    radius: 4
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: Theme.accent }
                        GradientStop { position: 1; color: Theme.pink }
                    }
                    Text {
                        id: newTxt
                        anchors.centerIn: parent
                        text: "NEW"
                        font.family: Theme.uiFont
                        font.pixelSize: 9
                        font.weight: Font.Black
                        color: "#ffffff"
                    }
                }

                // 悬停播放遮罩
                Rectangle {
                    anchors.fill: parent
                    radius: Theme.radiusS
                    color: Qt.rgba(0, 0, 0, 0.30)
                    opacity: del.hovered ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 140 } }
                    Text {
                        anchors.centerIn: parent
                        text: "\uE768"
                        font.family: Theme.iconFont
                        font.pixelSize: 26
                        color: "#ffffff"
                        opacity: 0.92
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: del.playItem(del.bvid)
                    }
                }
            }
        }

        // ---------------- 文字区 ----------------
        Column {
            width: parent.width - 184 - 14
            anchors.verticalCenter: parent.verticalCenter
            spacing: 7

            Text {
                width: parent.width
                text: del.title
                color: del.hovered ? "#ffffff" : Theme.text
                font.family: Theme.uiFont
                font.pixelSize: 14
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                maximumLineCount: 2
                wrapMode: Text.Wrap
                lineHeight: 1.25
                height: Math.min(implicitHeight, 38)
                Behavior on color { ColorAnimation { duration: 120 } }
            }

            Text {
                width: parent.width
                visible: del.descSnippet.length > 0
                text: del.descSnippet
                color: Theme.textMute
                font.family: Theme.uiFont
                font.pixelSize: 11
                elide: Text.ElideRight
                maximumLineCount: 1
                wrapMode: Text.NoWrap
            }

            Item { width: 1; height: 2 }

            Item {
                width: parent.width
                height: 18

                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 10

                    Row {
                        spacing: 4
                        anchors.verticalCenter: parent.verticalCenter
                        Text {
                            text: "\uE77B"
                            font.family: Theme.iconFont
                            font.pixelSize: 11
                            color: Theme.textMute
                        }
                        Text {
                            text: del.author
                            color: Theme.textDim
                            font.family: Theme.uiFont
                            font.pixelSize: 12
                        }
                    }
                    Text {
                        text: "·"
                        color: Theme.textMute
                        font.pixelSize: 11
                    }
                    Text {
                        text: del.pubRel
                        color: del.isNew ? Theme.accent : Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                        font.weight: del.isNew ? Font.DemiBold : Font.Normal
                    }
                    Text {
                        text: "·"
                        color: Theme.textMute
                        font.pixelSize: 11
                    }
                    Text {
                        text: "播放 " + del.playText
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                    }
                    Text {
                        text: "弹幕 " + del.danmakuText
                        color: Theme.textMute
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                    }
                }
            }
        }
    }

    // ---------------- 右侧快捷操作 ----------------
    // 始终占位（不是 hover 才显示），只在 hover 时改变透明度，避免"鼠标过去就没了"
    Item {
        id: actionBar
        width: 30
        height: 84
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter

        opacity: del.hovered ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: 120 } }
        visible: opacity > 0.01


        Column {
            anchors.fill: parent
            spacing: 4

            Rectangle {
                width: 28
                height: 24
                radius: 6
                color: playMa.pressed ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.34)
                                      : (playMa.containsMouse ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.22)
                                                              : Theme.scrim(0.06))
                Text {
                    anchors.centerIn: parent
                    text: "\uE8A7"
                    font.family: Theme.iconFont
                    font.pixelSize: 11
                    color: (playMa.containsMouse || playMa.pressed) ? Theme.accent : Theme.textDim
                }
                MouseArea {
                    id: playMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: del.clickedItem(del.bvid)
                }
            }

            Rectangle {
                width: 28
                height: 24
                radius: 6
                color: linkMa.pressed ? Theme.scrim(0.18)
                                      : (linkMa.containsMouse ? Theme.scrim(0.12) : Theme.scrim(0.06))
                Text {
                    anchors.centerIn: parent
                    text: "\uE71B"
                    font.family: Theme.iconFont
                    font.pixelSize: 11
                    color: linkMa.containsMouse ? Theme.text : Theme.textDim
                }
                MouseArea {
                    id: linkMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: del.copyItem(del.bvid)
                }
            }

            Rectangle {
                width: 28
                height: 24
                radius: 6
                visible: del.isNew
                color: seenMa.pressed ? Qt.rgba(Theme.ok.r, Theme.ok.g, Theme.ok.b, 0.3)
                                      : (seenMa.containsMouse ? Qt.rgba(Theme.ok.r, Theme.ok.g, Theme.ok.b, 0.2)
                                                              : Theme.scrim(0.06))
                Text {
                    anchors.centerIn: parent
                    text: "\uE73E"
                    font.family: Theme.iconFont
                    font.pixelSize: 11
                    color: seenMa.containsMouse ? Theme.ok : Theme.textDim
                }
                MouseArea {
                    id: seenMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: del.seenItem(del.bvid)
                }
            }
        }
    }
}
