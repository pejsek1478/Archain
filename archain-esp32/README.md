# Archain Field Diary – port pro Arduino Nano ESP32

Port Flask aplikace (Flask + SQLite + Jinja) na ESP32-S3: vestavěný `WebServer`, data v JSON souborech na LittleFS (nebo SD kartě).
Deska si vytvoří vlastní Wi-Fi, telefony se připojí na `http://192.168.4.1` (nebo `http://archain.local`).

## Co je v balíčku
- `archain-esp32.ino` – celá aplikace
- `styles_css.h` – původní `styles.css` zabalené do flash paměti (vygenerováno, vzhled zůstal stejný)

## Sestavení
1. Arduino IDE → Board Manager → **Arduino ESP32 Boards** → deska **Arduino Nano ESP32**.
2. Library Manager → **ArduinoJson 7.x** (jediná externí knihovna).
3. Tools → **Partition Scheme**: stačí cokoliv s datovou částí. Sketch zkusí nejdřív LittleFS (partition SPIFFS) a když není, použije FFat (partition FATFS); výsledek vypíše na Serial monitoru spolu se seznamem partition. Jen když není žádná, web vrátí vysvětlující hlášku.
4. Nahraj. Na Serial monitoru (115200) uvidíš start, úložiště, stav Wi-Fi (včetně důvodu, proč se nepřipojila), adresy a každých 10 s stavový řádek, plus log požadavků a přihlášení. První otevření → `/setup` → vytvoř owner účet.

## Nastavení (začátek `.ino`)
| Položka | Význam |
|---|---|
| `AP_SSID` / `AP_PASS` | vlastní Wi-Fi desky (heslo min. 8 znaků) |
| `STA_SSID` / `STA_PASS` | volitelně se deska připojí i k tvé Wi-Fi → funguje auto-počasí (wttr.in) a NTP čas |
| `USE_SD`, `SD_CS_PIN` | `1` = ukládat na SD kartu přes SPI (víc místa na fotky/3D modely) |
| `MAX_UPLOAD`, `MIN_FREE` | limit jednoho souboru a rezerva volného místa |

## Co se změnilo oproti originálu
- **Úložiště**: SQLite → JSON soubory (`/archain/users.json`, `people.json`, `e/<id>.json`, `up/…`). Stará `diary.db` se automaticky nepřenáší.
- **Hesla**: místo werkzeugu solený, 5000× iterovaný SHA-256 (mbedtls). Relace jsou v RAM (po restartu desky se uživatelé přihlásí znovu).
- **Fotky** se v prohlížeči před nahráním zmenší na 1600 px (šetří flash a čas); soubory nahrané k záznamu mají stále limit 8 souborů × 8 MB.
- **Offline provoz**: mapa (Leaflet), 3D náhled (model-viewer) a mapové tiles se načítají z CDN, takže fungují jen na zařízení s internetem. Mapa má vždy seznam souřadnic s odkazem na OpenStreetMap; Google Maps iframe jsem nahradil odkazem.
- Drobné opravy proti originálu: unikátní jména uživatelů, nelze odebrat posledního admina, smazání uživatele převede jeho záznamy na mazajícího admina (originál tu padal na DB chybě), profil ukazuje jen záznamy, které smí prohlížející vidět, mapa ukazuje i vlastní záznamy, nahrané soubory se servírují s bezpečným typem (HTML/SVG jen jako download), při smazání záznamu se mažou i jeho soubory.

## Omezení, o kterých je dobré vědět
- **GPS tlačítko** vyžaduje „secure context“ – na `http://192.168.4.1` ho Chrome/Safari zablokují (stejně jako u originálu přes LAN). Možnosti: zadat souřadnice ručně, na Androidu Chrome povolit adresu v `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, nebo přidat HTTPS server s vlastním certifikátem.
- `WebServer` obsluhuje **jeden požadavek najednou** – stránka s mnoha fotkami se načítá postupně. Počítej s jednotkami uživatelů.
- Formulář má limit 32 polí (`WEBSERVER_MAX_POST_ARGS`), tj. dohromady cca 20 vybraných členů týmu a nálezců.
- Hledání ignoruje velikost písmen jen u ASCII (např. „Č“ vs. „č“ se neshodují).
- Nahrané přílohy nejdou odebrat z existujícího záznamu (stejně jako v originále), jen smazat celý záznam.
- Žádná ochrana proti CSRF a žádné HTTPS (jako originál) – nevystavuj desku do internetu.
- Auto-počasí blokuje server až ~4 s, pokud wttr.in neodpovídá.
