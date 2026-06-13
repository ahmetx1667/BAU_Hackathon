function selectedDomain(select) {
  const option = select.options[select.selectedIndex];
  return option ? option.dataset.domain || "" : "";
}

function bindEmailDomainSelect(select) {
  const targetId = select.dataset.domainTarget;
  if (!targetId) {
    return;
  }
  const target = document.getElementById(targetId);
  if (!target) {
    return;
  }
  const update = () => {
    target.textContent = selectedDomain(select);
  };
  select.addEventListener("change", update);
  update();
}

document.querySelectorAll(".js-school-select").forEach(bindEmailDomainSelect);

function bindPostModeControls(form) {
  const mode = form.querySelector("select[name='mode']");
  const location = form.querySelector("select[name='location']");
  const place = form.querySelector("select[name='place_preference']");
  if (!mode || !location || !place) {
    return;
  }

  const firstEnabledValue = (select) => {
    const option = Array.from(select.options).find((item) => !item.disabled);
    return option ? option.value : "";
  };

  const sync = () => {
    const isOnline = mode.value === "Online";
    [location, place].forEach((select) => {
      Array.from(select.options).forEach((option) => {
        option.disabled = isOnline ? option.value !== "Online" : option.value === "Online";
      });
    });

    if (isOnline) {
      location.value = "Online";
      place.value = "Online";
      return;
    }

    if (location.value === "Online") {
      location.value = firstEnabledValue(location);
    }
    if (place.value === "Online") {
      place.value = firstEnabledValue(place);
    }
  };

  mode.addEventListener("change", sync);
  sync();
}

document.querySelectorAll(".js-post-form").forEach(bindPostModeControls);

function markActiveNavigation() {
  const currentPath = window.location.pathname === "/" ? "/" : window.location.pathname.replace(/\/$/, "");
  document.querySelectorAll("nav a[href]").forEach((link) => {
    const href = link.getAttribute("href");
    if (!href || href === "/") {
      return;
    }
    const isActive = currentPath === href || (href !== "/" && currentPath.startsWith(`${href}/`));
    if (isActive) {
      link.setAttribute("aria-current", "page");
    }
  });
}

function bindCharacterCounters() {
  document.querySelectorAll("textarea[maxlength], input[maxlength]").forEach((field) => {
    const max = field.getAttribute("maxlength");
    if (!max || field.dataset.counterBound === "true") {
      return;
    }
    field.dataset.counterBound = "true";
    const counter = document.createElement("span");
    counter.className = "char-counter";
    const update = () => {
      counter.textContent = `${field.value.length}/${max}`;
    };
    field.insertAdjacentElement("afterend", counter);
    field.addEventListener("input", update);
    update();
  });
}

function bindSubmitState() {
  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const button = event.submitter instanceof HTMLButtonElement
        ? event.submitter
        : form.querySelector("button[type='submit']");
      if (!button || button.dataset.keepLabel === "true") {
        return;
      }
      if (button.name) {
        return;
      }
      button.dataset.originalLabel = button.textContent;
      button.textContent = "İşleniyor...";
      button.disabled = true;
    });
  });
}

markActiveNavigation();
bindCharacterCounters();
bindSubmitState();
