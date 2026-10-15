// ============================================================
// GOKTUNGU GCS — DRON PANELI PFD (Boeing tarzi cam kokpit)  (IS152)
// ------------------------------------------------------------
// Kaynak: kullanicinin yukledigi "Advanced Avionics Glass Cockpit" PFD'si.
// Yalniz gostergeler alindi; SAG TARAFTAKI 3B UCAK GORUNUMU CIKARILDI
// (kullanici istegi). drawPFD ve alt cizim islevleri oldugu gibi korunur;
// telemetriden beslenir. Sanal tuval 800x560; panel tuvaline sigacak
// sekilde olceklenir (yuksek DPI net cizim).
//
// Kamu API:
//   PanelPFD.ciz(canvas, {pitch, roll, hdg, spd(kt), alt(ft), vsi(ft/dk), selspd})
//   PanelPFD.telemetriDurum(d) -> yukaridaki durum (birim donusumu)
// ============================================================
window.PanelPFD = (function(){
  "use strict";
  var ctx = null;
  // IS155: ufuk ustundeki bosluk kaldirildi -> AI yukari cekildi, sanal
  // yukseklik kisaltildi (asagida H=528, drawPFD'de AI_Y=10).
  var W = 800, H = 528, PFD_W = 800;
  var _mod = "";   // yapay ufuk sag altta gosterilen ucus modu
  var _gpsFix = null, _gpsUydu = null;   // IS155: yapay ufuk sol altta GPS durumu
  var _gpsKutu = null;                    // IS155: GPS kutusu (tiklama: fokus)
  var _modKutu = null;                    // IS155: mod kutusu (tiklama: mod sec)
  var _arm = "", _armRenk = "#c2cbd6";    // IS156: ARM durumu (sol ust kutu)
  var _armKutu = null, _islemKutu = null; // IS156: ARM/Islemler tiklama alanlari

  // IS153: GUNDUZ TEMASI. Acik temada koyu PFD renklerini acik karsiliklariyla
  // esleyen bir katman; cizim kodu DEGISMEDEN gunduz gorunumu verir. Yapay ufuk
  // (gok/yer), vurgu kutulari (sari deger kutulari) ve renkli uyarilar (yesil/
  // magenta/turuncu) her iki temada okunur oldugu icin eslenmez.
  var GUNDUZ_ESLE = {
    // yapay ufuk: gunduz icin daha acik gok/yer (tasarima uygun)
    "#1a74c4":"#6fb2e8", "#7a4a1e":"#bb9061",
    // koyu zeminler -> acik
    "#1a1c22":"#e9edf2", "#222830":"#dbe2ea", "#1a1e28":"#eef2f7", "#141820":"#e6ebf1",
    // acik metin/tik -> koyu
    "#fff":"#14202e", "#ffffff":"#14202e", "#ddd":"#223040", "#cccccc":"#2c3a4e",
    "#ccc":"#2c3a4e", "#e0e0e0":"#223040",
    "#9aa0b0":"#5b6675", "#b0b8c8":"#4a5666", "#6a7a8a":"#5b6675",
    "#8a97a6":"#5b6675", "#555a64":"#6b7686", "#9aa7b6":"#5b6675",
    // kenar/cizgi -> acik gri
    "#2a2e38":"#c7d0db", "#3a3f4a":"#c7d0db", "#2e3340":"#c7d0db", "#444":"#b3bece", "#3a3f4a":"#c7d0db",
    // koyu tikler -> orta gri (acik zeminde gorunur)
    "#666":"#8f9bab", "#555":"#8f9bab", "#404858":"#aab4c2",
  };
  function _mapRenk(v) {
    if (typeof v !== "string") return v;
    var k = v.toLowerCase();
    return GUNDUZ_ESLE[k] || v;
  }
  function temaCtx(c) {
    return new Proxy(c, {
      get: function (t, p) { var val = t[p]; return typeof val === "function" ? val.bind(t) : val; },
      set: function (t, p, v) { if (p === "fillStyle" || p === "strokeStyle") v = _mapRenk(v); t[p] = v; return true; },
    });
  }

// =================================================================
function clipRect(x,y,w,h,fn){ ctx.save();ctx.beginPath();ctx.rect(x,y,w,h);ctx.clip();fn();ctx.restore(); }

function roundClip(x,y,w,h,r,fn){
  ctx.save();ctx.beginPath();
  ctx.moveTo(x+r,y);ctx.lineTo(x+w-r,y);ctx.arcTo(x+w,y,x+w,y+r,r);
  ctx.lineTo(x+w,y+h-r);ctx.arcTo(x+w,y+h,x+w-r,y+h,r);
  ctx.lineTo(x+r,y+h);ctx.arcTo(x,y+h,x,y+h-r,r);
  ctx.lineTo(x,y+r);ctx.arcTo(x,y,x+r,y,r);
  ctx.closePath();ctx.clip();fn();ctx.restore();
}

function lerpColor(c1,c2,t){
  const h=s=>parseInt(s,16);
  const r1=h(c1.slice(1,3)),g1=h(c1.slice(3,5)),b1=h(c1.slice(5,7));
  const r2=h(c2.slice(1,3)),g2=h(c2.slice(3,5)),b2=h(c2.slice(5,7));
  return `rgb(${Math.round(r1+(r2-r1)*t)},${Math.round(g1+(g2-g1)*t)},${Math.round(b1+(b2-b1)*t)})`;
}

// =================================================================
//  MAIN RENDER

function drawPFD(p, roll, r, curSpd, curAlt, curHdg, vsiVal, selSpd, locDev, gsDev){

  // ---- PFD LAYOUT CONSTANTS ----
  // The attitude indicator (AI) is a rounded rectangle in the center
  // IS155: AI_Y 55 -> 10 (ufuk ustundeki bosluk kaldirildi)
  const AI_X=130, AI_Y=10, AI_W=530, AI_H=400;
  const AI_CX=AI_X+AI_W/2, AI_CY=AI_Y+AI_H/2;

  // IS154: ust "UCUS MODU" basligi kaldirildi; mod, yapay ufuk icinde SAG ALTA
  // kucuk kutu olarak cizilir (asagida, drawAttitude'dan sonra).
  ctx.fillStyle='#1a1c22'; ctx.fillRect(0,0,PFD_W,55);

  // ========================
  // 2. ATTITUDE INDICATOR (rounded rectangle with clip)
  // ========================
  roundClip(AI_X, AI_Y, AI_W, AI_H, 18, ()=>{
    drawAttitude(AI_X, AI_Y, AI_W, AI_H, AI_CX, AI_CY, p, roll, r);
  });

  // AI border
  ctx.strokeStyle='#2a2e38'; ctx.lineWidth=2;
  ctx.beginPath();
  ctx.moveTo(AI_X+18,AI_Y); ctx.lineTo(AI_X+AI_W-18,AI_Y);
  ctx.arcTo(AI_X+AI_W,AI_Y,AI_X+AI_W,AI_Y+18,18);
  ctx.lineTo(AI_X+AI_W,AI_Y+AI_H-18);
  ctx.arcTo(AI_X+AI_W,AI_Y+AI_H,AI_X+AI_W-18,AI_Y+AI_H,18);
  ctx.lineTo(AI_X+18,AI_Y+AI_H);
  ctx.arcTo(AI_X,AI_Y+AI_H,AI_X,AI_Y+AI_H-18,18);
  ctx.lineTo(AI_X,AI_Y+18);
  ctx.arcTo(AI_X,AI_Y,AI_X+18,AI_Y,18);
  ctx.stroke();

  // IS152: Flight director + ILS (LOC/GS) drona ozgu degil, kaldirildi.

  // ========================
  // 4. AIRCRAFT SYMBOL (fixed, white)
  // ========================
  drawAircraftSymbol(AI_CX, AI_CY);

  // ========================
  // 5. BANK ANGLE ARC + POINTER
  // ========================
  drawBankArc(AI_CX, AI_CY, AI_Y, roll);

  // ========================
  // 7. AIRSPEED TAPE (left of AI) + VSI right next to it
  // ========================
  drawAirspeedTape(0, AI_Y-5, 96, AI_H+10, curSpd, selSpd, vsiVal);
  drawVSI(98, AI_Y-5, 32, AI_H+10, vsiVal);

  // ========================
  // 8. ALTIMETER TAPE (right of AI)
  // ========================
  drawAltimeterTape(AI_X+AI_W+2, AI_Y-5, 130, AI_H+10, curAlt, vsiVal);

  // ========================
  // 10. HEADING COMPASS ARC (below AI) — IS154: hiz seridinin solundan
  // irtifa seridinin sagina kadar TAM GENISLIGE yayilir (ortada dar degil).
  // ========================
  {
    // IS155: tam ortali (pSol/pSag simetrik) -> 001 kutusu panel ortasinda
    var pSol = 8, pSag = 800 - 8;                  // simetrik, orta = 400
    var pGen = pSag - pSol;
    drawHeadingCompass(pSol + pGen / 2, AI_Y + AI_H + 10, pGen - 20, curHdg);
  }

  // IS156: DORT KOSE KUTUSU — hepsi ayni stil, canvas'a cizili (resize'da
  // birlikte olceklenir). ARM sol-ust, ISLEMLER sag-ust, GPS sol-alt, MOD sag-alt.
  {
    var yUst = AI_Y + 8, yAlt = AI_Y + AI_H - 34;
    _armKutu   = koseKutu(_arm || '—', _armRenk, AI_X + 10, yUst, false);
    _islemKutu = koseKutu('İŞLEMLER', '#00e676', AI_X + AI_W - 10, yUst, true);
    var fx = _gpsFix, gtxt, gcol;
    if (fx == null || fx <= 0) { gtxt = 'NO GPS'; gcol = '#ff5d5d'; }
    else if (fx < 3) { gtxt = 'WAIT GPS'; gcol = '#ffb020'; }
    else { gtxt = (fx >= 5 ? 'RTK FIX' : 'GPS FIX'); gcol = '#00e676'; }
    if (_gpsUydu != null && fx != null && fx >= 2) gtxt += ' ' + _gpsUydu;
    _gpsKutu = koseKutu(gtxt, gcol, AI_X + 10, yAlt, false);
    _modKutu = koseKutu(_mod || '—', '#00e676', AI_X + AI_W - 10, yAlt, true);
  }
  // IS152: sahte airliner ustveri katmani (DME/RA/ILS/IPOS) kaldirildi.
}

// IS156: kose kutusu cizimi (ARM/ISLEMLER/GPS/MOD icin ortak). sag=true ise
// x saga hizalama referansidir. Doner: {x,y,w,h} (tiklama alani).
function koseKutu(txt, renk, x, y, sag) {
  ctx.font = 'bold 17px Arial';
  var w = ctx.measureText(txt).width + 16;
  var bx = sag ? (x - w) : x;
  ctx.fillStyle = 'rgba(6,10,16,0.60)'; ctx.fillRect(bx, y, w, 26);
  ctx.strokeStyle = renk; ctx.lineWidth = 1.5; ctx.strokeRect(bx, y, w, 26);
  ctx.fillStyle = renk; ctx.textAlign = 'left'; ctx.fillText(txt, bx + 8, y + 18);
  return { x: bx, y: y, w: w, h: 26 };
}

// ---- ATTITUDE INDICATOR INTERNALS ----
function drawAttitude(ax, ay, aw, ah, acx, acy, p, roll, r){
  const pitchScale = 9.5;
  // W → p (pitchDeg) goes negative → pitchYOff negative → hy = acy - (negative) = acy + offset → horizon moves DOWN → sky fills upper AI ✓
  const pitchYOff = p * pitchScale;

  const rAI = -r;
  const dx = Math.cos(rAI)*900, dy = Math.sin(rAI)*900;
  const hx = acx - Math.sin(rAI)*pitchYOff;
  const hy = acy - Math.cos(rAI)*pitchYOff;

  // Sky (blue)
  ctx.fillStyle='#1a74c4';
  ctx.fillRect(ax,ay,aw,ah);
  // Horizon fill — sky polygon
  ctx.beginPath();
  ctx.moveTo(hx-dx,hy+dy); ctx.lineTo(hx+dx,hy-dy);
  ctx.lineTo(hx+dx-dy*2,hy-dy-dx*2); ctx.lineTo(hx-dx-dy*2,hy+dy-dx*2);
  ctx.closePath(); ctx.fillStyle='#1a74c4'; ctx.fill();
  // Ground (brown)
  ctx.beginPath();
  ctx.moveTo(hx-dx,hy+dy); ctx.lineTo(hx+dx,hy-dy);
  ctx.lineTo(hx+dx+dy*2,hy-dy+dx*2); ctx.lineTo(hx-dx+dy*2,hy+dy+dx*2);
  ctx.closePath(); ctx.fillStyle='#7a4a1e'; ctx.fill();

  // Horizon line (white, thick)
  ctx.beginPath(); ctx.moveTo(hx-dx,hy+dy); ctx.lineTo(hx+dx,hy-dy);
  ctx.strokeStyle='#fff'; ctx.lineWidth=2.5; ctx.stroke();

  // Pitch ladder — positive deg = sky side (above center), negative = ground side
  for(let deg=-30; deg<=30; deg+=5){
    if(deg===0) continue;
    // +deg = sky side = above horizon = positive offset upward (negated pitchYOff convention)
    const so = deg * pitchScale;
    const lhx = hx - Math.sin(rAI)*so, lhy = hy - Math.cos(rAI)*so;
    const isMajor = deg%10===0;
    const len = isMajor ? 62 : (deg%5===0 ? 35 : 20);
    const lx1 = lhx - Math.cos(rAI)*len, ly1 = lhy + Math.sin(rAI)*len;
    const lx2 = lhx + Math.cos(rAI)*len, ly2 = lhy - Math.sin(rAI)*len;
    ctx.beginPath(); ctx.moveTo(lx1,ly1); ctx.lineTo(lx2,ly2);
    ctx.strokeStyle='#fff'; ctx.lineWidth=isMajor?2:1.2; ctx.stroke();
    if(isMajor){
      // End caps: sky lines cap toward horizon (downward), ground lines cap upward
      const capLen=8, capDir=deg>0?1:-1;
      ctx.beginPath(); ctx.moveTo(lx1,ly1); ctx.lineTo(lx1+Math.sin(rAI)*capDir*capLen, ly1+Math.cos(rAI)*capDir*capLen); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(lx2,ly2); ctx.lineTo(lx2+Math.sin(rAI)*capDir*capLen, ly2+Math.cos(rAI)*capDir*capLen); ctx.stroke();
      // Labels (rotate with AI tilt)
      ctx.save();
      ctx.translate(lx1-Math.cos(rAI)*22, ly1+Math.sin(rAI)*22);
      ctx.rotate(rAI);
      ctx.fillStyle='#fff'; ctx.font='bold 12px Arial'; ctx.textAlign='center'; ctx.textBaseline='middle';
      ctx.fillText(Math.abs(deg),0,0);
      ctx.restore();
      ctx.save();
      ctx.translate(lx2+Math.cos(rAI)*22, ly2-Math.sin(rAI)*22);
      ctx.rotate(rAI);
      ctx.fillStyle='#fff'; ctx.font='bold 12px Arial'; ctx.textAlign='center'; ctx.textBaseline='middle';
      ctx.fillText(Math.abs(deg),0,0);
      ctx.restore();
    }
  }
}

// ---- FLIGHT DIRECTOR ----
function drawFlightDirector(acx, acy, p, roll){
  // Magenta FD bars — command pitch up/down and roll
  // Simplified: FD commands level flight (0 pitch, 0 roll)
  // W → p negative → p*3.5 negative → acy + negative = bar moves UP (sky side) ✓
  const fdPitchErr = p * 3.5;
  const fdRollErr  = roll * 2.2;  // D (right bank) → vertical bar moves right

  ctx.save();
  ctx.strokeStyle='#cc44cc'; ctx.lineWidth=4; ctx.lineCap='butt';

  // Horizontal bar (pitch command) — wide bar
  ctx.beginPath();
  ctx.moveTo(acx-80, acy+fdPitchErr);
  ctx.lineTo(acx+80, acy+fdPitchErr);
  ctx.stroke();

  // Vertical bar (roll command) — tall bar
  ctx.beginPath();
  ctx.moveTo(acx+fdRollErr, acy-60);
  ctx.lineTo(acx+fdRollErr, acy+60);
  ctx.stroke();
  ctx.restore();
}

// ---- AIRCRAFT SYMBOL ----
function drawAircraftSymbol(acx, acy){
  ctx.save();
  ctx.strokeStyle='#fff'; ctx.lineWidth=3; ctx.lineCap='round';
  // Left wing
  ctx.beginPath(); ctx.moveTo(acx-65,acy); ctx.lineTo(acx-22,acy); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(acx-22,acy); ctx.lineTo(acx-22,acy+10); ctx.stroke();
  // Right wing
  ctx.beginPath(); ctx.moveTo(acx+65,acy); ctx.lineTo(acx+22,acy); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(acx+22,acy); ctx.lineTo(acx+22,acy+10); ctx.stroke();
  // Center dot
  ctx.fillStyle='#fff';
  ctx.beginPath(); ctx.arc(acx,acy,4,0,Math.PI*2); ctx.fill();
  // Small center box (737 style)
  ctx.strokeStyle='#fff'; ctx.lineWidth=2;
  ctx.strokeRect(acx-5,acy-5,10,10);
  ctx.restore();
}

// ---- BANK ARC ----
function drawBankArc(acx, acy, aiy, roll){
  const arcR = 190;
  const arcCY = acy; // centered vertically on AI center

  ctx.save();
  // Arc ticks
  for(const deg of [-60,-45,-30,-20,-10,0,10,20,30,45,60]){
    const rad=(deg-90)*Math.PI/180;
    const tx=acx+Math.cos(rad)*arcR, ty=arcCY+Math.sin(rad)*arcR;
    const len=deg%30===0?16:(deg%10===0?10:7);
    const bx=acx+Math.cos(rad)*(arcR-len), by=arcCY+Math.sin(rad)*(arcR-len);
    ctx.beginPath(); ctx.moveTo(tx,ty); ctx.lineTo(bx,by);
    ctx.strokeStyle='#fff'; ctx.lineWidth=deg%30===0?2:1.2; ctx.stroke();
    if(Math.abs(deg)===30||Math.abs(deg)===60||deg===0){
      const lbl=deg===0?'':Math.abs(deg);
      if(lbl){
        ctx.fillStyle='#bbb'; ctx.font='10px Arial'; ctx.textAlign='center';
        ctx.fillText(lbl, acx+Math.cos(rad)*(arcR-26), arcCY+Math.sin(rad)*(arcR-26)+3);
      }
    }
  }

  // Moving roll pointer — negate roll so D (right bank) moves pointer to the right
  const rollRad=(-roll-90)*Math.PI/180;
  const px=acx+Math.cos(rollRad)*arcR, py=arcCY+Math.sin(rollRad)*arcR;
  const pax=Math.cos(rollRad), pay=Math.sin(rollRad);
  ctx.beginPath();
  ctx.moveTo(px,py);
  ctx.lineTo(px-pax*14+pay*8,py-pay*14-pax*8);
  ctx.lineTo(px-pax*14-pay*8,py-pay*14+pax*8);
  ctx.closePath(); ctx.fillStyle='#ffdd00'; ctx.fill();

  // Fixed triangle at top (reference)
  ctx.beginPath();
  ctx.moveTo(acx,arcCY-arcR+2);
  ctx.lineTo(acx-8,arcCY-arcR+16);
  ctx.lineTo(acx+8,arcCY-arcR+16);
  ctx.closePath(); ctx.strokeStyle='#fff'; ctx.lineWidth=1.5; ctx.stroke();

  ctx.restore();
}

// ---- LOCALIZER SCALE (bottom of AI) ----
function drawLocalizerScale(ax, ay, aw, ah, acx, acy, locDev){
  const scaleY = ay+ah-28;
  const dotSpacing = 55; // px per dot
  const maxDots = 2;

  ctx.save();
  // Scale background strip (subtle)
  ctx.fillStyle='rgba(0,0,0,0.25)'; ctx.fillRect(acx-dotSpacing*2.5-8, scaleY-10, dotSpacing*5+16, 20);

  // Dot markers
  for(let d=-2;d<=2;d++){
    if(d===0) continue;
    const x=acx+d*dotSpacing;
    ctx.beginPath(); ctx.arc(x,scaleY,5,0,Math.PI*2);
    ctx.fillStyle='rgba(255,255,255,0.7)'; ctx.fill();
  }
  // Center line (small tick)
  ctx.beginPath(); ctx.moveTo(acx,scaleY-8); ctx.lineTo(acx,scaleY+8);
  ctx.strokeStyle='rgba(255,255,255,0.5)'; ctx.lineWidth=1.5; ctx.stroke();

  // LOC diamond (magenta)
  const locX = Math.max(acx-dotSpacing*2, Math.min(acx+dotSpacing*2, acx+locDev*dotSpacing));
  ctx.beginPath();
  ctx.moveTo(locX,scaleY-8); ctx.lineTo(locX+7,scaleY);
  ctx.lineTo(locX,scaleY+8); ctx.lineTo(locX-7,scaleY);
  ctx.closePath();
  ctx.strokeStyle='#cc44cc'; ctx.lineWidth=2.5; ctx.stroke();

  // LOC label
  ctx.fillStyle='#00cc00'; ctx.font='bold 10px Arial'; ctx.textAlign='left';
  ctx.fillText('LOC', ax+8, scaleY+4);
  ctx.restore();
}

// ---- GLIDESLOPE SCALE (right of AI) ----
function drawGlideslopeScale(ax, ay, aw, ah, acx, acy, gsDev){
  const scaleX = ax+aw-28;
  const dotSpacing = 50;

  ctx.save();
  // Dot markers
  for(let d=-2;d<=2;d++){
    if(d===0) continue;
    const y=acy+d*dotSpacing;
    ctx.beginPath(); ctx.arc(scaleX,y,5,0,Math.PI*2);
    ctx.fillStyle='rgba(255,255,255,0.7)'; ctx.fill();
  }
  // Center tick
  ctx.beginPath(); ctx.moveTo(scaleX-8,acy); ctx.lineTo(scaleX+8,acy);
  ctx.strokeStyle='rgba(255,255,255,0.5)'; ctx.lineWidth=1.5; ctx.stroke();

  // GS diamond (magenta)
  const gsY = Math.max(acy-dotSpacing*2, Math.min(acy+dotSpacing*2, acy-gsDev*dotSpacing));
  ctx.beginPath();
  ctx.moveTo(scaleX,gsY-8); ctx.lineTo(scaleX+8,gsY);
  ctx.lineTo(scaleX,gsY+8); ctx.lineTo(scaleX-8,gsY);
  ctx.closePath();
  ctx.strokeStyle='#cc44cc'; ctx.lineWidth=2.5; ctx.stroke();

  // GS label
  ctx.fillStyle='#00cc00'; ctx.font='bold 10px Arial'; ctx.textAlign='left';
  ctx.fillText('GS', scaleX-8, ay+16);
  ctx.restore();
}

// ---- AIRSPEED TAPE ----
function drawAirspeedTape(tx, ty, tw, th, curSpd, selSpd, vsiVal){
  const tcx=tx+tw/2, tcy=ty+th/2;
  ctx.fillStyle='#222830'; ctx.fillRect(tx,ty,tw,th);
  ctx.strokeStyle='#3a3f4a'; ctx.lineWidth=1; ctx.strokeRect(tx,ty,tw,th);

  // Tape background
  ctx.fillStyle='#1a1e28'; ctx.fillRect(tx+2,ty+2,tw-4,th-4);

  // Speed markings
  clipRect(tx+2,ty+2,tw-4,th-4,()=>{
    const pxPerKt=3.5;
    for(let s=Math.max(0,curSpd-80);s<=curSpd+80;s++){
      const yp=tcy+(curSpd-s)*pxPerKt;
      if(yp<ty||yp>ty+th) continue;
      if(s%10===0){
        ctx.beginPath(); ctx.moveTo(tx+tw-22,yp); ctx.lineTo(tx+tw-4,yp);
        ctx.strokeStyle='#ccc'; ctx.lineWidth=1.5; ctx.stroke();
        ctx.fillStyle='#ddd'; ctx.font='bold 17px Arial'; ctx.textAlign='right';
        ctx.fillText(s, tx+tw-26, yp+4);
      } else if(s%5===0){
        ctx.beginPath(); ctx.moveTo(tx+tw-14,yp); ctx.lineTo(tx+tw-4,yp);
        ctx.strokeStyle='#666'; ctx.lineWidth=1; ctx.stroke();
      }
    }
    // Green REF speed bar (VREF)
    const vrefSpd=99999; // IS152: drona ozgu VREF yok, gizli
    const vrefY=tcy+(curSpd-vrefSpd)*pxPerKt;
    if(vrefY>ty&&vrefY<ty+th){
      ctx.beginPath(); ctx.moveTo(tx+4,vrefY); ctx.lineTo(tx+tw-4,vrefY);
      ctx.strokeStyle='#00cc00'; ctx.lineWidth=2; ctx.setLineDash([4,3]); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle='#00cc00'; ctx.font='bold 9px Arial'; ctx.textAlign='left';
      ctx.fillText('REF',tx+4,vrefY-2);
    }
    // Speed trend arrow (magenta)
    const trendPx=vsiVal*0.008*pxPerKt;
    if(Math.abs(trendPx)>5){
      ctx.beginPath(); ctx.moveTo(tx+tw-10,tcy); ctx.lineTo(tx+tw-10,tcy-trendPx);
      ctx.strokeStyle='#cc44cc'; ctx.lineWidth=2; ctx.stroke();
    }
  });

  // Selected speed bug (magenta) on tape edge
  const selY=tcy+(curSpd-selSpd)*3.5;
  if(selY>ty&&selY<ty+th){
    ctx.fillStyle='#cc44cc';
    ctx.beginPath(); ctx.moveTo(tx+tw,selY); ctx.lineTo(tx+tw-14,selY-8); ctx.lineTo(tx+tw-14,selY+8); ctx.closePath(); ctx.fill();
  }

  // Current speed box (amber/white outline) — IS154: anlik deger buyutuldu
  ctx.fillStyle='#0d1018'; ctx.fillRect(tx,tcy-26,tw,52);
  ctx.strokeStyle='#e5c842'; ctx.lineWidth=2.5; ctx.strokeRect(tx,tcy-26,tw,52);
  ctx.fillStyle='#e5c842'; ctx.font='bold 38px Arial'; ctx.textAlign='center';
  ctx.fillText(curSpd, tcx, tcy+13);

  // Selected speed readout (magenta, top)
  ctx.fillStyle='#1a1e28'; ctx.fillRect(tx,ty,tw,26);
  ctx.fillStyle='#cc44cc'; ctx.font='bold 16px Arial'; ctx.textAlign='center';
  ctx.fillText(selSpd, tcx, ty+18);

  // Labels
  ctx.fillStyle='#555a64'; ctx.font='bold 26px Arial'; ctx.textAlign='center';
  ctx.fillText('m/s', tcx, ty+th-8);

  // Yer hizi (m/s) altta
  ctx.fillStyle='#00cc00'; ctx.font='bold 11px Arial'; ctx.textAlign='left';
  ctx.fillText('YER '+curSpd, tx+2, ty+th+16);
}

// ---- ALTIMETER TAPE ----
function drawAltimeterTape(tx, ty, tw, th, curAlt, vsiVal){
  const tcx=tx+tw/2, tcy=ty+th/2;
  ctx.fillStyle='#222830'; ctx.fillRect(tx,ty,tw,th);
  ctx.strokeStyle='#3a3f4a'; ctx.lineWidth=1; ctx.strokeRect(tx,ty,tw,th);
  ctx.fillStyle='#1a1e28'; ctx.fillRect(tx+2,ty+2,tw-4,th-4);

  clipRect(tx+2,ty+2,tw-4,th-4,()=>{
    // IS152: metrik olcek — ana adim 50 m, ara adim 10 m
    const pxPerM=0.55;
    const base=Math.round(curAlt/50)*50;
    for(let a=base-800;a<=base+800;a+=50){
      if(a<0) continue;
      const yp=tcy+(curAlt-a)*pxPerM;
      if(yp<ty||yp>ty+th) continue;
      ctx.beginPath(); ctx.moveTo(tx+4,yp); ctx.lineTo(tx+20,yp);
      ctx.strokeStyle='#ccc'; ctx.lineWidth=1.5; ctx.stroke();
      ctx.fillStyle='#ddd'; ctx.font='bold 17px Arial'; ctx.textAlign='left';
      ctx.fillText(a,tx+22,yp+4);
    }
    for(let a=base-800;a<=base+800;a+=10){
      if(a<0) continue;
      const yp=tcy+(curAlt-a)*pxPerM;
      if(yp<ty||yp>ty+th) continue;
      if(a%50!==0){
        ctx.beginPath(); ctx.moveTo(tx+4,yp); ctx.lineTo(tx+12,yp);
        ctx.strokeStyle='#666'; ctx.lineWidth=1; ctx.stroke();
      }
    }
  });

  // Current alt box — IS154: tek buyuk okunur deger (metre)
  ctx.fillStyle='#0d1018'; ctx.fillRect(tx,tcy-26,tw,52);
  ctx.strokeStyle='#e5c842'; ctx.lineWidth=2.5; ctx.strokeRect(tx,tcy-26,tw,52);
  ctx.fillStyle='#e5c842'; ctx.font='bold 34px Arial'; ctx.textAlign='center';
  ctx.fillText(curAlt, tcx, tcy+12);

  // IS152: secili irtifa (demo) ve baro ayari drona ozgu degil, kaldirildi.
  ctx.fillStyle='#555a64'; ctx.font='bold 26px Arial'; ctx.textAlign='center';
  ctx.fillText('İRT m', tcx, ty+th-8);
}

// ---- VSI (Vertical Speed Indicator) ----
function drawVSI(tx, ty, tw, th, vsiVal){
  // IS152: metrik dikey hiz (m/s), olcek +/-10 m/s
  const VMAK = 10;
  const tw2 = tw;
  const mid = ty + th/2;
  const clampedVsi = Math.max(-VMAK, Math.min(vsiVal, VMAK));

  // Background panel
  ctx.fillStyle='#141820'; ctx.fillRect(tx, ty, tw2, th);
  ctx.strokeStyle='#2e3340'; ctx.lineWidth=1.5; ctx.strokeRect(tx, ty, tw2, th);

  // Title (rotated to fit narrow column)
  ctx.save();
  ctx.translate(tx+tw2/2, ty+18);
  ctx.fillStyle='#6a7a8a'; ctx.font='bold 8px Arial'; ctx.textAlign='center';
  ctx.fillText('DH', 0, 0);
  ctx.restore();

  // Non-linear scale mapping (m/s)
  function vsiToY(v) {
    const sign = v >= 0 ? -1 : 1;
    const abs = Math.min(Math.abs(v), VMAK);
    const frac = abs <= VMAK/2
      ? (abs / (VMAK/2)) * 0.45
      : 0.45 + ((abs - VMAK/2) / (VMAK/2)) * 0.42;
    return mid + sign * frac * th * 0.5;
  }

  // Scale ticks (m/s)
  const scaleMarks = [
    { v:  10, lbl:'10' }, { v:  7.5, lbl:'' }, { v:  5, lbl:'5' },
    { v:  2.5, lbl:'' },  { v:  0, lbl:'0' },  { v: -2.5, lbl:'' },
    { v: -5, lbl:'5' },   { v: -7.5, lbl:'' }, { v: -10, lbl:'10' }
  ];
  for(const mark of scaleMarks){
    const yp = vsiToY(mark.v);
    const isMaj = mark.lbl !== '';
    if(mark.v === 0){
      ctx.beginPath(); ctx.moveTo(tx+4,yp); ctx.lineTo(tx+tw2-4,yp);
      ctx.strokeStyle='#6a7a8a'; ctx.lineWidth=1.5; ctx.stroke();
    } else {
      const tickW = isMaj ? tw2*0.5 : tw2*0.28;
      ctx.beginPath(); ctx.moveTo(tx+tw2-tickW, yp); ctx.lineTo(tx+tw2-4, yp);
      ctx.strokeStyle = isMaj ? '#b0b8c8' : '#404858';
      ctx.lineWidth = isMaj ? 1.8 : 1; ctx.stroke();
      if(isMaj){
        ctx.fillStyle='#9aa0b0'; ctx.font='bold 9px Arial'; ctx.textAlign='right';
        ctx.fillText(mark.lbl, tx+tw2-tickW-2, yp+3);
      }
    }
  }

  // Colored bar from zero to needle
  const needleY = vsiToY(clampedVsi);
  const barColor = clampedVsi > 0 ? '#00bb55' : clampedVsi < 0 ? '#dd6600' : '#445566';
  if(Math.abs(clampedVsi) > 0.3){
    ctx.fillStyle = barColor + '44';
    ctx.fillRect(tx+tw2*0.62, Math.min(mid,needleY), tw2*0.28, Math.abs(mid-needleY)||1);
    ctx.fillStyle = barColor;
    ctx.fillRect(tx+tw2*0.62, clampedVsi>0?needleY:needleY-2, tw2*0.28, 2);
  }

  // Needle line + arrowhead
  const needleColor = clampedVsi > 1 ? '#00cc55' : clampedVsi < -1 ? '#ee7700' : '#e0e0e0';
  ctx.save();
  ctx.beginPath(); ctx.moveTo(tx+4, needleY); ctx.lineTo(tx+tw2-10, needleY);
  ctx.strokeStyle=needleColor; ctx.lineWidth=2.5; ctx.lineCap='round'; ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(tx+tw2-2, needleY);
  ctx.lineTo(tx+tw2-13, needleY-6);
  ctx.lineTo(tx+tw2-13, needleY+6);
  ctx.closePath(); ctx.fillStyle=needleColor; ctx.fill();
  ctx.restore();

  // Sayisal kutu (m/s)
  if(Math.abs(vsiVal) > 0.3){
    const boxH=18, boxW=tw2-4;
    const boxY = clampedVsi>=0 ? needleY-boxH-4 : needleY+4;
    const clampedBoxY = Math.max(ty+30, Math.min(ty+th-boxH-4, boxY));
    ctx.fillStyle='#0a0e14'; ctx.fillRect(tx+2, clampedBoxY, boxW, boxH);
    ctx.strokeStyle=needleColor; ctx.lineWidth=1.2; ctx.strokeRect(tx+2, clampedBoxY, boxW, boxH);
    ctx.fillStyle=needleColor; ctx.font='bold 12px Arial'; ctx.textAlign='center';
    ctx.fillText((vsiVal>0?'+':'')+vsiVal.toFixed(1), tx+tw2/2, clampedBoxY+13);
  }
}

// ---- HEADING COMPASS ARC ----
function drawHeadingCompass(acx, compY, aiw, curHdg){
  const compW=aiw+20, compH=86;   // IS154: daha yuksek (buyuk fontlar)
  const cx=acx, compX=acx-compW/2;

  ctx.fillStyle='#1a1e28'; ctx.fillRect(compX,compY,compW,compH);
  ctx.strokeStyle='#2e3340'; ctx.lineWidth=1; ctx.strokeRect(compX,compY,compW,compH);

  clipRect(compX+2,compY+2,compW-4,compH-4,()=>{
    const pxPerDeg=8;   // IS154: tikler yayilir, genis cetveldeki bosluk dolar
    for(let h=Math.floor(curHdg)-60;h<=Math.floor(curHdg)+60;h++){
      let nh=((h%360)+360)%360; if(nh===0)nh=360;
      const xp=cx+(h-curHdg)*pxPerDeg;
      if(xp<compX||xp>compX+compW) continue;
      if(nh%5===0){
        ctx.beginPath(); ctx.moveTo(xp,compY+2); ctx.lineTo(xp,compY+(nh%10===0?24:14));
        ctx.strokeStyle=nh%10===0?'#ccc':'#555'; ctx.lineWidth=nh%10===0?2:1; ctx.stroke();
      }
      if(nh%10===0){
        let lbl=String(Math.floor(nh/10));
        if(nh===360||nh===0) lbl='K'; else if(nh===90) lbl='D';
        else if(nh===180) lbl='G'; else if(nh===270) lbl='B';
        const isCard=['K','D','G','B'].includes(lbl);
        ctx.fillStyle=isCard?'#00cc00':'#ccc';
        ctx.font=isCard?'bold 21px Arial':'bold 16px Arial';   // IS154: buyuk
        ctx.textAlign='center'; ctx.fillText(lbl,xp,compY+48);
      }
    }
  });

  // Heading pointer (triangle above compass)
  ctx.beginPath(); ctx.moveTo(cx,compY+2); ctx.lineTo(cx-7,compY-8); ctx.lineTo(cx+7,compY-8);
  ctx.closePath(); ctx.fillStyle='#ffdd00'; ctx.fill();

  // Heading readout box — IS155: pusula etiketleriyle ayni font (16px), tam ortali
  ctx.fillStyle='#0d1018'; ctx.fillRect(cx-32,compY+compH-30,64,25);
  ctx.strokeStyle='#ffdd00'; ctx.lineWidth=1.5; ctx.strokeRect(cx-32,compY+compH-30,64,25);
  ctx.fillStyle='#ffdd00'; ctx.font='bold 16px Arial'; ctx.textAlign='center';
  ctx.fillText(String(Math.round(curHdg)%360).padStart(3,'0')+'°', cx, compY+compH-12);

  // MANYETIK etiketi
  ctx.fillStyle='#00cc00'; ctx.font='bold 12px Arial'; ctx.textAlign='center';
  ctx.fillText('MANYETİK', cx, compY+compH+16);
  // IS154: sabit "secili heading" (demo) kaldirildi (drona ozgu degil).
}

// ---- MISC OVERLAYS ----
function drawMiscOverlays(ax, ay, aw, ah, curAlt, curSpd, curHdg, locDev, gsDev){
  const AI_CX=ax+aw/2;

  // IPOS / Radio information (top left of AI area)
  ctx.fillStyle='#fff'; ctx.font='bold 10px Arial'; ctx.textAlign='left';
  ctx.fillText('IPOS/104°', ax+12, ay+20);
  ctx.fillStyle='#ccc'; ctx.font='10px Arial';
  ctx.fillText('DME  ---', ax+12, ay+34);
  ctx.fillStyle='#00cc00'; ctx.font='bold 10px Arial';
  ctx.fillText('LNAV/VNAV', ax+12, ay+50);

  // Radio altimeter (bottom center, green)
  if(curAlt<2500){
    const raAlt=Math.max(0,Math.round(curAlt-500)); // simplified RA
    ctx.fillStyle='rgba(0,0,0,0.6)'; ctx.fillRect(AI_CX-30,ay+ah-50,60,22);
    ctx.fillStyle='#00cc00'; ctx.font='bold 14px Arial'; ctx.textAlign='center';
    ctx.fillText(raAlt, AI_CX, ay+ah-35);
    ctx.fillStyle='#00cc00'; ctx.font='9px Arial';
    ctx.fillText('RA', AI_CX, ay+ah-25);
  }

  // LOC/GS deviation readout (text, top right corner of AI)
  const locPx=Math.abs(locDev)*55;
  const gsPx=Math.abs(gsDev)*50;
  ctx.fillStyle='rgba(0,0,0,0.5)'; ctx.fillRect(ax+aw-95,ay+4,88,44);
  ctx.fillStyle=locPx>90?'#ffaa00':'#cc44cc'; ctx.font='bold 9px Arial'; ctx.textAlign='left';
  ctx.fillText('LOC '+(locDev>=0?'R':'L')+Math.abs(locDev).toFixed(1), ax+aw-90, ay+17);
  ctx.fillStyle=gsPx>90?'#ffaa00':'#cc44cc'; ctx.font='bold 9px Arial';
  ctx.fillText('G/S '+(gsDev>=0?'+':'')+gsDev.toFixed(1), ax+aw-90, ay+32);

  // Turn rate indicator (slip/skid ball — moves opposite to yaw: Z=left yaw, ball goes right)
  const ballX = AI_CX + yawDeg*2.5;
  ctx.beginPath(); ctx.arc(Math.max(AI_CX-22,Math.min(AI_CX+22,ballX)), ay+ah+82, 7, 0, Math.PI*2);
  ctx.fillStyle='#fff'; ctx.fill();
  ctx.strokeStyle='#999'; ctx.lineWidth=1; ctx.stroke();
  ctx.beginPath(); ctx.moveTo(AI_CX-24,ay+ah+75); ctx.lineTo(AI_CX-24,ay+ah+89);
  ctx.strokeStyle='#fff'; ctx.lineWidth=1.5; ctx.stroke();
  ctx.beginPath(); ctx.moveTo(AI_CX+24,ay+ah+75); ctx.lineTo(AI_CX+24,ay+ah+89);
  ctx.strokeStyle='#fff'; ctx.lineWidth=1.5; ctx.stroke();

  // DH / MDA (decision height) readout (right side above alt tape)
  ctx.fillStyle='#cc44cc'; ctx.font='bold 11px Arial'; ctx.textAlign='right';
  ctx.fillText('427ᴹ', ax+aw+128, ay-8);
  ctx.fillStyle='#cc44cc'; ctx.font='bold 20px Arial';
  ctx.fillText('1 400', ax+aw+128, ay+14);

  // Marker beacon area (top center of AI) — outer/middle/inner
  ctx.fillStyle='rgba(255,255,255,0.12)'; ctx.fillRect(AI_CX-24,ay+4,48,28);
  ctx.strokeStyle='#555'; ctx.lineWidth=0.8; ctx.strokeRect(AI_CX-24,ay+4,48,28);
  ctx.fillStyle='#888'; ctx.font='9px Arial'; ctx.textAlign='center';
  ctx.fillText('5.2', AI_CX, ay+14);
  // Small circular DME arc
  ctx.beginPath(); ctx.arc(AI_CX+14,ay+17,8,Math.PI*1.25,Math.PI*0.25); 
  ctx.strokeStyle='#aaa'; ctx.lineWidth=1.5; ctx.stroke();
}

  // ---- kamu: telemetriyi PFD durumuna cevir ----
  function telemetriDurum(d){
    d = d || {};
    // IS156: ARM/hazirlik durumu (arm_check.js dkHazirRozetTazele mantiginin ozeti)
    var h = d.hazirlik || {};
    var armMetin, armRenk;
    if (!d.baglanti) { armMetin = "BAĞLANTI YOK"; armRenk = "#ff5d5d"; }
    else if (d.armed) { armMetin = "ARM · UÇUŞTA"; armRenk = "#00e676"; }
    else if (h.hazir === true) { armMetin = "UÇUŞA HAZIR"; armRenk = "#00e676"; }
    else if (h.hazir === false) { armMetin = "HAZIR DEĞİL"; armRenk = "#ffb020"; }
    else { armMetin = "DURUM BEKLENİYOR"; armRenk = "#c2cbd6"; }
    var spdMs = (typeof d.groundspeed === "number") ? d.groundspeed : 0;
    var altM  = (typeof d.alt_rel === "number") ? d.alt_rel : 0;
    var vzMs  = (typeof d.vz === "number") ? d.vz : 0;   // + asagi (NED)
    return {
      pitch: (typeof d.pitch === "number") ? d.pitch : 0,
      roll:  (typeof d.roll === "number") ? d.roll : 0,
      hdg:   (typeof d.heading === "number") ? d.heading : 0,
      spd:   Math.round(spdMs),                    // m/s (metrik)
      alt:   Math.round(altM),                      // m (metrik)
      vsi:   Math.round((-vzMs) * 10) / 10,        // m/s (yukari +), 1 ondalik
      selspd: Math.round(spdMs),
      mod:   (d.mod || "").toString().toUpperCase(),
      armMetin: armMetin, armRenk: armRenk,
      gpsFix: (typeof d.gps_fix === "number") ? d.gps_fix : null,
      gpsUydu: (typeof d.uydu === "number") ? d.uydu : null,
    };
  }

  // ---- kamu: canvas'a ciz ----
  function ciz(canvas, st){
    if (!canvas) return;
    var c = canvas.getContext("2d");
    if (!c) return;
    var dpr = window.devicePixelRatio || 1;
    var cw = canvas.clientWidth || canvas.width || 320;
    var ch = Math.round(cw * H / W);
    // CSS yukseklik oranini koru
    if (canvas.style) canvas.style.height = ch + "px";
    var bw = Math.round(cw * dpr), bh = Math.round(ch * dpr);
    if (canvas.width !== bw || canvas.height !== bh){ canvas.width = bw; canvas.height = bh; }
    var s = bw / W;
    // IS153: gunduz temasinda renk eslemeli baglam kullan
    var acikTema = false;
    try { acikTema = document.documentElement.getAttribute("data-tema") === "acik"; } catch (e) {}
    ctx = acikTema ? temaCtx(c) : c;
    _mod = st.mod || "";
    _arm = st.armMetin || ""; _armRenk = st.armRenk || "#c2cbd6";
    _gpsFix = (typeof st.gpsFix === "number") ? st.gpsFix : null;
    _gpsUydu = (typeof st.gpsUydu === "number") ? st.gpsUydu : null;
    ctx.setTransform(s, 0, 0, s, 0, 0);
    // arka plan
    ctx.fillStyle = "#1a1c22"; ctx.fillRect(0, 0, W, H);
    var r = (st.roll || 0) * Math.PI / 180;
    // ILS sapmalari drona ozgu degil -> 0 (localizer/glideslope ortada durur)
    drawPFD(st.pitch || 0, st.roll || 0, r, st.spd || 0, st.alt || 0,
            st.hdg || 0, st.vsi || 0, st.selspd || (st.spd || 0), 0, 0);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  return { ciz: ciz, telemetriDurum: telemetriDurum,
           gpsKutuAlani: function () { return _gpsKutu; },
           modKutuAlani: function () { return _modKutu; },
           armKutuAlani: function () { return _armKutu; },
           islemKutuAlani: function () { return _islemKutu; } };
})();
