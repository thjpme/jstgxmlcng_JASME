"""外部レビュー（docs/REVIEW_CODEX_2026-11.md）の R1・R2・R12: 変換し直したときの画像の持ち越し（pipeline.reapply_images）。

R1: 号だけ違う別の論文に、前の論文の画像を入れない（持ち越しで別の論文を見分ける鍵に号を加える。記事識別子・ZIP の名前は変えない）。
R2: 画像を入れていない前の図も、同じ本体の図の数に数える（図を削除して番号を詰めたとき、削除した図の画像を残った図に入れない）。
R12: 持ち越せた画像が 0 枚でも、保存したレポートに「入れ直しが要る前の画像」の節を出す。内容は架空。
"""
import make_fixtures as mf
from conftest import one_color_png
from jasme_jats.config import ArticleMeta
from jasme_jats.pipeline import Options, add_images, convert, kept_images, reapply_images
from jasme_jats.report import images_action, render

S = mf.S


def png(color) -> bytes:
    return one_color_png(color=color)


def make(path, figs, title="持ち越しの検証用文書", pic="", cap_style="fig_cap", label="図", text="本文の段落である。"):
    """図（表）figs（キャプションの本体の一覧。番号は前から付ける）を並べた小さな論文。pic で docx の画像の中身を変える。
    表（label="表"）は、キャプションの後ろに画像を置く（画像で組んだ表）。"""
    def parts(b):
        out = [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], text)]
        for n, cap in enumerate(figs, 1):
            rid = b.add_image(f"c{n}.png", mf.png_bytes(f"{pic} {label} {cap} {n}"))
            img = mf.para(S["body"], mf.drawing(rid, 1440000, 960000, 900 + n))
            capp = mf.para(S[cap_style], f"{label}{n}　{cap}")
            out += [capp, img] if label == "表" else [img, capp]
        return out
    mf.make_article(path, title, parts)
    return path


def conv(tmp, docx, journal, issue="1", fpage="1"):
    meta = ArticleMeta.from_dict({"volume": "31", "issue": issue, "fpage": fpage, "lpage": "30", "pub_date": "2026-03-31",
                                  "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり"})
    return convert(docx, meta, journal, Options(out_dir=tmp / "out"))


def user(res):
    return {i.key: i for i in res.images if i.status == "user"}


# ---------------------------------------------------------------------------- R1
def test_r1_other_issue_same_first_page_gets_no_image_in_app(tmp_path):
    """1 画面版: 31 巻 1 号・開始ページ 1 の論文の fig01 に画像を入れ、31 巻 2 号・開始ページ 1 の別の論文を変換しても、前の画像を入れない。"""
    from test_app import filled
    a = make(tmp_path / "A.docx", ["児童の記述"], title="論文Aの題目", pic="A")
    st = filled(tmp_path, docx=a)
    st.convert()
    pic = tmp_path / "p.png"
    pic.write_bytes(png((200, 10, 10)))
    st.add_images({"fig01": str(pic)})
    assert st.missing_images() == []
    b = make(tmp_path / "B.docx", ["児童の記述"], title="論文Bの題目", pic="B")
    st.set_inputs(docx=str(b), issue="2")
    st.convert()
    assert st.res.meta.article_id(st.res.journal) == "31_1"               # 記事識別子は変えない（所有者の決定）
    assert [i.status for i in st.res.images] == ["missing"] and user(st.res) == {}
    [d] = st.res.images_dropped
    assert d.key == "fig01" and d.other_article and "号" in d.why
    action = images_action(st.res)
    assert not action.done and st.needs_action
    assert f"前の論文（{d.other_article}）で入れた画像 1 枚は、記事の巻・号・ページが違うので入れていません。" in action.box_detail
    assert "1号" in d.other_article                                      # 記事識別子が同じでも、前の論文が分かる


def test_r1_same_issue_revised_docx_still_carries(tmp_path, journal):
    """同じ号で docx だけ改稿した場合は、今までどおり持ち越す（号の表記の揺れ〈全角・半角〉も同じ号とみなす）。"""
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童の記述"]), journal, issue="2")
    add_images(res, {"fig01": ("x.png", png((1, 2, 3)))})
    kept = kept_images(res)
    new = conv(tmp_path, make(tmp_path / "b.docx", ["児童の記述"], text="直した本文の段落である。"), journal, issue="２")
    assert reapply_images(new, kept) == ["fig01"] and new.images_dropped == []


def test_r1_empty_issue_both_carries_and_empty_vs_filled_does_not(tmp_path, journal):
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童の記述"]), journal, issue="")
    add_images(res, {"fig01": ("x.png", png((1, 2, 3)))})
    kept = kept_images(res)
    same = conv(tmp_path, make(tmp_path / "b.docx", ["児童の記述"]), journal, issue="")
    assert reapply_images(same, kept) == ["fig01"]
    other = conv(tmp_path, make(tmp_path / "c.docx", ["児童の記述"]), journal, issue="3")
    assert reapply_images(other, kept) == [] and [d.key for d in other.images_dropped] == ["fig01"]
    assert other.images_dropped[0].other_article


def test_r1_other_first_page_same_issue_is_still_other_article(tmp_path, journal):
    """号ごとにページ付けしない（巻で通し）誌でも、開始ページが違えば今までどおり別の論文（号の比べは足すだけ）。"""
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童の記述"]), journal, issue="1", fpage="1")
    add_images(res, {"fig01": ("x.png", png((1, 2, 3)))})
    kept = kept_images(res)
    new = conv(tmp_path, make(tmp_path / "b.docx", ["児童の記述"]), journal, issue="1", fpage="13")
    assert reapply_images(new, kept) == [] and new.images_dropped[0].other_article == "31_1"


