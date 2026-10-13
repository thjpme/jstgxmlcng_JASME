"""J-STAGE へのアップロード用のフォルダ構成と ZIP を作る。

J-STAGE『記事アップロードフォルダ構成（FULL-J）』に従う:
  {資料コード}/{巻}/{号}/{記事識別子}/{記事識別子}.xml
                                     /{記事識別子}.pdf      ← PDF は J-STAGE で必須（利用者が用意）
                                     /Graphics/{画像}
ZIP のファイル名は {資料コード}_{記事識別子}.zip（例: jasme_31_1.zip）。複数の論文を続けて変換しても名前が重ならないように、
フォルダ構成の資料に書かれた {資料コード}.zip に記事識別子を足している。J-STAGE が確かめるのは ZIP の中のフォルダ構成で、
記事アップロードメッセージ一覧に ZIP の名前についてのエラーは日本語のファイル名（EMSGM034E）しかない
（2026-10 の試験登載で、この名前のまま受け付けられることを確認）。
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


def article_dir(out_dir: Path, journal, meta) -> Path:
    aid = meta.article_id(journal)
    return out_dir / journal.journal_id / (meta.volume or "0") / (meta.issue or "0") / aid


def write_package(out_dir: Path, journal, meta, xml_bytes: bytes, pdf_path=None):
    """XML と（あれば）PDF を所定の位置に置き、ZIP を作る。画像は images.export_images で Graphics/ に出力済みとする。"""
    adir = article_dir(out_dir, journal, meta)
    adir.mkdir(parents=True, exist_ok=True)
    aid = meta.article_id(journal)
    (adir / f"{aid}.xml").write_bytes(xml_bytes)
    has_pdf = False
    if pdf_path:
        shutil.copyfile(pdf_path, adir / f"{aid}.pdf")
        has_pdf = True
    return make_zip(out_dir, journal, meta), adir, has_pdf


def make_zip(out_dir: Path, journal, meta) -> Path:
    """フォルダ構成（{資料コード}/…）を ZIP にする。利用者が後から画像を入れたとき（pipeline.add_images）にも作り直す。"""
    zpath = out_dir / f"{journal.journal_id}_{meta.article_id(journal)}.zip"
    root = out_dir / journal.journal_id
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(out_dir).as_posix())
    return zpath
