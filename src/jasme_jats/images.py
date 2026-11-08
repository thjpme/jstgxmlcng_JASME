"""画像の書き出し（J-STAGE が扱える jpg / gif / png にする）。

docx の画像はそのまま使えるものが多いが（Word でトリミングした画像は、表示される範囲に切り取る。`crop_image`）、Word の図（EMF / WMF）は変換が必要。
変換には LibreOffice（soffice）と pypdfium2 を使う。どちらもない環境では変換せず、
レポートで「要対応」として知らせる。
"""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

DIRECT = {"png": "png", "jpg": "jpg", "jpeg": "jpg", "gif": "gif"}
PILLOW = {"bmp", "tif", "tiff", "jfif", "pjpeg", "webp"}
METAFILE = {"emf", "wmf", "emz", "wmz"}
FMT = {"png": "PNG", "jpg": "JPEG", "gif": "GIF"}     # 出力ファイル名の拡張子 → Pillow の形式


@dataclass
class ImageResult:
    image_id: str
    name: str
    source: str
    status: str        # ok / converted / failed / missing / user（利用者が後から用意した画像）
    message: str = ""
    crop: tuple | None = None   # Word のトリミングに合わせて切り取って出力したときの割合（ImageRef.crop）。切り取らなければ None
    edits: tuple = ()           # 書き出しで反映しなかった Word の加工（ImageRef.edits の写し）


class CropError(Exception):
    """Word で切り取った（トリミングした）画像を切り取れない理由（利用者向けの日本語の文。「…ため」の前に入る形）。"""


def crop_text(crop) -> str:
    """切り取りの割合の表示（0 でない辺だけ。順は左・上・右・下）: 「左 50.0%・右 10.0%」。レポートと知らせで共用。"""
    parts = [f"{label} {v * 100:.1f}%" for label, v in zip(("左", "上", "右", "下"), crop) if v]
    text = "・".join(parts)
    return text


def crop_box(size, crop) -> tuple:
    """(x0, y0, x1, y1)。幅か高さが 1 px 未満なら CropError。"""
    w, h = size
    l, t, r, b = crop
    box = (round(w * l), round(h * t), w - round(w * r), h - round(h * b))
    if box[2] - box[0] < 1 or box[3] - box[1] < 1:
        raise CropError("切り取ると画像が残らない")
    return box


def _check_croppable(im) -> None:
    """切り取れない画像なら CropError。"""
    if getattr(im, "n_frames", 1) > 1:
        raise CropError("複数のコマのある画像（動く GIF など）の")
    try:
        orient = im.getexif().get(0x0112, 1)
    except Exception:  # noqa: BLE001
        orient = 1
    if orient not in (0, 1):
        raise CropError("画像に向きの情報（Exif）があり、Word が表示する向きでの切り取りの位置を決められない")


_PNG_MODES = {"1", "L", "LA", "I;16", "P", "RGB", "RGBA"}


def crop_image(data: bytes, fmt: str, crop) -> tuple:
    """Word のトリミング crop に合わせて切り取った画像。fmt は "PNG" / "JPEG" / "GIF"。

    戻り値: (切り取った画像のバイト列, (元の幅, 高さ), (切り取った後の幅, 高さ))。切り取りが 1 px 未満で全体のままなら
    (None, 元の大きさ, 元の大きさ)（呼び出し側は元のバイト列をそのまま使う）。切り取れなければ CropError。
    """
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # noqa: BLE001
        raise CropError(f"画像を読めない（{e}）") from e
    try:
        box = crop_box(im.size, crop)
        if box == (0, 0, im.size[0], im.size[1]):
            return None, im.size, im.size
        _check_croppable(im)
        out = im.crop(box)
        kw = {}
        if im.info.get("dpi"):
            kw["dpi"] = im.info["dpi"]
        if im.info.get("icc_profile"):
            kw["icc_profile"] = im.info["icc_profile"]
        if fmt == "JPEG":
            if out.mode not in ("RGB", "L", "CMYK"):
                out = out.convert("RGB")
            if im.format == "JPEG":
                from PIL import JpegImagePlugin
                kw["qtables"] = im.quantization
                sub = JpegImagePlugin.get_sampling(im)
                if sub != -1:
                    kw["subsampling"] = sub
                if im.info.get("progressive") or im.info.get("progression"):
                    kw["progressive"] = True
        elif fmt == "PNG":
            if out.mode not in _PNG_MODES:
                out = out.convert("RGBA" if ("A" in out.mode or "transparency" in out.info) else "RGB")
        if fmt == "GIF":
            kw = {}
        buf = io.BytesIO()
        out.save(buf, fmt, **kw)
        return buf.getvalue(), im.size, out.size
    except CropError:
        raise
    except Exception as e:  # noqa: BLE001
        raise CropError(f"画像を切り取って保存できない（{e}）") from e


