#!/bin/sh
# Sır kalıpları — tek kaynak. pre-commit kancası da CI de buradan okur.
#
# Neden tek dosya: iki ayrı liste tutulsa biri güncellenip diğeri unutulur
# ve "kancada yakalanan ama CI'da kaçan" bir sır sessizce commit'lenir.
# Kalıbı değiştireceksen yalnızca burayı değiştir.
#
# Kullanım — kaynak olarak alınır (POSIX sh, dash uyumlu):
#
#   kok=$(git rev-parse --show-toplevel)
#   . "$kok/scripts/secret-patterns.sh"
#
# Verir:
#   DESENLER      içerikte aranan anahtar kalıpları   (grep -E)
#   SIR_DOSYA     izlenmemesi gereken dosya adları    (grep -E)
#   SIR_ISTISNA   dosya adı listesinin istisnası      (grep -vE)
#   sir_tara_repo tüm İZLENEN dosyaları tarar (CI bunu çağırır)
#
# Kalıplar ERE: `grep -E` ve `git grep -E` aynı sonucu vermeli.

# Anthropic, OpenAI, ElevenLabs, AWS, GitHub ve genel özel anahtar başlığı.
DESENLER='sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{20}|sk-[A-Za-z0-9]{40,}|sk_[a-f0-9]{40,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'

# Sır dosyası adları: .env ve türevleri, .key, .pem.
SIR_DOSYA='^\.env$|^\.env\..*|\.key$|\.pem$'

# Doldurulmuş `.env` yasak, örneği serbest.
SIR_ISTISNA='^\.env\.example$'

# İzlenen bütün dosyaları tarar — CI işleri bunu çağırıyor.
# Kanca bunu kullanmaz: o yalnızca sahnelenen farkı tarar (pre-commit
# semantiği). Kalıplar ortak, kapsam bilinçli olarak farklı.
sir_tara_repo() {
    kirli=0

    bulunan=$(git grep -nEI "$DESENLER" -- . || true)
    if [ -n "$bulunan" ]; then
        echo "RED: izlenen bir dosyada anahtara benzeyen dize var:"
        echo "$bulunan" | sed -E 's/(.{0,24}).*/\1…/' | head -5
        kirli=1
    fi

    yasak=$(git ls-files | grep -E "$SIR_DOSYA" | grep -vE "$SIR_ISTISNA" || true)
    if [ -n "$yasak" ]; then
        echo "RED: sır dosyası izleniyor: $yasak"
        kirli=1
    fi

    return "$kirli"
}