# ---------------------------------------------------------------------------- R2
def test_r2_deleted_figure_image_not_put_on_renumbered_twin(tmp_path, journal):
    """図1・図2 の本体がどちらも「児童の記述」で、fig01 にだけ画像 → 図1 を削除して旧図2 を図1 に改番: 入れない。"""
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童の記述", "児童の記述"], pic="X"), journal)
    add_images(res, {"fig01": ("x.png", png((9, 9, 9)))})
    kept = kept_images(res)
    assert list(kept) == ["fig01"]
    new = conv(tmp_path, make(tmp_path / "b.docx", ["児童の記述"], pic="Y"), journal)
    assert reapply_images(new, kept) == [] and user(new) == {}
    [d] = new.images_dropped
    assert d.key == "fig01" and "決められません" in d.why and d.suggest == ""
    assert not images_action(new).done and new.needs_action


def test_r2_same_for_tables(tmp_path, journal):
    kw = {"cap_style": "tab_cap", "label": "表"}
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童の記述", "児童の記述"], pic="X", **kw), journal)
    keys = [i.key for i in res.images]
    assert keys == ["tab01", "tab02"]
    add_images(res, {"tab01": ("x.png", png((9, 9, 9)))})
    kept = kept_images(res)
    new = conv(tmp_path, make(tmp_path / "b.docx", ["児童の記述"], pic="Y", **kw), journal)
    assert reapply_images(new, kept) == [] and [d.key for d in new.images_dropped] == ["tab01"]


def test_r2_different_body_of_unimaged_figure_still_carries(tmp_path, journal):
    """画像を入れていない前の図の本体が違うときは、今までどおり入る（前の図2 を消しても、図1 は図1）。"""
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童の記述", "授業の全体の流れ"]), journal)
    add_images(res, {"fig01": ("x.png", png((9, 9, 9)))})
    kept = kept_images(res)
    new = conv(tmp_path, make(tmp_path / "b.docx", ["児童の記述"]), journal)
    assert reapply_images(new, kept) == ["fig01"] and new.images_dropped == []


def test_r2_unimaged_old_figure_matching_now_exactly_blocks_fuzzy_carry(tmp_path, journal):
    """前の図1「児童Aの記述」（画像あり）・図2「児童Bの記述」（画像なし）で図1 を消すと、今の図1「児童Bの記述」は前の図2 なので、
    0.8 以上で似ていても前の図1 の画像を入れない。"""
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童Aの記述", "児童Bの記述"]), journal)
    add_images(res, {"fig01": ("x.png", png((9, 9, 9)))})
    kept = kept_images(res)
    new = conv(tmp_path, make(tmp_path / "b.docx", ["児童Bの記述"]), journal)
    assert reapply_images(new, kept) == [] and [d.key for d in new.images_dropped] == ["fig01"]
    assert "見つかりません" in new.images_dropped[0].why


def test_r2_unimaged_old_figure_closer_after_edit_blocks_fuzzy_carry(tmp_path, journal):
    """前の図2（画像なし）のキャプションを少し直して図1 に繰り上げた形: 今の図1 は前の図2 にいちばん近いので、前の図1 の画像を入れない。"""
    res = conv(tmp_path, make(tmp_path / "a.docx", ["三角形の辺の長さを調べた児童Aの記述", "三角形の辺の長さを調べた児童Bの記述"]), journal)
    add_images(res, {"fig01": ("x.png", png((9, 9, 9)))})
    kept = kept_images(res)
    new = conv(tmp_path, make(tmp_path / "b.docx", ["三角形の辺の長さを調べた児童Bの記述を"]), journal)
    assert reapply_images(new, kept) == [] and [d.key for d in new.images_dropped] == ["fig01"]


def test_r2_fuzzy_carry_with_other_unimaged_figure_unchanged(tmp_path, journal):
    """本体が少し変わった図は、画像を入れていないほかの図がそのままなら今までどおり入れる（要確認 image_changed）。"""
    res = conv(tmp_path, make(tmp_path / "a.docx", ["三角形の辺の長さを調べた児童Aの記述", "三角形の辺の長さを調べた児童Bの記述"]), journal)
    add_images(res, {"fig01": ("x.png", png((9, 9, 9)))})
    kept = kept_images(res)
    new = conv(tmp_path, make(tmp_path / "b.docx", ["三角形の辺の長さを調べた児童Aの記述を", "三角形の辺の長さを調べた児童Bの記述"]), journal)
    assert reapply_images(new, kept) == ["fig01"] and [c.key for c in new.images_changed] == ["fig01"]


# ---------------------------------------------------------------------------- R12
def test_r12_saved_report_lists_dropped_when_none_carried(tmp_path, journal):
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童の記述"]), journal)
    add_images(res, {"fig01": ("x.png", png((9, 9, 9)))})
    kept = kept_images(res)
    new = conv(tmp_path, make(tmp_path / "b.docx", ["全く無関係の内容"]), journal)
    assert reapply_images(new, kept) == [] and [d.key for d in new.images_dropped] == ["fig01"]
    saved = new.report_path.read_text(encoding="utf-8")
    assert "入れ直しが要る前の画像" in saved and saved == render(new)


def test_r12_nothing_kept_leaves_report_alone(tmp_path, journal):
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童の記述"]), journal)
    before = res.report_path.read_text(encoding="utf-8")
    assert reapply_images(res, {}) == [] and res.report_path.read_text(encoding="utf-8") == before
