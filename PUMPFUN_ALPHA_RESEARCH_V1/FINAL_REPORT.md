# PUMPFUN ALPHA RESEARCH ENGINE — RAPORT KOŃCOWY
## Kompleksowe Badanie Ilościowe, On-Chain Forensics, Insider Intelligence i Wczesna Predykcja Pumpów na Solanie

---

## 1. Podsumowanie Wykonawcze i Zakres Danych
- **Okno badawcze (30 dni):** `2026-10-25T22:22:02+00:00` → `2026-11-24T22:22:02+00:00` (`2026-10-25T23:22:02+01:00` → `2026-11-24T23:22:02+01:00` czasu polskiego CET).
- **Zebrane uniwersum `pump.fun`:** **8,462** unikalnych tokenów, w tym **2,726** premier utworzonych w ostatnich 30 dniach (**Grupa A**) oraz **2,289** zdarzeń wzrostowych łącznie ze starszymi tokenami wybitymi w tym oknie (**Grupa B**).
- **Głęboka kohorta transakcyjno-świecowa:** **493** tokenów z pełną rekonstrukcją świec (`1m`, `15m`, `4h`), taśm transakcyjnych od sekundy zero życia tokena, płynności DexScreener, **689** historii twórców, **420** portfeli zweryfikowanych w `profile-api.pump.fun` oraz śledzeniem finansowania `SOL` przez `Solana RPC`.
- **Odkryte anomalie i higiena danych:** Zidentyfikowano i odseparowano **193 zmanipulowane pule wash-tradingowe** (raportujące fałszywe miliardowe `ath_market_cap` przy zerowej płynności) oraz **799 tokenów z aktywnym/zakończonym trybem bota AI `Mayhem Mode`**.

---

## 2. Bezpośrednie Odpowiedzi na 20 Ostatecznych Pytań Badawczych (Rozdział 24)

1. **Jakie 10 cech najczęściej łączy tokeny o największych wzrostach?**
   (1) Wysokie tempo napływu **niezależnych kupujących** w pierwszych minutach (`independent_buyer_velocity`: mediana `2.4/min` vs `0.6/min` w grupie kontrolnej, waga modelu `+1.125`); (2) silna **absorpcja pierwszej korekty** (`dip_absorption_ratio`: mediana `2.46x` vs `0.80x`, `Cliff's d = +0.597`); (3) asymetryczna przewaga dolarowa kupna nad sprzedażą (`buy_sell_usd_ratio`: mediana `1.73x` vs `1.00x`); (4) brak wczesnego zrzutu tokenów przez twórcę (`creator_dumped_at_T = 0`); (5) 3-krotnie wyższy początkowy bilet zakupu w pierwszych 10 transakcjach (`mediana $95.8` vs `$31.5`); (6) wysoki indeks przejścia w FOMO (`fomo_transition_index`, $p < 10^{-19}$); (7) status **First-Mover** dla tickera (`mediana 7.25x` vs `1.91x` dla klonów); (8) niska saturacja semantyczna narracji ($\le 5$ podobnych premier w 24h: `11.30x` vs `2.37x`); (9) wyłączony sztuczny bot `Mayhem Mode` (`7.37x` vs `1.52x`); (10) dodatni reżim makro `SOL` (`24h > 0%`: `2.20x` vs `1.00x`).

2. **Jakie cechy pojawiają się najwcześniej?**
   Już w pierwszych **30–180 sekundach** widoczne są: wielkość pierwszych 10 zakupów, brak sprzedaży twórcy, tempo napływu niezależnych portfeli (po odfiltrowaniu bundli z bloku 0), status *First-Mover*, saturacja semantyczna nazwy oraz wyłączenie trybu `Mayhem Mode`.

3. **Które sygnały mają największą wartość predykcyjną?**
   Przed ucieczką ceny ($\le 3\times$ od startu) najwyższą wartość predykcyjną dają: **absorpcja pierwszego cofnięcia (`dip_absorption_ratio >= 1.35`)**, **przewaga kupna do sprzedaży USD (`>= 2.2x`)**, **stosunek obrotu do kapitalizacji (`vol/mcap >= 0.35`)** oraz **tempo niezależnych kupujących (`>= 2.5/min` bez sprzedaży twórcy)** — wszystkie z oceną dowodu **A**.

