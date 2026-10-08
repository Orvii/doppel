#!/bin/sh
# Doppel başlatıcı — Linux. Doppel.bat'in eşi.
#
# Sanal ortamı elle aktive etmeye gerek yok: betik kendi klasörüne geçip
# sırayla .venv/bin/python3, .venv/bin/python, sonra PATH'teki python3'ü
# arıyor. Depo "nereye kopyalarsan orada çalışır" modelinde olduğu için
# mutlak yol varsayımı yok; yol her seferinde bu dosyanın konumundan
# türetiliyor.
#
# Neden `python3` düşüşü var: paketler sistem python3'üne de kurulmuş
# olabilir. Bulunan yorumlayıcı hiçbir şey değilse hata mesajı ne
# yapılacağını söylüyor — sessizce ölmüyor.
#
# Masaüstü oturumu gerekmiyor; doppel.py kendi X11/headless yolunu
# seçiyor. Otomatik başlatma girişi (~/.config/autostart) bu betiği
# mutlak yoluyla çağırıyor — adı ve konumu değişirse orası da güncellenmeli.

cd "$(dirname "$0")" || exit 1

if [ -x ".venv/bin/python3" ]; then
    python=".venv/bin/python3"
elif [ -x ".venv/bin/python" ]; then
    python=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    python="python3"
else
    echo "HATA: ne .venv içinde Python var ne PATH'te python3." >&2
    echo "Kurulum:  python3 -m venv .venv" >&2
    echo "          .venv/bin/python -m pip install -r requirements.txt -r requirements-linux.txt" >&2
    exit 1
fi

exec "$python" doppel.py "$@"