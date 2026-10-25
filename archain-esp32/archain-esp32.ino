// Archain Field Diary - port for Arduino Nano ESP32 (ESP32-S3)
//
// Flask + SQLite + Jinja  ->  WebServer + LittleFS/SD + JSON files.
// Libraries: ArduinoJson 7.x (Library Manager). Everything else ships with the ESP32 core.
// This code was ported using Claude Sonnet 5.5

#include <WiFi.h>
#include <WebServer.h>
#include <uri/UriBraces.h>
#include <ESPmDNS.h>
#include <HTTPClient.h>
#include <FS.h>
#include <ArduinoJson.h>
#include <vector>
#include <algorithm>
#include <functional>
#include <time.h>
#include "mbedtls/md.h"
#include "esp_partition.h"
#include "styles_css.h"

// ============================== CONFIG ==============================
static const char *AP_SSID   = "Archain";        // the board's own Wi-Fi (field use, no internet)
static const char *AP_PASS   = "archain-field";  // min. 8 characters, "" = open network
static const char *STA_SSID  = "VASE_SSID";               // optional: also join your Wi-Fi (weather + NTP + maps)
static const char *STA_PASS  = "YOUR_PASSWD";
static const char *HOSTNAME  = "nano-web";        // http://archain.local
static const char *TZ_INFO   = "CET-1CEST,M3.5.0,M10.5.0/3";  // Central Europe
#define USE_SD        0                          // 1 = store everything on an SPI SD card
#define SD_CS_PIN     10                         // Nano ESP32: D10
static const size_t MAX_UPLOAD   = 8UL * 1024 * 1024;   // per file
static const size_t MIN_FREE     = 256UL * 1024;        // keep this much storage free
static const int    PW_ROUNDS    = 5000;
static const unsigned long SESS_TTL = 12UL * 3600UL * 1000UL;
// ====================================================================

#if USE_SD
  #include <SD.h>
  #include <SPI.h>
#else
  #include <LittleFS.h>   // used when the partition scheme has a SPIFFS partition
  #include <FFat.h>       // fallback when it only has a FATFS partition
#endif
fs::FS *gFs = nullptr;     // the active storage
const char *gFsName = "none";
size_t freeBytes() {
#if USE_SD
  return SD.totalBytes() - SD.usedBytes();
#else
  return gFs == &FFat ? FFat.freeBytes() : LittleFS.totalBytes() - LittleFS.usedBytes();
#endif
}
#define STORE (*gFs)

#define P_ROOT  "/archain"
#define P_E     "/archain/e"
#define P_UP    "/archain/up"
#define P_USERS "/archain/users.json"
#define P_PEOPLE "/archain/people.json"
#define P_META  "/archain/meta.json"

WebServer server(80);
JsonDocument gUsers;     // reloaded on every request

struct Me { bool ok = false; int id = 0; bool admin = false; String name; } me;
struct Sess { String tok; int uid = 0; String flash, cat; unsigned long seen = 0; };
static const int SESS_MAX = 8;
Sess sess[SESS_MAX];
Sess *cs = nullptr;
String nowMsg, nowCat;   // flash shown on the page being rendered right now

struct Pending { String stored, orig, mime, field; size_t size = 0; };
std::vector<Pending> pending;
Pending upCur; File upFile; String upPath, upErr; size_t upSize = 0; bool upActive = false;

// ============================== utils ==============================
String esc(const String &s) {
  String o; o.reserve(s.length() + 8);
  for (size_t i = 0; i < s.length(); i++) {
    char c = s[i];
    switch (c) {
      case '&': o += "&amp;"; break;
      case '<': o += "&lt;"; break;
      case '>': o += "&gt;"; break;
      case '"': o += "&quot;"; break;
      case '\'': o += "&#39;"; break;
      default: o += c;
    }
  }
  return o;
}
String utf8Cut(const String &s, size_t n) {
  if (s.length() <= n) return s;
  size_t k = n;
  while (k > 0 && (((uint8_t)s[k]) & 0xC0) == 0x80) k--;
  return s.substring(0, k);
}
String firstChar(const String &s) {
  if (!s.length()) return "?";
  size_t k = 1;
  while (k < s.length() && (((uint8_t)s[k]) & 0xC0) == 0x80) k++;
  String c = s.substring(0, k);
  if (k == 1) c.toUpperCase();
  return c;
}
String trimmed(String s) { s.trim(); return s; }
String randHex(int bytes) {
  String s;
  for (int i = 0; i < bytes; i++) { char b[3]; snprintf(b, 3, "%02x", (unsigned)(esp_random() & 0xff)); s += b; }
  return s;
}
String hashPw(const String &pw, const String &salt) {
  const mbedtls_md_info_t *info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  uint8_t h[32], buf[160];
  String base = salt + ":" + pw;
  size_t bl = base.length() > sizeof(buf) - 32 ? sizeof(buf) - 32 : base.length();
  memcpy(buf + 32, base.c_str(), bl);
  mbedtls_md(info, buf + 32, bl, h);
  for (int i = 0; i < PW_ROUNDS; i++) { memcpy(buf, h, 32); mbedtls_md(info, buf, 32 + bl, h); }
  String out;
  for (int i = 0; i < 32; i++) { char b[3]; snprintf(b, 3, "%02x", h[i]); out += b; }
  return out;
}
bool ctEq(const String &a, const String &b) {
  if (a.length() != b.length()) return false;
  uint8_t d = 0;
  for (size_t i = 0; i < a.length(); i++) d |= a[i] ^ b[i];
  return d == 0;
}
String nowStr() {   // "YYYY-MM-DDTHH:MM" or "" when the clock is not synced
  time_t t = time(nullptr);
  if (t < 1700000000) return "";
  struct tm tm; localtime_r(&t, &tm);
  char b[20]; strftime(b, sizeof b, "%Y-%m-%dT%H:%M", &tm);
  return String(b);
}
String fmtTime(const char *t) { String s = t ? t : ""; s.replace("T", " "); return s; }
bool validTime(const String &t) {
  return t.length() == 16 && t[4] == '-' && t[7] == '-' && t[10] == 'T' && t[13] == ':';
}
bool parseCoord(const String &raw, double lo, double hi, double &out) {
  String s = trimmed(raw); s.replace(",", ".");
  if (!s.length()) return false;
  char *end; double v = strtod(s.c_str(), &end);
  if (*end != 0 || v < lo || v > hi) return false;
  out = v; return true;
}
bool containsCI(String hay, const String &needleLower) { hay.toLowerCase(); return hay.indexOf(needleLower) >= 0; }
String sanitizeExt(const String &name) {
  int d = name.lastIndexOf('.');
  if (d < 0) return "";
  String e = "."; 
  for (size_t i = d + 1; i < name.length() && e.length() < 6; i++) {
    char c = name[i];
    if (isalnum((unsigned char)c)) e += (char)tolower(c);
  }
  return e.length() > 1 ? e : String("");
}
bool safeName(const String &n) {
  if (!n.length() || n.length() > 48 || n.indexOf("..") >= 0) return false;
  for (size_t i = 0; i < n.length(); i++) { char c = n[i]; if (!(isalnum((unsigned char)c) || c == '.' || c == '_' || c == '-')) return false; }
  return true;
}

// ============================== storage ==============================
bool loadJson(const String &path, JsonDocument &d) {
  File f = STORE.open(path, "r");
  if (!f) return false;
  DeserializationError e = deserializeJson(d, f);
  f.close();
  return !e;
}
bool saveJson(const String &path, JsonDocument &d) {
  String tmp = path + ".tmp";
  File f = STORE.open(tmp, "w");
  if (!f) return false;
  serializeJson(d, f);
  f.close();
  STORE.remove(path);
  return STORE.rename(tmp, path);
}
void loadArr(const char *p, JsonDocument &d) { if (!loadJson(p, d) || !d.is<JsonArray>()) d.to<JsonArray>(); }
int nextId(const char *key) {
  JsonDocument d;
  if (!loadJson(P_META, d) || !d.is<JsonObject>()) d.to<JsonObject>();
  int v = d[key] | 1;
  d[key] = v + 1;
  saveJson(P_META, d);
  return v;
}
String entryPath(int id) { return String(P_E) + "/" + id + ".json"; }
bool loadEntry(int id, JsonDocument &d) { return loadJson(entryPath(id), d); }
bool saveEntry(int id, JsonDocument &d) { return saveJson(entryPath(id), d); }
std::vector<int> entryIds() {
  std::vector<int> ids;
  File dir = STORE.open(P_E);
  if (dir) {
    for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
      String n = f.name(); n = n.substring(n.lastIndexOf('/') + 1);
      if (n.endsWith(".json")) { int id = n.toInt(); if (id > 0) ids.push_back(id); }
      f.close();
    }
    dir.close();
  }
  std::sort(ids.begin(), ids.end(), std::greater<int>());
  return ids;
}
void removeUpload(const String &stored) { if (safeName(stored)) STORE.remove(String(P_UP) + "/" + stored); }

