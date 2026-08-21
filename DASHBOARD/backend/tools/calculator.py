"""Safe arithmetic calculator tool. Copy any file in this folder to add a tool:
define a TOOL spec (or a TOOLS list) plus run(args) (or run_<name>(args))."""

import ast
import math
import operator as op

TOOL = {
    "name": "calculate",
    "description": "Evaluate a math expression (arithmetic, %, **, sqrt, log, etc). "
                   "Use for any pricing, forecast or unit-economics arithmetic.",
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "e.g. '4.99 * 120000 * 0.72'"},
        },
        "required": ["expression"],
    },
}

_OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
        ast.Pow: op.pow, ast.Mod: op.mod, ast.FloorDiv: op.floordiv,
        ast.USub: op.neg, ast.UAdd: op.pos}
_FUNCS = {"sqrt": math.sqrt, "log": math.log, "log10": math.log10, "exp": math.exp,
          "abs": abs, "round": round, "min": min, "max": max}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError("unsupported expression")


def run(args):
    expr = str(args.get("expression", ""))
    try:
        result = _eval(ast.parse(expr, mode="eval"))
        return "%s = %s" % (expr, result)
    except Exception as e:
        return "Error evaluating %r: %s" % (expr, e)
