"""J-STAGE へのアップロード用のフォルダ構成と ZIP を作る。

J-STAGE『記事アップロードフォルダ構成（FULL-J）』に従う:
  {資料コード}/{巻}/{号}/{記事識別子}/{記事識別子}.xml
                                     /{記事識別子}.pdf      ← PDF は J-STAGE で必須（利用者が用意）
                                     /Graphics/{画像}
ZIP のファイル名は {資料コード}_{記事識別子}.zip（例: jasme_31_1.zip）。複数の論文を続けて変換しても名前が重ならないように、
フォルダ構成の資料に書かれた {資料コード}.zip に記事識別子を足している。J-STAGE が確かめるのは ZIP の中のフォルダ構成で、
記事アップロードメッセージ一覧に ZIP の名前についてのエラーは日本語のファイル名（EMSGM034E）しかない
（2026-10 の試験登載で、この名前のまま受け付けられることを確認）。

ZIP に入れるものは upload_entries だけで決める（今回の変換で作った XML、今回指定した PDF、Graphics/ のうち作業する人が入れた画像）。
記事フォルダに残っている前回の変換の残りや手で置いたファイル、同じ出力フォルダで変換したほかの記事は入れない
（入れなかったファイルは unzipped_files で求め、レポートの 10 章に出す）。作った ZIP は zip_problems で読み直して確かめる。
"""
from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

# ZIP に入れる画像の状態（images.SlotImage.status）: 作業する人が入れた画像だけ（docx の画像は書き出さない。修正計画 W1）
ZIP_STATUSES = ("user",)
RE_NAME = re.compile(r"[A-Za-z0-9._\-]+")      # ZIP の名前・ZIP の中のフォルダ名・ファイル名に使える文字（EMSGM034E）


def article_dir(out_dir: Path, journal, meta) -> Path:
    aid = meta.article_id(journal)
    return out_dir / journal.journal_id / (meta.volume or "0") / (meta.issue or "0") / aid


def zip_image_names(images) -> list:
    """ZIP に入れる画像の名前（images.SlotImage のうち、作業する人が入れたもの〈状態 user〉）。"""
    return [i.name for i in images if i.name and i.status in ZIP_STATUSES]


def upload_entries(out_dir: Path, journal, meta, image_names=(), has_pdf=False) -> list:
    """アップロード用の ZIP に入れる項目（ZIP の中のパス。out_dir からの相対）。ZIP の中身はこれだけで決める。

    {記事識別子}.xml、今回置いた {記事識別子}.pdf（has_pdf）、Graphics/ の画像（image_names。zip_image_names の名前）。
    """
    adir = article_dir(Path(""), journal, meta).as_posix()
    aid = meta.article_id(journal)
    out = [f"{adir}/{aid}.xml"]
    if has_pdf:
        out.append(f"{adir}/{aid}.pdf")
    out += [f"{adir}/Graphics/{name}" for name in image_names]
    return out


def write_package(out_dir: Path, journal, meta, xml_bytes: bytes, pdf_path=None, image_names=()):
    """XML と（あれば）PDF を所定の位置に置き、ZIP を作る。画像は pipeline.add_images が Graphics/ に入れたものとする。

    image_names: ZIP に入れる画像の名前（zip_image_names）。戻り値: (ZIP のパス, 記事フォルダ, PDF を置いたか)。
    """
    adir = article_dir(out_dir, journal, meta)
    adir.mkdir(parents=True, exist_ok=True)
    aid = meta.article_id(journal)
    (adir / f"{aid}.xml").write_bytes(xml_bytes)
    has_pdf = False
    if pdf_path:
        dest = adir / f"{aid}.pdf"
        # 記事フォルダに残っている前の変換の PDF をそのまま指定したとき（--pdf に出力先の PDF）は、写さずに使う
        if not (dest.exists() and Path(pdf_path).samefile(dest)):
            shutil.copyfile(pdf_path, dest)
        has_pdf = True
    return make_zip(out_dir, journal, meta, image_names, has_pdf), adir, has_pdf


def zip_path(out_dir: Path, journal, meta) -> Path:
    return out_dir / f"{journal.journal_id}_{meta.article_id(journal)}.zip"


