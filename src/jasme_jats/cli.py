"""コマンドラインの入口。

  python -m jasme_jats 論文.docx --meta 書誌情報.toml --out 出力フォルダ [--ai api|manual|none]

書誌情報ファイル（TOML）の例は examples/meta_example.toml を参照。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import ArticleMeta, JournalConfig
from .pipeline import Options, convert


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jasme-jats", description="Word（docx）の論文を J-STAGE 全文 XML（JATS 1.1）に変換する")
    ap.add_argument("docx", type=Path, help="変換する論文（.docx）")
    ap.add_argument("--meta", type=Path, help="書誌情報（巻・号・頁・日付など）の TOML ファイル")
    ap.add_argument("--out", type=Path, default=Path("output"), help="出力フォルダ（既定: output）")
    ap.add_argument("--config", type=Path, help="雑誌の設定ファイル（既定: 同梱の jasme.toml）")
    ap.add_argument("--split-labels", choices=["yes", "no"], help="図表番号を <label> に分けるか（既定: 設定ファイルに従う）")
    ap.add_argument("--ai", choices=["none", "api", "manual"], default="none", help="AI による補完の方法")
    ap.add_argument("--ai-model", default="claude-opus-5-5", help="API モードで使うモデル")
    ap.add_argument("--ai-response", type=Path, help="手動モード: AI の回答（JSON）を保存したファイル")
    ap.add_argument("--pdf", type=Path, help="記事の PDF（J-STAGE への登載に必須。指定すると ZIP に入れる）")
    ap.add_argument("--no-metafile-conversion", action="store_true", help="EMF/WMF 画像の変換を行わない")
    a = ap.parse_args(argv)

    journal = JournalConfig.load(a.config)
    meta = ArticleMeta.load(a.meta) if a.meta else ArticleMeta()
    opts = Options(out_dir=a.out, split_labels=None if a.split_labels is None else a.split_labels == "yes",
                   ai_mode=a.ai, ai_model=a.ai_model, ai_api_key=os.environ.get("ANTHROPIC_API_KEY"),
                   ai_response=a.ai_response.read_text(encoding="utf-8") if a.ai_response else None,
                   pdf_path=a.pdf, convert_metafiles=not a.no_metafile_conversion)
    res = convert(a.docx, meta, journal, opts)
    fid = res.fidelity
    print(f"文字の不変性チェック: {fid.summary()}（段落 {fid.units} 件中 {fid.mapped} 件を出力、{len(fid.excluded)} 件は除外）")
    print(f"最終出力の再チェック: {'合格' if fid.final_ok else '不合格'}")
    print(f"DTD 検証: {'合格' if res.dtd_valid else '不合格'}")
    print(f"XML: {res.xml_path}")
    print(f"ZIP: {res.zip_path}")
    print(f"レポート: {res.report_path}")
    if res.ai_report_path:
        print(f"AI 判断一覧: {res.ai_report_path}")
    if res.prompt_path:
        print(f"AI 依頼文: {res.prompt_path}")
    if res.ai.error:
        print(f"AI: {res.ai.error}", file=sys.stderr)
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
