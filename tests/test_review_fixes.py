"""Defects found in the October 2026 review, each pinned where it was found.

Every case reproduced a wrong answer before its fix: a chapter counted after
\\end{document}, a one-line verbatim that hid the rest of the file, a figure
chosen as the main document, a severity the configuration could not switch
off, an option-less run that passed by checking nothing.
"""

from __future__ import annotations

import json
import os

import pytest

import mechcheck.rules  # noqa: F401
from mechcheck import report as reporters
from mechcheck.cli import EXIT_USAGE, main
from mechcheck.config import Config
from mechcheck.model import Finding, Severity
from mechcheck.runner import RunResult, run, write_baseline
from mechcheck.texsource import TexProject, find_main_document

BS = chr(92)
NL = chr(10)


def write(tmp_path, name: str, text: str) -> None:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=NL)


def doc(body: str, cls: str = "article", options: str = "") -> str:
    head = BS + "documentclass" + (f"[{options}]" if options else "") + "{" + cls + "}"
    return head + NL + BS + "begin{document}" + NL + body + NL + BS + "end{document}" + NL


def check(root, only=None, **overrides):
    config = Config.load(str(root), overrides={"max_per_rule": 0, **overrides})
    return run(str(root), config, only=only, offline=True, baseline=None)


# --------------------------------------------------------------------------- #
# the reader
# --------------------------------------------------------------------------- #

def test_an_input_file_is_read_where_it_is_input(tmp_path):
    write(tmp_path, "main.tex", doc(BS + "input{chapters/intro}" + NL + "Closing words."))
    write(tmp_path, "chapters/intro.tex", "Opening words of the chapter.")
    project = TexProject.load(str(tmp_path))
    text = project.text
    assert text.index("Opening words") < text.index("Closing words") < text.index(BS + "end{document}")


def test_the_word_limit_counts_input_chapters(tmp_path):
    write(tmp_path, "main.tex", doc(BS + "input{chapters/intro}"))
    write(tmp_path, "chapters/intro.tex", " ".join(["word"] * 300))
    result = check(tmp_path, only=["MET001"], rules={"MET001": {"max_words": 100}})
    assert [f.rule for f in result.findings] == ["MET001"]


def test_a_verbatim_closed_on_its_own_line_hides_nothing_after_it(tmp_path):
    body = ("Run " + BS + "begin{verbatim}make" + BS + "end{verbatim} first." + NL
            + "Then read " + BS + "label{sec:later}the rest.")
    write(tmp_path, "main.tex", doc(body))
    project = TexProject.load(str(tmp_path))
    assert [c.arg(0) for c in project.commands("label")] == ["sec:later"]
    assert project.environments("document")


def test_a_verbatim_opened_after_another_begin_is_still_verbatim(tmp_path):
    body = (BS + "begin{figure}" + BS + "begin{lstlisting}" + NL + BS + "label{fig:inside}" + NL
            + BS + "end{lstlisting}" + BS + "end{figure}")
    write(tmp_path, "main.tex", doc(body))
    assert not TexProject.load(str(tmp_path)).commands("label")


def test_a_comment_after_end_verbatim_is_a_comment(tmp_path):
    body = (BS + "begin{verbatim}" + NL + "x" + NL + BS + "end{verbatim} % " + BS + "label{gone}")
    write(tmp_path, "main.tex", doc(body))
    assert not TexProject.load(str(tmp_path)).commands("label")


def test_a_standalone_figure_is_not_the_main_document(tmp_path):
    write(tmp_path, "paper.tex", doc("The paper."))
    write(tmp_path, "figures/main.tex", doc("A figure.", cls="standalone"))
    assert find_main_document(str(tmp_path)) == "paper.tex"


