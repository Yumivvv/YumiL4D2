# Yumi的L4D2工具箱
# Copyright (C) 2026 ZengDeRong
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""从视频简介里提取网盘链接（夸克 / 百度 / 蓝奏云 / 阿里 / 123 / 天翼 / 迅雷）.

B 站简介里为了防和谐，经常把域名拆开或插中文，例如：

    链接: https://pan.删除baidu.com/s/1mLRDkcit中文c2Sz05w6EwbKaA?pwd=6sg4

处理策略：
  1. 找到所有 http(s):// 开头的片段；
  2. 去掉 URL 内部夹杂的中文 / 全角字符 / 零宽字符；
  3. 按常见网盘域名做白名单匹配；
  4. 顺便把 ?pwd= / 提取码 / 密码 也识别出来。
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

# 常见网盘域名 → 显示名 & 主题色
PAN_HOSTS: dict[str, tuple[str, str]] = {
    "pan.quark.cn": ("夸克网盘", "#5B8CFF"),
    "quark.cn": ("夸克", "#5B8CFF"),
    "pan.baidu.com": ("百度网盘", "#3D6EFF"),
    "eyun.baidu.com": ("百度企业网盘", "#3D6EFF"),
    "yun.baidu.com": ("百度网盘", "#3D6EFF"),
    "wwi.lanzou": ("蓝奏云", "#00B8A9"),
    "lanzou": ("蓝奏云", "#00B8A9"),
    "pan.lanzou": ("蓝奏云", "#00B8A9"),
    # 蓝奏云后来换了一批域名，跟老域名**没有共同的词根**（lanzn / lanzv / lanzm…），
    # 所以 `pattern in host` 那种子串匹配对它们完全不生效 —— 用户报的
    # `https://wwavf.lanzn.com/i37EB4gwigjg` 就是这种情况（提取不到）。
    # 这里把已知的几套新域名都列上，另外靠 _LANZOU_HOST_RE 兜住「wwXXX.lanz*」
    # 这种「子域名带随机串」的写法。
    "lanzn.com": ("蓝奏云", "#00B8A9"),
    "lanzn": ("蓝奏云", "#00B8A9"),
    "lanzv.com": ("蓝奏云", "#00B8A9"),
    "lanzm.com": ("蓝奏云", "#00B8A9"),
    "lanzoup.com": ("蓝奏云", "#00B8A9"),
    "lanzoui.com": ("蓝奏云", "#00B8A9"),
    "lanzouf.com": ("蓝奏云", "#00B8A9"),
    "lanzouw.com": ("蓝奏云", "#00B8A9"),
    "lanzoux.com": ("蓝奏云", "#00B8A9"),
    "lanzouy.com": ("蓝奏云", "#00B8A9"),
    "www.aliyundrive.com": ("阿里云盘", "#7B61FF"),
    "www.alipan.com": ("阿里云盘", "#7B61FF"),
    "alipan.com": ("阿里云盘", "#7B61FF"),
    "www.123pan.com": ("123 云盘", "#2F80ED"),
    "123pan.com": ("123 云盘", "#2F80ED"),
    "cloud.189.cn": ("天翼云盘", "#1E88E5"),
    "pan.xunlei.com": ("迅雷云盘", "#2F6BFF"),
    "caiyun.139.com": ("移动云盘", "#2196F3"),
    "drive.google.com": ("Google Drive", "#34A853"),
    "mega.nz": ("MEGA", "#D9272E"),
    "www.dropbox.com": ("Dropbox", "#0061FF"),
    "115.com": ("115 网盘", "#2A6BFF"),
    "pan.115.com": ("115 网盘", "#2A6BFF"),
    "share.weiyun.com": ("腾讯微云", "#2CA5E6"),
    "weiyun.com": ("腾讯微云", "#2CA5E6"),
    "pan.wo.cn": ("联通云盘", "#E60012"),
    # 爱发电：创作者赞助平台，直接跳转，无需提取码/密码
    "afdian.com": ("爱发电", "#E8590C"),
    "afdian.net": ("爱发电", "#E8590C"),
    "www.afdian.com": ("爱发电", "#E8590C"),
    # ifdian.net 也是爱发电（镜像/备用域名）
    "ifdian.net": ("爱发电", "#E8590C"),
    "www.ifdian.net": ("爱发电", "#E8590C"),
    # Steam 创意工坊：跳转到 MOD 详情页，无需提取码/密码
    "steamcommunity.com": ("Steam 创意工坊", "#1B2838"),
}

