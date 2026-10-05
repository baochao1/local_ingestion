"""API 冒烟：从 /openapi.json 自动枚举并调用所有 GET 端点，抓出 5xx。

只读、安全（不执行写操作）。404 属"无数据"预期，5xx 才是真 bug。

用法：
    python api_smoke.py
    python api_smoke.py --show-keys   # 同时打印响应顶层字段（用于核对前后端契约）
"""
from __future__ import annotations

import io
import json
import re
import sys
from urllib.parse import urljoin

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

API_ROOT = "http://127.0.0.1:8090"
SPEC_URL = f"{API_ROOT}/openapi.json"


def get_json(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def status_of(url: str, timeout: int = 15) -> tuple[int, object]:
    """返回 (status, parsed_json_or_None)；连接错误返回 (-1, error_string)。"""
    try:
        status, data = get_json(url, timeout)
        return status, data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except Exception:  # noqa: BLE001
            return e.code, body
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def fill_params(path: str) -> str:
    """把 /x/{id} 这类路径参数替换成合理的示例值。"""
    def repl(m):
        name = m.group(1).lower()
        if "fqn" in name:
            return "seed.table"
        if "type" in name:
            return "table"
        if "version" in name:
            return "1"
        return "1"

    return re.sub(r"\{([^}]+)\}", repl, path)


def main() -> int:
    status, spec = status_of(SPEC_URL)
    if status != 200:
        print(f"无法获取 openapi.json（status={status}）：{spec}")
        return 2

    paths = spec.get("paths", {})
    ok, notfound, server_err, other = [], [], [], []

    for path, methods in sorted(paths.items()):
        for method, meta in methods.items():
            if method.lower() != "get":
                continue
            url = urljoin(API_ROOT + "/", fill_params(path.lstrip("/")))
            st, data = status_of(url)
            line = f"{st:>3}  GET {path}"
            if st == 200:
                ok.append(line)
            elif st == 404:
                notfound.append(line + "  (无数据，预期)")
            elif st >= 500 or st == -1:
                server_err.append(line + f"  {str(data)[:200]}")
            else:
                other.append(line + f"  {str(data)[:160]}")

            if "--show-keys" in sys.argv and isinstance(data, dict):
                print(f"      keys: {sorted(data.keys())}")

    print(f"GET 端点 {len(ok) + len(notfound) + len(server_err) + len(other)} 个")
    print(f"  ✓ 200: {len(ok)}")
    print(f"  · 404: {len(notfound)}")
    print(f"  ✗ 5xx/连接失败: {len(server_err)}")
    print(f"  ! 其他: {len(other)}")

    print("\n=== 5xx / 连接失败（真 bug）===")
    for l in server_err:
        print(l)
    if not server_err:
        print("（无）")

    print("\n=== 其他非 200（需人工确认）===")
    for l in other:
        print(l)
    if not other:
        print("（无）")

    return 1 if (server_err or other) else 0


if __name__ == "__main__":
    sys.exit(main())
