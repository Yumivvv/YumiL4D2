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

/* 主题色调色用的单通道（R/G/B）滑块
   - 拖动时走 core.previewAccent（实时变色、不写盘）
   - 松手走 core.setAccent（落盘）
   - 当前值直接从 core.uiAccent 解析，所以「恢复默认」/预设色点也能让手柄跟着动
*/
Item {
    id: cs
    property string label: "R"
    property int index: 0          // 0=R 1=G 2=B
    height: 24

    function cur() {
        var h = core.uiAccent;
        var v = parseInt(h.substr(1 + index * 2, 2), 16);
        return isNaN(v) ? 0 : v;
    }

    function rgbOf(v) {
        var h = core.uiAccent;
        var r = parseInt(h.substr(1, 2), 16) || 0;
        var g = parseInt(h.substr(3, 2), 16) || 0;
        var b = parseInt(h.substr(5, 2), 16) || 0;
        if (index === 0) r = v;
        else if (index === 1) g = v;
        else b = v;
        return [r, g, b];
    }

    function colorOf(v) {
        // 用 #RRGGBB 字符串而不是 Qt.rgb —— 本工程的 QML 运行时里 Qt.rgb 会被判成
        // “不是函数”（Qt.rgba 却正常），字符串拼接最稳。
        var c = rgbOf(v);
        var h = "0123456789ABCDEF";
        function b(n) {
            var x = Math.max(0, Math.min(255, n));
            return h.charAt(Math.floor(x / 16)) + h.charAt(x % 16);
        }
        return "#" + b(c[0]) + b(c[1]) + b(c[2]);
    }

    Row {
        anchors.fill: parent
        spacing: 8

        Text {
            text: cs.label
            width: 12
            color: Theme.textDim
            font.family: Theme.monoFont
            font.pixelSize: 11
            anchors.verticalCenter: parent.verticalCenter
        }

        Item {
            width: Math.max(0, parent.width - 12 - 34 - 16)
            height: parent.height

            Rectangle {
                id: track
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                height: 6
                radius: 3
                // 渐变直接画「这个通道从 0 到 255」的真实颜色，调起来直观
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: cs.colorOf(0) }
                    GradientStop { position: 1.0; color: cs.colorOf(255) }
                }

                Rectangle {
                    x: Math.max(0, track.width * (cs.cur() / 255) - width / 2)
                    anchors.verticalCenter: parent.verticalCenter
                    width: csMa.pressed ? 12 : 10
                    height: width
                    radius: width / 2
                    color: "#ffffff"
                    border.width: 2
                    border.color: Theme.borderHi
                    Behavior on width { NumberAnimation { duration: 90 } }
                }

                MouseArea {
                    id: csMa
                    anchors.fill: parent
                    anchors.topMargin: -9
                    anchors.bottomMargin: -9
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor

                    function applyAt(x) {
                        var r = Math.max(0, Math.min(1, x / track.width));
                        var v = Math.round(r * 255);
                        var c = cs.rgbOf(v);
                        core.previewAccent(c[0], c[1], c[2]);
                    }
                    onPressed: function (m) { applyAt(m.x); }
                    onPositionChanged: function (m) {
                        if (pressed) applyAt(m.x);
                    }
                    onReleased: function (m) {
                        var c = cs.rgbOf(cs.cur());
                        core.setAccent(c[0], c[1], c[2]);
                    }
                }
            }
        }

        Text {
            width: 34
            horizontalAlignment: Text.AlignRight
            text: cs.cur()
            color: Theme.textDim
            font.family: Theme.monoFont
            font.pixelSize: 11
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
