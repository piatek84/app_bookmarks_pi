/* Drag-and-drop reordering for bookmark categories/bookmarks and the document
 * list, plus AJAX-ifying every form in .bookmark-groups and .notes-documents-row
 * (bookmarks, documents, sticky notes) so saving doesn't do a full page
 * navigation. A full reload was landing on the right #anchor, but only after
 * the browser painted the top of the page first -- a visible jump. Fetching
 * the updated markup and swapping just those sections plus .toast keeps the
 * scroll position exactly where it was. Every action still degrades to a real
 * form submit (full reload) if fetch fails or JS didn't load, since the
 * server-rendered forms are real.
 */
(function () {
  function isBeforeTarget(rect, x, y) {
    var midX = rect.left + rect.width / 2;
    var midY = rect.top + rect.height / 2;
    // Off the target's row entirely: order by which row it's above.
    if (Math.abs(y - midY) > rect.height / 2) {
      return y < midY;
    }
    // Roughly the same row (relevant for the categories grid): order by column.
    return x < midX;
  }

  // Nudges a scrollable container's own scrollbar (e.g. the document list's
  // fixed-height overflow box) while the pointer hovers near its top/bottom
  // edge during a drag, so items scrolled out of view can be reached as drop
  // targets. No-ops on containers that don't actually scroll.
  function autoScroll(container, y) {
    var rect = container.getBoundingClientRect();
    var edge = 32;
    var maxScroll = container.scrollHeight - container.clientHeight;
    if (maxScroll <= 0) return;
    if (y - rect.top < edge) {
      container.scrollTop = Math.max(0, container.scrollTop - 12);
    } else if (rect.bottom - y < edge) {
      container.scrollTop = Math.min(maxScroll, container.scrollTop + 12);
    }
  }

  function closestItem(container, selector, dragEl, x, y) {
    var items = container.querySelectorAll(selector);
    var closest = null;
    var closestDistance = Infinity;
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      if (item === dragEl) continue;
      var rect = item.getBoundingClientRect();
      var cx = rect.left + rect.width / 2;
      var cy = rect.top + rect.height / 2;
      var distance = Math.hypot(x - cx, y - cy);
      if (distance < closestDistance) {
        closestDistance = distance;
        closest = item;
      }
    }
    return closest;
  }

  // Bookmarks can be dragged both within their category (reordering) and
  // into a different category's list (moving). Unlike setupDragReorder, the
  // valid drop target here isn't fixed to one container up front, so this
  // tracks the item's live parent <ul> as it's dragged across category
  // boundaries and always submits to the list it lands in.
  function setupBookmarkDrag(root) {
    var items = root.querySelectorAll("li[data-id]");
    for (var i = 0; i < items.length; i++) {
      items[i].setAttribute("draggable", "true");
    }

    var dragEl = null;

    root.addEventListener("dragstart", function (event) {
      var item = event.target.closest("li[data-id]");
      if (!item || !root.contains(item)) return;
      dragEl = item;
      item.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", "");
    });

    root.addEventListener("dragend", function () {
      if (dragEl) dragEl.classList.remove("dragging");
      dragEl = null;
    });

    root.addEventListener("dragover", function (event) {
      if (!dragEl) return;
      var list = event.target.closest(".bookmark-list");
      if (!list || !root.contains(list)) return;
      event.preventDefault();
      var target = closestItem(list, "li[data-id]", dragEl, event.clientX, event.clientY);
      if (target) {
        var rect = target.getBoundingClientRect();
        if (isBeforeTarget(rect, event.clientX, event.clientY)) {
          list.insertBefore(dragEl, target);
        } else {
          list.insertBefore(dragEl, target.nextSibling);
        }
      } else if (!list.contains(dragEl)) {
        list.appendChild(dragEl);
      }
    });

    root.addEventListener("drop", function (event) {
      if (!dragEl) return;
      event.preventDefault();
      var list = dragEl.closest(".bookmark-list");
      var group = dragEl.closest(".bookmark-group[data-category]");
      if (!list || !group) return;
      var id = dragEl.dataset.id;
      var order = Array.prototype.map.call(list.querySelectorAll("li[data-id]"), function (item) {
        return item.dataset.id;
      });
      var more = group.querySelector(".bookmark-more");
      var fields = { category: group.dataset.category, id: order };
      if (more && more.open) fields.open_more = "1";
      submitAjax("/bookmarks/" + id + "/move", fields);
    });
  }

  function setupDragReorder(container, selector, ignoreSelector, datasetKey, onDrop) {
    var items = container.querySelectorAll(selector);
    for (var i = 0; i < items.length; i++) {
      items[i].setAttribute("draggable", "true");
    }

    var dragEl = null;

    container.addEventListener("dragstart", function (event) {
      if (ignoreSelector && event.target.closest(ignoreSelector)) return;
      var item = event.target.closest(selector);
      if (!item || !container.contains(item)) return;
      dragEl = item;
      item.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", "");
    });

    container.addEventListener("dragend", function () {
      if (dragEl) dragEl.classList.remove("dragging");
      dragEl = null;
    });

    container.addEventListener("dragover", function (event) {
      if (!dragEl) return;
      event.preventDefault();
      autoScroll(container, event.clientY);
      var target = closestItem(container, selector, dragEl, event.clientX, event.clientY);
      if (!target) return;
      var rect = target.getBoundingClientRect();
      if (isBeforeTarget(rect, event.clientX, event.clientY)) {
        target.parentNode.insertBefore(dragEl, target);
      } else {
        target.parentNode.insertBefore(dragEl, target.nextSibling);
      }
    });

    container.addEventListener("drop", function (event) {
      if (!dragEl) return;
      event.preventDefault();
      var order = Array.prototype.map.call(container.querySelectorAll(selector), function (item) {
        return item.dataset[datasetKey];
      });
      onDrop(order);
    });
  }

  function fallbackSubmit(action, fields) {
    var form = document.createElement("form");
    form.method = "post";
    form.action = action;
    form.style.display = "none";
    Object.keys(fields).forEach(function (name) {
      var value = fields[name];
      (Array.isArray(value) ? value : [value]).forEach(function (v) {
        var input = document.createElement("input");
        input.type = "hidden";
        input.name = name;
        input.value = v;
        form.appendChild(input);
      });
    });
    document.body.appendChild(form);
    form.submit();
  }

  function toFormData(fields) {
    var data = new FormData();
    Object.keys(fields).forEach(function (name) {
      var value = fields[name];
      (Array.isArray(value) ? value : [value]).forEach(function (v) {
        data.append(name, v);
      });
    });
    return data;
  }

  function fieldsFromForm(form) {
    var fields = {};
    new FormData(form).forEach(function (value, name) {
      if (fields[name] === undefined) fields[name] = value;
      else if (Array.isArray(fields[name])) fields[name].push(value);
      else fields[name] = [fields[name], value];
    });
    return fields;
  }

  function rememberOpenCategories() {
    var open = {};
    document.querySelectorAll(".bookmark-group[data-category]").forEach(function (group) {
      var more = group.querySelector(".bookmark-more");
      if (more && more.open) open[group.dataset.category] = true;
    });
    return open;
  }

  function applyOpenCategories(open) {
    document.querySelectorAll(".bookmark-group[data-category]").forEach(function (group) {
      if (!open[group.dataset.category]) return;
      var more = group.querySelector(".bookmark-more");
      if (more) more.open = true;
    });
  }

  // Generic <details id="..."> open-state preservation for a swapped region,
  // keyed by id (unlike rememberOpenCategories, which is bookmark-specific
  // and keyed by category name for its nested "show more" panels).
  function rememberOpenDetails(root) {
    var open = {};
    root.querySelectorAll("details[id]").forEach(function (d) {
      if (d.open) open[d.id] = true;
    });
    return open;
  }

  function applyOpenDetails(root, open) {
    root.querySelectorAll("details[id]").forEach(function (d) {
      if (open[d.id]) d.open = true;
    });
  }

  function swapFromHtml(html) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var openCategories = rememberOpenCategories();

    var newGroups = doc.querySelector(".bookmark-groups");
    var oldGroups = document.querySelector(".bookmark-groups");
    if (newGroups && oldGroups) {
      oldGroups.replaceWith(newGroups);
      applyOpenCategories(openCategories);
    }

    // Sticky notes + documents (upload/delete/reorder, add/edit/delete note)
    // used to be plain form posts that fully reloaded the page -- jarring on
    // a long document list or when editing a note further down. AJAX-ifying
    // them (see the submit listener below) means swapping this region back
    // in too, same as .bookmark-groups above.
    var newRow = doc.querySelector(".notes-documents-row");
    var oldRow = document.querySelector(".notes-documents-row");
    if (newRow && oldRow) {
      var openDetails = rememberOpenDetails(oldRow);
      oldRow.replaceWith(newRow);
      applyOpenDetails(newRow, openDetails);
    }

    var newToast = doc.querySelector(".toast");
    var oldToast = document.querySelector(".toast");
    if (oldToast) oldToast.remove();
    if (newToast) {
      var h1 = document.querySelector(".page > h1");
      if (h1) h1.insertAdjacentElement("afterend", newToast);
    }

    // Clear any #edit-bookmark-N / #category-N / #edit-note-N hash left over
    // from a plain <a href="#..."> so the (freshly replaced) modal doesn't
    // reopen via :target, without triggering a scroll the way setting
    // location.hash does.
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);

    initGroups();
    initDocumentDrag();
  }

  function submitAjax(action, fields) {
    fetch(action, { method: "POST", body: toFormData(fields) })
      .then(function (response) {
        if (!response.ok) throw new Error("bad status " + response.status);
        var url = new URL(response.url, window.location.href);
        if (url.pathname !== "/bookmarks") {
          window.location.href = response.url;
          return null;
        }
        return response.text();
      })
      .then(function (html) {
        if (html) swapFromHtml(html);
      })
      .catch(function () {
        // JS/network hiccup: fall back to a real submit so the action still lands.
        fallbackSubmit(action, fields);
      });
  }

  // The native <summary> only opens/closes the list from the top; this button
  // sits after the last bookmark so collapsing doesn't require scrolling back up.
  document.addEventListener("click", function (event) {
    var btn = event.target.closest(".bookmark-less-btn");
    if (!btn) return;
    var details = btn.closest("details.bookmark-more");
    if (details) details.open = false;
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.closest(".bookmark-groups, .notes-documents-row")) return;
    event.preventDefault();
    var fields = fieldsFromForm(form);
    var group = form.closest(".bookmark-group[data-category]");
    var more = group && group.querySelector(".bookmark-more");
    if (more && more.open) fields.open_more = "1";
    submitAjax(form.action, fields);
  });

  function initGroups() {
    var categoriesContainer = document.querySelector(".bookmark-groups");
    if (categoriesContainer) {
      setupDragReorder(categoriesContainer, ".bookmark-group", "li[data-id]", "category", function (order) {
        submitAjax("/bookmarks/categories/reorder", { category: order });
      });
      setupBookmarkDrag(categoriesContainer);
    }
  }

  // Re-run after every AJAX swap, same as initGroups, since .notes-documents-row
  // (which contains the document list) gets freshly replaced each time.
  function initDocumentDrag() {
    var documentList = document.querySelector("#documents-settings .document-list");
    if (documentList) {
      setupDragReorder(documentList, "li[data-id]", null, "id", function (order) {
        submitAjax("/documents/reorder", { id: order, open_documents: "1" });
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    initGroups();
    initDocumentDrag();
  });
})();
