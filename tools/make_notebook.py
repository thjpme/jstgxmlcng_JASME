"""Colab 用ノートブック notebooks/JASME_docx_to_JSTAGE_XML.ipynb（従来版）と JASME_docx_to_JSTAGE_XML_GUI.ipynb（1 画面版）を生成する。

  python tools/make_notebook.py [--branch ブランチ名]

ipynb を直接編集せず、このスクリプトを直して作り直す（CLAUDE.md。作り直し忘れは tests/test_notebook.py が検出する）。
"""
import ast
import json
import re
import textwrap
from pathlib import Path

REPO = "thjpme/jstgxmlcng_JASME"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "notebooks" / "JASME_docx_to_JSTAGE_XML.ipynb"
OUT_GRADIO = ROOT / "notebooks" / "JASME_docx_to_JSTAGE_XML_GUI.ipynb"      # 一般の利用者用: Gradio の 1 画面（docs/GUI_PLAN.md）
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


def module_constants(path, names) -> dict:
    """Python のファイル path の最上位の「名前 = リテラル」の値を、パッケージを import せずに読む（{名前: 値}）。

    版（__init__.py）・原稿種別（jasme.toml）と同じく、リポジトリの src の値を使うため（インストール済みの別の版の jasme_jats を
    読まない。lxml などの依存を入れずに動く）。行が見つからない・値がリテラルでないときは、分かるエラーで止める。
    """
    found = {}
    for node in ast.parse(Path(path).read_text(encoding="utf-8")).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for t in targets:
            if isinstance(t, ast.Name) and t.id in names and node.value is not None:
                try:
                    found[t.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    missing = [n for n in names if n not in found]
    if missing:
        path = Path(path)
        where = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        raise SystemExit(f"{where} に {'・'.join(f'{n} = …' for n in missing)} の行が見つかりません（ノートブックの既定の AI モデル"
                         "などは、この行の値から作ります。名前を変えたなら tools/make_notebook.py も直してください。値は式や"
                         "ほかの名前を使わず、リテラルだけで書きます）")
    return found


# 既定の AI モデル（手順 4 の MODEL の既定と、「API キーについての詳細」の 4.・5.）は src/jasme_jats/ai_assist.py の値を使う
_AI = module_constants(ROOT / "src" / "jasme_jats" / "ai_assist.py", ("DEFAULT_MODEL", "DEFAULT_MODEL_INFO"))
DEFAULT_MODEL, DEFAULT_MODEL_INFO = _AI["DEFAULT_MODEL"], _AI["DEFAULT_MODEL_INFO"]
if not (isinstance(DEFAULT_MODEL, str) and DEFAULT_MODEL.strip()) or not (
        isinstance(DEFAULT_MODEL_INFO, dict) and {"name", "input_usd", "output_usd", "not_before", "per_run_usd"} <= set(DEFAULT_MODEL_INFO)):
    raise SystemExit("src/jasme_jats/ai_assist.py の DEFAULT_MODEL（モデル名の文字列）か DEFAULT_MODEL_INFO（name・input_usd・"
                     "output_usd・not_before・per_run_usd〔下限と上限の 2 つ〕を持つ辞書）の形が違います")
_Y, _M, _D = str(DEFAULT_MODEL_INFO["not_before"]).split("-")
MODEL_NOT_BEFORE = f"{int(_Y)} 年 {int(_M)} 月 {int(_D)} 日"    # 提供終了の予定（この日より前には終わらない）
_LOW, _HIGH = DEFAULT_MODEL_INFO["per_run_usd"]          # 1 回の変換にかかる費用の目安（ドル。下限・上限。AI に出版版 PDF も送る）
COST_NOTE = (f"出版版 PDF も一緒に送ります。1 回あたりおおむね {_LOW:g}〜{_HIGH:g} ドル（目安。論文の長さとページ数で変わります。"
             "実際の API で測って直します）。図の画像や書誌だけを直して変換し直すときは、前の回答を使うので料金はかかりません"
             "（Word で原稿を直したときや、AI・モデル・PDF を変えたときは、AI を呼び直します）。")
MODEL_LINE = (f'MODEL = "{DEFAULT_MODEL}"  #@param ["{DEFAULT_MODEL}", "自動（最新の Opus）"] {{allow-input: true}}\n')


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)}


