"""Hidden test cases.

suite: "qa"      -> failures are shown to Codex as a QA report (feedback tests)
       "holdout" -> never shown; used only for the final score
scope: "core"    -> what turn 1 asks for (SPEC.md as shipped)
       "v2"      -> the two additions requested in turn 3
"""

TESTS = []


class Fail(Exception):
    pass


def case(suite, scope, name, desc):
    def deco(fn):
        TESTS.append({"suite": suite, "scope": scope, "name": name, "desc": desc, "fn": fn})
        return fn

    return deco


def G(members, *expenses, currency="USD", rates=None):
    g = {"currency": currency, "members": list(members), "expenses": list(expenses)}
    if rates is not None:
        g["rates"] = rates
    return g


def E(eid, payer, amount, split, **extra):
    e = {"id": eid, "payer": payer, "amount": amount, "split": split}
    e.update(extra)
    return e


def eq(actual, expected):
    if actual != expected:
        raise Fail(f"expected: {expected!r}\ngot:      {actual!r}")


def bal(L, g, expected):
    try:
        got = L.balances(g)
    except Exception as exc:  # noqa: BLE001
        raise Fail(f"expected: {expected!r}\ngot:      raised {type(exc).__name__}: {exc}")
    if isinstance(got, dict):
        got = dict(got)
    eq(got, expected)


def transfers(L, g, expected):
    try:
        got = L.settle(g)
    except Exception as exc:  # noqa: BLE001
        raise Fail(f"expected: {expected!r}\ngot:      raised {type(exc).__name__}: {exc}")
    try:
        got = [tuple(t) for t in got]
    except TypeError:
        pass
    eq(got, expected)


def invalid(L, g, must_contain=None):
    try:
        got = L.balances(g)
    except L.ValidationError as exc:
        if must_contain and must_contain not in str(exc):
            raise Fail(f"expected: ValidationError mentioning {must_contain!r}\ngot:      ValidationError({str(exc)!r})")
        return
    except Exception as exc:  # noqa: BLE001
        raise Fail(f"expected: ValidationError\ngot:      {type(exc).__name__}: {exc}")
    raise Fail(f"expected: ValidationError\ngot:      no error, returned {got!r}")


def cli_lines(cli, cmd, g, code=0):
    rc, out, err = cli([cmd], g)
    if rc != code:
        raise Fail(f"expected: exit status {code}\ngot:      exit status {rc} (stderr: {err.strip()[:200]!r})")
    return out.strip().splitlines()


# ---------------------------------------------------------------- QA / core

@case("qa", "core", "equal-leftover-alphabetical",
      "Equal split of 100.00 among quinn, rory, sage (members listed sage, quinn, rory): the extra cent goes to the name that sorts first.")
def _(L, cli):
    bal(L, G(["sage", "quinn", "rory"], E("q1", "sage", "100.00", {"type": "equal"})),
        {"quinn": -3334, "rory": -3333, "sage": 6667})


@case("qa", "core", "equal-leftover-several-cents",
      "Equal split of 0.05 among 3 people: the 2 leftover cents go one each to the first two names.")
def _(L, cli):
    bal(L, G(["quinn", "rory", "sage", "tess"],
             E("q2", "tess", "0.05", {"type": "equal", "among": ["sage", "rory", "quinn"]})),
        {"quinn": -2, "rory": -2, "sage": -1, "tess": 5})


@case("qa", "core", "money-exact-cents",
      'Amount "4.35" must be exactly 435 cents.')
def _(L, cli):
    bal(L, G(["quinn", "rory"], E("q3", "quinn", "4.35", {"type": "equal", "among": ["rory"]})),
        {"quinn": 435, "rory": -435})


@case("qa", "core", "names-normalised",
      "Names are case-insensitive, trimmed, and returned in lowercase.")
def _(L, cli):
    bal(L, G([" Quinn", "RORY"], E("q4", "quinn ", "10.00", {"type": "equal", "among": ["QUINN", "rory"]})),
        {"quinn": 500, "rory": -500})


@case("qa", "core", "duplicate-members",
      'members ["quinn", "Quinn "] name the same person twice: must be a ValidationError.')
def _(L, cli):
    invalid(L, G(["quinn", "Quinn "]))


@case("qa", "core", "amount-json-number",
      "An amount given as a JSON number (12.5) instead of a string: ValidationError mentioning the expense id.")
