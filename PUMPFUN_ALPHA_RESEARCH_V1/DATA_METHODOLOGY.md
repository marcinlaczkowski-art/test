# DATA METHODOLOGY — METODOLOGIA BADAWCZA I KONTROLA BŁĘDÓW

## 1. Architektura Zbioru Danych i Eliminacja Survivorship Bias
1. **Pełne Uniwersum (`ALL_TOKENS.csv`, $N = 8,462$):**
   - **Grupa A — NEW TOKENS ($N = 2,726$):** Tokeny utworzone na `pump.fun` wewnątrz okna 30-dniowego (`2026-10-25T22:22:02+00:00` – `2026-11-24T22:22:02+00:00`). Aby uniknąć błędu przeżywalności (*survivorship bias*), zbiór zbudowano łącząc: (a) globalne rankingi `market_cap`, `ath_market_cap`, `created_timestamp`, `last_trade_timestamp` (zarówno `complete=true`, jak i `complete=false`), (b) stratyfikowane zapytania alfanumeryczne (`a–z`, `0–9`) i tematyczne, oraz (c) **pełne historie wszystkich tokenów utworzonych przez 689 twórców** (`coins-v2/user-created-coins`), z których większość stanowią tokeny nieudane, porzucone i martwe rozłożone równomiernie w ciągu całych 30 dni.
   - **Grupa B — PUMP EVENTS ($N = 2,289$ w uniwersum; $N = 192$ zweryfikowanych świecowo w kohorcie głębokiej):** Wszystkie tokeny `pump.fun`, które wykonały realny ruch wzrostowy ($\ge 2\times$ wiarygodnej ceny przy kapitalizacji szczytowej $\ge \$7\,500$) w badanym okresie, wliczając starsze tokeny uruchomione przed `2026-10-25`.

2. **Odkrycie i Kwarantanna Zmanipulowanych Pul (`ATH Spoofing`):**
   - Podczas audytu surowych danych wykryto **193 tokeny** w oknie 30-dniowym (m.in. klony o tickerach `USOE`, `XTX`, `AODF`, `test`), które raportowały pozorne `ath_market_cap` rzędu $\$50\text{M}–\$76\text{B}$ przy zerowej lub śladowej płynności kanonicznej ($<\$1\,500$) i bieżącej wycenie $\sim \$1\,300$ (pojedyncze transakcje na niestandardowych pulach lub niezmigrowane tokeny z błędem kwotowania).
   - Zgodnie z wymogiem metodologicznym (*„Nie uznawaj pojedynczego zakupu przy bardzo niskiej płynności za wiarygodny pump. Oddzielaj anomalie cenowe”*), tokeny te zostały oznaczone flagą `status_suspicious_activity = 1` w `ALL_TOKENS.csv` i **wykluczone z rankingów prawdziwych pumpów oraz treningu modelu**.

---

## 2. Trzy Niezależne Miary Wzrostu (Rozdział 4)
Dla każdego z **493** tokenów głębokiej kohorty wyznaczono trzy oddzielne mnożniki:
1. **`raw_single_tx_multiple`:** Stosunek maksymalnej ceny pojedynczego ticku transakcyjnego do minimalnego ticku początkowego (podatny na szpilki przy niskiej płynności).
2. **`reliable_market_multiple`:** Stosunek maksymalnej wiarygodnej ceny świecowej $\max(\text{Close}, 0.5(\text{High}+\text{Close}))$ wspartej obrotem $\ge \$50$ na świecę i wieloma transakcjami do pierwszej wiarygodnej ceny rynkowej po inicjalizacji krzywej.
3. **`realizable_liquidity_adj_multiple`:** Mnożnik możliwy do zrealizowania dla standardowej pozycji wyjściowej $\$500$ z uwzględnieniem głębokości jednostronnej puli $D = 0.5 \cdot L_{\text{USD}}$ na stałym iloczynie AMM ($x \cdot y = k$) oraz łącznych opłat transakcyjnych ($1.2\%$):
   $$M_{\text{realizable}} = M_{\text{reliable}} \cdot \frac{1}{1 + \frac{500}{0.5 \cdot L_{\text{USD}}}} \cdot 0.988$$

---

## 3. Eliminacja Look-Ahead Bias i Przecieku Danych
- W module **Early Signal Detection (`EARLY_SIGNALS.csv`)** dla każdego punktu $T \in \{30\text{s}, 1\text{m}, 3\text{m}, 5\text{m}, 10\text{m}, 15\text{m}, 30\text{m}\}$ uwzględniono **wyłącznie transakcje o `blockTimeMs <= created_timestamp + T`**.
- Cechy historyczne twórcy (`creator_prior_win_rate`) oraz portfeli Smart Money (`causal_smart_wallets_in`) obliczono **ściśle przyczynowo**: portfel otrzymuje status historycznie skutecznego tylko na podstawie tokenów uruchomionych co najmniej 60 minut przed startem bieżącego tokena.
- Walidacja modelu odbywa się na **podziale ściśle chronologicznym** (50% Train / 20% Val / 30% Test wg czasu utworzenia tokena) oraz **5-krokowej rozszerzającej walidacji kroczącej (*Expanding Walk-Forward*)**.
- Przy testowaniu **35 hipotez badawczych** zastosowano nieparametryczny test Manna-Whitneya U (odporny na skośność rozkładów krypto), miarę siły efektu **Cliff's $\delta \in [-1, 1]$** oraz korektę wielokrotnego testowania **Benjamini-Hochberg False Discovery Rate ($q_{\text{FDR}}$)**.
