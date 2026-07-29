# Faza 5a — ekrany Upload → Zakres+Estymacja → Przebieg — design spec

Status: **approved** (2026-07-29, via interaktywny brainstorming).

## Kontekst

Faza 4 (silnik zadań: `POST /scans`, `POST /scans/{id}/start`, `GET /scans/{id}`,
`GET /scans/{id}/events`) jest zrobiona i zmergowana. Główny spec
(`docs/superpowers/specs/2026-07-28-is-it-worth-it-design.md`) opisuje Fazę 5 jako cały
frontend: "Upload → Mapowanie kolumn → Zakres + estymacja kosztu → Przebieg → Raport".

W brainstormingu ustalono, że to w praktyce trzy niezależne kawałki o różnej gotowości:
- **Upload → Zakres+Estymacja → Przebieg** — czyste konsumowanie istniejącego API Fazy 4,
  samowystarczalne, gotowe do budowy teraz. **To jest zakres tego dokumentu (Faza 5a).**
- **Mapowanie kolumn** (korekta auto-detekcji) — wymaga nowego endpointu backendowego
  (podgląd wykrytego mapowania przed commitem). Odłożone do Fazy 5c, własny brainstorming.
- **Raport** (tabela kategorii, macierz scenariuszy, drill-down) — silnik marży z Fazy 0-2
  istnieje jako czysta funkcja, ale nic go nie używa; potrzebny nowy backendowy moduł
  `reports/` agregujący ceny + koszty. Odłożone do Fazy 5b, własny brainstorming.

Frontend jest obecnie czystym scaffoldem (Vite + React 19 + TS + Tailwind v4), bez routera,
bez biblioteki do fetchowania danych, bez żadnego test runnera (tylko `oxlint` do lintu).

## Zakres Fazy 5a

### Wchodzi

- **Routing**: brak biblioteki routingu (react-router itp.). Jeden komponent najwyższego
  poziomu trzyma w stanie aktualny krok (`"upload" | "scope" | "progress"`) i przełącza
  widoki warunkowo — trzy liniowe kroki bez potrzeby głębokiego linkowania nie uzasadniają
  nowej zależności.
- **Fetching danych**: natywny `fetch`/`EventSource` we własnych hookach, bez TanStack Query
  ani podobnej biblioteki — brak cache'owania/refetchów w tle/invalidacji do zarządzania na
  tym etapie.
- **Trzy ekrany**:
  1. `UploadStep` — wybór/wysyłka pliku CSV.
  2. `ScopeEstimateStep` — formularz zakresu (pełny/próbka + N per kategoria, limit dostawy,
     próg nieświeżości, limit współbieżności) → `POST /scans` (liczy estymację, **nic nie
     kosztuje**) → pokazanie kosztu/czasu z i bez wymuszonego odświeżenia nieświeżych +
     liczby nakładających/nieświeżych produktów → decyzja użytkownika → `POST /scans/{id}/start`.
  3. `ProgressStep` — SSE live progress, stan końcowy jako prosty podsumowujący komunikat.
- **Obsługa zerwania SSE**: automatyczny reconnect (kilka prób z rosnącym opóźnieniem), potem
  fallback na polling `GET /scans/{id}` co kilka sekund. Użytkownik nigdy nie widzi
  "zawieszonego" ekranu.
- **Testy**: Vitest + React Testing Library, TDD tak jak backend — hooki testowane z
  mockowanym `fetch`/`EventSource` (zero prawdziwych zapytań sieciowych w testach), komponenty
  testowane przez renderowanie + interakcję użytkownika, asercje na widocznym
  stanie/tekście, nie na szczegółach implementacji.

### Nie wchodzi (świadomie, zostaje na kolejne pod-fazy)

- Ekran korekty mapowania kolumn (Faza 5c) — jeśli auto-detekcja CSV się nie uda, użytkownik
  dostaje czytelny komunikat błędu (400 z backendu) i musi poprawić plik ręcznie.
  Świadome ograniczenie tej pod-fazy.
- Ekran Raportu i jakikolwiek link do niego (Faza 5b) — `ProgressStep`'s stan końcowy to
  tylko podsumowanie liczników (bez agregacji marży, bo backend jej jeszcze nie liczy).
- Live śledzenie narastającego kosztu w trakcie skanu — obecne API zwraca tylko
  `completed_products`/`total_products`, nie koszt-do-tej-pory. Pasek postępu pokazuje
  liczbę produktów, nie kwotę. Dodanie tego wymagałoby zmian w Fazie 4's `Scan`/`ScanStore` —
  świadomie poza zakresem, żeby nie otwierać ponownie zamkniętej fazy backendu.

## Architektura

Jeden komponent najwyższego poziomu (`ScanWizard`) trzyma stan kroku i dane przekazywane
między krokami (przesłany plik → `scan_id` + estymacja → id do SSE). Trzy komponenty-ekrany,
każdy z jedną odpowiedzialnością, bez propsów-worków — każdy dostaje dokładnie to, czego
potrzebuje, i zwraca callback do przejścia dalej.

## Warstwa danych

Hooki w `frontend/src/api/`:
- `createScan(file, scopeConfig) -> {scanId, estimate, overlappingCount, staleCount, warnings}`
  — `POST /scans` (multipart).
- `startScan(scanId, forceRefreshStale) -> void` — `POST /scans/{id}/start`.
- `useScanEvents(scanId)` — otwiera `EventSource` na `GET /scans/{id}/events`; przy błędzie
  próbuje reconnect (backoff), po wyczerpaniu prób przełącza się na `setInterval` odpytujący
  `GET /scans/{id}`. Zwraca aktualny stan skanu (status, liczniki) + źródło danych
  (`"sse" | "polling"`), żeby UI mógł to zasygnalizować.

## Obsługa błędów

Każdy krok pokazuje błąd zwrócony przez backend (400 z konkretnym komunikatem: zły nagłówek
CSV, zła wartość `max_concurrency` itp.) bezpośrednio użytkownikowi, z możliwością poprawy i
ponownej próby tego samego kroku.

## Design wizualny

Nie ustalony w tym dokumencie — przy implementacji używany jest skill `frontend-design`
(globalny, ogólne wskazówki estetyczne) do nadania spójnego, nieszablonowego stylu zamiast
domyślnego wyglądu komponentów. Ten dokument opisuje funkcjonalność i strukturę, nie wygląd.

## Weryfikacja końcowa

1. `npm run lint` i `npm test` (Vitest) w `frontend/` — zielone.
2. Ręczny przebieg w przeglądarce: wgranie prawdziwego CSV → wybór zakresu (pełny i próbka) →
   zobaczenie estymacji → start → live progress do końca (SSE), w tym symulacja zerwania
   połączenia (np. przez devtools) i potwierdzenie przejścia na polling.
3. Ścieżki błędów: upload pustego pliku, zła wartość liczbowa w formularzu zakresu — czytelny
   komunikat, nie martwy ekran.

## Świadomie poza zakresem Fazy 5a

Mapowanie kolumn (Faza 5c), Raport i agregacja marży (Faza 5b), live koszt w trakcie skanu,
router, biblioteka do fetchowania danych.
