"""Arithmetic formulas of KPIs: numbers, variables, + - * / and parentheses.

Formulas are typed by users, so they are never passed to ``eval``: they are
parsed with ``ast`` and only the nodes below are accepted and evaluated.
"""
import ast
import operator
import re

VARIABLE_CODE_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class FormulaError(ValueError):
    """The formula is not valid or cannot be evaluated."""


def _parse(formula):
    try:
        return ast.parse((formula or '').strip(), mode='eval').body
    except SyntaxError as error:
        raise FormulaError('syntax') from error


def formula_variables(formula):
    """Return the variable codes used in ``formula``.

    :raises FormulaError: with ``args[0]`` one of ``'empty'``, ``'syntax'`` or
        ``'unsupported'`` when the formula is not an arithmetic expression.
    """
    if not (formula or '').strip():
        raise FormulaError('empty')
    names = set()

    def visit(node):
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            visit(node.left)
            visit(node.right)
        elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            visit(node.operand)
        elif isinstance(node, ast.Constant) and type(node.value) in (int, float):
            pass
        elif isinstance(node, ast.Name):
            names.add(node.id)
        else:
            raise FormulaError('unsupported')

    visit(_parse(formula))
    return names


def evaluate_formula(formula, values):
    """Evaluate ``formula`` with ``values`` (``{code: number}``).

    :raises FormulaError: ``'division_by_zero'`` or ``'unknown_variable'`` on
        top of the errors of :func:`formula_variables`.
    """
    formula_variables(formula)

    def evaluate(node):
        if isinstance(node, ast.BinOp):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Div) and not right:
                raise FormulaError('division_by_zero')
            return _BINARY_OPERATORS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp):
            return _UNARY_OPERATORS[type(node.op)](evaluate(node.operand))
        if isinstance(node, ast.Constant):
            return float(node.value)
        if node.id not in values:
            raise FormulaError('unknown_variable', node.id)
        return float(values[node.id] or 0.0)

    return evaluate(_parse(formula))
