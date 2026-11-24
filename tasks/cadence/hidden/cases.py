"""Hidden test cases for task2 (`cadence`).

suite: "qa"      -> failures are shown to Codex as a QA report (feedback tests)
       "holdout" -> never shown; used only for the final score
scope: "core"    -> what turn 1 asks for (SPEC.md as shipped)
       "v2"      -> the two additions requested in turn 3 (holidays; minute/hour rules)

QA cases use rule ids starting with "qa-"; holdout cases use ids starting with "h-".
"""

import time

TESTS = []


class Fail(Exception):
    pass


def case(suite, scope, name, desc):
    def deco(fn):
        TESTS.append({"suite": suite, "scope": scope, "name": name, "desc": desc, "fn": fn})
        return fn

    return deco


BERLIN = "Europe/Berlin"
NY = "America/New_York"


def P(*rules, tz=BERLIN, **extra):
    p = {"timezone": tz, "rules": list(rules)}
    p.update(extra)
    return p


def R(rid, text, **extra):
    r = {"id": rid, "rule": text}
    r.update(extra)
    return r


def eq(actual, expected, what=""):
    if actual != expected:
        raise Fail(f"{what}expected: {expected!r}\n{what}got:      {actual!r}")


def _rows(got):
    try:
        return [(o["rule"], o["key"], o["start"], o["end"]) for o in got]
    except Exception:  # noqa: BLE001
        return got


def _call(fn, plan, start, end, expected):
    try:
        return fn(plan, start, end)
    except Exception as exc:  # noqa: BLE001
        raise Fail(f"expected: {expected!r}\ngot:      raised {type(exc).__name__}: {exc}")


def occ(L, plan, start, end, expected):
    """expected: list of (rule, key, start, end)."""
    eq(_rows(_call(L.occurrences, plan, start, end, expected)), expected)


def keys(L, plan, start, end, expected):
    got = _call(L.occurrences, plan, start, end, expected)
    try:
        got = [o["key"] for o in got]
    except Exception:  # noqa: BLE001
        pass
    eq(got, expected)


def agenda(L, plan, start, end, expected):
    eq(_rows(_call(L.agenda, plan, start, end, expected)), expected)


def plan_error(L, plan, start="2025-01-01T00:00Z", end="2025-01-02T00:00Z", must_contain=None, fn=None):
    try:
        got = (fn or L.occurrences)(plan, start, end)
    except L.PlanError as exc:
        if must_contain and must_contain not in str(exc):
            raise Fail(f"expected: PlanError mentioning {must_contain!r}\ngot:      {type(exc).__name__}({str(exc)!r})")
        return exc
    except Exception as exc:  # noqa: BLE001
        raise Fail(f"expected: PlanError\ngot:      {type(exc).__name__}: {exc}")
    raise Fail(f"expected: PlanError\ngot:      no error, returned {got!r}")


def syntax(L, text, token=None, position=None):
    """canonical(text) must raise RuleSyntaxError at the start of `token` (or at `position`)."""
    if position is None:
        position = len(text) if token is None else text.index(token)
    try:
        got = L.canonical(text)
    except L.RuleSyntaxError as exc:
        pos = getattr(exc, "position", "<no position attribute>")
        if pos != position or isinstance(pos, bool):
            raise Fail(f"rule text: {text!r}\nexpected: RuleSyntaxError with position {position}\ngot:      position {pos!r}")
        return
    except Exception as exc:  # noqa: BLE001
        raise Fail(f"rule text: {text!r}\nexpected: RuleSyntaxError with position {position}\ngot:      {type(exc).__name__}: {exc}")
    raise Fail(f"rule text: {text!r}\nexpected: RuleSyntaxError with position {position}\ngot:      no error, returned {got!r}")


def canon(L, text, expected):
    try:
        got = L.canonical(text)
    except Exception as exc:  # noqa: BLE001
        raise Fail(f"rule text: {text!r}\nexpected: {expected!r}\ngot:      raised {type(exc).__name__}: {exc}")
    if got != expected:
        raise Fail(f"rule text: {text!r}\nexpected: {expected!r}\ngot:      {got!r}")
    again = L.canonical(got)
    if again != got:
        raise Fail(f"canonical is not idempotent on {got!r}: got {again!r}")


def run_cli(cli, args, plan, code):
    rc, out, err = cli(args, plan)
    if rc != code:
        raise Fail(f"command: {' '.join(args)}\nexpected: exit status {code}\ngot:      exit status {rc} (stderr: {err.strip()[-300:]!r})")
    return out.splitlines(), err.splitlines()


def D(day, hhmm, off="+02:00"):
    return f"{day}T{hhmm}:00{off}"


# ================================================================ QA / core

@case("qa", "core", "canonical-sorts-and-normalises",
      "canonical(): lists sorted (month days ascending, 'last' at the end; times ascending), duration 150m written as 2h30m.")
def _(L, cli):
    canon(L, "EVERY 3 Months ON last,15,1 AT 18:00,06:30 FOR 150m FROM 2025-01-31 TIMES 4",
          "every 3 months on 1,15,last at 06:30,18:00 for 2h30m from 2025-01-31 times 4")


@case("qa", "core", "canonical-defaults-spelled-out",
      "canonical(): N always written, unit singular for 1, default 'on' written for week rules, 24h -> 1d, 1d60m -> 1d1h.")
def _(L, cli):
    canon(L, "every week at 09:00 for 24h from 2025-01-08",
          "every 1 week on wed at 09:00 for 1d from 2025-01-08")
    canon(L, "every days at 07:00 for 1d60m from 2025-02-01 until 2025-02-01",
          "every 1 day at 07:00 for 1d1h from 2025-02-01 until 2025-02-01")


@case("qa", "core", "syntax-position-is-character-offset",
      "RuleSyntaxError.position is a character offset into the text as given (extra spaces count); a duplicate in a list points at the start of the list token.")
def _(L, cli):
    syntax(L, "  every  2 weeks on mon,mon at 09:00 for 1h from 2025-01-06", "mon,mon")
    syntax(L, "every 2 weeks   on tue,funday at 09:00 for 1h from 2025-01-06", "tue,funday")


@case("qa", "core", "syntax-position-at-end-of-text",
      "Rule text that ends where another token is required: position == len(text).")
def _(L, cli):
    syntax(L, "every week at 09:00 for 15m")
    syntax(L, "every week at 09:00 for 15m from 2025-01-06 until")


@case("qa", "core", "syntax-strict-token-shapes",
      "Tokens with the wrong shape are rejected at their own position: time '9:30', count '02', duration '30m1h'.")
def _(L, cli):
    syntax(L, "every day at 9:30 for 15m from 2025-01-06", "9:30")
    syntax(L, "every 02 days at 09:30 for 15m from 2025-01-06", "02")
    syntax(L, "every day at 09:30 for 30m1h from 2025-01-06", "30m1h")


@case("qa", "core", "syntax-dates-and-trailing-text",
      "Impossible date 2025-02-30, 'until' before 'from', and text after the end of the rule are syntax errors at that token.")
def _(L, cli):
    syntax(L, "every day at 09:30 for 15m from 2025-02-30", "2025-02-30")
    syntax(L, "every day at 09:30 for 15m from 2025-03-10 until 2025-03-09", "2025-03-09")
    syntax(L, "every day at 09:30 for 15m from 2025-03-10 until 2025-03-12 times 3", "times")


@case("qa", "core", "weeks-are-monday-based",
      "every 2 weeks on mon,fri from Wed 2025-01-08: week 0 is Jan 6-12, so Fri Jan 10, then Mon Jan 20 and Fri Jan 24.")
def _(L, cli):
    p = P(R("qa-biweekly", "every 2 weeks on mon,fri at 10:00 for 1h from 2025-01-08"))
    keys(L, p, "2025-01-01T00:00Z", "2025-02-01T00:00Z",
         ["2025-01-10T10:00", "2025-01-20T10:00", "2025-01-24T10:00"])


@case("qa", "core", "month-day-missing-is-skipped",
      "every month on 31: months without a 31st are skipped, not moved to the last day.")