def soffice_path():
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _crop_white(img, pad=12):
    from PIL import Image, ImageChops
    rgb = img.convert("RGB")
    bg = Image.new("RGB", rgb.size, (255, 255, 255))
    mask = ImageChops.difference(rgb, bg).convert("L").point(lambda v: 255 if v > 8 else 0)
    box = mask.getbbox()
    if not box:
        return rgb
    return rgb.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(rgb.width, box[2] + pad),
                     min(rgb.height, box[3] + pad)))


def convert_metafile(data: bytes, ext: str, min_width_px=1200):
    """EMF / WMF を PNG にする。戻り値: (png の bytes または None, メッセージ)"""
    soffice = soffice_path()
    if not soffice:
        return None, "LibreOffice が見つからないため EMF/WMF を変換できない（Colab では「EMF/WMF 画像を変換する」を有効にする）"
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"image.{ext}"
        src.write_bytes(data)
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", td, str(src)],
                           check=True, capture_output=True, timeout=120)
        except Exception as e:  # noqa: BLE001
            return None, f"LibreOffice での変換に失敗: {e}"
        pdf = Path(td) / "image.pdf"
        if not pdf.exists():
            return None, "LibreOffice での変換に失敗（PDF ができない）"
        try:
            import pypdfium2 as pdfium
        except ImportError:
            pdfium = None
        from PIL import Image
        if pdfium is not None:
            doc = pdfium.PdfDocument(str(pdf))
            page = doc[0]
            w, h = page.get_size()
            low = page.render(scale=1).to_pil()
            cropped = _crop_white(low, pad=2)
            # 内容の範囲だけを高解像度で描き直す
            box = _bbox(low)
            if box:
                cw = box[2] - box[0]
                scale = max(300 / 72, min(1200 / 72, min_width_px / max(cw, 1)))
                crop = (max(0, box[0] - 2), max(0, h - box[3] - 2), max(0, w - box[2] - 2), max(0, box[1] - 2))
                img = page.render(scale=scale, crop=crop).to_pil()
                img = _crop_white(img)
            else:
                img = cropped
            doc.close()
        else:
            try:
                subprocess.run([soffice, "--headless", "--convert-to", "png", "--outdir", td, str(src)],
                               check=True, capture_output=True, timeout=120)
                img = _crop_white(Image.open(Path(td) / "image.png"))
            except Exception as e:  # noqa: BLE001
                return None, f"LibreOffice での PNG 変換に失敗: {e}"
        buf = io.BytesIO()
        img.save(buf, "PNG", dpi=(300, 300))
        return buf.getvalue(), f"{ext.upper()} を PNG に変換（{img.width}×{img.height} px）"


