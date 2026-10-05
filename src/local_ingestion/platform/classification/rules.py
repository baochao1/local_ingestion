"""Sensitivity / grading rules (MOD-05).

Why this module exists
----------------------
Nothing in the codebase ever wrote ``grade_level`` for *scanned* data — the only
writer was :func:`platform.storage.seed` filling it with ``randint(1, 9)``. That
left two consumers permanently empty:

* :meth:`platform.catalog.source.SqlCatalogStatsSource.sensitive_count` counts
  rows with ``grade_level >= SENSITIVE_GRADE_THRESHOLD`` (2), so the overview's
  sensitive-asset ratio was always 0.
* :func:`platform.versioning.adapter.build_catalog_state` derives
  ``is_pii`` / ``high_sensitivity`` from **tags and properties** (``PII`` /
  ``HIGH`` tags or ``properties.pii``), which the scan never set either — so
  every change was classified as if it touched non-sensitive data.

The scale below is chosen to fit that threshold: **1 means "not sensitive"**,
and 2..5 ascend. Marking ordinary business columns as 2 would push the ratio to
~100% and make the metric useless, so grade 2 is reserved for genuinely
sensitive business data.

Grade ladder
------------
===  ============  =========================================================
1    INTERNAL      一般业务数据，不含个人信息
2    SENSITIVE     业务敏感但非个人身份（金额、余额、价格…）
3    PII           可识别到自然人（姓名、手机、邮箱、地址…）
4    PII_HIGH      强标识/高敏个人信息（证件号、银行卡、医疗、生物特征…）
5    CONFIDENTIAL  机密（工资、征信、密钥、口令…）
===  ============  =========================================================

Matching is deliberately conservative on ``name``: ``product_name`` is *not*
PII, only person-ish names (``name``, ``user_name``, ``full_name``…) are.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

#: grade -> code stored in ``grade_code``.
GRADE_CODES = {
    1: "INTERNAL",
    2: "SENSITIVE",
    3: "PII",
    4: "PII_HIGH",
    5: "CONFIDENTIAL",
}

#: Grade at/above which a column is personally identifiable.
PII_GRADE = 3
#: Grade at/above which a column counts as high-sensitivity.
HIGH_GRADE = 4

_TOKEN_SPLIT = re.compile(r"[^a-zA-Z0-9]+")

_PII_HIGH_TOKENS = frozenset({
    "idcard", "ssn", "passport", "passportno", "bankcard", "cardno",
    "creditcard", "iban", "taxno", "medical", "biometric", "fingerprint",
    "dna", "faceid", "credential", "secret", "token", "password", "passwd",
    "pwd", "privatekey", "apikey",
})
_PII_HIGH_COMPOUND = re.compile(r"(?:id|identity)card|(?:card|account)no")

_PII_TOKENS = frozenset({
    "phone", "mobile", "tel", "telephone", "email", "mail", "address",
    "addr", "birthday", "birth", "dob", "gender", "sex", "nickname",
    "avatar", "ip", "postcode", "zipcode", "wechat", "qq",
})
#: ``name`` only counts as PII when it names a *person* — product/file names
#: must stay ungraded (1).
_PERSON_NAME = re.compile(
    r"^(?:user|customer|cust|client|contact|person|emp|employee|member|"
    r"account|full|real|first|last|nick|sur|given)?_?name$"
)

#: Deliberately excludes operational counters (qty/quantity/stock): they are not
#: sensitive, and since the sensitive threshold is 2 they would otherwise push
#: the overview's sensitive-asset ratio towards 100%.
_SENSITIVE_TOKENS = frozenset({
    "amount", "money", "price", "salary", "income", "balance", "cost",
    "fee", "payment", "pay", "profit", "revenue", "discount", "rate",
    "turnover", "tax", "invoice", "bonus",
})

_CN_PII_HIGH = ("身份证", "护照", "银行卡", "信用卡", "病历", "指纹", "社保", "密钥", "口令", "密码")
_CN_PII = ("姓名", "手机", "电话", "邮箱", "邮件", "地址", "生日", "出生", "性别", "昵称", "邮编")
_CN_SENSITIVE = ("金额", "余额", "价格", "工资", "薪资", "收入", "成本", "费用", "发票", "税率", "利润")


@dataclass(frozen=True)
class Verdict:
    """Outcome of grading one column."""

    grade_level: int
    grade_code: str
    is_pii: bool
    high_sensitivity: bool
    reason: str

    @property
    def tags(self) -> tuple:
        out = []
        if self.is_pii:
            out.append("PII")
        if self.high_sensitivity:
            out.append("HIGH")
        return tuple(out)


def _tokens(name: str) -> set:
    out: set = set()
    for part in _TOKEN_SPLIT.split(name or ""):
        if not part:
            continue
        for sub in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|[0-9]+", part):
            out.add(sub.lower())
    return out


def classify_column(
    name: str,
    data_type: Optional[str] = None,
    description: Optional[str] = None,
) -> Verdict:
    """Grade a single column from its name, type and comment.

    Rules are evaluated most-severe-first, so the first hit wins.
    """
    tokens = _tokens(name)
    # Compound forms (``id_card_no`` -> ``idcardno``) must be matched against the
    # name in its original order — joining a *set* of tokens scrambles it.
    norm = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    haystack = f"{name or ''} {description or ''}"

    def _verdict(level: int, reason: str) -> Verdict:
        return Verdict(
            grade_level=level,
            grade_code=GRADE_CODES[level],
            is_pii=level >= PII_GRADE,
            high_sensitivity=level >= HIGH_GRADE,
            reason=reason,
        )

    # 5 - secrets / credentials ("key" alone is ambiguous, so it only counts
    # when qualified as a cryptographic/API key).
    if tokens & {"password", "passwd", "pwd", "secret", "token", "privatekey", "apikey", "credential"}:
        return _verdict(5, "credential")
    if "key" in tokens and tokens & {"api", "private", "secret", "access", "auth", "encryption"}:
        return _verdict(5, "credential:key")
    if any(k in haystack for k in ("密码", "口令", "密钥")):
        return _verdict(5, "credential:cn")

    # 4 - strong identifiers / high-sensitivity personal data
    if tokens & _PII_HIGH_TOKENS or _PII_HIGH_COMPOUND.search(norm):
        return _verdict(4, "identifier")
    if any(k in haystack for k in _CN_PII_HIGH):
        return _verdict(4, "identifier:cn")

    # 3 - personal data
    if tokens & _PII_TOKENS:
        return _verdict(3, "personal")
    if _PERSON_NAME.match((name or "").strip().lower().replace("_", "")):
        return _verdict(3, "personal:name")
    if any(k in haystack for k in _CN_PII):
        return _verdict(3, "personal:cn")

    # 2 - business-sensitive
    if tokens & _SENSITIVE_TOKENS:
        return _verdict(2, "business")
    if (data_type or "").lower().startswith("money"):
        return _verdict(2, "business:money")
    if any(k in haystack for k in _CN_SENSITIVE):
        return _verdict(2, "business:cn")

    return _verdict(1, "default")


def classify_table(columns: list) -> Verdict:
    """Grade a table as the most severe of its columns (floor 1)."""
    if not columns:
        return Verdict(1, GRADE_CODES[1], False, False, "no-columns")
    worst = max(
        (classify_column(c.name, getattr(c, "data_type", None), getattr(c, "description", None))
         for c in columns),
        key=lambda v: v.grade_level,
    )
    return Verdict(
        grade_level=worst.grade_level,
        grade_code=GRADE_CODES[worst.grade_level],
        is_pii=worst.grade_level >= PII_GRADE,
        high_sensitivity=worst.grade_level >= HIGH_GRADE,
        reason=f"max-column:{worst.reason}",
    )
