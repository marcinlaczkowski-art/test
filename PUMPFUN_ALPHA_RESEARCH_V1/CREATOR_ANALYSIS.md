# CREATOR ANALYSIS — ANALIZA TWÓRCÓW TOKENÓW I ICH HISTORII

## 1. Archetypy Przebadanych Twórców ($N = 689$ portfeli deweloperskich)
Dzięki endpointowi `coins-v2/user-created-coins/{creator}` odtworzono pełne portfolio historyczne twórców z naszej kohorty:

| Archetyp twórcy (Sekcja 10) | Liczba portfeli twórców | Udział (%) |
| --- | --- | --- |
| SINGLE_LAUNCH_WINNER | 368 | 53.41 |
| REPEAT_SUCCESSFUL_OPERATOR | 130 | 18.87 |
| ONE_OFF_OR_SMALL_CREATOR | 74 | 10.74 |
| ONE_HIT_WONDER_MULTI_TRY | 65 | 9.43 |
| SPAM_SERIAL_DEPLOYER | 40 | 5.81 |
| SERIAL_EXTRACTOR_RUGGER | 12 | 1.74 |


---

## 2. Top 20 Twórców wg Powtarzalnych Wyników (`pumps_over_25k_mcap` i `max_historical_ath_usd`)
| creator_wallet | total_tokens_created | sampled_tokens_analyzed | migrated_tokens_count | migration_rate_pct | pumps_over_25k_mcap | max_historical_ath_usd | median_ath_usd | preferred_launch_hour_utc | duplicate_ticker_reuse_rate | linked_cluster_observed | creator_early_dump_observed | creator_archetype |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EjcwXG6ywzorxLcX7565C614LdhxiHF6uJhkYyRTDVgZ | 17446 | 50 | 3 | 0.02 | 46 | 227,533.64 | 76,444.20 | 15 | 0.4 | 1 | 1 | REPEAT_SUCCESSFUL_OPERATOR |
| yHCxHBEaJW5tbndqC8JciSThr7U1cqLpdcsvHcx6PRe | 914 | 50 | 29 | 3.17 | 45 | 449,957,637.61 | 724,834.83 | - | 0 | 1 | 0 | REPEAT_SUCCESSFUL_OPERATOR |
| 5YRgrP3mjGzrzirYYN5HAQH19cTYREYwGxW6XRJQUzij | 105 | 50 | 31 | 29.52 | 42 | 24,702,219.27 | 84,288.82 | - | 0 | 1 | 0 | REPEAT_SUCCESSFUL_OPERATOR |
| 6mWEJG9LoRdto8TwTdZxmnJpkXpTsEerizcGiCNZvzXd | 286 | 50 | 6 | 2.1 | 27 | 6,043,380.72 | 26,726.66 | - | 0 | 0 | 0 | REPEAT_SUCCESSFUL_OPERATOR |
| 2Bonf26MDnpJPwJkocnQLfHWjdeStLD5iCtV3yC7Q6z4 | 1648 | 50 | 4 | 0.24 | 26 | 4,911,069.18 | 25,247.92 | - | 0 | 1 | 1 | REPEAT_SUCCESSFUL_OPERATOR |
| 6c1Dmi9L4rTXT5GcTbTv8p3BuBEn8SJbo37UGJ3f6yfj | 4773 | 50 | 0 | 0 | 25 | 194,250.02 | 25,128.61 | 7 | 0.34 | 1 | 1 | SPAM_SERIAL_DEPLOYER |
| DYmsQudNqJyyDvq86XmzAvrU9T7xwfQEwh6gPQw9TPNF | 2233 | 50 | 2 | 0.09 | 24 | 7,975,424.79 | 23,718.32 | 0 | 0.06 | 1 | 1 | REPEAT_SUCCESSFUL_OPERATOR |
| JDd3hy3gQn2V982mi1zqhNqUw1GfV2UL6g76STojCJPN | 2875 | 50 | 3 | 0.1 | 24 | 168,460.09 | 24,197.70 | 5 | 0.18 | 1 | 1 | REPEAT_SUCCESSFUL_OPERATOR |
| 29yFzeBZgxf5zqrAkKXwgZtQehRf4pL8WbV2nRJikbw8 | 16617 | 50 | 10 | 0.06 | 23 | 9,739,601,293.72 | 22,946.77 | 19 | 0.04 | 0 | 0 | REPEAT_SUCCESSFUL_OPERATOR |
| KEN7s6mHAFpqmvppk7L9VaJW3htu3jz6z3dDjiaWdYT | 23 | 23 | 23 | 100 | 23 | 606,005,809.20 | 451,476.13 | - | 0 | 1 | 0 | REPEAT_SUCCESSFUL_OPERATOR |
| Btxty83QiNskbHX5XPMWk9o54SYj9uNpKEKkbCu6gL3q | 22 | 22 | 22 | 100 | 22 | 666,218,655.99 | 201,619.43 | - | 0 | 1 | 0 | REPEAT_SUCCESSFUL_OPERATOR |
| CzbN6T1gKkKutvuPXcxNmV8FLqzjsDWebWmg9o8e2ZbU | 5452 | 50 | 1 | 0.02 | 22 | 5,961,065.80 | 19,826.32 | - | 0 | 0 | 0 | ONE_OFF_OR_SMALL_CREATOR |
| timeworn2X1EwMLSzeVhdVTbVSzSCKuibKd2kQ2Lsyn | 8637 | 50 | 5 | 0.06 | 19 | 248,649.92 | 18,354.90 | - | 0 | 1 | 1 | REPEAT_SUCCESSFUL_OPERATOR |
| CKEfb2i4Z8Mb5qqt5J4LpgSqXPnbgmv4zP6Y2yHQWuUR | 36 | 36 | 15 | 41.67 | 18 | 2,423,062,532.54 | 28,345.47 | 19 | 0.75 | 1 | 0 | REPEAT_SUCCESSFUL_OPERATOR |
| CxgPWvH2GoEDENELne2XKAR2z2Fr4shG2uaeyqZceGve | 164 | 50 | 10 | 6.1 | 18 | 260,281,800.63 | 13,637.46 | - | 0 | 1 | 0 | REPEAT_SUCCESSFUL_OPERATOR |
| HyYNVYmnFmi87NsQqWzLJhUTPBKQUfgfhdbBa554nMFF | 495 | 50 | 17 | 3.43 | 17 | 2,480,789,284.65 | 0 | - | 0 | 0 | 0 | REPEAT_SUCCESSFUL_OPERATOR |
| HrCPnDvDgbpbFxKxer6Pw3qEcfAQQNNjb6aJNFWgTEng | 31 | 31 | 16 | 51.61 | 16 | 396,551,084.99 | 33,504.01 | - | 0 | 1 | 0 | REPEAT_SUCCESSFUL_OPERATOR |
| 4EPNLZHUnEbpxZm6qTPkXpMG2EDektbjUA1yAugHJLc4 | 26 | 26 | 13 | 50 | 16 | 16,398,460.72 | 77,194.34 | - | 0 | 0 | 0 | REPEAT_SUCCESSFUL_OPERATOR |
| 3z4vj1nAujLnciPgZaGz4VYecZa6gbYUg3Yr9MoyuiMG | 6445 | 50 | 13 | 0.2 | 15 | 1,474,303.21 | 9,759.40 | - | 0 | 1 | 1 | REPEAT_SUCCESSFUL_OPERATOR |
| 69aiAKU3uJMxMLRkUEGFNt6nQ43PiVimE4ZbErJ7VSM1 | 3496 | 50 | 5 | 0.14 | 14 | 20,436,332.46 | 11,189.03 | - | 0 | 1 | 1 | REPEAT_SUCCESSFUL_OPERATOR |


---

## 3. Kluczowe Odkrycia dot. Twórców (Weryfikacja Hipotez H18–H20)
1. **Seryjni spamerzy (`>10` utworzonych tokenów) to fabryki porażek (H20 — Dowód A):** Twórcy masowo uruchamiający dziesiątki tokenów osiągają drastycznie niższe mnożniki niż twórcy selektywni (`1–3` projekty), często stosując ten sam szablon nazw i natychmiastowo wyciągając drobne kwoty SOL.
2. **Zachowanie twórcy w pierwszych 5 minutach jest ważniejsze niż jego dawne CV (H18 vs H19):** Sam historyczny odsetek sukcesów twórcy (`creator_prior_win_rate`, H19) ma ograniczoną wartość predykcyjną, ponieważ udani operatorzy często rotują świeże portfele deweloperskie, natomiast **brak zrzutu tokenów przez twórcę w pierwszych 5 minutach (`creator_dumped_at_T = 0`, H18)** jest jednym z najmocniejszych filtrów ochronnych przed natychmiastowym rug-pullem!
