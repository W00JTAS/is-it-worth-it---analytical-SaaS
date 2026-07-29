# Faza 4 — silnik zadań (job engine) — design spec

Status: **approved** (2026-07-29, via interaktywny brainstorming).

## Kontekst

Faza 3 (provider layer: `PriceProvider`/`OfferResult` protokół, `PerplexityProvider`, cache
SQLite) jest zrobiona i zmergowana do `master`. Główny spec
(`docs/superpowers/specs/2026-07-28-is-it-worth-it-design.md`) opisuje Fazę 4 tylko na wysokim
poziomie: "silnik zadań: asynchroniczny, wznawialny, z limitem współbieżności pod rate limit,
strumieniujący postęp" plus estymacja kosztu przed startem i tryb próbkowania. Ten dokument
rozstrzyga architekturę na tyle konkretnie, żeby dało się z niej zrobić plan implementacyjny
(`writing-plans`) w stylu Fazy 3.

W trakcie brainstormingu doszły też dwa dodatkowe tematy, które poniżej mają swoje sekcje:
1. Funkcja ostrzegania o nieświeżych produktach przy ponownym wgraniu podobnego katalogu.
2. Ponowna analiza wyboru providera (Perplexity) na podstawie wcześniejszego, niezależnego
   researchu porównującego 5 modeli źródeł cen — z konkretną decyzją, co robimy z Allegro i z
   surowym "open-web SERP" jako alternatywnymi/dodatkowymi źródłami.

## Zakres Fazy 4

### Wchodzi

- **Trwałe przechowanie katalogu**: tabela `products` w SQLite (surowy `sqlite3`, ten sam
  wzorzec co `PriceCache` z Fazy 3 — `CREATE TABLE IF NOT EXISTS`, brak ORM/migracji, brak
  nowych zależności). Przy starcie skanu wgrany CSV jest parsowany istniejącym
  `CsvCatalogSource` (Faza 0-2) i persystowany jako wiersze `products`, każdy powiązany z
  `scan_id`.
- **Metadane zadania**: tabela `scans` — status (`pending`/`running`/`done`/`failed`),
  konfiguracja zakresu (pełny/próbka + parametry), liczniki postępu, estymacja kosztu/czasu,
  znacznik czasu utworzenia.
- **Rozstrzyganie zakresu**: pełny skan (wszystkie produkty) albo próbkowanie (algorytm
  water-filling, patrz niżej).
- **Estymacja kosztu/czasu przed startem**: policz liczbę zapytań faktycznie potrzebnych (po
  odjęciu trafień w `PriceCache`) × koszt/czas per zapytanie do Perplexity. Zwracane jako część
  odpowiedzi na żądanie utworzenia skanu, zanim faktycznie ruszy.
- **Wykrywanie nieświeżych produktów** (nowy temat z tej rozmowy — patrz sekcja osobna niżej).
- **Silnik zadań**: asynchroniczny worker (`asyncio` + `httpx.AsyncClient` lub odpowiednik),
  limit współbieżności **konfigurowalny w żądaniu utworzenia skanu** (parametr z sensownym
  bezpiecznym defaultem — nie sztywna stała w kodzie, bo docelowo ma przyjść z UI Fazy 5),
  wznawialny **wyłącznie jako odporność na awarię procesu**: jeśli backend padnie w trakcie
  skanu, kolejne żądanie (np. restart + wywołanie odpowiedniego endpointu, albo automatyczne
  wznowienie przy starcie procesu — do ustalenia w planie implementacyjnym) kontynuuje produkty
  ze statusem `pending`. **Świadomie odrzucone**: ręczna pauza/wznów z poziomu UI — niepotrzebna
  złożoność na V1.
- **API**: minimalne REST + SSE, patrz sekcja "API".

### Nie wchodzi (świadomie, zostaje na Fazę 5)

- Interaktywny ekran korekty mapowania kolumn CSV (funkcja `column_mapping.py` z Fazy 0-2 już
  istnieje jako czysta logika — Faza 5 dopiero owija ją w UI).
