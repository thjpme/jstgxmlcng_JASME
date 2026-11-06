import sys
from jasme_jats.ai_assist import parse_response, parse_cut_response
print("recursionlimit", sys.getrecursionlimit())
for depth in (900, 1000, 3000, 20000):
    deep2 = '{"placements": [], "operations": [' + "[" * depth + "]" * depth + "]}"
    for f in (parse_response, parse_cut_response):
        try:
            r = f(deep2); print(depth, f.__name__, "ok", type(r).__name__)
        except RecursionError:
            print(depth, f.__name__, "RecursionError")
        except ValueError as e:
            print(depth, f.__name__, "ValueError", str(e)[:60])
# 切れた深い回答
deep3 = '{"placements": [{"float": "s1", "after": "d1", "items": [' + "[" * 20000
for f in (parse_response, parse_cut_response):
    try:
        r = f(deep3); print("cut20000", f.__name__, "ok", r)
    except RecursionError:
        print("cut20000", f.__name__, "RecursionError")
    except ValueError as e:
        print("cut20000", f.__name__, "ValueError", str(e)[:60])
