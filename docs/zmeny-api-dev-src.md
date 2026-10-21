# Změny API ve větvi dev-3.1

Evok · větev `dev-3.1` proti `main` (`b2e241c`)

Přehled změn, které ovlivní klienty REST, JSON, Bulk, WebSocket, RPC a webhooku, konfiguraci a HW definice.
Nekompatibilní změny jsou uvedené jako první. U každé změny je commit
(`https://github.com/UnipiTechnology/evok/commit/<hash>`).

## Před vydáním ověřit na zařízení

- **Uzly Unipi pro Node-RED:** jakou hlavičku `Origin` posílají na WebSocket. Pokud posílají svou vlastní adresu,
  Evok je odmítne s 403 a je potřeba ji přidat do `allowed_origins`.
- **Konfigurace nginx v balíčku:** pro WebSocket musí předávat původního hostitele (`proxy_set_header Host $host`,
  `$host:$server_port` z evok-web funguje od `b1415ef`), jinak webové rozhraní přes nginx nedostane WebSocket.
  Ověřeno s evok-web 3.18 na Patronu.
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
- **1-Wire čidla z konfigurace:** žádná událost `lost: true` hned po startu nebo po restartu sběrnice, čidlo
  se čte až po nalezení na sběrnici. Čidlo, které hledání na sběrnici nenašlo, se hlásí jako ztracené. — `5fa3eca`
- **RO, DO, LED:** bez `pulse_duration`, `timeout` (DO) a `pending`, pulz se nastavuje přes sequencer výstupu
  (`/rest/sequencer/<typ>_<okruh>`, `running` místo `pending`). Během něj se změna výstupu kromě aliasu odmítne
  s 409 (RPC `-32002`), nejdřív ho zrušte přes sequencer. RPC metody `*_set_for_time` a `output_get` zůstávají.
  — `a85fb14`, `57492fe`
- **Reset a nv_save jednotky:** coil se zapíše jednou bez retries, chybějící odpověď není chyba, Evok počká
  na restart jednotky; dřív se timeout opakoval (reset se poslal dvakrát) a vrátil 503. `value` u `nv_save` zůstane
  2 s na 1, další uložení se mezitím odmítne. — `0ab8d2c`, `752616a`

### Okruhy podle HW definic

- Relé 17–28 na M403/L403 mají okruhy `1_17`…`1_28`, dřív přepsala relé 1–12. — `50da3b3`
- Vstupy a výstupy 17–32 jedné feature čtou další registr. — `b71adde`, `50da3b3`
- Datové body s `count > 1` a 32bitovým typem jdou po dvou registrech, takže mají jiné okruhy. — `50da3b3`

### REST a JSON

- Chybové stavy: 404 neznámé zařízení, 400 neplatná data, 401 chybějící nebo neplatný token, 403 změna s tokenem
  jen pro čtení, 503 nedostupná jednotka, 500 interní chyba. — `4b36483`, `a3f4679`, `9f9482c`
- `POST /rest/all` vrací 405, POST s jinou částí URL než `/alias` vrací 404. — `3c8f58e`, `34bdcd2`
- Alias `all` je rezervovaný, alias má nejvýš 64 znaků. — `34bdcd2`, `3bae093`
- `/rest/*` čte i JSON objekt (`Content-Type: application/json` nebo tělo začínající `{`) a kontroluje jeho
  parametry; dřív se JSON tělo ignorovalo a POST vrátil 200 beze změny. JSON tělo, které není objekt, se na
  `/rest/*` i `/json/*` odmítne s 400, dřív 500. — `23831b4`

### Bulk

- Změny se provádějí po Modbus jednotkách, ne v pořadí požadavku. Při chybě vrátí výsledky hotových jednotek a změn
  chybné jednotky před chybou. — `a3f4679`
- Filtr `global_device_id` byl odstraněn. — `6cd0802`
- `device_circuits` přijímá i aliasy, alternativní názvy v `device_types` (např. `di` a `input`) se sloučí, dřív
  se zařízení vrátila dvakrát. — `854054f`

### WebSocket

- Jen příkazy `all`, `filter`, `full`, `set`. Dřív šlo volat libovolnou metodu zařízení. — `8e72731`
- Události jsou vždy seznam. Pomalý klient dostává sloučené změny, takže může minout krátký pulz. — `7f827fa`, `053da5d`

