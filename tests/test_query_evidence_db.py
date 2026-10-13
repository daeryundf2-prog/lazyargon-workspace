"""query_evidence_db.py 회귀 테스트 — 읽기전용 강제·쿼리·잔존 흔적 검색."""

import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import query_evidence_db as qe  # noqa: E402

SECRET = "영업비밀문서_v7"


@pytest.fixture()
def evidence_db(tmp_path):
    db = tmp_path / "증거.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, sender TEXT, content TEXT)")
    conn.execute("INSERT INTO messages (sender, content) VALUES ('김철수', '안녕하세요')")
    conn.execute("INSERT INTO messages (sender, content) VALUES ('이영희', ?)", (SECRET,))
    conn.commit()
    conn.close()
    return db


def test_list_schema(evidence_db, capsys):
    assert qe.main([str(evidence_db), "--list-schema"]) == 0
    out = capsys.readouterr().out
    assert "messages" in out and "sender" in out and "content" in out


def test_select_query_markdown(evidence_db, capsys):
    assert qe.main([str(evidence_db), "--sql", "SELECT sender, content FROM messages"]) == 0
    out = capsys.readouterr().out
    assert "김철수" in out and "안녕하세요" in out


def test_select_query_csv_format(evidence_db, tmp_path):
    out = tmp_path / "r.md"
    assert qe.main([str(evidence_db), "--sql", "SELECT sender FROM messages", "--format", "csv", "-o", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "```csv" in text
    assert "sender" in text.split("```csv", 1)[1]
    assert "김철수" in text


def test_write_statement_rejected(evidence_db, capsys):
    """DELETE/UPDATE/INSERT는 읽기전용 계약 위반으로 거부되어야 한다."""
    for sql in ("DELETE FROM messages", "UPDATE messages SET sender='x'", "INSERT INTO messages VALUES (9,'a','b')"):
        assert qe.main([str(evidence_db), "--sql", sql]) == 2


def test_readonly_connection_blocks_writes(evidence_db):
    conn = qe.open_readonly(str(evidence_db))
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM messages")
    conn.close()


def test_residual_keyword_found_after_delete(evidence_db):
    """회귀: 삭제한 레코드의 문자열이 페이지 잔존 바이트에서 발견되어야 한다.

    secure_delete가 켜진 sqlite 빌드는 삭제 시 내용을 0으로 덮어 쓰므로
    전제 자체가 성립하지 않는다 — 그 플랫폼에서는 스킵한다(도구는 흔적을
    '찾을 수 있으면' 보고하는 설계이고, 못 찾는 것이 부존재 증명은 아니다).
    """
    probe = sqlite3.connect(str(evidence_db))
    secure = probe.execute("PRAGMA secure_delete").fetchone()[0]
    probe.close()
    if secure:
        pytest.skip("이 sqlite 빌드는 secure_delete=ON — 잔존 바이트 전제가 성립하지 않음")

    conn = sqlite3.connect(str(evidence_db))
    conn.execute("DELETE FROM messages WHERE sender = '이영희'")
    conn.commit()
    conn.close()  # journal 플러시

    hits = qe.scan_residual(str(evidence_db), [SECRET])
    assert hits, "삭제한 레코드의 잔존 흔적이 발견되어야 함"
    assert any(h["encoding"] == "utf-8" for h in hits)
    assert all("offset" in h and h["context"] for h in hits)


def test_residual_absent_keyword_not_found(evidence_db):
    hits = qe.scan_residual(str(evidence_db), ["존재하지않는문자열xyz"])
    assert hits == []


def test_missing_db_and_no_args(evidence_db):
    with pytest.raises(SystemExit) as exc:  # argparse 표준 동작 — required 누락
        qe.main([])
    assert exc.value.code == 2
    assert qe.main(["없는.db", "--list-schema"]) == 2
    assert qe.main([str(evidence_db)]) == 2  # 옵션 누락


def test_report_render_with_all_sections(evidence_db, tmp_path):
    out = tmp_path / "보고서.md"
    rc = qe.main([
        str(evidence_db), "--list-schema",
        "--sql", "SELECT sender, content FROM messages LIMIT 10",
        "--keywords", "안녕", "-o", str(out),
    ])
    assert rc == 0
    md = out.read_text(encoding="utf-8")
    assert "스키마" in md and "쿼리 결과" in md and "잔존 흔적 검색" in md
    assert "복구 보장이 아니며" in md  # 한계 고지


# ── 심화 하드닝 회귀 (WITH 우회·URI 이스케이프·식별자 인용·CSV 주입) ──

def test_with_prefixed_mutation_rejected():
    # SQLite는 CTE 부착 변경을 허용한다 — 접두어 화이트리스트만으로는 우회된다.
    with pytest.raises(ValueError):
        qe.check_statement("WITH x AS (SELECT 1) DELETE FROM messages")
    with pytest.raises(ValueError):
        qe.check_statement("with x as (select 1) insert into t select * from x")
    with pytest.raises(ValueError):
        qe.check_statement("WITH x AS (SELECT 1) UPDATE t SET a=1 /* note */")
    # 정상 WITH SELECT는 통과한다
    assert qe.check_statement("WITH x AS (SELECT 1) SELECT * FROM x").startswith("WITH")


def test_open_readonly_escapes_percent_in_path(tmp_path):
    d = tmp_path / "100%20증거 dir"
    d.mkdir()
    db = d / "evidence.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE t (a)")
    con.commit()
    con.close()
    conn = qe.open_readonly(str(db))
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    conn.close()


def test_list_schema_quotes_hostile_table_name(tmp_path):
    db = tmp_path / "evil.db"
    con = sqlite3.connect(str(db))
    con.execute('CREATE TABLE "we;ird""table" (a)')  # SQL 식별자 내 따옴표는 두 번
    con.commit()
    con.close()
    conn = qe.open_readonly(str(db))
    schema = qe.list_schema(conn)
    conn.close()
    assert schema[0]["table"] == 'we;ird"table'


def test_csv_formula_injection_neutralized():
    out = qe.rows_to_csv(["v"], [["=1+1"], ["+cmd"], ["@x"], ["-123"], ["-SUM(A1)"]])
    assert "'=1+1" in out
    assert "'+cmd" in out
    assert "'@x" in out
    assert "\n-123" in out, "일반 음수는 그대로 둔다"
    assert "'-SUM(A1)" in out


def test_sql_comment_tokenizer_preserves_strings_and_identifiers():
    sql = "SELECT 'a/*text*/b' AS col, \"ident--x\" FROM t -- trailing\n/* block */"
    cleaned = qe.check_statement(sql)
    assert "'a/*text*/b'" in cleaned
    assert '"ident--x"' in cleaned
    assert "-- trailing" not in cleaned
    assert "/* block */" not in cleaned
    assert qe.strip_sql_comments("SELECT 'a--b'") == "SELECT 'a--b'"
    with pytest.raises(ValueError):
        qe.check_statement("SELECT /* unterminated")
    with pytest.raises(ValueError):
        qe.check_statement("SELECT 'unterminated")
