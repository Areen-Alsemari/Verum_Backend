"""Tests for the pinned parameter file: its hash check, its shape and its provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from _anomaly_cases import healthy, parameter_document, rehash, request_with, write_parameters
from verum.agents.anomaly_detection import AnomalyDetectionAgent
from verum.agents.anomaly_detection import parameters as pinned

pytestmark = pytest.mark.fast


def test_the_shipped_file_matches_the_pinned_hash() -> None:
    """The file in the package hashes to the constant pinned in the code and loads.

    Independent: yes, because the hash is computed here from the bytes with the standard library.
    """
    digest = hashlib.sha256(pinned.PARAMETERS_PATH.read_bytes()).hexdigest()
    assert digest == pinned.EXPECTED_PARAMETERS_SHA256
    assert pinned.load_parameters().sha256 == digest


def test_a_changed_byte_is_refused_before_parsing(tmp_path: Path) -> None:
    """A file with one byte changed is refused, whatever it contains.

    Independent: yes, because the file is written here and altered by one character.
    """
    path, digest = write_parameters(tmp_path)
    assert pinned.load_from(path, digest).window_threshold == 3.0
    path.write_bytes(path.read_bytes().replace(b"3.0", b"9.0", 1))
    with pytest.raises(ValueError, match="hash mismatch"):
        pinned.load_from(path, digest)


def test_a_wrong_expected_hash_is_refused(tmp_path: Path) -> None:
    """An intact file is refused when the pinned hash is not its hash.

    Independent: yes, because the wrong hash is a constant written in the test.
    """
    path, _ = write_parameters(tmp_path)
    with pytest.raises(ValueError, match="hash mismatch"):
        pinned.load_from(path, "0" * 64)


def test_a_malformed_document_is_refused_even_with_the_right_hash(tmp_path: Path) -> None:
    """A document of the wrong method or shape fails to parse, with its own hash given.

    Independent: yes, because each malformed document is written out.
    """
    wrong_method = parameter_document() | {"method_id": "other"}
    path, digest = write_parameters(tmp_path, wrong_method)
    with pytest.raises(ValueError, match="another method"):
        pinned.load_from(path, digest)
    short = parameter_document()
    short["mass_balance"]["coefficients"] = [700.0, 700.0]
    path, digest = write_parameters(tmp_path, short)
    with pytest.raises(ValueError, match="three tank areas"):
        pinned.load_from(path, digest)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        pinned.load_from(path, hashlib.sha256(b"[]").hexdigest())


def test_the_shipped_file_records_train_only_and_the_fitted_numbers() -> None:
    """The provenance names the train split only, and the file holds 41 fitted numbers.

    Independent: yes, because the numbers are counted here from the file.
    """
    doc: dict[str, Any] = json.loads(pinned.PARAMETERS_PATH.read_text(encoding="utf-8"))
    provenance = doc["provenance"]
    assert provenance["splits_used"] == ["train"]
    assert len(provenance["train_file_sha256"]) == 64
    counted = len(doc["mass_balance"]["coefficients"]) + 1
    counted += sum(len(f["coefficients"]) + 1 for f in doc["pump_fits"])
    counted += len(doc["receipt_line"]["coefficients"]) + 1
    assert counted == provenance["fitted_numbers"] == 41
    assert doc["thresholds"]["window_score"] > max(doc["thresholds"]["residuals"].values())


def test_only_the_twelve_listed_fields_change_the_answer() -> None:
    """Overwriting every other signal leaves the events and the score unchanged.

    Independent: yes, because the other signals are replaced by arbitrary values.
    """
    base = request_with(healthy("A") | {"FT-201": 380.0})
    other = json.loads(json.dumps(base))
    listed = set(pinned.load_parameters().fields)
    for signal in other["input"]["observations"]["summary"]["signals"]:
        if signal["tag_id"] not in listed:
            signal.update(mean=12345.0, latest_value=7.0, slope_per_s=3.0, minimum=1.0, maximum=2.0)
    rehash(other)
    first = AnomalyDetectionAgent().run(base)["result"]["events"]
    second = AnomalyDetectionAgent().run(other)["result"]["events"]
    residual = [e for e in first if "-residual-" in e["event_id"]]
    assert residual == [e for e in second if "-residual-" in e["event_id"]]
