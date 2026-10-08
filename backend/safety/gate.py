"""Risk sınıflandırıcı — hangi eylem onay ister.

Ajanın kabuk komutu çalıştırma yetkisi olduğu andan itibaren bu modül isteğe
bağlı olmaktan çıkıyor. GUI'de bir dosyayı silmek birkaç tıklama ve geri
dönüşüm kutusuna gider; `Remove-Item -Recurse -Force` bir satır ve gitmez.

Sınıflandırma **desen eşleştirmeyle** yapılıyor, modele sorularak değil.
"Bu tehlikeli mi?" diye modele sormak, aynı modelin komutu üretmiş olması
nedeniyle dairesel; ayrıca bir API çağrısı daha demek.

Kapsam sınırı: bu bir kum havuzu değil, bir hatırlatıcı. Kararlı bir saldırgan
desenlerin etrafından dolaşır. Amaç, iyi niyetli bir ajanın geri alınamaz bir
şeyi fark etmeden yapmasını engellemek.

İki varsayılan bilinçli olarak sıkı: **tanınmayan araç adı** onay istiyor
(açık liste — depoya araç ekleniyor ve sessizce kapısız kalan bir aracı fark
etmenin yolu, bir şeyi bozmasını beklemek olurdu) ve tıklamada yalnızca
pencere başlığına değil, **tıklanan denetimin etiketine** de bakılıyor:
"Gönder" düğmesi sıradan bir pencerenin içinde durabiliyor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Risk(str, Enum):
    SAFE = "safe"
    CONFIRM = "confirm"


@dataclass(frozen=True)
class Verdict:
    risk: Risk
    reason: str = ""

    @property
    def needs_confirmation(self) -> bool:
        return self.risk is Risk.CONFIRM


SAFE = Verdict(Risk.SAFE)


def _rule(pattern: str, reason: str) -> tuple[re.Pattern[str], str]:
    return re.compile(pattern, re.IGNORECASE), reason


#: Kabuk komutu desenleri. Sıra önemli değil, ilk eşleşen kazanır.
SHELL_RULES = [
    _rule(r"\brm\b|\bRemove-Item\b|\bdel\b|\berase\b|\brd\b|\brmdir\b",
          "deletes a file or folder"),
    # `format` tek başına aranamaz: PowerShell'in en sık kullanılan salt-okunur
    # cmdlet'leri `Format-List`, `Format-Table`, `Format-Wide`. İlk sürüm bunu
    # yapıyordu ve bir dosya listeleme komutuna "formats a disk" dedi.
    # Boş yere uyaran bir kapı görmezden gelinir; o yüzden burada geniş değil
    # dar olmak doğru.
    _rule(r"\bformat(?:\.com)?\s+[A-Za-z]:|\bFormat-Volume\b|\bdiskpart\b|\bmkfs\b",
          "formats a disk"),
    _rule(r"\bStop-Computer\b|\bshutdown\b|\bRestart-Computer\b|\blogoff\b",
          "shuts down or restarts the machine"),
    _rule(r"\bStop-Process\b|\btaskkill\b|\bkill\b", "kills a running process"),
    _rule(r"\breg\b\s+(delete|add)|\bSet-ItemProperty\b.*HK(LM|CU)|\bregedit\b",
          "changes the registry"),
    _rule(r"\bSet-ExecutionPolicy\b|\bDisable-\w+|\bUninstall-\b|\bwinget\s+uninstall\b",
          "changes a system setting or uninstalls an app"),
    _rule(r"\bnetsh\b|\bSet-NetFirewall|\bNew-NetFirewall", "changes a network or firewall setting"),
    _rule(r"\bschtasks\b|\bNew-ScheduledTask\b|\bNew-Service\b|\bsc\.exe\b",
          "creates a persistent task or service"),
    _rule(r"\bcurl\b.*\|\s*(iex|bash|sh)|\bInvoke-Expression\b|\biex\b|\bInvoke-WebRequest\b.*\|",
          "pipes something downloaded into a shell"),
    _rule(r"\bgit\b\s+(push|reset\s+--hard|clean\s+-\w*[fd]|checkout\s+--)",
          "an irreversible git operation"),
    # `2>$null` gürültü bastırma, dosyaya yazma değil — onu dışarıda bırak.
    _rule(r"\bSet-Content\b|\bOut-File\b|>>?\s*(?!\$null\b)[A-Za-z0-9_.\\/]",
          "overwrites a file"),
    _rule(r"\bStart-Process\b.*-Verb\s+RunAs|\brunas\b", "runs as administrator"),
]

#: Tıklama koordinatı yerine pencere başlığına bakan kurallar. Başlık her
#: zaman okunuyor; tıklanan denetimin etiketi (LABEL_RULES) okunamadığında
#: kararı tek başına o veriyor.
WINDOW_RULES = [
    _rule(r"\bbank|\bhesab[ıi]m|ödeme|payment|checkout|iyzico|paypal|stripe",
          "a payment or banking window"),
    _rule(r"biçimlendir|format|disk yönetimi|disk management",
          "a disk tool"),
    _rule(r"kayıt defteri|registry editor", "the registry editor"),
]

#: Tıklanan denetimin etiketi. Pencere başlığı yetmiyor: "Gönder" düğmesi
#: sıradan bir pencerenin, hatta bir tarayıcı sekmesinin içinde durabiliyor.
#: Kalıplar dar tutuldu — kaydetme, kapatma, iptal geri alınabilir ve
#: onları da sormak, sıradan tıklamayı sürekli onaya düşürürdü; boş yere
#: uyaran bir kapı görmezden gelinir.
#:
#: Türkçe küçük harf katlaması `re.IGNORECASE` ile düzgün çalışmıyor:
#: 'İ' ve 'ı' harfleri için köşeli parantez sınıfı şart (`[iı]`, `[öo]`).
LABEL_RULES = [
    _rule(r"\bg[öo]nder\b|\bsend\b|\bsubmit\b|\bpayla[sş](?:[iı]m)?\b",
          "clicks a control that sends or shares"),
    _rule(r"\bpay\b|\bbuy\b|\bpurchase\b|sat[iı]n\s*al\b|\böde(?:me)?\b|\bcheckout\b",
          "clicks a control that pays or buys"),
    _rule(r"\bs[iı]l(?:me)?\b|\bdelete\b|\bremove\b|\bkald[iı]r\b",
          "clicks a control that deletes"),
    _rule(r"\bpublish\b|\bpost\b|yay[iı]nla\b",
          "clicks a control that publishes"),
]

#: Tıklama araçları. Hem pencere başlığı hem tıklanan denetimin etiketi
#: süzülüyor. Sağ ve orta tık da burada: ikisi de bir düğmeyi ya da bağlam
#: menüsündeki "Sil"i çalıştırabiliyor. Üçüncü tık da öyle — sol ve çift
#: tık zaten süzülüyordu, kardeşini dışarıda bırakmak tutarsız olurdu.
CLICK_TOOLS = frozenset({
    "left_click", "right_click", "middle_click", "double_click", "triple_click",
})

#: Sorgusuz geçebilen araçlar. **Açık liste**: `classify` sonunda buraya
#: bakıyor ve burada olmayan ad onay istiyor. Kuru koşudaki `SALT_OKUNUR`
#: ile aynı gerekçe — depoya araç eklenip buraya yazılmadığında, yeni aracın
#: sessizce kapısız kalmasını beklemek yerine bir soru soruluyor; kapıyı
#: unutmanın bedeli bir onay, hiç fark etmemenin bedeli geri alınamaz bir
#: eylem olurdu.
#:
#: Kendi içinde onay isteyen araçlar (skill_write, remote_write, write_files
#: gibi) burada: onlar `self.approve`'u doğrudan çağırıyor ve burada
#: CONFIRM demek çift soru olurdu.
SAFE_TOOLS = frozenset({
    # okuma ve durum
    "screenshot", "zoom", "cursor_position", "read_ui_tree", "read_file",
    "list_dir", "list_apps", "skill_list", "office_read", "office_history",
    "terminal_read", "workflow_list", "remote_list", "remote_read",
    "side_windows", "side_capture",
    # fare ve zamanlama — tıklama değil
    "mouse_move", "left_mouse_down", "left_mouse_up", "scroll", "hold_key",
    "wait",
    # kendi içinde onay isteyenler
    "skill_write", "skill_remove", "button_write", "button_remove",
    "remote_write", "remote_run", "write_files",
    # geri alınabilir ya da kullanıcıya görünür olanlar
    "heads_up", "launch_app", "terminal_open", "terminal_close",
    "office_open", "office_edit", "office_close", "switch_display",
    "record_start", "record_stop", "side_close", "side_act",
    "workflow_save", "workflow_run", "workflow_remove", "remote_connect",
})

#: Yazılan metin bunlara benziyorsa dur — ajan kimlik bilgisi girmemeli.
SECRET_HINTS = [
    _rule(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b", "looks like a card number"),
    _rule(r"\b\d{11}\b", "looks like a national ID number"),
    _rule(r"\bsk-[A-Za-z0-9_-]{16,}|\bghp_[A-Za-z0-9]{20,}", "an API key"),
]


def classify_shell(command: str) -> Verdict:
    """Kabuk komutunu sınıflandırır."""
    for pattern, reason in SHELL_RULES:
        if pattern.search(command):
            return Verdict(Risk.CONFIRM, reason)
    return SAFE


def classify_typing(text: str) -> Verdict:
    """Yazılacak metni sınıflandırır."""
    for pattern, reason in SECRET_HINTS:
        if pattern.search(text):
            return Verdict(Risk.CONFIRM, reason)
    return SAFE


def classify_window(title: str) -> Verdict:
    """Ön plandaki pencereyi sınıflandırır — tıklama ve yazma öncesi."""
    for pattern, reason in WINDOW_RULES:
        if pattern.search(title):
            return Verdict(Risk.CONFIRM, reason)
    return SAFE


def classify_label(label: str, okunabilir: bool = True) -> Verdict:
    """Tıklanan denetimin etiketini sınıflandırır.

    Etiket okunamadıysa boş gelir ve burada SAFE dönüyor: UIA'nın kapalı
    olduğu yer (oyun, tuval, yükseltilmiş pencere) sıradan kullanımda da
    yaygın ve oradaki her tıklamayı onaya düşürmek, kapıyı yorgunlukla
    işlevsiz kılardı. Pencere başlığı süzgeci o yerde yine çalışıyor.

    `okunabilir=False` AYRI bir hâl: erişilebilirlik katmanı soruya hiç
    cevap veremedi ("hangi nokta" sorusu sorulamadı). Bu, boş etiketle
    aynı sayılamaz — sessiz SAFE tam olarak burada doğar; okunamayan bir
    hedefte tıklama koordinatına değil denetimin ne olduğuna bakılabildiği
    hâlde bakılamadığında, kapı soruyor.
    """
    if not okunabilir:
        return Verdict(
            Risk.CONFIRM,
            "cannot read the accessibility label of the clicked control",
        )
    for pattern, reason in LABEL_RULES:
        if pattern.search(label):
            return Verdict(Risk.CONFIRM, reason)
    return SAFE


def classify_write(path: str) -> Verdict:
    """Dosya yazmayı sınıflandırır.

    Yeni bir dosya oluşturmak geri alınabilir — silersin, biter. Var olan bir
    dosyanın üzerine yazmak değil: eski içerik gitmiştir. Kapı bu ayrımı
    yapıyor, yoksa ajanın her `write_file` çağrısı onay isterdi ve onay
    yorgunluğu kapıyı işlevsiz kılardı.
    """
    from ..computer.files import FileError, inspect_write

    try:
        info = inspect_write(path)
    except FileError:
        return SAFE  # yol zaten geçersiz; araç anlamlı bir hata verecek

    if info.sensitive:
        return Verdict(Risk.CONFIRM, "writes to a system or credential file")
    if info.existed:
        return Verdict(Risk.CONFIRM, f"overwrites the existing file {info.path.name}")
    return SAFE


def classify(name: str, payload: dict, window_title: str = "",
             label: str = "", label_okunabilir: bool = True) -> Verdict:
    """Bir araç çağrısının tamamını sınıflandırır.

    `label` tıklanacak denetimin erişilebilirlik etiketi; okuyan taraf
    `Dispatcher._hedef_etiketi`. Etiket boş gelirse karar pencere
    başlığına kalır.

    `label_okunabilir=False` ise erişilebilirlik katmanı soruya hiç cevap
    veremedi — bu boş etiketle aynı şey değil: okunamayan bir hedefe
    tıklama onay istiyor (bkz. `classify_label`), çünkü "okuyamadım"ı
    "riskli değil" saymak sessiz SAFE üretirdi.
    """
    if name == "run_shell":
        return classify_shell(str(payload.get("command", "")))

    if name == "write_file":
        if payload.get("append"):
            return SAFE  # ekleme veri kaybetmiyor
        return classify_write(str(payload.get("path", "")))

    if name == "edit_file":
        # Düzenleme cerrahi ve eşsiz eşleşme şartı var; hassas dosyada yine sor.
        from ..computer.files import FileError, inspect_write

        try:
            if inspect_write(str(payload.get("path", ""))).sensitive:
                return Verdict(Risk.CONFIRM, "edits a sensitive file")
        except FileError:
            pass
        return SAFE

    if name == "terminal_send":
        # Terminale yazılan da bir komut; kabukla aynı kurallara tabi.
        text = payload.get("text")
        if text:
            return classify_shell(str(text))
        return SAFE

    if name == "type":
        verdict = classify_typing(str(payload.get("text", "")))
        if verdict.needs_confirmation:
            return verdict

    if name in CLICK_TOOLS:
        # Pencere başlığı önce: bir banka penceresinde etiket okunamamış
        # olsa bile başlık gerçeği söylüyor ve başlık her zaman okunuyor.
        verdict = classify_window(window_title)
        if verdict.needs_confirmation:
            return verdict
        return classify_label(label, okunabilir=label_okunabilir)

    if name in {"type", "key", "left_click_drag"}:
        return classify_window(window_title)

    if name == "office_save":
        # Yol verilmeden kaydetme belgenin kendi dosyasına gidiyor — açılışta
        # zaten okunan dosya; normal kaydetme, kapının işi değil. `path`
        # başka bir dosyayı işaret ediyorsa üzerine yazma riski
        # `write_file`la aynı: var olan dosya sorulur.
        hedef = payload.get("path")
        if not hedef:
            return SAFE
        return classify_write(str(hedef))

    if name == "side_launch":
        # Yan alanda açılan uygulamayı Berkay göremiyor — masaüstü görünmez.
        # Görünür bir eylemi kaçırırsa fark eder, görünmez olanı fark etmez;
        # o yüzden burada onay, ne açıldığının tek göstergesi.
        return Verdict(Risk.CONFIRM, "opens an app on the invisible workspace")

    if name == "side_act" and payload.get("action") == "type":
        # Yan alanda tıklama sormuyoruz, yoksa paralel çalışma diye bir şey
        # kalmaz. Yazılan metin başka: kimlik bilgisi kalıpları burada da
        # aynı kapıdan geçiyor.
        return classify_typing(str(payload.get("text", "")))

    if name in SAFE_TOOLS:
        return SAFE

    # Açık liste, kuru koşudaki `SALT_OKUNUR` ile aynı gerekçe: depoya araç
    # eklenip buraya yazılmadığında aracın sessizce kapısız kalmasını
    # beklemek yerine, tanınmayan ad onay istiyor. Listeye her bilinçli
    # ekleme bir karar; unutmanın bedeli bir soru oluyor.
    return Verdict(Risk.CONFIRM, f"runs {name!r}, which the gate does not know")


#: Uzak makinede sorgusuz çalışabilecek komutlar.
#:
#: Yerel kapı bir **yasak listesi**: tehlikeli kalıpları arıyor, gerisine
#: izin veriyor. Uzak makinede bu ters çevrildi ve bunun somut bir sebebi
#: var: yerelde yanlış giden bir komut Berkay'ın kendi dosyası, sunucuda
#: aynı komut çalışan bir servisi düşürüyor ve geri dönüşü yok. Bir yazma
#: işlemini onaylamak ucuz; yanlış bir yazmayı geri almak mümkün değil.
#:
#: Bu yüzden burada **izin listesi**: yalnızca okuyan komutlar sorgusuz
#: geçiyor, tanımadığımız her şey soruluyor.
READ_ONLY_REMOTE = frozenset({
    "ls", "dir", "cat", "head", "tail", "wc", "stat", "file", "find", "locate",
    "grep", "egrep", "fgrep", "rg", "sort", "uniq", "cut", "tr", "column",
    "df", "du", "free", "uptime", "uname", "hostname", "whoami", "id", "groups",
    "date", "pwd", "echo", "printf", "env", "printenv", "which", "type",
    "ps", "pgrep", "lsof", "ss", "netstat", "ip", "ifconfig", "lsblk", "blkid",
    "md5sum", "sha256sum", "sha1sum", "base64", "readlink", "realpath",
    "dpkg", "apt-cache", "pip", "python3", "node", "nproc", "lscpu", "vmstat",
    "true", "false", "test", "sleep", "tee",
})

#: Alt komutu okumaya çeviren durumlar. `systemctl status` zararsız,
#: `systemctl stop` bir servisi düşürüyor.
READ_ONLY_SUB = {
    "systemctl": {"status", "is-active", "is-enabled", "list-units",
                  "list-unit-files", "show", "cat"},
    "journalctl": None,          # None: tüm alt komutlar okuma sayılıyor
    "git": {"status", "log", "diff", "show", "branch", "remote", "config"},
    "docker": {"ps", "logs", "images", "inspect", "stats", "version"},
    "systemd-analyze": None,
}

#: Komutu okuma olmaktan çıkaran işaretler. `>` dosyaya yazıyor, `sed -i`
#: yerinde değiştiriyor, `sudo` yetki yükseltiyor.
_REMOTE_UNSAFE = re.compile(
    r">|\bsudo\b|\bsu\b|\bdd\b|\bmkfs|\bchmod\b|\bchown\b|\bmv\b|\bcp\b|"
    r"\bln\b|\btruncate\b|\bcrontab\b|\bpasswd\b|\buseradd\b|\buserdel\b|"
    r"\bapt\b|\bapt-get\b|\byum\b|\bdnf\b|\bpip\s+install|\bnpm\s+i"
)


def _subcommand(words: list[str]) -> str:
    """Bayrakları atlayıp asıl alt komutu bulur.

    Önce ikinci kelime alınıyordu ve `git -C /srv/app log` salt-okunur bir
    listelemeyken onay istiyordu. Boş yere uyaran bir kapı görmezden
    gelinir; bu dosyada aynı hata `format` kuralında bir kez yapıldı.
    """
    atla = False
    for word in words:
        if atla:
            atla = False
            continue
        if word.startswith("-"):
            # `-C DIZIN` gibi değer alan bayraklar: değeri de atla.
            atla = word in {"-C", "-c", "-f", "-H", "-u", "--git-dir"}
            continue
        return word
    return ""


def classify_remote(command: str) -> Verdict:
    """Uzak komut. Tanımadığımız her şey onay istiyor."""
    text = command.strip()
    if not text:
        return SAFE
    if _REMOTE_UNSAFE.search(text):
        return Verdict(Risk.CONFIRM, "changes something on the remote machine")

    # Boru ve zincirin her parçası ayrı ayrı bakılıyor: `cat x | sh` içindeki
    # `cat` zararsız, `sh` değil.
    for segment in re.split(r"\|\||&&|\||;", text):
        words = segment.split()
        if not words:
            continue
        head = words[0].rsplit("/", 1)[-1]
        if head in READ_ONLY_SUB:
            allowed = READ_ONLY_SUB[head]
            sub = _subcommand(words[1:])
            if allowed is not None and sub not in allowed:
                return Verdict(
                    Risk.CONFIRM, f"runs {head} {sub} on the remote machine"
                )
            continue
        if head not in READ_ONLY_REMOTE:
            return Verdict(Risk.CONFIRM, f"runs {head} on the remote machine")
    return SAFE
