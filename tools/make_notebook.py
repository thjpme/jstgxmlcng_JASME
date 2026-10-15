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
try:
    import tomllib
except ModuleNotFoundError:   # Python 3.10
    import tomli as tomllib
with open(ROOT / "src" / "jasme_jats" / "data" / "jasme.toml", "rb") as _f:
    MANUSCRIPT_TYPES = tomllib.load(_f).get("manuscript_types", {})
TYPE_CHOICES = [f"{ja} / {en}" for ja, en in MANUSCRIPT_TYPES.items()] + ["その他"]
TYPE_PARAM = (f'manuscript_type = {json.dumps(TYPE_CHOICES[0], ensure_ascii=False)}  '
              f'#@param {json.dumps(TYPE_CHOICES, ensure_ascii=False)}\n')


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


# 手順 4 の直後に出す、API キーの詳しい説明（Colab のテキストセルで開閉できる）
API_HELP = '''<details>
<summary><b>API キーについての詳細（クリックで開きます）</b></summary>

<p>「API で自動実行」を使うときだけ必要です。手動モード（チャットに貼り付け）なら API キーは要りません。</p>
<p>1.〜5. は Claude（推奨）の場合の説明です。ChatGPT・Gemini・Sakana AI を使うときは 6. を見てください。</p>

<h4>1. API キーを作る（最初に 1 回だけ）</h4>
<ol>
<li>Claude Console（<a href="https://platform.claude.com/" target="_blank">https://platform.claude.com/</a>）にログインします。アカウントがなければ作成します。
API の料金は、claude.ai の有料プラン（Pro など）とは別にかかります。</li>
<li>「Settings → Billing」（<a href="https://platform.claude.com/settings/billing" target="_blank">https://platform.claude.com/settings/billing</a>）で、利用料（クレジット）を購入します。
同じ画面で、1 か月に使う金額の上限を設定できます。使いすぎを防ぐため、上限を設定しておくことをお勧めします。</li>
<li>「Settings → API keys」（<a href="https://platform.claude.com/settings/keys" target="_blank">https://platform.claude.com/settings/keys</a>）で <b>Create key</b> を押し、名前（例: <code>jasme-colab</code>）を付けて作成します。</li>
<li>表示されたキー（<code>sk-ant-</code> で始まる長い文字列）をコピーします。<b>キーが表示されるのはこのときだけです。</b>
控えずに閉じてしまったら、新しいキーを作り直してください。</li>
</ol>

<h4>2. Colab にキーを登録する（Google アカウントごとに 1 回）</h4>
<ol>
<li>画面左端の 🔑（鍵の形）のアイコンを押します。「シークレット」という画面が開きます。</li>
<li>「<b>＋ 新しいシークレットを追加</b>」を押します。「ノートブックからのアクセス」「名前」「値」「アクション」の欄が並んだ行が 1 行増えます。</li>
<li>「<b>名前</b>」の欄に <code>ANTHROPIC_API_KEY</code> と入力します（大文字・小文字もこのとおりに。スペースは入れられません）。</li>
<li>「<b>値</b>」の欄に、コピーしておいた API キー（<code>sk-ant-</code> で始まる文字列）を貼り付けます。
入力した値は隠して表示されます。「アクション」の目のアイコンを押すと、正しく貼り付けられたか確かめられます。</li>
<li>行の左端の「<b>ノートブックからのアクセス</b>」のスイッチを押してオンにします（✕ の表示からオンの表示に変わります）。</li>
<li>保存ボタンはありません。入力した内容がそのまま保存されるので、シークレットの画面は閉じてかまいません。</li>
<li>上の手順 4 で「API で自動実行」を選び、手順 5 を実行します。シークレットへのアクセスを許可するか聞かれたら、許可します。</li>
</ol>
<p>シークレットの画面にある「Gemini API キー」の欄は、Claude を使うときは関係ありません。</p>
<p>手順 5 で「シークレット ANTHROPIC_API_KEY を読めませんでした」と出たときは、名前の綴りと「ノートブックからのアクセス」がオンになっているかを確認してください。
キーが間違っている・無効になっているときは、変換レポートの「AI による補完」の章にエラーが表示されます。</p>

<h4>3. キーを安全に扱う</h4>
<ul>
<li>キーをノートブックのセルやメール・チャットに直接書かないでください。シークレットに保存した値は非公開で、自分と、アクセスを許可したノートブックからしか見えません。ノートブックを他の人と共有しても、キーは渡りません。</li>
<li>キーが漏れたおそれがあるときは、Claude Console の「Settings → API keys」でそのキーを削除し、新しく作り直してください。</li>
</ul>

<h4>4. 料金の目安（Claude）</h4>
<ul>
<li>「API で自動実行」で手順 5 を実行するたびに料金がかかります（既定のモデル <code>claude-opus-5-5</code> は、入力 100 万トークンあたり 4 ドル、出力 100 万トークンあたり 20 ドル）。</li>
<li>試験に使った論文（AI への依頼文が約 4 万字）では、1 回あたりおおむね 0.3〜1 ドル程度と見込まれます（論文の長さ・図の数で変わります）。</li>
<li>実際に使ったトークン数は、変換レポートの「AI による補完」の章の最後に表示されます。</li>
</ul>

<h4>5. API で使うモデルについて</h4>
<ul>
<li>手順 4 の「API で使うモデル（MODEL）」の既定は、このツールで動作を確かめた <code>claude-opus-5-5</code>（Claude Opus 5.5）です。
Anthropic の発表では、このモデルの提供終了は 2027 年 9 月 22 日より前にはならない予定です（<a href="https://platform.claude.com/docs/en/about-claude/model-deprecations" target="_blank">モデルの提供終了の予定</a>）。</li>
<li>将来このモデルが使えなくなった場合は、ツールが Anthropic のモデル一覧から使える最新の Opus を自動で選んでやり直し、変換レポートの「AI による補完」の章にその旨を表示します。</li>
<li>はじめから最新の Opus を使いたいときは、「自動（最新の Opus）」を選びます。ただし、動作を確かめていない新しいモデルが選ばれることがあります。</li>
<li>モデル名を自分で入力することもできます。使えるモデルの名前（Claude API ID）は、Anthropic のモデル一覧（<a href="https://platform.claude.com/docs/en/models/overview" target="_blank">Models overview</a>）で確認できます。</li>
<li>ChatGPT・Gemini・Sakana AI の API を使うときは、次の 6. を見てください。API キーがなくても、「手動（チャットに貼り付け）」を選べば、
それぞれのチャット画面に依頼文を貼り付けて使えます。</li>
</ul>

<h4>6. ChatGPT・Gemini・Sakana AI の API を使うとき</h4>
<ul>
<li>「API で自動実行」は、ChatGPT（OpenAI）、Gemini（Google）、Sakana AI（Sakana Namazu・Sakana Fugu）の API にも対応しています。ただし、<b>推奨は Claude です</b>
（このツールの AI への依頼文と動作の確認は、Claude で行っています）。</li>
<li>API キーの作り方、利用料の支払い、利用上限の設定などは、<b>各社の案内を自分で調べて行ってください</b>（このノートブックでは説明しません）。</li>
<li>作った API キーは、上の 2. と同じ手順で Colab のシークレットに登録します。「名前」は、ChatGPT では <code>OPENAI_API_KEY</code>、
Gemini では <code>GEMINI_API_KEY</code>（<code>GOOGLE_API_KEY</code> という名前で登録したものも使えます）、Sakana AI では <code>SAKANA_API_KEY</code> にします。</li>
<li>使うモデルの名前は、手順 4 の「Claude 以外のモデル名（OTHER_MODEL）」に自分で入力します（各社の資料で確認してください）。
<b>Claude Opus と同等以上の性能のモデル（各社の最上位クラスのモデル）を推奨します。</b>
性能の低いモデルでは、取りこぼしや誤った提案が増えます（誤った提案はプログラムの検証で採用されませんが、補完の効果が下がります）。</li>
<li>論文の本文は、選んだ会社（OpenAI、Google、Sakana AI）に送信されます。送信した内容の扱いは、各社の利用規約で確認してください。
無料の利用枠では、送信した内容がサービスの改善に使われる場合があります。<b>Sakana AI は、既定で送信した内容をモデルの学習に使う設定です。</b>
未公開の原稿を送るので、使う前に Sakana AI の管理画面（Console）の設定で、学習への利用を止めて（オプトアウトして）ください。</li>
<li>料金は各社の料金表で確認してください。使ったトークン数は、変換レポートの「AI による補完」の章の最後に表示されます。</li>
</ul>
</details>'''