# 无需提取码/密码的平台（爱发电、Steam 工坊这类公开跳转页）。
# 简介里如果同时有「百度网盘 提取码 aaaa」和「爱发电链接」，之前会把
# 「提取码 aaaa」错误地分配给爱发电 —— 因为 _nearest_code 见码就抓。
# 有了这个集合，这些平台直接跳过提取码提取。
_NO_CODE_HOSTS = (
    "afdian.com", "afdian.net", "ifdian.net", "steamcommunity.com",
)

# 提取码 / 密码 的常见写法
_CODE_PATTERNS = [
    re.compile(r"(?:提取码|提取碼|密码|密碼|访问码|訪問碼|pwd|code)\s*[:：=]?\s*([A-Za-z0-9]{4,8})", re.I),
    re.compile(r"提取码\s*([A-Za-z0-9]{4,8})"),
]

# URL 里不该出现的字符：中文、全角标点、空白、零宽字符，
# 以及防和谐常用的各种括号（【】[]（）—— 干扰词被删掉后括号会留下来，
# 之前 `https://pan.baidu.com/s/1AbCdEfG[删]?pwd=z9y8` 会变成 `...EfG[]?pwd=...`，
# 方括号没在过滤集里，链接就带着 `[]` 一起被打开了）。
_CJK = re.compile(
    r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef"
    r"\u200b-\u200f\u2028-\u202e\ufeff"
    r"\[\]【】〔〕〖〗「」『』《》〈〉()（）]"
)
# B 站简介里常见的"防和谐"拆字：删除/去掉/去除 这类词
_STOP_WORDS = re.compile(r"(删除|去掉|去除|删掉|屏蔽|防屏蔽|不要|打不开就删|中文)")

# 蓝奏云的域名形状：`wwX.lanz*.<tld>` / `lanz*.<tld>`
# 例如 wwavf.lanzn.com、wwi.lanzoup.com、pan.lanzou.com
_LANZOU_HOST_RE = re.compile(r"(^|\.)lanz[a-z]*(\.|$)")

# 整个括号块（含内容）—— 防和谐插字最常用的包装。
# 覆盖：中文括号、英文括号、方头括号、书名号、以及「（DANKING！）」这种全角叹号结尾。
# 注意 `[^）)]*` 不跨越另一个括号，避免把 `(a)(b)` 这种连着的吃成一大段。
_PAREN_BLOCK = re.compile(
    r"（[^（）]*）|\([^()]*\)|【[^【】]*】|\[[^\[\]]*\]"
    r"|〔[^〔〕]*〕|〖[^〖〗]*〗|「[^「」]*」|『[^『』]*』"
    r"|《[^《》]*》|〈[^〈〉]*〉"
)


def _clean_url(raw: str) -> str:
    """去掉 URL 中夹杂的中文和干扰文字，返回干净的 URL。"""
    s = raw
    # ✂ 先把「整段括号块」删掉（含里面的英文），再干别的。
    #
    # ★ 为什么必须先做这一步：作者防和谐不只插中文，还会插**纯英文**括注。
    #   用户报的真实案例：
    #       https://pan.b（删删删）aidu.com/s/1P9uaqDEDMoSoqH（DANKING！）W50iJHyw?pwd=62nx
    #   旧逻辑只删中文字符（_CJK），于是 `DANKING` 这种纯 ASCII 被原样留下，
    #   拼出的 URL 变成 .../s/1P9uaqDEDMoSoqHDANKINGW50iJHyw —— **链接是错的**，
    #   点开必然 404，但界面上看着又像「提取成功了」，比提取不到更坑。
    #   括号里的东西本来就不可能是路径的一部分（URL 里不会有全角括号），
    #   所以整段丢掉是安全的。
    s = _PAREN_BLOCK.sub("", s)
    # 再把明显的干扰词整段删掉
    s = _STOP_WORDS.sub("", s)
    # 再逐字符过滤中文 / 全角 / 零宽
    s = _CJK.sub("", s)
    # 去掉末尾可能残留的标点和空白
    s = s.strip().strip(".,;:!?)】]》\"'，。；：！？、）】")
    return s


