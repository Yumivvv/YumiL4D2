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

// 色盘：HSV 色相环 + 明度条 + 饱和度条，点哪里选哪里。
//
// 为什么自己做而不是用 QtQuick.Dialogs 的 ColorDialog：
//   * 系统取色框是 Windows 原生窗口，风格和这个程序完全不搭（一开就像切了个软件）；
//   * 它返回的是**模态阻塞**结果，而这个程序的设置面板是覆盖层，模态框会顶在最上面，
//     关掉之后覆盖层焦点容易乱；
//   * 我们只要「点一下换个主题色」，自己画一个几十行就够，还能顺带保留 RGB 微调。
//
// 交互：
//   · 点色盘任意位置 → 取该点的色相/饱和度
//   · 拖明度条 → 调整亮度
//   · 下面的输入框可以直接敲 hex，或者拖 R/G/B 三条微调
// 所有改动都通过 `picked(color)` 实时抛给外面，所见即所得。
Item {
    id: picker
    objectName: "accentWheel"

    property color current: "#FF4D57"
    signal picked(color c)
    signal released()          // 松手：这时才该落盘（拖动中只做预览）

    // 把当前 HSV 落成 #RRGGBB 交给 Core 存下来。
    // 由外面的 onReleased 调一次 —— 拖动过程中每一步都写 config.json 会明显卡顿。
    function commit() {
        var c = Qt.hsva(picker.hue, picker.sat, picker.val, 1.0);
        var h = "0123456789ABCDEF";
        function b(n) {
            var x = Math.max(0, Math.min(255, Math.round(n * 255)));
            return h.charAt(Math.floor(x / 16)) + h.charAt(x % 16);
        }
        var r = c.r * 255, g = c.g * 255, bl = c.b * 255;
        core.setAccent(Math.round(r), Math.round(g), Math.round(bl));
    }

    // 内部用 HSV 存，避免 RGB↔HSV 反复转换丢精度
    property real hue: 0.98
    property real sat: 0.70
    property real val: 1.0

    // 外部改了 current（预设色 / 恢复默认）时，把 HSV 同步回来
    function syncFromColor(c) {
        var h = c.hsvHue < 0 ? 0 : c.hsvHue;
        picker.hue = h;
        picker.sat = c.hsvSaturation;
        picker.val = c.hsvValue;
    }

    function emitColor() {
        var c = Qt.hsva(picker.hue, picker.sat, picker.val, 1.0);
        picker.picked(c);
    }

    onCurrentChanged: {
        // 只有和当前 HSV 算出来的颜色不一致时才回灌，避免拖动时打架
        var mine = Qt.hsva(picker.hue, picker.sat, picker.val, 1.0);
        if (Math.abs(mine.r - current.r) > 0.004
                || Math.abs(mine.g - current.g) > 0.004
                || Math.abs(mine.b - current.b) > 0.004)
            picker.syncFromColor(current);
    }

    Component.onCompleted: picker.syncFromColor(picker.current)

    implicitWidth: 268
    implicitHeight: 200

    // ---------------------------------------------------------- 色盘本体
    // 用 Canvas 画：每像素按 (角度=色相, 半径=饱和度) 上色，中心白、边缘纯色。
    // 比堆一堆 Rectangle 便宜得多，也才画得圆。
    Item {
        id: wheelBox
        width: 156
        height: 156
        anchors.left: parent.left
        anchors.top: parent.top

        Canvas {
            id: wheelCanvas
            anchors.fill: parent
            onPaint: {
                var ctx = getContext("2d");
                ctx.reset();
                var cx = width / 2, cy = height / 2;
                var rad = Math.min(cx, cy) - 2;
                // 逐「小方块」画而不是 getImageData/putImageData ——
                // 像素级 ImageData 在部分 Qt 版本里画出来是全黑（实测），
                // 用 fillRect 铺 2px 小格既稳又快（78×78 次调用，只在重绘时算一次）。
                var step = 2;
                for (var y = 0; y < height; y += step) {
                    for (var x = 0; x < width; x += step) {
                        var dx = x + step / 2 - cx;
                        var dy = y + step / 2 - cy;
                        var dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist > rad)
                            continue;
                        var ang = Math.atan2(dy, dx) / (2 * Math.PI);
                        if (ang < 0) ang += 1;
                        var s = Math.min(1, dist / rad);
                        var c = Qt.hsva(ang, s, picker.val, 1.0);
                        ctx.fillStyle = c;
                        ctx.fillRect(x, y, step, step);
                    }
                }
                // 外圈描边，暗色主题下才看得清边界
                ctx.beginPath();
                ctx.arc(cx, cy, rad, 0, Math.PI * 2);
                ctx.strokeStyle = Qt.rgba(1, 1, 1, Theme.dark ? 0.18 : 0.35);
                ctx.lineWidth = 1;
                ctx.stroke();
            }
            // val 变了要重画（色盘亮度跟着变）
            Connections {
                target: picker
                function onValChanged() { wheelCanvas.requestPaint(); }
            }
            Component.onCompleted: requestPaint()
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
        }

        // 选中的位置：一个小圆环
        Rectangle {
            readonly property real rad: Math.min(wheelBox.width, wheelBox.height) / 2 - 2
            readonly property real ang: picker.hue * Math.PI * 2
            readonly property real dist: picker.sat * rad
            x: wheelBox.width / 2 + Math.cos(ang) * dist - width / 2
            y: wheelBox.height / 2 + Math.sin(ang) * dist - height / 2
            width: 12
            height: 12
            radius: 6
            color: "transparent"
            border.width: 2
            border.color: "#ffffff"
            // 外面再套一圈深色，浅色主题下也看得见
            Rectangle {
                anchors.fill: parent
                anchors.margins: -1
                radius: width / 2
                color: "transparent"
                border.width: 1
                border.color: Qt.rgba(0, 0, 0, 0.4)
                z: -1
            }
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.CrossCursor
            function pick(mx, my) {
                var cx = wheelBox.width / 2, cy = wheelBox.height / 2;
                var dx = mx - cx, dy = my - cy;
                var rad = Math.min(cx, cy) - 2;
                var dist = Math.min(rad, Math.sqrt(dx * dx + dy * dy));
                var ang = Math.atan2(dy, dx) / (2 * Math.PI);
                if (ang < 0) ang += 1;
                picker.hue = ang;
                picker.sat = rad > 0 ? dist / rad : 0;
                picker.emitColor();
            }
            onPressed: function (m) { pick(m.x, m.y); }
            onPositionChanged: function (m) { if (pressed) pick(m.x, m.y); }
            onReleased: picker.released()
        }
    }

    // ---------------------------------------------------------- 明度条
    Item {
        id: valBox
        anchors.left: wheelBox.right
        anchors.leftMargin: 10
        anchors.top: parent.top
        width: 22
        height: 156

        Rectangle {
            anchors.fill: parent
            radius: 6
            border.width: 1
            border.color: Theme.border
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: Qt.hsva(picker.hue, picker.sat, 1.0, 1.0) }
                GradientStop { position: 1.0; color: "#000000" }
            }
        }

        // 当前明度的位置
        Rectangle {
            y: (1 - picker.val) * (valBox.height - 6)
            width: valBox.width + 4
            x: -2
            height: 6
            radius: 3
            color: "transparent"
            border.width: 2
            border.color: "#ffffff"
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.SizeVerCursor
            function setVal(my) {
                picker.val = Math.max(0.05, Math.min(1.0, 1 - my / valBox.height));
                picker.emitColor();
            }
            onPressed: function (m) { setVal(m.y); }
            onPositionChanged: function (m) { if (pressed) setVal(m.y); }
            onReleased: picker.released()
        }
    }

    // ---------------------------------------------------------- 预览 + hex
    Column {
        anchors.left: valBox.right
        anchors.leftMargin: 12
        anchors.top: parent.top
        spacing: 8

        Rectangle {
            width: 54
            height: 54
            radius: 10
            color: Theme.accent
            border.width: 1
            border.color: Theme.borderHi
            Text {
                anchors.centerIn: parent
                text: "Aa"
                color: "#ffffff"
                font.family: Theme.uiFont
                font.pixelSize: 16
                font.bold: true
            }
        }
        Text {
            text: core.uiAccent.toUpperCase()
            color: Theme.textDim
            font.family: Theme.monoFont
            font.pixelSize: 10
        }
    }

    // ---------------------------------------------------------- RGB 微调
    // 保留三条滑块：色盘选不准「差一点点」的时候，拖 RGB 更直接
    Column {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: wheelBox.bottom
        anchors.topMargin: 10
        spacing: 4

        ChannelSlider { label: "R"; index: 0; width: parent.width; height: 18 }
        ChannelSlider { label: "G"; index: 1; width: parent.width; height: 18 }
        ChannelSlider { label: "B"; index: 2; width: parent.width; height: 18 }
    }
}
