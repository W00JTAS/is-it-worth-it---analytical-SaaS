# IS_IT_WORTH_IT — architektura BYOK + logowanie + ustawienia + migracja na Supabase

## Context

**Nadrzędny cel projektu: publiczne repo i działające demo**, które da się obejrzeć bez zakładania
konta. To ma pierwszeństwo przed pozyskaniem realnych użytkowników, a ta kolejność rozstrzyga kilka
decyzji poniżej inaczej, niż rozstrzygnęłaby ją logika „budujemy SaaS".

Projekt jest dziś **jednoosobowym narzędziem lokalnym**: brak logowania, brak użytkowników, jeden
plik SQLite (`backend/data/app.sqlite3`, 387 MB), klucz Perplexity czytany raz z `os.environ` do
procesowego singletona, poświadczenia WooCommerce/Shopify przekazywane jako jawne pola formularza
przy każdym żądaniu i nigdzie nietrzymane.

Faza researchu (handoff_15/16) zamknęła się werdyktem: **nie istnieje ścieżka jednocześnie darmowa
i skalująca się do pełnego katalogu**. Przyjęty kierunek to **BYOK** — użytkownik podpina własnego
dostawcę AI. To wymusza trzy rzeczy, których dziś nie ma i których nie da się dodać osobno: konta
użytkowników, bezpieczne przechowywanie cudzych sekretów, oraz bazę, która to udźwignie.

## Decyzje podjęte (stałe — nie otwierać ponownie)

