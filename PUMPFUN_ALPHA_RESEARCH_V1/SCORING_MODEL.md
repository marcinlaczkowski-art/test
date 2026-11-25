# SCORING MODEL — TRÓJFILAROWY SYSTEM OCENY POTENCJAŁU I RYZYKA (0–100)

## 1. Architektura Trzech Niezależnych Ocen (Rozdział 17)
Zgodnie ze specyfikacją nie łączono potencjału wzrostowego i ryzyka w jedną nieprzejrzystą liczbę. Każdy token otrzymuje w czasie rzeczywistym **trzy osobne wyniki w skali 0–100**:

### A. `PUMP POTENTIAL SCORE` (0–100)
Wyznaczany przez regularyzowany model regresji logistycznej (`BalancedL2Logistic`, wyuczony wyłącznie na pierwszych chronologicznie 50% tokenów bez przecieku informacji), kalibrowany na prawdopodobieństwo osiągnięcia **co najmniej $3\times$ dalszego wzrostu po momencie sygnału** z karą za gonienie przegrzanych świec (`already_moved_multiple > 8x`).

#### Wagi wyznaczone empirycznie na zbiorze treningowym:
| Cecha wejściowa (standaryzowana Z-score) | Waga empiryczna (L2 Logistic, Train 50%) |
| --- | --- |
| independent_buyer_velocity | 1.125 |
| creator_dumped_at_T | -0.7101 |
| dip_absorption_ratio_at_T | 0.7064 |
| causal_smart_wallets_in | 0.5059 |
| meme_shareability_score | 0.4728 |
| vol_to_mcap_ratio_at_T | 0.4246 |
| is_ticker_first_mover | -0.4241 |
| buy_sell_usd_ratio | -0.3423 |
| mayhem_enabled | 0.26 |
| wallet_concentration_change | 0.2472 |
| liquidity_growth_pct_at_T | -0.1498 |
| creator_prior_win_rate | 0.1457 |
| buyer_acceleration_ratio | 0.1346 |
| tx_acceleration_ratio | -0.0596 |
| sol_ret_24h_pct | -0.0451 |
| has_social_links | -0.0379 |


### B. `MANIPULATION RISK SCORE` (0–100)
Niezależny indeks mierzący sztuczną aktywność i manipulację mikrostrukturą:
- Aktywność autonomicznego bota `Mayhem Mode` (`+22–25 pkt`),
- Liczba portfeli bundlujących w tym samym bloku startowym (`do +25–30 pkt`),
- Udział snajperów z pierwszych sekund i anomalna dyspersja wielkości zleceń (`do +25 pkt`),
- Niski odsetek niezależnych kupujących oraz niska płynność puli (`do +20 pkt`).

### C. `INSIDER & SUPPLY RISK SCORE` (0–100)
Niezależny indeks koncentracji i ryzyka zrzutu podaży:
- Udział TOP 5 / TOP 10 holderów poza pulą płynności (`do +30–35 pkt`),
- Udział podaży w rękach wykrytych klastrów powiązanych portfeli i bundlerów (`do +25–30 pkt`),
- Wczesna sprzedaż przez portfel twórcy (`+10–20 pkt`),
- Szacowany wpływ zrzutu $5\%$ podaży na głębokość płynności AMM (`do +20 pkt`).

---

## 2. Interpretacja Macierzy Decyzyjnej
- **Wysoki Potential ($\ge 65$) + Niskie Ryzyko Manipulacji ($<40$) + Niskie Ryzyko Podaży ($<40$):** Priorytetowy kandydat organicznego popytu.
- **Wysoki Potential ($\ge 65$) + Wysokie Ryzyko Podaży/Manipulacji ($\ge 55$):** *Skoordynowany Insider Runner* — wysoka szansa na dynamiczny ruch (często napędzany przez klastry zamykające podaż), ale ekstremalne ryzyko nagłego załamania; oznaczany flagą `high_potential_high_risk_warning = 1` w `BACKTEST_RESULTS.csv`.
