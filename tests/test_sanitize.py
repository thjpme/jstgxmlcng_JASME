"""tools/sanitize_docx.py: 同じファイルを断る・失敗しても既存の出力を壊さない・個人情報を取り除いても本文の文字を変えない。"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from lxml import etree

import make_fixtures as mf
from conftest import ALL_DOCS, FIXTURES, FLOAT, FLOAT_TEXT, FULL, OUTSIDE, PLACE
from jasme_jats.docx_reader import read_docx
from jasme_jats.fidelity import source_texts
from jasme_jats.pdfdocx import AUTHOR, tracked_counts
from jasme_jats.pipeline import Options, convert

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("sanitize_docx", ROOT / "tools" / "sanitize_docx.py")
sd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sd)
SCRIPT = str(ROOT / "tools" / "sanitize_docx.py")

WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = mf.NSDECL


def test_sanitize_refuses_same_file(tmp_path):
    p = tmp_path / "a.docx"
    shutil.copy(FULL, p)
    before = p.read_bytes()
    with pytest.raises(ValueError, match="同じファイル"):
        sd.sanitize(p, p)
    assert p.read_bytes() == before
    link = tmp_path / "link.docx"
    try:
        os.symlink(p, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink を作れない環境")
    with pytest.raises(ValueError, match="同じファイル"):
        sd.sanitize(p, link)
    assert p.read_bytes() == before


def test_sanitize_failure_keeps_existing_output(tmp_path):
    src = tmp_path / "bad.docx"
    src.write_bytes(b"not a zip")
    dst = tmp_path / "out.docx"
    dst.write_bytes(b"old")
    with pytest.raises(zipfile.BadZipFile):
        sd.sanitize(src, dst)
    assert dst.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.glob("*.docx")) == ["bad.docx", "out.docx"]


def _rewrite(src, dst, edit):
    """edit(name, bytes) -> bytes | None（None は部品を落とす）。追加の部品は edit(None, None) が返す {name: bytes}。"""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = edit(item.filename, zin.read(item.filename))
            if data is not None:
                zout.writestr(item, data)
        for name, data in (edit(None, None) or {}).items():
            zout.writestr(name, data)


def _dirty_docx(tmp_path):
    def parts(b):
        return [mf.para(mf.S["sec1"], "１．はじめに"),
                mf.para(mf.S["body"], "本文の文。",
                        mf.deleted('<w:r><w:t>消した文。</w:t></w:r>'),
                        f'<w:ins w:id="77" w:author="{AUTHOR}" w:date="2026-01-01T00:00:00Z"><w:r><w:t>補</w:t></w:r></w:ins>',
                        '<w:commentRangeStart w:id="1"/><w:r><w:t>注目</w:t></w:r><w:commentRangeEnd w:id="1"/>'
                        '<w:r><w:rPr><w:b/></w:rPr><w:commentReference w:id="1"/></w:r>'),
                mf.para(mf.S["body"], "最後の文。")]
    base = tmp_path / "base.docx"
    mf.make_article(base, "個人情報の取り除きの検証用文書", parts)
    ct_add = ('<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
              '<Override PartName="/word/people.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.people+xml"/>'
              '<Override PartName="/docProps/custom.xml" ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>'
              '<Default Extension="jpeg" ContentType="image/jpeg"/>')
    hdr = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {NS}><w:p><w:r><w:t>架空大学の地の文</w:t></w:r>'
           '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> AUTHOR </w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>架空太郎</w:t></w:r>'
           '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:hdr>')
    ftr = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}><w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
           '<w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>')

    def edit(name, data):
        if name is None:
            return {"word/comments.xml": f'<?xml version="1.0"?><w:comments {NS}><w:comment w:id="1" w:author="架空花子" w:initials="KH"><w:p><w:r><w:t>コメント</w:t></w:r></w:p></w:comment></w:comments>'.encode(),
                    "word/people.xml": f'<?xml version="1.0"?><w:people {NS}/>'.encode(),
                    "word/header9.xml": hdr.encode(), "word/footer9.xml": ftr.encode(),
                    "docProps/custom.xml": b'<?xml version="1.0"?><Properties/>',
                    "docProps/thumbnail.jpeg": b"\xff\xd8\xff\xd9",
                    "customXml/item9.xml": b"<x/>", "customXml/_rels/item9.xml.rels": b"<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'/>"}
        s = data.decode("utf-8") if name.endswith((".xml", ".rels")) else None
        if name in ("word/header9.xml", "word/footer9.xml"):
            return data
        if name == "[Content_Types].xml":
            s = s.replace("</Types>", ct_add + "</Types>")
        elif name == "word/_rels/document.xml.rels":
            s = s.replace("</Relationships>",
                          '<Relationship Id="rId901" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>'
                          '<Relationship Id="rId902" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/people" Target="people.xml"/>'
                          '<Relationship Id="rId903" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header9.xml"/>'
                          '<Relationship Id="rId904" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer9.xml"/>'
                          '<Relationship Id="rId905" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="../customXml/item9.xml"/>'
                          '</Relationships>')
        elif name == "_rels/.rels":
            s = s.replace("</Relationships>",
                          '<Relationship Id="rId801" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail" Target="docProps/thumbnail.jpeg"/>'
                          '<Relationship Id="rId802" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" Target="docProps/custom.xml"/>'
                          '</Relationships>')
        elif name == "word/settings.xml":
            s = re.sub(r"(<w:settings[^>]*>)", r'\1<w:attachedTemplate r:id="rId1"/>', s, count=1)
        elif name == "word/_rels/settings.xml.rels":
            s = s.replace("</Relationships>",
                          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" '
                          'Target="file:///C:/Users/someone/t.dotm" TargetMode="External"/></Relationships>')
        elif name == "docProps/core.xml":
            s = re.sub(r"<dc:creator>.*?</dc:creator>|<dc:creator/>", "<dc:creator>架空太郎</dc:creator>", s)
            s = re.sub(r"<cp:lastModifiedBy>.*?</cp:lastModifiedBy>|<cp:lastModifiedBy/>", "<cp:lastModifiedBy>架空花子</cp:lastModifiedBy>", s)
            s = re.sub(r"<dc:title>.*?</dc:title>|<dc:title/>", "<dc:title>架空の題目</dc:title>", s)
            if "<dc:title>" not in s:
                s = s.replace("</cp:coreProperties>", "<dc:title>架空の題目</dc:title></cp:coreProperties>")
        elif name == "docProps/app.xml":
            s = re.sub(r"<Company>.*?</Company>|<Company/>", "<Company>架空会社</Company>", s)
            s = re.sub(r"<TitlesOfParts>.*?</TitlesOfParts>",
                       '<TitlesOfParts><vt:vector size="1" baseType="lpstr"><vt:lpstr>架空の題目</vt:lpstr></vt:vector></TitlesOfParts>', s, flags=re.S)
        elif name == "word/document.xml":
            s = s.replace("<w:sectPr", '<w:sectPr', 1)
            s = re.sub(r"(<w:sectPr[^>]*>)", r'\1<w:headerReference w:type="even" r:id="rId903"/><w:footerReference w:type="even" r:id="rId904"/>', s, count=1)
        return s.encode("utf-8") if s is not None else data
    src = tmp_path / "dirty.docx"
    _rewrite(base, src, edit)
    return src


def _names(path):
    with zipfile.ZipFile(path) as z:
        return z.namelist()


def test_sanitize_removes_personal_info_and_keeps_text(tmp_path, journal, meta):
    src = _dirty_docx(tmp_path)
    assert "word/comments.xml" in _names(src) and "docProps/thumbnail.jpeg" in _names(src)
    dst = tmp_path / "clean.docx"
    sd.sanitize(src, dst)
    names = _names(dst)
    for gone in ("word/comments.xml", "word/people.xml", "docProps/custom.xml", "docProps/thumbnail.jpeg"):
        assert gone not in names
    assert not [n for n in names if n.startswith("customXml/")]
    with zipfile.ZipFile(dst) as z:
        blob = b"".join(z.read(n) for n in names if n.endswith((".xml", ".rels")))
        text = blob.decode("utf-8")
        assert "commentRangeStart" not in text and "commentReference" not in text and "commentRangeEnd" not in text
        authors = set(re.findall(r'w:author="([^"]*)"', text))
        assert authors <= {sd.AUTHOR_PLACEHOLDER, AUTHOR} and AUTHOR in authors and sd.AUTHOR_PLACEHOLDER in authors
        assert "attachedTemplate" not in text and "someone" not in text
        hdr = etree.fromstring(z.read("word/header9.xml"))
        assert not hdr.findall(".//{%s}t" % WNS)
        ftr = etree.fromstring(z.read("word/footer9.xml"))
        assert [t.text for t in ftr.iter("{%s}t" % WNS)] == ["1"]
        core = etree.fromstring(z.read("docProps/core.xml"))
        for el in core:
            if etree.QName(el).localname in ("creator", "lastModifiedBy", "title"):
                assert not el.text
        app = z.read("docProps/app.xml").decode("utf-8")
        assert "架空会社" not in app and "架空の題目" not in app
        titles = re.search(r"<TitlesOfParts>(.*?)</TitlesOfParts>", app, re.S).group(1)
        assert "<vt:lpstr" in titles and not any(re.findall(r"<vt:lpstr>(.*?)</vt:lpstr>", titles))
        # 残った関係の内部のターゲットと Override の PartName はすべて ZIP にある
        nameset = set(names)
        for n in names:
            if n.endswith(".rels"):
                for rel in etree.fromstring(z.read(n)):
                    if rel.get("TargetMode") != "External":
                        assert sd._rel_target(n, rel.get("Target")) in nameset, (n, rel.get("Target"))
        for o in etree.fromstring(z.read("[Content_Types].xml")).iter(sd.CT_NS + "Override"):
            assert o.get("PartName").lstrip("/") in nameset
        # r 名前空間の属性の値が、その部品の rels の Id にある
        for n in names:
            if n.startswith("word/") and n.endswith(".xml"):
                relname = "word/_rels/" + n[len("word/"):] + ".rels"
                ids = {r.get("Id") for r in etree.fromstring(z.read(relname))} if relname in nameset else set()
                for el in etree.fromstring(z.read(n)).iter():
                    for k, v in el.attrib.items():
                        if k.startswith("{%s}" % RNS) and k.split("}")[1] in ("id", "embed", "link"):
                            assert v in ids, (n, k, v)
    assert tracked_counts(src) == tracked_counts(dst)
    assert source_texts(src) == source_texts(dst)
    opts = lambda d: Options(out_dir=tmp_path / d, convert_metafiles=False)
    a, b = convert(src, meta, journal, opts("o1")), convert(dst, meta, journal, opts("o2"))
    assert b.fidelity.ok
    xa, xb = (next((tmp_path / d).glob("*.xml")).read_bytes() for d in ("o1", "o2"))
    assert xa == xb


@pytest.mark.parametrize("doc", ALL_DOCS + [FLOAT, PLACE, OUTSIDE, FLOAT_TEXT], ids=lambda p: p.name)
def test_sanitize_keeps_text_of_all_fixtures(doc, tmp_path):
    dst = tmp_path / "out.docx"
    sd.sanitize(doc, dst)
    assert source_texts(doc) == source_texts(dst)

    def view(p):
        return [(x.src, x.plain(), x.autonum) for x in read_docx(p).all_paragraphs()]
    assert view(doc) == view(dst)


def test_sanitize_warns_local_external_path(tmp_path, capsys):
    src = tmp_path / "ext.docx"
    _rewrite(FULL, src, lambda n, d: None if n is None else (
        d.replace(b"</Relationships>",
                  b'<Relationship Id="rId950" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                  b'Target="file:///C:/Users/someone/a.png" TargetMode="External"/></Relationships>')
        if n == "word/_rels/document.xml.rels" else d))
    dst = tmp_path / "out.docx"
    sd.sanitize(src, dst)
    err = capsys.readouterr().err
    assert "外部のパスを含む関係" in err and "someone" not in err
    assert dst.exists()


def test_sanitize_cli_same_file(tmp_path):
    p = tmp_path / "a.docx"
    shutil.copy(FULL, p)
    before = p.read_bytes()
    r = subprocess.run([sys.executable, SCRIPT, str(p), str(p)], capture_output=True, text=True)
    assert r.returncode == 1 and "同じファイル" in r.stderr
    assert p.read_bytes() == before


def test_sanitize_cli_bad_input(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a zip")
    r = subprocess.run([sys.executable, SCRIPT, str(bad), str(tmp_path / "o.docx")], capture_output=True, text=True)
    assert r.returncode == 1 and "Traceback" not in r.stderr
    r = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True)
    assert r.returncode == 2


def test_sanitize_keeps_source_permission(tmp_path):
    src = tmp_path / "a.docx"
    shutil.copy(FULL, src)
    os.chmod(src, 0o644)
    dst = tmp_path / "o.docx"
    r = subprocess.run([sys.executable, SCRIPT, str(src), str(dst)], capture_output=True, text=True)
    assert r.returncode == 0
    assert (dst.stat().st_mode & 0o777) == 0o644


def test_sanitize_cli_not_docx_and_broken_xml(tmp_path):
    notdocx = tmp_path / "x.docx"
    with zipfile.ZipFile(notdocx, "w") as z:
        z.writestr("hello.txt", "x")
    out = tmp_path / "o.docx"
    r = subprocess.run([sys.executable, SCRIPT, str(notdocx), str(out)], capture_output=True, text=True)
    assert r.returncode == 1 and "Traceback" not in r.stderr and not out.exists()
    broken = tmp_path / "b.docx"
    with zipfile.ZipFile(FULL) as zin, zipfile.ZipFile(broken, "w") as zout:
        for it in zin.infolist():
            d = zin.read(it.filename)
            zout.writestr(it, b"<broken" if it.filename == "word/settings.xml" else d)
    r = subprocess.run([sys.executable, SCRIPT, str(broken), str(out)], capture_output=True, text=True)
    assert r.returncode == 1 and "Traceback" not in r.stderr and not out.exists()
