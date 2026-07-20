const examples = {
  short: {
    spoken: "Hey hey hey, checking how you work.",
    raw: "Hey hey hey, checking how you work.",
    formatted: "Checking how you work."
  },
  request: {
    spoken: "Can you please study a bit more on how the widget works that talks like the concierge widget? Because I believe there is…",
    raw: "Can you please study a bit more on how the widget works that talks like the concierge widget? Because I believe there is…",
    formatted: "Please study how the widget works that talks like the concierge widget, as I believe there is a lot to learn there."
  }
};

const spoken = document.querySelector("#spoken-text");
const raw = document.querySelector("#raw-text");
const formatted = document.querySelector("#formatted-text");

document.querySelectorAll("[data-example]").forEach((button) => {
  button.addEventListener("click", () => {
    const example = examples[button.dataset.example];
    spoken.textContent = example.spoken;
    raw.textContent = example.raw;
    formatted.textContent = example.formatted;
    document.querySelectorAll("[data-example]").forEach((candidate) => {
      const selected = candidate === button;
      candidate.classList.toggle("active", selected);
      candidate.setAttribute("aria-pressed", String(selected));
    });
  });
});
