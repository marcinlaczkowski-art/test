import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.replay_token import extract_mint

M = "5EmvWDizkpjAXbcfCcVq69w1id8GaLzi4LLwtuSgpump"


def test_extract_mint_from_link_and_raw():
    assert extract_mint(f"https://pump.fun/coin/{M}?highlight_callout=abc") == M
    assert extract_mint(M) == M
