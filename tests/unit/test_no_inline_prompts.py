"""
SPN-05 acceptance test: no prompt string literal exists outside the
prompts/ directory (enforced here as a lint test, per the WBS).

Two independent checks, both AST-based:

1. Call-site check (any file): a string literal passed as the `prompt=`
   or `system=` argument to any call is always a violation, regardless
   of length -- that argument name is exactly where a hand-written
   prompt would be smuggled in instead of a Prompt loaded from the
   registry.

2. Long-literal check (files that actually talk to the model): within a
   module that imports p1.llm or p1.prompts, OR that IS one of those
   modules itself (e.g. gateway.py doesn't need to import itself to be
   capable of holding a hand-written prompt) -- any string constant long
   and wordy enough to read as prose (not a docstring) is flagged too, in
   case a prompt is built into a plain local variable before being passed
   along under some other name.

Scoping check 2 to model-calling modules is what keeps this precise:
files that are all SQL (storage/messages_repo.py) or long descriptive
fixture text (scripts/generate_seed_fixtures.py) never call the gateway
and are not in scope for "did someone hand-write a prompt here."
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = [REPO_ROOT / "src", REPO_ROOT / "scripts"]

PROMPT_KEYWORD_ARGS = {"prompt", "system"}
MODEL_CALLING_MODULES = {"p1.llm", "p1.prompts"}

# A literal only counts as prompt-shaped under check 2 if it clears BOTH
# thresholds -- long enough and wordy enough that it reads as prose, not
# data (a SQL statement or a CSV description is long but not this).
MIN_CHARS = 200
MIN_WORDS = 30


def _docstring_locations(tree: ast.Module) -> set[tuple[int, int]]:
    """(lineno, col_offset) of every module/class/function docstring
    constant in this file, so they're excluded from both checks."""
    locations = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    locations.add((value.lineno, value.col_offset))
    return locations


def _is_own_model_calling_module(path: Path) -> bool:
    """True if `path` itself lives inside src/p1/llm/ or src/p1/prompts/ --
    those modules don't need to "import" themselves to be capable of
    holding a hand-written prompt (this is exactly how the first version
    of this check missed a literal added directly to gateway.py)."""
    parts = path.resolve().relative_to(REPO_ROOT).parts
    if "src" not in parts:
        return False
    remainder = parts[parts.index("src") + 1 :]
    return remainder[:2] in (("p1", "llm"), ("p1", "prompts"))


def _imports_model_calling_module(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and any(
            node.module == m or node.module.startswith(m + ".") for m in MODEL_CALLING_MODULES
        ):
            return True
        if isinstance(node, ast.Import) and any(alias.name in MODEL_CALLING_MODULES for alias in node.names):
            return True
    return False


def _is_model_calling_module(path: Path, tree: ast.Module) -> bool:
    return _is_own_model_calling_module(path) or _imports_model_calling_module(tree)


def _looks_like_prompt(text: str) -> bool:
    if len(text) < MIN_CHARS:
        return False
    return len(text.split()) >= MIN_WORDS


def _violations_in_file(path: Path) -> list[tuple[Path, int, str, str]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    docstring_locs = _docstring_locations(tree)
    found = []

    # Check 1: prompt=/system= keyword argument, any file.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in PROMPT_KEYWORD_ARGS and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    found.append((path, kw.value.lineno, kw.value.value[:80], f"literal passed as {kw.arg}="))

    # Check 2: long prose-shaped literal, only within model-calling modules
    # (either because the file imports p1.llm/p1.prompts, or because it IS
    # one of those modules).
    if _is_model_calling_module(path, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if (node.lineno, node.col_offset) in docstring_locs:
                    continue
                if _looks_like_prompt(node.value):
                    found.append((path, node.lineno, node.value[:80], "long prose-shaped literal"))

    return found


def _all_py_files():
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        yield from root.rglob("*.py")


def test_no_prompt_literals_outside_prompts_directory():
    violations = []
    for path in _all_py_files():
        violations.extend(_violations_in_file(path))

    assert not violations, (
        "Prompt-shaped string literal(s) found outside prompts/. Move the text to a "
        "versioned file under prompts/<capability>/vN.md and load it with "
        "p1.prompts.PromptRegistry instead:\n"
        + "\n".join(
            f"  {p.relative_to(REPO_ROOT)}:{ln}: [{reason}] {snippet!r}..."
            for p, ln, snippet, reason in violations
        )
    )
