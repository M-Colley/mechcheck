"""BibTeX parsing, the YAML subset, configuration precedence, venue packs.

The venue tests deliberately assert *structure*, never specific page limits:
limits change every cycle, and a test that pins one would start failing for the
right reason at the worst time. What must not break is the shape of a pack and
the honesty of its metadata.
"""

from __future__ import annotations

import os

import pytest

import mechcheck.rules  # noqa: F401
from mechcheck import bibtex, minyaml
from mechcheck.config import Config, PROFILES, available_venues, load_venue
from mechcheck.model import REGISTRY, Severity

BS = chr(92)


# --------------------------------------------------------------------------- #
# bibtex
# --------------------------------------------------------------------------- #

SAMPLE = """
@inproceedings{key1,
  author = {Colley, Mark and Rukzio, Enrico},
  title = {A Design Space for {External} Communication},
  booktitle = {Proceedings of AutomotiveUI},
  year = {2020},
  doi = {10.1145/3409120.3410646},
  pages = {101-110}
}

@article{key2,
  author = "Doe, Jane",
  title = "Another Work",
  journal = "Journal of Tests",
  year = 2023,
  url = {https://doi.org/10.1000/xyz}
}
"""


def test_parses_entries_with_both_delimiter_styles():
    entries = bibtex.parse(SAMPLE, "refs.bib")
    assert [e.key for e in entries] == ["key1", "key2"]
    assert entries[1].get("author") == "Doe, Jane"


def test_records_line_numbers_for_entries_and_fields():
    entries = bibtex.parse(SAMPLE, "refs.bib")
    assert entries[0].line == 2
    assert entries[0].line_of("pages") > entries[0].line


def test_extracts_doi_from_a_url_when_the_field_is_absent():
    entries = bibtex.parse(SAMPLE, "refs.bib")
    assert entries[1].doi == "10.1000/xyz"


def test_author_surnames_and_year():
    entry = bibtex.parse(SAMPLE, "refs.bib")[0]
    assert entry.author_surnames() == ["Colley", "Rukzio"]
    assert entry.year == 2020


def test_braces_are_stripped_for_comparison_but_kept_in_the_raw_field():
    entry = bibtex.parse(SAMPLE, "refs.bib")[0]
    assert "{External}" in entry.get("title")
    assert entry.title == "A Design Space for External Communication"


def test_similarity_is_tolerant_of_subtitles_but_not_of_different_works():
    assert bibtex.similarity("A Design Space for External Communication",
                             "A Design Space for External Communication of Vehicles") > 0.7
    assert bibtex.similarity("A Design Space for External Communication",
                             "Knitting Patterns of the Nineteenth Century") < 0.4


def test_malformed_entry_does_not_raise():
    broken = "@article{oops, author = {No closing brace"
    assert isinstance(bibtex.parse(broken, "x.bib"), list)


def test_preprint_detection():
    arxiv = "@article{a, title={T}, journal={arXiv preprint arXiv:2301.00001}, year={2023}}"
    entry = bibtex.parse(arxiv, "x.bib")[0]
    assert entry.is_preprint()
    assert entry.arxiv_id == "2301.00001"


# --------------------------------------------------------------------------- #
# the YAML subset
# --------------------------------------------------------------------------- #

YAML_SAMPLE = """
# a comment
profile: thesis
stage: submission
count: 42
enabled: true
missing: null
disable:
  - VEN*
  - ANON*
rules:
  ABB004:
    ignore:
      - HMI
      - ADAS
  STY012:
    max_words: 45
flow: [a, b, c]
severity: {}
pairs: {STR005: info, FIG003: warn}
"""


@pytest.mark.parametrize("parse", [minyaml.loads_builtin, minyaml.loads])
def test_yaml_subset_round_trips_through_both_parsers(parse):
    data = parse(YAML_SAMPLE)
    assert data["profile"] == "thesis"
    assert data["count"] == 42
    assert data["enabled"] is True
    assert data["missing"] is None
    assert data["disable"] == ["VEN*", "ANON*"]
    assert data["rules"]["ABB004"]["ignore"] == ["HMI", "ADAS"]
    assert data["rules"]["STY012"]["max_words"] == 45
    assert data["flow"] == ["a", "b", "c"]
    assert data["severity"] == {}
    assert data["pairs"] == {"STR005": "info", "FIG003": "warn"}


# The default config that `mechcheck init` writes contains "severity: {}".
# Read back as the string "{}", that made severity_for() raise on .items() --
# so on a machine without PyYAML, which is what `pip install mechcheck` gives
# you, every rule that actually found something crashed instead of reporting.

def test_the_config_that_init_writes_parses_the_same_without_pyyaml():
    from mechcheck.scaffold import CONFIG_TEMPLATE
    text = CONFIG_TEMPLATE.format(profile="thesis", venue_line="venue: null")
    builtin, best = minyaml.loads_builtin(text), minyaml.loads(text)
    assert isinstance(builtin["severity"], dict)
    for key in ("profile", "stage", "severity", "disable", "enable", "rules"):
        assert builtin[key] == best[key], key


