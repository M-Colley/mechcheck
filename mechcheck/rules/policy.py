"""Statements a venue expects, and reporting conventions that are checkable.

Two families live here:

* **Required statements** -- AI disclosure, ethics approval, data availability.
  Whether they are required is venue data, not code, so each check asks the
  venue pack first and stays silent when nothing requires it.
* **Statistics reporting** -- the narrow set of APA/HCI conventions that a
  regex can judge honestly: a bare ``p < .05`` where the exact value belongs,
  a test statistic with no degrees of freedom, a test with no effect size
  anywhere near it.  These are reported as prompts, never as errors: the tool
  cannot know whether the number is right, only whether it is present.
"""

from __future__ import annotations

import re

from mechcheck.model import Category, Severity, rule

_STUDY_SIGNALS = re.compile(
    r"\b(participants?|subjects?|respondents?|interviewe(?:e|es)|we recruited|"
    r"sample of|between-subjects?|within-subjects?|user study|field study|survey|questionnaire)\b",
    re.IGNORECASE)

_ETHICS = re.compile(
    r"\b(ethic(?:s|al)\s+(?:approval|committee|board|review|clearance)|IRB|"
    r"institutional review board|informed consent|Ethikkommission|ethics vote)\b", re.IGNORECASE)

_AI_DISCLOSURE = re.compile(
    r"\b(generative\s+AI|large language model|LLM|ChatGPT|GPT-[0-9]|Claude|Copilot|"
    r"AI[- ]assisted|AI writing|künstliche Intelligenz)\b", re.IGNORECASE)

_DATA_AVAILABILITY = re.compile(
    r"\b(data\s+(?:and\s+materials\s+)?(?:are|is)?\s*available|availability statement|"
    r"open science|supplementary material|we (?:share|provide|release) (?:our|the) (?:data|code|materials)|"
    r"osf\.io|zenodo|preregist(?:ered|ration))\b", re.IGNORECASE)

_BARE_P = re.compile(r"\bp\s*[<>]\s*\.?0*5\b|\bp\s*[<>]\s*0?\.0?5\b", re.IGNORECASE)
_P_VALUE = re.compile(r"\bp\s*[<=>]\s*0?\.\d+", re.IGNORECASE)
_TEST_STAT = re.compile(r"\b([Ftχ2]|chi\^?2|U|W|H|Z)\s*(\([^)]{1,30}\))?\s*=\s*[-−]?\d", re.IGNORECASE)
_EFFECT_SIZE = re.compile(
    r"(\\eta|η|eta)[\^_]?2|\bCohen'?s?\s*d\b|\bd\s*=\s*[-−]?\d|\br\s*=\s*[-−]?[01]?\.\d|"
    r"\bomega\^?2|\bpartial\s+eta|\bCramer'?s?\s*V\b|\bodds ratio\b|\bOR\s*=", re.IGNORECASE)

_DEMOGRAPHICS = re.compile(
    r"\b(age[ds]?\b|M\s*=\s*\d|mean age|years old|Jahre alt|gender|women|men|non-?binary)\b",
    re.IGNORECASE)


def _requires(ctx, key: str, rule_id: str) -> bool:
    """Venue pack decides; config can override; otherwise the check is off."""
    explicit = ctx.opt(rule_id, "required", None)
    if explicit is not None:
        return bool(explicit)
    return bool(ctx.config.venue_field("requires", key, default=False))


def _venue_already_requires(ctx, command: str) -> bool:
    """True when the venue pack lists this command, so VEN004 reports it instead."""
    for spec in ctx.config.venue_field("required_commands", default=[]) or []:
        name = spec.get("command") if isinstance(spec, dict) else spec
        if str(name or "").lstrip(chr(92)).lower() == command.lower():
            return True
    return False


def _has_study(ctx) -> bool:
    return len(_STUDY_SIGNALS.findall(ctx.project.prose)) >= 3


@rule("POL001", "No AI-use disclosure", Category.POLICY, Severity.WARN,
      rationale="ACM's authorship policy requires disclosing the use of generative AI in producing the work; most universities now require the same in a thesis.",
      fix="Add a short statement saying which tools were used and for what -- or that none were.")
def ai_disclosure(ctx):
    if not _requires(ctx, "ai_disclosure", "POL001"):
        return
    if _AI_DISCLOSURE.search(ctx.project.prose):
        return
    yield ctx.finding("POL001", "no statement about the use (or non-use) of generative AI",
                      file=ctx.project.main,
                      fix="State which AI tools were used for what, or that none were used.")


@rule("POL002", "Study reported without an ethics statement", Category.POLICY, Severity.WARN,
      rationale="A study with human participants and no word about ethics approval or consent is a reviewer's first question and an examiner's second.",
      fix="Add one sentence: approving body, approval number, and that participants gave informed consent.")
def ethics_statement(ctx):
    if not _has_study(ctx):
        return
    if _ETHICS.search(ctx.project.prose):
        return
    yield ctx.finding("POL002", "the document reports a study but never mentions ethics approval or informed consent",
                      file=ctx.project.main)


@rule("POL003", "No data availability / open science statement", Category.POLICY, Severity.INFO,
      rationale="Open science statements are expected across HCI now, and several venues have a dedicated field for one.",
      fix="Say where the data, materials and analysis code are -- or why they cannot be shared.")
def data_availability(ctx):
    if not (_requires(ctx, "data_availability", "POL003") or _has_study(ctx)):
        return
    if _DATA_AVAILABILITY.search(ctx.project.prose):
        return
    yield ctx.finding("POL003", "no data availability or open science statement found",
                      file=ctx.project.main)


