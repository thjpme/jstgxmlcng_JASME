import io, struct
from PIL import Image
t=io.BytesIO(); Image.new("RGB",(16,8),"red").save(t,"JPEG"); tb=t.getvalue()
# TIFF little endian
ifd0_off=8
ifd0=struct.pack("<H",1)+struct.pack("<HHII",0x0112,3,1,1)  # orientation 1
ifd1_off=ifd0_off+len(ifd0)+4
ifd1_entries=2
thumb_off=ifd1_off+2+12*ifd1_entries+4
ifd1=struct.pack("<H",2)+struct.pack("<HHII",0x0201,4,1,thumb_off)+struct.pack("<HHII",0x0202,4,1,len(tb))+struct.pack("<I",0)
tiff=b"II*\x00"+struct.pack("<I",ifd0_off)+ifd0+struct.pack("<I",ifd1_off)+ifd1+tb
exif=b"Exif\x00\x00"+tiff
b=io.BytesIO(); Image.new("RGB",(64,32),"blue").save(b,"JPEG",exif=exif)
s=Image.open(io.BytesIO(b.getvalue()))
print("orientation", s.getexif().get(0x0112))
print("raw info exif has thumb:", tb in s.info["exif"])
c=s.crop((32,0,64,32))
o=io.BytesIO(); c.save(o,"JPEG",exif=s.info["exif"]); print("out (raw exif) has thumb:", tb in o.getvalue())
o=io.BytesIO(); c.save(o,"JPEG",exif=s.getexif()); print("out (getexif) has thumb:", tb in o.getvalue())
o=io.BytesIO(); c.save(o,"JPEG"); print("out (no exif) has thumb:", tb in o.getvalue(), "exif" in Image.open(o).info)
