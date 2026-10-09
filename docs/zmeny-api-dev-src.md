# Změny API ve větvi dev-src

Evok · větev `dev-src` proti `main` (`b2e241c`) · do `4003436` · 135 commitů

Přehled změn, které ovlivní klienty REST, JSON, Bulk, WebSocket, RPC a webhooku, konfiguraci a HW definice.
Nekompatibilní změny jsou uvedené jako první. U každé změny je commit
(`https://github.com/UnipiTechnology/evok/commit/<hash>`).

## Před vydáním ověřit na zařízení

- **Uzly Unipi pro Node-RED:** jakou hlavičku `Origin` posílají na WebSocket. Pokud posílají svou vlastní adresu,
  Evok je odmítne s 403 a je potřeba ji přidat do `allowed_origins`.
- **Konfigurace nginx v balíčku:** pro WebSocket musí předávat původního hostitele (`proxy_set_header Host $host`),
  jinak webové rozhraní přes nginx nedostane WebSocket.
- **Firmware a sken po změně:** pokud firmware promítne zápis do registrů se zpožděním, vrátí odpověď na změnu
  ještě starý stav a opraví ho až další sken.

## Nekompatibilní změny

### Přístup k API

- Výchozí adresa API je `127.0.0.1`, dřív všechna rozhraní. Prázdná `address` poslouchá dál na všech. — `5b81429`
- CORS se posílá jen originům z `allowed_origins`, dřív `*` pro všechny. WebSocket z prohlížeče z cizího originu
  dostane 403. — `2b7f668`
- Tělo požadavku je omezené na 1 MB, zpráva WebSocket klienta na 64 kB. — `ba4212f`, `053da5d`

### Zařízení a jejich stav

- **Watchdog:** — `6ac4eb0`, `f298e87`, `fce8d1d`
  - okruh je jméno jednotky (`1`) místo `1_01`, uložené aliasy watchdogů se nenavážou,
  - `nv_save` vrací chybu a zmizel z `full()`,
  - `value` je 0/1 místo 0–3, restart hlásí jen `was_wd_reset`.
- **AI a AO:** `modes` obsahuje jen `unit` a `range`, bez kódu registru a `transformation`. — `e792e17`
- **OwPower:** `value` je vždy 0/1, dřív po zápisu `true`/`false`. — `2042b3d`
- **DI:** `ds_mode` mimo režim `DirectSwitch` vrací chybu, dřív se tiše ignoroval. — `96f66c6`
- **PWM:** hardwarové PWM odmítne frekvenci nad 50 kHz. Jiné dělení frekvence: jiné hodnoty registrů, přesnější
  frekvence a jemnější střída. — `a05718c`
- **Neplatné hodnoty se odmítají** místo tichého zpracování: NaN a nekonečno, hodnota výstupu `'2'`, AO mimo rozsah
  (dřív se ořízla), neznámý režim DI. — `1a6910c`, `891bd4a`, `5f15f41`
- NaN a nekonečné hodnoty AI a datových bodů se vrací jako řetězce `'NaN'`, `'Infinity'`, `'-Infinity'`. — `5f15f41`
- `last_comm` jednotky je `null` před první komunikací, dřív asi 1,7e9 s. — `2f323f0`

### Okruhy podle HW definic

- Relé 17–28 na M403/L403 mají okruhy `1_17`…`1_28`, dřív přepsala relé 1–12. — `50da3b3`
- Vstupy a výstupy 17–32 jedné feature čtou další registr. — `b71adde`, `50da3b3`
- Datové body s `count > 1` a 32bitovým typem jdou po dvou registrech, takže mají jiné okruhy. — `50da3b3`

### REST a JSON

- Chybové stavy: 404 neznámé zařízení, 400 neplatná data, 401 chybějící nebo neplatný token, 403 změna s tokenem
  jen pro čtení, 503 nedostupná jednotka, 500 interní chyba. — `4b36483`, `a3f4679`, `9f9482c`
- `POST /rest/all` vrací 405, POST s jinou částí URL než `/alias` vrací 404. — `3c8f58e`, `34bdcd2`
- Alias `all` je rezervovaný, alias má nejvýš 64 znaků. — `34bdcd2`, `3bae093`

### Bulk

- Změny se provádějí po Modbus jednotkách, ne v pořadí požadavku. Při chybě vrátí výsledky hotových jednotek a změn
  chybné jednotky před chybou. — `a3f4679`
- Filtr `global_device_id` byl odstraněn. — `6cd0802`

### WebSocket

- Jen příkazy `all`, `filter`, `full`, `set`. Dřív šlo volat libovolnou metodu zařízení. — `8e72731`
- Události jsou vždy seznam. Pomalý klient dostává sloučené změny, takže může minout krátký pulz. — `7f827fa`, `053da5d`

### RPC

