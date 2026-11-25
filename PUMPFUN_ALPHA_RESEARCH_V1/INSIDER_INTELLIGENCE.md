# INSIDER INTELLIGENCE & SUPPLY CONCENTRATION — ANALIZA KLASTRÓW, PODAŻY I ZYSKÓW

## 1. Metodyka Wykrywania Klastrów i Poziomy Pewności Dowodów (Moduł 9A)
Zbudowano wielowarstwowy graf powiązań (`networkx`) na zbiorze **493** tokenów, wykrywając łącznie **1154** nietrywialnych klastrów portfeli. Każde powiązanie posiada jawny typ, podstawę dowodową, poziom pewności oraz alternatywne wyjaśnienie:
- **`SAME_BLOCK_BUNDLE` (Pewność: HIGH):** Zakupy wielu portfeli w dokładnie tym samym bloku Solany (`blockId`) w pierwszych sekundach życia tokena (narzędzia Jito / bundlery deweloperskie).
- **`DIRECT_SOL_FUNDING_CREATOR` / `DIRECT_SOL_TRANSFER` (Pewność: HIGH):** Bezpośredni transfer natywnego `SOL` pomiędzy twórcą a wczesnym kupującym lub między kupującymi potwierdzony w `Solana RPC` (`getTransaction` v1).
- **`SHARED_PERSONAL_FUNDER` (Pewność: HIGH):** Wspólne zasilenie `SOL` z niskoczęstotliwościowego portfela prywatnego (`<95` transakcji lub długi horyzont czasowy).
- **`SHARED_CEX_HOTWALLET` (Pewność: LOW — NIE włączane automatycznie jako jeden operator!):** Wspólny adres zasilający o bardzo wysokiej częstotliwości (`>=100` tx w `<15` min), oznaczany jako gorący portfel giełdy/mostu, aby wyeliminować fałszywe oskarżenia o manipulację.
- **`CROSS_TOKEN_CO_SNIPE` (Pewność: MEDIUM):** Powtarzalne wspólne wejścia w pierwszych 15 kupujących na $\ge 3$ niezależnych tokenach.

---

## 2. Ewolucja Koncentracji Podaży w 7 Punktach Życia Tokena (Moduł 9B)
Porównanie mediany koncentracji podaży (po wykluczeniu pul płynności, bonding curve i programów technicznych) pomiędzy tokenami `hit_5x = 1` a pozostałymi (`hit_5x = 0`):

| checkpoint | hit_5x | top1_pct | top5_pct | top10_pct | clusters_pct | insiders_pct |
| --- | --- | --- | --- | --- | --- | --- |
| 1_launch | 0 | 0.347 | 0.4025 | 0.4025 | 0 | 0.1058 |
| 1_launch | 1 | 6.822 | 11.454 | 11.454 | 5.904 | 11.217 |
| 2_pre_pump_early | 0 | 0.6997 | 0.9342 | 0.9342 | 0.0001 | 0.2875 |
| 2_pre_pump_early | 1 | 6.865 | 20.696 | 27.154 | 19.403 | 24.913 |
| 3_pump_onset | 0 | 1 | 1.271 | 1.271 | 0.0008 | 0.3521 |
| 3_pump_onset | 1 | 6.422 | 19.05 | 30.09 | 19.229 | 26.029 |
| 4_peak_volume | 0 | 0.9955 | 1.497 | 1.497 | 0.0001 | 0.02 |
| 4_peak_volume | 1 | 5.584 | 17.856 | 27.391 | 16.737 | 23.857 |
| 5_ath | 0 | 0.6325 | 1.116 | 1.129 | 0 | 0.0052 |
| 5_ath | 1 | 5.91 | 17.773 | 27.436 | 20.705 | 24.924 |
| 6_post_ath | 0 | 0.316 | 0.4981 | 0.5141 | 0 | 0 |
| 6_post_ath | 1 | 5.71 | 17.441 | 27.597 | 20.121 | 23.174 |
| 7_latest | 0 | 0.0076 | 0.0107 | 0.0127 | 0 | 0 |
| 7_latest | 1 | 5.47 | 17.126 | 26.981 | 20.121 | 21.774 |


---

