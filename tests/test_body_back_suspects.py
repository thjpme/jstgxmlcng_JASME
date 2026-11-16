"""本文・後付けの構造の検出と直し（修正計画の単位 D。C037・C014・C032・C026 と、引用文献の一覧がない原稿の守り）。

機械が挙げたスタイルを確かめる段落（plan.style_suspects。要確認 style_check）と、後付けの見出しの比べ方（back_heading_key）・
標準スタイルの番号の段落の推定（規則 3）を、架空の小さな原稿で確かめる。実際の API は呼ばない。
"""
from lxml import etree

import make_fixtures as mf
from jasme_jats import report
from jasme_jats.article import STYLE_SUSPECT_KINDS
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import TO_CHECK, actions
from jasme_jats.structure import back_heading_inline, back_heading_key, heading_body_detail

S = mf.S
para, run, br = mf.para, mf.run, mf.br
REF1 = "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．"


def _article(path, body_parts, back):
    """make_article と同じ冒頭・英文の部分で、本文（body_parts(b)）と後付け（back(b)）を与える小さな論文。"""
    b = mf.Builder()
    b.bullet = None
    body = mf.front_ja(b, "架空の題目の検証用文書", "―検証用の小さな論文―", [("架空大学", "試験　六郎")])
    body += body_parts(b) + back(b)
    body += mf.front_en(b, "A Small Article", "For Checking", [("Rokuro SHIKEN", "Fictional University")], ["Small article abstract."])
    body += mf.tail(b)
    b.save(path, body)
    return path


def _refs(extra=()):
    return lambda b: [para(S["ref_head"], "引用および参考文献"), para(S["ref"], REF1)] + list(extra)


def _intro(b):
    return [para(S["sec1"], "１．はじめに"), para(S["body"], "試験（2024）による。架空の本文である。")]


def _convert(tmp_path, name, body_parts, back, meta, journal):
    path = _article(tmp_path / f"{name}.docx", body_parts, back)
    return convert(path, meta, journal, Options(out_dir=tmp_path / name))


def _src(res, text):
    return next(s for s, p in res.plan.paras.items() if p.plain() == text)


def _kinds(res, kind=None):
    return [(s.kind, s.src) for s in res.plan.style_suspects if kind is None or s.kind == kind]


def _act(res, key):
    return next((a for a in actions(res) if a.key == key), None)


def _xml(res):
    return etree.parse(str(res.xml_path))


def _t(e):
    return "".join(e.itertext())


# ----------------------------------------------------------------------------- D1 入れ物
def test_style_suspect_kinds_and_texts_agree():
    """種類ごとの決まった文（STYLE_SUSPECT_JA）と種類（STYLE_SUSPECT_KINDS）は同じ。AI を待たない種類も種類のうち。"""
    assert set(report.STYLE_SUSPECT_JA) == set(STYLE_SUSPECT_KINDS)
    assert set(report.STYLE_NO_AI_KINDS) <= set(STYLE_SUSPECT_KINDS)
    assert {"ref_symbol", "back_heading", "ref_cont"} == set(report.STYLE_NO_AI_KINDS)
    assert all(what and how for what, how in report.STYLE_SUSPECT_JA.values())


# ----------------------------------------------------------------------------- D2 C037 見出しと本文が 1 段落
def test_heading_body_detail_rules():
    assert heading_body_detail("１．はじめに\n　近年，架空の研究が進んでいる。試験は甲を示した。本稿はその続きである。", "章").startswith(
        "見出しの段落の中の改行（Shift+Enter）の後ろに、本文らしい文（")
    assert heading_body_detail("１．はじめに\n―架空の背景―", "章") == ""
    assert heading_body_detail("１．はじめに\n短い文。", "章") != ""                 # 「。」があれば短くても
    long = "１．はじめに　" + "架空の研究の背景を述べる文である。" * 4
    assert "全体が章の見出し" in heading_body_detail(long, "章")
    assert heading_body_detail("１．架空の研究の背景と目的についての長い見出しの文字", "章") == ""


