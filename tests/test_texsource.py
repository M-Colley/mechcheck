"""The parser is the foundation: if offsets drift, every finding points at the
wrong line and the tool stops being trusted. These tests pin that down."""

from __future__ import annotations

import os

import pytest

from mechcheck.texsource import (TexProject, build_prose_view, find_main_document,
                                 parse_commands, parse_environments, read_group,
                                 strip_comments_line)

BS = chr(92)
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def test_read_group_handles_nesting_and_escapes():
    assert read_group("{a{b}c}rest", 0) == ("a{b}c", 7)
    assert read_group("{a" + BS + "}b}", 0) == ("a" + BS + "}b", 6)
    assert read_group("no group", 0) is None
    assert read_group("{unterminated", 0) is None


def test_comment_stripping_preserves_length_and_escapes():
    line = "text % comment"
    stripped = strip_comments_line(line)
    assert len(stripped) == len(line)
    assert stripped.rstrip() == "text"
    # An escaped percent is content, not a comment.
    escaped = "50" + BS + "% of users"
    assert strip_comments_line(escaped).rstrip() == escaped


def test_parse_commands_does_not_match_longer_control_words():
    text = BS + "ref{a} " + BS + "reflect{b}"
    found = parse_commands(text, "ref", 1)
    assert [c.arg(0) for c in found] == ["a"]


def test_parse_commands_reads_optional_and_mandatory_arguments():
    text = BS + "includegraphics[width=1cm]{img/x.pdf}"
    cmd = parse_commands(text, "includegraphics", 1)[0]
    assert cmd.opts == ("width=1cm",)
    assert cmd.arg(0) == "img/x.pdf"


def test_parse_environments_respects_nesting():
    text = (BS + "begin{figure}A" + BS + "begin{figure}B" + BS + "end{figure}C"
            + BS + "end{figure}")
    envs = parse_environments(text, "figure")
    assert len(envs) == 2
    outer = max(envs, key=lambda e: e.end - e.start)
    assert "A" in outer.body(text) and "C" in outer.body(text)


def test_prose_view_masks_maths_but_keeps_length_and_text():
    text = "The value $" + BS + "alpha = 5$ was used."
    prose = build_prose_view(text)
    assert len(prose) == len(text)
    assert "alpha" not in prose
    assert "The value" in prose and "was used" in prose


def test_prose_view_keeps_text_inside_formatting_commands():
    text = "This is " + BS + "textit{important} here."
    prose = build_prose_view(text)
    assert "important" in prose
    assert "textit" not in prose


class TestProject:
    @pytest.fixture(scope="class")
    def project(self):
        return TexProject.load(os.path.join(FIXTURES, "sample"))

    def test_follows_input_files(self, project):
        assert [f.path for f in project.files] == ["main.tex", "chapters/method.tex"]

    def test_ignores_labels_inside_verbatim(self, project):
        labels = [c.arg(0) for c in project.commands("label")]
        assert "fig:notreal" not in labels

    def test_ignores_references_inside_comments(self, project):
        refs = [c.arg(0) for c in project.any_commands(["ref", "cref"])]
        assert "nothing" not in refs

    def test_offsets_map_back_to_the_right_file_and_line(self, project):
        import re

        match = re.search(r"tab:missing", project.text)
        assert match is not None
        path, line, _col = project.locate(match.start())
        assert path == "chapters/method.tex"
        assert line == 3

    def test_documentclass_and_options(self, project):
        assert project.documentclass() == ("acmart", ["sigconf"])

    def test_floats_are_found_across_files(self, project):
        names = [e.name for e in project.floats()]
        assert names.count("figure") == 2
        assert names.count("table") == 1


def test_find_main_document_prefers_the_real_root(tmp_path):
    (tmp_path / "chapter.tex").write_text("Just a chapter, no preamble.", encoding="utf-8")
    (tmp_path / "main.tex").write_text(
        BS + "documentclass{article}" + BS + "begin{document}x" + BS + "end{document}",
        encoding="utf-8")
    assert find_main_document(str(tmp_path)) == "main.tex"


def test_missing_main_document_returns_none(tmp_path):
    (tmp_path / "notes.tex").write_text("no document class here", encoding="utf-8")
    assert find_main_document(str(tmp_path)) is None
