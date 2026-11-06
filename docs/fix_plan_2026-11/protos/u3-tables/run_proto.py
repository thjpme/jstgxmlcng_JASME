import sys, runpy
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path[:0] = ["/home/user/jstgxmlcng_JASME/tests", str(HERE)]
import proto  # noqa
for s in sys.argv[1:]:
    print("=====", s)
    runpy.run_path(str(HERE / s), run_name="__main__")