def test_heading_body_suspect_in_style_check(meta, journal, tmp_path):
    """章見出しの段落に Shift+Enter で本文が続く形: heading_body が 1 つ、style_check に「Enter を押して段落を分け」、10 章の
    「改行を消して」には挙げない。XML は今のまま（見出しと本文が 1 つの title）。要対応はない。"""
    body = "　近年，架空の研究が進んでいる。試験（2024）は甲を示した。本稿はその続きである。"
    res = _convert(tmp_path, "c037", lambda b: [para(S["sec1"], "１．はじめに", br(), body),
                                                 para(S["sec1"], "２．方法"), para(S["body"], "方法の本文。")],
                   _refs(), meta, journal)
    src = _src(res, "１．はじめに\n" + body)
    assert _kinds(res) == [("heading_body", src)]
    act = _act(res, "style_check")
    assert act.level == TO_CHECK and src in act.box_detail and "Enter を押して段落を分け" in act.box_detail
    assert not any(src in w and "改行が要らなければ" in w for w in res.warnings)
    assert res.fidelity.ok and not res.needs_action
    assert body in _t(_xml(res).find(".//body/sec/title"))
    assert _act(res, "ai_finish") is not None          # AI を待つ種類（推奨の手順）
    # 場所の列は改行の前までの見出しの文字（本文の書き出しを 2 回並べない）。一覧の行・コマンドラインに段落の分けも含むと書く
    assert f"{src}（１．はじめに…（見出し））" in act.box_detail and "近年" not in act.box_detail.split(src)[1].split("「")[0]
    assert "（段落のつなぎ・分けを含む）" in act.checklist and "（段落のつなぎ・分けを含む）" in act.cli


def test_short_second_line_of_heading_is_not_heading_body(meta, journal, tmp_path):
    res = _convert(tmp_path, "c037s", lambda b: [para(S["sec1"], "１．はじめに", br(), "―架空の背景―"),
                                                  para(S["body"], "試験（2024）による。")], _refs(), meta, journal)
    assert _kinds(res, "heading_body") == []
    src = _src(res, "１．はじめに\n―架空の背景―")
    assert any(src in w and "改行が要らなければ" in w for w in res.warnings)


# ----------------------------------------------------------------------------- D3 C014 推定した見出しの知らせ
def test_heading_guess_without_styles(meta, journal, tmp_path):
    """見出しのスタイルのない原稿で、標準スタイルの「1. はじめに」「2. 方法」は章と推定し、heading_guess で知らせる。"""
    res = _convert(tmp_path, "c014n", lambda b: [para(S["normal"], "1. はじめに"), para(S["body"], "試験（2024）による。"),
                                                  para(S["normal"], "2. 方法"), para(S["body"], "方法の本文。")],
                   _refs(), meta, journal)
    s1, s2 = _src(res, "1. はじめに"), _src(res, "2. 方法")
    assert _kinds(res, "heading_guess") == [("heading_guess", s1), ("heading_guess", s2)]
    assert [_t(x) for x in _xml(res).findall(".//body/sec/title")] == ["1. はじめに", "2. 方法"]
    det = next(x.detail for x in res.plan.style_suspects if x.src == s1)
    assert "番号の形から章見出しにしました" in det
    assert "本文の番号つきの箇条なら「本文」のスタイル" in _act(res, "style_check").box_detail
    assert not res.needs_action


def test_heading_guess_bold_body_paragraph(meta, journal, tmp_path):
    """本文スタイルの太字の「１．…」（章見出しのスタイルのない原稿）は章のまま、heading_guess で知らせる。"""
    res = _convert(tmp_path, "c014b", lambda b: [para(S["body"], run("１．はじめに", b=True)), para(S["body"], "試験（2024）による。"),
                                                  para(S["body"], run("２．方法", b=True)), para(S["body"], "方法の本文。")],
                   _refs(), meta, journal)
    assert len(_kinds(res, "heading_guess")) == 2
    assert [_t(x) for x in _xml(res).findall(".//body/sec/title")] == ["１．はじめに", "２．方法"]
    assert "全体が太字で番号の形から章見出しにしました" in res.plan.style_suspects[0].detail


