#!/usr/bin/env python3
"""域名级 vs 文章级：判断「你的内容」到底有没有进 AI 的引用池。

**这个脚本存在的唯一理由，是我们自己在这上面判错过一次。**

当时的错误是这样发生的：统计发现某技术社区的域名在引用池里出现了 89 次，
于是想知道「其中有多少是我们的文章」。用了一个看起来合理的正则——
`/articles/` ——去标记「我方文章」，结果把那个社区上**所有人**的文章
都算成了自己的，得出「我方被引 22 次」。

真实答案是 **0 次**。改成拿自己文章的真实 ID 逐个精确匹配之后，一篇都没有。

差别有多大：一个让人以为「技术社区这条路走通了」，一个说明「一篇都没进去」。
**这两个结论会导向完全相反的资源分配。**

所以规矩是：

    域名进了引用池  ≠  你的文章进了引用池

前者只说明「AI 认这个平台」，后者才说明「AI 认你写的东西」。
判断后者**必须落到 URL / ID 级的精确匹配**，不能用域名、不能用路径通配。

用法:
    domain_vs_article.py --citations cites.jsonl --assets my-assets.txt

    cites.jsonl  每行一个 JSON: {"engine":"...", "url":"..."}
    my-assets.txt 每行一个自有资产的唯一标识(文章 ID 或完整 URL),# 开头为注释
"""
import argparse, collections, json, re, sys


def domain_of(url):
    m = re.match(r"https?://([^/]+)", url)
    if not m:
        return None
    d = m.group(1).lower()
    return d[4:] if d.startswith("www.") else d


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--citations", required=True)
    p.add_argument("--assets", required=True,
                   help="自有资产清单。**必须是唯一标识**：文章数字 ID 或完整 URL；"
                        "不要写域名或路径片段，那正是本脚本要防的错误")
    a = p.parse_args()

    assets = []
    for line in open(a.assets, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            assets.append(line)
    # 防呆：资产标识太短或看着像域名/路径通配，直接拒绝——这类写法必然误匹配
    for x in assets:
        if len(x) < 8 or x.count("/") == 0 and "." in x and not x.isdigit():
            sys.exit(f"⛔ 资产标识 “{x}” 看起来像域名或过短的片段。\n"
                     f"   本脚本要求唯一标识（文章 ID 或完整 URL）。\n"
                     f"   用域名匹配正是它要防的那个错误，见文件头。")

    dom = collections.Counter()
    mine = collections.Counter()
    mine_by_engine = collections.Counter()
    urls_seen = set()

    for line in open(a.citations, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        url, eng = rec.get("url"), rec.get("engine", "?")
        if not url:
            continue
        d = domain_of(url)
        if d:
            dom[d] += 1
        urls_seen.add(url)
        for x in assets:
            if x in url:
                mine[x] += 1
                mine_by_engine[eng] += 1
                break

    print(f"引用总数 {sum(dom.values())} / 去重 URL {len(urls_seen)} / 去重域名 {len(dom)}\n")
    print("=== 被引域名 Top 15（域名级，只说明 AI 认这些平台）===")
    for d, n in dom.most_common(15):
        print(f"  {n:5d}  {d}")

    hit = sum(mine.values())
    print(f"\n=== 我方资产被引（文章级，逐 ID 精确匹配）：{hit} 次 ===")
    if hit:
        for x, n in mine.most_common():
            print(f"  {n:5d}  {x}")
        print("\n  按引擎:", dict(mine_by_engine.most_common()))
    else:
        print("  0 —— 一篇都没进引用池。")
        # 把「域名在池里但我们的文章不在」这件事明确点出来,这正是最容易读错的地方
        for x in assets:
            d = domain_of(x) if x.startswith("http") else None
            if d and dom.get(d):
                print(f"  ⚠️ 注意：{d} 这个域名在池中出现 {dom[d]} 次，"
                      f"但没有一次是你的内容。**别把这个数当成自己的成绩。**")


if __name__ == "__main__":
    main()