def _(L, cli):
    p = P(R("qa-31st", "every month on 31 at 12:00 for 1h from 2025-01-31"))
    keys(L, p, "2025-01-01T00:00Z", "2025-06-01T00:00Z",
         ["2025-01-31T12:00", "2025-03-31T12:00", "2025-05-31T12:00"])


@case("qa", "core", "duration-is-elapsed-time",
      "Europe/Berlin, 2025-03-30 (clocks go forward): 'at 01:00 for 3h' ends at 05:00+02:00.")
def _(L, cli):
    p = P(R("qa-night", "every day at 01:00 for 3h from 2025-03-30 times 1"))
    occ(L, p, "2025-03-29T00:00Z", "2025-03-31T00:00Z",
        [("qa-night", "2025-03-30T01:00", "2025-03-30T01:00:00+01:00", "2025-03-30T05:00:00+02:00")])


@case("qa", "core", "gap-time-moves-later-and-duplicate-removed",
      "Berlin 2025-03-30 'at 02:30,03:30 ... times 3': 02:30 becomes 03:30+02:00 (key stays 02:30), the 03:30 duplicate is removed before 'times' counts.")
def _(L, cli):
    p = P(R("qa-gap", "every day at 02:30,03:30 for 20m from 2025-03-30 times 3"))
    occ(L, p, "2025-03-29T00:00Z", "2025-04-05T00:00Z", [
        ("qa-gap", "2025-03-30T02:30", "2025-03-30T03:30:00+02:00", "2025-03-30T03:50:00+02:00"),
        ("qa-gap", "2025-03-31T02:30", "2025-03-31T02:30:00+02:00", "2025-03-31T02:50:00+02:00"),
        ("qa-gap", "2025-03-31T03:30", "2025-03-31T03:30:00+02:00", "2025-03-31T03:50:00+02:00"),
    ])


@case("qa", "core", "repeated-local-time-means-earlier-instant",
      "America/New_York 2025-11-02 01:30 happens twice: the occurrence starts at 01:30-04:00 and, one hour later, ends at 01:30-05:00.")
def _(L, cli):
    p = P(R("qa-fold", "every day at 01:30 for 1h from 2025-11-02 times 1"), tz=NY)
    occ(L, p, "2025-11-01T00:00Z", "2025-11-04T00:00Z",
        [("qa-fold", "2025-11-02T01:30", "2025-11-02T01:30:00-04:00", "2025-11-02T01:30:00-05:00")])


@case("qa", "core", "times-counts-cancelled-occurrences",
      "'times 3' with the second occurrence cancelled leaves two occurrences; a fourth is not generated.")
def _(L, cli):
    p = P(R("qa-three", "every day at 08:00 for 30m from 2025-05-01 times 3"),
          overrides=[{"rule": "qa-three", "key": "2025-05-02T08:00", "action": "cancel"}])
    keys(L, p, "2025-04-25T00:00Z", "2025-05-20T00:00Z", ["2025-05-01T08:00", "2025-05-03T08:00"])


@case("qa", "core", "window-is-overlap-half-open",
      "An occurrence is returned (whole) if it overlaps [start, end): one still running at 'start' is included; ending exactly at 'start' or starting exactly at 'end' is not.")
def _(L, cli):
    p = P(R("qa-late", "every day at 23:00 for 2h from 2025-06-01"))
    occ(L, p, "2025-06-02T01:00+02:00", "2025-06-02T23:00+02:00", [])
    occ(L, p, "2025-06-02T00:30+02:00", "2025-06-02T23:30+02:00", [
        ("qa-late", "2025-06-01T23:00", D("2025-06-01", "23:00"), D("2025-06-02", "01:00")),
        ("qa-late", "2025-06-02T23:00", D("2025-06-02", "23:00"), D("2025-06-03", "01:00")),
    ])


@case("qa", "core", "move-uses-final-time-for-window",
      "A 'move' override: the occurrence is found by its new time (moved into the window from outside it), keeps its key, and takes the override's 'for' duration.")
def _(L, cli):
    p = P(R("qa-weekly", "every week on mon at 09:00 for 1h from 2025-01-06"),
          overrides=[{"rule": "qa-weekly", "key": "2025-01-13T09:00", "action": "move",
                      "to": "2025-01-08T15:00", "for": "30m"}])
    occ(L, p, "2025-01-06T00:00+01:00", "2025-01-12T00:00+01:00", [
        ("qa-weekly", "2025-01-06T09:00", D("2025-01-06", "09:00", "+01:00"), D("2025-01-06", "10:00", "+01:00")),
        ("qa-weekly", "2025-01-13T09:00", D("2025-01-08", "15:00", "+01:00"), D("2025-01-08", "15:30", "+01:00")),
    ])
    occ(L, p, "2025-01-13T00:00+01:00", "2025-01-19T00:00+01:00", [])


@case("qa", "core", "override-must-match-an-occurrence",
      "An override whose key is not an occurrence of the rule is a PlanError mentioning the rule id, even when it is far outside the query window.")
def _(L, cli):
    p = P(R("qa-mondays", "every week on mon at 09:00 for 1h from 2025-01-06"),
          overrides=[{"rule": "qa-mondays", "key": "2026-07-07T09:00", "action": "cancel"}])
    plan_error(L, p, "2025-01-06T00:00Z", "2025-01-07T00:00Z", "qa-mondays")


@case("qa", "core", "override-key-may-be-date-only",
      "For a rule with one 'at' time the override key may be just the date; with two 'at' times a date-only key is a PlanError.")
def _(L, cli):
    p = P(R("qa-daily", "every day at 08:00 for 30m from 2025-05-01"),
          overrides=[{"rule": "qa-daily", "key": "2025-05-02", "action": "cancel"}])
    keys(L, p, "2025-05-01T00:00+02:00", "2025-05-04T00:00+02:00", ["2025-05-01T08:00", "2025-05-03T08:00"])
    p = P(R("qa-twice", "every day at 08:00,20:00 for 30m from 2025-05-01"),
          overrides=[{"rule": "qa-twice", "key": "2025-05-02", "action": "cancel"}])
    plan_error(L, p, "2025-05-01T00:00+02:00", "2025-05-04T00:00+02:00", "qa-twice")


@case("qa", "core", "order-by-instant-then-priority",
      "Results are ordered by start instant across time zones (10:00 Berlin is before 04:30 New York in January); equal start and end: higher priority first.")
def _(L, cli):
    p = P(R("qa-c", "every day at 14:00 for 1h from 2025-01-15 times 1"),
          R("qa-b", "every day at 04:30 for 1h from 2025-01-15 times 1", timezone=NY),
          R("qa-d", "every day at 14:00 for 1h from 2025-01-15 times 1", priority=3),
          R("qa-a", "every day at 10:00 for 1h from 2025-01-15 times 1"))
    occ(L, p, "2025-01-15T00:00Z", "2025-01-16T00:00Z", [
        ("qa-a", "2025-01-15T10:00", "2025-01-15T10:00:00+01:00", "2025-01-15T11:00:00+01:00"),
        ("qa-b", "2025-01-15T04:30", "2025-01-15T04:30:00-05:00", "2025-01-15T05:30:00-05:00"),
        ("qa-d", "2025-01-15T14:00", "2025-01-15T14:00:00+01:00", "2025-01-15T15:00:00+01:00"),
        ("qa-c", "2025-01-15T14:00", "2025-01-15T14:00:00+01:00", "2025-01-15T15:00:00+01:00"),
    ])


@case("qa", "core", "agenda-ranking",
      "agenda(): higher priority wins; with equal priority the earlier start wins and covers with its whole interval.")
