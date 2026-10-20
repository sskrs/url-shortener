const form = document.getElementById("shorten-form");
const result = document.getElementById("result");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  result.textContent = "";
  const response = await fetch("/api/shorten", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: document.getElementById("url").value }),
  });
  const data = await response.json();
  if (!response.ok) {
    result.textContent = data.detail || "Something went wrong";
    return;
  }
  // Build the link with DOM methods, not innerHTML, so user input can't inject HTML.
  const link = document.createElement("a");
  link.href = data.short_url;
  link.textContent = data.short_url;
  result.append("Short link: ", link);
});
