# IS_IT_WORTH_IT — design spec

Status: **approved** (2026-07-28, via interactive brainstorming + plan mode).

## Context

Narzędzie oceniające, **czy dropshipping danego produktu / współpraca z daną hurtownią jest opłacalna**.

Hurtownia daje klientowi plik CSV (nazwa produktu, cena hurtowa, EAN, kategoria hurtowni). System ma:
podzielić plik na kategorie → dla produktów znaleźć **najtańszą realną ofertę na rynku** → policzyć marżę
z uwzględnieniem kosztów → wydać raport, czy i przy jakiej marży ta współpraca ma sens.

Kluczowy warunek biznesowy: liczy się **oferta z realnym czasem dostawy** (domyślnie ≤ 5 dni). Tanie oferty
płynące 2 miesiące z Chin są dla tej analizy bezwartościowe i muszą być odfiltrowane.

Projekt jest greenfield — repo zawierało tylko `CLAUDE.md`, `.claude/` (skille design/impeccable) i `.gitignore`.

### Decyzje podjęte w brainstormingu

| Temat | Decyzja |
|---|---|
| Rynek / źródło cen | **Open web przez Perplexity Sonar** (max kompletność). Allegro ewentualnie później jako drugi provider |
| Zakres V1 | **Lokalne narzędzie web**, jeden użytkownik, bez logowania — ale architektura gotowa pod późniejszy SaaS (free/premium) |
| Tryby skanu | **Oba**: pełny skan każdego produktu **oraz** próbkowanie N produktów per kategoria |
| Model kosztów | **B** — konfigurowalne: prowizja %, wysyłka, VAT, zwroty. Model **C** (progi per kategoria, pakowanie, opłaty płatnicze) zostaje na **premium** |
| Cena sprzedaży | **Widełki scenariuszy** (np. −10 / −5 / 0 / +5 % względem najtańszej oferty) |
| Klucz API | **Użytkownik podaje własny klucz Perplexity** — koszty ponosi sam |
| Stack | **React + Vite + TS + Tailwind** (frontend) + **Python FastAPI** (backend) |
| Platformy e-commerce | Docelowo aplikacja na **Shopify / WooCommerce**, z **zapisem do sklepu** (nie tylko raport). W V1: fundamenty + szkic `ShopifySource` |

### Dlaczego to nietrywialne (research)

Źródła cen dzielą się na modele o różnej charakterystyce: porównywarki z feedów (Google Shopping, Ceneo) widzą
tylko sklepy, które **same** wgrały produkt; marketplace API (Allegro) są kompletne tylko dla swojej platformy, ale
znają realny czas dostawy; open-web/LLM daje największą kompletność kosztem prędkości, ceny i dokładności.
Wybraliśmy open-web → **projekt musi aktywnie zarządzać kosztem, czasem i wiarygodnością odpowiedzi LLM**.

Skala problemu: 6 500 produktów × 1 zapytanie ≈ **ponad 2 h** przy limicie ~50 zapytań/min i realnym koszcie
rzędu dziesiątek dolarów. Stąd cache, próbkowanie i estymacja kosztu przed startem nie są dodatkami — są rdzeniem.

---

## Architektura

Pipeline z wyraźnymi granicami — każdy etap testowalny osobno:

```
CatalogSource → Normalize → Scope+Estimate → Price Discovery → Margin Engine → Report
  (CSV | Shopify | Woo)                            ↕ Cache (SQLite)        ↓
                                                                    CatalogSink (przyszłość)
```

Backend jest **API-first**: cała wartość żyje za HTTP API, React SPA jest tylko jednym z klientów.
Aplikacja Shopify (osadzona w panelu) i wtyczka WooCommerce (PHP) będą kolejnymi — żadna z nich nie
uruchomi kodu z `frontend/`. Dlatego **żadna logika domenowa nie może trafić do frontendu**.

### Backend (`backend/app/`)

- **`sources/`** — **skąd biorą się produkty** (bliźniak `providers/`):
  - `base.py` — protokół `CatalogSource` → zwraca znormalizowane `Product`
  - `csv_source.py` — implementacja V1: wykrycie separatora (PL często `;`) i kodowania (utf-8 / cp1250),
    auto-mapowanie kolumn (nazwa / cena hurtowa / EAN / kategoria) z ręczną korektą
  - `shopify_source.py` — **szkic w V1** (odczyt katalogu, bez OAuth i deploymentu), żeby wcześnie
    sprawdzić, czy abstrakcja wytrzymuje zderzenie z realnym API Shopify
  - `woo_source.py` — później
