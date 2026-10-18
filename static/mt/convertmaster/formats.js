// Desteklenen türler ve uzantılar. Hem ana süreçte (require) hem pencerelerde (<script>) çalışır.
// "source": kaynak olarak seçilebilen uzantılar, "target": hedef uzantılar.
// "play": Chromium'un (Electron) doğrudan önizleyebildiği uzantılar; diğerleri için önizleme üretilir.
(function (root) {
  'use strict';

  const TYPES = {
    video: {
      color: '#a855f7',
      source: ['mp4', 'mkv', 'avi', 'mov', 'wmv', 'webm', 'flv', 'm4v', 'mpg', 'mpeg', 'ts', 'mts', 'm2ts', '3gp', 'ogv', 'vob'],
      // Hedefler: video kapları, animasyonlu GIF ve (yalnız ses çıkarma) ses biçimleri
      target: ['mp4', 'mkv', 'webm', 'avi', 'mov', 'wmv', 'flv', 'm4v', 'mpg', '3gp', 'ogv', 'gif', 'mp3', 'm4a', 'wav', 'flac', 'ogg', 'opus'],
      audioOnlyTargets: ['mp3', 'm4a', 'wav', 'flac', 'ogg', 'opus'],
      play: ['mp4', 'm4v', 'webm', 'ogv', 'mov', 'mkv'],
      defaultSource: ['mkv', 'avi', 'mov', 'wmv'],
      defaultTarget: 'mp4',
    },
    image: {
      color: '#34d399',
      source: ['jpg', 'jpeg', 'png', 'webp', 'avif', 'gif', 'bmp', 'tif', 'tiff', 'ico', 'svg', 'tga'],
      target: ['jpg', 'png', 'webp', 'avif', 'gif', 'bmp', 'tiff', 'ico'],
      play: ['jpg', 'jpeg', 'png', 'webp', 'avif', 'gif', 'bmp', 'ico', 'svg'],
      defaultSource: ['png', 'bmp', 'tif', 'tiff'],
      defaultTarget: 'jpg',
    },
    audio: {
      color: '#f97316',
      source: ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg', 'oga', 'opus', 'wma', 'aiff', 'aif', 'amr', 'ac3', 'mka', 'ape', 'wv'],
      target: ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg', 'opus', 'wma', 'aiff', 'ac3'],
      play: ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg', 'oga', 'opus', 'webm'],
      defaultSource: ['wav', 'flac', 'wma', 'm4a'],
      defaultTarget: 'mp3',
    },
  };

  // Konuşmadan metne (whisper.cpp) modelleri: ilk kullanımda indirilir
  const SPEECH_MODELS = {
    // mb: yaklaşık indirme boyutu (yalnız bilgi amaçlı; doğrulama sunucunun Content-Length'iyle yapılır)
    tiny: { file: 'ggml-tiny.bin', mb: 75 },
    base: { file: 'ggml-base.bin', mb: 142 },
    small: { file: 'ggml-small.bin', mb: 466 },
    medium: { file: 'ggml-medium-q5_0.bin', mb: 514 },
    turbo: { file: 'ggml-large-v3-turbo-q5_0.bin', mb: 547 },
  };

  // Whisper'ın tanıdığı dillerden sık kullanılanlar (konuşma dili seçimi için; "auto" = algıla)
  const SPEECH_LANGS = ['auto', 'tr', 'en', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'ru', 'uk', 'ar', 'fa', 'az', 'el', 'bg', 'ro', 'pl', 'cs', 'hu',
    'sv', 'no', 'da', 'fi', 'zh', 'ja', 'ko', 'hi', 'ur', 'id', 'ms', 'th', 'vi', 'he'];

  // Resimden metin (OCR, Tesseract) dilleri — Tesseract kodları; ilk kullanımda indirilir
  const OCR_LANGS = ['tur', 'eng', 'deu', 'fra', 'spa', 'ita', 'por', 'nld', 'rus', 'ukr', 'ara', 'fas', 'heb', 'aze', 'ell', 'pol',
    'chi_sim', 'chi_tra', 'jpn', 'kor', 'hin'];
  // Tesseract kodu → ISO 639-1 (dil adını göstermek için)
  const OCR_ISO = { tur: 'tr', eng: 'en', deu: 'de', fra: 'fr', spa: 'es', ita: 'it', por: 'pt', nld: 'nl', rus: 'ru', ukr: 'uk', ara: 'ar',
    fas: 'fa', heb: 'he', aze: 'az', ell: 'el', pol: 'pl', chi_sim: 'zh-Hans', chi_tra: 'zh-Hant', jpn: 'ja', kor: 'ko', hin: 'hi' };

  const QUALITY = ['high', 'medium', 'low'];
  const RESOLUTIONS = ['source', '2160', '1440', '1080', '720', '480', '360'];
  const FPS = ['source', '60', '50', '30', '25', '24', '15'];
  const AUDIO_BITRATES = ['64', '96', '128', '160', '192', '256', '320'];
  const SAMPLE_RATES = ['source', '48000', '44100', '32000', '22050', '16000'];

  const extOf = (p) => {
    const m = /\.([^./\\]+)$/.exec(String(p || ''));
    return m ? m[1].toLowerCase() : '';
  };

  function typeOfExt(ext) {
    for (const [k, v] of Object.entries(TYPES)) if (v.source.includes(ext)) return k;
    return null;
  }

  // Bir proje için varsayılan dönüştürme seçenekleri
  function defaultOptions() {
    return {
      video: { quality: 'medium', resolution: 'source', fps: 'source', codec: 'h264', speed: 'medium', audioBitrate: '192', noAudio: false },
      image: { quality: 85, maxWidth: 0, maxHeight: 0, keepMeta: false },
      audio: { bitrate: '192', sampleRate: 'source', channels: 'source' },
    };
  }

  function defaultSpeech() {
    return { enabled: false, model: 'base', language: 'auto', perWindow: false };
  }

  // Resim projelerinde OCR (varsayılan kapalı; istenirse açılır)
  function defaultOcr() {
    return { enabled: false, languages: ['tur', 'eng'] };
  }

  const api = { TYPES, SPEECH_MODELS, SPEECH_LANGS, OCR_LANGS, OCR_ISO, defaultOcr, QUALITY, RESOLUTIONS, FPS, AUDIO_BITRATES, SAMPLE_RATES, extOf, typeOfExt, defaultOptions, defaultSpeech };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FORMATS = api;
})(typeof self !== 'undefined' ? self : this);