def _host_label(url: str) -> tuple[str, str] | None:
    """按域名匹配网盘类型，返回 (显示名, 颜色) 或 None。"""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None
    for pattern, info in PAN_HOSTS.items():
        if host == pattern or host.endswith("." + pattern) or pattern in host:
            return info
    # 兜底：蓝奏云的域名爱换，但形状很稳定 —— `wwX.lanz*.<tld>`
    # （wwi / wwavf / wwa / ww1… 前缀随机，lanzn / lanzou / lanzv… 主域也换）。
    # 与其每次都等用户报「这个链接提取不到」，不如按形状认。
    if _LANZOU_HOST_RE.search(host):
        return PAN_HOSTS["lanzou"]
    return None


def _extract_code(text: str, url: str) -> str:
    """从 URL 参数或周围文字里找提取码。

    注意：**保留原始大小写**。有些网盘（蓝奏云、夸克）的提取码区分大小写，
    统一转成大写会让用户粘贴进去打不开。
    """
    # 1) URL 自带的 ?pwd=xxx
    try:
        qs = parse_qs(urlparse(url).query)
        for key in ("pwd", "password", "passcode", "code", "extractcode"):
            if key in qs and qs[key]:
                val = qs[key][0].strip()
                if 2 <= len(val) <= 10:
                    return val
    except ValueError:
        pass
    # 2) 文字里的 "提取码: xxxx"
    for pat in _CODE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return ""


# 提取码出现的位置，用来判断它属于哪个链接
_CODE_FIND = re.compile(
    r"(?:提取码|提取碼|密码|密碼|访问码|訪問碼|pwd|code)\s*[:：=]?\s*([A-Za-z0-9]{4,8})", re.I
)


def _nearest_code(text: str, url_start: int, url_end: int,
                  spans: list[tuple[int, int]]) -> str:
    """找文本里紧邻该链接的提取码。

    简介里两种排版都常见，必须都认：

    **① 码在同一行**（最常见的百度写法）::

        https://pan.baidu.com/s/1P9uaq...?pwd=62nx 提取码: 62nx

    **② 码在下一行**（夸克/蓝奏爱这么写）::

        链接：https://pan.quark.cn/s/851a9b7...7089c
        提取码：xuhr

    ★ 这里改过两版，两个坑都记一下：
      - 第一版只看「距离最近」，于是**下一行开头的码会被上一行的链接抢走**
        （蓝奏云那行抢了上一行夸克的 `1iqM`）；
      - 第二版限制「必须同一行」，结果**夸克这种码在下一行的又拿不到了**
        （BV1dLyYzjEkK 那条视频就是这样）。
      现在是：**同一行优先**；同一行找不到，才允许看**紧邻的下一行**，
      并且中间不能夹着别的链接（否则那个码属于别人）。
    """
    line_start = text.rfind("\n", 0, url_start) + 1
    line_end = text.find("\n", url_end)
    if line_end < 0:
        line_end = len(text)
    # 下一行范围（用于「码在下一行」那种排版）
    next_start = line_end + 1
    next_end = text.find("\n", next_start)
    if next_end < 0:
        next_end = len(text)

    best: tuple[int, str] | None = None
    for m in _CODE_FIND.finditer(text):
        pos = m.start()
        if pos < url_start - 40 or pos > url_end + 90:
            continue
        # 落在**别的** URL 内部的码（如别人的 ?pwd=）不属于我
        inside_other = any(
            a <= pos < b and not (a == url_start and b == url_end)
            for a, b in spans
        )
        if inside_other:
            continue

        in_same = line_start <= pos <= line_end
        in_next = next_start <= pos <= next_end
        if not (in_same or in_next):
            continue
        # 「下一行」里的码：中间不能夹着别的链接
        if in_next and not in_same:
            if any(url_end < a < pos for a, _b in spans):
                continue

        dist = abs(pos - url_end) if pos >= url_end else abs(url_start - pos)
        # 同一行优先：加个大权重，保证同行的码永远赢过下一行的
        weight = dist if in_same else dist + 10000
        if best is None or weight < best[0]:
            best = (weight, m.group(1))
    return best[1] if best else ""


# ---------------------------------------------------------------------------
# 从链接周围的文字里推断"这个网盘装的是什么文件"
# ---------------------------------------------------------------------------