def _(L, cli):
    invalid(L, G(["quinn", "rory"], E("qa-n1", "quinn", 12.5, {"type": "equal"})), "qa-n1")


@case("qa", "core", "amount-three-decimals",
      'Amount "10.005" has three decimal places: ValidationError mentioning the expense id.')
def _(L, cli):
    invalid(L, G(["quinn", "rory"], E("qa-d3", "quinn", "10.005", {"type": "equal"})), "qa-d3")


@case("qa", "core", "amount-zero",
      'Amount "0.00" is not greater than zero: ValidationError mentioning the expense id.')
def _(L, cli):
    invalid(L, G(["quinn", "rory"], E("qa-z0", "quinn", "0.00", {"type": "equal"})), "qa-z0")


@case("qa", "core", "exact-sum-mismatch",
      "Exact split of 50.00 where the parts add up to 45.00: ValidationError mentioning the expense id.")
def _(L, cli):
    invalid(L, G(["quinn", "rory", "sage"],
                 E("qa-x1", "quinn", "50.00", {"type": "exact", "amounts": {"rory": "20.00", "sage": "25.00"}})), "qa-x1")


@case("qa", "core", "percent-sum",
      "Percent split where the percentages add up to 90: ValidationError mentioning the expense id.")
def _(L, cli):
    invalid(L, G(["quinn", "rory"],
                 E("qa-p1", "quinn", "10.00", {"type": "percent", "percents": {"quinn": "50", "rory": "40"}})), "qa-p1")


@case("qa", "core", "percent-leftover-largest-fraction",
      "Percent split of 10.00 at 33.33 / 33.33 / 33.34: the leftover cent goes to the largest discarded fraction (sage).")
def _(L, cli):
    bal(L, G(["quinn", "rory", "sage", "tess"],
             E("q5", "tess", "10.00", {"type": "percent", "percents": {"quinn": "33.33", "rory": "33.33", "sage": "33.34"}})),
        {"quinn": -333, "rory": -333, "sage": -334, "tess": 1000})


@case("qa", "core", "unknown-participant",
      "Equal split among a name that is not a member: ValidationError mentioning the expense id.")
def _(L, cli):
    invalid(L, G(["quinn", "rory"], E("qa-u1", "quinn", "10.00", {"type": "equal", "among": ["quinn", "zed"]})), "qa-u1")


@case("qa", "core", "duplicate-expense-id",
      "Two expenses with the same id: ValidationError mentioning that id.")
def _(L, cli):
    invalid(L, G(["quinn", "rory"],
                 E("qa-dup", "quinn", "10.00", {"type": "equal"}),
                 E("qa-dup", "rory", "5.00", {"type": "equal"})), "qa-dup")


@case("qa", "core", "unknown-split-type",
      'Split type "ratio" is not supported: ValidationError mentioning the expense id.')
def _(L, cli):
    invalid(L, G(["quinn", "rory"], E("qa-t1", "quinn", "10.00", {"type": "ratio"})), "qa-t1")


@case("qa", "core", "equal-among-duplicate",
      'Equal split with among ["quinn", "QUINN"]: ValidationError mentioning the expense id.')
def _(L, cli):
    invalid(L, G(["quinn", "rory"], E("qa-a2", "rory", "10.00", {"type": "equal", "among": ["quinn", "QUINN"]})), "qa-a2")


@case("qa", "core", "settle-greedy",
      "Settlement for balances quinn +90.00, rory +10.00, sage -70.00, tess -30.00.")
def _(L, cli):
    g = G(["quinn", "rory", "sage", "tess"],
          E("q6", "quinn", "120.00", {"type": "equal"}),
          E("q7", "rory", "40.00", {"type": "exact", "amounts": {"sage": "40.00"}}))
    transfers(L, g, [("sage", "quinn", 7000), ("tess", "quinn", 2000), ("tess", "rory", 1000)])


@case("qa", "core", "settle-ties",
      "Settlement ties: equal debts are paid in name order, and equal credits are paid in name order.")
