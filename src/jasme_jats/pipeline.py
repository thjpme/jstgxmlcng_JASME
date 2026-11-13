"""変換の全体の流れ。

  1. docx を読み取る（docx_reader）
  2. 段落の役割を決め、論文の構造を組み立てる（structure）。そのまま組み立てると段落の文字が XML にも除外の記録にも入らなくなる
     構造（同じ種類の後付けの見出し・英文要旨の見出しが 2 つ、著者名の付かない所属。K1・K2）は plan.structure_conflicts に記録され、
     組み立ての直後（AI を呼ぶ前。ルート2 は補った docx を作る前の元の docx で）に StructureConflictError で変換を中止する
  3. 機械的にリンクを付ける（linker, refparse）
  4. （任意）AI による補完: AI が返した操作を検証し、構造の組み直し・リンクの追加として適用する（ai_assist）。
     回答が途中で切れていたら、最後まで書かれた図表の位置の指定（placements）だけを読んで反映し、要対応として知らせる。
     AI の役割の指定（set_role）で組み直すと構造の衝突（K1・K2）ができるときは、衝突の範囲の set_role を、なお残ればすべての
     set_role を不採用（CONFLICT_ROLE_WHY。レポートの 2 章）にして組み直す（中止しない）
  5. XML を組み立てる（builder）
  6. 文字の不変性チェック（fidelity）… AI 補完を行った場合も、必ずこの最終段階で行う
  7. 目印を取り除き、画像の置き場所をすべて書いた XML（Result.xml_base）を作り、入れた画像を反映した最終出力
     （package.apply_images）で、もう一度文字列を照合する（fidelity.final_check）
  8. J-STAGE 指定 DTD で検証する（validate。最終出力で）
  9. docx の画像のうち、画像の置き場所（ImageSlot）を作れなかったもの（置き場所をすべて書いた XML〈xml_base〉に、その画像を含む
     置き場所の名前が出ていないもの。画像を置けない場所・出力しなかった段落の中にある画像）を調べる（lost_images）。XML の画像の名前が
     置き場所の一覧と合うかも調べる（image_problems。変換ツールの不具合の守り）。画像の位置に数えなかった飾りの図形を集める（decorations）。
     あわせて、出力した表の形（行ごとの列の数・セルの重なり・縦の結合の範囲・セルのない行）を調べる（table_problems）。
     Word の自動番号のある段落で、文字を出したのに番号を出していないものも調べる（lost_autonums）。
     最終の XML に私用領域の文字（読めない文字）が残っていないかも調べ（pua_chars）、記号フォントの符号を普通の文字に置き換えた
     記号を集める（symbols_replaced）
 10. J-STAGE のアップロード時のチェックのうち XML だけで判定できるものを再現する（jstage_rules。画像の置き場所の名前で）
 11. J-STAGE のフォルダ構成と ZIP（今回の XML・PDF・作業する人が入れた画像だけを入れ、読み直して確かめる）、レポート
     （package, report）。docx の中の画像は書き出さない（図・表の画像は作業する人が用意し、add_images で入れる。入れるたびに
     XML を apply_images で作り直し、文字・DTD・J-STAGE のチェック・ZIP の確かめをやり直す。修正計画 W1 の 2.6）

作り方は 2 通り（Options.route）:
  ルート1（docx）: docx から作る。docx の文字は 1 文字も変えない。記事の PDF があれば照合して、違いをレポートに載せるだけ（pdfmatch）
  ルート2（pdf） : docx から作り、出版版 PDF で補う。Word の文字が正で、著者校正の直し（(B)）と、組版の違い（(A)。全角・半角・
                   ダッシュ・引用符など）を PDF に合わせた docx（Word の変更履歴つき）を先に作り（pdfdocx）、それをルート1 と同じ処理で
                   変換する。Word が付ける番号（自動番号・脚注番号）は docx の文字ではないので、変換のときに全角・半角と字形を PDF に
                   合わせる（照合しない段落〈表のセル・囲み・別行数式〉と、付記・謝辞・注・引用文献・資料・英文要旨の
                   見出しの番号は Word の形のまま）。最後に、補った docx が元の docx から (A) と報告した (B) 以外に変わっていないことを確かめる
                   （補完の確かめ。fidelity.verify_supplement）
"""
from __future__ import annotations

import datetime as _dt
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import __version__
from .ai_assist import (DEFAULT_MODEL, AIOutcome, apply_ops, build_request, call_provider, float_placements,
                        manual_prompt, parse_cut_response, parse_response, retarget_ops, role_overrides,
                        split_ops, target_keys)
from .article import _para_text
from .builder import build, finalize, serialize, word_note_marks
from .config import ArticleMeta, JournalConfig
from .docx_reader import read_docx
from .fidelity import SupplementResult, final_check, supplement_targets, verify, verify_supplement
from .imagelist import write_check
from .images import ChangedImage, DroppedImage, KeptImage, SlotImage, check_user_image
from .jstage_rules import check as jstage_check
from .linker import cited_refs, link
from .model import Decision, Decoration, LostImage, LostNumber, PuaChar, TableProblem
from .package import (XLINK_HREF, apply_images, article_dir, make_zip, unzipped_files, write_package, zip_image_names,
                      zip_problems)
from .pdfdocx import DocxFix, make_fixed_docx, same_file
from .pdfmatch import PdfCheck, check_pdf
from .report import (BOX_PENDING_NOTE, actions, blocking, decoration_where, render, render_ai_only, slot_where, step,
                     structure_conflict_text)
from .report import pdf_fallback as report_pdf_fallback
from .structure import FN_IMAGE_EXCLUDED, REF_IMAGE_EXCLUDED, classify, conflict_overrides, float_caption, float_targets
from .ooxml import is_pua
from .tracking import GEN, SPAN
from .validate import validate


class AIRequiredError(Exception):
    """位置を機械的に決められない図表があるのに、AI による補完を使わない設定で変換しようとした。

    文の中の画面の操作は目印（report.step）で書く。画面に出すときは colab.step_text で（ノートブックは colab.ai_required_box、
    1 画面版は app.py、コマンドラインは cli.py が screen を指定して）語に置き換える。
    """

    def __init__(self, plan):
        self.floats = [plan.floats[fid] for fid in plan.unplaced_floats]
        lines = [f"- {info.float.fid}: アンカー段落「{_head(plan, info.float.anchor_src)}」付近、"
                 f"{float_caption(info)}（{info.reason}）" for info in self.floats]
        super().__init__(
            f"この原稿には、位置を機械的に決められない図表（テキストボックス・グループ図形に入った図表）が {len(self.floats)} 件"
            "あります。これらの位置と組み合わせは AI に判断させる必要があるため、AI による補完を「使わない」設定では変換できません。"
            + step("ai_modes") + "、もう一度変換してください。\n" + "\n".join(lines))


class StructureConflictError(Exception):
    """docx の構造に、そのまま変換すると段落の文字が XML に入らなくなる形（同じ種類の後付けの見出し・英文要旨の見出しが 2 つ、
    著者名の付かない所属。docs/REVIEW_2026-11.md の K1・K2）があるので、変換を中止した。

    report.actions の知らせではなく、AIRequiredError と同じ例外の表示。文の中の画面の操作は目印（report.step）で書き、
    画面に出すときは colab.step_text で（ノートブックは colab.structure_conflict_box、1 画面版は app.py、コマンドラインは cli.py が
    screen を指定して）語に置き換える。テストが中止のときの構造（plan.fns など）を見られるよう plan を持つ。
    """

    def __init__(self, plan):
        self.plan = plan
        self.conflicts = list(plan.structure_conflicts)
        super().__init__(structure_conflict_text(plan))


# AI の set_role を、構造の衝突（K1・K2）ができるので使わなかったときの理由（レポートの 2 章の不採用の一覧に出る。_reject_roles）
CONFLICT_ROLE_WHY = ("この回答の役割の指定を合わせて組み直すと、同じ種類の後付けの見出し（英文要旨の見出し）が 2 つになるか、所属が著者名に付かなくなり、"
                     "段落の文字が XML に入らなくなるので使わなかった")


def _reject_roles(ops, outcome, pred):
    """AI の set_role のうち、pred(op) が真で、まだ不採用の一覧にないものを、構造の衝突（CONFLICT_ROLE_WHY）で不採用にする（2 章）。

    同じ段落への set_role が複数あれば、すべて不採用にする。apply_ops は不採用の一覧にある操作（同じ dict）を飛ばすので、
    採用の一覧には入らない。"""
    for op in ops:
        if op.get("op") == "set_role" and pred(op) and not any(r[0] is op for r in outcome.rejected):
            outcome.rejected.append((op, CONFLICT_ROLE_WHY))


def _head(plan, src) -> str:
    p = plan.paras.get(src)
    return "".join(a.text for a in p.atoms if a.kind == "text")[:20] if p is not None else src


# 途中で切れた回答から、図表の位置の指定の一部だけを反映したときの知らせ（要対応。レポートの冒頭・2 章・14 章、Colab、CLI）
PARTIAL_MSG = ("図表の位置の指定（placements）のうち、最後まで書かれていた {n} 件だけを読み取って反映しました（検証で"
               "採用しなかったものは 2 章）。リンクなどの操作（operations）と気づき（notes）は反映していません。AI に出し直して"
               "もらうと、すべてが反映されます。チャットでは「回答が途中で切れました。同じ形式で最初から出し直してください」と"
               "頼み、新しい回答を最初から最後まで貼り付けて変換し直します（続きだけを貼り付けても読めません）。API で自動実行"
               "するときは、もう一度変換します（また途中で切れるときは、"
               "「手動（チャットに貼り付け）」に切り替えて変換し、依頼文をチャットに貼り付けて回答してもらいます）。")


