"""Release gate: the golden evaluation set must hold on every commit.

A change that flips a golden conclusion (incumbent tier, work origin,
vulnerability read, decision verdict, grant eligibility) fails here before it
can ship a wrong verdict. Extend src/tools/eval_cases.py, don't weaken it.
"""
from src.tools.run_eval import run


def test_golden_evaluation_set_holds(capsys):
    exit_code = run()
    out = capsys.readouterr().out
    assert exit_code == 0, f"golden expectations broken:\n{out}"
    assert "All golden expectations hold." in out
