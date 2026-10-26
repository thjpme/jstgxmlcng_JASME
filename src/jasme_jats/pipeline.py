"""変換の全体の流れ。

  1. docx を読み取る（docx_reader）
  2. 段落の役割を決め、論文の構造を組み立てる（structure）
  3. 機械的にリンクを付ける（linker, refparse）
  4. （任意）AI による補完: AI が返した操作を検証し、構造の組み直し・リンクの追加として適用する（ai_assist）。
     回答が途中で切れていたら、最後まで書かれた図表の位置の指定（placements）だけを読んで反映し、要対応として知らせる
  5. XML を組み立てる（builder）
  6. 文字の不変性チェック（fidelity）… AI 補完を行った場合も、必ずこの最終段階で行う
  7. 目印を取り除いた最終出力を作り、もう一度文字列を照合する（fidelity.final_check）
  8. J-STAGE 指定 DTD で検証する（validate）
  9. docx の画像のうち XML に出力しなかったもの（画像を置けない場所・出力しなかった段落の中の画像）を調べる（lost_images）
 10. J-STAGE のアップロード時のチェックのうち XML だけで判定できるものを再現する（jstage_rules）
 11. 画像の書き出し、J-STAGE のフォルダ構成と ZIP、レポート（images, package, report）

作り方は 2 通り（Options.route）:
  ルート1（docx）: docx から作る。docx の文字は 1 文字も変えない。記事の PDF があれば照合して、違いをレポートに載せるだけ（pdfmatch）
  ルート2（pdf） : 出版版 PDF に合わせて直した docx（Word の変更履歴つき）を先に作り（pdfdocx）、それをルート1 と同じ処理で
                   変換する。Word が付ける番号（自動番号・脚注番号）は docx の文字ではないので、変換のときに全角・半角を PDF に合わせる
"""
from __future__ import annotations

import datetime as _dt
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import __version__
from .ai_assist import (AIOutcome, apply_ops, build_request, call_provider, float_placements, image_blocks,
                        manual_prompt, parse_cut_response, parse_response, retarget_ops, role_overrides, split_ops,
                        target_keys)
from .builder import build, finalize, serialize, word_note_marks
from .config import ArticleMeta, JournalConfig
from .docx_reader import read_docx
from .fidelity import final_check, verify
from .images import ImageResult, export_images, user_image
from .jstage_rules import check as jstage_check
from .linker import cited_refs, link
from .model import Decision, LostImage
from .package import article_dir, make_zip, write_package
from .pdfdocx import DocxFix, make_fixed_docx
from .pdfmatch import PdfCheck, check_pdf
from .report import figure_body_detail, images_to_prepare, render, render_ai_only
from .structure import classify, float_caption, float_targets
from .tracking import SPAN
from .validate import validate


class AIRequiredError(Exception):
    """位置を機械的に決められない図表があるのに、AI による補完を使わない設定で変換しようとした。"""

    def __init__(self, plan):
        self.floats = [plan.floats[fid] for fid in plan.unplaced_floats]
        lines = [f"- {info.float.fid}: アンカー段落「{_head(plan, info.float.anchor_src)}」付近、"
                 f"{float_caption(info)}（{info.reason}）" for info in self.floats]
        super().__init__(
            f"この原稿には、位置を機械的に決められない図表（テキストボックス・グループ図形に入った図表）が {len(self.floats)} 件"
            "あります。これらの位置と組み合わせは AI に判断させる必要があるため、AI による補完を「使わない」設定では変換できません。"
            "「API で自動実行」か「手動（チャットに貼り付け）」を選んで、もう一度変換してください。\n" + "\n".join(lines))


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
    ai_provider: str = "claude"               # API モードで使う AI: claude（推奨）/ openai（ChatGPT）/ gemini
    ai_model: str = "claude-opus-5-5"         # claude 以外では利用者が指定する
    ai_api_key: Optional[str] = None
    ai_response: Optional[str] = None         # 手動モード: AI の回答（JSON）
    pdf_path: Optional[Path] = None
    route: str = "docx"                       # docx（ルート1: docx から作る）/ pdf（ルート2: 出版版 PDF に合わせてから作る）
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
    pdf_check: Optional[PdfCheck] = None                # 出版版 PDF との照合（PDF がなければ None）。ルート2 では直した docx との照合
    lost_images: list = field(default_factory=list)     # docx にあるのに XML に出力しなかった画像（LostImage。要対応）
    hidden_images: list = field(default_factory=list)   # 隠し文字の中の画像の ID（Word で表示されないので出力しない）
    route: str = "docx"
    docx_fix: Optional[DocxFix] = None                  # ルート2: PDF に合わせて直した docx と、直した箇所
    xml_path: Optional[Path] = None
    zip_path: Optional[Path] = None
    report_path: Optional[Path] = None
    prompt_path: Optional[Path] = None
    ai_report_path: Optional[Path] = None

    @property
    def ok(self) -> bool:
        return bool(self.fidelity.ok and self.fidelity.final_ok and self.dtd_valid)


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
        loc = (plan.locations.get(p.src) or REGION_JA.get(plan.region.get(p.src, ""), "")
               or NOTE_PARTS.get(p.src[:1], ""))
        lost.append(LostImage(img.image_id, p.src, loc, reason, text=p.text_only().strip()[:20], source=img.target))
    return lost, hidden