4. **Czy są konkretne godziny z wyższym prawdopodobieństwem pumpa?**
   Surowa liczba pumpów jest najwyższa podczas sesji USA (`15:00–22:00` czasu polskiego CET), ale ze względu na proporcjonalny wysyp nowych premier **warunkowe prawdopodobieństwo sukcesu pojedynczego tokena nie różni się istotnie statystycznie między sesją USA a pozostałymi godzinami** (H30, $q_{\text{FDR}} > 0.30$). Lekką przewagę punktową wykazują pojedyncze godziny przejściowe (szczegóły w `HOURLY_PATTERNS.csv`), jednak sam zegar nie tworzy przewagi bez sygnałów on-chain.

5. **Jakie rodzaje nazw i tickerów mają największy potencjał?**
   Nazwy łatwe do wymówienia (`pronounceability_score > 0.70`) i o wysokiej udostępnialności memetycznej (`meme_shareability_score`) uzyskują statystycznie wyższe mnożniki (H23, H24 — klasa **B**), natomiast **sama krótka długość tickera (3–5 znaków) NIE odróżnia zwycięzców od przegranych**, ponieważ 90%+ martwych tokenów również stosuje krótkie tickery (H22). Kluczowa jest świeżość semantyczna (brak przesycenia podobnymi nazwami w ostatnich 24h — H26, klasa **A**).

6. **Jakie narracje są najbardziej skuteczne?**
   Największą objętość kapitału i liczbę dużych wybić generują narracje **`AI_Agents_Tech`** (napędzane wdrożeniem `solana.ai`), **`Animals_Pets`**, **`Internet_Memes_Culture`** oraz **`Absurd_Toilet_Humor`**. Pomiędzy samą kategorią AI a absurdalnym humorem nie ma statystycznej różnicy w medianie mnożnika (H27 — klasa **D**): o sukcesie decyduje moment wejścia w nowy mikrotrend przed falą klonów.

7. **Jak zachowują się pierwsi kupujący?**
   W przyszłych pumpach pierwsi nabywcy wchodzą większym przeciętnym kapitałem niż w tokenach martwych (H08 — klasa **A**) i częściej dokupują kolejne transze w miarę potwierdzania popytu (`scale_in_buyer_share`, H11 — klasa **A**), zamiast realizować natychmiastowy zysk po kilkunastu procentach ruchu.

8. **Jak rozpoznać moment przejścia w FOMO?**
   Przejście w FOMO następuje w minucie, w której po wstępnym wzroście ceny o $\ge 25\%$ tempo napływu **nowych** portfeli przyspiesza ponad dwukrotnie względem poprzednich minut, udział mniejszych zleceń detalicznych (`<$25`) rośnie do $>65\%$, a odstępy między transakcjami spadają poniżej kilku sekund (`FOMO Transition Index > 50`, H07 — $p < 10^{-20}$, klasa **A**).

9. **Czy powtarzają się grupy portfeli kupujących przed pumpami?**
   Tak — w zbiorze wykryto **608 klastrów portfeli** oraz dziesiątki par adresów współwystępujących w pierwszych 15 kupujących na $\ge 3$ niezależnych tokenach (`WALLET_CLUSTERS.csv`, `WALLET_INTELLIGENCE.csv`).

10. **Czy można rozpoznać insiderów na podstawie przepływów między portfelami?**
    Tak, łącząc analizę tego samego bloku startowego (`blockId` + `txIndex`), bezpośrednie transfery `SOL` przed startem tokena z `Solana RPC` oraz wspólne prywatne portfele finansujące — przy obowiązkowym odfiltrowaniu gorących portfeli giełd CEX/mostów o wysokiej częstotliwości transakcji.

11. **Jaka część podaży największych pumpów znajduje się w rękach powiązanych klastrów?**
    W fazie akumulacji i szczytu powiązane klastry oraz potencjalni insiderzy kontrolują w największych pumpach nierzadko od kilkunastu do ponad $30\%–50\%$ aktywnej podaży poza pulą płynności (szczegółowy rozkład w 7 punktach czasu w `SUPPLY_CONCENTRATION.csv`).