- `ao_set` bere `mode` místo frekvence, metody `ai_set*` byly odstraněny. — `af3982c`
- Chybové kódy: neplatné parametry `-32602`, nedostupná jednotka `-32000`, změna s tokenem jen pro čtení `-32001`,
  interní chyba `-32603` bez textu výjimky. — `cb94d9f`, `c8a92a4`

### Ostatní

- `print_log` u `modbus_slave` byl nahrazen `GET /log`. — `54fe858`

## Nové funkce

- **Zabezpečení:** volitelný `token` pro všechna API (Bearer, Basic, `?token=` u WebSocketu) a `allowed_origins`.
  — `763016c`, `2b7f668`
- **Token jen pro čtení:** volitelný `read_token` (vyžaduje `token`). Povolí čtení REST a JSON, dotazy bulk, `all`,
  `full`, `filter` a události WebSocketu, metody RPC pro čtení a `/log`. Změna zařízení vrátí 403 `ReadOnlyAccess`,
  v RPC `-32001`; bulk se změnou se odmítne celý. — `4003436`
- `GET /log?lines=N` vrací konec logu. — `54fe858`
- `POST /modbus_slave/{circuit}` se `scan_enabled` a aliasem. `full()` vrací `scan_enabled` a `scan_error`.
  — `2319b2b`, `96ba320`, `d1add77`
- Datové body jde zapisovat přes `writable`, `full()` ho vrací. — `eb4eda5`, `e792e17`
- `pulse_duration` a `pending` i u RO a LED, RPC metoda `relay_set_for_time`. — `e16a3bf`
- Odpověď na POST, bulk i WebSocket `set` obsahuje stav po zápisu a událost přijde hned. — `a3f4679`
- **Nové události:** — `60e2287`, `08d9f56`, `62b37ef`, `891bd4a`
  - změna aliasu zařízení na Modbus jednotce,
  - ztráta a obnovení komunikace s jednotkou,
  - změna `counter_mode`, režimu a debounce DI.
- Úspěšná odpověď bulk obsahuje `"success": true`. — `ba4212f`
- Smazání aliasu nepřipojeného zařízení přes `POST /rest/run/alias` s `delete`. — `b7cebd6`
- **Konfigurace:** `apis.rpc.enabled`, webhook `min_interval`, u sběrnic `timeout`, `connect_timeout` a `retries`.
  — `f7ebda1`, `0044241`, `16463d5`, `a6ede44`

## Zastaralé

- `counter_mode` a `counter_modes` u DI. `Disabled` jen hlásí čítač 0, režim se neukládá. — `a5d8065`
- `timeout` u DO je alias `pulse_duration`. — `e16a3bf`
- `nv_sav_coil` ve WD feature se nepoužívá, ukládání řeší feature NV_SAVE. — `f298e87`
- `frequency` u registrového bloku je alias `scan_divider`, zaloguje se varování, obojí v jednom bloku je chyba.
  Hodnota je dělitel skenů, ne frekvence. — `d95f57a`

## Konfigurace a HW definice

Neplatná hodnota je chyba: jednotka nebo feature se nevytvoří a chyba se zaloguje.

- **Tokeny:** `token` a `read_token` musí být neprázdné řetězce, `read_token` vyžaduje `token` a musí se od něj lišit;
  `allowed_origins` je seznam originů http/https. Jinak Evok nenastartuje. — `763016c`, `2b7f668`, `4003436`
- **Jednotka:** `scan_frequency` > 0, `scan_enabled` jen `true`/`false`, `slave-id` 1–247 na RTU a 0–255 na TCP.
  — `d1add77`, `96ba320`
- **Registrové bloky:** nejvýš 125 registrů, adresy do 65535, bez překryvů. — `2f323f0`, `9f9482c`
- **Okruhy:** duplicitní okruh je chyba feature, `start_index` platí i pro RO, DO a LED. — `50da3b3`
- **Režimy:** `value` režimu musí být jedinečné celé číslo, datový typ v `transformation` AI musí být známý.
  — `e005aa4`, `a053e80`
- **Datové body:** zapisovatelný datový bod v input registru je chyba. — `e792e17`
- **Watchdog:** jeden na jednotku, `count` se nepoužívá. — `6ac4eb0`

## Běh a instalace

- Python 3.12, `tmodbus` místo `pymodbus`. — `862d760`, `733871c`
- Volby `--config-dir` a `--alias-file` (proměnné `EVOK_CONFIG_DIR`, `EVOK_ALIAS_FILE`). Bez `config.yaml` Evok
  skončí chybou. — `af85489`

---

Sestaveno ze zpráv 135 commitů mezi `main` a `dev-src` (po `4003436`) a ze změn dokumentace API. Kód na `main`
nebyl porovnáván řádek po řádku, drobnosti, které zprávy commitů nepopisují, mohou chybět.
