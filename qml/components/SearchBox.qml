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

Rectangle {
    id: box
    property alias text: field.text
    property string placeholder: "搜索…"
    property string glyph: "\uE721"
    property int editHeight: 36
    signal accepted()
    signal cleared()
    signal edited(string value)

    implicitHeight: editHeight
    radius: Theme.radiusS
    color: Theme.surfaceSoft
    border.width: 1
    border.color: field.activeFocus ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.55) : Theme.border
    Behavior on border.color { ColorAnimation { duration: Theme.anim } }

    Row {
        anchors.fill: parent
        anchors.leftMargin: 11
        anchors.rightMargin: 8
        spacing: 7

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: box.glyph
            font.family: Theme.iconFont
            font.pixelSize: 13
            color: field.activeFocus ? Theme.accent : Theme.textMute
            Behavior on color { ColorAnimation { duration: Theme.anim } }
        }

        TextField {
            id: field
            width: parent.width - 60
            height: parent.height
            verticalAlignment: TextInput.AlignVCenter
            color: Theme.text
            placeholderText: box.placeholder
            placeholderTextColor: Theme.textMute
            selectionColor: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.45)
            selectedTextColor: "#ffffff"
            font.family: Theme.uiFont
            font.pixelSize: 13
            background: null
            padding: 0
            onTextChanged: box.edited(text)
            onAccepted: box.accepted()
            Keys.onEscapePressed: {
                if (text.length > 0) {
                    text = "";
                    box.cleared();
                }
            }
        }

        // 清除按钮
        Item {
            width: 18
            height: 18
            anchors.verticalCenter: parent.verticalCenter
            visible: field.text.length > 0
            opacity: visible ? 1 : 0
            Text {
                anchors.centerIn: parent
                text: "\uE711"
                font.family: Theme.iconFont
                font.pixelSize: 9
                color: clearMa.containsMouse ? Theme.accent : Theme.textMute
            }
            MouseArea {
                id: clearMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    field.text = "";
                    box.cleared();
                    field.forceActiveFocus();
                }
            }
        }
    }
}
