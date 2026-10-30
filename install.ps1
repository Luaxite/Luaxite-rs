# install.ps1 [-NoModifyPath]
# Windows installer for zenpel (PowerShell 5.1+, built into Windows 10/11). Counterpart of install.sh.
#   irm https://raw.githubusercontent.com/Zenpel/Zenpel/HEAD/install.ps1 | iex
#   iex "& { $(irm https://raw.githubusercontent.com/Zenpel/Zenpel/HEAD/install.ps1) } -NoModifyPath"
param([switch]$NoModifyPath)

# Through `irm | iex` this runs in the caller's own session scope: remember the settings below and put them back when done (the finally at the
# end), so an install does not leave the user's PowerShell with $ErrorActionPreference = 'Stop' or a changed TLS setting.
$savedErrorAction = $ErrorActionPreference
$savedProgress = $ProgressPreference
$savedSecurityProtocol = [Net.ServicePointManager]::SecurityProtocol
try {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'   # progress bars make Invoke-WebRequest very slow on 5.1
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $Repo = 'Zenpel/Zenpel'
    $Name = 'zenpel'

    # CPU -> release target (assets are named <target>.zip, same as install.sh)
    $cpu = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    switch ($cpu) {
        'AMD64' { $target = 'x86_64-pc-windows-msvc' }
        'ARM64' { $target = 'aarch64-pc-windows-msvc' }
        default { throw "error: unsupported CPU: $cpu" }
    }
    $url = "https://github.com/$Repo/releases/latest/download/$target.zip"

    $tmp = Join-Path ([IO.Path]::GetTempPath()) "$Name-install-$PID"
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    try {
        # download and unpack
        $zip = Join-Path $tmp 'p.zip'
        try { Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip }
        catch { throw "error: download failed: $url" }
        $extract = Join-Path $tmp 'x'
        Expand-Archive -Path $zip -DestinationPath $extract -Force
        $src = Get-ChildItem -Path $extract -Recurse -File -Filter "$Name.exe" | Select-Object -First 1
        if (-not $src) { throw "error: no $Name.exe in payload" }

        # where to install: over an existing zenpel when its folder is writable, else the default folder
        $dir = $null
        $overwrite = $false
        $existing = Get-Command "$Name.exe" -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($existing) {
            $q = Split-Path -Parent $existing.Source
            try {
                $probe = Join-Path $q ".$Name.$PID"
                New-Item -ItemType File -Path $probe -Force | Out-Null
                Remove-Item $probe -Force
                $dir = $q
                $overwrite = $true
            } catch { }
        }
        if (-not $dir) { $dir = Join-Path $env:LOCALAPPDATA "Programs\$Name\bin" }
        New-Item -ItemType Directory -Path $dir -Force | Out-Null

        $exe = Join-Path $dir "$Name.exe"
        try { Copy-Item -Path $src.FullName -Destination $exe -Force }
        catch { throw "error: cannot write $exe (is $Name running?)" }

        # smoke test
        try {
            & $exe --help *> $null
            if ($LASTEXITCODE -ne 0) { throw 'nonzero exit' }
        } catch { [Console]::Error.WriteLine("warning: $exe did not run") }
        Write-Host "installed: $exe"

        # PATH (user scope), unless it was installed over an existing zenpel (already on PATH) or -NoModifyPath
        $onPath = $overwrite
        if (-not $NoModifyPath -and -not $overwrite) {
            # Read the user PATH raw (DoNotExpandEnvironmentNames) and write it back as ExpandString: GetEnvironmentVariable / SetEnvironmentVariable would
            # turn every %VAR% entry into its current value, silently freezing it.
            $envKey = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
            try {
                $userPath = [string]$envKey.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
                $parts = @($userPath -split ';' | Where-Object { $_ -ne '' })
                $norm = $dir.TrimEnd('\')
                $present = $parts | Where-Object {
                    $_.TrimEnd('\') -ieq $norm -or [Environment]::ExpandEnvironmentVariables($_).TrimEnd('\') -ieq $norm
                }
                if (-not $present) {
                    $envKey.SetValue('Path', (($parts + $dir) -join ';'), [Microsoft.Win32.RegistryValueKind]::ExpandString)
                    # writing the registry does not tell running programs: setting and removing a throwaway variable makes Windows broadcast the change
                    [Environment]::SetEnvironmentVariable("${Name}_path_refresh", '1', 'User')
                    [Environment]::SetEnvironmentVariable("${Name}_path_refresh", $null, 'User')
                    Write-Host 'PATH: updated user PATH'
                }
            }
            finally { $envKey.Close() }
            $env:Path = "$dir;$env:Path"   # usable in this session too
            $onPath = $true
        }
        if ($onPath) { Write-Host "done: run $Name" }
        else { Write-Host "done: add $dir to your PATH, then run $Name" }
    }
    finally {
        Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
finally {
    $ErrorActionPreference = $savedErrorAction
    $ProgressPreference = $savedProgress
    [Net.ServicePointManager]::SecurityProtocol = $savedSecurityProtocol
}
