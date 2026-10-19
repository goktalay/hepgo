# HEPGO SITL ikilileri — ArduPilot 4.7.2 + `SIM_SRV_REV` + `SIM_PLN_THR_MUL` yamaları

HEPGO'nun sanal dronları (`app/drone_sitl.py`) gerçek ArduPilot SITL süreçleridir (`arduplane`, `arducopter`). Resmi
`firmware.ardupilot.org` ikilisi yerine **yamalı** ikili kullanılır; yamalar sırayla: `0001-sim-srv-rev.patch` (sanal servo montajı, §20.1)
ve `0002-sim-pln-thr-mul.patch` (plane itki çarpanı → azami hız, §23).

## Yama 0002: `SIM_PLN_THR_MUL` (float, varsayılan 1; docs/ucus-simulatoru.md §23.1)
Stok `SIM_Plane` modelinde itki = gaz × `thrust_scale` (2 kg · g / 0,7 = 28 N) → tam gaz seviye hızı ≈ 31,8 m/s; bunu değiştiren parametre yoktur
(`SIM_ENGINE_MUL` plane modelinde okunmaz). Kullanıcı: CAYMAZ 222 cc motor tam gazda 45 m/s. Yama `libraries/SITL/SITL.h/.cpp` (`var_info3` idx 3)
ve `SIM_Plane.cpp calculate_forces` (itki × mul; gürültü terimi ölçeksiz) — hız √mul ile ölçeklenir; HEPGO `flightsim_power.thr_mul_icin(v)` aynı fizikten
çarpanı çözer (45 m/s → 1,993) ve oturum başında `AIRSPEED_MAX/CRUISE`, `THR_MAX 100` ile birlikte yazar. İkili desteği dosyada `\0PLN_THR_MUL\0` imzasıyla
anlaşılır (`drone_sitl.hiz_olcegi_destegi`); yamasız ikilide yalnız ArduPilot sınırları + sarı uyarı.
Ölçüm (`tools/sitl/dogrula_guc.py`, FBWA + gaz %100, 70 sn): yamasız ikili yer hızı **32,7 m/s** (hava 29,4; stok fizik) → yamalı ikili **47,6 m/s**
(hava 41,9; hafif tırmanışta) — hedef 45 ±%10 içinde.

Yerleştirilmiş dizinler: `/opt/hepgo/sitl/bin` (yalnız 0001), **`/opt/hepgo/sitl/bin-new` (0001 + 0002)** — `.version`:
`4.7.2-FIRMWARE_VERSION_TYPE_OFFICIAL+hepgo-sim-srv-rev+pln-thr-mul (fb773567 + tools/sitl/0001-sim-srv-rev.patch + 0002-sim-pln-thr-mul.patch)`.
DEV `HEPGO_SITL_DIR` ve PROD yerleştirmesi kullanıcı onayıyla (aşağıdaki "Yerleştirme").

## Neden (docs/ucus-simulatoru.md §20.1)
Gerçek uçakta `SERVOn_REVERSED=1` servo **montaj yönünü** düzeltir. Stok SITL fiziği (`SIM_Plane` vb.) servo PWM'ini doğrudan
yüzey açısına çevirir — sanal montaj hep "düz" — bu yüzden gerçek uçağın parametre dosyası (CAYMAZ: `SERVO1_REVERSED=1`,
`SERVO2_REVERSED=0`) SITL'e aynen yazılınca kontrol tersine döner ve uçak takla atar. Kullanıcı kararı: sanal uçak gerçek
uçağın servo montajını da taklit etmeli.

## Yama: `SIM_SRV_REV` (int32 bit maskesi; bit n-1 = SERVOn ters monteli)
- `libraries/SITL/SITL.h/.cpp`: yeni parametre `SIM_SRV_REV` (`var_info3` indeks 2, varsayılan 0).
- `libraries/SITL/SIM_Aircraft.h/.cpp`: `Aircraft::apply_servo_reverse_mask` — `update_model()` girişinde, maskedeki her kanalın
  PWM'i 1500 µs ekseninde yansıtılır (`pwm' = 3000 − pwm`, 1000–2000 içinde; PWM 0 = çıkış yok → dokunulmaz). Fizik modeline
  (`update(input)`) yansıtılmış kopya gider → **tüm modeller** (plane, copter, quadplane, heli …) kapsanır; maske 0 iken davranış
  birebir eskisi gibidir.
- Net etki: ArduPilot `REVERSED=1` ile çıkışı ters çevirir, sanal montaj geri çevirir → yüzey hareketi gerçek uçakla aynı.
- Motor (ESC) kanallarına bit konmamalı: ArduPilot motor çıkışını ham yazar (`AP_Motors::rc_write → SRV_Channels::set_output_pwm`,
  REVERSED uygulanmaz); HEPGO `drone_params.srv_rev_mask` bu kanalları (kayıtlı `SERVOn_FUNCTION` motor kodu ya da araç tipinin
  varsayılan motor kanalı) atlar. Helikopter swash/kuyruk ve uçak gazı scaled/trimmed yazılır → REVERSED etkili → bit konur.

## Sürüm
- Kaynak: `https://github.com/ArduPilot/ardupilot` etiketi **`Plane-4.7.2`** = `fb773567` (Copter-4.7.2 aynı commit; resmi
  `stable-4.7.2` ikilileriyle aynı kaynak).
