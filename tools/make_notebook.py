"""Colab 用ノートブック notebooks/JASME_docx_to_JSTAGE_XML.ipynb を生成する。

  python tools/make_notebook.py

ノートブックを Colab 上で直接編集して GitHub に保存してもよいが、その場合はこのスクリプトにも同じ変更を反映すること。
"""
import json
import re
from pathlib import Path

REPO = "thjpme/jstgxmlcng_JASME"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "notebooks" / "JASME_docx_to_JSTAGE_XML.ipynb"
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "src" / "jasme_jats" / "__init__.py").read_text()).group(1)
VERSION_NOTE = "（試用版。正式版は 1.0 から）" if VERSION.startswith("0.") else ""


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)}


# Colab ではどのセルの ▶ も押せてしまうので、各手順の最初で前の手順が済んでいるかを確かめる。
# 済んだ手順は変数 DONE に記録し、ある手順をやり直したら、それより後の手順は「未実行」に戻す。
GUARD = """_need = [n for n in (NEED) if n not in globals().get("DONE", set())]
if _need:
    raise SystemExit("先に手順 " + "・".join(map(str, _need)) + " を実行してください（上から順に ▶ を押します。"
                     "前の手順をやり直したときは、その後の手順もやり直してください）。")
"""


def guard(*steps):
    return GUARD.replace("NEED", ", ".join(map(str, steps)) + ",")


def mark(step):
    return f'DONE = {{n for n in globals().get("DONE", set()) if n < {step}}} | {{{step}}}\n'


def code(text, form=True):
    meta = {"cellView": "form"} if form else {}
    return {"cell_type": "code", "metadata": meta, "execution_count": None, "outputs": [],
            "source": text.strip("\n").splitlines(keepends=True)}


