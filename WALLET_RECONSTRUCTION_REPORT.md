# WALLET RECONSTRUCTION REPORT V2.1 — GŁĘBOKA REKONSTRUKCJA RPC I KLASTRY PORTFELI

## 1. Wyeliminowanie limitu 3 transakcji z V2
W V2 rekonstrukcja on-chain pobierała maksymalnie 3 transakcje `getTransaction(jsonParsed)` na portfel. W V2.1 (`src/step1_deep_wallet_rpc_v2_1.py`):
- Przeprowadzono wielostronicową paginację `getSignaturesForAddress` (do `1 000` sygnatur na portfel; łącznie przeanalizowano **`52,902` sygnatur** dla **`107` priorytetowych portfeli**).
- Sparsowano do **25 pełnych transakcji `jsonParsed` na portfel** (łącznie **`2,338` pełnych transakcji** — ponad 8-krotnie głębiej niż w V2):
  - Dla portfeli o `<= 25` transakcjach w całym życiu sparsowano **100% historii** (`history_complete = True`, `history_coverage = 1.0`, `data_confidence = "high_confidence"`, `n = 11`).
  - Dla wysokoczęstotliwościowych portfeli/botów (`> 25` sygnatur) zastosowano próbkowanie warstwowe (najstarsze transakcje genezy/finansowania + środek + najnowsze), jawnie ustawiając `history_complete = False` i obniżając ufność do `"medium_confidence"` lub `"low_confidence"`.

## 2. Rozkład poziomów ufności w `WALLET_INTELLIGENCE_V2_1.csv` (`n = 1291` portfeli)
| data_confidence | wallets_count |
| --- | --- |
| low_confidence | 1260 |
| medium_confidence | 12 |
| high_confidence | 11 |
| unknown | 8 |

## 3. Klasyfikacja relacji i klastrów (`WALLET_CLUSTERS_V2_1.csv`)
Zgodnie z sekcją 5 wymogów odróżniono 8 typów relacji i 5 poziomów pewności:
- **Zakup w tym samym slocie (`same_slot_co_buyers`) ma poziom `"low_confidence"` (`shared_control_proven = 0`) i NIE jest traktowany jako dowód wspólnej kontroli.**
- Wspólne źródło finansowania jest dzielone na prywatny portfel finansujący (`shared_private_funder`) oraz gorący portfel giełdy/CEX (`exchange_funded_wallets`, wykrywany po wysokiej gęstości wypłat `>=95 tx / <15 min`).

| relationship_type | confidence_level | wallets_count |
| --- | --- | --- |
| confirmed_technical_addresses | confirmed_technical_relationship | 12334 |
| creator_connected_wallets | medium_confidence | 4 |
| directly_linked_wallets | medium_confidence | 8 |
| exchange_funded_wallets | medium_confidence | 63 |
| repeated_co_snipers | low_confidence | 711 |
| same_slot_bundle_buyers | medium_confidence | 427 |
| same_slot_co_buyers | low_confidence | 3347 |
| unknown_relationship | unknown | 3288 |
