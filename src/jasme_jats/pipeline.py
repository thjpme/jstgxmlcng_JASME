"""変換の全体の流れ。

  1. docx を読み取る（docx_reader）
  2. 段落の役割を決め、論文の構造を組み立てる（structure）
  3. 機械的にリンクを付ける（linker, refparse）
  4. （任意）AI による補完: AI が返した操作を検証し、構造の組み直し・リンクの追加として適用する（ai_assist）
  5. XML を組み立てる（builder）
  6. 文字の不変性チェック（fidelity）… AI 補完を行った場合も、必ずこの最終段階で行う
  7. 目印を取り除いた最終出力を作り、もう一度文字列を照合する（fidelity.final_check）
  8. J-STAGE 指定 DTD で検証する（validate）
  9. J-STAGE のアップロード時のチェックのうち XML だけで判定できるものを再現する（jstage_rules）
 10. 画像の書き出し、J-STAGE のフォルダ構成と ZIP、レポート（images, package, report）

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
                        manual_prompt, parse_response, retarget_ops, role_overrides, split_ops, target_keys)
from .builder import build, finalize, serialize, word_note_marks
from .config import ArticleMeta, JournalConfig
from .docx_reader import read_docx
from .fidelity import final_check, verify
from .images import ImageResult, export_images, user_image
from .jstage_rules import check as jstage_check
from .linker import cited_refs, link
from .model import Decision
from .package import article_dir, make_zip, write_package
from .pdfdocx import DocxFix, make_fixed_docx
from .pdfmatch import PdfCheck, check_pdf
from .report import images_to_prepare, render, render_ai_only
from .structure import classify
from .validate import validate


class AIRequiredError(Exception):
    """位置を機械的に決められない図表があるのに、AI による補完を使わない設定で変換しようとした。"""

    def __init__(self, plan):
        self.floats = [plan.floats[fid] for fid in plan.unplaced_floats]
        lines = [f"- {info.float.fid}: アンカー段落「{_head(plan, info.float.anchor_src)}」付近、"
                 f"{_float_caption(info)}（{info.reason}）" for info in self.floats]
        super().__init__(
            f"この原稿には、位置を機械的に決められない図表（テキストボックス・グループ図形に入った図表）が {len(self.floats)} 件"
            "あります。これらの位置と組み合わせは AI に判断させる必要があるため、AI による補完を「使わない」設定では変換できません。"
            "「API で自動実行」か「手動（チャットに貼り付け）」を選んで、もう一度変換してください。\n" + "\n".join(lines))


def _head(plan, src) -> str:
    p = plan.paras.get(src)
    return "".join(a.text for a in p.atoms if a.kind == "text")[:20] if p is not None else src


def _float_caption(info) -> str:
    """浮動配置の図形の中のキャプション（表のセルの中のものも）の冒頭。"""
    import unicodedata
    from .structure import RE_FIGCAP, RE_TABCAP
    caps = []
    for q in info.paras + [c for t in info.tables for c in t.paragraphs()]:
        t = unicodedata.normalize("NFKC", q.plain()).strip()
        if RE_FIGCAP.match(t) or RE_TABCAP.match(t):
            caps.append(f"「{q.plain().strip()[:20]}」")
    return "".join(caps) or "キャプションなし"


def _float_ids(plan, info) -> str:
    """浮動配置の図形の中身を出力した図・表の ID（F1、T2 など）。"""
    paras, tables = {id(q) for q in info.paras}, {id(t) for t in info.tables}
    ids = [f.fid for f in plan.figures if f.fid and (
        any(id(q) in paras for q in f.image_paras + ([f.caption] if f.caption is not None else []))
        or any(id(t) in tables for t in f.tables))]
    ids += [t.tid for t in plan.tables if t.table is not None and id(t.table) in tables]
    return "・".join(ids)


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
    forced_floats: list = field(default_factory=list)   # AI による補完でも位置が決まらず、本文の冒頭に仮に置いた図表の説明
    pdf_check: Optional[PdfCheck] = None                # 出版版 PDF との照合（PDF がなければ None）。ルート2 では直した docx との照合
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
            if outcome.raw and not outcome.error:
                try:
                    data = parse_response(outcome.raw)
                except Exception as e:  # noqa: BLE001
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
                    outcome.error = f"貼り付けられた回答を JSON として読めませんでした: {e}"
            else:
                output_note = ("> 手動モード: 「AI依頼文.txt」をチャット（claude.ai など）に貼り付け、返ってきた JSON を"
                               "ツールに貼り戻して再実行すると、AI による補完が反映されます。この出力は AI 補完の前の状態です。")
                if plan.unplaced_floats:
                    output_note += ("位置を決められない図表（3 章）は、AI の回答を反映するまで、本文の冒頭に仮に置いています。")
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
    # 位置を決められなかった図表（本文の冒頭に仮に置いている）
    pending_ai = opts.ai_mode == "manual" and data is None and not outcome.error   # 手動モードで AI の回答を待っている
    forced_floats = []
    for sid in plan.unplaced_floats:
        fi = plan.floats[sid]
        ids = _float_ids(plan, fi)
        where = f"XML の本文の冒頭にある {ids}" if ids else "XML の本文の冒頭"
        near = f"図形 {sid} のアンカー段落「{_head(plan, fi.float.anchor_src)}」付近"
        if pending_ai:
            detail = (f"テキストボックス・グループ図形 {sid} の位置を決められない（{fi.reason}）。AI の回答を反映すると配置される"
                      f"（今は本文の冒頭に仮に置いている）")
        else:
            detail = (f"AI による補完でも位置を決められなかったため、本文の冒頭に仮に置いた。手作業で、{where}を正しい位置"
                      f"（Word で表示したときに図の左上の直上にある本文の段落の後。{near}）に移すこと。"
                      f"機械的に決められなかった理由: {fi.reason}")
            forced_floats.append(f"{_float_caption(fi)}: {where}（{near}）")
        unresolved_after.append(("float", fi.float.anchor_src, _float_caption(fi), detail))
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
        prompt_path=prompt_path, forced_floats=forced_floats, pdf_check=pdf_check, route=opts.route, docx_fix=docx_fix)
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
