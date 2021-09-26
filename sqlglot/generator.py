import logging
import textwrap

import sqlglot.expressions as exp
from sqlglot.errors import ErrorLevel, UnsupportedError
from sqlglot.helper import csv
from sqlglot.tokens import Token, TokenType, Tokenizer


class Generator:
    BODY_TOKENS = {
        TokenType.SELECT,
        TokenType.FROM,
        TokenType.JOIN,
        TokenType.WHERE,
        TokenType.GROUP,
        TokenType.HAVING,
        TokenType.ORDER,
        TokenType.UNION,
        TokenType.WITH,
    }

    TRANSFORMS = {
        TokenType.BOOLEAN: 'BOOLEAN',
        TokenType.TINYINT: 'TINYINT',
        TokenType.SMALLINT: 'SMALLINT',
        TokenType.INT: 'INT',
        TokenType.BIGINT: 'BIGINT',
        TokenType.FLOAT: 'FLOAT',
        TokenType.DOUBLE: 'DOUBLE',
        TokenType.CHAR: 'CHAR',
        TokenType.VARCHAR: 'VARCHAR',
        TokenType.TEXT: 'TEXT',
        TokenType.BINARY: 'BINARY',
        TokenType.JSON: 'JSON',
        exp.Array: lambda self, e: f"ARRAY({self.expressions(e, flat=True)})",
        exp.ArrayAgg: lambda self, e: f"ARRAY_AGG({self.sql(e, 'this')})",
        exp.ArrayContains: lambda self, e: f"ARRAY_CONTAINS({self.sql(e, 'this')}, {self.sql(e, 'expression')})",
        exp.ArraySize: lambda self, e: f"ARRAY_SIZE({self.sql(e, 'this')})",
        exp.DateAdd: lambda self, e: f"DATE_ADD({self.sql(e, 'this')}, {self.sql(e, 'expression')})",
        exp.DateDiff: lambda self, e: f"DATE_DIFF({self.sql(e, 'this')}, {self.sql(e, 'expression')})",
        exp.DateStrToDate: lambda self, e: f"DATE_STR_TO_DATE({self.sql(e, 'this')})",
        exp.Day: lambda self, e: f"DAY({self.sql(e, 'this')})",
        exp.Initcap: lambda self, e: f"INITCAP({self.sql(e, 'this')})",
        exp.JSONPath: lambda self, e: f"JSON_PATH({self.sql(e, 'this')}, {self.sql(e, 'path')})",
        exp.Month: lambda self, e: f"MONTH({self.sql(e, 'this')})",
        exp.Quantile: lambda self, e: f"QUANTILE({self.sql(e, 'this')}, {self.sql(e, 'quantile')})",
        exp.StrPosition: lambda self, e: f"STR_POSITION({csv(self.sql(e, 'this'), self.sql(e, 'substr'), self.sql(e, 'position'))})",
        exp.StrToTime: lambda self, e: f"STR_TO_TIME({self.sql(e, 'this')}, {self.sql(e, 'format')})",
        exp.StrToUnix: lambda self, e: f"STR_TO_UNIX({self.sql(e, 'this')}, {self.sql(e, 'format')})",
        exp.StructExtract: lambda self, e: f"STRUCT_EXTRACT({self.sql(e, 'this')}, {self.sql(e, 'expression')})",
        exp.TimeStrToDate: lambda self, e: f"TIME_STR_TO_DATE({self.sql(e, 'this')})",
        exp.TimeStrToTime: lambda self, e: f"TIME_STR_TO_TIME({self.sql(e, 'this')})",
        exp.TimeStrToUnix: lambda self, e: f"TIME_STR_TO_UNIX({self.sql(e, 'this')})",
        exp.TimeToStr: lambda self, e: f"TIME_TO_STR({self.sql(e, 'this')}, {self.sql(e, 'format')})",
        exp.TimeToTimeStr: lambda self, e: f"TIME_TO_TIME_STR({self.sql(e, 'this')})",
        exp.TimeToUnix: lambda self, e: f"TIME_TO_UNIX({self.sql(e, 'this')})",
        exp.TsOrDsToDateStr: lambda self, e: f"TS_OR_DS_TO_DATE_STR({self.sql(e, 'this')})",
        exp.TsOrDsToDate: lambda self, e: f"TS_OR_DS_TO_DATE({self.sql(e, 'this')})",
        exp.UnixToStr: lambda self, e: f"UNIX_TO_STR({self.sql(e, 'this')}, {self.sql(e, 'format')})",
        exp.UnixToTime: lambda self, e: f"UNIX_TO_TIME({self.sql(e, 'this')})",
        exp.UnixToTimeStr: lambda self, e: f"UNIX_TO_TIME_STR({self.sql(e, 'this')})",
    }

    def __init__(self, **opts):
        self.transforms = {**self.TRANSFORMS, **(opts.get('transforms') or {})}
        self.pretty = opts.get('pretty')
        self.identifier = opts.get('identifier') or '"'
        self.identify = opts.get('identify', False)
        self.quote = opts.get('quote') or "'"
        self.escape = opts.get('escape') or "'"
        self.pad = opts.get('pad', 2)
        self.unsupported_level = opts.get('unsupported_level', ErrorLevel.WARN)
        self.unsupported_messages = []
        self._indent = opts.get('indent', 4)
        self._level = 0
        self.opts = opts

    def generate(self, expression):
        self.unsupported_messages = []
        sql = self.sql(expression).strip()

        if self.unsupported_level == ErrorLevel.IGNORE:
            return sql

        for msg in self.unsupported_messages:
            if self.unsupported_level == ErrorLevel.RAISE:
                raise UnsupportedError(msg)
            logging.warning(msg)

        return sql

    def unsupported(self, message):
        self.unsupported_messages.append(message)

    def indent(self, sql, level=None, pad=0):
        level = self._level if level is None else level
        if self.pretty:
            sql = f"{' ' * (level * self._indent + pad)}{sql}"
        return sql

    def sep(self, sep=' '):
        return f"{sep.strip()}\n" if self.pretty else sep

    def seg(self, sql, sep=' ', level=None, pad=0):
        return f"{self.sep(sep)}{self.indent(sql, level=level, pad=pad)}"

    def wrap(self, expression):
        self._level += 1
        this_sql = self.indent(self.sql(expression, 'this'))
        self._level -= 1
        return f"({self.sep('')}{this_sql}{self.seg(')', sep='')}"

    def no_format(self, func):
        original = self.pretty
        self.pretty = False
        result = func()
        self.pretty = original
        return result

    def indent_newlines(self, sql, skip_first=False):
        if not self.pretty:
            return sql

        return '\n'.join(
            line if skip_first and i == 0 else self.indent(line, pad=self.pad)
            for i, line in enumerate(sql.split('\n'))
        )

    def sql(self, expression, key=None, identify=False):
        if not expression:
            return ''

        if isinstance(expression, str):
            return expression

        if key:
            return self.sql(expression.args.get(key), identify=identify)

        transform = self.transforms.get(expression.__class__) or self.transforms.get(expression.token_type)

        if callable(transform):
            return transform(self, expression)
        if transform:
            return transform

        if isinstance(expression, Token):
            text = expression.text.replace(Tokenizer.ESCAPE_CODE, self.escape)
            if expression.token_type == TokenType.IDENTIFIER or (self.identify and identify):
                text = f"{self.identifier}{text}{self.identifier}"
            elif expression.token_type == TokenType.STRING:
                return f"{self.quote}{text}{self.quote}"
            return text

        return getattr(self, f"{expression.key}_sql")(expression)

    def characterset_sql(self, expression):
        default = 'DEFAULT ' if expression.args.get('default') else ''
        return f"{default}CHARACTER SET={self.sql(expression, 'this')}"

    def column_sql(self, expression):
        fields = expression.args.get('fields')

        if fields:
            return '.'.join(self.sql(field) for field in fields)

        return '.'.join(part for part in [
            self.sql(expression, 'db', identify=True),
            self.sql(expression, 'table', identify=True),
            self.sql(expression, 'this', identify=True),
        ] if part)

    def columndef_sql(self, expression):
        column = self.sql(expression, 'this')
        kind = self.sql(expression, 'kind')
        not_null = ' NOT NULL' if expression.args.get('not_null') else ''
        default = self.sql(expression, 'default')
        default = f" DEFAULT {default}" if default else ''
        auto_increment = ' AUTO_INCREMENT' if expression.args.get('auto_increment') else ''
        collate = self.sql(expression, 'collate')
        collate = f" COLLATE {collate}" if collate else ''
        comment = self.sql(expression, 'comment')
        comment = f" COMMENT {comment}" if comment else ''
        return f"{column} {kind}{not_null}{default}{collate}{auto_increment}{comment}"

    def create_sql(self, expression):
        this = self.sql(expression, 'this')
        kind = self.sql(expression, 'kind').upper()
        expression_sql = self.sql(expression, 'expression')
        expression_sql = f"AS{self.sep()}{expression_sql}" if expression_sql else ''
        temporary = ' TEMPORARY' if expression.args.get('temporary') else ''
        replace = ' OR REPLACE' if expression.args.get('replace') else ''
        exists_sql = ' IF NOT EXISTS' if expression.args.get('exists') else ''
        file_format = self.sql(expression, 'file_format')
        file_format = f" {file_format} " if file_format else ' '
        engine = self.sql(expression, 'engine')
        engine = f"ENGINE={engine}" if engine else ''
        auto_increment = self.sql(expression, 'auto_increment')
        auto_increment = f"AUTO_INCREMENT={auto_increment}" if auto_increment else ''
        character_set = self.sql(expression, 'character_set')
        collate = self.sql(expression, 'collate')
        collate = f"COLLATE={collate}" if collate else ''
        comment = self.sql(expression, 'comment')
        comment = f"COMMENT={comment}" if comment else ''

        options = ' '.join(
            option for option in (
                engine,
                auto_increment,
                character_set,
                collate,
                comment,
            ) if option
        )

        return f"CREATE{temporary}{replace} {kind}{exists_sql} {this}{file_format}{expression_sql}{options}"

    def cte_sql(self, expression):
        sql = ', '.join(
            f"{self.sql(e, 'alias')} AS {self.wrap(e)}"
            for e in expression.args['expressions']
        )
        recursive = 'RECURSIVE ' if expression.args.get('recursive') else ''

        return f"WITH {recursive}{sql}{self.sep()}{self.indent(self.sql(expression, 'this'))}"

    def drop_sql(self, expression):
        this = self.sql(expression, 'this')
        kind = expression.args['kind'].upper()
        exists_sql = ' IF EXISTS ' if expression.args.get('exists') else ' '
        return f"DROP {kind}{exists_sql}{this}"

    def fileformat_sql(self, expression):
        if self.sql(expression, 'this'):
            self.unsupported('File formats are not supported')
        return ''

    def hint_sql(self, expression):
        if self.sql(expression, 'this'):
            self.unsupported('Hints are not supported')
        return ''

    def insert_sql(self, expression):
        overwrite = self.sql(expression, 'overwrite')
        kind = 'OVERWRITE' if overwrite else 'INTO'
        this = self.sql(expression, 'this')
        exists = ' IF EXISTS ' if expression.args.get('exists') else ' '
        expression_sql = self.sql(expression, 'expression')
        return f"INSERT {kind} TABLE {this}{exists}{expression_sql}"

    def hivenotmatchedinsert_sql(self, expression):
        this = expression.args['this']

        if isinstance(this, str):
            return f'INSERT {this}'
        else:
            this = this.sql()
            values = expression.args['values'].sql()
            return f'INSERT {this} VALUES {values}'

    def table_sql(self, expression):
        return '.'.join(part for part in [
            self.sql(expression, 'db', identify=True),
            self.sql(expression, 'table', identify=True),
            self.sql(expression, 'this', identify=True),
        ] if part)

    def tuple_sql(self, expression):
        return f"({self.expressions(expression, flat=True)})"

    def update_sql(self, expression):
        this = self.sql(expression, 'this')
        set_sql = self.expressions(expression)
        where_sql = self.sql(expression.args.get('where'))
        return f"UPDATE {this} SET {set_sql}{where_sql}"

    def values_sql(self, expression):
        return f"VALUES{self.seg('')}{self.expressions(expression)}"

    def from_sql(self, expression):
        expressions = ', '.join(self.sql(e) for e in expression.args['expressions'])
        return f"{self.seg('FROM')} {expressions}"

    def group_sql(self, expression):
        return self.op_expressions('GROUP BY', expression)

    def having_sql(self, expression):
        this = self.indent_newlines(self.sql(expression, 'this'))
        return f"{self.seg('HAVING')}{self.sep()}{this}"

    def join_sql(self, expression):
        side = self.sql(expression, 'side')
        kind = self.sql(expression, 'kind')
        op_sql = self.seg(' '.join(op for op in [side, kind, 'JOIN'] if op))
        on_sql = self.sql(expression, 'on')

        if on_sql:
            on_sql = self.indent_newlines(on_sql, skip_first=True)
            on_sql = f"{self.seg('ON', pad=self.pad)} {on_sql}"

        expression_sql = self.sql(expression, 'expression')
        this_sql = self.sql(expression, 'this')
        return f"{expression_sql}{op_sql} {this_sql}{on_sql}"

    def lateral_sql(self, expression):
        this = self.sql(expression, 'this')
        op_sql = self.seg(f"LATERAL VIEW{' OUTER' if expression.args.get('outer') else ''}")
        alias = self.sql(expression, 'table')
        columns = ', '.join(self.sql(e) for e in expression.args.get('columns', []))
        return f"{op_sql}{self.sep()}{this} {alias} AS {columns}"

    def limit_sql(self, expression):
        return f"{self.seg('LIMIT')} {self.sql(expression, 'this')}"

    def order_sql(self, expression, flat=False):
        return self.op_expressions('ORDER BY', expression, flat=flat)

    def ordered_sql(self, expression):
        desc = self.sql(expression, 'desc')
        desc = f" {desc}" if desc else ''
        return f"{self.sql(expression, 'this')}{desc}"

    def select_sql(self, expression):
        hint = self.sql(expression, 'hint')
        distinct = ' DISTINCT' if expression.args.get('distinct') else ''
        expressions = self.expressions(expression)
        return csv(
            f"SELECT{hint}{distinct}{self.sep()}{expressions}",
            self.sql(expression, 'from'),
            *[self.sql(sql) for sql in expression.args.get('laterals', [])],
            *[self.sql(sql) for sql in expression.args.get('joins', [])],
            self.sql(expression, 'where'),
            self.sql(expression, 'group'),
            self.sql(expression, 'having'),
            self.sql(expression, 'order'),
            self.sql(expression, 'limit'),
            sep='',
        )

    def schema_sql(self, expression):
        sql = f"({self.sep('')}{self.expressions(expression)}{self.seg(')', sep='')}"
        return f"{self.sql(expression, 'this')} {sql}"

    def union_sql(self, expression):
        this = self.sql(expression, 'this')
        op = self.seg(f"UNION{'' if expression.args['distinct'] else ' ALL'}")
        expression = self.indent(self.sql(expression, 'expression'), pad=0)
        return f"{this}{op}{self.sep()}{expression}"

    def unnest_sql(self, expression):
        args = self.expressions(expression, flat=True)
        table = self.sql(expression, 'table')
        ordinality = ' WITH ORDINALITY' if expression.args.get('ordinality') else ''
        columns = ', '.join(self.sql(e) for e in expression.args.get('columns', []))
        alias = f" AS {table}" if table else ''
        alias = f"{alias} ({columns})" if columns else alias
        return f"UNNEST({args}){ordinality}{alias}"

    def where_sql(self, expression):
        this = self.indent_newlines(self.sql(expression, 'this'))
        return f"{self.seg('WHERE')}{self.sep()}{this}"

    def window_sql(self, expression):
        this_sql = self.sql(expression, 'this')
        partition = expression.args.get('partition')
        partition = 'PARTITION BY ' +  ', '.join(self.sql(by) for by in partition) if partition else ''
        order = expression.args.get('order')
        order_sql = self.order_sql(order, flat=True) if order else ''
        partition_sql = partition + ' ' if partition and order else partition
        spec = expression.args.get('spec')
        spec_sql = ' ' + self.window_spec_sql(spec) if spec else ''
        return f"{this_sql} OVER({partition_sql}{order_sql}{spec_sql})"

    def window_spec_sql(self, expression):
        kind = self.sql(expression, 'kind')
        start = csv(self.sql(expression, 'start'), self.sql(expression, 'start_side'), sep=' ')
        end = csv(self.sql(expression, 'end'), self.sql(expression, 'end_side'), sep=' ')
        return f"{kind} BETWEEN {start} AND {end}"

    def between_sql(self, expression):
        this = self.sql(expression, 'this')
        low = self.sql(expression, 'low')
        high = self.sql(expression, 'high')
        return f"{this} BETWEEN {low} AND {high}"

    def bracket_sql(self, expression):
        return f"{self.sql(expression, 'this')}[{self.expressions(expression, flat=True)}]"

    def case_sql(self, expression):
        pad = self.pad + 2

        this = self.sql(expression, 'this')
        this = f" {this}" if this else ''

        ifs = [
            f"WHEN {self.sql(e, 'this')} THEN {self.sql(e, 'true')}"
            for e in expression.args['ifs']
        ]

        if expression.args.get('default') is not None:
            ifs.append(f"ELSE {self.sql(expression, 'default')}")

        original = self.pretty
        self.pretty = self.opts.get('pretty')
        ifs = ''.join(self.seg(e, pad=pad) for e in ifs)
        case = f"CASE{this}{ifs}{self.seg('END', pad=self.pad)}"
        self.pretty = original
        return case

    def decimal_sql(self, expression):
        if isinstance(expression, Token):
            return 'DECIMAL'
        args = ', '.join(
            arg.text
            for arg in [expression.args.get('precision'), expression.args.get('scale')]
            if arg
        )
        return f"DECIMAL({args})"

    def extract_sql(self, expression):
        this = self.sql(expression, 'this')
        expression_sql = self.sql(expression, 'expression')
        return f"EXTRACT({this} FROM {expression_sql})"

    def if_sql(self, expression):
        return self.case_sql(exp.Case(ifs=[expression], default=expression.args['false']))

    def in_sql(self, expression):
        in_sql = (
            self.no_format(lambda: self.sql(expression, 'query')) or
            self.expressions(expression, flat=True)
        )
        return f"{self.sql(expression, 'this')} IN ({in_sql})"

    def interval_sql(self, expression):
        return f"INTERVAL {self.sql(expression, 'this')} {self.sql(expression, 'unit')}"

    def anonymous_sql(self, expression):
        return f"{self.sql(expression, 'this').upper()}({self.expressions(expression, flat=True)})"

    def paren_sql(self, expression):
        return self.no_format(lambda: f"({self.sql(expression, 'this')})")

    def neg_sql(self, expression):
        return f"-{self.sql(expression, 'this')}"

    def not_sql(self, expression):
        return f"NOT {self.sql(expression, 'this')}"

    def alias_sql(self, expression):
        to_sql = self.sql(expression, 'alias')
        to_sql = f" AS {to_sql}" if to_sql else ''

        if expression.args['this'].token_type in self.BODY_TOKENS:
            if self.pretty:
                return f"{self.wrap(expression)}{to_sql}"
            return f"({self.sql(expression, 'this')}){to_sql}"
        return f"{self.sql(expression, 'this')}{to_sql}"

    def and_sql(self, expression):
        return self.binary(expression, 'AND', newline=self.pretty)

    def bitwiseand_sql(self, expression):
        return self.binary(expression, '&')

    def bitwiseleftshift_sql(self, expression):
        return self.binary(expression, '<<')

    def bitwisenot_sql(self, expression):
        return f"~{self.sql(expression, 'this')}"

    def bitwiseor_sql(self, expression):
        return self.binary(expression, '|')

    def bitwiserightshift_sql(self, expression):
        return self.binary(expression, '>>')

    def bitwisexor_sql(self, expression):
        return self.binary(expression, '^')

    def cast_sql(self, expression):
        return f"CAST({self.sql(expression, 'this')} AS {self.sql(expression, 'to')})"

    def count_sql(self, expression):
        distinct = 'DISTINCT ' if expression.args['distinct'] else ''
        return f"COUNT({distinct}{self.sql(expression, 'this')})"

    def div_sql(self, expression):
        return self.sql(exp.Cast(
            this=exp.Slash(
                this=expression.args['this'],
                expression=expression.args['expression']
            ),
            to=Token(TokenType.INT, 'INT'),
        ))

    def dpipe_sql(self, expression):
        return self.binary(expression, '||')

    def dot_sql(self, expression):
        return f"{self.sql(expression, 'this')}.{self.sql(expression, 'expression')}"

    def eq_sql(self, expression):
        return self.binary(expression, '=')

    def gt_sql(self, expression):
        return self.binary(expression, '>')

    def gte_sql(self, expression):
        return self.binary(expression, '>=')

    def is_sql(self, expression):
        return self.binary(expression, 'IS')

    def like_sql(self, expression):
        return self.binary(expression, 'LIKE')

    def lt_sql(self, expression):
        return self.binary(expression, '<')

    def lte_sql(self, expression):
        return self.binary(expression, '<=')

    def minus_sql(self, expression):
        return self.binary(expression, '-')

    def mod_sql(self, expression):
        return self.binary(expression, '%')

    def neq_sql(self, expression):
        return self.binary(expression, '<>')

    def or_sql(self, expression):
        return self.binary(expression, 'OR', newline=self.pretty)

    def plus_sql(self, expression):
        return self.binary(expression, '+')

    def regexlike_sql(self, expression):
        return self.binary(expression, 'RLIKE')

    def slash_sql(self, expression):
        return self.binary(expression, '/')

    def star_sql(self, expression):
        return self.binary(expression, '*')

    def merge_sql(self, expression):
        delta_location = expression.args['this'].args['this'].args['this'].text
        delta_alias = expression.args['this'].args['alias'].text

        using = expression.args['using'].args['this']
        using_alias = expression.args['using'].args['alias']

        on_expression = expression.args['condition'].sql()
        matched_update = expression.args['matched_update']
        matched_update_sql = ''
        if matched_update:
            matched_update_sql = matched_update.sql()

        not_matched_update = expression.args['not_matched_update']
        not_matched_update_sql = ''
        if not_matched_update:
            not_matched_update_sql = not_matched_update.sql()

        sql = f"MERGE INTO delta.`{delta_location}` {delta_alias} USING {using} {using_alias} ON {on_expression}"
        if matched_update_sql:
            sql += f" WHEN MATCHED THEN {matched_update_sql}"
        if not_matched_update_sql:
            sql += f" WHEN NOT MATCHED THEN {not_matched_update_sql}"
        return sql

    def binary(self, expression, op, newline=False):
        sep = '\n' if newline else ' '
        return f"{self.sql(expression, 'this')}{sep}{op} {self.sql(expression, 'expression')}"

    def expressions(self, expression, flat=False, pad=0):
        # pylint: disable=cell-var-from-loop
        if flat:
            return ', '.join(self.sql(e) for e in expression.args['expressions'])

        return self.sep(', ').join(
            self.indent(
                f"{'  ' if self.pretty else ''}{self.no_format(lambda: self.sql(e))}",
                pad=pad,
            )
            for e in expression.args['expressions']
        )

    def op_expressions(self, op, expression, flat=False):
        expressions_sql = self.expressions(expression, flat=flat)
        if flat:
            return f"{op} {expressions_sql}"
        return f"{self.seg(op)}{self.sep()}{expressions_sql}"
