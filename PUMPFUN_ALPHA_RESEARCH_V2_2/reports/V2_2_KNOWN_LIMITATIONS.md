# V2_2_KNOWN_LIMITATIONS — JAWNY REJESTR OGRANICZEŃ I BLOKAD V2.2

## 1. Brak potwierdzonej przewagi ekonomicznej (`EDGE_STATUS = NOT_ESTABLISHED`)
Najważniejsze ograniczenie badawcze: na obecnym etapie **nie udowodniono powtarzalnej dodatniej wartości oczekiwanej netto po kosztach** w niezależnym teście wielkoskalowym (`STATUS_C_ECONOMICALLY_VALIDATED = False`).

## 2. Czas trwania Paper Tradingu (`PAPER_TRADING_STATUS = IN_PROGRESS`)
Wymóg minimum **30 kolejnych dni** działania w czasie rzeczywistym rozpoczął się w dniu uruchomienia V2.2 (`2026-11-25`, zebrano dotychczas `0.0002` dnia). Nie wolno skracać tego wymogu przez odtwarzanie danych historycznych.

## 3. Wielkość próby OOT (`OOT_STATUS = INSUFFICIENT_SAMPLE`)
W chronologicznym zbiorze OOT zebrano dotychczas `270` kompletnych obserwacji `4h` i `5` pozytywnych przypadków `hit_2x_4h` wobec wymaganego minimum `1 000` tokenów i `30` przypadków pozytywnych (przy niskiej bazowej częstości pumpów `~1%–2%` w niefiltrowanym strumieniu potrzebne jest ok. `1 500–3 000` kolejnych emisji chronologicznych). Ponadto horyzont `24h` dla najświeższych emisji OOT jest prawostronnie ocenzurowany (`CENSORED`).

## 4. Rekonstrukcja rezerw po migracji na zewnętrzny AMM (`RESERVE_RECONSTRUCTION_INCOMPLETE`)
Publiczne API taśmy swapów nie dostarcza pełnych instrukcji dodawania/usuwania płynności LP na zewnętrznych pulach Raydium/PumpSwap. W V2.2 wszystkie takie przypadki (`41 / 650` w kohorcie bazowej) są oznaczane jako `RESERVE_RECONSTRUCTION_INCOMPLETE` i wyłączane z dokładnego backtestu. Pełna rekonstrukcja rezerw po migracji wymaga dedykowanego archiwalnego indeksatora kont Solany (np. płatny węzeł Geyser / Helius archival RPC).

## 5. Pokrycie historii portfeli i brak archiwalnych danych X/Telegram
- Na publicznych węzłach RPC głęboka historia dziesiątków tysięcy portfeli podlega limitom zapytań — portfele z niepełną historią mają status `INSUFFICIENT_HISTORY` lub `PARTIAL_PAGINATED`.
- Brak wiarygodnego darmowego źródła historycznych stanów kont X/Telegram z dokładnością co do sekundy przed pumpem — aktywność historyczna social media ma jawny status `UNKNOWN` (bez używania dzisiejszej liczby obserwujących).