// ============================== users / sessions ==============================
JsonArray U() { return gUsers.as<JsonArray>(); }
JsonObject userById(int id) { for (JsonObject u : U()) if ((int)u["id"] == id) return u; return JsonObject(); }
bool saveUsers() { return saveJson(P_USERS, gUsers); }
bool nameTaken(const String &n, int exceptId) { for (JsonObject u : U()) if (n == (const char *)u["name"] && (int)u["id"] != exceptId) return true; return false; }
int adminCount() { int c = 0; for (JsonObject u : U()) if (u["admin"] | false) c++; return c; }
int addUser(const String &name, const String &pw, const String &role, const String &contact, bool admin) {
  int id = nextId("u");
  JsonObject o = U().add<JsonObject>();
  String salt = randHex(8);
  o["id"] = id; o["name"] = name; o["salt"] = salt; o["hash"] = hashPw(pw, salt);
  o["role"] = role; o["contact"] = contact; o["admin"] = admin; o["bio"] = ""; o["photo"] = "";
  saveUsers();
  return id;
}
String getCookie(const char *name) {
  String c = server.header("Cookie"), key = String(name) + "=";
  int i = 0;
  while (true) {
    i = c.indexOf(key, i);
    if (i < 0) return "";
    if (i == 0 || c[i - 1] == ' ' || c[i - 1] == ';') break;
    i++;
  }
  int s = i + key.length(), e = c.indexOf(';', s);
  return c.substring(s, e < 0 ? c.length() : e);
}
Sess *findSess() {
  String t = getCookie("sid");
  if (t.length() != 32) return nullptr;
  for (int i = 0; i < SESS_MAX; i++)
    if (sess[i].tok == t) {
      if (millis() - sess[i].seen > SESS_TTL) { sess[i].tok = ""; return nullptr; }
      sess[i].seen = millis();
      return &sess[i];
    }
  return nullptr;
}
Sess *newSess(int uid) {
  int pick = 0;
  for (int i = 0; i < SESS_MAX; i++) {
    if (sess[i].tok.length() == 0) { pick = i; break; }
    if (sess[i].seen < sess[pick].seen) pick = i;
  }
  sess[pick] = Sess(); sess[pick].tok = randHex(16); sess[pick].uid = uid; sess[pick].seen = millis();
  return &sess[pick];
}
void loadMe() {
  me = Me(); cs = nullptr;
  loadArr(P_USERS, gUsers);
  cs = findSess();
  if (!cs) return;
  JsonObject u = userById(cs->uid);
  if (u.isNull()) { cs->tok = ""; cs = nullptr; return; }
  me.ok = true; me.id = cs->uid; me.admin = u["admin"] | false; me.name = u["name"].as<String>();
}
void flash(const String &msg, const char *cat) { if (cs) { cs->flash = msg; cs->cat = cat; } }
void flashNow(const String &msg, const char *cat) { nowMsg = msg; nowCat = cat; }
void redirect(const String &to) {
  server.sendHeader("Location", to);
  server.sendHeader("Cache-Control", "no-store");
  server.send(303, "text/plain", "");
}
// Replaces Flask's before_request + login_required/admin checks.
bool gate(bool needLogin = true, bool needAdmin = false) {
  loadMe();
  Serial.printf("[%lus] %s %s  (%s)\n", millis() / 1000, server.method() == HTTP_GET ? "GET" : "POST", server.uri().c_str(), me.ok ? me.name.c_str() : "not signed in");
  if (U().size() == 0) { redirect("/setup"); return false; }
  if (needLogin && !me.ok) { redirect("/login"); return false; }
  if (needAdmin && !me.admin) { flash("Admin access required.", "warning"); redirect("/"); return false; }
  return true;
}

// ============================== HTML output ==============================
String ob;
void W(const char *s) { ob += s; if (ob.length() > 1400) { server.sendContent(ob); ob = ""; } }
void W(const String &s) { ob += s; if (ob.length() > 1400) { server.sendContent(ob); ob = ""; } }

void pageStart(const String &title) {
  server.sendHeader("Cache-Control", "no-store");
  server.setContentLength(CONTENT_LENGTH_UNKNOWN);
  server.send(200, "text/html; charset=utf-8", "");
  ob = "";
  W("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\"/><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/><title>");
  W(esc(title)); W(" - Archain</title><link rel=\"stylesheet\" href=\"/static/styles.css\"/></head><body>");
  W("<header class=\"site-header\"><div><p class=\"kicker\">Archaeological Field Diary</p><h1>Archain Field Diary</h1></div><nav>");
  if (me.ok) {
    W("<a href=\"/\">Entries</a><a href=\"/entries/new\">New entry</a><a href=\"/map\">Map</a><a href=\"/directory\">Users</a>");
    if (me.admin) W("<a href=\"/people\">Finders</a><a href=\"/users\">Admin panel</a>");
    W("<button class=\"button ghost theme-toggle\" type=\"button\" onclick=\"toggleTheme()\">Theme</button>");
    W("<form method=\"post\" action=\"/logout\"><button class=\"link button-link\" type=\"submit\">Sign out (" + esc(me.name) + ")</button></form>");
  } else {
    W("<a href=\"/login\">Sign in</a>");
  }
  W("</nav></header><main class=\"container\">");
  String m = nowMsg, c = nowCat;
  if (cs && cs->flash.length()) { m = cs->flash; c = cs->cat; cs->flash = ""; }
  nowMsg = ""; nowCat = "";
  if (m.length()) W("<div class=\"flash-stack\"><div class=\"flash flash-" + c + "\">" + esc(m) + "</div></div>");
}
void pageEnd() {
  W(R"JS(</main><script>
const st=localStorage.getItem('archain-theme');if(st)document.body.dataset.theme=st;
function toggleTheme(){const n=(document.body.dataset.theme||'light')==='light'?'dark':'light';document.body.dataset.theme=n;localStorage.setItem('archain-theme',n);}
function togglePassword(cb){document.querySelectorAll('input[name=password],input[name=new_password],input[name=confirm_password],input[name=current_password]').forEach(f=>f.type=cb.checked?'text':'password');}
</script></body></html>)JS");
  if (ob.length()) server.sendContent(ob);
  ob = "";
  server.sendContent("");   // terminates the chunked response
}
void avatar(JsonObject u, bool large) {
  W(large ? "<div class=\"avatar large\">" : "<div class=\"avatar\">");
  String ph = u["photo"] | "";
  if (ph.length()) W("<img src=\"/uploads/" + esc(ph) + "\" alt=\"" + esc(u["name"] | "") + "\" />");
  else W("<span>" + esc(firstChar(u["name"] | "")) + "</span>");
  W("</div>");
}

// ============================== entries ==============================
bool inArr(JsonVariantConst arr, int id) {
  for (JsonVariantConst v : arr.as<JsonArrayConst>()) if (v.as<int>() == id) return true;
  return false;
}
bool canView(JsonVariantConst e) { return me.ok && (me.admin || e["owner"].as<int>() == me.id || inArr(e["users"], me.id)); }
bool canEdit(JsonVariantConst e) { return me.ok && (me.admin || e["owner"].as<int>() == me.id); }
bool entryMatches(JsonVariantConst e, const String &ql) {
  if (containsCI(e["title"] | "", ql) || containsCI(e["notes"] | "", ql)) return true;
  for (JsonVariantConst t : e["tags"].as<JsonArrayConst>()) if (containsCI(t.as<String>(), ql)) return true;
  return false;
}
String coordStr(double v) { return String(v, 6); }