# ----------------------------------------------------------------------------- D6 C032 付記の見出しと本文が 1 段落
def test_back_heading_inline_rules():
    assert back_heading_inline("付記　本研究は架空の研究会での発表を基にした。") == "付記"
    assert back_heading_inline("【謝　辞】　本研究に協力いただいた架空の方々に感謝する。") == "謝辞"
    assert back_heading_inline("謝辞：架空の協力者の皆様に深く感謝いたします。") == "謝辞"
    assert back_heading_inline("付記したように，架空の結果が得られた。") == ""
    assert back_heading_inline("注：数値は架空の調査の平均である。") == ""
    assert back_heading_inline("付記　短い。") == ""                       # 後ろが 10 字に満たない
    assert back_heading_inline("【謝辞　架空の協力者の皆様に深く感謝いたします。") == ""      # 括弧が組にならない


def test_notes_heading_and_body_in_one_paragraph(meta, journal, tmp_path):
    """本文スタイルの「付記　本研究は…」は back_heading で知らせる（AI を待たない種類）。XML は今のまま本文の段落。"""
    text = "付記　本研究は架空の研究会での発表を基にした。"
    res = _convert(tmp_path, "c032n", lambda b: _intro(b) + [para(S["body"], text)], _refs(), meta, journal)
    src = _src(res, text)
    assert _kinds(res) == [("back_heading", src)]
    act = _act(res, "style_check")
    assert "付記の見出しと本文が 1 つの段落です" in act.box_detail and "「付記見出し」「謝辞見出し」のスタイル" in act.box_detail
    assert _act(res, "ai_finish") is None
    assert text in [_t(p) for p in _xml(res).findall(".//body/sec/p")]
    assert not res.needs_action


def test_body_sentences_are_not_back_heading(meta, journal, tmp_path):
    res = _convert(tmp_path, "c032x", lambda b: _intro(b) + [para(S["body"], "付記したように，架空の結果が得られた。"),
                                                              para(S["body"], "注：数値は架空の調査の平均である。")],
                   _refs(), meta, journal)
    assert _kinds(res) == []


def test_back_heading_key():
    assert back_heading_key("５．引用文献") == "引用文献"
    assert back_heading_key("【謝　辞】") == "謝辞"
    assert back_heading_key("Ⅴ　参考文献") == "参考文献"
    assert back_heading_key("（付記）") == "付記"
    assert back_heading_key("引用文献の検討") == "引用文献の検討"


# ----------------------------------------------------------------------------- D4 C026 引用文献の続きの段落
def _ref_paras(texts):
    return [para(S["ref"], t) for t in texts]


def _refs_of(res):
    return [_t(r) for r in _xml(res).iter("ref")]


def test_ref_continuations_listed(meta, journal, tmp_path):
    """URL の行・「著者（年）．」の次の行・DOI の行で分かれた文献: ref_cont が 3 つ。<ref> の数と文字は今のまま（つながない）。
    AI を待たない種類（ai_finish は出ない）。3 章の「どこからもリンクされていない文献」に「（前の文献の続きの疑い）」を添える。"""
    extra = ["甲野一郎（2020）．「架空の調査」．", "https://example.org/report/2020.pdf（2024年1月1日閲覧）",
             "乙川二郎（2019）．", "『架空の本』．架空書房．",
             "Hei, A. (2018). A fictional paper. Fictional Journal, 3(2), 1-9.", "DOI: 10.0000/fict.2018.3"]
    res = _convert(tmp_path, "c026", _intro, _refs(_ref_paras(extra)), meta, journal)
    srcs = [_src(res, t) for t in (extra[1], extra[3], extra[5])]
    assert _kinds(res) == [("ref_cont", s) for s in srcs]
    assert len(_refs_of(res)) == 7 and res.fidelity.ok and not res.needs_action
    det = {x.src: x.detail for x in res.plan.style_suspects}
    assert "の続きの疑いがあります（URL・DOI で始まります）。今は別の文献" in det[srcs[0]]
    assert "（年が読めません）" in det[srcs[1]] and "「乙川二郎（2019）．」" in det[srcs[1]]
    assert _act(res, "ai_finish") is None
    act = _act(res, "style_check")
    assert "前の段落の終わりの段落記号を消して 1 つの段落にする" in act.box_detail
    ch3 = report.render(res).split("## 3.")[1].split("## 4.")[0]
    assert "架空書房．）（前の文献の続きの疑い）" in ch3 and "(2018). A fictional pa）、" in ch3       # 年のある文献には添えない


