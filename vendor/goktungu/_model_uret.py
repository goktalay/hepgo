# -*- coding: utf-8 -*-
"""GOKTUNGU harita 3B ikonlari icin kompakt glb model ureteci (bagimsiz, numpy).
Konvansiyon (glTF): X = burun/ileri, Y = yukari, Z = sag kanat (sancak).
Cesium HPR ile X burun heading yonune gelir. minimumPixelSize sayesinde her
zoom'da gorunur. model.color (MIX) ile drona gore renklendirilir."""
import struct, json, math, os
import numpy as np

CIK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
os.makedirs(CIK, exist_ok=True)

# ---------- mesh yardimcilari (her parca: (V[n,3], F[m,3]) ) ----------
def birlestir(parcalar):
    V=[]; F=[]; off=0
    for v,f in parcalar:
        V.append(v); F.append(f+off); off+=len(v)
    return np.vstack(V), np.vstack(F)

def kutu(cx,cy,cz, sx,sy,sz):
    hx,hy,hz=sx/2,sy/2,sz/2
    v=np.array([[-hx,-hy,-hz],[hx,-hy,-hz],[hx,hy,-hz],[-hx,hy,-hz],
                [-hx,-hy,hz],[hx,-hy,hz],[hx,hy,hz],[-hx,hy,hz]],float)
    v+=[cx,cy,cz]
    f=np.array([[0,1,2],[0,2,3],[4,6,5],[4,7,6],[0,4,5],[0,5,1],
                [1,5,6],[1,6,2],[2,6,7],[2,7,3],[3,7,4],[3,4,0]],int)
    return v,f

def silindir(cx,cy,cz, r, h, eksen='y', n=16, r2=None):
    """eksen boyunca yukseklik h; r2 verilirse ust yaricap (koni)."""
    r2 = r if r2 is None else r2
    ang=np.linspace(0,2*math.pi,n,endpoint=False)
    alt=np.stack([np.cos(ang)*r, np.full(n,-h/2), np.sin(ang)*r],1)
    ust=np.stack([np.cos(ang)*r2, np.full(n,h/2), np.sin(ang)*r2],1)
    v=np.vstack([alt,ust,[[0,-h/2,0]],[[0,h/2,0]]])
    f=[]
    for i in range(n):
        j=(i+1)%n
        f+= [[i,j,n+j],[i,n+j,n+i]]              # yan
        f+= [[2*n, j, i]]                         # alt kapak
        f+= [[2*n+1, n+i, n+j]]                   # ust kapak
    v=np.array(v,float); f=np.array(f,int)
    # eksen dondur: varsayilan Y. 'x' -> Y->X, 'z' -> Y->Z
    if eksen=='x': v=v[:,[1,0,2]]; v[:,0]*=-1
    elif eksen=='z': v=v[:,[0,2,1]]
    v+=[cx,cy,cz]
    return v,f

def disk(cx,cy,cz,r,h=0.6,n=20): return silindir(cx,cy,cz,r,h,'y',n)

def kure(cx,cy,cz,r, n=10):
    us=np.linspace(-math.pi/2,math.pi/2,n); vs=np.linspace(0,2*math.pi,2*n,endpoint=False)
    V=[]
    for u in us:
        for w in vs:
            V.append([math.cos(u)*math.cos(w)*r, math.sin(u)*r, math.cos(u)*math.sin(w)*r])
    V=np.array(V,float); F=[]
    m=len(vs)
    for i in range(n-1):
        for j in range(m):
            j2=(j+1)%m
            a=i*m+j; b=i*m+j2; c=(i+1)*m+j; d=(i+1)*m+j2
            F+=[[a,b,d],[a,d,c]]
    V+=[cx,cy,cz]; return V,np.array(F,int)

def ucgen_yatay(x0, genis, uzun, y):
    """Yon ucgeni: burunda (+X), yatay (XZ), y yuksekliginde."""
    v=np.array([[x0+uzun,y,0],[x0,y,genis/2],[x0,y,-genis/2]],float)
    f=np.array([[0,1,2],[0,2,1]],int)  # cift yon
    return v,f

