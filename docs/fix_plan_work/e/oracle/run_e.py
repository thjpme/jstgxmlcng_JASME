"""単位 E の、実装を見ない反例の期待と実際を比べる。

使い方:
    python run_e.py --src <jasme_jats の src> [--label 名前] [--only N01,A01,...] [--list]

- 指定した src の jasme_jats を import し、公開 API（pipeline.convert・Options）だけで変換する。
- docx は gen_e.py で作る（docx/ に置く。なければその場で作る）。
- ケースごとに OK / FAIL と理由を出す。期待には「exact」（FIX_PLAN の方針から一つに決まる）と、
  「either」（決めかねるので、許される結果を列挙し、どれかに当たれば OK）がある。どの either に当たったかも出す。
- 結果は results_<label>.json に書く。--list は期待の一覧（cases_e.json）を書いて終わる。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def setup(src):
    """src は jasme_jats を含むフォルダ（リポジトリの src）か、jasme_jats のパッケージのフォルダそのもの（base0231_src など）。
    パッケージのフォルダなら、jasme_jats という名前のリンクを作ってから読む。読んだ jasme_jats が src のものでなければ止める。"""
    src = Path(src).resolve()
    if (src / "jasme_jats" / "__init__.py").exists():
        root, pkg = src, src / "jasme_jats"
    elif (src / "__init__.py").exists():
        root = HERE / (".pkg_" + __import__("hashlib").md5(str(src).encode()).hexdigest()[:10])
        root.mkdir(exist_ok=True)
        link = root / "jasme_jats"
        if not link.exists():
            link.symlink_to(src, target_is_directory=True)
        pkg = src
    else:
        sys.exit(f"jasme_jats が見つからない: {src}")
    sys.path.insert(0, str(root))
    global convert, Options, etree, META, JOURNAL
    import jasme_jats
    if Path(jasme_jats.__file__).resolve().parent != pkg.resolve():
        sys.exit(f"指定と違う jasme_jats を読んだ: {jasme_jats.__file__}（指定 {pkg}）")
    from lxml import etree  # noqa: F401
    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import Options, convert  # noqa: F401
    META = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                                  "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり",
                                  "keywords": "proof; 論証"})
    JOURNAL = JournalConfig.load()


# ----------------------------------------------------------------------------- 変換と取り出し
class Run:
    def __init__(self, res, out):
        self.res = res
        self.root = etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])
        self.report = res.report_path.read_text(encoding="utf-8")
        self.prompt = res.prompt_path.read_text(encoding="utf-8") if res.prompt_path and res.prompt_path.exists() else ""
        self.out = out

    def fns(self):
        return [{"id": fn.get("id"), "text": text(fn), "ps": [text(p) for p in fn.findall("p")]}
                for fn in self.root.findall(".//fn-group/fn")]

    def body_xrefs(self):
        """本文（fn-group の外）の注へのリンク: (rid, 文字, sup があるか)。"""
        fg = set(self.root.iterfind(".//fn-group//xref"))
        return [(x.get("rid"), text(x), x.find("sup") is not None)
                for x in self.root.iter("xref") if x.get("ref-type") == "fn" and x not in fg]

    def fn_xrefs(self):
        return [(x.get("rid"), text(x)) for x in self.root.iterfind(".//fn-group//xref") if x.get("ref-type") == "fn"]

    def apps(self):
        return [{"title": app.findtext("title"), "text": text(app)} for app in self.root.iterfind(".//app-group/app")]

    def trans_abstract(self):
        ta = self.root.find(".//trans-abstract")
        return [text(p) for p in ta.findall("p")] if ta is not None else None

    def xml_text(self):
        return text(self.root)

    def excluded(self):
        return list(self.res.fidelity.excluded)

    def src_of(self, plain):
        """段落の文字（物の印 U+FFFC と前後の空白を除いて比べる）から段落 ID を引く。見つからなければ例外（FAIL にする）。"""
        def norm(t):
            return t.replace("\ufffc", "").strip()
        for s, p in self.res.plan.paras.items():
            if norm(p.plain()) == norm(plain):
                return s
        for s, why, t in self.res.fidelity.excluded:
            if norm(t) == norm(plain):
                return s
        raise LookupError(f"段落が見つからない: {plain}")


def text(el):
    return "".join(el.itertext())


DOCX = HERE / "docx"


def docx(name):
    p = DOCX / f"{name}.docx"
    if not p.exists():
        import gen_e
        DOCX.mkdir(exist_ok=True)
        gen_e.build(name, p)
    return p


def conv(ctx, name, ops=None, manual=False, tag=""):
    out = ctx["out"] / f"{name}{tag}"
    if out.exists():
        shutil.rmtree(out)
    kw = dict(out_dir=out, convert_metafiles=False)
    if ops is not None:
        kw.update(ai_mode="manual", ai_response=json.dumps({"operations": ops, "placements": [], "notes": []},
                                                              ensure_ascii=False))
    elif manual:
        kw.update(ai_mode="manual")
    return Run(convert(docx(name), META, JOURNAL, Options(**kw)), out)


def op(src, role):
    return {"op": "set_role", "src": src, "text": "", "occurrence": 1, "target": "", "role": role, "image": "",
            "mathml": "", "surname": "", "given": "", "reason": "試験", "confidence": "高"}


# ----------------------------------------------------------------------------- 期待の書き方
class Checks:
    def __init__(self):
        self.items = []     # (kind, 期待, ok, 実際)

    def exact(self, what, ok, actual=""):
        self.items.append(("exact", what, bool(ok), str(actual)[:400]))

    def either(self, what, alts, actual=""):
        """alts: [(名前, ok)]。どれかに当たれば OK。"""
        hit = [n for n, ok in alts if ok]
        self.items.append(("either", f"{what}（許す: {' / '.join(n for n, _ in alts)}）", bool(hit),
                           f"当たり: {hit}; {str(actual)[:300]}"))

    def info(self, what, actual):
        self.items.append(("info", what, True, str(actual)[:400]))


def common(c, r, label=""):
    res = r.res
    c.exact(f"{label}不変性チェック・最終チェック・DTD に合格",
            res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid,
            (res.fidelity.ok, res.fidelity.final_ok, res.dtd_valid, getattr(res.fidelity, "problems", ""))[:3])
    c.exact(f"{label}J-STAGE のチェックの問題なし", res.jstage_issues == [], res.jstage_issues)
    c.exact(f"{label}XML に入らなかった画像なし", res.lost_images == [], res.lost_images)


def no_endnote_provisional(c, r):
    bad = [line for line in r.report.splitlines() if "文末脚注" in line and "出力していません" in line]
    c.exact("「Word の文末脚注を XML に出力していません」の暫定の知らせが出ない", not bad, bad[:2])
    unsupported = [e for e in r.excluded() if "未対応" in e[1]]
    c.exact("「未対応」の理由の除外がない", not unsupported, unsupported)


def fn_marks(c, r, texts):
    """fn-group の注が texts の順で、番号が 1) 2) … の通し番号。"""
    fns = r.fns()
    c.exact(f"fn-group の注が {len(texts)} 件", len(fns) == len(texts), [f["text"][:30] for f in fns])
    for i, t in enumerate(texts, 1):
        f = fns[i - 1] if i <= len(fns) else None
        c.exact(f"fn{i} が「{t[:16]}…」で、id=fn{i}・先頭が「{i})」",
                f is not None and f["id"] == f"fn{i}" and t in f["text"] and f["text"].startswith(f"{i})"),
                f and (f["id"], f["text"][:40]))


def body_refs(c, r, expect):
    got = r.body_xrefs()
    c.exact(f"本文の注のリンク（rid・文字・上付き）が {expect}", got == expect, got)


def excluded_with(r, needle):
    return [e for e in r.excluded() if needle in e[2]]


def not_in_xml(c, r, needle):
    c.exact(f"「{needle[:16]}」が XML にない", needle not in r.xml_text())


def in_xml(c, r, needle):
    c.exact(f"「{needle[:16]}」が XML にある", needle in r.xml_text())


def prompt_lines(r, src):
    return [line for line in r.prompt.splitlines() if line.startswith(f"- [{src}]")]


# ----------------------------------------------------------------------------- ケース
CASES = {}


def case(name, desc):
    def deco(f):
        CASES[name] = (desc, f)
        return f
    return deco


@case("N01", "文末脚注だけ（2 段落の文末脚注 1 件）が fn-group の fn1 になる")
def c_n01(ctx, c):
    r = conv(ctx, "N01")
    common(c, r)
    fn_marks(c, r, ["文末脚注の一段落目の架空の説明。"])
    f = r.fns()[:1]
    c.exact("fn1 は 2 段落（2 段落目は文末脚注の二段落目）", f and len(f[0]["ps"]) == 2 and "二段落目" in f[0]["ps"][1], f)
    c.exact("fn-group の見出しは「注」（Word の脚注と同じく補う）", r.root.findtext(".//fn-group/title") == "注",
            r.root.findtext(".//fn-group/title"))
    body_refs(c, r, [("fn1", "1)", True)])
    no_endnote_provisional(c, r)


@case("N02", "脚注だけ（今のまま。回帰）")
def c_n02(ctx, c):
    r = conv(ctx, "N02")
    common(c, r)
    fn_marks(c, r, ["脚注だけの原稿の架空の注。"])
    body_refs(c, r, [("fn1", "1)", True)])
    c.exact("レポートの文言は今のまま「注 1（うち Word の脚注 1）」", "注 1（うち Word の脚注 1）" in r.report)


@case("N03", "脚注と文末脚注が本文で入れ違いに参照される（文末 3・脚注 5・文末 4）→ 本文で最初に参照される順の通し番号")
def c_n03(ctx, c):
    r = conv(ctx, "N03")
    common(c, r)
    fn_marks(c, r, ["文末脚注Ｂの架空の文。", "脚注Ａの架空の文。", "文末脚注Ｃの架空の文。"])
    body_refs(c, r, [("fn1", "1)", True), ("fn2", "2)", True), ("fn3", "3)", True)])
    no_endnote_provisional(c, r)
    c.info("レポートの注の件数の行（脚注と文末脚注の表記）", [ln for ln in r.report.splitlines() if "うち Word の" in ln][:2])


@case("N04", "脚注 id=5 と文末脚注 id=5 の衝突（脚注が先）→ fn1・fn2 に分かれる")
def c_n04(ctx, c):
    r = conv(ctx, "N04")
    common(c, r)
    fn_marks(c, r, ["番号が重なる脚注の架空の文。", "番号が重なる文末脚注の架空の文。"])
    body_refs(c, r, [("fn1", "1)", True), ("fn2", "2)", True)])


@case("N05", "脚注 id=5 と文末脚注 id=5 の衝突（文末脚注が先）→ 文末脚注が fn1")
def c_n05(ctx, c):
    r = conv(ctx, "N05")
    common(c, r)
    fn_marks(c, r, ["先に参照される文末脚注の架空の文。", "後に参照される脚注の架空の文。"])
    body_refs(c, r, [("fn1", "1)", True), ("fn2", "2)", True)])


@case("N06", "脚注の中から文末脚注を参照 → 文末脚注は除外されず fn2 になる")
def c_n06(ctx, c):
    r = conv(ctx, "N06")
    common(c, r)
    fn_marks(c, r, ["この脚注の中から文末脚注を参照する", "脚注の中から参照される架空の文末脚注。"])
    body_refs(c, r, [("fn1", "1)", True)])
    c.exact("文末脚注が除外されていない", not excluded_with(r, "脚注の中から参照される"), excluded_with(r, "脚注の中から参照される"))
    c.either("fn1 の中の参照", [("fn2 へのリンク「2)」", ("fn2", "2)") in r.fn_xrefs()),
                                ("リンクなし（番号の文字だけ・何もなし）", ("fn2", "2)") not in r.fn_xrefs())], r.fn_xrefs())
    no_endnote_provisional(c, r)


@case("N07", "参照が w:del の中の脚注 → 参照されていない注として理由付きで除外（不変性チェックに合格）")
def c_n07(ctx, c):
    r = conv(ctx, "N07")
    common(c, r)
    fn_marks(c, r, ["残る脚注の架空の文。"])
    body_refs(c, r, [("fn1", "1)", True)])
    not_in_xml(c, r, "参照が削除された脚注の架空の文。")
    ex = excluded_with(r, "参照が削除された脚注")
    c.exact("参照が削除された脚注が、空白以外の理由付きで除外されている",
            len(ex) == 1 and ex[0][1] and ex[0][1] != "空白のみの段落", ex)


@case("N08", "参照が w:ins の中の脚注 → ふつうの参照として fn2")
def c_n08(ctx, c):
    r = conv(ctx, "N08")
    common(c, r)
    fn_marks(c, r, ["残る脚注の架空の文。", "参照が挿入された脚注の架空の文。"])
    body_refs(c, r, [("fn1", "1)", True), ("fn2", "2)", True)])


@case("N09", "参照されていない脚注・文末脚注（文字あり）→ 理由付きで除外。AI 依頼文で set_role を勧めない")
def c_n09(ctx, c):
    r = conv(ctx, "N09", manual=True)
    common(c, r)
    fn_marks(c, r, ["参照される文末脚注の架空の文。"])
    body_refs(c, r, [("fn1", "1)", True)])
    for needle in ("どこからも参照されない脚注の架空の文。", "どこからも参照されない文末脚注の架空の文。"):
        not_in_xml(c, r, needle)
        ex = excluded_with(r, needle)
        c.exact(f"「{needle[:12]}」が理由付きで除外（空白の理由・未対応の理由ではない）",
                len(ex) == 1 and ex[0][1] and ex[0][1] != "空白のみの段落" and "未対応" not in ex[0][1], ex)
        src = ex[0][0] if ex else None
        lines = prompt_lines(r, src) if src else []
        c.exact(f"AI 依頼文の除外一覧で「{needle[:12]}」に set_role を勧めない（N6）",
                lines and not any("set_role" in line for line in lines), lines)
    no_endnote_provisional(c, r)


@case("N10", "参照されていない脚注・文末脚注が空白だけ（全角・半角）→ 空白のみの段落として除外し、合格")
def c_n10(ctx, c):
    r = conv(ctx, "N10")
    common(c, r)
    fn_marks(c, r, ["参照される脚注の架空の文。"])
    blanks = [e for e in r.excluded() if e[2] and not e[2].strip()]
    c.exact("空白だけの注の段落 2 件が「空白のみの段落」として除外",
            len([e for e in blanks if e[1] == "空白のみの段落" and e[0][0] in "fe"]) == 2, blanks)


@case("N11", "文末脚注の中の空白だけの段落 → 合格、前後の文字は fn1 に入る")
def c_n11(ctx, c):
    r = conv(ctx, "N11")
    common(c, r)
    fn_marks(c, r, ["空白の段落の前の架空の文。"])
    f = r.fns()[:1]
    c.exact("fn1 に空白の段落の後の文も入る", f and "空白の段落の後の架空の文。" in f[0]["text"], f)
    c.either("空白だけの段落", [("空白のみの段落として除外", any(e[1] == "空白のみの段落" and e[2] == "　"
                                                    for e in r.excluded())),
                            ("fn1 の段落として出力（3 段落）", f and len(f[0]["ps"]) == 3)], f)


@case("N12", "customMarkFollows の文末脚注（3 件の 2 件目）→ 番号を 1 つ使い、印の文字は docx のまま（暫定の判断 2）")
def c_n12(ctx, c):
    r = conv(ctx, "N12")
    common(c, r)
    fns = r.fns()
    c.exact("fn-group の注が 3 件", len(fns) == 3, [f["text"][:20] for f in fns])
    c.exact("fn1 は「1)」で始まる一つ目の注", len(fns) > 0 and fns[0]["text"].startswith("1)") and "一つ目" in fns[0]["text"],
            fns[:1])
    c.exact("fn3 は「3)」で始まる三つ目の注（番号を 1 つ使う）",
            len(fns) > 2 and fns[2]["id"] == "fn3" and fns[2]["text"].startswith("3)") and "三つ目" in fns[2]["text"], fns[2:3])
    c.exact("fn2 に記号の注の文字", len(fns) > 1 and "記号の架空の注。" in fns[1]["text"], fns[1:2])
    c.either("fn2 の先頭", [("docx の記号「*」のまま", len(fns) > 1 and fns[1]["text"].startswith("*")),
                         ("生成した「2)」", len(fns) > 1 and fns[1]["text"].startswith("2)"))], fns[1:2])
    body_refs(c, r, [("fn1", "1)", True), ("fn2", "", False), ("fn3", "3)", True)])
    in_xml(c, r, "記号で示す文末脚注*。")


@case("N13", "参照だけの段落（文字のない段落）の中の参照も参照として数え、注を出力する")
def c_n13(ctx, c):
    r = conv(ctx, "N13")
    common(c, r)
    fns = r.fns()
    c.exact("fn-group に参照だけの段落から参照される脚注がある",
            len(fns) == 1 and "参照だけの段落から参照される架空の脚注。" in fns[0]["text"], fns)
    c.either("本文のリンク", [("fn1 へのリンクあり", ("fn1", "1)", True) in r.body_xrefs()),
                          ("リンクなし（段落を除外。Decision・8 章で知らせる）", r.body_xrefs() == [])], r.body_xrefs())


ABS0 = "This fictional abstract describes a classroom study on shapes."


def app_case(name, title, nxt):
    def f(ctx, c):
        r = conv(ctx, name)
        common(c, r)
        apps = r.apps()
        c.exact(f"app-group/app/title が「{title}」", [a["title"] for a in apps] == [title], apps)
        c.exact("続く段落が app の中", apps and nxt in apps[0]["text"], apps)
        c.exact("英文要旨は要旨の段落だけ", r.trans_abstract() == [ABS0], r.trans_abstract())
        return r
    return f


for _n, _t, _x, _d in [
    ("A01", "資料（授業プリント）", "問1　架空の式を計算せよ。", "「資料（授業プリント）」（かっこ）"),
    ("A02", "資料Ⅰ　授業プリント", "問1　架空の式を計算せよ。", "「資料Ⅰ　授業プリント」（ローマ数字）"),
    ("A03", "資料Ⅱ（ワークシート）", "問1　架空の式を計算せよ。", "「資料Ⅱ（ワークシート）」"),
    ("A04", "付録①　調査票", "問1　架空の式を計算せよ。", "「付録①　調査票」（丸数字・本文のスタイル）"),
    ("A05", "資料1-2　授業の記録", "問1　架空の式を計算せよ。", "「資料1-2　授業の記録」（枝番）"),
    ("A06", "【資料1】", "問1　架空の式を計算せよ。", "「【資料1】」（先頭の括弧）"),
    ("A07", "Appendix A", "Question 1. Compute the fictional expression.", "「Appendix A」"),
    ("A08", "資料", "問1　架空の式を計算せよ。", "「資料」だけの行（行末）"),
    ("A15", "資料　授業プリント", "問1　架空の式を計算せよ。", "「資料　授業プリント」（今も認識する。回帰）"),
    ("A17", "資料1　調査票", "問1　架空の式を計算せよ。", "本文のスタイルの「資料1　調査票」（今も認識する。A04 の比較）"),
]:
    case(_n, f"英文要旨の後の {_d} が資料の見出しになる")(app_case(_n, _t, _x))


@case("A16", "英文要旨の後の「資料1　…」「資料2　…」が 2 つの app になる")
def c_a16(ctx, c):
    r = conv(ctx, "A16")
    common(c, r)
    apps = r.apps()
    c.exact("app が 2 つ（資料1・資料2）", [a["title"] for a in apps] == ["資料1　架空の授業プリント", "資料2　架空のワークシート"],
            apps)
    c.exact("英文要旨は要旨の段落だけ", r.trans_abstract() == [ABS0], r.trans_abstract())


def not_app_case(name, line):
    def f(ctx, c):
        r = conv(ctx, name)
        common(c, r)
        c.exact("app-group がない", r.apps() == [], r.apps())
        c.exact(f"「{line}」は英文要旨のまま", line in (r.trans_abstract() or []), r.trans_abstract())
    return f


case("A09", "英文要旨の後の「資料を配布した。」（文）は資料の見出しにしない")(not_app_case("A09", "資料を配布した。"))
case("A10", "英文要旨の後の「資料-1　…」（語の直後の ASCII のハイフン）は資料の見出しにしない")(
    not_app_case("A10", "資料-1　授業プリント"))


def heading_app_case(name, title, nxt):
    def f(ctx, c):
        r = app_case(name, title, nxt)(ctx, c)
        src = r.src_of(title)
        decs = [d for d in r.res.plan.decisions if d.src == src]
        c.exact("見出しのスタイルで資料を始めた Decision がその段落に記録される（決定事項 8(a)）", bool(decs),
                [(d.category, d.message[:60]) for d in decs])
    return f


case("A11", "英文要旨の後の章見出しのスタイルの段落（RE_APPENDIX に合わない文字）から資料を始め、Decision を記録")(
    heading_app_case("A11", "授業で用いたワークシート", "ワークシートの架空の問いを示す。"))
case("A11b", "英文要旨の後の節見出しのスタイルの段落から資料を始め、Decision を記録")(
    heading_app_case("A11b", "架空の調査の記録", "調査の架空の手順を示す。"))


@case("A12", "和文の論文で、英文要旨の中に和文の段落 → 移さず、Decision（applied=False）と 10 章の警告")
def c_a12(ctx, c):
    import gen_e
    r = conv(ctx, "A12")
    rc = conv(ctx, "A12c")
    common(c, r)
    c.exact("英文要旨の 3 段落はそのまま（自動では移さない）", r.trans_abstract() == [
        ABS0, gen_e.JP_IN_ABS, "The fictional results suggest further study."], r.trans_abstract())
    src = r.src_of(gen_e.JP_IN_ABS)
    decs = [d for d in r.res.plan.decisions if d.src == src and not d.applied]
    c.exact("和文の段落に Decision（applied=False）", bool(decs), [(d.message[:60], d.applied) for d in r.res.plan.decisions
                                                              if d.src == src])
    new = sorted(set(r.res.warnings) - set(rc.res.warnings))
    c.exact("10 章の警告が増える（和文の段落がない原稿と比べて）", bool(new), new)


@case("A13", "英文要旨の段落に漢字が少し（3 割未満）→ 警告しない")
def c_a13(ctx, c):
    import gen_e
    r = conv(ctx, "A13")
    rc = conv(ctx, "A13c")
    common(c, r)
    c.exact("英文要旨は 2 段落のまま", r.trans_abstract() == [ABS0, gen_e.SMALL_JP], r.trans_abstract())
    new = sorted(set(r.res.warnings) - set(rc.res.warnings))
    c.exact("警告が増えない", not new, new)
    src = r.src_of(gen_e.SMALL_JP)
    c.exact("その段落に applied=False の Decision がない",
            not [d for d in r.res.plan.decisions if d.src == src and not d.applied])


@case("A14", "引用文献の後ろの「資料　…」（章見出しのスタイル）→ 暫定の判断 1 では警告だけ（資料にしてもよい）")
def c_a14(ctx, c):
    r = conv(ctx, "A14")
    rc = conv(ctx, "A14c")
    common(c, r)
    in_xml(c, r, "引用文献の後ろに置いた資料の架空の中身。")
    new = sorted(set(r.res.warnings) - set(rc.res.warnings))
    apps = r.apps()
    c.either("引用文献の後ろの資料", [
        ("資料にせず 10 章の警告（暫定の判断 1）", apps == [] and bool(new)),
        ("app-group/app/title が「資料　架空の授業プリント」（決定事項 8(b) の『はい』）",
         [a["title"] for a in apps] == ["資料　架空の授業プリント"])], {"apps": apps, "new_warnings": new})
    c.exact("英文要旨は要旨の段落だけ", r.trans_abstract() == [ABS0], r.trans_abstract())


@case("R01", "AI: 英文要旨の段落に set_role app_heading → そこから資料が始まる")
def c_r01(ctx, c):
    r0 = conv(ctx, "R01", tag="_0")
    src = r0.src_of("Worksheet used in the fictional lesson")
    r = conv(ctx, "R01", ops=[op(src, "app_heading")])
    common(c, r)
    c.exact("set_role が採用される", r.res.ai.rejected == [], r.res.ai.rejected)
    apps = r.apps()
    c.exact("app/title が指定した段落", [a["title"] for a in apps] == ["Worksheet used in the fictional lesson"], apps)
    c.exact("続く段落が app の中", apps and "Question one asks" in apps[0]["text"], apps)
    c.exact("英文要旨は 1 段落目だけ", r.trans_abstract() == [ABS0], r.trans_abstract())


@case("R02", "AI: 英文題目に set_role app_heading → 不採用")
def c_r02(ctx, c):
    r0 = conv(ctx, "R01", tag="_0")
    src = r0.src_of("A Fictional Study")
    r = conv(ctx, "R01", ops=[op(src, "app_heading")], tag="_r02")
    common(c, r)
    c.exact("不採用（理由あり）", len(r.res.ai.rejected) == 1 and r.res.ai.rejected[0][1], r.res.ai.rejected)
    tt = r.root.findtext(".//article-meta//trans-title-group/trans-title")
    c.exact("英文題目はそのまま", tt == "A Fictional Study", tt)
    c.exact("app-group がない", r.apps() == [], r.apps())


@case("R03", "AI: Word の脚注の段落に set_role p・exclude → どちらも不採用（理由あり）")
def c_r03(ctx, c):
    r0 = conv(ctx, "N02", tag="_0")
    src = r0.src_of("脚注だけの原稿の架空の注。")
    r = conv(ctx, "N02", ops=[op(src, "p"), op(src, "exclude")], tag="_r03")
    common(c, r)
    rej = r.res.ai.rejected
    c.exact("2 件とも不採用（理由あり）", len(rej) == 2 and all(w for _, w in rej), rej)
    fn_marks(c, r, ["脚注だけの原稿の架空の注。"])


@case("R04", "AI: Word の文末脚注の段落に set_role exclude・p → どちらも不採用（理由あり）")
def c_r04(ctx, c):
    r0 = conv(ctx, "N01", tag="_0")
    src = r0.src_of("文末脚注の一段落目の架空の説明。")
    r = conv(ctx, "N01", ops=[op(src, "exclude"), op(src, "p")], tag="_r04")
    common(c, r)
    rej = r.res.ai.rejected
    c.exact("2 件とも不採用（理由あり）", len(rej) == 2 and all(w for _, w in rej), rej)
    fn_marks(c, r, ["文末脚注の一段落目の架空の説明。"])


@case("R05", "AI: 図形の中の段落（float_id。図のキャプション）に set_role p → 不採用")
def c_r05(ctx, c):
    r0 = conv(ctx, "R05", tag="_0")
    src = r0.src_of("図1　架空の図形")
    r = conv(ctx, "R05", ops=[op(src, "p")], tag="_r05")
    common(c, r)
    rej = r.res.ai.rejected
    c.exact("不採用（理由あり）", len(rej) == 1 and rej[0][1], rej)
    c.exact("図のキャプションはそのまま", r.root.find(".//fig/caption") is not None)


@case("R06", "AI: 誌名行（除外。領域なし）に set_role p → 採用するなら効果があり依頼文でも勧める／不採用なら依頼文で勧めない")
def c_r06(ctx, c):
    r0 = conv(ctx, "A15", manual=True, tag="_0")
    ex = [e for e in r0.excluded() if "誌名" in e[1]]
    src, line = ex[0][0], ex[0][2]
    hint = any("set_role" in ln for ln in prompt_lines(r0, src))
    r = conv(ctx, "A15", ops=[op(src, "p")], tag="_r06")
    common(c, r)
    rejected = bool(r.res.ai.rejected)
    c.either("set_role の採否と依頼文の案内が一致する（N6）", [
        ("不採用で、依頼文でも勧めない", rejected and not hint),
        ("採用され本文に出て、依頼文でも勧める", not rejected and line in r.xml_text() and hint)],
        {"rejected": r.res.ai.rejected, "hint": hint, "in_xml": line in r.xml_text()})


@case("R07", "AI: 見出しのスタイルで始めた資料の見出しに set_role abstract → 英文要旨に戻る")
def c_r07(ctx, c):
    r0 = conv(ctx, "A11", tag="_0")
    src = r0.src_of("授業で用いたワークシート")
    r = conv(ctx, "A11", ops=[op(src, "abstract")], tag="_r07")
    common(c, r)
    c.exact("set_role が採用される", r.res.ai.rejected == [], r.res.ai.rejected)
    c.exact("見出しが英文要旨に入る", "授業で用いたワークシート" in (r.trans_abstract() or []), r.trans_abstract())
    c.exact("見出しが app の題目にない", "授業で用いたワークシート" not in [a["title"] for a in r.apps()], r.apps())


@case("R08", "AI: 脚注の参照がある本文の段落に set_role exclude → 採用なら注はリンクなしで出力（除外された段落の中の参照も数える）")
def c_r08(ctx, c):
    r0 = conv(ctx, "R08", tag="_0")
    src = r0.src_of("除外を指定する段落の文。")
    r = conv(ctx, "R08", ops=[op(src, "exclude")])
    common(c, r)
    in_xml(c, r, "除外された段落から参照される架空の脚注。")
    fns = r.fns()
    accepted = not r.res.ai.rejected
    target = next((f["id"] for f in fns if "除外された段落から参照される" in f["text"]), None)
    c.either("set_role exclude の採否と注", [
        ("採用され、段落は除外、注は fn-group に出る（本文のリンクなし）",
         accepted and "除外を指定する段落の文" not in r.xml_text() and target is not None
         and all(x[0] != target for x in r.body_xrefs())),
        ("不採用で、注はふつうにリンクされる", not accepted and ("fn1", "1)", True) in r.body_xrefs())],
        {"rejected": r.res.ai.rejected, "fns": [f["text"][:30] for f in fns], "xrefs": r.body_xrefs()})
    c.exact("残る参照の注も出る", any("残る参照の架空の脚注。" in f["text"] for f in fns), [f["text"][:30] for f in fns])
    c.info("その注についての Decision", [(d.category, d.src, d.message[:80]) for d in r.res.plan.decisions
                                       if d.category == "note"])


# ----------------------------------------------------------------------------- 実行
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/home/user/jstgxmlcng_JASME/src")
    ap.add_argument("--label", default="run")
    ap.add_argument("--only", default="")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        (HERE / "cases_e.json").write_text(json.dumps({n: d for n, (d, _) in CASES.items()}, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
        print(f"{len(CASES)} 件")
        return
    setup(a.src)
    import jasme_jats
    ctx = {"out": HERE / f"out_{a.label}"}
    ctx["out"].mkdir(exist_ok=True)
    names = [n for n in CASES if not a.only or n in a.only.split(",")]
    results = {}
    nok = 0
    for n in names:
        desc, f = CASES[n]
        c = Checks()
        try:
            f(ctx, c)
            err = ""
        except Exception as e:  # 変換の失敗もケースの FAIL にする
            import traceback
            err = "".join(traceback.format_exception_only(type(e), e)).strip()
            c.items.append(("exact", "変換と確かめが例外なく終わる", False, err + traceback.format_exc()[-600:]))
        ok = all(i[2] for i in c.items)
        nok += ok
        results[n] = {"desc": desc, "ok": ok, "checks": [dict(zip(("kind", "what", "ok", "actual"), i)) for i in c.items]}
        print(f"{'OK  ' if ok else 'FAIL'} {n}: {desc}")
        for kind, what, good, actual in c.items:
            if not good:
                print(f"     x [{kind}] {what} … 実際: {actual}")
            elif kind in ("either", "info"):
                print(f"     - [{kind}] {what} … {actual}")
    print(f"\n{jasme_jats.__version__} ({Path(jasme_jats.__file__).resolve().parent}): OK {nok} / {len(names)}")
    (HERE / f"results_{a.label}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