- Sam UI: ekrany, live progress bar, tabela raportu, dialog z pytaniem o nieświeże produkty
  (backend tej fazy tylko dostarcza dane potrzebne do takiego dialogu — patrz niżej).

## Dane i trwałość

### Tabela `products`

Jeden wiersz per produkt per skan (nie globalny katalog master — każdy skan ma swój zestaw
wierszy, powiązanych przez `scan_id`, żeby dwa niezależne skany tego samego pliku nie
kolidowały ze sobą). Kolumny odzwierciedlają istniejący `Product` dataclass z Fazy 0-2
(`tenant_id`, `source`, `external_id`, `variant_id`, `name`, `ean`, `wholesale_price`,
`currency`, `category`) plus pola specyficzne dla skanu: `scan_id`, `status`
(`pending`/`done`/`skipped`/`failed`), `offer_price`, `offer_currency`, `offer_source_url`, itd.
(pola z `OfferResult` po zakończeniu lookupu) — dokładny schemat SQL to zadanie dla planu
implementacyjnego, nie tego dokumentu.

### Tabela `scans`

`id`, `status`, `scope_type` (`full`/`sample`), `scope_config` (np. JSON: N per kategoria, seed),
`max_concurrency`, `staleness_threshold_days`, `total_products`, `completed_products`,
`estimated_cost_usd`, `estimated_seconds`, `created_at`.

### Lokalizacja plików SQLite

Jeden plik SQLite dla całej trwałej aplikacji (cache z Fazy 3 + `products` + `scans` razem) —
prostota dla lokalnego narzędzia jednoosobowego, zgodnie z resztą decyzji o unikaniu
niepotrzebnej infrastruktury na V1. Dokładna ścieżka domyślna — do ustalenia w planie
implementacyjnym (np. `backend/data/app.sqlite3`, tworzone przy starcie jeśli nie istnieje).

## Próbkowanie — algorytm water-filling

Użytkownik podaje jedno **N = docelowa liczba produktów per kategoria**.

1. Dla każdej kategorii, jeśli `rozmiar_kategorii <= N`: bierzemy wszystkie produkty z tej
   kategorii; niedobór (`N - rozmiar_kategorii`) trafia do wspólnej puli.
2. Pula jest rozdzielana **równo** (nie proporcjonalnie do wielkości kategorii) między
   kategorie, które mają jeszcze zapas produktów ponad swoje N.
3. Redystrybucja jest **iteracyjna** (klasyczny water-filling): jeśli kategoria po dołożeniu
   swojej części puli i tak przekroczy własny rozmiar, nadwyżka wraca do puli i jest
   redystrybuowana dalej wśród pozostałych kategorii z zapasem — nie tylko jeden przebieg.
4. Jeśli pula nie dzieli się równo między pozostałe kategorie z zapasem, reszta z dzielenia jest
   tracona (jedna kategoria nie dostaje dodatkowego produktu). Kolejność kategorii przy
   przydzielaniu reszty musi być **deterministyczna** (stabilnie posortowana lista, nigdy
   `set` — powtórzenie lekcji z Fazy 0-2 o niedeterministycznej kolejności iteracji rzutującej
   na wynik).
5. Wybór KONKRETNYCH produktów w ramach kategorii: **losowy, z seedem wyprowadzonym z ID
   skanu** — zapewnia, że wznowienie po awarii (patrz wyżej) wybiera dokładnie tę samą próbkę,
   nie inną.

## Wykrywanie nieświeżych produktów (nowy temat)

**Problem**: użytkownik wgrywa CSV podobny/identyczny do tego z poprzedniego skanu (np. 2
tygodnie później), żeby zobaczyć aktualną sytuację. System powinien to wykryć i zapytać, zanim
zacznie skanować od zera.

**Mechanizm**: przy tworzeniu nowego skanu, dla każdego produktu z nowego CSV dopasowanego po
EAN/`external_id` do produktu już istniejącego w bazie z wcześniejszego skanu, sprawdzamy wiek
ostatniego udanego sprawdzenia ceny (`cached_at` z `PriceCache`, Faza 3 — już istnieje, nic
nowego do zbudowania po tej stronie).