def _(L, cli):
    day = "2025-06-02"
    p = P(R("qa-sync", f"every day at 10:00 for 1h30m from {day} times 1"),
          R("qa-desk", f"every day at 09:00 for 3h from {day} times 1"),
          R("qa-lunch", f"every day at 11:30 for 1h from {day} times 1", priority=2),
          R("qa-walk", f"every day at 12:00 for 1h from {day} times 1", priority=1))
    agenda(L, p, f"{day}T00:00+02:00", "2025-06-03T00:00+02:00", [
        ("qa-desk", f"{day}T09:00", D(day, "09:00"), D(day, "11:30")),
        ("qa-lunch", f"{day}T11:30", D(day, "11:30"), D(day, "12:30")),
        ("qa-walk", f"{day}T12:00", D(day, "12:30"), D(day, "13:00")),
    ])


@case("qa", "core", "agenda-min-segment",
      "agenda() with min_segment 15m: leftover pieces of 10m are discarded and not handed to a lower-ranked occurrence; an untouched 5m occurrence stays.")
def _(L, cli):
    day = "2025-06-02"
    p = P(R("qa-block", f"every day at 09:00 for 1h from {day} times 1"),
          R("qa-call", f"every day at 09:10 for 40m from {day} times 1", priority=1),
          R("qa-ping", f"every day at 14:00 for 5m from {day} times 1"),
          R("qa-fill", f"every day at 09:00 for 30m from {day} times 1", priority=-1),
          min_segment="15m")
    agenda(L, p, f"{day}T00:00+02:00", "2025-06-03T00:00+02:00", [
        ("qa-call", f"{day}T09:10", D(day, "09:10"), D(day, "09:50")),
        ("qa-ping", f"{day}T14:00", D(day, "14:00"), D(day, "14:05")),
    ])


@case("qa", "core", "agenda-cut-to-window",
      "agenda(): segments are cut to the window, and min_segment (30m) looks at the length before the cut.")
def _(L, cli):
    day = "2025-06-02"
    p = P(R("qa-long", f"every day at 09:00 for 2h from {day} times 1"),
          R("qa-mid", f"every day at 09:30 for 30m from {day} times 1", priority=1),
          min_segment="30m")
    agenda(L, p, f"{day}T09:20+02:00", f"{day}T09:40+02:00", [
        ("qa-long", f"{day}T09:00", D(day, "09:20"), D(day, "09:30")),
        ("qa-mid", f"{day}T09:30", D(day, "09:30"), D(day, "09:40")),
    ])


@case("qa", "core", "cli-output",
      "CLI: 'occurrences START END PLAN.json' prints 'START END RULE KEY' lines, or 'nothing scheduled'; 'canonical' prints the canonical form.")
def _(L, cli):
    p = P(R("qa-standup", "every day at 09:30 for 15m from 2025-03-05 times 2"))
    out, _ = run_cli(cli, ["occurrences", "2025-03-05T00:00+01:00", "2025-03-06T00:00+01:00"], p, 0)
    eq(out, ["2025-03-05T09:30:00+01:00 2025-03-05T09:45:00+01:00 qa-standup 2025-03-05T09:30"])
    out, _ = run_cli(cli, ["occurrences", "2025-03-10T00:00+01:00", "2025-03-11T00:00+01:00"], p, 0)
    eq(out, ["nothing scheduled"])
    out, _ = run_cli(cli, ["canonical", "every week at 10:00 for 60m from 2025-03-05"], None, 0)
    eq(out, ["every 1 week on wed at 10:00 for 1h from 2025-03-05"])


@case("qa", "core", "cli-errors",
      "CLI: PlanError -> 'error: ...' on stderr, exit 2; RuleSyntaxError adds the rule text and a caret line; invalid JSON -> exit 1.")
def _(L, cli):
    text = "every 2 fortnights at 09:30 for 45m from 2025-01-06"
    _, err = run_cli(cli, ["canonical", text], None, 2)
    if len(err) < 3 or not err[0].startswith("error: ") or err[-2:] != [text, " " * 8 + "^"]:
        raise Fail(f"expected stderr: 'error: <message>', then {text!r}, then {' ' * 8 + '^'!r}\ngot:      {err!r}")
    _, err = run_cli(cli, ["occurrences", "2025-03-05T00:00Z", "2025-03-06T00:00Z"], P(tz="Mars/Olympus"), 2)
    if not err or not err[0].startswith("error: "):
        raise Fail(f"expected stderr starting with 'error: '\ngot:      {err!r}")
    _, err = run_cli(cli, ["occurrences", "2025-03-05T00:00Z", "2025-03-06T00:00Z"], "{not json", 1)
    if not err or not err[0].startswith("error: "):
        raise Fail(f"expected stderr starting with 'error: '\ngot:      {err!r}")


def _old_rules(prefix, n, start):
    forms = [
        "every day at {h:02d}:00 for 1h from {s}",
        "every 2 weeks on mon,thu at {h:02d}:15 for 45m from {s}",
        "every month on 1,15,last at {h:02d}:30 for 2h from {s}",
        "every 3 days at {h:02d}:45 for 30m from {s}",
    ]
    return [R(f"{prefix}{i}", forms[i % 4].format(h=i % 24, s=start)) for i in range(n)]


@case("qa", "core", "performance-far-window",
      "200 rules starting 1970-01-01, ten one-day windows in 2060: must finish within the time limit (section 11).")
def _(L, cli):
    p = P(*_old_rules("qa-r", 200, "1970-01-01"))
    t0 = time.time()
    total = 0
    for d in range(10, 20):
        total += len(L.occurrences(p, f"2060-03-{d}T00:00+01:00", f"2060-03-{d + 1}T00:00+01:00"))
    if time.time() - t0 > 3.0:
        raise Fail(f"took {time.time() - t0:.1f}s, limit 3s")
    eq(total, PERF_QA_TOTAL, "total occurrences over the ten windows: ")


PERF_QA_TOTAL = 790  # cross-checked with an independent brute-force count


# ================================================================ QA / v2

@case("qa", "v2", "holiday-skip-not-counted",
      "holiday 'skip': candidates on holidays are removed before 'times' counts (daily from Dec 23, times 3, Dec 24-26 holidays -> Dec 23, 27, 28).")
def _(L, cli):
    p = P(R("qa-skip", "every day at 09:00 for 1h from 2025-12-23 times 3", holiday="skip"),
          holidays=["2025-12-24..2025-12-26"])
    keys(L, p, "2025-12-20T00:00Z", "2026-01-05T00:00Z",
         ["2025-12-23T09:00", "2025-12-27T09:00", "2025-12-28T09:00"])


@case("qa", "v2", "holiday-shift-next-day",
      "holiday 'shift': a Monday occurrence on a holiday takes place on Tuesday at the same local time and keeps its Monday key.")
def _(L, cli):
    p = P(R("qa-shift", "every week on mon at 09:00 for 1h from 2025-04-14", holiday="shift"),
          holidays=["2025-04-21"])
    occ(L, p, "2025-04-20T00:00Z", "2025-04-27T00:00Z",
        [("qa-shift", "2025-04-21T09:00", D("2025-04-22", "09:00"), D("2025-04-22", "10:00"))])


@case("qa", "v2", "holiday-shift-slot-taken",
      "holiday 'shift' on 'mon,tue': the shifted Monday would land on Tuesday's own slot, so it is removed and does not count toward 'times'.")
def _(L, cli):
    p = P(R("qa-pair", "every week on mon,tue at 09:00 for 1h from 2025-04-14 times 3", holiday="shift"),
          holidays=["2025-04-21"])
    keys(L, p, "2025-04-01T00:00Z", "2025-05-31T00:00Z",
         ["2025-04-14T09:00", "2025-04-15T09:00", "2025-04-22T09:00"])


@case("qa", "v2", "holiday-and-overrides",
      "Overrides come after the holiday step: a shifted occurrence is cancelled by its (holiday) key; an override on a skipped candidate is a PlanError.")
def _(L, cli):
    p = P(R("qa-shifted", "every week on mon at 09:00 for 1h from 2025-04-14", holiday="shift"),
          holidays=["2025-04-21"],
          overrides=[{"rule": "qa-shifted", "key": "2025-04-21T09:00", "action": "cancel"}])
    occ(L, p, "2025-04-20T00:00Z", "2025-04-27T00:00Z", [])
    p = P(R("qa-skipped", "every week on mon at 09:00 for 1h from 2025-04-14", holiday="skip"),
          holidays=["2025-04-21"],
          overrides=[{"rule": "qa-skipped", "key": "2025-04-21T09:00", "action": "cancel"}])
    plan_error(L, p, "2025-04-20T00:00Z", "2025-04-27T00:00Z", "qa-skipped")