- **`normalize/`** — parsowanie cen (przecinek dziesiętny), **walidacja sumy kontrolnej EAN-13/8**,
  deduplikacja, grupowanie po kategoriach.
- **`providers/`** — **serce rozszerzalności**:
  - `base.py` — protokół `PriceProvider` z jedną metodą: `find_cheapest(product, market, max_delivery_days) -> OfferResult`
  - `perplexity.py` — implementacja V1 (Sonar, structured JSON output)
  - `allegro.py` — **nie w V1**, ale interfejs ma to unieść bez przepisywania reszty
- **`cache/`** — SQLite, klucz `(ean, market, provider, max_delivery_days)` + TTL. Nigdy nie płacimy dwa razy za ten sam produkt.
- **`jobs/`** — silnik zadań: asynchroniczny, **wznawialny**, z limitem współbieżności pod rate limit, strumieniujący postęp.
- **`pricing/`** — silnik marży (model B) + macierz scenariuszy cenowych.
- **`reports/`** — agregacja per kategoria i globalnie.
- **`api/`** — trasy FastAPI.

### Frontend (`frontend/src/`)

Przepływ ekranów: **Upload → Mapowanie kolumn → Zakres + estymacja kosztu → Przebieg (live progress) → Raport**.

Raport: tabela kategorii, macierz scenariuszy, drill-down do produktu, wyraźne oznaczenie ofert
niepewnych / odrzuconych przez filtr dostawy.

---

## Kluczowe decyzje projektowe

### 1. Kontrakt providera (najważniejszy interfejs w systemie)

`OfferResult` musi zawierać co najmniej: `price`, `currency`, `seller`, `source_url`, `delivery_days`,
`confidence`, `citations`, `raw_response`. Bez `source_url` oferta jest **nieważna** — patrz niżej.

### 2. Polityka „żadnych zmyślonych cen"

To główne ryzyko całego projektu — LLM potrafi podać cenę, której nie ma. Obrona warstwowa:

- structured output z **wymaganym** `source_url` i cytowaniami; brak źródła → wynik odrzucony,
- pole `confidence`; niska pewność → produkt oznaczony w raporcie, nie wliczany po cichu do średnich,
- **detekcja anomalii**: cena rynkowa poniżej ceny hurtowej lub absurdalnie wysoka → flaga do ręcznego przeglądu,
- `raw_response` trzymany w bazie, żeby każdą liczbę w raporcie dało się zaudytować.

### 3. Uczciwość statystyczna próbkowania

Tryb próbkowania daje **oszacowanie**, nie pomiar. Raport pokazuje wielkość próby i przedział ufności,
i nie udaje precyzji, której nie ma. Próbkowanie warstwowe (proporcjonalnie do liczebności kategorii).

### 4. Pieniądze na `Decimal`, nigdy `float`

Wszystkie kwoty w `Decimal` z jawnym zaokrąglaniem. Waluty trzymane jawnie — oferty zagraniczne wymagają przeliczenia.

### 5. Estymacja przed uruchomieniem

Przed startem skanu użytkownik widzi: liczbę zapytań (po odjęciu trafień w cache), szacowany koszt w USD
i szacowany czas. To jego pieniądze — nie wolno go zaskoczyć.

### 6. Gotowość na platformy e-commerce (tanie teraz, drogie później)

Trzy rzeczy wchodzą do V1 **wyłącznie dlatego**, że dorobienie ich później jest nieproporcjonalnie kosztowne:

- **`tenant_id` w schemacie bazy od pierwszej migracji.** Aplikacje Shopify są z natury wielo-sklepowe
  (instalacja + OAuth per sklep). W V1 pole ma wartość domyślną i nikt go nie widzi. Dodanie go do
  działającej bazy później oznacza migrację wszystkich tabel i audyt każdego zapytania.
- **Stabilne ID zewnętrzne na produkcie** (`external_id`, `variant_id`, `source`), obok EAN.
  EAN nie wystarczy do wskazania *którego wariantu w sklepie* dotyczy wynik — warianty i braki EAN są normą.
