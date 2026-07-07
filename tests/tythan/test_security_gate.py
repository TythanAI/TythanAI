from tythan.security_gate import (
    format_report,
    scan_change,
    scan_content,
    scan_path,
    worst_severity,
)


def rule_ids(findings):
    return {f.rule_id for f in findings}


class TestRules:
    def test_aws_key(self):
        fs = scan_content('KEY = "AKIAIOSFODNN7EXAMPLE"\n', "conf.py")
        assert "SEC-AWS-KEY" in rule_ids(fs)
        assert worst_severity(fs) == "CRITICAL"

    def test_private_key_block(self):
        fs = scan_content("-----BEGIN RSA PRIVATE KEY-----\n", "id_rsa")
        assert "SEC-PRIVATE-KEY" in rule_ids(fs)

    def test_hardcoded_password(self):
        fs = scan_content('password = "hunter2hunter2"\n', "settings.py")
        assert "SEC-GENERIC-SECRET" in rule_ids(fs)

    def test_shell_true(self):
        fs = scan_content("subprocess.run(cmd, shell=True)\n", "run.py")
        assert "PY-SHELL-TRUE" in rule_ids(fs)

    def test_shell_true_only_python(self):
        fs = scan_content("subprocess.run(cmd, shell=True)\n", "notes.md")
        assert "PY-SHELL-TRUE" not in rule_ids(fs)

    def test_sql_fstring(self):
        code = 'cur.execute(f"SELECT * FROM users WHERE id = {uid}")\n'
        fs = scan_content(code, "db.py")
        assert "PY-SQL-FSTRING" in rule_ids(fs)
        assert worst_severity(fs) == "CRITICAL"

    def test_verify_false(self):
        fs = scan_content("requests.get(url, verify=False)\n", "http.py")
        assert "PY-VERIFY-FALSE" in rule_ids(fs)

    def test_yaml_safe_load_ok(self):
        fs = scan_content("yaml.load(f, Loader=yaml.SafeLoader)\n", "cfg.py")
        assert "PY-YAML-LOAD" not in rule_ids(fs)
        fs2 = scan_content("yaml.load(f)\n", "cfg.py")
        assert "PY-YAML-LOAD" in rule_ids(fs2)

    def test_js_sql_template(self):
        code = "db.query(`SELECT * FROM t WHERE id = ${id}`)\n"
        fs = scan_content(code, "api.ts")
        assert "JS-SQL-TEMPLATE" in rule_ids(fs)

    def test_jwt_none(self):
        fs = scan_content('jwt.decode(t, key, algorithms=["none"])\n', "auth.py")
        assert "CFG-JWT-NONE" in rule_ids(fs)

    def test_entropy_detector(self):
        fs = scan_content('api_key_x = "9fJ2kQ8vLxT3mZ7pW1nR5yB0cD4eG6hA"\n', "cfg.py")
        assert any(f.rule_id in ("SEC-HIGH-ENTROPY", "SEC-GENERIC-SECRET") for f in fs)

    def test_clean_code(self):
        fs = scan_content("def add(a, b):\n    return a + b\n", "math.py")
        assert fs == []

    def test_random_token(self):
        fs = scan_content("token = str(random.randint(0, 999999))\n", "otp.py")
        assert "PY-RANDOM-TOKEN" in rule_ids(fs)


class TestScanChange:
    def test_new_file_scans_everything(self):
        fs = scan_change(None, "eval(user_input)\n", "x.py")
        assert "PY-EVAL" in rule_ids(fs)

    def test_preexisting_issue_not_reported(self):
        old = "subprocess.run(c, shell=True)\nx = 1\n"
        new = "subprocess.run(c, shell=True)\nx = 2\n"
        assert scan_change(old, new, "a.py") == []

    def test_introduced_issue_reported(self):
        old = "x = 1\n"
        new = "x = 1\nsubprocess.run(c, shell=True)\n"
        assert "PY-SHELL-TRUE" in rule_ids(scan_change(old, new, "a.py"))

    def test_modified_line_reported(self):
        old = "subprocess.run(c)\n"
        new = "subprocess.run(c, shell=True)\n"
        assert "PY-SHELL-TRUE" in rule_ids(scan_change(old, new, "a.py"))


class TestScanPath:
    def test_walks_tree_and_skips_git(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "bad.py").write_text("eval(x())\n")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "cfg.py").write_text("eval(x())\n")
        fs = scan_path(tmp_path)
        assert len(fs) == 1 and fs[0].file.endswith("bad.py")

    def test_single_file(self, tmp_path):
        f = tmp_path / "one.py"
        f.write_text("eval(x())\n")
        assert rule_ids(scan_path(tmp_path, "one.py")) == {"PY-EVAL"}

    def test_report_formatting(self, tmp_path):
        (tmp_path / "b.py").write_text("eval(x())\n")
        report = format_report(scan_path(tmp_path))
        assert "PY-EVAL" in report and "1 finding" in report
        assert format_report([]) == "No security findings."
