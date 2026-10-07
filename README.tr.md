# Yan Masa

> İngilizce README: [README.md](README.md). Bu belge uzun hâli —
> her kararın arkasındaki ölçümlerle.

Yan masanda oturan bir bilgisayar kontrol ajanı. Ekranı Claude Opus 5'in
`computer_toolset_20260801` araç setiyle görüyor, fareyi ve klavyeyi ham Win32
`SendInput` ile sürüyor.

Adı buradan geliyor: ajanın **kendi masaüstü ve kendi imleci** var. Uzun bir
işi görünmez bir çalışma alanında yaparken senin faren, odağın ve
pencerelerin sende kalıyor — ikiniz aynı anda çalışabiliyorsunuz.

Yerel bir Qt (PySide6) masaüstü uygulaması — web katmanı, tarayıcı motoru ya
da HTTP köprüsü yok. Görsel dil Windows 11 Fluent; renkler ve tema kayıt
defterinden okunuyor, sabit palet yok.

Ayakta olanlar: yakalama, girdi, ajan döngüsü, ikinci imleç, UIA yan kanalı,
dosya araçları, kalıcı terminal oturumları, ofis belgeleri, yetenek yazma,
uzak makine paneli, güvenlik kapısı, acil durdurma ve Qt arayüzü. Ses hâlâ
yok — "Ne eksik, ne kırık" bölümü hepsini sayıyor.

## Neden bu mimari

Ekranı okuyan modeli biz yazmıyoruz. Claude'un computer araç seti GA ve
`claude-opus-5` destekliyor; `screenshot`, `zoom`, `left_click`, `type`, `key`
gibi 17 üye aracı var ve koordinatları modele gönderilen karenin piksel
uzayında. Bize düşen Windows tarafındaki el: kareyi yakalamak, sınırlara
sığdırmak ve modelin söylediği piksele gerçekten tıklamak.

Modelin kabul ettiği kare iki sınırın altında olmak zorunda: uzun kenar en
çok 2576 px **ve** görsel token sayısı en çok 4784 (28×28 piksel bir token).
Bu makinede iki adet 1920×1080 monitör var, yani sanal masaüstü 3840×1080.
Tüm masaüstünü tek kare olarak göndermek hem kenarı aşıyor hem token
bütçesini, o yüzden **monitör başına** yakalıyoruz; her kare 1920×1080, iki
sınırın da altında, küçültme yok, bu makinede koordinat matematiği tam 1:1.

Kural yine de koda gömülü değil: `model_kare_boyutu` her kareyi sınırlara
göre boyutlandırır ve tıklama çevirisi aynı fonksiyonu okur. 4K bir monitör
ya da yan masada büyük bir pencere takıldığında ölçek kendiliğinden girer —
sessizce yanlış yere tıklamak yerine hesaplanmış bir ölçekle.

Yerel bir görüntü modeli seçenek değil: bu makinedeki RX 560 (4 GB) üzerinde
OmniParser/Qwen-VL sınıfı bir model çalışmıyor.

## Arayüz

```
.venv/Scripts/pythonw.exe yanmasa.py
```

İki pencere açılır:

- **Ajan penceresi** — solda dar bir ray, sağda sayfalar. Dört sayfa hep
  orada: **Akış** (ajanın adım adım ne yaptığı), **Masa** (ajanın kendi
  masaüstünün canlı görüntüsü), **Geçmiş** (diskteki denetim kaydı, gün
  gün) ve **Akışlar** (kaydedilmiş iş dizileri). Altına ajanın açtıkları
  geliyor:
  tablo, yazı belgesi, kod, sunucu, yetenek panelleri. Bunlar
  `QDockWidget`'tı ve başlığa çift tıklayınca ayrı bir Windows penceresine
  çıkıyorlardı; ajan üç belge açtığında ekranda ne olduğunu kimse
  söyleyemediği için sayfalara geçildi. Gerekçe ve kaybedilen `app/ray.py`
  içinde yazılı.
- **Komut çubuğu** — ajanla konuşulan yer burası, ana pencere değil.
  Çerçevesiz, hep üstte, ekranın köşesinde yüzen bir çubuk. Dört parçası var:
  mikrofon, **yazı alanı** (ses kullanılamıyorsa tek çalışan giriş yolu),
  ajanın o an yaptığı işi gösteren **önizleme karesi** — eylem, hedef,
  gerekçe ve gerçek bir küçük resim — ve **maskot**. Sürüklenip taşınır,
  konumu `~/.ajan/bar.json` içinde kalır.

Fluent'e uymanın pratikteki anlamı `app/fluent.py`'de: renkler sistemden
okunuyor. Temayı açığa alırsan uygulama açılır, vurgu rengini değiştirirsen
uygulama onu alır. Sabit bir palet yazmak, Fluent olduğunu iddia edip tek
gerçek kuralını çiğnemek olurdu.

### Maskot ne yaptığını çizmiyor, yazıyor

Maskotun elinde nesneler vardı: dizüstü, mercek, sayfa, sunucu. Her biri kol,
el ve tutuş noktası hesaplayan bir kompozisyondu ve altı turda hiçbiri
iyi olmadı — 78 piksellik bir sahnede bir kol iki piksel, bir kalem bir
piksel ediyor. Sonunda nesneler tamamen kalktı (1180 kare ve on SVG silindi),
yerine bir **konuşma baloncuğu** geldi.

Bir baloncuk çizilen nesneden iki nedenle iyi. Belirsizlik yok: dizüstü çizimi
"ofis işi" diyebilir, `notlar.md yazıyor` tam olarak ne yaptığını söylüyor.
Ve ölçekten bağımsız: yazı 11 puntoda okunuyor, iki piksellik bir kol hiçbir
puntoda okunmuyor.

Yazı harf harf akıyor (42 harf/sn) ve akış bitince ucundaki imleç yanıp
sönmeye başlıyor — tersi olsaydı yanıp sönen imleç yazı durmuşken "devam
ediyor" derdi. Yeni bir iş geldiğinde baloncuk boşalmıyor, **ortak ön ek
korunup gerisi değişiyor**: `Dosya yazıyor: a.md` ile `Dosya yazıyor: b.md`
arasında gözün takip ettiği şey iş kalıyor, animasyon olmuyor. Baloncuğun
ölçüsü görünen harflerden değil **tam metinden** alınıyor; görünenden alsaydı
yazarken sağ kenar sürüklenir ve satır kırılımı harf sayısıyla oynardı.
İki satıra sığmayan yazı üç noktayla kesiliyor: `QTextLayout` fazlasını
sessizce düşürüyor ve kesildiğini söylemeyen bir baloncuk yalan söylüyor.

### Cevabın kendisi

Cevap `QLabel` değil, kendi düzenini kuran bir widget: imlecin son harfin
tam yanında durması gerekiyor ve `QLabel` satır kırılımını nereye koyduğunu
söylemiyor. Bunun bir bedeli var ve üçünü de ekranda gördüm.

**Paragraf başına bir düzen.** Tek bir `QTextLayout` bütün metni alıyordu
ve `QTextLayout` satır sonunu bilmiyor: `
` sıradan bir karakter, satır
kırılımını yalnızca sarma üretiyor. Sonuç "…(lightest).One caveat" gibi
birbirine yapışmış iki paragraf. Ölçtüm — iki paragraflı bir metin tek
satıra iniyordu. Boş satır tam satır değil yarım satır boşluk bırakıyor:
yüzen bir çubukta yer pahalı.

**Yıldızlar ekranda yok.** Model `**Reacher**` yazıyor. İşaretler metinden
çıkarılıp yerleri kalın olarak çiziliyor; ters tırnak içi kod da öyle.
İşaretleri saklayıp yalnızca çizimde gizlemek olurdu ama o zaman
kopyaladığın metinde yıldızlar kalırdı. Akış sırasında yarım kalan bir
`**` kendiliğinden çözülüyor: her parçada ham metinden yeniden
hesaplanıyor, kapanmayan işaret eşleşmiyor.