def _(L, cli):
    transfers(L, G(["quinn", "rory", "sage", "tess"], E("q8", "tess", "30.00", {"type": "equal", "among": ["sage", "rory", "quinn"]})),
              [("quinn", "tess", 1000), ("rory", "tess", 1000), ("sage", "tess", 1000)])
    transfers(L, G(["quinn", "rory", "sage"],
                   E("q9", "rory", "10.00", {"type": "equal", "among": ["sage"]}),
                   E("q10", "quinn", "10.00", {"type": "equal", "among": ["sage"]})),
              [("sage", "quinn", 1000), ("sage", "rory", 1000)])


@case("qa", "core", "cli-balances-format",
      "CLI `balances` output for quinn +5.00, rory -5.00, sage 0.00.")
def _(L, cli):
    g = G(["sage", "rory", "quinn"], E("q11", "quinn", "10.00", {"type": "equal", "among": ["quinn", "rory"]}))
    eq(cli_lines(cli, "balances", g), ["quinn: +5.00", "rory: -5.00", "sage: 0.00"])


@case("qa", "core", "cli-all-settled",
      "CLI `settle` with no expenses prints `all settled` and exits 0.")
def _(L, cli):
    eq(cli_lines(cli, "settle", G(["quinn", "rory"])), ["all settled"])


@case("qa", "core", "cli-validation-error",
      "CLI with invalid input (unknown payer): `error: ...` on stderr, exit status 2.")
def _(L, cli):
    rc, out, err = cli(["settle"], G(["quinn"], E("q12", "zed", "1.00", {"type": "equal"})))
    eq((rc, err.startswith("error:")), (2, True))


@case("qa", "core", "cli-bad-json",
      "CLI with a file that is not valid JSON: `error: ...` on stderr, exit status 1.")
def _(L, cli):
    rc, out, err = cli(["balances"], "{not json")
    eq((rc, err.startswith("error:")), (1, True))


# ----------------------------------------------------------- holdout / core

@case("holdout", "core", "equal-leftover-many", "")
def _(L, cli):
    names = ["gil", "fin", "eve", "dee", "cy", "ben", "ada"]
    exp = {n: -14 for n in names}
    exp.update({"ada": -15, "ben": -15, "hal": 100})
    bal(L, G(names + ["hal"], E("h1", "hal", "1.00", {"type": "equal", "among": names})), exp)


@case("holdout", "core", "money-float-traps", "")
def _(L, cli):
    bal(L, G(["dana", "eli"],
             E("h2", "dana", "0.29", {"type": "equal", "among": ["eli"]}),
             E("h3", "eli", "1.15", {"type": "equal", "among": ["dana"]}),
             E("h3b", "eli", "8.20", {"type": "equal", "among": ["dana"]})),
        {"dana": 29 - 115 - 820, "eli": -29 + 115 + 820})


@case("holdout", "core", "money-short-forms", "")
def _(L, cli):
    bal(L, G(["dana", "eli"],
             E("h4", "dana", "7", {"type": "equal", "among": ["eli"]}),
             E("h5", "eli", "7.5", {"type": "equal", "among": ["dana"]})),
        {"dana": -50, "eli": 50})


@case("holdout", "core", "money-invalid-forms", "")
def _(L, cli):
    for i, bad in enumerate(["-5.00", "1e3", "abc", "5.5.5", "", "+5", " 5.00"]):
        eid = f"h-bad{i}"
        try:
            invalid(L, G(["dana", "eli"], E(eid, "dana", bad, {"type": "equal"})), eid)
        except Fail as f:
            raise Fail(f"amount {bad!r}: {f}")


@case("holdout", "core", "exact-zero-part", "")
def _(L, cli):
    bal(L, G(["dana", "eli", "fay"],
             E("h6", "fay", "10.00", {"type": "exact", "amounts": {"dana": "10.00", "eli": "0.00"}})),
        {"dana": -1000, "eli": 0, "fay": 1000})


@case("holdout", "core", "exact-unknown-participant", "")
def _(L, cli):
    invalid(L, G(["dana", "eli"],
                 E("h-x2", "dana", "10.00", {"type": "exact", "amounts": {"eli": "5.00", "zed": "5.00"}})), "h-x2")


@case("holdout", "core", "exact-json-number", "")
def _(L, cli):
    invalid(L, G(["dana", "eli"],
                 E("h-x3", "dana", "10.00", {"type": "exact", "amounts": {"eli": 10.0}})), "h-x3")


@case("holdout", "core", "percent-tie-alphabetical", "")
def _(L, cli):
    bal(L, G(["dana", "eli", "fay"],
             E("h7", "fay", "1.01", {"type": "percent", "percents": {"eli": "50", "dana": "50"}})),
        {"dana": -51, "eli": -50, "fay": 101})