12. **Czy insiderzy sprzedają podczas pumpa, czy utrzymują większość tokenów?**
    Występują oba reżimy (`INSIDER_PROFIT_ANALYSIS.csv`): w trwałych i wielofalowych projektach powszechny jest wzorzec **`PARTIAL_TAKE_PROFIT_HIGH_RETENTION`** (odzyskanie włożonego kapitału `SOL` + zysk podczas wzrostu przy zachowaniu istotnego pakietu tokenów), podczas gdy w szybkich rug-pullach następuje **`FULL_DISTRIBUTION_EXIT`**.

13. **Czy duża koncentracja podaży jest sygnałem potencjału, czy przede wszystkim ryzyka?**
    Jest **mieczem obosiecznym**: kontrolowana wczesna koncentracja ułatwia wypchnięcie ceny po krzywej bondingowej (dlatego pumpy mają wyższą koncentrację szczytową niż martwe tokeny — H14), ale jednocześnie tworzy potężny nawis podażowy — zrzut $5\%–10\%$ podaży przy płytkiej płynności wywołuje załamanie ceny o dziesiątki procent (`INSIDER_RISK.csv`), a agresywne bundlowanie na starcie sprzyja krachom $>85\%$ (H17). Dlatego nasz system bezwzględnie rozdziela `Pump Potential Score` od `Insider & Supply Risk Score`.

14. **Jak rozpoznać organiczne zainteresowanie?**
    Organiczny popyt cechuje się: (a) wysokim udziałem niezależnych portfeli niepowiązanych wspólnym blokiem startowym ani prywatnym funderem, (b) rosnącym przyspieszeniem liczby kupujących w minutach 2–10, (c) brakiem aktywnego bota `Mayhem Mode`, oraz (d) silną absorpcją pierwszej korekty przez nowych nabywców.

15. **Jak odróżnić sztuczny wolumen od realnego popytu?**
    Trzy niezawodne filtry on-chain wykryte w badaniu: (1) sprawdzenie flagi protokołu `mayhem_state` (eliminuje 24-godzinny sztuczny obrót agenta AI), (2) porównanie raportowanego `ath_market_cap` z realną płynnością kanoniczną `canonical_pool_liquidity_usd` i statusem migracji `complete` (eliminuje 193 zmanipulowane pule wash-tradingowe), oraz (3) pomiar stosunku unikalnych niezależnych kupujących do całkowitej liczby transakcji (`tx_count / unique_independent_buyers`).

16. **Jak zachowują się tokeny przed kolejnymi falami wzrostu?**
    Tokeny wielofalowe (`11_MULTI_WAVE_PUMP`) po pierwszej fali ($\ge 2.2\times$) i głębokiej korekcie ($\ge 35\%$) wykazują stabilizację bazy holderów, wygaszenie presji sprzedażowej dużych portfeli oraz ponowny skok przyspieszenia nowych kupujących z wyższego dołka płynnościowego.

17. **Jakie sygnały ostrzegają przed załamaniem?**
    (1) Sprzedaż $\ge 40\%–50\%$ pakietu przez portfel twórcy; (2) wysoka liczba portfeli bundlujących z bloku 0 rozpoczynających synchroniczną realizację zysków; (3) załamanie relacji kupna do sprzedaży (`buy_sell_usd_ratio < 0.7`) na pierwszym cofnięciu; (4) dysproporcja między wysoką kapitalizacją nominalną a niską płynnością puli DEX ($L_{\text{USD}}$), gdzie sprzedaż $5\%$ podaży załamuje cenę o $>40\%$.

