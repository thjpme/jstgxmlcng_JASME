"""<fn><p><table-wrap> が DTD に合うか（work/a1_after_item の出力に表を差し込んで確かめる）。"""
import sys, copy
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/src")
from lxml import etree
from jasme_jats.validate import validate
from jasme_jats.builder import DOCTYPE
src = open("work/a1_after_item/31_1.xml", "rb").read()
root = etree.fromstring(src)
def run(label, mutate):
    r = copy.deepcopy(root)
    mutate(r)
    body = etree.tostring(r, encoding="unicode")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n' + DOCTYPE + "\n" + body + "\n").encode()
    print(label, validate(xml))
TW = '<table-wrap><table><tbody><tr><td>A</td><td>1</td></tr></tbody></table></table-wrap>'
TWID = '<table-wrap id="T9"><caption><p>表1　x</p></caption><table><tbody><tr><td>A</td><td>1</td></tr></tbody></table></table-wrap>'
def in_p(tw, new_p=True):
    def m(r):
        fn = r.find(".//fn-group/fn")
        if new_p:
            p = etree.SubElement(fn, "p")
        else:
            p = fn.find("p")
        p.append(etree.fromstring(tw))
    return m
def direct(r):
    r.find(".//fn-group/fn").append(etree.fromstring(TW))
def only_table(r):
    fn = r.find(".//fn-group/fn")
    for c in list(fn): fn.remove(c)
    p = etree.SubElement(fn, "p"); p.append(etree.fromstring(TW))
run("baseline", lambda r: None)
run("fn/p(new)/table-wrap", in_p(TW))
run("fn/p(existing, mixed)/table-wrap", in_p(TW, False))
run("fn/p/table-wrap id+caption", in_p(TWID))
run("fn/table-wrap direct", direct)
run("fn with only p/table-wrap", only_table)
