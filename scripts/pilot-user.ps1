<#
.SYNOPSIS
  Add, replace or remove one pilot login (username + password) for the local pilot proxy.

.DESCRIPTION
  Prompts for the password without echoing it, hashes it with Caddy (the password goes over
  stdin, never on a command line), and stores only "username bcrypt-hash" in
  infra/pilot/users.caddy (git-ignored). Run it in your own PowerShell window, then apply:
    docker compose -f infra/compose.yml --profile pilot restart proxy

  Passwords must be 12+ printable ASCII characters without spaces. Windows PowerShell adds a
  byte-order mark and CR when piping to a program; the container keeps only printable ASCII
  before hashing, so those extra bytes never become part of the password.

.EXAMPLE
  .\scripts\pilot-user.ps1 -Name alice
  .\scripts\pilot-user.ps1 -Name alice -Remove
#>
param(
    [string]$Name,
    [switch]$Remove
)
$ErrorActionPreference = "Stop"
$UsersFile = Join-Path $PSScriptRoot "..\infra\pilot\users.caddy"
$CaddyImage = "caddy:2.11.7"

function Get-PilotHash([string]$Plain) {
    if ($Plain -notmatch '^[\x21-\x7E]{12,}$') {
        throw "Use 12+ printable ASCII characters without spaces."
    }
    $hash = ($Plain | docker run -i --rm --entrypoint sh $CaddyImage -c "tr -cd '\041-\176\n' | caddy hash-password --algorithm bcrypt") |
        Where-Object { $_ -match '^\$2[aby]\$' } | Select-Object -Last 1
    if (-not $hash) { throw "Hashing failed; nothing was written." }
    return $hash.Trim()
}

function Set-PilotLogin([string]$Name, [string]$Plain, [switch]$Remove) {
    if ($Name -cnotmatch '^[a-z0-9][a-z0-9._-]{1,31}$') {
        throw "Use a lowercase username of 2-32 characters: letters, digits, '.', '_' or '-'."
    }
    $lines = @()
    if (Test-Path $UsersFile) {
        $lines = @(Get-Content $UsersFile | Where-Object { $_ -and -not $_.StartsWith("$Name ") })
    }
    if (-not $Remove) { $lines += "$Name $(Get-PilotHash $Plain)" }
    $text = if ($lines) { ($lines -join "`n") + "`n" } else { "" }
    $dir = Resolve-Path (Split-Path $UsersFile -Parent)
    # LF line endings and no BOM: Caddy would read a CR as part of the hash.
    [IO.File]::WriteAllText((Join-Path $dir "users.caddy"), $text, (New-Object Text.UTF8Encoding($false)))
    return $lines.Count
}

if ($MyInvocation.InvocationName -eq ".") { return }  # dot-sourced (tests): define functions only
if (-not $Name) { throw "Pass -Name <username>." }

$plain = $null
if (-not $Remove) {
    $secure = Read-Host "Password for $Name (12+ printable characters, no spaces)" -AsSecureString
    $confirm = Read-Host "Repeat the password" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $bstr2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($confirm)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        if ($plain -ne [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr2)) { throw "Passwords don't match." }
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr2)
    }
}
try {
    $count = Set-PilotLogin -Name $Name -Plain $plain -Remove:$Remove
} finally {
    $plain = $null
}
Write-Host "$(if ($Remove) { 'Removed' } else { 'Saved' }) login '$Name' ($count login(s) in infra/pilot/users.caddy)."
Write-Host "Apply it: docker compose -f infra/compose.yml --profile pilot restart proxy"