# ---------- glb yazimi ----------
def yaz_glb(yol, gruplar):
    """gruplar: [(renk[r,g,b,a], (V,F)), ...] her grup ayri primitive+material."""
    bin_blob=b""; bviews=[]; accs=[]; prims=[]; mats=[]
    def ekle_acc(arr, hedef, tip, ctype):
        nonlocal bin_blob
        data=arr.astype('<f4').tobytes() if ctype==5126 else arr.astype('<u4').tobytes()
        # 4-byte hizala
        while len(bin_blob)%4: bin_blob+=b"\x00"
        off=len(bin_blob); bin_blob+=data
        bviews.append({"buffer":0,"byteOffset":off,"byteLength":len(data),"target":hedef})
        acc={"bufferView":len(bviews)-1,"componentType":ctype,"count":len(arr),"type":tip}
        if ctype==5126:
            acc["min"]=arr.min(0).tolist(); acc["max"]=arr.max(0).tolist()
        accs.append(acc); return len(accs)-1
    for renk,(V,F) in gruplar:
        V=np.asarray(V,float); F=np.asarray(F,int)
        # duz normaller: her ucgen icin yeni verteksler (flat shading)
        P=V[F.reshape(-1)]                       # (3m,3)
        tri=P.reshape(-1,3,3)
        n=np.cross(tri[:,1]-tri[:,0], tri[:,2]-tri[:,0])
        ln=np.linalg.norm(n,axis=1,keepdims=True); ln[ln==0]=1; n=n/ln
        N=np.repeat(n,3,axis=0)
        idx=np.arange(len(P),dtype=np.uint32).reshape(-1,3)
        pa=ekle_acc(P,34962,"VEC3",5126)
        na=ekle_acc(N,34962,"VEC3",5126)
        ia=ekle_acc(idx.reshape(-1,1)[:,0] if False else idx.reshape(-1), 34963,"SCALAR",5125)
        mats.append({"pbrMetallicRoughness":{"baseColorFactor":list(renk),
                     "metallicFactor":0.1,"roughnessFactor":0.75},
                     "doubleSided":True})
        prims.append({"attributes":{"POSITION":pa,"NORMAL":na},"indices":ia,"material":len(mats)-1})
    gltf={
      "asset":{"version":"2.0","generator":"goktungu-model-uret"},
      "scene":0,"scenes":[{"nodes":[0]}],
      "nodes":[{"mesh":0}],
      "meshes":[{"primitives":prims}],
      "materials":mats,"accessors":accs,"bufferViews":bviews,
      "buffers":[{"byteLength":len(bin_blob)}],
    }
    js=json.dumps(gltf,separators=(',',':')).encode('utf-8')
    while len(js)%4: js+=b" "
    while len(bin_blob)%4: bin_blob+=b"\x00"
    glb=struct.pack("<III",0x46546C67,2,12+8+len(js)+8+len(bin_blob))
    glb+=struct.pack("<II",len(js),0x4E4F534A)+js
    glb+=struct.pack("<II",len(bin_blob),0x004E4942)+bin_blob
    open(yol,"wb").write(glb)
    return len(glb)

# ---------- renk paleti (beyaz/gri taban; model.color ile tint edilir) ----------
GOVDE=[0.82,0.85,0.90,1]; KOYU=[0.30,0.34,0.40,1]; VURGU=[1.0,0.36,0.36,1]
CAM=[0.35,0.70,0.95,1]; DISK=[0.75,0.80,0.86,0.45]; UCGEN=[1.0,0.85,0.2,1]
METAL=[0.6,0.64,0.7,1]

# ===== SABIT KANAT =====
def model_ucak():
    g=[]
    g.append((GOVDE, birlestir([kutu(0,0,0, 20,2.6,2.6), silindir(10,0,0,1.3,4,'x',12,0.2)])))  # govde+burun
    g.append((GOVDE, kutu(-1,0,0, 5.5,0.6,30)))                # ana kanat (Z span)
    g.append((GOVDE, kutu(-9,0.6,0, 3.5,0.5,12)))              # yatay kuyruk
    g.append((KOYU,  kutu(-9,2.4,0, 3.5,4.5,0.5)))             # dikey kuyruk
    g.append((VURGU, silindir(11,0,0,0.6,1.2,'x',10)))         # burun vurgu
    g.append((UCGEN, ucgen_yatay(13, 8, 10, 2.2)))             # yon ucgeni
    yaz_glb(os.path.join(CIK,"ucak.glb"), g)

