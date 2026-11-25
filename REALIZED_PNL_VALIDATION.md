# REALIZED PNL VALIDATION V2.1 — ŚCISŁA KOLEJKA FIFO I KONTROLA BAZY KOSZTOWEJ

## 1. Metodologia FIFO (`src/wallet_supply_fifo_v2_1.py`)
W V2 zrealizowany wynik portfela był liczony uproszczonym saldem przepływów `SOL_out - SOL_in`, co błędnie przypisywało czysty zysk portfelom sprzedającym tokeny otrzymane darmowym transferem SPL z innego portfela. W V2.1 wdrożono pełną księgowość lotów **FIFO (First-In, First-Out)**:
1. Każdy zakup `buy` tworzy lot `[ilość_tokenów, koszt_jednostkowy_SOL_z_opłatą]`.
2. Zindeksowany transfer wewnętrzny SPL pomiędzy dwoma portfelami przenosi odpowiadające mu najstarsze loty FIFO wraz z ich oryginalną bazą kosztową (`carried_lots`) bez fałszywej realizacji zysku.
3. Każda sprzedaż `sell` konsumuje najstarsze dostępne loty FIFO portfela i wylicza zrealizowany PnL netto po odjęciu opłaty transakcyjnej.
4. **Twarda reguła `UNKNOWN_COST_BASIS`:** Jeżeli portfel sprzedaje więcej tokenów niż wynika z jego zindeksowanych zakupów i transferów przychodzących (`unmatched_sold_tokens > 0`), baza kosztowa jest nieznana — rekord otrzymuje `cost_basis_status = "UNKNOWN_COST_BASIS"` oraz `fifo_realized_pnl_sol = None` (brak zgadywania zysku!).
5. Rozdzielono 5 niezależnych kategorii: `fifo_realized_pnl_sol`, `fifo_unrealized_pnl_sol`, `internal_transfer_in/out_tokens`, `non_token_sol_flows_net_sol` oraz `fees_paid_sol`.

## 2. Podsumowanie `REALIZED_PNL_V2_1.csv` (`9,194` par portfel-token)
| cost_basis_status | wallet_token_rows |
| --- | --- |
| FIFO_VERIFIED | 5713 |
| FIFO_PARTIAL_TAPE | 2127 |
| UNKNOWN_COST_BASIS | 1354 |

- Zweryfikowano testem jednostkowym `09_fifo_realized_pnl_validation` (dwulotowy zakup `100 @ 0.01 SOL` + `100 @ 0.03 SOL`, częściowa sprzedaż `150 @ 0.05 SOL` -> dokładny zrealizowany wynik FIFO `+4.999625 SOL`, pozostałe `50` szt. z bazą `1.500075 SOL`, a sprzedaż bez pokrycia oznaczona jako `UNKNOWN_COST_BASIS`).