def _read_cut(outcome, text):
    """途中で切れた回答から、最後まで書かれている図表の位置の指定だけを読む（ai_assist.parse_cut_response）。

    読めたら、読み取りの誤りを消して、要対応の説明（outcome.partial）を書く。読めなければ None（outcome は変えない）。
    """
    data = parse_cut_response(text)
    if data is None:
        return None
    outcome.error = ""
    outcome.partial = PARTIAL_MSG.format(n=len(data["placements"]))
    return data


def _spaced(text: str) -> str:
    """文の中に図表の ID（英数字）を挟むときの空白: 先頭・末尾が英数字なら、その側に半角の空白を足す（例:「 F1・F2 」
    「 F1 と段落「…」」）。"""
    return (" " if text[:1].isascii() else "") + text + (" " if text[-1:].isascii() else "")


def _located(plan, src) -> str:
    """レポートの 3 章の場所に使う段落の ID: src に場所（plan.locations）があれば src、なければ（空の段落など、出力しない段落）
    本文でその前にある、場所のある段落（見つからなければ src。場所の欄には段落の ID がそのまま出る）。"""
    if plan.locations.get(src):
        return src
    seq = plan.body_seq
    k = seq.index(src) if src in seq else -1
    while k >= 0:
        if plan.locations.get(seq[k]):
            return seq[k]
        k -= 1
    return src


@dataclass
class Options:
    out_dir: Path
    split_labels: Optional[bool] = None       # None なら雑誌の設定に従う
    ai_mode: str = "none"                     # none / api / manual
    ai_provider: str = "claude"               # API モードで使う AI: claude（推奨）/ openai（ChatGPT）/ gemini / sakana（Sakana AI）
    ai_model: str = DEFAULT_MODEL             # claude 以外では利用者が指定する
    ai_api_key: Optional[str] = None
    ai_response: Optional[str] = None         # 手動モード: AI の回答（JSON）
    pdf_path: Optional[Path] = None
    route: str = "docx"                       # docx（ルート1: docx から作る）/ pdf（ルート2: docx から作り、出版版 PDF で補う）


@dataclass
class Result:
    docx_name: str
    created: str
    tool_version: str
    split_labels: bool
    meta: ArticleMeta
    journal: JournalConfig
    plan: object
    fidelity: object
    dtd_valid: bool
    dtd_errors: list
    jstage_issues: list
    link_counts: dict
    unresolved_after: list
    images: list        # 画像の置き場所と入れた画像（images.SlotImage。XML の順）
    warnings: list
    ai: AIOutcome
    build_notes: list = field(default_factory=list)
    hidden_text: list = field(default_factory=list)
    tracked_changes: int = 0
    comments: int = 0
    has_pdf: bool = False
    output_note: str = ""
    forced_floats: list = field(default_factory=list)   # AI による補完でも位置が決まらず、仮の位置（アンカー段落の後ろ・本文の最後）に置いた図表の説明
    pdf_check: Optional[PdfCheck] = None                # 出版版 PDF との照合（PDF がなければ None）。ルート2 では補った docx との照合
    lost_images: list = field(default_factory=list)     # 画像を入れる場所（置き場所）を作れなかった docx の画像（LostImage。要対応 lost）
    image_problems: list = field(default_factory=list)  # XML の画像の名前が置き場所の一覧と合わない（image_problems の文。要対応 image_names）
    decorations: list = field(default_factory=list)     # 画像の位置に数えなかった飾りの図形（model.Decoration。9 章。知らせない）
    lost_autonums: list = field(default_factory=list)   # Word の自動番号があるのに XML に番号を出さなかった段落（model.LostNumber。要対応）
    pua_chars: list = field(default_factory=list)       # 最終の XML に残った私用領域の文字（model.PuaChar。要対応 pua_left）
    symbols_replaced: list = field(default_factory=list)  # 記号フォントの私用領域の符号を置き換えた記号（model.SymbolReplaced。要確認 symbol_replaced。8 章）
    unshown_numbers: list = field(default_factory=list)  # 番号を出さなかった題目・副題・著者名・所属の段落（BuildInfo.unshown_numbers。10 章）
    table_problems: list = field(default_factory=list)  # 出力した XML の表の形の崩れ（TableProblem。要対応 table_shape）
    tables_checked: int = 0                             # 形を確かめた表の数（12 章。すべての行が削除された空の表は数えない）
    zip_issues: list = field(default_factory=list)      # アップロード用の ZIP を読み直して見つけた問題（package.zip_problems。jstage_issues とは別）
    not_zipped: list = field(default_factory=list)      # 記事フォルダにあるのに ZIP に入れなかったファイル（package.unzipped_files。10 章）
    hidden_images: list = field(default_factory=list)   # 隠し文字の中の画像の ID（Word で表示されないので出力しない）
    # 隠し文字のうち、スタイル・既定の書式の設定で隠した文字 [(src, text)] と画像の ID（規則が暫定なので要確認。6 章）
    style_hidden: list = field(default_factory=list)
    resultless_fields: list = field(default_factory=list)   # 結果を持たないフィールドで、Word では表示のあるもの（model.ResultlessField。要確認 resultless_field。6 章）
    style_hidden_images: list = field(default_factory=list)
    joined: list = field(default_factory=list)          # 段落記号の削除でつないだ段落 [(最初の段落の ID, [段落の ID, …])]（6 章）
    deleted_rows: list = field(default_factory=list)    # 変更履歴で削除された、文字のない表の行（model.DeletedRow。読み飛ばした。6 章）
    newlines: list = field(default_factory=list)        # 段落の中の改行（model.Newline。段落ごと。10 章と、題目などは要確認）
    # 確かめてもらう和文の著者名の分け方 [(段落 ID, builder.EasternSplit)]（BuildInfo.name_splits。要確認 name_split）
    name_splits: list = field(default_factory=list)
    route: str = "docx"
    docx_fix: Optional[DocxFix] = None                  # ルート2: 出版版 PDF で補った docx と、補った箇所・直さなかった箇所
    # ルート2 の補完の確かめ（fidelity.SupplementResult。補った docx が元の docx から、組版の違いと報告した校正の直し以外に
    # 変わっていないか）。ルート1 と、PDF の文字を読めずに補わなかったときは None
    supplement: Optional[SupplementResult] = None
    xml_base: bytes = b""       # 画像の置き場所をすべて書いた XML（目印を除いた形。名前の拡張子は .png。最終の XML は apply_images で作る）
    images_dropped: list = field(default_factory=list)  # 変換し直す前の画像のうち、入れ直さなかったもの（images.DroppedImage。手順 images と 9 章で知らせる）
    images_changed: list = field(default_factory=list)  # キャプションが少し変わった図に入れ直した画像（images.ChangedImage。確かめてもらう）
    xml_path: Optional[Path] = None
    zip_path: Optional[Path] = None
    report_path: Optional[Path] = None
    check_path: Optional[Path] = None       # 図の確かめの一覧（imagelist.write_check。出力フォルダの {記事識別子}_図の確かめ.html。ZIP には入らない）
    prompt_path: Optional[Path] = None
    ai_report_path: Optional[Path] = None

    @property
    def ok(self) -> bool:
        """文字の不変性チェック・最終出力の再チェック・DTD 検証と、ルート2 の補完の確かめ（supplement があるとき）がすべて合格
        （要対応の有無は needs_action）。"""
        return bool(self.fidelity.ok and self.fidelity.final_ok and self.dtd_valid
                    and (self.supplement is None or self.supplement.ok))

    @property
    def needs_action(self) -> bool:
        """要対応の知らせ（report.actions の level が「要対応」）か、残っている必須の手順があるか（report.blocking）。
        コマンドラインの終了コード 1、Colab の手順 8 で一度止める。ok でなければ必ず真（不変性チェック・DTD 検証の不合格は要対応）。
        推奨の手順（AI の回答待ちなど）は数えない。"""
        return bool(blocking(actions(self)))

    @property
    def pdf_fallback(self) -> bool:
        """ルート2（docx から作り、出版版 PDF で補う）で PDF の文字を読めず、docx を補わずに変換した（要対応。M4）。"""
        return report_pdf_fallback(self)


def installed_from_git() -> tuple:
    """pip で GitHub から入れた場合の (ブランチ名, コミット ID)。pip が direct_url.json に記録したもの。"""
    try:
        import json
        from importlib.metadata import distribution
        info = json.loads(distribution("jasme-jats").read_text("direct_url.json") or "{}")
        vcs = info.get("vcs_info") or {}
        return vcs.get("requested_revision", ""), vcs.get("commit_id", "")[:7]
    except Exception:  # noqa: BLE001
        return "", ""


