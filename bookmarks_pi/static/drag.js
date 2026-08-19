/* Drag-and-drop reordering for bookmark categories and the bookmarks within
 * them. Everything else in this app is plain forms + redirects; this is the
 * one feature that genuinely needs JS (there's no CSS-only way to persist a
 * drag gesture). Reordering itself still ends in a normal form submit, so a
 * failed/blocked script just leaves the existing up/down buttons as the
 * fallback way to reorder categories.
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

  function submitReorder(action, hiddenFields, listFieldName, order) {
    var form = document.createElement("form");
    form.method = "post";
    form.action = action;
    form.style.display = "none";

    Object.keys(hiddenFields).forEach(function (name) {
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = hiddenFields[name];
      form.appendChild(input);
    });

    order.forEach(function (value) {
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = listFieldName;
      input.value = value;
      form.appendChild(input);
    });

    document.body.appendChild(form);
    form.submit();
  }

  // Plain forms (edit/delete/move) do a full page reload too; tag them the
  // same way so an open "show more" list doesn't snap shut on save just
  // because the server re-renders <details> without an open attribute.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var group = form.closest(".bookmark-group[data-category]");
    if (!group) return;
    var more = group.querySelector(".bookmark-more");
    if (!more || !more.open || form.querySelector('input[name="open_more"]')) return;
    var input = document.createElement("input");
    input.type = "hidden";
    input.name = "open_more";
    input.value = "1";
    form.appendChild(input);
  });

  document.addEventListener("DOMContentLoaded", function () {
    var categoriesContainer = document.querySelector(".bookmark-groups");
    if (categoriesContainer) {
      setupDragReorder(categoriesContainer, ".bookmark-group", "li[data-id]", "category", function (order) {
        submitReorder("/bookmarks/categories/reorder", {}, "category", order);
      });
    }

    document.querySelectorAll(".bookmark-group[data-category]").forEach(function (group) {
      setupDragReorder(group, "li[data-id]", null, "id", function (order) {
        var more = group.querySelector(".bookmark-more");
        var fields = { category: group.dataset.category };
        if (more && more.open) fields.open_more = "1";
        submitReorder("/bookmarks/reorder", fields, "id", order);
      });
    });
  });
})();
