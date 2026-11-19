import sys, os
sys.path.insert(0, ".")
from app.panlink import extract_links
from app.store import Library

lib = Library()
n = 0
for v in lib.all_items():
    ls = extract_links(v.get("desc") or "", fallback_label=v.get("title") or "")
    for l in ls:
        if n < 12:
            print(f"{l['name']:6s} | {(l['label'] or '-')[:40]:42s} | {v['title'][:30]}")
        n += 1
print()
print("链接总数:", n)
