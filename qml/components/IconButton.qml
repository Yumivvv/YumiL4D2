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

Item {
    id: btn
    property string glyph: ""
    property string tip: ""
    property bool active: false
    property bool danger: false
    property bool enabledBtn: true
    property int boxSize: 36
    signal clicked()

    implicitWidth: boxSize
    implicitHeight: boxSize
    opacity: enabledBtn ? 1.0 : 0.4

    // 按下时缩放，给明确的点击手感
    scale: ma.pressed ? 0.92 : (ma.containsMouse ? 1.04 : 1.0)
    Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }

    Rectangle {
        id: bg
        anchors.fill: parent
        radius: Theme.radiusS
        color: ma.pressed
               ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.30)
               : btn.active
                 ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
                 : (ma.containsMouse ? Theme.scrim(0.09) : Theme.scrim(0.025))
        border.width: 1
        border.color: ma.pressed
                      ? Theme.accent
                      : btn.active ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.45)
                                   : (ma.containsMouse ? Theme.borderHi : Theme.border)
        Behavior on color { ColorAnimation { duration: 100 } }
        Behavior on border.color { ColorAnimation { duration: 100 } }

        Text {
            anchors.centerIn: parent
            text: btn.glyph
            font.family: Theme.iconFont
            font.pixelSize: Math.round(btn.boxSize * 0.42)
            color: ma.pressed ? "#ffffff"
                 : btn.danger ? Theme.accent
                 : btn.active ? Theme.accent
                 : (ma.containsMouse ? Theme.text : Theme.textDim)
            Behavior on color { ColorAnimation { duration: 100 } }
        }

        // 点击水波纹
        Rectangle {
            id: ripple
            anchors.centerIn: parent
            width: 0
            height: 0
            radius: width / 2
            color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.35)
            opacity: 0

            ParallelAnimation {
                id: rippleAnim
                NumberAnimation {
                    target: ripple; property: "width"
                    from: 6; to: btn.boxSize * 1.5; duration: 320; easing.type: Easing.OutCubic
                }
                NumberAnimation {
                    target: ripple; property: "height"
                    from: 6; to: btn.boxSize * 1.5; duration: 320; easing.type: Easing.OutCubic
                }
                NumberAnimation {
                    target: ripple; property: "opacity"
                    from: 0.7; to: 0.0; duration: 340
                }
            }
        }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: btn.enabledBtn ? Qt.PointingHandCursor : Qt.ArrowCursor
        enabled: btn.enabledBtn
        onClicked: {
            rippleAnim.restart();
            btn.clicked();
        }
    }

    ToolTip.visible: btn.tip.length > 0 && ma.containsMouse && btn.enabledBtn
    ToolTip.text: btn.tip
    ToolTip.delay: 450
}
