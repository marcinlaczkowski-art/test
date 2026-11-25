# BEHAVIORAL ANALYSIS — PSYCHOLOGIA RYNKU, DYNAMIKA KUPUJĄCYCH I PRZEJŚCIE W FOMO

## 1. Zwycięzcy (Pumpy 5x+) kontra Dopasowana Grupa Kontrolna (Przegrani)
Wszystkie wskaźniki wyznaczono bezpośrednio na podstawie rzeczywistych transakcji on-chain bez przypisywania nieudowodnionych intencji psychologicznych:

| Wskaźnik zachowań rynkowych | Pumpy 5x+ (Zwycięzcy) | Grupa Kontrolna (Przegrani) |
| --- | --- | --- |
| Unikalni kupujący w 1. minucie (mediana) | 29 | 3 |
| Unikalni kupujący w 5 minutach (mediana) | 51 | 4 |
| Unikalni kupujący w 30 minutach (mediana) | 53 | 5 |
| Średnia wartość pierwszych 10 zakupów USD (mediana) | 95.755 | 32.46 |
| Udział małych zakupów <$25 (mediana) | 0.5148 | 0.5 |
| Udział dużych zakupów >$250 (mediana) | 0.0315 | 0 |
| Kupujący zwiększający pozycję >=2x (scale-in share, mediana) | 0.1644 | 0.1 |
| FOMO Transition Index (0–100, mediana) | 19.99 | 10 |
| Czas do 10 kupujących w sekundach (mediana) | 3 | 22 |
| Odsetek zrzutu przez twórcę (creator_dumped_flag %) | 34.7 | 70 |


---

## 2. Mechanizm Przejścia w FOMO (`FOMO Transition Index`)
Zdefiniowaliśmy mierzalny wskaźnik przejścia w fazę FOMO oparty na dwóch jednoczesnych zjawiskach mikrostrukturalnych:
1. **Nagłe przyspieszenie tempa napływu nowych portfeli** ($\ge 2\times$ względem poprzednich 2 minut) już po wykonaniu przez cenę wstępnego wybicia ($\ge +25\%$).
2. **Asymetria przepływu kapitału** (`buy_sell_usd_ratio`) wspierana zagęszczeniem transakcji detalicznych.

- W grupie zwycięzców (`5x+`) mediana `fomo_transition_index` wynosi **19.99** wobec **10.00** w grupie kontrolnej — jest to jeden z najsilniejszych efektów w całym badaniu.
- **Małe zakupy kontra duże zakupy:** Największe pumpy inicjowane są przez większy kapitał startowy (wyższa mediana pierwszych 10 zakupów `early10_avg_buy_usd`), po czym w fazie FOMO dołącza fala drobnych zleceń detalicznych (`<$25`), która winduje łączną liczbę unikalnych adresów, podczas gdy przeciętny bilet pojedynczego zlecenia maleje wraz z popularyzacją tokena.

---

## 3. Dlaczego Obiecujące Tokeny z Grupy Kontrolnej Upadają? ($N = 207$ par)
Każdy z **207** tokenów kontrolnych został dopasowany czasowo (mediana różnicy startu rzędu kilku minut, ten sam reżim ceny `SOL`) do tokena wzrostowego:

| Mechanizm porażki tokena kontrolnego | Liczba tokenów | Udział (%) |
| --- | --- | --- |
| EARLY_DEV_OR_SNIPER_EXTRACTION | 108 | 52.17 |
| COLD_START_NO_ORGANIC_BUYERS | 79 | 38.16 |
| PROMISING_START_FAILED_FOMO_IGNITION | 11 | 5.31 |
| LOW_VOLUME_ATTRITION | 9 | 4.35 |


---

## 4. Sygnały Ostrzegające Przed Załamaniem (Zachowanie Sprzedających)
1. **Wczesna sprzedaż przez portfel twórcy (`creator_dumped_flag = 1`):** Drastycznie obniża medianę dalszego mnożnika wzrostu (potwierdzone z mocą dowodową **A** w teście H18).
2. **Brak absorpcji pierwszej korekty:** Gdy podczas pierwszego cofnięcia o $\ge 12\%$ wolumen sprzedaży przekracza zakupy (`dip_absorption_ratio < 0.8`) i zanika napływ nowych portfeli, token niemal zawsze przechodzi w trwałe wygaszanie płynności.
3. **Skoncentrowane wyjścia bundlerów z bloku startowego:** Tokeny z wysoką liczbą portfeli kupujących w tym samym bloku startowym (`bundle_wallets_count`) wykazują istotnie wyższe prawdopodobieństwo obsunięcia $>85\%$ od ATH.
