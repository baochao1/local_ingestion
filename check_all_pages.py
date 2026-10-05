"""全站页面巡检：渲染状态 + console 报错 + 网络 4xx/5xx。

与上一版的区别：新增网络层断言。之前的版本只看 console/白屏，
因此 `POST` 的 400/500 完全被漏掉（本次注册 500 就是这么藏住的）。

用法：
    python check_all_pages.py            # 只巡检
    python check_all_pages.py --routes a,b   # 自定义路由
输出：pages_report.json
"""
from __future__ import annotations

import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://localhost:5173"

# 与 web/src/router.tsx 保持同步：新增路由务必同步加入此处巡检。
DEFAULT_ROUTES = [
    # 认证/首页
    "/login",
    # 第一批：API 已落地
    "/app/dashboard",
    "/app/datasources",
    "/app/datasources/1",
    "/app/catalog",
    "/app/catalog?q=test",
    "/app/catalog/tables/1",
    "/app/catalog/columns/1",
    "/app/changes",
    "/app/changes/statistics",
    "/app/changes/entities/table/some.table/history",
    "/app/changes/1",
    "/app/subscriptions",
    "/app/tasks",
    "/app/tasks/audit",
    "/app/tasks/partitions",
    "/app/tasks/1",
    "/app/system",
    "/app/governance/approvals",
    "/app/governance/tickets",
    "/app/business/terms",  # 业务术语（API 已落地）
    # 第二批：MOD-03/04/05 降级占位
    "/app/profile",
    "/app/profile/tables/1",
    "/app/profile/quality/rules",
    "/app/profile/quality/results",
    "/app/classification",
    "/app/classification/tags",
    "/app/classification/rules",
    "/app/classification/sensitive-assets",
    "/app/sampling",
    "/app/sampling/preview/1",
    "/app/sampling/columns/1/values",
    # 第三批：MOD-07/08 + 业务元数据
    "/app/lineage",
    "/app/lineage/tables/1",
    "/app/lineage/columns/1",
    "/app/permissions",
    "/app/permissions/accounts",
    "/app/permissions/matrix",
    "/app/permissions/risks",
    "/app/permissions/changes",
    "/app/business/entities",  # 业务实体（降级占位）
    # 第四批：MOD-11 系统管理
    "/app/admin",
    "/app/admin/users",
    "/app/admin/roles",
    "/app/admin/data-policies",
    "/app/admin/account-mappings",
    # 模块索引路由（重定向，顺带巡检避免死链）
    "/app/governance",
    "/app/business",
]

# favicon 404 属已知噪音，不计入失败
NOISE_PATTERNS = ("favicon.ico",)


def is_noise(url: str) -> bool:
    return any(p in url for p in NOISE_PATTERNS)


def main(routes: list[str]) -> None:
    results = []
    with sync_playwright() as p:
        browser = None
        for ch in ("msedge", "chrome"):
            try:
                browser = p.chromium.launch(channel=ch, headless=True, args=["--no-sandbox"])
                print(f"launched with channel={ch}")
                break
            except Exception as e:  # noqa: BLE001
                print(f"channel {ch} failed: {e}")
        if browser is None:
            print("无可用浏览器通道")
            sys.exit(1)

        page = browser.new_page()
        for route in routes:
            console_errors: list[str] = []
            page_errors: list[str] = []
            bad_responses: list[dict] = []

            def on_console(m):
                if m.type == "error":
                    console_errors.append(m.text)

            def on_pageerror(e):
                page_errors.append(str(e))

            def on_response(resp):
                if resp.status >= 400 and not is_noise(resp.url):
                    bad_responses.append({"url": resp.url, "status": resp.status})

            page.on("console", on_console)
            page.on("pageerror", on_pageerror)
            page.on("response", on_response)

            try:
                page.goto(BASE + route, wait_until="networkidle", timeout=20000)
                page.wait_for_timeout(1500)
            except Exception as e:  # noqa: BLE001
                console_errors.append(f"goto: {e}")

            info = page.evaluate(
                """() => {
                    const root = document.getElementById('root');
                    return {
                        rootLen: root ? root.innerHTML.length : -1,
                        hasOverlay: !!document.querySelector('vite-error-overlay'),
                        bodySnippet: document.body ? document.body.innerText.slice(0, 300) : '',
                        title: document.title,
                    };
                }"""
            )

            rec = {
                "route": route,
                "title": info["title"],
                "rootLen": info["rootLen"],
                "hasOverlay": info["hasOverlay"],
                "consoleErrors": console_errors,
                "pageErrors": page_errors,
                "badResponses": bad_responses,
                "bodySnippet": info["bodySnippet"],
            }
            results.append(rec)

            # 404 多为"该 id 无数据"的预期结果，不计为失败；5xx 与其它 4xx 才是。
            notfound = [b for b in bad_responses if b["status"] == 404]
            real_bad = [b for b in bad_responses if b["status"] != 404]
            flag = "FAIL" if (real_bad or page_errors or info["hasOverlay"]) else "ok"
            print(f"[{flag}] {route} rootLen={info['rootLen']} "
                  f"netFail={len(real_bad)} net404={len(notfound)} "
                  f"consoleErr={len(console_errors)} pageErr={len(page_errors)}")
            for b in real_bad:
                print(f"     {b['status']} {b['url']}")
            for pe in page_errors[:3]:
                print(f"     pageerror: {pe[:200]}")

        browser.close()

    with open("pages_report.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nWROTE pages_report.json")


if __name__ == "__main__":
    custom = None
    if "--routes" in sys.argv:
        custom = sys.argv[sys.argv.index("--routes") + 1].split(",")
    main(custom or DEFAULT_ROUTES)
