"""SQL AST validation before SQLite prepares governed catalog formulas."""

from sqlglot import exp, parse
from sqlglot.optimizer.qualify import qualify
from app.sql.schema import SCHEMA
from app.sql.formulas import validate_metric_formulas


def validate_select(sql: str, relations: set[str]) -> None:
    """Require one SELECT with known relations and no mutation or external calls."""
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise ValueError("SQL comments are forbidden")
    statements = parse(sql,read="sqlite")
    if len(statements) != 1 or not isinstance(statements[0],exp.Select):
        raise ValueError("Exactly one SELECT is required")
    tree = statements[0]
    if any(isinstance(node,(exp.Union,exp.Intersect,exp.Except)) for node in tree.walk()):
        raise ValueError("Set operations are forbidden, including nested operations")
    forbidden = (exp.Insert,exp.Update,exp.Delete,exp.Create,exp.Drop,exp.Command,
                 exp.Alter,exp.Into,exp.Attach,exp.Pragma)
    if any(isinstance(node,forbidden) for node in tree.walk()):
        raise ValueError("Only read-only SELECT expressions are allowed")
    ctes = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this,exp.Identifier) or table.db or table.catalog:
            raise ValueError("External relations and table functions are forbidden")
        if table.name not in relations | ctes:
            raise ValueError(f"Unknown relation: {table.name}")
    # Unknown/UDF calls include load_extension and file/network functions.
    for function in tree.find_all(exp.Anonymous):
        raise ValueError(f"Unapproved function: {function.name}")


def validate_query(sql: str, max_rows: int = 100) -> None:
    """Enforce approved tables/columns, lexical restrictions and a literal row cap."""
    validate_select(sql,set(SCHEMA))
    tree = parse(sql,read="sqlite")[0]
    if any(not isinstance(star.parent,exp.Count) for star in tree.find_all(exp.Star)):
        raise ValueError("Star projections are forbidden; name approved columns explicitly")
    validate_metric_formulas(tree)
    # User-visible CTEs must not shadow approved database relations.
    if {cte.alias_or_name for cte in tree.find_all(exp.CTE)} & set(SCHEMA):
        raise ValueError("CTEs cannot shadow governed relations")
    limit = tree.args.get("limit")
    literal = limit.expression if limit else None
    if not isinstance(literal,exp.Literal) or not literal.is_int or not 1 <= int(literal.this) <= max_rows:
        raise ValueError("A bounded literal LIMIT is required")
    if tree.args.get("offset") is not None:
        raise ValueError("OFFSET is not allowed")
    try:
        qualify(tree.copy(),dialect="sqlite",schema=SCHEMA,validate_qualify_columns=True)
    except Exception as error:
        raise ValueError("SQL contains an unapproved or ambiguous column") from error