@case("qa", "v2", "hour-rule-elapsed-steps",
      "'every 6 hours ... from 2025-03-29T00:00' (Berlin): steps are elapsed time, so after the clock change starts are 07:00 and 13:00; keys are UTC.")
def _(L, cli):
    p = P(R("qa-six", "every 6 hours for 30m from 2025-03-29T00:00"))
    occ(L, p, "2025-03-29T22:00Z", "2025-03-30T12:00Z", [
        ("qa-six", "2025-03-29T23:00Z", "2025-03-30T00:00:00+01:00", "2025-03-30T00:30:00+01:00"),
        ("qa-six", "2025-03-30T05:00Z", "2025-03-30T07:00:00+02:00", "2025-03-30T07:30:00+02:00"),
        ("qa-six", "2025-03-30T11:00Z", "2025-03-30T13:00:00+02:00", "2025-03-30T13:30:00+02:00"),
    ])


@case("qa", "v2", "minute-rule-text",
      "Minute/hour rule text: canonical form keeps the unit and writes the date-time with 'T'; 'at' is not allowed; 'from' needs a date-time.")
def _(L, cli):
    canon(L, "Every 90 MINUTES for 15m from 2025-01-06t08:00 times 5",
          "every 90 minutes for 15m from 2025-01-06T08:00 times 5")
    syntax(L, "every hour at 09:00 for 15m from 2025-01-06T08:00", "at")
    syntax(L, "every 2 hours for 1h from 2025-01-06", "2025-01-06")


@case("qa", "v2", "hour-rule-until-and-override",
      "Hour rule: 'until' compares the local start date; a 'move' override addresses the occurrence by its UTC key.")
def _(L, cli):
    p = P(R("qa-eight", "every 8 hours for 1h from 2025-07-01T20:00 until 2025-07-02"),
          overrides=[{"rule": "qa-eight", "key": "2025-07-02T10:00Z", "action": "move", "to": "2025-07-02T13:30"}])
    occ(L, p, "2025-07-01T00:00Z", "2025-07-31T00:00Z", [
        ("qa-eight", "2025-07-01T18:00Z", D("2025-07-01", "20:00"), D("2025-07-01", "21:00")),
        ("qa-eight", "2025-07-02T02:00Z", D("2025-07-02", "04:00"), D("2025-07-02", "05:00")),
        ("qa-eight", "2025-07-02T10:00Z", D("2025-07-02", "13:30"), D("2025-07-02", "14:30")),
        ("qa-eight", "2025-07-02T18:00Z", D("2025-07-02", "20:00"), D("2025-07-02", "21:00")),
    ])


@case("qa", "v2", "minute-rule-performance",
      "20 minute rules starting 1990-01-01, five one-hour windows in 2040: must finish within the time limit (section 11).")
def _(L, cli):
    p = P(*[R(f"qa-m{n}", f"every {n} minutes for 1m from 1990-01-01T00:00") for n in range(1, 21)])
    t0 = time.time()
    for h in range(5):
        got = L.occurrences(p, f"2040-05-05T{h:02d}:00Z", f"2040-05-05T{h + 1:02d}:00Z")
        eq(len([o for o in got if o["rule"] == "qa-m1"]), 60, "occurrences of the every-minute rule in one hour: ")
    if time.time() - t0 > 3.0:
        raise Fail(f"took {time.time() - t0:.1f}s, limit 3s")


# ================================================================ holdout / core

@case("holdout", "core", "h-canonical-weekdays", "")
def _(L, cli):
    canon(L, "every 1 weeks on sun,tue,mon at 23:59,00:00 for 1440m from 2024-02-29 until 2024-02-29",
          "every 1 week on mon,tue,sun at 00:00,23:59 for 1d from 2024-02-29 until 2024-02-29")
    canon(L, " \tEVERY  WEEKS ON Sat AT 07:05 FOR 1D FROM 2025-08-02\t ",
          "every 1 week on sat at 07:05 for 1d from 2025-08-02")


@case("holdout", "core", "h-canonical-units-and-defaults", "")
def _(L, cli):
    canon(L, "every\t5 day at 12:00 for 2d24h61m from 2025-06-01 times 10",
          "every 5 days at 12:00 for 3d1h1m from 2025-06-01 times 10")
    canon(L, "every 2 month at 08:00 for 45m from 2025-01-31",
          "every 2 months on 31 at 08:00 for 45m from 2025-01-31")
    canon(L, "every 1 months on LAST,2 at 08:00 for 60m from 2025-01-31",
          "every 1 month on 2,last at 08:00 for 1h from 2025-01-31")


@case("holdout", "core", "h-syntax-on-clause", "")
def _(L, cli):
    syntax(L, "every 2 days on mon at 09:00 for 1h from 2025-01-06", "on")
    syntax(L, "every week on 15 at 09:00 for 1h from 2025-01-06", "15")
    syntax(L, "every month on 0 at 09:00 for 1h from 2025-01-06", "0")
    syntax(L, "every month on 1,32 at 09:00 for 1h from 2025-01-06", "1,32")
    syntax(L, "every month on 1,,2 at 09:00 for 1h from 2025-01-06", "1,,2")
    syntax(L, "every month on 01 at 09:00 for 1h from 2025-01-06", "01")
    t = "every month on mon at 09:00 for 1h from 2025-01-06"
    syntax(L, t, position=t.index(" mon ") + 1)


@case("holdout", "core", "h-syntax-end-and-blank", "")
def _(L, cli):
    syntax(L, "", position=0)
    syntax(L, "   ", position=3)
    syntax(L, "every day at 10:00 for 1h from  ", position=len("every day at 10:00 for 1h from  "))
    syntax(L, "every 2", position=7)
    syntax(L, "weekly at 10:00 for 1h from 2025-01-06", position=0)
    syntax(L, "\t every day at 10:00 for 1h from 2025-01-06 times")


@case("holdout", "core", "h-syntax-values", "")
def _(L, cli):
    syntax(L, "every day at 10:00 for 0m from 2025-01-06", "0m")
    syntax(L, "every day at 10:00 for 1.5h from 2025-01-06", "1.5h")
    syntax(L, "every day at 24:00 for 1h from 2025-01-06", "24:00")
    syntax(L, "every day at 09:00,09:00 for 1h from 2025-01-06", "09:00,09:00")
    syntax(L, "every 0 days at 09:00 for 1h from 2025-01-06", "0")
    syntax(L, "every +2 days at 09:00 for 1h from 2025-01-06", "+2")
    syntax(L, "every day at 09:00 for 1h from 2025-1-06", "2025-1-06")
    t = "every day at 09:00 for 1h from 2025-01-06 times 0"
    syntax(L, t, position=len(t) - 1)
    t = "every day at 09:00 for 1h from 2025-01-06 until 2025-01-05"
    syntax(L, t, position=t.index("2025-01-05"))
    syntax(L, "every day at 09:00 for 1h from ２０２５-01-06", "２")
    syntax(L, "every day at 09:00 for 1h from 2025-01-06 forever and ever", "forever")


@case("holdout", "core", "h-syntax-error-inside-plan", "")
def _(L, cli):
    text = "every week on wed at 15:00  for 1h from 2025-13-03"
    p = P(R("h-ok", "every day at 09:00 for 1h from 2025-01-01"), R("h-broken", text))
    exc = plan_error(L, p, must_contain="h-broken")
    if not isinstance(exc, L.RuleSyntaxError):
        raise Fail(f"expected: RuleSyntaxError\ngot:      {type(exc).__name__}")
    eq(getattr(exc, "position", None), text.index("2025-13-03"), "position: ")
    if not issubclass(L.RuleSyntaxError, L.PlanError):
        raise Fail("RuleSyntaxError must be a subclass of PlanError")


