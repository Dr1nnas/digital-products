(function () {
  var m = document.getElementById('main-img'); if (!m) return;
  document.querySelectorAll('.thumb').forEach(function (b) {
    b.addEventListener('click', function () {
      m.src = b.getAttribute('data-full'); m.width = b.getAttribute('data-w'); m.height = b.getAttribute('data-h');
      document.querySelectorAll('.thumb').forEach(function (t) { t.classList.remove('active'); }); b.classList.add('active');
    });
  });
})();