- **`CatalogSink` jako nazwany, jeszcze niezaimplementowany kierunek.** Skoro docelowo aplikacja ma
  *działać* na sklepie (sugerować ceny, oznaczać nierentowne produkty), wynik analizy musi dać się
  odwzorować z powrotem na konkretny obiekt w sklepie. To wymóg na model danych, nie na kod.

**Świadome napięcie do rozstrzygnięcia przed wersją platformową:** ustaliliśmy „użytkownik podaje własny
klucz Perplexity". W aplikacji na Shopify to słaby UX — tam standardem jest rozliczenie przez Shopify
Billing API, a nie proszenie sklepu o klucz do zewnętrznego LLM-a. V1 zostaje przy własnym kluczu;
decyzja o modelu rozliczeń zapada przy pracach nad integracją, nie teraz.

---

## Meta-projekt: reguły, skille, subagenty

`CLAUDE.md` tego projektu wymaga zaprojektowania ich **przed** kodem:

**Reguły (`.claude/rules/`)**
- `money.md` — `Decimal`, jawne waluty, zasady zaokrąglania
- `provider-contract.md` — jak wygląda poprawny provider i jego kontrakt
- `no-hallucinated-prices.md` — polityka z pkt 2 jako twarda reguła projektu

**Skille (`.claude/skills/`)**
- `add-price-provider` — krok po kroku dodanie nowego źródła cen (np. Allegro) zgodnie z kontraktem
- `add-catalog-source` — dodanie nowego źródła produktów (WooCommerce, kolejna platforma). Design:
  `2026-08-26-catalog-source-base-class-design.md` (wspólna warstwa normalizacji `BaseCatalogSource`
  + sam skill, zanim powstanie trzecie źródło).
- `cost-safety` — jak testować ścieżki LLM **bez** palenia realnych tokenów (mocki, nagrane odpowiedzi)

**Subagenty (`.claude/agents/`)**
- `report-analyst` — projektowanie i weryfikacja logiki agregacji/raportu
- `provider-tester` — sprawdzanie zgodności providera z kontraktem na nagranych odpowiedziach

---

## Plan realizacji (na wysokim poziomie)

Kolejność jest celowa: **wszystko, co da się zbudować bez wydawania pieniędzy na API, powstaje najpierw.**
Faza po fazie szczegóły — patrz odpowiadający plan implementacyjny (writing-plans).

0. Scaffold (backend FastAPI, frontend Vite/React/TS/Tailwind, pytest, lint)
1. CatalogSource (CSV) + Normalize — TDD, bez API
2. Margin Engine — TDD, bez API
3. Provider layer + Perplexity + Cache
4. Job engine (async, wznawialny, streaming postępu)
5. Frontend (pełny przepływ ekranów + raport)
6. Szkic `ShopifySource` (weryfikacja abstrakcji, bez OAuth/hostingu)
7. Meta — spisanie reguł/skilli/subagentów z sekcji wyżej. Zrobione:
   `2026-08-26-phase-7-meta-writeup.md` (plan vs. faktyczny stan, z uzasadnieniem rozbieżności).

## Weryfikacja końcowa

1. `pytest` w `backend/` — zielone.
2. Lint/build we `frontend/` — czyste.
3. Ścieżka e2e w przeglądarce: wgranie prawdziwego CSV → mapowanie → tryb próbkowania → raport.
4. Kontrola kosztu: licznik zapytań zgodny z estymacją; ponowny skan tego samego pliku → ~0 nowych zapytań (cache).
5. Kontrola wiarygodności: każda cena w raporcie ma klikalne źródło; oferty bez źródła nie trafiają do wyniku.

## Świadomie poza zakresem V1

Konta i logowanie, płatności, model kosztów C, provider Allegro, wielorynkowość, monitoring cen w czasie.

Po stronie platform: **OAuth i instalacja aplikacji Shopify, webhooki (w tym obowiązkowe GDPR), hosting,
UI osadzone w panelu Shopify, wtyczka WooCommerce, `CatalogSink` (zapis do sklepu), Shopify Billing.**

Architektura ma to wszystko unieść — ale teraz budujemy wyłącznie fundamenty i szkic odczytu z Shopify.