@case("holdout", "core", "h-week-interval-from-sunday", "")
def _(L, cli):
    p = P(R("h-tri", "every 3 weeks on sun,mon at 07:00 for 1h from 2025-03-02"), tz=NY)
    occ(L, p, "2025-03-01T00:00Z", "2025-04-10T00:00Z", [
        ("h-tri", "2025-03-02T07:00", "2025-03-02T07:00:00-05:00", "2025-03-02T08:00:00-05:00"),
        ("h-tri", "2025-03-17T07:00", "2025-03-17T07:00:00-04:00", "2025-03-17T08:00:00-04:00"),
        ("h-tri", "2025-03-23T07:00", "2025-03-23T07:00:00-04:00", "2025-03-23T08:00:00-04:00"),
        ("h-tri", "2025-04-07T07:00", "2025-04-07T07:00:00-04:00", "2025-04-07T08:00:00-04:00"),
    ])


@case("holdout", "core", "h-month-days-skip-and-merge", "")
def _(L, cli):
    p = P(R("h-ends", "every 2 months on 30,last,29 at 06:00 for 30m from 2024-12-30"))
    keys(L, p, "2024-12-01T00:00Z", "2025-05-01T00:00Z",
         ["2024-12-30T06:00", "2024-12-31T06:00", "2025-02-28T06:00", "2025-04-29T06:00", "2025-04-30T06:00"])


@case("holdout", "core", "h-times-counts-keys-in-order", "")
def _(L, cli):
    p = P(R("h-few", "every month on last,30 at 21:00,09:00 for 1h from 2025-04-01 times 3"))
    keys(L, p, "2025-04-01T00:00Z", "2025-08-01T00:00Z",
         ["2025-04-30T09:00", "2025-04-30T21:00", "2025-05-30T09:00"])
    keys(L, p, "2025-05-30T12:00+02:00", "2025-09-01T00:00Z", [])


@case("holdout", "core", "h-until-inclusive", "")
def _(L, cli):
    p = P(R("h-odd", "every 2 days at 10:00 for 1h from 2025-07-01 until 2025-07-05"))
    keys(L, p, "2025-06-01T00:00Z", "2025-08-01T00:00Z",
         ["2025-07-01T10:00", "2025-07-03T10:00", "2025-07-05T10:00"])


@case("holdout", "core", "h-duration-across-fall-back", "")
def _(L, cli):
    p = P(R("h-autumn", "every week on sun at 00:30 for 4h from 2025-10-26 times 1"))
    occ(L, p, "2025-10-25T00:00Z", "2025-10-27T00:00Z",
        [("h-autumn", "2025-10-26T00:30", "2025-10-26T00:30:00+02:00", "2025-10-26T03:30:00+01:00")])


@case("holdout", "core", "h-half-hour-gap", "")
def _(L, cli):
    p = P(R("h-island", "every day at 02:15 for 30m from 2025-10-05 times 1"), tz="Australia/Lord_Howe")
    occ(L, p, "2025-10-04T00:00Z", "2025-10-06T00:00Z",
        [("h-island", "2025-10-05T02:15", "2025-10-05T02:45:00+11:00", "2025-10-05T03:15:00+11:00")])


@case("holdout", "core", "h-gap-duplicate-and-times", "")
def _(L, cli):
    p = P(R("h-spring", "every day at 03:00,02:00,02:59 for 10m from 2025-03-09 times 4"), tz=NY)
    occ(L, p, "2025-03-08T00:00Z", "2025-03-20T00:00Z", [
        ("h-spring", "2025-03-09T02:00", "2025-03-09T03:00:00-04:00", "2025-03-09T03:10:00-04:00"),
        ("h-spring", "2025-03-09T02:59", "2025-03-09T03:59:00-04:00", "2025-03-09T04:09:00-04:00"),
        ("h-spring", "2025-03-10T02:00", "2025-03-10T02:00:00-04:00", "2025-03-10T02:10:00-04:00"),
        ("h-spring", "2025-03-10T02:59", "2025-03-10T02:59:00-04:00", "2025-03-10T03:09:00-04:00"),
    ])


@case("holdout", "core", "h-repeated-hour-southern", "")
def _(L, cli):
    p = P(R("h-south", "every day at 02:30 for 1h from 2025-04-06 times 1"), tz="Australia/Sydney")
    occ(L, p, "2025-04-05T00:00Z", "2025-04-07T00:00Z",
        [("h-south", "2025-04-06T02:30", "2025-04-06T02:30:00+11:00", "2025-04-06T02:30:00+10:00")])


@case("holdout", "core", "h-override-validation", "")
def _(L, cli):
    def bad(rule, *ovs):
        plan_error(L, P(rule, overrides=list(ovs)), "2025-02-01T00:00Z", "2025-02-02T00:00Z", rule["id"])

    one = R("h-one", "every week on tue at 11:00 for 1h from 2025-01-07 times 4")
    two = R("h-two", "every day at 08:00,18:00 for 1h from 2025-01-07")
    bad(one, {"rule": "h-one", "key": "2025-01-14", "action": "cancel"},
        {"rule": "h-one", "key": "2025-01-14T11:00", "action": "move", "to": "2025-01-14T12:00"})
    bad(one, {"rule": "h-one", "key": "2025-01-14T12:00", "action": "cancel"})
    bad(one, {"rule": "h-one", "key": "2025-02-04", "action": "cancel"})
    bad(two, {"rule": "h-two", "key": "2025-01-08", "action": "cancel"})
    bad(two, {"rule": "h-two", "key": "2025-01-08T08:00", "action": "postpone"})
    bad(two, {"rule": "h-two", "key": "2025-01-08T08:00", "action": "move"})
    plan_error(L, P(one, overrides=[{"rule": "h-none", "key": "2025-01-14", "action": "cancel"}]))
    keys(L, P(one, overrides=[{"rule": "h-one", "key": "2025-01-28", "action": "cancel"}]),
         "2025-01-01T00:00Z", "2025-03-01T00:00Z", ["2025-01-07T11:00", "2025-01-14T11:00", "2025-01-21T11:00"])


@case("holdout", "core", "h-move-into-gap-and-before-from", "")
def _(L, cli):
    p = P(R("h-noon", "every day at 12:00 for 45m from 2025-03-28 times 2"),
          R("h-early", "every day at 12:00 for 45m from 2025-03-28 times 1"),
          overrides=[{"rule": "h-noon", "key": "2025-03-29", "action": "move", "to": "2025-03-30T02:15"},
                     {"rule": "h-early", "key": "2025-03-28T12:00", "action": "move", "to": "2025-03-01T08:00", "for": "2h"}])
    occ(L, p, "2025-03-28T00:00Z", "2025-04-02T00:00Z", [
        ("h-noon", "2025-03-28T12:00", "2025-03-28T12:00:00+01:00", "2025-03-28T12:45:00+01:00"),
        ("h-noon", "2025-03-29T12:00", "2025-03-30T03:15:00+02:00", "2025-03-30T04:00:00+02:00"),
    ])
    occ(L, p, "2025-03-01T00:00Z", "2025-03-02T00:00Z",
        [("h-early", "2025-03-28T12:00", "2025-03-01T08:00:00+01:00", "2025-03-01T10:00:00+01:00")])


@case("holdout", "core", "h-move-long-into-window", "")
def _(L, cli):
    p = P(R("h-wed", "every week on wed at 15:00 for 1h from 2025-09-03"),
          overrides=[{"rule": "h-wed", "key": "2025-09-10", "action": "move", "to": "2025-09-16T23:30", "for": "1d"}])
    occ(L, p, "2025-09-17T00:00+02:00", "2025-09-18T00:00+02:00", [
        ("h-wed", "2025-09-10T15:00", D("2025-09-16", "23:30"), D("2025-09-17", "23:30")),
        ("h-wed", "2025-09-17T15:00", D("2025-09-17", "15:00"), D("2025-09-17", "16:00")),
    ])
    occ(L, p, "2025-09-10T00:00+02:00", "2025-09-11T00:00+02:00", [])


