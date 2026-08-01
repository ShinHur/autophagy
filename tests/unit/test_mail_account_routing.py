from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "skills" / "mail" / "scripts"))

import mail_account_routing  # noqa: E402
from mail_account_routing import AccountSelectionError, select_account  # noqa: E402


@pytest.mark.parametrize("account", ["gmail", "site"])
def test_explicit_account_is_selected(account: str) -> None:
    assert select_account(account) == account


def test_explicit_account_overrides_reply_inheritance() -> None:
    assert select_account("site", reply_to_account="gmail") == "site"
    assert select_account("gmail", reply_to_account="site") == "gmail"


@pytest.mark.parametrize("account", [" gmail ", "site\n", "\tsite"])
def test_surrounding_whitespace_is_stripped(account: str) -> None:
    assert select_account(account) == account.strip()


@pytest.mark.parametrize("account", ["gmail", "site"])
def test_reply_inherits_thread_account(account: str) -> None:
    assert select_account(None, reply_to_account=account) == account


def test_invalid_reply_account_is_rejected() -> None:
    with pytest.raises(AccountSelectionError) as excinfo:
        select_account(None, reply_to_account="other")
    assert "other" in str(excinfo.value)


def test_missing_account_fails_closed() -> None:
    with pytest.raises(AccountSelectionError) as excinfo:
        select_account(None)
    message = str(excinfo.value)
    assert "gmail" in message and "site" in message


@pytest.mark.parametrize(
    "account",
    ["outlook", "backend", "naver", "gmail.com", "gmail,site", "", "   "],
)
def test_unknown_account_is_rejected(account: str) -> None:
    with pytest.raises(AccountSelectionError):
        select_account(account)


@pytest.mark.parametrize("account", ["GMAIL", "Gmail", "SITE", "Site", "sItE"])
def test_casing_variants_are_not_coerced(account: str) -> None:
    with pytest.raises(AccountSelectionError):
        select_account(account)


def test_contract_lists_only_public_accounts() -> None:
    assert set(mail_account_routing.ACCOUNTS) == {"gmail", "site"}
    assert issubclass(AccountSelectionError, ValueError)
