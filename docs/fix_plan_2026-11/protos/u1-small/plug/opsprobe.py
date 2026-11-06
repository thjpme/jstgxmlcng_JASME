import json, os
from jasme_jats import ai_assist
_orig = ai_assist.parse_response
LOG = os.path.join(os.path.dirname(__file__), "probe.log")
def parse_response(text):
    d = _orig(text)
    open(LOG + ".all", "a").write("call\n")
    if "operations" not in d:
        with open(LOG, "a") as f:
            f.write("NO_OPS keys=%s\n" % sorted(d))
    return d
ai_assist.parse_response = parse_response
from jasme_jats import pipeline
pipeline.parse_response = parse_response