| # | Decyzja |
|---|---|
| 1 | **Rejestracja na zaproszenie + publiczne demo** (nie otwarty self-service — patrz „Dlaczego") |
| 2 | **Supabase Vault** jako magazyn sekretów (nie szyfrowanie po stronie aplikacji) |
| 3 | **Jeden generyczny model `connections`**, ale teraz implementujemy wyłącznie `kind='ai_provider'` |
| 4 | **Wszystko w chmurze** — Supabase Postgres jedyną bazą, koniec SQLite |
| 5 | **Nie zapisywać `offer_raw_response`** + retencja starych skanów |
| 6 | **Backend na Fly.io** (kontener long-running), **frontend na Vercel** |
| 7 | **Testy na lokalnym Postgresie w kontenerze** — jedyny wyjątek od pkt. 4 |
| 8 | **BYOK obowiązkowy dla kont**; jedyny wyjątek to tryb demo na kluczu operatora |
| 9 | **Groq = tryb próbny, Perplexity = tryb roboczy** — onboarding mówi to wprost |
| 10 | **Spike Groq na starcie**, przed budową infrastruktury |
| 11 | **Jedno repo, publiczne, w całości** — łącznie z warstwą chmurową i konfiguracją deploymentu |
| 12 | **Demo: 3 gotowe próbki** (technologia, zabawki, kuchnia) na kluczu Groq operatora |
| 13 | **Shopify/WooCommerce zostają w kodzie, znikają z UI**; w przyszłości osobne repo per platforma |

### Dlaczego rejestracja na zaproszenie zamiast otwartej

Otwarta rejestracja czyni Cię depozytariuszem cudzych kluczy Groq/Perplexity — z RODO, obowiązkiem
reakcji na incydent i faktem, że jeden przejęty kontener odsłania je wszystkie naraz. Otwartość
nie zmienia architektury: obsługa wielu użytkowników wygląda identycznie przy zaproszeniach. Za to
**zmniejsza zakres** — znika CAPTCHA, limity antyabuse'owe, weryfikacja e-maili i polityka
prywatności. Odwiedzający i tak nie zakłada konta; klika demo.

## Ustalenia, które zmieniły projekt

Zweryfikowane bezpośrednio na żywej bazie, w historii gita i w dokumentacji — nie założone:

- **Darmowy Groq nie wykona pełnego skanu — nie wolno, tylko w ogóle.** 17 500–26 500 lookupów × 2
  requesty (wzorzec dwuwywołaniowy) = 35–53 tys. żądań przy limicie **250/dobę** → **140–212 dni**.
  Limit 30 RPM nigdy nie wiąże; 250 RPD wyczerpuje się w **8 minut**. Darmowy tier to
  **~125 produktów dziennie**. Stąd decyzje 9 i 12.
- **260 z 387 MB to surowe payloady** (152 MB w `scan_products`, 108 MB w `price_cache`). Po ich
  usunięciu cały dotychczasowy zbiór to ~35–80 MB. Decyzja 5 jest tym, co czyni free tier możliwym.
- **Cache jest już martwy.** Wszystkie 19 774 wierszy zapisano w jednym 5-godzinnym oknie 28,8 dnia
  temu, przy TTL 30 dni. Wygasa, zanim jakakolwiek migracja zdąży wejść → **nie piszemy skryptu
  migracji cache'u.**
- **Bug pełnego skanu już wystrzelił.** Skan `db7e21c0`: 72 747 wierszy, 26 404 zrobione, status
  `running` na wieki — dokładnie ta awaria trwałości, o którą chodzi w Fazie 5, już leży w danych.
- **`MappingStep.tsx:49` re-POST-uje cały CSV przy każdej zmianie mapowania** (5 pól × 15,7 MB),
  a `ScopeEstimateStep` wysyła go szósty raz. Lokalnie za darmo; po wyjściu w chmurę to **~94 MB
  transferu na sesję**. Blocker stworzony wyłącznie przez przejście do chmury.
- **Free tier Supabase przechodzi w read-only powyżej 500 MB** bazy, a projekt pauzuje po 7 dniach
  bezczynności. Retencja jest infrastrukturą nośną, nie higieną.
- **Historia gita jest czysta.** Repo jest dziś prywatne; `.env.local` nigdy nie zostało
  zacommitowane, w całej historii nie ma żadnego wzorca klucza, nie ma pliku CSV od hurtowni ani
  bazy SQLite. Upublicznienie **nie wymaga przepisywania historii** — to rzadki i cenny stan wyjściowy.

## Tryb demo

Odwiedzający wchodzi na stronę, wybiera jedną z **3 gotowych próbek** (technologia / zabawki / kuchnia),
klika i widzi realny skan kończący się raportem — **bez zakładania konta i bez własnego klucza**.

Ograniczenia wymuszone przez limit 250 RPD na kluczu operatora:

- **Próbki są sztywne i zdefiniowane po stronie serwera** — stały zestaw ~20 produktów na kategorię.
  Tryb demo **nie może** przyjmować wgranego CSV ani żadnego wejścia od użytkownika; inaczej dowolna
  osoba spali Twój klucz w 8 minut. To jest wymóg bezpieczeństwa, nie wygody.
- **Globalny cache pracuje tutaj na naszą korzyść**: pierwszy przebieg każdej próbki go zapełnia,
  każdy kolejny odwiedzający dostaje wynik natychmiast i za zero żądań. Próbki należy **rozgrzać raz po
  deployu**, żeby pierwsze kliknięcie nigdy nie trafiło w zimny cache.
- **Dzienny budżet demo** w `provider_usage` (osobna pseudo-connection operatora) + cap per IP.
  Po wyczerpaniu budżetu demo serwuje ostatni zapisany raport zamiast odmawiać.
- Zimny przebieg próbki to ~40 żądań, czyli **~6 zimnych dem na dobę**; ciepłych bez ograniczeń.

## Architektura docelowa

### Schemat (Postgres)

Nowe: `profiles`, `connections`, `connection_secrets`, `provider_usage`.
Przerobione: `scans` (+`user_id`, `connection_id`, `provider`, `worker_id`, `heartbeat_at`,
`resume_after`, `expires_at`), `scan_products` (+`user_id`, −`offer_raw_response`), `price_cache`
(−`raw_response`, `ean` → `lookup_key`).

Mapowanie typów — trzy pułapki, każda z regresją do napisania **przed** SQL-em:

| Dziś | Docelowo | Uwaga |
|---|---|---|
| pieniądze jako `TEXT` ↔ `Decimal` | `numeric` **bez skali** | `numeric(14,2)` po cichu zaokrągla — dokładnie klasa błędu opisana w `CLAUDE.md`. psycopg3 mapuje `numeric ↔ Decimal` dokładnie. |
| znaczniki czasu jako `REAL` epoch | `timestamptz` | **Domenowo zostaje `float`**: `to_timestamp($n)` przy zapisie, `extract(epoch ...)` przy odczycie. `staleness.py:23-33` liczy na floatach i zostaje nietknięte. |
| `INSERT OR REPLACE` (`sqlite_cache.py:113,121`) | `ON CONFLICT DO UPDATE` | **Nie jest równoważne.** `OR REPLACE` kasuje wiersz, więc negatywny wpis zeruje 8 kolumn; `DO UPDATE` nie — nieaktualna oferta przetrwałaby i została podana jako realna cena. `DO UPDATE SET` musi jawnie nullować `price, currency, seller, source_url, delivery_days, confidence, citations`. |

`price_cache.lookup_key` (`ean:…` / `name:<sha256>`) to jedyny sposób, by 4 722 produkty bez EAN
(6,5%) w ogóle trafiły do cache'u — dziś `lookup.py:14-15` omija go dla nich. **Osobna zmiana, poza
portem** — rusza sygnatury `get`/`set`/`invalidate`, `staleness.py` i 6 testów.

### RLS i kto czego dotyka

**Przeglądarka nigdy nie rozmawia z Postgresem bezpośrednio.** Wszystko idzie przez FastAPI z rolą
serwisową (omija RLS); własność wymusza Python przez fasadę `for_user()`. RLS włączone wszędzie jako
druga warstwa — i dlatego, że przy publicznym repo każdy zobaczy te polityki.

- `connections`, `connection_secrets`, `price_cache`, `provider_usage` — RLS **bez polityk**
  (= deny-all), wyłącznie rola serwisowa. Nawet UUID-y sekretów nie trafiają do przeglądarki.
- `profiles`, `scans`, `scan_products` — polityka `select using (auth.uid() = user_id)`.
- `vault.decrypted_secrets` — **nigdy** nie nadawać `authenticated`.

### Warstwa dostępu do bazy

- **`psycopg[binary,pool]`, synchroniczne.** Cały kod to sync-wewnątrz-`asyncio.to_thread`
  (`engine.py:26`, `api.py:409`, `api.py:283`); async kaskadowałoby na 253 testy przy zerowym zysku —
  wąskim gardłem jest 30 zapytań HTTP na minutę, nie baza. psycopg3 daje przy okazji dokładne
  `numeric ↔ Decimal` i `jsonb ↔ dict`. Nie `supabase-py` (klient PostgREST — bez `COPY`, bez Vault).
- **`ConnectionPool` w `lifespan`** zastępuje trzy globalne singletony (`api.py:41-43`).
  **Skasować oba `threading.Lock`** — istnieją tylko dlatego, że jedno połączenie SQLite jest
  współdzielone; z pulą stają się czystą serializacją. Największy zysk wydajnościowy portu pochodzi
  z usunięcia kodu.
- **Supavisor, tryb transakcyjny, port 6543** dla aplikacji; migracje przez połączenie bezpośrednie
  (5432). Ustawić `prepare_threshold=None` — psycopg3 auto-preparuje po 5 wykonaniach, czego tryb
  transakcyjny nie wspiera (`prepared statement "_pg3_0" already exists` pod obciążeniem).
- **Migracje: Supabase CLI** (`supabase/migrations/*.sql`), nie Alembic — nie ma ORM-a, więc
  autogenerate jest martwy, a RLS, enumy, granty i `pg_cron` to większość tego schematu.
- **`ScanStore` (9 metod) i `PriceCache` (4 metody) zachowują nazwy i sygnatury** — zmienia się
  konstruktor (`db_path` → `pool`) i wnętrze.

### Auth

- Frontend: `@supabase/supabase-js` v2 (nie `@supabase/ssr` — to SPA). Pierwsze w historii projektu
  `import.meta.env`: `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_API_BASE_URL`.
- Backend: weryfikacja **JWKS/asymetryczna** przez `pyjwt[crypto]` `PyJWKClient` (cache kluczy, zero
  round-tripów). Nie legacy HS256, nie `GET /auth/v1/user` per żądanie.
- `Authorization: Bearer`, nie ciasteczka — prostszy CORS, zero CSRF. CORS trzeba dodać
  (`main.py` ma dziś 13 linii i zero middleware).
- **Fasada `store.for_user(user.id)`** — identyczne nazwy metod, predykat `user_id` wstrzykiwany
  wewnątrz. Dzięki temu (a) testy nie zmieniają ciał, (b) nie da się zapomnieć filtra w call-site,
  (c) cudzy skan wpada w istniejącą ścieżkę `404`, nigdy `403`.
- **Router jest konieczny** (`react-router` v7): callback potwierdzenia e-maila niesie `?code=`,
  `/login`, `/demo` i `/settings/connections` nie są krokami kreatora, a 4-godzinny skan, do którego
  raportu wraca się przechodząc kreator od nowa, jest bezużyteczny. **Kreator zostaje bez zmian**
  wewnątrz trasy `/`. Koszt: ~6 plików testowych dostaje wrapper `renderWithProviders`, zero
  przepisywania logiki.
- **`EventSource` nie umie wysłać nagłówka `Authorization`** (`useScanEvents.ts:60`) → zamiana na
  `fetch` + `ReadableStream`, zachowując istniejącą logikę 3 rekonesansów i fallbacku na polling.
  Przy okazji `SSE_POLL_INTERVAL_SECONDS` z 0,3 → 2 s: przy 0,3 s jeden klient oglądający
  4-godzinny skan wykonuje **48 000 zapytań `get_scan`**, każde z `COUNT(*)` po `scan_products`.

### BYOK

`get_provider()` (singleton czytający `os.environ`) → fabryka rozwiązująca per żądanie:
`connections` → `connection_secrets` → jeden `select decrypted_secret from vault.decrypted_secrets`
→ `GroqProvider` / `PerplexityProvider`.

Rozwiązywane w **dwóch** punktach, bo `create_scan` potrzebuje `provider.name` do kluczy cache'u:
w `POST /scans` (estymata, zapis `scans.provider`) i raz w `POST /scans/{id}/start` — potem
provider żyje przez cały skan. **Nigdy nie czytać Vaultu per produkt** (17 500 odszyfrowań i
4-godzinne okno ekspozycji plaintextu). Nigdy nie logować klucza — zaudytować `perplexity.py:74-77`,
które loguje `exc`.

`GroqProvider`: `compound-mini` (grounded search) → `openai/gpt-oss-20b` z `json_schema` koercujący
do **tego samego** `RESPONSE_SCHEMA` (`perplexity.py:20-33`). Wymaga wyciągnięcia
`_parse_response` (`perplexity.py:95-152`) do `app/providers/parsing.py` — jego reguły walidacji są
niezależne od dostawcy i **nie wolno, by rozjechały się** między dwoma providerami piszącymi do
jednego cache'u.

**Cache zostaje globalny, międzyużytkownikowy** — przy limicie 250 RPD to jedyny powód, dla którego
drugi użytkownik cokolwiek skończy, i to on czyni tryb demo wykonalnym. Bezpieczny dopiero po
decyzji 5: to `raw_response` odbijało echem prompt zawierający `product.name` z cudzego katalogu.
Cztery twarde zasady: `API_URL` **zostaje zaszyty na sztywno** (konfigurowalny base URL oddałby
cache w ręce atakującego — przy publicznym repo tym bardziej), zero promptów i identyfikatorów
w cache'u, RLS bez polityk, a w polskim UI zdanie o współdzieleniu wyników.

## Fazy

Ok. 48 zadań. Każda faza kończy się stanem zdatnym do uruchomienia i przetestowania.

**Faza 0 — spike Groq** · ~2 zadania
Darmowe konto Groq (2 min, bez karty — zweryfikowane). Kilkanaście realnych zapytań na produktach
z katalogu, porównanych z wynikami Perplexity. Rozstrzyga naraz jakość groundingu compound **i** czy
`json_schema` + search składają się w jednym wywołaniu — co połowi wszystkie wyliczenia RPD.
*Dlaczego pierwsza:* ryzyko jest zewnętrzne, a odpowiedź warunkuje resztę.

**Faza 1 — GroqProvider, retry, budżet limitów** (wciąż SQLite) · ~8 zadań
`app/providers/retry.py` (backoff z jitterem, `Retry-After`; 429/5xx ponawialne, 4xx trwałe —
zły klucz musi paść natychmiast, nie 17 500 razy). `ProviderRateLimited`, `ProviderAuthError`.
`GroqProvider`. Test live skip-on-env wzorem `test_perplexity_live.py`. Batchowanie w `run_scan`
+ status `paused`. Wyciągnięcie `_parse_response`, `ProviderProfile` w Protokole, przeniesienie
`COST_PER_QUERY_USD`/`SECONDS_PER_QUERY` z `estimate.py` na providera.
*Najbardziej ryzykowna produktowo.* Jeśli jakość compound jest istotnie gorsza od sonar, decyzja 9
wymaga rewizji — lepiej wiedzieć teraz.

**Faza 2 — port na Postgres** (jednoużytkownikowo, `user_id` = stały UUID dev) · ~11 zadań
Najpierw **`backend/tests/conftest.py`, którego dziś nie ma**: dedup `_make_app` z trzech
identycznych kopii i zastąpienie 22 bezpośrednich konstrukcji `ScanStore`/`PriceCache` fixture'ami —
wciąż na SQLite, żeby było bisektowalne. Potem: projekt Supabase, `0001_init.sql`, psycopg +
`pydantic-settings`, pula w `lifespan`, przepisane wnętrza obu store'ów, skasowane locki,
`ON CONFLICT` z pełnym zerowaniem, `COPY`, usunięcie `offer_raw_response`, sweeper retencji,
archiwizacja 387 MB.
*Najbardziej ryzykowna inżyniersko.* 253 testy przenoszą się na prawdziwą bazę naraz; różnica
`ON CONFLICT` jest cicha i nieobjęta żadnym testem; konwersje pieniędzy dotykają każdej ścieżki
odczytu; **`create_scan` wstawia produkty po jednym w pętli Pythona** (`store.py:129-152`) — po
sieci do Supabase to 72 747 round-tripów, czyli dziesiątki minut w żądaniu, na które czeka
użytkownik. `COPY` jest **obowiązkową częścią portu, nie optymalizacją**. Faza bez częściowego
odwrotu: store'a nie da się sportować w połowie.
*Bramka:* zielony przebieg na lokalnym kontenerze **przed** dotknięciem wnętrz; regresja na negatywny
re-cache napisana pierwsza; jeden realny `create_scan` na 72 747 wierszach z pomiarem zegarowym.

**Faza 3 — auth, connections, Vault, RLS** · ~11 zadań
`0002_auth.sql`, `app/secrets/vault.py`, `app/auth/deps.py`, fasada `for_user()`, 7 tras objętych
autoryzacją, CORS. Frontend: supabase-js, `src/config.ts`, router, `authedFetch`, obejście SSE,
slot konta w `AppShell`, `/settings/connections`, onboarding prowadzący po darmowy klucz Groq,
rejestracja na zaproszenie. **`connections` implementuje wyłącznie `kind='ai_provider'`** —
Woo/Shopify zostają w kodzie źródeł jako dowód rozszerzalności `CatalogSource`, ale bez UI i bez
zapisu poświadczeń; web dostaje tylko wzmiankę, że powstaną aplikacje per platforma.

**Faza 4 — BYOK i tryb demo** · ~9 zadań
Fabryka providera, księga `provider_usage` (RPM/RPD per connection, trwała — RPD musi przeżyć
restart), estymata pokazująca liczbę żądań, pozostały budżet dnia i **„ten skan zajmie N dni"**,
weryfikacja połączenia. Tryb demo: 3 sztywne próbki po stronie serwera, trasa `/demo` bez
logowania, budżet dzienny operatora + cap per IP, rozgrzewanie cache'u po deployu, fallback na
ostatni raport po wyczerpaniu budżetu.

**Faza 5 — trwałość, deploy i upublicznienie** · ~7 zadań
Atomowe przejęcie skanu w bazie zamiast `_scans_in_flight` (`api.py:51` — per-proces, dziś
niepoprawne przy >1 workerze), heartbeat, resumer w `lifespan`, scheduler dla `paused`,
**jednokrotny upload CSV** zamiast sześciokrotnego + cap na rozmiar, Dockerfile + `fly.toml`
(region `waw`/`fra`, `min_machines_running=1`; **1 GB RAM, nie 512 MB** — `POST /scans` trzyma cały
upload i 72 747 dataclass w pamięci; ~$2–4/mies.), projekt Vercel, **pierwszy w historii projektu**
`.github/workflows/ci.yml`, oraz **checklist upublicznienia repo** z sekcji „Publikacja na GitHubie".

## Pliki krytyczne

- [backend/app/scans/api.py](backend/app/scans/api.py) — singletony (61-82), `DEFAULT_DB_PATH` (39),
  `_scans_in_flight` (51), zaszyty `"default"` (309, 400), interwał SSE (57), 6 nieuwierzytelnionych tras
- [backend/app/scans/store.py](backend/app/scans/store.py) — przepisanie schematu, pętla insertów
  (129-152) → `COPY`, `threading.Lock`, fasada `for_user()`
- [backend/app/cache/sqlite_cache.py](backend/app/cache/sqlite_cache.py) — `ON CONFLICT` (113, 121),
  `lookup_key`, usunięcie `raw_response`
- [backend/app/providers/base.py](backend/app/providers/base.py) + [perplexity.py](backend/app/providers/perplexity.py)
  — Protokół, `ProviderProfile`, wyciągnięcie `_parse_response` (95-152)
- [frontend/src/api/client.ts](frontend/src/api/client.ts) + [useScanEvents.ts](frontend/src/api/useScanEvents.ts)
  — 6 ścieżek względnych → `API_BASE` + bearer; `EventSource` bez nagłówka auth

## Weryfikacja

- **Faza 0:** realne odpowiedzi Groq obok odpowiedzi Perplexity na tych samych produktach — ocena
  ręczna, plus jednoznaczna odpowiedź, czy `json_schema` + search działają w jednym żądaniu.
- **Każda faza:** `cd backend && .venv/bin/pytest` (dziś 253 przechodzi, 4 skip) oraz
  `cd frontend && npm test && npm run build && npm run lint`. `npm run build` nie jest opcjonalne —
  repo ma udokumentowaną klasę błędów, którą łapie wyłącznie `tsc -b`.
- **Faza 2 dodatkowo:** jeden `create_scan` na realnym pliku 72 747 wierszy przeciwko chmurowej bazie,
  z pomiarem czasu; `mcp__claude_ai_Supabase__get_advisors` czysty (security + performance).
- **Faza 3 dodatkowo:** próba odczytu cudzego skanu kończy się `404`; `get_advisors` nie zgłasza
  tabeli bez RLS.
- **Faza 4 dodatkowo:** próba wywołania demo z własnym CSV odrzucona; cap per IP działa; po
  wyczerpaniu budżetu demo nadal pokazuje raport.
- **Faza 5 dodatkowo:** `/security-review` na całości **przed** przełączeniem repo na publiczne,
  plus ponowny skan historii pod kątem sekretów.
- **Przed każdym mergem fazy:** przegląd całej gałęzi (wymóg `CLAUDE.md` tego repo — każdy błąd,
  który tu miał znaczenie, złapał whole-branch review, żaden nie `npm test`). Uwaga dla niego:
  zweryfikowane non-finding *„`asyncio.to_thread(create_scan, ...)` nie wprowadza błędu
  wielowątkowości SQLite"* **staje się nieaktualne z chwilą wejścia Postgresa** — jedno połączenie
  pod lockiem zmienia się w pulę.

## Gdzie stałe decyzje zabolą

1. **„Wszystko w chmurze" (4) kontra testy lokalne (7).** Dosłowne czytanie pkt. 4 daje 20–60 ms RTT
   na każde zapytanie pętli deweloperskiej i uniemożliwia pracę offline. *Założenie przyjęte:*
   kontener `supabase start`, i tak wymagany przez pkt. 7, obsługuje **całą** wewnętrzną pętlę dev;
   baza chmurowa służy weryfikacji integracyjnej. Bez tego Faza 2 jest udręką.
2. **Vault (2) daje mniej, niż się wydaje.** Skoro tylko rola serwisowa czyta
   `vault.decrypted_secrets`, backend musi trzymać klucz serwisowy — jeden przejęty kontener
   odsłania wszystkie cudze klucze, dokładnie jak ostrzega dokumentacja Supabase. Vault kupuje
   szyfrowanie w spoczynku, nie kompartmentalizację. Rejestracja na zaproszenie (1) mocno ogranicza
   skutki, bo „cudze klucze" to garstka zaproszonych osób.
3. **Klucz operatora w trybie demo (12) łamie czystą regułę „BYOK obowiązkowy".** To świadomy
   wyjątek na rzecz demo. Cały jego ciężar spoczywa na tym, że próbki są sztywne po stronie serwera —
   gdyby demo kiedykolwiek przyjęło wejście od użytkownika, staje się darmową bramką do Twojego
   klucza. To musi być komentarzem w kodzie, nie tylko zdaniem w planie.
4. **Free tier Supabase to pas startowy.** Ściana przy 10–15 kontach z pełnym skanem. Przy
   zaproszeniach to nie problem na długo, ale płatny tier jest na mapie drogowej niezależnie.

## Ścieżka wykonania

Po zatwierdzeniu: Faza 0 (spike) → zapis specyfikacji, potem plan wykonawczy per faza, osobny
worktree na fazę i przegląd całej gałęzi przed każdym mergem.