String fetchWeather(double lat, double lon) {
  if (WiFi.status() != WL_CONNECTED) return "";
  HTTPClient http;
  http.setTimeout(4000);
  if (!http.begin("http://wttr.in/" + String(lat, 4) + "," + String(lon, 4) + "?format=%C+%t")) return "";
  int code = http.GET();
  String r = code == 200 ? http.getString() : "";
  http.end();
  r.trim();
  if (r.length() > 80 || r.indexOf("Unknown") >= 0 || r.indexOf('<') >= 0) return "";
  return r;
}

void argIds(const char *name, JsonArray out, std::function<bool(int)> ok) {
  for (int i = 0; i < server.args(); i++) {
    if (server.argName(i) != name) continue;
    int v = server.arg(i).toInt();
    if (v > 0 && ok(v) && !inArr(out, v)) out.add(v);
  }
}
// Fills d from the posted form (used for saving and for re-rendering after a validation error).
void entryFromRequest(JsonDocument &d) {
  d["title"] = utf8Cut(trimmed(server.arg("title")), 200);
  d["notes"] = utf8Cut(trimmed(server.arg("notes")), 20000);
  String t = trimmed(server.arg("event_time"));
  d["time"] = validTime(t) ? t : nowStr();
  d["loc"] = utf8Cut(trimmed(server.arg("location_label")), 200);
  double v;
  if (parseCoord(server.arg("latitude"), -90, 90, v)) d["lat"] = v;
  if (parseCoord(server.arg("longitude"), -180, 180, v)) d["lon"] = v;
  d["weather"] = utf8Cut(trimmed(server.arg("weather")), 120);
  JsonArray tags = d["tags"].to<JsonArray>();
  String raw = server.arg("tags"); int s = 0;
  while (s <= (int)raw.length() && tags.size() < 12) {
    int c = raw.indexOf(',', s); if (c < 0) c = raw.length();
    String tg = trimmed(raw.substring(s, c)); tg.toLowerCase(); tg = utf8Cut(tg, 40);
    bool dup = false; for (JsonVariant x : tags) if (tg == x.as<String>()) dup = true;
    if (tg.length() && !dup) tags.add(tg);
    s = c + 1;
  }
  argIds("users", d["users"].to<JsonArray>(), [](int id) { JsonObject u = userById(id); return !u.isNull() && !(u["admin"] | false); });
  JsonDocument pp; loadArr(P_PEOPLE, pp);
  argIds("people", d["people"].to<JsonArray>(), [&](int id) { for (JsonObject p : pp.as<JsonArray>()) if ((int)p["id"] == id) return true; return false; });
}
std::vector<Pending> takePending() { std::vector<Pending> v; v.swap(pending); return v; }
void discardPending(std::vector<Pending> &v) { for (auto &p : v) removeUpload(p.stored); v.clear(); }
void attachPending(JsonDocument &d, std::vector<Pending> &v) {
  JsonArray files = d["files"].is<JsonArray>() ? d["files"].as<JsonArray>() : d["files"].to<JsonArray>();
  for (auto &p : v) {
    if (p.field != "attachments") { removeUpload(p.stored); continue; }
    JsonObject f = files.add<JsonObject>();
    f["f"] = p.stored; f["n"] = p.orig; f["m"] = p.mime;
  }
  v.clear();
}

void renderEntryForm(JsonVariantConst e, const String &action, bool editing) {
  pageStart(editing ? "Edit entry" : "New entry");
  W("<section class=\"form-card\"><h2>"); W(editing ? "Edit diary entry" : "New diary entry");
  W("</h2><form method=\"post\" enctype=\"multipart/form-data\" class=\"stack\" action=\"" + esc(action) + "\">");
  W("<label>Title<input type=\"text\" name=\"title\" maxlength=\"200\" value=\"" + esc(e["title"] | "") + "\" required /></label>");
  W("<label>Entry time<input type=\"datetime-local\" name=\"event_time\" value=\"" + esc(e["time"] | "") + "\" /><span class=\"helper\">Leave blank to use the current time.</span></label>");
  W("<label>Location label<input type=\"text\" name=\"location_label\" placeholder=\"Unit 3, Trench B\" value=\"" + esc(e["loc"] | "") + "\" /></label>");
  String lat = e["lat"].isNull() ? "" : coordStr(e["lat"].as<double>());
  String lon = e["lon"].isNull() ? "" : coordStr(e["lon"].as<double>());
  W("<div class=\"grid-2\"><label>Latitude<input type=\"text\" inputmode=\"decimal\" name=\"latitude\" id=\"latitude\" placeholder=\"52.1\" value=\"" + lat + "\" /></label>");
  W("<label>Longitude<input type=\"text\" inputmode=\"decimal\" name=\"longitude\" id=\"longitude\" placeholder=\"13.4\" value=\"" + lon + "\" /></label></div>");
  W("<div class=\"actions\"><button type=\"button\" class=\"button ghost\" onclick=\"captureLocation()\">Use GPS from device</button><span class=\"helper\" id=\"gps-note\"></span></div>");
  W("<label>Weather / Conditions<input type=\"text\" name=\"weather\" id=\"weather\" placeholder=\"Overcast, 14&deg;C\" value=\"" + esc(e["weather"] | "") + "\" /><span class=\"helper\">Auto-filled from coordinates when the board has internet access.</span></label>");
  W("<label>Field notes<textarea name=\"notes\" rows=\"6\" required>" + esc(e["notes"] | "") + "</textarea></label>");
  String tg; for (JsonVariantConst t : e["tags"].as<JsonArrayConst>()) { if (tg.length()) tg += ", "; tg += t.as<String>(); }
  W("<label>Tags (comma separated)<input type=\"text\" name=\"tags\" placeholder=\"ceramic, survey, trench-b\" value=\"" + esc(tg) + "\" /></label>");
  W("<label>Attach photos, 3D models, or field files<input type=\"file\" name=\"attachments\" multiple /><span class=\"helper\">Large photos are shrunk in the browser before upload to save board storage.</span></label>");
  W("<div class=\"grid-2\"><label>Team members (shared access)<select name=\"users\" multiple>");
  for (JsonObject u : U()) {
    if (u["admin"] | false) continue;
    W(String("<option value=\"") + (int)u["id"] + "\"" + (inArr(e["users"], u["id"]) ? " selected" : "") + ">" + esc(u["name"] | "") + " (" + esc(u["role"] | "") + ")</option>");
  }
  W("</select></label><label>People who found it<select name=\"people\" multiple>");
  JsonDocument pp; loadArr(P_PEOPLE, pp);
  for (JsonObject p : pp.as<JsonArray>())
    W(String("<option value=\"") + (int)p["id"] + "\"" + (inArr(e["people"], p["id"]) ? " selected" : "") + ">" + esc(p["name"] | "") + "</option>");
  W("</select></label></div><button type=\"submit\" class=\"button\">"); W(editing ? "Update entry" : "Save entry"); W("</button></form></section>");
  W(R"JS(<script>
const $=id=>document.getElementById(id);
const tIn=document.querySelector('input[name="event_time"]');
if(!tIn.value){const d=new Date();d.setMinutes(d.getMinutes()-d.getTimezoneOffset());tIn.value=d.toISOString().slice(0,16);}
if(!window.isSecureContext)$('gps-note').textContent='Browser GPS needs HTTPS - type the coordinates by hand (see README).';
function captureLocation(){
  if(!navigator.geolocation){alert('Geolocation is not supported on this device.');return;}
  navigator.geolocation.getCurrentPosition(p=>{$('latitude').value=p.coords.latitude.toFixed(6);$('longitude').value=p.coords.longitude.toFixed(6);lookupWeather();},()=>alert('Unable to fetch location. Check permissions and that the page is served over HTTPS.'));
}
function lookupWeather(){
  const w=$('weather'),a=$('latitude').value,o=$('longitude').value;
  if(w.value||!a||!o)return;
  fetch('/weather?lat='+encodeURIComponent(a)+'&lon='+encodeURIComponent(o)).then(r=>r.json()).then(d=>{if(d.weather&&!w.value)w.value=d.weather;}).catch(()=>{});
}
$('latitude').addEventListener('change',lookupWeather);$('longitude').addEventListener('change',lookupWeather);
const MAXPX=1600;
document.querySelectorAll('input[type=file][name=attachments]').forEach(inp=>inp.addEventListener('change',async()=>{
  const dt=new DataTransfer();
  for(const f of inp.files){
    if(!/^image\/(jpeg|png|webp)$/.test(f.type)||f.size<300000){dt.items.add(f);continue;}
    try{
      const bm=await createImageBitmap(f);
      const s=Math.min(1,MAXPX/Math.max(bm.width,bm.height));
      const c=document.createElement('canvas');c.width=Math.round(bm.width*s);c.height=Math.round(bm.height*s);
      c.getContext('2d').drawImage(bm,0,0,c.width,c.height);
      const b=await new Promise(r=>c.toBlob(r,'image/jpeg',0.85));
      dt.items.add(new File([b],f.name.replace(/\.\w+$/,'')+'.jpg',{type:'image/jpeg'}));
    }catch(x){dt.items.add(f);}
  }
  inp.files=dt.files;
}));
</script>)JS");
  pageEnd();
}

