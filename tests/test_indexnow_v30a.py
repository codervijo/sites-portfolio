"""v30.A — `[index]` table + IndexNow key provisioning + CHECK_153."""
from __future__ import annotations

import pytest

from portfolio import indexnow, lamill_toml
from portfolio.checks.deploy import check_153_indexnow_key_present as chk
from portfolio.lamill_toml import LAMILL_TOML_FILENAME

_BASE = 'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n'


def _site(tmp_path, *, index="", pkg=True):
    text = _BASE + (("\n" + index) if index else "")
    (tmp_path / LAMILL_TOML_FILENAME).write_text(text)
    if pkg:
        (tmp_path / "package.json").write_text('{"name":"x"}')
    return tmp_path


# ---- [index] parsing (additive-optional) ----


def test_index_absent_is_none(tmp_path):
    _site(tmp_path)
    assert lamill_toml.load(tmp_path).index is None


def test_index_parsed(tmp_path):
    _site(tmp_path, index='[index]\nindexnow_key = "abc123"\nindexnow_enabled = true\n')
    idx = lamill_toml.load(tmp_path).index
    assert idx.indexnow_key == "abc123"
    assert idx.indexnow_enabled is True


def test_index_enabled_defaults_true(tmp_path):
    _site(tmp_path, index='[index]\nindexnow_key = "abc"\n')
    assert lamill_toml.load(tmp_path).index.indexnow_enabled is True


def test_index_disabled(tmp_path):
    _site(tmp_path, index="[index]\nindexnow_enabled = false\n")
    idx = lamill_toml.load(tmp_path).index
    assert idx.indexnow_enabled is False
    assert idx.indexnow_key is None


def test_index_bad_key_type_raises(tmp_path):
    _site(tmp_path, index="[index]\nindexnow_key = 123\n")
    with pytest.raises(lamill_toml.ParseError):
        lamill_toml.load(tmp_path)


def test_minimal_lamill_toml_still_loads(tmp_path):
    # additive-optional invariant: schema + [deploy] only, no [index]/[stack]
    (tmp_path / LAMILL_TOML_FILENAME).write_text(_BASE)
    doc = lamill_toml.load(tmp_path)
    assert doc.index is None and doc.stack is None


# ---- indexnow provisioning ----


def test_generate_key_format():
    k = indexnow.generate_key()
    assert len(k) == 32 and all(c in "0123456789abcdef" for c in k)


def test_provision_writes_key_file_and_table(tmp_path):
    _site(tmp_path)
    key, written = indexnow.provision(tmp_path)
    assert (tmp_path / "public" / f"{key}.txt").read_text().strip() == key
    assert lamill_toml.load(tmp_path).index.indexnow_key == key
    assert indexnow.is_provisioned(tmp_path)
    assert len(written) == 2  # key file + lamill.toml


def test_provision_idempotent(tmp_path):
    _site(tmp_path)
    key1, _ = indexnow.provision(tmp_path)
    key2, written2 = indexnow.provision(tmp_path)
    assert key1 == key2
    assert written2 == []  # nothing re-written on a provisioned site


def test_is_provisioned_false_when_keyfile_missing(tmp_path):
    # key recorded in [index] but public/<key>.txt absent → not provisioned
    _site(tmp_path, index='[index]\nindexnow_key = "deadbeef"\n')
    assert indexnow.is_provisioned(tmp_path) is False


# ---- CHECK_153 + fixer ----


def test_check_warns_when_unprovisioned(tmp_path):
    _site(tmp_path)
    assert chk.run(str(tmp_path)).status == "warn"


def test_check_passes_after_provision(tmp_path):
    _site(tmp_path)
    indexnow.provision(tmp_path)
    assert chk.run(str(tmp_path)).status == "pass"


def test_check_passes_when_disabled(tmp_path):
    _site(tmp_path, index="[index]\nindexnow_enabled = false\n")
    assert chk.run(str(tmp_path)).status == "pass"


def test_check_passes_non_web(tmp_path):
    _site(tmp_path, pkg=False)
    assert chk.run(str(tmp_path)).status == "pass"


def test_fix_dry_run_writes_nothing(tmp_path):
    _site(tmp_path)
    res = chk.fix_tier_1.apply(tmp_path, True, False)
    assert res.status == "would-fix"
    assert not (tmp_path / "public").exists()


def test_fix_provisions(tmp_path):
    _site(tmp_path)
    res = chk.fix_tier_1.apply(tmp_path, False, False)
    assert res.status == "fixed"
    assert indexnow.is_provisioned(tmp_path)
    assert chk.run(str(tmp_path)).status == "pass"


def test_fix_nothing_to_do_when_provisioned(tmp_path):
    _site(tmp_path)
    indexnow.provision(tmp_path)
    res = chk.fix_tier_1.apply(tmp_path, False, False)
    assert res.status == "nothing-to-do"