def test_ccs_xml_is_not_prose(tmp_path):
    ccs = (BS + "begin{CCSXML}" + NL + "<concept_desc>Human-centered computing~Human computer "
           "interaction (HCI)</concept_desc>" + NL + BS + "end{CCSXML}" + NL)
    body = ccs + "Research in Human-Computer Interaction (HCI) is broad. HCI matters."
    write(tmp_path, "main.tex", doc(body, cls="acmart", options="manuscript"))
    result = check(tmp_path, only=["ABB001", "ABB005", "STY008", "POL008"])
    assert not {f.rule for f in result.findings} & {"ABB001", "ABB005", "STY008", "POL008"}


def test_an_input_on_another_drive_does_not_crash(tmp_path, monkeypatch):
    write(tmp_path, "main.tex", doc(BS + "input{chap}"))
    write(tmp_path, "chap.tex", "Chapter text.")

    def other_drive(path, start=None):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")
    monkeypatch.setattr(os.path, "relpath", other_drive)
    project = TexProject.load(str(tmp_path), "main.tex")
    assert "Chapter text." in project.text


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #

def test_severity_off_switches_a_rule_off(tmp_path):
    write(tmp_path, "main.tex", doc("This is the the result."))
    result = check(tmp_path, severity={"STY003": "off"})
    assert "STY003" not in {f.rule for f in result.findings}
    reporters.render_text(result)          # used to raise KeyError on Severity.NEVER


def test_fail_on_off_read_as_false_means_never():
    assert Severity.parse(False, Severity.ERROR) is Severity.NEVER


def test_a_draft_blocks_nothing_even_for_a_rule_made_an_error(tmp_path):
    write(tmp_path, "main.tex", doc("This is the the result."))
    result = check(tmp_path, only=["STY003"], stage="draft", severity={"STY003": "error"})
    assert result.findings and all(f.severity is Severity.INFO for f in result.findings)


def test_the_final_stage_still_promotes_a_rule_set_to_warn(tmp_path):
    write(tmp_path, "main.tex", doc("This is the the result."))
    result = check(tmp_path, only=["STY003"], stage="final", severity={"STY003": "warn"})
    assert all(f.severity is Severity.ERROR for f in result.findings)


def test_the_baseline_freezes_findings_the_cap_held_back(tmp_path):
    write(tmp_path, "main.tex", doc(NL.join("Line " + str(i) + " has the the slip." for i in range(25))))
    config = Config.load(str(tmp_path), overrides={"max_per_rule": 10})
    result = run(str(tmp_path), config, only=["STY003"], offline=True, baseline=None)
    assert write_baseline(str(tmp_path / ".mechcheck-baseline.json"), result) == 25
    again = run(str(tmp_path), config, only=["STY003"], offline=True,
                baseline=str(tmp_path / ".mechcheck-baseline.json"))
    assert not again.findings and not again.truncated


# --------------------------------------------------------------------------- #
# the command line and its output
# --------------------------------------------------------------------------- #

def test_an_unknown_only_rule_is_a_usage_error(tmp_path, capsys):
    write(tmp_path, "main.tex", doc("Text."))
    assert main(["check", str(tmp_path), "--offline", "--only", "NOPE123"]) == EXIT_USAGE
    assert "NOPE123" in capsys.readouterr().err


def test_a_missing_main_document_is_a_usage_error(tmp_path, capsys):
    write(tmp_path, "main.tex", doc("Text."))
    assert main(["check", str(tmp_path), "--offline", "--main", "typo.tex"]) == EXIT_USAGE


def test_json_with_skipped_rules_stays_json(tmp_path, capsys):
    write(tmp_path, "main.tex", doc("Text."))
    main(["check", str(tmp_path), "--offline", "-f", "json", "--show-skipped",
          "--fail-on", "never", "--no-baseline"])
    json.loads(capsys.readouterr().out)


def _Result(finding):
    return RunResult(findings=[finding])


@pytest.mark.parametrize("name", ["intro, v2:final.tex"])
def test_a_github_annotation_escapes_the_file_name(name):
    out = reporters.render_github(_Result(Finding(rule="STY003", message="m", severity=Severity.WARN,
                                                  file=name, line=3)))
    props = out.split("::")[1]
    assert "intro%2C v2%3Afinal.tex" in props