cells = [
    md(f"""
# 論文 docx → J-STAGE 全文 XML 変換（全国数学教育学会誌『数学教育学研究』）

**ツールの版: {VERSION}**{VERSION_NOTE}　… 手順 1 を実行すると、実際に読み込まれた版（とコミット ID）も表示されます。

このノートブックは、テンプレートで作成された論文の Word ファイル（.docx）を、J-STAGE の全文 XML（JATS 1.1）に変換します。
パソコンに何かをインストールする必要はありません。**上から順に、各セルの左の ▶ ボタンを押して実行してください。**
前の手順を実行せずに後の手順の ▶ を押すと、「先に手順 ○ を実行してください」と表示されて止まります。

| 手順 | 内容 |
|---|---|
| 1 | 準備（最初に 1 回だけ。▶ を押したら、終わるのを待たずに手順 2 の ▶ を押しておくと、準備の後に続けて実行されます） |
| 2 | 論文の docx と PDF をアップロード（ボタンが別々に出ます） |
| 3 | 書誌情報（巻・号・ページ・日付）を入力 |
| 4 | AI による補完の方法を選ぶ |
| 5 | 変換を実行（結果のレポートが表示されます） |
| 6 | （手動モードのときだけ）AI の回答を貼り付けて再変換 |
| 7 | 結果をダウンロード |

- 本文の文字は 1 文字も変えません。変換後に、docx と XML の文字を 1 文字ずつ照合して確かめます（レポートの「文字の不変性チェック」）。
- アップロードしたファイルは、このノートブックを閉じる（ランタイムが切れる）と Google のサーバーから消えます。
- 「API で自動実行」を選ぶと、論文の本文が Anthropic 社の Claude API に送信されます。

ソースコードと説明書: https://github.com/{REPO}
"""),
    code(f"""
#@title 1. 準備（最初に 1 回だけ。1 分ほどかかります）
#@markdown 図が Word の図形（EMF/WMF 形式）で貼られている論文では、画像の変換に LibreOffice を使います。チェックを入れると LibreOffice を**裏で**インストールします（数分かかりますが、終わるのを待たずに手順 2 以降へ進めます。手順 5 の変換は、インストールが終わってから始まります）。
CONVERT_EMF = True  #@param {{type:"boolean"}}
#@markdown 開発者向け: 開発中の版を試すときだけチェックを入れます（実行するとブランチ名の入力欄が出ます）。
USE_DEV_VERSION = False  #@param {{type:"boolean"}}

import shutil, subprocess, sys
# このランタイムで一度ツールを使っていると、古い版がメモリに残ったままになる（入れ直しても反映されない）
loaded_before = "jasme_jats" in sys.modules
BRANCH = "main"
if USE_DEV_VERSION:
    BRANCH = input("開発版のブランチ名を入力して Enter を押してください: ").strip()
    if not BRANCH:
        raise SystemExit("ブランチ名が入力されていません。開発版を使わないときは、チェックを外して実行してください。")
url = f"git+https://github.com/{REPO}.git@{{BRANCH}}"
for args in (["jasme-jats[ai,images] @ " + url],                          # ツールと必要なライブラリ
             ["--force-reinstall", "--no-deps", "jasme-jats @ " + url]):  # ツール本体は毎回最新に入れ直す
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", *args], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:])
        raise SystemExit("ツールのインストールに失敗しました。" + ("ブランチ名を確認してください。" if USE_DEV_VERSION else
                                                                  "しばらくしてからもう一度実行してください。"))
if loaded_before:
    raise SystemExit("ツールを最新の版に入れ替えましたが、このランタイムには前の版が読み込まれたままです。"
                     "メニューの「ランタイム」→「セッションを再起動」（表示によっては「ランタイムを再起動」）を選んでから、"
                     "手順 1 からもう一度実行してください。")
# LibreOffice はインストールに数分かかるので裏で入れる（手順 5 で終わるのを待つ）
LO_LOG = "/content/libreoffice_install.log"
if CONVERT_EMF and not (shutil.which("soffice") or shutil.which("libreoffice")):
    if globals().get("LO_PROC") is None or LO_PROC.poll() is not None:
        LO_PROC = subprocess.Popen("apt-get -qq update && (apt-get -qq install -y --no-install-recommends "
                                   "libreoffice-draw-nogui || apt-get -qq install -y libreoffice-draw)",
                                   shell=True, stdout=open(LO_LOG, "w"), stderr=subprocess.STDOUT)
# 版の表示は別のプロセスで行う（ここで読み込むと、次に手順 1 を実行したときに「前の版が残っている」扱いになるため）
ver = subprocess.run([sys.executable, "-c", "from jasme_jats.pipeline import tool_version; print(tool_version())"],
                     capture_output=True, text=True).stdout.strip()
print("準備ができました。ツールの版:", ver)
if USE_DEV_VERSION:
    print("※ 開発版（ブランチ", BRANCH, "）を使っています。")
elif ver and not ver.startswith("{VERSION}"):
    print("※ このノートブックの説明は版 {VERSION} のものです。ノートブックを開き直してください。")
if globals().get("LO_PROC") is not None and LO_PROC.poll() is None:
    print("LibreOffice を裏でインストールしています（数分）。終わるのを待たずに手順 2 へ進んでください。")
""" + "DONE = {1}\n"),
    code("""
#@title 2. 論文の docx と PDF をアップロード
#@markdown 実行すると、まず **docx 用**の「ファイル選択」ボタンが出ます。docx を選ぶと、続けて **PDF 用**の「ファイル選択」ボタンが出ます。
#@markdown J-STAGE に登載する PDF がまだなければ、下のチェックを外してから実行してください（PDF 用のボタンは出ません。後で jasme.zip に入れることもできます）。
UPLOAD_PDF = True  #@param {type:"boolean"}
""" + guard(1) + """
from pathlib import Path
from google.colab import files

WORK = Path("/content/jasme_work")
INPUT = WORK / "input"
INPUT.mkdir(parents=True, exist_ok=True)


def upload(what, ext):
    print(f"▼ {what}（{ext}）を選んでください")
    paths = []
    for name, data in files.upload().items():
        if not name.lower().endswith(ext):
            print(f"  「{name}」は {ext} ではないので使いません")
            continue
        (INPUT / name).write_bytes(data)
        paths.append(INPUT / name)
    return paths


docx_files = upload("論文の Word ファイル", ".docx")
if not docx_files:
    raise SystemExit("docx ファイルが選ばれていません。もう一度この手順を実行してください。")
if len(docx_files) > 1:
    print("  docx が複数選ばれたため、最初の 1 つだけを使います")
docx_path = docx_files[0]
pdf_path = None
if UPLOAD_PDF:
    print()
    pdf_files = upload("J-STAGE に登載する PDF", ".pdf")
    pdf_path = pdf_files[0] if pdf_files else None
print()
print("論文:", docx_path.name)
print("PDF :", pdf_path.name if pdf_path else "（なし。J-STAGE への登載には PDF が必要です）")
""" + mark(2)),
    code("""
#@title 3. 書誌情報を入力
#@markdown **巻・号・ページ**（J-STAGE のフォルダ名・ファイル名と DOI に使います）
volume = ""  #@param {type:"string"}
issue = ""  #@param {type:"string"}
first_page = ""  #@param {type:"string"}
last_page = ""  #@param {type:"string"}
#@markdown **日付**（YYYY-MM-DD の形で。分からなければ空欄）
pub_date = ""  #@param {type:"string"}
jstage_release_date = ""  #@param {type:"string"}
received = ""  #@param {type:"string"}
accepted = ""  #@param {type:"string"}
#@markdown **その他**（DOI は空欄なら 10.24529/jasme.巻.号_開始ページ を使います）
doi = ""  #@param {type:"string"}
subject = "論文"  #@param {type:"string"}
corresponding_author = ""  #@param {type:"string"}
#@markdown corresponding_author: 責任著者が何番目の著者か（例: 1）。複数なら「1,2」。
""" + guard(1, 2) + """meta_input = {"volume": volume, "issue": issue, "fpage": first_page, "lpage": last_page,
              "pub_date": pub_date, "epub_date": jstage_release_date, "received": received,
              "accepted": accepted, "doi": doi, "subject_ja": subject, "corresp": corresponding_author}
print("入力しました。未入力の項目はレポートに表示されます。")
""" + mark(3)),
    code("""
#@title 4. AI による補完の方法を選ぶ
#@markdown - **使わない**: 機械的な変換だけを行います。
#@markdown - **API で自動実行**: Claude API を呼び出して、機械処理で取りこぼした引用・スタイルの誤り・画像の数式などを補完します。左の 🔑（シークレット）に名前 `ANTHROPIC_API_KEY` で API キーを登録し、「ノートブックからのアクセス」をオンにしてください（API の利用料がかかります）。
#@markdown - **手動**: AI への依頼文を作ります。claude.ai などのチャットに貼り付け、返ってきた回答を手順 6 で貼り戻します（API キー不要）。
AI_MODE = "使わない"  #@param ["使わない", "API で自動実行", "手動（チャットに貼り付け）"]
MODEL = "claude-opus-5-5"  #@param {type:"string"}
#@markdown 図表番号（「図1」）を J-STAGE の <label> 要素に分けるか（分けると番号とタイトルの間の空白 1 文字を落とします。既定は分けない）
SPLIT_LABELS = False  #@param {type:"boolean"}
""" + guard(1, 2, 3) + """AI = {"使わない": "none", "API で自動実行": "api", "手動（チャットに貼り付け）": "manual"}[AI_MODE]
print("AI による補完:", AI_MODE)
""" + mark(4)),
    code("""
#@title 5. 変換を実行
""" + guard(1, 2, 3, 4) + """import shutil
from IPython.display import HTML, Markdown, display
from jasme_jats.colab import error_box, prompt_box
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert

api_key = None
if AI == "api":
    from google.colab import userdata
    try:
        api_key = userdata.get("ANTHROPIC_API_KEY")
    except Exception as e:
        raise SystemExit(f"シークレット ANTHROPIC_API_KEY を読めませんでした: {e}")

if CONVERT_EMF and globals().get("LO_PROC") is not None:
    if LO_PROC.poll() is None:
        print("LibreOffice のインストールが終わるのを待っています（EMF/WMF の図の変換に使います）…", flush=True)
        LO_PROC.wait()
    if not (shutil.which("soffice") or shutil.which("libreoffice")):
        print("※ LibreOffice をインストールできませんでした。EMF/WMF の図は変換されません（レポート 9 章）。記録:", LO_LOG)

OUT = WORK / "output"
shutil.rmtree(OUT, ignore_errors=True)
journal = JournalConfig.load()
meta = ArticleMeta.from_dict(meta_input)
res = convert(docx_path, meta, journal, Options(out_dir=OUT, ai_mode=AI, ai_model=MODEL, ai_api_key=api_key,
                                              pdf_path=pdf_path, split_labels=SPLIT_LABELS))
fid = res.fidelity
print("文字の不変性チェック:", fid.summary(), f"（段落 {fid.units} 件中 {fid.mapped} 件を出力、{len(fid.excluded)} 件は除外）")
print("最終出力の再チェック:", "合格" if fid.final_ok else "不合格")
print("DTD 検証:", "合格" if res.dtd_valid else "不合格")
print("J-STAGE のアップロード時チェック:", "問題なし" if not res.jstage_issues else f"要対応 {len(res.jstage_issues)} 件")
for mid, msg in res.jstage_issues:
    print("  ", mid, msg)
manual_prompt = None
if AI == "manual" and res.prompt_path:
    # 依頼文は、レポートの前に目立つ枠で出し、レポートの後ろにも同じものをコピーできる枠を出す
    attach = OUT / "AI添付画像"
    image_names = sorted(p.name for p in attach.iterdir()) if attach.exists() else []
    for n in image_names:
        files.download(str(attach / n))
    manual_prompt = res.prompt_path.read_text(encoding="utf-8")
    display(HTML(prompt_box(manual_prompt, image_names)))
if res.ai.error:
    display(HTML(error_box("AI による補完ができませんでした", res.ai.error)))
display(Markdown(res.report_path.read_text(encoding="utf-8")))
if manual_prompt:
    display(HTML(prompt_box(manual_prompt, compact=True)))
""" + mark(5)),
    md("""
### 6.（手動モードのときだけ）AI の回答を貼り付けて再変換

チャットから返ってきた回答は、`json` と書かれたコードブロック（灰色の枠）1 つのはずです。枠の右上の**コピーボタン**でコピーし、
下のセルの `r'''` と `'''` の間に貼り付けてから ▶ を押してください（コードブロックの外の文章が混じらず、中身がそのままコピーされます）。

- 回答がコードブロックになっていない、またはアーティファクト（別の画面）として返ってきたときは、チャットで
  「回答の書き方に従って、```json のコードブロック 1 つで出し直してください」と頼んでください。
- 読めなかったときは、何行目のどこが読めないかが表示されます。
"""),
    code("""
AI_RESPONSE = r'''
ここに AI の回答を貼り付ける
'''

""" + guard(1, 2, 3, 4, 5) + """if AI != "manual":
    raise SystemExit("この手順は手動モードのときだけ使います。手順 4 で「手動（チャットに貼り付け）」を選び、手順 5 からやり直してください。")
if not AI_RESPONSE.strip() or "ここに AI の回答を貼り付ける" in AI_RESPONSE:
    raise SystemExit("AI の回答が貼り付けられていません。上の r''' と ''' の間に貼り付けてから実行してください。")
res = convert(docx_path, meta, journal, Options(out_dir=OUT, ai_mode="manual", ai_response=AI_RESPONSE,
                                              pdf_path=pdf_path, split_labels=SPLIT_LABELS))
fid = res.fidelity
print("文字の不変性チェック:", fid.summary(), "/ 最終出力の再チェック:", "合格" if fid.final_ok else "不合格",
      "/ DTD 検証:", "合格" if res.dtd_valid else "不合格",
      "/ J-STAGE のアップロード時チェック:", "問題なし" if not res.jstage_issues else f"要対応 {len(res.jstage_issues)} 件")
if res.ai.error:
    display(HTML(error_box("貼り付けた回答を読み込めませんでした（AI による補完は反映されていません）", res.ai.error)))
display(Markdown(res.report_path.read_text(encoding="utf-8")))
""", form=False),
    code("""
#@title 7. 結果をダウンロード
#@markdown 「変換結果.zip」の中に、J-STAGE にアップロードする jasme.zip、XML、変換レポートが入っています。
""" + guard(1, 2, 3, 4, 5) + """archive = shutil.make_archive(str(WORK / "変換結果"), "zip", OUT)
files.download(archive)
"""),
]



def render() -> str:
    nb = {
        "nbformat": 4, "nbformat_minor": 0,
        "metadata": {"colab": {"provenance": [], "toc_visible": True},
                     "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}},
        "cells": cells,
    }
    return json.dumps(nb, ensure_ascii=False, indent=1) + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print("written:", OUT)
