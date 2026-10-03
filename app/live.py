"""Canlı yayın medya yardımcıları — MediaRecorder'ın parçalı MP4 (fMP4) akışını kutulara ayırır.

Yayıncı (tarayıcı) kamerayı MediaRecorder ile ~1 sn'lik fMP4 parçaları olarak WebSocket'ten gönderir; sunucu:
  · ilk 'ftyp'+'moov' kutularını başlangıç (init) segmenti olarak saklar ve codec dizgesini çıkarır
    (izleyici MediaSource'u bununla açar, ör. video/mp4; codecs="avc1.42e01f,mp4a.40.2"),
  · her 'moof'+'mdat' çiftini bir parça olarak izleyicilere iletir; parçanın video izinin ilk örneği anahtar kare mi
    (sample_is_non_sync_sample = 0) bakar — geç katılan izleyici son anahtar kareden başlar.
Yeniden kodlama yapılmaz (CPU harcanmaz); yalnız bayt kopyalanır.
"""
import struct


def _iter(buf, start=0, end=None):
    """buf[start:end] içindeki tam kutular: (tür, başlangıç, boyut, başlık uzunluğu)."""
    i = start
    end = len(buf) if end is None else end
    while i + 8 <= end:
        size, typ = struct.unpack_from('>I4s', buf, i)
        hl = 8
        if size == 1:
            if i + 16 > end:
                break
            size = struct.unpack_from('>Q', buf, i + 8)[0]
            hl = 16
        elif size == 0:
            size = end - i
        if size < hl or i + size > end:
            break
        yield typ.decode('latin-1'), i, size, hl
        i += size


def _find(buf, start, end, path):
    """İç içe kutu yolu (ör. ['mdia', 'hdlr']) → (başlangıç, boyut, başlık) ya da None."""
    for typ, s, size, hl in _iter(buf, start, end):
        if typ == path[0]:
            if len(path) == 1:
                return s, size, hl
            r = _find(buf, s + hl, s + size, path[1:])
            if r:
                return r
    return None


def _all(buf, start, end, typ):
    return [(s, size, hl) for t, s, size, hl in _iter(buf, start, end) if t == typ]


def _codec(buf, entry_type, s, size, hl):
    """Örnek girdisinden (stsd) MSE codec dizgesi."""
    if entry_type in ('avc1', 'avc3'):
        cfg = _find(buf, s + hl + 78, s + size, ['avcC'])
        if cfg:
            o = cfg[0] + cfg[2]
            return f'{entry_type}.{buf[o + 1]:02x}{buf[o + 2]:02x}{buf[o + 3]:02x}'
        return 'avc1.42e01f'
    if entry_type in ('hvc1', 'hev1'):
        return f'{entry_type}.1.6.L93.B0'
    if entry_type == 'vp09':
        cfg = _find(buf, s + hl + 78, s + size, ['vpcC'])
        if cfg:
            o = cfg[0] + cfg[2] + 4   # tam kutu (sürüm + bayrak)
            level = buf[o + 1] or 10   # kaydedici seviyeyi 0 (bilinmiyor) yazabiliyor → MSE geçerli en düşük seviye
            return f'vp09.{buf[o]:02d}.{level:02d}.{(buf[o + 2] >> 4) or 8:02d}'
        return 'vp09.00.10.08'
    if entry_type == 'av01':
        return 'av01.0.04M.08'
    if entry_type == 'mp4a':
        esds = _find(buf, s + hl + 28, s + size, ['esds'])
        aot = 2
        if esds:   # DecoderSpecificInfo (etiket 0x05) ilk 5 bit = ses nesne türü
            d = bytes(buf[esds[0] + esds[2]: esds[0] + esds[1]])
            k = d.find(b'\x05')
            while k != -1 and k + 2 < len(d):
                j = k + 1
                while j < len(d) and d[j] & 0x80:
                    j += 1
                if j + 1 < len(d):
                    aot = d[j + 1] >> 3 or 2
                    break
                k = d.find(b'\x05', k + 1)
        return f'mp4a.40.{aot}'
    if entry_type in ('Opus', 'opus'):
        return 'opus'
    return entry_type