- **Próg nieświeżości**: stały domyślny **14 dni**, konfigurowalny jako parametr żądania
  (ten sam wzorzec co `max_concurrency`). Świadomie **odrębny** od twardego TTL cache'u (30 dni
  domyślnie) — TTL decyduje kiedy wynik przestaje być ważny w ogóle; próg nieświeżości decyduje
  kiedy *proaktywnie pytamy użytkownika*, czy chce wymusić odświeżenie mimo że cache jeszcze
  formalnie ważny.
- **Co zwraca backend**: krok estymacji (przy tworzeniu skanu, przed jego faktycznym startem)
  zwraca dodatkowo: liczbę produktów nakładających się z poprzednimi skanami, i ile z nich
  przekracza próg nieświeżości.
- **Co robi Faza 5**: renderuje to jako pytanie do użytkownika ("X produktów niesprawdzanych od
  Y dni — sprawdzić ponownie?") i przekazuje jego decyzję jako parametr **faktycznego** startu
  skanu (`force_refresh_stale: bool` czy podobnie) — jeśli `false`, te produkty są od razu
  oznaczone `skipped`/`done` z istniejącą ceną z cache, bez ponownego zapytania do Perplexity.

## API

Minimalne REST + SSE (Server-Sent Events wybrane zamiast WebSocket — potrzebujemy tylko
kierunku backend→frontend; wybrane zamiast pollingu — spec wprost wymaga "strumieniującego"
postępu):

**Rozstrzygnięte: tworzenie skanu to zawsze DWA kroki, nigdy jeden** — zgodnie z zasadą z
głównego specu ("Estymacja przed uruchomieniem... to jego pieniądze — nie wolno go zaskoczyć"),
żadne żądanie nie może jednocześnie policzyć estymacji i od razu zacząć wydawać pieniądze na
Perplexity:

- `POST /scans` — przyjmuje plik CSV (multipart) + parametry zakresu (pełny/próbka + N,
  `max_concurrency`, `staleness_threshold_days`). Parsuje CSV, persystuje `products` powiązane
  z nowym `scan_id`, wykrywa nakładanie z poprzednimi skanami i nieświeże produkty, liczy
  estymację kosztu/czasu. Tworzy wiersz `scans` ze statusem `estimated` — **nie odpala
  workera**. Zwraca `scan_id` + estymacja + info o nieświeżych produktach.
- `POST /scans/{id}/start` — przyjmuje `force_refresh_stale: bool` (decyzja użytkownika z
  dialogu Fazy 5). Dopiero to żądanie oznacza nieświeże-ale-pomijane produkty jako
  `skipped`/`done` z ceną z cache, przestawia `scans.status` na `running`, i faktycznie odpala
  asynchronicznego workera.
- `GET /scans/{id}` — status i liczniki postępu (dla klientów bez SSE, albo do odświeżenia po
  utracie połączenia SSE).
- `GET /scans/{id}/events` — strumień SSE z live postępem (ile zrobione, narastający koszt).

Dokładne kształty żądań/odpowiedzi (pola JSON, kody błędów) — do ustalenia w planie
implementacyjnym; ten dokument ustala tylko podział na kroki i odpowiedzialność każdego z nich.

## Ponowna analiza wyboru providera (Perplexity) — kontekst i decyzje

Użytkownik przedstawił treść wcześniejszej, niezależnej rozmowy (research), która porównała 5
modeli źródeł cen:

| # | Model | Przykłady | Kompletność | Zna czas dostawy? |
|---|---|---|---|---|
| 1 | Porównywarki z feedów | Google Shopping, Ceneo | Tylko opt-in sprzedawcy | Częściowo |
| 2 | Live marketplace | **Allegro**, Amazon, eBay | Kompletne dla platformy | **Tak, realny** |
| 3 | Open-web SERP | DataForSEO, SerpApi, Bing | Najbliżej "całego internetu" | Nie |
| 4 | LLM web-search | **Perplexity Sonar** (zbudowane) | Bardzo szeroka | Potrafi wywnioskować |
| 5 | Bazy EAN | UPCitemdb, EAN-Search | — | Nie |

Ten research **potwierdza**, że model 3 (open-web SERP) i model 4 (Perplexity/LLM) to faktycznie
dwa różne mechanizmy — nie jeden, jak przedstawiał to wcześniejszy, błędny opis bez dostępu do
tego researchu. Ważniejsze: ten sam research rekomendował rozpoczęcie V1 od Allegro (model 2)
jako głównego providera, a open-web/Perplexity dołożenie dopiero w V2 — czyli odwrotny priorytet
niż to, co faktycznie trafiło do zatwierdzonego głównego specu i zostało zbudowane w Fazie 3.
Nie ma zapisu, czy ta zmiana priorytetu była świadomą decyzją w tamtej wcześniejszej rozmowie
(transkrypt urywa się przed odpowiedzią) — potraktowane jako materialna rozbieżność do
świadomego rozstrzygnięcia teraz, nie zignorowania.

**Decyzje podjęte teraz:**

- **Allegro** (model 2) — zostaje odłożone na "kiedyś", bez konkretnej daty. Zweryfikowano
  (WebSearch, 2026-07-29): Allegro REST API `GET /offers/listing` jest publicznie dostępne bez
  konta sprzedawcy, wspiera parametr GTIN/EAN — rekomendacja z tamtego researchu jest technicznie
  wykonalna, nie tylko teoretyczna, gdyby projekt do niej wrócił.
- **Open-web SERP** (model 3) — **nie wprowadzamy teraz**. Powód: SERP nie zastępuje Perplexity
  (surowy SERP nie zna czasu dostawy — to wciąż jedyne miejsce, gdzie LLM ma realną przewagę),
  więc dołożenie SERP to dodatkowa warstwa kosztu/złożoności, nie tańsza alternatywa. Zamiast
  wprowadzać teraz na spekulację, **kryterium powrotu do tematu jest zapisane jawnie**: po
  pierwszym realnym skanie z Fazy 4/5, zmierzyć na prawdziwym katalogu użytkownika % produktów z
  `found=false` / niską `confidence` z samego Perplexity. Jeśli okaże się to realnym problemem
  (nie tylko teoretycznym), wrócić do SERP z twardymi liczbami. **Ten dokument jest miejscem
  zapisania tego zobowiązania** — dokładnie ten sam problem (zgubienie decyzji między
  rozmowami) już raz się przydarzył między wklejonym researchem a finalnym głównym specem.

## Weryfikacja końcowa (dla Fazy 4)

1. `pytest` w `backend/` — zielone, w tym testy na mockowanym providerze (bez realnych zapytań
   do Perplexity w standardowym przebiegu testów, zgodnie z regułą z Fazy 3).
2. Test wznowienia po awarii: symulowane przerwanie w trakcie skanu, restart, potwierdzenie że
   kontynuuje dokładnie te same `pending` produkty bez duplikowania już zrobionych.
3. Test algorytmu water-filling: zestaw kategorii o różnych rozmiarach, w tym przypadek gdzie
   redystrybucja wymaga więcej niż jednej iteracji, i przypadek z niepodzielną resztą.
4. Test wykrywania nieświeżości: dwa kolejne "skany" tego samego EAN-u z różnicą czasu większą
   i mniejszą niż próg — potwierdzenie poprawnej klasyfikacji.
5. Kontrola kosztu: estymacja zwrócona przed startem zgadza się z faktyczną liczbą zapytań po
   zakończeniu skanu (uwzględniając trafienia w cache i nieświeże-ale-pominięte produkty).

## Świadomie poza zakresem Fazy 4

Ręczna pauza/wznów z UI, sam UI/ekrany (Faza 5), provider Allegro (odłożone), open-web SERP
(odłożone z jawnym kryterium powrotu), model kosztów C, wielorynkowość, `ShopifySource` (Faza 6).
