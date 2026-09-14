"""Tests for text zoning — doc 09 §4."""

from src.gateway.app.core.zoning import split_zones


def test_fenced_block_goes_to_artifact():
    text = "Fix this:\n```python\nprint('hello')\n```"
    instruction, artifact = split_zones(text)
    assert "print" not in instruction
    assert "print" in artifact
    assert "Fix this" in instruction


def test_inline_code_goes_to_artifact():
    text = "What does `return` mean in Python?"
    instruction, artifact = split_zones(text)
    assert "`return`" not in instruction
    assert "return" in artifact


def test_no_artifact():
    text = "Let me know when you are free"
    instruction, artifact = split_zones(text)
    assert instruction == text
    assert artifact == ""


def test_empty():
    assert split_zones("") == ("", "")


def test_only_fence():
    text = "```python\ndef foo(): pass\n```"
    instruction, artifact = split_zones(text)
    assert instruction == ""
    assert "def foo" in artifact


def test_unclosed_fence_b7():
    """B7: unclosed fence → treat rest as artifact."""
    text = "Fix this:\n```python\nprint('hello')\nmore code"
    instruction, artifact = split_zones(text)
    assert "print" in artifact


def test_stack_trace_goes_to_artifact():
    text = (
        "I got this error:\n"
        'Traceback (most recent call last):\n'
        '  File "test.py", line 10, in <module>\n'
        '    foo()\n'
        'NameError: name \'foo\' is not defined'
    )
    instruction, artifact = split_zones(text)
    assert "Traceback" in artifact
    assert "I got this error" in instruction
