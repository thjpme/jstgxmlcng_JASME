"""外部レビュー 2 回目（docs/REVIEW_CODEX_2026-11.md）の S3: 和文の所属の段落を共有する著者の扱い（R4 の続き）。

和文の著者表で所属のセルが空の行は、前の行の所属の段落を使う（structure.Classifier.read_author_table_ja）。0.38.0 の R4 の修正（split_aff）は、
段落が同じかを見ずに所属を分けたので、同じ段落を 2 回出す（a）・出力と除外の両方に入れる（b）ことがあった。最初から同じ段落を共有する
著者に違う英文の所属が来たときは、知らせなしに 2 つの所属を指していた（c）。

所有者の決定（2026-11-20）: 段落 1 つを複数の著者が共有しているときは分けない（同じ段落を 2 回出せない）。英文の所属が違うときは、
0.37.0 と同じ形（共有の所属と英文だけの所属の両方を指す）のままにし、要確認 front_check（aff_shared）で知らせる。和文の段落が著者ごとに
別にある場合は、1 回目の決定どおり分ける。docx は make_fixtures.make_conflict で作る（内容は架空）。
"""
import make_fixtures as mf
from lxml import etree

from jasme_jats import frontcheck
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import TO_CHECK, actions, front_reported_srcs

EDU = "Fictional University, Faculty of Education"
SCI = "Fictional University, Faculty of Science"
ARTS = "Fictional University, Faculty of Arts"
INST = "Fictional Institute"
NAMES_JA = ("試験　六郎", "検証　七郎", "確認　八郎", "点検　九郎")
NAMES_EN = ("Rokuro SHIKEN", "Nanao KENSHO", "Hachiro KAKUNIN", "Kuro TENKEN")


def run(tmp_path, journal, meta, ja_affs, en_affs, name="s3"):
    """和文の所属 ja_affs（著者ごと。"" は空のセルで、前の行の所属の段落を使う。改行で兼任）・英文の所属 en_affs（著者ごと。
    None なら英文の所属の行を置かない。改行で兼任）の論文を変換し、確かめ（不変性・最終・DTD・J-STAGE のチェック）が合格することを
    確かめて返す。"""
    ja_rows = [(aff, NAMES_JA[k]) for k, aff in enumerate(ja_affs)]
    en_rows = []
    for k, aff in enumerate(en_affs):
        en_rows.append(("name", NAMES_EN[k]))
        for line in (aff.split("\n") if aff is not None else []):
            en_rows.append(("aff", line))
    path = mf.make_conflict(tmp_path / f"{name}.docx", ja_rows=ja_rows, en_rows=en_rows)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / f"out_{name}", ai_mode="none"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, (res.fidelity.missing, res.fidelity.duplicates)
    assert res.jstage_issues == []
    assert not any(a.key == "fidelity" for a in actions(res))
    # 出力した段落（所属の和文・英文）を除外にも記録しない
    out = {p.src for x in res.plan.affs for p in (x.ja, x.en) if p is not None}
    assert not out & {x.src for x in res.plan.exclusions if not x.blank}
    return res


def xml_affs(res):
    """XML の著者ごとの所属の参照 [[rid…]…] と、所属 {id: {lang: 文字}}。"""
    root = etree.fromstring(res.xml_base)
    refs = [[x.get("rid") for x in c.iter("xref") if x.get("ref-type") == "aff"] for c in root.iter("contrib")]
    lang = "{http://www.w3.org/XML/1998/namespace}lang"
    affs = {}
    for alt in root.iter("aff-alternatives"):
        affs[alt.get("id")] = {a.get(lang): "".join(a.itertext()).strip() for a in alt.iter("aff")}
    for a in root.iter("aff"):
        if a.get("id"):
            affs[a.get("id")] = {a.get(lang): "".join(a.itertext()).strip()}
    return refs, affs


def shared(res):
    return [f for f in frontcheck.plan_findings(res.plan, "ja") if f.kind == frontcheck.AFF_SHARED]


def front_action(res):
    return next((a for a in actions(res) if a.key == "front_check"), None)


def ja_paras(res, text="架空大学"):
    return [p for p in res.plan.paras.values() if p.plain() == text]


# ---------------------------------------------------------------------------- 再現（a）（b）（c）
def test_a_shared_paragraph_different_en(tmp_path, journal, meta):
    """(a) 和文 架空大学/A・架空大学/B・空欄/C（C は B の段落を共有）、英文 Education・Science・Arts: B は自分の段落で分け
    （aff2 = 和文 B の段落・英文 Science）、C は共有の所属 aff2 と英文だけの所属 aff3（Arts）を指し、要確認で知らせる。
    0.38.0 は B の段落を 2 回出して fidelity 不合格だった。"""
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学", ""), (EDU, SCI, ARTS))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff2"], ["aff2", "aff3"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"ja": "架空大学", "en": SCI}, "aff3": {"en": ARTS}}
    d6, d8 = ja_paras(res)
    assert res.plan.affs[0].ja is d6 and res.plan.affs[1].ja is d8
    assert not [x for x in res.plan.exclusions if x.src == d8.src]
    f = shared(res)
    assert len(f) == 1 and f[0].level == frontcheck.CHECK and f[0].note == "3"
    c = res.plan.authors[2]
    assert set(f[0].srcs) == {c.name_ja.src, d8.src, res.plan.affs[2].en.src}
    a = front_action(res)
    assert a is not None and a.level == TO_CHECK and not res.needs_action
    assert "著者 3 の和文の所属の段落" in a.top and "Word で所属の段落を著者ごとに書いて" in a.top
    # 知らせた段落は、要確認 style_check などに重ねて挙げない
    assert set(f[0].srcs) <= front_reported_srcs(res)