cells = [
    md(f"""
# 論文 docx → J-STAGE 全文 XML 変換（全国数学教育学会誌『数学教育学研究』）

**ツールの版: {VERSION}**{VERSION_NOTE}　… 手順 1 を実行すると、実際に読み込まれた版（とコミット ID）も表示されます。

このノートブックは、テンプレートで作成された論文の Word ファイル（.docx）を、J-STAGE の全文 XML（JATS 1.1）に変換します。
パソコンに何かをインストールする必要はありません。**上から順に、各セルの左の ▶ ボタンを押して実行してください。**
**前の手順の実行が終わってから、次の手順の ▶ を押します**（実行中に次の ▶ を押すと、アップロードのボタンなどが出ないことがあります）。
前の手順を実行せずに後の手順の ▶ を押すと、「先に手順 ○ を実行してください」と表示されて止まります。

| 手順 | 内容 |
|---|---|
| 1 | 準備（最初に 1 回だけ。「準備ができました」と表示されたら、手順 2 に進みます） |
| 2 | 作り方を選び、論文の docx と PDF をアップロード（ボタンが別々に出ます） |
| 3 | 書誌情報（巻・号・ページ・査読の有無・キーワード・日付）を入力 |
| 4 | AI による補完の方法を選ぶ |
| 5 | 変換を実行（結果のレポートが表示されます） |
| 6 | （手動モードのときだけ）AI の回答を貼り付けて再変換 |
| 7 | （画像を用意できなかった図があるときだけ）足りない画像をアップロード |
| 8 | 結果をダウンロード |
| 9 | 続けて他の論文を変換するとき: ▶ を押してから、手順 2 に戻る |

- 作り方は 2 通りあり、手順 2 で選びます。
  - **出版版 PDF に合わせてから作る**（初期値。PDF が必要）: docx の文字を出版版 PDF に合わせて直した docx（Word の変更履歴つき）を先に作り、
    それを変換します。直した docx も結果に入るので、Word で開いて変更を確かめられます。
  - **docx から作る**: 本文の文字は 1 文字も変えません。PDF をアップロードすると、docx と PDF の文字を照合して、違う箇所をレポートに出します。
    PDF がまだないときは、こちらを選びます。
- どちらでも、変換後に、変換した docx と XML の文字を 1 文字ずつ照合して確かめます（レポートの「文字の不変性チェック」）。
- アップロードしたファイルは、このノートブックを閉じる（ランタイムが切れる）と Google のサーバーから消えます。
- 「API で自動実行」を選ぶと、論文の本文が選んだ AI の会社（Claude は Anthropic、ChatGPT は OpenAI、Gemini は Google、Sakana AI は Sakana AI）の API に送信されます。
- 複数の論文を続けて変換するときは、1 本ごとに手順 8 で結果をダウンロードしてから、手順 9 の ▶ を押し、手順 2 から繰り返します。
  手順 3 などの入力欄には前の論文の値が残るので、書き換えてから実行します（心配なときは、ノートブックを開き直して手順 1 から）。

ソースコードと説明書: https://github.com/{REPO}
"""),
    code(f"""
#@title 1. 準備（最初に 1 回だけ。1 分ほどかかります）
#@markdown **EMF/WMF の図を変換する（CONVERT_EMF）**: 図が Word の図形（EMF/WMF 形式）で貼られている論文では、画像の変換に LibreOffice を使います。チェックを入れると LibreOffice を**裏で**インストールします（数分かかります。インストールは手順 1 の後も裏で続き、手順 5 の変換はそれが終わってから始まります）。
CONVERT_EMF = True  #@param {{type:"boolean"}}
#@markdown **開発版を使う（USE_DEV_VERSION）**: 開発者向け。開発中の版を試すときだけチェックを入れます（実行するとブランチ名の入力欄が出ます）。
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
    print("LibreOffice を裏でインストールしています（数分）。インストールは裏で続くので、このまま手順 2 に進んでください"
          "（手順 5 の変換は、インストールが終わってから始まります）。")
""" + "DONE = {1}\n"),
    code("""
#@title 2. 作り方を選び、論文の docx と PDF をアップロード
#@markdown **作り方（ROUTE）**: 最初に選びます。
#@markdown - **出版版 PDF に合わせてから作る**（初期値）: 受け取った docx が著者校正の前の原稿で、出版社が組版で直した文字（全角・半角、「資料」→「付録」など）が出版版 PDF にしかないことがあるため、docx の文字を PDF に合わせて直した docx（**Word の変更履歴つき**。スタイル・書式・数式・図・注はそのまま）を作り、それを変換します。表の中・数式・図の中の文字・リンクの文字は直しません。PDF のページ番号・投稿受付日など組版で入る文字や、表・図の中の文字は docx に足しません（足さなかった文字はレポートの 13 章の最後に一覧が出ます。本文が混じっていないか確かめてください）。**PDF のアップロードが必要です。**
#@markdown - **docx から作る**: docx の本文の文字を 1 文字も変えずに XML にします。PDF をアップロードすると、変換の後に docx の文字と PDF の文字を照合し、違う箇所（全角・半角の違い、「資料」と「付録」など）をレポートの 13 章に出します（XML は docx の文字のままです）。PDF がまだないときや、docx が最終版だと分かっているときに選びます。
ROUTE = "出版版 PDF に合わせてから作る"  #@param ["出版版 PDF に合わせてから作る", "docx から作る"]
#@markdown **PDF もアップロードする（UPLOAD_PDF）**: J-STAGE に登載する PDF がまだなければ、チェックを外し、作り方を「docx から作る」にしてから実行してください（PDF 用のボタンは出ません。後で jasme_巻_開始ページ.zip に入れることもできます）。
UPLOAD_PDF = True  #@param {type:"boolean"}
""" + guard(1) + """
from pathlib import Path
from google.colab import files

ROUTE_KEY = {"docx から作る": "docx", "出版版 PDF に合わせてから作る": "pdf"}[ROUTE]
if ROUTE_KEY == "pdf" and not UPLOAD_PDF:
    raise SystemExit("「出版版 PDF に合わせてから作る」には PDF が必要です。UPLOAD_PDF にチェックを入れるか、PDF がまだないときは"
                     "作り方（ROUTE）を「docx から作る」にして、もう一度この手順を実行してください。")
WORK = Path("/content/jasme_work")
INPUT = WORK / "input"
INPUT.mkdir(parents=True, exist_ok=True)
USER_IMAGES = {}   # 手順 7 でアップロードした画像（出力ファイル名 → (元のファイル名, 中身)）。論文を選び直したら捨てる


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
if ROUTE_KEY == "pdf" and not pdf_path:
    raise SystemExit("「出版版 PDF に合わせてから作る」には PDF が必要です。もう一度この手順を実行し、PDF を選んでください"
                     "（PDF がまだないときは、作り方（ROUTE）を「docx から作る」にしてから実行します）。")
print()
print("作り方:", ROUTE)
print("論文:", docx_path.name)
print("PDF :", pdf_path.name if pdf_path else "（なし。J-STAGE への登載には PDF が必要です）")
""" + mark(2)),
    code("""
#@title 3. 書誌情報を入力
#@markdown 各欄の上の説明（日本語）に対応する欄に入力します。日付は YYYY-MM-DD の形で、分からなければ空欄にします。
#@markdown ***
#@markdown **巻（volume）**（J-STAGE のフォルダ名・ファイル名と DOI に使います）
volume = ""  #@param {type:"string"}
#@markdown **号（issue）**
issue = ""  #@param {type:"string"}
#@markdown **最初のページ（first_page）**
first_page = ""  #@param {type:"string"}
#@markdown **最後のページ（last_page）**
last_page = ""  #@param {type:"string"}
#@markdown ***
#@markdown **査読の有無（peer_review）**（必須。必ず選んでください）
peer_review = "（選んでください）"  #@param ["（選んでください）", "査読あり", "査読なし"]
#@markdown **最終査読日（last_review_date）**（査読ありで、分かれば）
last_review_date = ""  #@param {type:"string"}
#@markdown ***
#@markdown **キーワード（日本語）（keywords_ja）**（任意。「；」または「;」で区切る。例: `数学教育；活動；哲学`）
keywords_ja = ""  #@param {type:"string"}
#@markdown **キーワード（英語）（keywords_en）**（任意。「;」または「；」で区切る。例: `mathematics education; activity; philosophy`）。日・英あわせて 100 個まで
keywords_en = ""  #@param {type:"string"}
#@markdown ***
#@markdown **発行日（pub_date）**
pub_date = ""  #@param {type:"string"}
#@markdown **J-STAGE 公開日（jstage_release_date）**
jstage_release_date = ""  #@param {type:"string"}
#@markdown **受付日（received）**
received = ""  #@param {type:"string"}
#@markdown **受理日（accepted）**
accepted = ""  #@param {type:"string"}
#@markdown ***
#@markdown **DOI（doi）**（空欄なら 10.24529/jasme.巻.号_開始ページ を使います）
doi = ""  #@param {type:"string"}
#@markdown **原稿種別（manuscript_type）**
""" + TYPE_PARAM + """#@markdown **原稿種別（日本語）（subject_other）**・**原稿種別（英語）（subject_other_en）**: 原稿種別で「その他」を選んだときだけ入力します
subject_other = ""  #@param {type:"string"}
subject_other_en = ""  #@param {type:"string"}
#@markdown **責任著者が何番目の著者か（corresponding_author）**（例: 1。複数なら「1,2」）
corresponding_author = ""  #@param {type:"string"}
""" + guard(1, 2) + """if peer_review not in ("査読あり", "査読なし"):
    raise SystemExit("査読の有無（peer_review）を選んでください。")
if peer_review == "査読なし" and last_review_date.strip():
    raise SystemExit("査読なしのときは、最終査読日（last_review_date）を空欄にしてください。")
if manuscript_type == "その他":
    if not subject_other.strip() or not subject_other_en.strip():
        raise SystemExit("原稿種別で「その他」を選んだときは、原稿種別（日本語）（subject_other）と（英語）（subject_other_en）を入力してください。")
    subject_ja, subject_en = subject_other.strip(), subject_other_en.strip()
else:
    subject_ja, subject_en = manuscript_type.split(" / ", 1)
    if subject_other.strip() or subject_other_en.strip():
        print("※ 原稿種別は「" + manuscript_type + "」を使います（subject_other の入力は使いません）")
meta_input = {"volume": volume, "issue": issue, "fpage": first_page, "lpage": last_page,
              "peer_review": peer_review, "approved": last_review_date,
              "keywords_ja": keywords_ja, "keywords_en": keywords_en,
              "pub_date": pub_date, "epub_date": jstage_release_date, "received": received,
              "accepted": accepted, "doi": doi,
              "subject_ja": subject_ja, "subject_en": subject_en,
              "corresp": corresponding_author}
from jasme_jats.config import ArticleMeta, keyword_language_mismatch, keyword_problem
try:
    _meta = ArticleMeta.from_dict(meta_input)   # 日付の書き方などをここで確かめる
except ValueError as e:
    raise SystemExit(f"入力を確認してください: {e}")
if keyword_problem(_meta):
    raise SystemExit(keyword_problem(_meta) + "。")
print("入力しました（原稿種別: " + subject_ja + " / " + subject_en + "、" + peer_review + "）。未入力の項目はレポートに表示されます。")
print("キーワード（日本語）:", "；".join(_meta.keywords_ja) or "（なし）")
print("キーワード（英語）  :", "; ".join(_meta.keywords_en) or "（なし）")
if keyword_language_mismatch(_meta):
    print("※ 日本語・英語の欄を取り違えていないか確認してください:", "、".join(keyword_language_mismatch(_meta)))
_prev = globals().get("PREVIOUS")   # 手順 8 で記録した、前の論文
if _prev:
    from jasme_jats.colab import carried_over, same_first_page
    if same_first_page(_prev["meta"], meta_input) and globals().get("_SAME_PAGE_OK") != docx_path.name:
        _SAME_PAGE_OK = docx_path.name
        raise SystemExit(f"巻と最初のページが、前の論文（{_prev['docx']}）と同じです。入力欄を今回の論文（{docx_path.name}）の"
                         "ものに書き換えてから ▶ を押してください。（同じ論文を変換し直すときは、もう一度 ▶ を押すと先に進みます）")
    if carried_over(_prev["meta"], meta_input):
        print(f"※ 次の項目が、前の論文（{_prev['docx']}）と同じ値です。今回の論文のものか確かめてください:",
              "、".join(carried_over(_prev["meta"], meta_input)))
""" + mark(3)),
    code("""
#@title 4. AI による補完の方法を選ぶ
#@markdown - **使わない**（推奨しません）: 機械的な変換だけを行います。取りこぼしがあっても補われません。テキストボックスなどに入った図表で、位置を機械的に決められないものがあると、手順 5 で変換を中止します（AI による補完が必要です）。
#@markdown - **API で自動実行**: AI の API を呼び出して、機械処理で取りこぼした引用・スタイルの誤り・画像の数式などを補完します。**Claude を推奨します**（ChatGPT・Gemini・Sakana AI にも対応）。左の 🔑（シークレット）に API キー（Claude は名前 `ANTHROPIC_API_KEY`）を登録し、「ノートブックからのアクセス」をオンにしてください（API の利用料がかかります）。キーの作り方と登録の手順は、このセルのすぐ下の「**API キーについての詳細**」を開いてください。
#@markdown - **手動**: AI への依頼文を作ります。claude.ai などのチャットに貼り付け、返ってきた回答を手順 6 で貼り戻します（API キー不要）。
#@markdown ***
#@markdown **AI による補完の方法（AI_MODE）**
AI_MODE = "手動（チャットに貼り付け）"  #@param ["使わない", "API で自動実行（Claude・推奨）", "API で自動実行（ChatGPT）", "API で自動実行（Gemini）", "API で自動実行（Sakana AI）", "手動（チャットに貼り付け）"]
#@markdown **Claude のモデル（MODEL）**（Claude を使うとき。通常は変更不要。「API キーについての詳細」の 5. を参照）
MODEL = "claude-opus-5-5"  #@param ["claude-opus-5-5", "自動（最新の Opus）"] {allow-input: true}
#@markdown **Claude 以外のモデル名（OTHER_MODEL）**（ChatGPT・Gemini・Sakana AI を使うときは必ず入力。**Claude Opus と同等以上の性能のモデル**（各社の最上位クラスのモデル）を推奨します。モデル名は各社の資料で確認してください。「API キーについての詳細」の 6. を参照）
OTHER_MODEL = ""  #@param {type:"string"}
#@markdown **図表番号を分ける（SPLIT_LABELS）**: 図表番号（「図1」）を J-STAGE の <label> 要素に分けるか（分けると番号とタイトルの間の空白 1 文字を落とします。既定は分けない）
SPLIT_LABELS = False  #@param {type:"boolean"}
""" + guard(1, 2, 3) + """AI = "api" if AI_MODE.startswith("API") else {"使わない": "none", "手動（チャットに貼り付け）": "manual"}[AI_MODE]
PROVIDER = {"API で自動実行（ChatGPT）": "openai", "API で自動実行（Gemini）": "gemini",
            "API で自動実行（Sakana AI）": "sakana"}.get(AI_MODE, "claude")
if PROVIDER == "claude":
    API_MODEL = "auto" if MODEL.startswith("自動") else MODEL.strip()
else:
    API_MODEL = OTHER_MODEL.strip()
    if not API_MODEL or API_MODEL.lower().startswith("claude"):
        raise SystemExit("Claude 以外を使うときは、Claude 以外のモデル名（OTHER_MODEL）の欄に、使うモデルの名前を入力してください"
                         "（Claude Opus と同等以上の性能のモデルを推奨します。モデル名は各社の資料で確認してください）。")
print("AI による補完:", AI_MODE + (f"（モデル: {API_MODEL}）" if AI == "api" else ""))
if PROVIDER != "claude":
    print("※ 推奨は Claude です。API キーの作り方・料金などは各社の案内で確かめてください（「API キーについての詳細」の 6.）。")
if PROVIDER == "sakana":
    from IPython.display import HTML, display
    from jasme_jats.colab import error_box
    display(HTML(error_box("Sakana AI は、既定で送信した内容をモデルの学習に使う設定です",
                           "未公開の原稿を送るので、手順 5 の前に、Sakana AI の管理画面（Console）の設定で"
                           "学習への利用を止めて（オプトアウトして）ください。")))
if AI == "none":
    from IPython.display import HTML, display
    from jasme_jats.colab import no_ai_box
    display(HTML(no_ai_box()))
""" + mark(4)),
    md(API_HELP),
    code("""
#@title 5. 変換を実行
""" + guard(1, 2, 3, 4) + """import shutil
from IPython.display import HTML, Markdown, display
from jasme_jats.colab import (ai_required_box, error_box, lost_images_box, missing_images_box, no_ai_box, pdf_diff_box,
                               prompt_box, unplaced_box)
from jasme_jats.report import pdf_summary
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import AIRequiredError, Options, add_images, convert

api_key = None
if AI == "api":
    from google.colab import userdata
    from jasme_jats.ai_assist import API_KEY_NAMES
    _err = None
    for _name in API_KEY_NAMES[PROVIDER]:
        try:
            api_key = userdata.get(_name)
            break
        except Exception as e:
            _err = e
    if not api_key:
        raise SystemExit(f"シークレット {' または '.join(API_KEY_NAMES[PROVIDER])} を読めませんでした: {_err or '値が空です'}")

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
try:
    res = convert(docx_path, meta, journal, Options(out_dir=OUT, ai_mode=AI, ai_provider=PROVIDER, ai_model=API_MODEL,
                                                  ai_api_key=api_key, pdf_path=pdf_path, route=ROUTE_KEY,
                                                  split_labels=SPLIT_LABELS))
except AIRequiredError as e:
    display(HTML(ai_required_box(str(e))))
    raise SystemExit("手順 4 で「API で自動実行」か「手動（チャットに貼り付け）」を選び、手順 4 からやり直してください。")
fid = res.fidelity
print("文字の不変性チェック:", fid.summary(), f"（段落 {fid.units} 件中 {fid.mapped} 件を出力、{len(fid.excluded)} 件は除外）")
print("最終出力の再チェック:", "合格" if fid.final_ok else "不合格")
print("DTD 検証:", "合格" if res.dtd_valid else "不合格")
print("J-STAGE のアップロード時チェック:", "問題なし" if not res.jstage_issues else f"要対応 {len(res.jstage_issues)} 件")
for mid, msg in res.jstage_issues:
    print("  ", mid, msg)
print("出版版 PDF との照合:", pdf_summary(res))
if res.docx_fix is not None:
    print("PDF に合わせて直した docx（変更履歴つき。手順 8 でダウンロードする ZIP に入ります）:", res.docx_fix.path.name)
if globals().get("USER_IMAGES"):
    _again = add_images(res, USER_IMAGES, skip_unneeded=True)
    if _again:
        print("手順 7 でアップロードした画像を入れ直しました:", "、".join(_again))
manual_prompt = None
if AI == "none":
    display(HTML(no_ai_box()))
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
if AI == "api":
    display(HTML(unplaced_box(res.plan)))
display(HTML(missing_images_box(res)))
display(HTML(lost_images_box(res)))
display(HTML(pdf_diff_box(res)))
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
if globals().get("PREVIOUS") and AI_RESPONSE.strip() == PREVIOUS.get("ai_response"):
    raise SystemExit(f"貼り付けられているのは、前の論文（{PREVIOUS['docx']}）の AI の回答です。今回の論文の依頼文（手順 5 の枠）を "
                     "AI に渡し、返ってきた回答に貼り替えてから ▶ を押してください。")
res = convert(docx_path, meta, journal, Options(out_dir=OUT, ai_mode="manual", ai_response=AI_RESPONSE,
                                              pdf_path=pdf_path, route=ROUTE_KEY, split_labels=SPLIT_LABELS))
LAST_AI_RESPONSE = AI_RESPONSE.strip()
if globals().get("USER_IMAGES"):
    _again = add_images(res, USER_IMAGES, skip_unneeded=True)
    if _again:
        print("手順 7 でアップロードした画像を入れ直しました:", "、".join(_again))
fid = res.fidelity
print("文字の不変性チェック:", fid.summary(), "/ 最終出力の再チェック:", "合格" if fid.final_ok else "不合格",
      "/ DTD 検証:", "合格" if res.dtd_valid else "不合格",
      "/ J-STAGE のアップロード時チェック:", "問題なし" if not res.jstage_issues else f"要対応 {len(res.jstage_issues)} 件",
      "/ 出版版 PDF との照合:", pdf_summary(res))
if res.ai.error:
    display(HTML(error_box("貼り付けた回答を読み込めませんでした（AI による補完は反映されていません）", res.ai.error)))
display(HTML(unplaced_box(res.plan)))
display(HTML(missing_images_box(res)))
display(HTML(lost_images_box(res)))
display(HTML(pdf_diff_box(res)))
display(Markdown(res.report_path.read_text(encoding="utf-8")))
""", form=False),
    code("""
#@title 7. 足りない画像をアップロード（画像を用意できなかった図があるときだけ）
#@markdown Word の図形で描かれた図などは、docx に画像ファイルがないので、変換で画像を作れません（手順 5 の赤い枠「画像ファイルを用意できなかった図」）。そのときだけ ▶ を押します。
#@markdown 図ごとに「ファイル選択」ボタンが出るので、その図の画像を選んでください。**ファイル名は何でもかまいません**（正しい名前にして入れ、jasme_巻_開始ページ.zip とレポートを作り直します）。PNG・JPEG のほか、図の部分だけの 1 ページの PDF も使えます。
#@markdown - 画像の作り方の例: 記事の PDF を開いて図の部分を切り取る（スクリーンショットなど）。Word で図を右クリックして「図として保存」を選ぶ。
#@markdown - 図の題目（「図1　…」）は XML に入っているので、画像には含めません。
#@markdown - 用意できない図は、ファイルを選ばずに「キャンセル」を押すと飛ばせます（後でこの手順をやり直せます）。
""" + guard(1, 2, 3, 4, 5) + """from IPython.display import HTML, Image, display
from jasme_jats.colab import error_box, missing_images_box
from jasme_jats.pipeline import add_images, graphics_path
from jasme_jats.report import images_to_prepare

USER_IMAGES = globals().get("USER_IMAGES") or {}
_missing = images_to_prepare(res)
if not _missing:
    print("用意が必要な画像はありません。手順 8 に進んでください。")
for _name, _cap, _why in _missing:
    print(f"▼ {_cap or _name} の画像を選んでください（{_name} として入れます。用意できないときはキャンセル）")
    _up = files.upload()
    if not _up:
        print("  選ばれなかったので飛ばします")
        continue
    if len(_up) > 1:
        print("  ファイルが複数選ばれたので、最初の 1 つだけを使います")
    _file, _data = next(iter(_up.items()))
    try:
        add_images(res, {_name: (_file, _data)})
    except ValueError as e:
        display(HTML(error_box(f"{_cap or _name} の画像を入れられませんでした", str(e))))
        continue
    USER_IMAGES[_name] = (_file, _data)
    print(f"  {_file} を {_name} として入れました")
    display(Image(filename=str(graphics_path(res) / _name), width=360))
if _missing:
    _rest = images_to_prepare(res)
    if len(_rest) < len(_missing):
        print(f"画像を {len(_missing) - len(_rest)} 件入れ、{res.zip_path.name} とレポートを作り直しました。")
    if _rest:
        display(HTML(missing_images_box(res)))
    else:
        print("足りない画像はなくなりました。手順 8 でダウンロードしてください。")
""" + mark(7)),
    code("""
#@title 8. 結果をダウンロード
#@markdown 「変換結果_巻_開始ページ.zip」の中に、J-STAGE にアップロードする jasme_巻_開始ページ.zip、XML、変換レポートが入っています。「出版版 PDF に合わせてから作る」では、PDF に合わせて直した docx（Word の変更履歴つき）も入っています。
""" + guard(1, 2, 3, 4, 5) + """from IPython.display import HTML, display
from jasme_jats.colab import lost_images_box, missing_images_box
from jasme_jats.report import images_to_prepare

_missing = images_to_prepare(res)
_key = str(docx_path) + "|" + ",".join(n for n, _, _ in _missing)
if _missing and globals().get("_NO_IMAGES_OK") != _key:
    _NO_IMAGES_OK = _key
    display(HTML(missing_images_box(res)))
    raise SystemExit(f"画像を用意できなかった図が {len(_missing)} 件あります。手順 7 で画像をアップロードしてから、もう一度この ▶ を押して"
                     "ください。画像を入れずにダウンロードするときは、そのままもう一度この ▶ を押します（後で ZIP の Graphics/ に"
                     "入れることもできます）。")
archive = shutil.make_archive(str(WORK / f"変換結果_{res.xml_path.stem}"), "zip", OUT)
files.download(archive)
CONVERTED = {**globals().get("CONVERTED", {}), Path(archive).name: docx_path.name}
print("ダウンロードしました:", Path(archive).name, "（" + docx_path.name + "）")
display(HTML(missing_images_box(res)))
display(HTML(lost_images_box(res)))
print("続けて他の論文を変換するときは、下の手順 9 の ▶ を押してください。")
""" + mark(8)),
    code("""
#@title 9. 続けて他の論文を変換する
#@markdown 手順 8 で結果をダウンロードした後、同じ画面のまま次の論文を変換するときに ▶ を押します。
#@markdown この論文のファイルと入力の記録を片付けて、手順 2 から始められるようにします（手順 1 の準備はやり直しません）。
#@markdown ▶ を押したら、**手順 2 から順に**実行してください。手順 3 などの入力欄には前の論文の値が残っているので、**今回の論文のものに書き換えます**。
#@markdown 書き換え漏れが心配なときは、ノートブックを開き直して、手順 1 からやり直すほうが確実です（入力欄が初期の値に戻ります）。
""" + guard(1) + """import shutil
from pathlib import Path
from IPython.display import HTML, display
from jasme_jats.colab import next_article_box

if 5 in DONE and 8 not in DONE and globals().get("_DISCARD_OK") != str(globals().get("docx_path")):
    _DISCARD_OK = str(globals().get("docx_path"))
    raise SystemExit(f"この論文（{docx_path.name}）の結果を、まだダウンロードしていません。手順 8 でダウンロードしてから、"
                     "もう一度この ▶ を押してください。ダウンロードせずに次の論文へ進むときは、そのままもう一度この ▶ を押します。")
if "docx_path" in globals():
    PREVIOUS = {"docx": docx_path.name, "meta": dict(globals().get("meta_input") or {}),
                "ai_response": globals().get("LAST_AI_RESPONSE", "")}
for _name in ("docx_path", "pdf_path", "meta_input", "meta", "res", "manual_prompt", "LAST_AI_RESPONSE", "_DISCARD_OK",
              "_SAME_PAGE_OK", "USER_IMAGES", "_NO_IMAGES_OK"):
    globals().pop(_name, None)
_work = Path("/content/jasme_work")
shutil.rmtree(_work / "input", ignore_errors=True)
shutil.rmtree(_work / "output", ignore_errors=True)
for _zip in _work.glob("変換結果*.zip"):
    _zip.unlink()
DONE = {1}
if globals().get("CONVERTED"):
    print("これまでにダウンロードした結果:")
    for _zip, _docx in CONVERTED.items():
        print("  ", _zip, "←", _docx)
print("次の論文の準備ができました。手順 2 の ▶ から順に実行してください。")
display(HTML(next_article_box(globals().get("PREVIOUS", {}).get("docx", ""))))
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