## 3. Ranking Klastrów wg Zgromadzonej Podaży (Moduł 9A/9B)
| cluster_id | mint | symbol | cohort_role | wallets_count | includes_creator | wallet_sample | dominant_link_type | evidence_basis | confidence_level | alternative_explanation | accumulated_supply_pct | retained_supply_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CQe1HJ_CL1 | CQe1HJMu5kfcnURwmS66vwPH9bxTJBmbn7KswFeZpump | $CAT | group_a_pump_candidate | 5 | 0 | 3ePN9tuUEjCJcfc9H8nGUeXypaaSpQiWUqjjv6ptLXYL;AcrnaLjnuCMgwzFyr2GmKyBdgFAtygc8nnumhSp14287;BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s;BwWK17z43AmDukau6m4NjjmhxcpyRnQHbToGfjmvamiB;DGq2Meb8mrEGWjJR7LtPigA2w8HM14bWaFqeePpqXBTw | CROSS_TOKEN_CO_SNIPE | Co-entered first 15 buyers in 3 tokens | MEDIUM | Competing sniper bots subscribing to identical launch triggers | 296.557 | 0 |
| B4KU4e_CL1 | B4KU4eMjKvasZ5zMiuYeUdn3kHa6emKfXD2J5Xg9WvRJ | Scam | group_a_pump_candidate | 18 | 1 | 2mrZotmYv1n9U8p7ZuX4VMaqXQnLDGSa5RitqKbNoR4C;48hFzzVyfe9EvdbWAfSR2wq2yiqNtmaCFjEEpXJzKsrJ;558fG1D9sAadkrC5Kf1FBK3NhMETLJKgz18vYFfp8UAq;5XrFPhrRfdjdhb2SBeRGvPUfjNymFuxGSnK7QJY7MCzX;5pXiu1Nhm2zoMWFbUP19WjEprPAz2XgqKEYUDUnGgGAy | SAME_BLOCK_BUNDLE | Co-bought in launch block 473303453 | HIGH | Coincidental public mempool sniper collision in same slot | 284.841 | 39.764 |
| GNd4M5_CL1 | GNd4M54bCt7JVWzDvui3Z9PVXVjmdHtZMqHHUBqhpump | MONY | group_a_pump_candidate | 6 | 0 | 7siN3qkQNXbzxu8qVp7NgPctdt3niPRcx14tNXg67SNk;81o99UWtur4TABbFb1KvcG9d5HAzptCA9Fzy9GmyuuPA;8QxwGHPmM431fJZzaSo1uu8m1iAvipEVJnH2nrJKt28D;B48ZR3Vs3ynsCR1beUaRizbLs2Fc3wXKqPXL57DaFxGv;BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s | CROSS_TOKEN_CO_SNIPE | Co-entered first 15 buyers in 3 tokens | HIGH | Competing sniper bots subscribing to identical launch triggers | 240.408 | 0 |
| 3ZDsB9_CL1 | 3ZDsB93P55McVhS6LGDUxqFXN5MuN1cmgmnJ4SZVpump | PS5 | group_a_pump_candidate | 4 | 0 | BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s;BwWK17z43AmDukau6m4NjjmhxcpyRnQHbToGfjmvamiB;Fzs4fLTNL8HkSZr1a3wMCCyFvKn3AE1M5Mru3a9ZS2vz;GGMASpvH3yiBPNooLd5LTnt7YFRTBpQKV3aggyxKKAjy | CROSS_TOKEN_CO_SNIPE | Co-entered first 15 buyers in 3 tokens | HIGH | Competing sniper bots subscribing to identical launch triggers | 173.718 | 40.073 |
| 87CQto_CL1 | 87CQtouHSb6YCXaPZ1pp8jD56VudRMXBVqU3oDMD1UJT | José | group_a_pump_candidate | 90 | 0 | 22BUeLdecT6B74At7BvRpHVVp4dgbyKEaatqiktsRnFW;2K6u7iJYz63uMwftr1MrWLKdPcspRongyAZoAWvCFaEB;2NUMEzNh4mFjZpzMwBqyyzoQLimbPZvpo3ksrJLM2rk3;2YDnmMQt7x7Y3VFounzsnZ3s8TdozqWyK9qeQPWY9saH;2maW7x2X4shMK3bNc3bGNvRpweindJXzujgdszgp3Zfb | SAME_BLOCK_BUNDLE | Co-bought in launch block 466271503 | HIGH | Coincidental public mempool sniper collision in same slot | 135.964 | 59.765 |
| uf5RNa_CL1 | uf5RNaK5gPLsEELF5oyath41CMNhehG3rNsrhSXpump | KJU | control_matched | 6 | 1 | 4A6Sy1x4RMiF7ZTERsbSV5j47c8WCjybNd1ziW2e2Yxn;CGhAbmcVrgvM1LrFrppJq2q5aaNbB6XjGWFdJdAZeeKK;FZU56d9iPqohXM5XBrYYBZLi2UoUnZT4V5Qf2631tEzb;GUhn9ivU5kMVJiUfUqDgwejKDVc8TuwZNZHgiZitowgm;SADWY55TzkbdnMAtQdcZWFtmCsjLrrLdZ5Sd7mkoPDd | CROSS_TOKEN_CO_SNIPE | Co-entered first 15 buyers in 6 tokens | HIGH | Competing sniper bots subscribing to identical launch triggers | 116.575 | 0 |
| jM9r9P_CL1 | jM9r9PJFyPaMEbhGZPbDeZJiysn2pfyz5TzdDs5pump | uni | group_a_pump_candidate | 48 | 1 | 25ZcRco9VbttzHwwuZ13198zkXmBshtRYmaQzba1Efgv;27HFmP7ccLadGswvQfvea4o3juLw75cPF4V6jWpHM3MX;2LZUYDR2g7rw1CpcWzo1JkfTLGYfwnkh7AJfurPiNBK5;2fdyyJhLt432jq1tf5iujotmrusBvMmyxWXq2i78Nvp9;2zHS7D9FHkbPdUUAq8aHLsfM4Wf2EETm6DPXggEkKgDL | SAME_BLOCK_BUNDLE | Co-bought in launch block 464233514 | HIGH | Coincidental public mempool sniper collision in same slot | 99.333 | 99.327 |
| 31yAGD_CL1 | 31yAGDtRaed952CoX3dDfhUu8ZtaKTn29pAL4ZsKpump | USOE | group_a_pump_candidate | 2 | 1 | 74jaa1piGoevziQHULbCuxAXkdAQRqbrNm7bUTFPtnwB;DK2KhGWkB8tztJExR7J9KW68PWyADJvQZwxET4Camy35 | SAME_BLOCK_BUNDLE | Co-bought in launch block 463511924 | HIGH | Coincidental public mempool sniper collision in same slot | 96.463 | 96.463 |
| BBRgG2_CL1 | BBRgG2GifeKNB1hSmzD2BwHMPK8wnDtcuE4NzxgHpump | BORLY | group_a_pump_candidate | 2 | 1 | 96V9uyAtn2QXPysT51Nv6hyHBsGmVYb26BKHM3mYxB8w;FAYJ5mY9H2VDeAoorRtxcmsje8EnAFEvsmwTkfdQ64sb | SAME_BLOCK_BUNDLE | Co-bought in launch block 467648481 | HIGH | Coincidental public mempool sniper collision in same slot | 96.13 | 96.13 |
| DD23R2_CL1 | DD23R2DJFKxUCB2CUvogviVhHA7D9RTsjbrFKWBzpump | ANSEM | group_a_pump_candidate | 22 | 1 | 27HFmP7ccLadGswvQfvea4o3juLw75cPF4V6jWpHM3MX;2CNKXijHQgEYYaR1eVKKSB6wLEbFNBzycoKeMja2ESeb;3bx6pJVD6TC8ijF66F6UHSyCx1kCHqgacS1T6iKHcwKk;4BHBSZA96XCaepYLvmteV6wLqKTqJPyfkME941X5PqHP;7NNzakXLFv2VfhUuoZ9i4Uy4f63BDJcR96tMCucXa6KL | SAME_BLOCK_BUNDLE | Co-bought in launch block 473290256 | HIGH | Coincidental public mempool sniper collision in same slot | 95.195 | 91.718 |
| ASjGJc_CL1 | ASjGJc3p3v5eVcc5LQE81QPkMpkSTpqm88PPgu8Xpump | MRSAVAGE | group_a_pump_candidate | 30 | 1 | 27HFmP7ccLadGswvQfvea4o3juLw75cPF4V6jWpHM3MX;2NLCLiXg6KTw12ADBobL8CQiYJsowAT5VQx6dQWcYnzr;2r9BDXjeqjzb3TTZZsbrZMYohps7C9AeWErSYJjEW8ZU;3KcPSJ8ouE7H1feoWHmhDwXhLnXhpxP6R6713uytFmBM;4fBSfzrCUDn4qKpA8TfbKwYHvJTmBWgrDDYuNuaYNfJX | SAME_BLOCK_BUNDLE | Co-bought in launch block 468224397 | HIGH | Coincidental public mempool sniper collision in same slot | 94.618 | 90.918 |
| EVbsBw_CL1 | EVbsBwxqdbMqadwAsVZ6KP9SJiaNmLSHAAb4W2mUpump | LUNO | group_a_pump_candidate | 48 | 1 | 27HFmP7ccLadGswvQfvea4o3juLw75cPF4V6jWpHM3MX;2GLSFr8EKA582tz5w79hjwnTLm4cS7cE4gUBXJ76RAdz;2UdWqZsuacmRUheA1grSuqVWXAAejbCYkvEjFBKfodKM;2z2q5gk8TDgqCidzkXkyevXH1aDaVjWL8cQwoRbMF1Jq;3uDjngcHPXNWmcjBNVecu2JJ3gubmnkpu1f6Q8ze1uzB | SAME_BLOCK_BUNDLE | Co-bought in launch block 470673059 | HIGH | Coincidental public mempool sniper collision in same slot | 92.917 | 91.977 |
| B8JPmr_CL1 | B8JPmruxFZkzxpWU1NFXwc2Zg1M9QWUo3cjtskP7pump | ANSEM | group_a_pump_candidate | 5 | 0 | 3ePN9tuUEjCJcfc9H8nGUeXypaaSpQiWUqjjv6ptLXYL;48hFzzVyfe9EvdbWAfSR2wq2yiqNtmaCFjEEpXJzKsrJ;AcrnaLjnuCMgwzFyr2GmKyBdgFAtygc8nnumhSp14287;BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s;DGq2Meb8mrEGWjJR7LtPigA2w8HM14bWaFqeePpqXBTw | CROSS_TOKEN_CO_SNIPE | Co-bought in launch block 473310424 | HIGH | Coincidental public mempool sniper collision in same slot | 91.325 | 0.642 |
| PgFtGG_CL1 | PgFtGGquvnv2zEkjG2N2QPvBTBrafuExGYEqahRpump | BRUH | group_a_pump_candidate | 22 | 1 | 2Zh7ZErXwovgVW47U8EgWABxUBC8dXLMnphLiY3GiTMf;2fV87vkwcKMrxsM7Zt3bdrS2uUkVypZBrZBFPhQXN23o;4Lagj4F4ncGWsfdFC1jowqBkLr17NzpNdfmZR9dY5N3n;5AArLAz5NoYHs3iXLZYwHAtuJKXpxFQiTh3Mxdx8gHpc;5Tck6drzbYKNvMf96QyV1UiUXkEyTn3q9L6Dzd8U5M3F | SAME_BLOCK_BUNDLE | Co-bought in launch block 466378580 | HIGH | Coincidental public mempool sniper collision in same slot | 89.097 | 87.54 |
| 8s11Pk_CL1 | 8s11PkgQt4ZzdZ7oo84hK5t9HG1EvdgAjcg4W7Lpump | BLOB | group_a_pump_candidate | 23 | 1 | 2KDGQysmq1Zbav65AkN79DTgUt4DRDjXs33HhdCwU8rr;2aqMYJwbTUJoC9GXGnxpAeFh315aLdnw5F66JL95rZYe;2rahsvafAagvZprfgJTWktTW535Wax4dzvBBs27xuPdR;4CgcTebVPXvN4T7uv9AeoXSoMhn5mAwzvYiaQHAB3Xpp;4Vu3UTHU7NEDQxodLzvHnda4cdh58tUJGLgFyUruxoxZ | SAME_BLOCK_BUNDLE | Co-bought in launch block 463741159 | HIGH | Coincidental public mempool sniper collision in same slot | 89.074 | 83.918 |