def test_b_shared_paragraph_same_en(tmp_path, journal, meta):
    """(b) (a) の C も Science: C は B の aff2 を指すだけ。B の段落は除外しない（出力と除外の二重にしない）。C の英文の所属は
    重複で除外する。矛盾がないので知らせない。"""
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学", ""), (EDU, SCI, SCI))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff2"], ["aff2"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"ja": "架空大学", "en": SCI}}
    d6, d8 = ja_paras(res)
    assert not [x for x in res.plan.exclusions if x.src == d8.src]
    sci = [p for p in res.plan.paras.values() if p.plain() == SCI]
    dup = {x.src: x.reason for x in res.plan.exclusions if x.reason.startswith("重複する所属")}
    assert list(dup) == [sci[1].src] and sci[0].src in dup[sci[1].src]
    assert shared(res) == [] and front_action(res) is None


def test_c_shared_from_start_different_en(tmp_path, journal, meta):
    """(c) A・B が最初から同じ和文の段落を共有、英文 Education・Science: B は aff1 と英文だけの aff2 を指し（今のまま）、要確認で知らせる。"""
    res = run(tmp_path, journal, meta, ("架空大学", ""), (EDU, SCI))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff1", "aff2"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"en": SCI}}
    f = shared(res)
    assert len(f) == 1 and f[0].note == "2"
    assert res.plan.affs[0].ja.src in f[0].srcs and res.plan.authors[1].name_ja.src in f[0].srcs
    a = front_action(res)
    assert a is not None and a.level == TO_CHECK and "著者 2 の和文の所属の段落" in a.cli


def test_c_shared_from_start_same_en(tmp_path, journal, meta):
    """(c) で英文も同じ: 今までどおり 1 つの所属を共有し、2 人目の英文は重複で除外する。知らせない。"""
    res = run(tmp_path, journal, meta, ("架空大学", ""), (EDU, EDU))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff1"]] and affs == {"aff1": {"ja": "架空大学", "en": EDU}}
    assert shared(res) == [] and front_action(res) is None


# ---------------------------------------------------------------------------- 場合分け
def test_shared_paragraph_three_sharers(tmp_path, journal, meta):
    """3 人が 1 つの段落を共有（A と B・C が空欄）、英文 Education・Science・Science: B・C とも共有の所属と英文だけの所属を指す。
    2 人目の Science は英文だけの所属にまとめる。B・C とも知らせる（1 項目ずつ）。"""
    res = run(tmp_path, journal, meta, ("架空大学", "", ""), (EDU, SCI, SCI))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff1", "aff2"], ["aff1", "aff2"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"en": SCI}}
    assert [f.note for f in shared(res)] == ["2", "3"]


def test_shared_paragraph_owner_resolved_before(tmp_path, journal, meta):
    """和文 架空大学/A・架空大学/B・空欄/C、英文 Education・Education・Science: B は aff1 にまとまる（B の段落は重複で除外のまま）。
    C は B と段落を共有しているので分けない（分けると B の段落を出力と除外の両方に入れる）。C は aff1 と英文だけの所属を指し、知らせる。"""
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学", ""), (EDU, EDU, SCI))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff1"], ["aff1", "aff2"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"en": SCI}}
    d6, d8 = ja_paras(res)
    assert [x.src for x in res.plan.exclusions if x.src == d8.src] == [d8.src]       # 除外の記録は 1 件
    assert [f.note for f in shared(res)] == ["3"]


def test_shared_and_separate_mixed(tmp_path, journal, meta):
    """別の段落と共有の混在: 和文 架空大学/A・空欄/B・架空大学/C・空欄/D、英文 Education・Education・Science・Science。
    A・B が段落 1 を、C・D が段落 2 を共有。C は分け（aff2）、D は C の aff2 を指すだけ。知らせない。"""
    res = run(tmp_path, journal, meta, ("架空大学", "", "架空大学", ""), (EDU, EDU, SCI, SCI))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff1"], ["aff2"], ["aff2"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"ja": "架空大学", "en": SCI}}
    assert shared(res) == []


def test_shared_paragraph_sharer_without_en(tmp_path, journal, meta):
    """英文の所属がない著者: 和文 架空大学/A・架空大学/B・空欄/C、英文 Education・（なし）・Science。B に英文がないので、C が段落を
    分けて aff2 にする（B は和文の文字が同じ aff1 のまま。0.38.0 までと同じ）。C に矛盾はないので知らせない。"""
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学", ""), (EDU, None, SCI))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff1"], ["aff2"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"ja": "架空大学", "en": SCI}}
    assert shared(res) == []


def test_shared_paragraph_with_concurrent(tmp_path, journal, meta):
    """兼任との組み合わせ: B が 架空大学・架空研究所 の 2 つ、C は空欄で B の 2 つの段落を共有。英文 Education・(Science, Institute)・
    (Arts, Institute): B は 1 つ目を分け（aff3）、C は 1 つ目が B の aff3 と英文だけの所属（Arts）、2 つ目は B と同じ aff2。"""
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学\n架空研究所", ""),
              (EDU, SCI + "\n" + INST, ARTS + "\n" + INST))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff3", "aff2"], ["aff3", "aff2", "aff4"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"ja": "架空研究所", "en": INST},
                    "aff3": {"ja": "架空大学", "en": SCI}, "aff4": {"en": ARTS}}
    assert [f.note for f in shared(res)] == ["3"]


def test_no_en_at_all_shared(tmp_path, journal, meta):
    """英文の所属が 1 つもない: 共有のまま（知らせない）。"""
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学", ""), (None, None, None))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff1"], ["aff1"]] and affs == {"aff1": {"ja": "架空大学"}}
    assert shared(res) == []
