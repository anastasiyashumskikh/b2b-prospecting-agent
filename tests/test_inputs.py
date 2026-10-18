from prospect.inputs import CompanyInput, parse_input


def test_parse_input_cleans_file(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("# demo\nAcme Corp\n\n  Acme Corp \nHooli | hooli.com\n")
    assert parse_input([], f) == [CompanyInput("Acme Corp", None), CompanyInput("Hooli", "hooli.com")]


def test_parse_input_args_and_file_merge(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("Initech\n")
    assert parse_input(["Hooli | https://www.hooli.com/", "initech"], f) == [
        CompanyInput("Hooli", "hooli.com"),
        CompanyInput("initech", None),
    ]


def test_duplicate_is_case_insensitive():
    assert parse_input(["Acme", "ACME", "acme | acme.com"], None) == [CompanyInput("Acme", None)]


def test_inline_comments_ignored():
    assert parse_input(["Zalando        # few public data", "Mercury # ambiguous"], None) == [
        CompanyInput("Zalando", None), CompanyInput("Mercury", None)
    ]
