[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("setup", "start", "package", "help")]
    [string]$Command = "start",

    [string]$Python = "python",
    [string]$DataDirectory = "",
    [string]$Timezone = "",
    [string]$HostAddress = "",

    [ValidateRange(1, 65535)]
    [int]$Port = 8000,

    [switch]$AllowRemote
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDirectory = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvDirectory "Scripts\python.exe"
$npmExecutable = "npm.cmd"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable $($Arguments -join ' ')"
    }
}

function Assert-CommandAvailable {
    param([Parameter(Mandatory = $true)][string]$Name)

    if ($null -eq (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $Name"
    }
}

function Assert-ToolVersions {
    Assert-CommandAvailable -Name $Python
    Assert-CommandAvailable -Name "node"
    Assert-CommandAvailable -Name $npmExecutable

    $pythonVersion = & $Python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    if ($LASTEXITCODE -ne 0 -or [version]$pythonVersion -lt [version]"3.12") {
        throw "Python 3.12 or newer is required; found $pythonVersion"
    }

    $nodeVersion = (& node --version).TrimStart("v")
    if ($LASTEXITCODE -ne 0 -or [version]$nodeVersion -lt [version]"22.12") {
        throw "Node.js 22.12 or newer is required; found $nodeVersion"
    }
}

function Ensure-VirtualEnvironment {
    Assert-ToolVersions
    Set-Location $projectRoot

    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Write-Host "Creating .venv with $Python ..."
        Invoke-CheckedCommand -Executable $Python -Arguments @("-m", "venv", $venvDirectory)
    }
}

function Initialize-RuntimeEnvironment {
    Ensure-VirtualEnvironment

    Write-Host "Installing the production frontend ..."
    Invoke-CheckedCommand -Executable $npmExecutable -Arguments @("--prefix", "frontend", "ci")
    Invoke-CheckedCommand -Executable $npmExecutable -Arguments @("--prefix", "frontend", "run", "build")

    Write-Host "Installing Mellowday into .venv ..."
    Invoke-CheckedCommand -Executable $venvPython -Arguments @(
        "-m", "pip", "install", "--upgrade", "pip"
    )
    Invoke-CheckedCommand -Executable $venvPython -Arguments @(
        "-m", "pip", "install", "-r", "requirements.txt"
    )
}

function Ensure-RuntimeEnvironment {
    $runtimeReady = Test-Path -LiteralPath $venvPython -PathType Leaf
    if ($runtimeReady) {
        try {
            & $venvPython -c "import mellowday, tzdata" 2>&1 | Out-Null
            $runtimeReady = $LASTEXITCODE -eq 0
        } catch {
            $runtimeReady = $false
        }
    }
    if (-not $runtimeReady) {
        Write-Host "No local environment found; running first-time setup."
        Initialize-RuntimeEnvironment
    }
}

function Start-Mellowday {
    Ensure-RuntimeEnvironment
    Set-Location $projectRoot

    if ($DataDirectory) {
        $env:MELLOWDAY_DATA_DIR = $DataDirectory
    }
    if ($Timezone) {
        $env:MELLOWDAY_TIMEZONE = $Timezone
    }
    if ($HostAddress) {
        $env:MELLOWDAY_HOST = $HostAddress
    }
    $env:MELLOWDAY_PORT = [string]$Port
    if ($AllowRemote) {
        $env:MELLOWDAY_ALLOW_REMOTE = "1"
    }

    $effectiveHost = if ($HostAddress) { $HostAddress } elseif ($env:MELLOWDAY_HOST) {
        $env:MELLOWDAY_HOST
    } else {
        "127.0.0.1"
    }
    $displayHost = if ($effectiveHost -in @("0.0.0.0", "::")) { "127.0.0.1" } else {
        $effectiveHost
    }

    Write-Host "Starting Mellowday at http://${displayHost}:$Port/"
    Write-Host "Press Ctrl+C to stop the application."
    Invoke-CheckedCommand -Executable $venvPython -Arguments @("-m", "mellowday", "serve")
}

function Build-ReleasePackage {
    Ensure-VirtualEnvironment

    Write-Host "Installing release verification dependencies ..."
    Invoke-CheckedCommand -Executable $venvPython -Arguments @(
        "-m", "pip", "install", "-r", "requirements-dev.txt"
    )
    Invoke-CheckedCommand -Executable $venvPython -Arguments @(
        "-m", "playwright", "install", "chromium"
    )

    Write-Host "Running the release verification gate ..."
    Invoke-CheckedCommand -Executable $npmExecutable -Arguments @("--prefix", "frontend", "ci")
    Invoke-CheckedCommand -Executable $npmExecutable -Arguments @("--prefix", "frontend", "test")
    Invoke-CheckedCommand -Executable $npmExecutable -Arguments @("--prefix", "frontend", "run", "check")
    Invoke-CheckedCommand -Executable $npmExecutable -Arguments @("--prefix", "frontend", "run", "build")
    Invoke-CheckedCommand -Executable $venvPython -Arguments @(
        "-m", "mypy", "src", "build_backend.py"
    )
    Invoke-CheckedCommand -Executable $venvPython -Arguments @("-m", "pytest", "-q")

    $distributionDirectory = Join-Path $projectRoot "dist"
    New-Item -ItemType Directory -Force -Path $distributionDirectory | Out-Null
    Invoke-CheckedCommand -Executable $venvPython -Arguments @(
        "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation",
        "--wheel-dir", $distributionDirectory
    )

    Write-Host "Release wheel created in $distributionDirectory"
}

function Show-Usage {
    Write-Host @"
Mellowday Windows source launcher

  .\mellowday.ps1 start [-Timezone Asia/Shanghai] [-DataDirectory D:\MellowdayData]
  .\mellowday.ps1 setup
  .\mellowday.ps1 package

start   Starts browser mode and performs setup automatically when .venv is absent.
setup   Rebuilds the React frontend and installs the source checkout into .venv.
package Runs the complete verification gate and creates a wheel in dist\.
"@
}

switch ($Command) {
    "setup" { Initialize-RuntimeEnvironment }
    "start" { Start-Mellowday }
    "package" { Build-ReleasePackage }
    "help" { Show-Usage }
}
