import os
import sqlite3
import subprocess
import sys


def test_old_profile_database_gets_the_goal_and_horizon_columns(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("create table financial_profiles (user_id varchar primary key, monthly_income float, age integer, dependents integer, existing_emi float, "
                "emergency_fund_months float, city_tier integer, tax_regime varchar, risk_label varchar, risk_confidence float, updated_at datetime)")
    con.commit(); con.close()
    code = "from shared import user_store as u; print(u.get_financial_profile('x'))"
    out = subprocess.run([sys.executable, "-c", code], env={**os.environ, "DB_URL": f"sqlite:///{db.as_posix()}", "PYTHONPATH": os.getcwd()}, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-400:]
    cols = [r[1] for r in sqlite3.connect(db).execute("pragma table_info(financial_profiles)")]
    assert "goal" in cols and "horizon_years" in cols
