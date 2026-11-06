import io, struct, zlib
from PIL import Image, JpegImagePlugin, PngImagePlugin
import PIL; print("Pillow", PIL.__version__)
def rt(im, fmt, **kw):
    b=io.BytesIO(); im.save(b, fmt, **kw); return Image.open(io.BytesIO(b.getvalue()))
# CMYK jpeg roundtrip
src = rt(Image.new("CMYK",(64,32),(10,200,30,40)),"JPEG",quality=90)
print("CMYK src", src.mode, src.getpixel((0,0)), "adobe", src.info.get("adobe"), "qt", len(src.quantization))
c = src.crop((16,0,64,32))
o = rt(c,"JPEG",qtables=src.quantization)
print("CMYK out", o.mode, o.getpixel((0,0)), "adobe", o.info.get("adobe"))
# subsampling for L
L = rt(Image.new("L",(64,32),100),"JPEG")
print("L sampling", JpegImagePlugin.get_sampling(L), "qt", len(L.quantization))
# 48-bit RGB png
import numpy as np
arr = (np.ones((10,20,3),dtype=">u2")*40000)
def png16(arr):
    h,w,_=arr.shape
    raw=b"".join(b"\x00"+arr[y].tobytes() for y in range(h))
    def ch(t,d): return struct.pack(">I",len(d))+t+d+struct.pack(">I",zlib.crc32(t+d)&0xffffffff)
    return b"\x89PNG\r\n\x1a\n"+ch(b"IHDR",struct.pack(">IIBBBBB",w,h,16,2,0,0,0))+ch(b"IDAT",zlib.compress(raw))+ch(b"IEND",b"")
im=Image.open(io.BytesIO(png16(arr))); im.load(); print("48bit", im.mode, im.getpixel((0,0)))
# I;16 save
g=Image.new("I;16",(20,10),50000); o=rt(g.crop((5,0,20,10)),"PNG"); print("I;16 ->", o.mode, o.getpixel((0,0)))
#g=Image.new("I",(20,10),50000); o=rt(g.crop((5,0,20,10)),"PNG"); print("I ->", o.mode, o.getpixel((0,0)))
# PA mode
try:
    pa=Image.new("PA",(20,10)); s=rt(pa,"PNG"); print("PA open", s.mode)
except Exception as e: print("PA", e)
# P with tRNS array
p=Image.new("P",(20,10),1); p.putpalette([255,0,0,0,0,255]+[0]*762)
s=rt(p,"PNG",transparency=bytes([0,128])); print("P trns", s.mode, s.info.get("transparency"))
o=rt(s.crop((5,0,20,10)),"PNG"); print("P trns out", o.mode, o.info.get("transparency"))
# gamma chunk
pn=PngImagePlugin.PngInfo()
s=rt(Image.new("RGB",(20,10)),"PNG",dpi=(299.9994,299.9994)); print("dpi float", s.info.get("dpi"))
o=rt(s.crop((1,0,20,10)),"PNG",dpi=s.info["dpi"]); print("dpi out", o.info.get("dpi"))
# JPEG progressive
s=rt(Image.new("RGB",(64,32),"red"),"JPEG",progressive=True); print("prog", s.info.get("progressive"), s.info.get("progression"))
o=rt(s.crop((16,0,64,32)),"JPEG",qtables=s.quantization,subsampling=JpegImagePlugin.get_sampling(s),progressive=True); print("prog out", o.info.get("progressive"))
# quality keep on cropped
try:
    s.crop((16,0,64,32)).save(io.BytesIO(),"JPEG",quality="keep"); print("keep ok")
except Exception as e: print("keep err", e)
# dpi in JPEG only via exif
ex=Image.Exif(); ex[0x011A]=300; ex[0x011B]=300; ex[0x0128]=2
s=rt(Image.new("RGB",(64,32)),"JPEG",exif=ex.tobytes()); print("jpeg exif-only dpi", s.info.get("dpi"), s.info.get("jfif_density"))
# RGBA content saved as JPEG
s=rt(Image.new("RGBA",(20,10),(255,0,0,0)),"PNG"); print("rgba->rgb", s.convert("RGB").getpixel((0,0)))