# 视频里常见的武器 / 内容名词，用来给链接起个说明
_NOUNS = [
    "AK47", "AK", "M4A1", "M4", "M16", "SCAR", "SCAR-H", "UZI", "MP5", "MP7",
    "SPAS", "SPAS-12", "霰弹枪", "连喷", "单喷", "狙击", "步枪", "手枪", "刀",
    "武士刀", "斧头", "砍刀", "平底锅", "榴弹", "烟幕弹", "燃烧瓶", "医疗包",
    "人物", "模型", "皮肤", "贴图", "武器", "枪械", "音效", "UI", "HUD",
    "MOD", "mod", "插件", "地图", "整合包", "合集", "模组", "补丁", "字体",
]
_NOUN_RE = re.compile("|".join(re.escape(n) for n in _NOUNS), re.I)

# 描述里常见但不该当作文件名的噪音
_NOISE = re.compile(
    r"(通过网盘分享的文件|通过分享的文件|分享的文件|网盘分享|分享的|"
    r"链接|下载|地址|网盘|提取码|密码|访问码|复制|打开|点击|这里|戳我|"
    r"链接如下|见下|以上|如下|百度|夸克|蓝奏云?|阿里|迅雷|123|天翼|微云|"
    r"https?://\S*|www\.\S*|【|】|\[|\]|\(|\)|（|）)"
)

# 明显的文件名（带扩展名）
_FILE_EXT = re.compile(
    r"[\w\u4e00-\u9fff\-. ]{2,60}?\.(?:vpk|zip|rar|7z|pak|exe|txt|pdf|mp4|mkv|"
    r"jpg|png|psd|blend|fbx|obj|dds|vtf|vmt|cfg|ini|docx?|xlsx?|pptx?)",
    re.I,
)


def _split_sentences(text: str) -> list[str]:
    """按换行和各种标点切句，用来定位链接所在的上下文。"""
    parts = re.split(r"[\n\r。；;！!？?]+", text)
    return [p.strip() for p in parts if p.strip()]


# 太宽泛、不构成"文件说明"的词，命中了就当没有
_TOO_GENERIC = re.compile(
    r"^(mod|mods|MOD|插件|补丁|文件|下载|资源|分享|自制|公开|限时|限时公开|"
    r"仅供学习交流|仅供交流|学习交流|侵删|转载|整合|内容)$",
    re.I,
)


def _looks_like_label(s: str) -> bool:
    """判断一段文字像不像"文件名说明"，比如「AK47和三连发：」。"""
    s = s.strip()
    if not (2 <= len(s) <= 30):
        return False
    # 句子式的长文本不是标签（"不过MOD存在一点小问题，应该是做手环…"）
    if re.search(r"[，,。！!？?；;]", s):
        return False
    # 带空格的叙述性短句（"首次安装 需要看l4n的工坊简介 只订阅的话无法生效"）也不是标签
    if len(s.split()) >= 3 and not _NOUN_RE.search(s):
        return False
    # 全是噪音词的不算
    core = _NOISE.sub("", s).strip()
    if not core:
        return False
    # 太宽泛的词不算
    if _TOO_GENERIC.match(core) or _TOO_GENERIC.match(s):
        return False
    # 纯英文/数字随机串不像说明
    if re.fullmatch(r"[A-Za-z0-9\-_]+", s) and not _NOUN_RE.search(s):
        return False
    return True


def _guess_label(text: str, url_start: int, url_end: int) -> str:
    """推断链接对应的文件说明，比如「AK47和三连发」。

    策略（从强到弱，都只看链接附近，避免误抓远处的句子）：
      1. 同一行里链接前面紧跟的短标签，如「AK47和三连发：https://...」
      2. 紧邻的上一行短标签（往前最多 2 行）
      3. 附近出现的文件名（xxx.vpk）
      4. 附近出现的武器/内容名词组合
    """
    # ---------- 1. 同一行、链接前面的部分 ----------
    line_start = text.rfind("\n", 0, url_start) + 1
    same_line_before = text[line_start:url_start]
    cand = _clean_label(same_line_before)
    if _looks_like_label(cand):
        return cand

    # ---------- 2. 紧邻的上一行（最多往前 2 行） ----------
    head = text[max(0, url_start - 90):url_start]
    prev_lines = [ln for ln in head.split("\n") if ln.strip()]
    for s in reversed(prev_lines[-2:]):
        c = _clean_label(s)
        if _looks_like_label(c) and not re.search(r"https?://", s):
            return c

    # ---------- 3. 附近文件名 ----------
    nearby = text[max(0, url_start - 100):min(len(text), url_end + 100)]
    m = _FILE_EXT.search(nearby)
    if m:
        name = m.group(0).strip()
        if len(name) >= 4:
            return name

    # ---------- 4. 附近名词组合 ----------
    window = text[max(0, url_start - 80):min(len(text), url_end + 80)]
    nouns = []
    for nm in _NOUN_RE.findall(window):
        if nm and nm not in nouns:
            nouns.append(nm)
    if nouns:
        return "、".join(nouns[:3]) + " 相关文件"

    return ""