---

## 4. Rekonstrukcja Ekonomiczna i Zyski Klastrów Insiderów (Moduł 9C)
Ściśle rozdzielono **zysk zrealizowany w SOL/USD** (faktycznie wypłacony z rynku po odjęciu kosztów zakupu i szacowanych opłat transakcyjnych) od **niezrealizowanej wyceny rynkowej pozostałych tokenów** (`unrealized_mtm_usd_not_realized`), której nie można utożsamiać z gotówkowym zyskiem z uwagi na ograniczoną płynność puli:

| cluster_id | symbol | wallets_count | confidence_level | sol_spent_buys | sol_received_sells | realized_profit_sol | realized_profit_usd | retained_supply_pct | unrealized_mtm_usd_not_realized | retention_pattern |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 9Pq7aL_CL1 | JOB | 23 | HIGH | 112.775 | 256.95 | 140.405 | 14,203.34 | 48.054 | 835,168.86 | PARTIAL_TAKE_PROFIT_HIGH_RETENTION |
| GexThZ_CL1 | WASTED | 22 | HIGH | 21.559 | 63.449 | 41.017 | 3,867.05 | 22.377 | 246,514.44 | PARTIAL_TAKE_PROFIT_HIGH_RETENTION |
| 31HzUs_CL1 | TrumpWars | 4 | HIGH | 36.956 | 71.858 | 33.806 | 3,211.94 | 16.904 | 16,928.36 | PARTIAL_TAKE_PROFIT_HIGH_RETENTION |
| UQLWvk_CL1 | ZOL | 5 | HIGH | 23.096 | 46.216 | 22.421 | 1,634.47 | 0.0092 | 3.55 | FULL_DISTRIBUTION_EXIT |
| HuN5y4_CL1 | Singularity | 4 | HIGH | 32.245 | 54.029 | 20.917 | 1,444.93 | 3.186 | 1,477.14 | FULL_DISTRIBUTION_EXIT |
| Df6yfr_CL1 | CHILLGUY | 6 | MEDIUM | 23.135 | 41.284 | 17.435 | 1,815.20 | 0 | 0 | FULL_DISTRIBUTION_EXIT |
| FTu55M_CL1 | FOOD | 3 | HIGH | 10.593 | 25.378 | 14.422 | 1,173.82 | 0 | 0 | FULL_DISTRIBUTION_EXIT |
| CVuTQK_CL2 | SORRUN | 7 | HIGH | 1.518 | 13.666 | 11.989 | 1,150.60 | 0 | 0 | FULL_DISTRIBUTION_EXIT |
| 2HcvsX_CL1 | INVISIBLE | 7 | HIGH | 14.399 | 26.625 | 11.802 | 1,195.58 | 0 | 0 | FULL_DISTRIBUTION_EXIT |
| DEgAkP_CL3 | BUCKME | 3 | HIGH | 0.2444 | 10.319 | 9.966 | 739.84 | 0 | 0 | FULL_DISTRIBUTION_EXIT |
| v4GK8f_CL1 | MCAT | 3 | HIGH | 8.889 | 19.016 | 9.843 | 691.3 | 8.613 | 281.19 | PARTIAL_TAKE_PROFIT_HIGH_RETENTION |
| HuN5y4_CL3 | Singularity | 26 | HIGH | 40.247 | 49.845 | 8.659 | 598.13 | 2.346 | 1,087.58 | FULL_DISTRIBUTION_EXIT |
| 7fmD1p_CL1 | DUVAL | 8 | HIGH | 12.222 | 20.684 | 8.124 | 572.53 | 12.137 | 14,518.53 | PARTIAL_TAKE_PROFIT_HIGH_RETENTION |
| 2GWQkx_CL1 | tiecat | 6 | HIGH | 18.019 | 25.795 | 7.321 | 523.76 | 2.509 | 48.91 | FULL_DISTRIBUTION_EXIT |
| uHMWNF_CL1 | PAYDAY | 2 | HIGH | 13.915 | 21.506 | 7.235 | 626.26 | 4.302 | 2,834.10 | FULL_DISTRIBUTION_EXIT |


