/* AJAX-ifies the calendar prev/next month arrows so paging through months
 * doesn't do a full page navigation -- that was resetting the scroll
 * position to the top of the page every time. Fetches the same
 * /bookmarks?month_offset=N URL the arrow already points to and swaps in
 * just the .calendar-nav markup, leaving the rest of the page (and the
 * scroll position) untouched. Falls back to a real navigation if fetch
 * fails or JS didn't load, since the arrows are real links either way.
 */
(function () {
  function swapCalendar(html, url) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var newNav = doc.querySelector(".calendar-nav");
    var oldNav = document.querySelector(".calendar-nav");
    if (!newNav || !oldNav) return false;
    oldNav.replaceWith(newNav);
    history.replaceState(null, "", url);
    return true;
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest(".calendar-arrow");
    if (!link) return;
    event.preventDefault();
    var url = link.href;
    fetch(url)
      .then(function (response) {
        if (!response.ok) throw new Error("bad status " + response.status);
        return response.text();
      })
      .then(function (html) {
        if (!swapCalendar(html, url)) window.location.href = url;
      })
      .catch(function () {
        window.location.href = url;
      });
  });
})();