def _clean_label(s: str) -> str:
    """清理标签文字：去掉结尾的冒号/链接/噪音词。"""
    s = s.strip()
    s = re.sub(r"https?://\S*", "", s)
    s = s.strip(" \t:：-=—•·、,，.。;；")
    s = _NOISE.sub("", s).strip(" \t:：-=—•·、,，.。;；")
    # 太短或纯符号就放弃
    if len(s) < 2 or not re.search(r"[\w\u4e00-\u9fff]", s):
        return ""
    return s[:40]


def _url_matches(text: str) -> list[tuple[str, int, int]]:
    """找出文本里的所有 http(s) 链接，返回 ``[(清洗后的 url, token 起点, token 终点)]``。

    ★ 为什么按「空白切 token、先清洗再匹配」而不是「先在原文里正则匹配、后清洗」：
      简介里防和谐的手法是**把干扰字插进 URL 内部**，不只是在域名中间，连协议名都会被
      拆开。真实案例（用户报的）：

          htt【删】ps://pan.ba【除】idu.com/s/18【文】VHP-PnAp7t3【字】dksJSOoU【谢】ww?pwd=【谢】tvrk

      直接拿 ``https?://[^\\s]+`` 去原文里找，``https`` 已经被插成 ``htt【删】ps``，
      压根匹配不上，于是整条链接被漏掉。
      而 ``_clean_url`` 本身是能把 ``【删】`` 这类东西清干净的 —— 问题只是**顺序**：
      必须**先清洗、再在清洗后的串里找协议头**。

    token 的原始区间也要带出去：提取码和文件说明都是根据「链接在原文里的位置」推断的，
    清洗会改变长度，所以只能用 token 在原文里的起止来定位上下文。

    ★★ 还要支持**裸域名**（没有 ``https://`` 的写法）。
      用户报的真实案例：
          ``pan.qu【删】ark.cn/s/2ce22bd402e3?pwd=U7sV``
      以及更常见的「链接: pan.quark.cn/s/xxx 提取码: abcd」——
      作者贴链接时经常把协议头省掉。以前只认 ``https?://``，这类链接**整条漏掉**。
      现在：清洗后如果开头就是一个已知网盘域名，自动补成 ``https://``。
    """
    out: list[tuple[str, int, int]] = []
    for tm in re.finditer(r"\S+", text):
        token = tm.group(0)
        # 先清洗整段 token：去掉防和谐插字、中文、全角、零宽字符
        cleaned = _clean_url(token)
        if not cleaned:
            continue

        found: list[str] = []
        for um in re.finditer(r"https?://\S+", cleaned):
            url = um.group(0).strip(".,;:!?)】]》\"'")
            if len(url) < 12:
                continue
            # ★ 带协议头 тоже 要有分享路径：
            #   「https://pan.baidu.com」这种只有域名的，点开是网盘首页，
            #   不是分享 —— 同样算噪音，别列出来。
            try:
                _host = (urlparse(url).hostname or "").lower()
            except ValueError:
                _host = ""
            _path = (urlparse(url).path or "").strip("/")
            if _host and not _path and not urlparse(url).query:
                continue
            found.append(url)

        if not found:
            # 没有协议头：看这个 token 里是不是藏着裸网盘域名
            bare = _bare_pan_url(cleaned)
            if bare:
                found.append(bare)

        for url in found:
            out.append((url, tm.start(), tm.end()))
    return out


# 裸域名（没有 https://）的形态：域名 + 可选路径
_BARE_URL_RE = re.compile(
    r"((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,24}(?:/[^\s]*)?)"
)
# 裸域名后面允许出现的字符（中文说明不该被吃进 URL）
_BARE_TAIL_STOP = "，。、；：！？【】《》「」\"'"