---

## 5. Wzorzec Insider Retention oraz Studium Przypadku `$COOL` (Moduł 9D)
### Analiza tokenów o tickerze `$COOL` obecnych w zbiorze pump.fun:
| symbol | name | mint | cohort_role | reliable_market_multiple | max_mcap_usd | liquidity_usd | detected_clusters_count | potential_insiders_peak_pct | potential_insiders_retained_pct | insider_supply_risk_score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cool | cooldog | DpD2hjvEHUHJWN1dtbueDuSkMBG5Vf6awWMvvbrDpump | group_b_legacy_candidate | 1.474 | 10,694.98 | 6,246.60 | 0 | 0 | 0 | 2.1 |


### Klastry utrzymujące najwyższy odsetek podaży po wzroście (`Insider Retention Pattern`):
| cluster_id | symbol | wallets_count | retained_supply_pct | realized_profit_sol | unrealized_mtm_usd_not_realized | est_liquidity_price_impact_if_dumped_pct | retention_pattern |
| --- | --- | --- | --- | --- | --- | --- | --- |
| jM9r9P_CL1 | uni | 48 | 99.327 | -2,623.00 | 5,182,679.66 | 99.98 | STRONG_HOLD_ACCUMULATION |
| 31yAGD_CL1 | USOE | 2 | 96.463 | -485.066 | 115,415.08 | 99.15 | STRONG_HOLD_ACCUMULATION |
| BBRgG2_CL1 | BORLY | 2 | 96.13 | -446.427 | 479,487.36 | 99.77 | STRONG_HOLD_ACCUMULATION |
| EVbsBw_CL1 | LUNO | 48 | 91.977 | -235.677 | 307,292.20 | 99.58 | STRONG_HOLD_ACCUMULATION |
| DD23R2_CL1 | ANSEM | 22 | 91.718 | -180.459 | 194,561.69 | 99.4 | STRONG_HOLD_ACCUMULATION |
| ASjGJc_CL1 | MRSAVAGE | 30 | 90.918 | -158.733 | 35,222.92 | 97.71 | STRONG_HOLD_ACCUMULATION |
| E5c1Jv_CL1 | TTP | 2 | 88.6 | -145.997 | 536,760.29 | 99.94 | STRONG_HOLD_ACCUMULATION |
| PgFtGG_CL1 | BRUH | 22 | 87.54 | -127.902 | 4,906,456.88 | 99.97 | STRONG_HOLD_ACCUMULATION |
| 8s11Pk_CL1 | BLOB | 23 | 83.918 | -72.455 | 2,949,859.49 | 99.92 | STRONG_HOLD_ACCUMULATION |
| npz2Fh_CL1 | DESSA | 12 | 83.525 | -93.141 | 676,719.18 | 99.65 | STRONG_HOLD_ACCUMULATION |
| BLrKuq_CL1 | RaRa | 2 | 81.928 | -55.795 | 22,322.95 | 95.51 | STRONG_HOLD_ACCUMULATION |
| 6a81Pf_CL1 | DAVID | 2 | 79.768 | -76.516 | 31,052.08 | 96.2 | STRONG_HOLD_ACCUMULATION |
| EA2yKY_CL1 | SIMBIRD | 3 | 79.508 | -27.486 | 255.01 | 7.99 | STRONG_HOLD_ACCUMULATION |
| 5wSQpQ_CL1 | SOUVENIR | 2 | 79.299 | -93.296 | 151,581.44 | 98.95 | STRONG_HOLD_ACCUMULATION |
| ejrz94_CL1 | ANTS | 17 | 79.053 | -19.025 | 1,496,671.85 | 99.85 | PARTIAL_TAKE_PROFIT_HIGH_RETENTION |


