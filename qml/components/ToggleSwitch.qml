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
    id: sw
    property bool checked: false
    property string label: ""
    signal toggled(bool value)
    implicitHeight: 22
    implicitWidth: track.width

    Rectangle {
        id: track
        width: 40
        height: 22
        radius: 11
        anchors.verticalCenter: parent.verticalCenter
        color: sw.checked ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.85)
                          : (ma.containsMouse ? Theme.surfaceHi : Theme.surfaceSoft)
        border.width: 1
        border.color: sw.checked ? Theme.accent : Theme.border
        Behavior on color { ColorAnimation { duration: Theme.anim } }

        Rectangle {
            id: knob
            width: 16
            height: 16
            radius: 8
            y: 2
            x: sw.checked ? track.width - width - 3 : 3
            color: sw.checked ? "#ffffff" : Theme.textDim
            Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
            Behavior on color { ColorAnimation { duration: Theme.anim } }
        }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            sw.checked = !sw.checked;
            sw.toggled(sw.checked);
        }
    }
}