def tool_version() -> str:
    branch, commit = installed_from_git()
    if commit:
        dev = f"開発版: ブランチ {branch}、" if branch and branch != "main" else ""
        return f"{__version__}（{dev}コミット {commit}）"
    try:
        here = Path(__file__).resolve().parent
        rev = subprocess.run(["git", "-C", str(here), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                             timeout=5)
        if rev.returncode == 0 and rev.stdout.strip():
            return f"{__version__}（コミット {rev.stdout.strip()}）"
    except Exception:  # noqa: BLE001
        pass
    return __version__


# 画像を置けない文脈（emit.Ctx の images=False）の要素。段落の文字をこの要素の中に出力していれば、その段落の画像は出力しない
NO_IMAGE_PLACES = {"mixed-citation": "引用文献の段落の中にある（引用文献には画像を出力できない）",
                   "title-group": "題目の段落の中にある（題目には画像を出力できない）",
                   "contrib": "著者名の段落の中にある（著者名には画像を出力できない）",
                   "aff": "所属の段落の中にある（所属には画像を出力できない）",
                   "label": "図表・見出しの番号の中にある（番号には画像を出力できない）"}
REGION_JA = {"front_ja": "和文の冒頭部", "authors": "著者表", "body": "本文", "notes": "付記", "ack": "謝辞", "fn": "注",
             "refs": "引用文献", "back": "後付け", "front_en": "英文の部分", "app": "資料", "excluded": "出力しなかった段落"}
# Word の脚注・文末脚注の段落（ID の頭文字。plan.locations と plan.region がないときの場所）
NOTE_PARTS = {"f": "Word の脚注", "e": "Word の文末脚注"}


def xml_image_names(root) -> list:
    """XML の木の <graphic>・<inline-graphic> の xlink:href（XML の順。重なりも残す）。"""
    return [el.get(XLINK_HREF) or "" for el in root.iter("graphic", "inline-graphic")]


def lost_images(doc, plan, root, info, exclusions, xml_base: bytes) -> tuple:
    """docx の画像の位置のうち、画像の置き場所がないもの（修正計画 W1 の 2.9）。戻り値: (LostImage の一覧, 隠し文字の中の画像の ID の一覧)。

    置き場所がないとは、どの置き場所（info.slots）の covers にも入っていないか、入っている置き場所の名前（info.slot_names）が
    置き場所をすべて書いた XML（xml_base。Result.xml_base）の xlink:href に 1 度も出ていないこと。builder の記録ではなく XML の木で
    調べる。xml_base で調べるので、作業する人が「入れない」とした置き場所と、入れていない任意の置き場所は「置き場所あり」になる
    （最終の XML からは apply_images が取り除くが、ここでは数えない）。図 1 つに <graphic> 1 つで、図に含めた画像はすべてその 1 枚に
    写るとみなす。
    不変性チェック（fidelity）は文字しか見ないので、画像を置けない文脈（題目・著者名・所属・引用文献・番号。emit の
    images=False）の段落や、出力しなかった段落（除外）の中の画像は、ここで調べないと XML からも ZIP からも黙って消える。
    root は組み立てた XML（jx:span の目印が残っているもの）。理由は、画像のある段落の文字を XML のどこに出力したか（jx:span の
    祖先の要素）と、除外の記録から推定する。飾りの図形（ImageRef.decoration）は画像の位置に数えない。
    隠し文字のランの中の画像（ImageRef.hidden）は、Word で表示されないので出力しない（隠し文字と同じ扱い）。別に返す。
    """
    shown = {Path(name).stem for name in xml_image_names(_parse(xml_base))}
    out = {img.image_id for slot in info.slots if Path(info.slot_names.get(slot.key, "")).stem in shown
           for img in slot.covers}
    holder = {}                                  # 画像の ID -> その画像のアトムがある段落
    for p in plan.paras.values():
        for img in p.images:
            holder.setdefault(img.image_id, p)
    places = {}                                  # 段落 ID -> その段落の文字を出力した場所（画像を置けない文脈の理由か ""）
    for sp in root.iter(SPAN):
        name = next((NO_IMAGE_PLACES[a.tag] for a in sp.iterancestors() if a.tag in NO_IMAGE_PLACES), "")
        places.setdefault(sp.get("src"), []).append(name)
    excluded = {}
    for e in exclusions:
        excluded.setdefault(e.src, e.reason)
    floats = {fl.fid: fl for fl in doc.floats}
    lost, hidden = [], []
    for img in doc.images:
        if img.image_id in out:
            continue
        if img.hidden:
            hidden.append(img.image_id)
            continue
        if img.decoration:      # 飾りの図形（枠・白い四角・線など）は画像の位置に数えない（XML に出さない）
            continue
        p = holder.get(img.image_id)
        if p is None:
            lost.append(LostImage(img.image_id, "", "", "画像のある段落が見つからない（変換ツールの不具合の可能性）",
                                  source=img.target))
            continue
        if any(places.get(p.src, [])):
            reason = next(x for x in places[p.src] if x)
        elif excluded.get(p.src) in (REF_IMAGE_EXCLUDED, FN_IMAGE_EXCLUDED):
            reason = excluded[p.src]            # 画像だけの段落の除外の理由が、そのまま画像の知らせの理由（原因と場所の手がかり）
        elif p.src in excluded:
            reason = f"XML に出力しなかった段落（理由「{excluded[p.src]}」）の中にある"
        elif p.src in places:
            reason = "段落は XML に出力したが、画像を入れる場所を XML に書いていない（変換ツールの不具合の可能性）"
        else:
            reason = "段落を XML に出力していない（変換ツールの不具合の可能性）"
        fl = floats.get(img.float_id or p.float_id)
        if fl is not None:
            # 画像だけの段落でも Word で探せるように、図形が結び付いている段落（アンカー段落）の文字も示す
            anchor = plan.paras.get(fl.anchor_src)
            head = anchor.text_only().strip()[:20] if anchor is not None else ""
            reason += (f"。テキストボックス・グループ図形 {fl.fid} の中の画像で、図形は段落 {fl.anchor_src}"
                       f"{f'「{head}」' if head else ' '}に結び付いている")
        elif p.in_textbox:
            reason += "。テキストボックスの中の画像"
        loc = _place(plan, p.src)
        lost.append(LostImage(img.image_id, p.src, loc, reason, text=p.text_only().strip()[:20], source=img.target))
    return lost, hidden


def image_problems(xml_bytes: bytes, images) -> list:
    """最終の XML（apply_images の後）の画像の名前が、画像の置き場所の一覧（images.SlotImage）と合わないところ（要対応 image_names。
    変換ツールの不具合の守りで、ふつうは出ない。修正計画 W1 の 2.9）。戻り値: 内容の文の一覧。

    (1) xlink:href に、置き場所にない名前がある。(2) 同じ名前が 2 回以上出る（同じ画像を 2 つの図が指す。C007 の形）。
    (3) 状態が missing（まだ入れていない）か user（入れた）の置き場所の名前が、XML に出ていない（「入れない」〈skipped〉と、入れていない
    任意〈unused〉の置き場所は、apply_images が要素ごと取り除くので数えない）。
    """
    names = xml_image_names(_parse(xml_bytes))
    known = {i.name for i in images if i.name}
    out = [f"XML の {name or '（名前なし）'} は、画像を入れる場所の一覧にない名前です" for name in dict.fromkeys(names)
           if name not in known]
    for name in dict.fromkeys(names):
        n = names.count(name)
        if n > 1:
            out.append(f"XML に {name} が {n} 回出ています（同じ画像を 2 つ以上の図が指しています）")
    shown = set(names)
    out += [f"{i.key}（{i.name}）が XML に出ていません" for i in images
            if i.status in ("missing", "user") and i.name not in shown]
    return out


def decorations(doc, plan, res) -> list:
    """画像の位置に数えなかった飾りの図形（ImageRef.decoration。隠し文字の中のものを除く）の一覧（model.Decoration。docx の順）。
    修正計画 W1 の 2.8。

    figure は、その飾りが図キャプションのある図形の中にあるときの、その図形の図の置き場所の幹（文字の図形だけのグループで描いた図
    〈data10・data25 の形〉の本体）。飾りの図形は FloatInfo.images に入らないので、図形は ImageRef.float_id で引き、図キャプションが
    図形の中の段落（Para.float_id が同じ）にある図の置き場所を候補にする（キャプションだけの図形を figure_units が組んだ図も入る）。
    候補が 2 つ以上なら、図形の中の docx の順で、その飾りの後ろにある最初の図キャプション（なければ最後の図キャプション）の図
    （2.3 の B3 の covers と同じ決め方。図形そのものの飾りは、図形の中のどの段落よりも前とみなす）。
    """
    anchors = {fl.fid: fl.anchor_src for fl in doc.floats}
    out = []
    for img in doc.images:
        if not img.decoration or img.hidden:
            continue
        out.append(Decoration(img, img.decoration, decoration_where(res, img, anchors.get(img.float_id, "")),
                              _decoration_figure(plan, img)))
    return out


def _decoration_figure(plan, img) -> str:
    """飾りの図形 img が図キャプションのある図形の中にあるときの、その図の置き場所の幹（なければ ""）。decorations の決め方。"""
    if not img.float_id:
        return ""
    order = [src for src, p in plan.paras.items() if p.float_id == img.float_id]
    cands = [s for s in plan.slots if s.kind == "fig" and s.caption is not None and s.caption.float_id == img.float_id]
    if not cands:
        return ""

    def at(slot):
        return order.index(slot.caption.src) if slot.caption.src in order else len(order)
    pos = order.index(img.para_src) if img.para_src in order else -1
    after = sorted((s for s in cands if at(s) > pos), key=at)
    return (after[0] if after else max(cands, key=at)).key


SECTION_JA = {"thead": "見出し行（thead）", "tbody": "本文の行（tbody）", "tfoot": "脚の行（tfoot）"}
NO_RECORD = "組み立ての記録がない表"


def _cell_span(cell, name) -> int:
    try:
        return max(1, int(cell.get(name, "1")))
    except ValueError:
        return 1


def _shape_problems(tbl, expect) -> list:
    """<table> の形を HTML の表の割り当てで調べる。expect は docx の表の列の数（docx がもともと不ぞろいなら None）。"""
    out = []
    for sec in tbl:
        if sec.tag not in SECTION_JA:       # コメントなどは tag が文字列でないので入らない
            continue
        name = SECTION_JA[sec.tag]
        carry = {}                          # 列 -> 上の行の rowspan がまだ覆う行の数（この行を含む）
        trs = [x for x in sec if x.tag == "tr"]
        for k, tr in enumerate(trs, 1):
            cells = [x for x in tr if x.tag in ("th", "td")]
            taken = set(carry)
            nxt = {c: n - 1 for c, n in carry.items() if n > 1}
            if not cells:
                out.append(f"XML の{name}の {k} 行目にセルがない")
            col = 0
            for cell in cells:
                while col in taken:
                    col += 1
                cover = range(col, col + _cell_span(cell, "colspan"))
                rs = _cell_span(cell, "rowspan")
                if any(x in taken for x in cover):
                    out.append(f"XML の{name}の {k} 行目でセルが重なっている")
                taken.update(cover)
                if rs > 1:
                    for x in cover:
                        nxt[x] = rs - 1
                col = cover.stop
            if taken and max(taken) + 1 != len(taken):
                out.append(f"XML の{name}の {k} 行目に、どのセルも覆わない列がある")
            if expect is not None and cells and len(taken) != expect:
                out.append(f"XML の{name}の {k} 行目が {len(taken)} 列ぶん（docx の表は {expect} 列）")
            carry = nxt
        if carry:
            out.append(f"縦の結合（rowspan）が XML の{name}の外にはみ出している")
    return out


def _table_name(tbl, where) -> str:
    anc = next((a for a in tbl.iterancestors("table-wrap", "fig") if a.get("id")), None)
    if anc is None:
        return where
    aid = anc.get("id")
    return f"表 {aid}" if anc.tag == "table-wrap" else f"図 {aid} の中の表"


def _place(plan, src) -> str:
    """段落の場所（plan.locations。なければ領域の名前・Word の脚注など）。"""
    return (plan.locations.get(src) or REGION_JA.get(plan.region.get(src, ""), "") or NOTE_PARTS.get(src[:1], ""))


def lost_autonums(plan, root, info) -> list:
    """Word の自動番号のある段落のうち、段落の文字を XML に出した（jx:span がある）のに、番号（jx:gen kind autonum、src がその段落）を
    出していないもの（model.LostNumber）。不変性チェックは docx の文字しか見ず、番号は docx の文字ではないので、ここで調べないと黙って落ちる。
    root は最後の組み立ての XML（目印が残っているもの）、info はその BuildInfo。次は調べない: 文字を出していない段落（除外・空白だけ・
    画像だけ・段落記号の削除でつないだ後ろの段落）、番号が空白だけの段落、builder が番号を出さないと決めて記録した段落
    （info.unshown_numbers。題目・副題・著者名・所属）。"""
    shown = {g.get("src") for g in root.iter(GEN) if g.get("kind") == "autonum"}
    skip = {u[0] for u in info.unshown_numbers}
    out, seen = [], set()
    for sp in root.iter(SPAN):
        src = sp.get("src")
        if src in seen:
            continue
        seen.add(src)
        p = plan.paras.get(src)
        if p is None or src in shown or src in skip:
            continue
        number = plan.pdf_numbers.get(("auto", src), p.autonum or "").strip()
        if not number:
            continue
        parent = sp.getparent()
        out.append(LostNumber(src, number, _place(plan, src), parent.tag if parent is not None else "",
                              p.text_only().strip()[:20]))
    return out


def pua_chars(plan, root, doc) -> list:
    """最終の XML に残った私用領域（U+E000–U+F8FF）の文字（model.PuaChar）。J-STAGE の画面では読めない文字（豆腐）になる。

    読み取りの置き換え（ooxml の記号の表）や builder の判断には頼らず、組み立ての XML（最終の XML と文字が同じ。目印が残っているもの）
    の文字・属性の値だけを見る。docx の文字（jx:span の中）か Word が付けた生成文字（jx:gen の中。箇条書きの記号・番号）かは目印で、
    フォントは読み取りの記録（doc.symbols。分かるときだけ）で添える。同じ段落・同じ符号・同じ種類は 1 件にまとめる。"""
    fonts = {(s.src, s.code): s.font for s in doc.symbols if not s.to}
    found = {}      # (段落の ID, 符号, 生成文字か, 要素) -> 個数（出現順）

    def note(el, text, owner):
        for c in text or "":
            if is_pua(c):
                src = owner.get("src") or "" if owner is not None else ""
                where = el.getparent().tag if el.tag in (GEN, SPAN) and el.getparent() is not None else el.tag
                key = (src, ord(c), owner is not None and owner.tag == GEN, where if isinstance(where, str) else "")
                found[key] = found.get(key, 0) + 1

    def walk(el, owner):
        if not isinstance(el.tag, str):
            return
        if el.tag in (GEN, SPAN):
            owner = el
        note(el, el.text, owner)
        for v in el.attrib.values():
            note(el, v, None)
        for ch in el:
            walk(ch, owner)
            note(el, ch.tail, owner)

    walk(root, None)
    out = []
    for (src, code, gen, where), n in found.items():
        p = plan.paras.get(src)
        out.append(PuaChar(src=src, code=code, generated=gen, font=fonts.get((src, code), ""), where=where.rsplit("}", 1)[-1], count=n,
                           location=_place(plan, src) if src else "", text=p.text_only().strip()[:20] if p is not None else ""))
    return out


def symbols_replaced(plan, root, doc) -> list:
    """記号フォントの私用領域の符号を Unicode の文字に置き換えたもの（model.SymbolReplaced。置き換えたものだけ）のうち、XML に
    出力したもの。箇条書きの記号は、XML に生成文字（jx:gen kind autonum、src が段落）として出し、その中に置き換えた文字があるもの
    （ルート2 で番号を PDF の字形に合わせたときは、置き換えた文字が残らないので除く）、w:sym・w:t の記号は、段落の文字を XML に出した
    （jx:span がある）もの。文書の順。"""
    spans = {sp.get("src") for sp in root.iter(SPAN)}
    gens = {}
    for g in root.iter(GEN):
        if g.get("kind") == "autonum":
            gens[g.get("src")] = gens.get(g.get("src"), "") + (g.text or "")
    return [s for s in doc.symbols if s.to and (s.to in gens.get(s.src, "") if s.kind == "bullet" else s.src in spans)]


def table_problems(root, info) -> tuple:
    """出力した表の形の確かめ（不変性チェックは文字しか、DTD 検証は要素の並びしか見ないため）。

    builder の結合の判断には頼らず、docx の行ごとの列の数（gridBefore + gridSpan の和 + gridAfter）と、出力した <table> の
    HTML の表の割り当て（行ごとの列の数・セルの重なり・縦の結合の節の外へのはみ出し・セルのない行）だけで判定する。
    docx の表がもともと行ごとに列の数の違う表なら、列の数は比べない。root の外に外した表（数式の画像にした図の中の表）は数えず、
    root の中の組み立ての記録がない <table> は、割り当てだけ確かめて「組み立ての記録がない表」とする。
    戻り値: (TableProblem の一覧, 確かめた表の数)
    """
    found, checked, recorded = [], 0, []
    for tbl, t, where in info.tables:
        if not any(a is root for a in tbl.iterancestors()):     # 外した要素の getroottree() は元の木を指すので、祖先をたどる
            continue
        recorded.append(tbl)
        if not t.rows:
            continue        # 変更履歴ですべての行が削除された表（空の td を 1 つ書く。10 章の警告）
        checked += 1
        widths = {row.grid_before + sum(max(1, c.gridspan) for c in row.cells) + row.grid_after
                  for row in t.rows if row.cells}
        expect = next(iter(widths)) if len(widths) == 1 else None
        probs = list(dict.fromkeys(_shape_problems(tbl, expect)))
        if probs:
            found.append(TableProblem(tid=t.tid, where=where, name=_table_name(tbl, where), problems=probs))
    for tbl in root.iter("table"):
        if any(tbl is x for x in recorded):
            continue
        checked += 1
        probs = list(dict.fromkeys([NO_RECORD] + _shape_problems(tbl, None)))
        found.append(TableProblem(tid="", where=NO_RECORD, name=_table_name(tbl, NO_RECORD), problems=probs))
    return found, checked


def dtd_places(plan) -> dict:
    """DTD 検証のエラーの場所（validate の where）。{XML の id: 場所の文}。

    引用文献（B 番号）・表（T 番号。キャプションの段落）・注（fn 番号）。短く「引用文献 129件目（B129）「冒頭の文字」」の形にする
    （件目は plan.locations と同じ書き方）。文字のない段落（数式だけの引用文献など）は、文字の代わりに、直前の文字のある段落の冒頭を
    添える（Word で探す手がかり）。
    """
    order = list(plan.paras)
    index = {src: i for i, src in enumerate(order)}

    def head(p):
        t = p.text_only().strip()
        return f"{t[:15]}{'…' if len(t) > 15 else ''}"

    def at(p, name):
        if head(p):
            return f"{name}「{head(p)}」"
        prev = next((head(plan.paras[s]) for s in reversed(order[:index.get(p.src, 0)]) if head(plan.paras[s])), "")
        return f"{name}の、文字のない段落 {p.src}" + (f"（直前は「{prev}」）" if prev else "")

    def named(p, kind, xid):
        loc = _place(plan, p.src)
        return f"{loc}（{xid}）" if loc.startswith(kind) else f"{kind} {xid}"
    places = {r.rid: at(r.para, named(r.para, "引用文献", r.rid)) for r in plan.refs if r.rid}
    places.update({t.tid: at(t.caption, f"表 {t.tid}") for t in plan.tables if t.tid and t.caption is not None})
    places.update({f.fid: at(f.paras[0], named(f.paras[0], "注", f.fid)) for f in plan.fns if f.fid and f.paras})
    return places


def _mechanical(docx_path, journal, overrides=None, placements=None):
    doc = read_docx(docx_path)
    plan = classify(doc, journal, overrides, placements)
    linker = link(plan, journal.ref_doi)
    return doc, plan, linker


def fixed_docx_path(docx_path, out_dir, article_id: str) -> Path:
    """ルート2 の、出版版 PDF で補った docx の書き出し先。出力フォルダの「<記事 ID>_PDFで補完した原稿.docx」。

    入力の docx がそのファイル（利用者が前回の補った docx を保存して、同じ出力フォルダでかけ直した）なら、入力を読みながら
    上書きして壊してしまうので、末尾に番号を付けた別の名前（「…_PDFで補完した原稿_2.docx」…）にする。別の名前は、入力とも、
    すでにあるファイルとも重ならないものにする。"""
    out_dir = Path(out_dir)
    path = out_dir / f"{article_id}_PDFで補完した原稿.docx"
    n = 1
    if same_file(docx_path, path):
        while path.exists():            # 入力とも、すでにあるファイルとも重ならない名前
            n += 1
            path = out_dir / f"{article_id}_PDFで補完した原稿_{n}.docx"
    return path


def _drop_fixed(docx_fix, fixed_path):
    """ルート2 で、この変換が書いた「出版版 PDF で補った docx」を消す（変換を中止するとき、中止のあとに残さない）。

    docx_fix が None（ルート1、または PDF の文字を読めず docx を作らなかった）なら何もしない: 前の変換が書いた同じ名前のファイルは、
    この変換のものではないので消さない。"""
    if docx_fix is not None and fixed_path is not None:
        Path(fixed_path).unlink(missing_ok=True)


def convert(docx_path, meta: ArticleMeta, journal: JournalConfig, opts: Options) -> Result:
    docx_path = Path(docx_path)
    out_dir = Path(opts.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    split = journal.split_labels if opts.split_labels is None else opts.split_labels

    docx_name = docx_path.name
    original_docx = docx_path       # 元の docx（ルート2 で docx_path を補った docx に差し替える前。補完の確かめで使う）
    docx_fix = None
    fixed_path = None
    if opts.route == "pdf":
        # ルート2: 出版版 PDF で補った docx（変更履歴つき）を作り、以降はそれを変換する
        if not opts.pdf_path:
            raise ValueError("docx から作り、出版版 PDF で補う（ルート2）には、記事の PDF が必要です")
        fixed = fixed_path = fixed_docx_path(docx_path, out_dir, meta.article_id(journal))
        # 構造の確かめ（K1・K2）と、位置を決められない図表の確かめは、補う前の docx で行う（補った docx を残さない。O7）。
        # 校正の直し（(B)）で見出しの重複が消える原稿でも、利用者が直すのは元の docx なので、元の docx の抜粋を見せて中止する。
        # fixed_docx_path は入力と同じパスにならない（入力がその名前なら番号つきの別の名前）ので、入力は消えない
        _, plan0, _ = _mechanical(docx_path, journal)
        if plan0.structure_conflicts:
            raise StructureConflictError(plan0)
        if plan0.unplaced_floats and opts.ai_mode == "none":
            raise AIRequiredError(plan0)
        docx_fix = make_fixed_docx(docx_path, opts.pdf_path, fixed, journal)
        if docx_fix.check.ok:
            docx_path = fixed
        else:                   # PDF の文字を読めなかった: 元の docx をそのまま変換する（レポートに理由を出す）
            docx_fix = None

    doc, plan, linker = _mechanical(docx_path, journal)
    if plan.structure_conflicts or (plan.unplaced_floats and opts.ai_mode == "none"):
        # AI を呼ぶ前に止める（API の費用をかけず、手動モードでも AI依頼文.txt を書かない）。AI が直せる形（2 つ目の「注」に p など）
        # でも、元の docx で止めて Word で直してもらう。ルート2 で、この run が補った docx を書いていれば消す（(1) をすり抜けたときだけ）
        _drop_fixed(docx_fix, fixed_path)
        if plan.structure_conflicts:
            raise StructureConflictError(plan)
        raise AIRequiredError(plan)
    root, info = build(plan, meta, journal, split)
    outcome = AIOutcome(mode=opts.ai_mode, model=opts.ai_model if opts.ai_mode == "api" else "",
                        provider=opts.ai_provider)
    prompt_path = None
    output_note = ""
    data = None                 # AI の回答（読めたもの）

    # ---------------------------------------------------------------- AI 補完
    if opts.ai_mode in ("api", "manual"):
        # docx の画像は AI に渡さない（図・表の画像は作業する人が用意する。修正計画 W1。call_provider の画像の引数は W8 が消す）
        req_text, _ = build_request(plan, linker, info.exclusions, info.unsplit_names, info.name_splits)
        if opts.ai_mode == "api":
            outcome = call_provider(opts.ai_provider, req_text, [], model=opts.ai_model, api_key=opts.ai_api_key)
            if outcome.raw and (not outcome.error or outcome.cut):
                try:
                    data = parse_response(outcome.raw)
                    outcome.error = ""          # 上限で止まっても、JSON が最後まで書かれていることがある
                except Exception as e:  # noqa: BLE001
                    data = _read_cut(outcome, outcome.raw)      # 途中で切れた回答: 最後まで書かれた位置の指定だけを読む
                    if data is None and not outcome.cut:
                        outcome.error = f"AI の回答を JSON として読めませんでした: {e}"
        else:
            prompt_path = out_dir / "AI依頼文.txt"
            prompt_path.write_text(manual_prompt(req_text), encoding="utf-8")
            if opts.ai_response and opts.ai_response.strip():
                outcome.raw = opts.ai_response
                try:
                    data = parse_response(opts.ai_response)
                except Exception as e:  # noqa: BLE001
                    data = _read_cut(outcome, opts.ai_response)  # 途中で切れた回答: 最後まで書かれた位置の指定だけを読む
                    if data is None:
                        outcome.error = f"貼り付けられた回答を JSON として読めませんでした: {e}"
            else:
                output_note = ("> 手動モード: 「AI依頼文.txt」をチャット（claude.ai など）に貼り付け、返ってきた JSON を"
                               "ツールに貼り戻して再実行すると、AI による補完が反映されます。この出力は AI 補完の前の状態です。")
                if plan.unplaced_floats:
                    output_note += ("位置を決められない図表（3 章）は、AI の回答を反映するまで、図が結び付いている段落"
                                    "（アンカー段落）のすぐ後ろ（箇条書き・引用の途中なら、その終わり。アンカー段落が本文で"
                                    "なければ本文の最後）に仮に置いています。")
                if plan.undecided_boxes:
                    output_note += BOX_PENDING_NOTE
        if data is not None:
            ops = split_ops(data, outcome)
            outcome.notes = [n for n in data.get("notes", []) if isinstance(n, str) and n.strip()]
            overrides = role_overrides(ops, plan, outcome)
            placements = float_placements(data, plan, outcome)
            keys = target_keys(plan)
            # 構造を最初から組み直し（docx を読み直す）、AI の操作を適用する。リンク先は組み直した後の ID に読み替える
            doc, plan, linker = _mechanical(docx_path, journal, overrides, placements)
            if plan.structure_conflicts:
                # 元の docx に衝突がないことは上で確かめたので、AI の回答の set_role で衝突ができた（同じ種類の見出し・英文要旨の
                # 見出しが 2 つになる、所属が著者名に付かなくなる）。中止せず、その set_role を不採用（2 章）にして組み直す。
                # 1 段目: 衝突の範囲（落ちる段落から置き換えた段落まで。著者名の続かない所属は和文の冒頭の中まで。conflict_overrides）
                # の段落への set_role だけを使わない（範囲に指定がなければ飛ばす）。2 段目: なお衝突が残れば、set_role をすべて使わない
                dropped = conflict_overrides(plan, overrides)
                if dropped:
                    _reject_roles(ops, outcome, lambda op: op["src"] in dropped)
                    overrides = {s: r for s, r in overrides.items() if s not in dropped}
                    doc, plan, linker = _mechanical(docx_path, journal, overrides, placements)
                if plan.structure_conflicts:
                    _reject_roles(ops, outcome, lambda op: True)
                    overrides = {}
                    doc, plan, linker = _mechanical(docx_path, journal, overrides, placements)
                if plan.structure_conflicts:
                    # 守り（ここには来ない）: set_role をすべて使わない組み立ては、上で衝突がないと確かめた組み立てと同じになる。
                    # placements は build_body（place_floats・place_boxes）でしか使わず、衝突を作る split_regions・build_front_ja・
                    # build_back・build_front_en は overrides だけで決まる。補った docx は残さない
                    _drop_fixed(docx_fix, fixed_path)
                    raise StructureConflictError(plan)
            retarget_ops(ops, keys, plan)
            for sid, spec in placements.items():
                if sid in plan.float_decisions:
                    outcome.accepted.append((spec["op"], plan.float_decisions[sid]))
                elif "kind" in spec:
                    # 文字だけのテキストボックスへの kind の指定で、組み直した後に使えなくなったもの（同じ回答の set_role で中の段落を
                    # 図表キャプション・除外にして文字だけのテキストボックスでなくなった、kind box の置く位置の段落が本文の段落で
                    # なくなった）。黙って捨てずに、不採用として 2 章に示す
                    why = (f"テキストボックス {sid} は、AI の役割の指定（set_role）を反映して組み直した後に文字だけのテキストボックスで"
                           "なくなったか、置く位置の段落が本文の段落でなくなったので、kind の指定は使わなかった")
                    outcome.rejected.append((spec["op"], why))
                elif spec.get("where") != "end":
                    # 浮動配置の図形の位置の指定で、組み直した後に使えなくなったもの（同じ回答の set_role で、置く位置の段落が本文の
                    # 段落でなくなった。structure.Classifier.place_floats）。黙って捨てずに、不採用として 2 章に示す（本文の外の段落の
                    # 後ろの指定〈where end〉は、検証のときに不採用に記録してある）
                    why = (f"図形 {sid} の置く位置の段落 {spec['after']} は、AI の役割の指定（set_role）を反映して組み直した後に本文の"
                           "段落でなくなったので、位置の指定は使わなかった" if sid in plan.floats else
                           f"図形 {sid} は、AI の役割の指定（set_role）を反映して組み直した後に図表の入った図形でなくなったので、"
                           "位置の指定は使わなかった")
                    outcome.rejected.append((spec["op"], why))
            apply_ops(ops, plan, doc, outcome, split)
            cited = cited_refs(plan)
            plan.uncited_refs = [r.rid for r in plan.refs if r.rid not in cited]
            root, info = build(plan, meta, journal, split)

    # ---------------------------------------------------------------- 出版版 PDF との照合
    pdf_check = None
    if opts.pdf_path:
        marks = {wid: m for wid, (_, m) in word_note_marks(plan, journal).items()}
        pdf_check = check_pdf(plan, opts.pdf_path, fn_marks=marks)
        if opts.route == "pdf" and pdf_check.number_edits:
            # ルート2: Word が付ける番号（docx の文字ではない）の全角・半角と字形（「●」→「・」）を PDF に合わせて組み立て直す
            plan.pdf_numbers = pdf_check.number_edits
            root, info = build(plan, meta, journal, split)

    # ---------------------------------------------------------------- 検証（最終段階）
    fid = verify(docx_path, root, plan.exclusions + info.exclusions)
    final_root = finalize(root)
    xml_base = serialize(final_root)
    images = slot_images(info)
    xml_bytes = apply_images(xml_base, images)      # 最終の XML（入れていない任意の置き場所を取り除く）。確かめはこの XML で
    final_check(root, xml_bytes, fid)
    valid, errors = validate(xml_bytes, dtd_places(plan))
    if not valid and any(getattr(f, "formula", None) is not None for f in plan.figures):
        # AI が書き起こした MathML が DTD に合わない場合は取り消して作り直す
        for f in plan.figures:
            f.formula = None
        for _, d in outcome.accepted:
            if d.category == "formula":
                d.applied = False
                d.message += "（※ DTD 検証で不適合だったため取り消し、画像のみ出力した）"
        root, info = build(plan, meta, journal, split)
        fid = verify(docx_path, root, plan.exclusions + info.exclusions)
        final_root = finalize(root)
        xml_base = serialize(final_root)
        images = slot_images(info)
        xml_bytes = apply_images(xml_base, images)
        final_check(root, xml_bytes, fid)
        valid, errors = validate(xml_bytes, dtd_places(plan))

    # 補完の確かめ（ルート2 で補った docx を作ったときだけ）: 補った docx が元の docx から、組版の違い（(A)）と 13.1 に報告した
    # 校正の直し（(B)）以外に変わっていないか。AI の再変換・DTD 検証の作り直しで docx は変わらないので、1 回でよい
    supplement = None
    if docx_fix is not None:
        # 大文字・小文字を (A) とする段落と番号の元の文字は、照合（pdfmatch）を通さず plan から別に作る（独立の確かめ）
        case_srcs, numbers_original = supplement_targets(
            plan, {wid: m for wid, (_, m) in word_note_marks(plan, journal).items()})
        autonum_srcs = {src for kind, src in numbers_original if kind == "auto"}   # 自動番号のある段落
        supplement = verify_supplement(original_docx, docx_path, docx_fix.fixes, case_srcs, numbers_original,
                                       plan.pdf_numbers, autonum_srcs)

    # 画像の出力漏れ（不変性チェックは文字しか見ない）
    lost, hidden_images = lost_images(doc, plan, root, info, plan.exclusions + info.exclusions, xml_base)
    # 表の形の崩れ（不変性チェックは文字しか、DTD 検証は要素の並びしか見ない）
    table_issues, tables_checked = table_problems(root, info)
    # 自動番号の出力漏れ（番号は docx の文字ではないので、不変性チェックは見ない）
    lost_numbers = lost_autonums(plan, root, info)
    # 私用領域の文字の守り（最終の XML に読めない文字が残っていないか）と、記号フォントの符号の置き換えの記録
    pua_left = pua_chars(plan, root, doc)
    symbols = symbols_replaced(plan, root, doc)

    # ---------------------------------------------------------------- 出力
    aid = meta.article_id(journal)
    jstage_issues = jstage_check(_parse(xml_bytes), aid, [i.name for i in images if i.name])     # 置き場所の名前（画像がまだないものも）
    # ZIP に入れるのは、今回の XML・今回指定した PDF・作業する人が入れた画像だけ（変換の直後は画像はない。記事フォルダに残っている
    # 前回の変換の残りなどは入れない）
    zip_path, adir, has_pdf = write_package(out_dir, journal, meta, xml_bytes, opts.pdf_path, zip_image_names(images))
    flat_xml = out_dir / f"{aid}.xml"
    flat_xml.write_bytes(xml_bytes)

    # AI が解決した箇所は「未解決」から除く
    import unicodedata
    ai_links = [(op["src"], unicodedata.normalize("NFKC", op["text"])) for op, _ in outcome.accepted
                if op["op"].startswith("link_")]
    unresolved_after = []
    for u in linker.unresolved:
        src, raw = u[1], unicodedata.normalize("NFKC", u[2])
        year = unicodedata.normalize("NFKC", u[5]) if len(u) > 5 else None
        if any(s == src and (t == year or (t and t in raw)) for s, t in ai_links):
            continue
        unresolved_after.append(u)
    # 位置を決められなかった図表（仮の位置: アンカー段落のすぐ後ろか、本文の最後に置いている。決定事項 21）
    pending_ai = opts.ai_mode == "manual" and data is None and not outcome.error   # 手動モードで AI の回答を待っている
    forced_floats = []
    read = {op.get("src") for op, _ in outcome.rejected if op.get("op") == "place_float"}   # 指定を読めた（採用しなかった）図形
    for sid in plan.unplaced_floats:
        fi = plan.floats[sid]
        # 手作業で移す XML の要素（図表の ID と、図形の中身から出した本文の段落など）
        targets = float_targets(plan, fi)
        place = plan.float_place(sid)
        where = f"XML の{place}にある{_spaced(targets)}" if targets else f"XML の{place}にある図表の中身"
        if pending_ai:
            detail = (f"テキストボックス・グループ図形 {sid} の位置を決められない（{fi.reason}）。AI の回答を反映すると配置される"
                      f"（今は{place}に仮に置いている）")
        else:
            if fi.end_why == "ai":
                region = REGION_JA.get(plan.region.get(fi.end_after, ""), "本文の外")
                head = (f"AI が本文の外（{region}）の段落 {fi.end_after} の後ろを指定したが、本文の外には図表を置けないため、"
                        "本文の最後に仮に置いた。")
            elif fi.end_why == "anchor":
                head = "図が結び付いている段落が本文の段落でないため、本文の最後に仮に置いた。"
            elif outcome.partial and sid not in read:
                head = f"AI の回答が途中で切れていて、この図表の位置の指定を読み取れなかったため、{place}に仮に置いた。"
            elif data is None and outcome.error:
                head = f"AI の回答を反映できなかったため（2 章）、{place}に仮に置いた。"
            else:
                head = f"AI による補完でも位置を決められなかったため、{place}に仮に置いた。"
            detail = (head + f"手作業で、{where}を正しい位置（Word で表示したときに図の左上の直上にある本文の段落の後）に"
                      f"移すこと。機械的に決められなかった理由: {fi.reason}")
            forced_floats.append(f"{float_caption(fi)}: {where.rstrip()}")
        # 場所の欄はアンカー段落の場所（空の段落なら、その前の段落の場所）
        unresolved_after.append(("float", _located(plan, fi.float.anchor_src), float_caption(fi), detail))
    # 文字だけのテキストボックス: 囲みか図の注記か決められなかったもの（除外。要確認）と、位置を推定して置いた囲み（要確認）
    for xid in plan.undecided_boxes + plan.estimated_boxes:
        bi = plan.textboxes[xid]
        head = next((_para_text(q).strip()[:20] for q in bi.paras if not q.is_blank), "")
        if bi.kind == "undecided" and pending_ai:
            detail = (f"囲みか図の注記か決められない（{bi.why}）。AI の回答を反映すると判断される（今は XML に出力して"
                      "いない）")
        elif bi.kind == "undecided":
            detail = (f"囲みか図の注記か決められない（{bi.why}）。XML に出力していない。AI による補完を使って変換し直すか、"
                      "Word で確かめ、本文に必要な囲みなら文字をテキストボックスの外（本文の段落）に出して変換し直す")
        else:
            detail = (f"囲み（boxed-text）を{plan.box_place(xid)}に置いた（位置は推定: {bi.place_why}）。PDF と見比べ、"
                      "違えば XML の中で boxed-text を正しい位置に移す")
        # 場所の欄はアンカー段落の場所（空の段落なら、その前の段落の場所。本文の外なら「引用文献 3件目」など）
        unresolved_after.append(("box", _located(plan, bi.box.anchor_src), f"テキストボックス {xid}「{head}」", detail))
    warnings = list(dict.fromkeys(doc.warnings + plan.warnings + info.warnings))
    build_notes = [Decision(did=f"M-B{i}", stage="mechanical", category=c, src=s, message=m,
                            location=plan.locations.get(s, "")) for i, (c, s, m) in enumerate(info.notes, 1)]
    res = Result(
        docx_name=docx_name, created=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"), tool_version=tool_version(),
        split_labels=split, meta=meta, journal=journal, plan=plan, fidelity=fid, dtd_valid=valid, dtd_errors=errors,
        jstage_issues=jstage_issues,
        link_counts=linker.count, unresolved_after=unresolved_after, images=images, warnings=warnings, ai=outcome,
        build_notes=build_notes, hidden_text=doc.hidden_text, tracked_changes=doc.tracked_changes,
        comments=doc.comments, has_pdf=has_pdf, output_note=output_note, xml_path=flat_xml, zip_path=zip_path,
        prompt_path=prompt_path, forced_floats=forced_floats, pdf_check=pdf_check, route=opts.route, docx_fix=docx_fix,
        supplement=supplement, lost_images=lost, hidden_images=hidden_images,
        lost_autonums=lost_numbers, unshown_numbers=list(info.unshown_numbers), pua_chars=pua_left, symbols_replaced=symbols,
        table_problems=table_issues, tables_checked=tables_checked, zip_issues=zip_problems(zip_path, journal, meta, images),
        image_problems=image_problems(xml_bytes, images),
        not_zipped=unzipped_files(out_dir, journal, meta, zip_path), joined=doc.joined, deleted_rows=doc.deleted_rows,
        newlines=info.newlines, name_splits=list(info.name_splits), style_hidden=doc.style_hidden, resultless_fields=doc.resultless_fields,
        style_hidden_images=[img.image_id for img in doc.images if img.hidden_style], xml_base=xml_base)
    slots = {slot.key: slot for slot in info.slots}
    for im in res.images:
        im.location = slot_where(res, slots[im.key])
    res.decorations = decorations(doc, plan, res)
    write_check(res)
    report_path = out_dir / f"{aid}_変換レポート.md"
    report_path.write_text(render(res), encoding="utf-8")
    res.report_path = report_path
    if outcome.mode != "none" and (outcome.accepted or outcome.rejected or outcome.error):
        res.ai_report_path = out_dir / f"{aid}_AI判断一覧.md"
        res.ai_report_path.write_text(render_ai_only(res), encoding="utf-8")
    return res


def slot_images(info) -> list:
    """出力した画像の置き場所（info.slots。XML の順）ごとの images.SlotImage（変換の直後: 状態は missing、任意の置き場所は unused）。
    名前は置き場所の名前（info.slot_names。拡張子は .png）。場所の文（location）は、Result を作った後に report.slot_where で入れる。"""
    return [SlotImage(key=slot.key, name=info.slot_names[slot.key], kind=slot.kind, label=slot.label,
                      caption=slot.caption.plain().strip() if slot.caption is not None else "",
                      status="unused" if slot.kind == "optional" else "missing", note=slot.note)
            for slot in info.slots]


def _parse(xml_bytes: bytes):
    """XML のバイト列を木にする（DTD・外部の実体を読まない）。"""
    from lxml import etree
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, huge_tree=True)
    return etree.fromstring(xml_bytes, parser)


def graphics_path(res: Result) -> Path:
    """出力フォルダの中の Graphics フォルダ（画像の置き場所）。"""
    return article_dir(res.zip_path.parent, res.journal, res.meta) / "Graphics"


def _prepare_images(res: Result, supplied: dict) -> dict:
    """入れる画像（add_images の supplied）を確かめ、{幹: (元のファイル名, バイト列, 形式, 大きさ)} にする。確かめだけで、何も書かない。"""
    need = {i.key: i for i in res.images if i.status in ("missing", "user", "skipped", "unused")}
    prepared = {}
    for key, src in supplied.items():
        if key not in need:
            names = "、".join(need) or "なし"
            raise ValueError(f"{key} は、この論文の画像を入れる場所ではありません（この論文の画像の名前: {names}）")
        if isinstance(src, tuple):
            label, data = src
        elif isinstance(src, (bytes, bytearray)):
            label, data = "", bytes(src)
        else:
            label, data = Path(src).name, Path(src).read_bytes()
        data = bytes(data)
        fmt, size = check_user_image(data, label or key)
        prepared[key] = (label, data, fmt, size)
    return prepared


def _store_images(res: Result, prepared: dict, skip=(), unskip=()) -> None:
    """確かめた画像を Graphics/ に書き、置き場所の状態を入れる（XML・ZIP・レポートは作り直さない。rebuild_outputs が行う）。
    skip の置き場所（キャプションのない画像）は「入れない」にする（前に入れた画像があれば消す）。unskip の置き場所は「入れない」をやめて未に戻す。"""
    import hashlib
    gdir = graphics_path(res)
    gdir.mkdir(parents=True, exist_ok=True)
    by_key = {i.key: i for i in res.images}
    for key in list(prepared) + list(skip):
        im = by_key[key]
        stem = Path(im.name).stem
        for old in gdir.glob(f"{stem}.*"):         # 同じ置き場所の前の画像（別の拡張子のものも）
            if old.is_file():
                old.unlink()
        im.name = f"{stem}.png"
        im.source_name, im.format, im.size, im.bytes, im.sha1 = "", "", None, 0, ""
        res.images_changed = [c for c in res.images_changed if c.key != key]     # 入れ直したので、前の画像の確かめは要らない
    for key, (label, data, fmt, size) in prepared.items():
        im = by_key[key]
        im.name = f"{Path(im.name).stem}.{fmt}"
        (gdir / im.name).write_bytes(data)
        im.status, im.source_name, im.format, im.size = "user", label, fmt, size
        im.bytes, im.sha1 = len(data), hashlib.sha1(data).hexdigest()
    for key in skip:
        by_key[key].status = "skipped"
    for key in unskip:
        by_key[key].status = "missing"


def _check_skip(res: Result, skip, supplied) -> list:
    """「入れない」にする置き場所の確かめ（キャプションのない画像だけ。画像を入れる置き場所とは重ならない）。"""
    keys = list(dict.fromkeys(skip or ()))
    by_key = {i.key: i for i in res.images}
    for key in keys:
        im = by_key.get(key)
        if im is None:
            raise ValueError(f"{key} は、この論文の画像を入れる場所ではありません（この論文の画像の名前: {'、'.join(by_key) or 'なし'}）")
        if im.kind != "nocap":
            what = "図・表の画像" if im.kind in ("fig", "table") else "任意の画像"
            raise ValueError(f"{key} は{what}なので、「入れない」にはできません（「入れない」にできるのは、キャプションのない画像だけです）")
        if key in supplied:
            raise ValueError(f"{key} は、画像を入れることと「入れない」を同時に指定できません")
    return keys


def _check_unskip(res: Result, unskip, supplied, skip) -> list:
    """「入れない」をやめる置き場所の確かめ（状態が「入れない」の置き場所だけ。画像を入れる・「入れない」にする置き場所とは重ならない）。"""
    keys = list(dict.fromkeys(unskip or ()))
    by_key = {i.key: i for i in res.images}
    for key in keys:
        im = by_key.get(key)
        if im is None:
            raise ValueError(f"{key} は、この論文の画像を入れる場所ではありません（この論文の画像の名前: {'、'.join(by_key) or 'なし'}）")
        if im.status != "skipped":
            raise ValueError(f"{key} は「入れない」にしていないので、「入れない」をやめることはできません")
        if key in supplied or key in skip:
            raise ValueError(f"{key} は、「入れない」をやめることと、画像を入れること・「入れない」にすることを同時に指定できません")
    return keys


def add_images(res: Result, supplied: dict, skip=None, unskip=None) -> list:
    """作業する人が用意した図・表の画像を Graphics/ に入れ、XML（apply_images）・アップロード用の ZIP・レポートを作り直す。

    supplied: 画像の置き場所の幹（fig03・tab01・img3fa9c2 など。Result.images の key）→ 画像（ファイルのパス、バイト列、または
      (元のファイル名, バイト列)）。元のファイル名は何でもよい。中身が PNG・JPEG・GIF の画像だけを受け付け（images.check_user_image）、
      バイト列をそのまま「{記事識別子}_{幹}.{形式}」の名前で書く（向き・圧縮・透過を変えない）。同じ置き場所の、別の拡張子の
      前の画像は消す。
    skip: 「入れない」とするキャプションのない画像の置き場所の幹（出版版 PDF で見て、ほかの図に写っている・飾りだけ、のとき）。
      その要素は XML から取り除き、手順 images の「全部で」から除く。図・表の幹は断る。
    unskip: 「入れない」をやめて未に戻す置き場所の幹（状態が「入れない」のものだけ）。
    受け付けるのは、この結果の置き場所の幹だけ。それ以外の幹と、PNG・JPEG・GIF でない画像があれば、1 枚も入れずに ValueError。
    入れた後の XML で、文字が変換のときの XML（xml_base）と同じこと（違えば最終出力の再チェックを不合格にする）・DTD・J-STAGE の
    アップロード時チェック・ZIP の確かめをやり直す。戻り値: 入れた画像の幹の一覧（Result.images の順。「入れない」にした幹は含めない）。
    """
    prepared = _prepare_images(res, supplied)
    skipped = _check_skip(res, skip, supplied)
    unskipped = _check_unskip(res, unskip, supplied, skipped)
    if not prepared and not skipped and not unskipped:
        return []
    _store_images(res, prepared, skipped, unskipped)
    rebuild_outputs(res)
    return [i.key for i in res.images if i.key in prepared]      # Result.images の順（XML の順）


# 持ち越しの照合（修正計画 W1 の 2.6）
CARRY_RATIO = 0.8         # キャプションの本体がこの割合以上で同じなら、同じ図とみなす
CARRY_WHERE = 20          # キャプションのない画像の場所を照らす、前の文字のある段落の先頭の字数
WHY_NO_SLOT = "同じキャプションの図が見つかりません（図がなくなったのなら、何もしなくてかまいません）"
WHY_NO_NOCAP = "同じ場所のキャプションのない画像が見つかりません（画像がなくなったのなら、何もしなくてかまいません）"
WHY_NO_OPT = "同じ位置の、画像で補える文字（囲い文字など）が見つかりません（文字がなくなったのなら、何もしなくてかまいません）"
WHY_WHERE = "画像のある場所の前の文章が変わっています"
WHY_ARTICLE = "記事の巻・ページが変わった別の論文なので、前の画像は入れていません"
WHY_NO_BODY = "キャプションが番号だけなので、同じ図か確かめられません"
WHY_SAME_CAPTION = "同じキャプションの図が 2 つ以上あり、どの図の画像か決められません"


def _body_key(text: str) -> str:
    """キャプションの本体を比べる形: NFKC にして、空白と約物（記号を除く句読点・括弧など）を除いたもの。"""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKC", text or "") if not c.isspace() and not unicodedata.category(c).startswith("P"))


def _body_key_plain(text: str) -> str:
    """NFKC にして空白を除いた文字（キャプションのない画像の場所の照合に使う）。"""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKC", text or "") if not c.isspace())


def _where_key(plan, slot) -> str:
    """キャプションのない画像の場所を照らす文字: 前の文字のある段落の先頭 20 字（なければ章の見出しの先頭。NFKC・空白を除く）。"""
    from .structure import text_before
    heading, para = text_before(plan, slot.src, slot)
    owner = para if para is not None else heading
    text = owner.text_only().strip() if owner is not None else ""
    return _body_key_plain(text)[:CARRY_WHERE]


def _slot_layout(res: Result) -> tuple:
    """置き場所の並び全体（任意を除く）: (幹, 種類, キャプションの本体, 場所の段落の先頭 20 字) の並び。変換し直す前と後で同じなら、
    置き場所は変わっていない（AI の回答の反映や、図と関係のない所の直し）ので、同じキャプションの図が並んでいても幹で入れ直せる。"""
    from .structure import caption_body
    if res.plan is None:
        return ()
    return tuple((s.key, s.kind, _body_key(caption_body(s.caption)) if s.caption is not None else "", _where_key(res.plan, s))
                 for s in res.plan.slots if s.kind != "optional")


def kept_images(res: Result) -> dict:
    """変換し直す前に、入れた画像と「入れない」の選択を覚える（修正計画 W1 の 2.6）。戻り値: {幹: images.KeptImage}。

    変換し直すと出力フォルダが消えるので、画像の中身もここで読む。変換し直した後に reapply_images に渡す。
    """
    from .structure import caption_body
    slots = {s.key: s for s in res.plan.slots} if res.plan is not None else {}
    aid = res.meta.article_id(res.journal)
    gdir = graphics_path(res) if res.zip_path is not None else None
    out = {}
    layout = None
    for im in res.images:
        slot = slots.get(im.key)
        if slot is None or im.status not in ("user", "skipped"):
            continue
        data = b""
        if im.status == "user":
            path = gdir / im.name if gdir is not None else None
            if path is None or not path.is_file():
                continue
            data = path.read_bytes()
        if layout is None:
            layout = _slot_layout(res)
        out[im.key] = KeptImage(
            key=im.key, kind=slot.kind, source_name=im.source_name, data=data, caption=im.caption,
            body=caption_body(slot.caption) if slot.caption is not None else "",
            where=_where_key(res.plan, slot) if slot.kind == "nocap" else "", skipped=im.status == "skipped", article_id=aid,
            layout=layout)
    return out


def reapply_images(res: Result, kept: dict) -> list:
    """変換し直した結果 res に、前の画像（kept_images）を、同じ図だと確かめられたものだけ入れ直す（修正計画 W1 の 2.6）。戻り値: 入れ直した幹の一覧。

    同じ記事（記事識別子が同じ）で、図・表は同じ幹・同じ種類の置き場所があり、キャプションの本体（番号を除いた文字）が同じとみなせる（割合 0.8 以上）
    ときだけ入れる。次のときは入れない（別の図の画像を黙って入れないため）。
    - 前の本体が今の別の図の本体と完全に同じ（図が足されて番号がずれた形）。
    - 本体が空（キャプションが番号だけ）で、同じ図か確かめられない。
    - 本体が完全に同じでなく（割合 1 未満）、今の置き場所の本体と完全に同じ本体の、別の前の画像がある（図が消えて番号がずれた形）。
    - 本体が完全に同じでも、同じ本体の前の画像か今の図が 2 つ以上あり、どれがどれか決められない。
    ただし、置き場所の並び全体（幹・種類・本体・場所。_slot_layout）が前と同じなら、置き場所は変わっていないので、上の 2 つ（本体が空・
    同じ本体が 2 つ以上）でも幹で入れ直す（AI の回答の反映や、図と関係のない所の直しで、同じキャプションの図の画像を毎回入れ直さないため）。
    キャプションのない画像は、同じ幹で、場所（前の文字のある段落の先頭 20 字）も同じときだけ。任意の画像は同じ幹なら入れる。入れなかった画像は
    res.images_dropped に、本体が少し変わった図に入れたものは res.images_changed（要確認 image_changed で確かめてもらう）に記録する。
    「入れない」も同じ規則で持ち越す。
    """
    import difflib
    import hashlib
    slots = {s.key: s for s in res.plan.slots}
    by_key = {i.key: i for i in res.images}
    aid = res.meta.article_id(res.journal)
    from .structure import caption_body
    bodies = {k: _body_key(caption_body(s.caption)) for k, s in slots.items() if s.caption is not None}
    old_bodies = {k.key: _body_key(k.body) for k in kept.values() if k.kind in ("fig", "table") and k.article_id == aid}
    prepared, skip, dropped, changed = {}, [], [], []
    layout = _slot_layout(res) if kept else ()

    def drop(k, why, suggest=""):
        if not k.skipped:
            dropped.append(DroppedImage(key=k.key, source_name=k.source_name, caption=k.caption, why=why, suggest=suggest,
                                        sha1=hashlib.sha1(k.data).hexdigest() if k.data else "",
                                        other_article=k.article_id if k.article_id != aid else ""))

    for key, k in kept.items():
        slot = slots.get(key)
        if k.article_id != aid:
            drop(k, WHY_ARTICLE)
            continue
        if k.kind in ("fig", "table"):
            old = old_bodies[key]
            same = [x for x, b in bodies.items() if x != key and slots[x].kind == k.kind and b == old] if old else []
            twins = [x for x, b in old_bodies.items() if x != key and kept[x].kind == k.kind and b == old]
            suggest = same[0] if len(same) == 1 and not twins else ""      # 同じ本体の前の画像が 2 つ以上なら、どれか示さない
            if slot is None or slot.kind != k.kind:
                drop(k, WHY_NO_SLOT, suggest)
                continue
            now = bodies.get(key, "")
            if not (k.layout and k.layout == layout):            # 置き場所の並びが前とまったく同じなら、同じ幹は同じ図（確かめを飛ばす）
                if not old or not now:                          # キャプションが番号だけ: 本体で同じ図か確かめられない
                    drop(k, WHY_NO_BODY if not old else WHY_NO_SLOT, suggest)
                    continue
                if same and now != old:                             # 別の図の本体と完全に同じ（この図は違う）: 著者が図を足して番号がずれた形
                    drop(k, WHY_NO_SLOT, suggest)
                    continue
                rivals = [x for x, b in old_bodies.items() if x != key and kept[x].kind == k.kind and b == now]
                if now == old and (same or rivals):                 # 同じ本体の図・前の画像が 2 つ以上: どれがどれか決められない
                    drop(k, WHY_SAME_CAPTION)
                    continue
                if rivals:                                          # 今の本体は別の前の画像のもの: 図が消えて番号がずれた形
                    drop(k, WHY_NO_SLOT, suggest)
                    continue
                ratio = difflib.SequenceMatcher(None, old, now).ratio()
                if ratio < CARRY_RATIO:
                    drop(k, WHY_NO_SLOT, suggest)
                    continue
                if ratio < 1.0:
                    changed.append(ChangedImage(key=key, source_name=k.source_name, old_caption=k.caption, new_caption=by_key[key].caption))
        elif k.kind == "nocap":
            if slot is None or slot.kind != "nocap":
                drop(k, WHY_NO_NOCAP)
                continue
            if _where_key(res.plan, slot) != k.where:
                drop(k, WHY_WHERE)
                continue
        else:
            if slot is None or slot.kind != k.kind:
                drop(k, WHY_NO_OPT)
                continue
        if k.skipped:
            skip.append(key)
        else:
            prepared[key] = (k.source_name, k.data) + tuple(check_user_image(k.data, k.source_name or key))
    res.images_dropped = dropped
    if not prepared and not skip:
        return []
    _store_images(res, prepared, skip)
    res.images_changed = changed                                # _store_images が、入れ直した幹の前の記録を消すので、その後に入れる
    rebuild_outputs(res)
    return list(prepared)


def rebuild_outputs(res: Result) -> None:
    """入れた画像（res.images）を反映した最終の XML を作り直し（apply_images）、書き出して、確かめをやり直す（修正計画 W1 の 2.6）。

    文字が変換のときの XML（xml_base）と同じか（違えば最終出力の再チェックを不合格にする。今の要対応 fidelity で知らせる）、DTD、
    J-STAGE のアップロード時チェック、XML の画像の名前（image_problems）、ZIP を作り直して読み直した確かめ（画像は、置き場所にない
    名前の画像と、入れたのに ZIP にない画像）と、ZIP に入れなかったファイル。最後にレポートを書き直す。
    """
    xml_bytes = apply_images(res.xml_base, res.images)
    root = _parse(xml_bytes)
    if "".join(root.itertext()) != "".join(_parse(res.xml_base).itertext()):
        res.fidelity.final_ok = False
        res.fidelity.final_differs = True
        res.fidelity.final_detail = "画像を入れて作り直した XML の文字が、変換のときの XML と違う（変換ツールの不具合の可能性）"
    res.dtd_valid, res.dtd_errors = validate(xml_bytes, dtd_places(res.plan))
    aid = res.meta.article_id(res.journal)
    res.jstage_issues = jstage_check(root, aid, [i.name for i in res.images if i.name])
    res.image_problems = image_problems(xml_bytes, res.images)
    out_dir = res.zip_path.parent
    adir = article_dir(out_dir, res.journal, res.meta)
    (adir / f"{aid}.xml").write_bytes(xml_bytes)
    if res.xml_path is not None:
        res.xml_path.write_bytes(xml_bytes)
    make_zip(out_dir, res.journal, res.meta, zip_image_names(res.images), res.has_pdf)
    # ZIP の中身が変わったので、ZIP の確かめと、入れなかったファイルを計算し直す（変換のときの値を残さない）
    res.zip_issues = zip_problems(res.zip_path, res.journal, res.meta, res.images)
    res.not_zipped = unzipped_files(out_dir, res.journal, res.meta, res.zip_path)
    write_check(res)
    res.report_path.write_text(render(res), encoding="utf-8")
