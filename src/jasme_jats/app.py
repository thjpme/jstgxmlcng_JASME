"""Gradio による 1 画面の操作画面（一般の利用者用。docs/GUI_PLAN.md の 4 章・8 章）。

2 層に分ける。
  - AppState: 入力と結果を持ち、「変換を押せるか」「要対応が残っているか」「回答待ちか」「足りない画像」などを決める。
    Gradio に依存しない純粋な Python。変換は pipeline.convert() を呼ぶだけで、docx の文字には触れない。
  - build_app(state, io): gr.Blocks を組み立て、ボタンの処理を AppState につなぐ。Colab に依存する操作（シークレットの読み出し）は
    io に切り出す（テストでは偽物を渡す）。

知らせは report.actions() から colab.result_boxes(screen="app") で出す（文の中の画面の操作は、この画面の欄の名前に置き換わる）。この画面に個別の表示は足さない（docs/DEVELOPMENT.md の原則 8）。
未公開の原稿を Gradio の中継サーバーに通さないため、launch() の share は必ず False。
Gradio の版は pyproject の gui の extra で固定している（上げるときは人が Colab で確かめてから）。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import __version__
from . import report as rp
from .ai_assist import API_KEY_NAMES, DEFAULT_MODEL, cost_note
from .colab import (ANSWER_LABEL, APPLY_LABEL, CONVERT_LABEL, ai_finish_of, check_box, error_box, manual_guide, report_details,
                    result_boxes, step_text, structure_conflict_box, summary_box)
from .config import ArticleMeta, JournalConfig, keyword_language_mismatch, keyword_problem
from .images import match_names
from .imagelist import check_frame
from .pipeline import Options, StructureConflictError, add_images, convert, kept_images, reapply_images
from .report import (actions, ai_done, ai_state, blocking, clash_images_text, image_rows, images_action, shorten_shown, shown_text,
                     unmatched_image_text)

DOCS = "https://github.com/thjpme/jstgxmlcng_JASME/blob/main/docs/USAGE.md"
MAX_IMAGE_SLOTS = 30          # 図ごとの行（ファイル選択）の数。最初から作って、置き場所の数だけ見せる。これより多い分は「まとめて入れる」で入れる
FIXED_VIEWS = 10              # 画面の更新（build_app の views）の先頭の固定の部品の数。その後ろに、図ごとのファイル選択、「入れない」のチェックが MAX_IMAGE_SLOTS 個ずつ続く

# 画面の入力欄。名前は AppState.inputs の鍵で、画面の部品の並びもこの順（INPUT_NAMES）
ROUTES = [("docx から作り、出版版 PDF で補う", "pdf"), ("docx から作る", "docx")]
AI_MODES = [("使わない", "none"), ("手動（チャットに貼り付け）", "manual"), ("API（Claude）", "api")]
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
          "subject_other_en": "原稿種別（英語）", "route": "作り方", "split_labels": "SPLIT_LABELS"}
# 変わると依頼文も変わり得る入力の名前（stale_text の文の分岐に使う）
DOCXISH = (LABELS["docx"], LABELS["pdf"], LABELS["route"], LABELS["split_labels"])
# 変換の結果を左右する入力（前回の変換と比べる）。AI の方法・モデルは次に変換するときに使う設定なので比べない（O3）
COMPARED_INPUTS = tuple(n for n in INPUT_NAMES if n not in ("ai_mode", "model"))


class InputError(Exception):
    """入力の誤り・足りない項目など、利用者に直してもらうこと。html があれば、その枠を出す（なければ赤い枠にメッセージを入れる）。"""

    def __init__(self, message: str, html: str = ""):
        super().__init__(message)
        self.html = html


_DIGESTS: dict = {}


def file_digest(path: "str | Path") -> str:
    """ファイルの中身の sha256（16 進）。on_change がキーを押すたびに呼ぶので、（パス・大きさ・更新時刻）ごとに覚える。
    例外は捕まえない（捕まえるのは AppState.fingerprint）。"""
    path = Path(path)
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _DIGESTS:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        _DIGESTS[key] = h.hexdigest()
    return _DIGESTS[key]


def _model_value(v) -> str:
    """MODEL の欄の値を Options.ai_model に渡す値にする。"""
    return "auto" if str(v).startswith("自動") else str(v).strip()


@dataclass(frozen=True)
class RunInputs:
    """変換したときの入力の写し。AppState.convert が作り、_run・apply_answer・add_images・download が使う。"""
    compared: dict
    docx: Path
    pdf: Optional[Path]
    route: str
    split_labels: bool
    ai_mode: str
    model: str
    meta: ArticleMeta
    journal: JournalConfig
    docx_name: str
    api_key: Optional[str] = field(default=None, repr=False)


def type_choices() -> list:
    """原稿種別の選択肢（「日本語 / English」と「その他」）。"""
    return [f"{ja} / {en}" for ja, en in JournalConfig.load().manuscript_types.items()] + [OTHER_TYPE]


# ---------------------------------------------------------------------------- Colab に依存する操作
class IO:
    """既定の io: API キーを環境変数から読む。"""

    def read_secret(self, names) -> "str | None":
        for name in names:
            value = os.environ.get(name)
            if value:
                return value
        return None


class ColabIO(IO):
    """Colab 用の io: シークレット（google.colab.userdata）を読む。"""

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
        self.kept: dict = {}                   # 変換し直す前に覚えた、入れた画像（pipeline.kept_images。変換の後に reapply_images で入れ直す）
        self.run: Optional[RunInputs] = None   # 変換したときの入力の写し（入力が写しと違えば、結果を残したまま断る）
        self.paper_changed = False             # 直前の convert() で docx の中身が前回と違った（on_convert が回答の欄を空にするか決める）
        self._last_docx = None                 # 最後に convert() が手順 3 まで進んだときの docx の digest（変換が後で失敗しても残す）
        # 最後に API モードで反映した AI の回答の写し（出力フォルダの AI回答.json の中身）。_run は出力フォルダを消すので、ここに持ち、
        # Options.ai_cache で渡す（依頼の番号・モデルが同じなら API を呼ばない。修正計画 W8 の 4.6）。reset() では消さない
        # （別の論文では依頼の番号が違うので使われない）
        self.ai_cache: Optional[str] = None

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

    # ---- 入力の写しとの比べ
    # 変換の後に入力が変わったとき、前の結果・貼り付けた回答・入れた画像は消さずに残し、理由を示して断る。on_change はキーを
    # 押すたびと「次の論文」で呼ばれ、触っただけで消すと取り返せないため。比べるのはファイルの中身（sha256）で、同じファイルの
    # 選び直しは変わっていない扱いにする。
    def fingerprint(self) -> dict:
        """COMPARED_INPUTS の名前ごとに、前回の変換と比べる値。"""
        out = {}
        f = self.inputs
        for name in COMPARED_INPUTS:
            v = f[name]
            if name in ("docx", "pdf"):
                if not v:
                    out[name] = None
                    continue
                try:
                    out[name] = file_digest(Path(v))
                except OSError:
                    out[name] = ("読めない", str(v))
            elif name == "split_labels":
                out[name] = bool(v)
            elif name == "route":
                out[name] = str(v)
            elif name in ("subject_other", "subject_other_en") and f["manuscript_type"] != OTHER_TYPE:
                out[name] = ""
            else:
                out[name] = unicodedata.normalize("NFKC", str(v or "")).strip()
        return out

    def changed_inputs(self) -> list:
        """前回の変換から変わった入力の LABELS の名前（COMPARED_INPUTS の順）。結果がないときは空。"""
        if self.res is None or self.run is None:
            return []
        now = self.fingerprint()
        return [LABELS[n] for n in COMPARED_INPUTS if now[n] != self.run.compared[n]]

    def stale_text(self, changed) -> str:
        names = "、".join(changed)
        if any(n in DOCXISH for n in changed):
            inner = ("入れた画像は、同じ図（番号とキャプションが同じ図）には変換の後に引き継がれます。手動モードでは新しい依頼文が出るので、"
                     "AI に渡して回答を貼り替えます")
        else:
            inner = ("入れた画像は、同じ図には変換の後に引き継がれます。貼り付けた回答は欄に残るので、変換の後にもう一度"
                     + rp.step("apply_button") + "を押します")
        text = ("入力が前回の変換から変わっています（変わった項目: " + names + "）。今の結果は、変える前の入力で作ったものです。"
                "変えた入力で作るには、" + rp.step("convert_again") + "してください（" + inner + "）。"
                "今の結果のまま続けるときは、入力を前回の変換のときの値に戻してください（同じファイルを選び直せば、変わっていない扱いになります）。")
        return _app_text(text)

    def settings_note(self) -> str:
        if self.res is None or self.run is None:
            return ""
        if self.inputs["ai_mode"] != self.run.ai_mode or _model_value(self.inputs["model"]) != self.run.model:
            return _app_text("「AI による仕上げの方法」の欄・MODEL の変更は、次に変換するときに使われます（今の結果は前の設定のままです。"
                             "変えた設定で作るには、" + rp.step("convert_again") + "してください）。")
        return ""

    def ready_text(self) -> str:
        """変換ボタンの横の文: 足りない項目、入力が変わったこと、設定の変更。"""
        parts = []
        miss = self.missing()
        if miss:
            parts.append("足りない項目: " + "、".join(miss))
        changed = self.changed_inputs()
        note = self.stale_text(changed) if changed else self.settings_note()
        if note:
            parts.append(note)
        return "\n\n".join(parts)

    # ---- 変換
    def _copy_inputs(self) -> tuple:
        """画面から受け取ったファイルを、元の名前で作業用の場所（work/input）に置く。戻り値: (docx の写し, PDF の写し or None)。"""
        f = self.inputs
        docx = Path(f["docx"])
        pdf = Path(f["pdf"]) if f["pdf"] else None
        (self.work / "input").mkdir(parents=True, exist_ok=True)
        local = self.work / "input" / docx.name
        if docx.resolve() != local.resolve():
            shutil.copyfile(docx, local)
        local_pdf = None
        if pdf:
            local_pdf = self.work / "input" / pdf.name
            if pdf.resolve() != local_pdf.resolve():
                shutil.copyfile(pdf, local_pdf)
        return local, local_pdf

    def _run(self, ai_mode: str, ai_response: "str | None", progress=None):
        step = progress or (lambda fraction, desc="": None)
        run = self.run
        opts = Options(out_dir=self.out_dir, ai_mode=ai_mode, ai_provider="claude", ai_model=run.model, ai_api_key=run.api_key,
                       ai_response=ai_response, pdf_path=run.pdf, route=run.route, split_labels=run.split_labels,
                       ai_cache=self.ai_cache)
        self.res = None                        # 出力フォルダを消すので、前の結果は先に捨てる（途中で止まったとき、消えたファイルを指さないため）
        shutil.rmtree(self.out_dir, ignore_errors=True)
        try:
            res = convert(run.docx, run.meta, run.journal, opts)
        except StructureConflictError as e:
            raise InputError(step_text(str(e), "app"), structure_conflict_box(str(e), "app"))
        if res.ai.mode == "api" and res.ai_answer_path is not None:
            self.ai_cache = res.ai_answer_path.read_text(encoding="utf-8")
        step(0.9, "画像を入れ直しています…")
        if self.kept:
            reapply_images(res, self.kept)     # 変換をやり直したときに、前に入れた画像を、同じ図だと確かめられたものだけ入れ直す
        self.res = res
        return res

    def convert(self, io: "IO | None" = None, progress=None):
        """「変換する」。足りない項目・入力の誤り・API キーの読み出し失敗・ファイルを読めないときは InputError。

        確かめ（足りない項目・入力の誤り・API キー・ファイルを読めない）で止まったときは、前の結果と入力の写しをそのまま残す。
        """
        io = io or IO()
        step = progress or (lambda fraction, desc="": None)
        self.paper_changed = False             # 入力の誤りで止まったときに、前回の値で回答の欄を消さないため
        meta = self._article_meta()
        journal = JournalConfig.load()
        api_key = None
        if self.inputs["ai_mode"] == "api":
            names = API_KEY_NAMES["claude"]
            api_key = io.read_secret(names)
            if not api_key:
                raise InputError(f"API キー（シークレット {' または '.join(names)}）を読めませんでした。")
        compared = self.fingerprint()
        for name in ("docx", "pdf"):
            v = compared[name]
            if isinstance(v, tuple) and v[0] == "読めない":
                raise InputError(_app_text(rp.step(name) + "のファイルを読めませんでした。選び直してから、"
                                           + rp.step("convert_again") + "してください。"))
        self.paper_changed = self._last_docx is not None and compared["docx"] != self._last_docx
        self._last_docx = compared["docx"]
        if self.res is not None:
            self.kept = kept_images(self.res)    # 前の変換で入れた画像を覚える（変換の後に reapply_images で同じ図に入れ直す）
        self.res = None
        self.run = None
        local_docx, local_pdf = self._copy_inputs()
        f = self.inputs
        self.run = RunInputs(compared=compared, docx=local_docx, pdf=local_pdf, route=str(f["route"]),
                             split_labels=bool(f["split_labels"]), ai_mode=f["ai_mode"], model=_model_value(f["model"]),
                             meta=meta, journal=journal, docx_name=Path(f["docx"]).name, api_key=api_key)
        step(0.2, self.convert_note())
        res = self._run(self.run.ai_mode, None, progress)
        step(1.0, "完了")
        return res

    def convert_note(self) -> str:
        """変換中の進み具合の文。API モードは、AI に依頼を送っている（出版版 PDF も送る）ことを言う。"""
        api = self.inputs["ai_mode"] == "api"
        return ("変換中…AI に依頼文" + ("と出版版 PDF " if self.inputs["pdf"] else "") + "を送って回答を待っています（数分かかることがあります）"
                if api else "変換中…（数分かかることがあります）")

    # ---- 手動モード
    @property
    def waiting_for_answer(self) -> bool:
        """手動モードで、AI の回答をまだ反映していない（report.ai_state が「回答待ち」）。"""
        return (self.res is not None and self.run is not None and self.run.ai_mode == "manual"
                and ai_state(self.res) == "回答待ち")

    @property
    def answer_box_open(self) -> bool:
        """手動の欄（依頼文・回答の欄〈ANSWER_LABEL〉・「反映」）を見せるか。

        AI による仕上げが済んでいない（report.ai_done が偽。回答待ち・失敗・一部）あいだは、貼り付け直せるように見せたままにする
        （知らせの key ではなく状態で決める。修正計画 W8 の 4.3）。
        手動モードで変換した結果のときだけ見せる（変換したときの入力の写し run.ai_mode で決める。変換の後に「AI による仕上げの方法」の
        欄を変えても変わらない。O3）。
        """
        if self.res is None or self.run is None or self.run.ai_mode != "manual" or self.res.ai.mode != "manual" or not self.res.prompt_path:
            return False
        return not ai_done(self.res)

    def prompt_text(self) -> str:
        if self.res is None or not self.res.prompt_path:
            return ""
        return self.res.prompt_path.read_text(encoding="utf-8")

    def apply_answer(self, text: str, io: "IO | None" = None, progress=None):
        """AI の回答を付けて変換し直す。"""
        if self.res is None or self.run is None or self.run.ai_mode != "manual":
            raise InputError("手動モードで変換してから、回答を貼り付けてください。")
        changed = self.changed_inputs()
        if changed:
            raise InputError(self.stale_text(changed))
        if not (text or "").strip():
            raise InputError("AI の回答が貼り付けられていません。")
        # 前の論文・図表や文献の並びが違う原稿への回答は、変換の中で依頼の番号で確かめて使わない（ai_assist.check_answer。
        # 「失敗」として知らせる。修正計画 W8 の 4.6）
        (progress or (lambda fraction, desc="": None))(0.2, "回答を反映して変換し直しています…")
        self.kept = kept_images(self.res)      # _run は出力フォルダを消すので、入れた画像は先に覚える
        return self._run("manual", text)

    # ---- 図の画像（修正計画 W1 の 4.5）。残りの数・図の一覧の文は report.images_action、行は report.image_rows から作る。
    # ここに書くのは、行のラベルと操作の案内だけ
    def image_rows(self) -> list:
        """画像の欄に出す行（report.image_rows のうち任意の置き場所を除いたもの。docx の順）。"""
        if self.res is None:
            return []
        return [row for row in image_rows(self.res) if row.kind != "optional"]

    def missing_images(self) -> list:
        """まだ画像を入れていない置き場所の行（report.ImageRow の状態 missing）。"""
        return [row for row in self.image_rows() if row.status == "missing"]

    def image_slots(self) -> list:
        """画面に行を出す置き場所: image_rows() の先頭から MAX_IMAGE_SLOTS 件まで。"""
        return self.image_rows()[:MAX_IMAGE_SLOTS]

    @staticmethod
    def slot_label(row) -> str:
        """行のラベル: 「{キャプションの先頭 30 字}（{幹}）— {未／入れた: 元のファイル名／入れない}」。キャプションのない画像は場所を添える。"""
        cap = shown_text(row.caption)
        head = shorten_shown(cap) if cap and row.kind != "nocap" else \
            "キャプションのない画像" + (f"（{shorten_shown(row.where)}）" if row.where else "")
        state = {"missing": "未", "skipped": "入れない"}.get(row.status) or ("入れた: " + (row.image.source_name if row.image is not None else row.name))
        return f"{head}（{row.key}）— {state}"

    def images_visible(self) -> bool:
        """「図の画像」の欄を出すか: 置き場所があるとき、または持ち越しの知らせがあるとき。"""
        if self.res is None:
            return False
        act = images_action(self.res)
        return bool(self.image_rows() or (act is not None and act.box_detail))

    def images_markdown(self) -> str:
        """「図の画像」の欄の見出しと説明: 見出しの進み具合と、残っているときの本文は手順 images の Action（progress・box_detail）。"""
        if self.res is None:
            return ""
        act = images_action(self.res)
        lines = ["### 図の画像" + (f"（{act.progress}）" if act is not None else "")]
        if act is not None and act.box_detail:
            lines.append(_app_text(act.box_detail))
        if self.image_rows():
            lines.append("下の「まとめて入れる」に、fig03.png・図3.png のような名前の画像（複数選べます）を選ぶと、名前で図に合わせます。"
                         "名前で合わない画像は、図ごとの行で選びます。選んだら「画像を入れる」を押してください。"
                         "キャプションのない画像を入れないときは、その行の「入れない」にチェックを入れます"
                         "（チェックを外して「画像を入れる」を押すと、「入れない」をやめて未に戻します）。")
        if len(self.image_rows()) > MAX_IMAGE_SLOTS:
            lines.append(f"図ごとの行は {MAX_IMAGE_SLOTS} 個までです。続きの図の画像は「まとめて入れる」で入れてください。")
        return "\n\n".join(lines)

    def check_html(self) -> str:
        """図の確かめの一覧（画像を埋め込んだ HTML。画像の要る図・表がなければ空文字）。"""
        return check_frame(self.res) if self.res is not None else ""

    def match_images(self, paths) -> tuple:
        """「まとめて入れる」で選んだファイルを、名前で置き場所に合わせる（images.match_names）。
        戻り値: ({幹: パス}, 合わなかったファイル名の一覧, 同じ幹に合った複数のファイル [(幹, [ファイル名, …])])。"""
        if self.res is None or not paths:
            return {}, [], []
        by_name = {}
        for p in paths:
            by_name.setdefault(Path(p).name, Path(p))
        # 任意の置き場所（画像で補える文字）も、名前が合えば入れる（行と手順の数には出さない）
        found, unmatched, clashes = match_names(list(by_name), image_rows(self.res), self.res.meta.article_id(self.res.journal))
        return {key: by_name[name] for key, name in found.items()}, unmatched, clashes

    def add_images(self, mapping: dict, skip=None, unskip=None) -> list:
        """選んだ画像を、図ごとに入れる。mapping: 画像の置き場所の幹 → ファイルのパス。skip: 「入れない」にするキャプションのない画像の幹。
        unskip: 「入れない」をやめて未に戻す幹。戻り値: 入れた画像の幹。"""
        if self.res is None:
            raise InputError("先に変換してください。")
        changed = self.changed_inputs()
        if changed:
            raise InputError(self.stale_text(changed))
        chosen = {name: Path(p) for name, p in (mapping or {}).items() if p}
        skip, unskip = list(skip or []), list(unskip or [])
        if not chosen and not skip and not unskip:
            raise InputError("画像が選ばれていません。")
        supplied = {name: (p.name, p.read_bytes()) for name, p in chosen.items()}
        try:
            added = add_images(self.res, supplied, skip=skip or None, unskip=unskip or None)
        except ValueError as e:
            raise InputError(str(e))
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
        "images": "入れた画像と変換の結果は、この画面に残っています。入力は変えず、開発者に知らせてください。",
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
        """ダウンロードの前に止める知らせ（report.blocking。要対応と、残っている必須の手順）の見出し。"""
        return [a.box_title for a in blocking(actions(self.res))] if self.res is not None else []

    def result_html(self) -> str:
        """結果の HTML: 要対応・要確認の枠 → 結果の要約 → レポート全文（畳む）。"""
        if self.res is None:
            return ""
        res = self.res
        parts = []
        # 手順 images は「図の画像」の欄（images_markdown）に出すので、ここでは重ねて出さない
        parts.append(result_boxes(res, skip=("images",) + (("ai_finish",) if self.waiting_for_answer else ()), screen="app"))
        if self.waiting_for_answer:
            # 手動の回答待ち: ai_finish の枠の代わりに、手順の番号つきの案内（なぜ・任意か・PDF を添付すること）を出す
            # （下の依頼文・回答の欄の案内。同じ文を重ねて出さない。修正計画 W8 の 4.5）
            parts.append(manual_guide(ai_finish_of(res), "app", res.pdf_name))
        parts.append(summary_box(res))
        parts.append(report_details(res.report_path.read_text(encoding="utf-8")))
        return "".join(parts)

    def download(self, accept_todo: bool = False) -> "tuple[str | None, str]":
        """ダウンロード用の ZIP を作る。戻り値: (ZIP のパス, 知らせ)。止める知らせ（要対応か、残っている必須の手順）があって accept_todo でなければ (None, 知らせ)。"""
        if self.res is None:
            return None, "先に変換してください。"
        changed = self.changed_inputs()
        if changed:
            return None, self.stale_text(changed)       # 「このままダウンロード」でも断る
        if self.needs_action and not accept_todo:
            return None, ("残っていることがあります: " + "／".join(self.todo_titles())
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
        self.kept = {}
        self.run = None
        self.paper_changed = False
        self._last_docx = None
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
        ai_mode = gr.Radio(AI_MODES, value=DEFAULTS["ai_mode"], label="AI による仕上げの方法",
                           info=("API は、Colab のシークレットに ANTHROPIC_API_KEY を登録しておく（利用料がかかります。" + cost_note()
                                 + "）。手動は、依頼文を出版版 PDF と一緒にチャット（claude.ai など）に送り、回答を貼り戻す"
                                 "（API キー不要。PDF の添付は強く推奨）"))
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
            answer = gr.Textbox(label=ANSWER_LABEL, lines=6)
            apply_btn = gr.Button(APPLY_LABEL)
        with gr.Column(visible=False) as images_col:
            images_md = gr.Markdown()
            bulk_files = gr.File(label="まとめて入れる（複数選べます。fig03.png・図3.png のような名前で図に合わせます）", file_count="multiple",
                                 file_types=["image"])
            image_files = [gr.File(label=f"図の画像 {k}", file_count="single", file_types=["image"], visible=False)
                           for k in range(1, MAX_IMAGE_SLOTS + 1)]        # 図ごとの行。view() が見せる数とラベルを決める
            skip_boxes = [gr.Checkbox(label="入れない（出版版 PDF で見て、ほかの図に写っている・飾りだけ、のとき）", visible=False)
                          for _ in range(MAX_IMAGE_SLOTS)]               # キャプションのない画像の行だけ見せる
            images_btn = gr.Button("画像を入れる")
            check_view = gr.HTML()                                        # 図の確かめ（取り違えの確かめの一覧）
        with gr.Row():
            accept = gr.Checkbox(label="このままダウンロード（要対応か、残っている手順があります）", visible=False)
            download_btn = gr.Button("結果をダウンロード")
            next_btn = gr.Button("次の論文")
        download_html = gr.HTML()                      # 「ZIP を保存」のボタン（download_button_html）

        inputs = [route, docx, pdf, volume, issue, fpage, lpage, peer_review, manuscript_type, approved, keywords_ja,
                  keywords_en, pub_date, epub_date, received, accepted, corresp, doi, subject_other, subject_other_en,
                  ai_mode, model, split_labels]
        assert len(inputs) == len(INPUT_NAMES)
        views = [message, result, manual_col, prompt, images_col, images_md, accept, download_html, bulk_files,
                 check_view] + image_files + skip_boxes
        assert len(views) == FIXED_VIEWS + 2 * MAX_IMAGE_SLOTS

        def sync(values):
            state.set_inputs(**dict(zip(INPUT_NAMES, values)))

        def view(error: "InputError | None" = None, download: str = "", notice: str = ""):
            """結果に応じた画面の更新（views の順）。notice は、操作の結果の知らせの HTML（message に error と並べて出す）。"""
            manual = state.answer_box_open
            slots = state.image_slots()
            hide = MAX_IMAGE_SLOTS - len(slots)
            return [(message_html(error) if error else "") + notice,
                    state.result_html(),
                    gr.update(visible=manual),
                    state.prompt_text() if manual else "",
                    gr.update(visible=state.images_visible()),
                    state.images_markdown(),
                    gr.update(visible=state.needs_action, value=False),
                    download,
                    None,
                    state.check_html()] \
                + [gr.update(visible=True, label=state.slot_label(row), value=None) for row in slots] + [gr.update(visible=False, value=None)] * hide \
                + [gr.update(visible=row.kind == "nocap", value=row.status == "skipped") for row in slots] + [gr.update(visible=False, value=False)] * hide

        def on_change(*values):
            sync(values)
            return gr.update(interactive=not state.missing()), state.ready_text()

        def on_convert(*values, progress=gr.Progress()):
            sync(values)

            def tail():
                # 別の論文に変えて変換したときだけ回答の欄を空にする。ready は変換し直した後に古い文を残さないため作り直す
                return [gr.update(value="") if state.paper_changed else gr.update(), state.ready_text()]
            try:
                state.convert(io, progress)
            except InputError as e:
                return view(e) + tail()
            except Exception as e:                 # 想定外の例外。Gradio の「Error」だけにせず、枠に出す
                return view(state.crash(e, "convert")) + tail()
            return view() + tail()

        def on_apply(text, progress=gr.Progress()):
            try:
                state.apply_answer(text, io, progress)
            except InputError as e:
                return view(e)
            except Exception as e:
                return view(state.crash(e, "apply"))
            return view()

        def on_images(bulk, *rest):
            rows = state.image_slots()                           # 行の並びは、直前の view() で出したもの
            paths, checks = rest[:MAX_IMAGE_SLOTS], rest[MAX_IMAGE_SLOTS:]
            mapping = {row.key: p for row, p in zip(rows, paths)}
            skip = [row.key for row, c in zip(rows, checks) if c and row.kind == "nocap" and row.status != "skipped"]
            # 「入れない」のチェックを外した行は、未に戻す（その行に画像を選んでいれば、画像を入れる）
            unskip = [row.key for row, c, p in zip(rows, checks, paths) if not c and row.status == "skipped" and not p]
            checked = {row.key for row, c in zip(rows, checks) if c and row.kind == "nocap"}
            notes = []
            try:
                matched, unmatched, clashes = state.match_images(bulk or [])
                for key, path in matched.items():
                    if mapping.get(key):                         # 行で選んだ画像があれば、そちらを使う（まとめての方は入れない）
                        notes.append(f"「{Path(path).name}」は、図ごとの行で画像を選んだ図（{key}）に合ったので、入れていません"
                                     "（行で選んだ画像を入れました）")
                    elif key in checked:                         # 「入れない」にチェックが付いている行
                        notes.append(f"「{Path(path).name}」は、「入れない」にチェックが付いた画像（{key}）に合ったので、入れていません")
                    else:
                        mapping[key] = path
                        unskip = [k for k in unskip if k != key]
                if unmatched:
                    notes += [unmatched_image_text(state.res, name, "ファイル名を直すか、図ごとの行で選んでください。") for name in unmatched]
                notes += [clash_images_text(key, names) for key, names in clashes]
                state.add_images(mapping, skip, unskip)
            except InputError as e:
                return view(e, notice=check_box("画像を入れられなかったファイル", "\n".join(notes)) if notes else "")
            except Exception as e:
                return view(state.crash(e, "images"))
            return view(notice=check_box("画像を入れられなかったファイル", "\n".join(notes)) if notes else "")

        def on_download(accept_todo):
            out = [gr.update()] * len(views)               # 結果などはそのまま（message と download_html だけ変える）
            try:
                path, note = state.download(accept_todo)
            except Exception as e:                         # ZIP を作れなかった（出力フォルダが消えているなど）
                out[0], out[7] = state.crash(e, "download").html, ""
                return out
            out[0] = error_box("ダウンロードの前に", note) if note else ""
            out[7] = download_button_html(path) if path else ""
            return out

        def on_next():
            state.reset()
            return [state.inputs[n] for n in INPUT_NAMES] + view() + [""]

        for comp in inputs:
            comp.change(on_change, inputs, [go, ready], api_name=False)
        go.click(on_convert, inputs, views + [answer, ready])
        apply_btn.click(on_apply, [answer], views)
        images_btn.click(on_images, [bulk_files] + image_files + skip_boxes, views)
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
