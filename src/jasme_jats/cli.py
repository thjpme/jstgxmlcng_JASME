"""コマンドラインの入口。

  python -m jasme_jats 論文.docx --meta 書誌情報.toml --out 出力フォルダ [--ai api|manual|none]
                       [--ai-provider claude|openai|gemini|sakana] [--ai-model モデル名] [--pdf 記事.pdf [--route docx|pdf]]

書誌情報ファイル（TOML）の例は examples/meta_example.toml を参照。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .ai_assist import API_KEY_NAMES, DEFAULT_MODEL
from .config import ArticleMeta, JournalConfig
from .pipeline import AIRequiredError, Options, add_images, convert
from .report import (FIGURE_BODY_ACTION, LOST_IMAGES_ACTION, PROVISIONAL, figure_issue_labels, graphics_dir,
                     images_to_prepare, lost_image_label, pdf_summary, provisional_exclusions, upload_issues)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jasme-jats", description="Word（docx）の論文を J-STAGE 全文 XML（JATS 1.1）に変換する")
    ap.add_argument("docx", type=Path, help="変換する論文（.docx）")
    ap.add_argument("--meta", type=Path, help="書誌情報（巻・号・頁・日付など）の TOML ファイル")
    ap.add_argument("--out", type=Path, default=Path("output"), help="出力フォルダ（既定: output）")
    ap.add_argument("--config", type=Path, help="雑誌の設定ファイル（既定: 同梱の jasme.toml）")
    ap.add_argument("--split-labels", choices=["yes", "no"], help="図表番号を <label> に分けるか（既定: 設定ファイルに従う）")
    ap.add_argument("--ai", choices=["none", "api", "manual"], default="none", help="AI による補完の方法")
    ap.add_argument("--ai-provider", choices=["claude", "openai", "gemini", "sakana"], default="claude",
                    help="API モードで使う AI（既定・推奨: claude。openai は ChatGPT、gemini は Gemini、sakana は Sakana AI）。"
                         "API キーは環境変数 ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY（または GOOGLE_API_KEY）/ "
                         "SAKANA_API_KEY")
    ap.add_argument("--ai-model",
                    help=f"API モードで使うモデル。claude の既定は {DEFAULT_MODEL}（auto で使える最新の Opus。指定したモデルが"
                         "使えなければ最新の Opus に切り替える）。claude 以外では必ず指定する（Claude Opus と同等以上のモデルを推奨）")
    ap.add_argument("--ai-response", type=Path, help="手動モード: AI の回答（JSON）を保存したファイル")
    ap.add_argument("--pdf", type=Path, help="記事の PDF（J-STAGE への登載に必須。指定すると ZIP に入れる。"
                                          "指定しなければ、記事フォルダに前の変換の PDF が残っていても ZIP に入れない）")
    ap.add_argument("--route", choices=["docx", "pdf"],
                    help="作り方。既定は --pdf があれば pdf、なければ docx。pdf: --pdf の出版版 PDF に合わせて直した docx"
                         "（Word の変更履歴つき）を出力フォルダに作り、それを変換する。docx: docx から作る（docx の文字は 1 文字も"
                         "変えない。--pdf があれば照合してレポートに載せるだけ）")
    ap.add_argument("--no-metafile-conversion", action="store_true", help="EMF/WMF 画像の変換を行わない")
    ap.add_argument("--images", type=Path,
                    help="画像を用意できなかった図（Word の図形で描かれた図など）の画像を入れたフォルダ。出力のファイル名"
                         "（25_77_01.png など。拡張子は .png・.jpg・.pdf などでもよい）と同じ名前の画像を Graphics/ に入れる")
    a = ap.parse_args(argv)
    if a.ai == "api" and a.ai_provider != "claude" and not a.ai_model:
        ap.error(f"--ai-provider {a.ai_provider} では --ai-model でモデル名を指定してください"
                 "（Claude Opus と同等以上のモデルを推奨）")
    if a.route is None:
        a.route = "pdf" if a.pdf else "docx"
    if a.route == "pdf" and not a.pdf:
        ap.error("--route pdf（出版版 PDF に合わせてから作る）では、--pdf で記事の PDF を指定してください")
    api_key = next((os.environ[k] for k in API_KEY_NAMES[a.ai_provider] if os.environ.get(k)), None)

    journal = JournalConfig.load(a.config)
    try:
        meta = ArticleMeta.load(a.meta) if a.meta else ArticleMeta()
    except ValueError as e:         # 巻・号・ページに英数字以外がある、日付を読めない、TOML の書き方の誤りなど
        print(f"書誌情報（{a.meta}）を確認してください: {e}", file=sys.stderr)
        return 2
    for note in meta.input_notes:   # 全角の数字を半角にしたなど
        print(f"※ 書誌情報: {note}")
    opts = Options(out_dir=a.out, split_labels=None if a.split_labels is None else a.split_labels == "yes",
                   ai_mode=a.ai, ai_provider=a.ai_provider, ai_model=a.ai_model or DEFAULT_MODEL, ai_api_key=api_key,
                   ai_response=a.ai_response.read_text(encoding="utf-8") if a.ai_response else None,
                   pdf_path=a.pdf, route=a.route, convert_metafiles=not a.no_metafile_conversion)
    try:
        res = convert(a.docx, meta, journal, opts)
    except AIRequiredError as e:
        print(e, file=sys.stderr)
        return 2
    fid = res.fidelity
    print(f"文字の不変性チェック: {fid.summary()}（段落 {fid.units} 件中 {fid.mapped} 件を出力、{len(fid.excluded)} 件は除外）")
    print(f"最終出力の再チェック: {'合格' if fid.final_ok else '不合格'}")
    print(f"DTD 検証: {'合格' if res.dtd_valid else '不合格'}")
    issues = upload_issues(res)     # XML で判定したものと、ZIP を読み直して見つけたもの
    print(f"J-STAGE のアップロード時チェック: {'問題なし' if not issues else f'要対応 {len(issues)} 件'}")
    for mid, msg in issues:
        print(f"  {mid}: {msg}")
    if res.pdf_check is not None:
        print(f"出版版 PDF との照合: {pdf_summary(res)}")
    if res.docx_fix is not None:
        print(f"PDF に合わせて直した docx（変更履歴つき）: {res.docx_fix.path}")
    print(f"XML: {res.xml_path}")
    print(f"ZIP: {res.zip_path}")
    print(f"レポート: {res.report_path}")
    if res.ai_report_path:
        print(f"AI 判断一覧: {res.ai_report_path}")
    if res.prompt_path:
        print(f"AI 依頼文: {res.prompt_path}")
    if res.ai.error:
        print(f"AI: {res.ai.error}", file=sys.stderr)
    if res.ai.partial:
        print(f"要対応: AI の回答が途中で切れていました。{res.ai.partial}", file=sys.stderr)
    if a.images:
        try:
            added = add_images(res, user_images_in(a.images, images_to_prepare(res)))
        except ValueError as e:
            print(f"画像: {e}", file=sys.stderr)
            return 1
        if added:
            print(f"画像を入れて ZIP とレポートを作り直した: {', '.join(added)}")
    if res.not_zipped:        # add_images の後の値（ZIP を作り直すと計算し直す）
        print(f"※ 記事フォルダにあるが ZIP に入れなかったファイル {len(res.not_zipped)} 件（前の変換の残りか、手で置いたもの。"
              "PDF は --pdf、画像は --images で指定し直すと入る。レポートの 10 章）: " + ", ".join(res.not_zipped))
    need = images_to_prepare(res)
    if need:
        print(f"要対応: 画像ファイルを用意できなかった図 {len(need)} 件。画像を作り、同じ名前でフォルダに入れて --images で"
              f"指定するか、ZIP の中の {graphics_dir(res)} に入れること（レポートの冒頭と 9 章）: " + ", ".join(f"{name}（{(cap[:20] + '…' if len(cap) > 20 else cap) or 'キャプションなし'}）" for name, cap, _ in need),
              file=sys.stderr)
    lost = res.lost_images
    if lost:
        print(f"要対応: XML に入らなかった画像 {len(lost)} 件（画像を出力できない引用文献・題目・著者名・所属の段落や、"
              f"出力しなかった段落の中にある。レポートの冒頭と 9 章）。{LOST_IMAGES_ACTION}\n"
              + "\n".join(f"  {lost_image_label(li)}: {li.reason}" for li in lost), file=sys.stderr)
    # 図の本体（画像・表）が見つからない図（表の文字は XML に入っているので、終了コードは変えない）
    labels = figure_issue_labels(res.plan)
    if labels:
        print(f"要対応: 図の本体（画像・表）が見つからない図 {len(labels)} 件（レポートの冒頭と 3 章）。{FIGURE_BODY_ACTION}\n"
              + "\n".join(f"  {x}" for x in labels), file=sys.stderr)
    # 文字だけのテキストボックスの段落・Word の文末脚注を XML に出力しなかったこと（暫定の知らせ。終了コードは変えない）
    for kind, rows in provisional_exclusions(res):
        what, detail, _ = PROVISIONAL[kind]
        print(f"要確認: {what.format(n=len(rows))}を、XML に出力していません（レポートの冒頭と 6 章）。{detail}", file=sys.stderr)
    # AI の回答を反映した後（API、または手動モードで回答あり）も位置を決められない図表が残っている
    ai_applied = res.ai.mode == "api" or (res.ai.mode == "manual" and a.ai_response)
    if ai_applied and res.plan.unplaced_floats:
        # 図表ごとに、キャプションと、XML の中の位置・ID（レポートの冒頭と同じ。pipeline の forced_floats）
        rows = res.forced_floats or [f"{fid}: {res.plan.float_place(fid)}" for fid in res.plan.unplaced_floats]
        print(f"要対応: 位置を決められなかった図表 {len(res.plan.unplaced_floats)} 件を、仮の位置（アンカー段落の後ろ、または"
              "本文の最後）に置きました。XML の中で手作業で正しい位置（Word で表示したときに、図の左上の直上にある本文の段落の後）"
              "に移してください（レポートの冒頭と 3 章）。\n" + "\n".join(f"  {x}" for x in rows), file=sys.stderr)
        return 1
    return 0 if res.ok and not lost else 1


def user_images_in(folder: Path, need) -> dict:
    """フォルダの中から、用意が必要な画像と同じ名前（拡張子は問わない）のファイルを探す。出力ファイル名 → パス。"""
    found = {}
    for name, _, _ in need:
        stem = name.rsplit(".", 1)[0]
        cands = sorted(p for p in folder.iterdir() if p.is_file() and p.stem == stem)
        if cands:
            found[name] = cands[0]
    return found


if __name__ == "__main__":
    sys.exit(main())
