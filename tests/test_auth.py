import pytest

from core.auth import hash_password, verify_password


def test_round_trip():
    stored = hash_password("correct horse")
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong horse", stored)


def test_salt_is_random():
    assert hash_password("same password")["hash"] != hash_password("same password")["hash"]


def test_password_never_stored_in_clear():
    stored = hash_password("s3cret-pass")
    assert "s3cret-pass" not in str(stored)


def test_short_password_rejected():
    with pytest.raises(ValueError):
        hash_password("short")


@pytest.mark.parametrize("stored", [None, {}, {"salt": "zz", "hash": "zz"}, {"salt": "", "hash": ""}])
def test_bad_stored_values_fail_closed(stored):
    assert not verify_password("anything", stored)
