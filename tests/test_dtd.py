"""DTD 検証の不合格の知らせ（C045）: エラーに原因の場所（引用文献・段落）を付け、同じ誤りは件数にまとめ、引用文献の後ろの
資料が原因のときは直し方を知らせる。XML は変えない（DTD 不合格のまま止める）。"""
from lxml import etree

import make_fixtures as mf
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import NEEDS_ACTION, actions, render
from jasme_jats.validate import group_errors, validate

S = mf.S

def _refs_xml(*refs):
    # 根は引用文献の一覧（DTD の検証は根の要素の名前を見ない）
    return ("<ref-list>" + "".join(refs) + "</ref-list>").encode("utf-8")


def _bad_ref(rid, text="架空の文献"):
    # 引用文献の中に別行数式（DTD は mixed-citation の中に disp-formula を認めない）
    return f'<ref id="{rid}"><mixed-citation><disp-formula><alternatives><graphic xlink:href="a.png" xmlns:xlink="http://www.w3.org/1999/xlink"/></alternatives></disp-formula>{text}</mixed-citation></ref>'


def _good_ref(rid):
    return f'<ref id="{rid}"><mixed-citation>正しい文献</mixed-citation></ref>'


def test_validate_names_the_ref_and_groups_same_errors():
    xml = _refs_xml(_bad_ref("B1"), _good_ref("B2"), _bad_ref("B3"), _bad_ref("B4"))
    ok, errors = validate(xml, where={"B3": "引用文献 3件目（B3）「架空の文献」"})
    assert not ok and len(errors) == 3                      # 件数はエラーの数のまま（文字列の一覧）
    assert all(isinstance(e, str) for e in errors)
    assert errors[0].startswith("引用文献 B1")              # 原因の場所（ref の id）が文に入る
    assert errors[1].startswith("引用文献 3件目（B3）「架空の文献」: ")    # 場所の文が分かれば、それを使う
    # 日本語の説明を先に書き、lxml の英語の文は括弧で添える
    assert all(e.split(": ", 1)[1].startswith("要素 disp-formula は、mixed-citation の中に置けません（Element disp-formula is not declared")
               for e in errors)
    groups = group_errors(errors)
    assert len(groups) == 1 and groups[0].count == 3        # 同じ誤りは 1 つにまとめる
    assert groups[0].places == ["引用文献 B1「架空の文献」", "引用文献 3件目（B3）「架空の文献」", "引用文献 B4「架空の文献」"]
    assert groups[0].message.startswith("要素 disp-formula は") and "Element disp-formula is not declared" in groups[0].message
    assert groups[0].kinds == {"ref"}


def test_validate_valid_and_other_places():
    ok, errors = validate(_refs_xml(_good_ref("B1")))
    assert ok and errors == []
    # 表の thead に tr がない: 表（table-wrap の id）まで辿れる
    xml = b'<table-wrap id="T1"><table><thead/><tbody><tr><td>x</td></tr></tbody></table></table-wrap>'
    ok, errors = validate(xml, where={"T1": "表 T1「表1 架空」"})
    assert not ok and len(errors) >= 1
    assert errors[0].startswith("表 T1「表1 架空」: ") and "thead" in errors[0]
    assert group_errors(errors)[0].kinds == {"table-wrap"}


def test_group_errors_plain_strings():
    # 場所のない文字列（場所を引けなかったとき）は、文のままにまとめる
    groups = group_errors(["Element a is bad", "Element a is bad", "Element b is bad"])
    assert [(g.message, g.count, g.places, g.kinds) for g in groups] == [
        ("Element a is bad", 2, [], set()), ("Element b is bad", 1, [], set())]


def _article(tmp_path, refs, name):
    path = tmp_path / name
    mf.make_article(path, "引用文献の中の数式の検証用文書",
                    lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）にならう。")],
                    refs=lambda b: refs)
    return path