def test_a_markdown_row_survives_a_newline_in_a_message():
    out = reporters.render_markdown(_Result(Finding(rule="STY003", message="one" + NL + "two",
                                                    severity=Severity.WARN, file="a.tex", line=1)))
    assert any(line.startswith("|") and "one two" in line for line in out.splitlines())


def test_a_sarif_uri_is_percent_encoded():
    out = reporters.render_sarif(_Result(Finding(rule="STY003", message="m", severity=Severity.WARN,
                                                 file="my chapter#1.tex", line=1)))
    uri = json.loads(out)["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri == "my%20chapter%231.tex"


# --------------------------------------------------------------------------- #
# rules: false positives at error level, and edits that changed correct text
# --------------------------------------------------------------------------- #

CHI = "manuscript,review,anonymous"


def fired(result) -> set:
    return {f.rule for f in result.findings}


def of(result, rule_id: str) -> list:
    return [f for f in result.findings if f.rule == rule_id]


@pytest.mark.parametrize("body", [
    "We rewrite each query before execution.",
    "Attackers hack the device in minutes.",
    "The buffer starts empty, " + BS + "texttt{buf = []}, and grows.",
    BS + "mintinline{python}{xs = []} is idiomatic.",
])
def test_ordinary_words_and_inline_code_are_not_unfinished_work(tmp_path, body):
    write(tmp_path, "main.tex", doc(body))
    assert "STY001" not in fired(check(tmp_path, only=["STY001"]))


def test_a_todo_inside_a_code_listing_is_a_note_not_an_error(tmp_path):
    write(tmp_path, "main.tex", doc(BS + "begin{lstlisting}" + NL + "# TODO: handle errors" + NL
                                   + BS + "end{lstlisting}"))
    hits = of(check(tmp_path, only=["STY001"]), "STY001")
    assert hits and all(f.severity is Severity.INFO for f in hits)


def test_a_lower_case_note_with_a_colon_is_still_a_marker(tmp_path):
    write(tmp_path, "main.tex", doc("todo: write the discussion."))
    assert "STY001" in fired(check(tmp_path, only=["STY001"]))


def test_a_todonotes_command_is_a_marker(tmp_path):
    write(tmp_path, "main.tex", doc("Results " + BS + "todo{better connect the two studies} follow."))
    assert "STY001" in fired(check(tmp_path, only=["STY001"]))


def test_one_marker_is_one_finding(tmp_path):
    write(tmp_path, "main.tex", doc("Text. % TODO: fill in the venue once announced."))
    assert len(of(check(tmp_path, only=["STY001"]), "STY001")) == 1


def test_a_subfigure_label_is_not_the_figure_label(tmp_path):
    body = (BS + "begin{figure}" + NL + BS + "begin{subfigure}{.4" + BS + "linewidth}" + NL
            + BS + "subcaption{Left}" + BS + "label{fig:a}" + NL + BS + "end{subfigure}" + NL
            + BS + "caption{Both panels.}" + BS + "label{fig:main}" + NL + BS + "end{figure}" + NL
            + "See Figure~" + BS + "ref{fig:main}.")
    write(tmp_path, "main.tex", doc(body))
    assert not fired(check(tmp_path, only=["FIG003", "FIG004"]))


def test_a_listing_label_given_as_an_option_is_defined(tmp_path):
    body = (BS + "begin{lstlisting}[caption={Code},label={lst:code}]" + NL + "x = 1" + NL
            + BS + "end{lstlisting}" + NL + "See Listing~" + BS + "ref{lst:code}.")
    write(tmp_path, "main.tex", doc(body))
    assert "REF001" not in fired(check(tmp_path, only=["REF001"]))


def test_nocite_star_names_no_key(tmp_path):
    write(tmp_path, "main.tex", doc("Text" + BS + "cite{a}. " + BS + "nocite{*}" + NL + BS + "bibliography{refs}"))
    write(tmp_path, "refs.bib", "@misc{a,\n  title = {T},\n  year = {2020},\n}\n")
    assert "REF005" not in fired(check(tmp_path, only=["REF005"]))


def test_acmart_key_value_options_are_understood(tmp_path):
    body = BS + "author{Jane Doe}" + NL + "Text."
    write(tmp_path, "main.tex", doc(body, cls="acmart", options="format=manuscript,review=true,anonymous=true"))
    assert not fired(check(tmp_path, only=["VEN002", "ANON001"]))


def test_anonymity_rules_stay_out_of_a_camera_ready_paper(tmp_path):
    body = (BS + "author{Jane Doe}" + NL + "Code: " + BS + "url{https://github.com/janedoe/tool}." + NL
            + BS + "begin{acks}We thank the DFG.\\end{acks}".replace("\\end", BS + "end"))
    write(tmp_path, "main.tex", doc(body, cls="acmart", options="sigconf"))
    result = check(tmp_path, profile="camera-ready")
    assert not {"ANON001", "ANON002", "ANON003", "ANON004"} & fired(result)


def test_single_anonymous_review_names_its_authors(tmp_path):
    write(tmp_path, "main.tex", doc(BS + "author{Jane Doe}" + NL + "Text.", cls="elsarticle"))
    assert "ANON001" not in fired(check(tmp_path, only=["ANON001"], venue="trf"))


def test_build_artefacts_are_not_upload_file_names(tmp_path):
    write(tmp_path, "main.tex", doc("Text.", cls="acmart", options=CHI))
    write(tmp_path, "main.synctex.gz", "x")
    write(tmp_path, "main.run.xml", "x")
    assert "VEN006" not in fired(check(tmp_path, only=["VEN006"]))


def test_plural_and_abbreviated_words_are_not_autoref_cases(tmp_path):
    preamble_doc = (BS + "documentclass{article}" + NL + BS + "usepackage{hyperref}" + NL + BS
                    + "begin{document}" + NL + "Figures~" + BS + "ref{fig:a} and~" + BS + "ref{fig:b} show it. Fig.~"
                    + BS + "ref{fig:a} again." + NL + BS + "end{document}" + NL)
    write(tmp_path, "main.tex", preamble_doc)
    assert "REF008" not in fired(check(tmp_path, only=["REF008"]))


def test_autoref_is_not_advised_without_hyperref(tmp_path):
    write(tmp_path, "main.tex", doc("As shown in Figure~" + BS + "ref{fig:a}."))
    assert "REF008" not in fired(check(tmp_path, only=["REF008"]))


@pytest.mark.parametrize("body", [
    "Die Personen, die die Aufgabe gelöst haben, wurden befragt.",
    BS + "paragraph{Latency} Latency was measured per trial.",
])
def test_grammatical_and_heading_doubles_are_not_repeated_words(tmp_path, body):
    write(tmp_path, "main.tex", doc(body))
    assert "STY003" not in fired(check(tmp_path, only=["STY003"]))


def test_a_time_range_is_not_a_numeric_range(tmp_path):
    write(tmp_path, "main.tex", doc("Sessions ran 10:00-12:00 each day."))
    assert "STY007" not in fired(check(tmp_path, only=["STY007"]))


def test_a_range_keeps_its_digits_as_typed(tmp_path):
    write(tmp_path, "main.tex", doc("Weeks 05-09 were quiet."))
    hits = of(check(tmp_path, only=["STY007"]), "STY007")
    assert hits and hits[0].edit.replacement == "05--09"


def test_the_body_may_introduce_again_what_the_abstract_introduced(tmp_path):
    body = (BS + "begin{abstract}" + NL + "An Automated Driving System (ADS) is studied." + NL + BS + "end{abstract}"
            + NL + "The Automated Driving System (ADS) drives. The ADS stops.")
    write(tmp_path, "main.tex", doc(body))
    assert "ABB001" not in fired(check(tmp_path, only=["ABB001"]))


def test_a_repeated_word_across_markup_is_reported_but_not_rewritten(tmp_path):
    write(tmp_path, "main.tex", doc("This is the " + BS + "emph{the} result."))
    hits = of(check(tmp_path, only=["STY003"]), "STY003")
    assert hits and all(f.edit is None for f in hits)


@pytest.mark.parametrize("body", [
    "We found $t(100) = 4.50$, $p = 1.8 " + BS + "times 10^{-5}$, as expected.",
    "We found t(100) = 4.50, p = 7.6e-7, as expected.",
    "$F(1, 20) = 5.00$, $" + BS + "eta^2_p = .20$, $p = .037$.",
    "We use the $L_p$ distance with $p = 2$ throughout.",
])
def test_p_values_are_read_as_written(tmp_path, body):
    write(tmp_path, "main.tex", doc(body))
    assert not {"STA001", "STA002"} & fired(check(tmp_path, only=["STA001", "STA002"]))


def test_a_teaser_figure_needs_alt_text_too(tmp_path):
    body = (BS + "begin{teaserfigure}" + NL + BS + "includegraphics[width=" + BS + "textwidth]{teaser}" + NL
            + BS + "caption{Our system.}" + NL + BS + "end{teaserfigure}")
    write(tmp_path, "main.tex", doc(body, cls="acmart", options=CHI))
    assert "ACC001" in fired(check(tmp_path, only=["ACC001"]))


def test_someone_elses_repository_is_not_an_error(tmp_path):
    body = BS + "author{Jane Doe}" + NL + "We build on " + BS + "url{https://github.com/pytorch/pytorch}."
    write(tmp_path, "main.tex", doc(body, cls="acmart", options="manuscript,review"))
    hits = of(check(tmp_path, only=["ANON003"]), "ANON003")
    assert hits and all(f.severity is Severity.WARN for f in hits)


def test_the_authors_own_repository_is_an_error(tmp_path):
    body = BS + "author{Jane Doe}" + NL + "Code: " + BS + "url{https://github.com/janedoe/tool}."
    write(tmp_path, "main.tex", doc(body, cls="acmart", options="manuscript,review"))
    hits = of(check(tmp_path, only=["ANON003"]), "ANON003")
    assert hits and hits[0].severity is Severity.ERROR


def test_an_institution_page_on_a_subdomain_is_identifying(tmp_path):
    write(tmp_path, "main.tex", doc("See " + BS + "url{https://hci.stanford.edu/~jdoe/proto}.",
                                    cls="acmart", options="manuscript,review"))
    assert "ANON003" in fired(check(tmp_path, only=["ANON003"]))


def test_supported_by_the_data_is_not_funding(tmp_path):
    write(tmp_path, "main.tex", doc("This interpretation is supported by the interview data.",
                                    cls="acmart", options="manuscript,review"))
    assert "ANON004" not in fired(check(tmp_path, only=["ANON004"]))


def test_supported_by_a_funder_is_funding(tmp_path):
    write(tmp_path, "main.tex", doc("This work was supported by the German Research Foundation.",
                                    cls="acmart", options="manuscript,review"))
    assert "ANON004" in fired(check(tmp_path, only=["ANON004"]))


def test_an_input_inside_iffalse_is_not_missing(tmp_path):
    write(tmp_path, "main.tex", doc(BS + "iffalse" + NL + BS + "input{old_chapter}" + NL + BS + "fi"))
    assert "STR001" not in fired(check(tmp_path, only=["STR001"]))


def test_inputs_resolve_from_the_main_files_folder(tmp_path):
    write(tmp_path, "paper/main.tex", doc(BS + "input{chapters/intro}"))
    write(tmp_path, "paper/chapters/intro.tex", "Chapter text.")
    project = TexProject.load(str(tmp_path), "paper/main.tex")
    assert "Chapter text." in project.text and not project.missing_inputs


def test_a_long_tail_without_a_full_stop_is_linear(tmp_path):
    import time

    # About 30 KB with no full stop: the old pattern took close to a minute.
    tail = (BS + "begin{lstlisting}" + NL + NL.join("x = compute(i, j)  # step " + str(i) for i in range(1000))
            + NL + BS + "end{lstlisting}" + NL + "words without a stop " * 50)
    write(tmp_path, "main.tex", doc("A short opening. " + tail))
    started = time.perf_counter()
    check(tmp_path, only=["STY012"])
    assert time.perf_counter() - started < 3


# --------------------------------------------------------------------------- #
# the fixer and the readers
# --------------------------------------------------------------------------- #

def test_the_fixer_keeps_each_lines_own_ending(tmp_path):
    from mechcheck import fixer

    text = (BS + "documentclass{article}\r\n" + BS + "begin{document}\n"
            + "We recruited 10-20 people.\r\n" + BS + "end{document}\n")
    (tmp_path / "main.tex").write_bytes(text.encode("utf-8"))
    config = Config.load(str(tmp_path), overrides={"max_per_rule": 0})
    fixer.fix(str(tmp_path), config, run, only=["STY007"], offline=True)
    out = (tmp_path / "main.tex").read_bytes().decode("utf-8")
    assert "10--20" in out
    assert out.count("\r\n") == 2 and out.count("\n") == 4


def test_the_fixer_leaves_a_latin1_file_alone(tmp_path):
    from mechcheck import fixer

    (tmp_path / "main.tex").write_bytes(
        (BS + "documentclass{article}\n" + BS + "begin{document}\nGr\xf6\xdfe: 10-20 people.\n"
         + BS + "end{document}\n").encode("latin-1"))
    config = Config.load(str(tmp_path), overrides={"max_per_rule": 0})
    report = fixer.fix(str(tmp_path), config, run, only=["STY007"], offline=True)
    assert any("UTF-8" in why for _r, _p, why in report.skipped)


def test_the_fixer_does_not_write_outside_the_project(tmp_path):
    from mechcheck import fixer

    root = tmp_path / "paper"
    write(root, "main.tex", doc(BS + "input{../shared/ack}"))
    write(tmp_path, "shared/ack.tex", "We recruited 10-20 people.")
    config = Config.load(str(root), overrides={"max_per_rule": 0})
    fixer.fix(str(root), config, run, only=["STY007"], offline=True)
    assert "10-20" in (tmp_path / "shared" / "ack.tex").read_text(encoding="utf-8")


def test_a_bib_field_is_reported_on_its_own_line():
    from mechcheck import bibtex

    text = "@article{k,\n  title = {T},\n  pages = {1-2},\n  year = {2020},\n}\n"
    entry = bibtex.parse(text)[0]
    assert entry.line_of("pages") == 3 and entry.line_of("title") == 2


def test_an_entry_inside_comment_is_not_an_entry():
    from mechcheck import bibtex

    text = "@comment{ @article{old, title = {Gone}, year = {1999}} }\n@misc{kept,\n  year = {2020},\n}\n"
    assert [e.key for e in bibtex.parse(text)] == ["kept"]


def test_a_config_pyyaml_rejects_is_still_read(tmp_path):
    pytest.importorskip("yaml")
    from mechcheck import minyaml

    assert minyaml.loads("profile: thesis\nnote: Fix: later\n").get("profile") == "thesis"


def test_a_glob_is_case_sensitive_everywhere(tmp_path):
    write(tmp_path, "main.tex", doc("Text."))
    config = Config.load(str(tmp_path), overrides={"disable": ["[ref]001", "REF00?"]})
    assert not config.enabled("REF002") and config.enabled("STY001")
    assert Config.load(str(tmp_path), overrides={"disable": ["ref001"]}).enabled("REF001")
