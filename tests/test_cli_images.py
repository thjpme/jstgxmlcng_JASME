"""コマンドラインの --images（名前で置き場所に合わせる）・--no-image・図の画像の表・終了コード（修正計画 W1 の 4.7。手順 14）。内容は架空。"""
import pytest

from conftest import META_EXAMPLE, key_png
from jasme_jats.cli import main
from test_image_carry import make

AID = "31_1"


def two_figs(tmp_path):
    return make(tmp_path / "a.docx", ["三角形ABC", "児童Bの記述"])


def row(out, key, label, state) -> bool:
    """表の行（幹・図番号・状態が、この順で空白をはさんで並ぶ行）があるか。"""
    import re
    return re.search(rf"^  {re.escape(key)}\s+{re.escape(label)}\s+{re.escape(state)}", out, re.M) is not None


def run(tmp_path, *args):
    return main([str(tmp_path / "a.docx"), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "out"), *args])


def keys_of(tmp_path, capsys):
    """画像なしで変換して、表の行から幹を取る。"""
    assert run(tmp_path) == 1
    out = capsys.readouterr().out
    return [line.split()[0] for line in out.splitlines() if line.startswith("  fig")]


def test_images_aliases_and_table(tmp_path, capsys):
    """--images のファイル名は、幹・図の番号の別名・記事識別子つきの名前のどれでもよい。表の見出しは手順 images の progress。"""
    two_figs(tmp_path)
    assert run(tmp_path) == 1
    cap = capsys.readouterr()
    assert "図の画像（あと 2 枚／全部で 2 枚）:" in cap.out and row(cap.out, "fig01", "図1", "未") and row(cap.out, "fig02", "図2", "未")
    assert cap.out.rstrip().splitlines()[-1].startswith("図の確かめの一覧: ") and cap.out.rstrip().endswith(f"{AID}_図の確かめ.html")
    d = tmp_path / "pics"
    d.mkdir()
    (d / "図1.png").write_bytes(key_png(1))                           # 番号からの別名
    assert run(tmp_path, "--images", str(d)) == 1                     # 1 枚だけ入れた: まだ残りがある
    cap = capsys.readouterr()
    assert "図の画像（あと 1 枚／全部で 2 枚）:" in cap.out and row(cap.out, "fig01", "図1", "入れた（図1.png・PNG・") and row(cap.out, "fig02", "図2", "未")
    (d / f"{AID}_fig02.PNG").write_bytes(key_png(2))                  # 記事識別子つき（大文字の拡張子）
    assert run(tmp_path, "--images", str(d)) == 0
    cap = capsys.readouterr()
    assert "図の画像（2 枚をすべて入れました）:" in cap.out and "画像を入れて ZIP とレポートを作り直した: " in cap.out and "fig01" in cap.out and "fig02" in cap.out


def test_images_unmatched_and_foreign_names_go_to_stderr(tmp_path, capsys):
    """合う置き場所のない名前・別の記事の識別子つきの名前は、標準エラーに出して続ける（合う画像は入れる）。重なる名前は入れない。"""
    two_figs(tmp_path)
    d = tmp_path / "pics"
    d.mkdir()
    (d / "fig01.png").write_bytes(key_png(1))
    (d / "cover.png").write_bytes(key_png(2))
    (d / "99_99_fig02.png").write_bytes(key_png(3))            # 別の記事の名前
    (d / ".hidden.png").write_bytes(key_png(4))                # 隠しファイルは見ない
    assert run(tmp_path, "--images", str(d)) == 1               # fig02 が残る
    cap = capsys.readouterr()
    assert "画像: 「cover.png」に合う図がありません" in cap.err and "画像: 「99_99_fig02.png」に合う図がありません" in cap.err
    assert ".hidden" not in cap.err and "図の画像（あと 1 枚／全部で 2 枚）:" in cap.out and row(cap.out, "fig01", "図1", "入れた（fig01.png")
    (d / "図2.png").write_bytes(key_png(5))
    (d / "fig02.jpg").write_bytes(key_png(6))                   # 同じ図 2 に合うファイルが 2 つ
    assert run(tmp_path, "--images", str(d)) == 1
    err = capsys.readouterr().err
    assert "同じ図（fig02）に合うファイルが複数あるので、どれも入れていません" in err and "図2.png" in err and "fig02.jpg" in err


def test_images_not_png_stops_with_2(tmp_path, capsys):
    """名前の合う画像が PNG・JPEG・GIF でなければ、1 枚も入れずに終了コード 2。"""
    two_figs(tmp_path)
    d = tmp_path / "pics"
    d.mkdir()
    (d / "fig01.png").write_bytes(key_png(1))
    (d / "fig02.png").write_bytes(b"not an image")
    assert run(tmp_path, "--images", str(d)) == 2
    assert "画像:" in capsys.readouterr().err


def test_no_image_table_and_exit_codes(tmp_path, capsys):
    """--no-image: キャプションのない画像を入れない。表の行は「入れない」で、手順の「全部で」から除く。終了コード 0・1・2。"""
    make(tmp_path / "a.docx", ["三角形ABC"], nocaps=[("画像の前の本文である。", "red")])
    assert run(tmp_path) == 1
    out = capsys.readouterr().out
    assert "図の画像（あと 2 枚／全部で 2 枚）:" in out
    nocap = next(line.split()[0] for line in out.splitlines() if line.startswith("  img"))
    assert f"  {nocap}" in out and "—" in out
    d = tmp_path / "pics"
    d.mkdir()
    (d / "fig01.png").write_bytes(key_png(1))
    assert run(tmp_path, "--images", str(d), "--no-image", nocap) == 0
    out = capsys.readouterr().out
    assert "図の画像（1 枚をすべて入れました）:" in out and row(out, nocap, "—", "入れない")
    assert run(tmp_path, "--images", str(d), "--no-image", "fig01") == 2       # 図の幹は入れないことにできない


def test_no_metafile_option_is_gone(tmp_path, capsys):
    two_figs(tmp_path)
    with pytest.raises(SystemExit) as e:
        run(tmp_path, "--no-metafile-conversion")
    assert e.value.code == 2 and "unrecognized arguments" in capsys.readouterr().err