@case("holdout", "core", "percent-too-precise", "")
def _(L, cli):
    invalid(L, G(["dana", "eli", "fay"],
                 E("h-p2", "dana", "10.00", {"type": "percent", "percents": {"dana": "33.333", "eli": "33.333", "fay": "33.334"}})), "h-p2")


@case("holdout", "core", "percent-zero", "")
def _(L, cli):
    invalid(L, G(["dana", "eli"],
                 E("h-p3", "dana", "10.00", {"type": "percent", "percents": {"dana": "100", "eli": "0"}})), "h-p3")


@case("holdout", "core", "percent-keys-normalised", "")
def _(L, cli):
    bal(L, G(["dana", "eli"],
             E("h8", "dana", "10.00", {"type": "percent", "percents": {"DANA": "60", "Eli ": "40"}})),
        {"dana": 400, "eli": -400})


@case("holdout", "core", "payer-not-participating", "")
def _(L, cli):
    bal(L, G(["dana", "eli", "fay", "gus"],
             E("h9", "gus", "9.00", {"type": "equal", "among": ["dana", "eli", "fay"]})),
        {"dana": -300, "eli": -300, "fay": -300, "gus": 900})


@case("holdout", "core", "balances-complete-and-zero-sum", "")
def _(L, cli):
    g = G(["dana", "eli", "fay", "gus", "hal"],
          E("h10", "dana", "100.00", {"type": "equal", "among": ["dana", "eli", "fay"]}),
          E("h11", "eli", "33.33", {"type": "percent", "percents": {"dana": "12.5", "fay": "37.5", "gus": "50"}}),
          E("h12", "gus", "0.07", {"type": "equal", "among": ["dana", "eli", "fay", "gus"]}),
          E("h13", "fay", "19.99", {"type": "percent", "percents": {"dana": "33.33", "eli": "33.33", "gus": "33.34"}}))
    bal(L, g, {"dana": 10000 - 3334 - 417 - 2 - 666, "eli": 3333 - 3333 - 2 - 666,
               "fay": 1999 - 3333 - 1250 - 2, "gus": 7 - 1666 - 1 - 667, "hal": 0})


@case("holdout", "core", "members-empty", "")
def _(L, cli):
    invalid(L, G([]))


@case("holdout", "core", "equal-among-empty", "")
def _(L, cli):
    invalid(L, G(["dana", "eli"], E("h-a0", "dana", "10.00", {"type": "equal", "among": []})), "h-a0")


@case("holdout", "core", "unknown-payer-message", "")
def _(L, cli):
    invalid(L, G(["dana", "eli"], E("h-up", "zed", "10.00", {"type": "equal"})), "h-up")


@case("holdout", "core", "settle-greedy-chain", "")
def _(L, cli):
    g = G(["dana", "eli", "fay", "gus", "ivy"],
          E("h14", "dana", "50.00", {"type": "exact", "amounts": {"eli": "15.00", "fay": "25.00", "ivy": "10.00"}}),
          E("h15", "gus", "10.00", {"type": "exact", "amounts": {"dana": "10.00"}}))
    transfers(L, g, [("fay", "dana", 2500), ("eli", "dana", 1500), ("ivy", "gus", 1000)])


@case("holdout", "core", "settle-debtor-tie-then-split", "")
def _(L, cli):
    g = G(["dana", "eli", "fay", "gus"],
          E("h16", "fay", "20.00", {"type": "exact", "amounts": {"dana": "10.00", "eli": "10.00"}}),
          E("h17", "gus", "10.00", {"type": "exact", "amounts": {"dana": "5.00", "eli": "5.00"}}))
    transfers(L, g, [("dana", "fay", 1500), ("eli", "gus", 1000), ("eli", "fay", 500)])


@case("holdout", "core", "api-types", "")
def _(L, cli):
    g = G(["dana", "eli"], E("h18", "dana", "3.00", {"type": "equal"}))
    b = L.balances(g)
    eq(sorted((k, type(v).__name__) for k, v in b.items()), [("dana", "int"), ("eli", "int")])
    t = L.settle(g)
    eq([tuple(type(x).__name__ for x in item) + (type(item).__name__,) for item in t], [("str", "str", "int", "tuple")])