**Seçim yıkama, tabaka değil.** Vurgu dolu vurgu rengiyle çiziliyordu ve
seçili bir cevap okunmaz bir pembe tabaka oluyordu. Bir de kalıcıydı:
çubuğa yazmak için Ctrl+A'ya basmak dökümü seçiyor ve seçim ekranda
kalıyordu. Odak gidince kalkıyor.

Tavanı aşan döküm sona kaydırılıyor ve üstteki satır ortasından kesiliyor.
Kesik bir harf sırası bozuk çizim gibi okunuyor; oysa söylenmek istenen
"yukarıda devamı var". Üstte kartın rengine giden bir geçiş var ve
kaydırma sıfırdayken hiç görünmüyor — sığan bir dökümün üstüne gölge
koymak olmayan bir devamı ima etmek olurdu.

## Neye dikkat ettiğini söylüyor

Ajan bir uygulamanın içinde, hatası başkalarına görünecek ya da geri
alınması zor olacak bir şeye dokunmadan önce bir iki cümlelik not
yazıyor: *ileti #genel kanalına gidiyor, özel mesaja değil*. Talimat bir
seçimi açık bıraktıysa ve o seçmek zorunda kaldıysa da yazıyor: *hangi
hesap olduğunu söylemedin, daha önce konuştuğun olanı aldım.*

Not sadece not. Koşuyu durdurmuyor ve sana bir şey sormuyor, yani bir
karara mal olmuyor — asıl mesele de bu: durduran şey okunmadan
tıklanıyor, soran şey okunmadan cevaplanıyor. Adım satırından ayrı
çiziliyor: adım *ne yaptığını* söylüyor, not *neyin ters gidebileceğini*,
ve ikisini aynı biçimde çizmek notu otuz satırlık bir listede kaybetmek
olurdu.

Bu, ölçülen en büyük kusurun ucuz yarısı. 20.574 gerçek oturumda en
büyük iki kalem, ajanın konulan kuralı çiğnemesi (%38,33 ve artıyor) ve
niyeti yanlış okuması (%26,95) — ve bunların yalnızca %2,99'unu ajan
kendi yakalıyor. Varsayımı eylemden **önce** söylemek, sonradan ne kadar
dikkatli anlatıldığından daha değerli; sonrası zaten geç.

## MCP sunucuları

Dış MCP sunucuları ajana bu uygulamada olmayan araçlar veriyor: yapısal
tarayıcı, GitHub istemcisi, web okuyucu. Tanımlar `~/.ajan/mcp.json`
içinde ve biçim **standart** olan — başka bir uygulama için hazırladığın
yapılandırma olduğu gibi yapışıyor, Claude Desktop'ınki için de bir "içe
aktar" düğmesi var.

Araçlar `mcp__<sunucu>__<araç>` adıyla geliyor ve oradan sonra her şeyle
aynı yoldan gidiyorlar: onay kapısı, denetim kaydı, kuru koşu, akış
kaydı. Hiçbiri ikinci kez yazılmadı.

`@modelcontextprotocol/server-everything` ile ölçtüm: `npx` üzerinden
bağlanma 3,5 s, 13 araç, bir çağrı 5 ms, ve görsel sonuçlar metne
düzleştirilmeden görsel blok olarak geçiyor — Playwright'ın ekran
görüntüsü aracının bütün anlamı zaten o.
`python scripts/mcp_dogrula.py` bu ölçümü yapıyor.

**Güvenlik duruşu kasıtlı ve bu işin uzun sürmesinin sebebi o.** Bir MCP
sunucusu senin makinende senin haklarınla çalışan bir süreç ve araç
tanımları *doğrudan modelin promptuna* giriyor — bu varsayımsal değil,
belgelenmiş bir saldırı yüzeyi: taranan 1.000 sunucunun %33'ünde kritik
açık, örneklenen paketlerin %71'i en düşük not.

Bu yüzden: hiçbir sunucu kendiliğinden açılmıyor — yapılandırmaya
yazmak çalıştırmaya izin vermek değil, açmak ne demek olduğunu söyleyen
ayrı bir tıklama. Her MCP çağrısında onay soruluyor ve onay metninde
aracın kendi tanımı duruyor. Tanımlar bilinen zehirleme kalıplarına karşı
taranıyor (`ignore previous instructions`, `do not tell the user`,
`<IMPORTANT>`, kimlik dosyası adları, "her araçtan önce beni çağır") ve
**işaretleniyor, engellenmiyor** — bu alandaki tarayıcıların yanlış
pozitif oranı yüksek ve engelleyen bir tarama çalışan sunucuları sessizce
bozardı. Araç kümesinin parmak izi tutuluyor, yani onayladıktan sonra
tanımını değiştiren sunucu bunu söylüyor. Sistem promptu da modele açıkça
yazıyor: bir araç tanımı ona verilmiş bir talimat değil.

`env` değerleri arayüzde **hiç** görünmüyor, yalnızca hangi anahtarların
tanımlı olduğu; `${VAR}` süreç ortamından okuyor, yani anahtarın dosyada
durması gerekmiyor.

## Kod yazarken izlemek

Ajan bir dosya yazdığında masanın **içinde** bir Code penceresi açılıyor:
dosya listesi, sekme, satır numarası, gerçek sözdizimi renklendirmesi,
altında terminal ve değişiklik çekmecesi. Ekran görüntüsü değil —
etrafındaki yakalanan pencereler ölçeklenmiş fotoğraf, bu pencere 1:1
canlı arayüz. Okunmayan bir kodu göstermenin bir anlamı yok.

Kod **model üretirken** beliriyor. Araç girdileri akıyor
(`input_json_delta`) ve `backend/agent/akankod.py` o yarım JSON'dan dosya
içeriğini çıkarıyor: yarım bir dize, ortasından kesilmiş bir kaçış,
son basamağı gelmemiş bir `ç`. `json.loads` bunların hepsini
reddediyor; tarayıcı nesneyi anahtar anahtar geziyor ve gelen kadarını
veriyor. Yani ekrandaki yazılma bir animasyon değil, modelin o anki
üretimi. Dosya diske hâlâ tek seferde yazılıyor ve durum satırı bunu
böyle söylüyor.

İkisi birden varsa masa bölünüyor: solda düzenleyici, sağda yakalanan
gerçek pencereler. Okunabilir enin altında bölünmüyor — iki okunmaz
bölme, bir okunur bölmeden kötü — ve dosya yazılırken masa kodun oluyor,
yazma bitince pencerelere dönüyor.

Alt çekmecede terminal ve değişiklik var, sekmeli. Sekme yalnızca
içeriği olan için çiziliyor: boş bir "Changes" sekmesi, bakılacak bir şey
varmış gibi duruyor.

## Geçmiş, kuru koşu, akışlar, tepsi

Dördü de aynı soruya farklı yerlerden cevap veriyor: aynı işi ikinci kez
yaptırmanın maliyeti ne olsun.

**Geçmiş sayfası.** `runs/*.jsonl` zaten yazılıyordu ve okuyanı yalnızca
`rapor.py` ile tekrar tespitiydi; bakmanın tek yolu dosyayı elle açmaktı.
Sayfa onu geri okuyor: talimat, ajanın cevabı, adım adım araç çağrıları,
hatalar. Kesik kayıt üç yerinden tolere ediliyor — turu okunmayan günde
kalmış eylemler, `bitti` satırı hiç gelmemiş turlar, sahipsiz `bitti`
satırları. Desteksiz iddialar burada rozetle görünüyor; daha önce durum
çubuğunda bir kez parlayıp kayboluyordu.

**Kuru koşu.** Çubuktaki DRY anahtarı. Kesme kod tarafında: dünyayı
değiştiren her araç çalışmadan `[dry run]` dönüyor, ekran görüntüsü ve
dosya okuma çalışmaya devam ediyor ki plan gerçek duruma bakarak
yapılsın. Liste **beyaz liste** — bu depoya araç ekleniyor ve kara liste
olsaydı yarın eklenen bir aracın kuru koşuda sessizce çalışması
varsayılan davranış olurdu. Kuru turlar kayda işaretle giriyor ve düğme
önerisine hiç girmiyor.