# Colab ではどのセルの ▶ も押せてしまうので、各手順の最初で前の手順が済んでいるかを確かめる。
# 済んだ手順は変数 DONE に記録する。各手順の最初（guard の直後）で、自分とそれより後の手順を「未実行」に戻し（unmark）、
# 最後まで済んだら自分を記録する（mark）。途中で止まった手順の後では、後ろの手順の guard が止める。
GUARD = """_need = [n for n in (NEED) if n not in globals().get("DONE", set())]
if _need:
    raise SystemExit("先に手順 " + "・".join(map(str, _need)) + " を実行してください（上から順に ▶ を押します。"
                     "前の手順をやり直したときは、その後の手順もやり直してください）。")
"""


def guard(*steps):
    return GUARD.replace("NEED", ", ".join(map(str, steps)) + ",")


def mark(step):
    return f'DONE = {{n for n in globals().get("DONE", set()) if n < {step}}} | {{{step}}}\n'


def unmark(step):
    return f'DONE = {{n for n in globals().get("DONE", set()) if n < {step}}}\n'


def code(text, form=True):
    meta = {"cellView": "form"} if form else {}
    return {"cell_type": "code", "metadata": meta, "execution_count": None, "outputs": [],
            "source": text.strip("\n").splitlines(keepends=True)}


DOCS = f"https://github.com/{REPO}/blob/main/docs"      # 説明書（利用者向け）


# 手順 1（準備）のセルは断片に分けて持つ（1 画面版のノートブックが、順番を変えて同じ断片を使う）
PREP_PARAMS = f"""
#@title 1. 準備（最初に 1 回だけ。1 分ほどかかります）
#@markdown **USE_DEV_VERSION**: 開発者向け。開発中の版を試すときだけチェックします（ブランチ名を尋ねます）。
USE_DEV_VERSION = False  #@param {{type:"boolean"}}

"""      # 見出しと入力欄
PREP_BRANCH = f"""import subprocess, sys
# このランタイムで一度ツールを使っていると、古い版がメモリに残ったままになる（入れ直しても反映されない）
loaded_before = "jasme_jats" in sys.modules
BRANCH = "main"
if USE_DEV_VERSION:
    BRANCH = input("開発版のブランチ名を入力して Enter を押してください: ").strip()
    if not BRANCH:
        raise SystemExit("ブランチ名が入力されていません。開発版を使わないときは、チェックを外して実行してください。")
"""      # 前の版の読み込みの確認と、入れるブランチ
PREP_PIP = f"""url = f"git+https://github.com/{REPO}.git@{{BRANCH}}"
for args in (["jasme-jats[ai,images,colab] @ " + url],                          # ツールと必要なライブラリ
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
"""      # ツールのインストール
PREP_VERSION = f"""# 版の表示は別のプロセスで行う（ここで読み込むと、次に手順 1 を実行したときに「前の版が残っている」扱いになるため）
ver = subprocess.run([sys.executable, "-c", "from jasme_jats.pipeline import tool_version; print(tool_version())"],
                     capture_output=True, text=True).stdout.strip()
if not ver:
    raise SystemExit("ツールを読み込めませんでした。メニューの「ランタイム」→「セッションを再起動」を選んでから、手順 1 からもう一度実行してください。")
print("準備ができました。ツールの版:", ver)
if BRANCH != "main":
    print("※ 開発版（ブランチ", BRANCH, "）を使っています。")
if not ver.startswith("{VERSION}"):
    # ノートブックとツールの版が違うと、後の手順がツールにない機能を呼んで止まる。正式版（main）のときは、ここで止めて開き直してもらう
    mismatch = "入ったツールの版（" + ver + "）が、このノートブックの版（{VERSION}）と違います。"
    if BRANCH != "main":
        print("※ " + mismatch + "手順の説明や画面が合わないことがあります。")
    else:
        raise SystemExit(mismatch + "ノートブックを GitHub（https://github.com/{REPO}）の main から開き直して、手順 1 からやり直してください。"
                         "開発中の版のノートブックを試しているときは、「開発版を使う（USE_DEV_VERSION）」にチェックを入れて、"
                         "そのブランチ名を入力してください。")
"""      # 入った版の表示と確認
PREP = PREP_PARAMS + PREP_BRANCH + PREP_PIP + PREP_VERSION      # 手順 1（準備）のセル


