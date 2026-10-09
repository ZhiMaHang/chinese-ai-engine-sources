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
判断后者**必须落到文章 ID 级的精确匹配**，不能用域名、不能用路径通配。

**还有第二个坑：镜像域。** 同一篇文章常常以好几个主机名被引（`.com`、`.cn`、
`.com.cn`、`developer.` 子域……），引擎引哪个不确定。按域名或 URL 前缀去数，
镜像域上的命中会全部漏掉。所以本脚本按**文章 ID 不限域名**匹配：

- 资产写成纯数字 ID（6 位以上），或 16 位以上、同时含字母和数字的短 ID：
  在 URL 里找这个 ID，两侧边界不能是同类字符（数字 ID 两侧不是数字；
  短 ID 两侧不是字母、数字、下划线、连字符），区分大小写，不限域名。
- 资产写成完整 URL：先从路径里抽平台 ID（路径最后一段是 6 位以上的纯数字；
  公众号 `mp.weixin.qq.com/s/<短ID>`），抽到了就改按 ID 匹配。只认最后一段，是因为
  路径中间的数字段常常是日期或栏目号，当成 ID 再不限域名去配，会把同站当天的别的文章都算成我方。
- 抽不到 ID 的 URL 只能按完整 URL 等值比较（协议不论、主机名不分大小写并去掉
  开头的 `www.`、去掉 `#…` 和路径末尾的 `/`；查询参数参与比较，顺序不论；
  `#/…`、`#!…` 这类单页站的 hash 路由例外，照样参与比较，否则整站会塌成同一个键）。
  镜像域上的引用、多了跟踪参数的引用都会漏，脚本会打出警告。

用法:
    domain_vs_article.py --citations cites.jsonl --assets my-assets.txt

    cites.jsonl  每行一个 JSON: {"engine":"...", "url":"..."}
    my-assets.txt 每行一个自有资产的唯一标识（文章 ID 优先；或完整 URL），# 开头为注释
