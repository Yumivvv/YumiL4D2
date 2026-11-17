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

/* 全局动作提示（右下角 Toast）
   ──────────────────────────────────────────────────────────────
   参考 Windows 11 / 常见桌面程序的样式：右下角深色小圆角卡片、
   左侧一个语义色圆环图标、右侧标题、右上角小叉、底部一条会走完的进度条。

   颜色按语义走：
     info  蓝  ⓘ  一般信息（复制、切换）
     ok    绿  ✓  成功（导入完成）
     warn  黄  ⚠  可挽回（放进回收站、被占用跳过）
     error 红  ✕  失败 / 不可挽回（永久删除、删除失败）

   交互约定：
     * 整层不吃鼠标，只有卡片本身可点（避免挡住下面的按钮）
     * **悬停不做任何事**：不暂停、不重置。提示到点就走，点卡片/点 ✕ 可以立刻关掉
       （早期版本做了「悬停暂停」，但鼠标经常就停在右下角，提示会一直卡着不走，
        看起来像在反复弹 —— 干脆去掉这个聪明反被聪明误的设计）
     * 光标保持默认箭头（提示只是通知，不是按钮）
     * 最多同时叠 3 条，新的排在下面
*/
Item {
    id: host
    objectName: "toastLayer"
    anchors.fill: parent
    z: 900

    property int cardW: 336
    property int gap: 8
    // 每条停留多久（毫秒）
    property int lifeMs: 3600
    readonly property int maxVisible: 3

    function levelColor(level) {
        switch (String(level || "info")) {
        case "ok":    return Theme.ok;
        case "warn":  return Theme.warn;
        case "error": return Theme.accent;
        default:      return Theme.cyan;
        }
    }

    function levelGlyph(level) {
        switch (String(level || "info")) {
        case "ok":    return "\uE73E";   // 勾
        case "warn":  return "\uE7BA";   // 三角感叹
        case "error": return "\uE711";   // 叉
        default:      return "\uE946";   // 圆 i
        }
    }

    function show(text, level) {
        var msg = String(text || "").trim();
        if (!msg)
            return;
        // 同一条消息连续触发时不要叠一堆 —— 直接把已有的那条重新计时
        for (var i = 0; i < toastModel.count; ++i) {
            var row = toastModel.get(i);
            if (row.text === msg && row.level === String(level || "info")) {
                toastModel.setProperty(i, "stamp", _newStamp());
                return;
            }
        }
        toastModel.insert(0, {
            text: msg,
            level: String(level || "info"),
            stamp: _newStamp()
        });
        while (toastModel.count > host.maxVisible)
            toastModel.remove(toastModel.count - 1);
    }

    // stamp 必须是**字符串**：delegate 里声明成 int 的话，
    // Date.now()+Math.random() 这种 double 会被截断成整数，
    // 于是 dismiss() 拿着截断值去 ListModel 里比原始 double，永远找不到 →
    // 提示永远不消失（还会一直重复播提示音）。
    property int _seq: 0
    function _newStamp() {
        host._seq += 1;
        return "t" + Date.now() + "_" + host._seq;
    }

    function dismiss(stamp) {
        for (var i = 0; i < toastModel.count; ++i) {
            if (toastModel.get(i).stamp === stamp) {
                toastModel.remove(i);
                return;
            }
        }
    }

    ListModel { id: toastModel }

    // 给测试/调试用
    function count() { return toastModel.count; }
    function item(i) {
        if (i < 0 || i >= toastModel.count)
            return null;
        return { text: toastModel.get(i).text, level: toastModel.get(i).level };
    }

    Column {
        id: stack
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: 20
        anchors.bottomMargin: 18
        spacing: host.gap

        Repeater {
            model: toastModel
            delegate: Item {
                id: slot
                required property string text
                required property string level
                required property string stamp

                objectName: "toastCard"
                width: host.cardW
                height: card.height

                function startLife() {
                    lifeTimer.restart();
                    lifeProg.restart();
                }

                // 真正的裁判：到点就把自己从模型里删掉。
                // 注意：**没有暂停**。以前鼠标悬停会暂停计时，但用户的鼠标经常就停在
                // 右下角那块，结果提示一直卡着不走（看着像「重复弹」）。提示只是通知，
                // 不需要优雅地等你读完 —— 想看可以截图，或者重新触发一次同样的操作。
                Timer {
                    id: lifeTimer
                    interval: host.lifeMs
                    repeat: false
                    onTriggered: host.dismiss(slot.stamp)

                    function restart() {
                        interval = host.lifeMs;
                        stop();
                        start();
                    }
                }

                Rectangle {
                    id: card
                    width: host.cardW
                    // 一行 46，换行往上长
                    height: Math.max(46, label.implicitHeight + 26)
                    radius: 8
                    // 提示卡跟着主题走：
                    //   夜间 → 深灰底 + 亮字（原来那套）
                    //   日间 → 白底 + 深字 + 略深边框，否则一块黑疙瘩戳在浅色界面上很突兀
                    color: {
                        if (Theme.dark) {
                            return hoverArea.containsMouse
                                 ? Qt.rgba(0.14, 0.15, 0.17, 0.98)
                                 : Qt.rgba(0.11, 0.12, 0.14, 0.97);
                        }
                        return hoverArea.containsMouse
                             ? Qt.rgba(1, 1, 1, 0.99)
                             : Qt.rgba(1, 1, 1, 0.97);
                    }
                    border.width: 1
                    border.color: Theme.dark ? Theme.scrim(0.10) : Qt.rgba(0, 0, 0, 0.10)
                    Behavior on color { ColorAnimation { duration: 110 } }

                    // 左侧语义色圆环 + 图标
                    Item {
                        id: badge
                        width: 22
                        height: 22
                        anchors.left: parent.left
                        anchors.leftMargin: 13
                        anchors.verticalCenter: parent.verticalCenter

                        Rectangle {
                            anchors.fill: parent
                            radius: 11
                            color: "transparent"
                            border.width: 1.6
                            border.color: host.levelColor(slot.level)
                        }
                        Text {
                            anchors.centerIn: parent
                            text: host.levelGlyph(slot.level)
                            font.family: Theme.iconFont
                            font.pixelSize: 10
                            color: host.levelColor(slot.level)
                        }
                    }

                    Text {
                        id: label
                        anchors.left: badge.right
                        anchors.leftMargin: 11
                        anchors.right: closeIcon.left
                        anchors.rightMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        text: slot.text
                        // 日间模式是白底，白字会看不见 —— 换成主题正文色
                        color: Theme.dark ? "#F2F4F8" : Theme.text
                        font.family: Theme.uiFont
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                        wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                        maximumLineCount: 3
                        elide: Text.ElideRight
                        lineHeight: 1.25
                    }

                    // 右上角小叉
                    Text {
                        id: closeIcon
                        anchors.right: parent.right
                        anchors.rightMargin: 9
                        anchors.top: parent.top
                        anchors.topMargin: 9
                        text: "\uE711"
                        font.family: Theme.iconFont
                        font.pixelSize: 9
                        color: closeMa.containsMouse
                               ? (Theme.dark ? "#ffffff" : Theme.text)
                               : (Theme.dark ? Theme.scrim(0.45) : Qt.rgba(0, 0, 0, 0.35))
                    }

                    // 底部进度条
                    Rectangle {
                        id: progTrack
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 1
                        anchors.rightMargin: 1
                        anchors.bottomMargin: 1
                        height: 3
                        radius: 1.5
                        color: Theme.scrim(0.09)
                        clip: true

                        Rectangle {
                            id: progFill
                            width: progTrack.width
                            height: parent.height
                            radius: 1.5
                            color: host.levelColor(slot.level)
                        }
                    }

                    // 悬停：暂停（不再重置！），光标保持默认箭头
                    MouseArea {
                        id: hoverArea
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.LeftButton
                        cursorShape: Qt.ArrowCursor
                        // 悬停**不做任何事**：既不暂停也不重置。
                        // 之前悬停暂停会让提示卡在右下角不走（鼠标常常就搁在那儿）。
                        onClicked: host.dismiss(slot.stamp)
                    }

                    // 小叉：叠在右上角，单独吃点击
                    MouseArea {
                        id: closeMa
                        x: parent.width - 26
                        y: 0
                        width: 26
                        height: 26
                        hoverEnabled: true
                        cursorShape: Qt.ArrowCursor
                        onClicked: host.dismiss(slot.stamp)
                    }

                    // 进度条动画只是视觉，真正的超时由 lifeTimer 负责
                    NumberAnimation {
                        id: lifeProg
                        target: progFill
                        property: "width"
                        from: progTrack.width
                        to: 0
                        duration: host.lifeMs
                        easing.type: Easing.Linear
                        function restart() {
                            from = progTrack.width;
                            duration = host.lifeMs;
                            running = false;
                            running = true;
                        }
                    }

                    SequentialAnimation {
                        id: enterAnim
                        PropertyAction { target: card; property: "opacity"; value: 0 }
                        PropertyAction { target: card; property: "x"; value: 16 }
                        ParallelAnimation {
                            NumberAnimation {
                                target: card; property: "opacity"
                                from: 0; to: 1; duration: 150
                                easing.type: Easing.OutCubic
                            }
                            NumberAnimation {
                                target: card; property: "x"
                                from: 16; to: 0; duration: 190
                                easing.type: Easing.OutCubic
                            }
                        }
                        ScriptAction { script: slot.startLife() }
                    }

                    Component.onCompleted: enterAnim.start()
                }
            }
        }
    }
}
