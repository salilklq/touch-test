# Fix the Python serial/pyserial environment on Windows.
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\fix_serial_env.ps1
#
# Notes:
#   - The package to install is "pyserial"; the import name is "serial".
#   - This script avoids bare "pip" and always uses "python -m pip".

[CmdletBinding()]
param(
    [switch]$NoInstallPython,
    [ValidateSet("PythonOrg", "Winget")]
    [string]$InstallMethod = "PythonOrg",
    [string]$PythonVersion = "3.12.10",
    [string]$WingetPythonId = "Python.Python.3.12",
    [int]$WingetTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-WarnLine {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-ErrLine {
    param([string]$Message)
    Write-Host "[ERR] $Message" -ForegroundColor Red
}

function Invoke-Tool {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [switch]$AllowFailure
    )

    & $FilePath @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        throw "$FilePath $($Arguments -join ' ') failed with exit code $exitCode"
    }
    return $exitCode
}

function Invoke-ProcessWithTimeout {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 300,
        [switch]$AllowFailure
    )

    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -PassThru -NoNewWindow
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        try {
            $process.Kill()
        }
        catch {
            # Best effort only.
        }
        throw "$FilePath timed out after $TimeoutSeconds seconds"
    }

    if ($process.ExitCode -ne 0 -and -not $AllowFailure) {
        throw "$FilePath $($Arguments -join ' ') failed with exit code $($process.ExitCode)"
    }

    return $process.ExitCode
}

function Test-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$PrefixArgs = @()
    )

    try {
        $probe = @"
import sys
print(sys.executable)
print(sys.version.split()[0])
"@
        $output = & $Command @PrefixArgs -c $probe 2>$null
        if ($LASTEXITCODE -eq 0 -and $output.Count -ge 2) {
            return [pscustomobject]@{
                Command = $Command
                PrefixArgs = $PrefixArgs
                Executable = [string]$output[0]
                Version = [string]$output[1]
            }
        }
    }
    catch {
        return $null
    }

    return $null
}

function Find-Python {
    $seen = @{}
    $candidates = New-Object System.Collections.Generic.List[object]

    foreach ($name in @("py", "python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $cmd -and -not $seen.ContainsKey($cmd.Source)) {
            $seen[$cmd.Source] = $true
            if ($name -eq "py") {
                $candidates.Add([pscustomobject]@{ Command = $cmd.Source; PrefixArgs = @("-3") }) | Out-Null
                $candidates.Add([pscustomobject]@{ Command = $cmd.Source; PrefixArgs = @() }) | Out-Null
            }
            else {
                $candidates.Add([pscustomobject]@{ Command = $cmd.Source; PrefixArgs = @() }) | Out-Null
            }
        }
    }

    $possiblePythonExe = New-Object System.Collections.Generic.List[string]
    $possiblePythonExe.Add((Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe")) | Out-Null
    $possiblePythonExe.Add((Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe")) | Out-Null
    $possiblePythonExe.Add((Join-Path $env:LocalAppData "Programs\Python\Python310\python.exe")) | Out-Null
    $possiblePythonExe.Add((Join-Path $env:USERPROFILE "AppData\Local\Programs\Python\Python312\python.exe")) | Out-Null
    $possiblePythonExe.Add((Join-Path $env:USERPROFILE "AppData\Local\Programs\Python\Python311\python.exe")) | Out-Null
    $possiblePythonExe.Add((Join-Path $env:USERPROFILE "miniconda3\python.exe")) | Out-Null
    $possiblePythonExe.Add((Join-Path $env:USERPROFILE "anaconda3\python.exe")) | Out-Null
    $possiblePythonExe.Add((Join-Path $env:USERPROFILE "scoop\apps\python\current\python.exe")) | Out-Null

    if ($env:ProgramFiles) {
        $possiblePythonExe.Add((Join-Path $env:ProgramFiles "Python312\python.exe")) | Out-Null
        $possiblePythonExe.Add((Join-Path $env:ProgramFiles "Python311\python.exe")) | Out-Null
        $possiblePythonExe.Add((Join-Path $env:ProgramFiles "Python310\python.exe")) | Out-Null
    }
    if (${env:ProgramFiles(x86)}) {
        $possiblePythonExe.Add((Join-Path ${env:ProgramFiles(x86)} "Python312\python.exe")) | Out-Null
        $possiblePythonExe.Add((Join-Path ${env:ProgramFiles(x86)} "Python311\python.exe")) | Out-Null
        $possiblePythonExe.Add((Join-Path ${env:ProgramFiles(x86)} "Python310\python.exe")) | Out-Null
    }

    $localPythonRoot = Join-Path $env:LocalAppData "Programs\Python"
    if (Test-Path -LiteralPath $localPythonRoot) {
        Get-ChildItem -LiteralPath $localPythonRoot -Directory -Filter "Python*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object {
                $possiblePythonExe.Add((Join-Path $_.FullName "python.exe")) | Out-Null
            }
    }

    foreach ($path in $possiblePythonExe) {
        if ($path -and (Test-Path -LiteralPath $path) -and -not $seen.ContainsKey($path)) {
            $seen[$path] = $true
            $candidates.Add([pscustomobject]@{ Command = $path; PrefixArgs = @() }) | Out-Null
        }
    }

    foreach ($candidate in $candidates) {
        $python = Test-PythonCandidate -Command $candidate.Command -PrefixArgs $candidate.PrefixArgs
        if ($null -ne $python) {
            return $python
        }
    }

    return $null
}

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)]$Python,
        [string[]]$Arguments = @(),
        [switch]$AllowFailure
    )

    $allArgs = @()
    $allArgs += $Python.PrefixArgs
    $allArgs += $Arguments
    return Invoke-Tool -FilePath $Python.Command -Arguments $allArgs -AllowFailure:$AllowFailure
}

