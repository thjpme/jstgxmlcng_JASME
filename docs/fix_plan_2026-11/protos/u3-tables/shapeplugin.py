import json, os
from lxml import etree
LOG = os.path.join(os.path.dirname(__file__), "plugin_log.jsonl")
def pytest_configure(config):
    import jasme_jats.pipeline as p
    from shape import table_shape
    orig = p.convert
    def wrapped(*a, **k):
        res = orig(*a, **k)
        try:
            root = etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])
            probs = [table_shape(t)[1] for t in root.iter("table")]
            n = len(probs)
            bad = [x for x in probs if x]
            with open(LOG, "a") as f:
                f.write(json.dumps(dict(test=os.environ.get("PYTEST_CURRENT_TEST", ""), docx=os.path.basename(str(a[0])), tables=n, bad=bad), ensure_ascii=False) + "\n")
        except Exception as e:
            with open(LOG, "a") as f:
                f.write(json.dumps(dict(test=os.environ.get("PYTEST_CURRENT_TEST", ""), err=repr(e))) + "\n")
        return res
    p.convert = wrapped
