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

// 圆形进度 / 环形加载
Canvas {
    id: root
    property color color1: Theme.accent
    property color color2: Theme.pink
    property real thickness: Math.max(1.6, width * 0.11)
    property real progress: -1   // <0 表示无限旋转
    property real speed: 1.0
    antialiasing: true

    onPaint: {
        var ctx = getContext("2d");
        var w = root.width, h = root.height;
        var lw = root.thickness;
        var r = Math.min(w, h) / 2 - lw;
        ctx.reset();
        ctx.clearRect(0, 0, w, h);
        ctx.lineWidth = lw;
        ctx.lineCap = "round";
        var grad = ctx.createLinearGradient(0, 0, w, h);
        grad.addColorStop(0, Qt.rgba(root.color1.r, root.color1.g, root.color1.b, 0.15));
        grad.addColorStop(0.55, Qt.rgba(root.color1.r, root.color1.g, root.color1.b, 0.8));
        grad.addColorStop(1, root.color2);
        ctx.strokeStyle = grad;
        ctx.beginPath();
        if (root.progress < 0) {
            ctx.arc(w / 2, h / 2, r, 0, Math.PI * 1.5, false);
        } else {
            ctx.arc(w / 2, h / 2, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * root.progress, false);
        }
        ctx.stroke();
    }

    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onProgressChanged: requestPaint()
    onColor1Changed: requestPaint()
    onColor2Changed: requestPaint()

    RotationAnimator on rotation {
        running: root.visible && root.progress < 0
        from: 0
        to: 360
        // 默认约 2.4 秒一圈。以前是 1.6 秒，小尺寸（14~16px）转起来
        // 会显得很急、像在闪，慢一点更像「在等」而不是「卡住了」。
        duration: 2400 / Math.max(0.1, root.speed)
        loops: Animation.Infinite
    }
}
