"""テスト用に公開リポジトリへ入れる docx から、コメントと作成者などの個人情報を取り除く。

  python tools/sanitize_docx.py 入力.docx 出力.docx

入力と同じファイルは出力に指定できない（元の docx を残すため、断る）。一時ファイルに書き出し、本文の文字
（`fidelity.source_texts`）と `word/media/` の画像の名前が入力と同じことを確かめてから出力に置き換える
（確かめに通らなければ出力には触れない）。

取り除く部品: コメント（comments*.xml・people.xml）、`customXml/`、`docProps/custom.xml`、`docProps/thumbnail.*`
（1 ページ目の画像。題目・氏名が写る）と、それらを指す関係・`[Content_Types].xml` の Override。
取り除く要素・属性: 本文・脚注・文末脚注のコメントの範囲と参照、`w:attachedTemplate` とその関係（テンプレートのパス）、
ヘッダー/フッターの文字のラン（ページ番号のフィールド PAGE・NUMPAGES・SECTIONPAGES の結果は残す）。
空にするもの: 文書のプロパティの作成者・最終更新者・題目・主題・説明・キーワード・分類、app.xml の Company・Manager・
HyperlinkBase と TitlesOfParts の文字列、`w:initials`。
置き換えるもの: 変更履歴などの `w:author`（`pdfdocx.AUTHOR` 以外）を「作成者」にする。`pdfdocx.AUTHOR` は、このツールの
変更履歴を作成者名で見分ける処理（`fidelity._ours` ほか）のために残す。
取り除かないもの: `w:rsid*`、`w14:paraId`、変更履歴の `w:date`、本文の `w:customXml` 要素（本文の文字を包むもの）、
外部ハイパーリンク、styles・numbering・theme・fontTable、ヘッダー/フッターのページ番号のフィールド。
残った関係に外部のローカルのパスがあれば、警告を標準エラーに出す（書き出しは止めない）。
"""
import os
import posixpath
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

from jasme_jats.fidelity import source_texts
from jasme_jats.ooxml import w
from jasme_jats.pdfdocx import AUTHOR

AUTHOR_PLACEHOLDER = "作成者"
SAME_FILE_MSG = "入力と出力に同じファイルが指定されています。元の docx を残すため、出力には別のファイル名を指定してください"
CHANGED_MSG = "本文の文字が変わったので書き出さなかった（このツールの不具合です）"
COMMENT_PARTS = re.compile(r"word/(?:comments|commentsExtended|commentsExtensible|commentsIds|people)\.xml$")
DROP_PARTS = re.compile(r"(?:customXml/.*|docProps/custom\.xml|docProps/thumbnail\.[A-Za-z]+)$")
HF_PART = re.compile(r"word/(?:header|footer)\d*\.xml$")
PAGE_FIELD = re.compile(r"(?:PAGE|NUMPAGES|SECTIONPAGES)\b", re.I)
LOCAL_PATH = re.compile(r"^(?:file:|[A-Za-z]:\\|\\\\|/Users/|/home/)|Users\\")

COMMENT_TAGS = {w("commentRangeStart"), w("commentRangeEnd"), w("commentReference")}
DC = "{http://purl.org/dc/elements/1.1/}"
CP = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
CORE_BLANK = (DC + "creator", CP + "lastModifiedBy", DC + "title", DC + "subject", DC + "description",
              CP + "keywords", CP + "category")
APP_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"
VT_LPSTR = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}lpstr"
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"


def _dropped(name: str) -> bool:
    return bool(COMMENT_PARTS.match(name) or DROP_PARTS.match(name))


def _rel_target(rels_name: str, target: str) -> str:
    """rels の Target が指す部品の名前（ZIP の中のパス）。"""
    if target.startswith("/"):
        return target[1:]
    base = posixpath.dirname(posixpath.dirname(rels_name))
    return posixpath.normpath(posixpath.join(base, target))


