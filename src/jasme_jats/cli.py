"""コマンドラインの入口。

  python -m jasme_jats 論文.docx --meta 書誌情報.toml --out 出力フォルダ [--ai api|manual|none]
                       [--ai-provider claude|openai|gemini|sakana] [--ai-model モデル名] [--pdf 記事.pdf [--route docx|pdf]]
                       [--ai manual --ai-response 回答のファイル]

書誌情報ファイル（TOML）の例は examples/meta_example.toml を参照。

終了コード: 0 は要対応も残っている必須の手順もなし、1 はどちらかあり（report.blocking。report.actions の「要対応」と、残っている必須の手順。
一覧は標準エラーに出す。--meta がない・画像が足りない、なども 1。手動モードで AI の回答をまだ指定していないのは推奨の手順なので 0）、2 は変換を中止した（書誌情報の誤り、AI による補完が
必要な原稿を --ai none で変換したとき、原稿の構造〈同じ種類の後付けの見出しが 2 つ・著者名の付かない所属。K1・K2〉を直す必要が
あるとき、--images の画像を読めないとき。引数の誤り〈指定したファイル・フォルダがない、
--ai manual でないのに --ai-response を指定した、など〉も argparse が 2 で止める）。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .ai_assist import API_KEY_NAMES, DEFAULT_MODEL
from .colab import step_text
from .config import ArticleMeta, JournalConfig
from .images import match_names
from .pipeline import AIRequiredError, Options, StructureConflictError, add_images, convert
from .report import actions, image_rows, images_action, pdf_summary, upload_issues


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
    ap.add_argument("--ai-response", type=Path,
                    help="手動モード（--ai manual と一緒に指定する）: AI の回答（JSON）を保存したファイル")
    ap.add_argument("--pdf", type=Path, help="記事の PDF（J-STAGE への登載に必須。指定すると ZIP に入れる。"
                                          "指定しなければ、記事フォルダに前の変換の PDF が残っていても ZIP に入れない）")
    ap.add_argument("--route", choices=["docx", "pdf"],
                    help="作り方。既定は --pdf があれば pdf、なければ docx。pdf: docx から作り、--pdf の出版版 PDF で補う"
                         "（著者校正の直しと、全角・半角・ダッシュ・引用符などの組版の違いを PDF から補った docx〈Word の"
                         "変更履歴つき〉を出力フォルダに作り、それを変換する）。docx: docx から作る（docx の文字は 1 文字も"
                         "変えない。--pdf があれば照合してレポートに載せるだけ）")
    ap.add_argument("--images", type=Path,
                    help="図・表の画像を入れたフォルダ（論文ごとに分ける）。ファイル名は fig03.png・図3.png・29_55_fig03.png のどれでもよい"
                         "（PNG・JPEG・GIF）。名前の合う画像を、中身を変えずに Graphics/ に入れる")
    ap.add_argument("--no-image", action="append", default=[], metavar="名前",
                    help="画像を入れない、キャプションのない画像の置き場所の名前（img3fa9c2 など。出版版 PDF で見て、ほかの図に写っている・"
                         "飾りだけ、のとき）。複数あるときは繰り返し指定する。図・表の画像は入れないことにできない")
    a = ap.parse_args(argv)
    if a.ai == "api" and a.ai_provider != "claude" and not a.ai_model:
        ap.error(f"--ai-provider {a.ai_provider} では --ai-model でモデル名を指定してください"
                 "（Claude Opus と同等以上のモデルを推奨）")
    if a.ai_response is not None and a.ai != "manual":
        # 回答のファイルは --ai manual のときだけ読む（--ai の既定は none）。黙って無視すると、AI の回答を反映していない結果になる
        ap.error("--ai-response（AI の回答のファイル）は --ai manual のときだけ読みます"
                 f"（今は --ai {a.ai}）。AI の回答を反映するときは --ai manual を一緒に指定してください")
    for opt, path in (("変換する docx", a.docx), ("--meta", a.meta), ("--pdf", a.pdf), ("--ai-response", a.ai_response)):
        # 通常のファイルでなくても読めるもの（/dev/stdin・プロセス置換の /dev/fd/NN など）は通す。フォルダは誤り
        if path is not None and (not path.exists() or path.is_dir()):
            ap.error(f"{opt} のファイルが見つかりません: {path}")
    if a.images is not None and not a.images.is_dir():
        ap.error(f"--images のフォルダが見つかりません: {a.images}")
    if a.route is None:
        a.route = "pdf" if a.pdf else "docx"
    if a.route == "pdf" and not a.pdf:
        ap.error("--route pdf（docx から作り、出版版 PDF で補う）では、--pdf で記事の PDF を指定してください")
    api_key = next((os.environ[k] for k in API_KEY_NAMES[a.ai_provider] if os.environ.get(k)), None)
    if a.ai == "api" and not api_key:
        ap.error(f"--ai api では API キーが必要です。環境変数 {' または '.join(API_KEY_NAMES[a.ai_provider])} に API キーを"
                 "設定してから実行してください（API キーがなければ --ai manual で依頼文を作れます）")

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
                   pdf_path=a.pdf, route=a.route)
    try:
        res = convert(a.docx, meta, journal, opts)
    except (AIRequiredError, StructureConflictError) as e:
        print(step_text(str(e), "cli"), file=sys.stderr)       # 画面の操作の目印をコマンドラインの指定に置き換える
        return 2
    fid = res.fidelity
    print(f"文字の不変性チェック: {fid.summary()}（段落 {fid.units} 件中 {fid.mapped} 件を出力、{len(fid.excluded)} 件は除外）")
    print(f"最終出力の再チェック: {'合格' if fid.final_ok else '不合格'}")
    if res.supplement is not None:
        print(f"補完の確かめ: {'合格' if res.supplement.ok else '不合格'}")
    print(f"DTD 検証: {'合格' if res.dtd_valid else '不合格'}")
    issues = upload_issues(res)     # XML で判定したものと、ZIP を読み直して見つけたもの
    print(f"J-STAGE のアップロード時チェック: {'問題なし' if not issues else f'要対応 {len(issues)} 件'}")
    for mid, msg in issues:
        print(f"  {mid}: {msg}")
    if res.pdf_check is not None:
        print(f"出版版 PDF との照合: {pdf_summary(res)}")
    if res.docx_fix is not None:
        print(f"PDF で補った docx（変更履歴つき）: {res.docx_fix.path}")
    print(f"XML: {res.xml_path}")
    print(f"ZIP: {res.zip_path}")
    print(f"レポート: {res.report_path}")
    if res.ai_report_path:
        print(f"AI 判断一覧: {res.ai_report_path}")
    if res.prompt_path:
        print(f"AI 依頼文: {res.prompt_path}")
    if a.images or a.no_image:
        try:
            supplied = images_in(a.images, res) if a.images else {}
            added = add_images(res, supplied, skip=a.no_image)
        except ValueError as e:
            print(f"画像: {e}", file=sys.stderr)
            return 2        # 画像を 1 枚も入れずに止める（ZIP とレポートは変換のときのまま）
        if added:
            print(f"画像を入れて ZIP とレポートを作り直した: {', '.join(added)}")
        if a.no_image:
            print(f"画像を入れないことにした（手順の「全部で」から除いた）: {', '.join(a.no_image)}")
    table = image_table(res)
    if table:
        print("\n".join(table))
        print(f"図の確かめの一覧: {res.check_path}")
    if res.not_zipped:        # add_images の後の値（ZIP を作り直すと計算し直す）
        print(f"※ 記事フォルダにあるが ZIP に入れなかったファイル {len(res.not_zipped)} 件（前の変換の残りか、手で置いたもの。"
              "PDF は --pdf、画像は --images で指定し直すと入る。レポートの 10 章）: " + ", ".join(res.not_zipped))
    # 要対応・要確認・手順（report.actions。レポートの冒頭・14 章、Colab の枠と同じもの）。画像を入れた後に調べる
    for act in actions(res):
        if act.cli:
            print(act.cli, file=sys.stderr)
    # 終了コード: 0 は要対応も残っている必須の手順もなし（要確認・推奨の手順だけなら 0）、1 はどちらかあり、2 は変換を中止した
    return 1 if res.needs_action else 0


def images_in(folder: Path, res) -> dict:
    """フォルダの画像を、ファイル名で置き場所に合わせる（images.match_names）。幹 → パス。

    受け付ける名前は fig03・図3・29_55_fig03 など（拡張子は問わない）。合う置き場所のないファイル、同じ置き場所に合う複数のファイルは
    標準エラーに出して続ける（別の記事の識別子の付いた名前も「合わない」名前）。隠しファイル（.で始まる名前）は見ない。
    """
    paths = {p.name: p for p in sorted(folder.iterdir()) if p.is_file() and not p.name.startswith(".")}
    rows = [row for row in image_rows(res) if row.kind != "optional"]
    found, unmatched, clashes = match_names(list(paths), rows, res.meta.article_id(res.journal))
    for name in unmatched:
        print(f"画像: 「{name}」に合う図がありません（fig03.png・図3.png・{res.meta.article_id(res.journal)}_fig03.png のような名前にします。"
              "ほかの記事の識別子が付いた名前は入れません）", file=sys.stderr)
    for key, names in clashes:
        print(f"画像: 同じ図（{key}）に合うファイルが複数あるので、どれも入れていません: {', '.join(names)}", file=sys.stderr)
    return {key: paths[name] for key, name in found.items()}


def image_table(res) -> list:
    """標準出力に出す図の画像の表の行（見出しは手順 images の progress、行は report.image_rows）。画像の要る図・表がなければ空。"""
    rows = [row for row in image_rows(res) if row.kind != "optional"]
    if not rows:
        return []
    act = images_action(res)
    out = ["図の画像" + (f"（{act.progress}）" if act is not None else "") + ":"]
    width = max(len(row.key) for row in rows)
    for row in rows:
        state = {"missing": "未", "skipped": "入れない"}.get(row.status) or f"入れた（{row.detail}）"
        out.append(f"  {row.key.ljust(width)}  {(row.label or '—').ljust(4)}  {state}")
    return out


if __name__ == "__main__":
    sys.exit(main())
