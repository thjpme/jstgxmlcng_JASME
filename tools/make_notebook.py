"""Colab 用ノートブック notebooks/JASME_docx_to_JSTAGE_XML.ipynb を生成する。

  python tools/make_notebook.py

ノートブックを Colab 上で直接編集して GitHub に保存してもよいが、その場合はこのスクリプトにも同じ変更を反映すること。
"""
import json
from pathlib import Path

REPO = "thjpme/jstgxmlcng_JASME"
OUT = Path(__file__).resolve().parent.parent / "notebooks" / "JASME_docx_to_JSTAGE_XML.ipynb"


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)}


def code(text, form=True):
    meta = {"cellView": "form"} if form else {}
    return {"cell_type": "code", "metadata": meta, "execution_count": None, "outputs": [],
            "source": text.strip("\n").splitlines(keepends=True)}


cells = [
    md(f"""
# 論文 docx → J-STAGE 全文 XML 変換（全国数学教育学会誌『数学教育学研究』）

このノートブックは、テンプレートで作成された論文の Word ファイル（.docx）を、J-STAGE の全文 XML（JATS 1.1）に変換します。
パソコンに何かをインストールする必要はありません。**上から順に、各セルの左の ▶ ボタンを押して実行してください。**

| 手順 | 内容 |
|---|---|
| 1 | 準備（最初に 1 回だけ） |
| 2 | 論文の docx（と PDF）をアップロード |
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
#@title 1. 準備（最初に 1 回だけ。1〜3 分かかります）
#@markdown 図が Word の図形（EMF/WMF 形式）で貼られている論文では、画像の変換に LibreOffice を使います。チェックを入れると追加でインストールします（数分かかります）。
CONVERT_EMF = True  #@param {{type:"boolean"}}
#@markdown 通常は変更不要です（開発中の版を試すときだけ、ブランチ名を書き換えます）。
BRANCH = "main"  #@param {{type:"string"}}

import subprocess, sys
r = subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                    f"jasme-jats[ai,images] @ git+https://github.com/{REPO}.git@{{BRANCH}}"],
                   capture_output=True, text=True)
if r.returncode != 0:
    print(r.stderr[-2000:])
    raise SystemExit("ツールのインストールに失敗しました。BRANCH の値を確認してください。")
if CONVERT_EMF:
    subprocess.run("apt-get -qq update > /dev/null && (apt-get -qq install -y --no-install-recommends "
                   "libreoffice-draw-nogui > /dev/null || apt-get -qq install -y libreoffice-draw > /dev/null)",
                   shell=True)
import jasme_jats
print("準備ができました（jasme-jats", jasme_jats.__version__, "）")
"""),
    code("""
#@title 2. 論文の docx（と PDF）をアップロード
#@markdown 実行すると「ファイル選択」ボタンが出ます。docx を選んでください。J-STAGE に登載する PDF があれば、同時に選ぶと ZIP に同梱します。
from pathlib import Path
from google.colab import files

WORK = Path("/content/jasme_work")
(WORK / "input").mkdir(parents=True, exist_ok=True)
uploaded = files.upload()
for name, data in uploaded.items():
    (WORK / "input" / name).write_bytes(data)
docx_files = [WORK / "input" / n for n in uploaded if n.lower().endswith(".docx")]
pdf_files = [WORK / "input" / n for n in uploaded if n.lower().endswith(".pdf")]
if not docx_files:
    raise SystemExit("docx ファイルが選ばれていません。もう一度実行してください。")
docx_path = docx_files[0]
pdf_path = pdf_files[0] if pdf_files else None
print("論文:", docx_path.name)
print("PDF :", pdf_path.name if pdf_path else "（なし。J-STAGE への登載には PDF が必要です）")
"""),
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
meta_input = {"volume": volume, "issue": issue, "fpage": first_page, "lpage": last_page,
              "pub_date": pub_date, "epub_date": jstage_release_date, "received": received,
              "accepted": accepted, "doi": doi, "subject_ja": subject, "corresp": corresponding_author}
print("入力しました。未入力の項目はレポートに表示されます。")
"""),
    code("""
#@title 4. AI による補完の方法を選ぶ
#@markdown - **使わない**: 機械的な変換だけを行います。
#@markdown - **API で自動実行**: Claude API を呼び出して、機械処理で取りこぼした引用・スタイルの誤り・画像の数式などを補完します。左の 🔑（シークレット）に名前 `ANTHROPIC_API_KEY` で API キーを登録し、「ノートブックからのアクセス」をオンにしてください（API の利用料がかかります）。
#@markdown - **手動**: AI への依頼文を作ります。claude.ai などのチャットに貼り付け、返ってきた回答を手順 6 で貼り戻します（API キー不要）。
AI_MODE = "使わない"  #@param ["使わない", "API で自動実行", "手動（チャットに貼り付け）"]
MODEL = "claude-opus-5-5"  #@param {type:"string"}
#@markdown 図表番号（「図1」）を J-STAGE の <label> 要素に分けるか（分けると番号とタイトルの間の空白 1 文字を落とします。既定は分けない）
SPLIT_LABELS = False  #@param {type:"boolean"}
AI = {"使わない": "none", "API で自動実行": "api", "手動（チャットに貼り付け）": "manual"}[AI_MODE]
print("AI による補完:", AI_MODE)
"""),
    code("""
#@title 5. 変換を実行
import shutil
from IPython.display import Markdown, display
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert

api_key = None
if AI == "api":
    from google.colab import userdata
    try:
        api_key = userdata.get("ANTHROPIC_API_KEY")
    except Exception as e:
        raise SystemExit(f"シークレット ANTHROPIC_API_KEY を読めませんでした: {e}")

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
if res.ai.error:
    print("AI:", res.ai.error)
if AI == "manual" and res.prompt_path:
    print()
    print("【手動モード】下の依頼文をすべてコピーして claude.ai などのチャットに貼り付けてください。")
    attach = OUT / "AI添付画像"
    if attach.exists():
        print("画像も添付してください（次のファイルをダウンロードします）:", ", ".join(p.name for p in attach.iterdir()))
        for p in attach.iterdir():
            files.download(str(p))
    import ipywidgets as widgets
    display(widgets.Textarea(value=res.prompt_path.read_text(encoding="utf-8"),
                             layout=widgets.Layout(width="100%", height="300px")))
display(Markdown(res.report_path.read_text(encoding="utf-8")))
"""),
    md("""
### 6.（手動モードのときだけ）AI の回答を貼り付けて再変換

チャットから返ってきた回答（`{"operations": [...` で始まる JSON）を、下のセルの `r'''` と `'''` の間に貼り付けてから ▶ を押してください。
"""),
    code("""
AI_RESPONSE = r'''
ここに AI の回答を貼り付ける
'''

res = convert(docx_path, meta, journal, Options(out_dir=OUT, ai_mode="manual", ai_response=AI_RESPONSE,
                                              pdf_path=pdf_path, split_labels=SPLIT_LABELS))
fid = res.fidelity
print("文字の不変性チェック:", fid.summary(), "/ 最終出力の再チェック:", "合格" if fid.final_ok else "不合格",
      "/ DTD 検証:", "合格" if res.dtd_valid else "不合格")
if res.ai.error:
    print("AI:", res.ai.error)
display(Markdown(res.report_path.read_text(encoding="utf-8")))
""", form=False),
    code("""
#@title 7. 結果をダウンロード
#@markdown 「変換結果.zip」の中に、J-STAGE にアップロードする jasme.zip、XML、変換レポートが入っています。
archive = shutil.make_archive(str(WORK / "変換結果"), "zip", OUT)
files.download(archive)
"""),
]

nb = {
    "nbformat": 4, "nbformat_minor": 0,
    "metadata": {"colab": {"provenance": [], "toc_visible": True},
                 "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}},
    "cells": cells,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("written:", OUT)
