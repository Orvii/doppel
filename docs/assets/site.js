// Doppel sitesi — küçük davranışlar.
//
// İki iş yapıyor, ikisi de "bir kez": bölüm girişleri ve kanıt sayacı.
// Döngü yok, sürekli animasyon yok, kütüphane yok — sayfa kendi başına
// açılabilsin diye (file:// dahil) tek dosya, bağımsız.

(function () {
  "use strict";

  var azHareket = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // 1) Bölüm girişleri: her öğe bir kez görünür olur, bir daha oynamaz.
  var girisekler = document.querySelectorAll(
    ".reveal, .hero-shot, .proof-row, .loop-steps, .closing-in"
  );

  if (azHareket || !("IntersectionObserver" in window)) {
    girisekler.forEach(function (el) { el.classList.add("gorundu"); });
  } else {
    var gozlemci = new IntersectionObserver(
      function (girisler) {
        girisler.forEach(function (giris) {
          if (giris.isIntersecting) {
            giris.target.classList.add("gorundu");
            gozlemci.unobserve(giris.target); // bir kez — tekrar oynamaz
          }
        });
      },
      { threshold: 0.18, rootMargin: "0px 0px -8% 0px" }
    );
    girisekler.forEach(function (el) { gozlemci.observe(el); });
  }

  // 2) Kanıt sayıları: görünür olunca bir kez sayar, sonra durur.
  //    Sayılar HTML'de gerçek değeriyle duruyor; sayaç yalnızca görsel.
  var sayilar = document.querySelectorAll(".num[data-count-to]");
  if (sayilar.length && !azHareket && "IntersectionObserver" in window) {
    var sayGozlemci = new IntersectionObserver(
      function (girisler) {
        girisler.forEach(function (giris) {
          if (!giris.isIntersecting) return;
          var el = giris.target;
          sayGozlemci.unobserve(el);
          var hedef = parseInt(el.getAttribute("data-count-to"), 10);
          if (!isFinite(hedef) || hedef === 0) { el.textContent = "0"; return; }
          var baslangic = performance.now();
          var sure = 900;
          function kare(an) {
            var t = Math.min(1, (an - baslangic) / sure);
            var yumusak = 1 - Math.pow(1 - t, 3); // ease-out cubic
            el.textContent = String(Math.round(hedef * yumusak));
            if (t < 1) requestAnimationFrame(kare);
            else el.textContent = String(hedef); // son değer tam, yuvarlanmış değil
          }
          requestAnimationFrame(kare);
        });
      },
      { threshold: 0.6 }
    );
    sayilar.forEach(function (el) { sayGozlemci.observe(el); });
  }
})();