def test_ref_continuations_none_for_whole_entries(meta, journal, tmp_path):
    """分けずに書いた文献・年のない正規の書き方（n.d.・印刷中）には出さない。"""
    extra = ["甲野一郎（2020）．「架空の調査」．https://example.org/report/2020.pdf（2024年1月1日閲覧）",
             "乙川二郎（2019）．『架空の本』．架空書房．", "文部科学省（n.d.）．「架空の資料」．", "丙山三郎（印刷中）．「架空の論文」．"]
    res = _convert(tmp_path, "c026ok", _intro, _refs(_ref_paras(extra)), meta, journal)
    assert _kinds(res) == [] and res.plan.ref_yearless_runs == []


def test_ref_yearless_run_is_appendix_not_continuation(meta, journal, tmp_path):
    """引用文献スタイルの年のない段落が 3 件以上続く所から後ろは、続きとして挙げず（URL で始まるものは挙げる）、資料の中身の疑いとして
    要確認 app_after_refs に 1 行出す。XML は今のまま。"""
    extra = ["甲野一郎（2020）．「架空の調査」．", "架空の資料の見出しの行", "架空の資料の一つ目の文である。", "架空の資料の二つ目の文である。",
             "架空の資料の三つ目の文である。", "https://example.org/appendix"]
    res = _convert(tmp_path, "c026run", _intro, _refs(_ref_paras(extra)), meta, journal)
    head = _src(res, extra[1])
    assert _kinds(res) == [("ref_cont", _src(res, extra[5]))]
    assert res.plan.ref_yearless_runs == [head]
    act = _act(res, "app_after_refs")
    assert act.level == TO_CHECK and head in act.box_detail and "年の読めない段落が 3 件以上続く所があります" in act.box_detail
    assert "資料の中身と思われる段落があります" in act.top
    # することの一覧の見出しも「資料の中身」（資料の見出しは見つけていない。点検 review19 の 3 回目の利用者向け 4）
    assert "**引用文献などの後ろの資料の中身**（1 件。10 章）" in act.checklist and "資料の見出し**" not in act.checklist
    assert any(head in w and "3 件以上続く所" in w for w in res.warnings)
    assert len(_refs_of(res)) == 7


def test_ref_continuation_run_does_not_count_urls(meta, journal, tmp_path):
    """URL・DOI で始まる段落は「続く数」に数えない: 文献 1 件が 3 段落に割れ（年のない段落 2 つ）、後ろに URL の段落が続いても打ち切らず、
    その後ろの本当の続きの段落も挙げる。"""
    regular = [f"架空{k}郎（20{10 + k}）．「架空の論文{k}」．『架空誌』，第{k}巻．" for k in range(1, 7)]
    extra = ["乙川二郎（2019）．", "『架空の本』．", "架空書房．", "https://example.org/book"] + regular + ["pp.1-9．"]
    res = _convert(tmp_path, "c026url", _intro, _refs(_ref_paras(extra)), meta, journal)
    assert [s for _, s in _kinds(res, "ref_cont")] == [_src(res, t) for t in ("『架空の本』．", "架空書房．", "https://example.org/book", "pp.1-9．")]
    assert res.plan.ref_yearless_runs == []


def test_ref_continuations_many_are_one_line(meta, journal, tmp_path):
    """年の読めない文献（URL を除く）が 3 割を超えて 3 件以上あるとき（年を括弧で書かない書き方など）は、1 件ずつ挙げずに 1 行にまとめる。"""
    extra = []
    for k in range(1, 5):
        extra += [f"Hei, A{k}., 201{k}. A fictional paper {k}. Fictional Journal.", f"架空{k}郎（200{k}）．「架空の論文」．"]
    res = _convert(tmp_path, "c026many", _intro, _refs(_ref_paras(extra)), meta, journal)
    conts = [x for x in res.plan.style_suspects if x.kind == "ref_cont"]
    assert len(conts) == 1 and "年の読めない文献が 4 件あります" in conts[0].detail
    assert len(res.plan.ref_conts) == 4


