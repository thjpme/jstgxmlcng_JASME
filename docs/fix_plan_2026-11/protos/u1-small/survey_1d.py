import zipfile, glob, os, re
from lxml import etree
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
q = lambda t: "{%s}%s" % (W, t)
files = sorted(glob.glob("/home/user/jstgxmlcng_JASME/tests/private/**/*.docx", recursive=True)) + sorted(glob.glob("/home/user/jstgxmlcng_JASME/tests/fixtures/*.docx"))
for f in files:
    z = zipfile.ZipFile(f)
    if "word/numbering.xml" not in z.namelist():
        print(os.path.basename(os.path.dirname(f)), os.path.basename(f)[-12:], "no numbering"); continue
    root = etree.fromstring(z.read("word/numbering.xml"))
    nums = root.findall(q("num"))
    ovs = [ov for n in nums for ov in n.findall(q("lvlOverride"))]
    ov_lvl = [ov for ov in ovs if ov.find(q("lvl")) is not None]
    ov_start = [ov for ov in ovs if ov.find(q("startOverride")) is not None]
    # どの num が本文で使われているか
    used = set()
    for part in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"):
        if part in z.namelist():
            used |= set(re.findall(rb'<w:numId w:val="(\d+)"', z.read(part)))
    used = {u.decode() for u in used}
    ov_lvl_used = [ov for n in nums if n.get(q("numId")) in used for ov in n.findall(q("lvlOverride")) if ov.find(q("lvl")) is not None]
    islgl = len(root.findall(".//" + q("isLgl"))); restart = len(root.findall(".//" + q("lvlRestart")))
    shared = {}
    for n in nums:
        a = n.find(q("abstractNumId")).get(q("val")); shared.setdefault(a, []).append(n.get(q("numId")))
    shared_used = sum(1 for a, ns in shared.items() if len([x for x in ns if x in used]) > 1)
    print(os.path.basename(os.path.dirname(f)), os.path.basename(f)[-14:] if "fixtures" in f else "", "nums", len(nums), "used", len(used & {n.get(q('numId')) for n in nums}),
          "lvlOverride", len(ovs), "ov/lvl", len(ov_lvl), "ov/lvl used", len(ov_lvl_used), "startOverride", len(ov_start),
          "isLgl", islgl, "lvlRestart", restart, "abstract shared by >1 used num", shared_used)
