<#
.SYNOPSIS
  Creates and manages the filament-kit Android release keystore.

.DESCRIPTION
  Default (no switch): create %LOCALAPPDATA%\filament-kit\release.jks once, with a random
  password stored via DPAPI in keystore.pw.dpapi. Refuses to overwrite an existing keystore.
  -Print   write the password to stdout (for make_release.sh; never log it)
  -Forget  delete the keystore AND the DPAPI password file (asks first; -Force skips the question)
  -Export <path>  write a passphrase-protected backup (.zip-less single file) for another PC
  -Import <path>  restore from such a backup (refuses to overwrite)
The password is generated here (CSPRNG); you never type it. A DPAPI file only decrypts on this
Windows account, so keep an -Export backup somewhere safe as well.
#>
[CmdletBinding()]
param(
    [switch]$Print,
    [switch]$Forget,
    [switch]$Force,
    [string]$Export,
    [string]$Import
)
$ErrorActionPreference = 'Stop'

$dir = Join-Path $env:LOCALAPPDATA 'filament-kit'
$jks = Join-Path $dir 'release.jks'
$pwFile = Join-Path $dir 'keystore.pw.dpapi'
$keytool = 'G:\Android\jdk-21.0.13+9\bin\keytool.exe'

function Read-StoredPassword {
    if (-not (Test-Path $pwFile)) { throw "No password file at $pwFile" }
    $ss = (Get-Content -LiteralPath $pwFile -Raw).Trim() | ConvertTo-SecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($ss)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Save-Password([string]$plain) {
    $ss = ConvertTo-SecureString $plain -AsPlainText -Force
    ConvertFrom-SecureString $ss | Set-Content -LiteralPath $pwFile -Encoding ascii
}

function New-RandomPassword {
    $chars = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })   # 48 chars
}

function Read-Passphrase([string]$prompt, [switch]$Confirm) {
    if ($env:FK_BACKUP_PASSPHRASE) { return (ConvertTo-SecureString $env:FK_BACKUP_PASSPHRASE -AsPlainText -Force) }   # automation/tests only
    $a = Read-Host $prompt -AsSecureString
    if ($Confirm) {
        $b = Read-Host 'Repeat passphrase' -AsSecureString
        $pa = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($a))
        $pb = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($b))
        if ($pa -ne $pb) { throw 'Passphrases do not match.' }
    }
    $a
}

if ($Print) {
    Write-Output (Read-StoredPassword)
    exit 0
}

if ($Forget) {
    if (-not $Force) {
        $ans = Read-Host "Delete $jks and $pwFile? Without a backup, installed apps can never be updated. Type YES"
        if ($ans -ne 'YES') { Write-Host 'Aborted.'; exit 1 }
    }
    Remove-Item -LiteralPath $jks, $pwFile -Force -ErrorAction SilentlyContinue
    Write-Host 'Keystore and password file deleted.'
    exit 0
}

if ($Export) {
    if (-not (Test-Path $jks) -or -not (Test-Path $pwFile)) { throw 'Nothing to export: keystore or password file missing.' }
    if (Test-Path $Export) { throw "Refusing to overwrite $Export" }
    $pass = Read-Passphrase 'Backup passphrase (you will need it to restore)' -Confirm
    # Passphrase-derived AES-256 key (PBKDF2-SHA256, 600k iterations); payload = JSON {jks b64, pw}.
    $payload = [Text.Encoding]::UTF8.GetBytes((@{
        jks = [Convert]::ToBase64String([IO.File]::ReadAllBytes($jks))
        pw  = (Read-StoredPassword)
    } | ConvertTo-Json -Compress))
    $salt = New-Object byte[] 16; $iv = New-Object byte[] 16
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create(); $rng.GetBytes($salt); $rng.GetBytes($iv); $rng.Dispose()
    $plainPass = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pass))
    $kdf = New-Object Security.Cryptography.Rfc2898DeriveBytes($plainPass, $salt, 600000, [Security.Cryptography.HashAlgorithmName]::SHA256)
    $key = $kdf.GetBytes(32); $kdf.Dispose()
    $aes = [Security.Cryptography.Aes]::Create(); $aes.Key = $key; $aes.IV = $iv
    $cipher = $aes.CreateEncryptor().TransformFinalBlock($payload, 0, $payload.Length); $aes.Dispose()
    $out = [Text.Encoding]::ASCII.GetBytes('FKKS1') + $salt + $iv + $cipher
    [IO.File]::WriteAllBytes($Export, $out)
    Write-Host "Backup written to $Export (restore with -Import)."
    exit 0
}

if ($Import) {
    if ((Test-Path $jks) -or (Test-Path $pwFile)) { throw 'A keystore already exists here; refusing to overwrite (use -Forget first).' }
    $raw = [IO.File]::ReadAllBytes($Import)
    if ([Text.Encoding]::ASCII.GetString($raw, 0, 5) -ne 'FKKS1') { throw 'Not a filament-kit keystore backup.' }
    $salt = $raw[5..20]; $iv = $raw[21..36]; $cipher = $raw[37..($raw.Length - 1)]
    $pass = Read-Passphrase 'Backup passphrase'
    $plainPass = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pass))
    $kdf = New-Object Security.Cryptography.Rfc2898DeriveBytes($plainPass, [byte[]]$salt, 600000, [Security.Cryptography.HashAlgorithmName]::SHA256)
    $aes = [Security.Cryptography.Aes]::Create(); $aes.Key = $kdf.GetBytes(32); $aes.IV = [byte[]]$iv
    try { $plain = $aes.CreateDecryptor().TransformFinalBlock([byte[]]$cipher, 0, $cipher.Length) }
    catch { throw 'Wrong passphrase or corrupted backup.' }
    $obj = [Text.Encoding]::UTF8.GetString($plain) | ConvertFrom-Json
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    [IO.File]::WriteAllBytes($jks, [Convert]::FromBase64String($obj.jks))
    Save-Password $obj.pw
    Write-Host "Restored $jks and the DPAPI password file."
    exit 0
}

# ---- create ----
if (Test-Path $jks) {
    Write-Error "Keystore already exists at $jks; refusing to overwrite."
    exit 1
}
if (-not (Test-Path $keytool)) { Write-Error "keytool not found at $keytool"; exit 1 }
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$pw = New-RandomPassword
$env:FK_KS_GEN_PW = $pw
try {
    $ErrorActionPreference = 'Continue'   # keytool writes progress to stderr
    & $keytool -genkeypair -keystore $jks -storetype PKCS12 -alias filament-kit `
        -keyalg RSA -keysize 4096 -validity 10000 -dname 'CN=filament-kit' `
        '-storepass:env' FK_KS_GEN_PW '-keypass:env' FK_KS_GEN_PW 2>$null | Out-Null
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $jks)) {
        Remove-Item -LiteralPath $jks -Force -ErrorAction SilentlyContinue
        Write-Error "keytool failed (exit $LASTEXITCODE); signing key NOT created."
        exit 1
    }
    Save-Password $pw
} finally {
    Remove-Item Env:FK_KS_GEN_PW -ErrorAction SilentlyContinue
}
Write-Host "Created $jks (password stored via DPAPI in $pwFile; never printed)."
Write-Host "BACK UP both files, and run -Export <path> for a copy that works on another PC."
