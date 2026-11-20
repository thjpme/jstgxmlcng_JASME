"""外部のレビュー（docs/REVIEW_CODEX_2026-11.md）の R4: 和文の所属が同じ著者の、英文の所属が違うとき。

和文の所属の文字が同じ著者は、和文の段落を 1 つの所属（Aff）にまとめ、2 人目の和文の段落を「重複する所属」で除外していた。
英文の所属が違うと、1 人目の英文所属が 2 人目にも付き、2 人目は 2 つの所属を指していた。所有者の決定で、共有を解く: 2 人目の
所属は docx の対応のとおり（和文は 2 人目の段落、英文は 2 人目の英文所属）の別の所属にし、除外していた和文の段落を出力に戻す
（除外の記録も外す）。和文・英文とも同じ著者だけを 1 つにまとめる。docx は make_fixtures.make_conflict で作る（内容は架空）。
"""
import make_fixtures as mf
from lxml import etree

from jasme_jats.pipeline import Options, convert

EDU = "Fictional University, Faculty of Education"
SCI = "Fictional University, Faculty of Science"
NAMES_JA = ("試験　六郎", "検証　七郎", "確認　八郎")
NAMES_EN = ("Rokuro SHIKEN", "Nanao KENSHO", "Hachiro KAKUNIN")


def run(tmp_path, journal, meta, ja_affs, en_affs, name="r4", en_rows=None):
    """和文の所属 ja_affs（著者ごと。改行で兼任）・英文の所属 en_affs（著者ごと。None なら英文の所属の行を置かない。改行で兼任）の
    論文を変換し、確かめ（不変性・最終・DTD・J-STAGE のチェック）が合格することを確かめて返す。"""
    ja_rows = [(aff, NAMES_JA[k]) for k, aff in enumerate(ja_affs)]
    if en_rows is None:
        en_rows = []
        for k, aff in enumerate(en_affs):
            en_rows.append(("name", NAMES_EN[k]))
            for line in (aff.split("\n") if aff is not None else []):
                en_rows.append(("aff", line))
    path = mf.make_conflict(tmp_path / f"{name}.docx", ja_rows=ja_rows, en_rows=en_rows)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / f"out_{name}", ai_mode="none"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert res.jstage_issues == []
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


def excluded_texts(res):
    return [(x.text.strip(), x.reason) for x in res.plan.exclusions if not x.blank]


def test_same_ja_same_en_still_shared(tmp_path, journal, meta):
    """和文も英文も同じ 2 人: 今までどおり 1 つの所属にまとめ、2 人目の和文・英文の段落は「重複する所属」で除外する。"""
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学"), (EDU, EDU))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff1"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}}
    dup = [t for t, why in excluded_texts(res) if why.startswith("重複する所属")]
    assert dup == ["架空大学", EDU]


def test_same_ja_different_en_split(tmp_path, journal, meta):
    """和文が同じで英文が違う 2 人（R4 の再現）: 所属を 2 つにし、1 人目は aff1 だけ、2 人目は aff2 だけを指す。aff2 の和文は
    2 人目の段落で、除外の記録にない。"""
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学"), (EDU, SCI))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff2"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"ja": "架空大学", "en": SCI}}
    plan = res.plan
    a1, a2 = plan.authors
    assert a1.affs == [plan.affs[0]] and a2.affs == [plan.affs[1]]
    second_ja = plan.affs[1].ja
    assert second_ja is not plan.affs[0].ja
    assert second_ja.src not in {x.src for x in plan.exclusions}
    assert not [t for t, why in excluded_texts(res) if why.startswith("重複する所属")]
    assert plan.locations[second_ja.src] == "所属2（和文）"


