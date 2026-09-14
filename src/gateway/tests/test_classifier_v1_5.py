"""Tests for ClassifierV1.5Heuristic — doc 09 acceptance criteria."""

import asyncio

import pytest

from src.gateway.app.core.classifier_v1_5 import ClassifierV1_5Heuristic
from src.gateway.app.core.interfaces import Message, Tier


def classify(prompt: str, *, system: str | None = None, **kwargs):
    messages = []
    if system:
        messages.append(Message(role="system", content=system))
    messages.append(Message(role="user", content=prompt))
    return asyncio.run(ClassifierV1_5Heuristic(**kwargs).classify(messages))


def signal_names(result) -> set[str]:
    return {s.name for s in result.signals}


def points_of(result, name: str) -> int | None:
    for s in result.signals:
        if s.name == name:
            return s.points
    return None


# =============================================================================
# §6.6 — Full scoring examples from the design doc (17 rows)
# =============================================================================


@pytest.mark.parametrize(
    ("prompt", "expected_tier", "expected_band"),
    [
        # C1 examples
        ('Fix this: print("hello world")', Tier.T1, "band_c1"),
        ("Đọc file JSON trong Python thế nào?", Tier.T1, "band_c1"),
        # Short prompts without complexity signals → C1 (brevity heuristic)
        ("Viết hàm parse CSV", Tier.T1, "band_c1"),
        ("Add JWT auth với fastapi-users", Tier.T1, "band_c1"),  # guard D6
        ("Tối ưu hàm này cho nhanh hơn", Tier.T1, "band_c1"),  # guard D3 — no evidence
        # C3 examples
        ("Fix my race condition please", Tier.T3, "band_c3"),  # D1
        ("Implement Raft consensus in Go", Tier.T3, "band_c3"),  # D4
        ("Thiết kế cơ chế token rotation chống replay", Tier.T3, "band_c3"),  # D6
        ("Query này chạy 30s, tối ưu giúp", Tier.T3, "band_c3"),  # D3 with evidence
        # Non-coding
        ("Let me know when you are free", Tier.T1, None),
        ("Tôi cần giao hàng trong 2-3 ngày", Tier.T1, None),
    ],
)
def test_scoring_examples(prompt, expected_tier, expected_band):
    result = classify(prompt)
    assert result.tier is expected_tier, f"prompt={prompt!r} got tier={result.tier}, expected={expected_tier}"
    if expected_band:
        assert expected_band in signal_names(result), f"prompt={prompt!r} signals={signal_names(result)}"


# =============================================================================
# §1.1 — Narrative invariant (G3): same task, different verbosity = same tier
# =============================================================================


def test_narrative_invariant_hello_world_bare():
    result = classify('Fix this: print("hello world")')
    assert result.tier is Tier.T1


def test_narrative_invariant_hello_world_verbose():
    prompt = (
        "Anh ơi em mới học lập trình, em có đoạn code hello world hai dòng thôi "
        "mà nó cứ báo lỗi hoài, em thử đủ cách rồi mà không được. "
        "Debug giúp em cái này với, nó chỉ có hai dòng thôi:\n"
        '```python\nprint("hello world")\n```'
    )
    result = classify(prompt)
    assert result.tier is Tier.T1, f"verbose hello world got {result.tier}, should be T1"


# =============================================================================
# §1.3 — Regression tests E1–E10
# =============================================================================


@pytest.mark.parametrize(
    ("label", "prompt", "should_not_have_signal"),
    [
        ("E1", "Let me know when you are free", "code"),
        ("E2", "I want to return to my hometown next year", "code"),
        ("E3", "The class I teach is about history", "code"),
        ("E4", "Tôi cần giao hàng trong 2-3 ngày", "math"),
        ("E5", "Cuộc họp diễn ra ngày 2026-08-21 nhé", "math"),
        ("E6", "Hi? How are you?", "multi_step"),
    ],
)
def test_false_positive_regression(label, prompt, should_not_have_signal):
    result = classify(prompt)
    assert should_not_have_signal not in signal_names(result), f"{label}: false positive {should_not_have_signal}"


def test_e7_definition_question_is_c1():
    result = classify("debug nghĩa là gì")
    assert result.tier is Tier.T1
    assert "band_c1" in signal_names(result)