cells = [
    md(f"""
# 論文 docx → J-STAGE 全文 XML 変換（全国数学教育学会誌『数学教育学研究』）

**ツールの版: {VERSION}**{VERSION_NOTE}

論文の Word ファイル（.docx）を、J-STAGE の全文 XML（JATS 1.1）に変換します。パソコンに何かをインストールする必要はありません。
**上から順に、各セルの左の ▶ を押してください**（前の手順の実行が終わってから、次の ▶ を押します）。手順 6 は手動モードのときだけ、手順 7 は画像の要る図・表があるときに使います。

説明書: [使い方・結果の見方・できないこと]({DOCS}/USAGE.md)　[AI の API キーと手動モード]({DOCS}/USAGE_AI.md)　ソースコード: https://github.com/{REPO}
"""),
    code(PREP + "DONE = {1}\n"),
    code("""
#@title 2. 作り方を選び、論文の docx と PDF をアップロード
#@markdown **ROUTE**（作り方）: 「docx から作り、出版版 PDF で補う」は、Word の文字を正として、出版版 PDF から著者校正の直しと組版の違い（全角・半角・ダッシュ・引用符など）を補った docx（Word の変更履歴つき）を作ってから変換します（PDF が必要）。「docx から作る」は docx の文字のまま変換します（PDF がまだないときはこちら）。違いは説明書の「出版版 PDF との照合と、2 通りの作り方」。
ROUTE = "docx から作り、出版版 PDF で補う"  #@param ["docx から作り、出版版 PDF で補う", "docx から作る"]
#@markdown **UPLOAD_PDF**: J-STAGE に登載する PDF もアップロードします。PDF がまだないときはチェックを外し、作り方を「docx から作る」にします。
UPLOAD_PDF = True  #@param {type:"boolean"}
""" + guard(1) + unmark(2) + """
from pathlib import Path
from google.colab import files

ROUTE_KEY = {"docx から作る": "docx", "docx から作り、出版版 PDF で補う": "pdf", "出版版 PDF に合わせてから作る": "pdf"}[ROUTE]
if ROUTE_KEY == "pdf" and not UPLOAD_PDF:
    raise SystemExit("「docx から作り、出版版 PDF で補う」には PDF が必要です。UPLOAD_PDF にチェックを入れるか、PDF がまだないときは"
                     "作り方（ROUTE）を「docx から作る」にして、もう一度この手順を実行してください。")
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
if ROUTE_KEY == "pdf" and not pdf_path:
    raise SystemExit("「docx から作り、出版版 PDF で補う」には PDF が必要です。もう一度この手順を実行し、PDF を選んでください"
                     "（PDF がまだないときは、作り方（ROUTE）を「docx から作る」にしてから実行します）。")
print()
print("作り方:", ROUTE)
print("論文:", docx_path.name)
print("PDF :", pdf_path.name if pdf_path else "（なし。J-STAGE への登載には PDF が必要です）")
""" + mark(2)),
    code("""
#@title 3. 書誌情報を入力
#@markdown 巻・号・ページは半角の英数字で。日付は 2026-03-31 の形で（2026/3/31 でもかまいません）。分からない項目は空欄にします。
#@markdown ***
#@markdown **巻（volume）・号（issue）・最初のページ（first_page）・最後のページ（last_page）**
volume = ""  #@param {type:"string"}
issue = ""  #@param {type:"string"}
first_page = ""  #@param {type:"string"}
last_page = ""  #@param {type:"string"}
#@markdown ***
#@markdown **査読の有無（peer_review）**（必須）・**最終査読日（last_review_date）**（査読ありで、分かれば）
peer_review = "（選んでください）"  #@param ["（選んでください）", "査読あり", "査読なし"]
last_review_date = ""  #@param {type:"string"}
#@markdown ***
#@markdown **キーワード**（任意。「;」か「；」で区切る。日・英あわせて 100 個まで）: **日本語（keywords_ja）・英語（keywords_en）**
keywords_ja = ""  #@param {type:"string"}
keywords_en = ""  #@param {type:"string"}
#@markdown ***
#@markdown **発行日（pub_date）・J-STAGE 公開日（jstage_release_date）・受付日（received）・受理日（accepted）**
pub_date = ""  #@param {type:"string"}
jstage_release_date = ""  #@param {type:"string"}
received = ""  #@param {type:"string"}
accepted = ""  #@param {type:"string"}
#@markdown ***
#@markdown **DOI（doi）**（空欄なら 10.24529/jasme.巻.号_開始ページ）・**原稿種別（manuscript_type）**・**その他の原稿種別（subject_other・subject_other_en）**（原稿種別で「その他」を選んだときだけ、日本語・英語で）・**責任著者が何番目の著者か（corresponding_author）**（例: 1。複数なら「1,2」）
doi = ""  #@param {type:"string"}
""" + TYPE_PARAM + """subject_other = ""  #@param {type:"string"}
subject_other_en = ""  #@param {type:"string"}
corresponding_author = ""  #@param {type:"string"}
""" + guard(1, 2) + unmark(3) + """if peer_review not in ("査読あり", "査読なし"):
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
for _note in _meta.input_notes:   # 全角の数字を半角にしたなど
    print("※", _note)
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
#@title 4. AI による仕上げの方法を選ぶ
#@markdown **AI_MODE**: AI による仕上げ（図・表の位置合わせ・リンクの取りこぼしの確かめなど）は、強く推奨します。どちらの方法でも、AI に出版版 PDF を渡すと（強く推奨）、図・表を出版版と同じ位置に置けます。**「手動（チャットに貼り付け）」**（初期値）は API キーが要りません。手順 5 に出る依頼文を、出版版 PDF を添付してチャット（claude.ai など）に送り、返ってきた回答を手順 6 で貼り戻します。はじめて使うときや、論文が少ないときに向きます。**「API で自動実行（Claude）」**は、貼り付けの手間がなく、何本も続けて変換するときに向きます（PDF も自動で送ります）。左の 🔑（シークレット）に API キー（名前 `ANTHROPIC_API_KEY`）を登録し、「ノートブックからのアクセス」をオンにしておきます（利用料がかかります。""" + COST_NOTE + """）。API で使う AI は Claude を推奨します（ChatGPT・Gemini・Sakana AI は動作を確かめていません）。「使わない」では、位置を決められない図・表を、結び付いた段落の後ろに置きます。登録のしかた・料金・手動の手順は説明書の [AI の API キーと手動モード](""" + DOCS + """/USAGE_AI.md)。
AI_MODE = "手動（チャットに貼り付け）"  #@param ["使わない", "API で自動実行（Claude）", "API で自動実行（ChatGPT）", "API で自動実行（Gemini）", "API で自動実行（Sakana AI）", "手動（チャットに貼り付け）"]
#@markdown **MODEL**（Claude のモデル。通常は変更不要）・**OTHER_MODEL**（ChatGPT・Gemini・Sakana AI のときは必ず入力。各社の最上位クラスのモデルを推奨）・**SPLIT_LABELS**（図表番号「図1」を <label> 要素に分ける。既定は分けない）
""" + MODEL_LINE + """OTHER_MODEL = ""  #@param {type:"string"}
SPLIT_LABELS = False  #@param {type:"boolean"}
""" + guard(1, 2, 3) + unmark(4) + """AI = "api" if AI_MODE.startswith("API") else {"使わない": "none", "手動（チャットに貼り付け）": "manual"}[AI_MODE]
PROVIDER = {"API で自動実行（ChatGPT）": "openai", "API で自動実行（Gemini）": "gemini",
            "API で自動実行（Sakana AI）": "sakana"}.get(AI_MODE, "claude")
if PROVIDER == "claude":
    API_MODEL = "auto" if MODEL.startswith("自動") else MODEL.strip()
else:
    API_MODEL = OTHER_MODEL.strip()
    if not API_MODEL or API_MODEL.lower().startswith("claude"):
        raise SystemExit("Claude 以外を使うときは、Claude 以外のモデル名（OTHER_MODEL）の欄に、使うモデルの名前を入力してください"
                         "（Claude Opus と同等以上の性能のモデルを推奨します。モデル名は各社の資料で確認してください）。")
print("AI による仕上げ:", AI_MODE + (f"（モデル: {API_MODEL}）" if AI == "api" else ""))
if PROVIDER != "claude":
    print("※ 推奨は Claude です。API キーの作り方・料金などは各社の案内で確かめてください（説明書 USAGE_AI.md の 6.）。")
if PROVIDER == "sakana":
    from IPython.display import HTML, display
    from jasme_jats.colab import error_box
    display(HTML(error_box("Sakana AI は、既定で送信した内容をモデルの学習に使う設定です",
                           "未公開の原稿を送るので、手順 5 の前に、Sakana AI の管理画面（Console）の設定で"
                           "学習への利用を止めて（オプトアウトして）ください。")))
""" + mark(4)),
    code("""
#@title 5. 変換を実行
""" + guard(1, 2, 3, 4) + unmark(5) + """import shutil
from IPython.display import HTML, display
from jasme_jats.colab import ai_finish_of, prompt_box, report_details, result_boxes, structure_conflict_box, summary_box
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, StructureConflictError, convert, kept_images, reapply_images

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

OUT = WORK / "output"
# やり直しのときは、前の変換で入れた画像（手順 7）を覚えておき、変換の後に同じ図へ入れ直す（変更した図には入れない）
KEPT = kept_images(res) if globals().get("res") is not None else {}
shutil.rmtree(OUT, ignore_errors=True)
journal = JournalConfig.load()
meta = ArticleMeta.from_dict(meta_input)
try:
    res = convert(docx_path, meta, journal, Options(out_dir=OUT, ai_mode=AI, ai_provider=PROVIDER, ai_model=API_MODEL,
                                                  ai_api_key=api_key, pdf_path=pdf_path, route=ROUTE_KEY,
                                                  split_labels=SPLIT_LABELS, ai_cache=globals().get("AI_CACHE")))
except StructureConflictError as e:
    display(HTML(structure_conflict_box(str(e))))
    raise SystemExit("上の赤い枠のとおり Word で原稿を直して保存し、手順 2 から選び直してやり直してください。")
if AI == "api" and res.ai_answer_path:
    # API の回答の写し（AI回答.json）を覚えておく。出力フォルダは毎回消すので、変数に持ち、同じ依頼・同じモデルで変換し直すときは
    # API を呼ばずに使う（画像を入れただけ・書誌を直しただけのやり直しで料金がかからない）
    AI_CACHE = res.ai_answer_path.read_text(encoding="utf-8")
if KEPT:
    _again = reapply_images(res, KEPT)
    if _again:
        print(f"前に入れた画像 {len(_again)} 枚を入れ直しました。")
# 要対応（赤）・要確認（黄）・手順（青）の枠（report.actions）。手動モードの AI による仕上げ（回答待ち）は、下の依頼文の枠があるので出さない
display(HTML(result_boxes(res, skip=("ai_finish",) if AI == "manual" else ())))
manual_prompt = None
if AI == "manual" and res.prompt_path:
    # 依頼文は、要対応・要確認・必須の手順の枠の後ろ（推奨の手順を必須の手順より先に出さない。1 画面版と同じ順）、レポートの前に
    # 目立つ枠で出す（見出しと説明は推奨の手順 ai_finish のもの。PDF を添付して送る案内つき）
    manual_prompt = res.prompt_path.read_text(encoding="utf-8")
    display(HTML(prompt_box(manual_prompt, ai_finish_of(res), "notebook", res.pdf_name)))
display(HTML(summary_box(res)))
display(HTML(report_details(res.report_path.read_text(encoding="utf-8"))))
""" + mark(5)),
    md(f"""
### 6.（手動モードのときだけ）AI の回答を貼り付けて再変換

手動モードで、AI の回答を使うときに行います（任意。このまま登載することもできますが、位置を聞かれた図・表は、出版版 PDF を添えた回答で PDF と同じ位置に置けます）。
チャットの回答（`json` のコードブロック）を右上のコピーボタンでコピーし、下のセルの `r'''` と `'''` の間に貼り付けてから ▶ を押します。
回答を読めないときの対処: 説明書の [AI の API キーと手動モード]({DOCS}/USAGE_AI.md) の 7.
"""),
    code("""
AI_RESPONSE = r'''
ここに AI の回答を貼り付ける
'''

""" + guard(1, 2, 3, 4, 5) + """if AI != "manual":
    raise SystemExit("この手順は手動モードのときだけ使います。手順 4 で「手動（チャットに貼り付け）」を選び、手順 5 からやり直してください。")
if not AI_RESPONSE.strip() or "ここに AI の回答を貼り付ける" in AI_RESPONSE:
    raise SystemExit("AI の回答が貼り付けられていません。上の r''' と ''' の間に貼り付けてから実行してください。")
# 前の論文・図表や文献の並びが違う原稿への回答は、変換の中で依頼の番号で確かめて使わない（「失敗」として枠に出る）
""" + unmark(5) + """KEPT = kept_images(res) if globals().get("res") is not None else {}      # 手順 7 で入れた画像があれば覚え、変換の後に同じ図へ入れ直す
try:
    res = convert(docx_path, meta, journal, Options(out_dir=OUT, ai_mode="manual", ai_response=AI_RESPONSE,
                                                  pdf_path=pdf_path, route=ROUTE_KEY, split_labels=SPLIT_LABELS))
except StructureConflictError as e:     # 手順 5 で確かめ済みなので通常は来ない（守り）
    display(HTML(structure_conflict_box(str(e))))
    raise SystemExit("上の赤い枠のとおり Word で原稿を直して保存し、手順 2 から選び直してやり直してください。")
if KEPT:
    _again = reapply_images(res, KEPT)
    if _again:
        print(f"前に入れた画像 {len(_again)} 枚を入れ直しました。")
display(HTML(result_boxes(res)))      # 要対応（赤）・要確認（黄）・手順（青）の枠（report.actions）
display(HTML(summary_box(res)))
display(HTML(report_details(res.report_path.read_text(encoding="utf-8"))))
""" + mark(5), form=False),
    code("""
#@title 7. 図の画像を入れる
#@markdown 画像の要る図・表があるときは、毎回この手順を行います。▶ を押すと、画像の要る図・表の一覧が出ます。出版版 PDF から図の部分だけを切り取った画像（PNG か JPEG。キャプションの行は写さない）を用意し、「まとめてアップロード」で選びます（ファイル名を fig04.png・図4.png のようにしておくと、名前で合わせます）。名前で合わなかった画像は、図ごとに選び直せます。キャプションのない画像を入れないときは、NO_IMAGE に名前（img3fa9c2 など。コンマ区切り）を書いてから ▶ を押します。全部入れた後に、入れた画像を差し替えるときは、REPLACE にチェックを入れてから ▶ を押し、差し替える画像を名前（fig04.png など）を付けてアップロードします（差し替えたら、チェックを外します）。
NO_IMAGE = ""  #@param {type:"string"}
REPLACE = False  #@param {type:"boolean"}
""" + guard(1, 2, 3, 4, 5) + unmark(7) + """import re
from IPython.display import HTML, display
from jasme_jats.colab import error_box, missing_images_box
from jasme_jats.images import match_names
from jasme_jats.imagelist import check_frame
from jasme_jats.pipeline import add_images
from jasme_jats.report import clash_images_text, image_rows, images_action, unmatched_image_text

_slots = [_row for _row in image_rows(res) if _row.kind != "optional"]
if not _slots and images_action(res) is None:
    print("入れる画像はありません。手順 8 に進んでください。")
else:
    display(HTML(check_frame(res)))      # 画像の要る図・表の一覧（入れた画像も出る）
_skip = [_n.strip() for _n in re.split(r"[,、，\\s]+", NO_IMAGE) if _n.strip()]
_nocaps = [_row.key for _row in _slots if _row.kind == "nocap"]
_bad = [_n for _n in _skip if _n not in _nocaps]      # アップロードの前に確かめる（書き違いで、選んだ画像が全部入らないことにならないように）
if _bad:
    display(HTML(error_box("NO_IMAGE を直してください（何も入れていません）",
                           f"NO_IMAGE の {'、'.join(_bad)} は、この論文のキャプションのない画像の名前ではありません"
                           f"（キャプションのない画像: {'、'.join(_nocaps) or 'なし'}）。NO_IMAGE を直してから、もう一度 ▶ を押してください。")))
_supplied = {}
if not _bad and (REPLACE or any(_row.status == "missing" and _row.key not in _skip for _row in _slots)):
    print("▼ " + ("差し替える" if REPLACE else "図の") + "画像をまとめて選んでください（複数選べます。ファイル名が fig04.png・図4.png のような名前の画像を、名前で図に合わせます。"
          "用意できていなければキャンセル）")
    _up = files.upload()
    # 任意の置き場所（画像で補える文字。一覧と手順の数には出さない）も、名前が合えば入れる
    _found, _unmatched, _clashes = match_names(list(_up), image_rows(res), res.meta.article_id(res.journal))
    _supplied = {_key: (_name, _up[_name]) for _key, _name in _found.items()}
    for _name in _unmatched:
        print("  " + unmatched_image_text(res, _name, "ファイル名を直すか、下で図ごとに選んでください。"))
    for _key, _names in _clashes:
        print("  " + clash_images_text(_key, _names))
    for _row in _slots:
        if _row.status != "missing" or _row.key in _supplied or _row.key in _skip:
            continue
        _what = (_row.label + " " if _row.label else "") + (_row.caption.strip()[:30] or "キャプションのない画像（" + _row.where + "）")
        print(f"▼ {_what} の画像を選んでください（{_row.key}。用意できていなければキャンセル）")
        _one = files.upload()
        if not _one:
            print("  選ばれなかったので飛ばします")
            continue
        if len(_one) > 1:
            print("  ファイルが複数選ばれたので、最初の 1 つだけを使います")
        _file, _data = next(iter(_one.items()))
        _supplied[_row.key] = (_file, _data)
if not _bad and (_supplied or _skip):
    try:
        _added = add_images(res, _supplied, skip=_skip or None)
    except ValueError as e:
        display(HTML(error_box("画像を入れられませんでした（1 枚も入れていません）", str(e))))
    else:
        if _added:
            print(f"画像を {len(_added)} 枚入れ、{res.zip_path.name} とレポートを作り直しました。")
        if _skip:
            print("画像を入れないことにしました:", "、".join(_skip))
        if REPLACE:
            print("差し替えが済んだら、REPLACE のチェックを外してください。")
    display(HTML(check_frame(res)))      # 確かめの一覧（図番号・キャプションと画像が合っているか）
_act = images_action(res)
if _act is not None:
    if missing_images_box(res):
        display(HTML(missing_images_box(res)))      # 残っているとき（または持ち越しの確かめ）の青い枠
    if _act.done:
        print(_act.progress + "。上の一覧で、図番号・キャプションと画像が合っているか確かめてから、手順 8 に進んでください。")
""" + mark(7)),
    code("""
#@title 8. 結果をダウンロード
#@markdown 「変換結果_巻_開始ページ.zip」（J-STAGE にアップロードする jasme_巻_開始ページ.zip、XML、変換レポート、図の確かめ.html〈ZIP を展開すると、入れた画像も見えます〉。「docx から作り、出版版 PDF で補う」では（PDF の文字を読めたとき）PDF で補った docx も）をダウンロードします。要対応（赤い枠）が残っていると一度止まります（そのままダウンロードするときは、もう一度 ▶）。
""" + guard(1, 2, 3, 4, 5) + unmark(8) + """import shutil
from IPython.display import HTML, display
from jasme_jats.colab import result_boxes
from jasme_jats.report import actions, blocking

_todo = blocking(actions(res))      # 止める知らせ（要対応と、残っている必須の手順。推奨の手順は止めない）
# 止めたかどうかの記録。止める知らせの中身（枠の見出しと本文）が変われば、変換し直した同じ docx でももう一度止める
_key = str(docx_path) + "|" + repr([(a.key, a.box_title, a.box_detail) for a in _todo])
if _todo and globals().get("_NEEDS_ACTION_OK") != _key:
    _NEEDS_ACTION_OK = _key
    display(HTML(result_boxes(res, blocking=True)))
    raise SystemExit(f"残っていることが {len(_todo)} 件あります（上の枠: " + "／".join(a.box_title for a in _todo) + "）。"
                     + ("図の画像は、手順 7 で入れてから、もう一度この ▶ を押してください。" if any(a.key == "images" for a in _todo) else "")
                     + "枠の説明に従って直してから変換し直すか、このままダウンロードするときは（結果を確かめるときなど）、"
                       "もう一度この ▶ を押します。")
archive = shutil.make_archive(str(WORK / f"変換結果_{res.xml_path.stem}"), "zip", OUT)
files.download(archive)
CONVERTED = {**globals().get("CONVERTED", {}), Path(archive).name: docx_path.name}
print("ダウンロードしました:", Path(archive).name, "（" + docx_path.name + "）")
display(HTML(result_boxes(res)))      # ダウンロードした結果に残っている要対応・要確認・手順
print("続けて他の論文を変換するときは、下の手順 9 の ▶ を押してください。")
""" + mark(8)),
    code("""
#@title 9. 続けて他の論文を変換する
#@markdown 手順 8 の後に ▶ を押すと、手順 2 から次の論文を始められます（手順 1 はやり直しません）。手順 3 などの入力欄には前の論文の値が残るので、今回の論文のものに書き換えてください。
""" + guard(1) + """import shutil
from pathlib import Path
from IPython.display import HTML, display
from jasme_jats.colab import next_article_box

if 5 in DONE and 8 not in DONE and globals().get("_DISCARD_OK") != str(globals().get("docx_path")):
    _DISCARD_OK = str(globals().get("docx_path"))
    raise SystemExit(f"この論文（{docx_path.name}）の結果を、まだダウンロードしていません。手順 8 でダウンロードしてから、"
                     "もう一度この ▶ を押してください。ダウンロードせずに次の論文へ進むときは、そのままもう一度この ▶ を押します。")
if "docx_path" in globals():
    PREVIOUS = {"docx": docx_path.name, "meta": dict(globals().get("meta_input") or {})}
for _name in ("docx_path", "pdf_path", "meta_input", "meta", "res", "manual_prompt", "_DISCARD_OK",
              "_SAME_PAGE_OK", "KEPT", "_NEEDS_ACTION_OK"):
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



# 1 画面版（Gradio。一般の利用者用）: 準備と画面を 1 つのセルにする。pip をして画面を開く。2 回目の実行（画面を開き直すとき）は
# ツールを入れ直さない（入れ直しには、セッションの再起動が要るため）
_gradio_prep = PREP_PIP + PREP_VERSION
for _old, _new in (("手順 1 からもう一度実行", "このセルをもう一度実行"), ("手順 1 からやり直して", "このセルからやり直して"),
                   ("次に手順 1 を実行したときに", "次にこのセルを実行したときに")):
    assert _old in _gradio_prep, _old
    _gradio_prep = _gradio_prep.replace(_old, _new)
_gradio_prep = _gradio_prep.replace("jasme-jats[ai,images,colab]", "jasme-jats[ai,images,colab,gui]")
_GRADIO_CELL = (PREP_PARAMS.replace("#@title 1. 準備（最初に 1 回だけ。1 分ほどかかります）", "#@title 準備して画面を開く（2 分ほどかかります）")
                + PREP_BRANCH
                + """if loaded_before:
    print("ツールは入っているので、画面を開き直します（新しい版を入れるときは、メニューの「ランタイム」→「セッションを再起動」を"
          "選んでから、このセルを実行します）。")
else:
"""
                + textwrap.indent(_gradio_prep, "    ")
                + """from jasme_jats.app import launch
if globals().get("_app") is not None:
    _app.close()                      # 開き直し
_app = launch()
""")
cells_gradio = [
    md(f"""
# 論文 docx → J-STAGE 全文 XML 変換（全国数学教育学会誌『数学教育学研究』）

**ツールの版: {VERSION}**{VERSION_NOTE}

論文の Word ファイル（.docx）を、J-STAGE の全文 XML（JATS 1.1）に変換します。パソコンに何かをインストールする必要はありません。
下のセルの ▶ を押すと、ツールの準備（2 分ほど）のあと、その下に画面が開きます。画面に docx と PDF、書誌情報を入れて「変換する」を押します。
メニューの「表示」でサイドバーなどを閉じると広く使えます。手順ごとにセルを実行する従来版のノートブックは、説明書の「使い方」にあります。

説明書: [使い方・結果の見方・できないこと]({DOCS}/USAGE.md)　[AI の API キーと手動モード]({DOCS}/USAGE_AI.md)　ソースコード: https://github.com/{REPO}
"""),
    code(_GRADIO_CELL),
]


BRANCH_LINE = 'BRANCH = "main"'


def notebook_branch(text: str) -> str:
    """ノートブック（JSON の文字列）の手順 1 が、既定でどのブランチからツールを入れるかを読む。"""
    m = re.search(r'BRANCH = \\"([^\\"]+)\\"', text)
    return m.group(1) if m else "main"


def render(branch: str = "main") -> str:
    """ノートブックの JSON を作る。branch は手順 1 が既定で入れるブランチ（開発中の版のノートブックは、そのブランチ名で作る）。"""
    return _notebook(cells, branch)


def render_gradio(branch: str = "main") -> str:
    """1 画面版（Gradio）のノートブックの JSON を作る。branch は render と同じ。"""
    return _notebook(cells_gradio, branch)


def _notebook(cell_list, branch: str = "main") -> str:
    if branch != "main":
        # 手順 1 の BRANCH = "main" を置き換える（開発版のチェックを入れなくても、そのブランチのツールが入る）
        assert sum(line.count(BRANCH_LINE) for c in cell_list for line in c["source"]) == 1
        cell_list = [dict(c, source=[line.replace(BRANCH_LINE, f'BRANCH = "{branch}"') for line in c["source"]])
                     for c in cell_list]
    nb = {
        "nbformat": 4, "nbformat_minor": 0,
        "metadata": {"colab": {"provenance": [], "toc_visible": True},
                     "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}},
        "cells": cell_list,
    }
    return json.dumps(nb, ensure_ascii=False, indent=1) + "\n"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Colab ノートブックを生成する")
    ap.add_argument("--branch", default="main",
                    help="手順 1 が既定でツールを入れるブランチ（既定 main）。開発中の版のノートブックを、そのブランチから"
                         "入れる形で作るときに指定する。main に反映するときは指定しない（main から入れる形に戻す）")
    a = ap.parse_args()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(a.branch), encoding="utf-8")
    print("written:", OUT, "" if a.branch == "main" else f"（手順 1 はブランチ {a.branch} から入れる）")
    OUT_GRADIO.write_text(render_gradio(a.branch), encoding="utf-8")
    print("written:", OUT_GRADIO)
