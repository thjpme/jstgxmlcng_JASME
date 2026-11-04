"""Gradio による 1 画面の操作画面（一般の利用者用。docs/GUI_PLAN.md の 4 章・8 章）。

2 層に分ける。
  - AppState: 入力と結果を持ち、「変換を押せるか」「要対応が残っているか」「回答待ちか」「足りない画像」などを決める。
    Gradio に依存しない純粋な Python。変換は pipeline.convert() を呼ぶだけで、docx の文字には触れない。
  - build_app(state, io): gr.Blocks を組み立て、ボタンの処理を AppState につなぐ。Colab に依存する操作（シークレットの読み出し・
    LibreOffice の待ち合わせ）は io に切り出す（テストでは偽物を渡す）。

知らせは report.actions() から colab.result_boxes(screen="app") で出す（文の中の画面の操作は、この画面の欄の名前に置き換わる）。この画面に個別の表示は足さない（docs/DEVELOPMENT.md の原則 8）。
未公開の原稿を Gradio の中継サーバーに通さないため、launch() の share は必ず False。
Gradio の版は pyproject の gui の extra で固定している（上げるときは人が Colab で確かめてから）。
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from . import __version__
from . import report as rp
from .ai_assist import API_KEY_NAMES, DEFAULT_MODEL
from .colab import (ANSWER_LABEL, APPLY_LABEL, CONVERT_LABEL, ai_required_box, error_box, no_ai_box, report_details, result_boxes,
                    step_text, summary_box)
from .config import ArticleMeta, JournalConfig, keyword_language_mismatch, keyword_problem
from .pipeline import AIRequiredError, Options, add_images, convert
from .report import NEEDS_ACTION, actions, ai_pending, images_to_prepare

DOCS = "https://github.com/thjpme/jstgxmlcng_JASME/blob/main/docs/USAGE.md"
MAX_IMAGE_SLOTS = 30          # 足りない画像の欄の数（最初から作って、足りない図の数だけ見せる）。これより多い分は「画像を入れる」の後に出る

# 画面の入力欄。名前は AppState.inputs の鍵で、画面の部品の並びもこの順（INPUT_NAMES）
ROUTES = [("docx から作り、出版版 PDF で補う", "pdf"), ("docx から作る", "docx")]
AI_MODES = [("使わない（推奨しません）", "none"), ("手動（チャットに貼り付け）", "manual"), ("API（Claude）", "api")]
PEER_REVIEWS = ["査読あり", "査読なし"]
AUTO_MODEL = "自動（最新の Opus）"
OTHER_TYPE = "その他"
DEFAULTS = {
    "route": "pdf", "docx": None, "pdf": None,
    "volume": "", "issue": "", "fpage": "", "lpage": "", "peer_review": None, "manuscript_type": None,
    "approved": "", "keywords_ja": "", "keywords_en": "", "pub_date": "", "epub_date": "", "received": "", "accepted": "",
    "corresp": "", "doi": "", "subject_other": "", "subject_other_en": "",
    "ai_mode": "manual", "model": DEFAULT_MODEL, "split_labels": False,
}
INPUT_NAMES = list(DEFAULTS)
# 次の論文のために空にする項目（巻・号・査読の有無・原稿種別・AI の設定は残す）
PER_ARTICLE = ("docx", "pdf", "fpage", "lpage", "approved", "keywords_ja", "keywords_en", "pub_date", "epub_date", "received",
               "accepted", "corresp", "doi", "subject_other", "subject_other_en")
LABELS = {"docx": "docx", "pdf": "PDF", "volume": "巻", "issue": "号", "fpage": "最初のページ", "lpage": "最後のページ",
          "peer_review": "査読の有無", "manuscript_type": "原稿種別", "approved": "最終査読日", "keywords_ja": "キーワード（日本語）",
          "keywords_en": "キーワード（英語）", "pub_date": "発行日", "epub_date": "J-STAGE 公開日", "received": "受付日",
          "accepted": "受理日", "corresp": "責任著者", "doi": "DOI", "subject_other": "原稿種別（日本語）",
          "subject_other_en": "原稿種別（英語）"}


class InputError(Exception):
    """入力の誤り・足りない項目など、利用者に直してもらうこと。html があれば、その枠を出す（なければ赤い枠にメッセージを入れる）。"""

    def __init__(self, message: str, html: str = ""):
        super().__init__(message)
        self.html = html


def type_choices() -> list:
    """原稿種別の選択肢（「日本語 / English」と「その他」）。"""
    return [f"{ja} / {en}" for ja, en in JournalConfig.load().manuscript_types.items()] + [OTHER_TYPE]


# ---------------------------------------------------------------------------- Colab に依存する操作
class IO:
    """既定の io: API キーを環境変数から読む。LibreOffice は待たない。"""

    def read_secret(self, names) -> "str | None":
        for name in names:
            value = os.environ.get(name)
            if value:
                return value
        return None

    def libreoffice_ready(self) -> None:
        """LibreOffice のインストールが終わるのを待つ（既定では何もしない）。"""


class ColabIO(IO):
    """Colab 用の io: シークレット（google.colab.userdata）を読む。LibreOffice は準備のセルが裏で入れているので終わるのを待つ。"""

    def read_secret(self, names) -> "str | None":
        from google.colab import userdata      # Colab でないときは使わないので、ここで import する
        for name in names:
            try:
                value = userdata.get(name)
            except Exception:                  # 未登録・アクセスを許可していない
                continue
            if value:
                return value
        return None

    def libreoffice_ready(self) -> None:
        import __main__
        proc = getattr(__main__, "LO_PROC", None)      # 準備のセルが裏で起動したインストール（tools/make_notebook.py）
        if proc is not None and proc.poll() is None:
            proc.wait()


# ---------------------------------------------------------------------------- 状態
def _app_text(text: str) -> str:
    """目印（report.step）を 1 画面版の語に置き換える（colab.STEP_WORDS の "app"）。"""
    return step_text(text, "app")


class AppState:
    """画面の入力と結果。Gradio に依存しない。"""

    def __init__(self, work: "Path | str | None" = None):
        self.work = Path(work) if work else Path(tempfile.mkdtemp(prefix="jasme_work_"))
        self.inputs = dict(DEFAULTS)
        self.res = None
        self.notes: list = []                  # 入力を確かめたときの知らせ（全角の数字を半角にしたなど）
        self.user_images: dict = {}            # 足りない画像: 出力ファイル名 → (元のファイル名, 中身)
        self._meta = None
        self._journal = None
        self._api_key = None

    @property
    def out_dir(self) -> Path:
        return self.work / "output"

    # ---- 入力
    def set_inputs(self, **values) -> None:
        for name, value in values.items():
            if name not in DEFAULTS:
                raise KeyError(name)
            self.inputs[name] = value

    def missing(self) -> list:
        """変換を押すのに足りない必須項目の名前（空なら押せる）。"""
        f = self.inputs
        need = ["docx"] + (["pdf"] if f["route"] == "pdf" else []) + ["volume", "issue", "fpage", "lpage", "peer_review",
                                                                        "manuscript_type"]
        out = [LABELS[k] for k in need if not str(f[k] or "").strip()]
        if f["manuscript_type"] == OTHER_TYPE:
            out += [LABELS[k] for k in ("subject_other", "subject_other_en") if not str(f[k] or "").strip()]
        return out

    def can_convert(self) -> bool:
        return not self.missing()

    def _article_meta(self) -> ArticleMeta:
        """入力から ArticleMeta を作る。誤りは InputError（ノートブックの手順 3 と同じ確かめ）。"""
        f = self.inputs
        miss = self.missing()
        if miss:
            raise InputError("次の項目が足りません: " + "、".join(miss))
        text = {k: str(f[k] or "").strip() for k in DEFAULTS if k not in ("docx", "pdf", "route", "split_labels")}
        if text["peer_review"] not in PEER_REVIEWS:
            raise InputError("査読の有無を選んでください。")
        if text["peer_review"] == "査読なし" and text["approved"]:
            raise InputError("査読なしのときは、最終査読日を空欄にしてください。")
        if text["manuscript_type"] == OTHER_TYPE:
            subject_ja, subject_en = text["subject_other"], text["subject_other_en"]
        else:
            subject_ja, subject_en = text["manuscript_type"].split(" / ", 1)
        meta_input = {"volume": text["volume"], "issue": text["issue"], "fpage": text["fpage"], "lpage": text["lpage"],
                      "peer_review": text["peer_review"], "approved": text["approved"],
                      "keywords_ja": text["keywords_ja"], "keywords_en": text["keywords_en"],
                      "pub_date": text["pub_date"], "epub_date": text["epub_date"], "received": text["received"],
                      "accepted": text["accepted"], "doi": text["doi"], "subject_ja": subject_ja, "subject_en": subject_en,
                      "corresp": text["corresp"]}
        try:
            meta = ArticleMeta.from_dict(meta_input)       # 日付の書き方などをここで確かめる
        except ValueError as e:
            raise InputError(f"入力を確認してください: {e}")
        if keyword_problem(meta):
            raise InputError(keyword_problem(meta) + "。")
        self.notes = list(meta.input_notes)
        if keyword_language_mismatch(meta):
            self.notes.append("日本語・英語の欄を取り違えていないか確認してください: " + "、".join(keyword_language_mismatch(meta)))
        return meta

    # ---- 変換
    def _run(self, ai_mode: str, ai_response: "str | None", progress=None):
        step = progress or (lambda fraction, desc="": None)
        f = self.inputs
        docx = Path(f["docx"])
        pdf = Path(f["pdf"]) if f["pdf"] else None
        (self.work / "input").mkdir(parents=True, exist_ok=True)
        local = self.work / "input" / docx.name       # 画面から受け取ったファイルは、元の名前で作業用の場所に置く
        if docx.resolve() != local.resolve():
            shutil.copyfile(docx, local)
        local_pdf = None
        if pdf:
            local_pdf = self.work / "input" / pdf.name
            if pdf.resolve() != local_pdf.resolve():
                shutil.copyfile(pdf, local_pdf)
        self.res = None                        # 出力フォルダを消すので、前の結果は先に捨てる（途中で止まったとき、消えたファイルを指さないため）
        shutil.rmtree(self.out_dir, ignore_errors=True)
        try:
            res = convert(local, self._meta, self._journal, Options(
                out_dir=self.out_dir, ai_mode=ai_mode, ai_provider="claude",
                ai_model="auto" if str(f["model"]).startswith("自動") else str(f["model"]).strip(),
                ai_api_key=self._api_key, ai_response=ai_response, pdf_path=local_pdf, route=f["route"],
                split_labels=bool(f["split_labels"])))
        except AIRequiredError as e:
            raise InputError(step_text(str(e), "app"), ai_required_box(str(e), "app"))
        step(0.9, "画像を入れ直しています…")
        if self.user_images:
            add_images(res, self.user_images, skip_unneeded=True)     # 変換をやり直したときに、受け取った画像を入れ直す
        self.res = res
        return res

    def convert(self, io: "IO | None" = None, progress=None):
        """「変換する」。足りない項目・入力の誤り・API キーの読み出し失敗は InputError。"""
        io = io or IO()
        step = progress or (lambda fraction, desc="": None)
        self._meta = self._article_meta()
        self._journal = JournalConfig.load()
        self._api_key = None
        if self.inputs["ai_mode"] == "api":
            names = API_KEY_NAMES["claude"]
            self._api_key = io.read_secret(names)
            if not self._api_key:
                raise InputError(f"API キー（シークレット {' または '.join(names)}）を読めませんでした。")
        self.res = None
        self.user_images = {}                  # 前の変換で受け取った画像は持ち越さない（同じ論文のやり直しは apply_answer）
        step(0.05, "LibreOffice を準備中…")
        io.libreoffice_ready()
        step(0.2, "変換中…（数分かかることがあります）")
        res = self._run(self.inputs["ai_mode"], None, progress)
        step(1.0, "完了")
        return res

    # ---- 手動モード
    @property
    def waiting_for_answer(self) -> bool:
        """手動モードで、AI の回答をまだ反映していない。"""
        return self.res is not None and self.inputs["ai_mode"] == "manual" and ai_pending(self.res)

    # 手動モードで、AI の回答を貼り付け直す案内（report.py の枠。colab.STEP_WORDS の repaste）が出る Action の key。これらが出ている
    # ときも、手動の欄（依頼文・回答の欄・「反映」）を見せたままにする。float_ref（リンクしなかった図・表の参照。AI の回答を反映した後も
    # AI がリンクを付けなかったとき、「AI に出し直してもらう」案内が貼り直しを勧める）・textbox_undecided（AI の回答を反映した後も
    # 囲みか注記か決められなかったテキストボックスがあるとき、同じく貼り直しを勧める）も入れる
    REPASTE_KEYS = ("ai_error", "partial", "forced", "float_ref", "textbox_undecided")

    @property
    def answer_box_open(self) -> bool:
        """手動の欄（依頼文・添付画像・回答の欄〈ANSWER_LABEL〉・「反映」）を見せるか。

        AI の回答をまだ反映していないとき（waiting_for_answer）に加えて、反映した後も、回答を読めない（ai_error）・途中で切れた
        （partial）・図表の位置が決まらない（forced）・AI もリンクを付けなかった図・表の参照がある（float_ref）の枠が出ているあいだは、
        貼り付け直せるように見せたままにする。
        回答の反映（apply_answer）ができるときだけ見せる（waiting_for_answer と同じく、「AI による補完の方法」の欄が手動のとき）。
        さらに、その結果が手動モードで作られたとき（依頼文があるとき）だけ見せる: AI を使っていない・API の結果のまま「AI による
        補完の方法」の欄だけを手動に切り替えても、空の依頼文と「反映」は出さない（変換し直すと出る）。
        """
        if self.res is None or self.inputs["ai_mode"] != "manual" or self.res.ai.mode != "manual" or not self.res.prompt_path:
            return False
        return ai_pending(self.res) or any(a.key in self.REPASTE_KEYS for a in actions(self.res))

    def prompt_text(self) -> str:
        if self.res is None or not self.res.prompt_path:
            return ""
        return self.res.prompt_path.read_text(encoding="utf-8")

    def attachments(self) -> list:
        """手動モードで依頼文と一緒に AI に渡す画像（AI添付画像/ の中）。"""
        folder = self.out_dir / "AI添付画像"
        return sorted(str(p) for p in folder.iterdir()) if folder.exists() else []

    def apply_answer(self, text: str, io: "IO | None" = None, progress=None):
        """AI の回答を付けて変換し直す。"""
        if self.res is None or self.inputs["ai_mode"] != "manual":
            raise InputError("手動モードで変換してから、回答を貼り付けてください。")
        if not (text or "").strip():
            raise InputError("AI の回答が貼り付けられていません。")
        (progress or (lambda fraction, desc="": None))(0.2, "回答を反映して変換し直しています…")
        return self._run("manual", text)

    # ---- 足りない画像
    def missing_images(self) -> list:
        """画像を用意する必要がある図: [(出力ファイル名, 図のキャプション, 理由)]。"""
        return images_to_prepare(self.res) if self.res is not None else []

    def image_slots(self) -> list:
        """画面に欄を出す図: missing_images() の先頭から MAX_IMAGE_SLOTS 件まで。"""
        return self.missing_images()[:MAX_IMAGE_SLOTS]

    @staticmethod
    def slot_label(name: str, caption: str) -> str:
        """欄のラベル: 「図のキャプション（出力ファイル名）」。キャプションがなければ出力ファイル名だけ。"""
        return f"{caption}（{name}）" if caption else name

    def images_markdown(self) -> str:
        rows = self.missing_images()
        if not rows:
            return ""
        lines = [f"次の図の画像が必要です（{len(rows)} 件）。図ごとにファイルを選んで「画像を入れる」を押してください。"
                 "ファイル名は何でもかまいません。一部の図だけ入れてもよく、残りの図の欄は残ります。"]
        if len(rows) > MAX_IMAGE_SLOTS:
            lines.append(f"一度に出す欄は {MAX_IMAGE_SLOTS} 件までです。上の {MAX_IMAGE_SLOTS} 件を入れると、続きの欄が出ます。")
        lines += [f"{i}. {self.slot_label(name, cap)}" for i, (name, cap, _why) in enumerate(rows, 1)]
        return "\n".join(lines)

    def add_images(self, mapping: dict) -> list:
        """選んだ画像を、図ごとに入れる。mapping: 出力ファイル名 → ファイルのパス。戻り値: 入れた出力ファイル名。"""
        if self.res is None:
            raise InputError("先に変換してください。")
        chosen = {name: Path(p) for name, p in (mapping or {}).items() if p}
        if not chosen:
            raise InputError("画像が選ばれていません。")
        supplied = {name: (p.name, p.read_bytes()) for name, p in chosen.items()}
        try:
            added = add_images(self.res, supplied)
        except ValueError as e:
            raise InputError(str(e))
        self.user_images.update(supplied)
        return added

    # ---- 想定外のエラー
    def report_location(self) -> str:
        """変換レポート（Markdown）の場所。なければ空文字。"""
        if self.res is not None and self.res.report_path.exists():
            return str(self.res.report_path)
        found = sorted(self.out_dir.glob("*_変換レポート.md")) if self.out_dir.exists() else []
        return str(found[0]) if found else ""

    # 操作ごとの案内（crash の operation）。入力や、貼り付けた回答・入れた画像を消す操作を勧めない。欄・ボタンの名前は、目印（report.step）で
    # 書いて colab.STEP_WORDS の 1 画面版の語に置き換える（文の中に欄の名前を直接書かない）
    CRASH_ADVICE = {
        "convert": _app_text("入力（" + rp.step("docx") + "・" + rp.step("pdf") + "・" + rp.step("meta") + "）が正しいかを確かめ、直してから、"
                             + rp.step("convert_again") + "してください。同じ例外で止まるときは、入力を変えずに、開発者に知らせてください。"),
        "apply": _app_text("反映の途中で止まったため、前の結果は捨てており、手動の欄（" + rp.step("prompt") + "・" + rp.step("answer_field") + "・"
                           + rp.step("apply_button") + "）は今は隠れています。" + rp.step("convert_again") + "すと、AI の回答を反映する前の結果と"
                           "手動の欄が戻り、貼り付けた回答も" + rp.step("answer_field") + "に残っています。欄が戻ったら、念のため回答を別の場所にも"
                           "保存してください。同じ例外で止まるときは、入力は変えずに、開発者に知らせてください。"),
        "images": _app_text("入れた画像と変換の結果は、この画面に残っています。入力は変えず、" + rp.step("convert_again") + "さずに（押すと、"
                            "入れた画像が消えます）、開発者に知らせてください。"),
        "download": "変換の結果は、この画面に残っています。もう一度ダウンロードの操作をしてかまいません。同じ例外で止まるときは、"
                    "入力は変えずに、開発者に知らせてください。"}

    # 回答の反映の想定外のエラーで、前の結果がまだ残っているとき（変換に入る前に止まった）。手動の欄も、貼り付けた回答もそのまま
    CRASH_ADVICE_APPLY_KEPT = _app_text(
        "前の結果と手動の欄（" + rp.step("prompt") + "・" + rp.step("answer_field") + "・" + rp.step("apply_button") + "）は、この画面にそのまま残っています。"
        "貼り付けた回答も欄に残っています。同じ例外で止まるときは、入力は変えずに、開発者に知らせてください。")

    # ダウンロードの想定外のエラーで、出力フォルダが消えているとき（ZIP を作り直せない）。画面の結果は読めるが、同じ操作は同じ例外で止まる
    CRASH_ADVICE_FOLDER_GONE = _app_text(
        "画面の結果は読めますが、サーバー側の出力フォルダがないので、ダウンロードの操作をもう一度しても同じ例外で止まります。"
        "必要な内容をこの画面から控えてから、入力を確かめて" + rp.step("convert_again") + "してください。")

    def crash(self, error: Exception, operation: str = "convert") -> InputError:
        """想定外の例外（変換ツールの不具合の可能性）を、画面に出す赤い枠にする。例外の種類と文を載せ、操作（operation。
        convert・apply・images・download）に合った案内を付ける。案内は、そのときの画面の状態（結果が残っているか・手動の欄が見えるか・
        出力フォルダがあるか）に合わせる。

        変換レポートの場所は、サーバー側のパスで利用者が取り出せないので書かない。結果が残っているときは、この画面の
        「変換レポートの全文を見る」を添えるよう案内する。
        """
        if operation not in self.CRASH_ADVICE:
            raise ValueError(f"知らない操作: {operation}")
        report = self.report_location() if self.res is not None else ""
        advice = self.CRASH_ADVICE[operation]
        if operation == "apply" and self.res is not None:       # 前の結果を捨てる前に止まった: 手動の欄は見えたまま
            advice = self.CRASH_ADVICE_APPLY_KEPT
        if report:
            who = "この画面の「変換レポートの全文を見る」の内容と、この例外の文を添えて、開発者に知らせてください。"
        elif self.res is not None:      # 結果は画面に残っているが、出力フォルダ（変換レポートのファイル）が見つからない
            who = ("この画面の「変換レポートの全文を見る」の内容と、この例外の文を添えて、開発者に知らせてください"
                   "（サーバー側の出力フォルダが見つからず、変換レポートのファイルは取り出せません）。")
            if operation == "download":
                advice = self.CRASH_ADVICE_FOLDER_GONE
        else:
            who = "この例外の文を添えて、開発者に知らせてください（変換レポートは作られていません）。"
        message = f"{type(error).__name__}: {error}\n\n変換ツールの不具合の可能性があります。{who}\n{advice}"
        return InputError(message, error_box("想定外のエラーで止まりました", message))

    # ---- 結果とダウンロード
    @property
    def needs_action(self) -> bool:
        return self.res is not None and self.res.needs_action

    def todo_titles(self) -> list:
        return [a.box_title for a in actions(self.res) if a.level == NEEDS_ACTION] if self.res is not None else []

    def result_html(self) -> str:
        """結果の HTML: 要対応・要確認の枠 → 結果の要約 → レポート全文（畳む）。"""
        if self.res is None:
            return ""
        res = self.res
        parts = [no_ai_box("app")] if self.inputs["ai_mode"] == "none" else []
        parts.append(result_boxes(res, skip=("ai_pending",) if self.waiting_for_answer else (), screen="app"))
        parts.append(summary_box(res))
        parts.append(report_details(res.report_path.read_text(encoding="utf-8")))
        return "".join(parts)

    def download(self, accept_todo: bool = False) -> "tuple[str | None, str]":
        """ダウンロード用の ZIP を作る。戻り値: (ZIP のパス, 知らせ)。要対応が残っていて accept_todo でなければ (None, 知らせ)。"""
        if self.res is None:
            return None, "先に変換してください。"
        if self.needs_action and not accept_todo:
            return None, ("要対応が残っています: " + "／".join(self.todo_titles())
                          + "。このままダウンロードするときは、「このままダウンロード」にチェックを入れてもう一度押してください。")
        archive = shutil.make_archive(str(self.work / f"変換結果_{self.res.xml_path.stem}"), "zip", self.out_dir)
        return archive, ""

    # ---- 次の論文
    def reset(self) -> None:
        """論文ごとの項目（ファイル・ページ・キーワード・日付・DOI）と結果を空にする。巻・号・査読の有無・原稿種別・AI の設定は残す。"""
        for name in PER_ARTICLE:
            self.inputs[name] = DEFAULTS[name]
        self.res = None
        self.notes = []
        self.user_images = {}
        self._meta = self._journal = self._api_key = None
        shutil.rmtree(self.work / "input", ignore_errors=True)
        shutil.rmtree(self.out_dir, ignore_errors=True)
        for archive in self.work.glob("変換結果*.zip"):
            archive.unlink()


def download_button_html(path: "str | Path") -> str:
    """「ZIP を保存」のボタン。ファイルは、画面の中の JavaScript が Gradio のファイルの経路（gradio_api/file=）から取り、ブラウザに保存させる。

    Colab の出力欄の中では、ファイルのリンクをそのまま開く（新しいタブや、リンク先への移動）と、Colab の中継の認証が
    タブごとに分かれているため開けない。画面の中からの取得（fetch）は同じ画面の認証で通るので、取ってから保存する。
    URL は画面の場所からの相対（root_path の下）。onclick の中では名前 URL が document.URL（文字列）に解決されるので、
    window.URL と書く（利用者の Colab で「URL.createObjectURL is not a function」になった）。
    """
    import html
    from urllib.parse import quote
    path = Path(path)
    url = "gradio_api/file=" + quote(str(path))
    js = ("const b=this;b.disabled=true;b.textContent='取り出しています…';"
          f"fetch('{url}').then(r=>{{if(!r.ok)throw new Error(r.status);return r.blob();}})"
          ".then(x=>{const a=document.createElement('a');a.href=window.URL.createObjectURL(x);"
          f"a.download={html.escape(repr(path.name))};document.body.appendChild(a);a.click();a.remove();"
          "b.textContent='保存しました（もう一度押すと再保存）';b.disabled=false;})"
          ".catch(e=>{b.textContent='保存できませんでした: '+e;b.disabled=false;});")
    return (f"<button onclick=\"{js}\" style='background:#2563eb;color:#ffffff;border:none;border-radius:6px;"
            "padding:10px 18px;font-size:16px;font-weight:bold;cursor:pointer;margin:8px 0'>"
            f"ZIP を保存（{html.escape(path.name)}）</button>")


# ---------------------------------------------------------------------------- 画面
def build_app(state: AppState, io: "IO | None" = None):
    """gr.Blocks を組み立てる（起動は launch または demo.launch）。state は 1 人の利用者の 1 回の作業を持つ。"""
    import gradio as gr
    io = io or IO()

    def message_html(e: InputError) -> str:
        return e.html or error_box("入力を確認してください", str(e))

    with gr.Blocks(title="論文 docx → J-STAGE XML 変換") as demo:
        gr.Markdown(f"# 論文 docx → J-STAGE XML 変換　版 {__version__}\n[説明書]({DOCS})")
        route = gr.Radio(ROUTES, value=DEFAULTS["route"], label="作り方",
                         info="PDF がまだないときは「docx から作る」")
        docx = gr.File(label="docx（論文の Word ファイル）", file_types=[".docx"], file_count="single")
        pdf = gr.File(label="PDF（J-STAGE に登載する PDF）", file_types=[".pdf"], file_count="single")
        with gr.Row():
            volume = gr.Textbox(label="巻", info="半角の英数字")
            issue = gr.Textbox(label="号")
            fpage = gr.Textbox(label="最初のページ")
            lpage = gr.Textbox(label="最後のページ")
        with gr.Row():
            peer_review = gr.Radio(PEER_REVIEWS, label="査読の有無")
            manuscript_type = gr.Dropdown(type_choices(), label="原稿種別")
        with gr.Accordion("任意の項目", open=False):
            approved = gr.Textbox(label="最終査読日", info="査読ありで、分かれば。2026-03-31 の形")
            keywords_ja = gr.Textbox(label="キーワード（日本語）", info="「;」で区切る")
            keywords_en = gr.Textbox(label="キーワード（英語）", info="「;」で区切る")
            pub_date = gr.Textbox(label="発行日")
            epub_date = gr.Textbox(label="J-STAGE 公開日")
            received = gr.Textbox(label="受付日")
            accepted = gr.Textbox(label="受理日")
            corresp = gr.Textbox(label="責任著者", info="何番目の著者か。例: 1（複数なら 1,2）")
            doi = gr.Textbox(label="DOI", info="空欄なら 10.24529/jasme.巻.号_開始ページ")
        ai_mode = gr.Radio(AI_MODES, value=DEFAULTS["ai_mode"], label="AI による補完の方法",
                           info="API は、Colab のシークレットに ANTHROPIC_API_KEY を登録しておく")
        with gr.Accordion("詳細設定", open=False):
            model = gr.Dropdown([DEFAULT_MODEL, AUTO_MODEL], value=DEFAULTS["model"], allow_custom_value=True,
                                label="MODEL（Claude のモデル。通常は変更不要）")
            split_labels = gr.Checkbox(label="SPLIT_LABELS（図表番号「図1」を <label> 要素に分ける）")
            subject_other = gr.Textbox(label="原稿種別（日本語）", info="原稿種別で「その他」を選んだときだけ")
            subject_other_en = gr.Textbox(label="原稿種別（英語）", info="同上")
        ready = gr.Markdown("足りない項目: docx")
        go = gr.Button(CONVERT_LABEL, variant="primary", interactive=False)
        message = gr.HTML()
        result = gr.HTML()
        with gr.Column(visible=False) as manual_col:
            prompt = gr.Textbox(label="依頼文（新しいチャットに貼り付けて送る）", lines=8, max_lines=8, interactive=False,
                                buttons=["copy"])
            attach = gr.File(label="依頼文と一緒に添付する画像", file_count="multiple", interactive=False)
            answer = gr.Textbox(label=ANSWER_LABEL, lines=6)
            apply_btn = gr.Button(APPLY_LABEL)
        with gr.Column(visible=False) as images_col:
            images_md = gr.Markdown()
            image_files = [gr.File(label=f"足りない図の画像 {k}", file_count="single", visible=False)
                           for k in range(1, MAX_IMAGE_SLOTS + 1)]        # 図ごとの欄。view() が見せる数とラベルを決める
            images_btn = gr.Button("画像を入れる")
        with gr.Row():
            accept = gr.Checkbox(label="このままダウンロード（要対応が残っています）", visible=False)
            download_btn = gr.Button("結果をダウンロード")
            next_btn = gr.Button("次の論文")
        download_html = gr.HTML()                      # 「ZIP を保存」のボタン（download_button_html）

        inputs = [route, docx, pdf, volume, issue, fpage, lpage, peer_review, manuscript_type, approved, keywords_ja,
                  keywords_en, pub_date, epub_date, received, accepted, corresp, doi, subject_other, subject_other_en,
                  ai_mode, model, split_labels]
        assert len(inputs) == len(INPUT_NAMES)
        views = [message, result, manual_col, prompt, attach, images_col, images_md, accept, download_html] + image_files
        assert len(views) == 9 + MAX_IMAGE_SLOTS

        def sync(values):
            state.set_inputs(**dict(zip(INPUT_NAMES, values)))

        def view(error: "InputError | None" = None, download: str = ""):
            """結果に応じた画面の更新（views の順）。"""
            manual = state.answer_box_open
            slots = state.image_slots()
            return [message_html(error) if error else "",
                    state.result_html(),
                    gr.update(visible=manual),
                    state.prompt_text() if manual else "",
                    state.attachments() if manual else None,
                    gr.update(visible=bool(state.missing_images())),
                    state.images_markdown(),
                    gr.update(visible=state.needs_action, value=False),
                    download] + [gr.update(visible=True, label=state.slot_label(name, cap), value=None)
                                 for name, cap, _why in slots] \
                + [gr.update(visible=False, value=None)] * (MAX_IMAGE_SLOTS - len(slots))

        def on_change(*values):
            sync(values)
            miss = state.missing()
            return gr.update(interactive=not miss), ("足りない項目: " + "、".join(miss) if miss else "")

        def on_convert(*values, progress=gr.Progress()):
            sync(values)
            try:
                state.convert(io, progress)
            except InputError as e:
                return view(e)
            except Exception as e:                 # 想定外の例外。Gradio の「Error」だけにせず、枠に出す
                return view(state.crash(e, "convert"))
            return view()

        def on_apply(text, progress=gr.Progress()):
            try:
                state.apply_answer(text, io, progress)
            except InputError as e:
                return view(e)
            except Exception as e:
                return view(state.crash(e, "apply"))
            return view()

        def on_images(*paths):
            names = [name for name, _cap, _why in state.image_slots()]       # 欄の並びは、直前の view() で出したもの
            try:
                state.add_images(dict(zip(names, paths)))
            except InputError as e:
                return view(e)
            except Exception as e:
                return view(state.crash(e, "images"))
            return view()

        def on_download(accept_todo):
            out = [gr.update()] * len(views)               # 結果などはそのまま（message と download_html だけ変える）
            try:
                path, note = state.download(accept_todo)
            except Exception as e:                         # ZIP を作れなかった（出力フォルダが消えているなど）
                out[0], out[8] = state.crash(e, "download").html, ""
                return out
            out[0] = error_box("ダウンロードの前に", note) if note else ""
            out[8] = download_button_html(path) if path else ""
            return out

        def on_next():
            state.reset()
            return [state.inputs[n] for n in INPUT_NAMES] + view() + [""]

        for comp in inputs:
            comp.change(on_change, inputs, [go, ready], api_name=False)
        go.click(on_convert, inputs, views)
        apply_btn.click(on_apply, [answer], views)
        images_btn.click(on_images, image_files, views)
        download_btn.click(on_download, [accept], views)
        next_btn.click(on_next, None, inputs + views + [answer])
    return demo


def _in_colab() -> bool:
    try:
        import google.colab  # noqa: F401
    except ImportError:
        return False
    return True


def _free_port() -> int:
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def colab_proxy_url(port: int) -> str:
    """Colab の中継（利用者のブラウザからランタイムのポートを開く URL。Google アカウントで認証され、本人しか開けない）。"""
    from google.colab import output
    return output.eval_js(f"google.colab.kernel.proxyPort({port})")


def colab_embed(port: int, height: int) -> None:
    """Colab の出力欄に、中継を通した画面を大きく埋め込む（出力欄の縦スクロールをなくし、ノートブックのスクロールだけにする）。

    新しいタブで開く形（google.colab.output.serve_kernel_port_as_window）は、ブラウザの保存領域の分離（storage partitioning）で
    動かなくなっており、Colab 自身が非推奨にしている。Colab の中では埋め込みしか残っていない。
    """
    from google.colab import output
    output.no_vertical_scroll()
    output.serve_kernel_port_as_iframe(port, height=str(height))


def launch(inline: bool = True, height: int = 1400):
    """画面を開く。share は必ず False（未公開の原稿を Gradio の中継サーバーに通さない）。

    Colab では、空いているポートで起動し、Colab の中継の URL を root_path に渡して、ファイルのリンク（ダウンロード）も中継を通るように
    してから、出力欄に大きく埋め込む（Gradio 自身の埋め込みは root_path を渡さないので、ファイルの URL がランタイムの内部のホスト名に
    なり、ブラウザから開けなかった）。Colab でなければ、ローカルのサーバーをブラウザで開く。
    """
    colab = _in_colab()
    state = AppState(Path("/content/jasme_work") if colab else None)
    demo = build_app(state, ColabIO() if colab else IO())
    common = dict(share=False, quiet=True, allowed_paths=[str(state.work)])
    if colab:
        port = _free_port()
        url = colab_proxy_url(port)
        demo.launch(server_port=port, root_path=url.split("?")[0].rstrip("/"), inline=False, prevent_thread_lock=True,
                    **common)
        colab_embed(port, height)
    else:
        demo.launch(inline=inline, **common)
    return demo