# ----------------------------------------------------------------------------- D5 引用文献の一覧がない原稿の守り
def test_refs_missing_is_needs_action(meta, journal, tmp_path):
    """引用文献の見出しを後付けの見出しと見分けられず、引用文献の一覧が 1 件もないのに本文に「著者（年）」の引用があれば要対応 refs_missing。
    見出しから後ろの文献の行の年は数えない。"""
    res = _convert(tmp_path, "refsmissing", lambda b: _intro(b) + [para(S["body"], "甲野（2020）と乙川（2019）も見る。（2021）")],
                   lambda b: [para(S["sec1"], "Ⅴ　文献一覧"), para(S["ref"], REF1), para(S["ref"], "甲野一郎（2020）．「架空の調査」．")],
                   meta, journal)
    assert res.plan.refs == [] and res.plan.refs_missing_cites == 3
    act = _act(res, "refs_missing")
    assert act.level == report.NEEDS_ACTION and "少なくとも 3 か所" in act.box_detail and "「参考文献見出し」のスタイル" in act.box_detail
    assert "`<ref-list>`" in act.top and res.needs_action
    assert "（少なくとも 3 か所）をリンクしていません" in report.render(res).split("## 3.")[1].split("## 4.")[0]


def test_refs_missing_not_without_citations(meta, journal, tmp_path):
    res = _convert(tmp_path, "norefs", lambda b: [para(S["sec1"], "１．はじめに"), para(S["body"], "引用のない架空の本文である。")],
                   lambda b: [], meta, journal)
    assert res.plan.refs == [] and _act(res, "refs_missing") is None


# ----------------------------------------------------------------------------- D7 C032 後付けの見出しの比べ方
def _back(res):
    back = _xml(res).find(".//back")
    return [(c.tag, _t(c.find("title")) if c.find("title") is not None else "") for c in back]


def test_ack_heading_in_brackets_becomes_ack(meta, journal, tmp_path):
    """本文スタイルの太字「【謝　辞】」（括弧と字間の全角空白）と謝辞の本文は <ack> になる。見出しの文字はそのまま（太字も）。"""
    res = _convert(tmp_path, "c032a", lambda b: _intro(b) + [para(S["body"], run("【謝　辞】", b=True)),
                                                              para(S["body"], "架空の協力者に感謝する。")], _refs(), meta, journal)
    root = _xml(res)
    ack = root.find(".//back/ack")
    assert ack is not None and _t(ack.find("title")) == "【謝　辞】" and ack.find("title/bold") is not None
    assert [_t(p) for p in ack.findall("p")] == ["架空の協力者に感謝する。"]
    assert "【謝　辞】" not in _t(root.find(".//body"))
    assert res.fidelity.ok and not res.needs_action and _kinds(res) == []
    src = _src(res, "【謝　辞】")
    assert res.plan.loose_back == {src: "ack_heading"}


def test_numbered_ref_heading_becomes_ref_list(meta, journal, tmp_path):
    """章見出しスタイルの「５．引用文献」「【引用文献】」は <ref-list> の見出しになり、本文の引用がリンクされる。"""
    for name, head in (("c032r", "５．引用文献"), ("c032b", "【引用文献】")):
        res = _convert(tmp_path, name, _intro, lambda b: [para(S["sec1"], head), para(S["ref"], REF1)], meta, journal)
        root = _xml(res)
        rl = root.find(".//back/ref-list")
        assert rl is not None and _t(rl.find("title")) == head and len(rl.findall("ref")) == 1
        assert any(x.get("ref-type") == "bibr" for x in root.iter("xref"))
        assert [_t(t) for t in root.findall(".//body/sec/title")] == ["１．はじめに"]
        assert res.fidelity.ok and _act(res, "refs_missing") is None


