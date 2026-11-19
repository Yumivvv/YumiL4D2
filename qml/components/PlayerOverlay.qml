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
import QtMultimedia
import L4D2

// 内置播放器：视频画面 + 控制条
Item {
    id: root
    property bool open: false
    property var player: null          // app.player.VideoPlayer
    property string errorMsg: ""

    signal closed()
    signal requestOpenExternal(string bvid)

    visible: open
    z: 300

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.86)
        MouseArea {
            anchors.fill: parent
            onClicked: root.closed()
        }
    }

    Rectangle {
        id: stage
        anchors.centerIn: parent
        // 舞台按 16:9 视频比例算，高度 = 宽度 * 9/16 + 控制条，画面正好铺满不留黑边
        readonly property real controlH: 56
        width: Math.min(parent.width - 80, 1080)
        height: Math.min(parent.height - 60, width * 9 / 16 + controlH)
        radius: Theme.radius
        color: "#05070A"
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.10)
        clip: true

        // 吃掉点击，避免点到背景就关掉播放器
        MouseArea {
            anchors.fill: parent
        }

        // ---------------- 视频画面 ----------------
        // 放在最底层（z:0），用 PreserveAspectCrop 铺满，避免出现黑边与压住控件
        Rectangle {
            id: videoArea
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: controls.top
            color: "#000000"
            clip: true
            z: 0

            VideoOutput {
                id: videoOut
                anchors.fill: parent
                fillMode: VideoOutput.PreserveAspectCrop

                Component.onCompleted: {
                    if (root.player)
                        root.player.attachOutput(videoOut.videoSink);
                }
            }
        }

        // ---------------- 顶部信息条 ----------------
        Rectangle {
            id: topBar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 46
            color: Qt.rgba(0, 0, 0, 0.55)
            z: 10

            Row {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.right: closeBtn.left
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8

                Text {
                    text: "\uE768"
                    font.family: Theme.iconFont
                    font.pixelSize: 12
                    color: Theme.accent
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    width: Math.min(implicitWidth, stage.width - 300)
                    text: root.player ? root.player.title : ""
                    color: Theme.text
                    font.family: Theme.uiFont
                    font.pixelSize: 13
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            IconButton {
                id: closeBtn
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                glyph: "\uE711"
                tip: "关闭 (Esc)"
                boxSize: 30
                onClicked: root.closed()
            }
        }

        // ---------------- 加载 / 错误 ----------------
        Item {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: topBar.bottom
            anchors.bottom: controls.top
            visible: root.player && (root.player.loading || !root.player.ready)
            z: 8

            Column {
                anchors.centerIn: parent
                spacing: 14

                Spinner {
                    width: 42
                    height: 42
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: root.player && root.player.loading
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.min(implicitWidth, stage.width - 140)
                    horizontalAlignment: Text.AlignHCenter
                    visible: root.player && root.player.loading
                    text: "正在获取视频流并缓存，首次播放需要等一下…"
                    color: Theme.textDim
                    font.family: Theme.uiFont
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }

                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.min(errText.implicitWidth + 36, stage.width - 140)
                    height: 36
                    radius: Theme.radiusS
                    visible: root.player && !root.player.loading && !root.player.ready
                                   && root.errorMsg.length > 0
                    color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
                    border.width: 1
                    border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.4)

                    Text {
                        id: errText
                        anchors.centerIn: parent
                        width: parent.width - 20
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                        text: root.errorMsg
                        color: Theme.accent
                        font.family: Theme.uiFont
                        font.pixelSize: 11
                    }
                }

                ActionButton {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: root.player && !root.player.loading && !root.player.ready
                    label: "在浏览器中打开"
                    width: 164
                    onClicked: root.requestOpenExternal(root.player ? root.player.bvid : "")
                }
            }
        }

        // ---------------- 控制条 ----------------
        Rectangle {
            id: controls
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: stage.controlH
            color: Qt.rgba(0.03, 0.04, 0.06, 0.92)
            z: 10

            Item {
                id: seekBar
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                height: 16

                readonly property real ratio: (root.player && root.player.duration > 0)
                                              ? Math.max(0, Math.min(1, root.player.position / root.player.duration))
                                              : 0

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width
                    height: 4
                    radius: 2
                    color: Qt.rgba(1, 1, 1, 0.14)

                    Rectangle {
                        width: parent.width * seekBar.ratio
                        height: parent.height
                        radius: 2
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: Theme.accent }
                            GradientStop { position: 1; color: Theme.pink }
                        }
                    }

                    Rectangle {
                        x: parent.width * seekBar.ratio - width / 2
                        anchors.verticalCenter: parent.verticalCenter
                        width: seekMa.containsMouse || seekMa.pressed ? 12 : 9
                        height: width
                        radius: width / 2
                        color: "#ffffff"
                        border.width: 2
                        border.color: Theme.accent
                        Behavior on width { NumberAnimation { duration: 100 } }
                    }
                }

                MouseArea {
                    id: seekMa
                    anchors.fill: parent
                    anchors.topMargin: -5
                    anchors.bottomMargin: -5
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    enabled: root.player && root.player.duration > 0
                    onClicked: function (m) {
                        if (!root.player) return;
                        root.player.seek(Math.round((m.x / seekBar.width) * root.player.duration));
                    }
                }
            }

            Row {
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 9
                spacing: 6

                Rectangle {
                    width: 32
                    height: 32
                    radius: 16
                    color: playMa.pressed ? Theme.accentDeep
                                          : (playMa.containsMouse ? Theme.accent : Qt.rgba(1, 1, 1, 0.10))
                    Behavior on color { ColorAnimation { duration: 110 } }
                    scale: playMa.pressed ? 0.9 : 1.0
                    Behavior on scale { NumberAnimation { duration: 90 } }

                    Text {
                        anchors.centerIn: parent
                        text: (root.player && root.player.playing) ? "\uE769" : "\uE768"
                        font.family: Theme.iconFont
                        font.pixelSize: 12
                        color: "#ffffff"
                    }
                    MouseArea {
                        id: playMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: if (root.player) root.player.togglePlay()
                    }
                }

                IconButton {
                    glyph: "\uE892"
                    tip: "后退 10 秒"
                    boxSize: 30
                    enabledBtn: root.player && root.player.ready
                    onClicked: if (root.player) root.player.seekRelative(-10000)
                }
                IconButton {
                    glyph: "\uE893"
                    tip: "前进 10 秒"
                    boxSize: 30
                    enabledBtn: root.player && root.player.ready
                    onClicked: if (root.player) root.player.seekRelative(10000)
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: (root.player ? root.player.positionText : "0:00") + " / "
                          + (root.player ? root.player.durationText : "0:00")
                    color: Theme.textDim
                    font.family: Theme.monoFont
                    font.pixelSize: 11
                }
            }

            Row {
                anchors.right: parent.right
                anchors.rightMargin: 14
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 9
                spacing: 6

                Item {
                    height: 30
                    width: 46
                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radiusXS
                        color: rateMa.pressed ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.3)
                                              : (rateMa.containsMouse ? Qt.rgba(1, 1, 1, 0.10)
                                                                      : Qt.rgba(1, 1, 1, 0.05))
                        Text {
                            anchors.centerIn: parent
                            text: (root.player ? root.player.rate.toFixed(1) : "1.0") + "x"
                            color: rateMa.containsMouse ? Theme.text : Theme.textDim
                            font.family: Theme.monoFont
                            font.pixelSize: 11
                        }
                    }
                    MouseArea {
                        id: rateMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (!root.player) return;
                            var seq = [1.0, 1.25, 1.5, 2.0, 0.75];
                            var cur = Math.round(root.player.rate * 100) / 100;
                            var idx = seq.findIndex(function (v) { return Math.abs(v - cur) < 0.01; });
                            root.player.setRate(seq[(idx + 1) % seq.length]);
                        }
                    }
                }

                // 音量：喇叭 + 滑块，**常驻显示**，不靠悬停。
                // 只有一个喇叭图标（以前 IconButton 一颗、滑块里又一颗，等于两个）。
                // 点喇叭 = 静音/取消静音；拖滑块 = 调音量。
                Row {
                    id: volBox
                    height: 30
                    spacing: 6

                    // 喇叭按钮（唯一的一个）
                    Item {
                        width: 26
                        height: 30
                        anchors.verticalCenter: parent.verticalCenter

                        Text {
                            anchors.centerIn: parent
                            text: (root.player && root.player.muted) ? "\uE74F" : "\uE767"
                            font.family: Theme.iconFont
                            font.pixelSize: 12
                            color: volMa.containsMouse ? Theme.text
                                                       : ((root.player && root.player.muted)
                                                          ? Theme.textMute : Theme.textDim)
                        }
                        MouseArea {
                            id: volMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: if (root.player) root.player.toggleMute()
                        }
                    }

                    // 滑块（一直显示）
                    Item {
                        id: volSliderBox
                        width: 82
                        height: 30
                        anchors.verticalCenter: parent.verticalCenter

                        Rectangle {
                            id: volTrack
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width
                            height: 4
                            radius: 2
                            color: Qt.rgba(1, 1, 1, 0.16)

                            // 已播放部分
                            Rectangle {
                                width: parent.width * (root.player ? root.player.volume / 100 : 0.8)
                                height: parent.height
                                radius: 2
                                color: (root.player && root.player.muted)
                                       ? Qt.rgba(1, 1, 1, 0.30)
                                       : Theme.accent
                                Behavior on width { NumberAnimation { duration: 70 } }
                            }
                            // 手柄
                            Rectangle {
                                x: parent.width * (root.player ? root.player.volume / 100 : 0.8) - width / 2
                                anchors.verticalCenter: parent.verticalCenter
                                width: volDrag.pressed ? 11 : 9
                                height: width
                                radius: width / 2
                                color: "#ffffff"
                                border.width: 2
                                border.color: Theme.accent
                                Behavior on width { NumberAnimation { duration: 90 } }
                            }

                            MouseArea {
                                id: volDrag
                                anchors.fill: parent
                                anchors.topMargin: -12
                                anchors.bottomMargin: -12
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor

                                function applyAt(x) {
                                    if (!root.player)
                                        return;
                                    var r = Math.max(0, Math.min(1, x / volTrack.width));
                                    root.player.previewVolume(Math.round(r * 100));
                                }
                                onPressed: function (m) { applyAt(m.x); }
                                onPositionChanged: function (m) {
                                    if (pressed) applyAt(m.x);
                                }
                                onReleased: function (m) {
                                    // 松手才落盘，避免拖动时反复写配置
                                    if (root.player)
                                        root.player.setVolume(root.player.volume);
                                }
                            }
                        }
                    }

                    // 音量百分比数字（小，跟滑块一起常驻）
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 24
                        horizontalAlignment: Text.AlignRight
                        text: (root.player && root.player.muted)
                              ? "静音"
                              : (root.player ? String(root.player.volume) : "80")
                        color: (root.player && root.player.muted) ? Theme.textMute : Theme.textDim
                        font.family: Theme.monoFont
                        font.pixelSize: 10
                    }
                }

                IconButton {
                    glyph: "\uE8A7"
                    tip: "在浏览器中打开"
                    boxSize: 30
                    onClicked: root.requestOpenExternal(root.player ? root.player.bvid : "")
                }
            }
        }
    }

    Connections {
        target: root.player
        ignoreUnknownSignals: true
        function onErrorOccurred(msg) { root.errorMsg = msg; }
        function onStateChanged() { }
    }

    readonly property bool playing: root.player ? root.player.playing : false
}