def make_zip(out_dir: Path, journal, meta, image_names=(), has_pdf=False) -> Path:
    """upload_entries の項目だけを ZIP にする。利用者が後から画像を入れたとき（pipeline.add_images）にも作り直す。"""
    zpath = zip_path(out_dir, journal, meta)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for name in upload_entries(out_dir, journal, meta, image_names, has_pdf):
            z.write(out_dir / name, name)
    return zpath


def zip_problems(zpath: Path, journal, meta, images=None) -> list:
    """作った ZIP を読み直し、J-STAGE のアップロードで弾かれる形を調べる。戻り値: [(メッセージ ID, 内容)]（jstage_rules.check と同じ形）。

    (a) ZIP の名前と (b) ZIP の中のフォルダ名・ファイル名に英数字以外（日本語など）がある（EMSGM034E。Graphics/ の画像の名前は
    jstage_rules.check が見るので、ここでは見ない）。(c) 記事フォルダの外の項目（同じ出力フォルダで変換したほかの記事など。
    J-STAGE で記事が 2 本登録されたり、EMSGM219E「資料コード、巻、号、記事コードが同一のファイルが存在します」になったりするおそれ）と、
    記事フォルダの中の想定外のファイル・フォルダ（EMSGM074E「不正なファイル又は、フォルダがあります」）。(d) 0 バイトのファイル
    （XML は EMSGM053E、PDF は EMSGM059E、画像は EMSGM073E）。(e) 記事の XML がない（'-'。make_zip は必ず入れるので、ZIP を
    手で作り直したときなどの確かめ）。メッセージ ID は記事アップロードメッセージ一覧（別紙 3）のもの。PDF がないことは見ない
    （14 章のチェックリストで知らせる）。
    images（images.SlotImage の一覧。渡したときだけ）: (f) Graphics/ に、画像の置き場所にない名前の画像がある、(g) 作業する人が入れた
    画像（状態 user）が ZIP にない（修正計画 W1 の 2.9）。置き場所の名前で、まだ入れていない画像は数えない（必須の手順 images が
    伝える。数えると、画像の要る論文で最初の変換のたびに要対応 upload が出る）。
    """
    out = []
    zpath = Path(zpath)
    if not RE_NAME.fullmatch(zpath.name):
        out.append(("EMSGM034E", f"アップロード用の ZIP の名前に英数字以外の文字がある（{zpath.name}）"))
    try:
        with zipfile.ZipFile(zpath) as z:
            infos = z.infolist()
    except (OSError, zipfile.BadZipFile) as e:
        return out + [("EMSGM034E", f"アップロード用の ZIP を ZIP として読めない（{e}）")]
    adir = article_dir(Path(""), journal, meta).as_posix()
    aid = meta.article_id(journal)
    expected = {f"{aid}.xml": ("EMSGM053E", "XML"), f"{aid}.pdf": ("EMSGM059E", "PDF")}
    bad_parts, outside = [], []
    for info in infos:
        name = info.filename.rstrip("/")
        parts = name.split("/")
        inner = name[len(adir) + 1:] if name.startswith(adir + "/") else None
        image = inner is not None and inner.startswith("Graphics/") and inner.count("/") == 1 and not info.is_dir()
        for k, part in enumerate(parts):
            if image and k == len(parts) - 1:
                continue
            path = "/".join(parts[:k + 1])
            if not RE_NAME.fullmatch(part) and path not in bad_parts:
                bad_parts.append(path)
                out.append(("EMSGM034E", f"ZIP の中のフォルダ名・ファイル名に英数字以外の文字がある（{path}）"))
        if inner is None:
            if info.is_dir() and (adir.startswith(name + "/") or name == adir):
                continue                                  # 記事フォルダと、そこまでのフォルダ（資料コード・巻・号）
            top = "/".join(parts[:4])
            if top not in outside:
                outside.append(top)
                shown = top + ("/" if top != name or info.is_dir() else "")
                out.append(("-", (f"記事フォルダ（{adir}/）の外に {shown} がある（ほかの記事なら、J-STAGE で記事が 2 本登録"
                                  "されたり、EMSGM219E になったりするおそれ）")))
            continue
        if info.is_dir() and inner == "Graphics":
            continue
        if inner in expected and not info.is_dir():
            mid, what = expected[inner]
        elif image:
            mid, what = "EMSGM073E", "画像"
        else:
            out.append(("EMSGM074E", f"記事フォルダの中に、アップロードできないファイル・フォルダがある（{inner}）"))
            continue
        if info.file_size == 0:
            out.append((mid, f"{what}のファイルが 0 バイト（{inner}）"))
    if not any(info.filename == f"{adir}/{aid}.xml" for info in infos):
        out.append(("-", f"アップロード用の ZIP に XML（{adir}/{aid}.xml）が入っていない（変換し直してください）"))
    if images is not None:
        known = {i.name for i in images if i.name}
        got = [info.filename[len(adir) + len("/Graphics/"):] for info in infos
               if info.filename.startswith(f"{adir}/Graphics/") and not info.is_dir()]
        out += [("-", f"ZIP の Graphics/ に、画像を入れる場所にない名前の画像がある（{name}）") for name in got if name not in known]
        out += [("-", f"入れた画像 {name} が、アップロード用の ZIP に入っていない（画像を入れ直してください）")
                for name in zip_image_names(images) if name not in got]
    return out


XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


def _remove_keep_tail(el) -> None:
    """要素を取り除く。後ろの文字（tail）は、前の兄弟要素の tail か親の text に移して残す。"""
    parent = el.getparent()
    if el.tail:
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def apply_images(xml_base: bytes, images) -> bytes:
    """画像の置き場所をすべて書いた XML（pipeline.Result.xml_base。名前の拡張子は .png）に、入れた画像を反映した最終の XML。

    images は images.SlotImage の一覧。入れた画像（状態 user）は xlink:href の拡張子を入れた画像の形式に合わせ、「入れない」とした
    置き場所（skipped。キャプションのない画像だけ）は要素ごと取り除き（<fig> の中のただ 1 つの <graphic> なら、その <fig> ごと。
    <inline-graphic> はそれだけ）、入れていない任意の置き場所（unused）の <inline-graphic> も取り除く。取り除くときも後ろの文字（tail）は
    残す（段落の文字は変わらない）。まだ入れていない置き場所（missing）はそのまま。変えるところがなければ xml_base をそのまま返す。
    変換のときも、後から画像を入れたときも、この 1 つの関数で最終の XML を作り直す（修正計画 W1 の 2.6）。
    """
    from lxml import etree

    from .builder import serialize
    todo = {Path(i.name).stem: i for i in images if i.status in ("user", "skipped", "unused")}
    if not todo:
        return xml_base
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, huge_tree=True)
    root = etree.fromstring(xml_base, parser)
    changed = False
    for el in list(root.iter("graphic", "inline-graphic")):
        href = el.get(XLINK_HREF) or ""
        img = todo.get(href.rsplit(".", 1)[0])
        if img is None:
            continue
        if img.status == "user":
            name = f"{Path(href).stem}.{img.format or href.rsplit('.', 1)[-1]}"
            if name != href:
                el.set(XLINK_HREF, name)
                changed = True
            continue
        parent = el.getparent()
        if (el.tag == "graphic" and parent is not None and parent.tag == "fig" and not parent.get("id")
                and len(parent) == 1 and not (parent.text or "").strip()):
            _remove_keep_tail(parent)       # キャプションのない図（<fig><graphic/></fig>）は <fig> ごと
        else:
            _remove_keep_tail(el)
        changed = True
    return serialize(root) if changed else xml_base


def unzipped_files(out_dir: Path, journal, meta, zpath: Path) -> list:
    """記事フォルダにあるのに、アップロード用の ZIP に入れなかったファイル（記事フォルダからの相対パス）。

    前回の変換の残り（今回指定しなかった PDF、今回は出力しなかった画像など）や、手で置いたファイル。レポートの 10 章に出す。
    """
    adir = article_dir(out_dir, journal, meta)
    if not adir.is_dir():
        return []
    try:
        with zipfile.ZipFile(zpath) as z:
            names = set(z.namelist())
    except (OSError, zipfile.BadZipFile):
        names = set()
    return sorted(f.relative_to(adir).as_posix() for f in adir.rglob("*")
                  if f.is_file() and f.relative_to(out_dir).as_posix() not in names)