def test_loose_heading_in_body_is_not_back(meta, journal, tmp_path):
    """本文の途中（後ろに章見出しのスタイルの段落が続く）の本文スタイルの「【文献】」は後付けにしない（g1）。back_heading で知らせる。"""
    res = _convert(tmp_path, "c032g1", lambda b: _intro(b) + [para(S["body"], "【文献】"), para(S["body"], "架空の文献の紹介の本文である。"),
                                                               para(S["sec1"], "２．方法"), para(S["body"], "方法の本文。")],
                   _refs(), meta, journal)
    src = _src(res, "【文献】")
    assert [_t(t) for t in _xml(res).findall(".//body/sec/title")] == ["１．はじめに", "２．方法"]
    sus = [x for x in res.plan.style_suspects if x.kind == "back_heading"]
    assert [x.src for x in sus] == [src] and "引用文献の見出しの形ですが、後ろに章見出しのスタイルの段落" in sus[0].detail
    assert res.plan.loose_back == {} and len(_xml(res).findall(".//ref")) == 1


def test_loose_heading_before_styled_same_heading(meta, journal, tmp_path):
    """後ろに「謝辞見出し」スタイルの段落がある本文の「【謝辞】」は後付けにしない（g2。K1 の中止に入らない）。"""
    res = _convert(tmp_path, "c032g2", lambda b: _intro(b) + [para(S["body"], "【謝辞】"), para(S["body"], "架空の本文である。"),
                                                               para(S["ack_head"], "謝辞"), para(S["body"], "架空の協力者に感謝する。")],
                   _refs(), meta, journal)
    src = _src(res, "【謝辞】")
    assert [x.src for x in res.plan.style_suspects if x.kind == "back_heading"] == [src]
    assert "後ろに同じ謝辞の見出し" in res.plan.style_suspects[0].detail
    assert _t(_xml(res).find(".//back/ack/title")) == "謝辞" and res.fidelity.ok


def test_two_loose_headings_of_same_kind_are_not_back(meta, journal, tmp_path):
    """同じ種類の緩い候補が 2 つあれば、どれも後付けにしない（g2。K1 の中止に入らない）。前に同じ種類の見出しがある候補も同じ。"""
    REF2 = "架空太郎（2023）．「別の論文」．『架空誌』，第4巻，pp.1-2．"
    cases = {
        "c032refs": (lambda b: [para(S["sec1"], "５．引用文献"), para(S["ref"], REF1), para(S["body"], "【参考文献】"), para(S["ref"], REF2)],
                     ["５．引用文献", "【参考文献】"], "ほかにも引用文献の見出しの形の段落"),
        "c032acks": (lambda b: [para(S["sec1"], "５．謝辞"), para(S["body"], "架空の機関に感謝する。"), para(S["body"], "【謝　辞】"),
                                para(S["body"], "もう一度感謝する。"), para(S["ref_head"], "引用文献"), para(S["ref"], REF1)],
                     ["５．謝辞", "【謝　辞】"], "ほかにも謝辞の見出しの形の段落"),
        "c032before": (lambda b: [para(S["ack_head"], "謝辞"), para(S["body"], "架空の機関に感謝する。"), para(S["body"], "【謝　辞】"),
                                  para(S["body"], "もう一度感謝する。"), para(S["ref_head"], "引用文献"), para(S["ref"], REF1)],
                       ["【謝　辞】"], "前に同じ謝辞の見出し"),
    }
    for name, (back, heads, why) in cases.items():
        res = _convert(tmp_path, name, _intro, back, meta, journal)       # 中止しない（StructureConflictError にならない）
        sus = [x for x in res.plan.style_suspects if x.kind == "back_heading"]
        assert [x.src for x in sus] == [_src(res, t) for t in heads], name
        assert all(why in x.detail for x in sus), name
        assert res.plan.loose_back == {} and res.fidelity.ok, name
        # 直し方は見出しの種類で出し分け、同じ種類の候補が 2 つなら、どちらか一方だけを見出しのスタイルにすると添える
        rows = dict(report.style_check_rows(res)[0])
        style = "参考文献見出し" if "refs" in name else "謝辞見出し"
        kind_ja = "引用文献" if "refs" in name else "謝辞"
        for x in sus:
            assert f"直し方: {kind_ja}の見出しなら、見出しの段落を「{style}」のスタイルにする" in rows[x.src], name
            assert ("どちらか一方だけを見出しのスタイルにする" in rows[x.src]) == (len(sus) == 2), name
            assert "付記・謝辞なら" not in rows[x.src], name