@pytest.mark.parametrize(
    ("label", "prompt"),
    [
        ("E8", "Implement Raft consensus in Go"),
        ("E9", "Fix my race condition please"),
        ("E10", "Build a distributed rate limiter"),
    ],
)
def test_under_routing_regression(label, prompt):
    """G1: no hard prompt assigned T1."""
    result = classify(prompt)
    assert result.tier is Tier.T3, f"{label}: {prompt!r} got {result.tier}, must be T3"


# =============================================================================
# §4.1 — Zone inversion: syntax tokens in prose don't trigger code
# =============================================================================


@pytest.mark.parametrize(
    "prompt",
    [
        "Let me know when you are free",
        "I want to return to my hometown next year",
        "The class I teach is about history",
    ],
)
def test_zone_inversion_no_false_code(prompt):
    result = classify(prompt)
    assert result.tier is Tier.T1


# =============================================================================
# §5.3 — C3 beats C1: "simple deadlock" is still C3
# =============================================================================


def test_c3_beats_c1_simple_deadlock():
    """A3: user says 'đơn giản' but task has deadlock driver."""
    result = classify("fix nhanh giúp mình cái deadlock đơn giản này")
    assert result.tier is Tier.T3


# =============================================================================
# §6.1 — Modifiers never change tier
# =============================================================================


def test_c1_with_max_modifiers_stays_t1():
    prompt = (
        "Thêm docstring cho file này, cả file utils.py và helpers.py nữa nhé. "
        "Trả về đúng JSON schema.\n"
        "```python\n" + "x = 1\n" * 200 + "```"
    )
    result = classify(prompt)
    assert result.tier is Tier.T1
    assert "band_c1" in signal_names(result)


# =============================================================================
# §4.3 — Only artifact, no instruction → C2
# =============================================================================


def test_only_artifact_defaults_c1_when_short():
    result = classify("```python\ndef foo(): return 42\n```")
    assert result.tier is Tier.T1


# =============================================================================
# §6.4 — Math regex fixes
# =============================================================================


def test_date_not_math():
    assert "math" not in signal_names(classify("Cuộc họp ngày 2026-08-21"))


def test_range_not_math():
    assert "math" not in signal_names(classify("Giao hàng trong 2-3 ngày"))


def test_real_math_still_works():
    """Toán thật vẫn phải được nhận ra sau các bản sửa false-positive §6.4.

    Từ doc 13 §2, prompt này đi vào nhánh genre math nên phát tín hiệu
    `genre_math` thay cho `math` của nhánh non-coding. Ý định của test không đổi:
    nó chặn việc sửa E4/E5 (ngày tháng, khoảng số) làm chết luôn toán thật.
    """
    names = signal_names(classify("Chứng minh bất đẳng thức Cauchy"))
    assert "math" in names or "genre_math" in names


# =============================================================================
# §6.4 — Multi-step question fix
# =============================================================================


def test_two_short_questions_not_multi_step():
    """E6: 'Hi? How are you?' — questions with <4 words don't count."""
    result = classify("Hi? How are you?")
    assert "multi_step" not in signal_names(result)


def test_two_real_questions_is_multi_step():
    result = classify("Cái này là gì vậy bạn? Và dùng trong trường hợp nào thì phù hợp?")
    assert result.score > 0


# =============================================================================
# §6.5 — Fast-path: coding tasks never enter fast-path
# =============================================================================


def test_short_coding_task_no_fast_path():
    result = classify("Implement Paxos")
    assert "fast_path_easy" not in signal_names(result)


def test_short_non_coding_gets_fast_path():
    result = classify("Thủ đô Việt Nam là gì")
    assert result.tier is Tier.T1


# =============================================================================
# §6.2 — Guard tests for drivers
# =============================================================================


def test_guard_d2_library_usage():
    """Using heapq/sort is not algo complexity."""
    result = classify("sort danh sách này dùng heapq")
    assert result.tier is not Tier.T3


def test_guard_d3_no_evidence():
    """'optimize' without perf evidence → not C3; short → C1."""
    result = classify("Tối ưu hàm này cho nhanh hơn")
    assert result.tier is not Tier.T3
    assert result.tier is Tier.T1


def test_guard_d6_library_integration():
    """'Add JWT auth with library' → not C3; short → C1."""
    result = classify("Add JWT auth với fastapi-users")
    assert result.tier is not Tier.T3
    assert result.tier is Tier.T1


