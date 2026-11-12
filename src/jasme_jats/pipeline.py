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
  7. 目印を取り除いた最終出力を作り、もう一度文字列を照合する（fidelity.final_check）
  8. J-STAGE 指定 DTD で検証する（validate）
  9. docx の画像のうち XML に出力しなかったもの（画像を置けない場所・出力しなかった段落の中の画像）を調べる（lost_images）。
     あわせて、出力した表の形（行ごとの列の数・セルの重なり・縦の結合の範囲・セルのない行）を調べる（table_problems）。
     Word の自動番号のある段落で、文字を出したのに番号を出していないものも調べる（lost_autonums）。
     最終の XML に私用領域の文字（読めない文字）が残っていないかも調べ（pua_chars）、記号フォントの符号を普通の文字に置き換えた
     記号を集める（symbols_replaced）
 10. J-STAGE のアップロード時のチェックのうち XML だけで判定できるものを再現する（jstage_rules。画像の名前を使うので、
     11 の画像の書き出しの後、ZIP を作る前に、出力した画像の名前で行う）
 11. 画像の書き出し、J-STAGE のフォルダ構成と ZIP（今回の XML・PDF・出力できた画像だけを入れ、読み直して確かめる）、
     レポート（images, package, report）

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
                        image_blocks, manual_prompt, parse_cut_response, parse_response, retarget_ops, role_overrides,
                        split_ops, target_keys)
from .article import _para_text
from .builder import build, finalize, serialize, word_note_marks
from .config import ArticleMeta, JournalConfig
from .docx_reader import read_docx
from .fidelity import SupplementResult, final_check, supplement_targets, verify, verify_supplement
from .images import ImageResult, export_images, user_image
from .jstage_rules import check as jstage_check
from .linker import cited_refs, link
from .model import Decision, LostImage, LostNumber, PuaChar, TableProblem
from .package import article_dir, make_zip, unzipped_files, write_package, zip_image_names, zip_problems
from .pdfdocx import DocxFix, make_fixed_docx, same_file
from .pdfmatch import PdfCheck, check_pdf
from .report import (BOX_PENDING_NOTE, NEEDS_ACTION, actions, figure_body_detail, images_to_prepare, render,
                     render_ai_only, step, structure_conflict_text)
from .report import pdf_fallback as report_pdf_fallback
from .structure import classify, conflict_overrides, float_caption, float_targets
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
    convert_metafiles: bool = True


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
    images: list
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
    lost_images: list = field(default_factory=list)     # docx にあるのに XML に出力しなかった画像（LostImage。要対応）
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
    xml_path: Optional[Path] = None
    zip_path: Optional[Path] = None
    report_path: Optional[Path] = None
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
        """要対応の知らせ（report.actions の level が「要対応」）があるか。コマンドラインの終了コード 1、Colab の手順 8 で
        一度止める。ok でなければ必ず真（不変性チェック・DTD 検証の不合格は要対応）。"""
        return any(a.level == NEEDS_ACTION for a in actions(self))

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