### RPC

- `ao_set` bere `mode` místo frekvence, metody `ai_set*` byly odstraněny. — `af3982c`
- Chybové kódy: neplatné parametry `-32602`, nedostupná jednotka `-32000`, změna s tokenem jen pro čtení `-32001`,
  interní chyba `-32603` bez textu výjimky. — `cb94d9f`, `c8a92a4`, `4003436`

### Ostatní

- **Sběrnice OWFS:** `hostname` / `port` owserveru jsou chyba konfigurace, sběrnice se nevytvoří, použijte `master`
  (viz Konfigurace). Jeden master obsluhuje jednu sběrnici OWFS, druhá sběrnice se stejným masterem se nevytvoří.
  — `776b371`, `dc7b1ee`

- `print_log` u `modbus_slave` byl nahrazen `GET /log`. — `54fe858`

## Nové funkce

- **Komunikace zařízení:** stav každého zařízení Modbus jednotky a 1-Wire čidla obsahuje `comm` (`ok`, `timeout`,
  `error`; 1-Wire čidlo jen `ok`, `timeout`) a `last_comm` (sekundy od poslední úspěšné komunikace); ztráta
  a obnovení jednotky pošle stavy všech jejích zařízení, `value` je poslední známá. Entity Home Assistantu jsou bez komunikace nedostupné. — `969798e`
- **Zabezpečení:** volitelný `token` pro všechna API (Bearer, Basic, `?token=` u WebSocketu) a `allowed_origins`.
  — `763016c`, `2b7f668`
- **Klient za proxy:** `trusted_downstream` v `apis`, adresy reverzních proxy (např. nginx evok-web), jejichž
  `X-Forwarded-For` / `X-Real-IP` určují adresu klienta v logu Evoku.
- **Token jen pro čtení:** volitelný `read_token` (vyžaduje `token`). Povolí čtení REST a JSON, dotazy bulk, `all`,
  `full`, `filter` a události WebSocketu, metody RPC pro čtení a `/log`. Změna zařízení vrátí 403 `ReadOnlyAccess`,
  v RPC `-32001`; bulk se změnou se odmítne celý. — `4003436`
- `GET /log?lines=N` vrací konec logu. — `54fe858`
- `POST /modbus_slave/{circuit}` se `scan_enabled` a aliasem. `full()` vrací `scan_enabled` a `scan_error`.
  — `2319b2b`, `96ba320`, `d1add77`
- Datové body jde zapisovat přes `writable`, `full()` ho vrací. — `eb4eda5`, `e792e17`
- **Sequencer** každého výstupu (RO, DO, LED), zařízení `sequencer` s okruhem `<typ>_<okruh>`
  (`/rest/sequencer/do_1_01`): pulz (`value`, `pulse_duration`), sekvence změn výstupu (`steps`, `final`) nebo
  `cancel`; stav obsahuje `running` a průběh, událost při startu, krocích a konci. RPC metoda `relay_set_for_time`.
  — `e16a3bf`, `7789635`, `a85fb14`
- Odpověď na POST, bulk i WebSocket `set` obsahuje stav po zápisu a událost přijde hned. — `a3f4679`
- **Nové události:** — `60e2287`, `08d9f56`, `62b37ef`, `891bd4a`
  - změna aliasu zařízení na Modbus jednotce,
  - ztráta a obnovení komunikace s jednotkou,
  - změna `counter_mode`, režimu a debounce DI,
  - změna frekvence PWM, u všech DO, které ji sdílejí,
  - změna napájení 1-Wire (`owpower`, hodnota 1 je sběrnice bez napájení).
- Úspěšná odpověď bulk obsahuje `"success": true`. — `ba4212f`
- `scan_error` u `modbus_slave` a chyby nedostupné jednotky uvádějí původní příčinu, např. chybějící sériový port.
  — `d990fe1`
- Smazání aliasu nepřipojeného zařízení přes `POST /rest/run/alias` s `delete`. — `b7cebd6`
- `GET /rest/serial_bus/{bus}` a `/rest/tcp_bus/{bus}` vrací konfiguraci Modbus sběrnice a její zařízení, dřív chybu
  500. Sběrnice jsou jen pro čtení a nejsou v `/rest/all`. — `b40a57c`