def _mechanical(docx_path, journal, overrides=None, placements=None):
    doc = read_docx(docx_path)
    plan = classify(doc, journal, overrides, placements)
    linker = link(plan, journal.ref_doi)
    return doc, plan, linker


def convert(docx_path, meta: ArticleMeta, journal: JournalConfig, opts: Options) -> Result:
    docx_path = Path(docx_path)
    out_dir = Path(opts.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    split = journal.split_labels if opts.split_labels is None else opts.split_labels

    docx_name = docx_path.name
    docx_fix = None
    if opts.route == "pdf":
        # ルート2: 出版版 PDF に合わせて直した docx（変更履歴つき）を作り、以降はそれを変換する
        if not opts.pdf_path:
            raise ValueError("出版版 PDF に合わせてから作る（ルート2）には、記事の PDF が必要です")
        fixed = out_dir / f"{meta.article_id(journal)}_PDFに合わせた原稿.docx"
        docx_fix = make_fixed_docx(docx_path, opts.pdf_path, fixed, journal)
        if docx_fix.check.ok:
            docx_path = fixed
        else:                   # PDF の文字を読めなかった: 元の docx をそのまま変換する（レポートに理由を出す）
            docx_fix = None

    doc, plan, linker = _mechanical(docx_path, journal)
    if plan.unplaced_floats and opts.ai_mode == "none":
        raise AIRequiredError(plan)
    root, info = build(plan, meta, journal, split)
    outcome = AIOutcome(mode=opts.ai_mode, model=opts.ai_model if opts.ai_mode == "api" else "",
                        provider=opts.ai_provider)
    prompt_path = None
    output_note = ""
    data = None                 # AI の回答（読めたもの）

    # ---------------------------------------------------------------- AI 補完
    if opts.ai_mode in ("api", "manual"):
        unsplit = [(src, msg.split("「", 1)[-1].split("」", 1)[0]) for cat, src, msg in info.notes if cat == "name"]
        req_text, req_images = build_request(plan, linker, info.exclusions, unsplit)
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
        if data is not None:
            ops = split_ops(data)
            outcome.notes = [str(n) for n in data.get("notes", []) if str(n).strip()]
            overrides = role_overrides(ops, plan, outcome)
            placements = float_placements(data, plan, outcome)
            keys = target_keys(plan)
            # 構造を最初から組み直し（docx を読み直す）、AI の操作を適用する。リンク先は組み直した後の ID に読み替える
            doc, plan, linker = _mechanical(docx_path, journal, overrides, placements)
            retarget_ops(ops, keys, plan)
            for sid, spec in placements.items():
                if sid in plan.float_decisions:
                    outcome.accepted.append((spec["op"], plan.float_decisions[sid]))
            apply_ops(ops, plan, doc, outcome)
            cited = cited_refs(plan)
            plan.uncited_refs = [r.rid for r in plan.refs if r.rid not in cited]
            root, info = build(plan, meta, journal, split)

    # ---------------------------------------------------------------- 出版版 PDF との照合
    pdf_check = None
    if opts.pdf_path:
        marks = {wid: m for wid, (_, m) in word_note_marks(plan, journal).items()}
        pdf_check = check_pdf(plan, opts.pdf_path, fn_marks=marks)
        if opts.route == "pdf" and pdf_check.number_edits:
            # ルート2: Word が付ける番号（docx の文字ではない）の全角・半角を PDF に合わせて組み立て直す
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

    # 画像の出力漏れ（不変性チェックは文字しか見ない）
    lost, hidden_images = lost_images(doc, plan, root, info, plan.exclusions + info.exclusions)

    # ---------------------------------------------------------------- 出力
    adir = article_dir(out_dir, journal, meta)
    images = export_images(doc, info.images, adir / "Graphics", convert_metafiles=opts.convert_metafiles)
    aid = meta.article_id(journal)
    jstage_issues = jstage_check(final_root, aid, [i.name for i in images if i.name])
    zip_path, adir, has_pdf = write_package(out_dir, journal, meta, xml_bytes, opts.pdf_path)
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
    # 画像のない図キャプションで、近くの表を図の本体にできなかったもの（structure.Classifier.table_for_figure）
    for src, why in plan.figure_issues:
        unresolved_after.append(("figbody", src, _head(plan, src), figure_body_detail(why)))
    warnings = list(dict.fromkeys(doc.warnings + info.warnings))
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
        lost_images=lost, hidden_images=hidden_images)
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
        make_zip(res.zip_path.parent, res.journal, res.meta)
        res.report_path.write_text(render(res), encoding="utf-8")
    return list(prepared)
