"""README 结构体检：代码块配对、重复段落、失效的旧文案。"""
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = os.path.join(ROOT, "README.md")
text = open(path, encoding="utf-8").read()

fence = "`" * 3
n = text.count(fence)
print("code fences:", n, "even?" , n % 2 == 0)
assert n % 2 == 0, "代码块没配对"

paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 60]
dups = {k: v for k, v in Counter(paras).items() if v > 1}
print("duplicate paragraphs:", len(dups))
for k, v in list(dups.items())[:5]:
    print(f"  x{v}: {k[:70]}")
assert not dups, "README 里有重复段落"

# 旧文案不该再出现。
# 注意「组合（一键切换）」「共扫描」是刻意留在「已删除/已改掉」那两句说明里的，
# 所以这里只查那些**不该以原样出现**的按钮/标签文案。
stale = [
    "检查这个 MOD",
    "禁用这个 MOD",
    "启用这个 MOD",
    "重新检查这个 MOD",
    "· 共扫描 ",
    # 背景图现在只留一个 background.*，不该再宣传「点图片名切换多张图」
    "| 点图片名 |",
]
for s in stale:
    if s in text:
        print("  [stale]", s)
        assert False, f"README 里还有旧文案：{s}"

# 新东西应该出现
need = ["今日扫描", "置顶评论", "音量与静音", "右下角", "检查MOD", "转换到本地MOD",
        "自定义主题色", "主题色", "自定义背景图",
        # 本轮新增
        "外观模式", "跟随系统", "夜间", "日间",
        "分享视频", "最近导入", "按导入日期筛选", "background",
        # 创意工坊导入
        "创意工坊导入", "订阅", "前置物品", "下载线程",
        "合集", "重新下载",
        # 加载顺序
        "加载顺序", "addonlist", "GBK", "文件不存在",
        # VPK 内部解析
        "VPK 内部解析", "addoninfo.txt", "addonimage.jpg", "目录树",
        # 创意工坊页 / CDN / 翻译
        "创意工坊页", "CDN 加速", "SNI", "简介与翻译", "MyMemory",
        "浏览", "QueryFiles",
        # 本轮：工坊页改版 + 网络加速
        "网络加速", "自动优选", "手动指定", "地名", "稍后看",
        "连前置一起下", "滚轮", "封面代理",
        # 本轮：加速与 DNS 分开
        "工坊 DNS", "腾讯 DNS", "阿里 DNS", "使用系统 DNS", "IPv4", "IPv6",
        # 本轮：工坊详情提速 / 合集判据 / 不跳回顶部
        "file_type", "num_children", "lite 快通道", "COLLECT_FAST_LIMIT",
        "直链在下载时解析", "先列前", "ListModel", "positionViewAtBeginning",
        "ws_scroll_test",
        # 本轮：下载命名 / 下完补封面 / 删除立刻刷新 / 无前置不提示
        "创意工坊 ID", "modmeta.json", "modcache", "_after_download",
        "_forget_paths", "showDepRow", "mod_delete_test",
        # 本轮：详情接口白送的 CDN 直链
        "file_url", "direct_file_url", "多文件", "_expand_collections",
        # 本轮：没前置就不出现那一行 + 手动「检查前置」
        "检查前置", "复查前置",
        # 本轮：简介（BBCode 清洗）+ 翻译挪到详情里手动翻
        "file_description", "description", "_plain_desc", "译成中文", "看原文",
        # 本轮：合集成员全列出来（流式补齐）+ 稍后看不再卡
        "workshopMembersChanged", "stop_streaming", "syncLaterModel",
        "memberItems", "已列出", "移除", "清空",
        # 本轮：多封面 / 统计数字 / 返回合集 / 重复成员 / 更新检查
        "多张封面", "缩略图条", "_desc_images", "requestWorkshopStats",
        "workshopStatsChanged", "detailStack", "重复", "time_updated",
        "mod_update_test",
        # 本轮：滚轮防穿透补全 + 加载顺序（滚动条配色 / 关掉不留进度 / 禁用标签）
        "滚动条", "resetAddonOrderState", "fileDisabled", "禁用",
        # 本轮：视频详情空间预算 + 分享文案带作者和日期
        "linkBudget", "发布日期", "UP：",
        # 本轮：滚动条拖到底（手写 ScrollBar 的 position 换算）
        "dragRange", "contentFromPos", "scroll_drag_test", "可拖行程",
        # 本轮：打包说明（spec 路径要从 SPECPATH 推算）
        "打包成独立 exe", "SPECPATH", "Yumi的L4D2工具箱.exe",
        # 本轮：单文件 exe（数据落在 exe 旁边、首运行建目录、瘦身）
        "98–99 MB", "USER_ROOT", "seed_user_dirs", "单文件", "_MEIPASS",
        "Qt6WebEngineCore.dll", "onefile_paths_test", "build_folder.spec",
        # 本轮：只看新的自动关 / 稍后看里点分类 / 日韩翻译 / 统计两行
        "只看新的", "detect_lang", "langpair", "假名", "谚文",
        "statDateChips", "ElideRight",
        # 本轮：服务器页（A2S 直查 / 收藏 / 直连）
        "A2S", "steam://connect/", "connect ip:port", "m:coop",
        "l4d2-maps.laoyutang.cn", "hl2master.steampowered.com", "challenge",
        "servers_test", "parse_mode",
        # 本轮：服务器表单（名称/权重/多面板/DPAPI 密码）+ IP 直连 + 编辑
        "添加服务器", "IP 直连", "排序权重", "面板地址", "DPAPI",
        "CryptProtectData", "saveServer", "serverDetail", "clearPasswords",
        "parseAddress", "z: 2", "IP 直连（不进收藏）",
        # 本轮：搜索（排序同一行 / 分词 / Ctrl+F / 没匹配空状态）
        "和排序同一行", "都要命中", "Ctrl+F",
        # 本轮：统一下载页（队列 / 进度 / 取消 / 重试 / 左下角入口）
        "下载页", "_after_mod_done", "协作式", "Ctrl+J",
        "进行中的数量", "清空已结束",
        # 本轮：工坊下载交给下载页（不再「一直显示处理中」）+ 进服务器页自动刷新
        "一直显示处理中", "会自动刷新一次", "防抖",
        # 本轮：任务栏最小化 / 窗口按钮统一 / 蓝奏云直链 / 线程上限 / 视频缓存删除 /
        #       色盘 / 服务器元数据字体
        "WindowMinimizeButtonHint", "WindowButtons", "winButtonsReserve",
        "蓝奏云可以直接下载", "ajaxfile.php", "1 / 2 / 3 / 4 / 6 / 8 / 12 / 16",
        "视频缓存」这一格已经删掉了", "putImageData", "Consolas",
        "按内容分字体",
        # 本轮：设置残留关闭按钮 / 工坊多图 / 工坊 DNS 主题色 / 设置排版
        "残留关闭按钮", "多张图只加载出封面", "四个分区", "② 外观与主题",
        "Property value set multiple times",
        # 本轮：蓝奏云直链（四条硬要求 / 实测结果）
        "四条硬要求", "acw_sc__v2", "apifile.woozooo.com", "ajaxfile.php",
        "X-FORWARDED-FOR", "down_ip=1", "_NoRedirect", "Location",
        "文件未授权", "wp_sign", "isngis", "clean_lanzou_url",
        "文件夹分享", "13 条真实链接",
        # 本轮：点本地下载没反应（槽签名写错 → 静默失败）
        "点本地下载没反应", "QVariantMap", "静默失败", "addPanFile",
        # 本轮：压缩包一键导入 MOD
        "压缩包一键导入 MOD", "importTaskArchive", "inspectTaskArchive",
        "bsdtar + libarchive", "同名文件按既有规则不覆盖",
        "archive_import_test",
        # 本轮：换背景图无效 / 服务器配置导入导出 / MOD 简介翻译
        "换了背景图但画面没变", "_bg_version",
        "导出 / 导入配置（分享给朋友）", "★ 面板密码绝不导出",
        "只加不删", "previewImport", "简介可以译成中文", "看原文 / 看译文"]
for s in need:
    assert s in text, f"README 缺少新内容：{s}"
    print("  ok:", s)

print("\nREADME 体检通过")