"""
import argparse, collections, json, re, sys
from urllib.parse import parse_qsl, urlsplit

# 一律用显式 ASCII 字符类：Python 的 \d 会匹配全角数字，全角 ID 收下后在 ASCII 的 URL 上永远配不上。
NUM_ID = re.compile(r"[0-9]{6,}")
SHORT_ID = re.compile(r"[A-Za-z0-9_-]{16,}")
HAS_LETTER = re.compile(r"[A-Za-z]")
HAS_DIGIT = re.compile(r"[0-9]")
URL_PREFIX = re.compile(r"https?://", re.IGNORECASE)
WECHAT_SHORT_PATH = re.compile(r"/s/([A-Za-z0-9_-]{16,})/?")

REJECT_HINT = ("   本脚本要求唯一标识：文章 ID，或能从中抽出文章 ID 的完整 URL。\n"
               "   用域名、路径片段或通配去匹配，正是它要防的那个错误，见文件头。")


def domain_of(url):
    m = re.match(r"https?://([^/]+)", url)
    if not m:
        return None
    d = m.group(1).lower()
    return d[4:] if d.startswith("www.") else d


def url_key(url):
    """抽不到 ID 的 URL 的等值比较键：协议不论、主机名小写去 www.、去 fragment、去路径末尾 /；
    查询参数保留并排序（⛔ 不丢：公众号长链、百家号这类靠参数区分文章，丢了会整站塌成一个键）。
    fragment 以 / 或 ! 开头的是单页站的 hash 路由（#/article/1、#!/p/2），同理保留，
    并对路由本身做同样的规范化（末尾 / 不论、路由里的查询参数顺序不论）。"""
    try:
        u = urlsplit(url)
        host = (u.hostname or "").lower()
        port = u.port
    except ValueError:
        return None
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    if port:
        host = f"{host}:{port}"
    route = ""
    if u.fragment.startswith(("/", "!")):
        r_path, _, r_query = u.fragment.partition("?")
        route = (r_path.rstrip("/"), tuple(sorted(parse_qsl(r_query, keep_blank_values=True))))
    return (host, u.path.rstrip("/"), tuple(sorted(parse_qsl(u.query, keep_blank_values=True))), route)


def classify(x):
    """返回 ("num"|"short", ID) 或 ("url", 规范化键)；写法不合格就退出。"""
    if "*" in x:
        sys.exit(f"⛔ 资产标识 “{x}” 含通配符 *，看起来像域名或路径片段的通配写法，拒收。\n{REJECT_HINT}")
    if URL_PREFIX.match(x):
        try:
            u = urlsplit(x)
        except ValueError:
            sys.exit(f"⛔ 资产标识 “{x}” 不是合法的 URL。\n{REJECT_HINT}")
        segs = [s for s in u.path.split("/") if s]
        if segs and NUM_ID.fullmatch(segs[-1]):
            aid = segs[-1]
            print(f"资产 {x} → 按 ID {aid} 匹配（不限域名，镜像域也算）")
            return ("num", aid)
        # /s/<短ID> 只认公众号的主机名：别的站上的 /s/<slug> 抽出来再不限域名去配，会把别人同名 slug 算成我方
        m = WECHAT_SHORT_PATH.fullmatch(u.path)
        if m and (u.hostname or "") == "mp.weixin.qq.com":
            aid = m.group(1)
            print(f"资产 {x} → 按 ID {aid} 匹配（不限域名，镜像域也算）")
            return ("short", aid)
        # 资产自带的 #… 只要不是 #/、#! 路由就会被丢掉；它若在区分文章（如 #detail?id=1），同页别的文章会全算成我方
        if u.fragment and not u.fragment.startswith(("/", "!")):
            sys.exit(f"⛔ 资产标识 “{x}” 带有 #{u.fragment} 片段，比较时会被丢掉。\n"
                     f"   普通页内锚点请去掉 # 及后面的部分；如果它在区分文章（hash 路由），请直接写文章 ID。\n{REJECT_HINT}")
        key = url_key(x)
        if key is None:
            sys.exit(f"⛔ 资产标识 “{x}” 解析不出主机名。\n{REJECT_HINT}")
        print(f"⚠️ 资产 {x}：此资产没有平台 ID，只能按完整 URL 匹配，镜像域会漏；"
              f"查询参数也参与比较，参数不一样（包括多了跟踪参数）的引用同样会漏。")
        return ("url", key)
    if NUM_ID.fullmatch(x):
        return ("num", x)
    if SHORT_ID.fullmatch(x):
        if HAS_LETTER.search(x) and HAS_DIGIT.search(x):
            return ("short", x)
        if not HAS_DIGIT.search(x):
            sys.exit(f"⛔ 资产标识 “{x}” 一个数字都没有，像是标题 slug 而不是文章 ID，拒收。\n"
                     f"   如果它确实是公众号短 ID（恰好全是字母），请改写成完整 URL："
                     f"https://mp.weixin.qq.com/s/{x}\n{REJECT_HINT}")
    sys.exit(f"⛔ 资产标识 “{x}” 看起来像域名或路径片段、通配，或过短的编号。\n{REJECT_HINT}")


def matcher(kind, val):
    if kind == "num":
        rx = re.compile(r"(?<![0-9])" + re.escape(val) + r"(?![0-9])")
        return lambda url: rx.search(url) is not None
    if kind == "short":
        rx = re.compile(r"(?<![0-9A-Za-z_-])" + re.escape(val) + r"(?![0-9A-Za-z_-])")
        return lambda url: rx.search(url) is not None
    return lambda url: url_key(url) == val


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--citations", required=True)
    p.add_argument("--assets", required=True,
                   help="自有资产清单。**必须是唯一标识**：文章 ID（纯数字 6 位以上，或 16 位以上含字母和数字的短 ID），"
                        "或能抽出文章 ID 的完整 URL；不要写域名或路径片段，那正是本脚本要防的错误")
    a = p.parse_args()

    assets = []
    for line in open(a.assets, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            assets.append(line)
    # 防呆：资产先分类，域名样式、路径片段、通配、过短的编号一律拒收——这类写法必然误匹配
    rules = [(x, kind, val, matcher(kind, val)) for x in assets for kind, val in [classify(x)]]

    dom = collections.Counter()
    mine = collections.Counter()
    mine_by_engine = collections.Counter()
    mine_hosts = collections.Counter()
    hosts_by_asset = collections.defaultdict(set)
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
        for x, kind, val, hit_fn in rules:
            if hit_fn(url):
                mine[x] += 1
                mine_by_engine[eng] += 1
                mine_hosts[d or "?"] += 1
                hosts_by_asset[x].add(d or "?")
                break

    print(f"引用总数 {sum(dom.values())} / 去重 URL {len(urls_seen)} / 去重域名 {len(dom)}\n")
    print("=== 被引域名 Top 15（域名级，只说明 AI 认这些平台）===")
    for d, n in dom.most_common(15):
        print(f"  {n:5d}  {d}")

    hit = sum(mine.values())
    print(f"\n=== 我方资产被引（文章级，按 ID 精确匹配、不限域名）：{hit} 次 ===")
    if hit:
        for x, n in mine.most_common():
            print(f"  {n:5d}  {x}")
        print("\n  按引擎:", dict(mine_by_engine.most_common()))
        print("\n=== 我方命中落在这些域名上（镜像域一眼可见）===")
        for d, n in mine_hosts.most_common():
            print(f"  {n:5d}  {d}")
        # 按资产逐个判断：多个平台的资产放在一起时，整节主机名本来就会 ≥2，按整节判断会沦为噪音
        for x, _ in mine.most_common():
            if len(hosts_by_asset[x]) >= 2:
                print(f"  ⚠️ 资产 {x} 的命中分布在 {len(hosts_by_asset[x])} 个主机名上：同一平台的镜像域属正常；"
                      f"但数字 ID 不限域名，别的站上恰好同号的 URL 也会被算进来，请逐条人工核。")
    else:
        print("  0 —— 一篇都没进引用池。")
        # 把「域名在池里但我们的文章不在」这件事明确点出来,这正是最容易读错的地方
        # （只对抽不到 ID、按完整 URL 匹配的资产有意义）
        for x, kind, val, _ in rules:
            d = domain_of(x) if kind == "url" else None
            if d and dom.get(d):
                print(f"  ⚠️ 注意：{d} 这个域名在池中出现 {dom[d]} 次，"
                      f"但没有一次是你的内容。**别把这个数当成自己的成绩。**")


if __name__ == "__main__":
    main()
