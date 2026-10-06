// Cloud-only image byte handling when a scratch executor is unavailable.
// Input: native image generation result.image_url, data:image/png;base64,...
// Never include remote signed URLs, runtime tokens or credentials in GitHub.
// Preserve the original base64 exactly, compute manifest SHA/dimensions here,
// commit bounded ASCII chunks via GitHub text APIs, then use decode_project_image.py
// and decode-image.yml to strictly validate/decode/push/test the same branch.
// PNG CRC/pixel stream/credential scans are enforced by the decoder in Actions.
function decode64(s){const chars="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",len=Math.floor(s.length*3/4)-(s.endsWith("==")?2:s.endsWith("=")?1:0),out=new Uint8Array(len);let b=0,bits=0,j=0;for(let i=0;i<s.length;i++){let v=chars.indexOf(s[i]);if(v<0)break;b=(b<<6)|v;bits+=6;if(bits>=8){bits-=8;out[j++]=(b>>>bits)&255;}}if(j!==len)throw Error("base64 length");return out;}
function sha256(bytes){
 const primes=[],k=[],h=[];for(let n=2;primes.length<64;n++){if(primes.every(p=>n%p)){primes.push(n);if(h.length<8)h.push((Math.sqrt(n)%1*4294967296)|0);k.push((Math.cbrt(n)%1*4294967296)|0);}}
 const len=bytes.length, padded=new Uint8Array(((len+9+63)>>6)<<6);padded.set(bytes);padded[len]=128;const bitlen=len*8;for(let i=0;i<8;i++)padded[padded.length-1-i]=Math.floor(bitlen/Math.pow(256,i))&255;
 const ro=(x,n)=>(x>>>n)|(x<<(32-n)),w=new Int32Array(64);
 for(let p=0;p<padded.length;p+=64){for(let i=0;i<16;i++)w[i]=(padded[p+i*4]<<24)|(padded[p+i*4+1]<<16)|(padded[p+i*4+2]<<8)|padded[p+i*4+3];for(let i=16;i<64;i++){let a=w[i-15],b=w[i-2];w[i]=(w[i-16]+(ro(a,7)^ro(a,18)^(a>>>3))+w[i-7]+(ro(b,17)^ro(b,19)^(b>>>10)))|0;}
 let [a,b,c,d,e,f,g,hh]=h;for(let i=0;i<64;i++){let t1=(hh+(ro(e,6)^ro(e,11)^ro(e,25))+((e&f)^(~e&g))+k[i]+w[i])|0,t2=((ro(a,2)^ro(a,13)^ro(a,22))+((a&b)^(a&c)^(b&c)))|0;hh=g;g=f;f=e;e=(d+t1)|0;d=c;c=b;b=a;a=(t1+t2)|0;}
 [a,b,c,d,e,f,g,hh].forEach((v,i)=>h[i]=(h[i]+v)|0);}
 return h.map(x=>(x>>>0).toString(16).padStart(8,"0")).join("");
}
function imageTransport(imageUrl) {
  const prefix="data:image/png;base64,";
  if (!imageUrl.startsWith(prefix)) throw new Error("Expected native PNG data URL");
  const encoded=imageUrl.slice(prefix.length), bytes=decode64(encoded);
  if(bytes.length>8*1024*1024)throw new Error("PNG too large");
  const u32=i=>((bytes[i]*16777216)+(bytes[i+1]<<16)+(bytes[i+2]<<8)+bytes[i+3])>>>0;
  const chunks=[];
  for(let i=0;i<encoded.length;i+=160000)chunks.push({name:"project-overview.png.b64."+String(chunks.length).padStart(3,"0"),content:encoded.slice(i,i+160000)});
  return {chunks,manifest:{bytes:bytes.length,dimensions:[u32(16),u32(20)],sha256:sha256(bytes),chunks:chunks.map(x=>x.name)}};
}
if(sha256(new Uint8Array([97,98,99]))!=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")throw new Error("SHA256 self-check failed");
