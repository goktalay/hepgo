#!/bin/bash
# HEPGO dış sağlık denetimi (03.11): servis "active" görünüp yanıt vermiyorsa (olay döngüsü kilitli, dosya sınırı dolu,
# soket kuyruğu dolu…) systemd bunu görmez. Bu betik her dakika her servise gerçek bir HTTP isteği atar; ardışık
# FAILS kez yanıt yoksa (HTTP kodu ne olursa olsun yanıt = canlı) servisi yeniden başlatır. Aynı servis için en çok
# 10 dk'da bir; yeni başlamış (2 dk) ya da active olmayan servise dokunmaz. Olaylar: journalctl -t hepgo-health
FAILS=3
COOLDOWN=600
STATE=/run/hepgo-health
mkdir -p "$STATE"
SERVICES="caymaz:uds:/run/hepgo/caymaz.sock turkbey:uds:/run/hepgo/turkbey.sock merkez:uds:/run/hepgo/merkez.sock
bakkal-demo:uds:/run/hepgo/bakkal-demo.sock berber-demo:uds:/run/hepgo/berber-demo.sock lokanta-demo:uds:/run/hepgo/lokanta-demo.sock
hepgo-demo:uds:/run/hepgo/hepgo-demo.sock mtweb:uds:/run/hepgo/mtweb.sock veilox:uds:/run/hepgo/veilox.sock
simumav:uds:/run/hepgo/simumav.sock masterworld:uds:/run/hepgo/masterworld.sock appgw:uds:/run/hepgo/appgw.sock
sshmasters:tcp:127.0.0.1:8095"
now=$(date +%s)
for item in $SERVICES; do
  name=${item%%:*}; rest=${item#*:}; kind=${rest%%:*}; addr=${rest#*:}
  unit=hepgo-$name
  [ "$(systemctl is-active "$unit" 2>/dev/null)" = active ] || { rm -f "$STATE/$name.fail"; continue; }
  since=$(date -d "$(systemctl show -p ActiveEnterTimestamp --value "$unit")" +%s 2>/dev/null || echo 0)
  [ $((now - since)) -lt 120 ] && { rm -f "$STATE/$name.fail"; continue; }
  if [ "$kind" = uds ]; then
    code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' --unix-socket "$addr" -H 'Host: localhost' http://localhost/ 2>/dev/null)
  else
    code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://$addr/" 2>/dev/null)
  fi
  if [ -n "$code" ] && [ "$code" != 000 ]; then rm -f "$STATE/$name.fail"; continue; fi
  n=$(( $(cat "$STATE/$name.fail" 2>/dev/null || echo 0) + 1 )); echo $n > "$STATE/$name.fail"
  logger -t hepgo-health "$unit yanıt vermiyor ($n/$FAILS)"
  [ $n -lt $FAILS ] && continue
  last=$(cat "$STATE/$name.restart" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt $COOLDOWN ]; then logger -t hepgo-health "$unit yeniden başlatma bekletildi (son ${COOLDOWN}s içinde yapıldı)"; continue; fi
  pid=$(systemctl show -p MainPID --value "$unit")
  fds=$(ls /proc/$pid/fd 2>/dev/null | wc -l)
  # kök neden için iz: watchdog dökümü uygulamada; burada dosya sayısı ve soket kuyruğu
  q=$( [ "$kind" = uds ] && ss -xl | awk -v a="$addr" '$5==a {print $3"/"$4}')
  logger -t hepgo-health "$unit YENİDEN BAŞLATILIYOR: $FAILS dk yanıt yok (pid $pid, açık dosya $fds, kuyruk ${q:-?})"
  echo $now > "$STATE/$name.restart"; rm -f "$STATE/$name.fail"
  systemctl restart "$unit"
done