@case("holdout", "core", "h-long-occurrence-overlap", "")
def _(L, cli):
    p = P(R("h-trip", "every week on fri at 18:00 for 2d12h from 2025-08-01"))
    occ(L, p, "2025-08-04T05:00+02:00", "2025-08-04T06:30+02:00",
        [("h-trip", "2025-08-01T18:00", D("2025-08-01", "18:00"), D("2025-08-04", "06:00"))])
    occ(L, p, "2025-08-04T06:00+02:00", "2025-08-04T07:00+02:00", [])
    occ(L, p, "2025-08-04T04:00:00Z", "2025-08-04T04:00:01Z", [])
    keys(L, p, "2025-08-04T03:59:59Z", "2025-08-04T04:00:00Z", ["2025-08-01T18:00"])


@case("holdout", "core", "h-ordering-ties-and-zones", "")
def _(L, cli):
    day = "2025-06-02"
    p = P(R("h-p", f"every day at 09:00 for 2h from {day} times 1"),
          R("h-q", f"every day at 09:00 for 1h from {day} times 1", priority=1),
          R("h-r", f"every day at 09:00 for 1h from {day} times 1"),
          R("h-s", f"every day at 12:30 for 1h from {day} times 1", priority=5, timezone="Asia/Kolkata"),
          R("h-u", f"every day at 07:00 for 1h from {day} times 1", priority=1, timezone="UTC"))
    occ(L, p, "2025-06-02T00:00Z", "2025-06-03T00:00Z", [
        ("h-s", f"{day}T12:30", f"{day}T12:30:00+05:30", f"{day}T13:30:00+05:30"),
        ("h-q", f"{day}T09:00", D(day, "09:00"), D(day, "10:00")),
        ("h-u", f"{day}T07:00", f"{day}T07:00:00+00:00", f"{day}T08:00:00+00:00"),
        ("h-r", f"{day}T09:00", D(day, "09:00"), D(day, "10:00")),
        ("h-p", f"{day}T09:00", D(day, "09:00"), D(day, "11:00")),
    ])


@case("holdout", "core", "h-agenda-three-levels", "")
def _(L, cli):
    day = "2025-06-02"
    p = P(R("h-c", f"every day at 09:00 for 3h from {day} times 1"),
          R("h-b", f"every day at 09:30 for 1h from {day} times 1", priority=1),
          R("h-a", f"every day at 10:00 for 1h from {day} times 1", priority=2),
          R("h-d", f"every day at 13:00 for 1h from {day} times 1"),
          R("h-e", f"every day at 13:00 for 2h from {day} times 1"))
    agenda(L, p, f"{day}T00:00+02:00", "2025-06-03T00:00+02:00", [
        ("h-c", f"{day}T09:00", D(day, "09:00"), D(day, "09:30")),
        ("h-b", f"{day}T09:30", D(day, "09:30"), D(day, "10:00")),
        ("h-a", f"{day}T10:00", D(day, "10:00"), D(day, "11:00")),
        ("h-c", f"{day}T09:00", D(day, "11:00"), D(day, "12:00")),
        ("h-d", f"{day}T13:00", D(day, "13:00"), D(day, "14:00")),
        ("h-e", f"{day}T13:00", D(day, "14:00"), D(day, "15:00")),
    ])


@case("holdout", "core", "h-agenda-min-segment", "")
def _(L, cli):
    day = "2025-06-02"
    p = P(R("h-x", f"every day at 09:00 for 1h from {day} times 1"),
          R("h-y", f"every day at 09:10 for 35m from {day} times 1", priority=1),
          R("h-z", f"every day at 13:00 for 5m from {day} times 1"),
          R("h-w", f"every day at 08:50 for 30m from {day} times 1", priority=-1),
          R("h-t", f"every day at 15:00 for 1h from {day} times 1", priority=-1),
          R("h-v", f"every day at 15:20 for 20m from {day} times 1"),
          min_segment="20m")
    agenda(L, p, f"{day}T00:00+02:00", "2025-06-03T00:00+02:00", [
        ("h-y", f"{day}T09:10", D(day, "09:10"), D(day, "09:45")),
        ("h-z", f"{day}T13:00", D(day, "13:00"), D(day, "13:05")),
        ("h-t", f"{day}T15:00", D(day, "15:00"), D(day, "15:20")),
        ("h-v", f"{day}T15:20", D(day, "15:20"), D(day, "15:40")),
        ("h-t", f"{day}T15:00", D(day, "15:40"), D(day, "16:00")),
    ])


@case("holdout", "core", "h-agenda-window-cut", "")
def _(L, cli):
    day = "2025-06-02"
    p = P(R("h-wide", f"every day at 09:00 for 2h from {day} times 1"),
          R("h-top", f"every day at 09:40 for 20m from {day} times 1", priority=4),
          min_segment="40m")
    agenda(L, p, f"{day}T09:30+02:00", f"{day}T09:50+02:00", [
        ("h-wide", f"{day}T09:00", D(day, "09:30"), D(day, "09:40")),
        ("h-top", f"{day}T09:40", D(day, "09:40"), D(day, "09:50")),
    ])
    # h-top ends exactly at the window start, so it is not part of this agenda at all
    agenda(L, p, f"{day}T10:00+02:00", f"{day}T10:30+02:00",
           [("h-wide", f"{day}T09:00", D(day, "10:00"), D(day, "10:30"))])
    p["min_segment"] = "1h1m"
    agenda(L, p, f"{day}T09:30+02:00", f"{day}T09:50+02:00",
           [("h-top", f"{day}T09:40", D(day, "09:40"), D(day, "09:50"))])


@case("holdout", "core", "h-agenda-rule-overlapping-itself", "")
def _(L, cli):
    p = P(R("h-roll", "every day at 09:00 for 36h from 2025-06-01"))
    agenda(L, p, "2025-06-02T00:00+02:00", "2025-06-04T00:00+02:00", [
        ("h-roll", "2025-06-01T09:00", D("2025-06-02", "00:00"), D("2025-06-02", "21:00")),
        ("h-roll", "2025-06-02T09:00", D("2025-06-02", "21:00"), D("2025-06-03", "21:00")),
        ("h-roll", "2025-06-03T09:00", D("2025-06-03", "21:00"), D("2025-06-04", "00:00")),
    ])


@case("holdout", "core", "h-performance-agenda", "")
def _(L, cli):
    rules = _old_rules("h-r", 150, "1975-06-15")
    for r in rules:
        r["rule"] += " until 2090-12-31"
        r["priority"] = int(r["id"][3:]) % 7
    p = P(*rules, tz=NY, overrides=[{"rule": "h-r0", "key": "1980-02-29", "action": "cancel"},
                                    {"rule": "h-r2", "key": "1999-12-31T02:30", "action": "cancel"}])
    t0 = time.time()
    total = 0
    for d in range(1, 21):
        total += len(L.occurrences(p, f"2071-10-{d:02d}T00:00-04:00", f"2071-10-{d + 1:02d}T00:00-04:00"))
        L.agenda(p, f"2071-10-{d:02d}T00:00-04:00", f"2071-10-{d + 1:02d}T00:00-04:00")
    if time.time() - t0 > 3.0:
        raise Fail(f"took {time.time() - t0:.1f}s, limit 3s")
    eq(total, PERF_HOLDOUT_TOTAL)


PERF_HOLDOUT_TOTAL = 1267  # cross-checked with an independent brute-force count