def test_a_config_of_the_wrong_shape_cannot_crash_a_rule(tmp_path):
    # Every one of these is the wrong type for its key.
    (tmp_path / "mechcheck.yaml").write_text(
        "\n".join(["severity: '{}'", "rules: nonsense", "disable: ACC006", "enable: ''"]),
        encoding="utf-8", newline="\n")
    cfg = Config.load(str(tmp_path))
    assert cfg.severity_for("STR005") is not None      # used to raise
    assert cfg.rule_option("ABB004", "ignore", []) == []
    assert cfg.enabled("ACC006") is False              # the scalar was meant as a list
    assert cfg.enabled("STR005") is True


def test_builtin_parser_survives_malformed_input():
    assert isinstance(minyaml.loads_builtin("::::\n  - \n\t\tbad"), dict)


def test_dumps_produces_something_the_parser_reads_back():
    original = {"profile": "paper", "disable": ["A*", "B*"], "rules": {"X": {"n": 3}}}
    text = minyaml.dumps(original)
    assert minyaml.loads_builtin(text) == original


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #

def test_cli_overrides_beat_the_config_file(tmp_path):
    (tmp_path / "mechcheck.yaml").write_text("profile: thesis\nstage: draft\n", encoding="utf-8")
    config = Config.load(str(tmp_path), overrides={"stage": "final"})
    assert config.profile == "thesis"
    assert config.stage == "final"


def test_severity_override_by_exact_id_and_by_glob(tmp_path):
    (tmp_path / "mechcheck.yaml").write_text(
        "severity:\n  FIG003: error\n  'STY*': info\n", encoding="utf-8")
    config = Config.load(str(tmp_path))
    assert config.severity_for("FIG003") is Severity.ERROR
    assert config.severity_for("STY003") is Severity.INFO


def test_disable_patterns(tmp_path):
    (tmp_path / "mechcheck.yaml").write_text("disable:\n  - 'BIO*'\n", encoding="utf-8")
    config = Config.load(str(tmp_path))
    assert not config.enabled("BIO001")
    assert config.enabled("FIG001")


def test_venue_pack_supplies_rule_defaults(tmp_path):
    config = Config.load(str(tmp_path), overrides={"venue": "autoui"})
    assert config.rule_option("MET002", "max_pages") == 13


def test_project_config_beats_the_venue_pack(tmp_path):
    (tmp_path / "mechcheck.yaml").write_text(
        "venue: autoui\nrules:\n  MET002:\n    max_pages: 12\n", encoding="utf-8")
    config = Config.load(str(tmp_path))
    assert config.rule_option("MET002", "max_pages") == 12


def test_unknown_venue_degrades_to_no_pack(tmp_path):
    config = Config.load(str(tmp_path), overrides={"venue": "not-a-venue"})
    assert config.venue_data == {}
    assert config.venue_field("length", "max_pages") is None


# --------------------------------------------------------------------------- #
# venue packs
# --------------------------------------------------------------------------- #

def test_the_expected_venues_ship():
    assert set(available_venues()) >= {"chi", "assets", "autoui", "imwut", "trf"}


@pytest.mark.parametrize("venue", available_venues())
def test_every_venue_pack_is_honest_about_its_provenance(venue):
    """A pack that cannot say when it was checked cannot be trusted with a deadline."""
    pack = load_venue(venue)
    assert pack.get("name"), f"{venue}: no name"
    assert pack.get("verified"), f"{venue}: no verified date"
    assert str(pack.get("source_url", "")).startswith("http"), f"{venue}: no source URL"


@pytest.mark.parametrize("venue", available_venues())
def test_every_venue_pack_parses_with_the_restricted_parser(venue):
    """The packs must stay inside the subset that every reader can handle."""
    path = os.path.join(os.path.dirname(load_venue.__module__ and ""), "")
    from mechcheck.config import VENUE_DIR

    raw = open(os.path.join(VENUE_DIR, venue + ".yaml"), encoding="utf-8").read()
    data = minyaml.loads_builtin(raw)
    assert data.get("name")
    assert isinstance(data.get("required_commands", []), list)


@pytest.mark.parametrize("venue", available_venues())
def test_venue_severity_overrides_name_real_rules(venue):
    pack = load_venue(venue)
    for rule_id in (pack.get("severity") or {}):
        assert REGISTRY.get(rule_id) is not None, f"{venue}: unknown rule {rule_id}"


@pytest.mark.parametrize("venue", available_venues())
def test_venue_rule_options_name_real_rules(venue):
    pack = load_venue(venue)
    for rule_id in (pack.get("rules") or {}):
        assert REGISTRY.get(rule_id) is not None, f"{venue}: unknown rule {rule_id}"


def test_profiles_are_all_usable():
    for name, spec in PROFILES.items():
        assert spec.get("description"), f"profile {name} has no description"
