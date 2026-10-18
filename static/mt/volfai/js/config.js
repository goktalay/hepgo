// VOLFAI - oyun sabitleri
export const GRID_W = 80;      // hücre (yatay)
export const GRID_H = 120;     // hücre (dikey)

export const CELL = {
  EMPTY: 0,      // sahipsiz (düşman bölgesi)
  CLAIMED: 1,    // ele geçirilmiş
  TRAIL: 2,      // çizilmekte olan hat
  BLOCK: 3,      // güç kutusu (içinden çizilemez)
};

export const CLEAR_PERCENT = 80;         // Volfied: en az %80
export const BASE_PLAYER_SPEED = 34;     // hücre/sn
export const SPEED_BOOST_MULT = 1.7;
export const FUSE_SPEED_RATIO = 0.85;    // fitil hızı / oyuncu hızı
export const LIVES_START = 3;

export const POWERUPS = {
  S: { name: 'HIZ',        duration: 12, weight: 24, color: '#ffd23f' },
  T: { name: 'DONDUR',     duration: 6,  weight: 20, color: '#5de4ff' },
  L: { name: 'LAZER',      duration: 10, weight: 22, color: '#ff5d8f' },
  P: { name: 'KALKAN',     duration: 0,  weight: 18, color: '#9bff8a' },
  E: { name: 'EK CAN',     duration: 0,  weight: 5,  color: '#ffffff' },
  B: { name: 'BONUS',      duration: 0,  weight: 11, color: '#ffa94d' },
};

export const SCORE = {
  PER_CELL: 10,
  BIG_AREA_MULT: 2,        // tek seferde >%20 alan
  BIG_AREA_THRESHOLD: 0.20,
  SMALL_ENEMY: 500,
  BOSS_HIT: 100,
  SPECIAL_CLEAR: 50000,
  ALL_BLOCKS: 20000,
  PER_PERCENT_OVER: 1000,
  PER_SECOND_LEFT: 50,
  BONUS_BOX: 2500,
};

// ---- Kampanya: 30 bölüm, her bölümde 5-10 parkur ----
export const LEVEL_COUNT = 30;
export const PARKUR_MIN = 5;
export const PARKUR_MAX = 10;

// Onur puanı: parkur bitirince kazanılır; bir sonraki bölümün kilidini açmak için gerekir
export const HONOR = {
  CLEAR: 10,            // parkuru bitirmek
  PER_PERCENT_OVER: 1,  // %80 üstü her yüzde (en fazla 20)
  SPECIAL: 10,          // boss'u lazerle yok etmek
  NO_DEATH: 5,          // hiç can kaybetmeden
  PER_PARKUR_REQUIRED: 15, // sonraki bölüm için parkur başına gereken onur
};

// HEPCOIN
export const COIN = {
  SPAWN_MIN: 5,    // sn
  SPAWN_MAX: 11,
  MAX_ON_FIELD: 3,
  LIFETIME: 14,    // sn, sonra kaybolur
  VALUES: [1, 1, 1, 2, 2, 3, 5],
};

// Hangar yükseltmeleri (HEPCOIN ile)
export const UPGRADES = {
  engine:  { name: 'İYON MOTORU',       desc: 'Gemi hızı +%8 / seviye',            icon: '⚡', costs: [60, 140, 280] },
  shield:  { name: 'KALKAN JENERATÖRÜ', desc: 'Parkura kalkanla başla; 3. seviyede 2 kalkan', icon: '🛡', costs: [80, 180, 340] },
  laser:   { name: 'LAZER ÇEKİRDEĞİ',   desc: 'Lazer süresi +3 sn / seviye, hasar artar', icon: '🔺', costs: [70, 160, 300] },
  cells:   { name: 'YEDEK GÜÇ HÜCRESİ', desc: 'Başlangıç canı +1 / seviye',        icon: '♥', costs: [100, 220, 400] },
  time:    { name: 'ZAMAN DİLATÖRÜ',    desc: 'Parkur süresi +15 sn / seviye',     icon: '⏱', costs: [50, 120, 240] },
  magnet:  { name: 'COIN MIKNATISI',    desc: 'HEPCOIN daha sık ve daha değerli düşer', icon: '◎', costs: [90, 200, 360] },
  armor:   { name: 'ZIRH PLAKASI',      desc: 'Gövde dayanımı +1 / seviye (kalkan yokken darbe emer)', icon: '▣', costs: [90, 190, 360] },
  deflector: { name: 'SAPTIRICI',       desc: 'Füze saptırıcı +1 / seviye, 3. seviyede daha hızlı dolum', icon: '◇', costs: [110, 230, 420] },
};

