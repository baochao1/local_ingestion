<#
.SYNOPSIS
    启动 Local Ingestion 后端（uvicorn），固化凭据密钥与数据库连接串。

.DESCRIPTION
    - 凭据加密密钥持久化在 .credential_key（首次运行生成，之后复用），
      保证多次重启后库内已加密的数据源凭据仍可解密。
    - 设置 DATABASE_URL（可用环境变量 LOCAL_INGESTION_DATABASE_URL 覆盖）。
    - 若 8090 已被占用，先停掉旧后端再启动，保证脚本可重复执行。
    - 数据库容器（wslc）需另行启动：wslc start pg-local-ingestion

.EXAMPLE
    .\start-backend.ps1              # 常规启动
    .\start-backend.ps1 -Migrate     # 启动前先跑 alembic 迁移（需 DB 已就绪）
#>
param(
    [string]$HostAddr = "127.0.0.1",
    [int]$Port = 8090,
    [switch]$Migrate
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venvPython = Join-Path $root ".venv/Scripts/python.exe"
if (-not (Test-Path $venvPython)) {
    throw "未找到虚拟环境解释器: $venvPython （请先 pip install -e . 创建 .venv）"
}

# 1) 持久化凭据加密密钥（32 字节 -> 44 字符 base64）
$keyFile = Join-Path $root ".credential_key"
if (Test-Path $keyFile) {
    $key = (Get-Content $keyFile -Raw).Trim()
    Write-Host "复用已存在的凭据密钥: $keyFile"
} else {
    $key = & $venvPython -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
    Set-Content -Path $keyFile -Value $key -NoNewline
    Write-Host "已生成并保存凭据密钥到: $keyFile"
}
$env:CREDENTIAL_ENCRYPTION_KEY = $key

# 2) 数据库连接串（可被环境变量覆盖）
$env:DATABASE_URL = if ($env:LOCAL_INGESTION_DATABASE_URL) {
    $env:LOCAL_INGESTION_DATABASE_URL
} else {
    "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"
}

# 3) 可选：迁移表结构
if ($Migrate) {
    Write-Host "确保 alembic 已安装并升级表结构..."
    & $venvPython -m pip install alembic *> $null
    $env:METADATA_DB_URL = $env:DATABASE_URL
    & $venvPython -m alembic upgrade head
}

# 4) 若端口被占用，停掉旧后端（避免重复实例）
$existing = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -ne 0 }
if ($existing) {
    Write-Host "端口 $Port 已被进程 $($existing -join ',') 占用，先停止..."
    Stop-Process -Id $existing -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

# 5) 启动
$out = Join-Path $root "backend.out"
$err = Join-Path $root "backend.err"
Write-Host "启动后端 http://$HostAddr`:$Port ..."
Start-Process -FilePath $venvPython `
    -ArgumentList "-m", "uvicorn", "local_ingestion.api.app:app", "--host", $HostAddr, "--port", $Port `
    -WorkingDirectory $root `
    -RedirectStandardOutput $out `
    -RedirectStandardError $err `
    -PassThru | Select-Object -ExpandProperty Id
Write-Host "已启动。日志: $err (stdout: $out)"