@case("holdout", "core", "h-cli", "")
def _(L, cli):
    day = "2025-06-02"
    p = P(R("h-base", f"every day at 09:00 for 1h from {day} times 1"),
          R("h-over", f"every day at 09:30 for 1h from {day} times 1", priority=1))
    out, _ = run_cli(cli, ["agenda", f"{day}T00:00+02:00", f"{day}T09:45+02:00"], p, 0)
    eq(out, [f"{day}T09:00:00+02:00 {day}T09:30:00+02:00 h-base {day}T09:00",
             f"{day}T09:30:00+02:00 {day}T09:45:00+02:00 h-over {day}T09:30"])
    out, _ = run_cli(cli, ["agenda", "2025-07-02T00:00+02:00", "2025-07-02T09:45+02:00"], p, 0)
    eq(out, ["nothing scheduled"])
    text = "every day  at 09:00 for 1h from 2025-06-02 times none"
    p["rules"].append(R("h-typo", text))
    _, err = run_cli(cli, ["occurrences", f"{day}T00:00+02:00", f"{day}T09:45+02:00"], p, 2)
    if len(err) < 3 or not err[0].startswith("error: ") or err[-2:] != [text, " " * text.index("none") + "^"]:
        raise Fail(f"expected stderr: 'error: <message>', the rule text, a caret under column {text.index('none')}\ngot:      {err!r}")
    if "h-typo" not in err[0]:
        raise Fail(f"expected the rule id in the message\ngot:      {err[0]!r}")
    _, err = run_cli(cli, ["occurrences", f"{day}T00:00+02:00", f"{day}T09:45+02:00", "/nonexistent/h-plan.json"], None, 1)
    if not err or not err[0].startswith("error: "):
        raise Fail(f"expected stderr starting with 'error: '\ngot:      {err!r}")
    _, err = run_cli(cli, ["agenda", f"{day}T00:00", f"{day}T09:45+02:00"], P(), 2)
    if not err or not err[0].startswith("error: "):
        raise Fail(f"expected stderr starting with 'error: '\ngot:      {err!r}")


@case("holdout", "core", "h-plan-validation", "")
def _(L, cli):
    ok = "every day at 09:00 for 1h from 2025-01-01"
    plan_error(L, P(R("h-dup", ok), R("h-dup", ok)), must_contain="h-dup")
    plan_error(L, P(R("h-flag", ok, priority=True)), must_contain="h-flag")
    plan_error(L, P(R("h-text", ok, priority="3")), must_contain="h-text")
    plan_error(L, P(R("h-zone", ok, timezone="Europe/Atlantis")), must_contain="h-zone")
    plan_error(L, P(R("h bad id", ok)))
    plan_error(L, P(R("", ok)))
    plan_error(L, {"timezone": BERLIN})
    plan_error(L, {"rules": []})
    plan_error(L, P(R("h-fine", ok), min_segment="soon"))
    keys(L, P(R("h_Fine-2", ok, priority=-4)), "2025-01-01T00:00Z", "2025-01-02T00:00Z", ["2025-01-01T09:00"])


@case("holdout", "core", "h-window-arguments", "")
def _(L, cli):
    p = P(R("h-hourly", "every day at 00:00,06:00,12:00,18:00 for 1h from 2025-01-01"))
    keys(L, p, "2025-01-02T05:59:59-05:00", "2025-01-02T17:00:01Z", ["2025-01-02T12:00", "2025-01-02T18:00"])
    for start, end in [("2025-01-02T00:00", "2025-01-03T00:00Z"),
                       ("2025-01-02T00:00Z", "2025-01-02T00:00Z"),
                       ("2025-01-02T12:00+01:00", "2025-01-02T10:00-01:00"),
                       ("2025-01-02 00:00Z", "2025-01-03T00:00Z"),
                       ("2025-01-02", "2025-01-03"),
                       ("2025-01-02T00:00Z", "2025-02-30T00:00Z")]:
        plan_error(L, p, start, end)
        plan_error(L, p, start, end, fn=L.agenda)


@case("holdout", "core", "h-whole-plan-validated", "")
def _(L, cli):
    good = R("h-good", "every week on thu at 16:00 for 1h from 2015-01-01")
    p = P(good, overrides=[{"rule": "h-good", "key": "2035-06-08", "action": "cancel"}])
    plan_error(L, p, "2025-01-01T00:00Z", "2025-01-08T00:00Z", "h-good")
    p = P(good, overrides=[{"rule": "h-good", "key": "2035-06-07", "action": "cancel"},
                           {"rule": "h-good", "key": "2014-12-25", "action": "cancel"}])
    plan_error(L, p, "2025-01-01T00:00Z", "2025-01-08T00:00Z", "h-good")
    p = P(good, overrides=[{"rule": "h-good", "key": "2035-06-07", "action": "cancel"}])
    keys(L, p, "2025-01-01T00:00Z", "2025-01-08T00:00Z", ["2025-01-02T16:00"])
    p = P(good, R("h-never", "every day at 09:00 for 1h from 2099-01-01 until 2098-01-01"))
    plan_error(L, p, "2025-01-01T00:00Z", "2025-01-08T00:00Z", "h-never")


# ================================================================ holdout / v2

@case("holdout", "v2", "h-holiday-skip-ranges", "")
def _(L, cli):
    rule = R("h-tt", "every week on tue,thu at 16:00 for 1h from 2025-12-16 until 2026-01-01", holiday="skip")
    hol = ["2025-12-25", "2025-12-30..2026-01-01", "2025-12-31..2026-01-02"]
    p = P(rule, holidays=hol, overrides=[{"rule": "h-tt", "key": "2025-12-18", "action": "cancel"}])
    keys(L, p, "2025-12-01T00:00Z", "2026-01-31T00:00Z", ["2025-12-16T16:00", "2025-12-23T16:00"])
    p = P(rule, holidays=hol, overrides=[{"rule": "h-tt", "key": "2025-12-25", "action": "cancel"}])
    plan_error(L, p, "2025-12-01T00:00Z", "2026-01-31T00:00Z", "h-tt")
    keep = R("h-keep", "every week on thu at 16:00 for 1h from 2025-12-25 times 1")
    keys(L, P(keep, holidays=hol), "2025-12-01T00:00Z", "2026-01-31T00:00Z", ["2025-12-25T16:00"])


@case("holdout", "v2", "h-holiday-shift-past-until", "")
def _(L, cli):
    p = P(R("h-first", "every month on 1 at 10:00 for 1h from 2025-01-01 until 2025-05-01", holiday="shift"),
          holidays=["2025-05-01..2025-05-04", "2025-01-01"])
    occ(L, p, "2025-01-01T00:00Z", "2025-06-30T00:00Z", [
        ("h-first", "2025-01-01T10:00", "2025-01-02T10:00:00+01:00", "2025-01-02T11:00:00+01:00"),
        ("h-first", "2025-02-01T10:00", "2025-02-01T10:00:00+01:00", "2025-02-01T11:00:00+01:00"),
        ("h-first", "2025-03-01T10:00", "2025-03-01T10:00:00+01:00", "2025-03-01T11:00:00+01:00"),
        ("h-first", "2025-04-01T10:00", "2025-04-01T10:00:00+02:00", "2025-04-01T11:00:00+02:00"),
        ("h-first", "2025-05-01T10:00", "2025-05-05T10:00:00+02:00", "2025-05-05T11:00:00+02:00"),
    ])
    occ(L, p, "2025-05-05T00:00+02:00", "2025-05-06T00:00+02:00",
        [("h-first", "2025-05-01T10:00", "2025-05-05T10:00:00+02:00", "2025-05-05T11:00:00+02:00")])


@case("holdout", "v2", "h-holiday-shift-two-into-one-slot", "")
def _(L, cli):
    p = P(R("h-tf", "every week on thu,fri at 10:00 for 1h from 2025-05-01 times 2", holiday="shift"),
          holidays=["2025-05-01..2025-05-02"])
    occ(L, p, "2025-04-01T00:00Z", "2025-07-01T00:00Z", [
        ("h-tf", "2025-05-01T10:00", D("2025-05-03", "10:00"), D("2025-05-03", "11:00")),
        ("h-tf", "2025-05-08T10:00", D("2025-05-08", "10:00"), D("2025-05-08", "11:00")),
    ])


