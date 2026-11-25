# V2_2_WALLET_INTELLIGENCE_REPORT — WALLET INTELLIGENCE 2.0, FIFO I POWTARZALNOŚĆ GRUP

## 1. Metodologia
Moduł `wallet_intelligence/wallet_intel_v2_2.py` buduje:
1. Profile portfeli z jawnym statusem `COMPLETE`, `PARTIAL_PAGINATED` oraz `INSUFFICIENT_HISTORY` (brak historii nigdy nie oznacza złego portfela ani zerowego win-rate).
2. Chronologiczny model **FIFO** przenoszący loty kosztowe przy transferach SPL pomiędzy portfelami (transfer nie jest sprzedażą!) i rozdzielający `REALIZED_FIFO_VERIFIED`, `UNREALIZED`, `ESTIMATED_PNL` oraz `UNKNOWN_PNL`.
3. Graf 8 typów relacji z wykluczeniem znanych portfeli giełd/custody (`KNOWN_CEX_CUSTODY_WALLETS`) oraz klasyfikacją `SAME_SLOT_BUY` wyłącznie jako `WEAK` (brak dowodu wspólnej kontroli).
4. Przyczynowy rejestr `wallet_cluster_track_record` wyliczany wyłącznie dla `outcome_known_at_ms <= cutoff_ts_ms`.

## 2. Liczba obserwacji i Braki
- Profile portfeli (`data/wallet_profiles_v2_2.csv`): **`660`** portfeli.
- Krawędzie grafu relacji (`data/wallet_graph_edges_v2_2.csv`): **`5875`** udokumentowanych krawędzi z `evidence_ids`.
- Zidentyfikowane wielokrotne klastry (`data/wallet_cluster_track_record_v2_2.csv`): **`118`** klastrów `CONFIRMED / PROBABLE`.

## 3. Rozkład krawędzi grafu i Top Klastry wg historii przed sygnałem
| relationship_type | confidence | edges_count |
| --- | --- | --- |
| COMMON_COUNTERPARTY | PROBABLE | 38 |
| CREATOR_LINK | CONFIRMED | 5 |
| DIRECT_FUNDING | CONFIRMED | 286 |
| REPEATED_CO_BUYING | PROBABLE | 332 |
| REPEATED_TRANSFER | CONFIRMED | 27 |
| REPEATED_TRANSFER | PROBABLE | 39 |
| SAME_SLOT_BUY | WEAK | 5090 |
| SHARED_FUNDER | CONFIRMED | 58 |

### Przykładowe rekordy `wallet_cluster_track_record_v2_2.csv`:
| cluster_id | tokens_accumulated | pre_pump_2x_wins | post_entry_failures | win_rate | median_entry_age_before_pump_sec | cumulative_realized_fifo_pnl_sol |
| --- | --- | --- | --- | --- | --- | --- |
| cl_BwWK17_DwYcmo | 6 | 0 | 6 | 0.0 | UNKNOWN | 0.4066 |
| cl_3tqpS1_5KhMUK_6Qa46j | 4 | 0 | 4 | 0.0 | UNKNOWN | 6.6719 |
| cl_BwWK17_Hjsrtr | 4 | 0 | 4 | 0.0 | UNKNOWN | 5.1858 |
| cl_2yuhb9_BwWK17 | 4 | 1 | 3 | 0.25 | 0.0000 | 0.7148 |
| cl_7siN3q_BwWK17 | 4 | 0 | 4 | 0.0 | UNKNOWN | 0.0033 |
| cl_5byH6q_BwWK17 | 4 | 0 | 4 | 0.0 | UNKNOWN | 0.0002 |
| cl_AgmyPN_BwWK17 | 3 | 0 | 3 | 0.0 | UNKNOWN | 0.4362 |
| cl_BwWK17_Gy4nMS | 3 | 0 | 3 | 0.0 | UNKNOWN | 0.6007 |
| cl_EMKY7r_haqq6q | 3 | 0 | 3 | 0.0 | UNKNOWN | 0.0822 |
| cl_haqq6q_nnnLxE | 3 | 0 | 3 | 0.0 | UNKNOWN | -0.1628 |
| cl_FxPeUc_nnnLxE | 3 | 0 | 3 | 0.0 | UNKNOWN | 0.1819 |
| cl_BwWK17_C6TWvL | 2 | 0 | 2 | 0.0 | UNKNOWN | 0.4424 |

## 4. Ograniczenia, Dowody i Status
- Publiczny węzeł RPC nie pozwala na bezkosztowe pobranie pełnych transakcji `jsonParsed` dla wszystkich dziesiątków tysięcy portfeli detalicznych — portfele bez pełnego pokrycia mają jawny status `INSUFFICIENT_HISTORY` lub `PARTIAL_PAGINATED`.
- W badanej próbie powtarzalne zyskowne klastry (`H2`) występują rzadko — większość powtarzających się grup to boty snajperskie lub deweloperskie o ujemnym lub zerowym wyniku netto dla kolejnych uczestników.
- Dowody: Testy akceptacyjne `16–22` (`PASS`).
- **Status:** `DATA_VALIDATED` (`PASS`).