def _bare_pan_url(cleaned: str) -> str:
    """从一段**没有协议头**的文本里揪出裸网盘域名，补成 ``https://…``。

    只认 ``PAN_HOSTS`` 里登记过的域名（避免把说明文字里的英文缩写当成链接），
    返回空串表示这个 token 里没有网盘链接。
    """
    s = str(cleaned or "").strip()
    if not s:
        return ""
    # 先按空白 / 常见中文标点切段，再逐段找域名
    for chunk in re.split(r"[\s%s]+" % re.escape(_BARE_TAIL_STOP), s):
        chunk = chunk.strip(".,;:!?)]}》\"'")
        if not chunk or "." not in chunk:
            continue
        m = _BARE_URL_RE.search(chunk)
        if not m:
            continue
        candidate = m.group(1)
        # 末尾可能粘着「提取码」之类中文：在第一个中文/全角处截断
        candidate = re.split(r"[\u4e00-\u9fff\uff00-\uffef]", candidate)[0]
        candidate = candidate.strip(".,;:!?)]}》\"'")
        if len(candidate) < 8:
            continue
        host = candidate.split("/")[0].lower()
        if not _host_label("https://" + host):
            continue          # 不是已知网盘域名

        # ★ 光有域名不算链接 —— 必须有**分享路径**。
        #   用户报的现象：简介里随口提一句「百度网盘：pan.baidu.com」
        #   「steamcommunity.com 上有很多 MOD」也会被当成网盘链接列出来，
        #   点开只是网盘首页，等于噪音。
        #   真实的分享链接一定带路径，且至少有一个非空段：
        #       pan.baidu.com/s/1AbCd      quark.cn/s/xxxx
        #       wwavf.lanzn.com/i37EB4     afdian.com/a/xxx
        #   所以这里要求 host 之后还有内容。
        rest = candidate[len(host):].strip("/")
        if not rest:
            continue

        return "https://" + candidate
    return ""


def extract_links(text: str, max_links: int = 8, fallback_label: str = "") -> list[dict]:
    """从一段文本里提取网盘链接.

    返回 [{"url","name","color","code","label","raw"}]
    label 是这个网盘里装什么的说明：优先从简介文字推断，
    推断不出来时用 fallback_label（一般是视频标题）。
    """
    if not text:
        return []

    results: list[dict] = []
    seen: set[str] = set()

    matches = _url_matches(text)
    # 链接在原文里占的区间：「别的链接内部的提取码不算我的」要靠它
    spans: list[tuple[int, int]] = [(s, e) for _, s, e in matches]

    for cleaned, tok_start, tok_end in matches:
        label = _host_label(cleaned)
        if label is None:
            continue  # 不是网盘链接就跳过

        # 去重（同一个链接只留一条）
        key = cleaned.split("#")[0]
        if key in seen:
            continue
        seen.add(key)

        name, color = label

        # 判断这个链接是否属于「无需提取码」的平台（爱发电 / Steam 工坊）
        host = ""
        try:
            host = (urlparse(cleaned).hostname or "").lower()
        except ValueError:
            host = ""
        no_code = any(h in host for h in _NO_CODE_HOSTS)

        # 提取码优先取 URL 自带的 pwd 参数
        code = ""
        if not no_code:
            code = _extract_code("", cleaned)
            if not code:
                # 否则找"距离这个链接最近"的那个提取码，避免多个链接之间串码
                code = _nearest_code(text, tok_start, tok_end, spans)

        # 推断这个网盘里装的是什么
        label_text = _guess_label(text, tok_start, tok_end)
        if not label_text and fallback_label:
            label_text = fallback_label[:40]

        results.append(
            {
                "url": cleaned,
                "name": name,
                "color": color,
                "code": code,
                "label": label_text,
                "raw": text[tok_start:tok_end],
            }
        )
        if len(results) >= max_links:
            break

    return results


def extract_links_json(text: str) -> list[dict]:
    return extract_links(text)


if __name__ == "__main__":
    sample = (
        "链接: https://pan.删除baidu.com/s/1mLRDkcit中文c2Sz05w6EwbKaA?pwd=6sg4\n"
        "夸克：https://pan.quark.cn/s/abcdef123456 提取码: q7k2\n"
        "蓝奏 https://wwi.lanzoup.com/iAbCd0xyz 密码 8h2j\n"
        "不是网盘的 https://www.bilibili.com/video/BV1xx411c7mD 应被忽略"
    )
    for it in extract_links(sample):
        print(it["name"], "|", it["url"], "| code =", it["code"])
