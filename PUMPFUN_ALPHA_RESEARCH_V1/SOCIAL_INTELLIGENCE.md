# SOCIAL & NARRATIVE INTELLIGENCE — NAZWY, MEMY, SPOŁECZNOŚĆ I WYDARZENIA ZEWNĘTRZNE

## 1. Wyniki Kategorii Tematycznych i Siły Narracji w 30 Dniach ($N = 2,726$ premier Grupy A)
| narrative_category | launches_30d | median_mult | pumps_5x | avg_shareability | migrated_rate | rate_5x_pct |
| --- | --- | --- | --- | --- | --- | --- |
| General_Novelty_Other | 1732 | 2.927 | 765 | 0.4736 | 49.6 | 44.17 |
| Animals_Pets | 327 | 6.727 | 175 | 0.5681 | 52.29 | 53.52 |
| AI_Agents_Tech | 138 | 8.756 | 83 | 0.4912 | 62.32 | 60.14 |
| Finance_Trading_Wealth | 115 | 1 | 27 | 0.4897 | 80.87 | 23.48 |
| Brands_Parody | 97 | 1 | 35 | 0.4069 | 35.05 | 36.08 |
| Internet_Memes_Culture | 85 | 3.061 | 37 | 0.5712 | 51.76 | 43.53 |
| Platform_Meta_Pump | 82 | 1.659 | 17 | 0.4792 | 18.29 | 20.73 |
| Politics_Macro | 61 | 2.565 | 24 | 0.521 | 62.3 | 39.34 |
| Anime_Gaming_Pop | 37 | 2.02 | 14 | 0.4531 | 54.05 | 37.84 |
| Absurd_Toilet_Humor | 28 | 23.16 | 19 | 0.5086 | 71.43 | 67.86 |
| Controversy_Edgy | 10 | 34.035 | 9 | 0.5009 | 90 | 90 |
| Celebrities_Creators | 10 | 2.609 | 4 | 0.4356 | 50 | 40 |
| Sports_Events | 4 | 7.628 | 2 | 0.4828 | 25 | 50 |


---

## 2. Analiza Semantyczna, Fonetyczna i Efekt Przesycenia Narracji (H22–H28)
1. **Mit krótkiego tickera obalony kontrolą populacyjną (H22):** Chociaż większość dużych pumpów posiada tickery 3–5-literowe, grupa kontrolna tokenów przegranych również ma medianę 4 znaków! Różnica efektu jest minimalna (`Cliff's d` bliskie zera) — krótki ticker jest warunkiem higienicznym, a nie samodzielnym predyktorem sukcesu.
2. **Łatwość wymowy i memetyczna udostępnialność (`pronounceability_score`, `meme_shareability_score` — H23, H24):** Wykazują dodatnią, statystycznie istotną, lecz umiarkowaną przewagę u zwycięzców (ocena **B**).
3. **Efekt Przesycenia Narracji (*Narrative Saturation*, H26 — Dowód A):** Tokeny uruchamiane w nienasyconym klastrze semantycznym ($\le 5$ podobnych premier w poprzednich 24h) osiągają wielokrotnie wyższe wyniki niż tokeny wrzucane w przesycony trend ($>15$ klonów w ciągu doby)!

---

## 3. Aktywność Społecznościowa vs Ruch Ceny oraz Zastrzeżenia Metodologiczne (Moduł 11)
- **Kierunek przyczynowości na `pump.fun`:** Analiza linków startowych (`twitter_link_type`) oraz dynamiki pierwszych minut wskazuje na wyraźną dychotomię:
  1. Tokeny podpinające link do **konkretnego zewnętrznego viralowego wpisu na X (`/status/...`) lub wydarzenia informacyjnego** reagują na istniejący już mem/wydarzenie zewnętrzne (wydarzenie internetowe → powstanie dziesiątek tokenów → koncentracja płynności na 1–2 liderach).
  2. Zaskakujący wynik testu **H29**: W kohorcie 5-minutowej samo posiadanie wklejonego linku X/WWW na starcie **nie gwarantowało** wyższego dalszego wzrostu po 5 min — masowi spamerzy rutynowo wklejają losowe lub recyklingowane linki X, podczas gdy wiele autentycznych memów zyskuje społeczność dopiero po pierwszym wybiciu cenowym (*cena najpierw przyciąga uwagę na tablicy pump.fun, a społeczność formuje się wtórnie wokół rosnącego wykresu*).
- **Rygor braku look-ahead bias:** Nie wykorzystywano dzisiejszej liczby obserwujących na X jako dowodu popularności przed historycznym pumpem (dane o historycznym stanie followerów z minuty startu nie są publicznie dostępne w otwartym API X).

### Dopasowanie do Wydarzeń Zewnętrznych Października–Listopada 2026 (Moduł 19):
| external_event_alignment | cohort_tokens | median_reliable_mult | avg_buyers |
| --- | --- | --- | --- |
| NONE | 486 | 1.849 | 45.331 |
| SOLANA_AI_AGENT_INFRA_ROLLOUT_NOV2026 | 5 | 1.354 | 33.8 |
| PUMPFUN_PRIVY_WALLET_CONTROVERSY_NOV2026 | 2 | 1.231 | 59.5 |