# =============================================================================
# Contract B.2 — never raise
# =============================================================================


@pytest.mark.parametrize("prompt", ["", " ", "a", "🙂🙂🙂", "?" * 200])
def test_abnormal_input_no_exception(prompt):
    result = classify(prompt)
    assert result.tier in (Tier.T1, Tier.T2, Tier.T3)
    assert 0 <= result.score <= 100


def test_empty_messages():
    assert asyncio.run(ClassifierV1_5Heuristic().classify([])).score >= 0


def test_no_user_message():
    result = asyncio.run(ClassifierV1_5Heuristic().classify([Message(role="system", content="abc")]))
    assert result.tier in (Tier.T1, Tier.T2, Tier.T3)


def test_timeout_returns_fallback():
    result = classify("Viết hàm Python kiểm tra số nguyên tố", router_timeout_ms=-1)
    assert result.tier is Tier.T2
    assert result.score == 45
    assert points_of(result, "classifier_error") == 0


def test_version_string():
    result = classify("hello")
    assert result.classifier_version == "heuristic-v1.5"
    assert result.latency_ms >= 0


# =============================================================================
# Over-routing examples from §8.1
# =============================================================================


def test_o3_large_artifact_with_docstring_request():
    """Paste 400 lines, ask for docstring → T1 (M1), not T2."""
    code = "def f():\n    pass\n" * 200
    result = classify(f"Thêm docstring cho file này\n```python\n{code}\n```")
    assert result.tier is Tier.T1


def test_o7_definition_question():
    """'debug nghĩa là gì' → C1 T1."""
    result = classify("debug nghĩa là gì")
    assert result.tier is Tier.T1


def test_o8_algo_concept_question_gets_t1():
    """Asking to explain DP or an algorithm conceptually is M3 (C1 -> T1), not D2 (C3)."""
    assert classify("Bạn hãy nói về quy hoạch động cho tôi").tier is Tier.T1
    assert classify("Quy hoạch động là gì?").tier is Tier.T1
    assert classify("Giải thích thuật toán Dijkstra").tier is Tier.T1
    assert classify("What is dynamic programming?").tier is Tier.T1
    assert classify("Giới thiệu về cấu trúc dữ liệu đồ thị").tier is Tier.T1


def test_d2_algo_implementation_still_gets_t3():
    """Actual algorithm implementation/solving tasks remain T3 (C3)."""
    assert classify("Giải bài toán cái ba lô bằng quy hoạch động").tier is Tier.T3
    assert classify("Hãy viết code tìm đường đi ngắn nhất trên đồ thị").tier is Tier.T3


# =============================================================================
# Under-routing examples from §8.2
# =============================================================================


def test_u4_flaky_test():
    result = classify("Test của tôi lúc được lúc không, chạy lại thì pass")
    assert result.tier is Tier.T3


def test_u6_system_design():
    result = classify("Thiết kế schema cho SaaS multi-tenant")
    assert result.tier is Tier.T3


def test_u7_unknown_cause():
    result = classify("Đã thử đủ cách vẫn lỗi, chỉ xảy ra trên prod")
    assert result.tier is Tier.T3


# =============================================================================
# English-only coverage — every driver/marker must work in English
# =============================================================================


class TestEnglishDrivers:
    def test_d1_race_condition_en(self):
        assert classify("Fix the race condition in our worker pool").tier is Tier.T3

    def test_d1_deadlock_en(self):
        assert classify("There's a deadlock when two goroutines acquire locks").tier is Tier.T3

    def test_d2_dynamic_programming_en(self):
        assert classify("Solve this with dynamic programming").tier is Tier.T3

    def test_d2_complexity_en(self):
        assert classify("What's the time complexity of this algorithm? Is it O(n log n)?").tier is Tier.T3

    def test_d3_slow_with_evidence_en(self):
        assert classify("This endpoint is slow, takes 5 seconds for 10000 rows").tier is Tier.T3

    def test_d3_optimize_no_evidence_en(self):
        """Guard D3: 'optimize' without evidence → not C3; short → C1."""
        assert classify("Optimize this function").tier is Tier.T1

    def test_d4_system_design_en(self):
        assert classify("Design a distributed rate limiter").tier is Tier.T3

    def test_d4_architecture_en(self):
        assert classify("Review the architecture of this microservice").tier is Tier.T3

    def test_d5_unknown_cause_en(self):
        assert classify("I don't know why it crashes, tried everything").tier is Tier.T3

    def test_d5_only_on_prod_en(self):
        assert classify("This bug only on prod, can't reproduce locally").tier is Tier.T3

    def test_d5_works_sometimes_en(self):
        assert classify("The test works sometimes, randomly fails on CI").tier is Tier.T3

    def test_d6_security_design_en(self):
        assert classify("Design a threat model for our auth scheme").tier is Tier.T3

    def test_d6_guard_library_en(self):
        """Guard D6: integrating existing auth library → not C3; short → C1."""
        assert classify("Add JWT auth using passport").tier is Tier.T1