@case("holdout", "core", "cli-settle-format", "")
def _(L, cli):
    g = G(["dana", "eli", "fay", "gus", "ivy"],
          E("h14", "dana", "50.00", {"type": "exact", "amounts": {"eli": "15.00", "fay": "25.00", "ivy": "10.00"}}),
          E("h15", "gus", "10.00", {"type": "exact", "amounts": {"dana": "10.00"}}))
    eq(cli_lines(cli, "settle", g), ["fay -> dana: 25.00", "eli -> dana: 15.00", "ivy -> gus: 10.00"])


@case("holdout", "core", "cli-small-negative", "")
def _(L, cli):
    g = G(["dana", "eli"], E("h19", "dana", "0.05", {"type": "equal", "among": ["eli"]}))
    eq(cli_lines(cli, "balances", g), ["dana: +0.05", "eli: -0.05"])


@case("holdout", "core", "cli-missing-file", "")
def _(L, cli):
    rc, out, err = cli(["balances", "/nonexistent/dir/group.json"], None)
    eq((rc, err.startswith("error:")), (1, True))


@case("holdout", "core", "cli-validation-exit-balances", "")
def _(L, cli):
    rc, out, err = cli(["balances"], G(["dana", "eli"], E("h20", "dana", "1.234", {"type": "equal"})))
    eq((rc, err.startswith("error:"), "h20" in err), (2, True, True))


# ------------------------------------------------------------------ QA / v2

@case("qa", "v2", "shares-basic",
      "Shares split of 10.00 with quinn 2, rory 1: quinn's 6.666.. share rounds up because it has the largest fraction.")
def _(L, cli):
    bal(L, G(["quinn", "rory", "sage"],
             E("q20", "sage", "10.00", {"type": "shares", "shares": {"quinn": 2, "rory": 1}})),
        {"quinn": -667, "rory": -333, "sage": 1000})


@case("qa", "v2", "shares-invalid",
      'Shares of 0, or given as a string ("2"): ValidationError mentioning the expense id.')
def _(L, cli):
    invalid(L, G(["quinn", "rory"], E("qa-s0", "quinn", "10.00", {"type": "shares", "shares": {"quinn": 0, "rory": 1}})), "qa-s0")
    invalid(L, G(["quinn", "rory"], E("qa-s1", "quinn", "10.00", {"type": "shares", "shares": {"quinn": "2", "rory": 1}})), "qa-s1")


@case("qa", "v2", "shares-bool",
      "Shares given as a boolean (true): ValidationError mentioning the expense id.")
def _(L, cli):
    invalid(L, G(["quinn", "rory"], E("qa-s2", "quinn", "10.00", {"type": "shares", "shares": {"quinn": True, "rory": 1}})), "qa-s2")


@case("qa", "v2", "fx-half-even",
      "10.00 EUR at 1.0825 = 10.825 USD, which rounds half-to-even to 10.82.")
def _(L, cli):
    bal(L, G(["quinn", "rory"],
             E("q21", "quinn", "10.00", {"type": "equal", "among": ["rory"]}, currency="EUR"),
             rates={"EUR": "1.0825"}),
        {"quinn": 1082, "rory": -1082})


@case("qa", "v2", "fx-missing-rate",
      "Expense in GBP with no GBP rate: ValidationError mentioning the expense id.")
def _(L, cli):
    invalid(L, G(["quinn", "rory"], E("qa-f1", "quinn", "10.00", {"type": "equal"}, currency="GBP"), rates={"EUR": "1.1"}), "qa-f1")


@case("qa", "v2", "fx-exact-not-allowed",
      "Exact split on an expense in EUR (group currency USD): ValidationError mentioning the expense id.")
def _(L, cli):
    invalid(L, G(["quinn", "rory"],
                 E("qa-f2", "quinn", "10.00", {"type": "exact", "amounts": {"rory": "10.00"}}, currency="EUR"),
                 rates={"EUR": "1.1"}), "qa-f2")


@case("qa", "v2", "fx-same-currency",
      'Expense currency "usd" in a USD group needs no rate and is not converted.')
def _(L, cli):
    bal(L, G(["quinn", "rory"], E("q22", "quinn", "10.00", {"type": "equal"}, currency="usd")),
        {"quinn": 500, "rory": -500})


