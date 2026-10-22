import pytest

from tessera.prompts import Prompt, load_prompts
from tessera.results import write_results


def test_load_prompts_and_estimates(tmp_path):
    path = tmp_path / "p.jsonl"
    path.write_text('{"id": 1, "prompt": "abcdefgh", "max_tokens": 10}\n\n{"id": "b", "prompt": "x"}\n')
    prompts = load_prompts(path)
    assert prompts == [Prompt("1", "abcdefgh", 10), Prompt("b", "x", 256)]
    assert [p.estimated_tokens() for p in prompts] == [12, 257]


@pytest.mark.parametrize("text, message", [('{"id": 1}\n', "not a prompt"), ('{"id": 1, "prompt": "a"}\n{"id": 1, "prompt": "b"}\n', "duplicate id")])
def test_bad_prompt_files(tmp_path, text, message):
    path = tmp_path / "p.jsonl"
    path.write_text(text)
    with pytest.raises(ValueError, match=message):
        load_prompts(path)


def test_results_formats(tmp_path):
    rows = [{"id": "a", "status": "ok", "attempts": 1, "text": "hi"}, {"id": "b", "status": "failed", "attempts": 3, "error": "x"}]
    assert write_results(tmp_path / "r.csv", rows) == 2
    assert (tmp_path / "r.csv").read_text().splitlines()[0] == "id,status,attempts,text,error"
    write_results(tmp_path / "r.jsonl", rows)
    assert len((tmp_path / "r.jsonl").read_text().splitlines()) == 2