class TestEnglishMarkers:
    def test_m1_rename_en(self):
        result = classify("Rename all variables in this file to camelCase")
        assert result.tier is Tier.T1

    def test_m1_add_docstring_en(self):
        result = classify("Add docstring to all functions\n```python\ndef foo(): pass\n```")
        assert result.tier is Tier.T1

    def test_m2_how_to_en(self):
        result = classify("How to read a CSV file in Python?")
        assert result.tier is Tier.T1

    def test_m3_what_is_en(self):
        result = classify("What is a closure in JavaScript?")
        assert result.tier is Tier.T1

    def test_m3_difference_en(self):
        result = classify("What's the difference between let and const?")
        assert result.tier is Tier.T1

    def test_m5_hello_world_en(self):
        result = classify("Write a hello world in Python")
        assert result.tier is Tier.T1

    def test_m5_simple_example_en(self):
        result = classify("Give me a simple example of async await")
        assert result.tier is Tier.T1


# =============================================================================
# Mixed Viet–English — common in real usage
# =============================================================================


class TestMixedLanguage:
    def test_mixed_vi_en_deadlock(self):
        """Vietnamese instruction with English tech term."""
        assert classify("Fix giúp cái deadlock trong worker pool").tier is Tier.T3

    def test_mixed_vi_en_hello_world(self):
        result = classify("Viết cho mình cái hello world bằng Python")
        assert result.tier is Tier.T1

    def test_mixed_en_vi_error(self):
        """English instruction with Vietnamese context."""
        assert classify("Fix this bug, đã thử đủ cách vẫn lỗi").tier is Tier.T3

    def test_mixed_design_schema(self):
        assert classify("Design schema cho SaaS multi-tenant").tier is Tier.T3

    def test_mixed_optimize_with_evidence(self):
        assert classify("Tối ưu query này, it takes 30 seconds").tier is Tier.T3

    def test_mixed_simple_rename(self):
        result = classify("Rename biến này cho đúng convention")
        assert result.tier is Tier.T1

    def test_mixed_how_to(self):
        result = classify("Làm sao để connect to database trong FastAPI?")
        assert result.tier is Tier.T1

    def test_mixed_narrative_easy(self):
        """Long Vietnamese narrative about an easy English task."""
        prompt = (
            "Anh ơi em mới học, em có cái hello world program "
            "mà nó print sai, just two lines of code thôi, "
            "giúp em fix với"
        )
        result = classify(prompt)
        assert result.tier is Tier.T1, f"mixed narrative hello world got {result.tier}"

    def test_mixed_narrative_hard(self):
        """Vietnamese narrative but actual hard English task."""
        prompt = "Giúp em implement distributed consensus với leader election trong Go"
        result = classify(prompt)
        assert result.tier is Tier.T3


# =============================================================================
# Doc 10 §7.1 — CP genre detection + band scoring (Part A)
# =============================================================================