void handleIndex() {
  if (!gate()) return;
  String q = trimmed(server.arg("q")), ql = q; ql.toLowerCase();
  pageStart("Field Diary Entries");
  W("<section class=\"hero\"><div><h2>Archain shared excavation diary</h2><p>Track contexts, GPS points, photos, 3D models, and the people who discovered each find. Running on an Arduino Nano ESP32.</p></div><a class=\"button\" href=\"/entries/new\">Log a new entry</a></section>");
  W("<form class=\"search-bar\" method=\"get\" action=\"/\"><input type=\"search\" name=\"q\" placeholder=\"Search by title, notes, or tags\" value=\"" + esc(q) + "\" /><button class=\"button ghost\" type=\"submit\">Search</button>");
  if (q.length()) W("<a class=\"link\" href=\"/\">Clear</a>");
  W("</form><section class=\"card-grid\">");
  int shown = 0;
  for (int id : entryIds()) {
    JsonDocument e;
    if (!loadEntry(id, e) || !canView(e) || (ql.length() && !entryMatches(e, ql))) continue;
    shown++;
    String notes = e["notes"] | "";
    W("<article class=\"card\"><header><h3>" + esc(e["title"] | "") + "</h3><p class=\"muted\">Logged " + esc(fmtTime(e["time"] | "")) + "</p></header>");
    W("<p>" + esc(utf8Cut(notes, 180)) + (notes.length() > 180 ? "..." : "") + "</p><div class=\"meta\">");
    String loc = e["loc"] | "";
    if (loc.length()) W("<span>" + esc(loc) + "</span>");
    if (!e["lat"].isNull() && !e["lon"].isNull()) W("<span>&#128205; " + coordStr(e["lat"]) + ", " + coordStr(e["lon"]) + "</span>");
    W(String("</div><footer><a class=\"link\" href=\"/entries/") + id + "\">Open entry &rarr;</a></footer></article>");
  }
  if (!shown) W("<div class=\"empty-state\"><h3>No entries yet</h3><p>Start by capturing your first field note and invite the rest of your team to collaborate.</p></div>");
  W("</section>");
  pageEnd();
}

