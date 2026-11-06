import json
from jasme_jats.ai_assist import parse_response, parse_cut_response, split_ops
op = {"op": "link_citation", "src": "d18", "text": "2001", "occurrence": 1, "target": "B2", "role": "", "image": "",
      "mathml": "", "surname": "", "given": "", "reason": "r", "confidence": "高"}
op2 = dict(op, src="d19")
cases = {
  "single_array": json.dumps([op], ensure_ascii=False),
  "single_array_fenced": "```json\n" + json.dumps([op], ensure_ascii=False) + "\n```",
  "multi_array": json.dumps([op, op2], ensure_ascii=False),
  "multi_array_fenced_pretty": "```json\n" + json.dumps([op, op2], ensure_ascii=False, indent=2) + "\n```",
  "single_op_object": json.dumps(op, ensure_ascii=False),
  "placements_only": json.dumps({"placements": []}),
  "empty_array": "[]",
  "ops_array_toplevel_of_objects_with_trailing": json.dumps([op], ensure_ascii=False) + "\n以上です。",
}
for k, v in cases.items():
    try:
        d = parse_response(v)
        print(k, "-> OK keys", sorted(d), "ops", len(d.get("operations", [])))
    except Exception as e:
        print(k, "-> ERR", type(e).__name__, str(e)[:120])
# A10
for depth in (500, 2000, 100000):
    deep = '{"placements": [' + "[" * depth + '{"a": "b'
    try:
        print("cut depth", depth, parse_cut_response(deep))
    except Exception as e:
        print("cut depth", depth, "EXC", type(e).__name__)
    deep2 = '{"placements": [], "operations": [' + "[" * depth + "]" * depth + "]}"
    try:
        parse_response(deep2); print("full depth", depth, "ok")
    except Exception as e:
        print("full depth", depth, "EXC", type(e).__name__, str(e)[:80])