18. **Jakie wzorce są mocne, a które pozornie interesujące?**
    - **Mocne (Klasa A):** Tempo niezależnych kupujących (`H02`), asymetria popytu `buy/sell USD` (`H04`), absorpcja pierwszej korekty (`H06`), indeks przejścia w FOMO (`H07`), wielkość pierwszych 10 zakupów (`H08`), brak sprzedaży twórcy (`H18`), łatwość wymowy tickera (`H23`), premia *First-Mover* (`H25`), niska saturacja narracji (`H26`), dodatni reżim `SOL` (`H33`).
    - **Pozornie interesujące / obalone przez dane (Klasa D):** Włączenie bota AI `Mayhem Mode` (`H21` — silny efekt ujemny: `1.52x` vs `7.37x`!), sama krótka długość tickera (`H22`), wulgarność/kontrowersyjność nazwy (`H28`), sztywne godziny sesji USA/UE (`H30–H31`), założenie mniejszego obsunięcia po migracji na DEX (`H34` — zjawisko *sell-the-graduation*).

19. **Jaka kombinacja sygnałów daje najlepsze rezultaty?**
    Połączenie w oknie **`1m – 5m`**: wysokiego tempa niezależnych kupujących (`>= 2.5/min`) + absorpcji pierwszego cofnięcia (`>= 1.35x`) + braku sprzedaży twórcy + wejścia portfeli *Smart Money* + statusu *First-Mover* przy wyłączonym `Mayhem Mode`, wsparte kontrolą `Manipulation Risk Score` i `Insider Supply Risk Score`.

20. **Czy model jest lepszy od prostych metod wyboru tokenów?**
    **TAK — w pełnym przekroju rankingowym i relacji zysku do pozostałego potencjału ($N_{\text{OOS}} = 356$):** Model `Pump Potential` uzyskał **`ROC-AUC = 0.745`**, **`Precision@20 = 70.0%`** (**`Lift = 1.947x`** względem losowego `35.0%`), średni zwrot netto po kosztach **`+147.76%`** (mediana **`+203.41%`**) oraz medianę przyszłego mnożnika **`32.067x`**. Wyraźnie pokonał globalnie sam wolumen (`ROC-AUC = 0.6528`, `Precision@20 = 60.0%`, mediana mnożnika `6.881x`) i losowy wybór (`ROC-AUC = 0.5286`). Ciekawą obserwacją badawczą jest to, że sam skrajny ogon `independent_buyer_velocity` (będący zresztą wagą nr 1 naszego modelu: `+1.125`) osiąga rekordowe `Precision@10` w wąskim top-10 przy niższym globalnym `ROC-AUC = 0.6103`, natomiast gonienie samego wzrostu ceny (`Price_Gain_Only`) daje mniejszy przyszły mnożnik (`11.099x` vs `32.067x` modelu), ponieważ wchodzi po wykonaniu znacznej części ruchu.

---

