"""The aliases: set, address a device by its alias, list, remove, delete."""

import pytest

ALIAS = "it_pump"
OUTPUT = "/rest/do/1_03/"


@pytest.fixture(autouse=True)
def no_alias(http):
    """DO 1_03 and 1_04 have no alias and the alias does not exist before and after each test"""

    def clean():
        for circuit in ("1_03", "1_04"):
            http.post_form(f"/rest/do/{circuit}/", {"alias": ""})
        http.post_form("/rest/run/alias/", {"delete": ALIAS})

    clean()
    yield
    clean()


def test_set_alias(http):
    r = http.post_form(f"{OUTPUT}alias", {"alias": ALIAS})
    assert r.status == 200, r.raw_text
    assert r.body["success"] is True
    assert r.body["result"]["alias"] == ALIAS


def test_set_alias_by_the_post_of_the_device(http):
    r = http.post_form(OUTPUT, {"alias": ALIAS})
    assert r.status == 200, r.raw_text
    assert r.body["result"]["alias"] == ALIAS


def test_device_by_alias(http):
    http.post_form(OUTPUT, {"alias": ALIAS})
    for path in (f"/rest/do/{ALIAS}/", f"/json/do/{ALIAS}/", f"/rest/output/{ALIAS}/"):
        r = http.get(path)
        assert r.status == 200, f"{path}: {r.raw_text}"
        assert r.body["circuit"] == "1_03"
    # the alias of a DO is not an alias of another type
    assert http.get(f"/rest/ro/{ALIAS}/").status == 404


def test_list_of_aliases(http):
    http.post_form(OUTPUT, {"alias": ALIAS})
    r = http.get("/rest/run/alias/")
    assert r.status == 200, r.raw_text
    assert r.body["dev"] == "run"
    assert r.body["aliases"][ALIAS] == {"circuit": "do_1_03", "devtype": "do"}


@pytest.mark.parametrize(
    "alias",
    [
        "bad alias",  # a space
        "all",  # addresses all devices of the type
        "1_04",  # a circuit of a device of the same type
        "a" * 65,  # longer than 64 characters
    ],
)
def test_invalid_alias_is_400(http, alias):
    r = http.post_form(OUTPUT, {"alias": alias})
    assert r.status == 400, r.raw_text
    assert "alias" not in http.get(OUTPUT).body


def test_duplicate_alias_is_400(http):
    http.post_form(OUTPUT, {"alias": ALIAS})
    r = http.post_form("/rest/do/1_04/", {"alias": ALIAS})
    assert r.status == 400, r.raw_text
    assert http.get(OUTPUT).body["alias"] == ALIAS


def test_remove_alias(http):
    http.post_form(OUTPUT, {"alias": ALIAS})
    r = http.post_form(OUTPUT, {"alias": ""})
    assert r.status == 200, r.raw_text
    assert "alias" not in r.body["result"]
    assert http.get(f"/rest/do/{ALIAS}/").status == 404


def test_delete_alias_by_name(http):
    http.post_form(OUTPUT, {"alias": ALIAS})
    r = http.post_form("/rest/run/alias/", {"delete": ALIAS})
    assert r.status == 200, r.raw_text
    assert ALIAS not in r.body["result"]["aliases"]
    assert "alias" not in http.get(OUTPUT).body
