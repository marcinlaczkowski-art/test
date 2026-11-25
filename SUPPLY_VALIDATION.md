# SUPPLY VALIDATION REPORT V2.1 — WALIDACJA KONCENTRACJI PODAŻY (`<= 100%`)

## 1. Przyczyna źródłowa błędu `> 100%` w V2
Audyt V2 wykrył 3 tokeny, dla których suma udziałów Top-20 przekraczała 100% podaży (`102%–107%`). Analiza forensyczna transakcji wykazała dokładny mechanizm:
1. Pojedynczy portfel akumulacyjny (`429nhLprX8iFhSxjNQYEcyHLSquZAYbHUNbzq99GaqLU`) skupił w transakcji otwierającej `793.1M` tokenów (`79.31%` całkowitej podaży na krzywej za `85.005 SOL`), a następnie przetransferował tokeny **poza krzywą swapów** (transfer SPL / zasilenie wtórnej puli płynności) bez zdarzenia `sell` na pierwotnej krzywej.
2. Kolejni kupujący nabyli `23%–28%` z puli wtórnej, przez co naiwne sumowanie wyłącznie sald ze swapów bez odjęcia transferów SPL i wykluczenia wszystkich adresów pul `pool.address` dawało sumę `> 100%`.

## 2. Zastosowane zabezpieczenia w V2.1 (`wallet_supply_fifo_v2_1.py` & `feature_engine.py`)
1. **Deduplikacja transakcji** po kluczu `(txId, legIndex, eventIndex)`.
2. **Dynamiczne wykluczenie wszystkich adresów technicznych:** `bonding_curve`, `associated_bonding_curve`, `raydium_pool`, wszystkich `tr["pool"]["address"]`, adresów burn (`1111...`, `1nc1nerator...`) oraz programów systemowych SPL/PumpSwap.
3. **Uwzględnienie transferów i spaleń SPL** z rekonstrukcji RPC (`spl_transfers`).
4. **Twardy niezmiennik `sum(holders) <= effective_supply`:** Jeżeli mimo tego z powodu nieindeksowanego transferu poza-swapowego suma zrekonstruowanych sald przekracza `100.01%` efektywnej podaży, token otrzymuje status **`INVALID_SUPPLY_RECONSTRUCTION`** oraz `usable_in_model = 0` (`supply_valid_flag = 0` w silniku cech — zablokowany przed użyciem w modelu!).

## 3. Wyniki walidacji na pełnym zbiorze 650 tokenów (`SUPPLY_CONCENTRATION_V2_1.csv`)
- Poprawnie zwalidowane tokeny (`usable_in_model == 1`): **`649 / 650`**
- Tokeny zablokowane jako `INVALID_SUPPLY_RECONSTRUCTION`: **`1`** (2 z 3 anomalii V2 zostały w pełni uzgodnione po wykluczeniu wszystkich pul `pool.address` i transferów SPL, a pozostały `1` przypadek z niepełnym transferem off-swap został automatycznie zablokowany).
- Maksymalna suma udziałów wszystkich portfeli wśród zwalidowanych tokenów: **`99.8002%`** (100% zgodności z niezmiennikiem `<= 100%`).

### Zablokowane rekordy `INVALID_SUPPLY_RECONSTRUCTION`:
| mint | symbol | supply_status | raw_reconstructed_holder_sum_pct | usable_in_model | invalid_reason |
| --- | --- | --- | --- | --- | --- |
| EfV7zwLPtGn92aEtJhRJFyamDo2ZnxtAFnjSuygPpump | USOE | INVALID_SUPPLY_RECONSTRUCTION | 100.12 | 0 | Off-swap SPL transfer or secondary unindexed LP deposit created >100% swap-ledger balance sum |
