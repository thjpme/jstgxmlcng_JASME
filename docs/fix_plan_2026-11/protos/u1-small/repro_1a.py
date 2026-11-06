import shutil, sys, os
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/tools")
import sanitize_docx
here = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(here, "same.docx")
shutil.copy("/home/user/jstgxmlcng_JASME/tests/fixtures/sample_full.docx", p)
print("before", os.path.getsize(p))
try:
    sanitize_docx.sanitize(p, p)
except Exception as e:
    print("exc", type(e).__name__, e)
print("after", os.path.getsize(p))
