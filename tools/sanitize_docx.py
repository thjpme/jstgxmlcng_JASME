"""テスト用に公開リポジトリへ入れる docx から、コメントと作成者などの個人情報を取り除く。

  python tools/sanitize_docx.py 入力.docx 出力.docx

取り除くもの: コメント（comments*.xml, people.xml と本文中のコメント範囲）、文書のプロパティの作成者・最終更新者。
本文の文字には触れない。
"""
import re
import sys
import zipfile

DROP_PARTS = {"word/comments.xml", "word/commentsExtended.xml", "word/commentsExtensible.xml", "word/commentsIds.xml",
              "word/people.xml"}


def sanitize(src, dst):
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            name = item.filename
            if name in DROP_PARTS:
                continue
            data = zin.read(name)
            if name == "word/document.xml":
                s = data.decode("utf-8")
                s = re.sub(r"<w:commentRangeStart [^>]*/>|<w:commentRangeEnd [^>]*/>", "", s)
                s = re.sub(r"<w:r>(?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?<w:commentReference [^>]*/></w:r>", "", s)
                s = re.sub(r"<w:r [^>]*>(?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?<w:commentReference [^>]*/></w:r>", "", s)
                data = s.encode("utf-8")
            elif name == "word/_rels/document.xml.rels":
                s = data.decode("utf-8")
                s = re.sub(r'<Relationship [^>]*Target="(?:comments|commentsExtended|commentsExtensible|commentsIds|people)\.xml"/>',
                           "", s)
                data = s.encode("utf-8")
            elif name == "[Content_Types].xml":
                s = data.decode("utf-8")
                s = re.sub(r'<Override PartName="/word/(?:comments|commentsExtended|commentsExtensible|commentsIds|people)\.xml"[^>]*/>',
                           "", s)
                data = s.encode("utf-8")
            elif name == "docProps/core.xml":
                s = data.decode("utf-8")
                s = re.sub(r"<dc:creator>.*?</dc:creator>", "<dc:creator></dc:creator>", s)
                s = re.sub(r"<cp:lastModifiedBy>.*?</cp:lastModifiedBy>", "<cp:lastModifiedBy></cp:lastModifiedBy>", s)
                data = s.encode("utf-8")
            elif name == "docProps/app.xml":
                s = data.decode("utf-8")
                s = re.sub(r"<Company>.*?</Company>", "<Company></Company>", s)
                data = s.encode("utf-8")
            zout.writestr(item, data)


if __name__ == "__main__":
    sanitize(sys.argv[1], sys.argv[2])
    print("written:", sys.argv[2])
