"""scripts/domain_vs_article.py 的回归测试（只用标准库；用 subprocess 跑脚本本身）。

运行：在仓库根目录执行 `python3 -I -m unittest discover -s tests -v`。
夹具在 tests/fixtures/，全部是假 ID、假参数。
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.environ.get("DVA_SCRIPT", os.path.join(ROOT, "scripts", "domain_vs_article.py"))
FIX = os.path.join(ROOT, "tests", "fixtures")

P10_ASSET = "https://mp.weixin.qq.com/s?__biz=MzAxMTExMTExMQ==&mid=2247000001&idx=1&sn=aaaa1111aaaa1111aaaa1111aaaa1111"
P11_ASSET = "https://baijiahao.baidu.com/s?id=1700000000000000001"
NO_ID_WARNING = "没有平台 ID，只能按完整 URL 匹配，镜像域会漏"


def run(assets, cites):
    """资产逐行写进临时文件，引用取 fixtures 里的 jsonl；返回 (退出码, stdout+stderr)。"""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("\n".join(assets) + "\n")
        path = f.name
    try:
        p = subprocess.run([sys.executable, "-I", SCRIPT, "--citations", os.path.join(FIX, cites), "--assets", path],
                           capture_output=True, text=True, encoding="utf-8")
    finally:
        os.unlink(path)
    return p.returncode, p.stdout + p.stderr


def hit_count(out):
    m = re.search(r"我方资产被引[^\n]*：(\d+) 次", out)
    if not m:
        raise AssertionError("输出里没有「我方资产被引…：N 次」那一行：\n" + out)
    return int(m.group(1))


def hit_hosts(out):
    """「我方命中落在这些域名上」一节列出的主机名；没有这一节就报错（不许当成空集）。"""
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("=== 我方命中落在这些域名上"):
            hosts = []
            for l in lines[i + 1:]:
                m = re.fullmatch(r"\s+(\d+)\s+(\S+)", l)
                if not m:
                    break
                hosts.append(m.group(2))
            return hosts
    raise AssertionError("输出里没有「我方命中落在这些域名上」一节：\n" + out)


class IdMatching(unittest.TestCase):
    def test_p1_numeric_id_counts_all_mirror_hosts(self):
        rc, out = run(["1234567"], "mirror_ids.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertEqual(hit_count(out), 4, out)
        self.assertEqual(sorted(hit_hosts(out)), sorted(
            ["cloud.tencent.com", "cloud.tencent.cn", "developer.cloud.tencent.com", "cloud.tencent.com.cn"]), out)
        self.assertIn("命中分布在 4 个主机名上", out)

    def test_p2_url_asset_extracts_id(self):
        rc, out = run(["https://cloud.tencent.com/developer/article/1234567"], "mirror_ids.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertIn("→ 按 ID 1234567 匹配", out)
        self.assertEqual(hit_count(out), 4, out)  # 修前是 2：1 条正版＋以资产 URL 为前缀的诱饵，3 条镜像全漏

    def test_p3_boundary_decoys_not_counted(self):
        rc, out = run(["1234567"], "mirror_ids.jsonl")
        self.assertEqual(hit_count(out), 4, out)
        rc, out = run(["1234567"], "decoys_only.jsonl")  # 只有 …/12345678 与 …/91234567 两条诱饵
        self.assertEqual(rc, 0, out)
        self.assertEqual(hit_count(out), 0, out)

    def test_p6_short_id_case_sensitive_and_bounded(self):
        rc, out = run(["AbCdEfGh1jKlMnOpQrStUv"], "wx_short_mixed.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertEqual(hit_count(out), 1, out)
        self.assertEqual(hit_hosts(out), ["mp.weixin.qq.com"], out)
        self.assertNotIn("命中分布在", out)

    def test_p8_all_letter_short_id_via_wechat_url(self):
        rc, out = run(["https://mp.weixin.qq.com/s/AbCdEfGhIjKlMnOpQrStUv"], "wx_short_alpha.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertIn("→ 按 ID AbCdEfGhIjKlMnOpQrStUv 匹配", out)
        self.assertEqual(hit_count(out), 1, out)

    def test_p14_multi_asset_single_host_each_no_hint(self):
        rc, out = run(["1234567", "7654321"], "two_platforms.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertEqual(hit_count(out), 2, out)
        self.assertEqual(sorted(hit_hosts(out)), ["blog.csdn.net", "cloud.tencent.com"], out)
        self.assertNotIn("命中分布在", out)


class Rejection(unittest.TestCase):
    def test_p4_domain_path_wildcard_short_number_rejected(self):
        for x in ["cloud.tencent.com", "developer.volcengine.com", "/articles/", "article/", "*1234567", "12345"]:
            with self.subTest(asset=x):
                rc, out = run([x], "mirror_ids.jsonl")
                self.assertNotEqual(rc, 0, out)
                self.assertIn("域名或路径", out)

    def test_p7_slug_like_and_too_short_rejected(self):
        # 全字母的两个要有专属改写指引（逐字给出 /s/ URL）；通用拒收提示里也有「完整 URL」四个字，⛔ 不能拿它当断言
        for x, needs_url_hint in [("AbCdEfGhIjKlMnOpQrStUv", True), ("hello-world-article", True), ("AbCdEfGh1jKlMnO", False),
                                  ("1234-5678-9012-3456", False)]:
            with self.subTest(asset=x):
                rc, out = run([x], "wx_short_mixed.jsonl")
                self.assertNotEqual(rc, 0, out)
                if needs_url_hint:
                    self.assertIn("https://mp.weixin.qq.com/s/" + x, out)

    def test_p9_fullwidth_digits_rejected(self):
        rc, out = run(["１２３４５６７"], "mirror_ids.jsonl")
        self.assertNotEqual(rc, 0, out)


class Boundaries(unittest.TestCase):
    """规格边界值：数字 ID 6 位起、短 ID 16 位起、短 ID 两侧不许连字符、跨主机名提示从 2 个起。"""

    def test_six_digit_id_accepted_and_bounded(self):
        rc, out = run(["123456"], "boundary.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertEqual(hit_count(out), 1, out)  # …/123456 算，…/1234567 不算

    def test_sixteen_char_short_id_accepted_and_bounded(self):
        rc, out = run(["AbCdEfGh1jKlMnOp"], "boundary.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertEqual(hit_count(out), 1, out)  # …/AbCdEfGh1jKlMnOp 算，…/AbCdEfGh1jKlMnOpQ 不算

    def test_cross_host_hint_from_two_hosts(self):
        rc, out = run(["1234567"], "two_hosts.jsonl")
        self.assertEqual(hit_count(out), 2, out)
        self.assertIn("命中分布在 2 个主机名上", out)


class UrlExtraction(unittest.TestCase):
    def test_trailing_slash_url_still_extracts_id(self):
        rc, out = run(["https://cloud.tencent.com/developer/article/1234567/"], "two_hosts.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertIn("→ 按 ID 1234567 匹配", out)
        self.assertEqual(hit_count(out), 2, out)

    def test_last_path_segment_is_the_id(self):
        # 知乎回答 URL 里有问题 ID 和回答 ID 两个数字段：必须取最后一段（回答 ID），否则同一问题下别人的回答也算我方
        rc, out = run(["https://www.zhihu.com/question/12345678/answer/87654321"], "zhihu_answers.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertIn("→ 按 ID 87654321 匹配", out)
        self.assertEqual(hit_count(out), 1, out)

    def test_mid_path_number_not_taken_as_id(self):
        # 路径中间的日期段不是文章 ID：抽出来不限域名去配，会把同站当天的别的文章都算成我方
        rc, out = run(["https://news.example.com/politics/20241008/aaaa1111/c.html"], "date_path.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("→ 按 ID", out)
        self.assertIn(NO_ID_WARNING, out)
        self.assertEqual(hit_count(out), 1, out)

    def test_wildcard_url_rejected(self):
        rc, out = run(["https://cloud.tencent.com/developer/article/*"], "mirror_ids.jsonl")
        self.assertNotEqual(rc, 0, out)
        self.assertIn("域名或路径", out)


class UrlFallback(unittest.TestCase):
    def test_hash_route_kept_in_key(self):
        # 单页站的 #/…、#!… 路由区分文章：丢掉它整站会塌成同一个键（多算方向）
        for asset in ["https://h5.example.com/#/article/100001", "https://h5.example.com/#!/p/100001",
                      "https://h5.example.com/"]:  # 最后一个是反向：资产不带路由，带路由的引用都不算
            with self.subTest(asset=asset):
                rc, out = run([asset], "hash_route.jsonl")
                self.assertEqual(rc, 0, out)
                self.assertEqual(hit_count(out), 1, out)

    def test_hash_route_normalized(self):
        # 路由里的参数顺序、末尾 / 不论（否则同一篇会漏）
        rc, out = run(["https://h5.example.com/#/list?tag=geo&page=2"], "hash_route.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertEqual(hit_count(out), 1, out)

    def test_valueless_params_kept(self):
        # ?100001 这类只有键没有值的参数也要参与比较（路由里、查询串里都一样），否则同站别的文章塌成一个键
        for asset in ["https://h5.example.com/#/detail?100001", "https://h5.example.com/page?100001"]:
            with self.subTest(asset=asset):
                rc, out = run([asset], "hash_route.jsonl")
                self.assertEqual(rc, 0, out)
                self.assertEqual(hit_count(out), 1, out)

    def test_asset_with_dropped_fragment_rejected(self):
        # 资产自带的非路由 #… 比较时会被丢掉：若它在区分文章，同页别的文章会全算成我方，所以拒收
        rc, out = run(["https://h5.example.com/index.html#detail?id=100001"], "hash_route.jsonl")
        self.assertNotEqual(rc, 0, out)
        self.assertIn("带有 #detail?id=100001 片段", out)  # 片段专属提示；通用拒收提示里也有「文章 ID」，⛔ 不能拿它当断言

    def test_domain_in_pool_hint_only_for_url_fallback_assets(self):
        rc, out = run(["https://example.com/post/not-cited"], "degenerate_example.jsonl")
        self.assertEqual(hit_count(out), 0, out)
        self.assertIn("example.com 这个域名在池中出现 1 次", out)
        rc, out = run(["https://cloud.tencent.com/developer/article/7777777"], "mirror_ids.jsonl")  # 抽得到 ID 的 URL
        self.assertEqual(hit_count(out), 0, out)
        self.assertNotIn("这个域名在池中出现", out)

    def test_p5_normalized_equality(self):
        rc, out = run(["https://example.com/post/hello-world"], "degenerate_example.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertEqual(hit_count(out), 1, out)
        self.assertIn(NO_ID_WARNING, out)

    def test_p10_wechat_long_link_query_kept_and_sorted(self):
        rc, out = run([P10_ASSET], "wechat_long.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertIn(NO_ID_WARNING, out)
        self.assertEqual(hit_count(out), 1, out)

    def test_p11_baijiahao_query_kept(self):
        rc, out = run([P11_ASSET], "baijiahao.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertEqual(hit_count(out), 1, out)

    def test_p12_bare_entry_url_matches_nothing(self):
        rc, out = run(["https://mp.weixin.qq.com/s"], "wechat_long.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertEqual(hit_count(out), 0, out)

    def test_p13_s_path_on_other_host_not_extracted(self):
        rc, out = run(["https://example.com/s/hello-world-article-slug"], "slug_s.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertIn(NO_ID_WARNING, out)
        self.assertNotIn("→ 按 ID", out)
        self.assertEqual(hit_count(out), 1, out)

    def test_p15_query_param_value_as_id_workaround(self):
        rc, out = run([P10_ASSET], "wechat_long_tracking.jsonl")  # ① 长链 URL：跟踪参数那条漏了
        self.assertEqual((rc, hit_count(out)), (0, 1), out)
        self.assertIn(NO_ID_WARNING, out)
        rc, out = run(["aaaa1111aaaa1111aaaa1111aaaa1111"], "wechat_long_tracking.jsonl")  # ② sn 的值当 ID
        self.assertEqual((rc, hit_count(out)), (0, 2), out)
        self.assertNotIn(NO_ID_WARNING, out)
        rc, out = run([P11_ASSET], "baijiahao_tracking.jsonl")  # ③ 百家号 URL
        self.assertEqual((rc, hit_count(out)), (0, 1), out)
        rc, out = run(["1700000000000000001"], "baijiahao_tracking.jsonl")  # ④ id 的值当 ID
        self.assertEqual((rc, hit_count(out)), (0, 2), out)


if __name__ == "__main__":
    unittest.main()
