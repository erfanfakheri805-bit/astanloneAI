"""
Code Intelligence - Python Inspector
=====================================
Local, read-only structural analysis of Python source using the
standard library `ast` module. Source is only ever PARSED, never
executed - that is what makes it safe to run on arbitrary
user-provided text, including from the HTTP API.

This backs the `code_analysis` capability (see
capabilities/capability_system.py and core.Core._first_time_setup,
which flips it from "planned" to "active" now that this module gives
it a real implementation). It intentionally does not attempt code
generation, code modification, or multi-language support in this
stage - see the README for what is and is not implemented yet.
"""

import ast


def inspect_source(source, filename="<input>"):
    """Parse `source` as Python and return a structured summary:

        {
            "valid": bool,
            "syntax_error": {"message", "line", "column"} | None,
            "functions": [{"name", "line", "args", "is_async"}, ...],
            "classes": [{"name", "line", "bases"}, ...],
            "imports": [{"module", "line"}, ...],
        }

    Never raises for invalid input - a SyntaxError (or any other parse
    failure) is captured and returned as part of the result rather than
    propagated, matching the rest of the application's "always return a
    structured, honest verdict" style instead of crashing the caller.
    """
    result = {
        "valid": False,
        "syntax_error": None,
        "functions": [],
        "classes": [],
        "imports": [],
    }

    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        result["syntax_error"] = {"message": e.msg, "line": e.lineno, "column": e.offset}
        return result
    except (ValueError, TypeError) as e:
        # ast.parse can raise these for things like embedded null bytes.
        result["syntax_error"] = {"message": str(e), "line": None, "column": None}
        return result

    result["valid"] = True

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result["functions"].append({
                "name": node.name,
                "line": node.lineno,
                "args": [a.arg for a in node.args.args],
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            })
        elif isinstance(node, ast.ClassDef):
            result["classes"].append({
                "name": node.name,
                "line": node.lineno,
                "bases": [_name_of(b) for b in node.bases],
            })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append({"module": alias.name, "line": node.lineno})
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                full = f"{module}.{alias.name}" if module else alias.name
                result["imports"].append({"module": full, "line": node.lineno})

    return result


def _name_of(node):
    """Best-effort readable name for a base-class expression node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name_of(node.value)}.{node.attr}"
    return ast.dump(node)