# ===== MULTIROTOR (N kol) =====
def model_multi(ad, N):
    g=[]
    g.append((GOVDE, kutu(0,0,0, 6.5,2.6,6.5)))
    g.append((KOYU,  kure(0,1.6,0, 2.4)))
    for i in range(N):
        aci = (360/N)*i + (45 if N%2==0 else 90)
        r=math.radians(aci)
        # kol: XZ duzleminde, aci burna (X) gore. X=cos, Z=sin
        armLen=12
        cx=math.cos(r)*armLen/2; cz=math.sin(r)*armLen/2
        # kol kutusu: yonu aci; basit olsun diye ince uzun kutu, dondur
        v,f=kutu(0,0,0, armLen,1.0,1.3)
        # Y ekseni etrafinda -aci dondur (X ileri, Z sag)
        ca,sa=math.cos(-r),math.sin(-r)
        R=np.array([[ca,0,sa],[0,1,0],[-sa,0,ca]])
        v=v@R.T; v+=[cx,0,cz]
        g.append((KOYU,(v,f)))
        tx=math.cos(r)*armLen; tz=math.sin(r)*armLen
        onMu = math.cos(r)>0.25
        g.append((VURGU if onMu else METAL, silindir(tx,0.8,tz,1.4,1.2,'y',10)))   # gobek
        g.append((VURGU if onMu else DISK, disk(tx,1.3,tz,4.2,0.35,16)))           # pervane disk
    g.append((UCGEN, ucgen_yatay(7, 6, 8, 2.6)))
    yaz_glb(os.path.join(CIK,ad+".glb"), g)

# ===== HELIKOPTER =====
def model_heli():
    g=[]
    g.append((GOVDE, kutu(0,0,0, 9,3.4,3.2)))
    g.append((CAM,   kure(2.5,0.3,0, 2.3)))
    g.append((KOYU,  kutu(-7,0.6,0, 9,1.0,1.0)))
    g.append((DISK,  disk(0,3.0,0, 9, 0.3, 24)))
    g.append((GOVDE, kutu(0,3.0,0, 18,0.35,0.8)))     # ana blade
    g.append((VURGU, kutu(-11,0.8,0.6, 0.3,0.4,5)))   # kuyruk rotor
    g.append((UCGEN, ucgen_yatay(6, 6, 8, 3.0)))
    yaz_glb(os.path.join(CIK,"heli.glb"), g)

# ===== RADAR (donen anten modelde; Cesium orientation ile dondurulur) =====
def model_radar():
    g=[]
    g.append((KOYU,  silindir(0,0.6,0, 3.4,1.2,'y',20)))    # taban
    g.append((METAL, silindir(0,3,0, 1.9,6,'y',16)))        # ayak
    # anten paneli: Z boyunca genis, hafif egik (X'e dogru)
    v,f=kutu(0,7.5,0, 1.4,6,11)
    # X ekseni etrafinda hafif egim
    a=math.radians(18); ca,sa=math.cos(a),math.sin(a)
    R=np.array([[1,0,0],[0,ca,-sa],[0,sa,ca]])
    v=(v-[0,7.5,0])@R.T+[0,7.5,0]
    g.append((GOVDE,(v,f)))
    g.append((VURGU, kutu(2.2,7.5,0, 3.5,0.6,0.6)))          # besleme cubugu (on)
    g.append((UCGEN, ucgen_yatay(3, 5, 6, 7.5)))             # yon ucgeni (antenle doner)
    yaz_glb(os.path.join(CIK,"radar.glb"), g)

# ===== ELEKTRO-OPTIK =====
def model_eo():
    g=[]
    g.append((KOYU,  silindir(0,2,0, 0.9,4,'y',14)))         # direk
    g.append((METAL, kutu(0,4.4,0, 3,1.2,4)))                # boyunduruk
    g.append((GOVDE, kure(0,5.0,0, 2.4)))                    # gimbal top
    g.append((KOYU,  silindir(2.6,5.0,0, 1.0,4.5,'x',14)))   # kamera namlu
    g.append((CAM,   silindir(4.8,5.0,0, 1.1,0.6,'x',14)))   # lens
    g.append((UCGEN, ucgen_yatay(3, 5, 6, 5.0)))
    yaz_glb(os.path.join(CIK,"eo.glb"), g)

model_ucak()
model_multi("quad",4); model_multi("hexa",6); model_multi("octo",8); model_multi("tri",3)
model_heli(); model_radar(); model_eo()
for f in sorted(os.listdir(CIK)):
    print(f, os.path.getsize(os.path.join(CIK,f)), "bayt")
