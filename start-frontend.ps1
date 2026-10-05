<#
.SYNOPSIS
    启动前端 Vite 开发服务器（http://localhost:5173）。

.DESCRIPTION
    - 复用 npm run dev；用 cmd /c 包装以兼容 Windows 上的 npm.cmd。
    - 若 5173 已被占用，先停掉旧进程再启动。
    - 开发代理已配置为转发 /api/v1 到 http://localhost:8090（见 web/vite.config.ts）。

.EXAMPLE
    .\start-frontend.ps1
#>
param(
    [int]$Port = 5173
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$web = Join-Path $root "web"
if (-not (Test-Path (Join-Path $web "node_modules"))) {
    Write-Host "未检测到 node_modules，先执行 npm install..."
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm install" `
        -WorkingDirectory $web -Wait -NoNewWindow
}

# 若端口被占用，停掉旧前端
$existing = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -ne 0 }
if ($existing) {
    Write-Host "端口 $Port 已被进程 $($existing -join ',') 占用，先停止..."
    Stop-Process -Id $existing -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

$out = Join-Path $web "frontend.out"
$err = Join-Path $web "frontend.err"
Write-Host "启动前端 http://localhost:$Port ..."
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm run dev" `
    -WorkingDirectory $web `
    -RedirectStandardOutput $out `
    -RedirectStandardError $err `
    -PassThru | Select-Object -ExpandProperty Id
Write-Host "已启动。日志: $err (stdout: $out)"