**Wnioski dot. Insider Retention (H14–H17):**
1. **Koncentracja podaży w największych pumpach vs przegranych:** Zwycięskie tokeny (`5x+`) wykazują **istotnie wyższą liczbę wykrytych klastrów oraz wyższą szczytową akumulację TOP 10 w fazie wzrostu** niż martwe tokeny kontrolne (testy H14 i H16 — dowód **A**). Wynika to z faktu, że w tokenach martwych nikt nie akumuluje dużych pakietów, natomiast silne wybicia często posiadają skoordynowaną grupę wczesnych akumulatorów lub aktywnych wielorybów „zamykających podaż” (*supply lock*).
2. **Dwie strony medalu (Potencjał vs Ryzyko):** Chociaż początkowa akumulacja pomaga wypchnąć cenę po stromym odcinku bonding curve, wysokie bundlowanie w bloku startowym zwiększa ryzyko gwałtownego załamania $>85\%$ (H17 — dowód **B**), a zatrzymanie znacznego pakietu przy płytkiej puli AMM generuje ogromny nawis podażowy.

---

## 6. Scenariusze Presji Sprzedażowej (1%, 5%, 10%, 25% Podaży) i Insider Risk Score (Moduł 9E–9F)
Orientacyjny wpływ zrzutu pakietu na cenę obliczono z głębokości puli stałego iloczynu AMM:

| symbol | mint | insider_supply_risk_score | manipulation_risk_score | potential_insiders_peak_pct | potential_insiders_retained_pct | liquidity_usd | sell_impact_1pct_supply_pct | sell_impact_5pct_supply_pct | sell_impact_10pct_supply_pct | sell_impact_25pct_supply_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FIONA | B34nXKzCgsJb9ChLuSHPRpXLE3WFSWyeT8Cqkzzmpump | 100 | 58.15 | 31.836 | 11.186 | 192,336.30 | 43.68 | 85.89 | 94.65 | 98.85 |
| JOB | 9Pq7aLAbhDG2tTnS22cm6kuysZVcZpLFE368HWuypump | 100 | 63 | 79.883 | 48.477 | 141,899.89 | 36.15 | 80.38 | 91.9 | 98.12 |
| BRUH | PgFtGGquvnv2zEkjG2N2QPvBTBrafuExGYEqahRpump | 100 | 63 | 89.18 | 88.237 | 181,983.78 | 62 | 94.08 | 98.08 | 99.64 |
| BLOB | 8s11PkgQt4ZzdZ7oo84hK5t9HG1EvdgAjcg4W7Lpump | 100 | 57 | 86.53 | 84.805 | 170,304.27 | 50.16 | 89.47 | 96.25 | 99.23 |
| ANTS | ejrz94zR4A2ScS8LdvRaQih2xUxaE2ydreqUNKmpump | 100 | 63 | 87.95 | 81.035 | 121,907.04 | 42.15 | 84.91 | 94.19 | 98.73 |
| JIMMY | 38M2z4UCfZEkUHFzD48vhKQhFhNyRGto8pZbLjNipump | 98.95 | 63 | 30.456 | 22.005 | 95,831.49 | 31.31 | 75.8 | 89.36 | 97.37 |
| DESSA | npz2FhoufQ7pKqhGpaipYWacrAkidyW2yDpVWSvpump | 98.53 | 63 | 86.132 | 85.257 | 85,741.64 | 29.74 | 74.1 | 88.35 | 97.05 |
| DUVAL | 7fmD1p3jzva28EPP9bPqbDoxZGj5j398yJoE3EVypump | 93.16 | 63 | 62.182 | 54.582 | 27,866.68 | 15.93 | 52.65 | 72.48 | 90.62 |
| Impeach | F2xQeTCTqnczXxXQaBWAfDpUnpxn4wQHRPSqvUYJpump | 91.92 | 45.74 | 25.626 | 38.026 | 30,982.14 | 14.83 | 50.25 | 70.32 | 89.52 |
| greg | 4Ye6Y6Vaic8cyPdfW2f9PcLhXkysBtSmV84G8X7spump | 90.92 | 70 | 52.063 | 48.207 | 21,853.58 | 12.08 | 43.67 | 63.92 | 85.89 |
| AMD | DDmGnuvroxVrb7CSyjYcezFU8gnAfhKasg4ZZezmpump | 90.42 | 63 | 37.313 | 21.543 | 38,971.20 | 11.32 | 41.69 | 61.85 | 84.59 |
| bro | 8wbxHYCKbGimALpDvNkxcvzGm1tAG4GN69Jzfejtpump | 90.41 | 70 | 51.291 | 50.366 | 18,949.85 | 11.3 | 41.64 | 61.81 | 84.56 |
| uni | jM9r9PJFyPaMEbhGZPbDeZJiysn2pfyz5TzdDs5pump | 90 | 57 | 99.419 | 99.419 | 161,093.91 | 63.17 | 94.44 | 98.21 | 99.66 |
| TTP | E5c1JvHbwEf3ud2m4PXPMugcMDevLrnskq7sj1FTpump | 90 | 57 | 89.217 | 89.217 | 27,822.95 | 51.74 | 90.22 | 96.56 | 99.3 |
| CONSOLE | 91fBfFGRG5Ry6ty4A1Q23hv1eEawsTu7rh2mvczRpump | 90 | 63 | 18.358 | 0.0113 | 134,896.27 | 58.25 | 92.84 | 97.62 | 99.54 |