## 3. TOP 10 Sygnałów Wczesnego Wykrywania (1–15 min) — Zestawienie Końcowe
| signal_name | definition | measurement_formula | availability_window | n_tokens_triggered | hit_rate_future_3x | lift_vs_baseline | median_future_multiple | mean_future_multiple | median_max_drawdown_pct | manipulation_resilience_and_risk | evidence_grade |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1. Institutional-Size Initial Conviction Ticket | Mediana pojedynczego zakupu >= $60 przy min. 6 kupujących i braku sprzedaży twórcy. | median_buy_usd >= 60 & new_buyers_cum >= 6 & creator_dumped_at_T == 0 | 1m–5m | 6 | 0.6667 | 2.49 | 77.82 | 163.8 | 63.19 | Średnie — wymaga weryfikacji klastrów finansowania | B |
| 2. Positive Macro SOL Regime + Buyer Flow | Start tokena w dodatnim reżimie SOL (24h > 0%) połączony z >= 5 niezależnymi kupującymi i brakiem sprzedaży twórcy. | sol_ret_24h_pct > 0 & independent_buyers_cum >= 5 & creator_dumped_at_T == 0 | 3m–10m | 24 | 0.625 | 2.34 | 44.76 | 1,834.12 | 49.16 | Bardzo niskie — zewnętrzny czynnik makro SOL | A |
| 3. First Pullback Absorption Surge | Po pierwszym cofnięciu ceny o >=12%, wolumen kupna na spadku przewyższa sprzedaż >= 1.35x (cena nadal <=3x od startu). | had_early_dip_at_T == 1 & dip_absorption_ratio_at_T >= 1.35 | 3m–15m | 26 | 0.5769 | 2.16 | 31.69 | 80.14 | 34.53 | Niskie — trudne do taniego sfabrykowania przy realnej podaży | A |
| 4. Asymmetric Buy-to-Sell Dollar Pressure | Stosunek wolumenu kupna do sprzedaży USD >= 2.2x przy min. 8 transakcjach kupna przed ucieczką ceny (>3x). | buy_sell_usd_ratio >= 2.2 & buy_tx_count >= 8 & mayhem_enabled == 0 | 1m–5m | 43 | 0.5349 | 2 | 4.55 | 158.89 | 29.23 | Niskie po odfiltrowaniu Mayhem AI | A |
| 5. Volume-to-MarketCap Ignition Ratio | Skumulowany obrót przekracza 35% bieżącej kapitalizacji przy braku sprzedaży twórcy i wyłączonym Mayhem. | vol_to_mcap_ratio_at_T >= 0.35 & creator_dumped_at_T == 0 & mayhem_enabled == 0 | 3m–10m | 37 | 0.5135 | 1.92 | 23.01 | 220.39 | 28.25 | Średnie — wymaga kontroli niezależnych portfeli | A |
| 6. Causal Smart Money Early Entry | Wejście min. 1 portfela z historyczną skutecznością >=45% (wyliczoną ściśle przed startem bieżącego tokena). | causal_smart_wallets_in >= 1 & creator_dumped_at_T == 0 | 1m–5m | 57 | 0.4912 | 1.84 | 4.32 | 152.32 | 19.35 | Niskie — oparte na wielokrotnej historii portfela | B |
| 7. Independent Buyer Velocity Surge | Napływ >= 2.5 niezależnych kupujących na minutę (po wykluczeniu bundlerów z bloku 0 i twórcy) bez zrzutu dewelopera. | independent_buyer_velocity >= 2.5 & creator_dumped_at_T == 0 | 1m–5m | 72 | 0.4444 | 1.66 | 2.74 | 396.63 | 29.62 | Niskie — odporne na bundlowanie w jednym bloku | A |
| 8. First-Mover Viral Narrative + Early Demand | Oryginalny pierwszy ticker narracji (is_ticker_first_mover=1) z linkami X/WWW i napływem >=1.5 niezależnych kupujących/min. | is_ticker_first_mover == 1 & has_social_links == 1 & independent_buyer_velocity >= 1.5 | 1m–5m | 91 | 0.4176 | 1.56 | 1.52 | 90.93 | 7.84 | Niskie — łączy przewagę narracyjną z popytem on-chain | A |
| 9. Low Manipulation Guardrail + Liquidity Lift | Wzrost płynności krzywej >= +12% przy niskim ryzyku manipulacji (<35 pkt) i wyłączonym Mayhem Mode. | liquidity_growth_pct_at_T >= 12 & realtime_manipulation_risk < 35 & mayhem_enabled == 0 | 3m–10m | 21 | 0.381 | 1.42 | 1.71 | 66.5 | 36.59 | Niskie — wbudowany filtr anty-manipulacyjny | B |
| 10. Healthy Supply De-Concentration | Stabilna lub malejąca koncentracja TOP 5 holderów (<= +0.5 pp) przy min. 5 niezależnych kupujących. | wallet_concentration_change <= 0.5 & independent_buyers_cum >= 5 | 5m–15m | 105 | 0.3048 | 1.14 | 1.06 | 98.29 | 3.34 | Niskie — mierzy realne rozproszenie tokenów | B |


---

## 4. Docelowa Architektura Systemu Wczesnego Wykrywania i Instrukcja Uruchomienia
Cały kod badawczy i produkcyjny znajduje się w katalogu `src/`, komplet 16 plików CSV oraz skoroszyt `PUMPFUN_ALPHA_RESEARCH.xlsx` w katalogu głównym, natomiast interaktywny 8-widokowy dashboard w `dashboard/index.html` (uruchamiany lokalnie komendą `python dashboard/serve_dashboard.py` lub bezpośrednio w przeglądarce).