- **MQTT API:** stavy zařízení se publikují na broker (retained), příkazy přichází přes
  `<prefix>/<device>/<circuit>/set`, stav `online` / `offline` s poslední vůlí. — `c8ff385`
- **Home Assistant:** `ha_discovery` MQTT API ohlásí zařízení přes MQTT discovery. — `0538f51`
- **Konfigurace:** `apis.rpc.enabled`, webhook `min_interval`, u sběrnic `timeout`, `connect_timeout` a `retries`.
  — `f7ebda1`, `0044241`, `16463d5`, `a6ede44`
- **Výstupy bez coilů:** RO, DO a LED bez `val_coil` zapisují svůj bit ve `val_reg` (holding registr), např. u jednotky
  bez coilů. DO bez PWM registrů je jednoduchý výstup, `modes` je nepovinné. — `05ad76c`
- **Sériové porty jednotky:** `serial_ports` u Modbus zařízení je seznam sériových portů, které obsluhuje, např. lokální
  jednotka 1 Patronu M527 s `/dev/ttyNS0`. Jejich sběrnice `MODBUSRTU` stojí během resetu a NV save jednotky a 0,5 s po něm,
  požadavek na portu poškodí zápis do její flash (chyba firmware). Parametr zařízení sběrnice `MODBUSTCP`; reset a NV save
  jiným Modbus masterem jednotky se nepokrývají. `evok-autogen.py` ho nastaví deskám BRAIN, E4AI4AO4DI5RO,
  E4AI4AO6DI5RO a E8AI4DI5RO, `ttyNS0`, `ttyNS1`... podle jejich pořadí.

## Zastaralé

- `time` 1-Wire čidla, čas smyčky událostí při čtení; nahrazuje ho `last_comm`. — `969798e`
- `counter_mode` a `counter_modes` u DI. `Disabled` jen hlásí čítač 0, režim se neukládá. — `a5d8065`
- Parametr `timeout` RPC metody `output_set_for_time` je alias `pulse_duration`. — `e16a3bf`
- `nv_sav_coil` ve WD feature se nepoužívá, ukládání řeší feature NV_SAVE. — `f298e87`
- `frequency` u registrového bloku je alias `scan_divider`, zaloguje se varování, obojí v jednom bloku je chyba.
  Hodnota je dělitel skenů, ne frekvence. — `d95f57a`
- Feature REGISTER v HW definicích, zaloguje se varování. Nahrazuje ho DATA_POINT s `datatype: uint16`, jeho
  zařízení jsou `data_point` místo `register`, okruh input registru je bez `_inp`. — `fec507a`, `97ca903`

## Konfigurace a HW definice

Neplatná hodnota je chyba: jednotka nebo feature se nevytvoří a chyba se zaloguje.

- **Tokeny:** `token` a `read_token` musí být neprázdné řetězce, `read_token` vyžaduje `token` a musí se od něj lišit;
  `allowed_origins` je seznam originů http/https. Jinak Evok nenastartuje. — `763016c`, `2b7f668`, `4003436`
- **Jednotka:** `scan_frequency` > 0, `scan_enabled` jen `true`/`false`, `slave-id` 1–247 na RTU a 0–255 na TCP.
  — `d1add77`, `96ba320`
- **Registrové bloky:** nejvýš 125 registrů, adresy do 65535, bez překryvů. — `2f323f0`, `9f9482c`
- **Modbus zařízení:** jméno musí být jedinečné přes všechny sběrnice. Druhé zařízení se stejným jménem se
  nevytvoří, dřív v API nahradilo první a chyběly jeho IO. — `d8acc38`
- **Jednotka, která neodpovídá:** zkouší se jedním požadavkem s `probe_timeout` sběrnice (0,1 s na RTU) bez retries,
  dřív každý pokus blokoval sběrnici na `(retries + 1) * timeout` (výchozí 1 s) a ostatní jednotky čekaly. — `30cb46f`
- **Priorita změn na sběrnici:** zápisy změny a čtení po nich jdou před scany sběrnice, změna nečeká na běžící scan
  své jednotky, jen na právě odesílaný požadavek. Scan jednotky čeká, dokud změna neskončí, nečte jednotku mezi jejími
  zápisy; ostatní jednotky zatím sběrnici používají. Po každé změně jde nejdřív čekající scan jednotky a jiné
  jednotky, proud změn scany nezastaví. Změna čekala na scany všech jednotek vytížené sběrnice, např. asi
  30 požadavků při 6 jednotkách, teď asi 5. — #267
