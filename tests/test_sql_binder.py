"""Binder corpus.

The measure of the analyzer's quality is how well it reads real SQL and
PL/SQL. Every time the binder gets something wrong, add the snippet here with
what it should extract — this file is the regression net for the part of the
system that is genuinely hard.

Run with `pytest tests`, or `python tests/test_sql_binder.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'tools'))

from apex_analyzer.parsers.plsql import analyse_plsql              # noqa: E402
from apex_analyzer.parsers.plsql_args import iter_calls, parse_value  # noqa: E402
from apex_analyzer.parsers.sqlparse import analyse_sql, normalise_sql  # noqa: E402
from apex_analyzer.parsers.urls import parse_apex_url, parse_url_items  # noqa: E402

# (sql, verb, {read tables}, {written tables}, {binds})
SQL_CORPUS = [
    ('select * from orders', 'SELECT', {'ORDERS'}, set(), set()),
    ('select o.id from order_app.orders o where o.id = :P1_ID',
     'SELECT', {'ORDERS'}, set(), {'P1_ID'}),
    ('select 1 from dual', 'SELECT', set(), set(), set()),
    ('select a.x, b.y from t1 a join t2 b on b.id = a.id left join t3 c on c.id = a.id',
     'SELECT', {'T1', 'T2', 'T3'}, set(), set()),
    ('select * from t1, t2 where t1.id = t2.id', 'SELECT', {'T1', 'T2'}, set(), set()),
    ('with recent as (select * from orders where rownum < 10) select * from recent',
     'SELECT', {'ORDERS'}, set(), set()),
    ('insert into orders (id, name) values (1, :P1_NAME)',
     'INSERT', set(), {'ORDERS'}, {'P1_NAME'}),
    ('update orders set status = :P1_S where id = :P1_ID',
     'UPDATE', set(), {'ORDERS'}, {'P1_S', 'P1_ID'}),
    ('delete from order_lines where order_id = :P1_ID',
     'DELETE', set(), {'ORDER_LINES'}, {'P1_ID'}),
    ('merge into orders o using staging s on (s.id = o.id) when matched then update '
     'set o.total = s.total', 'MERGE', {'STAGING'}, {'ORDERS'}, set()),
    ('select * from orders@remote_db', 'SELECT', {'ORDERS'}, set(), set()),
    ('select (select count(*) from order_lines l where l.order_id = o.id) from orders o',
     'SELECT', {'ORDERS', 'ORDER_LINES'}, set(), set()),
    ("select name from customers where name like 'FROM staging'",   # literal, not a table
     'SELECT', {'CUSTOMERS'}, set(), set()),
    ('select /* a comment with the word from orders */ x from t9',
     'SELECT', {'T9'}, set(), set()),
]


def test_sql_corpus():
    for sql, verb, reads, writes, binds in SQL_CORPUS:
        analysis = analyse_sql(sql)
        assert analysis.verb == verb, f'{sql!r}: verb {analysis.verb} != {verb}'
        actual_reads = {t.name for t in analysis.tables if t.access == 'READ'}
        actual_writes = {t.name for t in analysis.tables if t.access != 'READ'}
        assert actual_reads == reads, f'{sql!r}: reads {actual_reads} != {reads}'
        assert actual_writes == writes, f'{sql!r}: writes {actual_writes} != {writes}'
        assert set(analysis.binds) == binds, f'{sql!r}: binds {analysis.binds} != {binds}'


def test_sql_shape_flags():
    star = analyse_sql('select * from orders')
    assert star.has_select_star
    hinted = analyse_sql('select /*+ full(o) */ x from orders o')
    assert hinted.has_hint
    linked = analyse_sql('select x from orders@remote')
    assert linked.has_db_link
    joined = analyse_sql('select 1 from a join b on b.i = a.i join c on c.i = a.i')
    assert joined.join_count == 2
    assert analyse_sql('select 1 from t where x = &P1_X.').substitutions == ['P1_X']


def test_sql_normalisation_makes_duplicates_converge():
    first = normalise_sql('SELECT  x\n  FROM orders   -- a comment\n')
    second = normalise_sql('select x from orders;')
    assert first == second


def test_plsql_extracts_dml_calls_and_behaviour():
    code = """
    begin
      insert into order_app.audit_log (id, note) values (seq_audit.nextval, 'x');
      order_pkg.create_order(p_customer_id => :P10_CUSTOMER_ID, p_order_id => l_id);
      update order_app.orders set status_code = 'OPEN' where order_id = l_id;
      commit;
    exception
      when others then null;
    end;
    """
    analysis = analyse_plsql(code)
    tables = {t.name for t in analysis.tables()}
    assert {'AUDIT_LOG', 'ORDERS'} <= tables
    assert ('ORDER_PKG', 'CREATE_ORDER') in analysis.calls
    # a table in a DML statement must never be read as a package call
    assert not any(name == 'AUDIT_LOG' for _, name in analysis.calls)
    assert analysis.has_commit
    assert analysis.has_exception_handler
    assert analysis.has_when_others_null
    assert 'P10_CUSTOMER_ID' in analysis.binds


def test_plsql_flags_injectable_dynamic_sql():
    injectable = analyse_plsql(
        "begin execute immediate 'delete from t where s = ''' || :P1_S || ''''; end;")
    assert injectable.has_dynamic_sql
    assert injectable.dynamic_sql_concatenates_input

    parameterised = analyse_plsql(
        "begin execute immediate 'delete from t where s = :1' using p_status; end;")
    assert parameterised.has_dynamic_sql
    assert not parameterised.dynamic_sql_concatenates_input


def test_plsql_ignores_builtin_packages():
    analysis = analyse_plsql(
        "begin dbms_output.put_line('x'); apex_util.set_session_state('P1_X', 1); "
        "my_pkg.do_work(); end;")
    packages = {package for package, _ in analysis.calls}
    assert packages == {'MY_PKG'}
    assert 'APEX_UTIL.SET_SESSION_STATE' in analysis.apex_api_calls


def test_export_call_parsing():
    export = """
    wwv_flow_imp_page.create_page_plug(
     p_id=>wwv_flow_imp.id(1001)
    ,p_plug_name=>'It''s a region, (really)'
    ,p_plug_source=>q'~select x from t where y = :P1_Y~'
    ,p_plug_display_sequence=>10
    ,p_plug_query_no_data_found=>wwv_flow_string.join(wwv_flow_t_varchar2('no ','data'))
    );
    """
    calls = list(iter_calls(export, 'test.sql'))
    assert len(calls) == 1, 'a nested helper call was treated as a top-level call'
    call = calls[0]
    assert call.procedure == 'create_page_plug'
    assert call.number('id') == 1001
    assert call.text('plugName') == "It's a region, (really)"
    assert call.text('plugSource') == 'select x from t where y = :P1_Y'
    assert call.number('plugDisplaySequence') == 10
    assert call.text('plugQueryNoDataFound') == 'no data'


def test_export_value_forms():
    assert parse_value("'plain'") == 'plain'
    assert parse_value("q'{braced}'") == 'braced'
    assert parse_value('42') == 42
    assert parse_value('null') is None
    assert parse_value('wwv_flow_api.id(987)') == 987
    assert parse_value("'a' || 'b'") == 'ab'


def test_apex_url_parsing():
    assert parse_apex_url('f?p=&APP_ID.:20:&SESSION.::&DEBUG.:::') == 20
    assert parse_apex_url('f?p=100:30:&SESSION.') == 30
    assert parse_apex_url('&APP_ID.:15') == 15
    assert parse_apex_url('20') == 20
    assert parse_apex_url('https://example.com/help') is None
    assert parse_url_items(
        'f?p=&APP_ID.:10:&SESSION.::&DEBUG.:10:P10_ID,P10_MODE:&P1_ID.,V') == \
        ['P10_ID', 'P10_MODE']


if __name__ == '__main__':
    failures = 0
    for name, function in sorted(globals().items()):
        if not name.startswith('test_') or not callable(function):
            continue
        try:
            function()
            print(f'PASS  {name}')
        except AssertionError as exc:
            failures += 1
            print(f'FAIL  {name}: {exc}')
        except Exception as exc:                       # noqa: BLE001
            failures += 1
            print(f'ERROR {name}: {type(exc).__name__}: {exc}')
    print(f'\n{failures} failure(s)')
    sys.exit(1 if failures else 0)
