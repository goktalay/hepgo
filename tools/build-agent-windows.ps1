<#
  HEPGO fabrika ajanı — Windows kurulum paketi (.exe) üretici.
  Bir WINDOWS derleme makinesinde çalıştırılır (burada, Linux'ta ÜRETİLEMEZ).

  Kullanım (yönetici PowerShell, depo kökünde):
      tools\build-agent-windows.ps1 -Integ mikro

  Gerekenler:
    * Python 3 (PATH'te; yalnız agent.profiles'tan bağımlılık/ad okumak için — paketlenen Python ayrıdır)
    * tar.exe (Windows 10+ yerleşik)
    * Inno Setup 6 (ISCC.exe PATH'te) — https://jrsoftware.org/isdl.php

  Üretir:  agent-dist\<integ>\hepgo-<integ>-setup-windows.exe
    İçinde: taşınabilir CPython 3.12 (python-build-standalone, pinli msvc, sha256 doğrulanır),
            TABAN + entegrasyon pip bağımlılıkları, app\ + agent\ kodu, NSSM (servis yöneticisi).
    Kurulumda: %ProgramFiles%\HepgoAgent-<integ> altına kurar, Windows servisi (NSSM) kaydeder,
               Başlat menüsü / Masaüstü kısayolu yerel ayar sayfasını (http://127.0.0.1:8765) açar.
#>
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('mikro', 'pdks', 'printer', 'camera', 'face')]
  [string]$Integ
)
$ErrorActionPreference = 'Stop'

# ---- pinli taşınabilir CPython (Windows msvc) ----
$PbsDate = '20241016'
$PbsPy   = '3.12.7'
$Triple  = 'x86_64-pc-windows-msvc'
$PbsFile = "cpython-$PbsPy+$PbsDate-$Triple-install_only.tar.gz"
$PbsUrl  = "https://github.com/astral-sh/python-build-standalone/releases/download/$PbsDate/$PbsFile"
$PbsSha  = 'f05531bff16fa77b53be0776587b97b466070e768e6d5920894de988bdcd547a'

# NSSM (servisi çalıştırmak için). Sürüm pinli; indirilip çıkarılır.
$NssmUrl = 'https://nssm.cc/release/nssm-2.24.zip'

$Root   = Split-Path -Parent $PSScriptRoot
$Cache  = Join-Path $Root 'tools\.cache'
$OutDir = Join-Path $Root "agent-dist\$Integ"
$Stage  = Join-Path $env:TEMP "hepgo-stage-$Integ"
New-Item -ItemType Directory -Force -Path $Cache, $OutDir | Out-Null
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'code') | Out-Null

Push-Location $Root
$Deps = (& python -c "import agent.profiles as p; print(' '.join(p.pip_requirements('$Integ')))").Trim()
$Name = (& python -c "import agent.profiles as p; print(p.get('$Integ')['name'])").Trim()
Pop-Location
Write-Host ">> [$Integ] $Name"
Write-Host ">> bağımlılıklar: $Deps"

# ---- 1) CPython indir + sha256 ----
$Tarball = Join-Path $Cache $PbsFile
if (-not (Test-Path $Tarball)) {
  Write-Host ">> CPython indiriliyor: $PbsUrl"
  Invoke-WebRequest -Uri $PbsUrl -OutFile $Tarball
}
$h = (Get-FileHash -Algorithm SHA256 $Tarball).Hash.ToLower()
if ($h -ne $PbsSha) { throw "CPython sha256 uyuşmadı: $h" }

Write-Host ">> CPython açılıyor"
tar -xzf $Tarball -C $Stage          # → $Stage\python\
$Py = Join-Path $Stage 'python\python.exe'
if (-not (Test-Path $Py)) { throw "taşınabilir python bulunamadı: $Py" }

# ---- 2) pip bağımlılıkları ----
Write-Host ">> pip + bağımlılıklar kuruluyor"
& $Py -m pip install --upgrade pip --no-warn-script-location
& $Py -m pip install --no-warn-script-location $Deps.Split(' ')

# ---- 3) kod ----
Write-Host ">> kod kopyalanıyor (app\, agent\)"
robocopy (Join-Path $Root 'app')   (Join-Path $Stage 'code\app')   /E /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null
robocopy (Join-Path $Root 'agent') (Join-Path $Stage 'code\agent') /E /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null

# ---- 4) NSSM ----
$NssmZip = Join-Path $Cache 'nssm-2.24.zip'
if (-not (Test-Path $NssmZip)) { Invoke-WebRequest -Uri $NssmUrl -OutFile $NssmZip }
Expand-Archive -Path $NssmZip -DestinationPath (Join-Path $Cache 'nssm') -Force
Copy-Item (Join-Path $Cache 'nssm\nssm-2.24\win64\nssm.exe') (Join-Path $Stage 'nssm.exe') -Force

# ---- 5) Inno Setup ----
$Iss = Join-Path $PSScriptRoot 'hepgo-agent.iss'
Write-Host ">> Inno Setup derleniyor (ISCC)"
& ISCC.exe "/DInteg=$Integ" "/DIntegName=$Name" "/DStageDir=$Stage" "/DOutDir=$OutDir" $Iss
Write-Host ">> ÜRETİLDİ: $OutDir\hepgo-$Integ-setup-windows.exe"
