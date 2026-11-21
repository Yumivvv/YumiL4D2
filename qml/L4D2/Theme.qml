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

pragma Singleton
import QtQuick

/* 配色 / 尺寸统一管理。

   深色和浅色两套色板都在这里，`dark` 这个属性决定当前用哪一套：
   - 由 Main.qml 把 `core.isDark` 同步进 `Theme.dark`
   - 所有颜色都是 `dark ? ... : ...` 的派生值，切换时引用它们的地方自动重绘

   除了主色板，还提供几组「跟着明暗走」的语义色：
   - scrim*   半透明叠层（深色用白色提亮、浅色用黑色压暗）
   - hero*    压在图片上的文字/按钮
*/
QtObject {
    // ---------------- 尺寸 ----------------
    readonly property int radius: 16
    readonly property int radiusS: 10
    readonly property int radiusXS: 8
    readonly property int headerH: 74
    readonly property int anim: 150

    // ---------------- 明暗开关 ----------------
    // true = 夜间（深色），false = 日间（浅色）。
    // 初值给 true（和程序原来的深色外观一致），Main.qml 起来后立刻按配置覆盖。
    property bool dark: true

    // ---------------- 颜色（深色 / 浅色两套） ----------------
    readonly property color bg: dark ? "#0A0C11" : "#F4F6FA"
    readonly property color bgAlt: dark ? "#0E1118" : "#EDF0F6"
    readonly property color surface: dark ? "#141822" : "#FFFFFF"
    readonly property color surfaceHi: dark ? "#1B2130" : "#E9EDF5"
    readonly property color surfaceSoft: dark ? "#10141C" : "#F7F9FC"
    readonly property color border: dark ? "#232A39" : "#DCE2EC"
    readonly property color borderHi: dark ? "#323B50" : "#C3CBD9"

    // 窗口底色渐变（原来写死在 Main.qml 里，现在跟着明暗走）
    readonly property color bgGradTop: dark ? "#12161F" : "#FFFFFF"
    readonly property color bgGradMid: dark ? "#0C0E14" : "#F6F8FC"
    readonly property color bgGradBottom: dark ? "#090B10" : "#EEF1F7"

    // 弹层/面板底色（背景图预览框、筛选浮层、MOD 详情底…）
    readonly property color panel: dark ? "#12161F" : "#FFFFFF"
    readonly property color panelHi: dark ? "#1A2029" : "#F2F5FA"
    readonly property color panelDeep: dark ? "#0B0E14" : "#FAFBFD"

    // 强调色：真正可改的是 accentBase（设置面板里的 RGB 滑块会写它），
    // 下面几个都由它派生 —— 改一处，全局的红/粉强调色跟着变，不用挨个改。
    property color accentBase: "#FF4D57"
    readonly property color accent: accentBase
    readonly property color accentDeep: Qt.darker(accentBase, 1.32)
    readonly property color accentGlow: alpha(accentBase, 0.24)
    // 按钮的 hover / 按下反馈：必须由 accentBase 派生，**不能写死**。
    // 以前 ActionButton 里写死了 #FF8087 / #F0404C 这些红，用户把主题改成
    // 蓝色后按下去还是红的 —— 就是这个 bug。
    readonly property color accentHover: Qt.lighter(accentBase, 1.16)
    readonly property color accentPress: Qt.lighter(accentBase, 1.34)
    readonly property color pink: dark ? "#FB7299" : "#E85D8A"
    readonly property color cyan: dark ? "#4DD0E1" : "#0E9CB3"
    readonly property color ok: dark ? "#3ED598" : "#1FA97A"
    readonly property color warn: dark ? "#F5B33C" : "#C4860F"
    // 失败/危险态（网盘链接已过期、已失效这类）。比 warn 更红一档，
    // 让人一眼区分「注意一下」和「这东西不能用了」。
    readonly property color error: dark ? "#FF5C5C" : "#D93636"

    readonly property color text: dark ? "#EDF0F7" : "#141A26"
    readonly property color textDim: dark ? "#A6AEC2" : "#47516A"
    readonly property color textMute: dark ? "#6B7488" : "#7A849B"

    // ---------------- 叠层（跟着明暗反着来） ----------------
    // 深色主题里「提亮」用白色半透明，浅色主题里必须换成黑色，否则一片糊白。
    function scrim(a) {
        return dark ? Qt.rgba(1, 1, 1, a) : Qt.rgba(0, 0, 0, a);
    }

    // 卡片/按钮的常态底、hover 底、按下底
    readonly property color scrimFaint: scrim(0.035)
    readonly property color scrimSoft: scrim(0.055)
    readonly property color scrimMid: scrim(0.10)
    readonly property color scrimStrong: scrim(0.18)

    // 压在封面图上的东西（播放按钮、时长角标、标题）永远是深底白字，
    // 不跟着主题变 —— 图片本身颜色不可控。
    readonly property color heroOverlay: Qt.rgba(0, 0, 0, 0.46)
    readonly property color heroText: "#FFFFFF"
    readonly property color heroSubText: "#E8EBF2"

    // ---------------- 滚动渐隐 ----------------
    // 列表/滚动区顶部的「渐隐遮罩」：盖住内容往上滚时被切掉的那一截。
    // 深色主题下用背景色（近黑）自然晕开；浅色主题下如果还用深色，
    // 就会在列表顶上横一道黑边（日间模式里那条很显眼的杠）。
    // 所以这里跟背景色走，只是不透明一点。
    readonly property color fadeSolid: dark ? "#0A0C11" : "#F4F6FA"
    function fade(amount) {
        return alpha(fadeSolid, amount);
    }

    // 字体。**不能写死**：图标字体在 Windows 11 叫 "Segoe Fluent Icons"，
    // Windows 10 上只有 "Segoe MDL2 Assets"。写死前者会让 Win10 用户的
    // 所有图标变成空白（开发机是 Win11 所以一直没发现）。
    // Main.qml 的 syncTheme() 会在启动时用 core.iconFontFamily 覆盖这三个值
    // （core 那边用 QFontDatabase 检测当前系统实际装了哪个）。
    property string uiFont: "Microsoft YaHei UI"
    property string iconFont: "Segoe MDL2 Assets"
    property string monoFont: "Consolas"

    function alpha(c, a) {
        return Qt.rgba(c.r, c.g, c.b, a)
    }
}
