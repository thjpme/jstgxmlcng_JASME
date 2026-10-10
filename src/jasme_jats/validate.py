"""J-STAGE 指定の DTD（JATS 1.1 Journal Publishing）による妥当性検証。

J-STAGE が公開している DTD 一式（https://www.jstage.jst.go.jp/dtds/1.1/）を dtd/ に同梱している。
同梱版は NLM が公開している JATS 1.1 の DTD と同一であることを確認済み（2026-10）。
ネットワークに接続せずに検証できる。
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree

DTD_PATH = Path(__file__).resolve().parent / "dtd" / "JATS-journalpublishing1.dtd"
_DTD = None


def load_dtd():
    global _DTD
    if _DTD is None:
        _DTD = etree.DTD(str(DTD_PATH))
    return _DTD


def validate(xml_bytes: bytes):
    """XML（DOCTYPE 付きでもよい）を DTD で検証する。戻り値: (妥当か, エラーの一覧)"""
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, huge_tree=True)
    root = etree.fromstring(xml_bytes, parser)
    dtd = load_dtd()
    ok = dtd.validate(root)
    errors = []
    if not ok:
        for e in dtd.error_log.filter_from_errors():
            errors.append(f"{e.line}行: {e.message}")
    return ok, errors