- `.version`: `4.7.2-FIRMWARE_VERSION_TYPE_OFFICIAL+hepgo-sim-srv-rev (fb773567 + tools/sitl/0001-sim-srv-rev.patch)`.
- HEPGO, ikilinin yamayı içerdiğini dosyada `\0SRV_REV\0` imzasını arayarak anlar (`drone_sitl.sanal_montaj_destegi`); resmi
  ikilide imza yoktur → montaj parametreleri nötr (0) yazılır + sarı uyarı (eski davranış, güvenli geri düşüş).

## Yeniden üretme (Ubuntu 24.04, gcc 13, Python 3.12; ~6 dk / 10 çekirdek)
```bash
git clone --depth 1 --branch Plane-4.7.2 https://github.com/ArduPilot/ardupilot ~/mt-work/ardupilot
cd ~/mt-work/ardupilot
git submodule update --init --depth 1 modules/waf modules/mavlink modules/DroneCAN/libcanard modules/DroneCAN/DSDL \
    modules/DroneCAN/dronecan_dsdlc modules/DroneCAN/pydronecan modules/gtest modules/lwip modules/gbenchmark \
    modules/littlefs modules/Micro-CDR modules/Micro-XRCE-DDS-Client modules/gsoap
python3 -m venv ~/mt-work/ap-venv && ~/mt-work/ap-venv/bin/pip install 'empy==3.3.4' pexpect future pymavlink intelhex lxml pyserial setuptools
export PATH=~/mt-work/ap-venv/bin:$PATH
git apply /opt/hepgo/fabrika-yonetim/tools/sitl/0001-sim-srv-rev.patch
git apply /opt/hepgo/fabrika-yonetim/tools/sitl/0002-sim-pln-thr-mul.patch   # 0001'in üstüne (sıra önemli)
./waf configure --board sitl && ./waf plane copter -j8
ls build/sitl/bin/arduplane build/sitl/bin/arducopter
```
Sistem paketleri: `gcc g++ make gawk python3-venv git` (apt ile kurulu olmalı; bu makinede ek kurulum gerekmedi).

## Yerleştirme
```bash
cp build/sitl/bin/arduplane build/sitl/bin/arducopter /opt/hepgo/sitl/bin/
cd /opt/hepgo/sitl/bin && for b in arduplane arducopter; do
  echo "$(sha256sum $b | cut -d' ' -f1)  $b  stable-4.7.2+hepgo-srvrev+plnthrmul" > $b.sha256
  echo "4.7.2-FIRMWARE_VERSION_TYPE_OFFICIAL+hepgo-sim-srv-rev+pln-thr-mul (fb773567 + tools/sitl/0001-sim-srv-rev.patch + 0002-sim-pln-thr-mul.patch)" > $b.version
done
```
(0002 derlemesi önce `/opt/hepgo/sitl/bin-new`'e konur; `bin`'e taşıma ve PROD yerleştirmesi kullanıcı onayıyla.)
DEV: `HEPGO_SITL_DIR=/opt/hepgo/sitl/bin` (eski resmi ikililer `bin-4.7.2-orig/`). PROD: `/opt/hepgo/caymazbuild/data/sitl`
(deploy kullanıcı tarafından; `.sha256` ile doğrulanır). Yeni ikili yerleştirildikten sonra çalışan SITL oturumları kapatılıp
yeniden açılmalı (ikili süreç başlangıcında yüklenir).

## Doğrulama
`tools/sitl/dogrula_guc.py <ikili dizini> hiz,speedup,yakit` (çıktı dizini DOGRULA_OUT, varsayılan /tmp/flsim/guc; §23: tam gaz hız ölçümü, SIM_SPEEDUP 4× zaman
oranı + .bin/kayıttan oynatma süresi, yakıt/batarya düşüşü ve bitiş) ve
`tools/sitl/dogrula_srv_rev.py <ikili dizini> rev10,rev00,rev10_mask0,copter,copter_mask1` (çıktı dizini DOGRULA_OUT, varsayılan /tmp/flsim/srvrev2) — gerçek SITL ile tekerlekli kalkış,
60 sn roll/irtifa istatistiği (sonuçlar §20.1 ölçüm notunda ve commit mesajında).
