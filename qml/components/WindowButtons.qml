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

// 窗口按钮组：最小化 / 最大化-还原 / 关闭。
//
// 为什么抽成一个组件：以前**每个页面页头各写了一整套**（视频页、MOD 页、
// 创意工坊页、服务器页共 4 套），于是出现了两个毛病：
//   1. 改一处样式或行为要改 4 遍，漏一处就「这个页面的按钮跟别的不一样」；
//   2. 4 套按钮各自锚在各自页头里，切页时位置会**轻微错位**（各页头的
//      rightMargin 不完全一致），看起来就像「每个界面的按钮是独立的」。
// 现在只在窗口右上角放**一份**，锚在窗口级，任何页面看到的都是同一组。
Item {
    id: group
    objectName: "windowButtons"

    // 由 Main.qml 传进来，避免这个组件反过来依赖 window 的 id
    property var target: null
    property bool maximized: false

    implicitWidth: row.implicitWidth
    implicitHeight: 34

    Row {
        id: row
        anchors.fill: parent
        spacing: 6

        IconButton {
            objectName: "winMinBtn"
            glyph: "\uE921"
            tip: "最小化"
            boxSize: 34
            onClicked: if (group.target) group.target.showMinimized()
        }
        IconButton {
            objectName: "winMaxBtn"
            glyph: group.maximized ? "\uE923" : "\uE922"
            tip: group.maximized ? "还原" : "最大化"
            boxSize: 34
            onClicked: if (group.target) group.target.toggleMaximized()
        }
        IconButton {
            objectName: "winCloseBtn"
            glyph: "\uE8BB"
            tip: "关闭到托盘"
            danger: true
            boxSize: 34
            onClicked: if (group.target) group.target.close()
        }
    }
}