def user_image(data: bytes, name: str, label: str = "") -> bytes:
    """利用者が用意した画像（PNG・JPEG・GIF など Pillow で読めるもの、または 1 ページの PDF）を、
    出力ファイル名の形式（拡張子で決まる png / jpg / gif）の画像にする。読めなければ ValueError。"""
    from PIL import Image
    label = label or "選んだファイル"
    if data[:5] == b"%PDF-":
        try:
            import pypdfium2 as pdfium
        except ImportError:
            raise ValueError(f"{label}は PDF です。PDF を画像にするには pypdfium2 が必要です（PNG か JPEG の画像を選んでください）") from None
        doc = pdfium.PdfDocument(data)
        try:
            if len(doc) != 1:
                raise ValueError(f"{label}は {len(doc)} ページの PDF です。図の部分だけの 1 ページの PDF か、PNG・JPEG の画像を選んでください")
            img = _crop_white(doc[0].render(scale=300 / 72).to_pil())
        finally:
            doc.close()
    else:
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception:  # noqa: BLE001
            raise ValueError(f"{label}を画像として読めません（PNG・JPEG などの画像を選んでください）") from None
    fmt = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "gif": "GIF"}.get(name.rsplit(".", 1)[-1].lower(), "PNG")
    if fmt == "JPEG" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode not in ("RGB", "RGBA", "L", "LA", "P", "1"):
        img = img.convert("RGB")      # CMYK の JPEG など
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


def _bbox(img):
    from PIL import Image, ImageChops
    rgb = img.convert("RGB")
    bg = Image.new("RGB", rgb.size, (255, 255, 255))
    return ImageChops.difference(rgb, bg).convert("L").point(lambda v: 255 if v > 8 else 0).getbbox()