function Install-PythonFromPythonOrg {
    param([string]$Version)

    $arch = $env:PROCESSOR_ARCHITECTURE
    $archWow = $env:PROCESSOR_ARCHITEW6432

    if ($arch -eq "ARM64" -or $archWow -eq "ARM64") {
        $fileName = "python-$Version-arm64.exe"
    }
    elseif ([Environment]::Is64BitOperatingSystem) {
        $fileName = "python-$Version-amd64.exe"
    }
    else {
        $fileName = "python-$Version.exe"
    }

    $url = "https://www.python.org/ftp/python/$Version/$fileName"
    $installerPath = Join-Path $env:TEMP $fileName

    Write-Step "Downloading Python $Version from python.org"
    Write-Host $url

    $needDownload = $true
    if (Test-Path -LiteralPath $installerPath) {
        $existing = Get-Item -LiteralPath $installerPath
        if ($existing.Length -gt 1000000) {
            $needDownload = $false
            Write-Ok "Using existing installer: $installerPath"
        }
    }

    if ($needDownload) {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($null -ne $curl) {
            Invoke-Tool -FilePath $curl.Source -Arguments @(
                "--location",
                "--fail",
                "--connect-timeout", "20",
                "--max-time", "600",
                "--output", $installerPath,
                $url
            ) | Out-Null
        }
        else {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $url -OutFile $installerPath -UseBasicParsing
        }
    }

    if (-not (Test-Path -LiteralPath $installerPath)) {
        throw "Python installer was not downloaded: $installerPath"
    }

    $installer = Get-Item -LiteralPath $installerPath
    if ($installer.Length -lt 1000000) {
        throw "Downloaded Python installer looks incomplete: $installerPath"
    }

    Write-Step "Installing Python $Version silently"
    Write-Host "This usually takes 1-3 minutes."
    $installArgs = @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_launcher=1",
        "Include_pip=1",
        "Include_test=0",
        "SimpleInstall=1"
    )
    Invoke-ProcessWithTimeout -FilePath $installerPath -Arguments $installArgs -TimeoutSeconds 600 | Out-Null
}

function Install-PythonWithWinget {
    param(
        [string]$PackageId,
        [int]$TimeoutSeconds
    )

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw "winget was not found"
    }

    Write-Step "Installing Python with winget"
    $installArgs = @(
        "install",
        "--id", $PackageId,
        "--exact",
        "--source", "winget",
        "--scope", "user",
        "--accept-package-agreements",
        "--accept-source-agreements"
    )
    $installExit = Invoke-ProcessWithTimeout -FilePath $winget.Source -Arguments $installArgs -TimeoutSeconds $TimeoutSeconds -AllowFailure

    if ($installExit -ne 0) {
        Write-WarnLine "User-scope winget install failed. Retrying without --scope."
        $installArgs = @(
            "install",
            "--id", $PackageId,
            "--exact",
            "--source", "winget",
            "--accept-package-agreements",
            "--accept-source-agreements"
        )
        Invoke-ProcessWithTimeout -FilePath $winget.Source -Arguments $installArgs -TimeoutSeconds $TimeoutSeconds | Out-Null
    }
}

Write-Host "Python serial environment fixer"
Write-Host "Working directory: $PSScriptRoot"

Write-Step "Looking for a usable Python"
$python = Find-Python

if ($null -eq $python) {
    Write-WarnLine "No usable Python was found. The Microsoft Store alias is not enough."

    if ($NoInstallPython) {
        Write-ErrLine "Python install was skipped because -NoInstallPython was provided."
        exit 1
    }

    if ($InstallMethod -eq "Winget") {
        Install-PythonWithWinget -PackageId $WingetPythonId -TimeoutSeconds $WingetTimeoutSeconds
    }
    else {
        Install-PythonFromPythonOrg -Version $PythonVersion
    }

    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"

    Write-Step "Looking for Python again"
    $python = Find-Python
}

if ($null -eq $python) {
    Write-ErrLine "Python is still not usable. Open a new PowerShell window and run this script again."
    exit 1
}

Write-Ok "Python $($python.Version)"
Write-Host "Executable: $($python.Executable)"

Write-Step "Ensuring pip is available"
Invoke-Python -Python $python -Arguments @("-m", "ensurepip", "--upgrade") -AllowFailure | Out-Null

Write-Step "Upgrading pip tooling"
Invoke-Python -Python $python -Arguments @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel") | Out-Null

Write-Step "Removing the wrong package name if it exists"
Invoke-Python -Python $python -Arguments @("-m", "pip", "uninstall", "-y", "serial") -AllowFailure | Out-Null

Write-Step "Installing the correct package: pyserial"
Invoke-Python -Python $python -Arguments @("-m", "pip", "install", "--upgrade", "pyserial") | Out-Null

Write-Step "Verifying import serial and serial.tools.list_ports"
$verify = @"
import sys
import serial
import serial.tools.list_ports

print("python_executable=" + sys.executable)
print("serial_module=" + str(getattr(serial, "__file__", "")))
print("pyserial_version=" + str(getattr(serial, "__version__", "unknown")))

ports = list(serial.tools.list_ports.comports())
if ports:
    print("ports=" + ", ".join(p.device for p in ports))
else:
    print("ports=none_detected")
"@

Invoke-Python -Python $python -Arguments @("-c", $verify) | Out-Null

Write-Ok "Done. Use this form instead of bare pip:"
Write-Host "  python -m pip install pyserial"
Write-Host ""
Write-Host "Your scripts can keep using:"
Write-Host "  import serial"
