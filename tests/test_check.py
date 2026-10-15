from mu2ebo_reporter.check import check

FACTS = {"board": {"rows": [{"config": "bpzq01R26_00", "values": {"sob": 1.41513, "flash_edep": 7.58519e-06}}]},
         "kb": "S/sqrt(B) 4.15 vs 3.26, rad. damage 1.10\u00d710\u22126"}


def test_supported_numbers_pass():
    r = check("Best **bpzq01R26_00**: sob = 1.41513, flash_edep = 7.58519e-6 (7.585 \u00d7 10\u207b\u2076).", FACTS)
    assert r["ok"], r


def test_invented_number_flagged():
    r = check("f_1 has a correlation of \u22120.89 with sob.", FACTS)
    assert [u["value"] for u in r["unsupported"]] == ["-0.89"]


def test_table_header_scale():
    report = "| config | flash_edep (\u00d710\u207b\u2076) |\n|---|---|\n| bpzq01R26_00 | 7.585 |\n"
    assert check(report, FACTS)["ok"]


def test_docdb_lines_reported_separately():
    r = check("DocDB 58092 quotes 4.15 vs 3.26 and 9.99.", FACTS)
    assert r["ok"] and [u["value"] for u in r["docdb_lines"]] == ["9.99"]


def test_small_integers_and_ids_ignored():
    assert check("1. Summary\n2. Setup with rOut_0 on 2026-10-15 in /exp/x/y2.tsv", FACTS)["ok"]


def test_spaced_exponent_and_log_axis():
    r = check("| bpzq01R26_00 | 7.58519 e\u201106 (\u2011log10 = 5.120) |", FACTS)
    assert r["ok"], r


def test_narrow_nbsp_before_exponent():
    assert check("flash_edep = 7.58519\u202fe\u201106", FACTS)["ok"]