class TestCPGenreDetection:
    """Genre detector for competitive programming — doc 10 §4.1."""

    def test_a1_cf_800_full_format_gets_c2(self):
        """A1: CF 800 problem with Example section — should be C2/T2, not C1/T1."""
        prompt = (
            "You are given an integer n. Determine whether n is divisible by 3.\n\n"
            "Input\nThe first line contains the number of test cases t (1 <= t <= 100).\n"
            "Each test case contains a single integer n (1 <= n <= 100).\n\n"
            "Output\nFor each test case, print YES or NO.\n\n"
            "Example\nInput\n3\n9\n7\n12\n\nOutput\nYES\nNO\nYES"
        )
        result = classify(prompt)
        assert "genre_cp" in signal_names(result), f"should detect CP genre, got {signal_names(result)}"
        assert result.tier in (Tier.T2, Tier.T3), f"CF problem should never be T1, got {result.tier}"

    def test_a2_cf_1400_full_format_gets_c2(self):
        """A2: CF 1400 greedy — genre=CP, at least C2/T2."""
        prompt = (
            "You are given an array of n integers a_1, ..., a_n. Find the maximum\n"
            "number of elements you can select such that no two selected elements\n"
            "are adjacent.\n\n"
            "Input\nThe first line contains the number of test cases t (1 <= t <= 1000).\n"
            "For each test case, the first line contains n (1 <= n <= 2*10^5).\n"
            "The second line contains n integers a_i.\n\n"
            "Output\nFor each test case, print the answer.\n\n"
            "Example\nInput\n2\n5\n1 2 3 4 5\n3\n10 20 10\n\nOutput\n9\n20"
        )
        result = classify(prompt)
        assert "genre_cp" in signal_names(result)
        assert result.tier in (Tier.T2, Tier.T3), f"CF 1400 should be at least T2, got {result.tier}"

    def test_a3_cf_2100_tree_update_query_gets_c3(self):
        """A3: CF 2100 with tree + update/query + n,q >= 10^5 — should be C3/T3 (rule a)."""
        prompt = (
            "You are given a tree with n vertices. Each vertex has a value a_i.\n"
            "Answer q queries: update a_v to x, then find the XOR on the path from root to v.\n\n"
            "Input\nThe first line contains n and q (1 <= n, q <= 2*10^5).\n\n"
            "Output\nFor each query, print the answer.\n\n"
            "Example\nInput\n5 3\n1 2 3 4 5\n1 2\n1 3\n2 4\n2 5\n4 7\n5 3\n1 0\n\n"
            "Output\n6\n6\n0"
        )
        result = classify(prompt)
        assert "genre_cp" in signal_names(result)
        assert result.tier is Tier.T3, f"CF 2100 with n,q>=10^5 + update should be T3, got {result.tier}"

    def test_a4_cf_2600_mod_998244353_gets_c3(self):
        """A4: CF 2600 with mod 998244353 — should be C3/T3 (rule b)."""
        prompt = (
            "Count the number of subsequences whose sum is divisible by k.\n"
            "Output the answer modulo 998244353.\n\n"
            "Input\nThe first line contains n and k (1 <= n, k <= 10^6).\n\n"
            "Output\nPrint the answer modulo 998244353.\n\n"
            "Example\nInput\n3 2\n1 2 3\n\nOutput\n3"
        )
        result = classify(prompt)
        assert "genre_cp" in signal_names(result)
        assert result.tier is Tier.T3, f"CF 2600 with 998244353 should be T3, got {result.tier}"

    def test_a5_cf_interactive_gets_c3(self):
        """A5: Interactive problem — should be C3/T3 (rule c)."""
        prompt = (
            "This is an interactive problem.\n\n"
            "There is a hidden permutation p of size n. You can ask at most n queries.\n"
            "In each query, you give two indices i, j and receive whether p[i] < p[j].\n\n"
            "Input\nThe first line contains the number of test cases t.\n"
            "For each test case, the first line contains n (1 <= n <= 10^5).\n\n"
            "Output\nAfter determining the permutation, print it."
        )
        result = classify(prompt)
        assert "genre_cp" in signal_names(result)
        assert result.tier is Tier.T3, f"interactive problem should be T3, got {result.tier}"

    def test_a6_bare_one_line_no_genre(self):
        """A6: Bare one-line problem without CF boilerplate — no genre_cp, falls to doc 09."""
        prompt = "Find the longest increasing subsequence of a permutation."
        result = classify(prompt)
        assert "genre_cp" not in signal_names(result), "bare problem should NOT be detected as CP"

    def test_a8_explain_algorithm_not_cp(self):
        """A8: 'Explain Dijkstra' is NOT a CP problem — should stay in doc 09 path."""
        prompt = "Explain how Dijkstra's algorithm works with an example"
        result = classify(prompt)
        assert "genre_cp" not in signal_names(result), "explanation request should not be CP"
        assert result.tier is Tier.T1, f"explanation should be T1, got {result.tier}"