def test_ai_proposal_on_loose_back_heading_says_xml_is_right(meta, journal, tmp_path):
    """機械が文字から後付けの見出しにした段落に、AI が「謝辞見出しにする」と提案していれば、行に XML ではもうそのように出していると添える。"""
    from jasme_jats.ai_assist import StyleFix
    res = _convert(tmp_path, "c032ai", lambda b: _intro(b) + [para(S["body"], run("【謝　辞】", b=True)),
                                                               para(S["body"], "架空の協力者に感謝する。")], _refs(), meta, journal)
    src = _src(res, "【謝　辞】")
    res.ai.style_fixes = [StyleFix(src, "ack_heading", "謝辞見出し", "Word で段落のスタイルを「謝辞見出し」にする", "謝辞の見出し", "高")]
    act = _act(res, "style_check")
    assert "機械が文字から謝辞の見出しと推定し、XML ではそのように出力しています" in act.box_detail


# ----------------------------------------------------------------------------- D8 C014 の規則 3
def _numbered_list(b):
    return [para(S["sec1"], "１．はじめに"), para(S["body"], "試験（2024）による。"),
            para(S["sec1"], "２．定義"), para(S["body"], "次の三つを考える。"),
            para(S["normal"], "1. 甲に関する知識"), para(S["normal"], "2. 乙に関する知識"),
            para(S["normal"], "3. 丙に関する知識"), para(S["body"], "以上の三つである。"),
            para(S["sec1"], "３．考察"), para(S["body"], "考察の本文。")]


def test_normal_numbered_paragraphs_stay_body_when_heading_style_exists(meta, journal, tmp_path):
    """章見出しのスタイルの章がある原稿の、標準スタイルの「1. …」が続く段落は偽の章にせず、2 章の <sec> の中の <p> にする。
    heading_guess で「本文の段落にしました」と知らせる。"""
    res = _convert(tmp_path, "c014", _numbered_list, _refs(), meta, journal)
    root = _xml(res)
    assert [_t(t) for t in root.findall(".//body/sec/title")] == ["１．はじめに", "２．定義", "３．考察"]
    sec2 = root.findall(".//body/sec")[1]
    assert [_t(p) for p in sec2.findall("p")] == ["次の三つを考える。", "1. 甲に関する知識", "2. 乙に関する知識", "3. 丙に関する知識",
                                                  "以上の三つである。"]
    sus = [x for x in res.plan.style_suspects if x.kind == "heading_guess"]
    assert len(sus) == 3 and all("本文の段落にしました" in x.detail and "章見出しのスタイルを付けて" in x.detail for x in sus)
    assert res.fidelity.ok and not res.needs_action


def test_forgotten_heading_style_becomes_body(meta, journal, tmp_path):
    """章見出しのスタイルを 1 つの章だけ付け忘れた原稿（標準スタイルの「3. 考察」。太字でない）は、規則 3 で本文の段落になる
    （今まで章になっていた形。heading_guess で、章見出しならスタイルを付けるよう知らせる）。太字なら章のまま。"""
    def body(bold):
        return lambda b: [para(S["sec1"], "１．はじめに"), para(S["body"], "試験（2024）による。"),
                          para(S["normal"], run("3. 考察", b=bold)), para(S["body"], "考察の本文。")]
    res = _convert(tmp_path, "c014f", body(False), _refs(), meta, journal)
    assert [_t(t) for t in _xml(res).findall(".//body/sec/title")] == ["１．はじめに"]
    assert [x.kind for x in res.plan.style_suspects] == ["heading_guess"]
    res = _convert(tmp_path, "c014fb", body(True), _refs(), meta, journal)
    assert [_t(t) for t in _xml(res).findall(".//body/sec/title")] == ["１．はじめに", "3. 考察"]
    assert "番号の形から章見出しにしました" in res.plan.style_suspects[0].detail


def test_autonum_list_stays_list_with_rule3(meta, journal, tmp_path):
    """Word の自動番号の箇条書きは、規則 3 の後も <list> のまま。"""
    res = _convert(tmp_path, "c014l", lambda b: _intro(b) + [mf.list_item(S["body"], "甲の項目", num_id=7),
                                                              mf.list_item(S["body"], "乙の項目", num_id=7)], _refs(), meta, journal)
    assert _xml(res).find(".//body//list") is not None and _kinds(res, "heading_guess") == []