**Akışlar.** Temiz biten bir işi ajana kaydettirebiliyorsun. Dünyayı
değiştiren adımlar kaydediliyor, bakma adımları düşüyor ve oynatma modele
hiç uğramıyor: düşünme yok, ekran görüntüsü yok, token yok. Tıklama
gerçek bir denetimin üstüne düştüyse o denetimin kimliği de kaydediliyor
(`AutomationId`, ad, tür, pencere) ve oynatırken denetim yeniden bulunup
o anki yeri kullanılıyor — pencere taşınmış olsa da çalışıyor. Denetim
bulunamıyorsa akış **duruyor**, kayıtlı koordinata tıklamıyor: denetim
gittiyse ekran kaydedilen ekran değil demektir ve orada artık başka bir
şey var.

**Tepsi ve global kısayol.** Tepsideki simge maskotun kendisi, duruma
göre renkli. Onay bekleyen ve durdurulmuş durumlar köşe rozetiyle
ayrılıyor: sistem vurgu rengi kullanıcının seçtiği bir şey ve bu makinede
`critical`'a yakın pembe — yalnızca gövde rengiyle ayırmak 16 pikselde
"çalışıyor" ile "durduruldu"yu aynı simge yapıyordu, çizip baktım.
Kısayol `Ctrl+Alt+Space`; doluysa sıradaki aday alınıyor (bu makinede
Ctrl+Alt+Y'ye düştü) ve hiçbiri boş değilse sebep durum satırında
yazıyor.

Menüde bir de **Start with Windows** kutusu var: kullanıcıya özel `Run`
anahtarı altında tek bir değer. `HKLM` de Zamanlanmış Görev de UAC
penceresi açtırıyor ve bir kutucuğu işaretlemenin bedeli yükseltme istemi
olamaz. Yazılan komut iki parçası da tırnaklı — kullanıcı adında boşluk
varsa tırnaksız komut sessizce hiçbir şey başlatmıyor. Kutu kaydın gerçek
hâlini gösteriyor: depo taşındıysa kayıt duruyor ama hiçbir şey
başlatmıyor, orada işaretli görünmek yalan olurdu.

## Kurulum

Proje kendi başına duruyor: dizini nereye kopyalarsan orada çalışıyor,
hiçbir çalışma alanı yöneticisine ya da dış depoya bağlı değil.

```
py -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
copy .env.example .env
```

Anahtarlar `.env` dosyasına girer. `.env` `.gitignore`'da — repoya asla
girmemeli. `ANTHROPIC_API_KEY` yoksa uygulama açılıyor ama çubukta
"Ajan kurulamadı" yazıyor; sessizce yarım çalışmıyor.

Ajanın kendine yazdığı yetenekler ve düğmeler depoda değil,
`~/.ajan/` altında: kendi yazdığı kod uygulamanın kaynağına karışmamalı ve
bir güncelleme onları silmemeli. `AJAN_STATE_DIR` ile taşınabiliyor.

## Çalıştırma ve doğrulama

```
.venv/Scripts/pythonw.exe yanmasa.py                          # uygulama
.venv/Scripts/python.exe -m pytest tests -q                # saf mantık, 654 test
.venv/Scripts/python.exe scripts/check_phase1.py           # yakalama, ekrana dokunmaz
.venv/Scripts/python.exe scripts/check_phase1.py --input   # Notepad'e Türkçe yazar
.venv/Scripts/python.exe scripts/masa_dogrula.py           # ajanın masası
.venv/Scripts/python.exe scripts/ajan.py                   # ajan, etkileşimli
.venv/Scripts/python.exe scripts/ajan.py "Not Defteri'ni aç"
```

`--input` ve `ajan.py` gerçekten fareyi ve klavyeyi sürüyor. Her an **Esc'ye
üç kez** basarak durdurabilirsin.

## Ajanın araçları

Computer araç seti fare ve klavyeyi veriyor. Üstüne on iki özel araç var:

| Araç | Ne için |
| --- | --- |
| `read_ui_tree` | Pencerenin denetimlerini tıklama noktalarıyla metin olarak verir. Ekran görüntüsünden çok daha ucuz ve koordinatları tahmin değil ölçüm. |
| `launch_app` | Uygulamayı doğrudan başlatır. Başlat menüsünde tıklatmak dört-beş tur sürüyordu. |
| `run_shell` | Tek atışlık PowerShell. Toplu dosya işleri ve sorgular. |
| `write_file` `read_file` `edit_file` `list_dir` | Dosya işleri. Her yerde UTF-8 — Windows'un cp1254 varsayılanı Türkçe metni sessizce bozuyor. |
| `terminal_open` `terminal_send` `terminal_read` `terminal_close` | Kalıcı terminal oturumları. |
| `office_open` `office_read` `office_edit` `office_save` `office_history` `office_close` | Kendi ofisimiz — gerçek .xlsx/.docx, Office kurulu olmadan. |
| `switch_display` | Hangi ekranda çalışılacağı. |

Sistem promptu ajana bir **araç merdiveni** veriyor: dosya işi için dosya
araçları, toplu iş için kabuk, etkileşimli program için terminal, uygulama
açmak için `launch_app`, bir şey bulmak için `read_ui_tree`, geriye kalan
her şey için ekran görüntüsü ve fare. Bir dosyayı Not Defteri'nde açıp
yazmak teknik olarak mümkün ama en pahalı yol.

Düşünme bütçesi adıma göre değişiyor: ilk adım `high` — yaklaşım orada
seçiliyor ve yanlış yaklaşım sonraki on adımı çöpe atar. Sonrası `medium`.
Bir eylem hata verdiyse ajan tıkanmış demektir, orada tekrar `high`.

## Kendi ofisimiz

Bu makinede Microsoft Office kurulu değil ve gerekmiyor. `office_*` araçları
gerçek `.xlsx` ve `.docx` üretiyor — Berkay dosyayı birine yolladığında karşı
taraf Excel'de açıyor. Fark dosya biçiminde değil, ajanın belgeye nasıl
eriştiğinde: bir arayüzü sürmek yerine hücre ve paragraf modeline doğrudan
yazıyor.

**Her düzenleme gerekçe taşır ve bu zorunlu bir alan.** `office_edit`
çağrısında `why` verilmezse değişiklik yapılmaz. İsteğe bağlı olsaydı model
çoğu zaman atlardı ve defter yarı dolu kalırdı; yarı dolu bir gerekçe defteri
hiç olmamasından kötüdür, çünkü güvenilir sanılır. `office_history` defteri
gösteriyor ve son N değişikliği geri alabiliyor — her kayıt önceki değeri de
tuttuğu için geri alma veri kaybetmiyor.

### Formüller

Formüller hesaplanıyor. Bu bir hata yüzünden yazıldı: ajan bir bütçe
tablosuna toplam formülü yazdı, sonra sonucun **21.290** olacağını söyledi.
Doğrusu 20.990'dı. Dosya doğruydu; yanlış olan ajanın kafadan yaptığı
toplama.

Şimdi `office_read` formül hücresini `=SUM(B1:B5) → 20990` diye gösteriyor
ve sistem promptu "ok işaretinden sonrakini kullan, kendin hesaplama" diyor.
Panelde de Excel'deki gibi: hücrede sonuç, formül çubuğunda formül.
Hesaplanamayan formül kırmızı kalıyor ve "N formül hesaplanamadı" yazıyor —
sıfır gösterip sonucu biliyormuş gibi yapmıyor.

Motor `formulas` 1.3.4. Pahalı olduğu için tabloda hiç formül yoksa hiç
çağrılmıyor, varsa defterdeki değişiklik sayısına göre önbelleğe alınıyor.

## Kendine yetenek yazmak

Ajan kendi araçlarını yazabiliyor. Bir işi ikinci kez aynı adımlarla
yaparken `skill_write` ile o işi bir araca çeviriyor; yazıldığı anda
yükleniyor ve bir sonraki adımda çağırıyor. Başka bir programın eklenti
sistemine bağlı değil — dosyalar `~/.ajan/yetenekler/`, sözleşme bir
`ARAC` sözlüğü ile `calistir(girdi, ortam)` fonksiyonu.

```python
ARAC = {
    "ad": "gun_farki",
    "aciklama": "Iki tarih arasindaki gun sayisi.",
    "girdi": {"bas": {"type": "string"}, "son": {"type": "string"}},
}

KOMUT = {"ad": "gun", "aciklama": "Gun farki", "talimat": "Su iki tarih arasini hesapla:"}

def calistir(girdi, ortam):
    from datetime import date
    return f"{(date.fromisoformat(girdi['son']) - date.fromisoformat(girdi['bas'])).days} gun"
```

`KOMUT` isteğe bağlı: çubuğa `/gun` yazınca o talimat gönderiliyor. `/`
yazdığın anda eldeki komutlar çubukta listeleniyor.

Sözleşmenin sert tarafları:

- **Bozuk yetenek gizlenmiyor.** Yüklenemeyen dosya sessizce atlanmıyor;
  hatasıyla listede duruyor. Sessizce atlamak, "yazdım" deyip hiç
  çalışmayan bir yetenek bırakmanın en kolay yolu.
- **Yarım kurulum yok.** Yükleme başarısızsa dosya eski hâline dönüyor.
- **Yerleşik araç adı ele geçirilemiyor.** Bir yetenek `run_shell` adını
  alıp kabuk çağrılarını üstlenemiyor.
- **Kapı yeteneğin içinde de devrede.** `ortam.kabuk("del /f /s /q ...")`
  yine Berkay'a soruluyor; yetenek yazmak kapıyı atlamanın yolu değil.
- **`.pyc` önbelleği devre dışı.** Kaynak doğrudan derleniyor. `importlib`
  bayt kodunu boyut ve zaman damgasıyla doğruluyor; tek karakterlik bir
  düzeltme (`+` yerine `*`) ikisini de değiştirmiyor ve düzeltilmiş dosya
  eski hâliyle çalışmaya devam ediyordu. Bir testte yakalandı.

## Ajan arayüze özellik ekleyebiliyor

Bir yetenek metin yerine **panel** döndürebiliyor: ana pencerede açılan,
ölçü/tablo/liste/günlük bölümlerinden oluşan gerçek bir arayüz.

Yetenek Qt kodu yazmıyor. Ne göstermek istediğini düz bir sözlükle
söylüyor, çizimi uygulama yapıyor:

```python
def calistir(girdi, ortam):
    return {"panel": {
        "baslik": "brky sunucu durumu",
        "bolumler": [
            {"tur": "olcu", "ogeler": [
                {"etiket": "Disk", "deger": "%68 dolu", "durum": "uyari"}]},
            {"tur": "tablo", "basliklar": ["Klasor", "Boyut"],
             "satirlar": [["/var/log", "4.4 GB"]]},
        ],
    }}
```

Ayrım kasıtlı ve üç somut sebebi var:

1. **Görsel dil korunuyor.** Ajanın eklediği panel uygulamanın geri
   kalanından ayırt edilemiyor: aynı Fluent renkleri, aynı yarıçap, aynı
   çizimler. Serbest Qt kodu her yetenekte biraz farklı görünen bir arayüz
   üretirdi.
2. **Arayüz thread'i düşmüyor.** Yetenek ajanın thread'inde çalışıyor;
   oradan widget kurmak Qt'de tanımsız davranış.
3. **Model de aynı şeyi görüyor.** Panel metne çevrilip ajana veriliyor;
   yoksa gösterdiği panelle çelişen bir cümle kurabilir.

Renkleri yetenek seçmiyor. `durum` alanına `iyi`, `uyari`, `kotu` ya da
`notr` yazıyor, rengi tema veriyor — açık temaya geçildiğinde ajanın
yazdığı hiçbir panelin düzeltilmesi gerekmiyor.

Tanınmayan bir bölüm türü sessizce atlanmıyor, hata olarak dönüyor: ajan
panelinin görünmediğini fark etmeli ki düzeltebilsin.

**Yapamadığı:** kendi sistem promptunu, güvenlik kapısını, modelini ve
pencere düzenini değiştiremiyor. Bunlar kodda ve bir kısmı kasıtlı — ajanın
kendi kapısını gevşetebilmesi, kapının olmaması demek.

## Discord eklentisi

`eklentiler/discord.py` — yetenek sisteminin gerçek bir işte kullanımı.
Bot API'si yok: ajan Discord'u senin gördüğün gibi görüyor ve senin
bastığın tuşlara basıyor, uygulamanın geri kalanıyla aynı yol.

**Neden klavye, neden erişilebilirlik ağacı değil:** ölçüldü. Discord
Electron ve UIA ağacı 33 düğüm döndürüyor — hepsi boş grup, tek satır metin
yok. `read_ui_tree` burada işe yaramıyor.

Ekran görüntüsü pahalı olduğu için eklenti gezinmeyi klavyeye yıkıyor.
`Ctrl+K` hızlı geçiş kutusu bir sunucuya, kanala ya da kişiye adını yazarak
gitmeyi sağlıyor; ajanın gözü yalnızca doğrulama için gerekiyor.

Korumalar, hepsi testli:

- **Discord ön planda değilse hiçbir tuş gönderilmiyor.** Bir kez öne
  getirmeyi deniyor, olmazsa duruyor. Yanlış pencereye giden tuş,
  başkasının sohbetine yazmak demek — bu projede bir kez oldu.
- **`yaz` göndermiyor.** Metni kutuya koyuyor; ajan ekrandan doğru kişide
  olduğunu doğruluyor, sonra `gonder` çağırıyor ve o adımda Berkay'a
  soruluyor.
- **Satır sonu içeren metin reddediliyor.** Discord'da Enter mesajı
  gönderir; çok satırlı bir metin yarısını erkenden yollardı.
- **Arama sonrası bekleniyor.** Yazdıktan hemen sonra Enter, liste henüz
  güncellenmediği için **önceki** sonuca gidiyor — yanlış kişiye mesaj
  yazmanın en kolay yolu.
- **Açılışta doğru monitöre geçiliyor.** Discord ikinci ekrandayken ajan
  birinciye bakıp onu hiç göremiyordu.

Sesli kanaldan ayrılmanın klavye kısayolu yok; eklenti bunu uyduracağına
söylüyor ve ajanın görüp tıklamasını istiyor.

## Düğmeler

Yetenek ajanın kullandığı araç; düğme Berkay'ın kullandığı kısayol. Düğme
çubukta duruyor, tıklanınca hazır bir talimat gidiyor.

İkisi de kurabiliyor. Ajan tekrar eden bir iş fark ettiğinde `button_write`
ile öneriyor — onaysız kurulmuyor, çünkü düğme Berkay'ın arayüzünü
değiştiriyor. Berkay artıya basıp Python yazmadan kendisi ekliyor: etiket,
talimat, çizim. Ajanın kurduğu düğme Berkay'ın düzenleyemediği bir şey
değil; ikisi de aynı `~/.ajan/dugmeler.json` dosyasına yazıyor.

Düğmeler yeteneklerden ayrı dosyada tutuluyor çünkü ömürleri farklı:
yetenek kod, düğme tercih. Bir yeteneği silmek onu çağıran düğmeyi
silmiyor.

Bozuk bir `dugmeler.json` uygulamayı açılmaktan alıkoymuyor — okuma hiçbir
durumda istisna fırlatmıyor, eksik alanlı kayıt atlanıyor, gerisi kalıyor.

## Uzak makine

Sunucu, uygulamanın bir paneli olarak açılıyor: klasörler bir listede, yol
tıklanabilir kırıntılarda, dosyalar boyutu ve tarihiyle. Terminalde `ls`
yazıp nerede olduğunu aklında tutmak yerine, Dosya Gezgini'nde ne
bekliyorsan o.

Bağlantı Windows'un kendi `ssh.exe`'siyle, bir Python SSH kütüphanesiyle
değil: `~/.ssh/config` içindeki takma adlar ve anahtarlar zaten orada.
`brky` diye bir takma adın varsa burada da `brky` yazıyorsun.

Dizin listesi `ls -l` ayrıştırılarak değil `find -printf` ile alınıyor.
`ls -l` çıktısı yerel dile göre değişiyor, boşluklu dosya adlarında
sütunları kaydırıyor ve tarih biçimi dosyanın yaşına göre farklılaşıyor.

Ajan da aynı oturumu kullanıyor — sen bağlanırsan o da bağlı oluyor. İki
ayrı bağlantı tutmak, panelde bir yeri gezerken ajana başka bir yerden
bahsetmek demekti.

**Uzak güvenlik kapısı yereldekinin tersi.** Yerelde yasak listesi:
tehlikeli kalıplar aranıyor, gerisi geçiyor. Uzakta izin listesi: yalnızca
okuyan komutlar sorgusuz geçiyor, tanımadığımız her şey soruluyor. Sebebi
somut — yerelde yanlış giden bir komut Berkay'ın kendi dosyası, sunucuda
aynı komut çalışan bir servisi düşürüyor.

Parola ile giriş yok ve arayüzde bu yazıyor: parolayı programdan beslemek
için onu bir yerde tutmak gerekirdi.

Panelden silme ve taşıma yapılamıyor. Yanlış klasörde yapılan bir
sağ tık > sil, sunucuda geri alınamaz.

## İkinci imleç

Ajan ekran görüntüsü alıp fareye dokunduğu anda bilgisayarı işgal ediyor:
imleç onun, odak onun, Berkay bekliyor. `side_*` araçları bunun paraleli.

Windows'un masaüstü nesnesi ikinci bir çalışma alanı veriyor — kendi pencere
listesi, kendi odak zinciri, kendi imleç konumu. `CreateDesktopW` ile
açılıyor, uygulamalar `STARTUPINFOW.lpDesktop` ile oraya doğuruluyor. Girdi
`SendInput` ile değil, pencerelere doğrudan gönderilen iletilerle veriliyor;
`backend/computer/mesaj.py` içinde imleci oynatabilecek tek bir çağrı yok ve
bir test bunu kaynağa bakarak doğruluyor.

Ölçüldü, hem klasik Win32'de (`charmap.exe`) hem Chromium'da (Chrome):

| ne | nasıl | doğrulama |
|---|---|---|
| yazma | `WM_CHAR` | `ağır işçi ÖĞÜŞ 42` birebir geri okundu |
| tıklama | `WM_LBUTTON*` | açılır liste 0→1; sayfa kırmızıdan yeşile |
| yakalama | `PrintWindow` | 1100×760, gerçek içerik |
| fiziksel imleç | — | koşu boyunca hiç çağrılmadı |

Bir defekt ölçüm sırasında çıktı: `TerminateProcess` yalnızca başlatılan
süreci öldürüyordu ve Chrome'un onlarca çocuk süreci hayatta kalıyordu.
Sonucu iki katmanlıydı — görünmez masaüstünde görünmez Chrome birikiyor, ve
profil kilidi ayakta kaldığı için bir sonraki açılış eski örneğe devredip
tıklamayı hiçbir yere ulaştırmıyordu. Beş koşudan biri bu yüzden
başarısızdı. İş nesnesi (`KILL_ON_JOB_CLOSE`) ile düzeltildi: sonraki beş
koşu 5/5, ayakta kalan süreç 0.

Yan alanın karesi arayüzde görünüyor ve ajanın imleci karenin üstüne
çiziliyor — arkasında son sekiz konumdan geçen bir iz var, yani nereye
tıkladığı değil **nereden geldiği** de tek karede okunuyor. İlk çizim
maskotun rengiyle kontursuzdu ve açık zeminde 1.2:1 kontrastla kayboluyordu;
ok artık koyu bir kılıf içinde.

Kare modele **gitmiyor**. Her eylemde görsel göndermek tur başına ~1500
token ve model zaten nereye tıkladığını biliyor; bilmeyen Berkay.

Üç sınır, `side_launch` açıklamasında ajana da söyleniyor: Mağaza
uygulamaları orada pencere açmıyor (Win11 Not Defteri dahil), kısayol
kombinasyonları (`Ctrl+S`) çalışmıyor çünkü değiştirici tuş başka bir iş
parçacığında basılı görünmüyor, ve sürükle-bırak yok.

`python scripts/ikinci_imlec_dogrula.py` bunu uçtan uca ölçüyor.

### Yan masanın videosu

Ekran görüntüsü ajanın nerede durduğunu söylüyor, ne yaptığını değil.
`record_start` / `record_stop` yan masadaki bir pencereyi `runs/<koşu>/`
altına mp4 olarak kaydediyor; paylaşılabilir bir dosya çıkıyor.

ffmpeg süreci `STARTUPINFOW.lpDesktop` ile **yan masaüstünde** doğuyor.
`subprocess` bu alanı hiç açmıyor ve normal bir `ffmpeg -i desktop`
Berkay'ın ekranını kaydederdi — yanlış ekranı, üstelik doğru görünen bir
dosya üreterek.

Ölçüldü, varsayılmadı (`python scripts/dogrula_kayit.py`): yan masaüstünde
`-i desktop` hiç çalışmıyor, ffmpeg "Failed to capture image (error 5)"
diyip ölüyor. Sebep `masaustu.py`'deki gerçeğin aynısı — Windows yalnızca
**girdi masaüstünü** çiziyor, etkin olmayan bir masaüstünün ekran yüzeyi
yok. `-i hwnd=` ise çalışıyor: charmap penceresi 43 karede, gerçek
içerikle. Bedeli kayıt başına tek pencere ve bu gizlenmiyor, aracın
tanımında modele de yazıyor.

Durdurma ffmpeg'in stdin'ine `q` yazıyor ve bekliyor. Öldürmek son çare:
sert öldürülen ffmpeg `moov` atomunu yazamıyor ve geriye açılmayan bir
mp4 kalıyor. Koşu biterken, uygulama kapanırken ve Esc ×3'te kayıt
kapanıyor — üçünde de arkada süreç kalmıyor. Kayıt sürerken durum
şeridinde yanıp sönen kırmızı bir nokta, geçen süre ve bir durdurma
düğmesi duruyor.

Kuru koşuda **engelli**: kayıt dosya yazıyor ve `kuru.py` izin listesine
girmiyor.

### Ajanın masası

Yan alan görünmezdi: `side_capture` yalnızca ajan bir eylem yaptığında kare
veriyordu, arada ekran donuyordu ve "şu anda ne oluyor" sorusunun cevabı
yoktu.

`app/masa.py` o cevap. Gizli masaüstündeki bütün pencereleri saniyede sekiz
kez yakalayıp gerçekten durdukları yere koyuyor, üstünde ajanın imleci
geziyor. Ölçüldü: 1100x760 bir Chrome penceresi kare başına 54 ms, yani
tavan ~18 fps. Sekizde kalmak bilinçli — bu döngü ajanın kendi işiyle aynı
makinede dönüyor ve öncelik onun. Yakalama kendi thread'inde ve pencere
gizlenince duruyor.

**Linux Mint gibi görünüyor ve sebebi var.** Baktığın şey senin masaüstün
değil. Windows gibi görünseydi her göz atışında hangi ekrana baktığını
çözmen gerekirdi; başka bir işletim sisteminin kabuğu tek bakışta "burası
başka bir yer" diyor. Renkler, panel, başlık çubukları ve duvar kâğıdı
burada sıfırdan çiziliyor — Mint'in duvar kâğıtları, logosu ve simgeleri
onların ve bu depoda yok.

Başlık çubuklarında kapat/küçült düğmesi yok. Salt okunur bir görüntüde
çalışmayan bir düğme yalan; yerine başlık ajanın hangi pencerede olduğunu
söylüyor, ki insanın gerçekten merak ettiği bu. Panelde iki gerçek düğme
var. **Duraklatma** gerçek bir iş yapıyor: yakalama kare başına 54 ms ve
sen bakmıyorken o payı ajana bırakmak doğru. **Yakınlaşma** masaüstünün
tamamı ile pencerelerin ortak kutusu arasında geçiyor — 1920x1080'i bir
sayfaya sığdırmak 0.57 ölçek demek ve 980 piksellik bir tarayıcı 560'a
inince içindeki yazı okunmuyor. İkisi de doğru; hangisine baktığın
panelde yazıyor.

Panel **üstte**, Mint'te altta duruyor. Masa artık uygulamanın bir sayfası
ve altta uygulamanın kendi durum şeridi var; ikisi alt alta gelince aynı
işi yapan iki çubuk oluyordu.

Duvar kâğıdı bir pixmap'e önbelleklenip yalnızca boyut değişince yeniden
çiziliyor. Düz bir geçişten fazlası olmasını ödeyen şey bu: iki ışık
kaynağı, dört yumuşak bant, vinyet ve gren. Büyük ve karanlık bir geçiş 8
bitlik kanalda bantlaşıyor ve o şeritleri kıran şey gren; ekranda
"kaliteli" görünen şeyin çoğu aslında o. Gren deterministik, yani aynı
durumun iki ekran görüntüsü birebir aynı çıkıyor ve bir gerileme
karşılaştırılarak yakalanabiliyor.

`python scripts/masa_dogrula.py` gizli masaüstünde gerçek uygulamalar açıp
kareyi `varliklar/onizleme/masa.png` dosyasına yazıyor.

![Ajanın masası](varliklar/onizleme/masa.png)

## Uygulama çeşitliliği

`launch_app` yalnızca PATH'e bakıyordu. Ölçüldü: on yedi yaygın uygulamadan
**on ikisi** bulunamıyordu — Discord, Chrome, Spotify, Telegram, Steam,
Firefox, WhatsApp… Ajan bunları açmak için ya tam yolu bilmek ya da Başlat
menüsünde tıklayarak gezinmek zorundaydı; ikincisi dört beş ekran görüntüsü.

Artık bir katalog var: **162 uygulama**, üç kaynaktan — Başlat menüsü
kısayolları (126), `App Paths` kayıt defteri (14) ve Mağaza uygulamaları
(22). İlk tarama 1.7 saniye, sonrası önbellekten.

Kısayolun hedefi çözülmüyor, `.lnk` doğrudan açılıyor: çalışma dizini,
argümanlar ve simge zaten onun içinde ve elle çıkarmak onları kaybetmek
olurdu.

Yazım hatası sessizce başka bir uygulamaya çözülmüyor — bu, ajanın
istenmeyen bir program açması demek olurdu. Ama öneri veriliyor:
`spotfy` → "Bunlar olabilir: Spotify". `list_apps` ile ajan kurulu
uygulamalara bakabiliyor.

## Anlık kod dosyaları

`write_files` birden çok dosyayı tek çağrıda yazıyor. Dosya başına ayrı
çağrı, dosya başına ayrı **model turu** demekti; dört dosyalık bir proje
dört fazladan tur harcıyordu.

Ölçüldü: dört dosyalık bir Python projesi kurmak ve betiği çalıştırmak
**3 tur, 52 saniye**. Klasörler kendiliğinden açılıyor.

Üzerine yazma tek seferde soruluyor, dosya başına değil: on dosyalık bir
projede on kere sormak, okumadan onaylamaya götürür. Reddedilirse hiçbir
dosya yazılmıyor.

Yazılan dosya arayüzde **kod paneli** olarak beliriyor — sözdizimi
renklendirmeli, satır sayısı ve tam yoluyla. "yazıldı" demek yetmiyor; ajan
diske kod koyuyor ve görmeden ona güvenmen gerekiyor.

Renklendirme sözdizimi ağacı kurmuyor, düzenli ifadeyle çalışıyor — bir
görüntüleyici için doğru olan bu. Renkler temadan geliyor; kod
renklendirmesi genelde kendi paletini getirir ve uygulamanın içinde yabancı
durur.

## Hız

Bir iş 38 saniye sürüyordu, aynı iş şimdi 14 saniye. Tahmin edilmedi,
ölçüldü — ve tahminlerin ikisi de yanlış çıktı.

| | önce | sonra |
|---|---|---|
| toplam | 38.4 sn | 13.9 sn |
| araçlar | 17.2 sn | 0.2 sn |
| model | 21.2 sn | 13.7 sn |

Dört değişiklik:

**Açık uygulamayı yeniden başlatma.**  **25 saniye** sürüyordu.
Pencere zaten açıkken öne getirme başarısız olunca başlatma yoluna
düşüyordu;  yeni bir pencere bekleyip 10 saniye zaman aşımına
giriyor, üstüne eklentinin kendi beklemeleri biniyordu. Pencere varsa artık
hiç başlatılmıyor: **4 ms**.

**Ön plana getirme gerçekten çalışsın.** Windows ön plan hırsızlığını
engelliyor;  çağrıların çoğunda sessizce yok
sayılıyordu ve ajan pencereyi açamayıp turlarca deniyordu.
 ile ön plandaki thread'e geçici bağlanınca 5/5 başarı,
her biri ~20 ms.

**Kare biçimi WebP kayıpsız.** Ölçüm iki monitörde:

| biçim | base64 | kodlama |
|---|---|---|
| PNG compress=1 | 632–1843 KB | 40–94 ms |
| WebP kayıpsız m=0 | 315–795 KB | 71–241 ms |
| WebP kalite 90 | 264–308 KB | 87–89 ms |

Kayıpsız seçildi. Kayıplı biçim daha küçük ama ajanın okuduğu şey küçük
yazı; yanlış okunan bir etiket yanlış tıklama demek ve bunun maliyeti
birkaç yüz kilobayttan yüksek.  daha da küçültüyor ama aynı
karede 910 ms sürüyor — her adıma binen 700 ms buna değmiyor.

**Önbellek noktası doğru yere.** Nokta computer araç setinin üstündeydi ve
bir nokta yalnızca kendisine kadar olanı kapsıyor: arkasındaki 28 özel araç
(~3700 token) ile sistem promptu (~2450 token) her istekte yeniden
işleniyordu. Nokta son statik aracın üstüne alındı ve sistem promptu
önbelleklenebilir blok yapıldı — her adımda **16.100 token önbellekten**
geliyor. Yetenekler noktadan sonra kaldığı için yeni yetenek yazmak
önbelleği bozmuyor.

Ayrıca sistem promptuna hız bölümü eklendi: birbirini izleyen eylemleri tek
turda gönder, metin sonucu yeten yerde ekran görüntüsü alma, bitirirken tek
cümle yaz.

## Ajanın kendi kaydı

Topluluk ve literatür agentic araçlarda üç kusuru tekrar tekrar ölçüyor, ve
üçünün ortak kökü şu: ajanın ne yaptığına dair diskte hiçbir şey yok.

- Computer-use ajanlarının eylemlerinin **%56.7'si yanlış elemanı**
  hedefliyor; hatanın %10'u hiçbir şeye denk gelmeyen tıklama.
- IDE ajanlarında en sık üç kusur keşfetmeden düzenlemeye başlamak (%63),
  ileri geri savrulma (%28.2) ve bağlam kaybı (%27.6).
- 20.574 gerçek oturumluk analizde görünür çözümlerin **%91.49'u**
  kullanıcının elle düzeltmesini gerektiriyor, ve oransal olarak **artan**
  kusurlardan biri ajanın **yapmadığı işi yaptım demesi**.

`backend/agent/kayit.py` her turu ve her eylemi `runs/<gün>.jsonl` dosyasına
yazıyor. Üstüne iki şey kuruldu.

**Doğrulanmış rapor.** Ajan "dosyayı yazdım" dediğinde o turda gerçekten bir
yazma aracı çalışmış mı diye bakılıyor. Çalışmamışsa durum satırına "bu
oturumda dosya yazma kaydı yok" düşüyor. Cevabın içine değil: cevap ajanın
sözü, bu ona dair bir gözlem.

Tek gerçek risk yanlış alarm — her cevabın altında haksız bir uyarı çıkarsa
insan uyarıyı okumayı bırakır ve o noktada gerçek olanı da kaçırır. Dört
kademe var: iddia kalıpla aranıyor ("kaydettim" iddia, "kaydedebilirim"
değil), soru ve olumsuz cümleler eleniyor, bu turda destek yoksa oturumun
tamamına bakılıyor, ve kalıplar kelimeden üretiliyor — elle yazarken
`çalıştırdım`ı yazıp `calistirdim`i kaçırmıştım.

**Tekrar eden işi otomatikleştirme.** Aynı araç dizisi üç kez **hatasız**
tamamlandığında talimatın sonuna bir not düşüyor ve ajan `button_write` ile
düğme öneriyor. Bu daha önce sistem promptunda bir cümleydi — modelin
hatırlamasına bırakılmıştı, ve otuz adımlık bir turun sonunda model "bunu
üçüncü kez yapıyorum" demiyor. Artık sayan taraf kod.

İmza turun araç dizisi, talimat metni değil: aynı işi iki kez birebir aynı
cümleyle istemiyorsun. Ardışık tekrarlar sadeleşiyor, yani dört dosya yazmak
ile beş dosya yazmak aynı iş. Tökezleyerek biten turlar sayılmıyor — üç kez
tökezleyen bir işi otomatikleştirmek, tökezlemeyi otomatikleştirmek olurdu.

Kayda dosya gövdeleri ve yetenek kodu **girmiyor**; anahtar deseni taşıyan
alanlar `[gizlendi]` yazılıyor. Bir denetim kaydının kendisi sızıntı kaynağı
olmamalı.

## Güvenlik

Üç katman, üçü de bağımsız:

1. **Sistem promptu** ajana nerede duracağını söyler (UAC, şifre, ödeme,
   silme, mesaj gönderme).
2. **`safety/gate.py`** komutu desen eşleştirmeyle sınıflandırır ve riskliyse
   onay ister. Prompt'a değil koda gömülü, çünkü prompt bir öneri, kapı bir
   mekanizma. Onay kancası bağlanmamışsa varsayılan **red**.
3. **`safety/killswitch.py`** Esc ×3 ile döngüyü keser. Ayrı thread'de
   yoklama yapıyor, ajan ne yaparsa yapsın cevap verir.

Kapsam sınırı: bu bir kum havuzu değil. Kararlı bir saldırgan desenlerin
etrafından dolaşır. Amaç, iyi niyetli bir ajanın geri alınamaz bir şeyi fark
etmeden yapmasını engellemek.

## Ne eksik, ne kırık

Bir README'de en işe yarayan bölüm bu.

- **Ses yok.** Gemini kullanılacak, API anahtarı henüz yok. Mikrofon
  düğmesi ve üç durumu hazır ama arkasındaki motor bağlı değil; arayüz bunu
  gizlemiyor, durum satırında yazıyor.
- **Yetenek kodu için kum havuzu yok.** `skill_write` ile kurulan kod bu
  süreçte, tam yetkiyle çalışıyor: `import os` yazıp güvenlik kapısını
  dolaşabilir. Koruma tek katman — her kurulum Berkay'ın onayını istiyor ve
  kodun tamamı onay ekranında gösteriliyor. Gerçek bir kum havuzu (ayrı
  süreç, kısıtlı içe aktarma) yazılmadı.
- **Açık tema denenmedi.** `fluent.py` iki temayı da üretiyor ama yalnızca
  koyu tema render edilip ölçüldü.
- **Belgeler salt okunur.** Tabloya ve yazı belgesine bakabiliyorsun, hücre
  seçebiliyorsun, formül çubuğu gerçek içeriği gösteriyor — ama
  düzenleyemiyorsun. Düzenlemeyi şu an sadece ajan yapıyor.
- **Maskotun silueti bize ait değil.** `varliklar/kaynak/bloub.svg`
  Berkay'ın verdiği bir çizim ve lisansı belirsiz; pozların hepsi ondan
  türüyor. Kendi siluetimizi çizmeyi denedim, karakteri tutmadı.
  Yeniden kullanacak biri için bu bir engel.
- **Denetim kaydı hiç budanmıyor.** `runs/` sonsuza kadar büyüyor ve
  kimse silmiyor. Tekrar tespiti son 14 güne bakıyor ama dosyalar
  duruyor.
- **Ajanın masası salt okunur.** Canlı izleyebiliyorsun ama içine
  tıklayıp yazamıyorsun; yan alana elle müdahale hiç yazılmadı.
- **MCP'nin yalnızca *araç* tarafı destekleniyor.** Kaynak (resource),
  prompt, sampling, roots ve elicitation yok. İnsanların gerçekten
  kullandığı sunucuların çoğu araç sunucusu; gerisi henüz yüzey alanına
  değmedi.
- **HTTP MCP sunucularında OAuth yok.** Adresle verilen sunucuya düz
  bağlanılıyor; OAuth isteyen bir sunucu bağlanmıyor.
- **MCP sunucuları kum havuzunda değil.** Senin haklarınla çalışan sıradan
  alt süreçler. Onay kapısı *ajanın* onlardan ne istediğini yönetiyor,
  sunucunun kendi başına ne yaptığını değil.
- **Her MCP çağrısında onay yorucu, bilerek.** Alternatifi araç başına
  onayı hatırlamaktı ve oradaki kusur, onayladıktan sonra değişen bir
  tanım. Yorarsa ödenen bedel bu — söyle, yeniden konuşulur.
- **Kurulum paketi yok.** Dizin nereye kopyalanırsa orada çalışıyor.
- **Akış oynatmada model yedeği yok.** Kaydedilmiş bir denetim
  bulunamayınca akış duruyor ve hangi adımda durduğunu söylüyor. Plandaki
  hâli o adımı modele devredip düzeltilmiş koordinatı kayda geri
  yazmaktı; o yazılmadı. Durmak bunun güvenli yarısı.
- **Akış imzası her zaman alınamıyor.** `ControlFromPoint` oyunlarda ve
  yükseltilmiş pencerelerde erişim reddiyle düşüyor — ölçtüm, önde bir
  oyun varken bütün noktalar düştü. O adımlar imzasız kaydediliyor ve
  kayıtlı koordinatla oynanıyor; pencere taşınırsa kırılıyorlar.
- **`write_files` akmıyor.** Bir dizi taşıyor ve dizinin içinde hangi
  dosyanın yazıldığını anlamak tarayıcıyı iki kat karmaşık yapardı. O
  araç tek seferde küçük dosyalar yazıyor; kod sayfası sonrasında
  hepsini gösteriyor.
- **Masadaki Code penceresinde geriye kaydırma yok.** Dosya yazılırken
  imleci takip ediyor. Sonradan düzgün okumak için raydaki Code sayfası
  var.
- **Geçmiş sayfası canlı takip etmiyor.** Kaydı açılışta ve "Refresh"e
  basınca okuyor. Her satırda iki haftalık JSONL'i yeniden okumak,
  bakılmayan bir sayfa için sürekli iş olurdu.
- **Uygulamanın kendi penceresi ekran görüntüsünden çıkarılmıyor.** Ajan
  kendi arayüzünü görebiliyor.
- **Ofisin arayüzü yok.** Ajan belgeyi yazıyor, sen Excel'de açıp bakıyorsun.
  Canlı ortak düzenleme ve canlı veri kaynağı arayüze bağlı, Faz 5'ten sonra.
- **Sunum (.pptx) yok.** Kütüphane çalışıyor, araç yazılmadı.
- **Yazı belgesinde ekleme geri alınamıyor.** python-docx'te paragraf silmek
  XML ağacına inmeyi gerektiriyor; yarım çalışan bir geri alma tehlikeli
  olacağı için hiç yapılmadı ve bu açıkça söyleniyor.
- **Terminal ekranı 120x40 sabit.** Daha geniş bir TUI kırpılır; ekran
  boyutu henüz araçtan ayarlanamıyor.
- **Terminalde kaydırma geçmişi yok.** Ajan yalnızca o anki ekranı görüyor;
  yukarı kayan çıktı kaybolur.
- **Uzun metin yazmak yavaş.** Karakter başına ~12 ms; 500 karakter 6 saniye.
  Panoya yazıp `Ctrl+V` daha hızlı ama kullanıcının panosunu eziyor.
- **Yakalama kendi penceremizi dışlamıyor.** Arayüz gelince ajan kendi
  ekranını okuyup geri besleme döngüsüne girer. Faz 5'te çözülecek.
- **`run_shell` çıktısı 8000 karakterde kesiliyor.** Kesildiği söyleniyor ama
  sayfalama yok; uzun çıktılı bir komut eksik okunur.
- **UAC diyaloğu erişilemez.** Güvenli masaüstünde çıktığı için ne
  yakalanabilir ne tıklanabilir. Ajan orada durup insandan istiyor.
- **Anti-cheat.** `SendInput` DirectInput yakalayan oyunlarda çalışmaz.
- **UIA her yerde çalışmaz.** Tuval, oyun, video, bazı web sayfaları boş ağaç
  verir. `read_ui_tree` bunu bildiriyor ve model ekran görüntüsüne dönüyor.

## Geliştirirken öğrenilenler

Beşi de gerçek koşuda çıktı, hepsi koda gömülü:

**Girdinin hedefi yoktur.** `type_text` ve `press` nereye yazdıklarını
bilmezler — o an odakta ne varsa oraya giderler. İlk doğrulama koşusunda
Notepad öne gelmedi ve test metni ikinci ekrandaki bir tarayıcı sekmesine
düştü, ardından gelen `Return` mesajı gönderdi. `computer/windows.py` bu
yüzden var: her klavye eyleminden önce `assert_foreground`.

**Toplu gönderim karakter yer.** İlk `type_text` 24 karakteri tek `SendInput`
çağrısında topluyordu. Kısa dizelerde kusursuz görünüyordu; 55 karakterlik
gerçek bir metin hedefe **39 karakter** olarak düştü, arada kalanlar `…` oldu.
Olaylar hedefin mesaj kuyruğunun tükettiğinden hızlı geliyordu. Şimdi karakter
başına bir çağrı, arada 12 ms.

**Boş yere uyaran bir kapı, kapı değildir.** Güvenlik kapısının ilk sürümü
`format` deseni arıyordu ve PowerShell'in en sık kullanılan salt-okunur
cmdlet'i **`Format-List`** ile eşleşiyordu. Bir dosya listeleme komutuna
"diski biçimlendiriyor" diye onay istedi. Sürekli yanlış alarm veren bir kapı
görmezden gelinir ve o noktada hiç kapı olmamasından kötüdür. Desen artık dar:
`format C:` ve `Format-Volume` yakalanıyor, `Format-List` geçiyor.

**Sessizce takılan bir el sıkışma.** Terminal oturumları ConPTY ile açılıyor.
ConPTY açılışta `ESC[c` (cihaz öznitelikleri) gönderip **cevap bekliyor**;
cevaplamazsan prompt hiç yazılmıyor. Oturum canlı, süreç çalışıyor, hata yok
— ekran sonsuza kadar boş. İlk düzeltme fazla cevap verdi: `ESC[1t` bir sorgu
değil terminale verilen bir komut ve ona cevap yazmak `[8;40;120t` dizisini
kabuğa yazılmış bir tuş dizisi olarak gönderdi, komut satırına düştü.
Yalnızca gerçek sorgular cevaplanmalı.

**Katı şema bir bütçedir.** Her araca `strict: True` koymuştum. Tek tek
hepsi geçiyordu, on sekizi birden "Schema is too complex" ile 400 dönüyordu:
katı şemalar kısıtlı bir gramere derleniyor ve toplam gramer boyutunun sınırı
var. Ölçüldü — 12 katı + 6 gevşek geçiyor, 18 katı geçmiyor. Katılık
kaldırıldı; doğrulama zaten dispatch tarafında ve modele düzeltmesi kolay
hata dönüyor. Bu sınır araç sayısıyla değil şema boyutuyla ilgili, yani yeni
araç eklerken sessizce geri gelebilir.

Beşi de yalnızca uçtan uca, gerçek bir hedefe karşı çalıştırınca ortaya çıktı.
Birim testler hiçbirini yakalayamazdı — ama hepsinin regresyon testi ya da
kodda gerekçesi artık yerinde.

## Yapı

```
backend/
  config.py             .env okuma; anahtarlara dokunan tek yer
  computer/
    displays.py         monitör envanteri, sanal masaüstü <-> ekran çevirisi
    capture.py          mss ile monitör başına PNG, zoom için kırpma
    input.py            SendInput: mutlak fare, unicode klavye
    windows.py          ön plan penceresi sorgusu ve odak kilidi
    uia.py              erişilebilirlik ağacı -> tıklama noktalı metin
    files.py            dosya okuma/yazma/düzenleme, her yerde UTF-8
    terminal.py         ConPTY + pyte: TUI'yi metin ekran olarak gösterir
  office/
    model.py            gerekçe defteri; her değişiklik neden yapıldığını taşır
    sheet.py            .xlsx okuma/yazma
    text.py             .docx okuma/yazma
    store.py            açık belgeler
  agent/
    loop.py             ajan döngüsü, akış, bağlam budama, değişken effort
    dispatch.py         araç çağrısı -> gerçek eylem, onay kapısı
    tools.py            özel araç tanımları
    prompts.py          sistem promptu
  safety/
    gate.py             risk sınıflandırıcı
    killswitch.py       Esc x3 acil durdurma
  computer/canli.py   masanın canlı karesi
  mcp/
    ayar.py             ~/.ajan/mcp.json — standart biçim, varsayılan kapalı
    istemci.py          asyncio istemcisi: bağlanma, araç listesi, çağrı
    guvenlik.py         tanım zehirlenmesi taraması ve parmak izi
  workflows/
    depo.py             akış deposu, adım ve imza biçimi
    imza.py             tıklanan denetimin kimliği; taşınınca yeniden bulma
    oynatici.py         adımları modele uğramadan çalıştırma
  agent/kuru.py         kuru koşu: beyaz liste ve modele dönen not
  agent/akankod.py      akan araç girdisinden yazılan dosyayı çıkarma
app/
  fluent.py             Fluent token'ları; tema ve vurgu sistemden okunuyor
  window.py             ana pencere, sayfalar, durum şeridi
  ray.py                sol ray ve sayfa başlığı
  commandbar.py         yüzen komut çubuğu: mikrofon, yazı alanı, önizleme
  baloncuk.py           maskotun konuşma baloncuğu; yazı harf harf akıyor
  masa.py               ajanın masası: gizli masaüstünün canlı görüntüsü
  kod_penceresi.py      masanın içindeki Code penceresi
  mcp_view.py           MCP sayfası: sunucular, araçları, uyarıları
  mint.py               masanın ortak paleti ve ölçüleri
  gecmis.py             koşu geçmişi sayfası
  akislar.py            kaydedilmiş akışlar sayfası
  tepsi.py              tepsi simgesi ve menüsü
  baslangic.py          Windows açılışında başlama (HKCU\...\Run)
  kisayol.py            global kısayol (RegisterHotKey, kendi thread'inde)
  etiketler.py          araç adlarının insan diline karşılığı
  sheet_view.py         Excel benzeri tablo: formül çubuğu, sayfa sekmeleri
  panels.py             tablo, yazı, kod, terminal, değişiklik listesi
yanmasa.py              masaüstü uygulaması girişi
scripts/
  check_phase1.py       yakalama ve girdi elle doğrulama
  ajan.py               terminal arayüzü (ajan çekirdeği)
  svg_yap.py            maskotun pozlarını üretir
  svg_onizleme.py       üretilen SVG'lerin PNG önizlemesi + tabaka
  masa_dogrula.py       ajanın masasını gerçek pencerelerle ölçer
  tanitim.py            README'nin tanıtım karesi — ekran değil, widget
varliklar/
  kaynak/bloub.svg      maskotun asıl silueti; pozlar buradan türüyor
  svg/                  üretilen varlıklar — elle düzenlenmez
  onizleme/             PNG önizlemeler; `svg_onizleme.py` yazıyor
tests/test_computer.py  saf mantık: koordinat, tuş, kapı, dosya, effort
```

## Sırlar

`.env` içine giren hiçbir şey repoya girmez. `config.py` `os.environ`'a
dokunan tek modül — bir anahtarın nereden geldiği tek yerden görülebilsin
diye.