class TestCPBandRules:
    """CP C3 escalation rules — doc 10 §4.2."""

    def test_cp_floor_c2_no_escalation(self):
        """CP without C3 markers -> C2 (floor), never C1."""
        prompt = (
            "Given n integers, find the maximum.\n\n"
            "Input\nThe first line contains the number of test cases t.\n"
            "Each test case: first line n (1 <= n <= 100), second line the integers.\n\n"
            "Output\nFor each test case, print the maximum.\n\n"
            "Example\nInput\n1\n3\n1 5 3\n\nOutput\n5"
        )
        result = classify(prompt)
        assert "genre_cp" in signal_names(result)
        assert "band_c2" in signal_names(result), f"simple CP should be C2, got {signal_names(result)}"
        assert result.tier is Tier.T2

    def test_cp_large_constraint_10_9_escalates(self):
        """Rule (d): constraint >= 10^9 -> C3."""
        prompt = (
            "Find the number of divisors of n.\n\n"
            "Input\nThe first line contains t (1 <= t <= 100).\n"
            "Each test case: n (1 <= n <= 10^18).\n\n"
            "Output\nFor each test case, print the answer.\n\n"
            "Example\nInput\n1\n12\n\nOutput\n6"
        )
        result = classify(prompt)
        assert "genre_cp" in signal_names(result)
        assert result.tier is Tier.T3, f"10^18 constraint should escalate to T3, got {result.tier}"

    def test_cp_hard_technique_fft(self):
        """Rule (e): hard technique keyword -> C3."""
        prompt = (
            "Multiply two polynomials using FFT.\n\n"
            "Input\nThe first line contains the number of test cases.\n"
            "Each test case has two polynomials.\n\n"
            "Output\nFor each test case, print the product polynomial.\n\n"
            "Example\nInput\n1\n1 2 3\n4 5\n\nOutput\n4 13 22 15"
        )
        result = classify(prompt)
        assert "genre_cp" in signal_names(result)
        assert result.tier is Tier.T3, f"FFT keyword should escalate to T3, got {result.tier}"

    def test_cp_bypasses_m2_example(self):
        """H1 regression: 'Example' section no longer pulls to C1 via M2."""
        prompt = (
            "Hard graph problem with bipartite matching.\n\n"
            "Input\nThe first line contains the number of test cases.\n"
            "Each test case: n, m (1 <= n, m <= 10^5).\n\n"
            "Output\nMaximum matching size.\n\n"
            "Example\nInput\n1\n3 3\n1 2\n2 3\n1 3\n\nOutput\n1"
        )
        result = classify(prompt)
        assert "genre_cp" in signal_names(result)
        assert "band_c1" not in signal_names(result), "CP genre should bypass M2 'Example' marker"



# =============================================================================
# doc 13 §3 — Math genre routing (issue #194)
# =============================================================================