def test_dtd_failure_names_ref_and_paragraph_and_suggests_moving_appendix(journal, meta, tmp_path):
    # 引用文献の後ろの資料（要確認 app_after_refs）に別行数式があると、引用文献の中に数式が入って DTD 不合格になる
    refs = [mf.para(S["sec1"], "資料　架空の授業プリント"),
            mf.para(S["ref"], mf.omathpara(mf.mr("x=1"))), mf.para(S["ref"], mf.omathpara(mf.mr("y=2")))]
    res = convert(_article(tmp_path, refs, "a.docx"), meta, journal, Options(out_dir=tmp_path / "out"))
    assert not res.dtd_valid and res.plan.app_after_refs and len(res.dtd_errors) == 2
    bs = [r for r in res.plan.refs if not r.para.text_only()]            # 数式だけの引用文献 2 件
    assert len(bs) == 2
    first = res.dtd_errors[0]
    n = res.plan.refs.index(bs[0]) + 1
    assert first.startswith(f"引用文献 {n}件目（{bs[0].rid}）の、文字のない段落 {bs[0].para.src}（直前は「") and "Element disp-formula is not declared in mixed-citation" in first
    assert "行:" not in first and first.count("（") <= 3                      # 数式だけの段落は、探す手がかりに直前の段落を添える（入れ子にしない）
    acts = {a.key: a for a in actions(res)}
    a = acts["dtd"]
    assert a.level == NEEDS_ACTION and "app_after_refs" in acts
    for text in (a.top, a.box_detail, a.cli):
        assert bs[0].rid in text and "2 件" in text
        assert "引用文献などの後ろ" in text and "英文要旨の後ろ" in text      # 直し方（資料の移動）
    assert text.count("Element disp-formula") == 1                           # 同じ誤りは 1 つにまとめる
    report = render(res)
    chapter12 = report.split("## 12.")[1].split("### J-STAGE")[0]
    assert chapter12.count("Element disp-formula is not declared in mixed-citation") == 1
    assert "（2 件）" in chapter12 and bs[0].rid in chapter12 and bs[1].rid in chapter12 and bs[1].para.src in chapter12
    assert "英文要旨の後ろ" in report.split("## 2.")[0].split("要対応: J-STAGE 指定の DTD")[1].split("\n\n")[0]
    # XML は変えない: DTD 不合格のまま、引用文献の中に別行数式が出る
    root = etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])
    assert len(root.findall(".//mixed-citation/disp-formula")) == 2


def test_no_appendix_advice_without_app_after_refs(journal, meta, tmp_path):
    # 資料の見出しがない（app_after_refs がない）ときは、場所は付けるが、資料の移動は勧めない
    refs = [mf.para(S["ref"], mf.omathpara(mf.mr("x=1")))]
    res = convert(_article(tmp_path, refs, "b.docx"), meta, journal, Options(out_dir=tmp_path / "out"))
    assert not res.dtd_valid and not res.plan.app_after_refs
    a = {a.key: a for a in actions(res)}["dtd"]
    for text in (a.top, a.box_detail, a.cli):
        assert "引用文献 1件目" not in text and "（B" in text and "英文要旨の後ろ" not in text
        assert "変換ツールの不具合の可能性" in text                           # 今までの文のまま


def test_error_in_section_without_id_names_the_section_title():
    # id を持つ祖先がなければ、題名を持つ最も近い祖先（本文の id のない節）の題名で示す
    xml = b"<body><sec><title>\xe3\x81\xaf\xe3\x81\x98\xe3\x82\x81\xe3\x81\xab</title><p>x</p><boom/></sec></body>"
    ok, errors = validate(xml)
    assert not ok and errors[0].startswith("節「はじめに」の中: ")
    assert errors[0].split(": ", 1)[1].startswith("要素 boom は") or "boom" in errors[0]


def test_dtd_hint_uses_the_titles_of_the_app_after_refs_notice(journal, meta, tmp_path):
    from jasme_jats.report import APP_TITLE_BOX
    refs = [mf.para(S["sec1"], "資料　架空の授業プリント"), mf.para(S["ref"], mf.omathpara(mf.mr("x=1")))]
    res = convert(_article(tmp_path, refs, "c.docx"), meta, journal, Options(out_dir=tmp_path / "out"))
    acts = {a.key: a for a in actions(res)}
    assert acts["app_after_refs"].box_title == APP_TITLE_BOX + "（要確認）"          # Colab・1 画面版の枠の題名
    assert f"「{APP_TITLE_BOX}」" in acts["dtd"].box_detail
    assert "引用文献などの後ろに、資料の見出しと思われる段落があります" in acts["dtd"].top
