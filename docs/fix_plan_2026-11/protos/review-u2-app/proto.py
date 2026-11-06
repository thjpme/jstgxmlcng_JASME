"""u2-app の設計の要所だけを AppState の派生で試作し、点検の指摘を確かめる（リポジトリは変えない）。"""
import hashlib, sys, unicodedata, shutil
from pathlib import Path
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/tests")
from conftest import FULL, TEMPLATE
from jasme_jats import app
from jasme_jats.app import AppState, InputError, type_choices, INPUT_NAMES, LABELS
from jasme_jats.colab import check_box

COMPARED = tuple(n for n in INPUT_NAMES if n not in ("ai_mode", "model"))
LABELS = dict(LABELS, route="作り方", split_labels="SPLIT_LABELS")
_D = {}
def file_digest(path):
    st = Path(path).stat(); k = (str(path), st.st_size, st.st_mtime_ns)
    if k not in _D: _D[k] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return _D[k]
FD = [file_digest]

class S(AppState):
    def __init__(s, w):
        super().__init__(w); s.run = None; s.paper_changed = False; s._last_docx = None
    def fingerprint(s):
        out = {}
        for n in COMPARED:
            v = s.inputs[n]
            if n in ("docx", "pdf"):
                if not v: out[n] = None
                else:
                    try: out[n] = FD[0](Path(v))
                    except FileNotFoundError: out[n] = ("読めない", str(v))
            elif n == "split_labels": out[n] = bool(v)
            elif n == "route": out[n] = str(v)
            else: out[n] = unicodedata.normalize("NFKC", str(v or "")).strip()
        return out
    def changed_inputs(s):
        if s.run is None: return []
        now = s.fingerprint(); return [LABELS[n] for n in COMPARED if now[n] != s.run["compared"][n]]
    def convert(s, io=None, progress=None):
        meta = s._article_meta()          # 設計 1-3 の 1（ここで止まると paper_changed は前回のまま）
        compared = s.fingerprint()
        s.paper_changed = s._last_docx is not None and compared["docx"] != s._last_docx
        s._last_docx = compared["docx"]
        s._meta = meta; s._journal = app.JournalConfig.load(); s._api_key = None
        s.res = None; s.user_images = {}
        s.run = {"compared": compared, "ai_mode": s.inputs["ai_mode"]}
        return s._run(s.inputs["ai_mode"], None, progress)
    def apply_answer(s, text, io=None, progress=None):
        if s.res is None or s.run is None or s.run["ai_mode"] != "manual":
            raise InputError("手動モードで変換してから")
        ch = s.changed_inputs()
        if ch: raise InputError("入力が前回の変換から変わっています: " + "、".join(ch))
        return s._run("manual", text)
    def result_html(s):
        if s.res is None: return ""
        ch = s.changed_inputs()
        head = check_box("入力が前回の変換から変わっています", "、".join(ch)) if ch else ""
        return head + super().result_html()

def fns_of(st):
    demo = app.build_app(st, app.IO())
    return {f.fn.__name__: f.fn for f in demo.fns.values()}

def base(tmp, docx):
    st = S(tmp)
    st.set_inputs(route="docx", docx=str(docx), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                  manuscript_type=type_choices()[0], ai_mode="manual")
    return st

tmp = Path(__file__).parent / "w"; shutil.rmtree(tmp, ignore_errors=True)
import os
os.environ.setdefault("X", "")
# (a) paper_changed が前回の値のまま残る
st = base(tmp / "a", FULL)
st.convert()
st.set_inputs(docx=str(TEMPLATE)); st.convert()
print("(a) B に変えて変換: paper_changed =", st.paper_changed)
st.set_inputs(received="あした")
try:
    st.convert()
except InputError as e:
    print("(a) 入力の誤りで止まった後: paper_changed =", st.paper_changed, "→ on_convert は回答の欄を空にする（B 用に貼った回答が消える）")

# (b) file_digest が OSError のとき、on_apply の crash の後の view() からも例外が出るか
st = base(tmp / "b", FULL)
st.convert()
def boom(p): raise OSError("写せません")
FD[0] = boom
try:
    st.apply_answer('{"operations": []}')
except OSError as e:
    print("(b) apply_answer: OSError →", e)
    err = st.crash(e, "apply")
    try:
        st.result_html()
        print("(b) view も通る")
    except OSError as e2:
        print("(b) crash の後の view()（result_html）でも OSError が出て、on_apply の外へ抜ける:", e2)
FD[0] = file_digest