void handleMap() {
  if (!gate()) return;
  JsonDocument pts; JsonArray arr = pts.to<JsonArray>();
  pageStart("Map");
  W("<section class=\"hero\"><div><h2>Entry map</h2><p>Every entry shared with you that has coordinates. The interactive map needs a device with internet access; the list below always works.</p></div></section>");
  W("<section class=\"card\"><div id=\"entry-map\" class=\"map-panel large\"></div><ul class=\"list\">");
  for (int id : entryIds()) {
    JsonDocument e;
    if (!loadEntry(id, e) || !canView(e) || e["lat"].isNull() || e["lon"].isNull()) continue;
    JsonObject o = arr.add<JsonObject>();
    o["id"] = id; o["t"] = e["title"]; o["lat"] = e["lat"]; o["lon"] = e["lon"]; o["time"] = fmtTime(e["time"] | "");
    String la = coordStr(e["lat"]), lo = coordStr(e["lon"]);
    W(String("<li><strong>") + esc(e["title"] | "") + "</strong><span class=\"muted\">" + esc(fmtTime(e["time"] | "")) + " &middot; " + la + ", " + lo + "</span>");
    W("<a class=\"link\" href=\"https://www.openstreetmap.org/?mlat=" + la + "&mlon=" + lo + "#map=16/" + la + "/" + lo + "\" target=\"_blank\" rel=\"noopener\">OSM</a>");
    W(String("<a class=\"link\" href=\"/entries/") + id + "\">Open entry &rarr;</a></li>");
  }
  if (!arr.size()) W("<li class=\"muted\">No entries with coordinates yet.</li>");
  W("</ul></section>");
  String js; serializeJson(pts, js); js.replace("</", "<\\/");
  W("<link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\" /><script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\"></script><script>const entries=" + js + ";");
  W(R"JS(
const el=document.getElementById('entry-map');
if(typeof L==='undefined'||!entries.length){el.style.display='none';}else{
  const map=L.map(el).setView([entries[0].lat,entries[0].lon],6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(map);
  entries.forEach(e=>{const m=L.marker([e.lat,e.lon]).addTo(map);
    const d=document.createElement('div');const b=document.createElement('strong');b.textContent=e.t;d.append(b,document.createElement('br'),e.time,document.createElement('br'));
    const a=document.createElement('a');a.href='/entries/'+e.id;a.textContent='Open entry';d.append(a);m.bindPopup(d);});
}
</script>)JS");
  pageEnd();
}

void handleNewGet() {
  if (!gate()) return;
  JsonDocument e; e["time"] = nowStr();
  renderEntryForm(e, "/entries/new", false);
}
void handleNewPost() {
  auto up = takePending();
  if (!gate()) { discardPending(up); return; }
  JsonDocument e; entryFromRequest(e);
  String err = upErr; upErr = "";
  if (!trimmed(e["title"] | "").length() || !trimmed(e["notes"] | "").length()) {
    discardPending(up); flashNow("Title and notes are required.", "warning");
    renderEntryForm(e, "/entries/new", false); return;
  }
  int id = nextId("e");
  e["id"] = id; e["owner"] = me.id;
  attachPending(e, up);
  if (String(e["weather"] | "").length() == 0 && !e["lat"].isNull() && !e["lon"].isNull())
    e["weather"] = fetchWeather(e["lat"], e["lon"]);
  if (!saveEntry(id, e)) { flash("Could not write to storage.", "warning"); redirect("/"); return; }
  flash(err.length() ? "Entry saved, but a file was skipped: " + err : String("Entry saved!"), err.length() ? "warning" : "success");
  redirect("/entries/" + String(id));
}

bool loadForEdit(int id, JsonDocument &e) {
  if (id <= 0 || !loadEntry(id, e)) { flash("Entry not found.", "warning"); redirect("/"); return false; }
  if (!canEdit(e)) { flash("You do not have permission to edit this entry.", "warning"); redirect("/entries/" + String(id)); return false; }
  return true;
}
void handleEditGet() {
  if (!gate()) return;
  int id = server.pathArg(0).toInt(); JsonDocument e;
  if (!loadForEdit(id, e)) return;
  renderEntryForm(e, "/entries/" + String(id) + "/edit", true);
}
void handleEditPost() {
  auto up = takePending();
  if (!gate()) { discardPending(up); return; }
  int id = server.pathArg(0).toInt(); JsonDocument old;
  if (!loadForEdit(id, old)) { discardPending(up); return; }
  JsonDocument e; entryFromRequest(e);
  String err = upErr; upErr = "";
  if (!trimmed(e["title"] | "").length() || !trimmed(e["notes"] | "").length()) {
    discardPending(up); flashNow("Title and notes are required.", "warning");
    renderEntryForm(e, "/entries/" + String(id) + "/edit", true); return;
  }
  e["id"] = id; e["owner"] = old["owner"]; e["files"] = old["files"];
  attachPending(e, up);
  if (String(e["weather"] | "").length() == 0 && !e["lat"].isNull() && !e["lon"].isNull())
    e["weather"] = fetchWeather(e["lat"], e["lon"]);
  saveEntry(id, e);
  flash(err.length() ? "Entry updated, but a file was skipped: " + err : String("Entry updated."), err.length() ? "warning" : "success");
  redirect("/entries/" + String(id));
}

void handleDetail() {
  if (!gate()) return;
  int id = server.pathArg(0).toInt(); JsonDocument e;
  if (id <= 0 || !loadEntry(id, e)) { flash("Entry not found.", "warning"); redirect("/"); return; }
  if (!canView(e)) { flash("You do not have access to this entry.", "warning"); redirect("/"); return; }
  pageStart(String("Entry ") + (e["title"] | ""));
  W(String("<section class=\"detail-header\"><div><p class=\"kicker\">Entry #") + id + "</p><h2>" + esc(e["title"] | "") + "</h2><p class=\"muted\">Logged " + esc(fmtTime(e["time"] | "")) + "</p></div><div class=\"actions\">");
  if (canEdit(e)) {
    W(String("<a class=\"button ghost\" href=\"/entries/") + id + "/edit\">Edit</a>");
    W(String("<form method=\"post\" action=\"/entries/") + id + "/delete\" onsubmit=\"return confirm('Delete this entry?');\"><button class=\"button danger\" type=\"submit\">Delete</button></form>");
  }
  W("</div></section><div class=\"detail-grid\"><article class=\"card\"><h3>Field notes</h3><p class=\"preline\">" + esc(e["notes"] | "") + "</p>");
  String wx = e["weather"] | ""; if (wx.length()) W("<p><strong>Weather:</strong> " + esc(wx) + "</p>");
  W("</article><article class=\"card\"><h3>Location</h3>");
  String loc = e["loc"] | ""; if (loc.length()) W("<p><strong>Label:</strong> " + esc(loc) + "</p>");
  if (!e["lat"].isNull() && !e["lon"].isNull()) {
    String la = coordStr(e["lat"]), lo = coordStr(e["lon"]);
    W("<p><strong>Coordinates:</strong> " + la + ", " + lo + "</p><p><a class=\"link\" href=\"https://www.openstreetmap.org/?mlat=" + la + "&mlon=" + lo + "#map=16/" + la + "/" + lo + "\" target=\"_blank\" rel=\"noopener\">Open in OpenStreetMap &rarr;</a></p>");
  } else W("<p class=\"muted\">No GPS coordinates provided.</p>");
  W("</article><article class=\"card\"><h3>Ownership</h3>");
  JsonObject ow = userById(e["owner"]);
  if (!ow.isNull()) W("<p><strong>Owner:</strong> " + esc(ow["name"] | "") + "</p>"); else W("<p class=\"muted\">Owner not assigned.</p>");
  W("<h4>Shared with</h4>");
  bool any = false;
  for (JsonVariantConst uid : e["users"].as<JsonArrayConst>()) {
    JsonObject u = userById(uid.as<int>()); if (u.isNull()) continue;
    if (!any) W("<ul>"); any = true;
    W("<li>" + esc(u["name"] | "") + " &mdash; " + esc(u["role"] | "") + "</li>");
  }
  if (any) W("</ul>"); else W("<p class=\"muted\">No shared team members listed.</p>");
  if (e["tags"].as<JsonArrayConst>().size()) {
    W("<h4>Tags</h4><div class=\"tag-list\">");
    for (JsonVariantConst t : e["tags"].as<JsonArrayConst>()) W("<span class=\"tag\">" + esc(t.as<String>()) + "</span>");
    W("</div>");
  }
  W("<h4>People who found it</h4>");
  JsonDocument pp; loadArr(P_PEOPLE, pp); any = false;
  for (JsonVariantConst pid : e["people"].as<JsonArrayConst>())
    for (JsonObject p : pp.as<JsonArray>()) if ((int)p["id"] == pid.as<int>()) {
      if (!any) W("<ul>"); any = true;
      String af = p["aff"] | "";
      W("<li>" + esc(p["name"] | "") + (af.length() ? " (" + esc(af) + ")" : String("")) + "</li>");
    }
  if (any) W("</ul>"); else W("<p class=\"muted\">No finders attached.</p>");
  W("</article></div><section class=\"card\"><h3>Attachments</h3>");
  JsonArrayConst files = e["files"].as<JsonArrayConst>();
  if (files.size()) {
    bool glb = false;
    W("<div class=\"attachments\">");
    for (JsonObjectConst f : files) {
      String st = f["f"] | "", nm = f["n"] | "", mt = f["m"] | "", ext = sanitizeExt(st);
      String url = "/uploads/" + esc(st);
      W("<div class=\"attachment\"><a href=\"" + url + "\" target=\"_blank\">" + esc(nm) + "</a>");
      if (ext == ".jpg" || ext == ".jpeg" || ext == ".png" || ext == ".gif" || ext == ".webp") W("<img loading=\"lazy\" src=\"" + url + "\" alt=\"" + esc(nm) + "\" />");
      else if (ext == ".glb" || ext == ".gltf") { glb = true; W("<model-viewer src=\"" + url + "\" auto-rotate camera-controls></model-viewer>"); }
      else W("<p class=\"muted\">" + esc(mt.length() ? mt : String("file")) + "</p>");
      W("</div>");
    }
    W("</div>");
    if (glb) W("<script type=\"module\" src=\"https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js\"></script>");
  } else W("<p class=\"muted\">No files attached.</p>");
  W("</section>");
  pageEnd();
}

void handleDelete() {
  if (!gate()) return;
  int id = server.pathArg(0).toInt(); JsonDocument e;
  if (id <= 0 || !loadEntry(id, e)) { flash("Entry already removed.", "warning"); redirect("/"); return; }
  if (!canEdit(e)) { flash("You do not have permission to delete this entry.", "warning"); redirect("/entries/" + String(id)); return; }
  for (JsonObjectConst f : e["files"].as<JsonArrayConst>()) removeUpload(f["f"] | "");
  STORE.remove(entryPath(id));
  flash("Entry deleted.", "success"); redirect("/");
}

// ============================== uploads ==============================
void onUpload() {   // multipart callback, called while the body is being received
  HTTPUpload &u = server.upload();
  if (u.status == UPLOAD_FILE_START) {
    upActive = false;
    if (!u.filename.length()) return;
    loadMe();
    if (!me.ok) return;
    if (pending.size() >= 8) { upErr = "too many files (max 8)"; return; }
    String stored = "u" + String(nextId("f")) + sanitizeExt(u.filename);
    upPath = String(P_UP) + "/" + stored;
    upFile = STORE.open(upPath, "w");
    if (!upFile) { upErr = "storage error"; return; }
    upCur = Pending(); upCur.stored = stored; upCur.orig = utf8Cut(u.filename, 120); upCur.mime = u.type; upCur.field = u.name;
    upSize = 0; upActive = true;
  } else if (u.status == UPLOAD_FILE_WRITE) {
    if (!upActive) return;
    bool full = freeBytes() < MIN_FREE + u.currentSize;
    if (upSize + u.currentSize > MAX_UPLOAD || full) {
      upErr = full ? "storage full" : "file too large";
      upFile.close(); STORE.remove(upPath); upActive = false; return;
    }
    upFile.write(u.buf, u.currentSize); upSize += u.currentSize;
  } else if (u.status == UPLOAD_FILE_END) {
    if (!upActive) return;
    upFile.close(); upCur.size = upSize; pending.push_back(upCur); upActive = false;
  } else if (u.status == UPLOAD_FILE_ABORTED) {
    if (upActive) { upFile.close(); STORE.remove(upPath); upActive = false; }
    discardPending(pending);
  }
}
void handleUploadGet() {
  if (!gate()) return;
  String fn = server.pathArg(0);
  File f;
  if (safeName(fn)) f = STORE.open(String(P_UP) + "/" + fn, "r");
  if (!f || f.isDirectory()) { server.send(404, "text/plain", "Not found"); return; }
  String ext = sanitizeExt(fn); const char *mime = nullptr;
  if (ext == ".jpg" || ext == ".jpeg") mime = "image/jpeg"; else if (ext == ".png") mime = "image/png";
  else if (ext == ".gif") mime = "image/gif"; else if (ext == ".webp") mime = "image/webp";
  else if (ext == ".pdf") mime = "application/pdf"; else if (ext == ".glb") mime = "model/gltf-binary";
  else if (ext == ".gltf") mime = "model/gltf+json";
  server.sendHeader("X-Content-Type-Options", "nosniff");
  server.sendHeader("Cache-Control", "private, max-age=86400");
  if (!mime) { mime = "application/octet-stream"; server.sendHeader("Content-Disposition", "attachment"); }
  server.streamFile(f, mime);
  f.close();
}
void handleWeather() {
  if (!gate()) return;
  double la, lo;
  if (!parseCoord(server.arg("lat"), -90, 90, la) || !parseCoord(server.arg("lon"), -180, 180, lo)) { server.send(400, "application/json", "{\"weather\":\"\"}"); return; }
  JsonDocument d; d["weather"] = fetchWeather(la, lo);
  String out; serializeJson(d, out);
  server.send(200, "application/json", out);
}

// ============================== auth / setup ==============================
void passwordForm(const char *title, const char *extra, const char *button, bool setup) {
  pageStart(title);
  W("<section class=\"form-card narrow\"><h2>"); W(title); W("</h2>"); W(extra);
  W("<form method=\"post\" class=\"stack\"><label>Name<input type=\"text\" name=\"name\" required /></label>");
  W("<label>Password<input type=\"password\" name=\"password\" maxlength=\"64\" required /></label><label class=\"inline\"><input type=\"checkbox\" onclick=\"togglePassword(this)\" /> Show password</label>");
  if (setup) W("<label>Contact<input type=\"text\" name=\"contact\" placeholder=\"email or phone\" /></label>");
  W("<button type=\"submit\" class=\"button\">"); W(button); W("</button></form>");
  if (!setup) W("<p class=\"helper\">First time? If no users exist, visit <a class=\"link\" href=\"/setup\">/setup</a> to create the owner account.</p>");
  W("</section>"); pageEnd();
}
void handleLoginGet() {
  loadMe();
  if (U().size() == 0) { redirect("/setup"); return; }
  if (me.ok) { redirect("/"); return; }
  passwordForm("Sign in", "", "Sign in", false);
}
void handleLoginPost() {
  loadMe();
  if (U().size() == 0) { redirect("/setup"); return; }
  if (me.ok) { redirect("/"); return; }
  String name = trimmed(server.arg("name")), pw = server.arg("password");
  for (JsonObject u : U()) {
    if (name == (const char *)u["name"] && ctEq(hashPw(pw, u["salt"] | ""), u["hash"] | "")) {
      cs = newSess(u["id"]);
      server.sendHeader("Set-Cookie", "sid=" + cs->tok + "; Path=/; HttpOnly; SameSite=Lax");
      Serial.printf("[login] OK: %s\n", name.c_str());
      flash("Welcome back!", "success"); redirect("/"); return;
    }
  }
  Serial.printf("[login] FAILED for '%s'\n", name.c_str());
  flashNow("Invalid credentials.", "warning");
  passwordForm("Sign in", "", "Sign in", false);
}
void handleLogout() {
  loadMe();
  if (cs) cs->tok = "";
  server.sendHeader("Set-Cookie", "sid=; Path=/; Max-Age=0; HttpOnly");
  redirect("/login");
}
void handleSetupGet() {
  loadMe();
  if (U().size() > 0) { redirect("/login"); return; }
  passwordForm("Create owner account", "<p class=\"helper\">This form is available only when no users exist. The first account becomes the owner admin.</p>", "Create owner", true);
}
void handleSetupPost() {
  loadMe();
  if (U().size() > 0) { redirect("/login"); return; }
  String name = trimmed(server.arg("name")), pw = server.arg("password");
  if (!name.length() || !pw.length()) { flashNow("Name and password are required.", "warning"); passwordForm("Create owner account", "", "Create owner", true); return; }
  addUser(utf8Cut(name, 120), pw, "Owner", utf8Cut(trimmed(server.arg("contact")), 120), true);
  loadMe(); cs = nullptr;
  flashNow("Admin account created. Please sign in.", "success");
  passwordForm("Sign in", "", "Sign in", false);
}

// ============================== users / profiles / people ==============================
void handleDirectory() {
  if (!gate()) return;
  pageStart("Users");
  W("<section class=\"hero\"><div><h2>Team directory</h2><p>Browse the archaeologists and collaborators on this project.</p></div></section><section class=\"card-grid\">");
  for (JsonObject u : U()) {
    W("<article class=\"card user-card\">"); avatar(u, false);
    W("<h3>" + esc(u["name"] | "") + "</h3><p class=\"muted\">" + esc(u["role"] | "") + "</p>");
    String c = u["contact"] | ""; if (c.length()) W("<p class=\"muted\">" + esc(c) + "</p>");
    W(String("<a class=\"link\" href=\"/users/") + (int)u["id"] + "\">View profile &rarr;</a></article>");
  }
  W("</section>"); pageEnd();
}
void handleProfile() {
  if (!gate()) return;
  int uid = server.pathArg(0).toInt(); JsonObject u = userById(uid);
  if (u.isNull()) { flash("User not found.", "warning"); redirect("/directory"); return; }
  bool mine = me.admin || me.id == uid;
  pageStart(u["name"] | "Profile");
  W("<section class=\"detail-header\"><div class=\"user-header\">"); avatar(u, true);
  W("<div><p class=\"kicker\">User profile</p><h2>" + esc(u["name"] | "") + "</h2><p class=\"muted\">" + esc(u["role"] | "") + "</p>");
  String c = u["contact"] | ""; if (c.length()) W("<p class=\"muted\">" + esc(c) + "</p>");
  W("</div></div>");
  if (mine) W(String("<a class=\"button ghost\" href=\"/users/") + uid + "/profile\">Edit profile</a>");
  W("</section><section class=\"card\"><h3>About</h3>");
  String bio = u["bio"] | ""; if (bio.length()) W("<p class=\"preline\">" + esc(bio) + "</p>"); else W("<p class=\"muted\">No bio provided.</p>");
  W("</section><section class=\"card\"><h3>Entries linked to " + esc(u["name"] | "") + "</h3>");
  bool any = false;
  for (int id : entryIds()) {
    JsonDocument e;
    if (!loadEntry(id, e) || !canView(e) || !((int)e["owner"] == uid || inArr(e["users"], uid))) continue;
    if (!any) W("<ul class=\"list\">"); any = true;
    W("<li><strong>" + esc(e["title"] | "") + "</strong> <span class=\"muted\">" + esc(fmtTime(e["time"] | "")) + "</span>");
    W(String("<a class=\"link\" href=\"/entries/") + id + "\">Open entry &rarr;</a></li>");
  }
  if (any) W("</ul>"); else W("<p class=\"muted\">No entries linked to this user yet.</p>");
  W("</section>");
  if (mine) {
    W(String("<section class=\"card\"><h3>Change password</h3><form method=\"post\" action=\"/users/") + uid + "/password\" class=\"stack\">");
    if (me.id == uid) W("<label>Current password<input type=\"password\" name=\"current_password\" maxlength=\"64\" required /></label>");
    W("<label>New password<input type=\"password\" name=\"new_password\" maxlength=\"64\" required /></label><label>Confirm new password<input type=\"password\" name=\"confirm_password\" maxlength=\"64\" required /></label><button type=\"submit\" class=\"button\">Update password</button></form></section>");
  }
  pageEnd();
}
void handleProfileEditGet() {
  if (!gate()) return;
  int uid = server.pathArg(0).toInt(); JsonObject u = userById(uid);
  if (u.isNull()) { flash("User not found.", "warning"); redirect("/directory"); return; }
  if (!(me.admin || me.id == uid)) { flash("You do not have permission to edit this profile.", "warning"); redirect("/users/" + String(uid)); return; }
  pageStart("Edit profile");
  W("<section class=\"form-card\"><h2>Edit profile</h2><form method=\"post\" enctype=\"multipart/form-data\" class=\"stack\">");
  W("<label>Name<input type=\"text\" name=\"name\" value=\"" + esc(u["name"] | "") + "\" required /></label>");
  W("<label>Role<input type=\"text\" name=\"role\" value=\"" + esc(u["role"] | "") + "\" /></label>");
  W("<label>Contact<input type=\"text\" name=\"contact\" value=\"" + esc(u["contact"] | "") + "\" /></label>");
  W("<label>Bio<textarea name=\"bio\" rows=\"4\">" + esc(u["bio"] | "") + "</textarea></label>");
  W("<label>Selfie photo<input type=\"file\" name=\"photo\" accept=\"image/*\" /></label><button type=\"submit\" class=\"button\">Save profile</button></form></section>");
  pageEnd();
}
void handleProfileEditPost() {
  auto up = takePending();
  if (!gate()) { discardPending(up); return; }
  int uid = server.pathArg(0).toInt(); JsonObject u = userById(uid);
  if (u.isNull() || !(me.admin || me.id == uid)) { discardPending(up); flash("You do not have permission to edit this profile.", "warning"); redirect("/directory"); return; }
  String name = utf8Cut(trimmed(server.arg("name")), 120);
  if (name.length() && !nameTaken(name, uid)) u["name"] = name;
  else if (name.length()) flash("That name is already in use.", "warning");
  u["role"] = utf8Cut(trimmed(server.arg("role")), 120);
  u["contact"] = utf8Cut(trimmed(server.arg("contact")), 120);
  u["bio"] = utf8Cut(trimmed(server.arg("bio")), 2000);
  for (auto &p : up) {
    String ext = sanitizeExt(p.stored);
    bool img = ext == ".jpg" || ext == ".jpeg" || ext == ".png" || ext == ".gif" || ext == ".webp";
    if (p.field == "photo" && img) { removeUpload(u["photo"] | ""); u["photo"] = p.stored; } else removeUpload(p.stored);
  }
  up.clear();
  saveUsers();
  if (!cs || !cs->flash.length()) flash("Profile updated.", "success");
  redirect("/users/" + String(uid));
}
void handlePassword() {
  if (!gate()) return;
  int uid = server.pathArg(0).toInt(); JsonObject u = userById(uid);
  String back = "/users/" + String(uid);
  if (u.isNull()) { flash("User not found.", "warning"); redirect("/directory"); return; }
  if (!(me.admin || me.id == uid)) { flash("You do not have permission to change this password.", "warning"); redirect(back); return; }
  String np = server.arg("new_password");
  if (me.id == uid && !ctEq(hashPw(server.arg("current_password"), u["salt"] | ""), u["hash"] | "")) { flash("Current password is incorrect.", "warning"); redirect(back); return; }
  if (!np.length() || np.length() > 64 || np != server.arg("confirm_password")) { flash("New password and confirmation must match.", "warning"); redirect(back); return; }
  String salt = randHex(8); u["salt"] = salt; u["hash"] = hashPw(np, salt); saveUsers();
  flash("Password updated.", "success"); redirect(back);
}
void handleUsersGet() {
  if (!gate(true, true)) return;
  pageStart("Team");
  W("<section class=\"form-card\"><h2>Admin panel: add team member</h2><form method=\"post\" class=\"stack\">");
  W("<label>Name<input type=\"text\" name=\"name\" required /></label><label>Password<input type=\"password\" name=\"password\" maxlength=\"64\" required /></label>");
  W("<label class=\"inline\"><input type=\"checkbox\" onclick=\"togglePassword(this)\" /> Show password</label>");
  W("<label>Role<input type=\"text\" name=\"role\" placeholder=\"Survey lead\" /></label><label>Contact<input type=\"text\" name=\"contact\" placeholder=\"email or phone\" /></label>");
  W("<label class=\"inline\"><input type=\"checkbox\" name=\"is_admin\" /> Admin access</label><button type=\"submit\" class=\"button\">Save</button></form></section>");
  W("<section class=\"card\"><h3>Team roster</h3><ul class=\"list\">");
  for (JsonObject u : U()) {
    int id = u["id"]; String c = u["contact"] | "";
    W("<li><div><strong>" + esc(u["name"] | "") + "</strong> <span>" + esc(u["role"] | "") + ((u["admin"] | false) ? " &middot; Admin" : "") + "</span>");
    if (c.length()) W(" <span class=\"muted\">" + esc(c) + "</span>");
    W(String("</div><div class=\"actions\"><a class=\"link\" href=\"/users/") + id + "/edit\">Edit</a>");
    W(String("<form method=\"post\" action=\"/users/") + id + "/delete\" onsubmit=\"return confirm('Delete this user?');\"><button class=\"button ghost\" type=\"submit\">Delete</button></form></div></li>");
  }
  W("</ul></section>"); pageEnd();
}
void handleUsersPost() {
  if (!gate(true, true)) return;
  String name = utf8Cut(trimmed(server.arg("name")), 120), pw = server.arg("password");
  if (!name.length() || !pw.length() || pw.length() > 64) flash("Name and password (max 64 characters) are required.", "warning");
  else if (nameTaken(name, 0)) flash("That name is already in use.", "warning");
  else { addUser(name, pw, utf8Cut(trimmed(server.arg("role")), 120), utf8Cut(trimmed(server.arg("contact")), 120), server.hasArg("is_admin")); flash("User added.", "success"); }
  redirect("/users");
}
void handleUserEditGet() {
  if (!gate(true, true)) return;
  JsonObject u = userById(server.pathArg(0).toInt());
  if (u.isNull()) { flash("User not found.", "warning"); redirect("/users"); return; }
  pageStart("Edit team member");
  W("<section class=\"form-card\"><h2>Edit team member</h2><form method=\"post\" class=\"stack\">");
  W("<label>Name<input type=\"text\" name=\"name\" value=\"" + esc(u["name"] | "") + "\" required /></label>");
  W("<label>New password<input type=\"password\" name=\"password\" maxlength=\"64\" placeholder=\"Leave blank to keep current\" /></label><label class=\"inline\"><input type=\"checkbox\" onclick=\"togglePassword(this)\" /> Show password</label>");
  W("<label>Role<input type=\"text\" name=\"role\" value=\"" + esc(u["role"] | "") + "\" /></label><label>Contact<input type=\"text\" name=\"contact\" value=\"" + esc(u["contact"] | "") + "\" /></label>");
  W(String("<label class=\"inline\"><input type=\"checkbox\" name=\"is_admin\" ") + ((u["admin"] | false) ? "checked" : "") + " /> Admin access</label>");
  W("<div class=\"actions\"><button type=\"submit\" class=\"button\">Save changes</button><a class=\"link\" href=\"/users\">Cancel</a></div></form></section>");
  pageEnd();
}
void handleUserEditPost() {
  if (!gate(true, true)) return;
  int uid = server.pathArg(0).toInt(); JsonObject u = userById(uid);
  if (u.isNull()) { flash("User not found.", "warning"); redirect("/users"); return; }
  String name = utf8Cut(trimmed(server.arg("name")), 120), pw = server.arg("password");
  bool adm = server.hasArg("is_admin");
  if (!name.length()) { flash("Name is required.", "warning"); redirect("/users/" + String(uid) + "/edit"); return; }
  if (nameTaken(name, uid)) { flash("That name is already in use.", "warning"); redirect("/users/" + String(uid) + "/edit"); return; }
  if (pw.length() > 64) { flash("Password is too long (max 64).", "warning"); redirect("/users/" + String(uid) + "/edit"); return; }
  if (!adm && (u["admin"] | false) && adminCount() <= 1) { flash("There must be at least one admin.", "warning"); redirect("/users/" + String(uid) + "/edit"); return; }
  u["name"] = name; u["role"] = utf8Cut(trimmed(server.arg("role")), 120); u["contact"] = utf8Cut(trimmed(server.arg("contact")), 120); u["admin"] = adm;
  if (pw.length()) { String salt = randHex(8); u["salt"] = salt; u["hash"] = hashPw(pw, salt); }
  saveUsers(); flash("User updated.", "success"); redirect("/users");
}
void handleUserDelete() {
  if (!gate(true, true)) return;
  int uid = server.pathArg(0).toInt(); JsonObject u = userById(uid);
  if (u.isNull()) { flash("User already removed.", "warning"); redirect("/users"); return; }
  if (uid == me.id) { flash("You cannot delete your own account.", "warning"); redirect("/users"); return; }
  // entries owned by the deleted user go to the deleting admin; the user is removed from shares
  for (int id : entryIds()) {
    JsonDocument e; if (!loadEntry(id, e)) continue;
    bool ch = false;
    if ((int)e["owner"] == uid) { e["owner"] = me.id; ch = true; }
    JsonArray a = e["users"].as<JsonArray>();
    for (size_t i = 0; i < a.size();) { if (a[i].as<int>() == uid) { a.remove(i); ch = true; } else i++; }
    if (ch) saveEntry(id, e);
  }
  removeUpload(u["photo"] | "");
  for (size_t i = 0; i < U().size(); i++) if ((int)U()[i]["id"] == uid) { U().remove(i); break; }
  saveUsers();
  for (int i = 0; i < SESS_MAX; i++) if (sess[i].uid == uid) sess[i].tok = "";
  flash("User deleted.", "success"); redirect("/users");
}
void handlePeople() {
  if (!gate(true, true)) return;
  JsonDocument pp; loadArr(P_PEOPLE, pp);
  if (server.method() == HTTP_POST) {
    String name = utf8Cut(trimmed(server.arg("name")), 120);
    if (name.length()) {
      JsonObject o = pp.as<JsonArray>().add<JsonObject>();
      o["id"] = nextId("p"); o["name"] = name; o["aff"] = utf8Cut(trimmed(server.arg("affiliation")), 120);
      saveJson(P_PEOPLE, pp); flash("Person added.", "success");
    } else flash("Name is required.", "warning");
    redirect("/people"); return;
  }
  pageStart("Finders");
  W("<section class=\"form-card\"><h2>Add finder</h2><form method=\"post\" class=\"stack\"><label>Name<input type=\"text\" name=\"name\" required /></label>");
  W("<label>Affiliation<input type=\"text\" name=\"affiliation\" placeholder=\"Local museum\" /></label><button type=\"submit\" class=\"button\">Save</button></form></section>");
  W("<section class=\"card\"><h3>Finders list</h3>");
  if (pp.as<JsonArray>().size()) {
    W("<ul class=\"list\">");
    for (JsonObject p : pp.as<JsonArray>()) {
      String af = p["aff"] | "";
      W("<li><strong>" + esc(p["name"] | "") + "</strong>" + (af.length() ? " <span>" + esc(af) + "</span>" : String("")) + "</li>");
    }
    W("</ul>");
  } else W("<p class=\"muted\">No finders yet.</p>");
  W("</section>"); pageEnd();
}

// ============================== setup / loop ==============================
void ensureDirs() {
  const char *dirs[] = {P_ROOT, P_E, P_UP};
  for (const char *d : dirs) if (!STORE.exists(d)) STORE.mkdir(d);
}
void listPartitions() {
  Serial.println("[boot] data partitions in the selected partition scheme:");
  esp_partition_iterator_t it = esp_partition_find(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, NULL);
  while (it) {
    const esp_partition_t *p = esp_partition_get(it);
    Serial.printf("[boot]   '%s'  subtype 0x%02x  %u KB\n", p->label, p->subtype, (unsigned)(p->size / 1024));
    it = esp_partition_next(it);
  }
  esp_partition_iterator_release(it);
}
void onWiFiEvent(WiFiEvent_t ev, WiFiEventInfo_t info) {
  switch (ev) {
    case ARDUINO_EVENT_WIFI_STA_CONNECTED: Serial.println("[wifi] associated with the router, waiting for an IP..."); break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP: Serial.printf("[wifi] got IP -> http://%s\n", WiFi.localIP().toString().c_str()); break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      Serial.printf("[wifi] not connected, reason %d (201 = SSID not found / 5 GHz only, 15 or 202 = wrong password, 2 = auth expired)\n", info.wifi_sta_disconnected.reason); break;
    case ARDUINO_EVENT_WIFI_AP_STACONNECTED: Serial.println("[wifi] a device joined the Archain access point"); break;
    case ARDUINO_EVENT_WIFI_AP_STADISCONNECTED: Serial.println("[wifi] a device left the Archain access point"); break;
    default: break;
  }
}
void printStatus() {
  Serial.printf("[status] storage: %s, free %u KB | AP '%s' http://%s", gFsName, (unsigned)(freeBytes() / 1024), AP_SSID, WiFi.softAPIP().toString().c_str());
  if (STA_SSID[0]) {
    if (WiFi.status() == WL_CONNECTED) Serial.printf(" | Wi-Fi '%s' http://%s", STA_SSID, WiFi.localIP().toString().c_str());
    else Serial.printf(" | Wi-Fi '%s' connecting (status %d)...", STA_SSID, (int)WiFi.status());
  }
  Serial.printf(" | AP clients: %d | heap %u KB | http://%s.local\n", WiFi.softAPgetStationNum(), (unsigned)(ESP.getFreeHeap() / 1024), HOSTNAME);
}
void setup() {
  Serial.begin(115200);
  for (unsigned long t = millis(); !Serial && millis() - t < 4000;) delay(10);   // USB CDC: wait for the monitor
  delay(200);
  Serial.println("\nArchain starting...");
  listPartitions();
  bool storageOk = false;
  const char *storageHint;
#if USE_SD
  storageOk = SD.begin(SD_CS_PIN);
  if (storageOk) { gFs = &SD; gFsName = "SD card"; }
  storageHint = "SD card init failed - check wiring and SD_CS_PIN.";
#else
  if (LittleFS.begin(true)) { gFs = &LittleFS; gFsName = "LittleFS"; storageOk = true; }
  else if (FFat.begin(true)) { gFs = &FFat; gFsName = "FFat"; storageOk = true; }
  storageHint = "No usable data partition - pick a Tools > Partition Scheme with SPIFFS or FATFS.";
#endif
  if (storageOk) { Serial.printf("[boot] storage mounted: %s\n", gFsName); ensureDirs(); }

  WiFi.setHostname(HOSTNAME);
  bool sta = STA_SSID[0] != 0;
  WiFi.mode(sta ? WIFI_AP_STA : WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS[0] ? AP_PASS : nullptr);
  WiFi.onEvent(onWiFiEvent);
  if (sta) {
    Serial.printf("[wifi] connecting to '%s' (2.4 GHz networks only)...\n", STA_SSID);
    WiFi.setAutoReconnect(true);
    WiFi.begin(STA_SSID, STA_PASS);
    configTzTime(TZ_INFO, "pool.ntp.org", "time.nist.gov");
  }
  MDNS.begin(HOSTNAME);

  if (!storageOk) {   // keep the board reachable and tell the user what is wrong
    Serial.println(storageHint);
    gFsName = "NONE";
    static String msg; msg = storageHint;
    server.onNotFound([]() { server.send(500, "text/plain", msg); });
    server.begin();
    return;
  }

  static const char *hdrs[] = {"Cookie"};
  server.collectHeaders(hdrs, 1);

  server.on("/", HTTP_GET, handleIndex);
  server.on("/map", HTTP_GET, handleMap);
  server.on("/login", HTTP_GET, handleLoginGet);
  server.on("/login", HTTP_POST, handleLoginPost);
  server.on("/logout", HTTP_POST, handleLogout);
  server.on("/setup", HTTP_GET, handleSetupGet);
  server.on("/setup", HTTP_POST, handleSetupPost);
  server.on("/static/styles.css", HTTP_GET, []() { server.sendHeader("Cache-Control", "max-age=86400"); server.send_P(200, "text/css", STYLES_CSS); });
  server.on("/weather", HTTP_GET, handleWeather);
  server.on("/entries/new", HTTP_GET, handleNewGet);
  server.on("/entries/new", HTTP_POST, handleNewPost, onUpload);
  server.on(UriBraces("/entries/{}/edit"), HTTP_GET, handleEditGet);
  server.on(UriBraces("/entries/{}/edit"), HTTP_POST, handleEditPost, onUpload);
  server.on(UriBraces("/entries/{}/delete"), HTTP_POST, handleDelete);
  server.on(UriBraces("/entries/{}"), HTTP_GET, handleDetail);
  server.on(UriBraces("/uploads/{}"), HTTP_GET, handleUploadGet);
  server.on("/directory", HTTP_GET, handleDirectory);
  server.on("/users", HTTP_GET, handleUsersGet);
  server.on("/users", HTTP_POST, handleUsersPost);
  server.on(UriBraces("/users/{}/profile"), HTTP_GET, handleProfileEditGet);
  server.on(UriBraces("/users/{}/profile"), HTTP_POST, handleProfileEditPost, onUpload);
  server.on(UriBraces("/users/{}/password"), HTTP_POST, handlePassword);
  server.on(UriBraces("/users/{}/edit"), HTTP_GET, handleUserEditGet);
  server.on(UriBraces("/users/{}/edit"), HTTP_POST, handleUserEditPost);
  server.on(UriBraces("/users/{}/delete"), HTTP_POST, handleUserDelete);
  server.on(UriBraces("/users/{}"), HTTP_GET, handleProfile);
  server.on("/people", HTTP_GET, handlePeople);
  server.on("/people", HTTP_POST, handlePeople);
  server.onNotFound([]() { server.send(404, "text/plain", "Not found"); });
  server.begin();

  printStatus();
}

void loop() {
  server.handleClient();
  static unsigned long last = 0;
  if (millis() - last > 10000) { last = millis(); printStatus(); }
  delay(1);
}