- **Čtení po změně:** jen bloky registrů čtené každým scanem (`scan_divider: 1`), bloky stavů měněných zařízení
  a zapsaných registrů, ostatní bloky přečte periodický scan. Změna četla všechny bloky, např. LED na xS51 zápis
  a 6 čtení, teď zápis a 2 čtení (rychlý blok, blok LED). Reset jednotky nebo NV save čte všechny bloky,
  změna bez takového bloku čte první blok jednotky, zjistí, jestli odpovídá. — #267
- **Modbus adresy:** sériový port může používat jen jedna sběrnice `MODBUSRTU`, `slave-id` musí být jedinečné na RTU
  sběrnici a na TCP serveru (`hostname`, `port`) přes všechny sběrnice `MODBUSTCP`. Druhá sběrnice nebo zařízení se
  nevytvoří, dřív obě četla a zapisovala stejnou jednotku. — `dc7b1ee`
- **Okruhy:** duplicitní okruh je chyba feature, `start_index` platí i pro RO, DO a LED. — `50da3b3`
- **Režimy:** `value` režimu musí být jedinečné celé číslo, datový typ v `transformation` AI musí být známý.
  — `e005aa4`, `a053e80`
- **Datové body:** zapisovatelný datový bod v input registru je chyba. — `e792e17`
- **Watchdog:** jeden na jednotku, `count` se nepoužívá. — `6ac4eb0`
- **1-Wire:** typ `DS2404` není podporovaný, nemá PIO a byl vždy ztracený. `address` čidla se najde i bez CRC,
  teček nebo malými písmeny. `scan_interval: 0` prohledá sběrnici jen po připojení a na vyžádání, dřív jednou
  za hodinu; změněný `scan_interval` platí hned. — `4ecdf2f`
- **Sběrnice OWFS:** jméno 1-Wire čidla musí být jedinečné přes všechny sběrnice OWFS, duplicitní čidlo z konfigurace
  se nevytvoří, nalezené se přeskočí; dřív druhé čidlo v API nahradilo první. — `fa35a94`
- **Sběrnice OWFS přes jádro:** čidla čte 1-Wire subsystém jádra (`/sys/bus/w1`), owserver ani asyncowfs se
  nepoužívají. Volba `master` (`w1_bus_master1`, výchozí je první) místo `hostname` / `port`, stav sběrnice
  obsahuje `master`. Adresa a okruh nalezeného čidla se nemění. `value` DS2406 je stav jeho klopných obvodů
  kanálů. S udev pravidlem `etc/udev/rules.d/60-evok-w1.rules` `do_scan` vynutí hledání a teploměry převádí
  najednou. — `776b371`, `2bb5167`

## Běh a instalace

- Python 3.12, `tmodbus` místo `pymodbus`. — `862d760`, `733871c`
- `tornado` 6.5.10 místo 6.3.3. — `1210fb1`
- Každý modul loguje vlastním loggerem, např. `evok.modbus.client` nebo `evok.w1.bus`, úroveň jedné části jde
  nastavit zvlášť; úroveň a soubor logu zůstávají na loggeru `evok`. — `48ab81e`
- 1-Wire přes jádro: ovladač masteru (např. `ds2482`) a moduly čidel místo balíčku `owserver`; bez závislostí
  `asyncowfs` a `anyio`. Balíček by měl instalovat udev pravidlo `etc/udev/rules.d/60-evok-w1.rules` (skupina
  `evok`). — `776b371`, `9790404`, `2bb5167`
- Volby `--config-dir` a `--alias-file` (proměnné `EVOK_CONFIG_DIR`, `EVOK_ALIAS_FILE`). Bez `config.yaml` Evok
  skončí chybou. — `af85489`
- OpenAPI dokument `Evok_API_OAS.yaml` se generuje ze schémat ve zdrojácích (`python -m evok.openapi`) a přikládá
  se ke každému GitHub release, v repozitáři není. — `9c2d987`, `8ccf4d5`

---

Sestaveno ze zpráv commitů mezi `main` a `dev-3.1` a ze změn dokumentace API. Kód na `main`
nebyl porovnáván řádek po řádku, drobnosti, které zprávy commitů nepopisují, mohou chybět.
