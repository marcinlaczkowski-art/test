# PUMPFUN ALPHA RESEARCH ENGINE — V1 • V2 • V2.1

Kompletne repozytorium projektu badawczego rynku **pump.fun (Solana)** podzielone na trzy niezależne wersje ewolucyjne w osobnych podfolderach:

1. **[`PUMPFUN_ALPHA_RESEARCH_V2_1/`](./PUMPFUN_ALPHA_RESEARCH_V2_1)** *(Wersja aktualna — rekomendowana)*
   - Ukierunkowana naprawa po drugim audycie (`PUMPFUN_ALPHA_V2_SECOND_AUDIT`): pełna kontrola znaczników czasu dla każdej cechy (`0% data leakage`), wspólny `src/feature_engine.py` (`100%` parzystości `Train/Val/OOT/Paper/Live`), `190/190` kompletności OOT dla `1h` i `4h`, wielostronicowa rekonstrukcja RPC portfeli, walidacja podaży (`<= 100%`), kolejka `FIFO` (`UNKNOWN_COST_BASIS`), symulator płynności `0.1–2.0 SOL`, 3-okresowy Walk-Forward z `4h` embargiem oraz 8 testów ablacji (`12/12` testów jednostkowych `PASS`).
   - Raport główny: [`PUMPFUN_ALPHA_RESEARCH_V2_1/FINAL_REPORT_V2_1.md`](./PUMPFUN_ALPHA_RESEARCH_V2_1/FINAL_REPORT_V2_1.md)

2. **[`PUMPFUN_ALPHA_RESEARCH_V2/`](./PUMPFUN_ALPHA_RESEARCH_V2)** *(Archiwalna przebudowa V2)*
   - Przebudowa na chronologiczny zbiór 650 tokenów bez selekcji po przyszłym ATH i wielohoryzontowe etykiety (`1h / 4h / 24h`).
   - Raport główny: [`PUMPFUN_ALPHA_RESEARCH_V2/FINAL_REPORT_V2.md`](./PUMPFUN_ALPHA_RESEARCH_V2/FINAL_REPORT_V2.md)

3. **[`PUMPFUN_ALPHA_RESEARCH_V1/`](./PUMPFUN_ALPHA_RESEARCH_V1)** *(Archiwalny oryginał V1)*
   - Pierwsza eksploracyjna wersja projektu badawczego zachowana w 100% jako punkt odniesienia do audytów.
   - Raport główny: [`PUMPFUN_ALPHA_RESEARCH_V1/FINAL_REPORT.md`](./PUMPFUN_ALPHA_RESEARCH_V1/FINAL_REPORT.md)