@case("qa", "v2", "cli-fx-settle",
      "CLI `settle` for a group with one EUR expense (20.00 EUR at 1.1, split equally between 2).")
def _(L, cli):
    g = G(["quinn", "rory"], E("q23", "quinn", "20.00", {"type": "equal"}, currency="EUR"), rates={"EUR": "1.1"})
    eq(cli_lines(cli, "settle", g), ["rory -> quinn: 11.00"])


# ------------------------------------------------------------- holdout / v2

@case("holdout", "v2", "fx-half-even-up", "")
def _(L, cli):
    bal(L, G(["dana", "eli"], E("h30", "dana", "10.00", {"type": "equal", "among": ["eli"]}, currency="EUR"),
             rates={"EUR": "1.0835"}), {"dana": 1084, "eli": -1084})


@case("holdout", "v2", "fx-long-rate", "")
def _(L, cli):
    bal(L, G(["dana", "eli"], E("h31", "dana", "7.00", {"type": "equal", "among": ["eli"]}, currency="CHF"),
             rates={"CHF": "0.857142"}), {"dana": 600, "eli": -600})


@case("holdout", "v2", "fx-rate-invalid", "")
def _(L, cli):
    for i, rate in enumerate(["0", "-1", 1.5, "abc"]):
        eid = f"h-r{i}"
        try:
            # The expense id is not required here: an invalid top-level rate may be reported at group level.
            invalid(L, G(["dana", "eli"], E(eid, "dana", "10.00", {"type": "equal"}, currency="EUR"), rates={"EUR": rate}))
        except Fail as f:
            raise Fail(f"rate {rate!r}: {f}")


@case("holdout", "v2", "shares-tie", "")
def _(L, cli):
    bal(L, G(["dana", "eli", "fay", "gus"],
             E("h32", "gus", "1.00", {"type": "shares", "shares": {"fay": 1, "eli": 1, "dana": 1}})),
        {"dana": -34, "eli": -33, "fay": -33, "gus": 100})


@case("holdout", "v2", "shares-largest-fraction", "")
def _(L, cli):
    bal(L, G(["dana", "eli", "fay"],
             E("h33", "fay", "1.00", {"type": "shares", "shares": {"dana": 1, "eli": 2}})),
        {"dana": -33, "eli": -67, "fay": 100})


@case("holdout", "v2", "shares-unknown-member", "")
def _(L, cli):
    invalid(L, G(["dana", "eli"], E("h-s9", "dana", "10.00", {"type": "shares", "shares": {"eli": 1, "zed": 1}})), "h-s9")


@case("holdout", "v2", "fx-percent", "")
def _(L, cli):
    bal(L, G(["dana", "eli", "fay"],
             E("h34", "fay", "20.00", {"type": "percent", "percents": {"dana": "50", "eli": "50"}}, currency="EUR"),
             rates={"EUR": "1.10"}), {"dana": -1100, "eli": -1100, "fay": 2200})


@case("holdout", "v2", "fx-code-case-insensitive", "")
def _(L, cli):
    bal(L, G(["dana", "eli"], E("h35", "dana", "5.00", {"type": "equal", "among": ["eli"]}, currency="eur"),
             rates={"Eur": "2"}), {"dana": 1000, "eli": -1000})


@case("holdout", "v2", "fx-convert-before-split", "")
def _(L, cli):
    bal(L, G(["dana", "eli", "fay"],
             E("h36", "fay", "0.03", {"type": "equal", "among": ["dana", "eli"]}, currency="EUR"),
             rates={"EUR": "1.5"}), {"dana": -2, "eli": -2, "fay": 4})


@case("holdout", "v2", "fx-equal-rounding", "")
def _(L, cli):
    bal(L, G(["dana", "eli", "fay", "gus"],
             E("h37", "gus", "10.00", {"type": "equal", "among": ["fay", "eli", "dana"]}, currency="EUR"),
             rates={"EUR": "1.0825"}), {"dana": -361, "eli": -361, "fay": -360, "gus": 1082})


@case("holdout", "v2", "cli-shares-balances", "")
def _(L, cli):
    g = G(["dana", "eli", "fay"], E("h38", "fay", "1.00", {"type": "shares", "shares": {"dana": 1, "eli": 2}}))
    eq(cli_lines(cli, "balances", g), ["dana: -0.33", "eli: -0.67", "fay: +1.00"])
