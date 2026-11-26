"""parse_tx: wykrywa przejscie na kolejny portfel i zakup nowego coina przez operatora."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.operator_tracker import parse_tx  # noqa: E402


def _tx(signer, transfers=(), token_delta=None):
    ins = [{"parsed": {"type": "transfer", "info": {"source": s, "destination": d, "lamports": int(sol * 1e9)}}}
           for s, d, sol in transfers]
    pre, post = [], []
    if token_delta:
        mint, owner, amt = token_delta
        post.append({"mint": mint, "owner": owner, "uiTokenAmount": {"uiAmount": amt}})
    return {"meta": {"err": None, "preTokenBalances": pre, "postTokenBalances": post},
            "transaction": {"message": {"accountKeys": [{"pubkey": signer}], "instructions": ins}}}


def test_hop_and_new_coin():
    hops, mints = parse_tx(_tx("OP1", [("OP1", "OP2", 20.8)]), "OP1")
    assert hops == [("OP2", 20.8)] and mints == []
    hops, mints = parse_tx(_tx("OP1", [("OP1", "X", 0.5)], ("MINT", "OP1", 3.4e7)), "OP1")
    assert hops == [] and mints == ["MINT"]
    # zakup podpisany przez kogos innego nie jest coinem operatora
    assert parse_tx(_tx("OTHER", (), ("MINT", "OP1", 1.0)), "OP1") == ([], [])
