"""Python 3.10 でも読める書き方か（pyproject は 3.10 以上。CI は 3.10 と 3.12）と、レポートの Markdown に生のタグがないか。

f 文字列の式の中のバックスラッシュ・外側と同じ引用符の入れ子は、3.12 以降でしか読めない。3.12 以降だけで動く環境でも見つけられるよう、
tokenize で確かめる（3.10・3.11 では、読み込むだけで SyntaxError になるので、このテストも確かめの対象外になる）。
"""
import re
import sys
from pathlib import Path

import pytest

from conftest import ALL_DOCS
from jasme_jats.pipeline import Options, convert

ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted(p for d in ("src", "tools", "tests") for p in (ROOT / d).rglob("*.py")
                 if "private" not in p.parts and ".venv" not in p.parts)


def py310_fstring_problems(source: str) -> list:
    """f 文字列の式の中に、3.10・3.11 で SyntaxError になる書き方（バックスラッシュ、外側と同じ引用符）があれば [(行, 理由)]。
    3.12 以降の tokenize（f 文字列を FSTRING_START・FSTRING_END などに分ける）で調べる。"""
    import io
    import tokenize
    found = []
    stack = []          # 開いている f 文字列: [引用符, 置換欄 { の深さ]
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        line = tok.start[0]
        in_field = any(depth > 0 for _, depth in stack)      # いまの位置が、どれかの f 文字列の置換欄の中
        if tok.type == tokenize.FSTRING_START:
            quote = tok.string.lstrip("rRbBfFuU")
            if stack and stack[-1][1] > 0 and quote == stack[-1][0]:
                found.append((line, "f 文字列の式の中に、外側と同じ引用符"))
            stack.append([quote, 0])
        elif tok.type == tokenize.FSTRING_END:
            stack.pop()
        elif tok.type == tokenize.OP and tok.string == "{" and stack:
            stack[-1][1] += 1
        elif tok.type == tokenize.OP and tok.string == "}" and stack:
            stack[-1][1] -= 1
        elif tok.type == tokenize.STRING and in_field:
            if "\\" in tok.string:
                found.append((line, "f 文字列の式の中にバックスラッシュ"))
            if any(depth > 0 and tok.string.lstrip("rRbBuU").startswith(q) for q, depth in stack):
                found.append((line, "f 文字列の式の中に、外側と同じ引用符"))
        elif tok.type == tokenize.FSTRING_MIDDLE and len(stack) > 1 and stack[-2][1] > 0 and "\\" in tok.string:
            found.append((line, "f 文字列の式の中にバックスラッシュ"))
    return found


@pytest.mark.skipif(sys.version_info < (3, 12), reason="3.11 以前では、読み込めない書き方があれば import の時点で失敗する")
def test_detector_finds_py310_fstring_problems():
    assert py310_fstring_problems("x = f\"{'a\\nb'.strip()}\"\n") == [(1, "f 文字列の式の中にバックスラッシュ")]
    assert py310_fstring_problems("x = f\"{d[\"k\"]}\"\n") == [(1, "f 文字列の式の中に、外側と同じ引用符")]
    assert py310_fstring_problems("x = f\"{d['k']}と{y!r:>{w}}\"\ny = f'''{d['k']}'''\n") == []


@pytest.mark.skipif(sys.version_info < (3, 12), reason="3.11 以前では、読み込めない書き方があれば import の時点で失敗する")
def test_sources_use_only_python310_fstring_syntax():
    bad = []
    for path in SOURCES:
        for line, why in py310_fstring_problems(path.read_text(encoding="utf-8")):
            bad.append(f"{path.relative_to(ROOT)}:{line}: {why}")
    assert bad == [], "\n".join(bad)


def test_all_sources_compile():
    """すべての .py が読める（実行している Python の構文で。3.10 で読めるかは上のテストが 3.12 以降で確かめる）。"""
    for path in SOURCES:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def raw_tags(markdown: str) -> list:
    """Markdown のコード（バッククォートで囲んだ部分とコードブロック）の外にある、タグに見える文字 <name…>。"""
    text = re.sub(r"```.*?```", "", markdown, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    return re.findall(r"<[A-Za-z][^<>\n]*>", text)


@pytest.mark.parametrize("split_labels", [False, True])
def test_report_has_no_raw_tags_outside_code(journal, meta, tmp_path, split_labels):
    """変換レポートの Markdown に、タグに見える文字を生で書かない（Markdown を HTML にすると、HTML のタグとして消える）。
    書誌情報の表（抄録の二次利用の説明）・図表番号の扱い・警告などの、ツールが書く文に限る。"""
    for k, docx in enumerate(ALL_DOCS):
        res = convert(docx, meta, journal, Options(out_dir=tmp_path / f"o{k}", split_labels=split_labels,
                                                   convert_metafiles=False))
        text = res.report_path.read_text(encoding="utf-8")
        assert raw_tags(text) == [], (docx.name, raw_tags(text)[:5])


def test_md_tag_wraps_tags_in_code():
    from jasme_jats.report import md_tag
    assert md_tag("a <label> b <xref ref-type=\"fig\" rid=\"x\"> c") == "a `<label>` b `<xref ref-type=\"fig\" rid=\"x\">` c"
    assert md_tag("`<label>` と 1 < 2 > 0") == "`<label>` と 1 < 2 > 0"       # 囲み済み・タグでない < はそのまま
