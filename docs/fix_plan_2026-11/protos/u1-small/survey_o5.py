import zipfile, glob, re, os, collections
files = sorted(glob.glob("/home/user/jstgxmlcng_JASME/tests/private/**/*.docx", recursive=True)) + ["/home/user/jstgxmlcng_JASME/tests/fixtures/JASME_template_20261009.docx"]
for f in files:
    z = zipfile.ZipFile(f)
    names = z.namelist()
    folder = os.path.basename(os.path.dirname(f))
    hf = [n for n in names if re.match(r"word/(header|footer)\d*\.xml$", n)]
    hf_text = 0
    for n in hf:
        hf_text += len(re.findall(rb"<w:t[ >]", z.read(n)))
    cx = [n for n in names if n.startswith("customXml/")]
    custom = "docProps/custom.xml" in names
    authors = collections.Counter()
    for n in names:
        if n.endswith(".xml"):
            for m in re.findall(rb'w:author="([^"]*)"', z.read(n)):
                authors[n.split("/")[-1]] += 1
    s = z.read("word/settings.xml") if "word/settings.xml" in names else b""
    attached = b"attachedTemplate" in s
    srel = z.read("word/_rels/settings.xml.rels") if "word/_rels/settings.xml.rels" in names else b""
    ext = len(re.findall(rb'TargetMode="External"', srel))
    drel = z.read("word/_rels/document.xml.rels")
    dext = len(re.findall(rb'TargetMode="External"', drel))
    comments = [n for n in names if "comments" in n or "people" in n]
    core = z.read("docProps/core.xml") if "docProps/core.xml" in names else b""
    corefields = re.findall(rb"<(dc:creator|cp:lastModifiedBy|cp:keywords|dc:title|dc:subject|dc:description|cp:category)>[^<]", core)
    app = z.read("docProps/app.xml") if "docProps/app.xml" in names else b""
    appf = re.findall(rb"<(Company|Manager|Template)>[^<]", app)
    rsid = len(re.findall(rb"w:rsid", z.read("word/document.xml")))
    person = sum(len(re.findall(rb"w15:person|w:initials", z.read(n))) for n in names if n.endswith(".xml"))
    w14para = len(re.findall(rb"w14:paraId", z.read("word/document.xml")))
    print(folder, os.path.getsize(f), "hf", len(hf), "hf_t", hf_text, "customXml", len(cx), "custom.xml", custom,
          "author", dict(authors), "attachedTpl", attached, "settingsExt", ext, "docExt", dext, "comments", comments,
          "core", [c.decode() for c in corefields], "app", [a.decode() for a in appf], "rsid", rsid>0, "person/initials", person)