def lost_images(doc, plan, root, info, exclusions) -> tuple:
    """docx の画像のうち、XML に出力しなかったもの。戻り値: (LostImage の一覧, 隠し文字の中の画像の ID の一覧)。

    不変性チェック（fidelity）は文字しか見ないので、画像を置けない文脈（題目・著者名・所属・引用文献・番号。emit の
    images=False）の段落や、出力しなかった段落（除外）の中の画像は、ここで調べないと XML からも Graphics/ からも黙って消える。
    root は組み立てた XML（jx:span の目印が残っているもの）、info はその組み立ての BuildInfo（出力した画像は info.images）。
    理由は、画像のある段落の文字を XML のどこに出力したか（jx:span の祖先の要素）と、除外の記録から推定する。
    隠し文字のランの中の画像（ImageRef.hidden）は、Word で表示されないので出力しない（隠し文字と同じ扱い）。別に返す。
    """
    out = {img.image_id for img in info.images}
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
        p = holder.get(img.image_id)
        if p is None:
            lost.append(LostImage(img.image_id, "", "", "画像のある段落が見つからない（変換ツールの不具合の可能性）",
                                  source=img.target))
            continue
        if any(places.get(p.src, [])):
            reason = next(x for x in places[p.src] if x)
        elif p.src in excluded:
            reason = f"XML に出力しなかった段落（理由「{excluded[p.src]}」）の中にある"
        elif p.src in places:
            reason = "段落は XML に出力したが、画像を出力していない（変換ツールの不具合の可能性）"
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
        req_text, req_images = build_request(plan, linker, info.exclusions, info.unsplit_names, info.name_splits)
        blocks = image_blocks(doc, req_images)
        if opts.ai_mode == "api":
            outcome = call_provider(opts.ai_provider, req_text, blocks, model=opts.ai_model, api_key=opts.ai_api_key)
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
            prompt_path.write_text(manual_prompt(req_text, blocks), encoding="utf-8")
            if blocks:
                img_dir = out_dir / "AI添付画像"
                img_dir.mkdir(exist_ok=True)
                for image_id, mt, data_ in blocks:
                    (img_dir / f"{image_id}.{mt.split('/')[-1].replace('jpeg', 'jpg')}").write_bytes(data_)
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
    xml_bytes = serialize(final_root)
    final_check(root, xml_bytes, fid)
    valid, errors = validate(xml_bytes)
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
        xml_bytes = serialize(final_root)
        final_check(root, xml_bytes, fid)
        valid, errors = validate(xml_bytes)

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
    lost, hidden_images = lost_images(doc, plan, root, info, plan.exclusions + info.exclusions)
    # 表の形の崩れ（不変性チェックは文字しか、DTD 検証は要素の並びしか見ない）
    table_issues, tables_checked = table_problems(root, info)
    # 自動番号の出力漏れ（番号は docx の文字ではないので、不変性チェックは見ない）
    lost_numbers = lost_autonums(plan, root, info)
    # 私用領域の文字の守り（最終の XML に読めない文字が残っていないか）と、記号フォントの符号の置き換えの記録
    pua_left = pua_chars(plan, root, doc)
    symbols = symbols_replaced(plan, root, doc)

    # ---------------------------------------------------------------- 出力
    adir = article_dir(out_dir, journal, meta)
    images = export_images(doc, info.images, adir / "Graphics", convert_metafiles=opts.convert_metafiles,
                           keep_dir=out_dir / "要変換")
    aid = meta.article_id(journal)
    jstage_issues = jstage_check(final_root, aid, [i.name for i in images if i.name])
    # ZIP に入れるのは、今回の XML・今回指定した PDF・出力できた画像だけ（記事フォルダに残っている前回の変換の残りなどは入れない）
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
    # 画像のない図キャプションで、近くの表を図の本体にできなかったもの（structure.Classifier.table_for_figure）
    for src, why in plan.figure_issues:
        unresolved_after.append(("figbody", src, _head(plan, src), figure_body_detail(why)))
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
        table_problems=table_issues, tables_checked=tables_checked, zip_issues=zip_problems(zip_path, journal, meta),
        not_zipped=unzipped_files(out_dir, journal, meta, zip_path), joined=doc.joined, deleted_rows=doc.deleted_rows,
        newlines=info.newlines, name_splits=list(info.name_splits), style_hidden=doc.style_hidden, resultless_fields=doc.resultless_fields,
        style_hidden_images=[img.image_id for img in doc.images if img.hidden_style])
    report_path = out_dir / f"{aid}_変換レポート.md"
    report_path.write_text(render(res), encoding="utf-8")
    res.report_path = report_path
    if outcome.mode != "none" and (outcome.accepted or outcome.rejected or outcome.error):
        res.ai_report_path = out_dir / f"{aid}_AI判断一覧.md"
        res.ai_report_path.write_text(render_ai_only(res), encoding="utf-8")
    return res


def graphics_path(res: Result) -> Path:
    """出力フォルダの中の Graphics フォルダ（画像の置き場所）。"""
    return article_dir(res.zip_path.parent, res.journal, res.meta) / "Graphics"


def add_images(res: Result, supplied: dict, skip_unneeded: bool = False) -> list:
    """利用者が用意した画像（Word の図形で描かれた図など、変換で画像ファイルを作れなかった図の画像）を Graphics/ に入れ、
    アップロード用の ZIP とレポートを作り直す。

    supplied: 出力ファイル名（25_77_01.png など）→ 画像（ファイルのパス、バイト列、または (元のファイル名, バイト列)）。
      元のファイル名は何でもよい。PNG・JPEG・GIF など、または 1 ページの PDF を、出力ファイル名の形式にして入れる。
    受け付けるのは、用意が必要な画像（report.images_to_prepare）の名前だけ。それ以外の名前と読めない画像は ValueError
    （skip_unneeded なら、用意が不要な名前は黙って飛ばす。変換をやり直した後に、前に受け取った画像を入れ直すとき）。
    戻り値: 入れた画像の出力ファイル名。
    """
    need = {name: why for name, _, why in images_to_prepare(res)}
    prepared = {}
    for name, src in supplied.items():
        if name not in need:
            if skip_unneeded:
                continue
            raise ValueError(f"{name} は、用意が必要な画像ではありません（必要なもの: {'、'.join(need) or 'なし'}）")
        if isinstance(src, tuple):
            label, data = src
        elif isinstance(src, (bytes, bytearray)):
            label, data = "", bytes(src)
        else:
            label, data = Path(src).name, Path(src).read_bytes()
        prepared[name] = (label, user_image(data, name, f"「{label}」" if label else ""))
    gdir = graphics_path(res)
    gdir.mkdir(parents=True, exist_ok=True)
    for name, (label, data) in prepared.items():
        (gdir / name).write_bytes(data)
        k = next(k for k, i in enumerate(res.images) if i.name == name)
        old = res.images[k]
        res.images[k] = ImageResult(old.image_id, name, old.source, "user",
                                    f"利用者が用意した画像{f'（{label}）' if label else ''}を入れた。変換のときの状態: {need[name]}")
        res.warnings = [w for w in res.warnings if not w.startswith(f"{old.image_id}:")]
    if prepared:
        out_dir = res.zip_path.parent
        make_zip(out_dir, res.journal, res.meta, zip_image_names(res.images), res.has_pdf)
        # ZIP の中身が変わったので、ZIP の確かめと、入れなかったファイルを計算し直す（変換のときの値を残さない）
        res.zip_issues = zip_problems(res.zip_path, res.journal, res.meta)
        res.not_zipped = unzipped_files(out_dir, res.journal, res.meta, res.zip_path)
        res.report_path.write_text(render(res), encoding="utf-8")
    return list(prepared)