def test_same_ja_three_authors_aba(tmp_path, journal, meta):
    """和文が同じ 3 人で英文が A・B・A: 所属は 2 つ（1 人目と 3 人目が共有、2 人目が別）。3 人目の和文・英文は重複で除外する。"""
    res = run(tmp_path, journal, meta, ("架空大学",) * 3, (EDU, SCI, EDU))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff2"], ["aff1"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"ja": "架空大学", "en": SCI}}
    plan = res.plan
    third_ja = [c for c in plan.paras.values() if c.plain() == "架空大学"][2]
    dup = {x.src: x.reason for x in plan.exclusions if x.reason.startswith("重複する所属")}
    assert third_ja.src in dup and plan.affs[0].ja.src in dup[third_ja.src]
    assert plan.affs[1].ja.src not in dup
    assert [t for t, why in excluded_texts(res) if why.startswith("重複する所属")] == ["架空大学", EDU]


def test_same_ja_three_authors_abb(tmp_path, journal, meta):
    """和文が同じ 3 人で英文が A・B・B: 所属は 2 つ（2 人目と 3 人目が共有）。3 人目の和文は 2 人目の所属にまとめて除外する。"""
    res = run(tmp_path, journal, meta, ("架空大学",) * 3, (EDU, SCI, SCI))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff2"], ["aff2"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"ja": "架空大学", "en": SCI}}
    plan = res.plan
    third_ja = [c for c in plan.paras.values() if c.plain() == "架空大学"][2]
    dup = {x.src: x.reason for x in plan.exclusions if x.reason.startswith("重複する所属")}
    assert plan.affs[1].ja.src in dup[third_ja.src]          # まとめた先（2 人目の段落）を理由に書く
    assert sum(1 for x in plan.exclusions if x.src == third_ja.src) == 1


def test_same_ja_no_en_aff_kept_shared(tmp_path, journal, meta):
    """和文が同じで英文の所属がない（英文の冒頭部に所属がない・2 人目の英文所属だけない）: 今までどおり共有のまま。"""
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学"), (None, None))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff1"]] and affs == {"aff1": {"ja": "架空大学"}}
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学"), (EDU, None), name="b")
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff1"]] and affs == {"aff1": {"ja": "架空大学", "en": EDU}}


def test_concurrent_affs_with_shared_ja(tmp_path, journal, meta):
    """兼任: 2 人目が所属を 2 つ持ち、1 つ目の和文が 1 人目と同じ。英文の 1 つ目が違えば、その所属だけを解き、2 つ目の英文は
    2 人目の 2 つ目の和文に対応付ける。"""
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学\n架空研究所"),
              (EDU, SCI + "\nFictional Institute"))
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff3", "aff2"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"ja": "架空研究所", "en": "Fictional Institute"},
                    "aff3": {"ja": "架空大学", "en": SCI}}
    # 英文が同じなら、今までどおり 1 つ目を共有する
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学\n架空研究所"),
              (EDU, EDU + "\nFictional Institute"), name="b")
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff1", "aff2"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": EDU}, "aff2": {"ja": "架空研究所", "en": "Fictional Institute"}}


def test_concurrent_affs_without_sharing_unchanged(tmp_path, journal, meta):
    """共有のない兼任は今までどおり（和文の所属の順に英文の所属を対応付ける）。"""
    res = run(tmp_path, journal, meta, ("架空大学\n架空研究所",), ("Fictional University\nFictional Institute",))
    refs, affs = xml_affs(res)
    assert refs == [["aff1", "aff2"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": "Fictional University"},
                    "aff2": {"ja": "架空研究所", "en": "Fictional Institute"}}


def test_en_aff_before_name_unchanged(tmp_path, journal, meta):
    """英文の所属が著者名の前にある（docs/REVIEW_2026-11.md の K13。対象外）: 今の挙動を変えない。1 人目の英文所属は著者に付かない
    新しい所属になり、2 人目の英文所属が共有の所属の英文になる（2 人目の英文の所属の行は 1 人目の名前の後ろ）。"""
    rows = [("aff", EDU), ("name", NAMES_EN[0]), ("aff", SCI), ("name", NAMES_EN[1])]
    res = run(tmp_path, journal, meta, ("架空大学", "架空大学"), None, en_rows=rows)
    refs, affs = xml_affs(res)
    assert refs == [["aff1"], ["aff1"]]
    assert affs == {"aff1": {"ja": "架空大学", "en": SCI}, "aff2": {"en": EDU}}
