"""用真实库里的简介抽查网盘链接提取效果."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.panlink import extract_links
from app.store import Library

lib = Library()
total = 0
with_link = 0
kinds: dict[str, int] = {}

for v in lib.all_items():
    items = extract_links(v.get("desc") or "")
    if items:
        with_link += 1
    for it in items:
        total += 1
        kinds[it["name"]] = kinds.get(it["name"], 0) + 1
        if total <= 8:
            print(f"{it['name']:10s} {it['url'][:74]:76s} code={it['code'] or '-'}")

print()
print("视频总数:", len(lib.videos))
print("含网盘链接:", with_link)
print("链接总数:", total)
print("按类型:", kinds)
