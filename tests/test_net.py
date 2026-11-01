"""The network layer: "not found" and "could not check" are different answers.

A proxy, a timeout or a 5xx says nothing about a reference, so none of them
may become "DOI does not resolve" -- an error-level finding that reads as an
accusation. Only a 404/410 from the registry itself is an answer.
"""

from __future__ import annotations

import http.client
import io
import urllib.error

import mechcheck.rules  # noqa: F401
from mechcheck import net
from mechcheck.config import Config
from mechcheck.runner import run

BS = chr(92)
NL = chr(10)


def project(tmp_path) -> str:
    (tmp_path / "main.tex").write_text(
        BS + "documentclass{article}" + NL + BS + "begin{document}" + NL
        + "Cited" + BS + "cite{k1}." + NL + BS + "bibliography{refs}" + NL
        + BS + "end{document}" + NL, encoding="utf-8")
    (tmp_path / "refs.bib").write_text(
        "@article{k1," + NL + "  title = {A Real Paper}," + NL + "  author = {Doe, Jane}," + NL
        + "  journal = {J}," + NL + "  year = {2020}," + NL + "  doi = {10.1145/1234567.1234568}," + NL
        + "}" + NL, encoding="utf-8")
    return str(tmp_path)


def bio001(root: str, tmp_path, monkeypatch, urlopen) -> list:
    monkeypatch.setenv("MECHCHECK_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(net.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    config = Config.load(root, overrides={"max_per_rule": 0})
    result = run(root, config, only=["BIO001"], offline=False, baseline=None)
    return [f for f in result.findings if f.rule == "BIO001"]


def test_an_outage_is_not_a_missing_doi(tmp_path, monkeypatch):
    def refused(req, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError("proxy refused"))
    assert bio001(project(tmp_path), tmp_path, monkeypatch, refused) == []


def test_a_server_error_is_not_a_missing_doi(tmp_path, monkeypatch):
    def unavailable(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, io.BytesIO(b""))
    assert bio001(project(tmp_path), tmp_path, monkeypatch, unavailable) == []


def test_a_404_from_both_registries_is_reported(tmp_path, monkeypatch):
    def missing(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, io.BytesIO(b""))
    assert len(bio001(project(tmp_path), tmp_path, monkeypatch, missing)) == 1


def test_a_host_that_keeps_failing_is_left_alone(tmp_path, monkeypatch):
    calls = []

    def refused(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.URLError(ConnectionRefusedError("down"))

    monkeypatch.setattr(net.urllib.request, "urlopen", refused)
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    fetcher = net.Fetcher(cache_dir=str(tmp_path / "cache"))
    for i in range(10):
        assert fetcher.get_json(f"https://api.example.org/works/{i}") is None
    assert len(calls) == net.MAX_HOST_FAILURES


def test_a_url_that_is_not_a_url_does_not_raise(tmp_path, monkeypatch):
    def invalid(req, timeout=None):
        raise http.client.InvalidURL("URL can't contain control characters")
    monkeypatch.setattr(net.urllib.request, "urlopen", invalid)
    fetcher = net.Fetcher(cache_dir=str(tmp_path / "cache"))
    assert fetcher.url_status("https://osf.io/study" + NL + " data.zip") is None
    assert fetcher.url_status("http://[::1/x") is None