def export_images(doc, images, out_dir: Path, convert_metafiles=True, *, keep_dir: Path):
    """BuildInfo.images（出力した画像）を out_dir に書き出す。

    変換できなかった EMF/WMF の元の画像は keep_dir に置く（省略できない。記事フォルダの中に置くと、記事フォルダを
    そのまま ZIP にしたときに入ってしまうため）。pipeline は出力フォルダの直下の 要変換/ を渡す（記事フォルダの外。
    日本語のフォルダ名はアップロード用の ZIP に入れられない: EMSGM034E・074E）。
    Word でトリミングした画像（ImageRef.crop）は表示される範囲に切り取って書く。切り取れない画像（EMF/WMF、Exif の向きの
    ある画像、動く GIF、保存できない形式など）は Graphics/ に書かず（Word で隠した部分を ZIP に入れない）、切り取る前の
    画像を keep_dir に置いて failed にする（用意が必要な画像として知らせる）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def keep_uncropped(img, name, data, cut_msg, as_png):
        """切り取れない画像: 切り取る前の画像を keep_dir に置き、failed の ImageResult を作る。"""
        stem = name.rsplit(".", 1)[0]
        src_ext = img.target.rsplit(".", 1)[-1].lower()
        keep_name, keep_data = f"{stem}.{src_ext}", data
        if as_png:
            try:
                from PIL import Image
                im = Image.open(io.BytesIO(data))
                if im.mode not in ("RGB", "RGBA", "L", "P"):
                    im = im.convert("RGB")
                buf = io.BytesIO()
                im.save(buf, "PNG")
                keep_name, keep_data = f"{stem}.png", buf.getvalue()
            except Exception:  # noqa: BLE001
                pass
        keep = Path(keep_dir) / keep_name
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.write_bytes(keep_data)
        return cut_msg(keep.name)

    def done(img, name, status, message="", crop=None):
        edits = img.edits
        if edits:
            note = "Word の加工（" + "・".join(edits) + "）は反映していない"
            message = f"{message}。{note}" if message else note
        results.append(ImageResult(img.image_id, name, img.target, status, message, crop=crop, edits=edits))

    for img in images:
        name = img.export_name
        if img.shape_only or not img.target:
            results.append(ImageResult(img.image_id, name, "", "missing",
                                       "Word の図形・グラフなどで画像ファイルがない。PDF 等から画像を作り、Colab（ノートブックは手順 7、"
                                       "1 画面版は「画像を入れる」の欄）かコマンドラインの --images で入れること（記事フォルダの Graphics/ に手で置いても ZIP には"
                                       "入らない）"))
            continue
        data = doc.media.get(img.target)
        src_ext = img.target.rsplit(".", 1)[-1].lower()
        if data is None:
            results.append(ImageResult(img.image_id, name, img.target, "missing", "docx の中に画像ファイルが見つからない"))
            continue
        want_ext = name.rsplit(".", 1)[-1]

        def cut_failed(reason, as_png):
            def msg(keep_name):
                return (f"Word で切り取った（トリミングした）画像だが、{reason}ため切り取れなかった。"
                        f"切り取る前の画像を 要変換/{keep_name} に保存した。Word の表示の範囲に切り取った画像を用意すること")
            return keep_uncropped(img, name, data, msg, as_png)

        if DIRECT.get(src_ext) == want_ext:
            if img.crop is None:
                (out_dir / name).write_bytes(data)
                done(img, name, "ok")
                continue
            try:
                out, (w0, h0), (w1, h1) = crop_image(data, FMT[want_ext], img.crop)
            except CropError as e:
                done(img, name, "failed", cut_failed(str(e), False))
                continue
            if out is None:
                (out_dir / name).write_bytes(data)
                done(img, name, "ok")
                continue
            try:
                (out_dir / name).write_bytes(out)
            except OSError as e:
                done(img, name, "failed", cut_failed(f"切り取った画像を保存できない（{e}）", False))
                continue
            done(img, name, "converted",
                 f"Word のトリミングに合わせて切り取った（{crop_text(img.crop)}。{w0}×{h0} px → {w1}×{h1} px）", crop=img.crop)
            continue
        if src_ext in PILLOW or (src_ext in DIRECT and DIRECT[src_ext] != want_ext):
            try:
                from PIL import Image
                im = Image.open(io.BytesIO(data))
                cut_msg, crop = "", None
                if img.crop is not None:
                    box = crop_box(im.size, img.crop)
                    if box != (0, 0, im.size[0], im.size[1]):
                        _check_croppable(im)
                        w0, h0 = im.size
                        im = im.crop(box)
                        crop = img.crop
                        cut_msg = f"、Word のトリミングに合わせて切り取った（{crop_text(crop)}。{w0}×{h0} px → {im.size[0]}×{im.size[1]} px）"
                if im.mode not in ("RGB", "RGBA", "L", "P"):
                    im = im.convert("RGB")
                im.save(out_dir / name, "PNG")
                done(img, name, "converted", f"{src_ext.upper()} を PNG に変換{cut_msg}", crop=crop)
            except CropError as e:
                done(img, name, "failed", cut_failed(str(e), True))
            except Exception as e:  # noqa: BLE001
                done(img, name, "failed", f"変換に失敗: {e}")
            continue
        if src_ext in METAFILE:
            if src_ext in ("emz", "wmz"):
                import gzip
                try:
                    data = gzip.decompress(data)
                    src_ext = src_ext[0] + "mf"
                except OSError:
                    pass
            png, msg = convert_metafile(data, src_ext) if convert_metafiles else (None, "EMF/WMF の変換を行わない設定")
            if img.crop is not None:
                ct = crop_text(img.crop)
                if png:
                    keep = Path(keep_dir) / name
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    keep.write_bytes(png)
                    done(img, name, "failed",
                         f"Word で切り取った（トリミングした）EMF/WMF の図で、切り取りの位置（{ct}）を変換した画像に当てはめられないため、"
                         f"切り取る前の画像を 要変換/{name} に保存した。Word の表示の範囲に切り取った画像を用意すること")
                    continue
                msg = f"{msg}（Word で切り取った図。切り取りの位置: {ct}）"
            elif png:
                (out_dir / name).write_bytes(png)
                done(img, name, "converted", msg)
                continue
            keep = Path(keep_dir) / f"{name.rsplit('.', 1)[0]}.{src_ext}"
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_bytes(data)
            done(img, name, "failed", f"{msg}。元の画像を 要変換/{keep.name} に保存した")
            continue
        done(img, name, "failed", f"未対応の画像形式（{src_ext}）")
    return results
