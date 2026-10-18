# Endüstriyel Tasarım — STEP sürümlerinin 3B önizlemesi (STL / GLB / PNG)

Her STEP (.step/.stp) sürümü için üç türetilmiş dosya tutulur; proje kartında ve proje içindeki çizim/montaj kartında
küçük resim + canlı 3B gösterilir, "STL indir" ile tek gövdeli STL alınır.

## Neden tarayıcıda?
PROD sunucusunda node ve OpenCascade (occt) yok. STEP çözümleme zaten görüntüleyici için `static/vendor/occt` (WASM) ile
tarayıcıda yapılıyor; dönüşüm de aynı yerde yapılır ve sonuç sunucuya **önbellek** olarak yazılır. Böylece 17 MB'lık bir
STEP her açılışta değil, bir kez çözümlenir; sonraki kullanıcılar GLB/PNG'yi alır.

## Ne zaman üretilir?
* **Yeni sürüm yüklendiğinde** — yükleyen kullanıcının tarayıcısı, yükleme bitince hemen üretir (ilerleme pencerede).
* **Önizlemesi olmayan mevcut sürüm** — proje listesi ya da proje sayfasını açan **ilk yazma izinli** kullanıcının
  tarayıcısı üretir (kartta "Önizleme hazırlanıyor %"). Salt okuyan kullanıcı "Önizleme bekliyor" görür.
* **Yeniden üret** (↻) — kart köşesinde ve montaj detayı başlığında; üzerine yazar.
* Aynı anda tek üretim (kuyruk); aynı sürüm için tekrar istek dinleyici olarak eklenir (`design_preview.js: ensurePreview`).

## Üretim adımları (`static/js/modules/design_preview.js`)
1. `GET /api/design/file?v=<vid>` — STEP indirilir (ilerleme).
2. `step-worker.js` (occt wasm) ile kademeli lineer sapma: ilk deneme 2 mm; üçgen sayısı 150 000'i aşarsa sapma
   oranla (üçgen ≈ 1/sapma) büyütülür, en çok 4 deneme. Gövdeler renge göre birleştirilir (`mergeGeometries`).
3. **STL** — ikili, birleşik tek gövde, **mm**, renk yok (`groupToStl`; 84 + 50·n bayt).
4. **GLB** — renkli, `GLTFExporter` binary; **mm → m** (glTF standardı).
5. **PNG** — 3/4 açıdan 480×360, şeffaf arka plan; en kısa boyut "yukarı" kabul edilir (CAD Z-yukarı → sahne Y-yukarı).
6. `PUT /api/design/versions/{vid}/preview?kind=stl|glb|thumb` (ham gövde; `putBinary`).

## Sunucu (`app/routers/design.py`)
* `PUT /api/design/versions/{vid}/preview?kind=…` — yazma izni (design modülünde "yaz"); sınır STL/GLB 50 MB, PNG 2 MB
  (Content-Length önce, okunan boyut sonra → 413); biçim denetimi (ikili STL uzunluk = 84 + 50·n, GLB `glTF` + sürüm 2,
  PNG imzası → 400). Dosya: `UPLOAD_DIR/design/preview/<vid>.{stl,glb,png}`; sütunlar `design_drawing_versions.preview_stl /
  preview_glb / preview_thumb / preview_at` (ALTER ile eklenir, `app/db.py`).
* `GET /api/design/file?s=<vid>` STL (`model/stl`; `dl=1` → `attachment`, ad `<çizim dosya adı kökü>.stl`, **yalnız Master**),
  `?g=<vid>` GLB (`model/gltf-binary`), `?t=<vid>` PNG (`preview_thumb`, yoksa eski `thumb_path`).
* `GET /api/design/projects` → her projede `step`: projedeki son STEP sürümü `{id, drawing_id, name, version, file_name,
  preview_thumb, preview_glb, preview_stl}`; `GET /projects/{pid}` ağacında ve `GET /drawings/{did}` içinde `current.preview`
  `{stl, glb, thumb, at}` adresleri.

## Gösterim (`static/js/modules/design.js`)
* Proje kartı: küçük resim; fare gelince dönen canlı GLB (`liveOnHover`), köşede "🧊 3B" (pencere) ve ↻.
* Çizim/montaj kartı: aynı; "3B görüntüle" hızlı GLB penceresi (OrbitControls, kadraj, Master'a STL indir).
* Montaj detayı başlığı: "Hızlı 3B", "STL indir" (Master), ↻. Ayrıntılı STEP görüntüleyici (parça ağacı, patlatma,
  eşleştirme, CFD) olduğu gibi kalır.

Test: `tests/test_design_preview.py` (PUT yetki/boyut/biçim/alanlar, dosya uçları).
