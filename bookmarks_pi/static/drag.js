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

  // Sticky notes drag freely anywhere on the page (not just reorder within a
  // list), so they can float over any other section -- calendar, bookmarks,
  // documents. Delegated on `document`, since the drop target is the whole
  // page and, unlike the other setups here, nothing about it depends on
  // which specific note elements currently exist -- so it's wired up once
  // and never needs re-binding after an AJAX swap.
  function setupNoteDrag() {
    var dragEl = null;
    var grabX = 0;
    var grabY = 0;

    document.addEventListener("dragstart", function (event) {
      var note = event.target.closest(".sticky-note[data-id]");
      if (!note || note.querySelector(".sticky-note-edit-form.editing")) return;
      dragEl = note;
      var rect = note.getBoundingClientRect();
      grabX = event.clientX - rect.left;
      grabY = event.clientY - rect.top;
      note.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", "");
    });

    document.addEventListener("dragend", function () {
      if (dragEl) dragEl.classList.remove("dragging");
      dragEl = null;
    });

    document.addEventListener("dragover", function (event) {
      if (!dragEl) return;
      event.preventDefault();
    });

    document.addEventListener("drop", function (event) {
      if (!dragEl) return;
      event.preventDefault();
      var page = dragEl.closest(".page");
      if (!page) return;
      // clientX/Y and the page's own viewport-relative rect are both taken
      // at the same scroll position, so their difference is scroll-invariant
      // -- exactly the page-relative offset a position:absolute left/top
      // needs, however far down the page has been scrolled.
      // Negative x/y is fine and intentional -- .page is centered with room
      // to spare on wider screens, and notes should be droppable out in
      // those margins, not just within .page's own box.
      var pageRect = page.getBoundingClientRect();
      var x = Math.round(event.clientX - pageRect.left - grabX);
      var y = Math.round(event.clientY - pageRect.top - grabY);
      dragEl.style.position = "absolute";
      dragEl.style.left = x + "px";
      dragEl.style.top = y + "px";
      submitAjax("/notes/" + dragEl.dataset.id + "/position", { x: x, y: y });
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

  // The sticky-note edit form defaults to the same href="#edit-note-N" +
  // :target CSS trick as the bookmark modal, so it still works without JS.
  // But unlike the modal (position:fixed, so navigating to it is a no-op for
  // scroll), the form sits in normal document flow -- jumping the fragment
  // scrolls it into view even though it's already on screen. With JS we skip
  // the hash entirely and toggle an .editing class instead, which the CSS
  // treats the same as :target but never triggers browser scroll-to-anchor.
  // (history.pushState was tried first to update the fragment without
  // scrolling, but :target doesn't re-evaluate on pushState/replaceState in
  // Chrome -- only on a real navigation -- so it silently stopped matching.)
  document.addEventListener("click", function (event) {
    var editLink = event.target.closest(".sticky-note-edit");
    if (editLink) {
      event.preventDefault();
      var form = document.getElementById(editLink.getAttribute("href").slice(1));
      if (form) form.classList.add("editing");
      return;
    }
    var cancelLink = event.target.closest(".sticky-note-edit-actions a");
    if (cancelLink) {
      event.preventDefault();
      var editForm = cancelLink.closest(".sticky-note-edit-form");
      if (editForm) editForm.classList.remove("editing");
      return;
    }
    // Color and rotation apply immediately (like drag-to-reposition) rather
    // than waiting for Save, since they aren't part of the note's text.
    var swatch = event.target.closest(".sticky-note-color-swatch");
    if (swatch) {
      var colorNote = swatch.closest(".sticky-note[data-id]");
      if (!colorNote) return;
      var color = swatch.dataset.color;
      colorNote.dataset.color = color;
      submitAjax("/notes/" + colorNote.dataset.id + "/color", { color: color });
      return;
    }
    var rotateBtn = event.target.closest(".sticky-note-rotate-btn");
    if (rotateBtn) {
      var rotateNote = rotateBtn.closest(".sticky-note[data-id]");
      if (!rotateNote) return;
      var current = parseFloat(getComputedStyle(rotateNote).getPropertyValue("--note-rotation")) || 0;
      var next = Math.max(-45, Math.min(45, current + Number(rotateBtn.dataset.dir) * 10));
      rotateNote.style.setProperty("--note-rotation", next + "deg");
      submitAjax("/notes/" + rotateNote.dataset.id + "/rotation", { deg: Math.round(next) });
    }
  });

  // The size slider updates live while dragging (so it's clear what's being
  // picked) but only saves -- via the AJAX swap, like color/rotation above --
  // once the user releases it. Saving on every "input" tick would fight the
  // drag with a mid-gesture DOM swap.
  document.addEventListener("input", function (event) {
    var slider = event.target.closest(".sticky-note-size-slider");
    if (!slider) return;
    var sizeNote = slider.closest(".sticky-note[data-id]");
    if (!sizeNote) return;
    sizeNote.style.setProperty("--note-size", slider.value + "px");
  });

  document.addEventListener("change", function (event) {
    var slider = event.target.closest(".sticky-note-size-slider");
    if (!slider) return;
    var sizeNote = slider.closest(".sticky-note[data-id]");
    if (!sizeNote) return;
    submitAjax("/notes/" + sizeNote.dataset.id + "/size", { size: slider.value });
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
    setupNoteDrag();
  });
})();