class Fmp4:
    """fMP4 bayt akışını init segmenti + (parça, anahtar_mı) olarak ayırır."""

    def __init__(self):
        self.buf = bytearray()
        self.init = None
        self._pre = bytearray()
        self._cur = None
        self._key = False
        self.video_id = None
        self.trex = {}         # track_ID → default_sample_flags
        self.codecs = []       # ['avc1.42e01f', 'mp4a.40.2']
        self.width = self.height = None

    @property
    def mime(self):
        return f'video/mp4; codecs="{",".join(self.codecs)}"' if self.codecs else 'video/mp4'

    def feed(self, data):
        self.buf += data
        out = []
        used = 0
        for typ, s, size, _hl in _iter(self.buf):
            used = s + size
            box = bytes(self.buf[s:s + size])
            if self.init is None:
                self._pre += box
                if typ == 'moov':
                    self.init = bytes(self._pre)
                    self._moov(box)
                    out.append(('init', self.init))
                continue
            if typ == 'moof':
                self._cur = bytearray(box)
                self._key = self._is_key(box)
            elif typ == 'mdat':
                if self._cur is not None:
                    self._cur += box
                    out.append(('frag', bytes(self._cur), self._key))
                    self._cur = None
            elif typ in ('ftyp', 'moov'):   # kaydedici yeniden başladı: yeni init (izleyici 'sequence' kipinde sürer)
                self._pre = bytearray(box) if typ == 'ftyp' else self._pre + box
                if typ == 'moov':
                    self.init = bytes(self._pre)
                    self._moov(box)
                    out.append(('init', self.init))
            elif self._cur is not None:   # styp / sidx / prft… parçanın parçası
                self._cur += box
        del self.buf[:used]
        return out

    def _moov(self, b):
        self.codecs, self.trex = [], {}
        for s, size, hl in _all(b, 8, len(b), 'trak'):
            tkhd = _find(b, s + hl, s + size, ['tkhd'])
            hdlr = _find(b, s + hl, s + size, ['mdia', 'hdlr'])
            stsd = _find(b, s + hl, s + size, ['mdia', 'minf', 'stbl', 'stsd'])
            if not (tkhd and hdlr):
                continue
            o = tkhd[0] + tkhd[2]
            ver = b[o]
            tid = struct.unpack_from('>I', b, o + (20 if ver == 1 else 12))[0]
            handler = bytes(b[hdlr[0] + hdlr[2] + 8: hdlr[0] + hdlr[2] + 12]).decode('latin-1')
            if handler == 'vide':
                self.video_id = tid
                w_off = o + (88 if ver == 1 else 76)
                try:
                    self.width = struct.unpack_from('>I', b, w_off)[0] >> 16
                    self.height = struct.unpack_from('>I', b, w_off + 4)[0] >> 16
                except struct.error:
                    pass
            if stsd:
                for t, es, esz, ehl in _iter(b, stsd[0] + stsd[2] + 8, stsd[0] + stsd[1]):
                    c = _codec(b, t, es, esz, ehl)
                    (self.codecs.insert(0, c) if handler == 'vide' else self.codecs.append(c))
                    break
        mvex = _find(b, 8, len(b), ['mvex'])
        if mvex:
            for s, size, hl in _all(b, mvex[0] + mvex[2], mvex[0] + mvex[1], 'trex'):
                o = s + hl + 4
                tid, _di, _dd, _ds, flags = struct.unpack_from('>IIIII', b, o)
                self.trex[tid] = flags

    def _is_key(self, b):
        for s, size, hl in _all(b, 8, len(b), 'traf'):
            tfhd = _find(b, s + hl, s + size, ['tfhd'])
            trun = _find(b, s + hl, s + size, ['trun'])
            if not (tfhd and trun):
                continue
            o = tfhd[0] + tfhd[2]
            tflags = int.from_bytes(b[o + 1:o + 4], 'big')
            tid = struct.unpack_from('>I', b, o + 4)[0]
            if self.video_id is not None and tid != self.video_id:
                continue
            p = o + 8
            default = self.trex.get(tid, 0)
            if tflags & 0x1:
                p += 8
            if tflags & 0x2:
                p += 4
            if tflags & 0x8:
                p += 4
            if tflags & 0x10:
                p += 4
            if tflags & 0x20:
                default = struct.unpack_from('>I', b, p)[0]
            r = trun[0] + trun[2]
            rflags = int.from_bytes(b[r + 1:r + 4], 'big')
            q = r + 8
            if rflags & 0x1:
                q += 4
            if rflags & 0x4:
                first = struct.unpack_from('>I', b, q)[0]
            elif rflags & 0x400:
                q2 = q + (4 if rflags & 0x100 else 0) + (4 if rflags & 0x200 else 0)
                first = struct.unpack_from('>I', b, q2)[0]
            else:
                first = default
            return not (first >> 16) & 1
        return self.video_id is None   # video izi yoksa (yalnız ses) her parça başlangıç noktası