@rule("POL004", "Participants described without demographics", Category.POLICY, Severity.INFO,
      rationale="Reviewers expect N, age (M/SD) and relevant characteristics; missing them is a predictable revision request.",
      fix="Report N, age M/SD, gender distribution and compensation.")
def participant_demographics(ctx):
    if not _has_study(ctx):
        return
    prose = ctx.project.prose
    if len(_DEMOGRAPHICS.findall(prose)) >= 2:
        return
    m = _STUDY_SIGNALS.search(prose)
    f, line, col = ctx.project.locate(m.start()) if m else (ctx.project.main, None, None)
    yield ctx.finding("POL004", "participants are mentioned but no demographics are reported",
                      file=f, line=line, col=col)


@rule("POL005", "Significance reported without an exact p value", Category.POLICY, Severity.INFO,
      rationale="APA style asks for exact p values; a bare 'p < .05' hides how strong the evidence actually is.",
      fix="Report the exact value, e.g. p = .032 (use p < .001 only below that threshold).")
def bare_p_value(ctx):
    for m in _BARE_P.finditer(ctx.project.prose):
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("POL005", f"'{m.group(0)}' instead of an exact p value",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))


@rule("POL006", "Test statistic without degrees of freedom", Category.POLICY, Severity.INFO,
      rationale="F, t and chi-square are uninterpretable without their degrees of freedom.",
      fix="Write F(2, 46) = 4.71 rather than F = 4.71.")
def missing_degrees_of_freedom(ctx):
    prose = ctx.project.prose
    for m in _TEST_STAT.finditer(prose):
        if m.group(2):
            continue  # parenthesised df present
        symbol = m.group(1)
        if symbol.lower() not in ("f", "t"):
            continue  # U, W, Z legitimately have no df
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("POL006", f"'{m.group(0).strip()}' has no degrees of freedom",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))


@rule("POL007", "Significant result without an effect size", Category.POLICY, Severity.INFO,
      rationale="A p value says whether an effect exists; only an effect size says whether it matters. Most HCI venues expect both.",
      fix="Report an effect size next to the test (eta squared, Cohen's d, r).")
def missing_effect_size(ctx):
    prose = ctx.project.prose
    window = int(ctx.opt("POL007", "window_chars", 320) or 320)
    for m in _P_VALUE.finditer(prose):
        neighbourhood = prose[max(0, m.start() - window):m.end() + window]
        if _EFFECT_SIZE.search(neighbourhood):
            continue
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("POL007", f"'{m.group(0)}' is reported with no effect size nearby",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))


@rule("POL008", "ACM CCS concepts missing", Category.POLICY, Severity.ERROR,
      rationale="ACM requires CCS concepts; TAPS rejects submissions without them.",
      fix="Generate the block at dl.acm.org/ccs and paste the \\ccsdesc lines below the abstract.")
def ccs_concepts(ctx):
    cls, _ = ctx.project.documentclass()
    if cls.lower() != "acmart" or _venue_already_requires(ctx, "ccsdesc"):
        return
    if ctx.project.commands("ccsdesc", 1) or ctx.project.environments("CCSXML"):
        return
    yield ctx.finding("POL008", "no \\ccsdesc / CCSXML block found",
                      file=ctx.project.main)


@rule("POL009", "Keywords missing", Category.POLICY, Severity.WARN,
      rationale="Keywords drive indexing and search; ACM templates expect them and TAPS flags their absence.",
      fix="Add \\keywords{...} with 3-6 terms.")
def keywords(ctx):
    cls, _ = ctx.project.documentclass()
    if cls.lower() != "acmart" or _venue_already_requires(ctx, "keywords"):
        return
    if ctx.project.commands("keywords", 1):
        return
    yield ctx.finding("POL009", "no \\keywords{...} found", file=ctx.project.main)


_NUMBER_WORDS = (r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
                 r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|"
                 r"fifty|sixty|seventy|eighty|ninety|hundred|hundreds|thousand")

#: Either the count itself, or a sentence that is plainly about it.
_PARTICIPANT_COUNT = re.compile(
    r"\b[Nn]\s*=\s*\d+"
    r"|\b(?:number|size)\s+of\s+(?:the\s+|our\s+)?(?:sample|participants)\b"
    r"|\bsample\s+size\b|\bhow\s+many\s+(?:participants|people)\b"
    r"|\b(?:\d{1,5}|(?:" + _NUMBER_WORDS + r")(?:[- ](?:" + _NUMBER_WORDS + r"))?)"
    r"(?:\s+\w+){0,2}\s+(?:participants|respondents|subjects|interviewees|users|students|"
    r"drivers|passengers|pedestrians|volunteers|people|persons|individuals|informants)\b",
    re.IGNORECASE)


@rule("POL010", "Study without a stated number of participants", Category.POLICY, Severity.INFO,
      rationale="N is the first number a reviewer looks for and the one every statistic depends on; a study section that never states it reads as unfinished.",
      fix="State the sample size where the participants are introduced: 'We recruited 24 participants (N = 24) ...'.")
def participant_count(ctx):
    if not _has_study(ctx):
        return
    prose = ctx.project.prose
    if _PARTICIPANT_COUNT.search(prose):
        return
    m = _STUDY_SIGNALS.search(prose)
    f, line, col = ctx.project.locate(m.start()) if m else (ctx.project.main, None, None)
    yield ctx.finding("POL010", "participants are mentioned but their number is never stated",
                      file=f, line=line, col=col)