// Gemiler: hız çarpanı, gövde dayanımı (zırh), saptırıcı sayısı, fiyat (HEPCOIN)
export const SHIPS = {
  monotros: { name: 'MONOTROS',  desc: 'Dengeli keşif gemisi. Volfai filosunun klasiği.', speed: 1.00, armor: 2, deflectors: 1, price: 0,   color: '#d8f7ff', glow: '#5de4ff' },
  kirlangic: { name: 'KIRLANGIÇ', desc: 'Çok hızlı, ince gövde. Hata affetmez.',          speed: 1.22, armor: 1, deflectors: 1, price: 250, color: '#ffe9a8', glow: '#ffd23f' },
  kale:     { name: 'KALE',      desc: 'Ağır zırhlı, yavaş. Darbelere dayanır.',            speed: 0.86, armor: 4, deflectors: 2, price: 320, color: '#c9ffd0', glow: '#9bff8a' },
  hayalet:  { name: 'HAYALET',   desc: 'Üç saptırıcı, orta hız. Füzelere karşı en güvenli.', speed: 1.06, armor: 2, deflectors: 3, price: 450, color: '#e6d1ff', glow: '#b48cff' },
};

// Güdümlü füze ve saptırıcı
export const MISSILE = {
  FROM_LEVEL: 4,        // bu bölümden itibaren boss füze atar
  SPEED_MIN: 16, SPEED_MAX: 30,
  TURN_MIN: 1.6, TURN_MAX: 3.4,   // rad/sn dönüş hızı
  LIFE: 7,
  DEFLECT_RANGE: 4.5,   // hücre; saptırıcı bu mesafede füzeyi imha eder
  REGEN_BASE: 25,       // sn; saptırıcı dolum süresi (seviye 3'te 14)
};

// Zorluk seviyeleri: çarpanlar parkur tanımına uygulanır; ödül çarpanı onur ve HEPCOIN'i artırır
export const DIFFICULTY = {
  acemi:    { name: 'ACEMİ',    desc: 'Öğrenmek için. Füzeler 4. bölümden.',                 bossSpeed: 1.15, smallSpeed: 1.15, smalls: 0, shoot: 1.2, shootMin: 0,    time: 1.0,  bossHp: 1.0, missileFrom: 4, fuse: 1.0,  lives: 0,  reward: 1.0, color: '#9bff8a' },
  uzman:    { name: 'UZMAN',    desc: 'Daha hızlı yaratıklar, daha çok düşman, %15 az süre. Ödül ×1.5.', bossSpeed: 1.45, smallSpeed: 1.4, smalls: 2, shoot: 1.8, shootMin: 0.15, time: 0.85, bossHp: 1.3, missileFrom: 2, fuse: 1.15, lives: 0,  reward: 1.5, color: '#ffd23f' },
  kahraman: { name: 'KAHRAMAN', desc: 'Acımasız. Bir can eksik, füzeler ilk bölümden. Ödül ×2.',  bossSpeed: 1.8,  smallSpeed: 1.7, smalls: 4, shoot: 2.6, shootMin: 0.35, time: 0.7,  bossHp: 1.6, missileFrom: 1, fuse: 1.3,  lives: -1, reward: 2.0, color: '#ff5d8f' },
};

// Görünüm: oyun alanı çözünürlüğü (hücre sayısı) ve nesne boyutu çarpanı (Ayarlar)
export const FIELD_SIZES = {
  buyuk:  { name: 'BÜYÜK',  desc: 'İri hücreler, büyük gemi (60×90)',     w: 60,  h: 90 },
  normal: { name: 'NORMAL', desc: 'Varsayılan (80×120)',                   w: 80,  h: 120 },
  ince:   { name: 'İNCE',   desc: 'Daha çok ayrıntı, küçük gemi (100×150)', w: 100, h: 150 },
};
export const SPRITE_SCALES = [1, 1.3, 1.6, 2];

export const TIMER = {
  WARN_AT: 10,          // son 10 sn: tik sesi + uyarı
  OVERTIME: 30,         // süre bitince can gider, bu kadar ek süre verilir (acele modu)
};

// HEPGO bütünleşmesi: oyun HEPGO'nun /static/mt/volfai/ altında aynı kökende sunulur; oturum HEPGO çerezidir (ayrı giriş yok).
// Master Tool hesap servisi (MASTERTOOL / api/vf) bu sürümde kullanılmaz.
export const HEPGO = {
  APP_VERSION: '0.5.0',
  ME_URL: '/api/auth/me',                           // oturumdaki HEPGO kullanıcısı (ad, avatar)
  PROFILE_URL: '/api/tools/volfai/profile',         // GET/PUT oyun profili (vf/profile ile aynı JSON şeması)
  LEADERBOARD_URL: '/api/tools/volfai/leaderboard', // şirket içi skor tablosu
  FILES_URL: '/api/files',                          // avatar: /api/files/<photo>?w=128
  HOME_URL: '/app#/tools',                          // Araçlar ana sayfası
};
