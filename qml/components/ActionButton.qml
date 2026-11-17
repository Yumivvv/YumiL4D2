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

Rectangle {
    id: btn
    property string label: ""
    property string glyph: ""
    property bool accent: true
    property bool enabledBtn: true
    property bool busy: false
    signal clicked()

    implicitHeight: 36
    implicitWidth: contentRow.implicitWidth + 30
    radius: Theme.radiusS
    opacity: enabledBtn ? 1.0 : 0.45

    // 按下缩小 + 变色，点击手感明确
    scale: ma.pressed ? 0.96 : 1.0
    Behavior on scale { NumberAnimation { duration: 100; easing.type: Easing.OutCubic } }

    gradient: Gradient {
        orientation: Gradient.Horizontal
        // 强调色的三种状态全部从 Theme.accentBase 派生。
        // ★ 这里以前写死了 "#FF8087" / "#FF626B" / "#F0404C" / "#FF5A63" 这些红色，
        //   于是用户把主题色改成蓝/紫之后，按钮按下去和悬停时还是红的。
        GradientStop {
            position: 0.0
            color: btn.accent
                   ? (ma.pressed ? Theme.accentPress
                                 : (ma.containsMouse ? Theme.accentHover : Theme.accent))
                   : (ma.pressed ? Theme.scrim(0.14)
                                 : (ma.containsMouse ? Theme.scrim(0.09) : Theme.surface))
        }
        GradientStop {
            position: 1.0
            color: btn.accent
                   ? (ma.pressed ? Qt.darker(Theme.accentPress, 1.06)
                                 : (ma.containsMouse ? Theme.accentDeep : Theme.accentDeep))
                   : (ma.pressed ? Theme.scrim(0.10)
                                 : (ma.containsMouse ? Theme.scrim(0.06) : Theme.surface))
        }
    }
    border.width: btn.accent ? 0 : 1
    border.color: ma.containsMouse ? Theme.borderHi : Theme.border

    Behavior on opacity { NumberAnimation { duration: Theme.anim } }

    Row {
        id: contentRow
        anchors.centerIn: parent
        spacing: 7

        Spinner {
            width: 14
            height: 14
            visible: btn.busy
            anchors.verticalCenter: parent.verticalCenter
            color1: btn.accent ? "#ffffff" : Theme.accent
            // 转圈的第二色也从强调色派生，别写死粉色
            color2: btn.accent ? Theme.alpha(Theme.accentPress, 0.75) : Theme.accentHover
            thickness: 1.8
        }
        Text {
            visible: btn.glyph.length > 0 && !btn.busy
            text: btn.glyph
            font.family: Theme.iconFont
            font.pixelSize: 13
            color: btn.accent ? "#ffffff" : Theme.text
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: btn.busy ? "处理中…" : btn.label
            font.family: Theme.uiFont
            // 固定字号，不要根据 implicitWidth 反推 —— 那样会形成绑定环
            // （font.pixelSize → implicitWidth → font.pixelSize），Qt 会刷警告。
            font.pixelSize: 12
            font.weight: Font.DemiBold
            color: btn.accent ? "#ffffff" : Theme.text
            anchors.verticalCenter: parent.verticalCenter
            // Text 的 implicitWidth 只跟字体和文字有关，与 width 无关，所以这样写安全。
            // 宽度被外部压小时靠 elide 省略，不再缩字号。
            width: btn.width > 0 ? Math.min(implicitWidth, btn.width - 24) : implicitWidth
            elide: Text.ElideRight
            maximumLineCount: 1
        }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: btn.enabledBtn && !btn.busy ? Qt.PointingHandCursor : Qt.ArrowCursor
        enabled: btn.enabledBtn && !btn.busy
        onClicked: btn.clicked()
    }
}
