"""Strict lossless PNG transport recovery; no tokens or network access required."""
import base64, binascii, hashlib, json, pathlib, re, struct, zlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGE = ROOT/'docs/images/project-overview.png'
MANIFEST = ROOT/'docs/images/project-overview.manifest.json'
LIMIT = 8 * 1024 * 1024

def validate_png(data):
    if not 32 <= len(data) <= LIMIT or data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Invalid PNG signature or size')
    offset=8; kinds=[]; idat=bytearray(); ihdr=None
    while offset < len(data):
        if offset+12 > len(data): raise ValueError('Truncated PNG chunk')
        size=struct.unpack('>I',data[offset:offset+4])[0]
        if size > LIMIT or offset+12+size > len(data): raise ValueError('Invalid chunk size')
        kind=data[offset+4:offset+8]; payload=data[offset+8:offset+8+size]
        crc=struct.unpack('>I',data[offset+8+size:offset+12+size])[0]
        if zlib.crc32(kind+payload)&0xffffffff != crc: raise ValueError('PNG CRC mismatch')
        # caBX is public generation provenance; arbitrary textual/executable metadata is rejected.
        if kind not in {b'IHDR',b'IDAT',b'IEND',b'caBX',b'sRGB',b'gAMA',b'cHRM',b'pHYs'}:
            raise ValueError('Unsupported PNG chunk')
        kinds.append(kind)
        if kind==b'IHDR':
            if ihdr is not None or size!=13 or len(kinds)!=1: raise ValueError('Invalid IHDR')
            ihdr=struct.unpack('>IIBBBBB',payload)
        if kind==b'IDAT': idat.extend(payload)
        offset+=12+size
        if kind==b'IEND':
            if size or offset!=len(data): raise ValueError('Invalid PNG end/trailing bytes')
            break
    if not ihdr or kinds[-1]!=b'IEND' or not idat: raise ValueError('Incomplete PNG')
    width,height,depth,color,compression,filter_method,interlace=ihdr
    if not 64<=width<=4096 or not 64<=height<=4096: raise ValueError('PNG dimensions outside bounds')
    if (depth,color,compression,filter_method,interlace) not in [(8,2,0,0,0),(8,6,0,0,0)]:
        raise ValueError('Only non-interlaced 8-bit RGB/RGBA PNG accepted')
    channels=3 if color==2 else 4
    row=1+width*channels; expected=row*height
    stream=zlib.decompressobj(); pixels=stream.decompress(bytes(idat),expected+1)
    if len(pixels)!=expected or not stream.eof or stream.unused_data or stream.unconsumed_tail:
        raise ValueError('PNG pixel stream length or termination invalid')
    if any(pixels[i] > 4 for i in range(0,expected,row)): raise ValueError('Invalid PNG scanline filter')
    if re.search(rb'(-----BEGIN [^\n]*PRIVATE KEY|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-proj-[A-Za-z0-9_-]{30,})',data):
        raise ValueError('Credential-like data in PNG')
    return width,height

def decode(root=ROOT):
    directory=root/'docs/images'; manifest=json.loads((directory/'project-overview.manifest.json').read_text())
    names=manifest['chunks']
    if not 1<=len(names)<=128 or names!=sorted(set(names)): raise ValueError('Invalid chunk list')
    if any(not re.fullmatch(r'project-overview\.png\.b64\.\d{3}',name) for name in names):
        raise ValueError('Unsafe transport filename')
    files=[directory/name for name in names]
    if any(p.is_symlink() or not p.is_file() for p in files): raise ValueError('Missing/unsafe chunk')
    if sum(p.stat().st_size for p in files)>LIMIT*2: raise ValueError('Transport too large')
    encoded=''.join(p.read_text(encoding='ascii').strip() for p in files)
    data=base64.b64decode(encoded,validate=True)
    if base64.b64encode(data).decode('ascii') != encoded: raise ValueError('Noncanonical base64')
    dimensions=validate_png(data)
    if len(data)!=manifest['bytes'] or list(dimensions)!=manifest['dimensions']:
        raise ValueError('Manifest size/dimension mismatch')
    if hashlib.sha256(data).hexdigest()!=manifest['sha256']: raise ValueError('Manifest SHA256 mismatch')
    target=directory/'project-overview.png'
    if target.exists() and target.read_bytes()!=data: raise ValueError('Refusing to overwrite different image')
    temporary=directory/'project-overview.png.tmp'; temporary.write_bytes(data); temporary.replace(target)
    for p in files: p.unlink()
    print(json.dumps({'bytes':len(data),'dimensions':dimensions,'sha256':manifest['sha256'],'credential_pattern_scan':'passed'}))

if __name__=='__main__': decode()
