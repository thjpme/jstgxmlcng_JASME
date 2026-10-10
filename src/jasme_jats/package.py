"""J-STAGE へのアップロード用のフォルダ構成と ZIP を作る。

J-STAGE『記事アップロードフォルダ構成（FULL-J）』に従う:
  {資料コード}/{巻}/{号}/{記事識別子}/{記事識別子}.xml
                                     /{記事識別子}.pdf      ← PDF は J-STAGE で必須（利用者が用意）
                                     /Graphics/{画像}
ZIP のファイル名は {資料コード}.zip。
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
    zpath = out_dir / f"{journal.journal_id}.zip"
    root = out_dir / journal.journal_id
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(out_dir).as_posix())
    return zpath, adir, has_pdf
