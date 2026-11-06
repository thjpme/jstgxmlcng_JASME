"""u2-app: 画像の持ち越し・O3（ラジオを変えた後の画面）・docx を外して「反映」・API キーなしの変換で _meta だけ入れ替わる。"""
import dataclasses, io, json, shutil, sys
from pathlib import Path
REPO = Path("/home/user/jstgxmlcng_JASME")
sys.path.insert(0, str(REPO / "tests"))
from conftest import TEMPLATE, FULL
from PIL import Image
from jasme_jats import app
from jasme_jats.app import AppState, InputError, type_choices
from jasme_jats.report import actions
HERE = Path(__file__).resolve().parent
W = HERE / "w_more"; shutil.rmtree(W, ignore_errors=True); W.mkdir()
real = app.convert
app.convert = lambda d, m, j, o: real(d, m, j, dataclasses.replace(o, convert_metafiles=False))

def filled(work, docx, mode="manual"):
    st = AppState(work)
    st.set_inputs(route="docx", docx=str(docx), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                  manuscript_type=type_choices()[0], ai_mode=mode)
    return st

print("== 1. 受け取った画像の持ち越し（論文A=テンプレート、論文B=テンプレートの写し〈別の論文の代わり〉）")
B = W / "other_paper.docx"; shutil.copyfile(TEMPLATE, B)
st = filled(W / "w1", TEMPLATE)
st.convert()
rows = st.missing_images(); print("missing:", [r[0] for r in rows])
buf = io.BytesIO(); Image.new("RGB", (60, 40), "white").save(buf, "PNG")
pic = W / "pic_for_A.png"; pic.write_bytes(buf.getvalue())
st.add_images({rows[0][0]: str(pic)})
st.set_inputs(docx=str(B), fpage="77")
res = st.apply_answer('{"operations": []}')
print("input docx of result:", res.docx_path.name if hasattr(res, "docx_path") else "?", "| user_images:", list(st.user_images),
      "| missing after:", [r[0] for r in st.missing_images()], "| xml:", res.xml_path.name)
print("work/input:", sorted(p.name for p in (st.work / "input").iterdir()))

print("== 2. O3: 手動で変換した後に AI の方法を変える")
st = filled(W / "w2", FULL)
st.convert()
print("manual: waiting", st.waiting_for_answer, "box_open", st.answer_box_open)
for mode in ("api", "none"):
    st.set_inputs(ai_mode=mode)
    html = st.result_html()
    print(mode, ": waiting", st.waiting_for_answer, "box_open", st.answer_box_open,
          "| ai_pending の枠:", "AI の回答をまだ反映していません" in html, "| 使わないの注意:", "AI による補完を「使わない」" in html)
    try:
        st.apply_answer('{"operations": []}')
        print("   apply: accepted")
    except InputError as e:
        print("   apply refused:", str(e)[:40])
print("== 2b. 使わないで変換した後に手動に変える")
st = filled(W / "w2b", FULL, mode="none"); st.convert(); st.set_inputs(ai_mode="manual")
print("waiting", st.waiting_for_answer, "box_open", st.answer_box_open)
try:
    r = st.apply_answer('{"operations": []}'); print("apply accepted; ai.mode =", r.ai.mode)
except InputError as e:
    print("apply refused", e)

print("== 3. 変換の後に docx の欄を空にして「反映」")
st = filled(W / "w3", FULL); st.convert()
st.set_inputs(docx=None)
demo = app.build_app(st, app.IO())
fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
out = fns["on_apply"]('{"operations": []}')
print("message has 想定外:", "想定外のエラーで止まりました" in out[0], "| TypeError:", "TypeError" in out[0], "| res kept:", st.res is not None)

print("== 4. API キーなしで変換を押した（InputError）後、前の結果のまま _meta だけ入れ替わる")
st = filled(W / "w4", FULL); st.convert()
old = st.res
st.set_inputs(fpage="77", ai_mode="api")
try:
    st.convert(app.IO())
except InputError as e:
    print("convert refused:", str(e)[:30])
print("res kept:", st.res is old, "| _meta.fpage:", st._meta.fpage)
st.set_inputs(ai_mode="manual")
r = st.apply_answer('{"operations": []}')
from lxml import etree
root = etree.fromstring(r.xml_path.read_bytes().split(b"\n", 2)[2])
print("after apply fpage:", next(root.iter("fpage")).text, "xml:", r.xml_path.name)

print("== 5. route と split_labels を変えて「反映」")
st = filled(W / "w5", FULL); st.convert()
st.set_inputs(split_labels=True)
r = st.apply_answer('{"operations": []}')
root = etree.fromstring(r.xml_path.read_bytes().split(b"\n", 2)[2])
print("labels in XML after apply with split_labels changed:", sum(1 for _ in root.iter("label")))
