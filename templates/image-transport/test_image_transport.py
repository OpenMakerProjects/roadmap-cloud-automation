import importlib.util,pathlib,tempfile,unittest,base64,json,hashlib,struct,zlib
spec=importlib.util.spec_from_file_location('decode',pathlib.Path(__file__).resolve().parents[1]/'tools/decode_project_image.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
def png():
    def chunk(kind,payload): return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff'*192)*64))+chunk(b'IEND',b'')
class TransportTests(unittest.TestCase):
    def test_png_checks(self):
        b=png();self.assertEqual(module.validate_png(b),(64,64))
        for bad in [b'bad',b[:-1],b+b'trailer',b[:50]+bytes([b[50]^1])+b[51:]]:
            with self.assertRaises(ValueError): module.validate_png(bad)
    def test_decode_and_cleanup(self):
        with tempfile.TemporaryDirectory() as t:
            root=pathlib.Path(t);d=root/'docs/images';d.mkdir(parents=True)
            b=png();name='project-overview.png.b64.000'
            (d/name).write_text(base64.b64encode(b).decode())
            (d/'project-overview.manifest.json').write_text(json.dumps({'bytes':len(b),'dimensions':[64,64],'sha256':hashlib.sha256(b).hexdigest(),'chunks':[name]}))
            module.decode(root);self.assertEqual((d/'project-overview.png').read_bytes(),b);self.assertFalse((d/name).exists())
    def test_bad_base64_keeps_transport(self):
        with tempfile.TemporaryDirectory() as t:
            root=pathlib.Path(t);d=root/'docs/images';d.mkdir(parents=True)
            name='project-overview.png.b64.000';(d/name).write_text('bad!!!')
            (d/'project-overview.manifest.json').write_text(json.dumps({'chunks':[name]}))
            with self.assertRaises(ValueError): module.decode(root)
            self.assertTrue((d/name).exists());self.assertFalse((d/'project-overview.png').exists())
if __name__=='__main__':unittest.main()
