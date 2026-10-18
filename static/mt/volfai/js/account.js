// VOLFAI (HEPGO sürümü) - hesap ve profil saklama
// Master Tool hesap servisi (vf auth ön-giriş/giriş/çıkış + vf profile uçları) yerine HEPGO oturumu kullanılır:
//   Giriş ekranı YOK — oyun HEPGO içinde (aynı köken) açılır, oturum çerezi zaten vardır.
//   GET /api/auth/me                        → kullanıcı (id, full_name/username, photo)
//   GET /api/tools/volfai/profile           → {user:{id,name,photo}, profile: JSON|null, updated_at}   (vf/profile ile aynı şema)
//   PUT /api/tools/volfai/profile {profile} → {ok:true}  (sunucu profili olduğu gibi saklar)
//   GET /api/tools/volfai/leaderboard       → şirket içi skor tablosu
// Yerel kopya (localStorage) gecikme/çevrimdışı için tutulur; sunucu ile mergeProfiles (yüksek değer kazanır) birleştirilir.
import { HEPGO } from './config.js';
import { normalizeProfile, mergeProfiles, emptyProfile } from './profile.js';

const LS_UID = 'volfai.hepgo.uid';            // son görülen HEPGO kullanıcı kimliği (yerel profil anahtarı için)
const lsKey = uid => `volfai.profile.${uid || 'guest'}`;

function lsGet(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* özel mod */ } }

const ERR_TR = {
  401: 'HEPGO oturumun kapanmış; sayfayı yenileyip tekrar giriş yap.',
  403: 'Araçlar modülüne erişim yetkin yok.',
  413: 'Profil çok büyük, sunucuya kaydedilemedi.',
};

export class Account {
  constructor() {
    const uid = lsGet(LS_UID);
    this.session = null;                                   // {user:{id,name,photo}} — /api/auth/me gelince dolar
    this.profile = normalizeProfile(lsGet(lsKey(uid)));    // yerel kopya (son kullanıcı)
    this.syncState = 'idle';                               // idle | syncing | error | ok | expired
    this.listeners = new Set();
    this._saveTimer = null;
    this.ready = this.init();
  }
  get uid() { return this.session?.user?.id || null; }
  get user() { return this.session?.user || null; }
  get isLoggedIn() { return !!this.session; }
  get hasApi() { return true; }                            // HEPGO içinde API her zaman aynı kökende
  get avatarUrl() { const p = this.user?.photo; return p ? `${HEPGO.FILES_URL}/${p}?w=128` : null; }
  onChange(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit() { for (const fn of this.listeners) fn(this); }

  /** HEPGO oturumunu oku, ardından sunucu profilini çek ve yerel kopyayla birleştir. */
  async init() {
    try {
      const me = await this.api(HEPGO.ME_URL);
      const id = String(me.id);
      this.session = { user: { id, name: me.full_name || me.username || 'HEPGO', photo: me.photo || null } };
      if (lsGet(LS_UID) !== id) { lsSet(LS_UID, id); this.profile = normalizeProfile(lsGet(lsKey(id))); }   // başka kullanıcı: onun yerel kopyası
      await this.pullProfile();
    } catch (e) {
      this.syncState = e.status === 401 ? 'expired' : 'error';
    }
    this.emit();
  }

  /** Profili yerel olarak kaydet; HEPGO sunucusuna da (gecikmeli) gönder. */
  save(immediate = false) {
    this.profile.updatedAt = Date.now();
    lsSet(lsKey(this.uid), this.profile);
    if (this.isLoggedIn) {
      clearTimeout(this._saveTimer);
      if (immediate) this.pushProfile();
      else this._saveTimer = setTimeout(() => this.pushProfile(), 1500);
    }
    this.emit();
  }

  async api(url, { method = 'GET', body = null } = {}) {
    const headers = { 'Content-Type': 'application/json' };
    const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : null, credentials: 'same-origin' });
    const text = await res.text();
    let data = null; try { data = text ? JSON.parse(text) : null; } catch (e) { data = { raw: text }; }
    if (!res.ok) {
      const err = new Error(ERR_TR[res.status] || (typeof data?.detail === 'string' && data.detail) || `Sunucu hatası (${res.status})`);
      err.status = res.status; err.data = data; throw err;
    }
    return data;
  }

  /** HEPGO'da ayrı giriş yok; oturum HEPGO'nun kendisinden gelir. */
  async login() { throw new Error('Giriş HEPGO üzerinden yapılır.'); }
  async logout() { window.location.href = HEPGO.HOME_URL; }

  async pullProfile() {
    if (!this.isLoggedIn) return;
    this.syncState = 'syncing'; this.emit();
    try {
      const data = await this.api(HEPGO.PROFILE_URL);
      if (data?.user?.name) this.session.user.name = data.user.name;
      if (data?.profile) this.profile = mergeProfiles(this.profile, data.profile);
      lsSet(lsKey(this.uid), this.profile);
      this.syncState = 'ok';
    } catch (e) {
      this.syncState = e.status === 401 ? 'expired' : 'error';
    }
    this.emit();
  }

  async pushProfile() {
    if (!this.isLoggedIn) return;
    this.syncState = 'syncing'; this.emit();
    try { await this.api(HEPGO.PROFILE_URL, { method: 'PUT', body: { profile: this.profile } }); this.syncState = 'ok'; }
    catch (e) { this.syncState = e.status === 401 ? 'expired' : 'error'; }
    this.emit();
  }

  /** Şirket içi skor tablosu: [{user_id, name, hi_score, coins, honor, parkurs}] */
  async leaderboard() {
    try { return await this.api(HEPGO.LEADERBOARD_URL); } catch (e) { return []; }
  }

  resetProgress() {
    const s = this.profile.settings;
    this.profile = emptyProfile(); this.profile.settings = s;
    this.save(true);
  }
}