@case("holdout", "v2", "h-holiday-shift-vs-overrides", "")
def _(L, cli):
    p = P(R("h-mt", "every week on mon,tue at 09:00 for 1h from 2025-04-14 until 2025-04-27", holiday="shift"),
          R("h-wd", "every week on wed at 09:00 for 1h from 2025-04-23 times 1", holiday="shift"),
          holidays=["2025-04-21", "2025-04-23"],
          overrides=[{"rule": "h-mt", "key": "2025-04-22T09:00", "action": "cancel"},
                     {"rule": "h-wd", "key": "2025-04-23", "action": "move", "to": "2025-04-25T14:00"}])
    occ(L, p, "2025-04-01T00:00Z", "2025-05-31T00:00Z", [
        ("h-mt", "2025-04-14T09:00", D("2025-04-14", "09:00"), D("2025-04-14", "10:00")),
        ("h-mt", "2025-04-15T09:00", D("2025-04-15", "09:00"), D("2025-04-15", "10:00")),
        ("h-wd", "2025-04-23T09:00", D("2025-04-25", "14:00"), D("2025-04-25", "15:00")),
    ])
    p["overrides"] = [{"rule": "h-mt", "key": "2025-04-21T09:00", "action": "cancel"}]
    plan_error(L, p, "2025-04-01T00:00Z", "2025-05-31T00:00Z", "h-mt")


@case("holdout", "v2", "h-holiday-shift-onto-gap", "")
def _(L, cli):
    p = P(R("h-sat", "every week on sat at 02:30 for 1h from 2025-03-22 times 2", holiday="shift"),
          holidays=["2025-03-29"])
    occ(L, p, "2025-03-01T00:00Z", "2025-05-01T00:00Z", [
        ("h-sat", "2025-03-22T02:30", "2025-03-22T02:30:00+01:00", "2025-03-22T03:30:00+01:00"),
        ("h-sat", "2025-03-29T02:30", "2025-03-30T03:30:00+02:00", "2025-03-30T04:30:00+02:00"),
    ])


@case("holdout", "v2", "h-holiday-validation", "")
def _(L, cli):
    ok = "every day at 09:00 for 1h from 2025-01-01"
    plan_error(L, P(R("h-a1", ok), holidays=["2025-05-04..2025-05-01"]))
    plan_error(L, P(R("h-a2", ok), holidays=["2025-02-30"]))
    plan_error(L, P(R("h-a3", ok), holidays=["2025-05-01...2025-05-04"]))
    plan_error(L, P(R("h-a4", ok, holiday="drop"), holidays=[]), must_contain="h-a4")
    plan_error(L, P(R("h-a5", "every 4 hours for 1h from 2025-01-01T00:00", holiday="shift")), must_contain="h-a5")
    keys(L, P(R("h-a6", ok + " times 1", holiday="keep"), holidays=["2025-01-01..2025-01-01"]),
         "2025-01-01T00:00Z", "2025-01-02T00:00Z", ["2025-01-01T09:00"])


@case("holdout", "v2", "h-minute-rule-through-fall-back", "")
def _(L, cli):
    p = P(R("h-45", "every 45 minutes for 10m from 2025-11-02T00:30 until 2025-11-02"), tz=NY)
    occ(L, p, "2025-11-02T05:00Z", "2025-11-02T07:30Z", [
        ("h-45", "2025-11-02T05:15Z", "2025-11-02T01:15:00-04:00", "2025-11-02T01:25:00-04:00"),
        ("h-45", "2025-11-02T06:00Z", "2025-11-02T01:00:00-05:00", "2025-11-02T01:10:00-05:00"),
        ("h-45", "2025-11-02T06:45Z", "2025-11-02T01:45:00-05:00", "2025-11-02T01:55:00-05:00"),
    ])
    keys(L, p, "2025-11-03T03:00Z", "2025-11-03T09:00Z",
         ["2025-11-03T03:00Z", "2025-11-03T03:45Z", "2025-11-03T04:30Z"])


@case("holdout", "v2", "h-hour-rule-skip-times-overrides", "")
def _(L, cli):
    rule = R("h-12", "every 12 hours for 1h from 2025-12-23T06:00 times 4", holiday="skip")
    hol = ["2025-12-24..2025-12-25"]
    p = P(rule, holidays=hol, overrides=[{"rule": "h-12", "key": "2025-12-26T05:00Z", "action": "cancel"}])
    keys(L, p, "2025-12-01T00:00Z", "2026-01-31T00:00Z",
         ["2025-12-23T05:00Z", "2025-12-23T17:00Z", "2025-12-26T17:00Z"])
    for key in ["2025-12-24T05:00Z", "2025-12-23T06:00", "2025-12-27T05:00Z", "2025-12-23T06:00Z", "2025-12-23"]:
        plan_error(L, P(rule, holidays=hol, overrides=[{"rule": "h-12", "key": key, "action": "cancel"}]),
                   "2025-12-01T00:00Z", "2026-01-31T00:00Z", "h-12")


@case("holdout", "v2", "h-minute-rule-anchor-gap-and-agenda", "")
def _(L, cli):
    p = P(R("h-2h", "every 2 hours for 30m from 2025-03-30T02:30 times 2"))
    occ(L, p, "2025-03-29T00:00Z", "2025-04-01T00:00Z", [
        ("h-2h", "2025-03-30T01:30Z", "2025-03-30T03:30:00+02:00", "2025-03-30T04:00:00+02:00"),
        ("h-2h", "2025-03-30T03:30Z", "2025-03-30T05:30:00+02:00", "2025-03-30T06:00:00+02:00"),
    ])
    day = "2025-06-02"
    p = P(R("h-work", f"every day at 09:00 for 1h from {day} times 1"),
          R("h-tick", f"every 30 minutes for 10m from {day}T09:00 times 3", priority=1))
    agenda(L, p, f"{day}T00:00+02:00", "2025-06-03T00:00+02:00", [
        ("h-tick", f"{day}T07:00Z", D(day, "09:00"), D(day, "09:10")),
        ("h-work", f"{day}T09:00", D(day, "09:10"), D(day, "09:30")),
        ("h-tick", f"{day}T07:30Z", D(day, "09:30"), D(day, "09:40")),
        ("h-work", f"{day}T09:00", D(day, "09:40"), D(day, "10:00")),
        ("h-tick", f"{day}T08:00Z", D(day, "10:00"), D(day, "10:10")),
    ])


@case("holdout", "v2", "h-minute-rule-text", "")
def _(L, cli):
    canon(L, "every minute for 1m from 2025-01-01T00:00", "every 1 minute for 1m from 2025-01-01T00:00")
    canon(L, "EVERY 1 HOURS FOR 60M FROM 2025-01-01T23:59 UNTIL 2025-01-01",
          "every 1 hour for 1h from 2025-01-01T23:59 until 2025-01-01")
    syntax(L, "every 15 minutes on mon for 5m from 2025-01-06T08:00", "on")
    syntax(L, "every 15 minutes for 5m from 2025-01-06T08:00 until 2025-01-05", "2025-01-05")
    syntax(L, "every 15 minutes for 5m from 2025-01-06T24:00", "2025-01-06T24:00")
    syntax(L, "every day at 09:00 for 1h from 2025-01-06T08:00", "2025-01-06T08:00")
    syntax(L, "every 15 minutes for 5m from 2025-01-06 08:00", "2025-01-06")


@case("holdout", "v2", "h-minute-rule-performance", "")
def _(L, cli):
    rules = [R(f"h-m{n}", f"every {n} {'hours' if n % 2 else 'minutes'} for 2m from 1985-06-01T00:00",
               holiday="skip" if n % 3 == 0 else "keep") for n in range(1, 25)]
    p = P(*rules, tz="Asia/Tokyo", holidays=["2055-08-11", "1990-01-01..1990-01-03"])
    t0 = time.time()
    for h in range(4):
        got = L.occurrences(p, f"2055-08-10T{h + 12:02d}:00Z", f"2055-08-10T{h + 13:02d}:00Z")
        eq(len([o for o in got if o["rule"] == "h-m2"]), 30)
        eq(len([o for o in got if o["rule"] == "h-m6"]), 10 if h < 3 else 0)  # 15:00Z is midnight in Tokyo
        L.agenda(p, f"2055-08-10T{h + 12:02d}:00Z", f"2055-08-10T{h + 13:02d}:00Z")
    if time.time() - t0 > 3.0:
        raise Fail(f"took {time.time() - t0:.1f}s, limit 3s")