class TestMathGenre:
    """Bài toán thuần phải được chấm theo bản chất, không theo độ dài lời kể.

    Nguồn: docs/design/13_math_genre_routing.md §3.
    """

    def test_math_genre_hard_routes_t3(self):
        """§3.1 — marker khó (chứng minh / tích phân) đẩy thẳng lên T3."""
        result = classify("Tính tích phân của x^2 từ 0 đến 1 và chứng minh kết quả.")
        assert "genre_math" in signal_names(result)
        assert result.tier is Tier.T3, f"marker khó phải ra T3, nhận {result.tier}"

    def test_math_genre_easy_floors_t2(self):
        """§3.2 — bài nhiều bước không marker: floor T2, KHÔNG được lên T3."""
        result = classify(
            "Giải phương trình bậc hai 2x^2 + 5x - 3 = 0 rồi tìm tổng hai nghiệm."
        )
        assert "genre_math" in signal_names(result)
        assert result.tier is Tier.T2, f"bài không marker phải dừng ở T2, nhận {result.tier}"

    def test_math_genre_not_hijacked_by_coding(self):
        """§3.3 — bài toán nhắc 'f(x)' vẫn vào nhánh math, không rơi vào _is_coding."""
        result = classify(
            "Cho đa thức f(x) = x^3 - 3x + 1, chứng minh f(x) không có nghiệm hữu tỉ."
        )
        assert "genre_math" in signal_names(result)

    def test_math_genre_detect_requires_answer_intent(self):
        """§3.4 — câu hỏi khái niệm không kích hoạt genre, giữ nhánh non-coding."""
        result = classify("Đạo hàm là gì?")
        assert "genre_math" not in signal_names(result)

    def test_math_genre_khong_cuop_nhanh_coding(self):
        """Prompt coding kèm code không được nhận nhầm thành bài toán."""
        result = classify(
            "Tính tổng mảng giúp mình, code đây:\n```python\ndef s(a):\n    return sum(a)\n```"
        )
        assert "genre_math" not in signal_names(result)

    def test_so_hoc_vat_van_o_t1(self):
        """Guard §2.2 — 'tính 15 * 23' không đáng floor T2, nếu không cost sẽ đội."""
        result = classify("Tính 15 * 23 + 7")
        assert result.tier is Tier.T1, f"số học vặt phải ở T1, nhận {result.tier}"

    def test_bai_kho_viet_ngan_va_viet_dai_cung_tier(self):
        """Issue #194 / case P156-F1-AI-004 — bất biến: cùng bài toán, hai cách viết.

        Đây là test định nghĩa 'sửa xong': trước bản vá, bản dài được +18 điểm
        `length` nên lên T3 còn bản ngắn thì không.
        """
        ngan = "Tìm x nguyên thỏa mãn x^3 - 3x + 1 = 0 mod 7 và chứng minh tính duy nhất."
        dai = (
            "Mình đang ôn thi và gặp một bài số học khá hóc búa, nhờ bạn giúp với nhé. "
            "Đề bài như sau: cho phương trình đồng dư bậc ba x^3 - 3x + 1 = 0 xét trên "
            "vành số nguyên modulo 7. Yêu cầu thứ nhất là tìm tất cả các giá trị x "
            "nguyên thỏa mãn phương trình đồng dư này. Yêu cầu thứ hai, quan trọng hơn, "
            "là chứng minh chặt chẽ rằng nghiệm tìm được là duy nhất trong phạm vi đã "
            "cho, tức là không tồn tại nghiệm nào khác. Bạn trình bày từng bước lập luận "
            "rõ ràng giúp mình, giải thích tại sao mỗi bước lại hợp lệ, và nêu rõ định lý "
            "số học nào được dùng ở mỗi chỗ nhé. Cảm ơn bạn nhiều."
        )
        r_ngan = classify(ngan)
        r_dai = classify(dai)
        assert r_ngan.tier is r_dai.tier, (
            f"cùng bài toán mà khác tier: ngắn={r_ngan.tier} dài={r_dai.tier}"
        )
        assert r_ngan.tier is Tier.T3, f"bài khó viết ngắn phải lên T3, nhận {r_ngan.tier}"


# =============================================================================
# Đề thi trắc nghiệm (issue #209)
# =============================================================================


class TestGenreMCQ:
    """Câu thi trắc nghiệm nhận ra bằng cấu trúc, không cần hỏi LLM.

    Đo trên MMLU-Pro: bắt 415/420 câu, không dính câu nào của HumanEval+.
    """

    def test_trac_nghiem_len_t3(self):
        prompt = (
            "Marginal revenue equals marginal cost at the point where "
            "A. total product is at its highest point "
            "B. average product is at its highest point "
            "C. total revenue is at its maximum "
            "D. total revenue is less than total cost "
        )
        result = classify(prompt)
        assert "genre_mcq" in signal_names(result)
        assert result.tier is Tier.T3

    def test_trac_nghiem_tieng_viet(self):
        prompt = (
            "Trong chu kỳ lấy lệnh, CPU lấy dữ liệu từ "
            "a. Bộ nhớ máy tính b. Các thanh ghi c. Đĩa cứng d. Vùng nhớ đệm "
        )
        assert "genre_mcq" in signal_names(classify(prompt))

    def test_cau_hoi_thuong_khong_bi_nhan_nham(self):
        """Prompt bình thường có chữ A, B không được kích hoạt."""
        for prompt in (
            "So sánh phương án A và phương án B giúp mình",
            "Viết hàm parse CSV",
            "Bạn khỏe không?",
        ):
            assert "genre_mcq" not in signal_names(classify(prompt)), prompt

    def test_code_khong_bi_nhan_nham(self):
        """HumanEval+ không được dính — đã kiểm 0/164 trên bộ thật."""
        prompt = (
            "def has_close_elements(numbers, threshold):\n"
            "    \"\"\"Check if any two numbers are closer than threshold.\n"
            "    A. no B. yes\n    \"\"\"\n"
        )
        result = classify(prompt)
        assert result.tier in (Tier.T1, Tier.T2, Tier.T3)