def _bytes(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _is_page_instr(instr: str) -> bool:
    return bool(PAGE_FIELD.match(instr.strip()))


def _strip_header_footer_text(root) -> bool:
    """ヘッダー/フッターの文字のランを取り除く。ページ番号のフィールドの結果は残す。"""
    stack = []   # フィールドの状態（文書の順。段落をまたぐフィールドもある）
    victims = []
    for el in root.iter():
        if el.tag == w("fldChar"):
            kind = el.get(w("fldCharType"))
            if kind == "begin":
                stack.append({"instr": "", "sep": False})
            elif kind == "separate" and stack:
                stack[-1]["sep"] = True
            elif kind == "end" and stack:
                stack.pop()
        elif el.tag == w("instrText"):
            if stack and not stack[-1]["sep"]:
                stack[-1]["instr"] += el.text or ""
        elif el.tag == w("r"):
            if el.find(w("t")) is None and el.find(w("delText")) is None:
                continue
            if stack and stack[-1]["sep"] and _is_page_instr(stack[-1]["instr"]):
                continue
            simple = next((a for a in el.iterancestors(w("fldSimple"))), None)
            if simple is not None and _is_page_instr(simple.get(w("instr")) or ""):
                continue
            victims.append(el)
    for el in victims:
        el.getparent().remove(el)
    return bool(victims)


def clean_part(name: str, data: bytes) -> bytes:
    """部品 1 つの個人情報を取り除く。変えたときだけ作り直し、変えなければ元のバイト列を返す。"""
    if name.startswith("word/") and name.endswith(".xml"):
        root = etree.fromstring(data)
        changed = False
        for el in list(root.iter(*COMMENT_TAGS)):
            parent = el.getparent()
            parent.remove(el)
            changed = True
            if parent.tag == w("r") and all(ch.tag == w("rPr") for ch in parent):
                parent.getparent().remove(parent)
        for el in root.iter():
            author = el.get(w("author"))
            if author is not None and author not in (AUTHOR, AUTHOR_PLACEHOLDER):
                el.set(w("author"), AUTHOR_PLACEHOLDER)
                changed = True
            if el.get(w("initials")):
                el.set(w("initials"), "")
                changed = True
        if HF_PART.match(name) and _strip_header_footer_text(root):
            changed = True
        if name == "word/settings.xml":
            for el in list(root.iter(w("attachedTemplate"))):
                el.getparent().remove(el)
                changed = True
        return _bytes(root) if changed else data
    if name.endswith(".rels"):
        root = etree.fromstring(data)
        changed = False
        for rel in list(root):
            target, kind = rel.get("Target", ""), rel.get("Type", "")
            if kind.endswith("/attachedTemplate") or (
                    rel.get("TargetMode") != "External" and _dropped(_rel_target(name, target))):
                root.remove(rel)
                changed = True
        return _bytes(root) if changed else data
    if name == "[Content_Types].xml":
        root = etree.fromstring(data)
        changed = False
        for el in list(root.iter(CT_NS + "Override")):
            if _dropped(el.get("PartName", "").lstrip("/")):
                root.remove(el)
                changed = True
        return _bytes(root) if changed else data
    if name == "docProps/core.xml":
        root = etree.fromstring(data)
        changed = False
        for tag in CORE_BLANK:
            for el in root.iter(tag):
                if el.text:
                    el.text = None
                    changed = True
        return _bytes(root) if changed else data
    if name == "docProps/app.xml":
        root = etree.fromstring(data)
        changed = False
        targets = [el for tag in ("Company", "Manager", "HyperlinkBase") for el in root.iter(APP_NS + tag)]
        for titles in root.iter(APP_NS + "TitlesOfParts"):
            targets.extend(titles.iter(VT_LPSTR))
        for el in targets:
            if el.text:
                el.text = None
                changed = True
        return _bytes(root) if changed else data
    return data


def _media(path) -> set:
    with zipfile.ZipFile(path) as z:
        return {n for n in z.namelist() if n.startswith("word/media/")}


def _warn_external_paths(path) -> None:
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith(".rels"):
                continue
            for rel in etree.fromstring(z.read(name)):
                if rel.get("TargetMode") == "External" and LOCAL_PATH.search(rel.get("Target", "")):
                    kind = rel.get("Type", "").rsplit("/", 1)[-1]
                    print("警告: 外部のパスを含む関係が残っています（" + name + "、" + kind + "）", file=sys.stderr)


def sanitize(src, dst) -> None:
    src, dst = Path(src), Path(dst)
    if dst.exists() and os.path.samefile(src, dst):
        raise ValueError(SAME_FILE_MSG)
    with zipfile.ZipFile(src) as z:
        if "word/document.xml" not in z.namelist():
            raise ValueError("docx ではありません（word/document.xml がありません）。書き出しません。")
    fd, tmp = tempfile.mkstemp(suffix=".docx", dir=str(dst.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                name = item.filename
                if _dropped(name):
                    continue
                data = b"" if item.is_dir() else clean_part(name, zin.read(name))
                zout.writestr(item, data)
        if source_texts(src) != source_texts(tmp) or _media(src) != _media(tmp):
            raise ValueError(CHANGED_MSG)
        _warn_external_paths(tmp)
        shutil.copymode(src, tmp)  # mkstemp の 0600 ではなく、元の権限に合わせる
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) != 2:
        print("使い方: python tools/sanitize_docx.py 入力.docx 出力.docx", file=sys.stderr)
        return 2
    try:
        sanitize(argv[0], argv[1])
    except (ValueError, OSError, zipfile.BadZipFile) as e:
        print(str(e) or type(e).__name__, file=sys.stderr)
        return 1
    except (etree.XMLSyntaxError, KeyError) as e:
        print("docx の部品を読めませんでした（" + type(e).__name__ + "： " + str(e) + "）。書き出しません。", file=sys.stderr)
        return 1
    print("written:", argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
