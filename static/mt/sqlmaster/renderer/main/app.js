"use strict";
(() => {
  // src/shared/providers.ts
  var PROVIDERS = [
    { id: "postgres", name: "PostgreSQL", short: "PG", kind: "server", dialect: "postgres", defaultPort: 5432, defaultUser: "postgres", color: "#3b82f6" },
    { id: "mssql", name: "SQL Server", short: "MSSQL", kind: "server", dialect: "mssql", defaultPort: 1433, defaultUser: "sa", color: "#ef4444" },
    { id: "mysql", name: "MySQL / MariaDB", short: "MySQL", kind: "server", dialect: "mysql", defaultPort: 3306, defaultUser: "root", color: "#f97316" },
    { id: "sqlite", name: "SQLite", short: "SQLite", kind: "file", dialect: "sqlite", color: "#22d3ee", fileExtensions: ["db", "sqlite", "sqlite3", "db3"] },
    { id: "duckdb", name: "DuckDB / Dosyalar (CSV, Parquet, JSON, Excel)", short: "DuckDB", kind: "file", dialect: "duckdb", color: "#fbbf24", fileExtensions: ["duckdb", "db", "csv", "parquet", "json", "xlsx"] }
  ];
  var providerMeta = (id) => PROVIDERS.find((p) => p.id === id) ?? PROVIDERS[0];

  // src/renderer/lib/api.ts
  var api = window.api;

  // src/shared/locales/tr.ts
  var tr = {
    "common.cancel": "\u0130ptal",
    "common.save": "Kaydet",
    "common.create": "Olu\u015Ftur",
    "common.ok": "Tamam",
    "common.delete": "Sil",
    "common.giveUp": "Vazge\xE7",
    "common.open": "A\xE7",
    "common.edit": "D\xFCzenle",
    "common.rename": "Yeniden adland\u0131r",
    "common.refresh": "Yenile",
    "common.newFolder": "Yeni klas\xF6r",
    "common.move": "Ta\u015F\u0131",
    "common.moveEllipsis": "Ta\u015F\u0131\u2026",
    "common.show": "G\xF6ster",
    "common.choose": "Se\xE7\u2026",
    "common.connect": "Ba\u011Flan",
    "common.folderName": "Klas\xF6r ad\u0131",
    "common.copy": "Kopyala",
    "common.close": "Kapat",
    "app.searchPh": "Ba\u011Flant\u0131larda ara\u2026  (Ctrl+F)",
    "app.newConn": "Ba\u011Flant\u0131 ekle",
    "app.addConn": "Ba\u011Flant\u0131 ekle",
    "app.settings": "Ayarlar",
    "app.stats": "{c} ba\u011Flant\u0131 \xB7 {f} klas\xF6r",
    "app.welcome": "Ho\u015F geldiniz",
    "app.results": "\u201C{q}\u201D i\xE7in sonu\xE7lar",
    "app.all": "T\xFCm ba\u011Flant\u0131lar",
    "app.welcomeHint": "PostgreSQL, SQL Server, MySQL, SQLite ya da CSV/Parquet/Excel dosyalar\u0131na ba\u011Flan\u0131n.<br>Bilgileri girin, ba\u011Flant\u0131y\u0131 deneyin ve kaydedin.",
    "app.folders": "Klas\xF6rler",
    "app.connections": "Ba\u011Flant\u0131lar",
    "app.dblHint": "A\xE7mak i\xE7in karta \xE7ift t\u0131klay\u0131n",
    "app.noMatch": "E\u015Fle\u015Fen ba\u011Flant\u0131 bulunamad\u0131.",
    "app.folderCount": "{n} ba\u011Flant\u0131",
    "app.newConnHere": "Bu klas\xF6rde yeni ba\u011Flant\u0131",
    "app.newSubfolder": "Alt klas\xF6r olu\u015Ftur",
    "app.duplicate": "Kopyas\u0131n\u0131 olu\u015Ftur",
    "app.moveToFolder": "Klas\xF6re ta\u015F\u0131\u2026",
    "app.connMoved": "Ba\u011Flant\u0131 ta\u015F\u0131nd\u0131",
    "app.folderIntoSelf": "Klas\xF6r kendi i\xE7ine ta\u015F\u0131namaz",
    "app.folderPh": "\xD6rn. M\xFC\u015Fteriler",
    "app.renameFolder": "Klas\xF6r\xFC yeniden adland\u0131r",
    "app.deleteFolder": "Klas\xF6r\xFC sil",
    "app.deleteFolderMsg": "<b>{name}</b> klas\xF6r\xFC silinsin mi?",
    "app.deleteFolderConns": "<br>\u0130\xE7indeki {n} ba\u011Flant\u0131 \xFCst klas\xF6re ta\u015F\u0131nacak.",
    "app.rootFolder": "Ana dizin (klas\xF6rs\xFCz)",
    "app.moveTitle": "\u201C{name}\u201D ta\u015F\u0131",
    "app.targetFolder": "Hedef klas\xF6r",
    "app.deleteConn": "Ba\u011Flant\u0131y\u0131 sil",
    "app.deleteConnMsg": "<b>{name}</b> ({target}) ba\u011Flant\u0131s\u0131 silinsin mi? Kay\u0131tl\u0131 parolas\u0131 da silinir.",
    "app.readOnlyTag": "Salt okunur",
    "app.writeTag": "Yaz\u0131labilir",
    "form.titleNew": "Yeni ba\u011Flant\u0131",
    "form.titleEdit": "Ba\u011Flant\u0131: {name}",
    "form.tabGeneral": "Genel",
    "form.tabSecurity": "G\xFCvenlik",
    "form.tabSsh": "SSH t\xFCneli",
    "form.name": "Etiket (g\xF6r\xFCnen ad)",
    "form.namePh": "\xD6rn. \xDCretim veritaban\u0131",
    "form.host": "Sunucu adresi",
    "form.port": "Port",
    "form.user": "Kullan\u0131c\u0131 ad\u0131",
    "form.password": "Parola",
    "form.pwSaved": "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (kay\u0131tl\u0131, de\u011Fi\u015Ftirmek i\xE7in yaz\u0131n)",
    "form.database": "Veritaban\u0131",
    "form.databasePh": "Bo\u015F b\u0131rak\u0131l\u0131rsa varsay\u0131lan veritaban\u0131",
    "form.file": "Veritaban\u0131 dosyas\u0131",
    "form.filePh": "C:\\Veriler\\uygulama.db",
    "form.sqliteHint": "SQLite veritaban\u0131 dosyas\u0131 (.db, .sqlite). Salt okunur kipte dosya de\u011Fi\u015Ftirilmez.",
    "form.duckdbHint": "Bir .duckdb dosyas\u0131 se\xE7in ya da bo\u015F b\u0131rak\u0131n (bellek i\xE7i). CSV, Parquet, JSON ve Excel dosyalar\u0131n\u0131 do\u011Frudan sorgulayabilirsiniz: SELECT * FROM 'C:\\veri\\satis.csv'",
    "form.inMemory": "Bellek i\xE7i",
    "form.folder": "Klas\xF6r",
    "form.color": "Renk",
    "form.comments": "Notlar",
    "form.readOnly": "Salt okunur mod",
    "form.readOnlyHint": "\xD6nerilir. INSERT/UPDATE/DELETE ve DDL komutlar\u0131 \xE7al\u0131\u015Ft\u0131r\u0131lmadan \xF6nce engellenir; isterseniz tek seferlik onaylars\u0131n\u0131z. Desteklenen veritabanlar\u0131nda oturum da salt okunur a\xE7\u0131l\u0131r.",
    "form.savePassword": "Parolay\u0131 kaydet",
    "form.savePasswordHint": "Parola yaln\u0131zca i\u015Fletim sisteminin anahtar zincirinde (Windows: DPAPI) \u015Fifreli saklan\u0131r. Kapal\u0131ysa her ba\u011Flant\u0131da sorulur.",
    "form.ssl": "TLS / SSL",
    "form.sslPrefer": "Tercih et (sunucu destekliyorsa \u015Fifreli)",
    "form.sslRequire": "Zorunlu (sertifika do\u011Frulanmaz)",
    "form.sslVerify": "Zorunlu + sertifikay\u0131 do\u011Frula",
    "form.sslDisable": "Kapal\u0131 (\u015Fifresiz)",
    "form.sslHint": "Varsay\u0131lan olarak TLS denenir; sunucu desteklemiyorsa ba\u011Flant\u0131 penceresi uyar\u0131 g\xF6sterir.",
    "form.sshEnable": "SSH t\xFCneli \xFCzerinden ba\u011Flan",
    "form.sshHint": "Veritaban\u0131na \xF6nce bir SSH sunucusuna ba\u011Flan\u0131larak ula\u015F\u0131l\u0131r. Anahtarla giri\u015F \xF6nerilir.",
    "form.sshHost": "SSH sunucusu",
    "form.sshAuth": "SSH kimlik do\u011Frulama",
    "form.sshKey": "\xD6zel anahtar",
    "form.sshAgent": "Ajan (Pageant)",
    "form.keyFile": "\xD6zel anahtar dosyas\u0131",
    "form.passphrase": "Anahtar parolas\u0131",
    "form.passSaved": "(kay\u0131tl\u0131)",
    "form.passEmpty": "Yoksa bo\u015F b\u0131rak\u0131n",
    "form.sshPassword": "SSH parolas\u0131",
    "form.hostKey": "SSH sunucu anahtar\u0131: {fp}",
    "form.test": "Ba\u011Flant\u0131y\u0131 dene",
    "form.saveConnect": "Kaydet ve a\xE7",
    "form.connecting": "Ba\u011Flan\u0131l\u0131yor\u2026",
    "form.testOk": "Ba\u011Flant\u0131 ba\u015Far\u0131l\u0131",
    "form.testFail": "Ba\u011Flant\u0131 kurulamad\u0131",
    "form.testDb": "Veritaban\u0131: {db} \xB7 Kullan\u0131c\u0131: {user}",
    "form.noTls": "Uyar\u0131: ba\u011Flant\u0131 \u015Fifresiz (sunucu TLS desteklemiyor).",
    "form.saved": "Ba\u011Flant\u0131 kaydedildi",
    "form.changesSaved": "De\u011Fi\u015Fiklikler kaydedildi",
    "set.title": "Ayarlar",
    "set.appearance": "G\xF6r\xFCn\xFCm",
    "set.theme": "Tema",
    "set.themeDark": "Gece",
    "set.themeLight": "G\xFCnd\xFCz",
    "set.themeSystem": "Sistem tercihi",
    "set.language": "Dil",
    "set.toLight": "G\xFCnd\xFCz temas\u0131na ge\xE7",
    "set.toDark": "Gece temas\u0131na ge\xE7",
    "set.saved": "Ayarlar kaydedildi",
    "set.query": "Sorgular",
    "set.rowLimit": "Sonu\xE7 ba\u015F\u0131na en fazla sat\u0131r",
    "set.previewRows": "Tablo a\xE7\u0131l\u0131nca g\xF6sterilen kay\u0131t",
    "set.fontSize": "Edit\xF6r yaz\u0131 boyutu (px)",
    "auth.subtitle": "Mastertool hesab\u0131n\u0131zla giri\u015F yap\u0131n",
    "auth.email": "E-posta",
    "auth.password": "\u015Eifre",
    "auth.remember": "Beni hat\u0131rla",
    "auth.forgot": "\u015Eifremi unuttum",
    "auth.noAccount": "Hesab\u0131n\u0131z yok mu?",
    "auth.register": "Hesap olu\u015Ftur",
    "auth.submit": "Giri\u015F yap",
    "auth.working": "Giri\u015F yap\u0131l\u0131yor\u2026",
    "auth.errRequired": "E-posta ve \u015Fifre gerekli.",
    "auth.errBadCredentials": "E-posta veya \u015Fifre hatal\u0131.",
    "auth.errUnverified": "E-posta adresiniz hen\xFCz do\u011Frulanmad\u0131. Gelen kutunuzdaki ba\u011Flant\u0131ya t\u0131klay\u0131n.",
    "auth.errSuspended": "Hesab\u0131n\u0131z ask\u0131ya al\u0131nm\u0131\u015F.",
    "auth.errRateLimited": "\xC7ok fazla deneme yap\u0131ld\u0131. Bir dakika sonra tekrar deneyin.",
    "auth.errOffline": "Sunucuya ula\u015F\u0131lam\u0131yor. \u0130nternet ba\u011Flant\u0131n\u0131z\u0131 kontrol edin.",
    "auth.errSessionExpired": "Oturumunuzun s\xFCresi doldu ya da \u015Fifreniz de\u011Fi\u015Fti. L\xFCtfen yeniden giri\u015F yap\u0131n.",
    "auth.signedOutElsewhere": "Ba\u015Fka bir Mastertool uygulamas\u0131nda \xE7\u0131k\u0131\u015F yap\u0131ld\u0131. Yerel ba\u011Flant\u0131lar\u0131n\u0131z bu bilgisayarda duruyor.",
    "auth.errAppDisabled": "Hesab\u0131n\u0131zda SQL Master kapal\u0131. Destek i\xE7in: mastertool.download > Hesab\u0131m > Destek.",
    "auth.errWrongApp": "Bu oturum ba\u015Fka bir uygulamaya ait. L\xFCtfen SQL Master i\xE7in yeniden giri\u015F yap\u0131n.",
    "auth.errServer": "Giri\u015F yap\u0131lamad\u0131: {msg}",
    "auth.devNotice": "Geli\u015Ftirme kipi: Mastertool sunucusu yerine yerel hesap kullan\u0131l\u0131yor (herhangi bir e-posta/\u015Fifre kabul edilir, senkron yok).",
    "acct.section": "Hesap ve senkronizasyon",
    "acct.signedInAs": "{email} olarak giri\u015F yap\u0131ld\u0131",
    "acct.syncToggle": "Ba\u011Flant\u0131 k\xFCt\xFCphanesini web ile senkronize et",
    "acct.syncHint": "Ba\u011Flant\u0131lar, klas\xF6rler ve genel ayarlar u\xE7tan uca \u015Fifrelenerek Mastertool hesab\u0131n\u0131za yedeklenir; parolalar yaln\u0131zca \u015Fifreli blob i\xE7inde ta\u015F\u0131n\u0131r, sunucu i\xE7eri\u011Fi okuyamaz.",
    "acct.lastSync": "Son senkron: {time}",
    "acct.never": "Hen\xFCz senkronize edilmedi",
    "acct.syncNow": "\u015Eimdi senkronize et",
    "acct.deleteRemote": "Sunucudaki kopyay\u0131 sil",
    "acct.deleteRemoteMsg": "Hesab\u0131n\u0131zdaki \u015Fifreli ba\u011Flant\u0131 k\xFCt\xFCphanesi kopyas\u0131 silinecek ve senkronizasyon kapat\u0131lacak. Bu bilgisayardaki ba\u011Flant\u0131lar silinmez.",
    "acct.deleteRemoteDone": "Sunucudaki kopya silindi; senkronizasyon kapat\u0131ld\u0131",
    "acct.logout": "\xC7\u0131k\u0131\u015F yap",
    "acct.logoutMsg": "Hesab\u0131n\u0131zdan \xE7\u0131k\u0131\u015F yap\u0131lacak; a\xE7\u0131k ba\u011Flant\u0131 pencereleri ve s\xFCren sorgular kapan\u0131r. Bu bilgisayardaki ba\u011Flant\u0131lar silinmez.",
    "acct.myAccount": "Hesab\u0131m (web)",
    "acct.backupNotice": "Farkl\u0131 bir hesapla giri\u015F yap\u0131ld\u0131; bu bilgisayardaki \xF6nceki ba\u011Flant\u0131lar yedeklendi.",
    "sync.off": "Senkronizasyon kapal\u0131",
    "sync.syncing": "Senkronize ediliyor\u2026",
    "sync.offline": "\xC7evrimd\u0131\u015F\u0131 \u2014 de\u011Fi\u015Fiklikler ba\u011Flant\u0131 gelince g\xF6nderilecek",
    "sync.errDecrypt": "Sunucudaki kopya bu hesab\u0131n anahtar\u0131yla \xE7\xF6z\xFClemedi; bu bilgisayardaki ba\u011Flant\u0131lar korunuyor.",
    "sync.errTooLarge": "K\xFCt\xFCphane 5 MB s\u0131n\u0131r\u0131n\u0131 a\u015F\u0131yor; senkronize edilemedi.",
    "sync.error": "Senkron hatas\u0131: {msg}",
    "sync.devMode": "Geli\u015Ftirme kipi \u2014 senkron yok",
    "update.available": "Yeni s\xFCr\xFCm haz\u0131r: {version}",
    "update.hint": "Mastertool hesab\u0131n\u0131zdan indirebilirsiniz.",
    "update.open": "Hesab\u0131m\u0131 a\xE7",
    "cw.objects": "Nesneler",
    "cw.collapseAll": "T\xFCm\xFCn\xFC daralt",
    "cw.filterPh": "Y\xFCklenmi\u015F nesnelerde s\xFCz\u2026",
    "cw.empty": "(bo\u015F)",
    "cw.openData": "Veriyi a\xE7",
    "cw.showDdl": "DDL g\xF6ster",
    "cw.openCode": "Kodu a\xE7",
    "cw.selectSql": "SELECT ifadesi olu\u015Ftur",
    "cw.addToBuilder": "Sorgu olu\u015Fturucuya ekle",
    "cw.newSqlHere": "Burada yeni SQL",
    "cw.copyName": "Ad\u0131 kopyala",
    "cw.copied": "Panoya kopyaland\u0131",
    "cw.newSql": "Yeni SQL",
    "cw.builder": "Sorgu olu\u015Fturucu",
    "cw.reconnect": "Yeniden ba\u011Flan",
    "cw.readOnly": "Salt okunur",
    "cw.readWrite": "Yazma a\xE7\u0131k",
    "cw.readOnlyTip": "Salt okunur kip: DML/DDL onay olmadan \xE7al\u0131\u015Fmaz. T\u0131klay\u0131n: kapat",
    "cw.readWriteTip": "Yazma a\xE7\u0131k: komutlar onays\u0131z \xE7al\u0131\u015F\u0131r. T\u0131klay\u0131n: salt okunura d\xF6n",
    "cw.disableRo": "Salt okunur kip kapat\u0131ls\u0131n m\u0131?",
    "cw.disableRoMsg": "Bu pencere kapanana kadar INSERT/UPDATE/DELETE ve DDL komutlar\u0131 onay sorulmadan \xE7al\u0131\u015Facak.",
    "cw.disableRoOk": "Yazmay\u0131 a\xE7",
    "cw.roOn": "Salt okunur kip a\xE7\u0131k",
    "cw.roOff": "Yazma a\xE7\u0131k \u2014 dikkatli olun",
    "cw.passwordTitle": "Parola gerekli",
    "cw.passwordFor": "{user}@{host} i\xE7in parola",
    "cw.notConnected": "Ba\u011Fl\u0131 de\u011Fil",
    "cw.connected": "Ba\u011Fl\u0131",
    "cw.connecting": "Ba\u011Flan\u0131l\u0131yor\u2026",
    "cw.noTls": "\u015Eifresiz",
    "cw.connectFailed": "Ba\u011Flant\u0131 kurulamad\u0131",
    "cw.retry": "Tekrar dene",
    "cw.resetCancel": "Sorgu iptale yan\u0131t vermedi; ba\u011Flant\u0131 yeniden kuruluyor.",
    "cw.resetExit": "Veritaban\u0131 ba\u011Flant\u0131s\u0131 koptu; yeniden kuruluyor.",
    "cw.emptyWorkspace": "Soldaki a\u011Fa\xE7tan bir tabloya \xE7ift t\u0131klay\u0131n ya da Ctrl+T ile yeni SQL sekmesi a\xE7\u0131n.",
    "cw.closeTab": "Sekme kapat\u0131ls\u0131n m\u0131?",
    "cw.closeTabMsg": "\u201C{name}\u201D sekmesindeki SQL kaydedilmedi.",
    "cw.closeTabOk": "Kapat",
    "tree.tables": "Tablolar",
    "tree.views": "G\xF6r\xFCn\xFCmler",
    "tree.matviews": "Materialized view\u2019lar",
    "tree.foreign_tables": "Yabanc\u0131 tablolar",
    "tree.functions": "Fonksiyonlar",
    "tree.procedures": "Prosed\xFCrler",
    "tree.triggers": "Trigger\u2019lar",
    "tree.sequences": "Sequence\u2019ler",
    "tree.types": "Tipler",
    "tree.columns": "Kolonlar",
    "tree.indexes": "\u0130ndeksler",
    "tree.constraints": "K\u0131s\u0131tlar",
    "tree.files": "Dosyalar",
    "kind.table": "Tablo",
    "kind.view": "G\xF6r\xFCn\xFCm",
    "kind.matview": "Materialized view",
    "kind.foreign-table": "Yabanc\u0131 tablo",
    "kind.function": "Fonksiyon",
    "kind.procedure": "Prosed\xFCr",
    "kind.trigger": "Trigger",
    "kind.sequence": "Sequence",
    "kind.type": "Tip",
    "kind.index": "\u0130ndeks",
    "kind.constraint": "K\u0131s\u0131t",
    "sql.run": "\xC7al\u0131\u015Ft\u0131r",
    "sql.runStatement": "\u0130fadeyi \xE7al\u0131\u015Ft\u0131r",
    "sql.cancel": "\u0130ptal",
    "sql.database": "Veritaban\u0131",
    "sql.history": "Ge\xE7mi\u015F",
    "sql.export": "D\u0131\u015Fa aktar",
    "sql.running": "\xC7al\u0131\u015F\u0131yor\u2026",
    "sql.done": "Tamamland\u0131 \xB7 {ms} ms",
    "sql.doneErrors": "{n} hata \xB7 {ms} ms",
    "sql.ddlHint": "\u015Eema de\u011Fi\u015Fti: a\u011Fac\u0131 yenilemek i\xE7in Yenile d\xFC\u011Fmesini kullan\u0131n.",
    "sql.placeholder": "SQL yaz\u0131n\u2026 Ctrl+Enter: se\xE7ili/t\xFCm\xFCn\xFC \xE7al\u0131\u015Ft\u0131r \xB7 Ctrl+Shift+Enter: imle\xE7teki ifade \xB7 Ctrl+Bo\u015Fluk: tamamla",
    "sql.tabTitle": "SQL {n}",
    "sql.historyEmpty": "Bu ba\u011Flant\u0131 i\xE7in ge\xE7mi\u015F yok.",
    "sql.rowsShort": "sat\u0131r",
    "res.result": "Sonu\xE7 {n}",
    "res.messages": "Mesajlar",
    "res.rows": "{n} sat\u0131r \xB7 {ms} ms",
    "res.rowsTruncated": "\u0130lk {n} sat\u0131r g\xF6steriliyor (s\u0131n\u0131r) \xB7 {ms} ms",
    "res.noRows": "Kay\u0131t yok",
    "res.affected": "{cmd}: {n} sat\u0131r etkilendi \xB7 {ms} ms",
    "res.command": "{cmd} \xB7 {ms} ms",
    "res.cancelled": "\u0130ptal edildi",
    "grid.copy": "Kopyala",
    "grid.copyHeaders": "Ba\u015Fl\u0131klarla kopyala",
    "grid.export": "Bu sonucu d\u0131\u015Fa aktar\u2026",
    "data.columns": "Kolonlar",
    "data.columnsHidden": "Kolonlar ({n}/{total})",
    "data.addFilter": "Filtre",
    "data.limit": "Kay\u0131t say\u0131s\u0131",
    "data.firstN": "\u0130lk {n}",
    "data.all": "T\xFCm\xFC (s\u0131n\u0131rla)",
    "data.openInEditor": "SQL edit\xF6r\xFCnde a\xE7",
    "data.clearFilters": "Filtreleri temizle",
    "data.rows": "{n} kay\u0131t \xB7 {ms} ms",
    "data.rowsMore": "\u0130lk {n} kay\u0131t \xB7 {ms} ms",
    "data.error": "Veri al\u0131namad\u0131",
    "data.sortAsc": "Artan s\u0131rala",
    "data.sortDesc": "Azalan s\u0131rala",
    "data.sortClear": "S\u0131ralamay\u0131 kald\u0131r",
    "data.filterColumn": "Bu kolona g\xF6re filtrele\u2026",
    "data.hideColumn": "Kolonu gizle",
    "data.showAll": "T\xFCm kolonlar\u0131 g\xF6ster",
    "data.filterEq": "= \u201C{v}\u201D olanlar",
    "data.filterNe": "\u2260 \u201C{v}\u201D olanlar",
    "data.filterNull": "NULL olanlar / olmayanlar",
    "data.column": "Kolon",
    "data.operator": "Ko\u015Ful",
    "data.value": "De\u011Fer",
    "data.inHint": "\u201Ci\xE7inde\u201D i\xE7in de\u011Ferleri virg\xFClle ay\u0131r\u0131n.",
    "data.filterTitle": "Filtre",
    "data.selectAll": "T\xFCm\xFC",
    "data.selectNone": "Hi\xE7biri",
    "op.=": "e\u015Fittir",
    "op.<>": "e\u015Fit de\u011Fil",
    "op.<": "k\xFC\xE7\xFCkt\xFCr",
    "op.>": "b\xFCy\xFCkt\xFCr",
    "op.<=": "k\xFC\xE7\xFCk ya da e\u015Fit",
    "op.>=": "b\xFCy\xFCk ya da e\u015Fit",
    "op.contains": "i\xE7erir",
    "op.not contains": "i\xE7ermez",
    "op.starts": "ile ba\u015Flar",
    "op.ends": "ile biter",
    "op.like": "LIKE",
    "op.not like": "NOT LIKE",
    "op.in": "i\xE7inde (liste)",
    "op.not in": "i\xE7inde de\u011Fil",
    "op.is null": "bo\u015F (NULL)",
    "op.is not null": "bo\u015F de\u011Fil",
    "code.execute": "\xC7al\u0131\u015Ft\u0131r",
    "code.loading": "Y\xFCkleniyor\u2026",
    "code.empty": "Tan\u0131m bulunamad\u0131",
    "qb.addTable": "Tablo ekle",
    "qb.limit": "S\u0131n\u0131r",
    "qb.clear": "Temizle",
    "qb.hint": "Tablolar\u0131 soldaki a\u011Fa\xE7tan buraya s\xFCr\xFCkleyin ya da \u201CTablo ekle\u201Dye t\u0131klay\u0131n. Bir kolonu ba\u015Fka tablonun kolonuna s\xFCr\xFCkleyerek JOIN olu\u015Fturun.",
    "qb.columns": "Kolonlar",
    "qb.conditions": "Ko\u015Fullar",
    "qb.results": "Sonu\xE7lar",
    "qb.generated": "\xDCretilen SQL",
    "qb.regenerate": "Diyagramdan yeniden \xFCret",
    "qb.otherDb": "Sorgu olu\u015Fturucu tek bir veritaban\u0131ndaki tablolarla \xE7al\u0131\u015F\u0131r.",
    "qb.dragJoin": "JOIN i\xE7in ba\u015Fka tablonun kolonuna s\xFCr\xFCkleyin",
    "qb.swapJoin": "Y\xF6n\xFC de\u011Fi\u015Ftir",
    "qb.deleteJoin": "JOIN\u2019i sil",
    "qb.noColumns": "Tablolardaki kolon kutucuklar\u0131n\u0131 i\u015Faretleyin (bo\u015Fsa SELECT *).",
    "qb.output": "G\xF6ster",
    "qb.column": "Kolon",
    "qb.alias": "Takma ad",
    "qb.aggregate": "Toplama",
    "qb.sort": "S\u0131ralama",
    "qb.addCondition": "Ko\u015Ful ekle",
    "qb.tabTitle": "Sorgu {n}",
    "ro.title": "Salt okunur kip",
    "ro.message": "Bu ba\u011Flant\u0131 salt okunur kipte. A\u015Fa\u011F\u0131daki ifadeler veri ya da \u015Femay\u0131 de\u011Fi\u015Ftirebilir:",
    "ro.hint": "Yaln\u0131zca bu \xE7al\u0131\u015Ft\u0131rma i\xE7in izin verebilirsiniz; kip ard\u0131ndan yeniden a\xE7\u0131l\u0131r.",
    "ro.runOnce": "Bu seferlik \xE7al\u0131\u015Ft\u0131r",
    "ro.notRun": "Salt okunur kip: \xE7al\u0131\u015Ft\u0131r\u0131lmad\u0131",
    "ro.blockedMsg": "Salt okunur kip: {n} ifade onay bekliyor.",
    "exp.title": "D\u0131\u015Fa aktar",
    "exp.hint": "Sorgu s\u0131n\u0131rs\u0131z olarak yeniden \xE7al\u0131\u015Ft\u0131r\u0131l\u0131r ve sonu\xE7lar belle\u011Fe al\u0131nmadan do\u011Frudan dosyaya yaz\u0131l\u0131r.",
    "exp.running": "D\u0131\u015Fa aktar\u0131l\u0131yor\u2026",
    "exp.done": "{n} sat\u0131r d\u0131\u015Fa aktar\u0131ld\u0131",
    "exp.failed": "D\u0131\u015Fa aktar\u0131m ba\u015Far\u0131s\u0131z",
    "err.refused": "Ba\u011Flant\u0131 reddedildi: port kapal\u0131 ya da sunucu \xE7al\u0131\u015Fm\u0131yor.",
    "err.dns": "Sunucu ad\u0131 \xE7\xF6z\xFCmlenemedi (DNS).",
    "err.timeout": "Zaman a\u015F\u0131m\u0131: sunucuya ula\u015F\u0131lamad\u0131.",
    "err.reset": "Sunucu ba\u011Flant\u0131y\u0131 kapatt\u0131.",
    "err.unreach": "Sunucuya a\u011F \xFCzerinden ula\u015F\u0131lam\u0131yor.",
    "err.sshAuth": "SSH giri\u015Fi ba\u015Far\u0131s\u0131z: kullan\u0131c\u0131 ad\u0131, anahtar ya da parola hatal\u0131.",
    "err.tls": "TLS/SSL hatas\u0131 \u2014 sertifika do\u011Frulanamad\u0131 ya da sunucu TLS desteklemiyor. ({msg})",
    "err.hostExit": "Veritaban\u0131 s\xFCreci beklenmedik \u015Fekilde kapand\u0131.",
    "err.unknown": "Bilinmeyen hata",
    "main.closeAnyway": "Yine de kapat",
    "main.closeRunning": "\xC7al\u0131\u015Fan sorgular var. Pencere kapan\u0131rsa iptal edilecek.",
    "main.copySuffix": " (kopya)",
    "main.errConnNotFound": "Ba\u011Flant\u0131 bulunamad\u0131",
    "main.errNoSession": "Bu pencerenin ba\u011Flant\u0131s\u0131 yok",
    "main.errKeyFile": "SSH anahtar dosyas\u0131 okunamad\u0131: {path}",
    // Mastertool ortak ayarlar iskeleti (SSH Master ile aynı metinler)
    "set.general": "Genel",
    "set.account": "Hesap",
    "set.about": "Hakk\u0131nda",
    "set.startup": "Ba\u015Flang\u0131\xE7",
    "set.openAtLogin": "Windows oturumu a\xE7\u0131l\u0131nca ba\u015Flat",
    "set.openAtLoginHint": "Tepsiye k\xFC\xE7\xFCltme a\xE7\u0131ksa uygulama tepside ba\u015Flar.",
    "set.window": "Pencere",
    "set.minTray": "K\xFC\xE7\xFClt\xFCld\xFC\u011F\xFCnde sistem tepsisinde g\xF6ster",
    "set.minTrayHint": "Pencere k\xFC\xE7\xFClt\xFCl\xFCnce g\xF6rev \xE7ubu\u011Fundan gizlenir ve saatin yan\u0131ndaki tepside SQL Master simgesi olarak g\xF6r\xFCn\xFCr. Simgeye t\u0131klay\u0131nca geri a\xE7\u0131l\u0131r; sa\u011F t\u0131kla h\u0131zl\u0131ca ba\u011Flanabilirsiniz.",
    "set.closeTray": "Kapat\u0131ld\u0131\u011F\u0131nda tepsiye gizle",
    "set.closeTrayHint": "Kapat (X) d\xFC\u011Fmesi uygulamadan \xE7\u0131kmak yerine onu tepsiye gizler. \xC7\u0131kmak i\xE7in tepsi men\xFCs\xFCndeki \u201C\xC7\u0131k\u0131\u015F\u201D\u0131 kullan\u0131n.",
    "about.version": "S\xFCr\xFCm {version}",
    "about.family": "Mastertool ailesinin bir par\xE7as\u0131d\u0131r: SQL Master \xB7 FTP Masters \xB7 SQL Master \xB7 Notepad Master \xB7 Convert Master",
    "about.checkUpdate": "G\xFCncellemeleri denetle",
    "about.checking": "Denetleniyor\u2026",
    "about.upToDate": "SQL Master g\xFCncel.",
    "about.checkFailed": "G\xFCncelleme denetlenemedi: {msg}",
    "about.licenses": "A\xE7\u0131k kaynak lisanslar\u0131",
    "about.licensesIntro": "SQL Master \u015Fu a\xE7\u0131k kaynak bile\u015Fenleri kullan\u0131r:",
    "about.chromium": "Chromium lisanslar\u0131n\u0131 a\xE7",
    "main.trayShow": "SQL Master\u2019\u0131 g\xF6ster",
    "main.trayQuick": "H\u0131zl\u0131 ba\u011Flan",
    "main.trayNone": "Kay\u0131tl\u0131 ba\u011Flant\u0131 yok",
    "main.trayQuit": "\xC7\u0131k\u0131\u015F",
    "set.languageHint": "A\xE7\u0131k ba\u011Flant\u0131 pencereleri yeniden a\xE7\u0131ld\u0131\u011F\u0131nda yeni dili kullan\u0131r.",
    "about.newVersion": "Yeni s\xFCr\xFCm haz\u0131r: {version}"
  };

  // src/shared/locales/en.ts
  var en = {
    "common.cancel": "Cancel",
    "common.save": "Save",
    "common.create": "Create",
    "common.ok": "OK",
    "common.delete": "Delete",
    "common.giveUp": "Cancel",
    "common.open": "Open",
    "common.edit": "Edit",
    "common.rename": "Rename",
    "common.refresh": "Refresh",
    "common.newFolder": "New folder",
    "common.move": "Move",
    "common.moveEllipsis": "Move\u2026",
    "common.show": "Show",
    "common.choose": "Choose\u2026",
    "common.connect": "Connect",
    "common.folderName": "Folder name",
    "common.copy": "Copy",
    "common.close": "Close",
    "app.searchPh": "Search connections\u2026  (Ctrl+F)",
    "app.newConn": "Add connection",
    "app.addConn": "Add connection",
    "app.settings": "Settings",
    "app.stats": "{c} connections \xB7 {f} folders",
    "app.welcome": "Welcome",
    "app.results": "Results for \u201C{q}\u201D",
    "app.all": "All connections",
    "app.welcomeHint": "Connect to PostgreSQL, SQL Server, MySQL, SQLite or CSV/Parquet/Excel files.<br>Enter the details, test the connection and save.",
    "app.folders": "Folders",
    "app.connections": "Connections",
    "app.dblHint": "Double-click a card to open",
    "app.noMatch": "No matching connections.",
    "app.folderCount": "{n} connections",
    "app.folderCount_one": "{n} connection",
    "app.newConnHere": "New connection in this folder",
    "app.newSubfolder": "New subfolder",
    "app.duplicate": "Duplicate",
    "app.moveToFolder": "Move to folder\u2026",
    "app.connMoved": "Connection moved",
    "app.folderIntoSelf": "A folder cannot be moved into itself",
    "app.folderPh": "e.g. Customers",
    "app.renameFolder": "Rename folder",
    "app.deleteFolder": "Delete folder",
    "app.deleteFolderMsg": "Delete folder <b>{name}</b>?",
    "app.deleteFolderConns": "<br>Its {n} connections will move to the parent folder.",
    "app.rootFolder": "Top level (no folder)",
    "app.moveTitle": "Move \u201C{name}\u201D",
    "app.targetFolder": "Target folder",
    "app.deleteConn": "Delete connection",
    "app.deleteConnMsg": "Delete connection <b>{name}</b> ({target})? Its saved password is removed too.",
    "app.readOnlyTag": "Read-only",
    "app.writeTag": "Writable",
    "form.titleNew": "New connection",
    "form.titleEdit": "Connection: {name}",
    "form.tabGeneral": "General",
    "form.tabSecurity": "Security",
    "form.tabSsh": "SSH tunnel",
    "form.name": "Label (display name)",
    "form.namePh": "e.g. Production database",
    "form.host": "Host",
    "form.port": "Port",
    "form.user": "User name",
    "form.password": "Password",
    "form.pwSaved": "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (saved, type to change)",
    "form.database": "Database",
    "form.databasePh": "Leave empty for the default database",
    "form.file": "Database file",
    "form.filePh": "C:\\Data\\app.db",
    "form.sqliteHint": "SQLite database file (.db, .sqlite). In read-only mode the file is never modified.",
    "form.duckdbHint": "Choose a .duckdb file or leave empty (in-memory). Query CSV, Parquet, JSON and Excel files directly: SELECT * FROM 'C:\\data\\sales.csv'",
    "form.inMemory": "In-memory",
    "form.folder": "Folder",
    "form.color": "Color",
    "form.comments": "Notes",
    "form.readOnly": "Read-only mode",
    "form.readOnlyHint": "Recommended. INSERT/UPDATE/DELETE and DDL are blocked before execution; you can approve them once. Where supported, the session itself is read-only too.",
    "form.savePassword": "Save password",
    "form.savePasswordHint": "The password is stored only in the OS keychain (Windows: DPAPI). When off, you are asked on every connect.",
    "form.ssl": "TLS / SSL",
    "form.sslPrefer": "Prefer (encrypted if the server supports it)",
    "form.sslRequire": "Require (certificate not verified)",
    "form.sslVerify": "Require + verify certificate",
    "form.sslDisable": "Off (unencrypted)",
    "form.sslHint": "TLS is tried by default; the connection window warns if the server does not support it.",
    "form.sshEnable": "Connect through an SSH tunnel",
    "form.sshHint": "The database is reached through an SSH server first. Key authentication is recommended.",
    "form.sshHost": "SSH server",
    "form.sshAuth": "SSH authentication",
    "form.sshKey": "Private key",
    "form.sshAgent": "Agent (Pageant)",
    "form.keyFile": "Private key file",
    "form.passphrase": "Key passphrase",
    "form.passSaved": "(saved)",
    "form.passEmpty": "Leave empty if none",
    "form.sshPassword": "SSH password",
    "form.hostKey": "SSH host key: {fp}",
    "form.test": "Test connection",
    "form.saveConnect": "Save and open",
    "form.connecting": "Connecting\u2026",
    "form.testOk": "Connection successful",
    "form.testFail": "Could not connect",
    "form.testDb": "Database: {db} \xB7 User: {user}",
    "form.noTls": "Warning: the connection is unencrypted (server does not support TLS).",
    "form.saved": "Connection saved",
    "form.changesSaved": "Changes saved",
    "set.title": "Settings",
    "set.appearance": "Appearance",
    "set.theme": "Theme",
    "set.themeDark": "Night",
    "set.themeLight": "Day",
    "set.themeSystem": "System preference",
    "set.language": "Language",
    "set.toLight": "Switch to day theme",
    "set.toDark": "Switch to night theme",
    "set.saved": "Settings saved",
    "set.query": "Queries",
    "set.rowLimit": "Maximum rows per result",
    "set.previewRows": "Rows shown when opening a table",
    "set.fontSize": "Editor font size (px)",
    "auth.subtitle": "Sign in with your Mastertool account",
    "auth.email": "Email",
    "auth.password": "Password",
    "auth.remember": "Remember me",
    "auth.forgot": "Forgot password",
    "auth.noAccount": "No account yet?",
    "auth.register": "Create account",
    "auth.submit": "Sign in",
    "auth.working": "Signing in\u2026",
    "auth.errRequired": "Email and password are required.",
    "auth.errBadCredentials": "Wrong email or password.",
    "auth.errUnverified": "Your email address is not verified yet. Click the link in your inbox.",
    "auth.errSuspended": "Your account is suspended.",
    "auth.errRateLimited": "Too many attempts. Try again in a minute.",
    "auth.errOffline": "Cannot reach the server. Check your internet connection.",
    "auth.errSessionExpired": "Your session expired or your password changed. Please sign in again.",
    "auth.signedOutElsewhere": "You signed out in another Mastertool app. Your local connections are still on this computer.",
    "auth.errAppDisabled": "SQL Master is disabled for your account. Support: mastertool.download > My account > Support.",
    "auth.errWrongApp": "This session belongs to another app. Please sign in to SQL Master again.",
    "auth.errServer": "Could not sign in: {msg}",
    "auth.devNotice": "Development mode: a local account is used instead of the Mastertool server (any email/password, no sync).",
    "acct.section": "Account and sync",
    "acct.signedInAs": "Signed in as {email}",
    "acct.syncToggle": "Sync the connection library with the web",
    "acct.syncHint": "Connections, folders and general settings are end-to-end encrypted and backed up to your Mastertool account; passwords only travel inside the encrypted blob and the server cannot read it.",
    "acct.lastSync": "Last sync: {time}",
    "acct.never": "Not synced yet",
    "acct.syncNow": "Sync now",
    "acct.deleteRemote": "Delete server copy",
    "acct.deleteRemoteMsg": "The encrypted library copy in your account will be deleted and sync turned off. Connections on this computer are kept.",
    "acct.deleteRemoteDone": "Server copy deleted; sync turned off",
    "acct.logout": "Sign out",
    "acct.logoutMsg": "You will be signed out; open connection windows and running queries are closed. Connections on this computer are kept.",
    "acct.myAccount": "My account (web)",
    "acct.backupNotice": "Signed in with a different account; previous connections on this computer were backed up.",
    "sync.off": "Sync is off",
    "sync.syncing": "Syncing\u2026",
    "sync.offline": "Offline \u2014 changes will be sent when you are back online",
    "sync.errDecrypt": "The server copy could not be decrypted with this account\u2019s key; connections on this computer are kept.",
    "sync.errTooLarge": "The library exceeds the 5 MB limit and could not be synced.",
    "sync.error": "Sync error: {msg}",
    "sync.devMode": "Development mode \u2014 no sync",
    "update.available": "New version available: {version}",
    "update.hint": "Download it from your Mastertool account.",
    "update.open": "Open my account",
    "cw.objects": "Objects",
    "cw.collapseAll": "Collapse all",
    "cw.filterPh": "Filter loaded objects\u2026",
    "cw.empty": "(empty)",
    "cw.openData": "Open data",
    "cw.showDdl": "Show DDL",
    "cw.openCode": "Open code",
    "cw.selectSql": "Generate SELECT",
    "cw.addToBuilder": "Add to query builder",
    "cw.newSqlHere": "New SQL here",
    "cw.copyName": "Copy name",
    "cw.copied": "Copied to clipboard",
    "cw.newSql": "New SQL",
    "cw.builder": "Query builder",
    "cw.reconnect": "Reconnect",
    "cw.readOnly": "Read-only",
    "cw.readWrite": "Writes on",
    "cw.readOnlyTip": "Read-only: DML/DDL needs approval. Click to turn off",
    "cw.readWriteTip": "Writes on: commands run without approval. Click to go back to read-only",
    "cw.disableRo": "Turn off read-only mode?",
    "cw.disableRoMsg": "Until this window closes, INSERT/UPDATE/DELETE and DDL will run without asking.",
    "cw.disableRoOk": "Allow writes",
    "cw.roOn": "Read-only mode on",
    "cw.roOff": "Writes allowed \u2014 be careful",
    "cw.passwordTitle": "Password required",
    "cw.passwordFor": "Password for {user}@{host}",
    "cw.notConnected": "Not connected",
    "cw.connected": "Connected",
    "cw.connecting": "Connecting\u2026",
    "cw.noTls": "Unencrypted",
    "cw.connectFailed": "Could not connect",
    "cw.retry": "Retry",
    "cw.resetCancel": "The query did not respond to cancel; reconnecting.",
    "cw.resetExit": "The database connection dropped; reconnecting.",
    "cw.emptyWorkspace": "Double-click a table in the tree or press Ctrl+T for a new SQL tab.",
    "cw.closeTab": "Close tab?",
    "cw.closeTabMsg": "The SQL in \u201C{name}\u201D is not saved.",
    "cw.closeTabOk": "Close",
    "tree.tables": "Tables",
    "tree.views": "Views",
    "tree.matviews": "Materialized views",
    "tree.foreign_tables": "Foreign tables",
    "tree.functions": "Functions",
    "tree.procedures": "Procedures",
    "tree.triggers": "Triggers",
    "tree.sequences": "Sequences",
    "tree.types": "Types",
    "tree.columns": "Columns",
    "tree.indexes": "Indexes",
    "tree.constraints": "Constraints",
    "tree.files": "Files",
    "kind.table": "Table",
    "kind.view": "View",
    "kind.matview": "Materialized view",
    "kind.foreign-table": "Foreign table",
    "kind.function": "Function",
    "kind.procedure": "Procedure",
    "kind.trigger": "Trigger",
    "kind.sequence": "Sequence",
    "kind.type": "Type",
    "kind.index": "Index",
    "kind.constraint": "Constraint",
    "sql.run": "Run",
    "sql.runStatement": "Run statement",
    "sql.cancel": "Cancel",
    "sql.database": "Database",
    "sql.history": "History",
    "sql.export": "Export",
    "sql.running": "Running\u2026",
    "sql.done": "Done \xB7 {ms} ms",
    "sql.doneErrors": "{n} errors \xB7 {ms} ms",
    "sql.doneErrors_one": "{n} error \xB7 {ms} ms",
    "sql.ddlHint": "Schema changed: use Refresh to reload the tree.",
    "sql.placeholder": "Type SQL\u2026 Ctrl+Enter: run selection/all \xB7 Ctrl+Shift+Enter: statement at cursor \xB7 Ctrl+Space: complete",
    "sql.tabTitle": "SQL {n}",
    "sql.historyEmpty": "No history for this connection.",
    "sql.rowsShort": "rows",
    "res.result": "Result {n}",
    "res.messages": "Messages",
    "res.rows": "{n} rows \xB7 {ms} ms",
    "res.rows_one": "{n} row \xB7 {ms} ms",
    "res.rowsTruncated": "Showing the first {n} rows (limit) \xB7 {ms} ms",
    "res.noRows": "No rows",
    "res.affected": "{cmd}: {n} rows affected \xB7 {ms} ms",
    "res.affected_one": "{cmd}: {n} row affected \xB7 {ms} ms",
    "res.command": "{cmd} \xB7 {ms} ms",
    "res.cancelled": "Cancelled",
    "grid.copy": "Copy",
    "grid.copyHeaders": "Copy with headers",
    "grid.export": "Export this result\u2026",
    "data.columns": "Columns",
    "data.columnsHidden": "Columns ({n}/{total})",
    "data.addFilter": "Filter",
    "data.limit": "Row count",
    "data.firstN": "First {n}",
    "data.all": "All (limited)",
    "data.openInEditor": "Open in SQL editor",
    "data.clearFilters": "Clear filters",
    "data.rows": "{n} rows \xB7 {ms} ms",
    "data.rows_one": "{n} row \xB7 {ms} ms",
    "data.rowsMore": "First {n} rows \xB7 {ms} ms",
    "data.error": "Could not load data",
    "data.sortAsc": "Sort ascending",
    "data.sortDesc": "Sort descending",
    "data.sortClear": "Clear sorting",
    "data.filterColumn": "Filter by this column\u2026",
    "data.hideColumn": "Hide column",
    "data.showAll": "Show all columns",
    "data.filterEq": "Equal to \u201C{v}\u201D",
    "data.filterNe": "Not equal to \u201C{v}\u201D",
    "data.filterNull": "NULL / not NULL",
    "data.column": "Column",
    "data.operator": "Condition",
    "data.value": "Value",
    "data.inHint": "For \u201Cin list\u201D, separate values with commas.",
    "data.filterTitle": "Filter",
    "data.selectAll": "All",
    "data.selectNone": "None",
    "op.=": "equals",
    "op.<>": "not equal",
    "op.<": "less than",
    "op.>": "greater than",
    "op.<=": "less or equal",
    "op.>=": "greater or equal",
    "op.contains": "contains",
    "op.not contains": "does not contain",
    "op.starts": "starts with",
    "op.ends": "ends with",
    "op.like": "LIKE",
    "op.not like": "NOT LIKE",
    "op.in": "in list",
    "op.not in": "not in list",
    "op.is null": "is NULL",
    "op.is not null": "is not NULL",
    "code.execute": "Execute",
    "code.loading": "Loading\u2026",
    "code.empty": "No definition found",
    "qb.addTable": "Add table",
    "qb.limit": "Limit",
    "qb.clear": "Clear",
    "qb.hint": "Drag tables here from the tree or click \u201CAdd table\u201D. Drag a column onto another table\u2019s column to create a JOIN.",
    "qb.columns": "Columns",
    "qb.conditions": "Conditions",
    "qb.results": "Results",
    "qb.generated": "Generated SQL",
    "qb.regenerate": "Regenerate from diagram",
    "qb.otherDb": "The query builder works with tables from a single database.",
    "qb.dragJoin": "Drag onto another table\u2019s column to JOIN",
    "qb.swapJoin": "Swap direction",
    "qb.deleteJoin": "Delete JOIN",
    "qb.noColumns": "Tick column boxes on the tables (none = SELECT *).",
    "qb.output": "Show",
    "qb.column": "Column",
    "qb.alias": "Alias",
    "qb.aggregate": "Aggregate",
    "qb.sort": "Sort",
    "qb.addCondition": "Add condition",
    "qb.tabTitle": "Query {n}",
    "ro.title": "Read-only mode",
    "ro.message": "This connection is in read-only mode. The following statements may change data or schema:",
    "ro.hint": "You can allow them for this run only; read-only mode comes back afterwards.",
    "ro.runOnce": "Run this once",
    "ro.notRun": "Read-only mode: not executed",
    "ro.blockedMsg": "Read-only mode: {n} statements need approval.",
    "ro.blockedMsg_one": "Read-only mode: {n} statement needs approval.",
    "exp.title": "Export",
    "exp.hint": "The query runs again without a row limit and results are streamed straight to the file.",
    "exp.running": "Exporting\u2026",
    "exp.done": "{n} rows exported",
    "exp.done_one": "{n} row exported",
    "exp.failed": "Export failed",
    "err.refused": "Connection refused: the port is closed or the server is not running.",
    "err.dns": "Could not resolve the host name (DNS).",
    "err.timeout": "Timed out: the server could not be reached.",
    "err.reset": "The server closed the connection.",
    "err.unreach": "The server is unreachable on the network.",
    "err.sshAuth": "SSH login failed: wrong user name, key or password.",
    "err.tls": "TLS/SSL error \u2014 certificate could not be verified or the server does not support TLS. ({msg})",
    "err.hostExit": "The database process exited unexpectedly.",
    "err.unknown": "Unknown error",
    "main.closeAnyway": "Close anyway",
    "main.closeRunning": "Queries are still running. They will be cancelled if you close this window.",
    "main.copySuffix": " (copy)",
    "main.errConnNotFound": "Connection not found",
    "main.errNoSession": "This window has no connection",
    "main.errKeyFile": "Could not read the SSH key file: {path}",
    // Mastertool ortak ayarlar iskeleti (SSH Master ile aynı metinler)
    "set.general": "General",
    "set.account": "Account",
    "set.about": "About",
    "set.startup": "Startup",
    "set.openAtLogin": "Start when I sign in to Windows",
    "set.openAtLoginHint": "If minimizing to the tray is on, the app starts in the tray.",
    "set.window": "Window",
    "set.minTray": "Show in the system tray when minimized",
    "set.minTrayHint": "When minimized, the window leaves the taskbar and appears as the SQL Master icon in the tray next to the clock. Click the icon to restore it; right-click to connect quickly.",
    "set.closeTray": "Hide to tray when closed",
    "set.closeTrayHint": "The close (X) button hides the app to the tray instead of quitting. Use \u201CQuit\u201D in the tray menu to exit.",
    "about.version": "Version {version}",
    "about.family": "Part of the Mastertool family: SQL Master \xB7 FTP Masters \xB7 SQL Master \xB7 Notepad Master \xB7 Convert Master",
    "about.checkUpdate": "Check for updates",
    "about.checking": "Checking\u2026",
    "about.upToDate": "SQL Master is up to date.",
    "about.checkFailed": "Could not check for updates: {msg}",
    "about.licenses": "Open-source licenses",
    "about.licensesIntro": "SQL Master uses the following open-source components:",
    "about.chromium": "Open Chromium licenses",
    "main.trayShow": "Show SQL Master",
    "main.trayQuick": "Quick connect",
    "main.trayNone": "No saved connections",
    "main.trayQuit": "Quit",
    "set.languageHint": "Open connection windows use the new language once reopened.",
    "about.newVersion": "New version available: {version}"
  };

  // src/shared/locales/fr.ts
  var fr = {
    "common.cancel": "Annuler",
    "common.save": "Enregistrer",
    "common.create": "Cr\xE9er",
    "common.ok": "OK",
    "common.delete": "Supprimer",
    "common.giveUp": "Annuler",
    "common.open": "Ouvrir",
    "common.edit": "Modifier",
    "common.rename": "Renommer",
    "common.refresh": "Actualiser",
    "common.newFolder": "Nouveau dossier",
    "common.move": "D\xE9placer",
    "common.moveEllipsis": "D\xE9placer\u2026",
    "common.show": "Afficher",
    "common.choose": "Choisir\u2026",
    "common.connect": "Se connecter",
    "common.folderName": "Nom du dossier",
    "common.copy": "Copier",
    "common.close": "Fermer",
    "app.searchPh": "Rechercher des connexions\u2026  (Ctrl+F)",
    "app.newConn": "Ajouter une connexion",
    "app.addConn": "Ajouter une connexion",
    "app.settings": "Param\xE8tres",
    "app.stats": "{c} connexions \xB7 {f} dossiers",
    "app.welcome": "Bienvenue",
    "app.results": "R\xE9sultats pour \xAB\xA0{q}\xA0\xBB",
    "app.all": "Toutes les connexions",
    "app.welcomeHint": "Connectez-vous \xE0 PostgreSQL, SQL Server, MySQL, SQLite ou \xE0 des fichiers CSV/Parquet/Excel.<br>Saisissez les informations, testez la connexion et enregistrez.",
    "app.folders": "Dossiers",
    "app.connections": "Connexions",
    "app.dblHint": "Double-cliquez sur une carte pour l\u2019ouvrir",
    "app.noMatch": "Aucune connexion correspondante.",
    "app.folderCount": "{n} connexions",
    "app.newConnHere": "Nouvelle connexion dans ce dossier",
    "app.newSubfolder": "Nouveau sous-dossier",
    "app.duplicate": "Dupliquer",
    "app.moveToFolder": "D\xE9placer vers un dossier\u2026",
    "app.connMoved": "Connexion d\xE9plac\xE9e",
    "app.folderIntoSelf": "Un dossier ne peut pas \xEAtre d\xE9plac\xE9 dans lui-m\xEAme",
    "app.folderPh": "ex. Clients",
    "app.renameFolder": "Renommer le dossier",
    "app.deleteFolder": "Supprimer le dossier",
    "app.deleteFolderMsg": "Supprimer le dossier <b>{name}</b>\u202F?",
    "app.deleteFolderConns": "<br>Ses {n} connexions seront d\xE9plac\xE9es dans le dossier parent.",
    "app.rootFolder": "Niveau sup\xE9rieur (aucun dossier)",
    "app.moveTitle": "D\xE9placer \xAB\xA0{name}\xA0\xBB",
    "app.targetFolder": "Dossier cible",
    "app.deleteConn": "Supprimer la connexion",
    "app.deleteConnMsg": "Supprimer la connexion <b>{name}</b> ({target})\u202F? Son mot de passe enregistr\xE9 sera \xE9galement supprim\xE9.",
    "app.readOnlyTag": "Lecture seule",
    "app.writeTag": "\xC9criture",
    "form.titleNew": "Nouvelle connexion",
    "form.titleEdit": "Connexion\xA0: {name}",
    "form.tabGeneral": "G\xE9n\xE9ral",
    "form.tabSecurity": "S\xE9curit\xE9",
    "form.tabSsh": "Tunnel SSH",
    "form.name": "Libell\xE9 (nom affich\xE9)",
    "form.namePh": "ex. Base de production",
    "form.host": "H\xF4te",
    "form.port": "Port",
    "form.user": "Nom d\u2019utilisateur",
    "form.password": "Mot de passe",
    "form.pwSaved": "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (enregistr\xE9 \u2014 saisissez pour modifier)",
    "form.database": "Base de donn\xE9es",
    "form.databasePh": "Laissez vide pour la base par d\xE9faut",
    "form.file": "Fichier de base de donn\xE9es",
    "form.filePh": "C:\\Data\\app.db",
    "form.sqliteHint": "Fichier de base de donn\xE9es SQLite (.db, .sqlite). En mode lecture seule, le fichier n\u2019est jamais modifi\xE9.",
    "form.duckdbHint": "Choisissez un fichier .duckdb ou laissez vide (en m\xE9moire). Interrogez directement des fichiers CSV, Parquet, JSON et Excel\xA0: SELECT * FROM 'C:\\data\\sales.csv'",
    "form.inMemory": "En m\xE9moire",
    "form.folder": "Dossier",
    "form.color": "Couleur",
    "form.comments": "Notes",
    "form.readOnly": "Mode lecture seule",
    "form.readOnlyHint": "Recommand\xE9. Les INSERT/UPDATE/DELETE et le DDL sont bloqu\xE9s avant ex\xE9cution\u202F; vous pouvez les autoriser ponctuellement. Lorsque c\u2019est possible, la session elle-m\xEAme est aussi en lecture seule.",
    "form.savePassword": "Enregistrer le mot de passe",
    "form.savePasswordHint": "Le mot de passe est stock\xE9 uniquement dans le trousseau du syst\xE8me (Windows\xA0: DPAPI). Si l\u2019option est d\xE9sactiv\xE9e, il est demand\xE9 \xE0 chaque connexion.",
    "form.ssl": "TLS / SSL",
    "form.sslPrefer": "Pr\xE9f\xE9rer (chiffr\xE9 si le serveur le prend en charge)",
    "form.sslRequire": "Exiger (certificat non v\xE9rifi\xE9)",
    "form.sslVerify": "Exiger + v\xE9rifier le certificat",
    "form.sslDisable": "D\xE9sactiv\xE9 (non chiffr\xE9)",
    "form.sslHint": "TLS est tent\xE9 par d\xE9faut\u202F; la fen\xEAtre de connexion vous avertit si le serveur ne le prend pas en charge.",
    "form.sshEnable": "Se connecter via un tunnel SSH",
    "form.sshHint": "La base de donn\xE9es est atteinte en passant d\u2019abord par un serveur SSH. L\u2019authentification par cl\xE9 est recommand\xE9e.",
    "form.sshHost": "Serveur SSH",
    "form.sshAuth": "Authentification SSH",
    "form.sshKey": "Cl\xE9 priv\xE9e",
    "form.sshAgent": "Agent (Pageant)",
    "form.keyFile": "Fichier de cl\xE9 priv\xE9e",
    "form.passphrase": "Phrase secr\xE8te de la cl\xE9",
    "form.passSaved": "(enregistr\xE9e)",
    "form.passEmpty": "Laissez vide s\u2019il n\u2019y en a pas",
    "form.sshPassword": "Mot de passe SSH",
    "form.hostKey": "Cl\xE9 d\u2019h\xF4te SSH\xA0: {fp}",
    "form.test": "Tester la connexion",
    "form.saveConnect": "Enregistrer et ouvrir",
    "form.connecting": "Connexion\u2026",
    "form.testOk": "Connexion r\xE9ussie",
    "form.testFail": "\xC9chec de la connexion",
    "form.testDb": "Base de donn\xE9es\xA0: {db} \xB7 Utilisateur\xA0: {user}",
    "form.noTls": "Attention\xA0: la connexion n\u2019est pas chiffr\xE9e (le serveur ne prend pas en charge TLS).",
    "form.saved": "Connexion enregistr\xE9e",
    "form.changesSaved": "Modifications enregistr\xE9es",
    "set.title": "Param\xE8tres",
    "set.appearance": "Apparence",
    "set.theme": "Th\xE8me",
    "set.themeDark": "Nuit",
    "set.themeLight": "Jour",
    "set.themeSystem": "Pr\xE9f\xE9rence du syst\xE8me",
    "set.language": "Langue",
    "set.toLight": "Passer au th\xE8me jour",
    "set.toDark": "Passer au th\xE8me nuit",
    "set.saved": "Param\xE8tres enregistr\xE9s",
    "set.query": "Requ\xEAtes",
    "set.rowLimit": "Nombre maximal de lignes par r\xE9sultat",
    "set.previewRows": "Lignes affich\xE9es \xE0 l\u2019ouverture d\u2019une table",
    "set.fontSize": "Taille de police de l\u2019\xE9diteur (px)",
    "auth.subtitle": "Connectez-vous avec votre compte Mastertool",
    "auth.email": "E-mail",
    "auth.password": "Mot de passe",
    "auth.remember": "Se souvenir de moi",
    "auth.forgot": "Mot de passe oubli\xE9",
    "auth.noAccount": "Pas encore de compte\u202F?",
    "auth.register": "Cr\xE9er un compte",
    "auth.submit": "Se connecter",
    "auth.working": "Connexion\u2026",
    "auth.errRequired": "L\u2019e-mail et le mot de passe sont requis.",
    "auth.errBadCredentials": "E-mail ou mot de passe incorrect.",
    "auth.errUnverified": "Votre adresse e-mail n\u2019est pas encore v\xE9rifi\xE9e. Cliquez sur le lien re\xE7u par e-mail.",
    "auth.errSuspended": "Votre compte est suspendu.",
    "auth.errRateLimited": "Trop de tentatives. R\xE9essayez dans une minute.",
    "auth.errOffline": "Serveur injoignable. V\xE9rifiez votre connexion Internet.",
    "auth.errSessionExpired": "Votre session a expir\xE9 ou votre mot de passe a chang\xE9. Reconnectez-vous.",
    "auth.signedOutElsewhere": "Vous vous \xEAtes d\xE9connect\xE9 dans une autre application Mastertool. Vos connexions locales restent sur cet ordinateur.",
    "auth.errAppDisabled": "SQL Master est d\xE9sactiv\xE9 pour votre compte. Assistance\xA0: mastertool.download > Mon compte > Assistance.",
    "auth.errWrongApp": "Cette session appartient \xE0 une autre application. Reconnectez-vous \xE0 SQL Master.",
    "auth.errServer": "Connexion impossible\xA0: {msg}",
    "auth.devNotice": "Mode d\xE9veloppement\xA0: un compte local est utilis\xE9 \xE0 la place du serveur Mastertool (n\u2019importe quel e-mail/mot de passe, sans synchronisation).",
    "acct.section": "Compte et synchronisation",
    "acct.signedInAs": "Connect\xE9 en tant que {email}",
    "acct.syncToggle": "Synchroniser la biblioth\xE8que de connexions avec le web",
    "acct.syncHint": "Les connexions, dossiers et param\xE8tres g\xE9n\xE9raux sont sauvegard\xE9s sur votre compte Mastertool avec un chiffrement de bout en bout\u202F; les mots de passe ne transitent que dans le paquet chiffr\xE9, que le serveur ne peut pas lire.",
    "acct.lastSync": "Derni\xE8re synchronisation\xA0: {time}",
    "acct.never": "Pas encore synchronis\xE9",
    "acct.syncNow": "Synchroniser maintenant",
    "acct.deleteRemote": "Supprimer la copie du serveur",
    "acct.deleteRemoteMsg": "La copie chiffr\xE9e de la biblioth\xE8que dans votre compte sera supprim\xE9e et la synchronisation d\xE9sactiv\xE9e. Les connexions de cet ordinateur sont conserv\xE9es.",
    "acct.deleteRemoteDone": "Copie du serveur supprim\xE9e\u202F; synchronisation d\xE9sactiv\xE9e",
    "acct.logout": "Se d\xE9connecter",
    "acct.logoutMsg": "Vous serez d\xE9connect\xE9\u202F; les fen\xEAtres de connexion ouvertes et les requ\xEAtes en cours seront ferm\xE9es. Les connexions de cet ordinateur sont conserv\xE9es.",
    "acct.myAccount": "Mon compte (web)",
    "acct.backupNotice": "Connexion avec un autre compte\u202F; les connexions pr\xE9c\xE9dentes de cet ordinateur ont \xE9t\xE9 sauvegard\xE9es.",
    "sync.off": "Synchronisation d\xE9sactiv\xE9e",
    "sync.syncing": "Synchronisation\u2026",
    "sync.offline": "Hors ligne \u2014 les modifications seront envoy\xE9es au retour de la connexion",
    "sync.errDecrypt": "La copie du serveur n\u2019a pas pu \xEAtre d\xE9chiffr\xE9e avec la cl\xE9 de ce compte\u202F; les connexions de cet ordinateur sont conserv\xE9es.",
    "sync.errTooLarge": "La biblioth\xE8que d\xE9passe la limite de 5 Mo et n\u2019a pas pu \xEAtre synchronis\xE9e.",
    "sync.error": "Erreur de synchronisation\xA0: {msg}",
    "sync.devMode": "Mode d\xE9veloppement \u2014 sans synchronisation",
    "update.available": "Nouvelle version disponible\xA0: {version}",
    "update.hint": "T\xE9l\xE9chargez-la depuis votre compte Mastertool.",
    "update.open": "Ouvrir mon compte",
    "cw.objects": "Objets",
    "cw.collapseAll": "Tout r\xE9duire",
    "cw.filterPh": "Filtrer les objets charg\xE9s\u2026",
    "cw.empty": "(vide)",
    "cw.openData": "Ouvrir les donn\xE9es",
    "cw.showDdl": "Afficher le DDL",
    "cw.openCode": "Ouvrir le code",
    "cw.selectSql": "G\xE9n\xE9rer un SELECT",
    "cw.addToBuilder": "Ajouter au g\xE9n\xE9rateur de requ\xEAtes",
    "cw.newSqlHere": "Nouveau SQL ici",
    "cw.copyName": "Copier le nom",
    "cw.copied": "Copi\xE9 dans le presse-papiers",
    "cw.newSql": "Nouveau SQL",
    "cw.builder": "G\xE9n\xE9rateur de requ\xEAtes",
    "cw.reconnect": "Se reconnecter",
    "cw.readOnly": "Lecture seule",
    "cw.readWrite": "\xC9criture activ\xE9e",
    "cw.readOnlyTip": "Lecture seule\xA0: le DML/DDL n\xE9cessite une approbation. Cliquez pour d\xE9sactiver",
    "cw.readWriteTip": "\xC9criture activ\xE9e\xA0: les commandes s\u2019ex\xE9cutent sans approbation. Cliquez pour revenir en lecture seule",
    "cw.disableRo": "D\xE9sactiver le mode lecture seule\u202F?",
    "cw.disableRoMsg": "Jusqu\u2019\xE0 la fermeture de cette fen\xEAtre, les INSERT/UPDATE/DELETE et le DDL s\u2019ex\xE9cuteront sans confirmation.",
    "cw.disableRoOk": "Autoriser l\u2019\xE9criture",
    "cw.roOn": "Mode lecture seule activ\xE9",
    "cw.roOff": "\xC9criture autoris\xE9e \u2014 soyez prudent",
    "cw.passwordTitle": "Mot de passe requis",
    "cw.passwordFor": "Mot de passe pour {user}@{host}",
    "cw.notConnected": "Non connect\xE9",
    "cw.connected": "Connect\xE9",
    "cw.connecting": "Connexion\u2026",
    "cw.noTls": "Non chiffr\xE9",
    "cw.connectFailed": "\xC9chec de la connexion",
    "cw.retry": "R\xE9essayer",
    "cw.resetCancel": "La requ\xEAte n\u2019a pas r\xE9pondu \xE0 l\u2019annulation\u202F; reconnexion en cours.",
    "cw.resetExit": "La connexion \xE0 la base de donn\xE9es a \xE9t\xE9 interrompue\u202F; reconnexion en cours.",
    "cw.emptyWorkspace": "Double-cliquez sur une table dans l\u2019arborescence ou appuyez sur Ctrl+T pour un nouvel onglet SQL.",
    "cw.closeTab": "Fermer l\u2019onglet\u202F?",
    "cw.closeTabMsg": "Le SQL de \xAB\xA0{name}\xA0\xBB n\u2019est pas enregistr\xE9.",
    "cw.closeTabOk": "Fermer",
    "tree.tables": "Tables",
    "tree.views": "Vues",
    "tree.matviews": "Vues mat\xE9rialis\xE9es",
    "tree.foreign_tables": "Tables externes",
    "tree.functions": "Fonctions",
    "tree.procedures": "Proc\xE9dures",
    "tree.triggers": "D\xE9clencheurs",
    "tree.sequences": "S\xE9quences",
    "tree.types": "Types",
    "tree.columns": "Colonnes",
    "tree.indexes": "Index",
    "tree.constraints": "Contraintes",
    "tree.files": "Fichiers",
    "kind.table": "Table",
    "kind.view": "Vue",
    "kind.matview": "Vue mat\xE9rialis\xE9e",
    "kind.foreign-table": "Table externe",
    "kind.function": "Fonction",
    "kind.procedure": "Proc\xE9dure",
    "kind.trigger": "D\xE9clencheur",
    "kind.sequence": "S\xE9quence",
    "kind.type": "Type",
    "kind.index": "Index",
    "kind.constraint": "Contrainte",
    "sql.run": "Ex\xE9cuter",
    "sql.runStatement": "Ex\xE9cuter l\u2019instruction",
    "sql.cancel": "Annuler",
    "sql.database": "Base de donn\xE9es",
    "sql.history": "Historique",
    "sql.export": "Exporter",
    "sql.running": "Ex\xE9cution\u2026",
    "sql.done": "Termin\xE9 \xB7 {ms} ms",
    "sql.doneErrors": "{n} erreurs \xB7 {ms} ms",
    "sql.ddlHint": "Le sch\xE9ma a chang\xE9\xA0: utilisez Actualiser pour recharger l\u2019arborescence.",
    "sql.placeholder": "Saisissez du SQL\u2026 Ctrl+Enter\xA0: ex\xE9cuter la s\xE9lection/tout \xB7 Ctrl+Shift+Enter\xA0: instruction sous le curseur \xB7 Ctrl+Space\xA0: compl\xE9ter",
    "sql.tabTitle": "SQL {n}",
    "sql.historyEmpty": "Aucun historique pour cette connexion.",
    "sql.rowsShort": "lignes",
    "res.result": "R\xE9sultat {n}",
    "res.messages": "Messages",
    "res.rows": "{n} lignes \xB7 {ms} ms",
    "res.rowsTruncated": "Affichage des {n} premi\xE8res lignes (limite) \xB7 {ms} ms",
    "res.noRows": "Aucune ligne",
    "res.affected": "{cmd}\xA0: {n} lignes affect\xE9es \xB7 {ms} ms",
    "res.command": "{cmd} \xB7 {ms} ms",
    "res.cancelled": "Annul\xE9",
    "grid.copy": "Copier",
    "grid.copyHeaders": "Copier avec les en-t\xEAtes",
    "grid.export": "Exporter ce r\xE9sultat\u2026",
    "data.columns": "Colonnes",
    "data.columnsHidden": "Colonnes ({n}/{total})",
    "data.addFilter": "Filtre",
    "data.limit": "Nombre de lignes",
    "data.firstN": "{n} premi\xE8res",
    "data.all": "Toutes (limit\xE9es)",
    "data.openInEditor": "Ouvrir dans l\u2019\xE9diteur SQL",
    "data.clearFilters": "Effacer les filtres",
    "data.rows": "{n} lignes \xB7 {ms} ms",
    "data.rowsMore": "{n} premi\xE8res lignes \xB7 {ms} ms",
    "data.error": "Impossible de charger les donn\xE9es",
    "data.sortAsc": "Tri croissant",
    "data.sortDesc": "Tri d\xE9croissant",
    "data.sortClear": "Effacer le tri",
    "data.filterColumn": "Filtrer sur cette colonne\u2026",
    "data.hideColumn": "Masquer la colonne",
    "data.showAll": "Afficher toutes les colonnes",
    "data.filterEq": "\xC9gal \xE0 \xAB\xA0{v}\xA0\xBB",
    "data.filterNe": "Diff\xE9rent de \xAB\xA0{v}\xA0\xBB",
    "data.filterNull": "NULL / non NULL",
    "data.column": "Colonne",
    "data.operator": "Condition",
    "data.value": "Valeur",
    "data.inHint": "Pour \xAB\xA0dans la liste\xA0\xBB, s\xE9parez les valeurs par des virgules.",
    "data.filterTitle": "Filtre",
    "data.selectAll": "Tout",
    "data.selectNone": "Aucun",
    "op.=": "\xE9gal \xE0",
    "op.<>": "diff\xE9rent de",
    "op.<": "inf\xE9rieur \xE0",
    "op.>": "sup\xE9rieur \xE0",
    "op.<=": "inf\xE9rieur ou \xE9gal",
    "op.>=": "sup\xE9rieur ou \xE9gal",
    "op.contains": "contient",
    "op.not contains": "ne contient pas",
    "op.starts": "commence par",
    "op.ends": "se termine par",
    "op.like": "LIKE",
    "op.not like": "NOT LIKE",
    "op.in": "dans la liste",
    "op.not in": "pas dans la liste",
    "op.is null": "est NULL",
    "op.is not null": "n\u2019est pas NULL",
    "code.execute": "Ex\xE9cuter",
    "code.loading": "Chargement\u2026",
    "code.empty": "Aucune d\xE9finition trouv\xE9e",
    "qb.addTable": "Ajouter une table",
    "qb.limit": "Limite",
    "qb.clear": "Effacer",
    "qb.hint": "Faites glisser des tables depuis l\u2019arborescence ou cliquez sur \xAB\xA0Ajouter une table\xA0\xBB. Faites glisser une colonne sur la colonne d\u2019une autre table pour cr\xE9er une JOIN.",
    "qb.columns": "Colonnes",
    "qb.conditions": "Conditions",
    "qb.results": "R\xE9sultats",
    "qb.generated": "SQL g\xE9n\xE9r\xE9",
    "qb.regenerate": "R\xE9g\xE9n\xE9rer \xE0 partir du diagramme",
    "qb.otherDb": "Le g\xE9n\xE9rateur de requ\xEAtes fonctionne avec les tables d\u2019une seule base de donn\xE9es.",
    "qb.dragJoin": "Faites glisser sur la colonne d\u2019une autre table pour une JOIN",
    "qb.swapJoin": "Inverser le sens",
    "qb.deleteJoin": "Supprimer la JOIN",
    "qb.noColumns": "Cochez les colonnes dans les tables (aucune = SELECT *).",
    "qb.output": "Afficher",
    "qb.column": "Colonne",
    "qb.alias": "Alias",
    "qb.aggregate": "Agr\xE9gat",
    "qb.sort": "Tri",
    "qb.addCondition": "Ajouter une condition",
    "qb.tabTitle": "Requ\xEAte {n}",
    "ro.title": "Mode lecture seule",
    "ro.message": "Cette connexion est en mode lecture seule. Les instructions suivantes peuvent modifier les donn\xE9es ou le sch\xE9ma\xA0:",
    "ro.hint": "Vous pouvez les autoriser pour cette ex\xE9cution uniquement\u202F; le mode lecture seule est r\xE9tabli ensuite.",
    "ro.runOnce": "Ex\xE9cuter une seule fois",
    "ro.notRun": "Mode lecture seule\xA0: non ex\xE9cut\xE9",
    "ro.blockedMsg": "Mode lecture seule\xA0: {n} instructions n\xE9cessitent une approbation.",
    "exp.title": "Exporter",
    "exp.hint": "La requ\xEAte est r\xE9ex\xE9cut\xE9e sans limite de lignes et les r\xE9sultats sont \xE9crits directement dans le fichier.",
    "exp.running": "Exportation\u2026",
    "exp.done": "{n} lignes export\xE9es",
    "exp.failed": "\xC9chec de l\u2019exportation",
    "err.refused": "Connexion refus\xE9e\xA0: le port est ferm\xE9 ou le serveur n\u2019est pas d\xE9marr\xE9.",
    "err.dns": "Impossible de r\xE9soudre le nom d\u2019h\xF4te (DNS).",
    "err.timeout": "D\xE9lai d\xE9pass\xE9\xA0: le serveur est injoignable.",
    "err.reset": "Le serveur a ferm\xE9 la connexion.",
    "err.unreach": "Le serveur est inaccessible sur le r\xE9seau.",
    "err.sshAuth": "\xC9chec de la connexion SSH\xA0: nom d\u2019utilisateur, cl\xE9 ou mot de passe incorrect.",
    "err.tls": "Erreur TLS/SSL \u2014 le certificat n\u2019a pas pu \xEAtre v\xE9rifi\xE9 ou le serveur ne prend pas en charge TLS. ({msg})",
    "err.hostExit": "Le processus de base de donn\xE9es s\u2019est arr\xEAt\xE9 de mani\xE8re inattendue.",
    "err.unknown": "Erreur inconnue",
    "main.closeAnyway": "Fermer quand m\xEAme",
    "main.closeRunning": "Des requ\xEAtes sont encore en cours. Elles seront annul\xE9es si vous fermez cette fen\xEAtre.",
    "main.copySuffix": " (copie)",
    "main.errConnNotFound": "Connexion introuvable",
    "main.errNoSession": "Cette fen\xEAtre n\u2019a aucune connexion",
    "main.errKeyFile": "Impossible de lire le fichier de cl\xE9 SSH\xA0: {path}",
    // Mastertool ortak ayarlar iskeleti (SSH Master ile aynı metinler)
    "set.general": "G\xE9n\xE9ral",
    "set.account": "Compte",
    "set.about": "\xC0 propos",
    "set.startup": "D\xE9marrage",
    "set.openAtLogin": "D\xE9marrer \xE0 l\u2019ouverture de session Windows",
    "set.openAtLoginHint": "Si la r\xE9duction dans la zone de notification est activ\xE9e, l\u2019application y d\xE9marre.",
    "set.window": "Fen\xEAtre",
    "set.minTray": "Afficher dans la zone de notification une fois r\xE9duite",
    "set.minTrayHint": "Une fois r\xE9duite, la fen\xEAtre quitte la barre des t\xE2ches et appara\xEEt sous forme d\u2019ic\xF4ne SQL Master pr\xE8s de l\u2019horloge. Cliquez sur l\u2019ic\xF4ne pour la restaurer ; clic droit pour une connexion rapide.",
    "set.closeTray": "Masquer dans la zone de notification \xE0 la fermeture",
    "set.closeTrayHint": "Le bouton Fermer (X) masque l\u2019application au lieu de la quitter. Utilisez \xAB Quitter \xBB dans le menu de l\u2019ic\xF4ne pour sortir.",
    "about.version": "Version {version}",
    "about.family": "Fait partie de la famille Mastertool : SQL Master \xB7 FTP Masters \xB7 SQL Master \xB7 Notepad Master \xB7 Convert Master",
    "about.checkUpdate": "Rechercher des mises \xE0 jour",
    "about.checking": "V\xE9rification\u2026",
    "about.upToDate": "SQL Master est \xE0 jour.",
    "about.checkFailed": "Impossible de rechercher des mises \xE0 jour : {msg}",
    "about.licenses": "Licences open source",
    "about.licensesIntro": "SQL Master utilise les composants open source suivants :",
    "about.chromium": "Ouvrir les licences Chromium",
    "main.trayShow": "Afficher SQL Master",
    "main.trayQuick": "Connexion rapide",
    "main.trayNone": "Aucune connexion enregistr\xE9e",
    "main.trayQuit": "Quitter",
    "set.languageHint": "Les fen\xEAtres de connexion ouvertes utiliseront la nouvelle langue apr\xE8s r\xE9ouverture.",
    "about.newVersion": "Nouvelle version disponible : {version}"
  };

  // src/shared/locales/de.ts
  var de = {
    "common.cancel": "Abbrechen",
    "common.save": "Speichern",
    "common.create": "Erstellen",
    "common.ok": "OK",
    "common.delete": "L\xF6schen",
    "common.giveUp": "Abbrechen",
    "common.open": "\xD6ffnen",
    "common.edit": "Bearbeiten",
    "common.rename": "Umbenennen",
    "common.refresh": "Aktualisieren",
    "common.newFolder": "Neuer Ordner",
    "common.move": "Verschieben",
    "common.moveEllipsis": "Verschieben\u2026",
    "common.show": "Anzeigen",
    "common.choose": "Durchsuchen\u2026",
    "common.connect": "Verbinden",
    "common.folderName": "Ordnername",
    "common.copy": "Kopieren",
    "common.close": "Schlie\xDFen",
    "app.searchPh": "Verbindungen suchen\u2026  (Ctrl+F)",
    "app.newConn": "Verbindung hinzuf\xFCgen",
    "app.addConn": "Verbindung hinzuf\xFCgen",
    "app.settings": "Einstellungen",
    "app.stats": "{c} Verbindungen \xB7 {f} Ordner",
    "app.welcome": "Willkommen",
    "app.results": "Ergebnisse f\xFCr \u201E{q}\u201C",
    "app.all": "Alle Verbindungen",
    "app.welcomeHint": "Verbinden Sie sich mit PostgreSQL, SQL Server, MySQL, SQLite oder CSV-/Parquet-/Excel-Dateien.<br>Geben Sie die Daten ein, testen Sie die Verbindung und speichern Sie.",
    "app.folders": "Ordner",
    "app.connections": "Verbindungen",
    "app.dblHint": "Zum \xD6ffnen auf eine Karte doppelklicken",
    "app.noMatch": "Keine passenden Verbindungen.",
    "app.folderCount": "{n} Verbindungen",
    "app.newConnHere": "Neue Verbindung in diesem Ordner",
    "app.newSubfolder": "Neuer Unterordner",
    "app.duplicate": "Duplizieren",
    "app.moveToFolder": "In Ordner verschieben\u2026",
    "app.connMoved": "Verbindung verschoben",
    "app.folderIntoSelf": "Ein Ordner kann nicht in sich selbst verschoben werden",
    "app.folderPh": "z. B. Kunden",
    "app.renameFolder": "Ordner umbenennen",
    "app.deleteFolder": "Ordner l\xF6schen",
    "app.deleteFolderMsg": "Ordner <b>{name}</b> l\xF6schen?",
    "app.deleteFolderConns": "<br>Die {n} Verbindungen darin werden in den \xFCbergeordneten Ordner verschoben.",
    "app.rootFolder": "Oberste Ebene (kein Ordner)",
    "app.moveTitle": "\u201E{name}\u201C verschieben",
    "app.targetFolder": "Zielordner",
    "app.deleteConn": "Verbindung l\xF6schen",
    "app.deleteConnMsg": "Verbindung <b>{name}</b> ({target}) l\xF6schen? Das gespeicherte Passwort wird ebenfalls entfernt.",
    "app.readOnlyTag": "Schreibgesch\xFCtzt",
    "app.writeTag": "Beschreibbar",
    "form.titleNew": "Neue Verbindung",
    "form.titleEdit": "Verbindung: {name}",
    "form.tabGeneral": "Allgemein",
    "form.tabSecurity": "Sicherheit",
    "form.tabSsh": "SSH-Tunnel",
    "form.name": "Bezeichnung (Anzeigename)",
    "form.namePh": "z. B. Produktionsdatenbank",
    "form.host": "Host",
    "form.port": "Port",
    "form.user": "Benutzername",
    "form.password": "Passwort",
    "form.pwSaved": "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (gespeichert, zum \xC4ndern eingeben)",
    "form.database": "Datenbank",
    "form.databasePh": "Leer lassen f\xFCr die Standarddatenbank",
    "form.file": "Datenbankdatei",
    "form.filePh": "C:\\Data\\app.db",
    "form.sqliteHint": "SQLite-Datenbankdatei (.db, .sqlite). Im schreibgesch\xFCtzten Modus wird die Datei nie ver\xE4ndert.",
    "form.duckdbHint": "W\xE4hlen Sie eine .duckdb-Datei oder lassen Sie das Feld leer (In-Memory). CSV-, Parquet-, JSON- und Excel-Dateien direkt abfragen: SELECT * FROM 'C:\\data\\sales.csv'",
    "form.inMemory": "In-Memory",
    "form.folder": "Ordner",
    "form.color": "Farbe",
    "form.comments": "Notizen",
    "form.readOnly": "Schreibgesch\xFCtzter Modus",
    "form.readOnlyHint": "Empfohlen. INSERT/UPDATE/DELETE und DDL werden vor der Ausf\xFChrung blockiert; Sie k\xF6nnen sie einmalig freigeben. Wo unterst\xFCtzt, ist auch die Sitzung selbst schreibgesch\xFCtzt.",
    "form.savePassword": "Passwort speichern",
    "form.savePasswordHint": "Das Passwort wird nur im Schl\xFCsselbund des Betriebssystems gespeichert (Windows: DPAPI). Wenn deaktiviert, werden Sie bei jeder Verbindung danach gefragt.",
    "form.ssl": "TLS / SSL",
    "form.sslPrefer": "Bevorzugen (verschl\xFCsselt, wenn der Server es unterst\xFCtzt)",
    "form.sslRequire": "Erzwingen (Zertifikat wird nicht gepr\xFCft)",
    "form.sslVerify": "Erzwingen + Zertifikat pr\xFCfen",
    "form.sslDisable": "Aus (unverschl\xFCsselt)",
    "form.sslHint": "TLS wird standardm\xE4\xDFig versucht; das Verbindungsfenster warnt, wenn der Server es nicht unterst\xFCtzt.",
    "form.sshEnable": "\xDCber einen SSH-Tunnel verbinden",
    "form.sshHint": "Die Datenbank wird zuerst \xFCber einen SSH-Server erreicht. Schl\xFCsselauthentifizierung wird empfohlen.",
    "form.sshHost": "SSH-Server",
    "form.sshAuth": "SSH-Authentifizierung",
    "form.sshKey": "Privater Schl\xFCssel",
    "form.sshAgent": "Agent (Pageant)",
    "form.keyFile": "Private Schl\xFCsseldatei",
    "form.passphrase": "Schl\xFCssel-Passphrase",
    "form.passSaved": "(gespeichert)",
    "form.passEmpty": "Leer lassen, falls keine",
    "form.sshPassword": "SSH-Passwort",
    "form.hostKey": "SSH-Hostschl\xFCssel: {fp}",
    "form.test": "Verbindung testen",
    "form.saveConnect": "Speichern und \xF6ffnen",
    "form.connecting": "Verbindung wird hergestellt\u2026",
    "form.testOk": "Verbindung erfolgreich",
    "form.testFail": "Verbindung nicht m\xF6glich",
    "form.testDb": "Datenbank: {db} \xB7 Benutzer: {user}",
    "form.noTls": "Warnung: Die Verbindung ist unverschl\xFCsselt (der Server unterst\xFCtzt kein TLS).",
    "form.saved": "Verbindung gespeichert",
    "form.changesSaved": "\xC4nderungen gespeichert",
    "set.title": "Einstellungen",
    "set.appearance": "Darstellung",
    "set.theme": "Design",
    "set.themeDark": "Nacht",
    "set.themeLight": "Tag",
    "set.themeSystem": "Systemeinstellung",
    "set.language": "Sprache",
    "set.toLight": "Zum Tag-Design wechseln",
    "set.toDark": "Zum Nacht-Design wechseln",
    "set.saved": "Einstellungen gespeichert",
    "set.query": "Abfragen",
    "set.rowLimit": "Maximale Zeilen pro Ergebnis",
    "set.previewRows": "Angezeigte Zeilen beim \xD6ffnen einer Tabelle",
    "set.fontSize": "Schriftgr\xF6\xDFe im Editor (px)",
    "auth.subtitle": "Mit Ihrem Mastertool-Konto anmelden",
    "auth.email": "E-Mail",
    "auth.password": "Passwort",
    "auth.remember": "Angemeldet bleiben",
    "auth.forgot": "Passwort vergessen",
    "auth.noAccount": "Noch kein Konto?",
    "auth.register": "Konto erstellen",
    "auth.submit": "Anmelden",
    "auth.working": "Anmeldung\u2026",
    "auth.errRequired": "E-Mail und Passwort sind erforderlich.",
    "auth.errBadCredentials": "E-Mail oder Passwort falsch.",
    "auth.errUnverified": "Ihre E-Mail-Adresse ist noch nicht best\xE4tigt. Klicken Sie auf den Link in Ihrem Posteingang.",
    "auth.errSuspended": "Ihr Konto ist gesperrt.",
    "auth.errRateLimited": "Zu viele Versuche. Versuchen Sie es in einer Minute erneut.",
    "auth.errOffline": "Server nicht erreichbar. Pr\xFCfen Sie Ihre Internetverbindung.",
    "auth.errSessionExpired": "Ihre Sitzung ist abgelaufen oder Ihr Passwort wurde ge\xE4ndert. Bitte melden Sie sich erneut an.",
    "auth.signedOutElsewhere": "Sie haben sich in einer anderen Mastertool-App abgemeldet. Ihre lokalen Verbindungen bleiben auf diesem Computer.",
    "auth.errAppDisabled": "SQL Master ist f\xFCr Ihr Konto deaktiviert. Support: mastertool.download > Mein Konto > Support.",
    "auth.errWrongApp": "Diese Sitzung geh\xF6rt zu einer anderen Anwendung. Bitte melden Sie sich erneut bei SQL Master an.",
    "auth.errServer": "Anmeldung nicht m\xF6glich: {msg}",
    "auth.devNotice": "Entwicklungsmodus: Statt des Mastertool-Servers wird ein lokales Konto verwendet (beliebige E-Mail/beliebiges Passwort, keine Synchronisierung).",
    "acct.section": "Konto und Synchronisierung",
    "acct.signedInAs": "Angemeldet als {email}",
    "acct.syncToggle": "Verbindungsbibliothek mit dem Web synchronisieren",
    "acct.syncHint": "Verbindungen, Ordner und allgemeine Einstellungen werden Ende-zu-Ende-verschl\xFCsselt in Ihrem Mastertool-Konto gesichert; Passw\xF6rter werden nur innerhalb des verschl\xFCsselten Pakets \xFCbertragen, und der Server kann es nicht lesen.",
    "acct.lastSync": "Zuletzt synchronisiert: {time}",
    "acct.never": "Noch nicht synchronisiert",
    "acct.syncNow": "Jetzt synchronisieren",
    "acct.deleteRemote": "Serverkopie l\xF6schen",
    "acct.deleteRemoteMsg": "Die verschl\xFCsselte Bibliothekskopie in Ihrem Konto wird gel\xF6scht und die Synchronisierung ausgeschaltet. Die Verbindungen auf diesem Computer bleiben erhalten.",
    "acct.deleteRemoteDone": "Serverkopie gel\xF6scht; Synchronisierung ausgeschaltet",
    "acct.logout": "Abmelden",
    "acct.logoutMsg": "Sie werden abgemeldet; ge\xF6ffnete Verbindungsfenster und laufende Abfragen werden geschlossen. Die Verbindungen auf diesem Computer bleiben erhalten.",
    "acct.myAccount": "Mein Konto (Web)",
    "acct.backupNotice": "Mit einem anderen Konto angemeldet; die bisherigen Verbindungen auf diesem Computer wurden gesichert.",
    "sync.off": "Synchronisierung aus",
    "sync.syncing": "Wird synchronisiert\u2026",
    "sync.offline": "Offline \u2014 \xC4nderungen werden gesendet, sobald Sie wieder online sind",
    "sync.errDecrypt": "Die Serverkopie konnte mit dem Schl\xFCssel dieses Kontos nicht entschl\xFCsselt werden; die Verbindungen auf diesem Computer bleiben erhalten.",
    "sync.errTooLarge": "Die Bibliothek \xFCberschreitet das Limit von 5 MB und konnte nicht synchronisiert werden.",
    "sync.error": "Synchronisierungsfehler: {msg}",
    "sync.devMode": "Entwicklungsmodus \u2014 keine Synchronisierung",
    "update.available": "Neue Version verf\xFCgbar: {version}",
    "update.hint": "Laden Sie sie aus Ihrem Mastertool-Konto herunter.",
    "update.open": "Mein Konto \xF6ffnen",
    "cw.objects": "Objekte",
    "cw.collapseAll": "Alle einklappen",
    "cw.filterPh": "Geladene Objekte filtern\u2026",
    "cw.empty": "(leer)",
    "cw.openData": "Daten \xF6ffnen",
    "cw.showDdl": "DDL anzeigen",
    "cw.openCode": "Code \xF6ffnen",
    "cw.selectSql": "SELECT erzeugen",
    "cw.addToBuilder": "Zum Abfrage-Designer hinzuf\xFCgen",
    "cw.newSqlHere": "Neues SQL hier",
    "cw.copyName": "Namen kopieren",
    "cw.copied": "In die Zwischenablage kopiert",
    "cw.newSql": "Neues SQL",
    "cw.builder": "Abfrage-Designer",
    "cw.reconnect": "Neu verbinden",
    "cw.readOnly": "Schreibgesch\xFCtzt",
    "cw.readWrite": "Schreiben an",
    "cw.readOnlyTip": "Schreibgesch\xFCtzt: DML/DDL erfordert Best\xE4tigung. Zum Ausschalten klicken",
    "cw.readWriteTip": "Schreiben an: Befehle werden ohne Best\xE4tigung ausgef\xFChrt. Klicken, um zum Schreibschutz zur\xFCckzukehren",
    "cw.disableRo": "Schreibgesch\xFCtzten Modus ausschalten?",
    "cw.disableRoMsg": "Bis dieses Fenster geschlossen wird, werden INSERT/UPDATE/DELETE und DDL ohne Nachfrage ausgef\xFChrt.",
    "cw.disableRoOk": "Schreiben erlauben",
    "cw.roOn": "Schreibgesch\xFCtzter Modus an",
    "cw.roOff": "Schreiben erlaubt \u2014 Vorsicht",
    "cw.passwordTitle": "Passwort erforderlich",
    "cw.passwordFor": "Passwort f\xFCr {user}@{host}",
    "cw.notConnected": "Nicht verbunden",
    "cw.connected": "Verbunden",
    "cw.connecting": "Verbindung wird hergestellt\u2026",
    "cw.noTls": "Unverschl\xFCsselt",
    "cw.connectFailed": "Verbindung nicht m\xF6glich",
    "cw.retry": "Erneut versuchen",
    "cw.resetCancel": "Die Abfrage hat nicht auf den Abbruch reagiert; Verbindung wird neu hergestellt.",
    "cw.resetExit": "Die Datenbankverbindung wurde unterbrochen; Verbindung wird neu hergestellt.",
    "cw.emptyWorkspace": "Doppelklicken Sie im Baum auf eine Tabelle oder dr\xFCcken Sie Ctrl+T f\xFCr einen neuen SQL-Tab.",
    "cw.closeTab": "Tab schlie\xDFen?",
    "cw.closeTabMsg": "Das SQL in \u201E{name}\u201C ist nicht gespeichert.",
    "cw.closeTabOk": "Schlie\xDFen",
    "tree.tables": "Tabellen",
    "tree.views": "Sichten",
    "tree.matviews": "Materialisierte Sichten",
    "tree.foreign_tables": "Fremdtabellen",
    "tree.functions": "Funktionen",
    "tree.procedures": "Prozeduren",
    "tree.triggers": "Trigger",
    "tree.sequences": "Sequenzen",
    "tree.types": "Typen",
    "tree.columns": "Spalten",
    "tree.indexes": "Indizes",
    "tree.constraints": "Constraints",
    "tree.files": "Dateien",
    "kind.table": "Tabelle",
    "kind.view": "Sicht",
    "kind.matview": "Materialisierte Sicht",
    "kind.foreign-table": "Fremdtabelle",
    "kind.function": "Funktion",
    "kind.procedure": "Prozedur",
    "kind.trigger": "Trigger",
    "kind.sequence": "Sequenz",
    "kind.type": "Typ",
    "kind.index": "Index",
    "kind.constraint": "Constraint",
    "sql.run": "Ausf\xFChren",
    "sql.runStatement": "Anweisung ausf\xFChren",
    "sql.cancel": "Abbrechen",
    "sql.database": "Datenbank",
    "sql.history": "Verlauf",
    "sql.export": "Exportieren",
    "sql.running": "Wird ausgef\xFChrt\u2026",
    "sql.done": "Fertig \xB7 {ms} ms",
    "sql.doneErrors": "{n} Fehler \xB7 {ms} ms",
    "sql.ddlHint": "Schema ge\xE4ndert: Mit \u201EAktualisieren\u201C den Baum neu laden.",
    "sql.placeholder": "SQL eingeben\u2026 Ctrl+Enter: Auswahl/alles ausf\xFChren \xB7 Ctrl+Shift+Enter: Anweisung am Cursor \xB7 Ctrl+Space: vervollst\xE4ndigen",
    "sql.tabTitle": "SQL {n}",
    "sql.historyEmpty": "Kein Verlauf f\xFCr diese Verbindung.",
    "sql.rowsShort": "Zeilen",
    "res.result": "Ergebnis {n}",
    "res.messages": "Meldungen",
    "res.rows": "{n} Zeilen \xB7 {ms} ms",
    "res.rowsTruncated": "Die ersten {n} Zeilen werden angezeigt (Limit) \xB7 {ms} ms",
    "res.noRows": "Keine Zeilen",
    "res.affected": "{cmd}: {n} Zeilen betroffen \xB7 {ms} ms",
    "res.command": "{cmd} \xB7 {ms} ms",
    "res.cancelled": "Abgebrochen",
    "grid.copy": "Kopieren",
    "grid.copyHeaders": "Mit Spaltenk\xF6pfen kopieren",
    "grid.export": "Dieses Ergebnis exportieren\u2026",
    "data.columns": "Spalten",
    "data.columnsHidden": "Spalten ({n}/{total})",
    "data.addFilter": "Filter",
    "data.limit": "Zeilenanzahl",
    "data.firstN": "Erste {n}",
    "data.all": "Alle (begrenzt)",
    "data.openInEditor": "Im SQL-Editor \xF6ffnen",
    "data.clearFilters": "Filter l\xF6schen",
    "data.rows": "{n} Zeilen \xB7 {ms} ms",
    "data.rowsMore": "Erste {n} Zeilen \xB7 {ms} ms",
    "data.error": "Daten konnten nicht geladen werden",
    "data.sortAsc": "Aufsteigend sortieren",
    "data.sortDesc": "Absteigend sortieren",
    "data.sortClear": "Sortierung aufheben",
    "data.filterColumn": "Nach dieser Spalte filtern\u2026",
    "data.hideColumn": "Spalte ausblenden",
    "data.showAll": "Alle Spalten anzeigen",
    "data.filterEq": "Gleich \u201E{v}\u201C",
    "data.filterNe": "Ungleich \u201E{v}\u201C",
    "data.filterNull": "NULL / nicht NULL",
    "data.column": "Spalte",
    "data.operator": "Bedingung",
    "data.value": "Wert",
    "data.inHint": "F\xFCr \u201Ein Liste\u201C die Werte durch Kommas trennen.",
    "data.filterTitle": "Filter",
    "data.selectAll": "Alle",
    "data.selectNone": "Keine",
    "op.=": "gleich",
    "op.<>": "ungleich",
    "op.<": "kleiner als",
    "op.>": "gr\xF6\xDFer als",
    "op.<=": "kleiner oder gleich",
    "op.>=": "gr\xF6\xDFer oder gleich",
    "op.contains": "enth\xE4lt",
    "op.not contains": "enth\xE4lt nicht",
    "op.starts": "beginnt mit",
    "op.ends": "endet mit",
    "op.like": "LIKE",
    "op.not like": "NOT LIKE",
    "op.in": "in Liste",
    "op.not in": "nicht in Liste",
    "op.is null": "ist NULL",
    "op.is not null": "ist nicht NULL",
    "code.execute": "Ausf\xFChren",
    "code.loading": "Wird geladen\u2026",
    "code.empty": "Keine Definition gefunden",
    "qb.addTable": "Tabelle hinzuf\xFCgen",
    "qb.limit": "Limit",
    "qb.clear": "Leeren",
    "qb.hint": "Ziehen Sie Tabellen aus dem Baum hierher oder klicken Sie auf \u201ETabelle hinzuf\xFCgen\u201C. Ziehen Sie eine Spalte auf die Spalte einer anderen Tabelle, um einen JOIN zu erstellen.",
    "qb.columns": "Spalten",
    "qb.conditions": "Bedingungen",
    "qb.results": "Ergebnisse",
    "qb.generated": "Erzeugtes SQL",
    "qb.regenerate": "Aus Diagramm neu erzeugen",
    "qb.otherDb": "Der Abfrage-Designer arbeitet mit Tabellen aus einer einzigen Datenbank.",
    "qb.dragJoin": "F\xFCr einen JOIN auf die Spalte einer anderen Tabelle ziehen",
    "qb.swapJoin": "Richtung umkehren",
    "qb.deleteJoin": "JOIN l\xF6schen",
    "qb.noColumns": "Aktivieren Sie die Spalten-Kontrollk\xE4stchen in den Tabellen (keine = SELECT *).",
    "qb.output": "Anzeigen",
    "qb.column": "Spalte",
    "qb.alias": "Alias",
    "qb.aggregate": "Aggregat",
    "qb.sort": "Sortierung",
    "qb.addCondition": "Bedingung hinzuf\xFCgen",
    "qb.tabTitle": "Abfrage {n}",
    "ro.title": "Schreibgesch\xFCtzter Modus",
    "ro.message": "Diese Verbindung ist im schreibgesch\xFCtzten Modus. Die folgenden Anweisungen k\xF6nnen Daten oder Schema \xE4ndern:",
    "ro.hint": "Sie k\xF6nnen sie nur f\xFCr diese Ausf\xFChrung erlauben; danach ist der Schreibschutz wieder aktiv.",
    "ro.runOnce": "Einmal ausf\xFChren",
    "ro.notRun": "Schreibgesch\xFCtzter Modus: nicht ausgef\xFChrt",
    "ro.blockedMsg": "Schreibgesch\xFCtzter Modus: {n} Anweisungen erfordern eine Best\xE4tigung.",
    "exp.title": "Exportieren",
    "exp.hint": "Die Abfrage wird ohne Zeilenlimit erneut ausgef\xFChrt und die Ergebnisse werden direkt in die Datei geschrieben.",
    "exp.running": "Wird exportiert\u2026",
    "exp.done": "{n} Zeilen exportiert",
    "exp.failed": "Export fehlgeschlagen",
    "err.refused": "Verbindung abgelehnt: Der Port ist geschlossen oder der Server l\xE4uft nicht.",
    "err.dns": "Der Hostname konnte nicht aufgel\xF6st werden (DNS).",
    "err.timeout": "Zeit\xFCberschreitung: Der Server war nicht erreichbar.",
    "err.reset": "Der Server hat die Verbindung geschlossen.",
    "err.unreach": "Der Server ist im Netzwerk nicht erreichbar.",
    "err.sshAuth": "SSH-Anmeldung fehlgeschlagen: falscher Benutzername, Schl\xFCssel oder falsches Passwort.",
    "err.tls": "TLS/SSL-Fehler \u2014 das Zertifikat konnte nicht gepr\xFCft werden oder der Server unterst\xFCtzt kein TLS. ({msg})",
    "err.hostExit": "Der Datenbankprozess wurde unerwartet beendet.",
    "err.unknown": "Unbekannter Fehler",
    "main.closeAnyway": "Trotzdem schlie\xDFen",
    "main.closeRunning": "Es laufen noch Abfragen. Sie werden abgebrochen, wenn Sie dieses Fenster schlie\xDFen.",
    "main.copySuffix": " (Kopie)",
    "main.errConnNotFound": "Verbindung nicht gefunden",
    "main.errNoSession": "Dieses Fenster hat keine Verbindung",
    "main.errKeyFile": "Die SSH-Schl\xFCsseldatei konnte nicht gelesen werden: {path}",
    // Mastertool ortak ayarlar iskeleti (SSH Master ile aynı metinler)
    "set.general": "Allgemein",
    "set.account": "Konto",
    "set.about": "\xDCber",
    "set.startup": "Start",
    "set.openAtLogin": "Bei der Windows-Anmeldung starten",
    "set.openAtLoginHint": "Ist \u201EIn den Infobereich minimieren\u201C aktiv, startet die App im Infobereich.",
    "set.window": "Fenster",
    "set.minTray": "Beim Minimieren im Infobereich anzeigen",
    "set.minTrayHint": "Beim Minimieren verschwindet das Fenster aus der Taskleiste und erscheint als SQL Master-Symbol neben der Uhr. Klicken Sie auf das Symbol, um es wiederherzustellen; Rechtsklick f\xFCr Schnellverbindung.",
    "set.closeTray": "Beim Schlie\xDFen im Infobereich ausblenden",
    "set.closeTrayHint": "Die Schlie\xDFen-Schaltfl\xE4che (X) blendet die App aus, statt sie zu beenden. Zum Beenden \u201EBeenden\u201C im Symbolmen\xFC verwenden.",
    "about.version": "Version {version}",
    "about.family": "Teil der Mastertool-Familie: SQL Master \xB7 FTP Masters \xB7 SQL Master \xB7 Notepad Master \xB7 Convert Master",
    "about.checkUpdate": "Nach Updates suchen",
    "about.checking": "Wird gepr\xFCft\u2026",
    "about.upToDate": "SQL Master ist auf dem neuesten Stand.",
    "about.checkFailed": "Updates konnten nicht gepr\xFCft werden: {msg}",
    "about.licenses": "Open-Source-Lizenzen",
    "about.licensesIntro": "SQL Master verwendet die folgenden Open-Source-Komponenten:",
    "about.chromium": "Chromium-Lizenzen \xF6ffnen",
    "main.trayShow": "SQL Master anzeigen",
    "main.trayQuick": "Schnellverbindung",
    "main.trayNone": "Keine gespeicherten Verbindungen",
    "main.trayQuit": "Beenden",
    "set.languageHint": "Ge\xF6ffnete Verbindungsfenster verwenden die neue Sprache nach dem erneuten \xD6ffnen.",
    "about.newVersion": "Neue Version verf\xFCgbar: {version}"
  };

  // src/shared/locales/es.ts
  var es = {
    "common.cancel": "Cancelar",
    "common.save": "Guardar",
    "common.create": "Crear",
    "common.ok": "Aceptar",
    "common.delete": "Eliminar",
    "common.giveUp": "Cancelar",
    "common.open": "Abrir",
    "common.edit": "Editar",
    "common.rename": "Cambiar nombre",
    "common.refresh": "Actualizar",
    "common.newFolder": "Nueva carpeta",
    "common.move": "Mover",
    "common.moveEllipsis": "Mover\u2026",
    "common.show": "Mostrar",
    "common.choose": "Examinar\u2026",
    "common.connect": "Conectar",
    "common.folderName": "Nombre de la carpeta",
    "common.copy": "Copiar",
    "common.close": "Cerrar",
    "app.searchPh": "Buscar conexiones\u2026  (Ctrl+F)",
    "app.newConn": "A\xF1adir conexi\xF3n",
    "app.addConn": "A\xF1adir conexi\xF3n",
    "app.settings": "Ajustes",
    "app.stats": "{c} conexiones \xB7 {f} carpetas",
    "app.welcome": "Bienvenido",
    "app.results": "Resultados para \xAB{q}\xBB",
    "app.all": "Todas las conexiones",
    "app.welcomeHint": "Con\xE9ctate a PostgreSQL, SQL Server, MySQL, SQLite o a archivos CSV/Parquet/Excel.<br>Introduce los datos, prueba la conexi\xF3n y gu\xE1rdala.",
    "app.folders": "Carpetas",
    "app.connections": "Conexiones",
    "app.dblHint": "Doble clic en una tarjeta para abrirla",
    "app.noMatch": "No hay conexiones que coincidan.",
    "app.folderCount": "{n} conexiones",
    "app.newConnHere": "Nueva conexi\xF3n en esta carpeta",
    "app.newSubfolder": "Nueva subcarpeta",
    "app.duplicate": "Duplicar",
    "app.moveToFolder": "Mover a carpeta\u2026",
    "app.connMoved": "Conexi\xF3n movida",
    "app.folderIntoSelf": "Una carpeta no se puede mover dentro de s\xED misma",
    "app.folderPh": "p. ej. Clientes",
    "app.renameFolder": "Cambiar nombre de la carpeta",
    "app.deleteFolder": "Eliminar carpeta",
    "app.deleteFolderMsg": "\xBFEliminar la carpeta <b>{name}</b>?",
    "app.deleteFolderConns": "<br>Sus {n} conexiones se mover\xE1n a la carpeta superior.",
    "app.rootFolder": "Nivel superior (sin carpeta)",
    "app.moveTitle": "Mover \xAB{name}\xBB",
    "app.targetFolder": "Carpeta de destino",
    "app.deleteConn": "Eliminar conexi\xF3n",
    "app.deleteConnMsg": "\xBFEliminar la conexi\xF3n <b>{name}</b> ({target})? Tambi\xE9n se elimina su contrase\xF1a guardada.",
    "app.readOnlyTag": "Solo lectura",
    "app.writeTag": "Escritura",
    "form.titleNew": "Nueva conexi\xF3n",
    "form.titleEdit": "Conexi\xF3n: {name}",
    "form.tabGeneral": "General",
    "form.tabSecurity": "Seguridad",
    "form.tabSsh": "T\xFAnel SSH",
    "form.name": "Etiqueta (nombre visible)",
    "form.namePh": "p. ej. Base de datos de producci\xF3n",
    "form.host": "Host",
    "form.port": "Puerto",
    "form.user": "Usuario",
    "form.password": "Contrase\xF1a",
    "form.pwSaved": "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (guardada, escribe para cambiarla)",
    "form.database": "Base de datos",
    "form.databasePh": "D\xE9jalo vac\xEDo para usar la base de datos predeterminada",
    "form.file": "Archivo de base de datos",
    "form.filePh": "C:\\Data\\app.db",
    "form.sqliteHint": "Archivo de base de datos SQLite (.db, .sqlite). En modo de solo lectura el archivo nunca se modifica.",
    "form.duckdbHint": "Elige un archivo .duckdb o d\xE9jalo vac\xEDo (en memoria). Consulta archivos CSV, Parquet, JSON y Excel directamente: SELECT * FROM 'C:\\data\\sales.csv'",
    "form.inMemory": "En memoria",
    "form.folder": "Carpeta",
    "form.color": "Color",
    "form.comments": "Notas",
    "form.readOnly": "Modo de solo lectura",
    "form.readOnlyHint": "Recomendado. INSERT/UPDATE/DELETE y DDL se bloquean antes de ejecutarse; puedes aprobarlos una vez. Donde se admite, la propia sesi\xF3n tambi\xE9n es de solo lectura.",
    "form.savePassword": "Guardar contrase\xF1a",
    "form.savePasswordHint": "La contrase\xF1a se guarda solo en el llavero del sistema (Windows: DPAPI). Si est\xE1 desactivado, se pide en cada conexi\xF3n.",
    "form.ssl": "TLS / SSL",
    "form.sslPrefer": "Preferir (cifrado si el servidor lo admite)",
    "form.sslRequire": "Exigir (sin verificar el certificado)",
    "form.sslVerify": "Exigir y verificar el certificado",
    "form.sslDisable": "Desactivado (sin cifrar)",
    "form.sslHint": "TLS se intenta de forma predeterminada; la ventana de conexi\xF3n avisa si el servidor no lo admite.",
    "form.sshEnable": "Conectar a trav\xE9s de un t\xFAnel SSH",
    "form.sshHint": "Primero se accede a un servidor SSH y desde all\xED a la base de datos. Se recomienda la autenticaci\xF3n con clave.",
    "form.sshHost": "Servidor SSH",
    "form.sshAuth": "Autenticaci\xF3n SSH",
    "form.sshKey": "Clave privada",
    "form.sshAgent": "Agente (Pageant)",
    "form.keyFile": "Archivo de clave privada",
    "form.passphrase": "Frase de contrase\xF1a de la clave",
    "form.passSaved": "(guardada)",
    "form.passEmpty": "D\xE9jalo vac\xEDo si no tiene",
    "form.sshPassword": "Contrase\xF1a SSH",
    "form.hostKey": "Clave de host SSH: {fp}",
    "form.test": "Probar conexi\xF3n",
    "form.saveConnect": "Guardar y abrir",
    "form.connecting": "Conectando\u2026",
    "form.testOk": "Conexi\xF3n correcta",
    "form.testFail": "No se pudo conectar",
    "form.testDb": "Base de datos: {db} \xB7 Usuario: {user}",
    "form.noTls": "Aviso: la conexi\xF3n no est\xE1 cifrada (el servidor no admite TLS).",
    "form.saved": "Conexi\xF3n guardada",
    "form.changesSaved": "Cambios guardados",
    "set.title": "Ajustes",
    "set.appearance": "Apariencia",
    "set.theme": "Tema",
    "set.themeDark": "Noche",
    "set.themeLight": "D\xEDa",
    "set.themeSystem": "Preferencia del sistema",
    "set.language": "Idioma",
    "set.toLight": "Cambiar al tema de d\xEDa",
    "set.toDark": "Cambiar al tema de noche",
    "set.saved": "Ajustes guardados",
    "set.query": "Consultas",
    "set.rowLimit": "M\xE1ximo de filas por resultado",
    "set.previewRows": "Filas mostradas al abrir una tabla",
    "set.fontSize": "Tama\xF1o de fuente del editor (px)",
    "auth.subtitle": "Inicia sesi\xF3n con tu cuenta de Mastertool",
    "auth.email": "Correo electr\xF3nico",
    "auth.password": "Contrase\xF1a",
    "auth.remember": "Recordarme",
    "auth.forgot": "Olvid\xE9 mi contrase\xF1a",
    "auth.noAccount": "\xBFNo tienes cuenta?",
    "auth.register": "Crear cuenta",
    "auth.submit": "Iniciar sesi\xF3n",
    "auth.working": "Iniciando sesi\xF3n\u2026",
    "auth.errRequired": "Se requieren el correo y la contrase\xF1a.",
    "auth.errBadCredentials": "Correo o contrase\xF1a incorrectos.",
    "auth.errUnverified": "Tu correo a\xFAn no est\xE1 verificado. Haz clic en el enlace de tu bandeja de entrada.",
    "auth.errSuspended": "Tu cuenta est\xE1 suspendida.",
    "auth.errRateLimited": "Demasiados intentos. Vuelve a intentarlo en un minuto.",
    "auth.errOffline": "No se puede acceder al servidor. Comprueba tu conexi\xF3n a Internet.",
    "auth.errSessionExpired": "Tu sesi\xF3n caduc\xF3 o tu contrase\xF1a cambi\xF3. Vuelve a iniciar sesi\xF3n.",
    "auth.signedOutElsewhere": "Cerraste sesi\xF3n en otra aplicaci\xF3n de Mastertool. Tus conexiones locales siguen en este equipo.",
    "auth.errAppDisabled": "SQL Master est\xE1 desactivado para tu cuenta. Soporte: mastertool.download > Mi cuenta > Soporte.",
    "auth.errWrongApp": "Esta sesi\xF3n pertenece a otra aplicaci\xF3n. Vuelve a iniciar sesi\xF3n en SQL Master.",
    "auth.errServer": "No se pudo iniciar sesi\xF3n: {msg}",
    "auth.devNotice": "Modo de desarrollo: se usa una cuenta local en lugar del servidor de Mastertool (cualquier correo/contrase\xF1a, sin sincronizaci\xF3n).",
    "acct.section": "Cuenta y sincronizaci\xF3n",
    "acct.signedInAs": "Sesi\xF3n iniciada como {email}",
    "acct.syncToggle": "Sincronizar la biblioteca de conexiones con la web",
    "acct.syncHint": "Las conexiones, carpetas y ajustes generales se guardan en tu cuenta de Mastertool con cifrado de extremo a extremo; las contrase\xF1as solo viajan dentro del bloque cifrado y el servidor no puede leerlo.",
    "acct.lastSync": "\xDAltima sincronizaci\xF3n: {time}",
    "acct.never": "A\xFAn no sincronizado",
    "acct.syncNow": "Sincronizar ahora",
    "acct.deleteRemote": "Eliminar la copia del servidor",
    "acct.deleteRemoteMsg": "Se eliminar\xE1 la copia cifrada de la biblioteca de tu cuenta y se desactivar\xE1 la sincronizaci\xF3n. Las conexiones de este equipo se conservan.",
    "acct.deleteRemoteDone": "Copia del servidor eliminada; sincronizaci\xF3n desactivada",
    "acct.logout": "Cerrar sesi\xF3n",
    "acct.logoutMsg": "Se cerrar\xE1 tu sesi\xF3n; las ventanas de conexi\xF3n abiertas y las consultas en curso se cerrar\xE1n. Las conexiones de este equipo se conservan.",
    "acct.myAccount": "Mi cuenta (web)",
    "acct.backupNotice": "Has iniciado sesi\xF3n con otra cuenta; se hizo una copia de seguridad de las conexiones anteriores de este equipo.",
    "sync.off": "Sincronizaci\xF3n desactivada",
    "sync.syncing": "Sincronizando\u2026",
    "sync.offline": "Sin conexi\xF3n \u2014 los cambios se enviar\xE1n al recuperar la conexi\xF3n",
    "sync.errDecrypt": "No se pudo descifrar la copia del servidor con la clave de esta cuenta; se conservan las conexiones de este equipo.",
    "sync.errTooLarge": "La biblioteca supera el l\xEDmite de 5 MB y no se pudo sincronizar.",
    "sync.error": "Error de sincronizaci\xF3n: {msg}",
    "sync.devMode": "Modo de desarrollo \u2014 sin sincronizaci\xF3n",
    "update.available": "Nueva versi\xF3n disponible: {version}",
    "update.hint": "Desc\xE1rgala desde tu cuenta de Mastertool.",
    "update.open": "Abrir mi cuenta",
    "cw.objects": "Objetos",
    "cw.collapseAll": "Contraer todo",
    "cw.filterPh": "Filtrar objetos cargados\u2026",
    "cw.empty": "(vac\xEDo)",
    "cw.openData": "Abrir datos",
    "cw.showDdl": "Mostrar DDL",
    "cw.openCode": "Abrir c\xF3digo",
    "cw.selectSql": "Generar SELECT",
    "cw.addToBuilder": "A\xF1adir al generador de consultas",
    "cw.newSqlHere": "Nuevo SQL aqu\xED",
    "cw.copyName": "Copiar nombre",
    "cw.copied": "Copiado al portapapeles",
    "cw.newSql": "Nuevo SQL",
    "cw.builder": "Generador de consultas",
    "cw.reconnect": "Reconectar",
    "cw.readOnly": "Solo lectura",
    "cw.readWrite": "Escritura activada",
    "cw.readOnlyTip": "Solo lectura: DML/DDL requiere aprobaci\xF3n. Haz clic para desactivarlo",
    "cw.readWriteTip": "Escritura activada: los comandos se ejecutan sin aprobaci\xF3n. Haz clic para volver a solo lectura",
    "cw.disableRo": "\xBFDesactivar el modo de solo lectura?",
    "cw.disableRoMsg": "Hasta que se cierre esta ventana, INSERT/UPDATE/DELETE y DDL se ejecutar\xE1n sin preguntar.",
    "cw.disableRoOk": "Permitir escritura",
    "cw.roOn": "Modo de solo lectura activado",
    "cw.roOff": "Escritura permitida \u2014 ten cuidado",
    "cw.passwordTitle": "Se requiere contrase\xF1a",
    "cw.passwordFor": "Contrase\xF1a para {user}@{host}",
    "cw.notConnected": "Sin conexi\xF3n",
    "cw.connected": "Conectado",
    "cw.connecting": "Conectando\u2026",
    "cw.noTls": "Sin cifrar",
    "cw.connectFailed": "No se pudo conectar",
    "cw.retry": "Reintentar",
    "cw.resetCancel": "La consulta no respondi\xF3 a la cancelaci\xF3n; reconectando.",
    "cw.resetExit": "Se perdi\xF3 la conexi\xF3n con la base de datos; reconectando.",
    "cw.emptyWorkspace": "Haz doble clic en una tabla del \xE1rbol o pulsa Ctrl+T para abrir una nueva pesta\xF1a SQL.",
    "cw.closeTab": "\xBFCerrar la pesta\xF1a?",
    "cw.closeTabMsg": "El SQL de \xAB{name}\xBB no est\xE1 guardado.",
    "cw.closeTabOk": "Cerrar",
    "tree.tables": "Tablas",
    "tree.views": "Vistas",
    "tree.matviews": "Vistas materializadas",
    "tree.foreign_tables": "Tablas externas",
    "tree.functions": "Funciones",
    "tree.procedures": "Procedimientos",
    "tree.triggers": "Triggers",
    "tree.sequences": "Secuencias",
    "tree.types": "Tipos",
    "tree.columns": "Columnas",
    "tree.indexes": "\xCDndices",
    "tree.constraints": "Restricciones",
    "tree.files": "Archivos",
    "kind.table": "Tabla",
    "kind.view": "Vista",
    "kind.matview": "Vista materializada",
    "kind.foreign-table": "Tabla externa",
    "kind.function": "Funci\xF3n",
    "kind.procedure": "Procedimiento",
    "kind.trigger": "Trigger",
    "kind.sequence": "Secuencia",
    "kind.type": "Tipo",
    "kind.index": "\xCDndice",
    "kind.constraint": "Restricci\xF3n",
    "sql.run": "Ejecutar",
    "sql.runStatement": "Ejecutar sentencia",
    "sql.cancel": "Cancelar",
    "sql.database": "Base de datos",
    "sql.history": "Historial",
    "sql.export": "Exportar",
    "sql.running": "Ejecutando\u2026",
    "sql.done": "Listo \xB7 {ms} ms",
    "sql.doneErrors": "{n} errores \xB7 {ms} ms",
    "sql.ddlHint": "El esquema cambi\xF3: usa Actualizar para recargar el \xE1rbol.",
    "sql.placeholder": "Escribe SQL\u2026 Ctrl+Enter: ejecutar selecci\xF3n/todo \xB7 Ctrl+Shift+Enter: sentencia en el cursor \xB7 Ctrl+Space: autocompletar",
    "sql.tabTitle": "SQL {n}",
    "sql.historyEmpty": "No hay historial para esta conexi\xF3n.",
    "sql.rowsShort": "filas",
    "res.result": "Resultado {n}",
    "res.messages": "Mensajes",
    "res.rows": "{n} filas \xB7 {ms} ms",
    "res.rowsTruncated": "Mostrando las primeras {n} filas (l\xEDmite) \xB7 {ms} ms",
    "res.noRows": "Sin filas",
    "res.affected": "{cmd}: {n} filas afectadas \xB7 {ms} ms",
    "res.command": "{cmd} \xB7 {ms} ms",
    "res.cancelled": "Cancelado",
    "grid.copy": "Copiar",
    "grid.copyHeaders": "Copiar con encabezados",
    "grid.export": "Exportar este resultado\u2026",
    "data.columns": "Columnas",
    "data.columnsHidden": "Columnas ({n}/{total})",
    "data.addFilter": "Filtrar",
    "data.limit": "N\xFAmero de filas",
    "data.firstN": "Primeras {n}",
    "data.all": "Todas (con l\xEDmite)",
    "data.openInEditor": "Abrir en el editor SQL",
    "data.clearFilters": "Quitar filtros",
    "data.rows": "{n} filas \xB7 {ms} ms",
    "data.rowsMore": "Primeras {n} filas \xB7 {ms} ms",
    "data.error": "No se pudieron cargar los datos",
    "data.sortAsc": "Orden ascendente",
    "data.sortDesc": "Orden descendente",
    "data.sortClear": "Quitar orden",
    "data.filterColumn": "Filtrar por esta columna\u2026",
    "data.hideColumn": "Ocultar columna",
    "data.showAll": "Mostrar todas las columnas",
    "data.filterEq": "Igual a \xAB{v}\xBB",
    "data.filterNe": "Distinto de \xAB{v}\xBB",
    "data.filterNull": "NULL / no NULL",
    "data.column": "Columna",
    "data.operator": "Condici\xF3n",
    "data.value": "Valor",
    "data.inHint": "Para \xABen la lista\xBB, separa los valores con comas.",
    "data.filterTitle": "Filtro",
    "data.selectAll": "Todas",
    "data.selectNone": "Ninguna",
    "op.=": "igual a",
    "op.<>": "distinto de",
    "op.<": "menor que",
    "op.>": "mayor que",
    "op.<=": "menor o igual",
    "op.>=": "mayor o igual",
    "op.contains": "contiene",
    "op.not contains": "no contiene",
    "op.starts": "empieza por",
    "op.ends": "termina en",
    "op.like": "LIKE",
    "op.not like": "NOT LIKE",
    "op.in": "en la lista",
    "op.not in": "no en la lista",
    "op.is null": "es NULL",
    "op.is not null": "no es NULL",
    "code.execute": "Ejecutar",
    "code.loading": "Cargando\u2026",
    "code.empty": "No se encontr\xF3 ninguna definici\xF3n",
    "qb.addTable": "A\xF1adir tabla",
    "qb.limit": "L\xEDmite",
    "qb.clear": "Limpiar",
    "qb.hint": "Arrastra tablas aqu\xED desde el \xE1rbol o haz clic en \xABA\xF1adir tabla\xBB. Arrastra una columna sobre la columna de otra tabla para crear un JOIN.",
    "qb.columns": "Columnas",
    "qb.conditions": "Condiciones",
    "qb.results": "Resultados",
    "qb.generated": "SQL generado",
    "qb.regenerate": "Regenerar desde el diagrama",
    "qb.otherDb": "El generador de consultas funciona con tablas de una sola base de datos.",
    "qb.dragJoin": "Arrastra sobre la columna de otra tabla para hacer JOIN",
    "qb.swapJoin": "Invertir direcci\xF3n",
    "qb.deleteJoin": "Eliminar JOIN",
    "qb.noColumns": "Marca las casillas de columna en las tablas (ninguna = SELECT *).",
    "qb.output": "Mostrar",
    "qb.column": "Columna",
    "qb.alias": "Alias",
    "qb.aggregate": "Agregado",
    "qb.sort": "Orden",
    "qb.addCondition": "A\xF1adir condici\xF3n",
    "qb.tabTitle": "Consulta {n}",
    "ro.title": "Modo de solo lectura",
    "ro.message": "Esta conexi\xF3n est\xE1 en modo de solo lectura. Las siguientes sentencias pueden modificar datos o el esquema:",
    "ro.hint": "Puedes permitirlas solo para esta ejecuci\xF3n; despu\xE9s se restablece el modo de solo lectura.",
    "ro.runOnce": "Ejecutar esta vez",
    "ro.notRun": "Modo de solo lectura: no se ejecut\xF3",
    "ro.blockedMsg": "Modo de solo lectura: {n} sentencias requieren aprobaci\xF3n.",
    "exp.title": "Exportar",
    "exp.hint": "La consulta se vuelve a ejecutar sin l\xEDmite de filas y los resultados se escriben directamente en el archivo.",
    "exp.running": "Exportando\u2026",
    "exp.done": "{n} filas exportadas",
    "exp.failed": "Error al exportar",
    "err.refused": "Conexi\xF3n rechazada: el puerto est\xE1 cerrado o el servidor no est\xE1 en ejecuci\xF3n.",
    "err.dns": "No se pudo resolver el nombre de host (DNS).",
    "err.timeout": "Tiempo de espera agotado: no se pudo acceder al servidor.",
    "err.reset": "El servidor cerr\xF3 la conexi\xF3n.",
    "err.unreach": "El servidor no es accesible en la red.",
    "err.sshAuth": "Error de inicio de sesi\xF3n SSH: usuario, clave o contrase\xF1a incorrectos.",
    "err.tls": "Error de TLS/SSL \u2014 no se pudo verificar el certificado o el servidor no admite TLS. ({msg})",
    "err.hostExit": "El proceso de la base de datos termin\xF3 inesperadamente.",
    "err.unknown": "Error desconocido",
    "main.closeAnyway": "Cerrar de todos modos",
    "main.closeRunning": "Todav\xEDa hay consultas en ejecuci\xF3n. Se cancelar\xE1n si cierras esta ventana.",
    "main.copySuffix": " (copia)",
    "main.errConnNotFound": "Conexi\xF3n no encontrada",
    "main.errNoSession": "Esta ventana no tiene conexi\xF3n",
    "main.errKeyFile": "No se pudo leer el archivo de clave SSH: {path}",
    // Mastertool ortak ayarlar iskeleti (SSH Master ile aynı metinler)
    "set.general": "General",
    "set.account": "Cuenta",
    "set.about": "Acerca de",
    "set.startup": "Inicio",
    "set.openAtLogin": "Iniciar al iniciar sesi\xF3n en Windows",
    "set.openAtLoginHint": "Si minimizar a la bandeja est\xE1 activado, la aplicaci\xF3n se inicia en la bandeja.",
    "set.window": "Ventana",
    "set.minTray": "Mostrar en la bandeja del sistema al minimizar",
    "set.minTrayHint": "Al minimizar, la ventana sale de la barra de tareas y aparece como icono de SQL Master junto al reloj. Haz clic en el icono para restaurarla; clic derecho para conectar r\xE1pidamente.",
    "set.closeTray": "Ocultar en la bandeja al cerrar",
    "set.closeTrayHint": "El bot\xF3n Cerrar (X) oculta la aplicaci\xF3n en la bandeja en lugar de salir. Usa \xABSalir\xBB en el men\xFA de la bandeja para cerrarla.",
    "about.version": "Versi\xF3n {version}",
    "about.family": "Parte de la familia Mastertool: SQL Master \xB7 FTP Masters \xB7 SQL Master \xB7 Notepad Master \xB7 Convert Master",
    "about.checkUpdate": "Buscar actualizaciones",
    "about.checking": "Comprobando\u2026",
    "about.upToDate": "SQL Master est\xE1 actualizado.",
    "about.checkFailed": "No se pudieron buscar actualizaciones: {msg}",
    "about.licenses": "Licencias de c\xF3digo abierto",
    "about.licensesIntro": "SQL Master utiliza los siguientes componentes de c\xF3digo abierto:",
    "about.chromium": "Abrir licencias de Chromium",
    "main.trayShow": "Mostrar SQL Master",
    "main.trayQuick": "Conexi\xF3n r\xE1pida",
    "main.trayNone": "No hay conexiones guardadas",
    "main.trayQuit": "Salir",
    "set.languageHint": "Las ventanas de conexi\xF3n abiertas usar\xE1n el nuevo idioma al volver a abrirse.",
    "about.newVersion": "Nueva versi\xF3n disponible: {version}"
  };

  // src/shared/locales/ar.ts
  var ar = {
    "common.cancel": "\u0625\u0644\u063A\u0627\u0621",
    "common.save": "\u062D\u0641\u0638",
    "common.create": "\u0625\u0646\u0634\u0627\u0621",
    "common.ok": "\u0645\u0648\u0627\u0641\u0642",
    "common.delete": "\u062D\u0630\u0641",
    "common.giveUp": "\u062A\u0631\u0627\u062C\u0639",
    "common.open": "\u0641\u062A\u062D",
    "common.edit": "\u062A\u0639\u062F\u064A\u0644",
    "common.rename": "\u0625\u0639\u0627\u062F\u0629 \u062A\u0633\u0645\u064A\u0629",
    "common.refresh": "\u062A\u062D\u062F\u064A\u062B",
    "common.newFolder": "\u0645\u062C\u0644\u062F \u062C\u062F\u064A\u062F",
    "common.move": "\u0646\u0642\u0644",
    "common.moveEllipsis": "\u0646\u0642\u0644\u2026",
    "common.show": "\u0625\u0638\u0647\u0627\u0631",
    "common.choose": "\u0627\u062E\u062A\u064A\u0627\u0631\u2026",
    "common.connect": "\u0627\u062A\u0635\u0627\u0644",
    "common.folderName": "\u0627\u0633\u0645 \u0627\u0644\u0645\u062C\u0644\u062F",
    "common.copy": "\u0646\u0633\u062E",
    "common.close": "\u0625\u063A\u0644\u0627\u0642",
    "app.searchPh": "\u0627\u0644\u0628\u062D\u062B \u0641\u064A \u0627\u0644\u0627\u062A\u0635\u0627\u0644\u0627\u062A\u2026  (Ctrl+F)",
    "app.newConn": "\u0625\u0636\u0627\u0641\u0629 \u0627\u062A\u0635\u0627\u0644",
    "app.addConn": "\u0625\u0636\u0627\u0641\u0629 \u0627\u062A\u0635\u0627\u0644",
    "app.settings": "\u0627\u0644\u0625\u0639\u062F\u0627\u062F\u0627\u062A",
    "app.stats": "\u0627\u0644\u0627\u062A\u0635\u0627\u0644\u0627\u062A: {c} \xB7 \u0627\u0644\u0645\u062C\u0644\u062F\u0627\u062A: {f}",
    "app.welcome": "\u0645\u0631\u062D\u0628\u064B\u0627",
    "app.results": "\u0646\u062A\u0627\u0626\u062C \xAB{q}\xBB",
    "app.all": "\u0643\u0644 \u0627\u0644\u0627\u062A\u0635\u0627\u0644\u0627\u062A",
    "app.welcomeHint": "\u0627\u062A\u0635\u0644 \u0628\u0640 PostgreSQL \u0623\u0648 SQL Server \u0623\u0648 MySQL \u0623\u0648 SQLite \u0623\u0648 \u0628\u0645\u0644\u0641\u0627\u062A CSV/Parquet/Excel.<br>\u0623\u062F\u062E\u0644 \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A\u060C \u0648\u0627\u062E\u062A\u0628\u0631 \u0627\u0644\u0627\u062A\u0635\u0627\u0644\u060C \u062B\u0645 \u0627\u062D\u0641\u0638\u0647.",
    "app.folders": "\u0627\u0644\u0645\u062C\u0644\u062F\u0627\u062A",
    "app.connections": "\u0627\u0644\u0627\u062A\u0635\u0627\u0644\u0627\u062A",
    "app.dblHint": "\u0627\u0646\u0642\u0631 \u0646\u0642\u0631\u064B\u0627 \u0645\u0632\u062F\u0648\u062C\u064B\u0627 \u0639\u0644\u0649 \u0628\u0637\u0627\u0642\u0629 \u0644\u0641\u062A\u062D\u0647\u0627",
    "app.noMatch": "\u0644\u0627 \u062A\u0648\u062C\u062F \u0627\u062A\u0635\u0627\u0644\u0627\u062A \u0645\u0637\u0627\u0628\u0642\u0629.",
    "app.folderCount": "\u0627\u0644\u0627\u062A\u0635\u0627\u0644\u0627\u062A: {n}",
    "app.newConnHere": "\u0627\u062A\u0635\u0627\u0644 \u062C\u062F\u064A\u062F \u0641\u064A \u0647\u0630\u0627 \u0627\u0644\u0645\u062C\u0644\u062F",
    "app.newSubfolder": "\u0645\u062C\u0644\u062F \u0641\u0631\u0639\u064A \u062C\u062F\u064A\u062F",
    "app.duplicate": "\u062A\u0643\u0631\u0627\u0631",
    "app.moveToFolder": "\u0646\u0642\u0644 \u0625\u0644\u0649 \u0645\u062C\u0644\u062F\u2026",
    "app.connMoved": "\u062A\u0645 \u0646\u0642\u0644 \u0627\u0644\u0627\u062A\u0635\u0627\u0644",
    "app.folderIntoSelf": "\u0644\u0627 \u064A\u0645\u0643\u0646 \u0646\u0642\u0644 \u0645\u062C\u0644\u062F \u0625\u0644\u0649 \u062F\u0627\u062E\u0644 \u0646\u0641\u0633\u0647",
    "app.folderPh": "\u0645\u062B\u0627\u0644: \u0627\u0644\u0639\u0645\u0644\u0627\u0621",
    "app.renameFolder": "\u0625\u0639\u0627\u062F\u0629 \u062A\u0633\u0645\u064A\u0629 \u0627\u0644\u0645\u062C\u0644\u062F",
    "app.deleteFolder": "\u062D\u0630\u0641 \u0627\u0644\u0645\u062C\u0644\u062F",
    "app.deleteFolderMsg": "\u0647\u0644 \u062A\u0631\u064A\u062F \u062D\u0630\u0641 \u0627\u0644\u0645\u062C\u0644\u062F <b>{name}</b>\u061F",
    "app.deleteFolderConns": "<br>\u0633\u062A\u064F\u0646\u0642\u0644 \u0627\u062A\u0635\u0627\u0644\u0627\u062A\u0647 ({n}) \u0625\u0644\u0649 \u0627\u0644\u0645\u062C\u0644\u062F \u0627\u0644\u0623\u0635\u0644.",
    "app.rootFolder": "\u0627\u0644\u0645\u0633\u062A\u0648\u0649 \u0627\u0644\u0623\u0639\u0644\u0649 (\u0628\u062F\u0648\u0646 \u0645\u062C\u0644\u062F)",
    "app.moveTitle": "\u0646\u0642\u0644 \xAB{name}\xBB",
    "app.targetFolder": "\u0627\u0644\u0645\u062C\u0644\u062F \u0627\u0644\u0647\u062F\u0641",
    "app.deleteConn": "\u062D\u0630\u0641 \u0627\u0644\u0627\u062A\u0635\u0627\u0644",
    "app.deleteConnMsg": "\u0647\u0644 \u062A\u0631\u064A\u062F \u062D\u0630\u0641 \u0627\u0644\u0627\u062A\u0635\u0627\u0644 <b>{name}</b> ({target})\u061F \u0633\u062A\u064F\u062D\u0630\u0641 \u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 \u0627\u0644\u0645\u062D\u0641\u0648\u0638\u0629 \u0623\u064A\u0636\u064B\u0627.",
    "app.readOnlyTag": "\u0644\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637",
    "app.writeTag": "\u0642\u0627\u0628\u0644 \u0644\u0644\u0643\u062A\u0627\u0628\u0629",
    "form.titleNew": "\u0627\u062A\u0635\u0627\u0644 \u062C\u062F\u064A\u062F",
    "form.titleEdit": "\u0627\u0644\u0627\u062A\u0635\u0627\u0644: {name}",
    "form.tabGeneral": "\u0639\u0627\u0645",
    "form.tabSecurity": "\u0627\u0644\u0623\u0645\u0627\u0646",
    "form.tabSsh": "\u0646\u0641\u0642 SSH",
    "form.name": "\u0627\u0644\u062A\u0633\u0645\u064A\u0629 (\u0627\u0644\u0627\u0633\u0645 \u0627\u0644\u0645\u0639\u0631\u0648\u0636)",
    "form.namePh": "\u0645\u062B\u0627\u0644: \u0642\u0627\u0639\u062F\u0629 \u0628\u064A\u0627\u0646\u0627\u062A \u0627\u0644\u0625\u0646\u062A\u0627\u062C",
    "form.host": "\u0627\u0644\u0645\u0636\u064A\u0641",
    "form.port": "\u0627\u0644\u0645\u0646\u0641\u0630",
    "form.user": "\u0627\u0633\u0645 \u0627\u0644\u0645\u0633\u062A\u062E\u062F\u0645",
    "form.password": "\u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631",
    "form.pwSaved": "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (\u0645\u062D\u0641\u0648\u0638\u0629\u060C \u0627\u0643\u062A\u0628 \u0644\u062A\u063A\u064A\u064A\u0631\u0647\u0627)",
    "form.database": "\u0642\u0627\u0639\u062F\u0629 \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A",
    "form.databasePh": "\u0627\u062A\u0631\u0643\u0647 \u0641\u0627\u0631\u063A\u064B\u0627 \u0644\u0627\u0633\u062A\u062E\u062F\u0627\u0645 \u0642\u0627\u0639\u062F\u0629 \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A \u0627\u0644\u0627\u0641\u062A\u0631\u0627\u0636\u064A\u0629",
    "form.file": "\u0645\u0644\u0641 \u0642\u0627\u0639\u062F\u0629 \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A",
    "form.filePh": "C:\\Data\\app.db",
    "form.sqliteHint": "\u0645\u0644\u0641 \u0642\u0627\u0639\u062F\u0629 \u0628\u064A\u0627\u0646\u0627\u062A SQLite (.db\u060C .sqlite). \u0641\u064A \u0648\u0636\u0639 \u0627\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637 \u0644\u0627 \u064A\u064F\u0639\u062F\u064E\u0651\u0644 \u0627\u0644\u0645\u0644\u0641 \u0623\u0628\u062F\u064B\u0627.",
    "form.duckdbHint": "\u0627\u062E\u062A\u0631 \u0645\u0644\u0641 .duckdb \u0623\u0648 \u0627\u062A\u0631\u0643\u0647 \u0641\u0627\u0631\u063A\u064B\u0627 (\u0641\u064A \u0627\u0644\u0630\u0627\u0643\u0631\u0629). \u0627\u0633\u062A\u0639\u0644\u0645 \u0645\u0628\u0627\u0634\u0631\u0629 \u0645\u0646 \u0645\u0644\u0641\u0627\u062A CSV \u0648Parquet \u0648JSON \u0648Excel: SELECT * FROM 'C:\\data\\sales.csv'",
    "form.inMemory": "\u0641\u064A \u0627\u0644\u0630\u0627\u0643\u0631\u0629",
    "form.folder": "\u0627\u0644\u0645\u062C\u0644\u062F",
    "form.color": "\u0627\u0644\u0644\u0648\u0646",
    "form.comments": "\u0645\u0644\u0627\u062D\u0638\u0627\u062A",
    "form.readOnly": "\u0648\u0636\u0639 \u0627\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637",
    "form.readOnlyHint": "\u0645\u0648\u0635\u0649 \u0628\u0647. \u062A\u064F\u062D\u0638\u0631 \u0623\u0648\u0627\u0645\u0631 INSERT/UPDATE/DELETE \u0648DDL \u0642\u0628\u0644 \u0627\u0644\u062A\u0646\u0641\u064A\u0630\u060C \u0648\u064A\u0645\u0643\u0646\u0643 \u0627\u0644\u0645\u0648\u0627\u0641\u0642\u0629 \u0639\u0644\u064A\u0647\u0627 \u0644\u0645\u0631\u0629 \u0648\u0627\u062D\u062F\u0629. \u0648\u062D\u064A\u062B\u0645\u0627 \u0643\u0627\u0646 \u0645\u062F\u0639\u0648\u0645\u064B\u0627\u060C \u062A\u0643\u0648\u0646 \u0627\u0644\u062C\u0644\u0633\u0629 \u0646\u0641\u0633\u0647\u0627 \u0644\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637 \u0623\u064A\u0636\u064B\u0627.",
    "form.savePassword": "\u062D\u0641\u0638 \u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631",
    "form.savePasswordHint": "\u062A\u064F\u062E\u0632\u064E\u0651\u0646 \u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 \u0641\u064A \u0633\u0644\u0633\u0644\u0629 \u0645\u0641\u0627\u062A\u064A\u062D \u0646\u0638\u0627\u0645 \u0627\u0644\u062A\u0634\u063A\u064A\u0644 \u0641\u0642\u0637 (Windows: DPAPI). \u0639\u0646\u062F \u0625\u064A\u0642\u0627\u0641 \u0627\u0644\u062E\u064A\u0627\u0631\u060C \u0633\u062A\u064F\u0637\u0644\u0628 \u0645\u0646\u0643 \u0639\u0646\u062F \u0643\u0644 \u0627\u062A\u0635\u0627\u0644.",
    "form.ssl": "TLS / SSL",
    "form.sslPrefer": "\u062A\u0641\u0636\u064A\u0644 (\u0645\u0634\u0641\u0651\u0631 \u0625\u0630\u0627 \u0643\u0627\u0646 \u0627\u0644\u062E\u0627\u062F\u0645 \u064A\u062F\u0639\u0645\u0647)",
    "form.sslRequire": "\u0625\u0644\u0632\u0627\u0645\u064A (\u062F\u0648\u0646 \u0627\u0644\u062A\u062D\u0642\u0642 \u0645\u0646 \u0627\u0644\u0634\u0647\u0627\u062F\u0629)",
    "form.sslVerify": "\u0625\u0644\u0632\u0627\u0645\u064A + \u0627\u0644\u062A\u062D\u0642\u0642 \u0645\u0646 \u0627\u0644\u0634\u0647\u0627\u062F\u0629",
    "form.sslDisable": "\u0625\u064A\u0642\u0627\u0641 (\u063A\u064A\u0631 \u0645\u0634\u0641\u0651\u0631)",
    "form.sslHint": "\u062A\u062A\u0645 \u0645\u062D\u0627\u0648\u0644\u0629 TLS \u0627\u0641\u062A\u0631\u0627\u0636\u064A\u064B\u0627\u060C \u0648\u062A\u064F\u062D\u0630\u0651\u0631\u0643 \u0646\u0627\u0641\u0630\u0629 \u0627\u0644\u0627\u062A\u0635\u0627\u0644 \u0625\u0630\u0627 \u0643\u0627\u0646 \u0627\u0644\u062E\u0627\u062F\u0645 \u0644\u0627 \u064A\u062F\u0639\u0645\u0647.",
    "form.sshEnable": "\u0627\u0644\u0627\u062A\u0635\u0627\u0644 \u0639\u0628\u0631 \u0646\u0641\u0642 SSH",
    "form.sshHint": "\u064A\u062A\u0645 \u0627\u0644\u0648\u0635\u0648\u0644 \u0625\u0644\u0649 \u0642\u0627\u0639\u062F\u0629 \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A \u0639\u0628\u0631 \u062E\u0627\u062F\u0645 SSH \u0623\u0648\u0644\u064B\u0627. \u064A\u064F\u0648\u0635\u0649 \u0628\u0627\u0644\u0645\u0635\u0627\u062F\u0642\u0629 \u0628\u0627\u0644\u0645\u0641\u062A\u0627\u062D.",
    "form.sshHost": "\u062E\u0627\u062F\u0645 SSH",
    "form.sshAuth": "\u0645\u0635\u0627\u062F\u0642\u0629 SSH",
    "form.sshKey": "\u0645\u0641\u062A\u0627\u062D \u062E\u0627\u0635",
    "form.sshAgent": "\u0627\u0644\u0648\u0643\u064A\u0644 (Pageant)",
    "form.keyFile": "\u0645\u0644\u0641 \u0627\u0644\u0645\u0641\u062A\u0627\u062D \u0627\u0644\u062E\u0627\u0635",
    "form.passphrase": "\u0639\u0628\u0627\u0631\u0629 \u0645\u0631\u0648\u0631 \u0627\u0644\u0645\u0641\u062A\u0627\u062D",
    "form.passSaved": "(\u0645\u062D\u0641\u0648\u0638\u0629)",
    "form.passEmpty": "\u0627\u062A\u0631\u0643\u0647 \u0641\u0627\u0631\u063A\u064B\u0627 \u0625\u0646 \u0644\u0645 \u062A\u0648\u062C\u062F",
    "form.sshPassword": "\u0643\u0644\u0645\u0629 \u0645\u0631\u0648\u0631 SSH",
    "form.hostKey": "\u0645\u0641\u062A\u0627\u062D \u0645\u0636\u064A\u0641 SSH: {fp}",
    "form.test": "\u0627\u062E\u062A\u0628\u0627\u0631 \u0627\u0644\u0627\u062A\u0635\u0627\u0644",
    "form.saveConnect": "\u062D\u0641\u0638 \u0648\u0641\u062A\u062D",
    "form.connecting": "\u062C\u0627\u0631\u064D \u0627\u0644\u0627\u062A\u0635\u0627\u0644\u2026",
    "form.testOk": "\u0646\u062C\u062D \u0627\u0644\u0627\u062A\u0635\u0627\u0644",
    "form.testFail": "\u062A\u0639\u0630\u0651\u0631 \u0627\u0644\u0627\u062A\u0635\u0627\u0644",
    "form.testDb": "\u0642\u0627\u0639\u062F\u0629 \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A: {db} \xB7 \u0627\u0644\u0645\u0633\u062A\u062E\u062F\u0645: {user}",
    "form.noTls": "\u062A\u062D\u0630\u064A\u0631: \u0627\u0644\u0627\u062A\u0635\u0627\u0644 \u063A\u064A\u0631 \u0645\u0634\u0641\u0651\u0631 (\u0627\u0644\u062E\u0627\u062F\u0645 \u0644\u0627 \u064A\u062F\u0639\u0645 TLS).",
    "form.saved": "\u062A\u0645 \u062D\u0641\u0638 \u0627\u0644\u0627\u062A\u0635\u0627\u0644",
    "form.changesSaved": "\u062A\u0645 \u062D\u0641\u0638 \u0627\u0644\u062A\u063A\u064A\u064A\u0631\u0627\u062A",
    "set.title": "\u0627\u0644\u0625\u0639\u062F\u0627\u062F\u0627\u062A",
    "set.appearance": "\u0627\u0644\u0645\u0638\u0647\u0631",
    "set.theme": "\u0627\u0644\u0633\u0645\u0629",
    "set.themeDark": "\u0644\u064A\u0644\u064A",
    "set.themeLight": "\u0646\u0647\u0627\u0631\u064A",
    "set.themeSystem": "\u062D\u0633\u0628 \u0627\u0644\u0646\u0638\u0627\u0645",
    "set.language": "\u0627\u0644\u0644\u063A\u0629",
    "set.toLight": "\u0627\u0644\u062A\u0628\u062F\u064A\u0644 \u0625\u0644\u0649 \u0627\u0644\u0633\u0645\u0629 \u0627\u0644\u0646\u0647\u0627\u0631\u064A\u0629",
    "set.toDark": "\u0627\u0644\u062A\u0628\u062F\u064A\u0644 \u0625\u0644\u0649 \u0627\u0644\u0633\u0645\u0629 \u0627\u0644\u0644\u064A\u0644\u064A\u0629",
    "set.saved": "\u062A\u0645 \u062D\u0641\u0638 \u0627\u0644\u0625\u0639\u062F\u0627\u062F\u0627\u062A",
    "set.query": "\u0627\u0644\u0627\u0633\u062A\u0639\u0644\u0627\u0645\u0627\u062A",
    "set.rowLimit": "\u0627\u0644\u062D\u062F \u0627\u0644\u0623\u0642\u0635\u0649 \u0644\u0644\u0635\u0641\u0648\u0641 \u0641\u064A \u0643\u0644 \u0646\u062A\u064A\u062C\u0629",
    "set.previewRows": "\u0639\u062F\u062F \u0627\u0644\u0635\u0641\u0648\u0641 \u0627\u0644\u0645\u0639\u0631\u0648\u0636\u0629 \u0639\u0646\u062F \u0641\u062A\u062D \u062C\u062F\u0648\u0644",
    "set.fontSize": "\u062D\u062C\u0645 \u062E\u0637 \u0627\u0644\u0645\u062D\u0631\u0631 (px)",
    "auth.subtitle": "\u0633\u062C\u0651\u0644 \u0627\u0644\u062F\u062E\u0648\u0644 \u0628\u062D\u0633\u0627\u0628 Mastertool",
    "auth.email": "\u0627\u0644\u0628\u0631\u064A\u062F \u0627\u0644\u0625\u0644\u0643\u062A\u0631\u0648\u0646\u064A",
    "auth.password": "\u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631",
    "auth.remember": "\u062A\u0630\u0643\u0651\u0631\u0646\u064A",
    "auth.forgot": "\u0646\u0633\u064A\u062A \u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631",
    "auth.noAccount": "\u0644\u064A\u0633 \u0644\u062F\u064A\u0643 \u062D\u0633\u0627\u0628\u061F",
    "auth.register": "\u0625\u0646\u0634\u0627\u0621 \u062D\u0633\u0627\u0628",
    "auth.submit": "\u062A\u0633\u062C\u064A\u0644 \u0627\u0644\u062F\u062E\u0648\u0644",
    "auth.working": "\u062C\u0627\u0631\u064D \u062A\u0633\u062C\u064A\u0644 \u0627\u0644\u062F\u062E\u0648\u0644\u2026",
    "auth.errRequired": "\u0627\u0644\u0628\u0631\u064A\u062F \u0627\u0644\u0625\u0644\u0643\u062A\u0631\u0648\u0646\u064A \u0648\u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 \u0645\u0637\u0644\u0648\u0628\u0627\u0646.",
    "auth.errBadCredentials": "\u0627\u0644\u0628\u0631\u064A\u062F \u0627\u0644\u0625\u0644\u0643\u062A\u0631\u0648\u0646\u064A \u0623\u0648 \u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 \u063A\u064A\u0631 \u0635\u062D\u064A\u062D\u0629.",
    "auth.errUnverified": "\u0644\u0645 \u064A\u062A\u0645 \u0627\u0644\u062A\u062D\u0642\u0642 \u0645\u0646 \u0628\u0631\u064A\u062F\u0643 \u0627\u0644\u0625\u0644\u0643\u062A\u0631\u0648\u0646\u064A \u0628\u0639\u062F. \u0627\u0646\u0642\u0631 \u0627\u0644\u0631\u0627\u0628\u0637 \u0641\u064A \u0635\u0646\u062F\u0648\u0642 \u0627\u0644\u0648\u0627\u0631\u062F.",
    "auth.errSuspended": "\u062D\u0633\u0627\u0628\u0643 \u0645\u0648\u0642\u0648\u0641.",
    "auth.errRateLimited": "\u0645\u062D\u0627\u0648\u0644\u0627\u062A \u0643\u062B\u064A\u0631\u0629 \u062C\u062F\u064B\u0627. \u062D\u0627\u0648\u0644 \u0645\u062C\u062F\u062F\u064B\u0627 \u0628\u0639\u062F \u062F\u0642\u064A\u0642\u0629.",
    "auth.errOffline": "\u062A\u0639\u0630\u0651\u0631 \u0627\u0644\u0648\u0635\u0648\u0644 \u0625\u0644\u0649 \u0627\u0644\u062E\u0627\u062F\u0645. \u062A\u062D\u0642\u0651\u0642 \u0645\u0646 \u0627\u062A\u0635\u0627\u0644\u0643 \u0628\u0627\u0644\u0625\u0646\u062A\u0631\u0646\u062A.",
    "auth.errSessionExpired": "\u0627\u0646\u062A\u0647\u062A \u062C\u0644\u0633\u062A\u0643 \u0623\u0648 \u062A\u063A\u064A\u0651\u0631\u062A \u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631. \u064A\u0631\u062C\u0649 \u062A\u0633\u062C\u064A\u0644 \u0627\u0644\u062F\u062E\u0648\u0644 \u0645\u062C\u062F\u062F\u064B\u0627.",
    "auth.signedOutElsewhere": "\u062A\u0645 \u062A\u0633\u062C\u064A\u0644 \u0627\u0644\u062E\u0631\u0648\u062C \u0641\u064A \u062A\u0637\u0628\u064A\u0642 Mastertool \u0622\u062E\u0631. \u0644\u0627 \u062A\u0632\u0627\u0644 \u0627\u062A\u0635\u0627\u0644\u0627\u062A\u0643 \u0627\u0644\u0645\u062D\u0644\u064A\u0629 \u0639\u0644\u0649 \u0647\u0630\u0627 \u0627\u0644\u0643\u0645\u0628\u064A\u0648\u062A\u0631.",
    "auth.errAppDisabled": "\u062A\u0645 \u062A\u0639\u0637\u064A\u0644 SQL Master \u0644\u062D\u0633\u0627\u0628\u0643. \u0627\u0644\u062F\u0639\u0645: mastertool.download > \u062D\u0633\u0627\u0628\u064A > \u0627\u0644\u062F\u0639\u0645.",
    "auth.errWrongApp": "\u0647\u0630\u0647 \u0627\u0644\u062C\u0644\u0633\u0629 \u062A\u062E\u0635 \u062A\u0637\u0628\u064A\u0642\u064B\u0627 \u0622\u062E\u0631. \u064A\u0631\u062C\u0649 \u062A\u0633\u062C\u064A\u0644 \u0627\u0644\u062F\u062E\u0648\u0644 \u0625\u0644\u0649 SQL Master \u0645\u062C\u062F\u062F\u064B\u0627.",
    "auth.errServer": "\u062A\u0639\u0630\u0651\u0631 \u062A\u0633\u062C\u064A\u0644 \u0627\u0644\u062F\u062E\u0648\u0644: {msg}",
    "auth.devNotice": "\u0648\u0636\u0639 \u0627\u0644\u062A\u0637\u0648\u064A\u0631: \u064A\u064F\u0633\u062A\u062E\u062F\u0645 \u062D\u0633\u0627\u0628 \u0645\u062D\u0644\u064A \u0628\u062F\u0644\u064B\u0627 \u0645\u0646 \u062E\u0627\u062F\u0645 Mastertool (\u0623\u064A \u0628\u0631\u064A\u062F \u0625\u0644\u0643\u062A\u0631\u0648\u0646\u064A/\u0643\u0644\u0645\u0629 \u0645\u0631\u0648\u0631\u060C \u062F\u0648\u0646 \u0645\u0632\u0627\u0645\u0646\u0629).",
    "acct.section": "\u0627\u0644\u062D\u0633\u0627\u0628 \u0648\u0627\u0644\u0645\u0632\u0627\u0645\u0646\u0629",
    "acct.signedInAs": "\u0645\u0633\u062C\u0651\u0644 \u0627\u0644\u062F\u062E\u0648\u0644 \u0628\u0627\u0633\u0645 {email}",
    "acct.syncToggle": "\u0645\u0632\u0627\u0645\u0646\u0629 \u0645\u0643\u062A\u0628\u0629 \u0627\u0644\u0627\u062A\u0635\u0627\u0644\u0627\u062A \u0645\u0639 \u0627\u0644\u0648\u064A\u0628",
    "acct.syncHint": "\u062A\u064F\u0646\u0633\u062E \u0627\u0644\u0627\u062A\u0635\u0627\u0644\u0627\u062A \u0648\u0627\u0644\u0645\u062C\u0644\u062F\u0627\u062A \u0648\u0627\u0644\u0625\u0639\u062F\u0627\u062F\u0627\u062A \u0627\u0644\u0639\u0627\u0645\u0629 \u0627\u062D\u062A\u064A\u0627\u0637\u064A\u064B\u0627 \u0625\u0644\u0649 \u062D\u0633\u0627\u0628 Mastertool \u0628\u062A\u0634\u0641\u064A\u0631 \u0645\u0646 \u0637\u0631\u0641 \u0625\u0644\u0649 \u0637\u0631\u0641\u061B \u0644\u0627 \u062A\u0646\u062A\u0642\u0644 \u0643\u0644\u0645\u0627\u062A \u0627\u0644\u0645\u0631\u0648\u0631 \u0625\u0644\u0627 \u062F\u0627\u062E\u0644 \u0627\u0644\u062D\u0632\u0645\u0629 \u0627\u0644\u0645\u0634\u0641\u0651\u0631\u0629\u060C \u0648\u0644\u0627 \u064A\u0633\u062A\u0637\u064A\u0639 \u0627\u0644\u062E\u0627\u062F\u0645 \u0642\u0631\u0627\u0621\u062A\u0647\u0627.",
    "acct.lastSync": "\u0622\u062E\u0631 \u0645\u0632\u0627\u0645\u0646\u0629: {time}",
    "acct.never": "\u0644\u0645 \u062A\u062A\u0645 \u0627\u0644\u0645\u0632\u0627\u0645\u0646\u0629 \u0628\u0639\u062F",
    "acct.syncNow": "\u0645\u0632\u0627\u0645\u0646\u0629 \u0627\u0644\u0622\u0646",
    "acct.deleteRemote": "\u062D\u0630\u0641 \u0627\u0644\u0646\u0633\u062E\u0629 \u0639\u0644\u0649 \u0627\u0644\u062E\u0627\u062F\u0645",
    "acct.deleteRemoteMsg": "\u0633\u064A\u062A\u0645 \u062D\u0630\u0641 \u0646\u0633\u062E\u0629 \u0627\u0644\u0645\u0643\u062A\u0628\u0629 \u0627\u0644\u0645\u0634\u0641\u0651\u0631\u0629 \u0641\u064A \u062D\u0633\u0627\u0628\u0643 \u0648\u0625\u064A\u0642\u0627\u0641 \u0627\u0644\u0645\u0632\u0627\u0645\u0646\u0629. \u0644\u0646 \u062A\u064F\u062D\u0630\u0641 \u0627\u0644\u0627\u062A\u0635\u0627\u0644\u0627\u062A \u0627\u0644\u0645\u0648\u062C\u0648\u062F\u0629 \u0639\u0644\u0649 \u0647\u0630\u0627 \u0627\u0644\u0643\u0645\u0628\u064A\u0648\u062A\u0631.",
    "acct.deleteRemoteDone": "\u062D\u064F\u0630\u0641\u062A \u0627\u0644\u0646\u0633\u062E\u0629 \u0639\u0644\u0649 \u0627\u0644\u062E\u0627\u062F\u0645 \u0648\u0623\u064F\u0648\u0642\u0641\u062A \u0627\u0644\u0645\u0632\u0627\u0645\u0646\u0629",
    "acct.logout": "\u062A\u0633\u062C\u064A\u0644 \u0627\u0644\u062E\u0631\u0648\u062C",
    "acct.logoutMsg": "\u0633\u064A\u062A\u0645 \u062A\u0633\u062C\u064A\u0644 \u062E\u0631\u0648\u062C\u0643\u060C \u0648\u0633\u062A\u064F\u063A\u0644\u0642 \u0646\u0648\u0627\u0641\u0630 \u0627\u0644\u0627\u062A\u0635\u0627\u0644 \u0627\u0644\u0645\u0641\u062A\u0648\u062D\u0629 \u0648\u0627\u0644\u0627\u0633\u062A\u0639\u0644\u0627\u0645\u0627\u062A \u0627\u0644\u062C\u0627\u0631\u064A\u0629. \u0644\u0646 \u062A\u064F\u062D\u0630\u0641 \u0627\u0644\u0627\u062A\u0635\u0627\u0644\u0627\u062A \u0627\u0644\u0645\u0648\u062C\u0648\u062F\u0629 \u0639\u0644\u0649 \u0647\u0630\u0627 \u0627\u0644\u0643\u0645\u0628\u064A\u0648\u062A\u0631.",
    "acct.myAccount": "\u062D\u0633\u0627\u0628\u064A (\u0627\u0644\u0648\u064A\u0628)",
    "acct.backupNotice": "\u062A\u0645 \u062A\u0633\u062C\u064A\u0644 \u0627\u0644\u062F\u062E\u0648\u0644 \u0628\u062D\u0633\u0627\u0628 \u0645\u062E\u062A\u0644\u0641\u061B \u062A\u0645 \u0627\u0644\u0627\u062D\u062A\u0641\u0627\u0638 \u0628\u0646\u0633\u062E\u0629 \u0627\u062D\u062A\u064A\u0627\u0637\u064A\u0629 \u0645\u0646 \u0627\u0644\u0627\u062A\u0635\u0627\u0644\u0627\u062A \u0627\u0644\u0633\u0627\u0628\u0642\u0629 \u0639\u0644\u0649 \u0647\u0630\u0627 \u0627\u0644\u0643\u0645\u0628\u064A\u0648\u062A\u0631.",
    "sync.off": "\u0627\u0644\u0645\u0632\u0627\u0645\u0646\u0629 \u0645\u062A\u0648\u0642\u0641\u0629",
    "sync.syncing": "\u062C\u0627\u0631\u064D \u0627\u0644\u0645\u0632\u0627\u0645\u0646\u0629\u2026",
    "sync.offline": "\u063A\u064A\u0631 \u0645\u062A\u0635\u0644 \u2014 \u0633\u062A\u064F\u0631\u0633\u064E\u0644 \u0627\u0644\u062A\u063A\u064A\u064A\u0631\u0627\u062A \u0639\u0646\u062F \u0639\u0648\u062F\u0629 \u0627\u0644\u0627\u062A\u0635\u0627\u0644",
    "sync.errDecrypt": "\u062A\u0639\u0630\u0651\u0631 \u0641\u0643 \u062A\u0634\u0641\u064A\u0631 \u0627\u0644\u0646\u0633\u062E\u0629 \u0639\u0644\u0649 \u0627\u0644\u062E\u0627\u062F\u0645 \u0628\u0645\u0641\u062A\u0627\u062D \u0647\u0630\u0627 \u0627\u0644\u062D\u0633\u0627\u0628\u061B \u0627\u0644\u0627\u062A\u0635\u0627\u0644\u0627\u062A \u0639\u0644\u0649 \u0647\u0630\u0627 \u0627\u0644\u0643\u0645\u0628\u064A\u0648\u062A\u0631 \u0645\u062D\u0641\u0648\u0638\u0629.",
    "sync.errTooLarge": "\u062A\u062A\u062C\u0627\u0648\u0632 \u0627\u0644\u0645\u0643\u062A\u0628\u0629 \u062D\u062F 5 \u0645\u064A\u063A\u0627\u0628\u0627\u064A\u062A \u0648\u0644\u0645 \u062A\u062A\u0645 \u0645\u0632\u0627\u0645\u0646\u062A\u0647\u0627.",
    "sync.error": "\u062E\u0637\u0623 \u0641\u064A \u0627\u0644\u0645\u0632\u0627\u0645\u0646\u0629: {msg}",
    "sync.devMode": "\u0648\u0636\u0639 \u0627\u0644\u062A\u0637\u0648\u064A\u0631 \u2014 \u062F\u0648\u0646 \u0645\u0632\u0627\u0645\u0646\u0629",
    "update.available": "\u064A\u062A\u0648\u0641\u0631 \u0625\u0635\u062F\u0627\u0631 \u062C\u062F\u064A\u062F: {version}",
    "update.hint": "\u0646\u0632\u0651\u0644\u0647 \u0645\u0646 \u062D\u0633\u0627\u0628\u0643 \u0639\u0644\u0649 Mastertool.",
    "update.open": "\u0641\u062A\u062D \u062D\u0633\u0627\u0628\u064A",
    "cw.objects": "\u0627\u0644\u0643\u0627\u0626\u0646\u0627\u062A",
    "cw.collapseAll": "\u0637\u064A \u0627\u0644\u0643\u0644",
    "cw.filterPh": "\u062A\u0635\u0641\u064A\u0629 \u0627\u0644\u0643\u0627\u0626\u0646\u0627\u062A \u0627\u0644\u0645\u062D\u0645\u0651\u0644\u0629\u2026",
    "cw.empty": "(\u0641\u0627\u0631\u063A)",
    "cw.openData": "\u0641\u062A\u062D \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A",
    "cw.showDdl": "\u0639\u0631\u0636 DDL",
    "cw.openCode": "\u0641\u062A\u062D \u0627\u0644\u0634\u064A\u0641\u0631\u0629",
    "cw.selectSql": "\u0625\u0646\u0634\u0627\u0621 SELECT",
    "cw.addToBuilder": "\u0625\u0636\u0627\u0641\u0629 \u0625\u0644\u0649 \u0645\u0646\u0634\u0626 \u0627\u0644\u0627\u0633\u062A\u0639\u0644\u0627\u0645\u0627\u062A",
    "cw.newSqlHere": "SQL \u062C\u062F\u064A\u062F \u0647\u0646\u0627",
    "cw.copyName": "\u0646\u0633\u062E \u0627\u0644\u0627\u0633\u0645",
    "cw.copied": "\u062A\u0645 \u0627\u0644\u0646\u0633\u062E \u0625\u0644\u0649 \u0627\u0644\u062D\u0627\u0641\u0638\u0629",
    "cw.newSql": "SQL \u062C\u062F\u064A\u062F",
    "cw.builder": "\u0645\u0646\u0634\u0626 \u0627\u0644\u0627\u0633\u062A\u0639\u0644\u0627\u0645\u0627\u062A",
    "cw.reconnect": "\u0625\u0639\u0627\u062F\u0629 \u0627\u0644\u0627\u062A\u0635\u0627\u0644",
    "cw.readOnly": "\u0644\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637",
    "cw.readWrite": "\u0627\u0644\u0643\u062A\u0627\u0628\u0629 \u0645\u0641\u0639\u0651\u0644\u0629",
    "cw.readOnlyTip": "\u0644\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637: \u0623\u0648\u0627\u0645\u0631 DML/DDL \u062A\u062D\u062A\u0627\u062C \u0625\u0644\u0649 \u0645\u0648\u0627\u0641\u0642\u0629. \u0627\u0646\u0642\u0631 \u0644\u0644\u0625\u064A\u0642\u0627\u0641",
    "cw.readWriteTip": "\u0627\u0644\u0643\u062A\u0627\u0628\u0629 \u0645\u0641\u0639\u0651\u0644\u0629: \u062A\u064F\u0646\u0641\u064E\u0651\u0630 \u0627\u0644\u0623\u0648\u0627\u0645\u0631 \u062F\u0648\u0646 \u0645\u0648\u0627\u0641\u0642\u0629. \u0627\u0646\u0642\u0631 \u0644\u0644\u0639\u0648\u062F\u0629 \u0625\u0644\u0649 \u0627\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637",
    "cw.disableRo": "\u0625\u064A\u0642\u0627\u0641 \u0648\u0636\u0639 \u0627\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637\u061F",
    "cw.disableRoMsg": "\u062D\u062A\u0649 \u0625\u063A\u0644\u0627\u0642 \u0647\u0630\u0647 \u0627\u0644\u0646\u0627\u0641\u0630\u0629\u060C \u0633\u062A\u064F\u0646\u0641\u064E\u0651\u0630 \u0623\u0648\u0627\u0645\u0631 INSERT/UPDATE/DELETE \u0648DDL \u062F\u0648\u0646 \u0633\u0624\u0627\u0644.",
    "cw.disableRoOk": "\u0627\u0644\u0633\u0645\u0627\u062D \u0628\u0627\u0644\u0643\u062A\u0627\u0628\u0629",
    "cw.roOn": "\u0648\u0636\u0639 \u0627\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637 \u0645\u0641\u0639\u0651\u0644",
    "cw.roOff": "\u0627\u0644\u0643\u062A\u0627\u0628\u0629 \u0645\u0633\u0645\u0648\u062D\u0629 \u2014 \u0643\u0646 \u062D\u0630\u0631\u064B\u0627",
    "cw.passwordTitle": "\u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 \u0645\u0637\u0644\u0648\u0628\u0629",
    "cw.passwordFor": "\u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 \u0644\u0640 {user}@{host}",
    "cw.notConnected": "\u063A\u064A\u0631 \u0645\u062A\u0635\u0644",
    "cw.connected": "\u0645\u062A\u0635\u0644",
    "cw.connecting": "\u062C\u0627\u0631\u064D \u0627\u0644\u0627\u062A\u0635\u0627\u0644\u2026",
    "cw.noTls": "\u063A\u064A\u0631 \u0645\u0634\u0641\u0651\u0631",
    "cw.connectFailed": "\u062A\u0639\u0630\u0651\u0631 \u0627\u0644\u0627\u062A\u0635\u0627\u0644",
    "cw.retry": "\u0625\u0639\u0627\u062F\u0629 \u0627\u0644\u0645\u062D\u0627\u0648\u0644\u0629",
    "cw.resetCancel": "\u0644\u0645 \u064A\u0633\u062A\u062C\u0628 \u0627\u0644\u0627\u0633\u062A\u0639\u0644\u0627\u0645 \u0644\u0644\u0625\u0644\u063A\u0627\u0621\u061B \u062C\u0627\u0631\u064D \u0625\u0639\u0627\u062F\u0629 \u0627\u0644\u0627\u062A\u0635\u0627\u0644.",
    "cw.resetExit": "\u0627\u0646\u0642\u0637\u0639 \u0627\u0644\u0627\u062A\u0635\u0627\u0644 \u0628\u0642\u0627\u0639\u062F\u0629 \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A\u061B \u062C\u0627\u0631\u064D \u0625\u0639\u0627\u062F\u0629 \u0627\u0644\u0627\u062A\u0635\u0627\u0644.",
    "cw.emptyWorkspace": "\u0627\u0646\u0642\u0631 \u0646\u0642\u0631\u064B\u0627 \u0645\u0632\u062F\u0648\u062C\u064B\u0627 \u0639\u0644\u0649 \u062C\u062F\u0648\u0644 \u0641\u064A \u0627\u0644\u0634\u062C\u0631\u0629 \u0623\u0648 \u0627\u0636\u063A\u0637 Ctrl+T \u0644\u0641\u062A\u062D \u0639\u0644\u0627\u0645\u0629 \u062A\u0628\u0648\u064A\u0628 SQL \u062C\u062F\u064A\u062F\u0629.",
    "cw.closeTab": "\u0625\u063A\u0644\u0627\u0642 \u0639\u0644\u0627\u0645\u0629 \u0627\u0644\u062A\u0628\u0648\u064A\u0628\u061F",
    "cw.closeTabMsg": "\u0644\u0645 \u064A\u062A\u0645 \u062D\u0641\u0638 SQL \u0641\u064A \xAB{name}\xBB.",
    "cw.closeTabOk": "\u0625\u063A\u0644\u0627\u0642",
    "tree.tables": "\u0627\u0644\u062C\u062F\u0627\u0648\u0644",
    "tree.views": "\u0637\u0631\u0642 \u0627\u0644\u0639\u0631\u0636",
    "tree.matviews": "\u0637\u0631\u0642 \u0627\u0644\u0639\u0631\u0636 \u0627\u0644\u0645\u0627\u062F\u064A\u0629",
    "tree.foreign_tables": "\u0627\u0644\u062C\u062F\u0627\u0648\u0644 \u0627\u0644\u062E\u0627\u0631\u062C\u064A\u0629",
    "tree.functions": "\u0627\u0644\u062F\u0648\u0627\u0644",
    "tree.procedures": "\u0627\u0644\u0625\u062C\u0631\u0627\u0621\u0627\u062A",
    "tree.triggers": "\u0627\u0644\u0645\u0634\u063A\u0651\u0644\u0627\u062A",
    "tree.sequences": "\u0627\u0644\u062A\u0633\u0644\u0633\u0644\u0627\u062A",
    "tree.types": "\u0627\u0644\u0623\u0646\u0648\u0627\u0639",
    "tree.columns": "\u0627\u0644\u0623\u0639\u0645\u062F\u0629",
    "tree.indexes": "\u0627\u0644\u0641\u0647\u0627\u0631\u0633",
    "tree.constraints": "\u0627\u0644\u0642\u064A\u0648\u062F",
    "tree.files": "\u0627\u0644\u0645\u0644\u0641\u0627\u062A",
    "kind.table": "\u062C\u062F\u0648\u0644",
    "kind.view": "\u0637\u0631\u064A\u0642\u0629 \u0639\u0631\u0636",
    "kind.matview": "\u0637\u0631\u064A\u0642\u0629 \u0639\u0631\u0636 \u0645\u0627\u062F\u064A\u0629",
    "kind.foreign-table": "\u062C\u062F\u0648\u0644 \u062E\u0627\u0631\u062C\u064A",
    "kind.function": "\u062F\u0627\u0644\u0629",
    "kind.procedure": "\u0625\u062C\u0631\u0627\u0621",
    "kind.trigger": "\u0645\u0634\u063A\u0651\u0644",
    "kind.sequence": "\u062A\u0633\u0644\u0633\u0644",
    "kind.type": "\u0646\u0648\u0639",
    "kind.index": "\u0641\u0647\u0631\u0633",
    "kind.constraint": "\u0642\u064A\u062F",
    "sql.run": "\u062A\u0634\u063A\u064A\u0644",
    "sql.runStatement": "\u062A\u0634\u063A\u064A\u0644 \u0627\u0644\u0639\u0628\u0627\u0631\u0629",
    "sql.cancel": "\u0625\u0644\u063A\u0627\u0621",
    "sql.database": "\u0642\u0627\u0639\u062F\u0629 \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A",
    "sql.history": "\u0627\u0644\u0633\u062C\u0644",
    "sql.export": "\u062A\u0635\u062F\u064A\u0631",
    "sql.running": "\u062C\u0627\u0631\u064D \u0627\u0644\u062A\u0634\u063A\u064A\u0644\u2026",
    "sql.done": "\u0627\u0643\u062A\u0645\u0644 \xB7 {ms} ms",
    "sql.doneErrors": "\u0627\u0644\u0623\u062E\u0637\u0627\u0621: {n} \xB7 {ms} ms",
    "sql.ddlHint": "\u062A\u063A\u064A\u0651\u0631 \u0627\u0644\u0645\u062E\u0637\u0637: \u0627\u0633\u062A\u062E\u062F\u0645 \xAB\u062A\u062D\u062F\u064A\u062B\xBB \u0644\u0625\u0639\u0627\u062F\u0629 \u062A\u062D\u0645\u064A\u0644 \u0627\u0644\u0634\u062C\u0631\u0629.",
    "sql.placeholder": "\u0627\u0643\u062A\u0628 SQL\u2026 Ctrl+Enter: \u062A\u0634\u063A\u064A\u0644 \u0627\u0644\u0645\u062D\u062F\u062F/\u0627\u0644\u0643\u0644 \xB7 Ctrl+Shift+Enter: \u0627\u0644\u0639\u0628\u0627\u0631\u0629 \u0639\u0646\u062F \u0627\u0644\u0645\u0624\u0634\u0631 \xB7 Ctrl+Space: \u0627\u0644\u0625\u0643\u0645\u0627\u0644",
    "sql.tabTitle": "SQL {n}",
    "sql.historyEmpty": "\u0644\u0627 \u064A\u0648\u062C\u062F \u0633\u062C\u0644 \u0644\u0647\u0630\u0627 \u0627\u0644\u0627\u062A\u0635\u0627\u0644.",
    "sql.rowsShort": "\u0635\u0641\u0648\u0641",
    "res.result": "\u0627\u0644\u0646\u062A\u064A\u062C\u0629 {n}",
    "res.messages": "\u0627\u0644\u0631\u0633\u0627\u0626\u0644",
    "res.rows": "\u0627\u0644\u0635\u0641\u0648\u0641: {n} \xB7 {ms} ms",
    "res.rowsTruncated": "\u0639\u0631\u0636 \u0623\u0648\u0644 {n} \u0635\u0641 (\u0627\u0644\u062D\u062F) \xB7 {ms} ms",
    "res.noRows": "\u0644\u0627 \u062A\u0648\u062C\u062F \u0635\u0641\u0648\u0641",
    "res.affected": "{cmd}: \u0627\u0644\u0635\u0641\u0648\u0641 \u0627\u0644\u0645\u062A\u0623\u062B\u0631\u0629: {n} \xB7 {ms} ms",
    "res.command": "{cmd} \xB7 {ms} ms",
    "res.cancelled": "\u0623\u064F\u0644\u063A\u064A",
    "grid.copy": "\u0646\u0633\u062E",
    "grid.copyHeaders": "\u0646\u0633\u062E \u0645\u0639 \u0627\u0644\u0639\u0646\u0627\u0648\u064A\u0646",
    "grid.export": "\u062A\u0635\u062F\u064A\u0631 \u0647\u0630\u0647 \u0627\u0644\u0646\u062A\u064A\u062C\u0629\u2026",
    "data.columns": "\u0627\u0644\u0623\u0639\u0645\u062F\u0629",
    "data.columnsHidden": "\u0627\u0644\u0623\u0639\u0645\u062F\u0629 ({n}/{total})",
    "data.addFilter": "\u062A\u0635\u0641\u064A\u0629",
    "data.limit": "\u0639\u062F\u062F \u0627\u0644\u0635\u0641\u0648\u0641",
    "data.firstN": "\u0623\u0648\u0644 {n}",
    "data.all": "\u0627\u0644\u0643\u0644 (\u0645\u062D\u062F\u0648\u062F)",
    "data.openInEditor": "\u0641\u062A\u062D \u0641\u064A \u0645\u062D\u0631\u0631 SQL",
    "data.clearFilters": "\u0645\u0633\u062D \u0639\u0648\u0627\u0645\u0644 \u0627\u0644\u062A\u0635\u0641\u064A\u0629",
    "data.rows": "\u0627\u0644\u0635\u0641\u0648\u0641: {n} \xB7 {ms} ms",
    "data.rowsMore": "\u0623\u0648\u0644 {n} \u0635\u0641 \xB7 {ms} ms",
    "data.error": "\u062A\u0639\u0630\u0651\u0631 \u062A\u062D\u0645\u064A\u0644 \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A",
    "data.sortAsc": "\u0641\u0631\u0632 \u062A\u0635\u0627\u0639\u062F\u064A",
    "data.sortDesc": "\u0641\u0631\u0632 \u062A\u0646\u0627\u0632\u0644\u064A",
    "data.sortClear": "\u0645\u0633\u062D \u0627\u0644\u0641\u0631\u0632",
    "data.filterColumn": "\u0627\u0644\u062A\u0635\u0641\u064A\u0629 \u062D\u0633\u0628 \u0647\u0630\u0627 \u0627\u0644\u0639\u0645\u0648\u062F\u2026",
    "data.hideColumn": "\u0625\u062E\u0641\u0627\u0621 \u0627\u0644\u0639\u0645\u0648\u062F",
    "data.showAll": "\u0625\u0638\u0647\u0627\u0631 \u0643\u0644 \u0627\u0644\u0623\u0639\u0645\u062F\u0629",
    "data.filterEq": "\u064A\u0633\u0627\u0648\u064A \xAB{v}\xBB",
    "data.filterNe": "\u0644\u0627 \u064A\u0633\u0627\u0648\u064A \xAB{v}\xBB",
    "data.filterNull": "NULL / \u0644\u064A\u0633 NULL",
    "data.column": "\u0627\u0644\u0639\u0645\u0648\u062F",
    "data.operator": "\u0627\u0644\u0634\u0631\u0637",
    "data.value": "\u0627\u0644\u0642\u064A\u0645\u0629",
    "data.inHint": "\u0641\u064A \xAB\u0636\u0645\u0646 \u0627\u0644\u0642\u0627\u0626\u0645\u0629\xBB\u060C \u0627\u0641\u0635\u0644 \u0627\u0644\u0642\u064A\u0645 \u0628\u0641\u0648\u0627\u0635\u0644.",
    "data.filterTitle": "\u062A\u0635\u0641\u064A\u0629",
    "data.selectAll": "\u0627\u0644\u0643\u0644",
    "data.selectNone": "\u0644\u0627 \u0634\u064A\u0621",
    "op.=": "\u064A\u0633\u0627\u0648\u064A",
    "op.<>": "\u0644\u0627 \u064A\u0633\u0627\u0648\u064A",
    "op.<": "\u0623\u0635\u063A\u0631 \u0645\u0646",
    "op.>": "\u0623\u0643\u0628\u0631 \u0645\u0646",
    "op.<=": "\u0623\u0635\u063A\u0631 \u0645\u0646 \u0623\u0648 \u064A\u0633\u0627\u0648\u064A",
    "op.>=": "\u0623\u0643\u0628\u0631 \u0645\u0646 \u0623\u0648 \u064A\u0633\u0627\u0648\u064A",
    "op.contains": "\u064A\u062D\u062A\u0648\u064A \u0639\u0644\u0649",
    "op.not contains": "\u0644\u0627 \u064A\u062D\u062A\u0648\u064A \u0639\u0644\u0649",
    "op.starts": "\u064A\u0628\u062F\u0623 \u0628\u0640",
    "op.ends": "\u064A\u0646\u062A\u0647\u064A \u0628\u0640",
    "op.like": "LIKE",
    "op.not like": "NOT LIKE",
    "op.in": "\u0636\u0645\u0646 \u0627\u0644\u0642\u0627\u0626\u0645\u0629",
    "op.not in": "\u0644\u064A\u0633 \u0636\u0645\u0646 \u0627\u0644\u0642\u0627\u0626\u0645\u0629",
    "op.is null": "\u0647\u0648 NULL",
    "op.is not null": "\u0644\u064A\u0633 NULL",
    "code.execute": "\u062A\u0646\u0641\u064A\u0630",
    "code.loading": "\u062C\u0627\u0631\u064D \u0627\u0644\u062A\u062D\u0645\u064A\u0644\u2026",
    "code.empty": "\u0644\u0645 \u064A\u064F\u0639\u062B\u0631 \u0639\u0644\u0649 \u062A\u0639\u0631\u064A\u0641",
    "qb.addTable": "\u0625\u0636\u0627\u0641\u0629 \u062C\u062F\u0648\u0644",
    "qb.limit": "\u0627\u0644\u062D\u062F",
    "qb.clear": "\u0645\u0633\u062D",
    "qb.hint": "\u0627\u0633\u062D\u0628 \u0627\u0644\u062C\u062F\u0627\u0648\u0644 \u0625\u0644\u0649 \u0647\u0646\u0627 \u0645\u0646 \u0627\u0644\u0634\u062C\u0631\u0629 \u0623\u0648 \u0627\u0646\u0642\u0631 \xAB\u0625\u0636\u0627\u0641\u0629 \u062C\u062F\u0648\u0644\xBB. \u0627\u0633\u062D\u0628 \u0639\u0645\u0648\u062F\u064B\u0627 \u0625\u0644\u0649 \u0639\u0645\u0648\u062F \u0641\u064A \u062C\u062F\u0648\u0644 \u0622\u062E\u0631 \u0644\u0625\u0646\u0634\u0627\u0621 JOIN.",
    "qb.columns": "\u0627\u0644\u0623\u0639\u0645\u062F\u0629",
    "qb.conditions": "\u0627\u0644\u0634\u0631\u0648\u0637",
    "qb.results": "\u0627\u0644\u0646\u062A\u0627\u0626\u062C",
    "qb.generated": "SQL \u0627\u0644\u0645\u064F\u0646\u0634\u0623",
    "qb.regenerate": "\u0625\u0639\u0627\u062F\u0629 \u0627\u0644\u0625\u0646\u0634\u0627\u0621 \u0645\u0646 \u0627\u0644\u0645\u062E\u0637\u0637",
    "qb.otherDb": "\u064A\u0639\u0645\u0644 \u0645\u0646\u0634\u0626 \u0627\u0644\u0627\u0633\u062A\u0639\u0644\u0627\u0645\u0627\u062A \u0645\u0639 \u062C\u062F\u0627\u0648\u0644 \u0645\u0646 \u0642\u0627\u0639\u062F\u0629 \u0628\u064A\u0627\u0646\u0627\u062A \u0648\u0627\u062D\u062F\u0629 \u0641\u0642\u0637.",
    "qb.dragJoin": "\u0627\u0633\u062D\u0628 \u0625\u0644\u0649 \u0639\u0645\u0648\u062F \u0641\u064A \u062C\u062F\u0648\u0644 \u0622\u062E\u0631 \u0644\u0625\u0646\u0634\u0627\u0621 JOIN",
    "qb.swapJoin": "\u0639\u0643\u0633 \u0627\u0644\u0627\u062A\u062C\u0627\u0647",
    "qb.deleteJoin": "\u062D\u0630\u0641 JOIN",
    "qb.noColumns": "\u062D\u062F\u0651\u062F \u0645\u0631\u0628\u0639\u0627\u062A \u0627\u0644\u0623\u0639\u0645\u062F\u0629 \u0641\u064A \u0627\u0644\u062C\u062F\u0627\u0648\u0644 (\u0628\u062F\u0648\u0646 \u062A\u062D\u062F\u064A\u062F = SELECT *).",
    "qb.output": "\u0625\u0638\u0647\u0627\u0631",
    "qb.column": "\u0627\u0644\u0639\u0645\u0648\u062F",
    "qb.alias": "\u0627\u0644\u0627\u0633\u0645 \u0627\u0644\u0645\u0633\u062A\u0639\u0627\u0631",
    "qb.aggregate": "\u0627\u0644\u062A\u062C\u0645\u064A\u0639",
    "qb.sort": "\u0627\u0644\u0641\u0631\u0632",
    "qb.addCondition": "\u0625\u0636\u0627\u0641\u0629 \u0634\u0631\u0637",
    "qb.tabTitle": "\u0627\u0633\u062A\u0639\u0644\u0627\u0645 {n}",
    "ro.title": "\u0648\u0636\u0639 \u0627\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637",
    "ro.message": "\u0647\u0630\u0627 \u0627\u0644\u0627\u062A\u0635\u0627\u0644 \u0641\u064A \u0648\u0636\u0639 \u0627\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637. \u0642\u062F \u062A\u064F\u063A\u064A\u0651\u0631 \u0627\u0644\u0639\u0628\u0627\u0631\u0627\u062A \u0627\u0644\u062A\u0627\u0644\u064A\u0629 \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A \u0623\u0648 \u0627\u0644\u0645\u062E\u0637\u0637:",
    "ro.hint": "\u064A\u0645\u0643\u0646\u0643 \u0627\u0644\u0633\u0645\u0627\u062D \u0628\u0647\u0627 \u0644\u0647\u0630\u0627 \u0627\u0644\u062A\u0634\u063A\u064A\u0644 \u0641\u0642\u0637\u061B \u062B\u0645 \u064A\u0639\u0648\u062F \u0648\u0636\u0639 \u0627\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637 \u0628\u0639\u062F \u0630\u0644\u0643.",
    "ro.runOnce": "\u062A\u0634\u063A\u064A\u0644 \u0644\u0645\u0631\u0629 \u0648\u0627\u062D\u062F\u0629",
    "ro.notRun": "\u0648\u0636\u0639 \u0627\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637: \u0644\u0645 \u064A\u064F\u0646\u0641\u064E\u0651\u0630",
    "ro.blockedMsg": "\u0648\u0636\u0639 \u0627\u0644\u0642\u0631\u0627\u0621\u0629 \u0641\u0642\u0637: {n} \u0645\u0646 \u0627\u0644\u0639\u0628\u0627\u0631\u0627\u062A \u062A\u062D\u062A\u0627\u062C \u0625\u0644\u0649 \u0645\u0648\u0627\u0641\u0642\u0629.",
    "exp.title": "\u062A\u0635\u062F\u064A\u0631",
    "exp.hint": "\u064A\u064F\u0639\u0627\u062F \u062A\u0634\u063A\u064A\u0644 \u0627\u0644\u0627\u0633\u062A\u0639\u0644\u0627\u0645 \u062F\u0648\u0646 \u062D\u062F \u0644\u0644\u0635\u0641\u0648\u0641 \u0648\u062A\u064F\u0643\u062A\u0628 \u0627\u0644\u0646\u062A\u0627\u0626\u062C \u0645\u0628\u0627\u0634\u0631\u0629 \u0625\u0644\u0649 \u0627\u0644\u0645\u0644\u0641.",
    "exp.running": "\u062C\u0627\u0631\u064D \u0627\u0644\u062A\u0635\u062F\u064A\u0631\u2026",
    "exp.done": "\u062A\u0645 \u062A\u0635\u062F\u064A\u0631 {n} \u0635\u0641",
    "exp.failed": "\u0641\u0634\u0644 \u0627\u0644\u062A\u0635\u062F\u064A\u0631",
    "err.refused": "\u0631\u064F\u0641\u0636 \u0627\u0644\u0627\u062A\u0635\u0627\u0644: \u0627\u0644\u0645\u0646\u0641\u0630 \u0645\u063A\u0644\u0642 \u0623\u0648 \u0627\u0644\u062E\u0627\u062F\u0645 \u0644\u0627 \u064A\u0639\u0645\u0644.",
    "err.dns": "\u062A\u0639\u0630\u0651\u0631 \u062D\u0644 \u0627\u0633\u0645 \u0627\u0644\u0645\u0636\u064A\u0641 (DNS).",
    "err.timeout": "\u0627\u0646\u062A\u0647\u062A \u0627\u0644\u0645\u0647\u0644\u0629: \u062A\u0639\u0630\u0651\u0631 \u0627\u0644\u0648\u0635\u0648\u0644 \u0625\u0644\u0649 \u0627\u0644\u062E\u0627\u062F\u0645.",
    "err.reset": "\u0623\u063A\u0644\u0642 \u0627\u0644\u062E\u0627\u062F\u0645 \u0627\u0644\u0627\u062A\u0635\u0627\u0644.",
    "err.unreach": "\u0644\u0627 \u064A\u0645\u0643\u0646 \u0627\u0644\u0648\u0635\u0648\u0644 \u0625\u0644\u0649 \u0627\u0644\u062E\u0627\u062F\u0645 \u0639\u0628\u0631 \u0627\u0644\u0634\u0628\u0643\u0629.",
    "err.sshAuth": "\u0641\u0634\u0644 \u062A\u0633\u062C\u064A\u0644 \u0627\u0644\u062F\u062E\u0648\u0644 \u0639\u0628\u0631 SSH: \u0627\u0633\u0645 \u0627\u0644\u0645\u0633\u062A\u062E\u062F\u0645 \u0623\u0648 \u0627\u0644\u0645\u0641\u062A\u0627\u062D \u0623\u0648 \u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 \u063A\u064A\u0631 \u0635\u062D\u064A\u062D.",
    "err.tls": "\u062E\u0637\u0623 TLS/SSL \u2014 \u062A\u0639\u0630\u0651\u0631 \u0627\u0644\u062A\u062D\u0642\u0642 \u0645\u0646 \u0627\u0644\u0634\u0647\u0627\u062F\u0629 \u0623\u0648 \u0623\u0646 \u0627\u0644\u062E\u0627\u062F\u0645 \u0644\u0627 \u064A\u062F\u0639\u0645 TLS. ({msg})",
    "err.hostExit": "\u0627\u0646\u062A\u0647\u062A \u0639\u0645\u0644\u064A\u0629 \u0642\u0627\u0639\u062F\u0629 \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A \u0628\u0634\u0643\u0644 \u063A\u064A\u0631 \u0645\u062A\u0648\u0642\u0639.",
    "err.unknown": "\u062E\u0637\u0623 \u063A\u064A\u0631 \u0645\u0639\u0631\u0648\u0641",
    "main.closeAnyway": "\u0625\u063A\u0644\u0627\u0642 \u0639\u0644\u0649 \u0623\u064A \u062D\u0627\u0644",
    "main.closeRunning": "\u0644\u0627 \u062A\u0632\u0627\u0644 \u0647\u0646\u0627\u0643 \u0627\u0633\u062A\u0639\u0644\u0627\u0645\u0627\u062A \u0642\u064A\u062F \u0627\u0644\u062A\u0634\u063A\u064A\u0644. \u0633\u064A\u062A\u0645 \u0625\u0644\u063A\u0627\u0624\u0647\u0627 \u0625\u0630\u0627 \u0623\u063A\u0644\u0642\u062A \u0647\u0630\u0647 \u0627\u0644\u0646\u0627\u0641\u0630\u0629.",
    "main.copySuffix": " (\u0646\u0633\u062E\u0629)",
    "main.errConnNotFound": "\u0644\u0645 \u064A\u064F\u0639\u062B\u0631 \u0639\u0644\u0649 \u0627\u0644\u0627\u062A\u0635\u0627\u0644",
    "main.errNoSession": "\u0644\u0627 \u064A\u0648\u062C\u062F \u0627\u062A\u0635\u0627\u0644 \u0644\u0647\u0630\u0647 \u0627\u0644\u0646\u0627\u0641\u0630\u0629",
    "main.errKeyFile": "\u062A\u0639\u0630\u0651\u0631\u062A \u0642\u0631\u0627\u0621\u0629 \u0645\u0644\u0641 \u0645\u0641\u062A\u0627\u062D SSH: {path}",
    // Mastertool ortak ayarlar iskeleti (SSH Master ile aynı metinler)
    "set.general": "\u0639\u0627\u0645",
    "set.account": "\u0627\u0644\u062D\u0633\u0627\u0628",
    "set.about": "\u062D\u0648\u0644",
    "set.startup": "\u0628\u062F\u0621 \u0627\u0644\u062A\u0634\u063A\u064A\u0644",
    "set.openAtLogin": "\u0627\u0644\u062A\u0634\u063A\u064A\u0644 \u0639\u0646\u062F \u062A\u0633\u062C\u064A\u0644 \u0627\u0644\u062F\u062E\u0648\u0644 \u0625\u0644\u0649 Windows",
    "set.openAtLoginHint": "\u0625\u0630\u0627 \u0643\u0627\u0646 \u0627\u0644\u062A\u0635\u063A\u064A\u0631 \u0625\u0644\u0649 \u0627\u0644\u0639\u0644\u0628\u0629 \u0645\u0641\u0639\u0651\u0644\u064B\u0627\u060C \u064A\u0628\u062F\u0623 \u0627\u0644\u062A\u0637\u0628\u064A\u0642 \u0641\u064A \u0627\u0644\u0639\u0644\u0628\u0629.",
    "set.window": "\u0627\u0644\u0646\u0627\u0641\u0630\u0629",
    "set.minTray": "\u0625\u0638\u0647\u0627\u0631 \u0641\u064A \u0639\u0644\u0628\u0629 \u0627\u0644\u0646\u0638\u0627\u0645 \u0639\u0646\u062F \u0627\u0644\u062A\u0635\u063A\u064A\u0631",
    "set.minTrayHint": "\u0639\u0646\u062F \u0627\u0644\u062A\u0635\u063A\u064A\u0631 \u062A\u062E\u062A\u0641\u064A \u0627\u0644\u0646\u0627\u0641\u0630\u0629 \u0645\u0646 \u0634\u0631\u064A\u0637 \u0627\u0644\u0645\u0647\u0627\u0645 \u0648\u062A\u0638\u0647\u0631 \u0643\u0623\u064A\u0642\u0648\u0646\u0629 SQL Master \u0641\u064A \u0627\u0644\u0639\u0644\u0628\u0629 \u0628\u062C\u0627\u0646\u0628 \u0627\u0644\u0633\u0627\u0639\u0629. \u0627\u0646\u0642\u0631 \u0627\u0644\u0623\u064A\u0642\u0648\u0646\u0629 \u0644\u0627\u0633\u062A\u0639\u0627\u062F\u062A\u0647\u0627\u060C \u0648\u0627\u0646\u0642\u0631 \u0628\u0632\u0631 \u0627\u0644\u0641\u0623\u0631\u0629 \u0627\u0644\u0623\u064A\u0645\u0646 \u0644\u0644\u0627\u062A\u0635\u0627\u0644 \u0627\u0644\u0633\u0631\u064A\u0639.",
    "set.closeTray": "\u0627\u0644\u0625\u062E\u0641\u0627\u0621 \u0641\u064A \u0627\u0644\u0639\u0644\u0628\u0629 \u0639\u0646\u062F \u0627\u0644\u0625\u063A\u0644\u0627\u0642",
    "set.closeTrayHint": "\u064A\u062E\u0641\u064A \u0632\u0631 \u0627\u0644\u0625\u063A\u0644\u0627\u0642 (X) \u0627\u0644\u062A\u0637\u0628\u064A\u0642 \u0641\u064A \u0627\u0644\u0639\u0644\u0628\u0629 \u0628\u062F\u0644 \u0625\u0646\u0647\u0627\u0626\u0647. \u0627\u0633\u062A\u062E\u062F\u0645 \xAB\u062E\u0631\u0648\u062C\xBB \u0645\u0646 \u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u0639\u0644\u0628\u0629 \u0644\u0644\u062E\u0631\u0648\u062C.",
    "about.version": "\u0627\u0644\u0625\u0635\u062F\u0627\u0631 {version}",
    "about.family": "\u062C\u0632\u0621 \u0645\u0646 \u0639\u0627\u0626\u0644\u0629 Mastertool: \u200FSQL Master \xB7 FTP Masters \xB7 SQL Master \xB7 Notepad Master \xB7 Convert Master",
    "about.checkUpdate": "\u0627\u0644\u062A\u062D\u0642\u0642 \u0645\u0646 \u0627\u0644\u062A\u062D\u062F\u064A\u062B\u0627\u062A",
    "about.checking": "\u062C\u0627\u0631\u064D \u0627\u0644\u062A\u062D\u0642\u0642\u2026",
    "about.upToDate": "SQL Master \u0645\u062D\u062F\u0651\u062B.",
    "about.checkFailed": "\u062A\u0639\u0630\u0651\u0631 \u0627\u0644\u062A\u062D\u0642\u0642 \u0645\u0646 \u0627\u0644\u062A\u062D\u062F\u064A\u062B\u0627\u062A: {msg}",
    "about.licenses": "\u062A\u0631\u0627\u062E\u064A\u0635 \u0627\u0644\u0645\u0635\u0627\u062F\u0631 \u0627\u0644\u0645\u0641\u062A\u0648\u062D\u0629",
    "about.licensesIntro": "\u064A\u0633\u062A\u062E\u062F\u0645 SQL Master \u0645\u0643\u0648\u0646\u0627\u062A \u0627\u0644\u0645\u0635\u0627\u062F\u0631 \u0627\u0644\u0645\u0641\u062A\u0648\u062D\u0629 \u0627\u0644\u062A\u0627\u0644\u064A\u0629:",
    "about.chromium": "\u0641\u062A\u062D \u062A\u0631\u0627\u062E\u064A\u0635 Chromium",
    "main.trayShow": "\u0625\u0638\u0647\u0627\u0631 SQL Master",
    "main.trayQuick": "\u0627\u062A\u0635\u0627\u0644 \u0633\u0631\u064A\u0639",
    "main.trayNone": "\u0644\u0627 \u062A\u0648\u062C\u062F \u0627\u062A\u0635\u0627\u0644\u0627\u062A \u0645\u062D\u0641\u0648\u0638\u0629",
    "main.trayQuit": "\u062E\u0631\u0648\u062C",
    "set.languageHint": "\u062A\u0633\u062A\u062E\u062F\u0645 \u0646\u0648\u0627\u0641\u0630 \u0627\u0644\u0627\u062A\u0635\u0627\u0644 \u0627\u0644\u0645\u0641\u062A\u0648\u062D\u0629 \u0627\u0644\u0644\u063A\u0629 \u0627\u0644\u062C\u062F\u064A\u062F\u0629 \u0639\u0646\u062F \u0625\u0639\u0627\u062F\u0629 \u0641\u062A\u062D\u0647\u0627.",
    "about.newVersion": "\u0625\u0635\u062F\u0627\u0631 \u062C\u062F\u064A\u062F \u0645\u062A\u0627\u062D: {version}"
  };

  // src/shared/locales/zh.ts
  var zh = {
    "common.cancel": "\u53D6\u6D88",
    "common.save": "\u4FDD\u5B58",
    "common.create": "\u521B\u5EFA",
    "common.ok": "\u786E\u5B9A",
    "common.delete": "\u5220\u9664",
    "common.giveUp": "\u53D6\u6D88",
    "common.open": "\u6253\u5F00",
    "common.edit": "\u7F16\u8F91",
    "common.rename": "\u91CD\u547D\u540D",
    "common.refresh": "\u5237\u65B0",
    "common.newFolder": "\u65B0\u5EFA\u6587\u4EF6\u5939",
    "common.move": "\u79FB\u52A8",
    "common.moveEllipsis": "\u79FB\u52A8\u2026",
    "common.show": "\u663E\u793A",
    "common.choose": "\u6D4F\u89C8\u2026",
    "common.connect": "\u8FDE\u63A5",
    "common.folderName": "\u6587\u4EF6\u5939\u540D\u79F0",
    "common.copy": "\u590D\u5236",
    "common.close": "\u5173\u95ED",
    "app.searchPh": "\u641C\u7D22\u8FDE\u63A5\u2026  (Ctrl+F)",
    "app.newConn": "\u65B0\u5EFA\u8FDE\u63A5",
    "app.addConn": "\u65B0\u5EFA\u8FDE\u63A5",
    "app.settings": "\u8BBE\u7F6E",
    "app.stats": "{c} \u4E2A\u8FDE\u63A5 \xB7 {f} \u4E2A\u6587\u4EF6\u5939",
    "app.welcome": "\u6B22\u8FCE",
    "app.results": "\u201C{q}\u201D\u7684\u641C\u7D22\u7ED3\u679C",
    "app.all": "\u6240\u6709\u8FDE\u63A5",
    "app.welcomeHint": "\u53EF\u8FDE\u63A5 PostgreSQL\u3001SQL Server\u3001MySQL\u3001SQLite \u6216 CSV/Parquet/Excel \u6587\u4EF6\u3002<br>\u586B\u5199\u8FDE\u63A5\u4FE1\u606F\uFF0C\u6D4B\u8BD5\u8FDE\u63A5\u540E\u4FDD\u5B58\u3002",
    "app.folders": "\u6587\u4EF6\u5939",
    "app.connections": "\u8FDE\u63A5",
    "app.dblHint": "\u53CC\u51FB\u5361\u7247\u5373\u53EF\u6253\u5F00",
    "app.noMatch": "\u6CA1\u6709\u5339\u914D\u7684\u8FDE\u63A5\u3002",
    "app.folderCount": "{n} \u4E2A\u8FDE\u63A5",
    "app.newConnHere": "\u5728\u6B64\u6587\u4EF6\u5939\u4E2D\u65B0\u5EFA\u8FDE\u63A5",
    "app.newSubfolder": "\u65B0\u5EFA\u5B50\u6587\u4EF6\u5939",
    "app.duplicate": "\u590D\u5236\u8FDE\u63A5",
    "app.moveToFolder": "\u79FB\u52A8\u5230\u6587\u4EF6\u5939\u2026",
    "app.connMoved": "\u8FDE\u63A5\u5DF2\u79FB\u52A8",
    "app.folderIntoSelf": "\u6587\u4EF6\u5939\u4E0D\u80FD\u79FB\u52A8\u5230\u5176\u81EA\u8EAB\u4E2D",
    "app.folderPh": "\u4F8B\u5982\uFF1A\u5BA2\u6237",
    "app.renameFolder": "\u91CD\u547D\u540D\u6587\u4EF6\u5939",
    "app.deleteFolder": "\u5220\u9664\u6587\u4EF6\u5939",
    "app.deleteFolderMsg": "\u786E\u5B9A\u5220\u9664\u6587\u4EF6\u5939 <b>{name}</b>\uFF1F",
    "app.deleteFolderConns": "<br>\u5176\u4E2D\u7684 {n} \u4E2A\u8FDE\u63A5\u5C06\u79FB\u81F3\u4E0A\u7EA7\u6587\u4EF6\u5939\u3002",
    "app.rootFolder": "\u9876\u5C42\uFF08\u65E0\u6587\u4EF6\u5939\uFF09",
    "app.moveTitle": "\u79FB\u52A8\u201C{name}\u201D",
    "app.targetFolder": "\u76EE\u6807\u6587\u4EF6\u5939",
    "app.deleteConn": "\u5220\u9664\u8FDE\u63A5",
    "app.deleteConnMsg": "\u786E\u5B9A\u5220\u9664\u8FDE\u63A5 <b>{name}</b>\uFF08{target}\uFF09\uFF1F\u5DF2\u4FDD\u5B58\u7684\u5BC6\u7801\u4E5F\u4F1A\u4E00\u5E76\u5220\u9664\u3002",
    "app.readOnlyTag": "\u53EA\u8BFB",
    "app.writeTag": "\u53EF\u5199",
    "form.titleNew": "\u65B0\u5EFA\u8FDE\u63A5",
    "form.titleEdit": "\u8FDE\u63A5\uFF1A{name}",
    "form.tabGeneral": "\u5E38\u89C4",
    "form.tabSecurity": "\u5B89\u5168",
    "form.tabSsh": "SSH \u96A7\u9053",
    "form.name": "\u6807\u7B7E\uFF08\u663E\u793A\u540D\u79F0\uFF09",
    "form.namePh": "\u4F8B\u5982\uFF1A\u751F\u4EA7\u6570\u636E\u5E93",
    "form.host": "\u4E3B\u673A",
    "form.port": "\u7AEF\u53E3",
    "form.user": "\u7528\u6237\u540D",
    "form.password": "\u5BC6\u7801",
    "form.pwSaved": "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\uFF08\u5DF2\u4FDD\u5B58\uFF0C\u8F93\u5165\u4EE5\u66F4\u6539\uFF09",
    "form.database": "\u6570\u636E\u5E93",
    "form.databasePh": "\u7559\u7A7A\u5219\u4F7F\u7528\u9ED8\u8BA4\u6570\u636E\u5E93",
    "form.file": "\u6570\u636E\u5E93\u6587\u4EF6",
    "form.filePh": "C:\\Data\\app.db",
    "form.sqliteHint": "SQLite \u6570\u636E\u5E93\u6587\u4EF6\uFF08.db\u3001.sqlite\uFF09\u3002\u53EA\u8BFB\u6A21\u5F0F\u4E0B\u7EDD\u4E0D\u4F1A\u4FEE\u6539\u8BE5\u6587\u4EF6\u3002",
    "form.duckdbHint": "\u9009\u62E9 .duckdb \u6587\u4EF6\uFF0C\u6216\u7559\u7A7A\uFF08\u5185\u5B58\u6A21\u5F0F\uFF09\u3002\u53EF\u76F4\u63A5\u67E5\u8BE2 CSV\u3001Parquet\u3001JSON \u548C Excel \u6587\u4EF6\uFF1ASELECT * FROM 'C:\\data\\sales.csv'",
    "form.inMemory": "\u5185\u5B58\u6A21\u5F0F",
    "form.folder": "\u6587\u4EF6\u5939",
    "form.color": "\u989C\u8272",
    "form.comments": "\u5907\u6CE8",
    "form.readOnly": "\u53EA\u8BFB\u6A21\u5F0F",
    "form.readOnlyHint": "\u63A8\u8350\u5F00\u542F\u3002INSERT/UPDATE/DELETE \u548C DDL \u4F1A\u5728\u6267\u884C\u524D\u88AB\u62E6\u622A\uFF0C\u53EF\u5355\u6B21\u6279\u51C6\u6267\u884C\u3002\u5728\u652F\u6301\u7684\u6570\u636E\u5E93\u4E0A\uFF0C\u4F1A\u8BDD\u672C\u8EAB\u4E5F\u8BBE\u4E3A\u53EA\u8BFB\u3002",
    "form.savePassword": "\u4FDD\u5B58\u5BC6\u7801",
    "form.savePasswordHint": "\u5BC6\u7801\u4EC5\u4FDD\u5B58\u5728\u64CD\u4F5C\u7CFB\u7EDF\u5BC6\u94A5\u94FE\u4E2D\uFF08Windows\uFF1ADPAPI\uFF09\u3002\u5173\u95ED\u540E\uFF0C\u6BCF\u6B21\u8FDE\u63A5\u65F6\u90FD\u4F1A\u8BE2\u95EE\u5BC6\u7801\u3002",
    "form.ssl": "TLS / SSL",
    "form.sslPrefer": "\u9996\u9009\uFF08\u670D\u52A1\u5668\u652F\u6301\u65F6\u52A0\u5BC6\uFF09",
    "form.sslRequire": "\u5FC5\u9700\uFF08\u4E0D\u9A8C\u8BC1\u8BC1\u4E66\uFF09",
    "form.sslVerify": "\u5FC5\u9700 + \u9A8C\u8BC1\u8BC1\u4E66",
    "form.sslDisable": "\u5173\u95ED\uFF08\u4E0D\u52A0\u5BC6\uFF09",
    "form.sslHint": "\u9ED8\u8BA4\u4F1A\u5C1D\u8BD5 TLS\uFF1B\u5982\u679C\u670D\u52A1\u5668\u4E0D\u652F\u6301\uFF0C\u8FDE\u63A5\u7A97\u53E3\u4F1A\u53D1\u51FA\u8B66\u544A\u3002",
    "form.sshEnable": "\u901A\u8FC7 SSH \u96A7\u9053\u8FDE\u63A5",
    "form.sshHint": "\u5148\u7ECF\u7531 SSH \u670D\u52A1\u5668\u518D\u8BBF\u95EE\u6570\u636E\u5E93\u3002\u5EFA\u8BAE\u4F7F\u7528\u5BC6\u94A5\u8BA4\u8BC1\u3002",
    "form.sshHost": "SSH \u670D\u52A1\u5668",
    "form.sshAuth": "SSH \u8BA4\u8BC1",
    "form.sshKey": "\u79C1\u94A5",
    "form.sshAgent": "\u4EE3\u7406\uFF08Pageant\uFF09",
    "form.keyFile": "\u79C1\u94A5\u6587\u4EF6",
    "form.passphrase": "\u79C1\u94A5\u5BC6\u7801",
    "form.passSaved": "\uFF08\u5DF2\u4FDD\u5B58\uFF09",
    "form.passEmpty": "\u6CA1\u6709\u5219\u7559\u7A7A",
    "form.sshPassword": "SSH \u5BC6\u7801",
    "form.hostKey": "SSH \u4E3B\u673A\u5BC6\u94A5\uFF1A{fp}",
    "form.test": "\u6D4B\u8BD5\u8FDE\u63A5",
    "form.saveConnect": "\u4FDD\u5B58\u5E76\u6253\u5F00",
    "form.connecting": "\u6B63\u5728\u8FDE\u63A5\u2026",
    "form.testOk": "\u8FDE\u63A5\u6210\u529F",
    "form.testFail": "\u65E0\u6CD5\u8FDE\u63A5",
    "form.testDb": "\u6570\u636E\u5E93\uFF1A{db} \xB7 \u7528\u6237\uFF1A{user}",
    "form.noTls": "\u8B66\u544A\uFF1A\u8FDE\u63A5\u672A\u52A0\u5BC6\uFF08\u670D\u52A1\u5668\u4E0D\u652F\u6301 TLS\uFF09\u3002",
    "form.saved": "\u8FDE\u63A5\u5DF2\u4FDD\u5B58",
    "form.changesSaved": "\u66F4\u6539\u5DF2\u4FDD\u5B58",
    "set.title": "\u8BBE\u7F6E",
    "set.appearance": "\u5916\u89C2",
    "set.theme": "\u4E3B\u9898",
    "set.themeDark": "\u591C\u95F4",
    "set.themeLight": "\u65E5\u95F4",
    "set.themeSystem": "\u8DDF\u968F\u7CFB\u7EDF",
    "set.language": "\u8BED\u8A00",
    "set.toLight": "\u5207\u6362\u5230\u65E5\u95F4\u4E3B\u9898",
    "set.toDark": "\u5207\u6362\u5230\u591C\u95F4\u4E3B\u9898",
    "set.saved": "\u8BBE\u7F6E\u5DF2\u4FDD\u5B58",
    "set.query": "\u67E5\u8BE2",
    "set.rowLimit": "\u6BCF\u4E2A\u7ED3\u679C\u7684\u6700\u5927\u884C\u6570",
    "set.previewRows": "\u6253\u5F00\u8868\u65F6\u663E\u793A\u7684\u884C\u6570",
    "set.fontSize": "\u7F16\u8F91\u5668\u5B57\u53F7\uFF08px\uFF09",
    "auth.subtitle": "\u4F7F\u7528\u4F60\u7684 Mastertool \u8D26\u6237\u767B\u5F55",
    "auth.email": "\u7535\u5B50\u90AE\u4EF6",
    "auth.password": "\u5BC6\u7801",
    "auth.remember": "\u8BB0\u4F4F\u6211",
    "auth.forgot": "\u5FD8\u8BB0\u5BC6\u7801",
    "auth.noAccount": "\u8FD8\u6CA1\u6709\u8D26\u6237\uFF1F",
    "auth.register": "\u521B\u5EFA\u8D26\u6237",
    "auth.submit": "\u767B\u5F55",
    "auth.working": "\u6B63\u5728\u767B\u5F55\u2026",
    "auth.errRequired": "\u9700\u8981\u586B\u5199\u7535\u5B50\u90AE\u4EF6\u548C\u5BC6\u7801\u3002",
    "auth.errBadCredentials": "\u7535\u5B50\u90AE\u4EF6\u6216\u5BC6\u7801\u9519\u8BEF\u3002",
    "auth.errUnverified": "\u4F60\u7684\u7535\u5B50\u90AE\u4EF6\u5C1A\u672A\u9A8C\u8BC1\u3002\u8BF7\u70B9\u51FB\u6536\u4EF6\u7BB1\u4E2D\u7684\u94FE\u63A5\u3002",
    "auth.errSuspended": "\u4F60\u7684\u8D26\u6237\u5DF2\u88AB\u505C\u7528\u3002",
    "auth.errRateLimited": "\u5C1D\u8BD5\u6B21\u6570\u8FC7\u591A\u3002\u8BF7\u4E00\u5206\u949F\u540E\u518D\u8BD5\u3002",
    "auth.errOffline": "\u65E0\u6CD5\u8FDE\u63A5\u670D\u52A1\u5668\u3002\u8BF7\u68C0\u67E5\u7F51\u7EDC\u8FDE\u63A5\u3002",
    "auth.errSessionExpired": "\u4F1A\u8BDD\u5DF2\u8FC7\u671F\u6216\u5BC6\u7801\u5DF2\u66F4\u6539\u3002\u8BF7\u91CD\u65B0\u767B\u5F55\u3002",
    "auth.signedOutElsewhere": "\u4F60\u5DF2\u5728\u53E6\u4E00\u4E2A Mastertool \u5E94\u7528\u4E2D\u9000\u51FA\u767B\u5F55\u3002\u672C\u5730\u8FDE\u63A5\u4ECD\u4FDD\u7559\u5728\u8FD9\u53F0\u7535\u8111\u4E0A\u3002",
    "auth.errAppDisabled": "\u6B64\u8D26\u6237\u5DF2\u505C\u7528 SQL Master\u3002\u83B7\u53D6\u652F\u6301\uFF1Amastertool.download > \u6211\u7684\u8D26\u6237 > \u652F\u6301\u3002",
    "auth.errWrongApp": "\u6B64\u4F1A\u8BDD\u5C5E\u4E8E\u5176\u4ED6\u5E94\u7528\u3002\u8BF7\u91CD\u65B0\u767B\u5F55 SQL Master\u3002",
    "auth.errServer": "\u65E0\u6CD5\u767B\u5F55\uFF1A{msg}",
    "auth.devNotice": "\u5F00\u53D1\u6A21\u5F0F\uFF1A\u4F7F\u7528\u672C\u5730\u8D26\u6237\u4EE3\u66FF Mastertool \u670D\u52A1\u5668\uFF08\u4EFB\u610F\u7535\u5B50\u90AE\u4EF6/\u5BC6\u7801\uFF0C\u4E0D\u540C\u6B65\uFF09\u3002",
    "acct.section": "\u8D26\u6237\u4E0E\u540C\u6B65",
    "acct.signedInAs": "\u5DF2\u767B\u5F55\uFF1A{email}",
    "acct.syncToggle": "\u4E0E\u7F51\u9875\u540C\u6B65\u8FDE\u63A5\u5E93",
    "acct.syncHint": "\u8FDE\u63A5\u3001\u6587\u4EF6\u5939\u548C\u5E38\u89C4\u8BBE\u7F6E\u4F1A\u4EE5\u7AEF\u5230\u7AEF\u52A0\u5BC6\u65B9\u5F0F\u5907\u4EFD\u5230\u4F60\u7684 Mastertool \u8D26\u6237\uFF1B\u5BC6\u7801\u4EC5\u5305\u542B\u5728\u52A0\u5BC6\u6570\u636E\u4E2D\u4F20\u8F93\uFF0C\u670D\u52A1\u5668\u65E0\u6CD5\u8BFB\u53D6\u3002",
    "acct.lastSync": "\u4E0A\u6B21\u540C\u6B65\uFF1A{time}",
    "acct.never": "\u5C1A\u672A\u540C\u6B65",
    "acct.syncNow": "\u7ACB\u5373\u540C\u6B65",
    "acct.deleteRemote": "\u5220\u9664\u670D\u52A1\u5668\u4E0A\u7684\u526F\u672C",
    "acct.deleteRemoteMsg": "\u5C06\u5220\u9664\u4F60\u8D26\u6237\u4E2D\u7684\u52A0\u5BC6\u5E93\u526F\u672C\u5E76\u5173\u95ED\u540C\u6B65\u3002\u6B64\u7535\u8111\u4E0A\u7684\u8FDE\u63A5\u4E0D\u4F1A\u88AB\u5220\u9664\u3002",
    "acct.deleteRemoteDone": "\u5DF2\u5220\u9664\u670D\u52A1\u5668\u526F\u672C\u5E76\u5173\u95ED\u540C\u6B65",
    "acct.logout": "\u9000\u51FA\u767B\u5F55",
    "acct.logoutMsg": "\u5C06\u9000\u51FA\u767B\u5F55\uFF0C\u5E76\u5173\u95ED\u5DF2\u6253\u5F00\u7684\u8FDE\u63A5\u7A97\u53E3\u548C\u6B63\u5728\u8FD0\u884C\u7684\u67E5\u8BE2\u3002\u6B64\u7535\u8111\u4E0A\u7684\u8FDE\u63A5\u4E0D\u4F1A\u88AB\u5220\u9664\u3002",
    "acct.myAccount": "\u6211\u7684\u8D26\u6237\uFF08\u7F51\u9875\uFF09",
    "acct.backupNotice": "\u5DF2\u4F7F\u7528\u5176\u4ED6\u8D26\u6237\u767B\u5F55\uFF1B\u6B64\u7535\u8111\u4E0A\u4E4B\u524D\u7684\u8FDE\u63A5\u5DF2\u5907\u4EFD\u3002",
    "sync.off": "\u540C\u6B65\u5DF2\u5173\u95ED",
    "sync.syncing": "\u6B63\u5728\u540C\u6B65\u2026",
    "sync.offline": "\u79BB\u7EBF \u2014 \u6062\u590D\u8054\u7F51\u540E\u5C06\u53D1\u9001\u66F4\u6539",
    "sync.errDecrypt": "\u65E0\u6CD5\u7528\u6B64\u8D26\u6237\u7684\u5BC6\u94A5\u89E3\u5BC6\u670D\u52A1\u5668\u526F\u672C\uFF1B\u6B64\u7535\u8111\u4E0A\u7684\u8FDE\u63A5\u5DF2\u4FDD\u7559\u3002",
    "sync.errTooLarge": "\u5E93\u8D85\u8FC7 5 MB \u4E0A\u9650\uFF0C\u65E0\u6CD5\u540C\u6B65\u3002",
    "sync.error": "\u540C\u6B65\u9519\u8BEF\uFF1A{msg}",
    "sync.devMode": "\u5F00\u53D1\u6A21\u5F0F \u2014 \u4E0D\u540C\u6B65",
    "update.available": "\u65B0\u7248\u672C\u53EF\u7528\uFF1A{version}",
    "update.hint": "\u8BF7\u4ECE\u4F60\u7684 Mastertool \u8D26\u6237\u4E0B\u8F7D\u3002",
    "update.open": "\u6253\u5F00\u6211\u7684\u8D26\u6237",
    "cw.objects": "\u5BF9\u8C61",
    "cw.collapseAll": "\u5168\u90E8\u6298\u53E0",
    "cw.filterPh": "\u7B5B\u9009\u5DF2\u52A0\u8F7D\u7684\u5BF9\u8C61\u2026",
    "cw.empty": "\uFF08\u7A7A\uFF09",
    "cw.openData": "\u6253\u5F00\u6570\u636E",
    "cw.showDdl": "\u663E\u793A DDL",
    "cw.openCode": "\u6253\u5F00\u4EE3\u7801",
    "cw.selectSql": "\u751F\u6210 SELECT",
    "cw.addToBuilder": "\u6DFB\u52A0\u5230\u67E5\u8BE2\u6784\u5EFA\u5668",
    "cw.newSqlHere": "\u5728\u6B64\u65B0\u5EFA SQL",
    "cw.copyName": "\u590D\u5236\u540D\u79F0",
    "cw.copied": "\u5DF2\u590D\u5236\u5230\u526A\u8D34\u677F",
    "cw.newSql": "\u65B0\u5EFA SQL",
    "cw.builder": "\u67E5\u8BE2\u6784\u5EFA\u5668",
    "cw.reconnect": "\u91CD\u65B0\u8FDE\u63A5",
    "cw.readOnly": "\u53EA\u8BFB",
    "cw.readWrite": "\u53EF\u5199",
    "cw.readOnlyTip": "\u53EA\u8BFB\uFF1ADML/DDL \u9700\u8981\u6279\u51C6\u3002\u70B9\u51FB\u5173\u95ED\u53EA\u8BFB",
    "cw.readWriteTip": "\u53EF\u5199\uFF1A\u547D\u4EE4\u65E0\u9700\u6279\u51C6\u5373\u53EF\u6267\u884C\u3002\u70B9\u51FB\u6062\u590D\u53EA\u8BFB",
    "cw.disableRo": "\u5173\u95ED\u53EA\u8BFB\u6A21\u5F0F\uFF1F",
    "cw.disableRoMsg": "\u5728\u6B64\u7A97\u53E3\u5173\u95ED\u4E4B\u524D\uFF0CINSERT/UPDATE/DELETE \u548C DDL \u5C06\u76F4\u63A5\u6267\u884C\u800C\u4E0D\u518D\u8BE2\u95EE\u3002",
    "cw.disableRoOk": "\u5141\u8BB8\u5199\u5165",
    "cw.roOn": "\u53EA\u8BFB\u6A21\u5F0F\u5DF2\u5F00\u542F",
    "cw.roOff": "\u5DF2\u5141\u8BB8\u5199\u5165 \u2014 \u8BF7\u8C28\u614E\u64CD\u4F5C",
    "cw.passwordTitle": "\u9700\u8981\u5BC6\u7801",
    "cw.passwordFor": "{user}@{host} \u7684\u5BC6\u7801",
    "cw.notConnected": "\u672A\u8FDE\u63A5",
    "cw.connected": "\u5DF2\u8FDE\u63A5",
    "cw.connecting": "\u6B63\u5728\u8FDE\u63A5\u2026",
    "cw.noTls": "\u672A\u52A0\u5BC6",
    "cw.connectFailed": "\u65E0\u6CD5\u8FDE\u63A5",
    "cw.retry": "\u91CD\u8BD5",
    "cw.resetCancel": "\u67E5\u8BE2\u672A\u54CD\u5E94\u53D6\u6D88\u64CD\u4F5C\uFF1B\u6B63\u5728\u91CD\u65B0\u8FDE\u63A5\u3002",
    "cw.resetExit": "\u6570\u636E\u5E93\u8FDE\u63A5\u5DF2\u65AD\u5F00\uFF1B\u6B63\u5728\u91CD\u65B0\u8FDE\u63A5\u3002",
    "cw.emptyWorkspace": "\u5728\u5BF9\u8C61\u6811\u4E2D\u53CC\u51FB\u8868\uFF0C\u6216\u6309 Ctrl+T \u65B0\u5EFA SQL \u6807\u7B7E\u9875\u3002",
    "cw.closeTab": "\u5173\u95ED\u6807\u7B7E\u9875\uFF1F",
    "cw.closeTabMsg": "\u201C{name}\u201D\u4E2D\u7684 SQL \u5C1A\u672A\u4FDD\u5B58\u3002",
    "cw.closeTabOk": "\u5173\u95ED",
    "tree.tables": "\u8868",
    "tree.views": "\u89C6\u56FE",
    "tree.matviews": "\u7269\u5316\u89C6\u56FE",
    "tree.foreign_tables": "\u5916\u90E8\u8868",
    "tree.functions": "\u51FD\u6570",
    "tree.procedures": "\u5B58\u50A8\u8FC7\u7A0B",
    "tree.triggers": "\u89E6\u53D1\u5668",
    "tree.sequences": "\u5E8F\u5217",
    "tree.types": "\u7C7B\u578B",
    "tree.columns": "\u5217",
    "tree.indexes": "\u7D22\u5F15",
    "tree.constraints": "\u7EA6\u675F",
    "tree.files": "\u6587\u4EF6",
    "kind.table": "\u8868",
    "kind.view": "\u89C6\u56FE",
    "kind.matview": "\u7269\u5316\u89C6\u56FE",
    "kind.foreign-table": "\u5916\u90E8\u8868",
    "kind.function": "\u51FD\u6570",
    "kind.procedure": "\u5B58\u50A8\u8FC7\u7A0B",
    "kind.trigger": "\u89E6\u53D1\u5668",
    "kind.sequence": "\u5E8F\u5217",
    "kind.type": "\u7C7B\u578B",
    "kind.index": "\u7D22\u5F15",
    "kind.constraint": "\u7EA6\u675F",
    "sql.run": "\u8FD0\u884C",
    "sql.runStatement": "\u8FD0\u884C\u5F53\u524D\u8BED\u53E5",
    "sql.cancel": "\u53D6\u6D88",
    "sql.database": "\u6570\u636E\u5E93",
    "sql.history": "\u5386\u53F2\u8BB0\u5F55",
    "sql.export": "\u5BFC\u51FA",
    "sql.running": "\u6B63\u5728\u8FD0\u884C\u2026",
    "sql.done": "\u5B8C\u6210 \xB7 {ms} ms",
    "sql.doneErrors": "{n} \u4E2A\u9519\u8BEF \xB7 {ms} ms",
    "sql.ddlHint": "\u6A21\u5F0F\u5DF2\u66F4\u6539\uFF1A\u8BF7\u4F7F\u7528\u201C\u5237\u65B0\u201D\u91CD\u65B0\u52A0\u8F7D\u5BF9\u8C61\u6811\u3002",
    "sql.placeholder": "\u8F93\u5165 SQL\u2026 Ctrl+Enter\uFF1A\u8FD0\u884C\u9009\u4E2D\u5185\u5BB9/\u5168\u90E8 \xB7 Ctrl+Shift+Enter\uFF1A\u8FD0\u884C\u5149\u6807\u5904\u8BED\u53E5 \xB7 Ctrl+Space\uFF1A\u81EA\u52A8\u8865\u5168",
    "sql.tabTitle": "SQL {n}",
    "sql.historyEmpty": "\u6B64\u8FDE\u63A5\u6CA1\u6709\u5386\u53F2\u8BB0\u5F55\u3002",
    "sql.rowsShort": "\u884C",
    "res.result": "\u7ED3\u679C {n}",
    "res.messages": "\u6D88\u606F",
    "res.rows": "{n} \u884C \xB7 {ms} ms",
    "res.rowsTruncated": "\u663E\u793A\u524D {n} \u884C\uFF08\u5DF2\u8FBE\u4E0A\u9650\uFF09\xB7 {ms} ms",
    "res.noRows": "\u65E0\u6570\u636E\u884C",
    "res.affected": "{cmd}\uFF1A\u5F71\u54CD {n} \u884C \xB7 {ms} ms",
    "res.command": "{cmd} \xB7 {ms} ms",
    "res.cancelled": "\u5DF2\u53D6\u6D88",
    "grid.copy": "\u590D\u5236",
    "grid.copyHeaders": "\u8FDE\u540C\u5217\u6807\u9898\u590D\u5236",
    "grid.export": "\u5BFC\u51FA\u6B64\u7ED3\u679C\u2026",
    "data.columns": "\u5217",
    "data.columnsHidden": "\u5217\uFF08{n}/{total}\uFF09",
    "data.addFilter": "\u7B5B\u9009",
    "data.limit": "\u884C\u6570",
    "data.firstN": "\u524D {n} \u884C",
    "data.all": "\u5168\u90E8\uFF08\u6709\u4E0A\u9650\uFF09",
    "data.openInEditor": "\u5728 SQL \u7F16\u8F91\u5668\u4E2D\u6253\u5F00",
    "data.clearFilters": "\u6E05\u9664\u7B5B\u9009",
    "data.rows": "{n} \u884C \xB7 {ms} ms",
    "data.rowsMore": "\u524D {n} \u884C \xB7 {ms} ms",
    "data.error": "\u65E0\u6CD5\u52A0\u8F7D\u6570\u636E",
    "data.sortAsc": "\u5347\u5E8F\u6392\u5E8F",
    "data.sortDesc": "\u964D\u5E8F\u6392\u5E8F",
    "data.sortClear": "\u6E05\u9664\u6392\u5E8F",
    "data.filterColumn": "\u6309\u6B64\u5217\u7B5B\u9009\u2026",
    "data.hideColumn": "\u9690\u85CF\u5217",
    "data.showAll": "\u663E\u793A\u6240\u6709\u5217",
    "data.filterEq": "\u7B49\u4E8E\u201C{v}\u201D",
    "data.filterNe": "\u4E0D\u7B49\u4E8E\u201C{v}\u201D",
    "data.filterNull": "NULL / \u975E NULL",
    "data.column": "\u5217",
    "data.operator": "\u6761\u4EF6",
    "data.value": "\u503C",
    "data.inHint": "\u4F7F\u7528\u201C\u5728\u5217\u8868\u4E2D\u201D\u65F6\uFF0C\u591A\u4E2A\u503C\u8BF7\u7528\u9017\u53F7\u5206\u9694\u3002",
    "data.filterTitle": "\u7B5B\u9009",
    "data.selectAll": "\u5168\u9009",
    "data.selectNone": "\u5168\u4E0D\u9009",
    "op.=": "\u7B49\u4E8E",
    "op.<>": "\u4E0D\u7B49\u4E8E",
    "op.<": "\u5C0F\u4E8E",
    "op.>": "\u5927\u4E8E",
    "op.<=": "\u5C0F\u4E8E\u6216\u7B49\u4E8E",
    "op.>=": "\u5927\u4E8E\u6216\u7B49\u4E8E",
    "op.contains": "\u5305\u542B",
    "op.not contains": "\u4E0D\u5305\u542B",
    "op.starts": "\u5F00\u5934\u662F",
    "op.ends": "\u7ED3\u5C3E\u662F",
    "op.like": "LIKE",
    "op.not like": "NOT LIKE",
    "op.in": "\u5728\u5217\u8868\u4E2D",
    "op.not in": "\u4E0D\u5728\u5217\u8868\u4E2D",
    "op.is null": "\u4E3A NULL",
    "op.is not null": "\u4E0D\u4E3A NULL",
    "code.execute": "\u6267\u884C",
    "code.loading": "\u6B63\u5728\u52A0\u8F7D\u2026",
    "code.empty": "\u672A\u627E\u5230\u5B9A\u4E49",
    "qb.addTable": "\u6DFB\u52A0\u8868",
    "qb.limit": "\u884C\u6570\u9650\u5236",
    "qb.clear": "\u6E05\u7A7A",
    "qb.hint": "\u4ECE\u5BF9\u8C61\u6811\u5C06\u8868\u62D6\u5230\u6B64\u5904\uFF0C\u6216\u70B9\u51FB\u201C\u6DFB\u52A0\u8868\u201D\u3002\u5C06\u67D0\u5217\u62D6\u5230\u53E6\u4E00\u5F20\u8868\u7684\u5217\u4E0A\u5373\u53EF\u521B\u5EFA JOIN\u3002",
    "qb.columns": "\u5217",
    "qb.conditions": "\u6761\u4EF6",
    "qb.results": "\u7ED3\u679C",
    "qb.generated": "\u751F\u6210\u7684 SQL",
    "qb.regenerate": "\u6839\u636E\u56FE\u8868\u91CD\u65B0\u751F\u6210",
    "qb.otherDb": "\u67E5\u8BE2\u6784\u5EFA\u5668\u53EA\u80FD\u4F7F\u7528\u540C\u4E00\u6570\u636E\u5E93\u4E2D\u7684\u8868\u3002",
    "qb.dragJoin": "\u62D6\u5230\u53E6\u4E00\u5F20\u8868\u7684\u5217\u4E0A\u4EE5\u521B\u5EFA JOIN",
    "qb.swapJoin": "\u4EA4\u6362\u65B9\u5411",
    "qb.deleteJoin": "\u5220\u9664 JOIN",
    "qb.noColumns": "\u5728\u8868\u4E0A\u52FE\u9009\u6240\u9700\u7684\u5217\uFF08\u4E0D\u52FE\u9009 = SELECT *\uFF09\u3002",
    "qb.output": "\u663E\u793A",
    "qb.column": "\u5217",
    "qb.alias": "\u522B\u540D",
    "qb.aggregate": "\u805A\u5408",
    "qb.sort": "\u6392\u5E8F",
    "qb.addCondition": "\u6DFB\u52A0\u6761\u4EF6",
    "qb.tabTitle": "\u67E5\u8BE2 {n}",
    "ro.title": "\u53EA\u8BFB\u6A21\u5F0F",
    "ro.message": "\u6B64\u8FDE\u63A5\u5904\u4E8E\u53EA\u8BFB\u6A21\u5F0F\u3002\u4EE5\u4E0B\u8BED\u53E5\u53EF\u80FD\u4F1A\u66F4\u6539\u6570\u636E\u6216\u6A21\u5F0F\uFF1A",
    "ro.hint": "\u4F60\u53EF\u4EE5\u4EC5\u5141\u8BB8\u672C\u6B21\u6267\u884C\uFF1B\u6267\u884C\u540E\u5C06\u6062\u590D\u53EA\u8BFB\u6A21\u5F0F\u3002",
    "ro.runOnce": "\u4EC5\u6267\u884C\u8FD9\u4E00\u6B21",
    "ro.notRun": "\u53EA\u8BFB\u6A21\u5F0F\uFF1A\u672A\u6267\u884C",
    "ro.blockedMsg": "\u53EA\u8BFB\u6A21\u5F0F\uFF1A{n} \u6761\u8BED\u53E5\u9700\u8981\u6279\u51C6\u3002",
    "exp.title": "\u5BFC\u51FA",
    "exp.hint": "\u67E5\u8BE2\u5C06\u5728\u4E0D\u9650\u5236\u884C\u6570\u7684\u60C5\u51B5\u4E0B\u91CD\u65B0\u8FD0\u884C\uFF0C\u7ED3\u679C\u4F1A\u76F4\u63A5\u4EE5\u6D41\u5F0F\u5199\u5165\u6587\u4EF6\u3002",
    "exp.running": "\u6B63\u5728\u5BFC\u51FA\u2026",
    "exp.done": "\u5DF2\u5BFC\u51FA {n} \u884C",
    "exp.failed": "\u5BFC\u51FA\u5931\u8D25",
    "err.refused": "\u8FDE\u63A5\u88AB\u62D2\u7EDD\uFF1A\u7AEF\u53E3\u672A\u5F00\u653E\u6216\u670D\u52A1\u5668\u672A\u8FD0\u884C\u3002",
    "err.dns": "\u65E0\u6CD5\u89E3\u6790\u4E3B\u673A\u540D\uFF08DNS\uFF09\u3002",
    "err.timeout": "\u8FDE\u63A5\u8D85\u65F6\uFF1A\u65E0\u6CD5\u8BBF\u95EE\u670D\u52A1\u5668\u3002",
    "err.reset": "\u670D\u52A1\u5668\u5173\u95ED\u4E86\u8FDE\u63A5\u3002",
    "err.unreach": "\u7F51\u7EDC\u4E0A\u65E0\u6CD5\u8BBF\u95EE\u8BE5\u670D\u52A1\u5668\u3002",
    "err.sshAuth": "SSH \u767B\u5F55\u5931\u8D25\uFF1A\u7528\u6237\u540D\u3001\u5BC6\u94A5\u6216\u5BC6\u7801\u9519\u8BEF\u3002",
    "err.tls": "TLS/SSL \u9519\u8BEF \u2014 \u65E0\u6CD5\u9A8C\u8BC1\u8BC1\u4E66\uFF0C\u6216\u670D\u52A1\u5668\u4E0D\u652F\u6301 TLS\u3002\uFF08{msg}\uFF09",
    "err.hostExit": "\u6570\u636E\u5E93\u8FDB\u7A0B\u610F\u5916\u9000\u51FA\u3002",
    "err.unknown": "\u672A\u77E5\u9519\u8BEF",
    "main.closeAnyway": "\u4ECD\u7136\u5173\u95ED",
    "main.closeRunning": "\u4ECD\u6709\u67E5\u8BE2\u6B63\u5728\u8FD0\u884C\u3002\u5173\u95ED\u6B64\u7A97\u53E3\u5C06\u53D6\u6D88\u8FD9\u4E9B\u67E5\u8BE2\u3002",
    "main.copySuffix": "\uFF08\u526F\u672C\uFF09",
    "main.errConnNotFound": "\u672A\u627E\u5230\u8FDE\u63A5",
    "main.errNoSession": "\u6B64\u7A97\u53E3\u6CA1\u6709\u8FDE\u63A5",
    "main.errKeyFile": "\u65E0\u6CD5\u8BFB\u53D6 SSH \u5BC6\u94A5\u6587\u4EF6\uFF1A{path}",
    // Mastertool ortak ayarlar iskeleti (SSH Master ile aynı metinler)
    "set.general": "\u5E38\u89C4",
    "set.account": "\u8D26\u6237",
    "set.about": "\u5173\u4E8E",
    "set.startup": "\u542F\u52A8",
    "set.openAtLogin": "\u767B\u5F55 Windows \u65F6\u542F\u52A8",
    "set.openAtLoginHint": "\u5982\u679C\u5F00\u542F\u4E86\u6700\u5C0F\u5316\u5230\u6258\u76D8\uFF0C\u5E94\u7528\u5C06\u5728\u6258\u76D8\u4E2D\u542F\u52A8\u3002",
    "set.window": "\u7A97\u53E3",
    "set.minTray": "\u6700\u5C0F\u5316\u65F6\u663E\u793A\u5728\u7CFB\u7EDF\u6258\u76D8",
    "set.minTrayHint": "\u6700\u5C0F\u5316\u540E\u7A97\u53E3\u4F1A\u4ECE\u4EFB\u52A1\u680F\u9690\u85CF\uFF0C\u5E76\u4EE5 SQL Master \u56FE\u6807\u663E\u793A\u5728\u65F6\u949F\u65C1\u7684\u6258\u76D8\u4E2D\u3002\u5355\u51FB\u56FE\u6807\u5373\u53EF\u6062\u590D\uFF1B\u53F3\u952E\u53EF\u5FEB\u901F\u8FDE\u63A5\u3002",
    "set.closeTray": "\u5173\u95ED\u65F6\u9690\u85CF\u5230\u6258\u76D8",
    "set.closeTrayHint": "\u5173\u95ED (X) \u6309\u94AE\u4F1A\u5C06\u5E94\u7528\u9690\u85CF\u5230\u6258\u76D8\u800C\u4E0D\u662F\u9000\u51FA\u3002\u8981\u9000\u51FA\uFF0C\u8BF7\u4F7F\u7528\u6258\u76D8\u83DC\u5355\u4E2D\u7684\u201C\u9000\u51FA\u201D\u3002",
    "about.version": "\u7248\u672C {version}",
    "about.family": "Mastertool \u7CFB\u5217\u4EA7\u54C1\u4E4B\u4E00\uFF1ASQL Master \xB7 FTP Masters \xB7 SQL Master \xB7 Notepad Master \xB7 Convert Master",
    "about.checkUpdate": "\u68C0\u67E5\u66F4\u65B0",
    "about.checking": "\u6B63\u5728\u68C0\u67E5\u2026",
    "about.upToDate": "SQL Master \u5DF2\u662F\u6700\u65B0\u7248\u672C\u3002",
    "about.checkFailed": "\u65E0\u6CD5\u68C0\u67E5\u66F4\u65B0\uFF1A{msg}",
    "about.licenses": "\u5F00\u6E90\u8BB8\u53EF",
    "about.licensesIntro": "SQL Master \u4F7F\u7528\u4EE5\u4E0B\u5F00\u6E90\u7EC4\u4EF6\uFF1A",
    "about.chromium": "\u6253\u5F00 Chromium \u8BB8\u53EF",
    "main.trayShow": "\u663E\u793A SQL Master",
    "main.trayQuick": "\u5FEB\u901F\u8FDE\u63A5",
    "main.trayNone": "\u6CA1\u6709\u5DF2\u4FDD\u5B58\u7684\u8FDE\u63A5",
    "main.trayQuit": "\u9000\u51FA",
    "set.languageHint": "\u5DF2\u6253\u5F00\u7684\u8FDE\u63A5\u7A97\u53E3\u5C06\u5728\u91CD\u65B0\u6253\u5F00\u540E\u4F7F\u7528\u65B0\u8BED\u8A00\u3002",
    "about.newVersion": "\u6709\u65B0\u7248\u672C\u53EF\u7528\uFF1A{version}"
  };

  // src/shared/locales/ru.ts
  var ru = {
    "common.cancel": "\u041E\u0442\u043C\u0435\u043D\u0430",
    "common.save": "\u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C",
    "common.create": "\u0421\u043E\u0437\u0434\u0430\u0442\u044C",
    "common.ok": "OK",
    "common.delete": "\u0423\u0434\u0430\u043B\u0438\u0442\u044C",
    "common.giveUp": "\u041E\u0442\u043C\u0435\u043D\u0430",
    "common.open": "\u041E\u0442\u043A\u0440\u044B\u0442\u044C",
    "common.edit": "\u0418\u0437\u043C\u0435\u043D\u0438\u0442\u044C",
    "common.rename": "\u041F\u0435\u0440\u0435\u0438\u043C\u0435\u043D\u043E\u0432\u0430\u0442\u044C",
    "common.refresh": "\u041E\u0431\u043D\u043E\u0432\u0438\u0442\u044C",
    "common.newFolder": "\u041D\u043E\u0432\u0430\u044F \u043F\u0430\u043F\u043A\u0430",
    "common.move": "\u041F\u0435\u0440\u0435\u043C\u0435\u0441\u0442\u0438\u0442\u044C",
    "common.moveEllipsis": "\u041F\u0435\u0440\u0435\u043C\u0435\u0441\u0442\u0438\u0442\u044C\u2026",
    "common.show": "\u041F\u043E\u043A\u0430\u0437\u0430\u0442\u044C",
    "common.choose": "\u0412\u044B\u0431\u0440\u0430\u0442\u044C\u2026",
    "common.connect": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0438\u0442\u044C\u0441\u044F",
    "common.folderName": "\u0418\u043C\u044F \u043F\u0430\u043F\u043A\u0438",
    "common.copy": "\u041A\u043E\u043F\u0438\u0440\u043E\u0432\u0430\u0442\u044C",
    "common.close": "\u0417\u0430\u043A\u0440\u044B\u0442\u044C",
    "app.searchPh": "\u041F\u043E\u0438\u0441\u043A \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0439\u2026  (Ctrl+F)",
    "app.newConn": "\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435",
    "app.addConn": "\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435",
    "app.settings": "\u041D\u0430\u0441\u0442\u0440\u043E\u0439\u043A\u0438",
    "app.stats": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0439: {c} \xB7 \u043F\u0430\u043F\u043E\u043A: {f}",
    "app.welcome": "\u0414\u043E\u0431\u0440\u043E \u043F\u043E\u0436\u0430\u043B\u043E\u0432\u0430\u0442\u044C",
    "app.results": "\u0420\u0435\u0437\u0443\u043B\u044C\u0442\u0430\u0442\u044B \u0434\u043B\u044F \xAB{q}\xBB",
    "app.all": "\u0412\u0441\u0435 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F",
    "app.welcomeHint": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0430\u0439\u0442\u0435\u0441\u044C \u043A PostgreSQL, SQL Server, MySQL, SQLite \u0438\u043B\u0438 \u043A \u0444\u0430\u0439\u043B\u0430\u043C CSV/Parquet/Excel.<br>\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043F\u0430\u0440\u0430\u043C\u0435\u0442\u0440\u044B, \u043F\u0440\u043E\u0432\u0435\u0440\u044C\u0442\u0435 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u0438 \u0441\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u0435.",
    "app.folders": "\u041F\u0430\u043F\u043A\u0438",
    "app.connections": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F",
    "app.dblHint": "\u0414\u0432\u0430\u0436\u0434\u044B \u0449\u0451\u043B\u043A\u043D\u0438\u0442\u0435 \u043A\u0430\u0440\u0442\u043E\u0447\u043A\u0443, \u0447\u0442\u043E\u0431\u044B \u043E\u0442\u043A\u0440\u044B\u0442\u044C",
    "app.noMatch": "\u041F\u043E\u0434\u0445\u043E\u0434\u044F\u0449\u0438\u0445 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0439 \u043D\u0435\u0442.",
    "app.folderCount": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0439: {n}",
    "app.newConnHere": "\u041D\u043E\u0432\u043E\u0435 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u0432 \u044D\u0442\u043E\u0439 \u043F\u0430\u043F\u043A\u0435",
    "app.newSubfolder": "\u041D\u043E\u0432\u0430\u044F \u043F\u043E\u0434\u043F\u0430\u043F\u043A\u0430",
    "app.duplicate": "\u0414\u0443\u0431\u043B\u0438\u0440\u043E\u0432\u0430\u0442\u044C",
    "app.moveToFolder": "\u041F\u0435\u0440\u0435\u043C\u0435\u0441\u0442\u0438\u0442\u044C \u0432 \u043F\u0430\u043F\u043A\u0443\u2026",
    "app.connMoved": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u043F\u0435\u0440\u0435\u043C\u0435\u0449\u0435\u043D\u043E",
    "app.folderIntoSelf": "\u041D\u0435\u043B\u044C\u0437\u044F \u043F\u0435\u0440\u0435\u043C\u0435\u0441\u0442\u0438\u0442\u044C \u043F\u0430\u043F\u043A\u0443 \u0432 \u0441\u0430\u043C\u0443 \u0441\u0435\u0431\u044F",
    "app.folderPh": "\u043D\u0430\u043F\u0440\u0438\u043C\u0435\u0440, \u041A\u043B\u0438\u0435\u043D\u0442\u044B",
    "app.renameFolder": "\u041F\u0435\u0440\u0435\u0438\u043C\u0435\u043D\u043E\u0432\u0430\u0442\u044C \u043F\u0430\u043F\u043A\u0443",
    "app.deleteFolder": "\u0423\u0434\u0430\u043B\u0438\u0442\u044C \u043F\u0430\u043F\u043A\u0443",
    "app.deleteFolderMsg": "\u0423\u0434\u0430\u043B\u0438\u0442\u044C \u043F\u0430\u043F\u043A\u0443 <b>{name}</b>?",
    "app.deleteFolderConns": "<br>\u0415\u0451 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F ({n}) \u0431\u0443\u0434\u0443\u0442 \u043F\u0435\u0440\u0435\u043C\u0435\u0449\u0435\u043D\u044B \u0432 \u0440\u043E\u0434\u0438\u0442\u0435\u043B\u044C\u0441\u043A\u0443\u044E \u043F\u0430\u043F\u043A\u0443.",
    "app.rootFolder": "\u0412\u0435\u0440\u0445\u043D\u0438\u0439 \u0443\u0440\u043E\u0432\u0435\u043D\u044C (\u0431\u0435\u0437 \u043F\u0430\u043F\u043A\u0438)",
    "app.moveTitle": "\u041F\u0435\u0440\u0435\u043C\u0435\u0441\u0442\u0438\u0442\u044C \xAB{name}\xBB",
    "app.targetFolder": "\u0426\u0435\u043B\u0435\u0432\u0430\u044F \u043F\u0430\u043F\u043A\u0430",
    "app.deleteConn": "\u0423\u0434\u0430\u043B\u0438\u0442\u044C \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435",
    "app.deleteConnMsg": "\u0423\u0434\u0430\u043B\u0438\u0442\u044C \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 <b>{name}</b> ({target})? \u0421\u043E\u0445\u0440\u0430\u043D\u0451\u043D\u043D\u044B\u0439 \u043F\u0430\u0440\u043E\u043B\u044C \u0442\u0430\u043A\u0436\u0435 \u0431\u0443\u0434\u0435\u0442 \u0443\u0434\u0430\u043B\u0451\u043D.",
    "app.readOnlyTag": "\u0422\u043E\u043B\u044C\u043A\u043E \u0447\u0442\u0435\u043D\u0438\u0435",
    "app.writeTag": "\u0417\u0430\u043F\u0438\u0441\u044C",
    "form.titleNew": "\u041D\u043E\u0432\u043E\u0435 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435",
    "form.titleEdit": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435: {name}",
    "form.tabGeneral": "\u041E\u0431\u0449\u0438\u0435",
    "form.tabSecurity": "\u0411\u0435\u0437\u043E\u043F\u0430\u0441\u043D\u043E\u0441\u0442\u044C",
    "form.tabSsh": "SSH-\u0442\u0443\u043D\u043D\u0435\u043B\u044C",
    "form.name": "\u041C\u0435\u0442\u043A\u0430 (\u043E\u0442\u043E\u0431\u0440\u0430\u0436\u0430\u0435\u043C\u043E\u0435 \u0438\u043C\u044F)",
    "form.namePh": "\u043D\u0430\u043F\u0440\u0438\u043C\u0435\u0440, \u0420\u0430\u0431\u043E\u0447\u0430\u044F \u0431\u0430\u0437\u0430 \u0434\u0430\u043D\u043D\u044B\u0445",
    "form.host": "\u0425\u043E\u0441\u0442",
    "form.port": "\u041F\u043E\u0440\u0442",
    "form.user": "\u0418\u043C\u044F \u043F\u043E\u043B\u044C\u0437\u043E\u0432\u0430\u0442\u0435\u043B\u044F",
    "form.password": "\u041F\u0430\u0440\u043E\u043B\u044C",
    "form.pwSaved": "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (\u0441\u043E\u0445\u0440\u0430\u043D\u0451\u043D, \u0432\u0432\u0435\u0434\u0438\u0442\u0435 \u0434\u043B\u044F \u0438\u0437\u043C\u0435\u043D\u0435\u043D\u0438\u044F)",
    "form.database": "\u0411\u0430\u0437\u0430 \u0434\u0430\u043D\u043D\u044B\u0445",
    "form.databasePh": "\u041E\u0441\u0442\u0430\u0432\u044C\u0442\u0435 \u043F\u0443\u0441\u0442\u044B\u043C \u0434\u043B\u044F \u0431\u0430\u0437\u044B \u0434\u0430\u043D\u043D\u044B\u0445 \u043F\u043E \u0443\u043C\u043E\u043B\u0447\u0430\u043D\u0438\u044E",
    "form.file": "\u0424\u0430\u0439\u043B \u0431\u0430\u0437\u044B \u0434\u0430\u043D\u043D\u044B\u0445",
    "form.filePh": "C:\\Data\\app.db",
    "form.sqliteHint": "\u0424\u0430\u0439\u043B \u0431\u0430\u0437\u044B \u0434\u0430\u043D\u043D\u044B\u0445 SQLite (.db, .sqlite). \u0412 \u0440\u0435\u0436\u0438\u043C\u0435 \u0442\u043E\u043B\u044C\u043A\u043E \u0434\u043B\u044F \u0447\u0442\u0435\u043D\u0438\u044F \u0444\u0430\u0439\u043B \u043D\u0438\u043A\u043E\u0433\u0434\u0430 \u043D\u0435 \u0438\u0437\u043C\u0435\u043D\u044F\u0435\u0442\u0441\u044F.",
    "form.duckdbHint": "\u0412\u044B\u0431\u0435\u0440\u0438\u0442\u0435 \u0444\u0430\u0439\u043B .duckdb \u0438\u043B\u0438 \u043E\u0441\u0442\u0430\u0432\u044C\u0442\u0435 \u043F\u0443\u0441\u0442\u044B\u043C (\u0432 \u043F\u0430\u043C\u044F\u0442\u0438). \u0417\u0430\u043F\u0440\u0430\u0448\u0438\u0432\u0430\u0439\u0442\u0435 \u0444\u0430\u0439\u043B\u044B CSV, Parquet, JSON \u0438 Excel \u043D\u0430\u043F\u0440\u044F\u043C\u0443\u044E: SELECT * FROM 'C:\\data\\sales.csv'",
    "form.inMemory": "\u0412 \u043F\u0430\u043C\u044F\u0442\u0438",
    "form.folder": "\u041F\u0430\u043F\u043A\u0430",
    "form.color": "\u0426\u0432\u0435\u0442",
    "form.comments": "\u0417\u0430\u043C\u0435\u0442\u043A\u0438",
    "form.readOnly": "\u0420\u0435\u0436\u0438\u043C \u0442\u043E\u043B\u044C\u043A\u043E \u0434\u043B\u044F \u0447\u0442\u0435\u043D\u0438\u044F",
    "form.readOnlyHint": "\u0420\u0435\u043A\u043E\u043C\u0435\u043D\u0434\u0443\u0435\u0442\u0441\u044F. INSERT/UPDATE/DELETE \u0438 DDL \u0431\u043B\u043E\u043A\u0438\u0440\u0443\u044E\u0442\u0441\u044F \u0434\u043E \u0432\u044B\u043F\u043E\u043B\u043D\u0435\u043D\u0438\u044F; \u0438\u0445 \u043C\u043E\u0436\u043D\u043E \u0440\u0430\u0437\u0440\u0435\u0448\u0438\u0442\u044C \u043E\u0434\u043D\u043E\u043A\u0440\u0430\u0442\u043D\u043E. \u0415\u0441\u043B\u0438 \u043F\u043E\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442\u0441\u044F, \u0441\u0430\u043C \u0441\u0435\u0430\u043D\u0441 \u0442\u0430\u043A\u0436\u0435 \u0440\u0430\u0431\u043E\u0442\u0430\u0435\u0442 \u0442\u043E\u043B\u044C\u043A\u043E \u043D\u0430 \u0447\u0442\u0435\u043D\u0438\u0435.",
    "form.savePassword": "\u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C \u043F\u0430\u0440\u043E\u043B\u044C",
    "form.savePasswordHint": "\u041F\u0430\u0440\u043E\u043B\u044C \u0445\u0440\u0430\u043D\u0438\u0442\u0441\u044F \u0442\u043E\u043B\u044C\u043A\u043E \u0432 \u0445\u0440\u0430\u043D\u0438\u043B\u0438\u0449\u0435 \u043A\u043B\u044E\u0447\u0435\u0439 \u041E\u0421 (Windows: DPAPI). \u0415\u0441\u043B\u0438 \u0432\u044B\u043A\u043B\u044E\u0447\u0435\u043D\u043E, \u043F\u0430\u0440\u043E\u043B\u044C \u0437\u0430\u043F\u0440\u0430\u0448\u0438\u0432\u0430\u0435\u0442\u0441\u044F \u043F\u0440\u0438 \u043A\u0430\u0436\u0434\u043E\u043C \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0438.",
    "form.ssl": "TLS / SSL",
    "form.sslPrefer": "\u041F\u0440\u0435\u0434\u043F\u043E\u0447\u0442\u0438\u0442\u0435\u043B\u044C\u043D\u043E (\u0448\u0438\u0444\u0440\u043E\u0432\u0430\u043D\u0438\u0435, \u0435\u0441\u043B\u0438 \u0441\u0435\u0440\u0432\u0435\u0440 \u043F\u043E\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442)",
    "form.sslRequire": "\u041E\u0431\u044F\u0437\u0430\u0442\u0435\u043B\u044C\u043D\u043E (\u0441\u0435\u0440\u0442\u0438\u0444\u0438\u043A\u0430\u0442 \u043D\u0435 \u043F\u0440\u043E\u0432\u0435\u0440\u044F\u0435\u0442\u0441\u044F)",
    "form.sslVerify": "\u041E\u0431\u044F\u0437\u0430\u0442\u0435\u043B\u044C\u043D\u043E + \u043F\u0440\u043E\u0432\u0435\u0440\u043A\u0430 \u0441\u0435\u0440\u0442\u0438\u0444\u0438\u043A\u0430\u0442\u0430",
    "form.sslDisable": "\u0412\u044B\u043A\u043B. (\u0431\u0435\u0437 \u0448\u0438\u0444\u0440\u043E\u0432\u0430\u043D\u0438\u044F)",
    "form.sslHint": "\u041F\u043E \u0443\u043C\u043E\u043B\u0447\u0430\u043D\u0438\u044E \u0438\u0441\u043F\u043E\u043B\u044C\u0437\u0443\u0435\u0442\u0441\u044F TLS; \u043E\u043A\u043D\u043E \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F \u043F\u0440\u0435\u0434\u0443\u043F\u0440\u0435\u0434\u0438\u0442, \u0435\u0441\u043B\u0438 \u0441\u0435\u0440\u0432\u0435\u0440 \u0435\u0433\u043E \u043D\u0435 \u043F\u043E\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442.",
    "form.sshEnable": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0430\u0442\u044C\u0441\u044F \u0447\u0435\u0440\u0435\u0437 SSH-\u0442\u0443\u043D\u043D\u0435\u043B\u044C",
    "form.sshHint": "\u0414\u043E\u0441\u0442\u0443\u043F \u043A \u0431\u0430\u0437\u0435 \u0434\u0430\u043D\u043D\u044B\u0445 \u043E\u0441\u0443\u0449\u0435\u0441\u0442\u0432\u043B\u044F\u0435\u0442\u0441\u044F \u0447\u0435\u0440\u0435\u0437 SSH-\u0441\u0435\u0440\u0432\u0435\u0440. \u0420\u0435\u043A\u043E\u043C\u0435\u043D\u0434\u0443\u0435\u0442\u0441\u044F \u0430\u0443\u0442\u0435\u043D\u0442\u0438\u0444\u0438\u043A\u0430\u0446\u0438\u044F \u043F\u043E \u043A\u043B\u044E\u0447\u0443.",
    "form.sshHost": "SSH-\u0441\u0435\u0440\u0432\u0435\u0440",
    "form.sshAuth": "\u0410\u0443\u0442\u0435\u043D\u0442\u0438\u0444\u0438\u043A\u0430\u0446\u0438\u044F SSH",
    "form.sshKey": "\u0417\u0430\u043A\u0440\u044B\u0442\u044B\u0439 \u043A\u043B\u044E\u0447",
    "form.sshAgent": "\u0410\u0433\u0435\u043D\u0442 (Pageant)",
    "form.keyFile": "\u0424\u0430\u0439\u043B \u0437\u0430\u043A\u0440\u044B\u0442\u043E\u0433\u043E \u043A\u043B\u044E\u0447\u0430",
    "form.passphrase": "\u041F\u0430\u0440\u043E\u043B\u044C\u043D\u0430\u044F \u0444\u0440\u0430\u0437\u0430 \u043A\u043B\u044E\u0447\u0430",
    "form.passSaved": "(\u0441\u043E\u0445\u0440\u0430\u043D\u0435\u043D\u0430)",
    "form.passEmpty": "\u041E\u0441\u0442\u0430\u0432\u044C\u0442\u0435 \u043F\u0443\u0441\u0442\u044B\u043C, \u0435\u0441\u043B\u0438 \u043D\u0435\u0442",
    "form.sshPassword": "\u041F\u0430\u0440\u043E\u043B\u044C SSH",
    "form.hostKey": "\u041A\u043B\u044E\u0447 \u0445\u043E\u0441\u0442\u0430 SSH: {fp}",
    "form.test": "\u041F\u0440\u043E\u0432\u0435\u0440\u0438\u0442\u044C \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435",
    "form.saveConnect": "\u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C \u0438 \u043E\u0442\u043A\u0440\u044B\u0442\u044C",
    "form.connecting": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435\u2026",
    "form.testOk": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u0443\u0441\u043F\u0435\u0448\u043D\u043E",
    "form.testFail": "\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0438\u0442\u044C\u0441\u044F",
    "form.testDb": "\u0411\u0430\u0437\u0430 \u0434\u0430\u043D\u043D\u044B\u0445: {db} \xB7 \u041F\u043E\u043B\u044C\u0437\u043E\u0432\u0430\u0442\u0435\u043B\u044C: {user}",
    "form.noTls": "\u0412\u043D\u0438\u043C\u0430\u043D\u0438\u0435: \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u043D\u0435 \u0437\u0430\u0448\u0438\u0444\u0440\u043E\u0432\u0430\u043D\u043E (\u0441\u0435\u0440\u0432\u0435\u0440 \u043D\u0435 \u043F\u043E\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442 TLS).",
    "form.saved": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u0441\u043E\u0445\u0440\u0430\u043D\u0435\u043D\u043E",
    "form.changesSaved": "\u0418\u0437\u043C\u0435\u043D\u0435\u043D\u0438\u044F \u0441\u043E\u0445\u0440\u0430\u043D\u0435\u043D\u044B",
    "set.title": "\u041D\u0430\u0441\u0442\u0440\u043E\u0439\u043A\u0438",
    "set.appearance": "\u0412\u043D\u0435\u0448\u043D\u0438\u0439 \u0432\u0438\u0434",
    "set.theme": "\u0422\u0435\u043C\u0430",
    "set.themeDark": "\u041D\u043E\u0447\u043D\u0430\u044F",
    "set.themeLight": "\u0414\u043D\u0435\u0432\u043D\u0430\u044F",
    "set.themeSystem": "\u041A\u0430\u043A \u0432 \u0441\u0438\u0441\u0442\u0435\u043C\u0435",
    "set.language": "\u042F\u0437\u044B\u043A",
    "set.toLight": "\u0412\u043A\u043B\u044E\u0447\u0438\u0442\u044C \u0434\u043D\u0435\u0432\u043D\u0443\u044E \u0442\u0435\u043C\u0443",
    "set.toDark": "\u0412\u043A\u043B\u044E\u0447\u0438\u0442\u044C \u043D\u043E\u0447\u043D\u0443\u044E \u0442\u0435\u043C\u0443",
    "set.saved": "\u041D\u0430\u0441\u0442\u0440\u043E\u0439\u043A\u0438 \u0441\u043E\u0445\u0440\u0430\u043D\u0435\u043D\u044B",
    "set.query": "\u0417\u0430\u043F\u0440\u043E\u0441\u044B",
    "set.rowLimit": "\u041C\u0430\u043A\u0441\u0438\u043C\u0443\u043C \u0441\u0442\u0440\u043E\u043A \u0432 \u0440\u0435\u0437\u0443\u043B\u044C\u0442\u0430\u0442\u0435",
    "set.previewRows": "\u0421\u0442\u0440\u043E\u043A \u043F\u0440\u0438 \u043E\u0442\u043A\u0440\u044B\u0442\u0438\u0438 \u0442\u0430\u0431\u043B\u0438\u0446\u044B",
    "set.fontSize": "\u0420\u0430\u0437\u043C\u0435\u0440 \u0448\u0440\u0438\u0444\u0442\u0430 \u0440\u0435\u0434\u0430\u043A\u0442\u043E\u0440\u0430 (px)",
    "auth.subtitle": "\u0412\u043E\u0439\u0434\u0438\u0442\u0435 \u0441 \u0443\u0447\u0451\u0442\u043D\u043E\u0439 \u0437\u0430\u043F\u0438\u0441\u044C\u044E Mastertool",
    "auth.email": "\u042D\u043B. \u043F\u043E\u0447\u0442\u0430",
    "auth.password": "\u041F\u0430\u0440\u043E\u043B\u044C",
    "auth.remember": "\u0417\u0430\u043F\u043E\u043C\u043D\u0438\u0442\u044C \u043C\u0435\u043D\u044F",
    "auth.forgot": "\u0417\u0430\u0431\u044B\u043B\u0438 \u043F\u0430\u0440\u043E\u043B\u044C",
    "auth.noAccount": "\u0415\u0449\u0451 \u043D\u0435\u0442 \u0443\u0447\u0451\u0442\u043D\u043E\u0439 \u0437\u0430\u043F\u0438\u0441\u0438?",
    "auth.register": "\u0421\u043E\u0437\u0434\u0430\u0442\u044C \u0443\u0447\u0451\u0442\u043D\u0443\u044E \u0437\u0430\u043F\u0438\u0441\u044C",
    "auth.submit": "\u0412\u043E\u0439\u0442\u0438",
    "auth.working": "\u0412\u0445\u043E\u0434\u2026",
    "auth.errRequired": "\u0423\u043A\u0430\u0436\u0438\u0442\u0435 \u044D\u043B. \u043F\u043E\u0447\u0442\u0443 \u0438 \u043F\u0430\u0440\u043E\u043B\u044C.",
    "auth.errBadCredentials": "\u041D\u0435\u0432\u0435\u0440\u043D\u0430\u044F \u044D\u043B. \u043F\u043E\u0447\u0442\u0430 \u0438\u043B\u0438 \u043F\u0430\u0440\u043E\u043B\u044C.",
    "auth.errUnverified": "\u0412\u0430\u0448 \u0430\u0434\u0440\u0435\u0441 \u044D\u043B. \u043F\u043E\u0447\u0442\u044B \u0435\u0449\u0451 \u043D\u0435 \u043F\u043E\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0451\u043D. \u041F\u0435\u0440\u0435\u0439\u0434\u0438\u0442\u0435 \u043F\u043E \u0441\u0441\u044B\u043B\u043A\u0435 \u0432 \u043F\u0438\u0441\u044C\u043C\u0435.",
    "auth.errSuspended": "\u0412\u0430\u0448\u0430 \u0443\u0447\u0451\u0442\u043D\u0430\u044F \u0437\u0430\u043F\u0438\u0441\u044C \u0437\u0430\u0431\u043B\u043E\u043A\u0438\u0440\u043E\u0432\u0430\u043D\u0430.",
    "auth.errRateLimited": "\u0421\u043B\u0438\u0448\u043A\u043E\u043C \u043C\u043D\u043E\u0433\u043E \u043F\u043E\u043F\u044B\u0442\u043E\u043A. \u041F\u043E\u0432\u0442\u043E\u0440\u0438\u0442\u0435 \u0447\u0435\u0440\u0435\u0437 \u043C\u0438\u043D\u0443\u0442\u0443.",
    "auth.errOffline": "\u041D\u0435\u0442 \u0441\u0432\u044F\u0437\u0438 \u0441 \u0441\u0435\u0440\u0432\u0435\u0440\u043E\u043C. \u041F\u0440\u043E\u0432\u0435\u0440\u044C\u0442\u0435 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u043A \u0438\u043D\u0442\u0435\u0440\u043D\u0435\u0442\u0443.",
    "auth.errSessionExpired": "\u0421\u0435\u0430\u043D\u0441 \u0438\u0441\u0442\u0451\u043A \u0438\u043B\u0438 \u043F\u0430\u0440\u043E\u043B\u044C \u0431\u044B\u043B \u0438\u0437\u043C\u0435\u043D\u0451\u043D. \u0412\u043E\u0439\u0434\u0438\u0442\u0435 \u0441\u043D\u043E\u0432\u0430.",
    "auth.signedOutElsewhere": "\u0412\u044B \u0432\u044B\u0448\u043B\u0438 \u0438\u0437 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u0430 \u0432 \u0434\u0440\u0443\u0433\u043E\u043C \u043F\u0440\u0438\u043B\u043E\u0436\u0435\u043D\u0438\u0438 Mastertool. \u041B\u043E\u043A\u0430\u043B\u044C\u043D\u044B\u0435 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F \u043E\u0441\u0442\u0430\u043B\u0438\u0441\u044C \u043D\u0430 \u044D\u0442\u043E\u043C \u043A\u043E\u043C\u043F\u044C\u044E\u0442\u0435\u0440\u0435.",
    "auth.errAppDisabled": "SQL Master \u043E\u0442\u043A\u043B\u044E\u0447\u0451\u043D \u0434\u043B\u044F \u0432\u0430\u0448\u0435\u0439 \u0443\u0447\u0451\u0442\u043D\u043E\u0439 \u0437\u0430\u043F\u0438\u0441\u0438. \u041F\u043E\u0434\u0434\u0435\u0440\u0436\u043A\u0430: mastertool.download > \u041C\u043E\u044F \u0443\u0447\u0451\u0442\u043D\u0430\u044F \u0437\u0430\u043F\u0438\u0441\u044C > \u041F\u043E\u0434\u0434\u0435\u0440\u0436\u043A\u0430.",
    "auth.errWrongApp": "\u042D\u0442\u043E\u0442 \u0441\u0435\u0430\u043D\u0441 \u043F\u0440\u0438\u043D\u0430\u0434\u043B\u0435\u0436\u0438\u0442 \u0434\u0440\u0443\u0433\u043E\u043C\u0443 \u043F\u0440\u0438\u043B\u043E\u0436\u0435\u043D\u0438\u044E. \u0412\u043E\u0439\u0434\u0438\u0442\u0435 \u0432 SQL Master \u0441\u043D\u043E\u0432\u0430.",
    "auth.errServer": "\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u0432\u043E\u0439\u0442\u0438: {msg}",
    "auth.devNotice": "\u0420\u0435\u0436\u0438\u043C \u0440\u0430\u0437\u0440\u0430\u0431\u043E\u0442\u043A\u0438: \u0432\u043C\u0435\u0441\u0442\u043E \u0441\u0435\u0440\u0432\u0435\u0440\u0430 Mastertool \u0438\u0441\u043F\u043E\u043B\u044C\u0437\u0443\u0435\u0442\u0441\u044F \u043B\u043E\u043A\u0430\u043B\u044C\u043D\u0430\u044F \u0443\u0447\u0451\u0442\u043D\u0430\u044F \u0437\u0430\u043F\u0438\u0441\u044C (\u043B\u044E\u0431\u044B\u0435 \u044D\u043B. \u043F\u043E\u0447\u0442\u0430/\u043F\u0430\u0440\u043E\u043B\u044C, \u0431\u0435\u0437 \u0441\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0430\u0446\u0438\u0438).",
    "acct.section": "\u0423\u0447\u0451\u0442\u043D\u0430\u044F \u0437\u0430\u043F\u0438\u0441\u044C \u0438 \u0441\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0430\u0446\u0438\u044F",
    "acct.signedInAs": "\u0412\u044B \u0432\u043E\u0448\u043B\u0438 \u043A\u0430\u043A {email}",
    "acct.syncToggle": "\u0421\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0438\u0440\u043E\u0432\u0430\u0442\u044C \u0431\u0438\u0431\u043B\u0438\u043E\u0442\u0435\u043A\u0443 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0439 \u0441 \u0432\u0435\u0431-\u0432\u0435\u0440\u0441\u0438\u0435\u0439",
    "acct.syncHint": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F, \u043F\u0430\u043F\u043A\u0438 \u0438 \u043E\u0431\u0449\u0438\u0435 \u043D\u0430\u0441\u0442\u0440\u043E\u0439\u043A\u0438 \u0448\u0438\u0444\u0440\u0443\u044E\u0442\u0441\u044F \u0441\u043A\u0432\u043E\u0437\u043D\u044B\u043C \u0448\u0438\u0444\u0440\u043E\u0432\u0430\u043D\u0438\u0435\u043C \u0438 \u0440\u0435\u0437\u0435\u0440\u0432\u0438\u0440\u0443\u044E\u0442\u0441\u044F \u0432 \u0432\u0430\u0448\u0435\u0439 \u0443\u0447\u0451\u0442\u043D\u043E\u0439 \u0437\u0430\u043F\u0438\u0441\u0438 Mastertool; \u043F\u0430\u0440\u043E\u043B\u0438 \u043F\u0435\u0440\u0435\u0434\u0430\u044E\u0442\u0441\u044F \u0442\u043E\u043B\u044C\u043A\u043E \u0432\u043D\u0443\u0442\u0440\u0438 \u0437\u0430\u0448\u0438\u0444\u0440\u043E\u0432\u0430\u043D\u043D\u043E\u0433\u043E \u0431\u043B\u043E\u043A\u0430, \u0438 \u0441\u0435\u0440\u0432\u0435\u0440 \u043D\u0435 \u043C\u043E\u0436\u0435\u0442 \u0435\u0433\u043E \u043F\u0440\u043E\u0447\u0438\u0442\u0430\u0442\u044C.",
    "acct.lastSync": "\u041F\u043E\u0441\u043B\u0435\u0434\u043D\u044F\u044F \u0441\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0430\u0446\u0438\u044F: {time}",
    "acct.never": "\u0415\u0449\u0451 \u043D\u0435 \u0441\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0438\u0440\u043E\u0432\u0430\u043D\u043E",
    "acct.syncNow": "\u0421\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0438\u0440\u043E\u0432\u0430\u0442\u044C",
    "acct.deleteRemote": "\u0423\u0434\u0430\u043B\u0438\u0442\u044C \u043A\u043E\u043F\u0438\u044E \u043D\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435",
    "acct.deleteRemoteMsg": "\u0417\u0430\u0448\u0438\u0444\u0440\u043E\u0432\u0430\u043D\u043D\u0430\u044F \u043A\u043E\u043F\u0438\u044F \u0431\u0438\u0431\u043B\u0438\u043E\u0442\u0435\u043A\u0438 \u0432 \u0432\u0430\u0448\u0435\u0439 \u0443\u0447\u0451\u0442\u043D\u043E\u0439 \u0437\u0430\u043F\u0438\u0441\u0438 \u0431\u0443\u0434\u0435\u0442 \u0443\u0434\u0430\u043B\u0435\u043D\u0430, \u0430 \u0441\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0430\u0446\u0438\u044F \u0432\u044B\u043A\u043B\u044E\u0447\u0435\u043D\u0430. \u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F \u043D\u0430 \u044D\u0442\u043E\u043C \u043A\u043E\u043C\u043F\u044C\u044E\u0442\u0435\u0440\u0435 \u0441\u043E\u0445\u0440\u0430\u043D\u044F\u0442\u0441\u044F.",
    "acct.deleteRemoteDone": "\u041A\u043E\u043F\u0438\u044F \u043D\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435 \u0443\u0434\u0430\u043B\u0435\u043D\u0430; \u0441\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0430\u0446\u0438\u044F \u0432\u044B\u043A\u043B\u044E\u0447\u0435\u043D\u0430",
    "acct.logout": "\u0412\u044B\u0439\u0442\u0438",
    "acct.logoutMsg": "\u0412\u044B \u0432\u044B\u0439\u0434\u0435\u0442\u0435 \u0438\u0437 \u0443\u0447\u0451\u0442\u043D\u043E\u0439 \u0437\u0430\u043F\u0438\u0441\u0438; \u043E\u0442\u043A\u0440\u044B\u0442\u044B\u0435 \u043E\u043A\u043D\u0430 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0439 \u0438 \u0432\u044B\u043F\u043E\u043B\u043D\u044F\u044E\u0449\u0438\u0435\u0441\u044F \u0437\u0430\u043F\u0440\u043E\u0441\u044B \u0431\u0443\u0434\u0443\u0442 \u0437\u0430\u043A\u0440\u044B\u0442\u044B. \u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F \u043D\u0430 \u044D\u0442\u043E\u043C \u043A\u043E\u043C\u043F\u044C\u044E\u0442\u0435\u0440\u0435 \u0441\u043E\u0445\u0440\u0430\u043D\u044F\u0442\u0441\u044F.",
    "acct.myAccount": "\u041C\u043E\u044F \u0443\u0447\u0451\u0442\u043D\u0430\u044F \u0437\u0430\u043F\u0438\u0441\u044C (\u0432\u0435\u0431)",
    "acct.backupNotice": "\u0412\u044B\u043F\u043E\u043B\u043D\u0435\u043D \u0432\u0445\u043E\u0434 \u0441 \u0434\u0440\u0443\u0433\u043E\u0439 \u0443\u0447\u0451\u0442\u043D\u043E\u0439 \u0437\u0430\u043F\u0438\u0441\u044C\u044E; \u043F\u0440\u0435\u0436\u043D\u0438\u0435 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F \u043D\u0430 \u044D\u0442\u043E\u043C \u043A\u043E\u043C\u043F\u044C\u044E\u0442\u0435\u0440\u0435 \u0441\u043E\u0445\u0440\u0430\u043D\u0435\u043D\u044B \u0432 \u0440\u0435\u0437\u0435\u0440\u0432\u043D\u043E\u0439 \u043A\u043E\u043F\u0438\u0438.",
    "sync.off": "\u0421\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0430\u0446\u0438\u044F \u0432\u044B\u043A\u043B\u044E\u0447\u0435\u043D\u0430",
    "sync.syncing": "\u0421\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0430\u0446\u0438\u044F\u2026",
    "sync.offline": "\u041D\u0435\u0442 \u0441\u0435\u0442\u0438 \u2014 \u0438\u0437\u043C\u0435\u043D\u0435\u043D\u0438\u044F \u0431\u0443\u0434\u0443\u0442 \u043E\u0442\u043F\u0440\u0430\u0432\u043B\u0435\u043D\u044B \u043F\u043E\u0441\u043B\u0435 \u0432\u043E\u0441\u0441\u0442\u0430\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u044F \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F",
    "sync.errDecrypt": "\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u0440\u0430\u0441\u0448\u0438\u0444\u0440\u043E\u0432\u0430\u0442\u044C \u043A\u043E\u043F\u0438\u044E \u043D\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435 \u043A\u043B\u044E\u0447\u043E\u043C \u044D\u0442\u043E\u0439 \u0443\u0447\u0451\u0442\u043D\u043E\u0439 \u0437\u0430\u043F\u0438\u0441\u0438; \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F \u043D\u0430 \u044D\u0442\u043E\u043C \u043A\u043E\u043C\u043F\u044C\u044E\u0442\u0435\u0440\u0435 \u0441\u043E\u0445\u0440\u0430\u043D\u0435\u043D\u044B.",
    "sync.errTooLarge": "\u0411\u0438\u0431\u043B\u0438\u043E\u0442\u0435\u043A\u0430 \u043F\u0440\u0435\u0432\u044B\u0448\u0430\u0435\u0442 \u043B\u0438\u043C\u0438\u0442 5 \u041C\u0411 \u0438 \u043D\u0435 \u043C\u043E\u0436\u0435\u0442 \u0431\u044B\u0442\u044C \u0441\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0438\u0440\u043E\u0432\u0430\u043D\u0430.",
    "sync.error": "\u041E\u0448\u0438\u0431\u043A\u0430 \u0441\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0430\u0446\u0438\u0438: {msg}",
    "sync.devMode": "\u0420\u0435\u0436\u0438\u043C \u0440\u0430\u0437\u0440\u0430\u0431\u043E\u0442\u043A\u0438 \u2014 \u0431\u0435\u0437 \u0441\u0438\u043D\u0445\u0440\u043E\u043D\u0438\u0437\u0430\u0446\u0438\u0438",
    "update.available": "\u0414\u043E\u0441\u0442\u0443\u043F\u043D\u0430 \u043D\u043E\u0432\u0430\u044F \u0432\u0435\u0440\u0441\u0438\u044F: {version}",
    "update.hint": "\u0421\u043A\u0430\u0447\u0430\u0439\u0442\u0435 \u0435\u0451 \u0432 \u0441\u0432\u043E\u0435\u0439 \u0443\u0447\u0451\u0442\u043D\u043E\u0439 \u0437\u0430\u043F\u0438\u0441\u0438 Mastertool.",
    "update.open": "\u041E\u0442\u043A\u0440\u044B\u0442\u044C \u0443\u0447\u0451\u0442\u043D\u0443\u044E \u0437\u0430\u043F\u0438\u0441\u044C",
    "cw.objects": "\u041E\u0431\u044A\u0435\u043A\u0442\u044B",
    "cw.collapseAll": "\u0421\u0432\u0435\u0440\u043D\u0443\u0442\u044C \u0432\u0441\u0451",
    "cw.filterPh": "\u0424\u0438\u043B\u044C\u0442\u0440 \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043D\u043D\u044B\u0445 \u043E\u0431\u044A\u0435\u043A\u0442\u043E\u0432\u2026",
    "cw.empty": "(\u043F\u0443\u0441\u0442\u043E)",
    "cw.openData": "\u041E\u0442\u043A\u0440\u044B\u0442\u044C \u0434\u0430\u043D\u043D\u044B\u0435",
    "cw.showDdl": "\u041F\u043E\u043A\u0430\u0437\u0430\u0442\u044C DDL",
    "cw.openCode": "\u041E\u0442\u043A\u0440\u044B\u0442\u044C \u043A\u043E\u0434",
    "cw.selectSql": "\u0421\u0433\u0435\u043D\u0435\u0440\u0438\u0440\u043E\u0432\u0430\u0442\u044C SELECT",
    "cw.addToBuilder": "\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u0432 \u043A\u043E\u043D\u0441\u0442\u0440\u0443\u043A\u0442\u043E\u0440 \u0437\u0430\u043F\u0440\u043E\u0441\u043E\u0432",
    "cw.newSqlHere": "\u041D\u043E\u0432\u044B\u0439 SQL \u0437\u0434\u0435\u0441\u044C",
    "cw.copyName": "\u041A\u043E\u043F\u0438\u0440\u043E\u0432\u0430\u0442\u044C \u0438\u043C\u044F",
    "cw.copied": "\u0421\u043A\u043E\u043F\u0438\u0440\u043E\u0432\u0430\u043D\u043E \u0432 \u0431\u0443\u0444\u0435\u0440 \u043E\u0431\u043C\u0435\u043D\u0430",
    "cw.newSql": "\u041D\u043E\u0432\u044B\u0439 SQL",
    "cw.builder": "\u041A\u043E\u043D\u0441\u0442\u0440\u0443\u043A\u0442\u043E\u0440 \u0437\u0430\u043F\u0440\u043E\u0441\u043E\u0432",
    "cw.reconnect": "\u041F\u0435\u0440\u0435\u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0438\u0442\u044C\u0441\u044F",
    "cw.readOnly": "\u0422\u043E\u043B\u044C\u043A\u043E \u0447\u0442\u0435\u043D\u0438\u0435",
    "cw.readWrite": "\u0417\u0430\u043F\u0438\u0441\u044C \u0432\u043A\u043B.",
    "cw.readOnlyTip": "\u0422\u043E\u043B\u044C\u043A\u043E \u0447\u0442\u0435\u043D\u0438\u0435: DML/DDL \u0442\u0440\u0435\u0431\u0443\u044E\u0442 \u043F\u043E\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043D\u0438\u044F. \u041D\u0430\u0436\u043C\u0438\u0442\u0435, \u0447\u0442\u043E\u0431\u044B \u0432\u044B\u043A\u043B\u044E\u0447\u0438\u0442\u044C",
    "cw.readWriteTip": "\u0417\u0430\u043F\u0438\u0441\u044C \u0432\u043A\u043B\u044E\u0447\u0435\u043D\u0430: \u043A\u043E\u043C\u0430\u043D\u0434\u044B \u0432\u044B\u043F\u043E\u043B\u043D\u044F\u044E\u0442\u0441\u044F \u0431\u0435\u0437 \u043F\u043E\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043D\u0438\u044F. \u041D\u0430\u0436\u043C\u0438\u0442\u0435, \u0447\u0442\u043E\u0431\u044B \u0432\u0435\u0440\u043D\u0443\u0442\u044C\u0441\u044F \u0432 \u0440\u0435\u0436\u0438\u043C \u0442\u043E\u043B\u044C\u043A\u043E \u0434\u043B\u044F \u0447\u0442\u0435\u043D\u0438\u044F",
    "cw.disableRo": "\u0412\u044B\u043A\u043B\u044E\u0447\u0438\u0442\u044C \u0440\u0435\u0436\u0438\u043C \u0442\u043E\u043B\u044C\u043A\u043E \u0434\u043B\u044F \u0447\u0442\u0435\u043D\u0438\u044F?",
    "cw.disableRoMsg": "\u041F\u043E\u043A\u0430 \u044D\u0442\u043E \u043E\u043A\u043D\u043E \u043E\u0442\u043A\u0440\u044B\u0442\u043E, INSERT/UPDATE/DELETE \u0438 DDL \u0431\u0443\u0434\u0443\u0442 \u0432\u044B\u043F\u043E\u043B\u043D\u044F\u0442\u044C\u0441\u044F \u0431\u0435\u0437 \u0437\u0430\u043F\u0440\u043E\u0441\u0430.",
    "cw.disableRoOk": "\u0420\u0430\u0437\u0440\u0435\u0448\u0438\u0442\u044C \u0437\u0430\u043F\u0438\u0441\u044C",
    "cw.roOn": "\u0420\u0435\u0436\u0438\u043C \u0442\u043E\u043B\u044C\u043A\u043E \u0434\u043B\u044F \u0447\u0442\u0435\u043D\u0438\u044F \u0432\u043A\u043B\u044E\u0447\u0451\u043D",
    "cw.roOff": "\u0417\u0430\u043F\u0438\u0441\u044C \u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043D\u0430 \u2014 \u0431\u0443\u0434\u044C\u0442\u0435 \u043E\u0441\u0442\u043E\u0440\u043E\u0436\u043D\u044B",
    "cw.passwordTitle": "\u0422\u0440\u0435\u0431\u0443\u0435\u0442\u0441\u044F \u043F\u0430\u0440\u043E\u043B\u044C",
    "cw.passwordFor": "\u041F\u0430\u0440\u043E\u043B\u044C \u0434\u043B\u044F {user}@{host}",
    "cw.notConnected": "\u041D\u0435\u0442 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F",
    "cw.connected": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u043E",
    "cw.connecting": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435\u2026",
    "cw.noTls": "\u0411\u0435\u0437 \u0448\u0438\u0444\u0440\u043E\u0432\u0430\u043D\u0438\u044F",
    "cw.connectFailed": "\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0438\u0442\u044C\u0441\u044F",
    "cw.retry": "\u041F\u043E\u0432\u0442\u043E\u0440\u0438\u0442\u044C",
    "cw.resetCancel": "\u0417\u0430\u043F\u0440\u043E\u0441 \u043D\u0435 \u043E\u0442\u0432\u0435\u0442\u0438\u043B \u043D\u0430 \u043E\u0442\u043C\u0435\u043D\u0443; \u0432\u044B\u043F\u043E\u043B\u043D\u044F\u0435\u0442\u0441\u044F \u043F\u0435\u0440\u0435\u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435.",
    "cw.resetExit": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u043A \u0431\u0430\u0437\u0435 \u0434\u0430\u043D\u043D\u044B\u0445 \u043F\u0440\u0435\u0440\u0432\u0430\u043D\u043E; \u0432\u044B\u043F\u043E\u043B\u043D\u044F\u0435\u0442\u0441\u044F \u043F\u0435\u0440\u0435\u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435.",
    "cw.emptyWorkspace": "\u0414\u0432\u0430\u0436\u0434\u044B \u0449\u0451\u043B\u043A\u043D\u0438\u0442\u0435 \u0442\u0430\u0431\u043B\u0438\u0446\u0443 \u0432 \u0434\u0435\u0440\u0435\u0432\u0435 \u0438\u043B\u0438 \u043D\u0430\u0436\u043C\u0438\u0442\u0435 Ctrl+T, \u0447\u0442\u043E\u0431\u044B \u043E\u0442\u043A\u0440\u044B\u0442\u044C \u043D\u043E\u0432\u0443\u044E \u0432\u043A\u043B\u0430\u0434\u043A\u0443 SQL.",
    "cw.closeTab": "\u0417\u0430\u043A\u0440\u044B\u0442\u044C \u0432\u043A\u043B\u0430\u0434\u043A\u0443?",
    "cw.closeTabMsg": "SQL \u0432\u043E \u0432\u043A\u043B\u0430\u0434\u043A\u0435 \xAB{name}\xBB \u043D\u0435 \u0441\u043E\u0445\u0440\u0430\u043D\u0451\u043D.",
    "cw.closeTabOk": "\u0417\u0430\u043A\u0440\u044B\u0442\u044C",
    "tree.tables": "\u0422\u0430\u0431\u043B\u0438\u0446\u044B",
    "tree.views": "\u041F\u0440\u0435\u0434\u0441\u0442\u0430\u0432\u043B\u0435\u043D\u0438\u044F",
    "tree.matviews": "\u041C\u0430\u0442\u0435\u0440\u0438\u0430\u043B\u0438\u0437\u043E\u0432\u0430\u043D\u043D\u044B\u0435 \u043F\u0440\u0435\u0434\u0441\u0442\u0430\u0432\u043B\u0435\u043D\u0438\u044F",
    "tree.foreign_tables": "\u0412\u043D\u0435\u0448\u043D\u0438\u0435 \u0442\u0430\u0431\u043B\u0438\u0446\u044B",
    "tree.functions": "\u0424\u0443\u043D\u043A\u0446\u0438\u0438",
    "tree.procedures": "\u041F\u0440\u043E\u0446\u0435\u0434\u0443\u0440\u044B",
    "tree.triggers": "\u0422\u0440\u0438\u0433\u0433\u0435\u0440\u044B",
    "tree.sequences": "\u041F\u043E\u0441\u043B\u0435\u0434\u043E\u0432\u0430\u0442\u0435\u043B\u044C\u043D\u043E\u0441\u0442\u0438",
    "tree.types": "\u0422\u0438\u043F\u044B",
    "tree.columns": "\u0421\u0442\u043E\u043B\u0431\u0446\u044B",
    "tree.indexes": "\u0418\u043D\u0434\u0435\u043A\u0441\u044B",
    "tree.constraints": "\u041E\u0433\u0440\u0430\u043D\u0438\u0447\u0435\u043D\u0438\u044F",
    "tree.files": "\u0424\u0430\u0439\u043B\u044B",
    "kind.table": "\u0422\u0430\u0431\u043B\u0438\u0446\u0430",
    "kind.view": "\u041F\u0440\u0435\u0434\u0441\u0442\u0430\u0432\u043B\u0435\u043D\u0438\u0435",
    "kind.matview": "\u041C\u0430\u0442\u0435\u0440\u0438\u0430\u043B\u0438\u0437\u043E\u0432\u0430\u043D\u043D\u043E\u0435 \u043F\u0440\u0435\u0434\u0441\u0442\u0430\u0432\u043B\u0435\u043D\u0438\u0435",
    "kind.foreign-table": "\u0412\u043D\u0435\u0448\u043D\u044F\u044F \u0442\u0430\u0431\u043B\u0438\u0446\u0430",
    "kind.function": "\u0424\u0443\u043D\u043A\u0446\u0438\u044F",
    "kind.procedure": "\u041F\u0440\u043E\u0446\u0435\u0434\u0443\u0440\u0430",
    "kind.trigger": "\u0422\u0440\u0438\u0433\u0433\u0435\u0440",
    "kind.sequence": "\u041F\u043E\u0441\u043B\u0435\u0434\u043E\u0432\u0430\u0442\u0435\u043B\u044C\u043D\u043E\u0441\u0442\u044C",
    "kind.type": "\u0422\u0438\u043F",
    "kind.index": "\u0418\u043D\u0434\u0435\u043A\u0441",
    "kind.constraint": "\u041E\u0433\u0440\u0430\u043D\u0438\u0447\u0435\u043D\u0438\u0435",
    "sql.run": "\u0412\u044B\u043F\u043E\u043B\u043D\u0438\u0442\u044C",
    "sql.runStatement": "\u0412\u044B\u043F\u043E\u043B\u043D\u0438\u0442\u044C \u043E\u043F\u0435\u0440\u0430\u0442\u043E\u0440",
    "sql.cancel": "\u041E\u0442\u043C\u0435\u043D\u0430",
    "sql.database": "\u0411\u0430\u0437\u0430 \u0434\u0430\u043D\u043D\u044B\u0445",
    "sql.history": "\u0418\u0441\u0442\u043E\u0440\u0438\u044F",
    "sql.export": "\u042D\u043A\u0441\u043F\u043E\u0440\u0442",
    "sql.running": "\u0412\u044B\u043F\u043E\u043B\u043D\u0435\u043D\u0438\u0435\u2026",
    "sql.done": "\u0413\u043E\u0442\u043E\u0432\u043E \xB7 {ms} \u043C\u0441",
    "sql.doneErrors": "\u041E\u0448\u0438\u0431\u043E\u043A: {n} \xB7 {ms} \u043C\u0441",
    "sql.ddlHint": "\u0421\u0445\u0435\u043C\u0430 \u0438\u0437\u043C\u0435\u043D\u0435\u043D\u0430: \u043D\u0430\u0436\u043C\u0438\u0442\u0435 \xAB\u041E\u0431\u043D\u043E\u0432\u0438\u0442\u044C\xBB, \u0447\u0442\u043E\u0431\u044B \u043F\u0435\u0440\u0435\u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044C \u0434\u0435\u0440\u0435\u0432\u043E.",
    "sql.placeholder": "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 SQL\u2026 Ctrl+Enter: \u0432\u044B\u043F\u043E\u043B\u043D\u0438\u0442\u044C \u0432\u044B\u0434\u0435\u043B\u0435\u043D\u043D\u043E\u0435/\u0432\u0441\u0451 \xB7 Ctrl+Shift+Enter: \u043E\u043F\u0435\u0440\u0430\u0442\u043E\u0440 \u043F\u043E\u0434 \u043A\u0443\u0440\u0441\u043E\u0440\u043E\u043C \xB7 Ctrl+Space: \u0430\u0432\u0442\u043E\u0434\u043E\u043F\u043E\u043B\u043D\u0435\u043D\u0438\u0435",
    "sql.tabTitle": "SQL {n}",
    "sql.historyEmpty": "\u0414\u043B\u044F \u044D\u0442\u043E\u0433\u043E \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F \u0438\u0441\u0442\u043E\u0440\u0438\u0438 \u043D\u0435\u0442.",
    "sql.rowsShort": "\u0441\u0442\u0440\u043E\u043A",
    "res.result": "\u0420\u0435\u0437\u0443\u043B\u044C\u0442\u0430\u0442 {n}",
    "res.messages": "\u0421\u043E\u043E\u0431\u0449\u0435\u043D\u0438\u044F",
    "res.rows": "\u0421\u0442\u0440\u043E\u043A: {n} \xB7 {ms} \u043C\u0441",
    "res.rowsTruncated": "\u041F\u043E\u043A\u0430\u0437\u0430\u043D\u044B \u043F\u0435\u0440\u0432\u044B\u0435 {n} \u0441\u0442\u0440\u043E\u043A (\u043B\u0438\u043C\u0438\u0442) \xB7 {ms} \u043C\u0441",
    "res.noRows": "\u041D\u0435\u0442 \u0441\u0442\u0440\u043E\u043A",
    "res.affected": "{cmd}: \u0437\u0430\u0442\u0440\u043E\u043D\u0443\u0442\u043E \u0441\u0442\u0440\u043E\u043A: {n} \xB7 {ms} \u043C\u0441",
    "res.command": "{cmd} \xB7 {ms} \u043C\u0441",
    "res.cancelled": "\u041E\u0442\u043C\u0435\u043D\u0435\u043D\u043E",
    "grid.copy": "\u041A\u043E\u043F\u0438\u0440\u043E\u0432\u0430\u0442\u044C",
    "grid.copyHeaders": "\u041A\u043E\u043F\u0438\u0440\u043E\u0432\u0430\u0442\u044C \u0441 \u0437\u0430\u0433\u043E\u043B\u043E\u0432\u043A\u0430\u043C\u0438",
    "grid.export": "\u042D\u043A\u0441\u043F\u043E\u0440\u0442\u0438\u0440\u043E\u0432\u0430\u0442\u044C \u044D\u0442\u043E\u0442 \u0440\u0435\u0437\u0443\u043B\u044C\u0442\u0430\u0442\u2026",
    "data.columns": "\u0421\u0442\u043E\u043B\u0431\u0446\u044B",
    "data.columnsHidden": "\u0421\u0442\u043E\u043B\u0431\u0446\u044B ({n}/{total})",
    "data.addFilter": "\u0424\u0438\u043B\u044C\u0442\u0440",
    "data.limit": "\u0427\u0438\u0441\u043B\u043E \u0441\u0442\u0440\u043E\u043A",
    "data.firstN": "\u041F\u0435\u0440\u0432\u044B\u0435 {n}",
    "data.all": "\u0412\u0441\u0435 (\u0441 \u043B\u0438\u043C\u0438\u0442\u043E\u043C)",
    "data.openInEditor": "\u041E\u0442\u043A\u0440\u044B\u0442\u044C \u0432 \u0440\u0435\u0434\u0430\u043A\u0442\u043E\u0440\u0435 SQL",
    "data.clearFilters": "\u0421\u0431\u0440\u043E\u0441\u0438\u0442\u044C \u0444\u0438\u043B\u044C\u0442\u0440\u044B",
    "data.rows": "\u0421\u0442\u0440\u043E\u043A: {n} \xB7 {ms} \u043C\u0441",
    "data.rowsMore": "\u041F\u0435\u0440\u0432\u044B\u0435 {n} \u0441\u0442\u0440\u043E\u043A \xB7 {ms} \u043C\u0441",
    "data.error": "\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044C \u0434\u0430\u043D\u043D\u044B\u0435",
    "data.sortAsc": "\u0421\u043E\u0440\u0442\u0438\u0440\u043E\u0432\u0430\u0442\u044C \u043F\u043E \u0432\u043E\u0437\u0440\u0430\u0441\u0442\u0430\u043D\u0438\u044E",
    "data.sortDesc": "\u0421\u043E\u0440\u0442\u0438\u0440\u043E\u0432\u0430\u0442\u044C \u043F\u043E \u0443\u0431\u044B\u0432\u0430\u043D\u0438\u044E",
    "data.sortClear": "\u0421\u0431\u0440\u043E\u0441\u0438\u0442\u044C \u0441\u043E\u0440\u0442\u0438\u0440\u043E\u0432\u043A\u0443",
    "data.filterColumn": "\u0424\u0438\u043B\u044C\u0442\u0440 \u043F\u043E \u044D\u0442\u043E\u043C\u0443 \u0441\u0442\u043E\u043B\u0431\u0446\u0443\u2026",
    "data.hideColumn": "\u0421\u043A\u0440\u044B\u0442\u044C \u0441\u0442\u043E\u043B\u0431\u0435\u0446",
    "data.showAll": "\u041F\u043E\u043A\u0430\u0437\u0430\u0442\u044C \u0432\u0441\u0435 \u0441\u0442\u043E\u043B\u0431\u0446\u044B",
    "data.filterEq": "\u0420\u0430\u0432\u043D\u043E \xAB{v}\xBB",
    "data.filterNe": "\u041D\u0435 \u0440\u0430\u0432\u043D\u043E \xAB{v}\xBB",
    "data.filterNull": "NULL / \u043D\u0435 NULL",
    "data.column": "\u0421\u0442\u043E\u043B\u0431\u0435\u0446",
    "data.operator": "\u0423\u0441\u043B\u043E\u0432\u0438\u0435",
    "data.value": "\u0417\u043D\u0430\u0447\u0435\u043D\u0438\u0435",
    "data.inHint": "\u0414\u043B\u044F \xAB\u0432 \u0441\u043F\u0438\u0441\u043A\u0435\xBB \u043F\u0435\u0440\u0435\u0447\u0438\u0441\u043B\u0438\u0442\u0435 \u0437\u043D\u0430\u0447\u0435\u043D\u0438\u044F \u0447\u0435\u0440\u0435\u0437 \u0437\u0430\u043F\u044F\u0442\u0443\u044E.",
    "data.filterTitle": "\u0424\u0438\u043B\u044C\u0442\u0440",
    "data.selectAll": "\u0412\u0441\u0435",
    "data.selectNone": "\u041D\u0438\u0447\u0435\u0433\u043E",
    "op.=": "\u0440\u0430\u0432\u043D\u043E",
    "op.<>": "\u043D\u0435 \u0440\u0430\u0432\u043D\u043E",
    "op.<": "\u043C\u0435\u043D\u044C\u0448\u0435",
    "op.>": "\u0431\u043E\u043B\u044C\u0448\u0435",
    "op.<=": "\u043C\u0435\u043D\u044C\u0448\u0435 \u0438\u043B\u0438 \u0440\u0430\u0432\u043D\u043E",
    "op.>=": "\u0431\u043E\u043B\u044C\u0448\u0435 \u0438\u043B\u0438 \u0440\u0430\u0432\u043D\u043E",
    "op.contains": "\u0441\u043E\u0434\u0435\u0440\u0436\u0438\u0442",
    "op.not contains": "\u043D\u0435 \u0441\u043E\u0434\u0435\u0440\u0436\u0438\u0442",
    "op.starts": "\u043D\u0430\u0447\u0438\u043D\u0430\u0435\u0442\u0441\u044F \u0441",
    "op.ends": "\u0437\u0430\u043A\u0430\u043D\u0447\u0438\u0432\u0430\u0435\u0442\u0441\u044F \u043D\u0430",
    "op.like": "LIKE",
    "op.not like": "NOT LIKE",
    "op.in": "\u0432 \u0441\u043F\u0438\u0441\u043A\u0435",
    "op.not in": "\u043D\u0435 \u0432 \u0441\u043F\u0438\u0441\u043A\u0435",
    "op.is null": "is NULL",
    "op.is not null": "is not NULL",
    "code.execute": "\u0412\u044B\u043F\u043E\u043B\u043D\u0438\u0442\u044C",
    "code.loading": "\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430\u2026",
    "code.empty": "\u041E\u043F\u0440\u0435\u0434\u0435\u043B\u0435\u043D\u0438\u0435 \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D\u043E",
    "qb.addTable": "\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u0442\u0430\u0431\u043B\u0438\u0446\u0443",
    "qb.limit": "\u041B\u0438\u043C\u0438\u0442",
    "qb.clear": "\u041E\u0447\u0438\u0441\u0442\u0438\u0442\u044C",
    "qb.hint": "\u041F\u0435\u0440\u0435\u0442\u0430\u0449\u0438\u0442\u0435 \u0441\u044E\u0434\u0430 \u0442\u0430\u0431\u043B\u0438\u0446\u044B \u0438\u0437 \u0434\u0435\u0440\u0435\u0432\u0430 \u0438\u043B\u0438 \u043D\u0430\u0436\u043C\u0438\u0442\u0435 \xAB\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u0442\u0430\u0431\u043B\u0438\u0446\u0443\xBB. \u041F\u0435\u0440\u0435\u0442\u0430\u0449\u0438\u0442\u0435 \u0441\u0442\u043E\u043B\u0431\u0435\u0446 \u043D\u0430 \u0441\u0442\u043E\u043B\u0431\u0435\u0446 \u0434\u0440\u0443\u0433\u043E\u0439 \u0442\u0430\u0431\u043B\u0438\u0446\u044B, \u0447\u0442\u043E\u0431\u044B \u0441\u043E\u0437\u0434\u0430\u0442\u044C JOIN.",
    "qb.columns": "\u0421\u0442\u043E\u043B\u0431\u0446\u044B",
    "qb.conditions": "\u0423\u0441\u043B\u043E\u0432\u0438\u044F",
    "qb.results": "\u0420\u0435\u0437\u0443\u043B\u044C\u0442\u0430\u0442\u044B",
    "qb.generated": "\u0421\u0433\u0435\u043D\u0435\u0440\u0438\u0440\u043E\u0432\u0430\u043D\u043D\u044B\u0439 SQL",
    "qb.regenerate": "\u041F\u0435\u0440\u0435\u0441\u043E\u0437\u0434\u0430\u0442\u044C \u043F\u043E \u0434\u0438\u0430\u0433\u0440\u0430\u043C\u043C\u0435",
    "qb.otherDb": "\u041A\u043E\u043D\u0441\u0442\u0440\u0443\u043A\u0442\u043E\u0440 \u0437\u0430\u043F\u0440\u043E\u0441\u043E\u0432 \u0440\u0430\u0431\u043E\u0442\u0430\u0435\u0442 \u0441 \u0442\u0430\u0431\u043B\u0438\u0446\u0430\u043C\u0438 \u0442\u043E\u043B\u044C\u043A\u043E \u043E\u0434\u043D\u043E\u0439 \u0431\u0430\u0437\u044B \u0434\u0430\u043D\u043D\u044B\u0445.",
    "qb.dragJoin": "\u041F\u0435\u0440\u0435\u0442\u0430\u0449\u0438\u0442\u0435 \u043D\u0430 \u0441\u0442\u043E\u043B\u0431\u0435\u0446 \u0434\u0440\u0443\u0433\u043E\u0439 \u0442\u0430\u0431\u043B\u0438\u0446\u044B \u0434\u043B\u044F JOIN",
    "qb.swapJoin": "\u041F\u043E\u043C\u0435\u043D\u044F\u0442\u044C \u043D\u0430\u043F\u0440\u0430\u0432\u043B\u0435\u043D\u0438\u0435",
    "qb.deleteJoin": "\u0423\u0434\u0430\u043B\u0438\u0442\u044C JOIN",
    "qb.noColumns": "\u041E\u0442\u043C\u0435\u0442\u044C\u0442\u0435 \u0441\u0442\u043E\u043B\u0431\u0446\u044B \u0432 \u0442\u0430\u0431\u043B\u0438\u0446\u0430\u0445 (\u043D\u0438\u0447\u0435\u0433\u043E \u043D\u0435 \u043E\u0442\u043C\u0435\u0447\u0435\u043D\u043E = SELECT *).",
    "qb.output": "\u041F\u043E\u043A\u0430\u0437",
    "qb.column": "\u0421\u0442\u043E\u043B\u0431\u0435\u0446",
    "qb.alias": "\u041F\u0441\u0435\u0432\u0434\u043E\u043D\u0438\u043C",
    "qb.aggregate": "\u0410\u0433\u0440\u0435\u0433\u0430\u0442",
    "qb.sort": "\u0421\u043E\u0440\u0442\u0438\u0440\u043E\u0432\u043A\u0430",
    "qb.addCondition": "\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u0443\u0441\u043B\u043E\u0432\u0438\u0435",
    "qb.tabTitle": "\u0417\u0430\u043F\u0440\u043E\u0441 {n}",
    "ro.title": "\u0420\u0435\u0436\u0438\u043C \u0442\u043E\u043B\u044C\u043A\u043E \u0434\u043B\u044F \u0447\u0442\u0435\u043D\u0438\u044F",
    "ro.message": "\u042D\u0442\u043E \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u0440\u0430\u0431\u043E\u0442\u0430\u0435\u0442 \u0432 \u0440\u0435\u0436\u0438\u043C\u0435 \u0442\u043E\u043B\u044C\u043A\u043E \u0434\u043B\u044F \u0447\u0442\u0435\u043D\u0438\u044F. \u0421\u043B\u0435\u0434\u0443\u044E\u0449\u0438\u0435 \u043E\u043F\u0435\u0440\u0430\u0442\u043E\u0440\u044B \u043C\u043E\u0433\u0443\u0442 \u0438\u0437\u043C\u0435\u043D\u0438\u0442\u044C \u0434\u0430\u043D\u043D\u044B\u0435 \u0438\u043B\u0438 \u0441\u0445\u0435\u043C\u0443:",
    "ro.hint": "\u041C\u043E\u0436\u043D\u043E \u0440\u0430\u0437\u0440\u0435\u0448\u0438\u0442\u044C \u0438\u0445 \u0442\u043E\u043B\u044C\u043A\u043E \u0434\u043B\u044F \u044D\u0442\u043E\u0433\u043E \u0437\u0430\u043F\u0443\u0441\u043A\u0430; \u0437\u0430\u0442\u0435\u043C \u0440\u0435\u0436\u0438\u043C \u0442\u043E\u043B\u044C\u043A\u043E \u0434\u043B\u044F \u0447\u0442\u0435\u043D\u0438\u044F \u0432\u043E\u0441\u0441\u0442\u0430\u043D\u043E\u0432\u0438\u0442\u0441\u044F.",
    "ro.runOnce": "\u0412\u044B\u043F\u043E\u043B\u043D\u0438\u0442\u044C \u043E\u0434\u0438\u043D \u0440\u0430\u0437",
    "ro.notRun": "\u0420\u0435\u0436\u0438\u043C \u0442\u043E\u043B\u044C\u043A\u043E \u0434\u043B\u044F \u0447\u0442\u0435\u043D\u0438\u044F: \u043D\u0435 \u0432\u044B\u043F\u043E\u043B\u043D\u0435\u043D\u043E",
    "ro.blockedMsg": "\u0420\u0435\u0436\u0438\u043C \u0442\u043E\u043B\u044C\u043A\u043E \u0434\u043B\u044F \u0447\u0442\u0435\u043D\u0438\u044F: \u043E\u043F\u0435\u0440\u0430\u0442\u043E\u0440\u043E\u0432, \u0442\u0440\u0435\u0431\u0443\u044E\u0449\u0438\u0445 \u043F\u043E\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043D\u0438\u044F: {n}.",
    "exp.title": "\u042D\u043A\u0441\u043F\u043E\u0440\u0442",
    "exp.hint": "\u0417\u0430\u043F\u0440\u043E\u0441 \u0432\u044B\u043F\u043E\u043B\u043D\u044F\u0435\u0442\u0441\u044F \u043F\u043E\u0432\u0442\u043E\u0440\u043D\u043E \u0431\u0435\u0437 \u043B\u0438\u043C\u0438\u0442\u0430 \u0441\u0442\u0440\u043E\u043A, \u0430 \u0440\u0435\u0437\u0443\u043B\u044C\u0442\u0430\u0442\u044B \u0437\u0430\u043F\u0438\u0441\u044B\u0432\u0430\u044E\u0442\u0441\u044F \u043F\u0440\u044F\u043C\u043E \u0432 \u0444\u0430\u0439\u043B.",
    "exp.running": "\u042D\u043A\u0441\u043F\u043E\u0440\u0442\u2026",
    "exp.done": "\u042D\u043A\u0441\u043F\u043E\u0440\u0442\u0438\u0440\u043E\u0432\u0430\u043D\u043E \u0441\u0442\u0440\u043E\u043A: {n}",
    "exp.failed": "\u041E\u0448\u0438\u0431\u043A\u0430 \u044D\u043A\u0441\u043F\u043E\u0440\u0442\u0430",
    "err.refused": "\u0412 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0438 \u043E\u0442\u043A\u0430\u0437\u0430\u043D\u043E: \u043F\u043E\u0440\u0442 \u0437\u0430\u043A\u0440\u044B\u0442 \u0438\u043B\u0438 \u0441\u0435\u0440\u0432\u0435\u0440 \u043D\u0435 \u0437\u0430\u043F\u0443\u0449\u0435\u043D.",
    "err.dns": "\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u0440\u0430\u0437\u0440\u0435\u0448\u0438\u0442\u044C \u0438\u043C\u044F \u0445\u043E\u0441\u0442\u0430 (DNS).",
    "err.timeout": "\u0412\u0440\u0435\u043C\u044F \u043E\u0436\u0438\u0434\u0430\u043D\u0438\u044F \u0438\u0441\u0442\u0435\u043A\u043B\u043E: \u0441\u0435\u0440\u0432\u0435\u0440 \u043D\u0435\u0434\u043E\u0441\u0442\u0443\u043F\u0435\u043D.",
    "err.reset": "\u0421\u0435\u0440\u0432\u0435\u0440 \u0437\u0430\u043A\u0440\u044B\u043B \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435.",
    "err.unreach": "\u0421\u0435\u0440\u0432\u0435\u0440 \u043D\u0435\u0434\u043E\u0441\u0442\u0443\u043F\u0435\u043D \u0432 \u0441\u0435\u0442\u0438.",
    "err.sshAuth": "\u041E\u0448\u0438\u0431\u043A\u0430 \u0432\u0445\u043E\u0434\u0430 SSH: \u043D\u0435\u0432\u0435\u0440\u043D\u043E\u0435 \u0438\u043C\u044F \u043F\u043E\u043B\u044C\u0437\u043E\u0432\u0430\u0442\u0435\u043B\u044F, \u043A\u043B\u044E\u0447 \u0438\u043B\u0438 \u043F\u0430\u0440\u043E\u043B\u044C.",
    "err.tls": "\u041E\u0448\u0438\u0431\u043A\u0430 TLS/SSL \u2014 \u043D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u043F\u0440\u043E\u0432\u0435\u0440\u0438\u0442\u044C \u0441\u0435\u0440\u0442\u0438\u0444\u0438\u043A\u0430\u0442 \u0438\u043B\u0438 \u0441\u0435\u0440\u0432\u0435\u0440 \u043D\u0435 \u043F\u043E\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442 TLS. ({msg})",
    "err.hostExit": "\u041F\u0440\u043E\u0446\u0435\u0441\u0441 \u0431\u0430\u0437\u044B \u0434\u0430\u043D\u043D\u044B\u0445 \u043D\u0435\u043E\u0436\u0438\u0434\u0430\u043D\u043D\u043E \u0437\u0430\u0432\u0435\u0440\u0448\u0438\u043B\u0441\u044F.",
    "err.unknown": "\u041D\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043D\u0430\u044F \u043E\u0448\u0438\u0431\u043A\u0430",
    "main.closeAnyway": "\u0412\u0441\u0451 \u0440\u0430\u0432\u043D\u043E \u0437\u0430\u043A\u0440\u044B\u0442\u044C",
    "main.closeRunning": "\u0417\u0430\u043F\u0440\u043E\u0441\u044B \u0435\u0449\u0451 \u0432\u044B\u043F\u043E\u043B\u043D\u044F\u044E\u0442\u0441\u044F. \u0415\u0441\u043B\u0438 \u0437\u0430\u043A\u0440\u044B\u0442\u044C \u044D\u0442\u043E \u043E\u043A\u043D\u043E, \u043E\u043D\u0438 \u0431\u0443\u0434\u0443\u0442 \u043E\u0442\u043C\u0435\u043D\u0435\u043D\u044B.",
    "main.copySuffix": " (\u043A\u043E\u043F\u0438\u044F)",
    "main.errConnNotFound": "\u041F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D\u043E",
    "main.errNoSession": "\u0423 \u044D\u0442\u043E\u0433\u043E \u043E\u043A\u043D\u0430 \u043D\u0435\u0442 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044F",
    "main.errKeyFile": "\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u043F\u0440\u043E\u0447\u0438\u0442\u0430\u0442\u044C \u0444\u0430\u0439\u043B \u043A\u043B\u044E\u0447\u0430 SSH: {path}",
    // Mastertool ortak ayarlar iskeleti (SSH Master ile aynı metinler)
    "set.general": "\u041E\u0431\u0449\u0438\u0435",
    "set.account": "\u0423\u0447\u0451\u0442\u043D\u0430\u044F \u0437\u0430\u043F\u0438\u0441\u044C",
    "set.about": "\u041E \u043F\u0440\u043E\u0433\u0440\u0430\u043C\u043C\u0435",
    "set.startup": "\u0417\u0430\u043F\u0443\u0441\u043A",
    "set.openAtLogin": "\u0417\u0430\u043F\u0443\u0441\u043A\u0430\u0442\u044C \u043F\u0440\u0438 \u0432\u0445\u043E\u0434\u0435 \u0432 Windows",
    "set.openAtLoginHint": "\u0415\u0441\u043B\u0438 \u0432\u043A\u043B\u044E\u0447\u0435\u043D\u043E \u0441\u0432\u043E\u0440\u0430\u0447\u0438\u0432\u0430\u043D\u0438\u0435 \u0432 \u0442\u0440\u0435\u0439, \u043F\u0440\u0438\u043B\u043E\u0436\u0435\u043D\u0438\u0435 \u0437\u0430\u043F\u0443\u0441\u043A\u0430\u0435\u0442\u0441\u044F \u0432 \u0442\u0440\u0435\u0435.",
    "set.window": "\u041E\u043A\u043D\u043E",
    "set.minTray": "\u0421\u0432\u043E\u0440\u0430\u0447\u0438\u0432\u0430\u0442\u044C \u0432 \u0441\u0438\u0441\u0442\u0435\u043C\u043D\u044B\u0439 \u0442\u0440\u0435\u0439",
    "set.minTrayHint": "\u041F\u0440\u0438 \u0441\u0432\u043E\u0440\u0430\u0447\u0438\u0432\u0430\u043D\u0438\u0438 \u043E\u043A\u043D\u043E \u0438\u0441\u0447\u0435\u0437\u0430\u0435\u0442 \u0441 \u043F\u0430\u043D\u0435\u043B\u0438 \u0437\u0430\u0434\u0430\u0447 \u0438 \u043F\u043E\u044F\u0432\u043B\u044F\u0435\u0442\u0441\u044F \u0437\u043D\u0430\u0447\u043A\u043E\u043C SQL Master \u0432 \u0442\u0440\u0435\u0435 \u0440\u044F\u0434\u043E\u043C \u0441 \u0447\u0430\u0441\u0430\u043C\u0438. \u0429\u0451\u043B\u043A\u043D\u0438\u0442\u0435 \u0437\u043D\u0430\u0447\u043E\u043A, \u0447\u0442\u043E\u0431\u044B \u0432\u043E\u0441\u0441\u0442\u0430\u043D\u043E\u0432\u0438\u0442\u044C \u043E\u043A\u043D\u043E; \u043F\u0440\u0430\u0432\u044B\u0439 \u0449\u0435\u043B\u0447\u043E\u043A \u2014 \u0431\u044B\u0441\u0442\u0440\u043E\u0435 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435.",
    "set.closeTray": "\u0421\u043A\u0440\u044B\u0432\u0430\u0442\u044C \u0432 \u0442\u0440\u0435\u0439 \u043F\u0440\u0438 \u0437\u0430\u043A\u0440\u044B\u0442\u0438\u0438",
    "set.closeTrayHint": "\u041A\u043D\u043E\u043F\u043A\u0430 \u0437\u0430\u043A\u0440\u044B\u0442\u0438\u044F (X) \u0441\u043A\u0440\u044B\u0432\u0430\u0435\u0442 \u043F\u0440\u0438\u043B\u043E\u0436\u0435\u043D\u0438\u0435 \u0432 \u0442\u0440\u0435\u0439, \u0430 \u043D\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0430\u0435\u0442 \u0435\u0433\u043E. \u0414\u043B\u044F \u0432\u044B\u0445\u043E\u0434\u0430 \u0438\u0441\u043F\u043E\u043B\u044C\u0437\u0443\u0439\u0442\u0435 \xAB\u0412\u044B\u0445\u043E\u0434\xBB \u0432 \u043C\u0435\u043D\u044E \u0442\u0440\u0435\u044F.",
    "about.version": "\u0412\u0435\u0440\u0441\u0438\u044F {version}",
    "about.family": "\u0427\u0430\u0441\u0442\u044C \u0441\u0435\u043C\u0435\u0439\u0441\u0442\u0432\u0430 Mastertool: SQL Master \xB7 FTP Masters \xB7 SQL Master \xB7 Notepad Master \xB7 Convert Master",
    "about.checkUpdate": "\u041F\u0440\u043E\u0432\u0435\u0440\u0438\u0442\u044C \u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u044F",
    "about.checking": "\u041F\u0440\u043E\u0432\u0435\u0440\u043A\u0430\u2026",
    "about.upToDate": "\u0423\u0441\u0442\u0430\u043D\u043E\u0432\u043B\u0435\u043D\u0430 \u043F\u043E\u0441\u043B\u0435\u0434\u043D\u044F\u044F \u0432\u0435\u0440\u0441\u0438\u044F SQL Master.",
    "about.checkFailed": "\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u043F\u0440\u043E\u0432\u0435\u0440\u0438\u0442\u044C \u043E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u0438\u044F: {msg}",
    "about.licenses": "\u041B\u0438\u0446\u0435\u043D\u0437\u0438\u0438 \u043E\u0442\u043A\u0440\u044B\u0442\u043E\u0433\u043E \u041F\u041E",
    "about.licensesIntro": "SQL Master \u0438\u0441\u043F\u043E\u043B\u044C\u0437\u0443\u0435\u0442 \u0441\u043B\u0435\u0434\u0443\u044E\u0449\u0438\u0435 \u043A\u043E\u043C\u043F\u043E\u043D\u0435\u043D\u0442\u044B \u0441 \u043E\u0442\u043A\u0440\u044B\u0442\u044B\u043C \u0438\u0441\u0445\u043E\u0434\u043D\u044B\u043C \u043A\u043E\u0434\u043E\u043C:",
    "about.chromium": "\u041E\u0442\u043A\u0440\u044B\u0442\u044C \u043B\u0438\u0446\u0435\u043D\u0437\u0438\u0438 Chromium",
    "main.trayShow": "\u041F\u043E\u043A\u0430\u0437\u0430\u0442\u044C SQL Master",
    "main.trayQuick": "\u0411\u044B\u0441\u0442\u0440\u043E\u0435 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435",
    "main.trayNone": "\u041D\u0435\u0442 \u0441\u043E\u0445\u0440\u0430\u043D\u0451\u043D\u043D\u044B\u0445 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0439",
    "main.trayQuit": "\u0412\u044B\u0445\u043E\u0434",
    "set.languageHint": "\u041E\u0442\u043A\u0440\u044B\u0442\u044B\u0435 \u043E\u043A\u043D\u0430 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0439 \u0431\u0443\u0434\u0443\u0442 \u0438\u0441\u043F\u043E\u043B\u044C\u0437\u043E\u0432\u0430\u0442\u044C \u043D\u043E\u0432\u044B\u0439 \u044F\u0437\u044B\u043A \u043F\u043E\u0441\u043B\u0435 \u043F\u043E\u0432\u0442\u043E\u0440\u043D\u043E\u0433\u043E \u043E\u0442\u043A\u0440\u044B\u0442\u0438\u044F.",
    "about.newVersion": "\u0414\u043E\u0441\u0442\u0443\u043F\u043D\u0430 \u043D\u043E\u0432\u0430\u044F \u0432\u0435\u0440\u0441\u0438\u044F: {version}"
  };

  // src/shared/i18n.ts
  var LANGUAGES = {
    tr: { name: "T\xFCrk\xE7e", dir: "ltr" },
    en: { name: "English", dir: "ltr" },
    fr: { name: "Fran\xE7ais", dir: "ltr" },
    de: { name: "Deutsch", dir: "ltr" },
    es: { name: "Espa\xF1ol", dir: "ltr" },
    ar: { name: "\u0627\u0644\u0639\u0631\u0628\u064A\u0629", dir: "rtl" },
    zh: { name: "\u4E2D\u6587", dir: "ltr" },
    ru: { name: "\u0420\u0443\u0441\u0441\u043A\u0438\u0439", dir: "ltr" }
  };
  var STRINGS = { tr, en, fr, de, es, ar, zh, ru };
  function createT(lang) {
    const dict = STRINGS[lang] || STRINGS.en;
    return (key, vars) => {
      let s = (vars?.n === 1 ? dict[`${key}_one`] : void 0) ?? dict[key] ?? STRINGS.en[key] ?? key;
      if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => vars[k] !== void 0 ? String(vars[k]) : m);
      return s;
    };
  }

  // src/renderer/lib/ui.ts
  var LANG = api.lang || "en";
  var t = createT(LANG);
  document.documentElement.lang = LANG;
  document.documentElement.dir = (LANGUAGES[LANG] || { dir: "ltr" }).dir;
  var ICONS = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    folderPlus: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 11v5M9.5 13.5h5"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
    terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    edit: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    move: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    play: '<path d="M7 5v14l11-7z"/>',
    chevronRight: '<path d="m9 6 6 6-6 6"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
    home: '<path d="m3 11 9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
    download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    upload: '<path d="M12 20V9M7 14l5-5 5 5M5 4h14"/>',
    sidebar: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    bolt: '<path d="M13 3 4 14h7l-1 7 9-11h-7z"/>',
    check: '<path d="m5 12 5 5 9-10"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    eyeOff: '<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.8 8.4 2 12 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M16 7l3 3M14 9l2 2"/>',
    history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
    link: '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
    drive: '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5 13 7.5 5h9L19 13M7 16.5h.01"/>',
    monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    open: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    crosshair: '<circle cx="12" cy="12" r="8"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
    palette: '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.8-.8 1.8-1.7 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-.9.8-1.7 1.7-1.7H16a5 5 0 0 0 5-5c0-4-4-7.2-9-7.2z"/><circle cx="7.5" cy="11" r="1.2"/><circle cx="10.5" cy="7" r="1.2"/><circle cx="15" cy="7.5" r="1.2"/>',
    columns: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>',
    rows: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 12h18"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    gauge: '<path d="M4 18a9 9 0 1 1 16 0"/><path d="m12 14 4-5"/><circle cx="12" cy="14" r="1.2"/>',
    swap: '<path d="M7 20V5M3 9l4-4 4 4M17 4v15M13 15l4 4 4-4"/>',
    broom: '<path d="M19 3 11 11M8 12l4 4-2 5-7-7 5-2zM6 17l-2 2"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    cloud: '<path d="M7 18a5 5 0 0 1-.6-9.96A6 6 0 0 1 18 9a4.5 4.5 0 0 1-.5 9z"/>',
    cloudOff: '<path d="M3 3l18 18M8.5 5.4A6 6 0 0 1 18 9a4.5 4.5 0 0 1 2.4 8.3M15 18H7a5 5 0 0 1-1.6-9.7"/>',
    logout: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l-5-5 5-5M5 12h11"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    reconnect: '<path d="M4 4v6h6M20 20v-6h-6"/><path d="M20 10a8 8 0 0 0-14.3-4.3L4 10M4 14a8 8 0 0 0 14.3 4.3L20 14"/>',
    database: '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-13M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/>',
    schema: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><path d="M6.5 10v4a2 2 0 0 0 2 2H14"/>',
    table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9.5h18M3 15h18M9.5 9.5V20"/>',
    view: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9.5h18"/><path d="M7 15s2-2.5 5-2.5 5 2.5 5 2.5-2 2.5-5 2.5S7 15 7 15z"/>',
    matview: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9.5h18M8 13h8M8 16.5h5"/>',
    func: '<path d="M14 4h-1.5A2.5 2.5 0 0 0 10 6.5V20M7 11h7"/><path d="m15 14 5 5M20 14l-5 5"/>',
    proc: '<path d="M5 4h14v16H5z"/><path d="m9 9 3 3-3 3M13 15h3"/>',
    trigger: '<path d="M13 3 4 14h7l-1 7 9-11h-7z"/>',
    sequence: '<path d="M4 7h3M4 12h3M4 17h3M10 7h10M10 12h10M10 17h10"/>',
    type: '<path d="M5 6h14M12 6v13M9 19h6"/>',
    index: '<path d="M4 6h16M4 12h10M4 18h6"/><path d="m17 15 3 3-3 3"/>',
    column: '<rect x="8" y="3" width="8" height="18" rx="1.5"/><path d="M8 8h8M8 13h8"/>',
    constraint: '<path d="M12 3 4 6v6c0 4.5 3.4 8 8 9 4.6-1 8-4.5 8-9V6z"/>',
    code: '<path d="m8 8-5 4 5 4M16 8l5 4-5 4M14 4l-4 16"/>',
    sql: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M8 13h8M8 17h5"/>',
    builder: '<rect x="3" y="3" width="7" height="6" rx="1.5"/><rect x="14" y="15" width="7" height="6" rx="1.5"/><rect x="14" y="3" width="7" height="6" rx="1.5"/><path d="M10 6h4M17.5 9v6"/>',
    sortAsc: '<path d="M7 20V4M3 8l4-4 4 4M14 6h7M14 11h5M14 16h3"/>',
    sortDesc: '<path d="M7 4v16M3 16l4 4 4-4M14 6h3M14 11h5M14 16h7"/>',
    filter: '<path d="M4 5h16l-6 8v6l-4-2v-4z"/>',
    hide: '<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.8 8.4 2 12 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6"/>',
    exportFile: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M12 11v6M9 14l3 3 3-3"/>',
    unlock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/>',
    wrap: '<path d="M4 6h16M4 12h13a3 3 0 0 1 0 6h-4M4 18h6"/><path d="m15 16-2 2 2 2"/>',
    format: '<path d="M4 6h16M8 10h12M8 14h12M4 18h16"/>',
    plusSq: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M12 8v8M8 12h8"/>',
    sigma: '<path d="M18 5H6l6 7-6 7h12"/>',
    file2: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    dots: '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>'
  };
  function icon(name, cls = "") {
    return `<svg class="i ${cls}" viewBox="0 0 24 24">${ICONS[name] || ""}</svg>`;
  }
  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }
  function formatDate(ms) {
    if (!ms) return "";
    return new Date(ms).toLocaleString(LANG, { dateStyle: "short", timeStyle: "short" });
  }
  function h(html) {
    const tpl = document.createElement("template");
    tpl.innerHTML = html.trim();
    return tpl.content.firstElementChild;
  }
  var $ = (s, root = document) => root.querySelector(s);
  var $$ = (s, root = document) => [...root.querySelectorAll(s)];
  var activeCtx = null;
  function closeContextMenu() {
    if (activeCtx) {
      activeCtx.remove();
      activeCtx = null;
    }
  }
  function contextMenu(x, y, items) {
    closeContextMenu();
    const menu = h('<div class="ctx"></div>');
    for (const it of items) {
      if (it === "-") {
        menu.appendChild(h("<hr>"));
        continue;
      }
      if (!it) continue;
      const b = h(`<button class="${it.danger ? "danger" : ""}">${it.icon ? icon(it.icon) : ""}<span>${esc(it.label)}</span>${it.kbd ? `<span class="kbd">${esc(it.kbd)}</span>` : ""}</button>`);
      if (it.disabled) b.disabled = true;
      b.addEventListener("click", () => {
        closeContextMenu();
        it.action();
      });
      menu.appendChild(b);
    }
    document.body.appendChild(menu);
    const r = menu.getBoundingClientRect();
    menu.style.left = Math.max(4, Math.min(x, innerWidth - r.width - 6)) + "px";
    menu.style.top = Math.max(4, Math.min(y, innerHeight - r.height - 6)) + "px";
    activeCtx = menu;
  }
  window.addEventListener("mousedown", (e) => {
    if (activeCtx && !activeCtx.contains(e.target)) closeContextMenu();
  }, true);
  window.addEventListener("blur", closeContextMenu);
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeContextMenu();
  });
  function toastHost() {
    let el = document.querySelector(".toasts");
    if (!el) {
      el = h('<div class="toasts"></div>');
      document.body.appendChild(el);
    }
    return el;
  }
  function toast(title, { type = "", sub = "", timeout = 3500 } = {}) {
    const el = h(`<div class="toast ${type}"><div class="t-body"><div class="t-title">${esc(title)}</div>${sub ? `<div class="t-sub">${esc(sub)}</div>` : ""}</div></div>`);
    toastHost().appendChild(el);
    if (timeout) setTimeout(() => el.remove(), timeout);
    return el;
  }
  function openModal(o) {
    return new Promise((resolve) => {
      const back = h('<div class="modal-backdrop"></div>');
      const modal = h(`<div class="modal">
      <header>${o.iconName ? `<span style="color:var(--accent)">${icon(o.iconName)}</span>` : ""}<h2>${esc(o.title)}</h2></header>
      <div class="body"></div><footer><span class="spacer"></span></footer></div>`);
      if (o.width) modal.style.width = `min(${o.width}px, calc(100vw - 32px))`;
      const bodyEl = $(".body", modal);
      if (typeof o.body === "string") bodyEl.innerHTML = o.body;
      else bodyEl.appendChild(o.body);
      const footer = $("footer", modal);
      const close = (val) => {
        back.remove();
        document.removeEventListener("keydown", onKey);
        resolve(val);
      };
      for (const b of o.buttons ?? []) {
        const btn = h(`<button class="btn ${b.cls || ""}">${b.icon ? icon(b.icon) : ""}${esc(b.label)}</button>`);
        btn.addEventListener("click", async () => {
          if (b.onClick) {
            const r = await b.onClick(modal, btn);
            if (r === false) return;
            close(r === void 0 ? b.value ?? null : r);
          } else close(b.value ?? null);
        });
        if (b.left) footer.insertBefore(btn, $(".spacer", footer));
        else footer.appendChild(btn);
      }
      const onKey = (e) => {
        if (e.key === "Escape") close(null);
        if (e.key === "Enter" && e.target.tagName !== "TEXTAREA" && !e.target.closest(".cm-editor")) {
          const primary = [...footer.querySelectorAll(".btn.primary")].pop();
          if (primary) {
            e.preventDefault();
            primary.click();
          }
        }
      };
      document.addEventListener("keydown", onKey);
      back.addEventListener("mousedown", (e) => {
        if (e.target === back) close(null);
      });
      back.appendChild(modal);
      document.body.appendChild(back);
      o.onMount?.(modal, close);
      const first = modal.querySelector("input:not([type=checkbox]):not([disabled]),textarea,select");
      if (first) setTimeout(() => first.focus(), 30);
    });
  }
  function prompt(title, { label = "", value = "", placeholder = "", okText = t("common.ok"), iconName = "edit", type = "text" } = {}) {
    return openModal({
      title,
      iconName,
      body: `<div class="field"><label>${esc(label)}</label><input class="input" id="pv" type="${type}" value="${esc(value)}" placeholder="${esc(placeholder)}"></div>`,
      buttons: [
        { label: t("common.cancel"), value: null },
        { label: okText, cls: "primary", onClick: (m) => {
          const i = $("#pv", m);
          const v = type === "password" ? i.value : i.value.trim();
          if (!v) {
            i.classList.add("invalid");
            return false;
          }
          return v;
        } }
      ],
      onMount: (m) => {
        const i = $("#pv", m);
        setTimeout(() => i.select(), 40);
      }
    });
  }
  function confirmBox(title, message, { okText = t("common.delete"), danger = true } = {}) {
    return openModal({
      title,
      iconName: danger ? "trash" : "check",
      body: `<div style="color:var(--text-2);line-height:1.5">${message}</div>`,
      buttons: [
        { label: t("common.giveUp"), value: false },
        { label: okText, cls: danger ? "primary danger-primary" : "primary", value: true }
      ]
    });
  }

  // src/renderer/lib/settings.ts
  var acct = { loggedIn: false, user: null, email: "", syncEnabled: false, state: "idle", lastSyncAt: null, error: null };
  var listeners = [];
  function syncText(st) {
    if (st.devMode) return t("sync.devMode");
    if (!st.syncEnabled || st.state === "off") return t("sync.off");
    if (st.state === "syncing") return t("sync.syncing");
    if (st.state === "offline") return t("sync.offline");
    if (st.state === "error") {
      if (st.error === "decrypt_failed") return t("sync.errDecrypt");
      if (st.error === "too_large") return t("sync.errTooLarge");
      return t("sync.error", { msg: st.errorMessage || st.error || "" });
    }
    return st.lastSyncAt ? t("acct.lastSync", { time: formatDate(st.lastSyncAt) }) : t("acct.never");
  }
  function onAcct(fn) {
    listeners.push(fn);
    fn(acct);
  }
  function setAcct(st) {
    acct = st;
    const live = document.querySelector("#acct-status");
    if (live) live.textContent = syncText(acct);
    listeners.forEach((fn) => fn(acct));
  }
  api.onAccountStatus(setAcct);
  void api.accountState().then(setAcct);
  async function logout() {
    const ok = await confirmBox(t("acct.logout"), esc(t("acct.logoutMsg")), { okText: t("acct.logout") });
    if (ok) void api.logout();
  }
  function themeButton(btn) {
    const light = matchMedia("(prefers-color-scheme: light)");
    const paint = () => {
      btn.innerHTML = icon(light.matches ? "moon" : "sun");
      btn.title = light.matches ? t("set.toDark") : t("set.toLight");
    };
    btn.onclick = () => api.setSettings({ appTheme: light.matches ? "dark" : "light" });
    light.addEventListener("change", paint);
    paint();
  }
  var OSS = [
    ["Electron", "MIT"],
    ["Chromium", "BSD-3-Clause"],
    ["Node.js", "MIT"],
    ["CodeMirror", "MIT"],
    ["node-postgres (pg, pg-cursor)", "MIT"],
    ["mssql / tedious", "MIT"],
    ["mysql2", "MIT"],
    ["DuckDB (@duckdb/node-api)", "MIT"],
    ["SQLite", "Public Domain"],
    ["ssh2", "MIT"]
  ];
  async function openSettings(s, startTab = "general") {
    let appTheme = s.appTheme || "system";
    const originalTheme = appTheme;
    const langOptions = Object.entries(LANGUAGES).map(([code, l]) => `<option value="${code}" ${code === LANG ? "selected" : ""}>${esc(l.name)}</option>`).join("");
    const tabs = [["general", "gear", t("set.general")], ["account", "user", t("set.account")], ["query", "sql", t("set.query")], ["about", "info", t("set.about")]];
    const body = h(`<div class="set-wrap">
    <nav class="set-nav">${tabs.map(([k, ic, l]) => `<button type="button" data-tab="${k}">${icon(ic)}<span>${esc(l)}</span></button>`).join("")}</nav>
    <div class="set-pages">
      <section data-page="general">
        <div class="field"><label>${esc(t("set.language"))}</label><select class="input" id="s-lang">${langOptions}</select>
          <span class="set-hint">${esc(t("set.languageHint"))}</span></div>
        <div class="field"><label>${esc(t("set.theme"))}</label>
          <div class="seg" id="s-theme">
            <button type="button" data-v="dark">${icon("moon")}${esc(t("set.themeDark"))}</button>
            <button type="button" data-v="light">${icon("sun")}${esc(t("set.themeLight"))}</button>
            <button type="button" data-v="system">${icon("monitor")}${esc(t("set.themeSystem"))}</button>
          </div></div>
        <div class="section-title">${esc(t("set.startup"))}</div>
        <label class="check"><input type="checkbox" id="s-login" ${s.openAtLogin ? "checked" : ""}><span>${esc(t("set.openAtLogin"))}<small>${esc(t("set.openAtLoginHint"))}</small></span></label>
        <label class="check"><input type="checkbox" id="s-mintray" ${s.minimizeToTray ? "checked" : ""}><span>${esc(t("set.minTray"))}<small>${esc(t("set.minTrayHint"))}</small></span></label>
        <label class="check"><input type="checkbox" id="s-closetray" ${s.closeToTray ? "checked" : ""}><span>${esc(t("set.closeTray"))}<small>${esc(t("set.closeTrayHint"))}</small></span></label>
      </section>

      <section data-page="account" class="hidden">
        <div class="acct-box">
          <div class="acct-who">${icon("user")}<span>${esc(t("acct.signedInAs", { email: acct.user?.email || acct.email || "" }))}</span></div>
          <label class="check"><input type="checkbox" id="s-sync" ${acct.syncEnabled ? "checked" : ""} ${acct.devMode ? "disabled" : ""}>
            <span>${esc(t("acct.syncToggle"))}<small>${esc(t("acct.syncHint"))}</small></span></label>
          <div class="acct-status">${icon("cloud")}<span id="acct-status">${esc(syncText(acct))}</span></div>
          <div class="acct-actions">
            <button class="btn sm" type="button" id="s-syncnow">${icon("refresh")}${esc(t("acct.syncNow"))}</button>
            <button class="btn sm" type="button" id="s-delremote">${icon("trash")}${esc(t("acct.deleteRemote"))}</button>
          </div>
          <div class="acct-actions">
            <button class="btn sm" type="button" id="s-web">${icon("open")}${esc(t("acct.myAccount"))}</button>
            <span style="flex:1"></span>
            <button class="btn sm danger" type="button" id="s-logout">${icon("logout")}${esc(t("acct.logout"))}</button>
          </div>
        </div>
      </section>

      <section data-page="query" class="hidden">
        <div class="row c-1-1">
          <div class="field"><label>${esc(t("set.rowLimit"))}</label><input class="input" id="s-limit" type="number" min="100" max="1000000" value="${esc(s.rowLimit)}"></div>
          <div class="field"><label>${esc(t("set.previewRows"))}</label><input class="input" id="s-preview" type="number" min="10" max="100000" value="${esc(s.previewRows)}"></div>
        </div>
        <div class="row c-1-1">
          <div class="field"><label>${esc(t("set.fontSize"))}</label><input class="input" id="s-font" type="number" min="9" max="24" value="${esc(s.editorFontSize)}"></div>
          <div></div>
        </div>
      </section>

      <section data-page="about" class="hidden">
        <div class="about-head"><img src="../../assets/icon.png" alt="">
          <div><div class="about-name">SQL Master</div><div class="about-ver">${esc(t("about.version", { version: api.version || "" }))}</div></div></div>
        <div class="set-hint">${esc(t("about.family"))}</div>
        <div class="acct-actions" style="align-items:center">
          <button class="btn sm" type="button" id="s-update">${icon("refresh")}${esc(t("about.checkUpdate"))}</button>
          <span class="about-update" id="s-update-res"></span>
        </div>
        <div class="section-title">${esc(t("about.licenses"))}</div>
        <div class="set-hint">${esc(t("about.licensesIntro"))}</div>
        <ul class="oss">${OSS.map(([n, l]) => `<li><span>${esc(n)}</span><span>${esc(l)}</span></li>`).join("")}</ul>
        <div class="acct-actions" style="align-items:center">
          <button class="btn sm" type="button" id="s-chromium">${icon("file2")}${esc(t("about.chromium"))}</button>
          <span class="set-hint" id="s-versions"></span>
        </div>
      </section>
    </div>
  </div>`);
    const q = (sel) => $(sel, body);
    const showTab = (k) => {
      $$(".set-nav button", body).forEach((b) => b.classList.toggle("on", b.dataset.tab === k));
      $$(".set-pages section", body).forEach((p) => p.classList.toggle("hidden", p.dataset.page !== k));
    };
    $$(".set-nav button", body).forEach((b) => b.onclick = () => showTab(b.dataset.tab));
    showTab(startTab);
    q("#s-sync").onchange = async (e) => {
      const el = e.target;
      const r = await api.setSyncEnabled(el.checked);
      if (!r.ok) {
        el.checked = !el.checked;
        toast(t("sync.error", { msg: r.code || "" }), { type: "err" });
      }
    };
    q("#s-syncnow").onclick = () => void api.syncNow();
    q("#s-web").onclick = () => void api.openWeb("account");
    q("#s-delremote").onclick = async () => {
      if (!await confirmBox(t("acct.deleteRemote"), esc(t("acct.deleteRemoteMsg")))) return;
      const r = await api.deleteRemoteLibrary();
      if (r.ok) {
        q("#s-sync").checked = false;
        toast(t("acct.deleteRemoteDone"), { type: "ok" });
      } else toast(t("sync.error", { msg: r.code || "" }), { type: "err" });
    };
    q("#s-logout").onclick = logout;
    void api.about().then((a) => q("#s-versions").textContent = `Electron ${a.electron} \xB7 Chromium ${a.chrome}`);
    q("#s-chromium").onclick = () => void api.openLicenses();
    q("#s-update").onclick = async () => {
      const res2 = q("#s-update-res");
      res2.className = "about-update";
      res2.textContent = t("about.checking");
      const r = await api.checkUpdate();
      if (!r.ok) {
        res2.className = "about-update err";
        res2.textContent = t("about.checkFailed", { msg: r.message || "" });
      } else if (r.newer && r.version) {
        res2.className = "about-update new";
        res2.textContent = t("about.newVersion", { version: r.version });
      } else {
        res2.className = "about-update ok";
        res2.textContent = t("about.upToDate");
      }
    };
    const setTheme = (v) => {
      appTheme = v;
      $$("#s-theme button", body).forEach((b) => b.classList.toggle("on", b.dataset.v === v));
      void api.setSettings({ appTheme: v });
    };
    $$("#s-theme button", body).forEach((b) => {
      b.onclick = () => setTheme(b.dataset.v);
      b.classList.toggle("on", b.dataset.v === appTheme);
    });
    const clamp = (v, min, max, def) => {
      const n = Number(v);
      return Number.isFinite(n) ? Math.min(max, Math.max(min, Math.round(n))) : def;
    };
    const res = await openModal({
      title: t("set.title"),
      iconName: "gear",
      width: 760,
      body,
      buttons: [
        { label: t("common.cancel"), value: null },
        {
          label: t("common.save"),
          cls: "primary",
          onClick: () => ({
            appTheme,
            language: q("#s-lang").value,
            openAtLogin: q("#s-login").checked,
            minimizeToTray: q("#s-mintray").checked,
            closeToTray: q("#s-closetray").checked,
            rowLimit: clamp(q("#s-limit").value, 100, 1e6, 1e4),
            previewRows: clamp(q("#s-preview").value, 10, 1e5, 100),
            editorFontSize: clamp(q("#s-font").value, 9, 24, 13)
          })
        }
      ]
    });
    if (!res) {
      if (appTheme !== originalTheme) void api.setSettings({ appTheme: originalTheme });
      return null;
    }
    const langChanged = res.language !== LANG;
    if (!langChanged) delete res.language;
    await api.setSettings(res);
    if (!langChanged) toast(t("set.saved"), { type: "ok" });
    return res;
  }

  // src/renderer/lib/mastertool.ts
  function mastertoolButton() {
    const a = h(`<a class="mtk-mt" href="https://mastertool.download/" title="Mastertool \u2014 SSH Master \xB7 FTP Masters \xB7 SQL Master">
    <span class="mtk-mt-in">
      <svg class="mtk-mt-ic" viewBox="0 0 32 32" aria-hidden="true">
        <defs><linearGradient id="mtkg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#6366f1"/></linearGradient></defs>
        <rect x="2" y="2" width="28" height="28" rx="8" fill="url(#mtkg)"/>
        <path d="M8.5 22.5V10l7.5 7.5 7.5-7.5v12.5" fill="none" stroke="#06101c" stroke-opacity=".28" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        <path class="mtk-mt-m" d="M8.5 22.5V10l7.5 7.5 7.5-7.5v12.5" fill="none" stroke="#06101c" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" pathLength="100"/>
      </svg>
      <span class="mtk-mt-tx">Mastertool</span>
      <svg class="mtk-mt-go" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7M9 7h8v8" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </span>
  </a>`);
    a.addEventListener("click", (e) => {
      e.preventDefault();
      void api.openWeb("mastertool");
    });
    return a;
  }

  // src/renderer/main/app.ts
  var COLORS = ["#22d3ee", "#3b82f6", "#6366f1", "#a855f7", "#ec4899", "#f97316", "#fbbf24", "#34d399", "#94a3b8"];
  var DND = "application/x-sqlm";
  var data = { folders: [], connections: [], settings: {} };
  var currentFolder = null;
  var query = "";
  var selectedId = null;
  $(".search-ico").innerHTML = icon("search");
  $("#btnSettings").innerHTML = icon("gear");
  $("#btnSettings").title = t("app.settings");
  $("#btnNewFolder").innerHTML = icon("folderPlus") + esc(t("common.newFolder"));
  $("#btnNewConn").innerHTML = icon("plus") + esc(t("app.newConn"));
  $("#search").placeholder = t("app.searchPh");
  themeButton($("#btnTheme"));
  $(".actions").appendChild(mastertoolButton());
  $("#btnSettings").onclick = () => openSettings(data.settings);
  $("#content").addEventListener("mousedown", (e) => {
    if (!e.target.closest(".card, .new-card")) {
      selectedId = null;
      updateSelectionUI();
    }
  });
  $("#btnNewFolder").onclick = () => newFolder();
  $("#btnNewConn").onclick = () => editConnection(null);
  $("#search").addEventListener("input", (e) => {
    query = e.target.value.trim().toLowerCase();
    render();
  });
  document.addEventListener("keydown", (e) => {
    if (document.querySelector(".modal-backdrop")) return;
    const inInput = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName ?? "");
    if (e.ctrlKey && e.key.toLowerCase() === "f") {
      e.preventDefault();
      $("#search").focus();
      $("#search").select();
    }
    if (e.ctrlKey && e.key.toLowerCase() === "n") {
      e.preventDefault();
      void editConnection(null);
    }
    if (e.key === "Escape" && document.activeElement === $("#search")) {
      $("#search").value = "";
      query = "";
      render();
      $("#search").blur();
    }
    if (e.key === "Backspace" && !inInput && currentFolder) goFolder(folderById(currentFolder)?.parentId ?? null);
    const sel = data.connections.find((c) => c.id === selectedId);
    if (sel && !inInput) {
      if (e.key === "Enter") void api.openConnection(sel.id);
      if (e.key === "Delete") void deleteConnection(sel);
      if (e.key === "F2") void editConnection(sel);
    }
  });
  api.onStoreChanged((d) => {
    data = d;
    render();
  });
  var lastErrorShown = null;
  onAcct((st) => {
    const b = $("#btnAccount");
    const name = st.user?.name || st.user?.email || st.email || "?";
    $(".ac-avatar", b).textContent = name.trim().slice(0, 1).toUpperCase();
    const s = !st.syncEnabled || st.state === "off" ? "off" : st.state || "idle";
    b.className = `account-chip s-${s}`;
    $(".ac-sync", b).innerHTML = s === "syncing" ? '<span class="spin"></span>' : icon(["off", "offline", "error"].includes(s) ? "cloudOff" : "cloud");
    b.title = `${st.user?.email || st.email || ""}
${syncText(st)}`;
    if (st.state === "error" && st.error !== lastErrorShown) {
      lastErrorShown = st.error;
      toast(syncText(st), { type: "err", timeout: 9e3 });
    }
    if (st.state === "ok") lastErrorShown = null;
  });
  $("#btnAccount").onclick = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    contextMenu(r.right - 260, r.bottom + 6, [
      { label: acct.user?.email || acct.email || "", icon: "user", disabled: true, action: () => {
      } },
      { label: syncText(acct), icon: acct.syncEnabled ? "cloud" : "cloudOff", disabled: true, action: () => {
      } },
      "-",
      { label: t("acct.syncNow"), icon: "refresh", disabled: !acct.syncEnabled, action: () => void api.syncNow() },
      { label: t("acct.myAccount"), icon: "open", action: () => void api.openWeb("account") },
      { label: t("app.settings"), icon: "gear", action: () => void openSettings(data.settings) },
      "-",
      { label: t("acct.logout"), icon: "logout", danger: true, action: logout }
    ]);
  };
  api.onUpdateAvailable(({ version }) => {
    const bar = $("#updateBar");
    bar.innerHTML = `${icon("download")}<span>${esc(t("update.available", { version }))} \u2014 ${esc(t("update.hint"))}</span>
    <button class="btn sm primary" data-a="open">${esc(t("update.open"))}</button>
    <button class="icon-btn" data-a="close" title="${esc(t("common.cancel"))}">${icon("x")}</button>`;
    bar.classList.remove("hidden");
    $('[data-a="open"]', bar).onclick = () => void api.openWeb("account");
    $('[data-a="close"]', bar).onclick = () => bar.classList.add("hidden");
  });
  api.onLibraryBackup((file) => toast(t("acct.backupNotice"), { sub: file, timeout: 12e3 }));
  void api.getStore().then((d) => {
    data = d;
    render();
  });
  var folderById = (id) => data.folders.find((f) => f.id === id);
  var sortByName = (a, b) => a.name.localeCompare(b.name, LANG, { sensitivity: "base" });
  function folderPath(id) {
    const out = [];
    let f = folderById(id);
    while (f) {
      out.unshift(f);
      f = folderById(f.parentId);
    }
    return out;
  }
  function countIn(folderId) {
    let n = data.connections.filter((c) => (c.folderId || null) === folderId).length;
    for (const sub of data.folders.filter((f) => (f.parentId || null) === folderId)) n += countIn(sub.id);
    return n;
  }
  function goFolder(id) {
    currentFolder = id && folderById(id) ? id : null;
    selectedId = null;
    render();
  }
  function updateSelectionUI() {
    $$(".conn-card").forEach((x) => x.classList.toggle("selected", x.dataset.id === selectedId));
  }
  var target = (c) => {
    const meta = providerMeta(c.provider);
    if (meta.kind === "file") return c.filePath || t("form.inMemory");
    const port = c.port && c.port !== meta.defaultPort ? `:${c.port}` : "";
    return `${c.user ? c.user + "@" : ""}${c.host || "localhost"}${port}${c.database ? "/" + c.database : ""}`;
  };
  function render() {
    if (currentFolder && !folderById(currentFolder)) currentFolder = null;
    renderCrumbs();
    renderGrid();
    updateSelectionUI();
    const nc = data.connections.length;
    $("#stats").textContent = nc ? t("app.stats", { c: nc, f: data.folders.length }) : t("app.welcome");
  }
  function renderCrumbs() {
    const el = $("#crumbs");
    el.innerHTML = "";
    if (query) {
      el.appendChild(h(`<span class="crumb current">${icon("search")} ${esc(t("app.results", { q: query }))}</span>`));
      return;
    }
    const parts = [{ id: null, name: t("app.all") }, ...folderPath(currentFolder)];
    parts.forEach((p, i) => {
      const last = i === parts.length - 1;
      const c = h(`<span class="crumb ${last ? "current" : ""}">${i === 0 ? icon("home") : icon("folder")}${esc(p.name)}</span>`);
      if (!last) {
        c.onclick = () => goFolder(p.id);
        makeDropTarget(c, p.id);
      }
      el.appendChild(c);
      if (!last) el.appendChild(h(`<span class="crumb-sep">${icon("chevronRight")}</span>`));
    });
  }
  function newCard(big = false) {
    const n = big ? h(`<div class="welcome"><div class="new-card"><div class="plus">${icon("plus")}</div><div class="lbl">${esc(t("app.addConn"))}</div><div class="hint">${t("app.welcomeHint")}</div></div></div>`) : h(`<div class="new-card"><div class="plus">${icon("plus")}</div><div class="lbl">${esc(t("app.addConn"))}</div></div>`);
    (n.classList.contains("new-card") ? n : $(".new-card", n)).onclick = () => void editConnection(null);
    return n;
  }
  function renderGrid() {
    const grid = $("#grid");
    grid.innerHTML = "";
    if (!data.connections.length && !data.folders.length) {
      grid.appendChild(newCard(true));
      return;
    }
    let folders;
    let conns;
    if (query) {
      folders = data.folders.filter((f) => f.name.toLowerCase().includes(query));
      conns = data.connections.filter((c) => [c.name, c.host, c.user, c.database, c.filePath, String(c.port ?? ""), c.comments, providerMeta(c.provider).name].some((v) => String(v || "").toLowerCase().includes(query)));
    } else {
      folders = data.folders.filter((f) => (f.parentId || null) === currentFolder);
      conns = data.connections.filter((c) => (c.folderId || null) === currentFolder);
    }
    folders.sort(sortByName);
    conns.sort(sortByName);
    if (folders.length) {
      grid.appendChild(h(`<div class="section-title">${esc(t("app.folders"))}</div>`));
      for (const f of folders) grid.appendChild(folderCard(f));
    }
    grid.appendChild(h(`<div class="section-title">${esc(t("app.connections"))}${conns.length ? `<span class="hint">${esc(t("app.dblHint"))}</span>` : ""}</div>`));
    if (!query) grid.appendChild(newCard());
    for (const c of conns) grid.appendChild(connCard(c));
    if (query && !conns.length && !folders.length) grid.appendChild(h(`<div class="empty-note" style="grid-column:1/-1">${esc(t("app.noMatch"))}</div>`));
  }
  function folderCard(f) {
    const n = countIn(f.id);
    const el = h(`<div class="card folder-card" draggable="true">
    <div class="avatar">${icon("folder")}</div>
    <div style="min-width:0"><div class="card-title">${esc(f.name)}</div><div class="card-sub">${esc(t("app.folderCount", { n }))}</div></div></div>`);
    el.addEventListener("dblclick", () => {
      $("#search").value = "";
      query = "";
      goFolder(f.id);
    });
    el.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      contextMenu(e.clientX, e.clientY, [
        { label: t("common.open"), icon: "open", action: () => goFolder(f.id) },
        { label: t("app.newConnHere"), icon: "plus", action: () => void editConnection(null, f.id) },
        { label: t("app.newSubfolder"), icon: "folderPlus", action: () => void newFolder(f.id) },
        "-",
        { label: t("common.rename"), icon: "edit", action: () => void renameFolder(f) },
        { label: t("common.moveEllipsis"), icon: "move", action: () => void moveDialog("folder", f) },
        "-",
        { label: t("common.delete"), icon: "trash", danger: true, action: () => void deleteFolder(f) }
      ]);
    });
    el.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData(DND, JSON.stringify({ type: "folder", id: f.id }));
      el.classList.add("dragging");
    });
    el.addEventListener("dragend", () => el.classList.remove("dragging"));
    makeDropTarget(el, f.id);
    return el;
  }
  function connCard(c) {
    const meta = providerMeta(c.provider);
    const where = query && c.folderId ? folderPath(c.folderId).map((f) => f.name).join(" / ") : "";
    const el = h(`<div class="card conn-card ${selectedId === c.id ? "selected" : ""}" data-id="${esc(c.id)}" draggable="true" style="--c:${esc(c.color || meta.color)}">
    <div class="card-head">
      <div class="avatar">${icon("database")}</div>
      <div style="min-width:0;flex:1">
        <div class="card-title">${esc(c.name)}</div>
        <div class="card-sub">${esc(target(c))}</div>
      </div>
    </div>
    <div class="quick">
      <button class="icon-btn" data-a="edit" title="${esc(t("common.edit"))}">${icon("edit")}</button>
      <button class="icon-btn connect" data-a="open" title="${esc(t("common.connect"))}">${icon("play")}</button>
    </div>
    <div class="card-foot">
      <span class="tag prov" style="--c:${meta.color}">${icon("database")}${esc(meta.short)}</span>
      ${c.readOnly ? `<span class="tag ro" title="${esc(t("form.readOnly"))}">${icon("lock")}${esc(t("app.readOnlyTag"))}</span>` : `<span class="tag rw">${icon("unlock")}${esc(t("app.writeTag"))}</span>`}
      ${c.ssh.enabled ? `<span class="tag">${icon("key")}SSH</span>` : ""}
      ${where ? `<span class="tag">${icon("folder")}${esc(where)}</span>` : ""}
    </div></div>`);
    if (c.comments) el.title = c.comments;
    el.addEventListener("click", (e) => {
      const a = e.target.closest("[data-a]")?.dataset.a;
      if (a === "open") return void api.openConnection(c.id);
      if (a === "edit") return void editConnection(c);
      selectedId = c.id;
      updateSelectionUI();
    });
    el.addEventListener("dblclick", (e) => {
      if (e.target.closest("[data-a]")) return;
      void api.openConnection(c.id);
    });
    el.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      selectedId = c.id;
      updateSelectionUI();
      contextMenu(e.clientX, e.clientY, [
        { label: t("common.connect"), icon: "play", kbd: "Enter", action: () => void api.openConnection(c.id) },
        "-",
        { label: t("common.edit"), icon: "edit", kbd: "F2", action: () => void editConnection(c) },
        { label: t("app.duplicate"), icon: "copy", action: () => void api.duplicateConnection(c.id) },
        { label: t("app.moveToFolder"), icon: "move", action: () => void moveDialog("conn", c) },
        "-",
        { label: t("common.delete"), icon: "trash", danger: true, kbd: "Del", action: () => void deleteConnection(c) }
      ]);
    });
    el.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData(DND, JSON.stringify({ type: "conn", id: c.id }));
      el.classList.add("dragging");
    });
    el.addEventListener("dragend", () => el.classList.remove("dragging"));
    return el;
  }
  function makeDropTarget(el, folderId) {
    let depth = 0;
    el.addEventListener("dragenter", (e) => {
      if (!e.dataTransfer.types.includes(DND)) return;
      depth++;
      el.classList.add("drop");
    });
    el.addEventListener("dragleave", () => {
      if (--depth <= 0) {
        depth = 0;
        el.classList.remove("drop");
      }
    });
    el.addEventListener("dragover", (e) => {
      if (e.dataTransfer.types.includes(DND)) {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
      }
    });
    el.addEventListener("drop", async (e) => {
      e.preventDefault();
      depth = 0;
      el.classList.remove("drop");
      const d = JSON.parse(e.dataTransfer.getData(DND) || "{}");
      if (d.type === "conn" && d.id) {
        await api.moveConnection(d.id, folderId);
        toast(t("app.connMoved"), { type: "ok", sub: folderId ? folderById(folderId)?.name : t("app.all") });
      } else if (d.type === "folder" && d.id && d.id !== folderId) {
        if (!await api.moveFolder(d.id, folderId)) toast(t("app.folderIntoSelf"), { type: "err" });
      }
    });
  }
  async function newFolder(parentId = currentFolder) {
    const name = await prompt(t("common.newFolder"), { label: t("common.folderName"), placeholder: t("app.folderPh"), okText: t("common.create"), iconName: "folderPlus" });
    if (name) await api.saveFolder({ name, parentId });
  }
  async function renameFolder(f) {
    const name = await prompt(t("app.renameFolder"), { label: t("common.folderName"), value: f.name, okText: t("common.save") });
    if (name) await api.saveFolder({ id: f.id, name });
  }
  async function deleteFolder(f) {
    const n = countIn(f.id);
    if (await confirmBox(t("app.deleteFolder"), t("app.deleteFolderMsg", { name: esc(f.name) }) + (n ? t("app.deleteFolderConns", { n }) : ""))) await api.deleteFolder(f.id);
  }
  function folderOptions(selected, excludeId) {
    const out = [`<option value="">${esc(t("app.rootFolder"))}</option>`];
    const walk = (parentId, depth) => {
      for (const f of data.folders.filter((x) => (x.parentId || null) === parentId).sort(sortByName)) {
        if (f.id === excludeId) continue;
        out.push(`<option value="${f.id}" ${f.id === selected ? "selected" : ""}>${"&nbsp;&nbsp;&nbsp;".repeat(depth)}${esc(f.name)}</option>`);
        walk(f.id, depth + 1);
      }
    };
    walk(null, 1);
    return out.join("");
  }
  async function moveDialog(type, item) {
    const current = type === "conn" ? item.folderId : item.parentId;
    const res = await openModal({
      title: t("app.moveTitle", { name: item.name }),
      iconName: "move",
      body: `<div class="field"><label>${esc(t("app.targetFolder"))}</label><select class="input" id="mv">${folderOptions(current, type === "folder" ? item.id : void 0)}</select></div>`,
      buttons: [
        { label: t("common.cancel"), value: null },
        { label: t("common.move"), cls: "primary", onClick: (m) => ({ v: $("#mv", m).value || null }) }
      ]
    });
    if (!res) return;
    if (type === "conn") await api.moveConnection(item.id, res.v);
    else if (!await api.moveFolder(item.id, res.v)) toast(t("app.folderIntoSelf"), { type: "err" });
  }
  async function deleteConnection(c) {
    if (await confirmBox(t("app.deleteConn"), t("app.deleteConnMsg", { name: esc(c.name), target: esc(target(c)) }))) {
      await api.deleteConnection(c.id);
      if (selectedId === c.id) selectedId = null;
    }
  }
  var opts = (list, v) => list.map(([k, l]) => `<option value="${k}" ${k === v ? "selected" : ""}>${esc(l)}</option>`).join("");
  async function editConnection(conn, folderId) {
    const isNew = !conn;
    const c = conn ?? {
      id: "",
      name: "",
      provider: "postgres",
      host: "localhost",
      port: null,
      database: "",
      user: "",
      filePath: "",
      sslMode: "prefer",
      readOnly: true,
      savePassword: true,
      color: COLORS[data.connections.length % COLORS.length],
      folderId: folderId ?? currentFolder,
      comments: "",
      ssh: { enabled: false, host: "", port: 22, user: "", auth: "key", keyPath: "", hostKey: null },
      createdAt: 0,
      hasPassword: false,
      hasSshPassword: false,
      hasSshPassphrase: false
    };
    let provider = c.provider;
    let color = c.color;
    let sshAuth = c.ssh.auth;
    const body = h(`<div class="site-form">
    <div class="tabs" id="f-tabs">
      <button data-tab="general" class="on">${icon("database")}${esc(t("form.tabGeneral"))}</button>
      <button data-tab="security">${icon("lock")}${esc(t("form.tabSecurity"))}</button>
      <button data-tab="ssh" class="server-only">${icon("key")}${esc(t("form.tabSsh"))}</button>
    </div>

    <section class="tab-panel" data-panel="general">
      <div class="prov-grid" id="f-prov">${PROVIDERS.map((p) => `<button type="button" class="prov-btn" data-v="${p.id}" style="--pc:${p.color}">${icon(p.kind === "file" ? "file2" : "database")}<span>${esc(p.short)}</span></button>`).join("")}</div>
      <div class="field"><label>${esc(t("form.name"))}</label><input class="input" id="f-name" placeholder="${esc(t("form.namePh"))}" value="${esc(c.name)}"></div>
      <div class="server-only" style="display:grid;gap:14px">
        <div class="row c-3-1">
          <div class="field"><label>${esc(t("form.host"))}</label><input class="input" id="f-host" placeholder="localhost" value="${esc(c.host)}" spellcheck="false"></div>
          <div class="field"><label>${esc(t("form.port"))}</label><input class="input" id="f-port" type="number" min="1" max="65535" value="${esc(c.port ?? "")}"></div>
        </div>
        <div class="row c-1-1">
          <div class="field"><label>${esc(t("form.user"))}</label><input class="input" id="f-user" value="${esc(c.user)}" spellcheck="false" autocomplete="off"></div>
          <div class="field"><label>${esc(t("form.password"))}</label>
            <div class="pw-wrap"><input class="input" id="f-pass" type="password" placeholder="${c.hasPassword ? esc(t("form.pwSaved")) : ""}" autocomplete="new-password">
            <button class="icon-btn" id="f-eye" type="button" title="${esc(t("common.show"))}">${icon("eye")}</button></div></div>
        </div>
        <div class="field"><label>${esc(t("form.database"))}</label><input class="input" id="f-db" value="${esc(c.database)}" placeholder="${esc(t("form.databasePh"))}" spellcheck="false"></div>
      </div>
      <div class="file-only field"><label>${esc(t("form.file"))}</label>
        <div class="key-wrap"><input class="input" id="f-file" value="${esc(c.filePath)}" placeholder="${esc(t("form.filePh"))}" spellcheck="false"><button class="btn" id="f-filepick" type="button">${esc(t("common.choose"))}</button></div>
        <small class="hint" id="f-file-hint"></small></div>
      <div class="row c-1-1">
        <div class="field"><label>${esc(t("form.folder"))}</label><select class="input" id="f-folder">${folderOptions(c.folderId)}</select></div>
        <div class="field"><label>${esc(t("form.color"))}</label><div class="colors" id="f-colors" style="height:36px;align-items:center"></div></div>
      </div>
      <div class="field"><label>${esc(t("form.comments"))}</label><textarea class="input plain" id="f-notes" rows="2">${esc(c.comments)}</textarea></div>
    </section>

    <section class="tab-panel hidden" data-panel="security">
      <label class="check"><input type="checkbox" id="f-ro" ${c.readOnly ? "checked" : ""}>
        <span>${esc(t("form.readOnly"))}<small>${esc(t("form.readOnlyHint"))}</small></span></label>
      <div class="server-only" style="display:grid;gap:14px">
        <label class="check"><input type="checkbox" id="f-savepw" ${c.savePassword ? "checked" : ""}>
          <span>${esc(t("form.savePassword"))}<small>${esc(t("form.savePasswordHint"))}</small></span></label>
        <div class="field"><label>${esc(t("form.ssl"))}</label><select class="input" id="f-ssl">${opts([
      ["prefer", t("form.sslPrefer")],
      ["require", t("form.sslRequire")],
      ["verify-full", t("form.sslVerify")],
      ["disable", t("form.sslDisable")]
    ], c.sslMode)}</select><small class="hint">${esc(t("form.sslHint"))}</small></div>
      </div>
    </section>

    <section class="tab-panel hidden" data-panel="ssh">
      <label class="check"><input type="checkbox" id="f-ssh" ${c.ssh.enabled ? "checked" : ""}><span>${esc(t("form.sshEnable"))}<small>${esc(t("form.sshHint"))}</small></span></label>
      <div id="ssh-fields" style="display:grid;gap:14px">
        <div class="row c-3-1">
          <div class="field"><label>${esc(t("form.sshHost"))}</label><input class="input" id="f-sshhost" value="${esc(c.ssh.host)}" spellcheck="false"></div>
          <div class="field"><label>${esc(t("form.port"))}</label><input class="input" id="f-sshport" type="number" value="${esc(c.ssh.port || 22)}"></div>
        </div>
        <div class="field"><label>${esc(t("form.user"))}</label><input class="input" id="f-sshuser" value="${esc(c.ssh.user)}" spellcheck="false"></div>
        <div class="field"><label>${esc(t("form.sshAuth"))}</label>
          <div class="seg" id="f-sshauth"><button data-v="key">${esc(t("form.sshKey"))}</button><button data-v="password">${esc(t("form.password"))}</button><button data-v="agent">${esc(t("form.sshAgent"))}</button></div></div>
        <div id="ssh-key" style="display:grid;gap:14px">
          <div class="field"><label>${esc(t("form.keyFile"))}</label>
            <div class="key-wrap"><input class="input" id="f-key" value="${esc(c.ssh.keyPath)}" placeholder="C:\\Users\\\u2026\\.ssh\\id_ed25519" spellcheck="false"><button class="btn" id="f-keypick" type="button">${esc(t("common.choose"))}</button></div></div>
          <div class="field"><label>${esc(t("form.passphrase"))}</label><input class="input" id="f-phrase" type="password" placeholder="${esc(c.hasSshPassphrase ? t("form.passSaved") : t("form.passEmpty"))}"></div>
        </div>
        <div class="field" id="ssh-pw"><label>${esc(t("form.sshPassword"))}</label><input class="input" id="f-sshpass" type="password" placeholder="${c.hasSshPassword ? esc(t("form.pwSaved")) : ""}"></div>
        ${c.ssh.hostKey ? `<div class="fp">${esc(t("form.hostKey", { fp: c.ssh.hostKey }))}</div>` : ""}
      </div>
    </section>

    <div class="test-result" id="f-result"></div>
  </div>`);
    const q = (s) => $(s, body);
    $$("#f-tabs button", body).forEach((b) => b.onclick = () => {
      $$("#f-tabs button", body).forEach((x) => x.classList.toggle("on", x === b));
      $$(".tab-panel", body).forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== b.dataset.tab));
    });
    const goTab = (name) => q(`#f-tabs button[data-tab="${name}"]`).click();
    const setProvider = (id) => {
      const prev = providerMeta(provider);
      provider = id;
      const meta = providerMeta(id);
      $$("#f-prov .prov-btn", body).forEach((b) => b.classList.toggle("on", b.dataset.v === id));
      const file = meta.kind === "file";
      $$(".server-only", body).forEach((x) => x.classList.toggle("hidden", file));
      $$(".file-only", body).forEach((x) => x.classList.toggle("hidden", !file));
      q("#f-port").placeholder = String(meta.defaultPort ?? "");
      const user = q("#f-user");
      if (!user.value || user.value === prev.defaultUser) user.value = meta.defaultUser ?? "";
      q("#f-file-hint").textContent = id === "duckdb" ? t("form.duckdbHint") : t("form.sqliteHint");
    };
    $$("#f-prov .prov-btn", body).forEach((b) => b.onclick = () => setProvider(b.dataset.v));
    setProvider(provider);
    if (!isNew) $$("#f-prov .prov-btn", body).forEach((b) => b.disabled = b.dataset.v !== provider && providerMeta(b.dataset.v).kind !== providerMeta(provider).kind);
    const syncSsh = () => {
      q("#ssh-fields").classList.toggle("hidden", !q("#f-ssh").checked);
      $$("#f-sshauth button", body).forEach((b) => b.classList.toggle("on", b.dataset.v === sshAuth));
      q("#ssh-key").classList.toggle("hidden", sshAuth !== "key");
      q("#ssh-pw").classList.toggle("hidden", sshAuth !== "password");
    };
    q("#f-ssh").onchange = syncSsh;
    $$("#f-sshauth button", body).forEach((b) => b.onclick = () => {
      sshAuth = b.dataset.v;
      syncSsh();
    });
    syncSsh();
    q("#f-eye").onclick = () => {
      const p = q("#f-pass");
      p.type = p.type === "password" ? "text" : "password";
      q("#f-eye").innerHTML = icon(p.type === "password" ? "eye" : "eyeOff");
    };
    q("#f-filepick").onclick = async () => {
      const p = await api.openFileDialog({ provider, defaultPath: q("#f-file").value || void 0 });
      if (p) {
        q("#f-file").value = p;
        if (!q("#f-name").value) q("#f-name").value = p.split(/[\\/]/).pop() || "";
      }
    };
    q("#f-keypick").onclick = async () => {
      const p = await api.openFileDialog({});
      if (p) q("#f-key").value = p;
    };
    const colorsEl = q("#f-colors");
    for (const col of COLORS) {
      const b = h(`<button type="button" style="--c:${col}" class="${col === color ? "on" : ""}"></button>`);
      b.onclick = () => {
        color = col;
        $$("button", colorsEl).forEach((x) => x.classList.toggle("on", x === b));
      };
      colorsEl.appendChild(b);
    }
    const readForm = () => ({
      id: c.id || void 0,
      name: q("#f-name").value.trim(),
      provider,
      host: q("#f-host").value.trim(),
      port: Number(q("#f-port").value) || null,
      database: q("#f-db").value.trim(),
      user: q("#f-user").value.trim(),
      password: q("#f-pass").value,
      filePath: q("#f-file").value.trim(),
      sslMode: q("#f-ssl").value,
      readOnly: q("#f-ro").checked,
      savePassword: q("#f-savepw").checked,
      color,
      folderId: q("#f-folder").value || null,
      comments: q("#f-notes").value,
      ssh: {
        enabled: q("#f-ssh").checked,
        host: q("#f-sshhost").value.trim(),
        port: Number(q("#f-sshport").value) || 22,
        user: q("#f-sshuser").value.trim(),
        auth: sshAuth,
        keyPath: q("#f-key").value.trim(),
        hostKey: c.ssh.hostKey
      },
      sshPassword: q("#f-sshpass").value,
      sshPassphrase: q("#f-phrase").value
    });
    const validate = () => {
      const f = readForm();
      const file = providerMeta(f.provider).kind === "file";
      let ok = true;
      const mark = (id, bad, tab) => {
        q(id).classList.toggle("invalid", bad);
        if (bad && ok) {
          ok = false;
          goTab(tab);
        }
      };
      if (!file) mark("#f-host", !f.host, "general");
      if (f.provider === "sqlite") mark("#f-file", !f.filePath, "general");
      if (!file && f.ssh.enabled) {
        mark("#f-sshhost", !f.ssh.host, "ssh");
        mark("#f-sshuser", !f.ssh.user, "ssh");
        if (f.ssh.auth === "key") mark("#f-key", !f.ssh.keyPath, "ssh");
      }
      return ok;
    };
    const showResult = (cls, html) => {
      const r = q("#f-result");
      r.className = `test-result show ${cls}`;
      r.innerHTML = html;
    };
    const runTest = async (btn) => {
      if (!validate()) return false;
      btn.disabled = true;
      showResult("", `<span class="spin" style="color:var(--accent);margin-top:2px"></span><div>${esc(t("form.connecting"))}</div>`);
      const res = await api.testConnection(readForm());
      btn.disabled = false;
      if (res.ok && res.info) {
        const lines = [esc(res.info.product)];
        if (res.info.database) lines.push(esc(t("form.testDb", { db: res.info.database, user: res.info.user ?? "" })));
        if (res.info.tls === false && providerMeta(provider).kind === "server") lines.push(`<span style="color:var(--warn)">${esc(t("form.noTls"))}</span>`);
        showResult("ok", `${icon("check")}<div><b>${esc(t("form.testOk"))}</b> \xB7 ${res.ms} ms<br>${lines.join("<br>")}
        ${res.sshFingerprint ? `<div class="fp">${esc(t("form.hostKey", { fp: res.sshFingerprint }))}</div>` : ""}</div>`);
      } else {
        showResult("err", `${icon("x")}<div><b>${esc(t("form.testFail"))}</b><br>${esc(res.message)}</div>`);
      }
      return false;
    };
    const save = async (andConnect) => {
      if (!validate()) return false;
      const id = await api.saveConnection(readForm());
      toast(isNew ? t("form.saved") : t("form.changesSaved"), { type: "ok", sub: readForm().name || readForm().host || readForm().filePath });
      if (andConnect) void api.openConnection(id);
      return true;
    };
    await openModal({
      title: isNew ? t("form.titleNew") : t("form.titleEdit", { name: c.name }),
      iconName: "database",
      width: 660,
      body,
      buttons: [
        { label: t("form.test"), icon: "bolt", left: true, onClick: (_m, btn) => runTest(btn) },
        { label: t("common.cancel"), cls: "ghost", value: null },
        { label: t("form.saveConnect"), onClick: () => save(true) },
        { label: t("common.save"), cls: "primary", onClick: () => save(false) }
      ]
    });
  }
})();
